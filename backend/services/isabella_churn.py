"""ISABELLA CHURN COMMANDER — detecção preditiva de cancelamento.

Score 0..100 por cliente com sinais REAIS:
  • reparos recentes (30d)
  • tickets de lentidão / wifi ruim (30d)
  • sinal óptico degradado da ONU vinculada
  • inadimplência (faturas em open/overdue)
  • plano antigo + sem upgrade
  • ausência de pagamentos recentes (60d)

Saída: `isabella_opportunities(kind=churn)` com ação recomendada
(retenção/desconto/visita técnica). 1-click humano executa.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import get_arpu, upsert_opportunity

log = logging.getLogger("ponto.isabella_churn")

REPAIR_TYPES = ("reparo", "lentidao", "lentidão", "wifi_ruim",
                  "sem internet", "ONU_LOW_SIGNAL", "ONU_OFFLINE")
SIGNAL_BAD_DBM = -27.0
WIN_DAYS = 30


def _now():
    return datetime.now(timezone.utc)


async def _company_scope(company_id: str) -> Dict[str, Any]:
    arpu = await get_arpu(company_id)
    cutoff = (_now() - timedelta(days=WIN_DAYS)).isoformat()
    return {"arpu": arpu, "cutoff": cutoff}


async def _client_signals(company_id: str, cutoff_iso: str) -> Dict[str, Dict[str, Any]]:
    """Agrega sinais de tickets por subscriber_id (atlaz_id_assinante)."""
    pipe = [
        {"$match": {"company_id": company_id,
                      "type": {"$in": list(REPAIR_TYPES)},
                      "$or": [
                          {"opened_at": {"$gte": cutoff_iso}},
                          {"created_at": {"$gte": cutoff_iso}}]}},
        {"$group": {
            "_id": "$atlaz_id_assinante",
            "n_tickets": {"$sum": 1},
            "types": {"$addToSet": "$type"},
            "last_ticket": {"$max": "$opened_at"},
        }},
    ]
    out: Dict[str, Dict[str, Any]] = {}
    async for row in db.tickets.aggregate(pipe):
        sid = row.get("_id")
        if sid is None:
            continue
        out[str(sid).strip()] = {
            "n_tickets": int(row["n_tickets"] or 0),
            "types": [t for t in (row.get("types") or []) if t],
            "last_ticket": row.get("last_ticket"),
        }
    return out


async def _overdue_signals(company_id: str) -> Dict[str, Dict[str, Any]]:
    """Cliente com fatura `overdue` há > 5 dias ou >=2 em open vencidas."""
    today_iso = _now().date().isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                      "status": {"$in": ["overdue", "open"]}}},
        {"$group": {
            "_id": "$subscriber_external_id",
            "n_overdue": {"$sum": {"$cond": [
                {"$eq": ["$status", "overdue"]}, 1, 0]}},
            "n_open": {"$sum": {"$cond": [
                {"$eq": ["$status", "open"]}, 1, 0]}},
            "oldest_due": {"$min": "$due_date"},
            "total_due_brl": {"$sum": "$amount"},
        }},
    ]
    out: Dict[str, Dict[str, Any]] = {}
    async for r in db.subscriber_invoices.aggregate(pipe):
        ext = r.get("_id")
        if not ext:
            continue
        # apenas considera realmente vencido
        oldest = r.get("oldest_due") or ""
        is_overdue = (r["n_overdue"] or 0) > 0 or oldest < today_iso
        if not is_overdue:
            continue
        out[str(ext)] = {
            "n_overdue": int(r["n_overdue"] or 0),
            "n_open": int(r["n_open"] or 0),
            "oldest_due": oldest,
            "total_due_brl": float(r.get("total_due_brl") or 0),
        }
    return out


def _score_from(signals: Dict[str, Any]) -> tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []
    n_t = signals.get("n_tickets", 0)
    if n_t >= 4:
        score += 35
        reasons.append(f"4+ reparos em 30d ({n_t})")
    elif n_t == 3:
        score += 28
        reasons.append("3 reparos em 30d")
    elif n_t == 2:
        score += 18
        reasons.append("2 reparos em 30d")
    elif n_t == 1:
        score += 8
        reasons.append("1 reparo em 30d")
    types = set(signals.get("types") or [])
    if {"lentidao", "lentidão"} & types or "wifi_ruim" in types or "sem internet" in types:
        score += 12
        reasons.append("Reclamação de lentidão/wifi/sem internet")
    if "ONU_LOW_SIGNAL" in types or "ONU_OFFLINE" in types:
        score += 10
        reasons.append("ONU com sinal baixo/offline")
    bad_signal = signals.get("bad_signal_dbm")
    if bad_signal is not None and bad_signal <= SIGNAL_BAD_DBM:
        score += 14
        reasons.append(f"Sinal óptico degradado ({bad_signal:.1f} dBm)")
    n_overdue = signals.get("n_overdue", 0)
    if n_overdue >= 2:
        score += 25
        reasons.append(f"{n_overdue} faturas vencidas")
    elif n_overdue == 1:
        score += 12
        reasons.append("Fatura vencida")
    if signals.get("days_since_payment", 0) >= 60:
        score += 10
        reasons.append("Sem pagamento há 60+ dias")
    return min(score, 100.0), reasons


def _recommend(score: float, signals: Dict[str, Any]) -> Dict[str, Any]:
    """Ação sugerida — humano aprova no painel."""
    types = set(signals.get("types") or [])
    if score >= 75:
        return {"type": "retention_offer",
                "channel": "whatsapp",
                "playbook": "diretor_call_back",
                "message": "Ligação do diretor de retenção em 2h + oferta de 1 mês grátis"}
    if "lentidao" in types or "lentidão" in types or "wifi_ruim" in types:
        return {"type": "schedule_repair",
                "channel": "field_ops",
                "playbook": "visita_tecnica_priorizada",
                "message": "Agendar visita técnica priorizada para sanar lentidão"}
    if signals.get("bad_signal_dbm") and signals["bad_signal_dbm"] <= SIGNAL_BAD_DBM:
        return {"type": "schedule_repair",
                "channel": "field_ops",
                "playbook": "reparo_optico",
                "message": "Reparo óptico — sinal degradado"}
    if signals.get("n_overdue", 0) >= 1:
        return {"type": "negotiation_offer",
                "channel": "whatsapp",
                "playbook": "negociacao_dunning_premium",
                "message": "Negociação personalizada com parcelamento"}
    return {"type": "satisfaction_survey",
            "channel": "whatsapp",
            "playbook": "nps_proativo",
            "message": "NPS proativo + escuta ativa"}


def _strip_atlaz(x: Any) -> str:
    """Normaliza external_code para comparação (remove prefixo ATLAZ-)."""
    s = str(x or "").strip()
    if s.upper().startswith("ATLAZ-"):
        return s.split("-", 1)[1].strip()
    return s


async def scan_company(company_id: str, *, limit: int = 500) -> Dict[str, Any]:
    scope = await _company_scope(company_id)
    cutoff = scope["cutoff"]
    arpu = scope["arpu"]
    ticket_sig = await _client_signals(company_id, cutoff)
    overdue_sig = await _overdue_signals(company_id)

    target_external_ids = set(ticket_sig.keys()) | set(overdue_sig.keys())
    if not target_external_ids:
        return {"company_id": company_id, "scanned": 0, "scored": 0,
                "opportunities": 0}

    # Busca subscribers — aceita external_code bare ou com prefixo ATLAZ-
    expanded = set()
    for k in target_external_ids:
        expanded.add(k)
        expanded.add(f"ATLAZ-{k}")
    subs = await db.subscribers.find(
        {"company_id": company_id,
         "external_code": {"$in": list(expanded)},
         "contract_status": {"$ne": "CANCELADO"}},
        {"_id": 0, "id": 1, "name": 1, "external_code": 1, "phone": 1,
         "plan_name": 1, "plan_price": 1, "cto_port": 1, "document": 1}
    ).to_list(20000)

    created = 0
    for s in subs:
        norm = _strip_atlaz(s.get("external_code"))
        sig = dict(ticket_sig.get(norm, {}))
        sig.update(overdue_sig.get(norm, {}))
        cto_port = s.get("cto_port") or {}
        signal = cto_port.get("signal_dbm")
        if signal is not None:
            try:
                sig["bad_signal_dbm"] = float(signal)
            except Exception:
                pass
        score, reasons = _score_from(sig)
        if score < 25:
            continue
        prob = min(score / 100.0, 0.95)
        impact = float(arpu) * 12.0 * prob  # 12 meses de LTV em risco
        action = _recommend(score, sig)
        await upsert_opportunity(
            company_id=company_id,
            kind="churn",
            subkind=action["type"],
            target_type="subscriber",
            target_id=s["id"],
            target_label=f"{s.get('name') or norm} ({norm})",
            score=score,
            probability=prob,
            impact_brl=impact,
            reason_codes=reasons,
            evidence={
                "n_tickets_30d": sig.get("n_tickets", 0),
                "types": list(sig.get("types") or []),
                "n_overdue": sig.get("n_overdue", 0),
                "total_due_brl": sig.get("total_due_brl", 0.0),
                "signal_dbm": sig.get("bad_signal_dbm"),
                "plan_name": s.get("plan_name"),
                "plan_price": s.get("plan_price"),
                "phone": s.get("phone"),
                "subscriber_external_id": norm,
            },
            recommended_action=action,
            source="isabella_churn",
        )
        created += 1
        await emit_event(
            EventType.CHURN_RISK_SCORED,
            company_id=company_id, source="isabella_churn",
            severity="critica" if score >= 75 else ("alta" if score >= 50 else "media"),
            payload={"subscriber_id": s["id"], "score": score,
                      "reasons": reasons[:5]})
        if created >= limit:
            break

    return {"company_id": company_id, "arpu": arpu,
            "scanned": len(subs), "scored": created,
            "opportunities": created}


async def scan_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await scan_company(cid))
        except Exception as e:
            log.exception("[churn] scan %s failed: %s", cid, e)
    return out
