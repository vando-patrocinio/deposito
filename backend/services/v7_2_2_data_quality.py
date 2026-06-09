"""
v7_2_2_data_quality.py — V7.2.2 G2/G3 (Backfill puro de qualidade de dados)

Sem novas IAs/scores/twins/painéis. Apenas:
  G2: tickets.assigned_to ← cadeia documentada de fontes existentes
  G3: tickets.category ← normaliza tickets.type (INSTALL/REPAIR/WITHDRAW)

Idempotente. Não sobrescreve valor válido. Registra `source_backfill_*`
para auditoria.
"""
from __future__ import annotations
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from database import db

logger = logging.getLogger("v7_2_2")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

VALID_CATEGORIES = {"INSTALL", "REPAIR", "WITHDRAW"}


# ═══════════════════════════════════════════════════════════
# G3 — Normalização de tickets.type → category canônica
# ═══════════════════════════════════════════════════════════
_RX_INSTALL = re.compile(
    r"\b(instal(a(ç|c)?ão|acao|ar)?|ativa(ç|c)ao|nov[ao]\s+cliente"
    r"|implanta(ç|c)ao|viabilidade)", re.I)
_RX_WITHDRAW = re.compile(
    r"\b(retir(ada|ar)|recolhi|desinstal|cancelament|devolu"
    r"|withdraw)", re.I)
_RX_REPAIR = re.compile(
    r"\b(repar|manuten|sem\s+(sinal|internet)|lent(o|id)|wifi|conex"
    r"|los|power\s*fail|offline|queda|rompiment|outage|suporte"
    r"|preventiv|visita)", re.I)


def _normalize_to_category(value: Any) -> Optional[str]:
    """Retorna INSTALL/REPAIR/WITHDRAW ou None."""
    if not value:
        return None
    v = str(value).strip()
    if v.upper() in VALID_CATEGORIES:
        return v.upper()
    if _RX_INSTALL.search(v):
        return "INSTALL"
    if _RX_WITHDRAW.search(v):
        return "WITHDRAW"
    if _RX_REPAIR.search(v):
        return "REPAIR"
    return None


def _category_from_ticket(t: Dict[str, Any]) -> Optional[str]:
    """Cadeia de fontes (ordem documentada V7.2.2)."""
    # Fonte 1: tickets.type (já preenchido)
    c = _normalize_to_category(t.get("type"))
    if c:
        return c
    # Fonte 2: ai_triage.type
    triage = t.get("ai_triage") or {}
    if isinstance(triage, dict):
        c = _normalize_to_category(triage.get("type"))
        if c:
            return c
        # Fonte 3: ai_triage.tags (lista)
        tags = triage.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                c = _normalize_to_category(tag)
                if c:
                    return c
    # Fonte 4: admin_notes / outcome
    for fld in ("admin_notes", "outcome", "subject", "description"):
        c = _normalize_to_category(t.get(fld))
        if c:
            return c
    return None


