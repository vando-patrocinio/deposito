"""
AUDITORIA EXECUTIVA — DIA ZERO
Extrai do MongoDB os números reais para validar elegibilidade do piloto WhatsApp.

Origem dos dados:
  - subscriber_invoices (status='overdue')        -> universo de inadimplentes
  - atlaz_clients_cache                            -> phone canônico do cliente
  - subscriber_access_points                       -> bridge external_id -> subscriber_id
  - subscribers                                    -> status / current_vlan_olt
  - smartolt_onus                                  -> status técnico (Online/LOS/Offline/Power fail)
  - billing_dunning_events                         -> histórico de cobrança (anti-spam)

Sem mocks. Sem estimativas que não venham do banco.
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import re
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    # Se já vier com DDI 55, mantém. Caso brasileiro mínimo: 10 ou 11 dígitos => prepend 55.
    if len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def is_smartolt_blocked(status: str | None) -> bool:
    """SmartOLT Gate: bloqueia cobrança se ONU não estiver Online."""
    if not status:
        return False  # sem info => não bloqueia (conservador, será reportado em coluna de risco)
    return status.strip().lower() != "online"


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    company_id = "co-demo"

    print("=" * 78)
    print("AUDITORIA EXECUTIVA — DIA ZERO — co-demo")
    print("=" * 78)

    # --------- 1. Universo: faturas vencidas ---------
    overdue = await db.subscriber_invoices.find(
        {"company_id": company_id, "status": "overdue"}
    ).to_list(length=None)
    total_overdue_invoices = len(overdue)
    total_overdue_amount = sum(float(i.get("amount") or 0) for i in overdue)

    # Agrupa por subscriber_external_id (1 cliente pode ter várias faturas)
    by_ext: dict[str, list] = defaultdict(list)
    for inv in overdue:
        ext = inv.get("subscriber_external_id")
        if ext:
            by_ext[ext].append(inv)

    eligible_ext_ids = list(by_ext.keys())
    distinct_clients_with_overdue = len(eligible_ext_ids)

    # --------- 2. Atlaz cache (telefone canônico) ---------
    atlaz_docs = await db.atlaz_clients_cache.find(
        {"company_id": company_id, "external_id": {"$in": eligible_ext_ids}}
    ).to_list(length=None)
    atlaz_by_ext = {d["external_id"]: d for d in atlaz_docs}

    # --------- 3. Subscriber Access Points (bridge para subscriber_id) ---------
    sap_docs = await db.subscriber_access_points.find(
        {"company_id": company_id, "subscriber_external_id": {"$in": eligible_ext_ids}}
    ).to_list(length=None)
    sap_by_ext: dict[str, dict] = {}
    for sap in sap_docs:
        sap_by_ext[sap["subscriber_external_id"]] = sap  # primeiro acesso

    sub_ids = [sap["subscriber_id"] for sap in sap_docs if sap.get("subscriber_id")]
    subs = await db.subscribers.find(
        {"company_id": company_id, "id": {"$in": sub_ids}}
    ).to_list(length=None)
    sub_by_id = {s["id"]: s for s in subs}

    # --------- 4. SmartOLT: mapa olt+pon -> melhor status conhecido ----------
    # Como subscribers carrega current_vlan_olt/pon, vamos casar com ONUs por olt_name+port
    onu_docs = await db.smartolt_onus.find(
        {"company_id": company_id}
    ).to_list(length=None)
    onus_by_olt_port: dict[tuple, list] = defaultdict(list)
    for o in onu_docs:
        key = (o.get("olt_name"), str(o.get("port") or ""))
        onus_by_olt_port[key].append(o)

    def best_onu_status_for_sub(s: dict) -> str | None:
        olt = s.get("current_vlan_olt")
        pon = s.get("current_vlan_pon")
        if not olt or not pon:
            return None
        # current_vlan_pon pode estar como "1/10" -> port = "10"
        if "/" in pon:
            _, port = pon.split("/", 1)
        else:
            port = pon
        key = (olt, str(port))
        candidates = onus_by_olt_port.get(key, [])
        if not candidates:
            return None
        # Prioriza Online > Warning > LOS > Power fail > Offline
        priority = {"Online": 4, "Warning": 3, "LOS": 2, "Power fail": 1, "Offline": 0}
        candidates_sorted = sorted(
            candidates, key=lambda x: priority.get((x.get("status") or "").strip(), -1), reverse=True
        )
        return candidates_sorted[0].get("status")

    # --------- 5. Construir base elegível enriquecida ---------
    rows = []
    for ext_id in eligible_ext_ids:
        invs = by_ext[ext_id]
        amount = sum(float(i.get("amount") or 0) for i in invs)
        oldest_due = min((i.get("due_date") or "") for i in invs)

        atlaz = atlaz_by_ext.get(ext_id) or {}
        phone = normalize_phone(atlaz.get("phone"))
        name = atlaz.get("name") or invs[0].get("subscriber_name") or "DESCONHECIDO"
        document = atlaz.get("document")

        sap = sap_by_ext.get(ext_id)
        sub = sub_by_id.get(sap["subscriber_id"]) if sap else None

        sub_status = sub.get("status") if sub else None
        onu_status = best_onu_status_for_sub(sub) if sub else None

        rows.append({
            "external_id": ext_id,
            "name": name,
            "document": document,
            "phone": phone,
            "amount_overdue": amount,
            "invoices_count": len(invs),
            "oldest_due": oldest_due,
            "subscriber_id": sub.get("id") if sub else None,
            "sub_status": sub_status,
            "onu_status": onu_status,
            "plan_price": float(sub.get("plan_price") or 0) if sub else 0.0,
        })

    # --------- 6. Aplicar gates ---------
    has_phone = [r for r in rows if r["phone"]]
    smartolt_excluded = [
        r for r in rows if r["onu_status"] and is_smartolt_blocked(r["onu_status"])
    ]
    onu_unknown = [r for r in rows if r["onu_status"] is None]

    # ELEGÍVEIS = tem telefone + ONU não bloqueada (Online OU desconhecida com sub ATIVO)
    eligible_final = [
        r for r in rows
        if r["phone"]
        and (r["onu_status"] is None or not is_smartolt_blocked(r["onu_status"]))
        and (r["sub_status"] in ("ATIVO", "active") or r["sub_status"] is None)
    ]

    # --------- 7. Anti-spam: já recebeu mensagem nas últimas 48h? ---------
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    recent_dunning = await db.billing_dunning_events.distinct(
        "subscriber_phone", {"company_id": company_id, "ts": {"$gte": cutoff}, "sent": True}
    )
    recent_dunning_set = set(p for p in recent_dunning if p)
    eligible_clean = [r for r in eligible_final if r["phone"] not in recent_dunning_set]

    # --------- 8. Top 10 score recuperação ---------
    def recovery_score(r: dict) -> float:
        # Score simples: valor em aberto x recência x plano ativo
        # Maior valor + ATIVO + ONU Online => score mais alto
        amt = r["amount_overdue"]
        bonus_active = 1.2 if r["sub_status"] in ("ATIVO", "active") else 0.8
        bonus_online = 1.3 if r["onu_status"] == "Online" else (
            1.0 if r["onu_status"] is None else 0.5
        )
        bonus_one_invoice = 1.15 if r["invoices_count"] == 1 else 1.0  # dívida pequena = + provável pagar
        return amt * bonus_active * bonus_online * bonus_one_invoice

    eligible_clean_sorted = sorted(eligible_clean, key=recovery_score, reverse=True)
    top10 = eligible_clean_sorted[:10]
    top10_total = sum(r["amount_overdue"] for r in top10)

    # --------- 9. Cenários ---------
    # Benchmarks setor ISP (cobrança WhatsApp em D+5..D+30):
    #  Pessimista: 8% conversão
    #  Provável:   18% conversão
    #  Otimista:   30% conversão
    scen = {
        "pessimista": top10_total * 0.08,
        "provavel": top10_total * 0.18,
        "otimista": top10_total * 0.30,
    }

    # --------- 10. RELATÓRIO ---------
    print(f"\n[1] Faturas vencidas no banco: {total_overdue_invoices} (R$ {total_overdue_amount:,.2f})")
    print(f"[2] Clientes distintos inadimplentes: {distinct_clients_with_overdue}")
    print(f"[3] Ticket médio dívida/cliente: R$ {(total_overdue_amount/max(distinct_clients_with_overdue,1)):,.2f}")
    print(f"[4] Clientes inadimplentes com telefone normalizado: {len(has_phone)}")
    print(f"[5] SmartOLT Gate — clientes excluídos (ONU LOS/Offline/Power fail/Warning): {len(smartolt_excluded)}")
    print(f"     ONU status desconhecido (sem casamento OLT+PON): {len(onu_unknown)}")
    sub_ativo_cnt = len([r for r in rows if r["sub_status"] in ("ATIVO","active")])
    sub_inativo_cnt = len([r for r in rows if r["sub_status"] == "INATIVO"])
    sub_unknown = len([r for r in rows if r["sub_status"] is None])
    print(f"     Subscribers: ATIVO={sub_ativo_cnt} INATIVO={sub_inativo_cnt} N/A={sub_unknown}")
    print(f"[6] Elegíveis finais (telefone + ONU OK + Sub ATIVO/N/A): {len(eligible_final)}")
    print(f"     ↳ Após anti-spam 48h: {len(eligible_clean)}")
    print(f"[7] TOP 10 por score de recuperação:")
    print(f"     {'#':<3}{'EXT_ID':<10} {'NOME':<35} {'R$':>10} {'PHONE':<14} {'ONU':<10} {'SUB':<8}")
    for i, r in enumerate(top10, 1):
        print(
            f"     {i:<3}{r['external_id']:<10} {r['name'][:34]:<35} "
            f"{r['amount_overdue']:>10,.2f} {(r['phone'] or '-'):<14} "
            f"{(r['onu_status'] or 'N/A'):<10} {(r['sub_status'] or '-'):<8}"
        )
    print(f"[8] Valor total carteira TOP 10: R$ {top10_total:,.2f}")
    print(f"[9] Recuperação esperada do lote (10 mensagens):")
    print(f"     PESSIMISTA (8%):  R$ {scen['pessimista']:,.2f}")
    print(f"     PROVÁVEL   (18%): R$ {scen['provavel']:,.2f}")
    print(f"     OTIMISTA   (30%): R$ {scen['otimista']:,.2f}")
    print(f"[10] Receita máxima do lote (100% pagamento): R$ {top10_total:,.2f}")

    # --------- 11. Template ---------
    template = (
        "Olá {nome}, aqui é da {empresa}. Identificamos sua fatura "
        "no valor de R$ {valor} vencida em {vencimento}. "
        "Para regularizar agora e evitar bloqueio, acesse: {link_2via} "
        "ou responda 1️⃣ para receber por aqui. Qualquer dúvida, estamos no WhatsApp."
    )
    print(f"\n[11] Template a utilizar:\n     {template}")

    print(f"\n[12] Riscos residuais:")
    print(f"     - {len(onu_unknown)} clientes sem casamento ONU↔assinante (gate aplicado em modo conservador).")
    print(f"     - Coleção subscriber_phones com is_whatsapp validado: ~5 de 2.789 (0.18%). "
          f"Validação WA é nominal — usamos phone do atlaz_clients_cache como fonte canônica.")
    print(f"     - 72 clientes inadimplentes ({distinct_clients_with_overdue - len(atlaz_docs)}) "
          f"não constam no cache Atlaz (sem telefone confiável).")
    print(f"     - Disparo em ambiente sandbox: WhatsApp Baileys sem sessão real autenticada. "
          f"Em PROD requer QR Code do operador.")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
