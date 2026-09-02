"""Subscriber Connection Status — verifica o status da ONU/ONT do cliente.

Fluxo:
    phone → subscriber_phones → subscribers → pppoe_user (ou nome)
                                          → smartolt_onus → status/signal

Resposta padronizada para ser injetada no system_prompt da Isabella quando
detectarmos intent de "problema/defeito/internet caiu". Permite que a IA
diga ao cliente "Já verifiquei aqui, sua conexão está [Online/Offline/LOS]
com sinal [Very good / Weak]" antes de seguir o protocolo.

Casos de retorno:
    - {found: True, connected: True/False, status, signal, olt, port,
       last_change, board}
    - {found: False, reason: <motivo amigável>}

AÇÃO REAL — Quando detectarmos LOS/Offline/Power fail num cliente
identificado, criamos AUTOMATICAMENTE um ticket de reparo no Kanban (em
`db.tickets`), com anti-duplicado de 6h. A IA é informada do ID do ticket
e usa isso na resposta ("Já abri o chamado #TKT-XYZ pra você").
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core import now_iso
from database import db

logger = logging.getLogger("subscriber_connection")

# Palavras-chave (PT-BR + LIGO domain) que disparam o check automático.
PROBLEM_INTENT_REGEX = re.compile(
    r"\b("
    r"caiu|caindo|caída|cair|"
    r"parou|paro|morreu|morreu|sumiu|sumiram|"
    r"acabou\s+(a\s+)?(internet|net|wi-?fi|sinal)|"
    r"voltou\s+a\s+(cair|parar)|"
    r"sem\s+(internet|sinal|conex|wi-?fi)|"
    r"n(ã|a)o\s+(funciona|tem|liga|conect|carreg|t(á|a))|"
    r"defeito|problema|panic|panou|panhei|"
    r"lent[oa]|len(ti|tí)ssim[oa]|trav(a|an|am|ar|ou|ando)|"
    r"oscila|instab|intermitente|"
    r"off(\s*line)?|offline|"
    r"sem\s+navegar|n(ã|a)o\s+navega|"
    r"reset(ei|ou)?|reiniciei|"
    r"net\s+ruim|internet\s+ruim|"
    r"luz\s+(vermelha|piscando|apagada)|"
    r"modem|roteador|onu|ont"
    r")\b",
    re.IGNORECASE,
)


def is_problem_intent(text: str) -> bool:
    """True se a mensagem do cliente sugere problema na conexão."""
    if not text:
        return False
    return bool(PROBLEM_INTENT_REGEX.search(text))


async def check_connection_for_phone(
    company_id: str, phone: str, subscriber_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta o status atual da ONU vinculada ao telefone.

    Retorna um dict pronto pra serializar e injetar no prompt da IA.
    NUNCA levanta exceção — sempre retorna {found: bool, ...}.

    Se `subscriber_id` for passado, pula o lookup phone→subscriber e usa
    direto — útil quando o cliente acabou de ser identificado por CPF e
    ainda não foi indexado em `subscriber_phones`.
    """
    if not company_id or (not phone and not subscriber_id):
        return {"found": False, "reason": "parâmetros vazios"}

    sub = None
    if subscriber_id:
        # Caminho direto — cliente identificado por CPF nesta inbound
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": subscriber_id},
            {"_id": 0, "name": 1, "pppoe_user": 1, "plan_name": 1,
             "external_code": 1, "branch": 1, "document": 1, "status": 1},
        )

    if not sub:
        # 1. phone → subscriber (tenta múltiplos formatos)
        digits = re.sub(r"\D", "", phone or "")
        candidates = {digits}
        if digits.startswith("55") and len(digits) >= 12:
            candidates.add(digits[2:])  # sem DDI
        if len(digits) >= 11:
            candidates.add(digits[-11:])  # últimos 11 (DDD + número)

        sub_phone_doc = None
        for cand in candidates:
            sub_phone_doc = await db.subscriber_phones.find_one(
                {"company_id": company_id,
                 "$or": [{"normalized_number": cand},
                         {"phone": cand}, {"raw_number": cand}]},
                {"_id": 0, "subscriber_id": 1},
            )
            if sub_phone_doc:
                break
        if not sub_phone_doc:
            return {"found": False,
                    "reason": "telefone não vinculado a nenhum assinante"}
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": sub_phone_doc["subscriber_id"]},
            {"_id": 0, "name": 1, "pppoe_user": 1, "plan_name": 1,
             "external_code": 1, "branch": 1, "document": 1, "status": 1},
        )
        if not sub:
            return {"found": False, "reason": "assinante não encontrado"}

    # 2. Acha a ONU — prioridade: pppoe_user > external_code > nome
    onu = None
    pppoe = (sub.get("pppoe_user") or "").strip()
    if pppoe:
        onu = await db.smartolt_onus.find_one(
            {"company_id": company_id, "pppoe_user": pppoe},
            {"_id": 0, "name": 1, "pppoe_user": 1, "status": 1,
             "signal_text": 1, "signal_1310": 1, "signal_1490": 1,
             "olt_name": 1, "board": 1, "port": 1,
             "last_status_change": 1, "unique_external_id": 1},
        )
    if not onu:
        # Fallback fuzzy: tenta achar ONU pelo nome do cliente
        # (algumas bases batizam a ONU com o nome do assinante)
        name = (sub.get("name") or "").strip()
        if name and len(name) >= 5:
            # Tenta primeiro nome + algum sobrenome
            first_token = name.split()[0]
            if len(first_token) >= 3:
                onu = await db.smartolt_onus.find_one(
                    {"company_id": company_id,
                     "name": {"$regex": re.escape(name[:25]), "$options": "i"}},
                    {"_id": 0, "name": 1, "pppoe_user": 1, "status": 1,
                     "signal_text": 1, "signal_1310": 1, "signal_1490": 1,
                     "olt_name": 1, "board": 1, "port": 1,
                     "last_status_change": 1, "unique_external_id": 1},
                )

    if not onu:
        # V15.3 — Mesmo sem ONU, geramos cadastro_claim para
        # o subscriber encontrado (alimenta Trust Score)
        try:
            from services.isabella_claim_generators import cadastro_claim
            await cadastro_claim(
                company_id=company_id, phone="", subscriber=sub,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[subscriber_connection] cadastro_claim sem ONU: %s", e,
            )
        return {
            "found": False,
            "subscriber_name": sub.get("name"),
            "plan_name": sub.get("plan_name"),
            "reason": ("assinante encontrado mas equipamento (ONU) não está "
                       "vinculado no cache SmartOLT"),
        }

    # --- Enriquecimento: busca endereço/bairro/cidade do ticket mais recente
    # do mesmo cliente. Os subscribers não armazenam endereço, mas os tickets
    # importados do Atlaz têm `client_snapshot.neighborhood` e `city`.
    address_info: Dict[str, Any] = {}
    try:
        recent_tk = await db.tickets.find_one(
            {"company_id": company_id, "client_id": sub.get("id")},
            {"_id": 0, "client_snapshot": 1},
            sort=[("created_at", -1)],
        )
        if not recent_tk:
            # Fallback: busca por nome se client_id não bater
            recent_tk = await db.tickets.find_one(
                {"company_id": company_id,
                 "client_snapshot.name": sub.get("name")},
                {"_id": 0, "client_snapshot": 1},
                sort=[("created_at", -1)],
            )
        if recent_tk:
            cs = recent_tk.get("client_snapshot") or {}
            address_info = {
                "neighborhood": cs.get("neighborhood") or cs.get("bairro"),
                "city": cs.get("city") or cs.get("cidade"),
                "address": cs.get("address") or cs.get("endereco"),
                "complement": cs.get("complement"),
                "cep": cs.get("cep"),
            }
            address_info = {k: v for k, v in address_info.items() if v}
    except Exception as e:
        logger.info("[subscriber_connection] enrich address skip: %s", e)

    status_raw = (onu.get("status") or "").strip()
    # Normaliza:
    #   "Online" → connected=True (conexão saudável)
    #   "Offline" / "LOS" / "Power fail" → connected=False
    connected = status_raw.lower() == "online"

    # Calcula tempo desde o último mudança de status
    last_change = onu.get("last_status_change")
    minutes_since = None
    try:
        if last_change:
            dt = datetime.fromisoformat(str(last_change).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            minutes_since = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
    except Exception:
        minutes_since = None

    # --- Persistência do SN no cadastro do cliente (estoque-cliente) ---
    onu_sn = onu.get("sn") or onu.get("serial_number") or onu.get("serial")
    onu_id_val = onu.get("unique_external_id")
    onu_model = onu.get("model") or onu.get("onu_model")
    try:
        equipment_snapshot = {
            "sn": onu_sn,
            "model": onu_model,
            "onu_id": onu_id_val,
            "onu_name": onu.get("name"),
            "olt_name": onu.get("olt_name"),
            "board": onu.get("board"),
            "port": onu.get("port"),
            "last_seen_at": now_iso(),
            "last_status": status_raw,
        }
        # Remove keys None pra não sobrescrever com vazio
        equipment_snapshot = {k: v for k, v in equipment_snapshot.items() if v is not None}
        if equipment_snapshot:
            await db.subscribers.update_one(
                {"company_id": company_id, "id": sub.get("id")},
                {"$set": {"equipment": equipment_snapshot}},
            )
    except Exception as e:
        logger.info("[subscriber_connection] save equipment falhou: %s", e)

    # ── P0 CEO 17/02/2026 — CLAIM TECHNICAL ─────────────────
    # Antes de retornar, gera claim auditável. A Isabella só pode
    # afirmar "online" / "sinal X" se `audit_passed=True`.
    def _parse_signal_dbm(s: Any) -> Optional[float]:
        """signal_1310 vem como string `'-22.4 dBm'` ou número ou None."""
        if s is None or s == "":
            return None
        try:
            import re as _re
            txt = str(s)
            m = _re.search(r"-?\d+\.?\d*", txt)
            return float(m.group(0)) if m else None
        except Exception:
            return None

    signal_1310_val = _parse_signal_dbm(onu.get("signal_1310"))
    signal_1490_val = _parse_signal_dbm(onu.get("signal_1490"))
    rx_in_range = (
        signal_1310_val is not None
        and -30.0 <= signal_1310_val <= -8.0
    )
    olt_reachable = bool(onu and onu.get("status") is not None)
    SNAPSHOT_MAX_H = 24.0
    snapshot_fresh = (
        minutes_since is not None
        and minutes_since / 60.0 <= SNAPSHOT_MAX_H
    )
    tech_checks = [
        {"name": "olt_reachable", "ok": olt_reachable,
         "onu_name": onu.get("name")},
        {"name": "rx_power_in_range",
         "ok": rx_in_range or status_raw.lower() == "los",
         "rx_dbm_1310": signal_1310_val,
         "rx_dbm_1490": signal_1490_val,
         "range": "[-30, -8] dBm"},
        {"name": "snapshot_fresh",
         "ok": snapshot_fresh if minutes_since is not None else True,
         "minutes_since_change": minutes_since,
         "max_h": SNAPSHOT_MAX_H},
    ]
    tech_warnings: List[str] = []
    if not olt_reachable:
        tech_warnings.append("olt_snapshot_missing")
    if signal_1310_val is None and status_raw.lower() != "los":
        tech_warnings.append("signal_1310_missing")
    if (minutes_since is not None
            and minutes_since / 60.0 > SNAPSHOT_MAX_H):
        tech_warnings.append(
            f"snapshot_stale:{minutes_since/60.0:.1f}h>{SNAPSHOT_MAX_H}h")

    tech_evidence = {
        "onu_sn": onu_sn,
        "onu_status_raw": status_raw,
        "connected": connected,
        "signal_1310_dbm": signal_1310_val,
        "signal_1490_dbm": signal_1490_val,
        "olt_name": onu.get("olt_name"),
        "minutes_since_change": minutes_since,
    }
    tech_claim_id: Optional[str] = None
    try:
        from services import isabella_factual_claims as _fc
        tech_claim = await _fc.claim(
            domain=_fc.ClaimDomain.TECHNICAL,
            entity_type="onu",
            entity_id=onu_sn or onu_id_val,
            company_id=company_id,
            checks=tech_checks,
            warnings=tech_warnings,
            evidence=tech_evidence,
        )
        tech_claim_id = tech_claim.get("id")
    except Exception as e:  # noqa: BLE001
        logger.exception("[subscriber_connection] tech claim exc: %s", e)

    # V15.3 — Gera também o cadastro_claim (subscriber_status). Esta
    # claim cobre a identificação cadastral (nome, plano, endereço) e
    # passa quase sempre para clientes ativos, alimentando o Trust
    # Score com evidência real do banco.
    cadastro_claim_id: Optional[str] = None
    try:
        from services.isabella_claim_generators import cadastro_claim
        res = await cadastro_claim(
            company_id=company_id, phone="", subscriber=sub,
        )
        cadastro_claim_id = res.get("evidence_id")
    except Exception as e:  # noqa: BLE001
        logger.warning("[subscriber_connection] cadastro_claim falhou: %s", e)

    return {
        "found": True,
        "subscriber_name": sub.get("name"),
        "subscriber_nickname": sub.get("nickname"),
        "plan_name": sub.get("plan_name"),
        "plan_speed": sub.get("plan_speed"),
        "plan_price": sub.get("plan_price"),
        "branch": sub.get("branch"),
        "external_code": sub.get("external_code"),
        "document": sub.get("document"),
        "billing_method": sub.get("billing_method"),
        "due_day": sub.get("due_day"),
        "neighborhood": address_info.get("neighborhood"),
        "city": address_info.get("city"),
        "address": address_info.get("address"),
        "cep": address_info.get("cep"),
        "connected": connected,
        "status": status_raw or "desconhecido",
        "signal_text": onu.get("signal_text"),
        "signal_1310": onu.get("signal_1310"),
        "signal_1490": onu.get("signal_1490"),
        "olt_name": onu.get("olt_name"),
        "board": onu.get("board"),
        "port": onu.get("port"),
        "last_status_change": last_change,
        "minutes_since_change": minutes_since,
        "onu_name": onu.get("name"),
        "onu_id": onu_id_val,
        "onu_sn": onu_sn,
        "onu_model": onu_model,
        "tech_audit_passed": (
            len(tech_warnings) == 0
            and all(c.get("ok") for c in tech_checks)),
        "tech_evidence_id": tech_claim_id,
        "cadastro_evidence_id": cadastro_claim_id,
        "tech_warnings": tech_warnings,
    }


def format_for_prompt(info: Dict[str, Any]) -> str:
    """Formata o resultado de check_connection_for_phone() em texto pronto
    pra ser anexado ao system_prompt da Isabella.
    """
    if not info.get("found"):
        reason = info.get("reason", "não foi possível verificar")
        sub_name = info.get("subscriber_name")
        if sub_name:
            return (
                "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
                f"Cliente: {sub_name}\n"
                f"Status: ❓ NÃO LOCALIZADO ({reason})\n"
                "AÇÃO: Diga ao cliente que você consultou o sistema mas o "
                "equipamento dele NÃO está vinculado ao cadastro técnico. "
                "Peça gentilmente que ele informe o CPF do titular pra você "
                "abrir um chamado especializado e localizar manualmente."
            )
        return (
            "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
            f"Status: ❓ TELEFONE NÃO IDENTIFICADO ({reason})\n"
            "AÇÃO: Você não conseguiu vincular este telefone a nenhum cliente. "
            "Peça o CPF do titular antes de prosseguir."
        )

    sub_name = info.get("subscriber_name", "Cliente")
    nick = info.get("subscriber_nickname") or ""
    plan = info.get("plan_name") or "—"
    branch = info.get("branch") or "—"
    document = info.get("document") or ""
    neighborhood = info.get("neighborhood") or ""
    city = info.get("city") or ""
    address = info.get("address") or ""
    cep = info.get("cep") or ""
    due_day = info.get("due_day")
    billing = info.get("billing_method") or ""
    status = info.get("status", "desconhecido")
    signal = info.get("signal_text") or "—"
    olt = info.get("olt_name") or "—"
    port = info.get("port") or "—"
    minutes = info.get("minutes_since_change")
    sn = info.get("onu_sn") or "—"
    model = info.get("onu_model") or "—"

    # Bloco com TODOS os dados que a Isabella JÁ TEM e NÃO deve pedir
    known_data_lines = [f"Nome: {sub_name}"]
    if nick:
        known_data_lines.append(f"Apelido/Tratamento: {nick}")
    known_data_lines.append(f"Plano: {plan}")
    if branch != "—":
        known_data_lines.append(f"Filial: {branch}")
    if neighborhood:
        known_data_lines.append(f"Bairro: {neighborhood}")
    if city:
        known_data_lines.append(f"Cidade: {city}")
    if address:
        known_data_lines.append(f"Endereço: {address}")
    if cep:
        known_data_lines.append(f"CEP: {cep}")
    if document:
        known_data_lines.append(f"CPF/CNPJ: {document}")
    if due_day:
        known_data_lines.append(f"Vencimento: dia {due_day}")
    if billing:
        known_data_lines.append(f"Forma de pagamento: {billing}")
    known_data_block = "\n  ".join(known_data_lines)

    if info.get("connected"):
        emoji = "🟢"
        action = (
            "AÇÃO: o equipamento do cliente está ONLINE e com sinal aceitável. "
            "Informe isso de forma natural ('Já verifiquei aqui no nosso sistema "
            "e seu equipamento está online, com sinal {signal}.'). "
            "Depois pergunte o que mais ele observou — pode ser problema no "
            "WiFi (não no link), no roteador secundário, ou em um aparelho "
            "específico. Conduza o troubleshooting começando pelo mais simples."
        ).format(signal=signal.lower())
    elif status.lower() in {"los"}:
        emoji = "🔴"
        action = (
            "AÇÃO: o equipamento está em LOS (Loss of Signal — fibra rompida "
            "ou desconectada). Diga ao cliente que você verificou e identificou "
            "uma INTERRUPÇÃO no sinal de fibra. NÃO peça reset do modem — não "
            "resolve LOS. O sistema JÁ ABRIU automaticamente uma bolha de "
            "reparo prioritária na Lousa (db.tickets) — use o ticket_id do "
            "bloco 'CHAMADO TÉCNICO ABERTO' que virá em seguida. AGENDE a "
            "visita usando a janela da Lousa (consulte agenda antes de "
            "prometer horário). SLA 24h úteis (residencial)."
        )
    elif status.lower() == "power fail":
        emoji = "🟡"
        action = (
            "AÇÃO: o equipamento está em POWER FAIL (sem energia). Pergunte "
            "gentilmente se houve queda de energia na casa do cliente ou se "
            "o roteador está desligado da tomada. Oriente a verificar se as "
            "luzes do equipamento estão acesas. Se sim, peça pra desligar e "
            "religar na tomada."
        )
    else:  # Offline
        emoji = "🔴"
        action = (
            "AÇÃO: o equipamento está OFFLINE (sumiu da OLT). Isso geralmente "
            "indica problema do lado do cliente: queda de energia local, modem "
            "desligado da tomada ou cabo solto. Como NÃO conseguimos diagnosticar "
            "remotamente com certeza, o protocolo é TRANSFERIR pro Atendimento "
            "Especializado pra um humano acompanhar — NÃO abra chamado técnico "
            "automaticamente (pode ser só tomada). Reconheça o problema com "
            "empatia, diga que está transferindo, e finalize a conversa "
            "naturalmente. O sistema vai injetar o bloco 'TRANSFERIR PARA "
            "ATENDIMENTO ESPECIALIZADO' em seguida — siga aquelas instruções."
        )

    last_info = ""
    if minutes is not None:
        if minutes < 60:
            last_info = f"ONLINE HÁ ~{minutes}min."
        elif minutes < 60 * 24:
            last_info = f"ONLINE HÁ ~{minutes // 60}h."
        else:
            last_info = f"ONLINE HÁ ~{minutes // (60 * 24)}d."
        # Se desconectado, é o tempo desde a queda
        if status.lower() != "online":
            last_info = last_info.replace("ONLINE HÁ", "Caiu há")

    # P0 CEO 17/02/2026 — REGRA DURA: se claim TECHNICAL não passou,
    # injeta bloco TECNICO_NAO_AUDITAVEL e proíbe Isabella de afirmar
    # status técnico ao cliente.
    audit_passed = info.get("tech_audit_passed", True)
    audit_warns = info.get("tech_warnings") or []
    evid_id = info.get("tech_evidence_id") or "—"

    if not audit_passed:
        return (
            "=== VERIFICAÇÃO TÉCNICA — AUDITORIA FALHOU ===\n"
            f"📋 Cliente identificado: {sub_name} · Plano: {plan}\n\n"
            f"🚫 STATUS TÉCNICO NÃO AUDITÁVEL\n"
            f"  evidence_id: {evid_id}\n"
            f"  warnings: {', '.join(audit_warns) or 'multiple'}\n\n"
            "AÇÃO OBRIGATÓRIA: NÃO afirme nada sobre estado do equipamento, "
            "potência ótica, online/offline ou sinal. A consulta retornou "
            "dados incompletos ou desatualizados. Responda apenas:\n"
            "  → 'Vou conferir essa informação com mais cuidado. Só um instante.'\n"
            "Em seguida, ROTEIE pra suporte ([ROTEAR_SUPORTE]) que o Álvaro "
            "consulta direto na OLT em tempo real."
        )

    return (
        "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
        f"🔒 evidence_id: {evid_id} (auditoria PASSOU)\n"
        "📋 DADOS QUE VOCÊ JÁ TEM SOBRE ESTE CLIENTE (NÃO PEÇA NOVAMENTE):\n"
        f"  {known_data_block}\n\n"
        f"🔌 SITUAÇÃO TÉCNICA AGORA:\n"
        f"  Equipamento: {emoji} **{status}** · Sinal: {signal}\n"
        f"  SN: {sn} · Modelo: {model}\n"
        f"  OLT: {olt} · Porta: {port}\n"
        f"  {last_info}\n\n"
        f"{action}\n"
        "⚠️ REGRA DE OURO: Os dados acima já estão no SISTEMA. NUNCA pergunte "
        "ao cliente algo que você JÁ TEM aqui (nome, plano, bairro, cidade, "
        "endereço, CPF, dia de vencimento, forma de pagamento). Se precisar "
        "confirmar, apenas mencione naturalmente (\"Vi aqui que seu plano é "
        f"{plan} e você está em {neighborhood or city or branch}, correto?\"). "
        "Mas use os dados pra DAR contexto à conversa, não pra pedir info.\n\n"
        "IMPORTANTE: NÃO recite estes dados técnicos crus pro cliente. "
        "Use linguagem leiga (ex: 'verifiquei aqui no sistema e seu equipamento "
        "está online há 3 dias, com sinal bom'). Apenas mencione 'OLT', 'porta', "
        "'LOS', 'sinal -28dBm', 'SN' se o cliente perguntar especificamente."
    )



# Status técnicos que justificam abrir ticket de reparo automaticamente.
# - LOS: SEMPRE gera bolha de reparo na Lousa (fibra rompida — só técnico resolve).
# - Power fail: gera bolha (cliente sem energia local, mas registra pro atendente
#   acompanhar/agendar visita preventiva).
# - Offline: NÃO gera ticket — fluxo agora transfere direto pra humano (decisão
#   do gestor em 02/2026; Isabella não tem como diagnosticar a causa real).
TICKET_TRIGGER_STATUSES = {"los", "power fail", "powerfail"}

# Status que primeiro tentam reboot remoto antes de abrir ticket.
# Por decisão do gestor (02/2026), Isabella NÃO reinicia automaticamente em
# LOS (não adianta — sinal cortado) nem em Offline (provável problema do lado
# do cliente — energia/cabo solto). Conjunto vazio = nenhum reboot automático.
# A função `try_reboot_onu()` permanece disponível pra futuro acionamento manual
# via UI ou tool-call específica.
REBOOT_FIRST_STATUSES: set = set()

# Janela de dedupe — não cria ticket novo se já tem um aberto pro mesmo cliente.
TICKET_DEDUPE_HOURS = 6

# Janela de dedupe pro reboot — se já fez reboot recente, não tenta de novo
# (evita ficar em loop reiniciando a ONU toda hora se cliente reclamar).
REBOOT_DEDUPE_MINUTES = 30


async def try_reboot_onu(
    company_id: str, conn_info: Dict[str, Any], phone: str,
) -> Dict[str, Any]:
    """Tenta reiniciar a ONU remotamente via SmartOLT API.

    Retorna:
      - {ok: True, action: "rebooted", was_recent: False}  → reboot disparado agora
      - {ok: True, action: "skipped_recent", was_recent: True}  → já houve reboot recente
      - {ok: False, action: "disabled"|"no_onu_id"|"http_error", error: ...}
    """
    onu_id = conn_info.get("onu_id")
    if not onu_id:
        return {"ok": False, "action": "no_onu_id"}

    # Dedupe — se reboot foi feito nos últimos 30 min, NÃO tenta de novo.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=REBOOT_DEDUPE_MINUTES)
              ).isoformat()
    recent = await db.smartolt_actions.find_one(
        {"company_id": company_id, "action": "reboot",
         "external_id": onu_id,
         "result_ok": True,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "created_at": 1},
    )
    if recent:
        logger.info(
            "[subscriber_connection] reboot SKIP (já feito recentemente): "
            "onu=%s last=%s", onu_id, recent.get("created_at"),
        )
        return {"ok": True, "action": "skipped_recent", "was_recent": True,
                 "last_reboot_at": recent.get("created_at")}

    # Chama SmartOLT API
    try:
        from routes.smartolt import _get_config, _http_post
    except ImportError as e:
        return {"ok": False, "action": "import_error", "error": str(e)}
    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        return {"ok": False, "action": "disabled",
                 "error": "SmartOLT não configurado/desabilitado"}
    try:
        resp = await _http_post(cfg, f"/onu/reboot/{onu_id}")
    except Exception as e:
        logger.warning(
            "[subscriber_connection] reboot FALHOU onu=%s err=%s", onu_id, e
        )
        # Registra a tentativa falha pra auditoria.
        await db.smartolt_actions.insert_one({
            "id": f"sma-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "action": "reboot",
            "external_id": onu_id,
            "onu_name": conn_info.get("onu_name"),
            "olt_name": conn_info.get("olt_name"),
            "actor_user": "isabella_ai",
            "actor_user_id": "isabella_ai",
            "result_ok": False,
            "result_raw": {"error": str(e)},
            "phone": phone,
            "trigger_status": conn_info.get("status"),
            "created_at": now_iso(),
        })
        return {"ok": False, "action": "http_error", "error": str(e)}

    ok = bool(resp.get("status"))
    await db.smartolt_actions.insert_one({
        "id": f"sma-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "action": "reboot",
        "external_id": onu_id,
        "onu_name": conn_info.get("onu_name"),
        "olt_name": conn_info.get("olt_name"),
        "actor_user": "isabella_ai",
        "actor_user_id": "isabella_ai",
        "result_ok": ok,
        "result_raw": resp,
        "phone": phone,
        "trigger_status": conn_info.get("status"),
        "created_at": now_iso(),
    })
    if ok:
        logger.info(
            "[subscriber_connection] REBOOT REMOTO ok onu=%s phone=%s",
            onu_id, phone,
        )
        return {"ok": True, "action": "rebooted", "was_recent": False,
                 "raw": resp}
    return {"ok": False, "action": "smartolt_refused",
             "error": resp.get("error") or str(resp)}


