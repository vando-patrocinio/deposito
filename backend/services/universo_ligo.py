"""UNIVERSO LIGO — score de relacionamento e níveis.

Níveis (do menor ao maior):
  1. Explorador      (0–99)
  2. Cometa          (100–249)
  3. Órbita          (250–499)
  4. Estelar         (500–799)
  5. Galáxia Ouro    (800–1199)
  6. Universo Ligo   (1200+)

Score (somente dados REAIS):
  tempo_casa_meses        × 5 (cap 60 meses → 300pts)
  faturas_pagas_em_dia    × 2 (cap 60 faturas → 120pts)
  nps_ultimo              × 5 (0..10 → 0..50pts)
  indicacoes_convertidas  × 100 (cap 3 → 300pts)
  produtos_adicionais     × 50  (PlayHub, IP fixo, 5G, WiFi+)
  sem_inadimplencia_ativa = +50
  inadimplencia_ativa     = -100
  retencao_bem_sucedida   × 80 (cap 3 → 240pts)
  incidente_sem_cancelamento × 20

Cliente é identificado por:
  • subscriber.id
  • phone (E.164 ou local)
  • document
  • external_code (atlaz)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.event_bus import EventType, emit_event

log = logging.getLogger("ponto.universo_ligo")

LEVELS = [
    {"id": 1, "key": "explorador",   "name": "Explorador",     "min": 0,    "max": 99},
    {"id": 2, "key": "cometa",       "name": "Cometa",         "min": 100,  "max": 249},
    {"id": 3, "key": "orbita",       "name": "Órbita",         "min": 250,  "max": 499},
    {"id": 4, "key": "estelar",      "name": "Estelar",        "min": 500,  "max": 799},
    {"id": 5, "key": "galaxia_ouro", "name": "Galáxia Ouro",   "min": 800,  "max": 1199},
    {"id": 6, "key": "universo_ligo", "name": "Universo Ligo", "min": 1200, "max": 999999},
]


def _now():
    return datetime.now(timezone.utc)


def _level_for(score: float) -> Dict[str, Any]:
    for lvl in LEVELS:
        if lvl["min"] <= score <= lvl["max"]:
            return lvl
    return LEVELS[-1]


def _normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    # 55 + DDD + 9digits → mantém
    return digits[-11:] if len(digits) >= 11 else digits


async def ensure_indexes() -> None:
    try:
        await db.universo_ligo_scores.create_index(
            [("company_id", 1), ("subscriber_id", 1)], unique=True)
        await db.universo_ligo_scores.create_index(
            [("company_id", 1), ("level_id", -1), ("score", -1)])
        await db.universo_ligo_history.create_index(
            [("subscriber_id", 1), ("changed_at", -1)])
    except Exception as e:  # noqa
        log.warning("[universo] indexes: %s", e)


async def identify(*, company_id: Optional[str] = None,
                     phone: Optional[str] = None,
                     subscriber_id: Optional[str] = None,
                     document: Optional[str] = None,
                     external_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Identifica um assinante por qualquer um dos canais."""
    q: Dict[str, Any] = {}
    if subscriber_id:
        q["id"] = subscriber_id
    elif external_code:
        q["external_code"] = {"$in": [external_code, f"ATLAZ-{external_code}"]}
    elif document:
        q["document"] = re.sub(r"\D", "", document)
    elif phone:
        norm = _normalize_phone(phone)
        # busca por phone completo OU pelos últimos 11 dígitos
        q["$or"] = [{"phone": phone}, {"phone": {"$regex": norm + "$"}}]
    else:
        return None
    if company_id:
        q["company_id"] = company_id
    sub = await db.subscribers.find_one(q, {"_id": 0})
    if not sub:
        return None
    score = await get_or_compute(sub["company_id"], sub["id"])
    sub["universo_ligo"] = score
    return sub


async def _activation_months(sub: Dict[str, Any]) -> int:
    act = sub.get("activation_date") or sub.get("created_at")
    if not act:
        return 0
    try:
        dt = datetime.fromisoformat(act.replace("Z", "+00:00"))
    except Exception:
        return 0
    delta = _now() - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else _now() - dt
    return max(0, int(delta.days / 30))


