"""
GATE SmartOLT — DIAGNÓSTICO E APLICAÇÃO

Investigação completa da capacidade de bloquear cobranças automaticamente
quando o cliente está com falha técnica (ONU offline/LOS/power fail).

Realidade dos dados (co-demo):
  - subscribers vinculados a ONU diretamente (smartolt_onu_linked_at != None): ~4 de 2.794
  - Subscribers com current_vlan_olt + current_vlan_pon (sincronizado via VLAN):
       75 de 229 inadimplentes (33%)
  - GPON: cada porta PON agrega N ONUs. Match por (olt, board, port) retorna
    múltiplos candidatos. Sem SN/MAC do cliente não é determinístico.

Estratégia adotada (multi-tier):
  Tier A — ALTA CONFIANÇA (bloquear): cliente vive numa porta PON cuja TOTALIDADE
            das ONUs está Offline/LOS/Power fail. Toda a árvore está morta.
  Tier B — DEGRADAÇÃO (alertar mas não bloquear): porta com >50% ONUs com falha.
  Tier C — SAUDÁVEL (liberar): porta com TODAS as ONUs Online.
  Tier D — INDETERMINADO: subscriber sem current_vlan_olt/pon → liberar com flag.

Saída: gravar em motor_ia_predictions (kind='smartolt_gate') o resultado por sub,
e printar relatório executivo.
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

BAD_STATES = {"offline", "los", "power fail"}
DEGRADED_STATES = {"warning"}


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    company_id = "co-demo"

    # 1) Universo inadimplente
    overdue_ext_ids = await db.subscriber_invoices.distinct(
        "subscriber_external_id", {"company_id": company_id, "status": "overdue"}
    )
    saps = await db.subscriber_access_points.find(
        {"company_id": company_id, "subscriber_external_id": {"$in": overdue_ext_ids}}
    ).to_list(None)
    sub_ids = [s["subscriber_id"] for s in saps if s.get("subscriber_id")]
    subs = await db.subscribers.find(
        {"company_id": company_id, "id": {"$in": sub_ids}}
    ).to_list(None)
    sub_by_id = {s["id"]: s for s in subs}

    # 2) Indexar ONUs por (olt, board, port)
    onus = await db.smartolt_onus.find({"company_id": company_id}).to_list(None)
    onus_by_port: dict[tuple, list] = defaultdict(list)
    for o in onus:
        key = (o.get("olt_name"), str(o.get("board")), str(o.get("port")))
        onus_by_port[key].append(o)

    # 3) Análise de saúde por porta
    port_health: dict[tuple, dict] = {}
    for key, lst in onus_by_port.items():
        total = len(lst)
        bad = sum(1 for o in lst if (o.get("status") or "").strip().lower() in BAD_STATES)
        degraded = sum(1 for o in lst if (o.get("status") or "").strip().lower() in DEGRADED_STATES)
        online = sum(1 for o in lst if (o.get("status") or "").strip().lower() == "online")
        port_health[key] = {
            "total": total,
            "bad": bad,
            "degraded": degraded,
            "online": online,
            "bad_pct": bad / total if total else 0,
        }

    # 4) Classificar inadimplentes
    # Prioriza smartolt_onu_status (enriquecido) — confidence direta na ONU específica.
    # Fallback para health de porta (multi-ONU).
    counters = defaultdict(int)
    detail = []
    for ext_id in overdue_ext_ids:
        sap = next((s for s in saps if s["subscriber_external_id"] == ext_id), None)
        sub = sub_by_id.get(sap["subscriber_id"]) if sap else None

        if not sub:
            counters["sem_subscriber"] += 1
            continue

        # Tier 1: ONU direta (pós-enriquecimento)
        onu_status = sub.get("smartolt_onu_status")
        if onu_status:
            st = (onu_status or "").strip().lower()
            if st in BAD_STATES:
                tier = "A_bloquear"
            elif st in DEGRADED_STATES:
                tier = "B_degradada"
            elif st == "online":
                tier = "C_saudavel"
            else:
                tier = "C_saudavel"
            counters[f"tier_{tier}"] += 1
            counters["resolved_via_direct_onu"] += 1
            detail.append({
                "external_id": ext_id,
                "subscriber_id": sub["id"],
                "name": sub.get("name"),
                "olt": sub.get("smartolt_onu_olt"),
                "pon": None,
                "via": "direct_onu",
                "onu_status": onu_status,
                "onu_sn": sub.get("smartolt_onu_sn"),
                "confidence": sub.get("smartolt_onu_confidence"),
                "tier": tier,
            })
            continue

        # Tier 2: fallback via porta PON
        olt = sub.get("current_vlan_olt")
        pon = sub.get("current_vlan_pon")
        if not olt or not pon:
            counters["tier_D_indeterminado"] += 1
            continue
        if "/" in pon:
            board, port = pon.split("/", 1)
        else:
            board, port = "1", pon
        key = (olt, board, str(port))
        hp = port_health.get(key)
        if not hp:
            counters["sem_porta_no_smartolt"] += 1
            continue

        if hp["total"] >= 1 and hp["bad"] == hp["total"]:
            tier = "A_bloquear"
        elif hp["bad_pct"] >= 0.5:
            tier = "B_degradada"
        elif hp["online"] == hp["total"]:
            tier = "C_saudavel"
        else:
            tier = "C_saudavel"  # maioria saudável → libera
        counters[f"tier_{tier}"] += 1
        counters["resolved_via_port_health"] += 1
        detail.append({
            "external_id": ext_id,
            "subscriber_id": sub["id"],
            "name": sub.get("name"),
            "olt": olt,
            "pon": pon,
            "via": "port_health",
            "port_total": hp["total"],
            "port_bad": hp["bad"],
            "port_online": hp["online"],
            "tier": tier,
        })

    # 5) Relatório
    print("=" * 78)
    print("GATE SmartOLT — DIAGNÓSTICO E DECISÃO")
    print("=" * 78)
    print(f"\nUniverso inadimplente:               {len(overdue_ext_ids)}")
    print(f"  → sem subscriber resolvido:        {counters['sem_subscriber']}")
    print(f"  → Tier D (indeterminado, sem VLAN):{counters['tier_D_indeterminado']}")
    print(f"  → sem porta correspondente:        {counters['sem_porta_no_smartolt']}")
    print(f"  → Tier A (BLOQUEAR — porta morta): {counters['tier_A_bloquear']}")
    print(f"  → Tier B (DEGRADADA — alerta):     {counters['tier_B_degradada']}")
    print(f"  → Tier C (LIBERAR — porta saudável):{counters['tier_C_saudavel']}")

    # 6) Quem é Tier A (deve ser EXCLUÍDO do piloto)
    tier_a = [d for d in detail if d["tier"] == "A_bloquear"]
    print(f"\n[Tier A — BLOQUEAR DO PILOTO] {len(tier_a)} clientes:")
    for d in tier_a[:20]:
        pon = d.get('pon') or '—'
        olt = d.get('olt') or '—'
        if d.get('via') == 'direct_onu':
            extra = f"ONU={d.get('onu_status')} sn={d.get('onu_sn')}"
        else:
            extra = f"({d.get('port_bad',0)}/{d.get('port_total',0)} ONUs ruins)"
        print(f"   {d['external_id']:<10} {(d['name'] or '')[:35]:<35} "
              f"{olt:<12} pon={pon:<6} {extra}")

    tier_b = [d for d in detail if d["tier"] == "B_degradada"]
    print(f"\n[Tier B — DEGRADADA, alerta apenas] {len(tier_b)} clientes")
    for d in tier_b[:10]:
        pon = d.get('pon') or '—'
        olt = d.get('olt') or '—'
        if d.get('via') == 'direct_onu':
            extra = f"ONU={d.get('onu_status')}"
        else:
            extra = f"({d.get('port_bad',0)}/{d.get('port_total',0)} ONUs ruins)"
        print(f"   {d['external_id']:<10} {(d['name'] or '')[:35]:<35} "
              f"{olt:<12} pon={pon:<6} {extra}")

    # 7) Persistir decisão
    payload = {
        "id": f"gate-smartolt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "kind": "smartolt_gate",
        "company_id": company_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": dict(counters),
        "tier_a_blocked": [d["external_id"] for d in tier_a],
        "tier_b_alert":   [d["external_id"] for d in tier_b],
        "details": detail,
    }
    await db.motor_ia_predictions.insert_one(payload)
    print(f"\n[OK] Gravado em motor_ia_predictions: {payload['id']}")
    print(f"\nElegíveis para piloto APÓS gate:")
    print(f"  = Inadimplentes ({len(overdue_ext_ids)}) − Tier A ({counters['tier_A_bloquear']}) − sem_subscriber ({counters['sem_subscriber']})")
    print(f"  = {len(overdue_ext_ids) - counters['tier_A_bloquear'] - counters['sem_subscriber']}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