def format_reboot_for_prompt(reboot_info: Dict[str, Any]) -> str:
    """Bloco pra IA dizer ao cliente que reiniciou remotamente."""
    if not reboot_info:
        return ""
    action = reboot_info.get("action")
    if action == "rebooted":
        return (
            "=== AÇÃO EXECUTADA: ONU REINICIADA REMOTAMENTE ===\n"
            "ACABEI DE REINICIAR a ONT/ONU do cliente remotamente, agora "
            "neste exato momento. Ele NÃO precisa fazer nada — só esperar "
            "1-2 minutos.\n\n"
            "AÇÃO PRO CLIENTE: informe que você reiniciou o equipamento dele "
            "remotamente (sem precisar dele desligar/religar a tomada), e "
            "peça pra ele AGUARDAR 2 minutos e testar novamente. Diga que "
            "se em 2 minutos não voltar, é só responder aqui que aí você "
            "abre o chamado técnico imediatamente. Tom: confiante, mas sem "
            "garantir 100%."
        )
    if action == "skipped_recent":
        last = reboot_info.get("last_reboot_at", "")
        return (
            "=== INFO: ONU JÁ FOI REINICIADA RECENTEMENTE ===\n"
            f"A ONU deste cliente já foi reiniciada remotamente em {last[:16]}. "
            "Reiniciar de novo NÃO vai ajudar (problema real exige técnico). "
            "PROSSIGA direto pra abertura do chamado técnico — não tente "
            "reset de novo. NÃO mencione a tentativa anterior pro cliente "
            "(seria confuso)."
        )
    return ""  # erro técnico — não polui o prompt; ticket vai abrir mesmo