async def _paid_in_time(company_id: str, ext_id: str) -> int:
    """Faturas pagas com paid_date <= due_date."""
    pipe = [
        {"$match": {"company_id": company_id,
                      "subscriber_external_id": ext_id,
                      "status": "paid"}},
        {"$project": {
            "in_time": {"$cond": [
                {"$lte": ["$paid_date", "$due_date"]}, 1, 0]}}},
        {"$group": {"_id": None, "n": {"$sum": "$in_time"}}},
    ]
    rows = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    return int(rows[0]["n"]) if rows else 0


async def _active_overdue(company_id: str, ext_id: str) -> int:
    today_iso = _now().date().isoformat()
    return await db.subscriber_invoices.count_documents(
        {"company_id": company_id,
         "subscriber_external_id": ext_id,
         "status": {"$in": ["open", "overdue"]},
         "due_date": {"$lt": today_iso}})


async def _referrals_converted(company_id: str,
                                  sub: Dict[str, Any]) -> int:
    """Indicações que viraram cliente. Olha indicacao_leads onde
    `referrer_subscriber_id` == sub.id e status convertido."""
    return await db.indicacao_leads.count_documents(
        {"company_id": company_id,
         "$or": [
             {"referrer_subscriber_id": sub["id"]},
             {"referrer_phone": sub.get("phone")},
             {"referrer_document": sub.get("document")},
         ],
         "status": {"$in": ["convertido", "converted", "ativo"]}})


async def _last_nps(company_id: str, sub_id: str) -> Optional[int]:
    doc = await db.nps_responses.find_one(
        {"company_id": company_id, "subscriber_id": sub_id},
        {"_id": 0, "score": 1}, sort=[("created_at", -1)])
    if doc and doc.get("score") is not None:
        return int(doc["score"])
    return None


async def _additional_products(sub: Dict[str, Any]) -> int:
    products = sub.get("addons") or sub.get("products") or []
    return len(products) if isinstance(products, list) else 0


async def _retention_wins(company_id: str, sub_id: str) -> int:
    """Outcomes de churn com success_rate=success contra este assinante."""
    return await db.isabella_outcomes.count_documents(
        {"company_id": company_id, "kind": "churn",
         "target_id": sub_id, "result": "success"})


async def compute(company_id: str, subscriber_id: str) -> Dict[str, Any]:
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": subscriber_id}, {"_id": 0})
    if not sub:
        raise ValueError(f"subscriber {subscriber_id} not found")
    ext_id = (sub.get("external_code") or "").replace("ATLAZ-", "")
    months = await _activation_months(sub)
    paid_in_time = await _paid_in_time(company_id, ext_id) if ext_id else 0
    nps_last = await _last_nps(company_id, sub["id"])
    referrals = await _referrals_converted(company_id, sub)
    addons = await _additional_products(sub)
    overdue = await _active_overdue(company_id, ext_id) if ext_id else 0
    retention = await _retention_wins(company_id, sub["id"])

    pts = {
        "tempo_casa": min(months, 60) * 5,
        "pagamentos_em_dia": min(paid_in_time, 60) * 2,
        "nps_score": ((nps_last or 0) * 5) if nps_last is not None else 0,
        "indicacoes": min(referrals, 3) * 100,
        "produtos_adicionais": addons * 50,
        "inadimplencia": -100 if overdue >= 1 else 50,
        "retencao_wins": min(retention, 3) * 80,
    }
    score = float(sum(pts.values()))
    score = max(0.0, score)  # piso
    lvl = _level_for(score)
    return {
        "company_id": company_id, "subscriber_id": subscriber_id,
        "subscriber_name": sub.get("name"),
        "subscriber_phone": sub.get("phone"),
        "score": round(score, 1),
        "level_id": lvl["id"], "level_key": lvl["key"],
        "level_name": lvl["name"],
        "components": pts,
        "factors": {
            "tempo_casa_meses": months,
            "pagamentos_em_dia": paid_in_time,
            "nps_ultimo": nps_last,
            "indicacoes_convertidas": referrals,
            "produtos_adicionais": addons,
            "inadimplencia_ativa": overdue,
            "retencoes_bem_sucedidas": retention,
        },
        "computed_at": _now().isoformat(),
    }


