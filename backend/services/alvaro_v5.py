"""
alvaro_v5.py — Álvaro IA 2.0 / Constituição V5.0
Sprint 1: Fundação Cognitiva

Reúne:
  - Fase J: Schema canônico DecisionV5 (cause/effect/impact/recommended_action/
    confidence/evidence) com validação estrita.
  - Fase A: consult_network(subscriber_id) — pré-consulta obrigatória de rede
    antes de qualquer triagem; bloqueia sugestão de reboot quando há LOS,
    Power Fail ou Offline.
  - Fase B: recurrence_score(subscriber_id) — score 0-100 com classificação
    Baixo/Médio/Alto/Crítico baseado em tickets 30d/90d, trocas de ONU/Drop/
    Conector/Porta/CTO.

Persiste em:
  - motor_ia_decisions       (adiciona campos v5_*)
  - motor_ia_recurrence_scores (nova collection)
  - motor_ia_events          (emite RECURRENCE_HIGH quando score > 70)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


# ────────────────────────── Helpers ──────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# Status de ONU que PROÍBEM sugestão de reboot
BLOCKING_ONU_STATUSES = {"offline", "los", "power fail", "power_fail"}


# ═══════════════════════════════════════════════════════════
# FASE J — DecisionV5 Schema (Regra de Ouro)
# ═══════════════════════════════════════════════════════════
REQUIRED_V5_FIELDS = (
    "cause", "effect", "impact",
    "recommended_action", "confidence", "evidence",
)


class DecisionV5Error(ValueError):
    """Tentativa de construir DecisionV5 sem todos os campos obrigatórios."""


def build_v5_decision(
    *,
    cause: str,
    effect: str,
    impact: str,
    recommended_action: str,
    confidence: float,
    evidence: List[Dict[str, Any]],
    company_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    action_type: str = "notify_manager",
    action_payload: Optional[Dict[str, Any]] = None,
    trigger_event_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    domain: str = "technical",
) -> Dict[str, Any]:
    """Constrói uma decisão V5-compliant.

    Levanta DecisionV5Error se qualquer campo obrigatório vier vazio.
    `evidence` deve ser uma lista NÃO vazia de dicts {type, value, source}.
    """
    # Validação estrita — sem evidência não existe IA
    for f in REQUIRED_V5_FIELDS:
        val = locals()[f]
        if val is None or (isinstance(val, str) and not val.strip()):
            raise DecisionV5Error(f"DecisionV5 requer campo '{f}' não vazio.")
    if not isinstance(evidence, list) or len(evidence) == 0:
        raise DecisionV5Error(
            "DecisionV5 requer pelo menos 1 item em 'evidence'.")
    if not (0.0 <= float(confidence) <= 1.0):
        raise DecisionV5Error("confidence deve estar entre 0.0 e 1.0.")

    return {
        "id": f"dec-{uuid.uuid4().hex[:14]}",
        "created_at": _now_iso(),
        "v5_compliant": True,
        "v5_schema_version": "5.0",
        # Regra de Ouro
        "cause": cause,
        "effect": effect,
        "impact": impact,
        "recommended_action": recommended_action,
        "confidence": round(float(confidence), 3),
        "evidence": evidence,
        "domain": domain,
        # contexto operacional
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "action_type": action_type,
        "action_payload": action_payload or {},
        "trigger_event_id": trigger_event_id,
        "correlation_id": correlation_id,
        "executed": False,
    }


async def persist_v5_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Grava em motor_ia_decisions. Espera dict já validado."""
    if not decision.get("v5_compliant"):
        raise DecisionV5Error(
            "Tentativa de persistir decisão não-V5. Use build_v5_decision().")
    to_save = decision.copy()
    await db.motor_ia_decisions.insert_one(to_save)
    to_save.pop("_id", None)
    return to_save