def format_offline_transfer_for_prompt() -> str:
    """Pra status Offline, Isabella transfere direto pro humano (sem ticket).

    O backend marca a conversa pra `aguardando` (handoff) após enviar a resposta.
    """
    return (
        "=== TRANSFERIR PARA ATENDIMENTO ESPECIALIZADO ===\n"
        "O equipamento do cliente está OFFLINE (sumiu da OLT). NÃO é possível "
        "diagnosticar remotamente se é tomada / cabo / energia / hardware "
        "queimado — protocolo do gestor é TRANSFERIR direto pra um humano "
        "acompanhar.\n\n"
        "AÇÃO (use 2 bolhas curtas, separadas por \"\"):\n"
        "1. Reconheça o problema com empatia e diga que verificou o sistema "
        "   e o equipamento está realmente desconectado.\n"
        "   Ex: 'Verifiquei aqui e seu equipamento aparece como desconectado "
        "   no nosso sistema. 🔴'\n"
        "2. Avise que vai transferir pro Atendimento Especializado e "
        "   despedir-se de forma natural. Frase OBRIGATÓRIA (gatilho de "
        "   handoff): 'Vou transferir você agora pro nosso Atendimento "
        "   Especializado, em instantes alguém da equipe vai te chamar por "
        "   aqui mesmo. 🤝'\n\n"
        "❌ NÃO ofereça reset / reboot — já foi descartado pela equipe técnica.\n"
        "❌ NÃO peça pra cliente verificar tomada — humano vai conduzir isso.\n"
        "❌ NÃO abra chamado — humano decide se abre depois de conversar.\n"
        "✅ Tom: acolhedor, sem alarmar, profissional."
    )