async def get_or_compute(company_id: str,
                            subscriber_id: str,
                            *, force: bool = False) -> Dict[str, Any]:
    """Lê do cache (`universo_ligo_scores`) ou recalcula se velho/força."""
    cached = await db.universo_ligo_scores.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id},
        {"_id": 0})
    fresh = False
    if cached and not force:
        try:
            dt = datetime.fromisoformat(
                cached["computed_at"].replace("Z", "+00:00"))
            if (_now() - dt) < timedelta(hours=24):
                return cached
        except Exception:
            pass
    fresh = True
    computed = await compute(company_id, subscriber_id)
    prev_level = (cached or {}).get("level_id")
    await db.universo_ligo_scores.update_one(
        {"company_id": company_id, "subscriber_id": subscriber_id},
        {"$set": computed}, upsert=True)
    if prev_level and prev_level != computed["level_id"]:
        await db.universo_ligo_history.insert_one({
            "id": f"ulhist-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "from_level_id": prev_level,
            "to_level_id": computed["level_id"],
            "from_level_name": next(
                (l["name"] for l in LEVELS if l["id"] == prev_level), ""),
            "to_level_name": computed["level_name"],
            "score": computed["score"],
            "changed_at": _now().isoformat(),
        })
        await emit_event(
            EventType.UNIVERSO_LEVEL_CHANGED,
            company_id=company_id, source="universo_ligo",
            severity="alta",
            payload={"subscriber_id": subscriber_id,
                      "from_level_id": prev_level,
                      "to_level_id": computed["level_id"],
                      "score": computed["score"]})
    if fresh:
        await emit_event(
            EventType.UNIVERSO_SCORE_UPDATED,
            company_id=company_id, source="universo_ligo",
            severity="baixa",
            payload={"subscriber_id": subscriber_id,
                      "score": computed["score"],
                      "level_id": computed["level_id"]})
    return computed


async def panel_summary(company_id: str) -> Dict[str, Any]:
    pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {
            "_id": "$level_id",
            "n": {"$sum": 1},
            "avg_score": {"$avg": "$score"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.universo_ligo_scores.aggregate(pipe).to_list(20)
    by_level: List[Dict[str, Any]] = []
    total = 0
    score_sum = 0.0
    for r in rows:
        lvl = next((l for l in LEVELS if l["id"] == r["_id"]),
                   {"name": "?", "key": "?"})
        n = int(r["n"] or 0)
        by_level.append({
            "level_id": r["_id"],
            "level_key": lvl["key"],
            "level_name": lvl["name"],
            "n_subscribers": n,
            "avg_score": round(float(r.get("avg_score") or 0), 1),
        })
        total += n
        score_sum += float(r.get("avg_score") or 0) * n
    return {
        "company_id": company_id,
        "n_total": total,
        "avg_score": round(score_sum / max(total, 1), 1),
        "levels": LEVELS,
        "distribution": by_level,
    }


async def refresh_all(company_id: str, *, limit: int = 5000) -> Dict[str, Any]:
    cur = db.subscribers.find(
        {"company_id": company_id,
         "contract_status": {"$nin": ["CANCELADO", "cancelado"]}},
        {"_id": 0, "id": 1}).limit(limit)
    n = 0
    n_level_changes = 0
    async for s in cur:
        prev = await db.universo_ligo_scores.find_one(
            {"company_id": company_id, "subscriber_id": s["id"]},
            {"_id": 0, "level_id": 1})
        prev_lvl = (prev or {}).get("level_id")
        try:
            r = await get_or_compute(company_id, s["id"], force=True)
            if prev_lvl and prev_lvl != r["level_id"]:
                n_level_changes += 1
            n += 1
        except Exception as e:
            log.warning("[universo] refresh %s: %s", s["id"], e)
    return {"company_id": company_id, "refreshed": n,
            "level_changes": n_level_changes}