# ═══════════════════════════════════════════════════════════
# FASE A — Pré-consulta de Rede (Álvaro 2.0)
# ═══════════════════════════════════════════════════════════
async def consult_network(
    subscriber_id: str,
    company_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta TUDO da rede para um assinante ANTES de qualquer triagem.

    Retorna ONU/CTO/VLAN/PON + histórico de sinal, tickets, incidentes e
    região. Se a ONU estiver em LOS/Power Fail/Offline, marca
    `block_reboot=True` — Álvaro não pode pedir reboot nesse cenário.
    """
    q = {"id": subscriber_id}
    if company_id:
        q["company_id"] = company_id
    sub = await db.subscribers.find_one(q)
    if not sub:
        return {
            "subscriber_id": subscriber_id,
            "found": False,
            "block_reboot": False,
            "evidence": [],
            "consulted_at": _now_iso(),
        }
    cid = sub.get("company_id") or company_id

    # 1. ONU atual (via smartolt_onu_sn)
    onu_sn = sub.get("smartolt_onu_sn")
    onu_doc = None
    if onu_sn:
        onu_doc = await db.smartolt_onus.find_one(
            {"company_id": cid, "sn": onu_sn})

    onu_status_raw = (
        (onu_doc or {}).get("status")
        or sub.get("smartolt_onu_status") or "Unknown"
    )
    onu_status_norm = onu_status_raw.strip().lower()
    block_reboot = onu_status_norm in BLOCKING_ONU_STATUSES

    # 2. CTO / Zona / PON / VLAN
    cto = sub.get("smartolt_onu_zone") or (onu_doc or {}).get("zone_name")
    pon = None
    if onu_doc:
        pon = (
            f"{onu_doc.get('olt_name')}::"
            f"{onu_doc.get('board')}/{onu_doc.get('port')}"
        )
    vlan = sub.get("current_vlan")
    signal_1310 = (onu_doc or {}).get("signal_1310") or \
        sub.get("smartolt_onu_signal_1310")

    # 3. Histórico de tickets 30/90 dias
    tickets_30 = await db.tickets.count_documents({
        "company_id": cid, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(30)},
    })
    tickets_90 = await db.tickets.count_documents({
        "company_id": cid, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(90)},
    })

    # 4. Histórico de equipamento (trocas)
    ceh = await db.client_equipment_history.find(
        {"company_id": cid, "client_id": subscriber_id}
    ).sort("captured_at", -1).to_list(50)

    # 5. Incidentes recentes na mesma região/CTO
    region_incidents = 0
    if cto:
        sub_ids_same_cto = await db.subscribers.distinct(
            "id",
            {"company_id": cid, "smartolt_onu_zone": cto}
        )
        if sub_ids_same_cto:
            region_incidents = await db.tickets.count_documents({
                "company_id": cid,
                "client_id": {"$in": sub_ids_same_cto},
                "opened_at": {"$gte": _cutoff(7)},
            })

    # 6. Eventos recentes relacionados (LOS, ONU_OFFLINE, etc.)
    recent_events = await db.motor_ia_events.find({
        "company_id": cid,
        "subscriber_id": subscriber_id,
        "created_at": {"$gte": _cutoff(7)},
    }).sort("created_at", -1).to_list(20)
    event_types_7d = [e.get("event_type") for e in recent_events]

    # Build evidence list — auditável
    evidence = [
        {"type": "onu_status", "value": onu_status_raw,
         "source": "smartolt_onus" if onu_doc else "subscribers"},
        {"type": "tickets_30d", "value": tickets_30, "source": "tickets"},
        {"type": "tickets_90d", "value": tickets_90, "source": "tickets"},
        {"type": "equipment_history_count", "value": len(ceh),
         "source": "client_equipment_history"},
        {"type": "region_incidents_7d", "value": region_incidents,
         "source": "tickets"},
        {"type": "recent_event_types_7d", "value": event_types_7d,
         "source": "motor_ia_events"},
    ]
    if signal_1310 is not None:
        evidence.append({"type": "signal_1310_dbm", "value": signal_1310,
                         "source": "smartolt_onus"})

    return {
        "subscriber_id": subscriber_id,
        "company_id": cid,
        "found": True,
        "onu": {
            "sn": onu_sn,
            "status": onu_status_raw,
            "status_normalized": onu_status_norm,
            "signal_1310": signal_1310,
        },
        "network": {
            "cto": cto, "pon": pon, "vlan": vlan,
        },
        "history": {
            "tickets_30d": tickets_30,
            "tickets_90d": tickets_90,
            "equipment_changes": len(ceh),
            "region_incidents_7d": region_incidents,
            "recent_event_types_7d": event_types_7d,
        },
        "block_reboot": block_reboot,
        "block_reason": (
            f"ONU em status '{onu_status_raw}' — reboot inútil. "
            f"Requer intervenção em campo."
        ) if block_reboot else None,
        "evidence": evidence,
        "consulted_at": _now_iso(),
    }


async def triage(
    subscriber_id: str,
    complaint: str,
    company_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Triagem Álvaro 2.0 — SEMPRE consulta rede antes.

    - Se ONU em LOS/Power Fail/Offline → bloqueia reboot, gera DecisionV5
      do tipo `field_intervention` com prioridade alta.
    - Caso contrário → ainda gera DecisionV5 (suporte remoto), confiança
      e ação adequadas ao contexto.

    NUNCA sugere "desligue e ligue" sem antes consultar a rede.
    """
    ctx = await consult_network(subscriber_id, company_id=company_id)

    if not ctx["found"]:
        decision = build_v5_decision(
            cause=f"Assinante {subscriber_id} não encontrado no cadastro.",
            effect="Impossível triar — dados ausentes.",
            impact="Atendimento bloqueado. Risco de churn pela espera.",
            recommended_action=(
                "Verificar cadastro do assinante e re-tentar triagem."),
            confidence=0.99,
            evidence=[{"type": "lookup", "value": "not_found",
                       "source": "subscribers"}],
            company_id=company_id,
            subscriber_id=subscriber_id,
            action_type="notify_manager",
            action_payload={
                "message":
                f"Triagem de {subscriber_id} falhou: assinante inexistente."
            },
            domain="operational",
        )
        return {
            "triage_id": f"trg-{uuid.uuid4().hex[:10]}",
            "subscriber_id": subscriber_id,
            "complaint": complaint,
            "decision": decision,
            "consult_network": ctx,
        }

    onu_status = ctx["onu"]["status_normalized"]

    if ctx["block_reboot"]:
        # PROIBIDO sugerir reboot. Gerar OS de intervenção em campo.
        decision = build_v5_decision(
            cause=(
                f"ONU do assinante {subscriber_id} está em "
                f"'{ctx['onu']['status']}' (LOS/Power Fail/Offline). "
                f"Reclamação reportada: '{complaint[:120]}'."
            ),
            effect=(
                f"Conectividade comprometida na CTO "
                f"{ctx['network']['cto'] or '?'} · "
                f"{ctx['history']['region_incidents_7d']} "
                f"incidentes na região nos últimos 7d."
            ),
            impact=(
                "Cliente sem serviço. Reboot pelo usuário NÃO resolve. "
                "SLA em risco e probabilidade alta de churn se não houver "
                "visita técnica em <24h."
            ),
            recommended_action=(
                "Identifiquei uma falha na ONU. Vou seguir com o "
                "diagnóstico adequado e abrir OS técnica prioritária "
                f"para a CTO {ctx['network']['cto'] or '—'}."
            ),
            confidence=0.93,
            evidence=ctx["evidence"],
            company_id=ctx["company_id"],
            subscriber_id=subscriber_id,
            action_type="open_technical_ticket",
            action_payload={
                "subscriber_id": subscriber_id,
                "issue": f"onu_{onu_status.replace(' ', '_')}",
                "cto": ctx["network"]["cto"],
                "priority": "high",
                "reason_no_reboot": (
                    "ONU em LOS/Power Fail/Offline. Reboot remoto não "
                    "resolve. Requer técnico em campo."
                ),
            },
            domain="technical",
        )
        return {
            "triage_id": f"trg-{uuid.uuid4().hex[:10]}",
            "subscriber_id": subscriber_id,
            "complaint": complaint,
            "reboot_blocked": True,
            "decision": decision,
            "consult_network": ctx,
        }

    # ONU saudável — pode tentar diagnóstico remoto antes
    decision = build_v5_decision(
        cause=(
            f"Reclamação reportada por {subscriber_id}: "
            f"'{complaint[:120]}'. ONU online."
        ),
        effect=(
            f"Sinal {ctx['onu']['signal_1310']}dBm · "
            f"tickets 30d={ctx['history']['tickets_30d']} · "
            f"VLAN {ctx['network']['vlan'] or '?'}."
        ),
        impact=(
            f"Sem sinal de degradação técnica imediata. "
            f"{ctx['history']['tickets_30d']} tickets em 30d sugere "
            f"acompanhamento adicional para evitar churn."
        ),
        recommended_action=(
            "Executar diagnóstico remoto guiado (WiFi, velocidade, "
            "configuração) antes de despachar técnico. Se sinal cair, "
            "escalar para visita."
        ),
        confidence=0.78,
        evidence=ctx["evidence"],
        company_id=ctx["company_id"],
        subscriber_id=subscriber_id,
        action_type="remote_diagnostic",
        action_payload={
            "subscriber_id": subscriber_id,
            "complaint": complaint,
            "next_step": "guided_wifi_check",
        },
        domain="technical",
    )
    return {
        "triage_id": f"trg-{uuid.uuid4().hex[:10]}",
        "subscriber_id": subscriber_id,
        "complaint": complaint,
        "reboot_blocked": False,
        "decision": decision,
        "consult_network": ctx,
    }


# ═══════════════════════════════════════════════════════════
# FASE B — Motor de Recorrência
# ═══════════════════════════════════════════════════════════
# Pesos (somam 100) — ajustáveis sem mexer em código se passarmos pra config
RECURRENCE_WEIGHTS = {
    "tickets_30d": 25,    # tickets últimos 30 dias (1 ticket = 5pts, cap 25)
    "tickets_90d": 15,    # 90 dias (1 ticket = 2pts, cap 15)
    "onu_swaps": 15,      # cada troca = 8pts, cap 15
    "drop_swaps": 10,     # cada troca = 5pts, cap 10
    "connector_swaps": 5,
    "port_changes": 15,
    "cto_changes": 15,
}


def _classify_recurrence(score: float) -> str:
    if score >= 81:
        return "CRITICO"
    if score >= 61:
        return "ALTO"
    if score >= 31:
        return "MEDIO"
    return "BAIXO"


async def _count_equipment_actions(
    company_id: str, subscriber_id: str
) -> Dict[str, int]:
    """Conta trocas reais a partir de client_equipment_history."""
    rows = await db.client_equipment_history.find(
        {"company_id": company_id, "client_id": subscriber_id}
    ).to_list(None)

    onu_sns_seen: List[str] = []
    onu_swaps = 0
    port_changes = 0
    cto_changes = 0

    for r in sorted(rows, key=lambda x: x.get("captured_at") or ""):
        action = r.get("action")
        sn = r.get("ont_sn")
        if action == "install" and sn:
            if onu_sns_seen and onu_sns_seen[-1] and sn != onu_sns_seen[-1]:
                onu_swaps += 1
            onu_sns_seen.append(sn)
        if action in ("port_swap", "port_link"):
            prev_port = r.get("prev_cto_port_number")
            cur_port = r.get("cto_port_number")
            if prev_port is not None and cur_port is not None \
                    and prev_port != cur_port:
                port_changes += 1
            prev_cto = r.get("prev_cto_id")
            cur_cto = r.get("cto_id")
            if prev_cto and cur_cto and prev_cto != cur_cto:
                cto_changes += 1

    return {
        "onu_swaps": onu_swaps,
        "port_changes": port_changes,
        "cto_changes": cto_changes,
    }


async def _count_proxy_swaps(
    company_id: str, subscriber_id: str
) -> Dict[str, int]:
    """Drop e conector não têm collection dedicada — proxy via tickets
    cuja descrição/subject menciona o termo. Conservador (subestima)."""
    cur = db.tickets.find({
        "company_id": company_id, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(180)},
    })
    drop = connector = 0
    async for t in cur:
        txt = " ".join([
            str(t.get("subject") or ""),
            str(t.get("description") or ""),
            str(t.get("category") or ""),
        ]).lower()
        if "drop" in txt:
            drop += 1
        if "conector" in txt or "connector" in txt:
            connector += 1
    return {"drop_swaps": drop, "connector_swaps": connector}


