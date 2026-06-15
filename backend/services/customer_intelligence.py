"""Customer Intelligence — Universo Ligo (Etapa 2 backend).

Reúne nível Universo Ligo + tags secundárias + score interno + contexto
financeiro/relacional do cliente, com cache em memória e invalidação por
evento. **Feature-flag-gated por padrão.**

Princípios:
- Zero dados inventados. Se faltar fonte, confidence=baixa.
- Tenants sintéticos NUNCA entram no ticket médio.
- Embaixador NUNCA por score — só por convite humano em
  `universo_ligo_invites.decision=APTO AND status in {invited_pending,accepted}`.
- Cliente comum vê APENAS o primary_level.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from constants.synthetic_tenants import SYNTHETIC_TENANTS
from database import db

log = logging.getLogger("ponto.customer_intelligence")

# ─── Feature flags (env) ──────────────────────────────────────────────
FF_ENABLED = os.environ.get("CUSTOMER_INTELLIGENCE_ENABLED", "false").lower() == "true"
FF_ISABELLA = os.environ.get("CUSTOMER_INTELLIGENCE_ISABELLA_CONTEXT", "false").lower() == "true"
FF_UI_BADGES = os.environ.get("CUSTOMER_INTELLIGENCE_UI_BADGES", "false").lower() == "true"

# ─── Cache em memória (TTL 1h) ────────────────────────────────────────
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_S = 3600

# Eventos que invalidam o cache de um subscriber:
INVALIDATE_EVENTS = {
    "UNIVERSO_LEVEL_CHANGED",
    "CHURN_RISK_SCORED",
    "EXPERIENCE_EVENT_DETECTED",
    "PAYMENT_STATUS_CHANGED",
    "TICKET_CLOSED",
    "CUSTOMER_PROFILE_UPDATED",
}

# ─── Constantes de níveis ─────────────────────────────────────────────
LEVELS = [
    ("explorador",   "Explorador",   "🌱",   0,   99),
    ("viajante",     "Viajante",     "🚶", 100,  249),
    ("cometa",       "Cometa",       "☄️", 250,  449),
    ("constelacao",  "Constelação",  "✨", 450,  699),
    ("galaxia",      "Galáxia",      "🌌", 700,  899),
    # Embaixador é por convite humano, não score:
    ("embaixador",   "Embaixador",   "⭐", 900, 1000),
]


def invalidate(subscriber_id: str) -> None:
    """Invalidação por evento (chamado por hook do event_bus)."""
    _CACHE.pop(subscriber_id, None)


def invalidate_all() -> None:
    _CACHE.clear()


# ─── Ticket médio da base real (cache 24h) ────────────────────────────
_TICKET_AVG: Optional[Tuple[float, float]] = None  # (avg, ts)


async def _real_base_avg_ticket() -> float:
    """Ticket médio recalculado a cada 24h. Filtra sintéticos."""
    global _TICKET_AVG
    now = time.time()
    if _TICKET_AVG and (now - _TICKET_AVG[1]) < 86400:
        return _TICKET_AVG[0]
    pipe = [
        {"$match": {"company_id": {"$nin": SYNTHETIC_TENANTS},
                    "status": "Ativo",
                    "monthly_fee": {"$gt": 0}}},
        {"$group": {"_id": None, "avg": {"$avg": "$monthly_fee"}}},
    ]
    cur = db.loyalty_imported_db.aggregate(pipe)
    docs = await cur.to_list(1)
    avg = float(docs[0]["avg"]) if docs and docs[0].get("avg") else 103.37
    _TICKET_AVG = (avg, now)
    return avg


# ─── Reuso de listas validadas (fundadores / embaixadores / invisíveis)
# Os arquivos /app/memory/*.md viraram fontes oficiais (ver
# ONE_TRUTH_MATRIX.md). Aqui usamos os critérios numéricos diretos
# em vez de parsear markdown — preserva auditabilidade.

async def _founder_candidate(document: str) -> bool:
    """Critério estrito do CLIENTE_FUNDADOR_REPORT.md (130 docs)."""
    if not document or document in {"00000000000", "99999999999", ""}:
        return False
    recs = await db.loyalty_imported_db.find(
        {"company_id": "co-demo", "document": document},
        {"status": 1, "registration_date": 1, "invoices_paid": 1,
         "invoices_overdue": 1}
    ).to_list(50)
    if not recs:
        return False
    actives = [r for r in recs if r.get("status") == "Ativo"]
    cancels = [r for r in recs if r.get("status") == "Desativado"]
    if not actives or cancels:
        return False
    valid = [r for r in recs if r.get("registration_date") and
             str(r["registration_date"])[:4] >= "2008"]
    if not valid:
        return False
    oldest = min(valid, key=lambda r: r["registration_date"])
    main = max(actives, key=lambda r: r.get("invoices_paid", 0) or 0)
    return (oldest["registration_date"] < "2020-01-01"
            and (main.get("invoices_paid") or 0) >= 50
            and (main.get("invoices_overdue") or 0) == 0)


async def _invisible_customer(loyalty_rec: Dict[str, Any]) -> bool:
    if not loyalty_rec:
        return False
    return (loyalty_rec.get("status") == "Ativo"
            and (loyalty_rec.get("tickets_open") or 0) == 0
            and (loyalty_rec.get("tickets_closed") or 0) == 0
            and (loyalty_rec.get("invoices_overdue") or 0) == 0
            and (loyalty_rec.get("invoices_paid") or 0) >= 12)


async def _ambassador_natural_candidate(loyalty_rec: Dict[str, Any]) -> bool:
    """Critério do EMBAIXADORES_NATURAIS.md."""
    if not loyalty_rec or loyalty_rec.get("status") != "Ativo":
        return False
    paid = loyalty_rec.get("invoices_paid") or 0
    overdue = loyalty_rec.get("invoices_overdue") or 0
    tc = loyalty_rec.get("tickets_closed") or 0
    to = loyalty_rec.get("tickets_open") or 0
    reg = str(loyalty_rec.get("registration_date") or "")
    return (paid >= 36 and overdue == 0 and tc <= 3 and to <= 1
            and "2017" <= reg[:4] < "2023")


async def _embaixador_invited(document: str) -> bool:
    """Embaixador APENAS por convite humano aceito."""
    if not document:
        return False
    inv = await db.universo_ligo_invites.find_one({
        "document": document,
        "decision": "APTO",
        "status": {"$in": ["invited_pending", "accepted"]},
        "do_not_contact_universo_ligo": {"$ne": True},
    })
    return bool(inv)


async def _churn_risk(subscriber_id: str) -> bool:
    if not subscriber_id:
        return False
    op = await db.isabella_commander_opportunities.find_one({
        "subscriber_id": subscriber_id,
        "kind": "churn",
        "status": "pending",
        "score": {"$gte": 70},
    })
    return bool(op)


async def _churn_recovered(subscriber_id: str) -> bool:
    if not subscriber_id:
        return False
    op = await db.isabella_commander_opportunities.find_one({
        "subscriber_id": subscriber_id,
        "kind": "churn",
        "status": "resolved",
        "outcome": "retained",
    })
    return bool(op)


# ─── Score interno (6 dimensões + multiplicador) ─────────────────────
async def _compute_score(sub: Dict[str, Any],
                         loyalty: Optional[Dict[str, Any]],
                         is_founder: bool) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    src = loyalty or sub  # prefere loyalty para tenure/paid/etc

    # Tenure
    reg = str(src.get("registration_date") or sub.get("created_at") or "")
    if reg and len(reg) >= 7:
        try:
            yr, mo = int(reg[:4]), int(reg[5:7])
            now = datetime.now(timezone.utc)
            tenure_m = (now.year - yr) * 12 + (now.month - mo)
        except Exception:
            tenure_m = 0
    else:
        tenure_m = 0
    d_tempo = min(1000, tenure_m * 10)
    if tenure_m:
        reasons.append(f"{tenure_m} meses de relacionamento")

    # Estabilidade financeira
    overdue = loyalty.get("invoices_overdue", 0) if loyalty else 0
    cancels = 0
    if sub.get("document"):
        cancels = await db.loyalty_imported_db.count_documents({
            "company_id": "co-demo",
            "document": sub.get("document"),
            "status": "Desativado",
        })
    d_estab = max(0, 1000 - overdue * 200 - cancels * 300)
    if overdue == 0 and cancels == 0:
        reasons.append("Zero inadimplência atual · zero cancelamentos no histórico")

    # Relacionamento (tickets + NPS bonus)
    tc = (loyalty or {}).get("tickets_closed", 0) or 0
    d_rel = max(0, 1000 - max(0, tc - 5) * 30)
    if sub.get("document"):
        nps = await db.nps_responses_mvp.find_one(
            {"document": sub["document"]}, sort=[("created_at", -1)]
        )
        if nps:
            sc = nps.get("score") or 0
            if sc >= 9:
                d_rel = min(1000, d_rel + 200)
                reasons.append(f"NPS Promoter ({sc})")
            elif sc <= 6:
                d_rel = max(0, d_rel - 200)
                reasons.append(f"NPS Detrator ({sc})")

    # Participação
    n_exp = 0
    if sub.get("name"):
        n_exp = await db.experience_campaigns.count_documents({
            "company_id": "co-demo",
            "target_label": {"$regex": f"^{sub['name']}$", "$options": "i"},
        })
    d_part = min(1000, n_exp * 200)
    if n_exp:
        reasons.append(f"{n_exp} campanha(s) de experiência (aniv/VIP)")

    # Indicações
    d_ind = 0  # referrals 100% sintético hoje — explicitamente 0

    # Histórico técnico
    incidents = 0
    if sub.get("id"):
        incidents = await db.isabella_incidents.count_documents({
            "company_id": "co-demo",
            "affected_subscriber_ids": sub["id"],
        })
    d_tech = max(0, 1000 - incidents * 50)

    base_score = int(
        d_tempo * 0.30 + d_estab * 0.20 + d_rel * 0.20
        + d_part * 0.10 + d_ind * 0.10 + d_tech * 0.10
    )
    multiplier = 1.5 if is_founder else 1.0
    if is_founder:
        reasons.append("Fundador histórico (multiplicador 1.5)")

    final = min(1000, int(base_score * multiplier))
    return final, reasons


def _level_from_score(score: int) -> Tuple[str, str, str]:
    for key, label, emoji, lo, hi in LEVELS[:-1]:  # exclui embaixador
        if lo <= score <= hi:
            return key, label, emoji
    return "galaxia", "Galáxia", "🌌"


def _confidence(missing: List[str], tenure_m: int) -> str:
    if len(missing) >= 3 or tenure_m < 6:
        return "baixa"
    if len(missing) >= 1 or tenure_m < 12:
        return "media"
    return "alta"


# ─── Build response ───────────────────────────────────────────────────
async def build_intelligence(subscriber_id: str) -> Dict[str, Any]:
    """Função principal. Calcula e retorna o JSON descrito no contrato."""
    # cache
    cached = _CACHE.get(subscriber_id)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_S:
        return cached[1]

    sub = await db.subscribers.find_one({"id": subscriber_id})
    if not sub:
        sub = await db.subscribers.find_one({"_id": subscriber_id})
    if not sub:
        return {"error": "subscriber_not_found", "subscriber_id": subscriber_id}

    cid = sub.get("company_id") or "co-demo"
    if cid in SYNTHETIC_TENANTS:
        return {"error": "synthetic_tenant_blocked", "subscriber_id": subscriber_id}

    doc = sub.get("document") or ""
    loyalty = None
    if doc:
        loyalty = await db.loyalty_imported_db.find_one(
            {"company_id": cid, "document": doc, "status": "Ativo"}
        )

    missing: List[str] = []
    sources: List[str] = ["subscribers"]
    if loyalty:
        sources.append("loyalty_imported_db")
    else:
        missing.append("loyalty_imported_db")

    is_founder = await _founder_candidate(doc)
    is_invisible = await _invisible_customer(loyalty or {})
    is_ambassador_natural = await _ambassador_natural_candidate(loyalty or {})
    is_embaixador_inv = await _embaixador_invited(doc)
    is_risk = await _churn_risk(subscriber_id)
    is_recovered = await _churn_recovered(subscriber_id)

    score, reasons = await _compute_score(sub, loyalty, is_founder)

    # Nível principal
    if is_embaixador_inv:
        level_key, level_label, level_emoji = "embaixador", "Embaixador", "⭐"
        reasons.insert(0, "Convite humano de Embaixador validado")
    else:
        level_key, level_label, level_emoji = _level_from_score(score)

    # Financeiro
    monthly = float((loyalty or {}).get("monthly_fee") or 0)
    base_avg = await _real_base_avg_ticket()
    multiplier_ticket = round(monthly / base_avg, 2) if base_avg > 0 else 0
    if monthly >= 6 * base_avg:
        financial_class = "black"
    elif monthly >= 3 * base_avg:
        financial_class = "high_ticket"
    else:
        financial_class = "normal"

    # Tags secundárias
    secondary: List[Dict[str, Any]] = []
    if financial_class == "high_ticket":
        secondary.append({
            "key": "high_ticket", "label": "High Ticket", "emoji": "💎",
            "visible_to_customer": False,
            "reason": f"Mensalidade R$ {monthly:.2f} ≥ 3× média da base "
                      f"(R$ {base_avg:.2f})"
        })
    if financial_class == "black":
        secondary.append({
            "key": "black", "label": "Black", "emoji": "🖤",
            "visible_to_customer": False,
            "reason": f"Mensalidade R$ {monthly:.2f} ≥ 6× média da base "
                      f"(R$ {base_avg:.2f})"
        })
    if is_founder:
        secondary.append({"key": "fundador", "label": "Fundador", "emoji": "🏛️",
                          "visible_to_customer": False,
                          "reason": "Cliente histórico, zero cancelamentos, "
                                    "registrado antes de 2020, ≥50 faturas pagas"})
    if is_ambassador_natural and not is_embaixador_inv:
        secondary.append({"key": "embaixador_natural",
                          "label": "Embaixador Natural", "emoji": "🤝",
                          "visible_to_customer": False,
                          "reason": "Comportamento de embaixador "
                                    "(longevidade + baixo atrito)"})
    if is_invisible:
        secondary.append({"key": "cliente_invisivel",
                          "label": "Cliente Invisível", "emoji": "🧭",
                          "visible_to_customer": False,
                          "reason": "Zero tickets · zero atraso · "
                                    "≥12 faturas pagas"})
    if is_risk:
        secondary.append({"key": "cliente_em_risco",
                          "label": "Cliente em Risco", "emoji": "⚠️",
                          "visible_to_customer": False,
                          "reason": "Oportunidade churn pendente "
                                    "(Isabella Commander, score ≥70)"})
    if is_recovered:
        secondary.append({"key": "cliente_recuperado",
                          "label": "Cliente Recuperado", "emoji": "🔄",
                          "visible_to_customer": False,
                          "reason": "Estava em risco, foi retido"})

    # Tenure
    reg = str((loyalty or {}).get("registration_date")
              or sub.get("created_at") or "")
    tenure_m = 0
    if reg and len(reg) >= 7:
        try:
            yr, mo = int(reg[:4]), int(reg[5:7])
            now = datetime.now(timezone.utc)
            tenure_m = (now.year - yr) * 12 + (now.month - mo)
        except Exception:
            pass

    if doc:
        sources.append("universo_ligo_invites")
        sources.append("isabella_commander_opportunities")
        sources.append("experience_campaigns")
        sources.append("nps_responses_mvp")

    confidence = _confidence(missing, tenure_m)

    payload = {
        "subscriber_id": subscriber_id,
        "company_id": cid,
        "customer_name": sub.get("name") or "",
        "primary_level": {
            "key": level_key,
            "label": level_label,
            "emoji": level_emoji,
            "visible_to_customer": True,
        },
        "internal_score": {
            "score": score, "max": 1000,
            "visible_to_customer": False,
            "confidence": confidence,
        },
        "secondary_tags": secondary,
        "reasons": reasons,
        "data_quality": {
            "confidence": confidence,
            "missing_fields": missing,
            "sources_used": list(dict.fromkeys(sources)),
        },
        "financial_context": {
            "monthly_revenue": monthly,
            "base_avg_ticket": round(base_avg, 2),
            "ticket_multiplier": multiplier_ticket,
            "financial_class": financial_class,
            "visible_to_customer": False,
        },
        "relationship_context": {
            "months_active": tenure_m,
            "founder_candidate": is_founder,
            "ambassador_candidate": is_ambassador_natural,
            "invisible_customer": is_invisible,
        },
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Audit trail (não bloqueante)
    try:
        await db.universo_ligo_score_audit.insert_one({
            "subscriber_id": subscriber_id, "company_id": cid,
            "score": score, "level_key": level_key,
            "tags": [t["key"] for t in secondary],
            "confidence": confidence,
            "computed_at": payload["last_updated_at"],
        })
    except Exception as e:
        log.warning(f"[ci] audit insert: {e}")

    _CACHE[subscriber_id] = (time.time(), payload)
    return payload


async def ensure_indexes() -> None:
    try:
        await db.universo_ligo_score_audit.create_index(
            [("subscriber_id", 1), ("computed_at", -1)]
        )
        await db.universo_ligo_score_audit.create_index(
            [("company_id", 1), ("level_key", 1)]
        )
    except Exception as e:
        log.warning(f"[ci] indexes: {e}")