# Marcador no texto da resposta que indica que Isabella concluiu o handoff de
# diagnóstico Offline. Usado pelo router pra mover a conversa pra 'aguardando'.
OFFLINE_HANDOFF_MARKER_REGEX = re.compile(
    r"transferir\s+.{0,60}?atendimento\s+especializado",
    re.IGNORECASE | re.DOTALL,
)


def is_offline_handoff_message(text: str) -> bool:
    """Detecta se a resposta da Isabella encerra com handoff de Offline."""
    if not text:
        return False
    return bool(OFFLINE_HANDOFF_MARKER_REGEX.search(text))


def format_power_fail_offer_for_prompt() -> str:
    """Pra Power fail, IA oferece agendamento em vez de só abrir chamado."""
    return (
        "=== ESTRATÉGIA — POWER FAIL ===\n"
        "O equipamento está sem energia (provavelmente queda de luz na casa "
        "do cliente ou tomada desligada). NÃO abra chamado técnico imediato "
        "— problema NÃO é nosso. AÇÃO:\n"
        "1. Pergunte: 'A energia da sua casa está OK?' / 'O modem está "
        "   ligado na tomada?'\n"
        "2. Se for queda de energia local: oriente a aguardar voltar.\n"
        "3. Se for problema persistente (cliente diz que ligou tudo e ainda "
        "   nada): OFEREÇA AGENDAR VISITA TÉCNICA: 'Quer que eu agende uma "
        "   visita pra amanhã (manhã 8h-12h ou tarde 13h-17h)?' Quando o "
        "   cliente confirmar o turno, agradeça e diga que vai abrir o "
        "   chamado já com o horário marcado."
    )