async def compute_recurrence_score(
    subscriber_id: str,
    company_id: Optional[str] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Calcula recurrence_score 0-100 e classifica.

    Quando score > 70 → emite evento RECURRENCE_HIGH para o motor de
    decisão criar OS preventiva no próximo ciclo.
    """
    sub = await db.subscribers.find_one({"id": subscriber_id})
    if not sub:
        return {
            "subscriber_id": subscriber_id,
            "found": False,
            "score": 0,
            "classification": "BAIXO",
        }
    cid = company_id or sub.get("company_id")

    # 1. Tickets 30/90d
    tickets_30 = await db.tickets.count_documents({
        "company_id": cid, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(30)},
    })
    tickets_90 = await db.tickets.count_documents({
        "company_id": cid, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(90)},
    })

    # 2. Equipment actions reais
    eq = await _count_equipment_actions(cid, subscriber_id)
    # 3. Drop/Connector proxy via tickets
    px = await _count_proxy_swaps(cid, subscriber_id)

    raw = {
        "tickets_30d": tickets_30,
        "tickets_90d": tickets_90,
        "onu_swaps": eq["onu_swaps"],
        "drop_swaps": px["drop_swaps"],
        "connector_swaps": px["connector_swaps"],
        "port_changes": eq["port_changes"],
        "cto_changes": eq["cto_changes"],
    }

    # Score: aplicar pesos com caps para evitar explosão
    points = 0.0
    breakdown: Dict[str, float] = {}
    multipliers = {
        "tickets_30d": 5.0, "tickets_90d": 2.0,
        "onu_swaps": 8.0, "drop_swaps": 5.0, "connector_swaps": 4.0,
        "port_changes": 7.5, "cto_changes": 7.5,
    }
    for key, weight in RECURRENCE_WEIGHTS.items():
        cnt = raw.get(key, 0)
        contrib = min(cnt * multipliers[key], weight)
        points += contrib
        breakdown[key] = round(contrib, 2)
    score = round(min(points, 100.0), 1)
    classification = _classify_recurrence(score)

    doc = {
        "id": f"rec-{uuid.uuid4().hex[:10]}",
        "subscriber_id": subscriber_id,
        "company_id": cid,
        "score": score,
        "classification": classification,
        "raw_counts": raw,
        "breakdown": breakdown,
        "priority_high": score > 70,
        "force_os": score > 70,
        "notify_supervisor": score > 70,
        "computed_at": _now_iso(),
    }

    if persist:
        # Upsert para manter histórico leve
        await db.motor_ia_recurrence_scores.update_one(
            {"subscriber_id": subscriber_id, "company_id": cid},
            {"$set": doc},
            upsert=True,
        )

        # Emite evento RECURRENCE_HIGH quando passa do threshold
        if score > 70:
            await db.motor_ia_events.insert_one({
                "id": f"evt-{uuid.uuid4().hex[:12]}",
                "event_id": f"evt-{uuid.uuid4().hex[:12]}",
                "event_type": "RECURRENCE_HIGH",
                "company_id": cid,
                "subscriber_id": subscriber_id,
                "payload": {
                    "subscriber_id": subscriber_id,
                    "score": score,
                    "classification": classification,
                    "raw_counts": raw,
                },
                "consumed": False,
                "created_at": _now_iso(),
                "timestamp": _now_iso(),
            })

    return doc


async def recompute_recurrence_batch(
    company_id: str, limit: int = 500
) -> Dict[str, Any]:
    """Recalcula recurrence_score para os assinantes ativos."""
    subs = await db.subscribers.find(
        {"company_id": company_id, "status": {"$ne": "inactive"}}
    ).limit(limit).to_list(limit)
    processed = 0
    high = 0
    critical = 0
    for s in subs:
        try:
            r = await compute_recurrence_score(
                s["id"], company_id=company_id, persist=True)
            processed += 1
            if r["classification"] == "ALTO":
                high += 1
            if r["classification"] == "CRITICO":
                critical += 1
        except Exception:
            continue
    return {
        "company_id": company_id,
        "processed": processed,
        "high": high,
        "critical": critical,
        "generated_at": _now_iso(),
    }