# ═══════════════════════════════════════════════════════════
# G2 — assigned_to via cadeia documentada de fontes
# ═══════════════════════════════════════════════════════════
async def _resolve_assigned_via_chain(
    company_id: str, t: Dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """Retorna (assigned_to, source) seguindo a ordem V7.2.2."""
    tid = t.get("id")

    # Fonte 0: assigned_collaborator_id (já existe no schema)
    col = t.get("assigned_collaborator_id")
    if col:
        return col, "tickets.assigned_collaborator_id"

    # Fonte 1: client_equipment_history.captured_by (action≈install)
    if tid:
        ceh = await db.client_equipment_history.find_one(
            {"company_id": company_id, "ticket_id": tid,
             "captured_by": {"$nin": [None, ""]}})
        if ceh and ceh.get("captured_by"):
            return ceh["captured_by"], (
                "client_equipment_history.captured_by")

    # Fonte 2: ai_preventive_suggestions.tech_id (ticket_id link)
    if tid:
        aps = await db.ai_preventive_suggestions.find_one(
            {"company_id": company_id, "ticket_id": tid,
             "tech_id": {"$nin": [None, ""]}})
        if aps and aps.get("tech_id"):
            return aps["tech_id"], (
                "ai_preventive_suggestions.tech_id")

    # Fonte 3: ai_triage.suggested_collaborator_id
    triage = t.get("ai_triage") or {}
    if isinstance(triage, dict):
        sc = triage.get("suggested_collaborator_id")
        if sc:
            return sc, "ai_triage.suggested_collaborator_id"

    # Fonte 4: closed_by se prefixo "col-"
    cb = t.get("closed_by")
    if cb and str(cb).startswith("col-"):
        return cb, "tickets.closed_by"

    # Fonte 5: appointments.created_by_id (via subscriber/client_id)
    cid = t.get("client_id")
    if cid:
        ap = await db.appointments.find_one(
            {"company_id": company_id, "subscriber_id": cid,
             "created_by_id": {"$nin": [None, ""]}})
        if ap and ap.get("created_by_id"):
            cbid = ap["created_by_id"]
            if str(cbid).startswith("col-"):
                return cbid, "appointments.created_by_id"

    return None, "unresolved"


# ═══════════════════════════════════════════════════════════
# Backfill principal — G2 + G3 numa única passada
# ═══════════════════════════════════════════════════════════
async def backfill_quality(
    company_id: str, dry_run: bool = True,
) -> Dict[str, Any]:
    """G2+G3 idempotente. Roda sobre todos os tickets do company."""
    total = await db.tickets.count_documents(
        {"company_id": company_id})

    # Cobertura antes
    before_assigned = await db.tickets.count_documents(
        {"company_id": company_id,
         "assigned_to": {"$nin": [None, ""]}})
    before_category = await db.tickets.count_documents(
        {"company_id": company_id,
         "category": {"$in": list(VALID_CATEGORIES)}})

    assigned_fixed = category_fixed = 0
    assigned_source_counts: Dict[str, int] = {}
    category_source_counts: Dict[str, int] = {}
    category_distribution: Dict[str, int] = {
        "INSTALL": 0, "REPAIR": 0, "WITHDRAW": 0}

    async for t in db.tickets.find({"company_id": company_id}):
        updates: Dict[str, Any] = {}

        # G2 — assigned_to
        if not t.get("assigned_to"):
            assignee, source = await _resolve_assigned_via_chain(
                company_id, t)
            if assignee:
                updates["assigned_to"] = assignee
                updates["source_backfill_assigned_to"] = source
                updates["assigned_to_backfilled_at"] = ISO()
                assigned_source_counts[source] = (
                    assigned_source_counts.get(source, 0) + 1)
                assigned_fixed += 1

        # G3 — category
        cur_cat = t.get("category")
        if cur_cat not in VALID_CATEGORIES:
            cat = _category_from_ticket(t)
            if cat:
                # source = primeira fonte onde foi achado
                src = "tickets.type" if _normalize_to_category(
                    t.get("type")) == cat else "heuristic_blob"
                updates["category"] = cat
                updates["source_backfill_category"] = src
                updates["category_backfilled_at"] = ISO()
                category_source_counts[src] = (
                    category_source_counts.get(src, 0) + 1)
                category_fixed += 1
                category_distribution[cat] += 1

        if updates and not dry_run:
            await db.tickets.update_one(
                {"_id": t["_id"]}, {"$set": updates})

    # Cobertura depois (se dry_run, simula)
    if dry_run:
        after_assigned = before_assigned + assigned_fixed
        after_category = before_category + category_fixed
    else:
        after_assigned = await db.tickets.count_documents(
            {"company_id": company_id,
             "assigned_to": {"$nin": [None, ""]}})
        after_category = await db.tickets.count_documents(
            {"company_id": company_id,
             "category": {"$in": list(VALID_CATEGORIES)}})

    # Distribuição final (consolidada — não só os fixed)
    final_dist: Dict[str, int] = {}
    for cat in VALID_CATEGORIES:
        n = await db.tickets.count_documents(
            {"company_id": company_id, "category": cat})
        final_dist[cat] = n

    return {
        "company_id": company_id,
        "dry_run": dry_run,
        "tickets_total": total,
        "G2_assigned_to": {
            "coverage_before_n": before_assigned,
            "coverage_before_pct": round(
                before_assigned / max(total, 1) * 100, 2),
            "fixed_n": assigned_fixed,
            "coverage_after_n": after_assigned,
            "coverage_after_pct": round(
                after_assigned / max(total, 1) * 100, 2),
            "sources_used": assigned_source_counts,
        },
        "G3_category": {
            "coverage_before_n": before_category,
            "coverage_before_pct": round(
                before_category / max(total, 1) * 100, 2),
            "fixed_n": category_fixed,
            "coverage_after_n": after_category,
            "coverage_after_pct": round(
                after_category / max(total, 1) * 100, 2),
            "sources_used": category_source_counts,
            "distribution_in_fixed": category_distribution,
            "distribution_final": final_dist,
        },
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# V7.3 — Backfill tickets.opened_at (G4)
# ═══════════════════════════════════════════════════════════
async def backfill_opened_at(
    company_id: str, dry_run: bool = True,
) -> Dict[str, Any]:
    """G4 idempotente. Ordem documentada:
       A) tickets.created_at
       B) client_equipment_history.captured_at (por ticket_id)
       C) tickets.closed_at - tempo_médio_estimado (fallback)
    Persiste `opened_at_source`. Não sobrescreve valor válido."""
    total = await db.tickets.count_documents(
        {"company_id": company_id})
    before = await db.tickets.count_documents({
        "company_id": company_id,
        "opened_at": {"$nin": [None, ""]}})

    # Tempo médio estimado (fonte C) — calcula uma vez
    avg_dur_hours = 24.0  # default conservador
    cur = db.tickets.find({
        "company_id": company_id,
        "opened_at": {"$nin": [None, ""]},
        "closed_at": {"$nin": [None, ""]}},
        {"opened_at": 1, "closed_at": 1})
    durs = []
    async for t in cur:
        try:
            o = t["opened_at"]
            cl = t["closed_at"]
            if isinstance(o, str):
                o = datetime.fromisoformat(
                    o.replace("Z", "+00:00"))
            if isinstance(cl, str):
                cl = datetime.fromisoformat(
                    cl.replace("Z", "+00:00"))
            d = (cl - o).total_seconds() / 3600.0
            if 0 < d < 30 * 24:  # filtra outliers
                durs.append(d)
        except Exception:
            continue
    if durs:
        avg_dur_hours = sum(durs) / len(durs)

    fixed = 0
    sources: Dict[str, int] = {}

    async for t in db.tickets.find({
        "company_id": company_id,
        "$or": [{"opened_at": None},
                {"opened_at": ""},
                {"opened_at": {"$exists": False}}],
    }):
        new_val = None
        src = None

        # A) created_at
        if t.get("created_at"):
            new_val = t["created_at"]
            src = "tickets.created_at"

        # B) client_equipment_history.captured_at
        if not new_val and t.get("id"):
            ceh = await db.client_equipment_history.find_one(
                {"company_id": company_id, "ticket_id": t["id"],
                 "captured_at": {"$nin": [None, ""]}})
            if ceh and ceh.get("captured_at"):
                new_val = ceh["captured_at"]
                src = "client_equipment_history.captured_at"

        # C) closed_at - tempo médio
        if not new_val and t.get("closed_at"):
            try:
                cl = t["closed_at"]
                if isinstance(cl, str):
                    cl = datetime.fromisoformat(
                        cl.replace("Z", "+00:00"))
                estimated = cl - timedelta(hours=avg_dur_hours)
                new_val = estimated.isoformat()
                src = "closed_at_minus_avg_duration"
            except Exception:
                pass

        if not new_val:
            continue

        sources[src] = sources.get(src, 0) + 1
        fixed += 1
        if not dry_run:
            await db.tickets.update_one(
                {"_id": t["_id"]},
                {"$set": {
                    "opened_at": new_val,
                    "opened_at_source": src,
                    "opened_at_backfilled_at": ISO()}})

    if dry_run:
        after = before + fixed
    else:
        after = await db.tickets.count_documents({
            "company_id": company_id,
            "opened_at": {"$nin": [None, ""]}})

    return {
        "company_id": company_id,
        "dry_run": dry_run,
        "tickets_total": total,
        "coverage_before_n": before,
        "coverage_before_pct": round(
            before / max(total, 1) * 100, 2),
        "fixed_n": fixed,
        "coverage_after_n": after,
        "coverage_after_pct": round(
            after / max(total, 1) * 100, 2),
        "sources_used": sources,
        "avg_duration_hours_used": round(avg_dur_hours, 2),
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════

async def executive_audit(
    company_id: str, window_days: int = 30,
    resync_field_ops: bool = True,
) -> Dict[str, Any]:
    """Roda recálculo dos motores EXISTENTES e devolve relatório
    completo. NÃO cria novos cálculos.

    V7.3: resync_field_ops=True chama company_v6.sync_smart_field_ops
    antes do recálculo (necessário após backfill_opened_at)."""
    from services import company_v6, ops_v51

    sync_result = None
    if resync_field_ops:
        sync_result = await company_v6.sync_smart_field_ops(
            company_id, window_days=max(window_days, 365))

    # Recálculo: company score + smart field + technician
    score = await company_v6.autonomous_company_score(
        company_id, window_days)
    sk = await company_v6.smart_field_ops_kpis(
        company_id, window_days)
    try:
        techs = await ops_v51.technician_ranking(
            company_id, window_days=window_days, limit=50)
        tech_avg = (sum(t["score"] for t in techs)
                    / max(len(techs), 1)) if techs else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("technician_ranking fail: %r", e)
        techs = []
        tech_avg = 0

    return {
        "company_id": company_id,
        "window_days": window_days,
        "company_score": score.get("score"),
        "classification": score.get("classification"),
        "components": score.get("components"),
        "technician": {
            "ranking_size": len(techs),
            "avg_score": round(tech_avg, 2),
            "top_3": [{"id": t.get("technician_id"),
                       "score": t.get("score"),
                       "tickets": t.get("tickets_total")}
                      for t in techs[:3]],
        },
        "smart_field": sk,
        "sync_field_ops": sync_result,
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# V9 P2.3 — Telemetria de adoção dos campos V9 (Smart Field)
# ═══════════════════════════════════════════════════════════
async def smart_field_adoption(
    company_id: str,
) -> Dict[str, Any]:
    """Mede adoção real dos 4 campos derivados V9 P2 em
    tickets fechados. Sem alterar regras de negócio."""

    async def _coverage(category: str, field: str,
                        cutoff_iso: Optional[str] = None) -> Dict[str, Any]:
        match: Dict[str, Any] = {"company_id": company_id,
                                  "category": category,
                                  "status": "finalizada"}
        if cutoff_iso:
            match["closed_at"] = {"$gte": cutoff_iso}
        total = await db.tickets.count_documents(match)
        if field == "reopened_within_7d":
            filled = await db.tickets.count_documents({
                **match, field: {"$type": "bool"}})
        else:
            filled = await db.tickets.count_documents({
                **match, field: {"$nin": [None, ""]}})
        pct = round(filled / max(total, 1) * 100, 2)
        return {"total": total, "filled": filled, "pct": pct}

    now = datetime.now(timezone.utc)
    c7 = (now - timedelta(days=7)).isoformat()
    c30 = (now - timedelta(days=30)).isoformat()

    out: Dict[str, Any] = {"company_id": company_id,
                            "generated_at": ISO(),
                            "categories": {}}

    # REPAIR: resolution_kind
    out["categories"]["REPAIR"] = {
        "field": "resolution_kind",
        "7d": await _coverage("REPAIR", "resolution_kind", c7),
        "30d": await _coverage("REPAIR", "resolution_kind", c30),
        "total": await _coverage("REPAIR", "resolution_kind"),
    }
    # WITHDRAW: asset_recovered + signed_receipt
    out["categories"]["WITHDRAW"] = {
        "fields": ["asset_recovered", "signed_receipt"],
        "asset_recovered": {
            "7d": await _coverage("WITHDRAW", "asset_recovered", c7),
            "30d": await _coverage("WITHDRAW", "asset_recovered", c30),
            "total": await _coverage("WITHDRAW", "asset_recovered")},
        "signed_receipt": {
            "7d": await _coverage("WITHDRAW", "signed_receipt", c7),
            "30d": await _coverage("WITHDRAW", "signed_receipt", c30),
            "total": await _coverage("WITHDRAW", "signed_receipt")},
    }
    # REOPEN: reopened_within_7d (global, qualquer categoria)
    reopened_total = await db.tickets.count_documents({
        "company_id": company_id, "reopened": True})
    reopened_calculated = await db.tickets.count_documents({
        "company_id": company_id, "reopened": True,
        "reopened_within_7d": {"$type": "bool"}})
    out["reopen"] = {
        "field": "reopened_within_7d",
        "total_reopened": reopened_total,
        "with_calc": reopened_calculated,
        "pct": round(reopened_calculated / max(reopened_total, 1) * 100,
                     2),
    }

    # Ranking por técnico (assigned_to)
    pipe_tech = [
        {"$match": {"company_id": company_id,
                    "status": "finalizada",
                    "category": {"$in": ["REPAIR", "WITHDRAW"]}}},
        {"$group": {
            "_id": "$assigned_to",
            "total": {"$sum": 1},
            "with_repair_kind": {"$sum": {"$cond": [
                {"$and": [{"$eq": ["$category", "REPAIR"]},
                          {"$in": ["$resolution_kind",
                                    ["remote", "onsite"]]}]},
                1, 0]}},
            "with_asset": {"$sum": {"$cond": [
                {"$and": [{"$eq": ["$category", "WITHDRAW"]},
                          {"$eq": [{"$type": "$asset_recovered"},
                                    "bool"]}]},
                1, 0]}},
        }},
        {"$sort": {"total": -1}}, {"$limit": 20}]
    tech_rank = []
    async for r in db.tickets.aggregate(pipe_tech):
        if not r.get("_id"):
            continue
        filled = r["with_repair_kind"] + r["with_asset"]
        tech_rank.append({
            "technician_id": r["_id"],
            "total_finalizados": r["total"],
            "with_v9_fields": filled,
            "adoption_pct": round(
                filled / max(r["total"], 1) * 100, 2)})
    out["technician_ranking"] = tech_rank

    # Ranking por equipe (branch — proxy de equipe)
    pipe_branch = [
        {"$match": {"company_id": company_id,
                    "status": "finalizada",
                    "category": {"$in": ["REPAIR", "WITHDRAW"]}}},
        {"$lookup": {"from": "subscribers",
                      "localField": "client_id",
                      "foreignField": "id",
                      "as": "sub"}},
        {"$unwind": {"path": "$sub", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": {"$ifNull": ["$sub.branch", "sem_filial"]},
            "total": {"$sum": 1},
            "filled": {"$sum": {"$cond": [
                {"$or": [
                    {"$in": ["$resolution_kind",
                              ["remote", "onsite"]]},
                    {"$eq": [{"$type": "$asset_recovered"},
                              "bool"]}]},
                1, 0]}},
        }}, {"$sort": {"total": -1}}, {"$limit": 10}]
    branch_rank = []
    async for r in db.tickets.aggregate(pipe_branch):
        branch_rank.append({
            "branch": r["_id"],
            "total_finalizados": r["total"],
            "with_v9_fields": r["filled"],
            "adoption_pct": round(
                r["filled"] / max(r["total"], 1) * 100, 2)})
    out["branch_ranking"] = branch_rank

    # Lista (até 30) de tickets sem preenchimento
    pending: List[Dict[str, Any]] = []
    async for t in db.tickets.find({
        "company_id": company_id, "status": "finalizada",
        "$or": [
            {"category": "REPAIR",
             "resolution_kind": {"$nin": ["remote", "onsite"]}},
            {"category": "WITHDRAW",
             "asset_recovered": {"$not": {"$type": "bool"}}},
        ],
    }, {"id": 1, "category": 1, "assigned_to": 1,
        "closed_at": 1}).sort("closed_at", -1).limit(30):
        pending.append({
            "ticket_id": t.get("id"),
            "category": t.get("category"),
            "assigned_to": t.get("assigned_to"),
            "closed_at": t.get("closed_at")})
    out["pending_sample"] = pending
    out["pending_sample_size"] = len(pending)

    # Status vs metas
    main_rates = []
    for cat_key in ("REPAIR",):
        main_rates.append(
            out["categories"]["REPAIR"]["30d"]["pct"])
    main_rates.append(
        out["categories"]["WITHDRAW"]["asset_recovered"]["30d"]["pct"])
    main_rates.append(
        out["categories"]["WITHDRAW"]["signed_receipt"]["30d"]["pct"])
    avg = sum(main_rates) / max(len(main_rates), 1)
    out["adoption_avg_30d_pct"] = round(avg, 2)
    out["status"] = (
        "EXCELENTE" if avg >= 90 else
        "OK" if avg >= 70 else
        "INSUFICIENTE")
    out["meta_minima_70"] = avg >= 70
    out["meta_ideal_90"] = avg >= 90
    return out