async def ensure_repair_ticket(
    company_id: str, conn_info: Dict[str, Any], phone: str,
    triggered_by_text: str,
) -> Optional[Dict[str, Any]]:
    """Cria (se já não existe) um ticket de reparo no Kanban a partir do
    diagnóstico técnico.

    Regras:
    - Só dispara se `conn_info.found == True` e `status` está em
      TICKET_TRIGGER_STATUSES (LOS / Offline / Power fail).
    - Dedup: se cliente já tem ticket "pendente" / "em_andamento" criado
      nas últimas 6h, retorna o existente sem criar duplicado.
    - O ticket é criado com `created_by: "isabella_ai"` para auditoria.

    Retorna o dict do ticket criado/encontrado, ou None se não aplicável.
    """
    if not conn_info or not conn_info.get("found"):
        return None
    status = (conn_info.get("status") or "").strip().lower()
    if status not in TICKET_TRIGGER_STATUSES:
        return None

    subscriber_id = conn_info.get("subscriber_id") or conn_info.get("onu_id")
    sub_name = conn_info.get("subscriber_name") or "Cliente"

    # 1. Dedupe — procura ticket recente aberto pro mesmo cliente
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TICKET_DEDUPE_HOURS)
              ).isoformat()
    existing = await db.tickets.find_one(
        {"company_id": company_id,
         "status": {"$in": ["pendente", "em_andamento", "aceito"]},
         "type": {"$in": ["reparo", "visita"]},
         "created_by": "isabella_ai",
         "client_snapshot.name": sub_name,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "status": 1, "created_at": 1, "priority": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        logger.info(
            "[subscriber_connection] ticket DUPLICADO ignorado pro %s "
            "(já existe %s · status=%s)",
            sub_name, existing.get("id"), existing.get("status")
        )
        return existing

    # 2. Cria o ticket novo
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    # LOS → prioridade (fibra rompida · rede)
    # Offline → prioridade (sem conexão · rede)
    # Power fail → padrao (cliente sem energia local · não é nosso problema)
    if status == "los" or status == "offline":
        priority = "prioridade"
    else:
        priority = "padrao"
    ticket_type = "reparo" if status != "power fail" else "visita"
    description = (
        f"Cliente {sub_name} reportou: \"{(triggered_by_text or '')[:120]}\"\n"
        f"\n"
        f"Diagnóstico SmartOLT (automático):\n"
        f"  Status: {conn_info.get('status')}\n"
        f"  Sinal RX (1490nm): {conn_info.get('signal_1490', '—')} dBm\n"
        f"  Sinal TX (1310nm): {conn_info.get('signal_1310', '—')} dBm\n"
        f"  Sinal qualitativo: {conn_info.get('signal_text', '—')}\n"
        f"  OLT: {conn_info.get('olt_name')} · "
        f"Placa {conn_info.get('board')} · Porta {conn_info.get('port')}\n"
        f"  ONU: {conn_info.get('onu_name')} (ID {conn_info.get('onu_id')})\n"
        f"  Tempo desde mudança de status: "
        f"{conn_info.get('minutes_since_change', '?')} min\n"
        f"\n"
        f"⚠️ Aberto automaticamente pela Isabella IA via WhatsApp ({phone})."
    )
    ticket = {
        "id": ticket_id,
        "company_id": company_id,
        "client_id": subscriber_id,
        "client_snapshot": {
            "name": sub_name,
            "plan": conn_info.get("plan_name"),
            "branch": conn_info.get("branch"),
            "external_code": conn_info.get("external_code"),
            "phone": phone,
            "address": None,
        },
        "type": ticket_type,
        "priority": priority,
        "scheduled_time": None,
        "position": 0,
        "status": "pendente",
        "assigned_collaborator_id": None,
        "opened_at": now_iso(),
        "closed_at": None,
        "closed_by": None,
        "outcome": None,
        "whatsapp_status": "nao_enviado",
        "whatsapp_last_message": None,
        "admin_action": None,
        "admin_notes": None,
        "created_by": "isabella_ai",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": "whatsapp_ai_auto",
        # iter237 — borda VERDE na Lousa (origem cliente: cliente acionou
        # a Isabella no WhatsApp e ela criou o ticket em nome dele)
        "origin_source": "isabella_ai",
        "ai_diagnosis": {
            "trigger_text": triggered_by_text,
            "status": conn_info.get("status"),
            "olt_name": conn_info.get("olt_name"),
            "port": conn_info.get("port"),
            "signal_1490": conn_info.get("signal_1490"),
            "minutes_since_change": conn_info.get("minutes_since_change"),
            "onu_id": conn_info.get("onu_id"),
            "phone": phone,
        },
        "description": description,
    }
    await db.tickets.insert_one(ticket)
    logger.info(
        "[subscriber_connection] TICKET CRIADO id=%s priority=%s status=%s "
        "client=%s phone=%s",
        ticket_id, priority, status, sub_name, phone,
    )

    # --- ALERTA: rompimento de rota troncal (LOS cluster) ---
    # Se 3+ tickets LOS na mesma OLT em <30min, é provável que houve
    # rompimento físico de fibra troncal afetando toda a porção da rede.
    # Emite um evento `los_cluster_alert` em `whatsapp_system_events` pra
    # UI exibir banner pro gestor / despachante.
    try:
        if status == "los":
            olt_name = (conn_info.get("olt_name") or "").strip()
            if olt_name:
                cutoff_30 = (datetime.now(timezone.utc) - timedelta(minutes=30)
                              ).isoformat()
                same_olt_count = await db.tickets.count_documents({
                    "company_id": company_id,
                    "created_by": "isabella_ai",
                    "type": "reparo",
                    "ai_diagnosis.status": {"$regex": "^los$", "$options": "i"},
                    "ai_diagnosis.olt_name": olt_name,
                    "created_at": {"$gte": cutoff_30},
                })
                if same_olt_count >= 3:
                    # Dedupe: só emite o alerta 1x por OLT em janela de 30min
                    already = await db.whatsapp_system_events.find_one({
                        "company_id": company_id,
                        "event": "los_cluster_alert",
                        "reason": {"$regex": re.escape(olt_name), "$options": "i"},
                        "created_at": {"$gte": cutoff_30},
                    }, {"_id": 0, "id": 1})
                    if not already:
                        await db.whatsapp_system_events.insert_one({
                            "id": f"wae-{uuid.uuid4().hex[:10]}",
                            "company_id": company_id,
                            "event": "los_cluster_alert",
                            "code": None,
                            "name": "los_cluster_alert",
                            "retry_count": None,
                            "reason": (
                                f"OLT {olt_name}: {same_olt_count} clientes em "
                                f"LOS em 30min — provável rompimento de fibra "
                                f"troncal."
                            ),
                            "olt_name": olt_name,
                            "tickets_count": int(same_olt_count),
                            "created_at": now_iso(),
                            "acknowledged": False,
                        })
                        logger.error(
                            "[subscriber_connection][ALERTA] LOS CLUSTER %s: "
                            "%s clientes em LOS na mesma OLT em 30min — "
                            "verificar rota troncal.",
                            olt_name, same_olt_count,
                        )
    except Exception as e:
        logger.info("[subscriber_connection] los-cluster detect skip: %s", e)

    return {"id": ticket_id, "status": "pendente", "priority": priority,
             "created_at": ticket["created_at"], "isNew": True}


def format_ticket_for_prompt(ticket_info: Dict[str, Any]) -> str:
    """Adiciona ao prompt uma seção explicando que o chamado foi aberto."""
    if not ticket_info:
        return ""
    is_new = ticket_info.get("isNew", False)
    ticket_id = ticket_info.get("id")
    priority = ticket_info.get("priority", "padrao")
    priority_label = "PRIORITÁRIO" if priority == "prioridade" else "padrão"
    if is_new:
        return (
            "=== AÇÃO EXECUTADA: CHAMADO TÉCNICO ABERTO AUTOMATICAMENTE ===\n"
            f"Ticket #{ticket_id} criado agora ({priority_label}). Status: pendente.\n"
            "A equipe técnica já recebeu o chamado e vai entrar em contato em "
            "até 24h úteis (residencial) ou 12h úteis (empresarial).\n\n"
            "AÇÃO: informe o cliente que VOCÊ JÁ ABRIU o chamado (use o número "
            f"#{ticket_id}, sem o prefixo 'tkt-'). Diga o prazo de SLA. "
            "Pergunte se ele tem alguma observação adicional (ex: melhor "
            "horário de visita, se a luz vai estar disponível, telefone "
            "alternativo). NÃO peça pra ele abrir o chamado — ele JÁ ESTÁ "
            "ABERTO."
        )
    return (
        "=== INFO: JÁ EXISTE CHAMADO EM ANDAMENTO ===\n"
        f"Cliente já tem um chamado de reparo aberto pela Isabella nas "
        f"últimas {TICKET_DEDUPE_HOURS}h (#{ticket_id}, status: "
        f"{ticket_info.get('status')}). NÃO crie outro chamado — informe ao "
        "cliente que o chamado dele JÁ ESTÁ EM ANDAMENTO. Pergunte se ele "
        "precisa de mais alguma coisa enquanto a equipe técnica não chega."
    )
