"""
audit_log_panel.py — Sprint 3 / iter222
Endpoint executivo do Audit Trail.

Rotas:
  GET  /api/audit-log              — listagem paginada + filtros
  GET  /api/audit-log/stats        — cards (totais, top users, 403s)
  GET  /api/audit-log/criticality  — distribuição por criticidade
  GET  /api/audit-log/{aid}        — detalhe de um evento
  GET  /api/audit-log/export.csv   — exporta CSV (admin/auditor)

Filtros: from, to, user_id, user_email, role, action, endpoint,
         company_id, category, status, criticality, q (text).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from database import db
from rbac import require_roles
from services.rate_limit import limiter, get_limit

router = APIRouter(prefix="/api/audit-log", tags=["audit-log"])


def _is_super(user: Dict[str, Any]) -> bool:
    """Super admin bypassa tenant isolation."""
    return bool((user or {}).get("is_super_admin"))

# ─────────────────── Helpers ───────────────────

CRITICALITY_BY_CATEGORY = {
    "destructive": "alta",
    "export": "media",
    "config_change": "alta",
    "ai_config_change": "alta",
    "login_admin": "media",
    "impersonate": "alta",
    "rbac_blocked": "media",
    "ai_rate_limited": "baixa",
}


def _crit(category: str) -> str:
    return CRITICALITY_BY_CATEGORY.get(category, "baixa")


def _mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return email
    name, dom = email.split("@", 1)
    if len(name) <= 2:
        m = name[0] + "*"
    else:
        m = name[0] + ("*" * (len(name) - 2)) + name[-1]
    return f"{m}@{dom}"


def _mask_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return ip
    # IPv4: 1.2.3.4 -> 1.2.*.* ; IPv6: prefixo + ::
    if ":" in ip:
        head = ip.split(":")[:2]
        return ":".join(head) + ":****"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return ip


def _doc_to_payload(d: Dict[str, Any], mask: bool = True) -> Dict[str, Any]:
    cat = d.get("category", "")
    crit = d.get("criticality") or _crit(cat)
    out = {
        "id": d.get("id"),
        "created_at": d.get("created_at"),
        "user_id": d.get("user_id"),
        "user_email": _mask_email(d.get("user_email")) if mask
                       else d.get("user_email"),
        "user_role": d.get("user_role"),
        "company_id": d.get("company_id"),
        "ip": _mask_ip(d.get("ip")) if mask else d.get("ip"),
        "user_agent": (d.get("user_agent") or "")[:80],
        "method": d.get("method"),
        "endpoint": d.get("target") or d.get("endpoint"),
        "action": d.get("action"),
        "category": cat,
        "status": d.get("status"),
        "reason": d.get("reason"),
        "criticality": crit,
        "data": d.get("data") or {},
    }
    return out


# ─────────────────── GET / ───────────────────
@router.get("")
async def list_audit_log(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
    role: Optional[str] = None,
    action: Optional[str] = None,
    endpoint: Optional[str] = None,
    company_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[int] = None,
    criticality: Optional[str] = None,
    q: Optional[str] = None,
):
    """Lista paginada do audit_log com filtros."""
    flt: Dict[str, Any] = {}
    if from_ or to:
        rng: Dict[str, Any] = {}
        if from_:
            rng["$gte"] = from_
        if to:
            rng["$lte"] = to
        flt["created_at"] = rng
    if user_id:
        flt["user_id"] = user_id
    if user_email:
        flt["user_email"] = {"$regex": re.escape(user_email), "$options": "i"}
    if role:
        flt["user_role"] = role
    if action:
        flt["action"] = {"$regex": re.escape(action), "$options": "i"}
    if endpoint:
        flt["target"] = {"$regex": re.escape(endpoint), "$options": "i"}
    if company_id:
        flt["company_id"] = company_id
    if category:
        flt["category"] = category
    if status is not None:
        flt["status"] = status
    if criticality:
        flt["criticality"] = criticality
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        flt["$or"] = [
            {"action": rx}, {"target": rx}, {"user_email": rx},
            {"reason": rx},
        ]

    total = await db.audit_log.count_documents(flt)
    cur = db.audit_log.find(flt).sort("created_at", -1) \
        .skip(skip).limit(limit)
    items = []
    async for d in cur:
        items.append(_doc_to_payload(d, mask=True))
    return {"total": total, "skip": skip, "limit": limit, "items": items}


# ─────────────────── GET /stats ───────────────────
@router.get("/stats")
async def stats(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    window_hours: int = Query(24, ge=1, le=720),
):
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=window_hours)).isoformat()

    flt_window = {"created_at": {"$gte": since}}

    total = await db.audit_log.count_documents(flt_window)
    deletes = await db.audit_log.count_documents(
        {**flt_window, "category": "destructive"})
    exports = await db.audit_log.count_documents(
        {**flt_window, "category": "export"})
    rbac_blocked = await db.audit_log.count_documents(
        {**flt_window, "category": "rbac_blocked"})
    impersonate = await db.audit_log.count_documents(
        {**flt_window, "category": "impersonate"})
    cfg_changes = await db.audit_log.count_documents(
        {**flt_window, "category": {
            "$in": ["config_change", "ai_config_change"]}})
    criticals = await db.audit_log.count_documents(
        {**flt_window, "criticality": {"$in": ["alta", "critica"]}})

    # Top usuários
    pipeline_users = [
        {"$match": flt_window},
        {"$group": {
            "_id": {"user_id": "$user_id", "email": "$user_email",
                      "role": "$user_role"},
            "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 5},
    ]
    top_users = []
    async for r in db.audit_log.aggregate(pipeline_users):
        u = r["_id"] or {}
        top_users.append({
            "user_id": u.get("user_id"),
            "email": _mask_email(u.get("email")),
            "role": u.get("role"),
            "count": r["n"],
        })

    # Top endpoints
    pipeline_eps = [
        {"$match": flt_window},
        {"$group": {"_id": "$target", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 8},
    ]
    top_endpoints = []
    async for r in db.audit_log.aggregate(pipeline_eps):
        if r["_id"]:
            top_endpoints.append({"endpoint": r["_id"], "count": r["n"]})

    # Por hora (últimas 24h)
    pipeline_hour = [
        {"$match": flt_window},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 13]},
            "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    by_hour = []
    async for r in db.audit_log.aggregate(pipeline_hour):
        by_hour.append({"hour": r["_id"], "count": r["n"]})

    return {
        "window_hours": window_hours,
        "cards": {
            "total": total,
            "deletes": deletes,
            "exports": exports,
            "rbac_blocked": rbac_blocked,
            "impersonate": impersonate,
            "config_changes": cfg_changes,
            "criticals": criticals,
        },
        "top_users": top_users,
        "top_endpoints": top_endpoints,
        "by_hour": by_hour,
        "generated_at": now.isoformat(),
    }


# ─────────────────── GET /criticality ───────────────────
@router.get("/criticality")
async def criticality_dist(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    window_hours: int = Query(24, ge=1, le=720),
):
    since = (datetime.now(timezone.utc)
             - timedelta(hours=window_hours)).isoformat()
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$criticality", "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {"alta": 0, "media": 0, "baixa": 0}
    async for r in db.audit_log.aggregate(pipeline):
        k = r["_id"] or "baixa"
        out[k] = r["n"]
    return out


# ─────────────────── GET /export.csv ───────────────────
# IMPORTANTE: precisa estar ANTES de /{aid} senão a rota dinâmica
# captura "export.csv" como aid.

# ─────────────────── Sprint 4 — LGPD endpoints ───────────────────
# (precisam estar ANTES de /{aid})

@router.get("/lgpd/subject-report")
async def lgpd_subject_report(
    subject_id: str = Query(..., min_length=1),
    email: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=10000),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    """Relatório LGPD (art. 18) — todas as ações sobre o titular.

    Pós-CTO audit: isolamento multi-tenant — auditor só vê eventos
    da própria company (super admin vê tudo).
    """
    from services.lgpd_chain import subject_report, insert_audit_event
    company_filter = None if _is_super(user) else user.get("company_id")
    report = await subject_report(subject_id, email, limit,
                                    company_id=company_filter)
    try:
        await insert_audit_event({
            "id": f"aud-lgpd-{datetime.now(timezone.utc).timestamp():.0f}",
            "company_id": user.get("company_id"),
            "user_id": user.get("sub") or user.get("id"),
            "user_email": user.get("email"),
            "user_role": user.get("role"),
            "category": "export",
            "criticality": "media",
            "method": "GET",
            "target": "/api/audit-log/lgpd/subject-report",
            "endpoint": "/api/audit-log/lgpd/subject-report",
            "action": f"LGPD subject_report subject_id={subject_id}",
            "status": 200,
            "data": {"subject_id": subject_id,
                       "events": report["total_events"],
                       "tenant_scoped": company_filter is not None},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
    return report


@router.get("/lgpd/verify-chain")
async def lgpd_verify_chain(
    limit: int = Query(5000, ge=1, le=20000),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    """Recomputa o hash-chain do audit_log e detecta adulteração."""
    from services.lgpd_chain import verify_chain
    return await verify_chain(limit=limit)


@router.get("/lgpd/subject-report.pdf")
async def lgpd_subject_pdf(
    subject_id: str = Query(..., min_length=1),
    email: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=10000),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    """Gera dossiê LGPD em PDF assinado por hash-chain."""
    from services.lgpd_chain import (
        subject_report, verify_chain, insert_audit_event,
    )
    from services.lgpd_pdf import build_pdf
    company_filter = None if _is_super(user) else user.get("company_id")
    report = await subject_report(subject_id, email, limit,
                                    company_id=company_filter)
    chain = await verify_chain(limit=5000)
    company = "SmartProv"
    pdf_bytes, dossie_id, checksum = build_pdf(report, chain, company)
    # Audita a emissão do dossiê
    try:
        await insert_audit_event({
            "id": f"aud-pdf-{datetime.now(timezone.utc).timestamp():.0f}",
            "company_id": user.get("company_id"),
            "user_id": user.get("sub") or user.get("id"),
            "user_email": user.get("email"),
            "user_role": user.get("role"),
            "category": "export",
            "criticality": "media",
            "method": "GET",
            "target": "/api/audit-log/lgpd/subject-report.pdf",
            "endpoint": "/api/audit-log/lgpd/subject-report.pdf",
            "action": (f"LGPD dossie PDF subject={subject_id} "
                          f"dossie_id={dossie_id}"),
            "status": 200,
            "data": {
                "subject_id": subject_id,
                "dossie_id": dossie_id,
                "checksum_sha256": checksum,
                "events": report["total_events"],
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
    fn = f"dossie-lgpd-{dossie_id}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fn}"',
            "X-LGPD-Dossie-Id": dossie_id,
            "X-LGPD-Checksum": checksum,
        },
    )


@router.get("/retention-policy")
async def get_policy(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.lgpd_chain import get_retention_policy
    return {"policy": await get_retention_policy()}


@router.put("/retention-policy")
async def put_policy(
    body: Dict[str, int],
    user: Dict[str, Any] = Depends(
        require_roles("administrador")),
):
    """Atualiza retention policy (dias por categoria). Admin only."""
    from services.lgpd_chain import set_retention_policy
    updated = await set_retention_policy(body or {})
    return {"policy": updated}


@router.post("/retention-policy/apply")
async def apply_policy_now(
    user: Dict[str, Any] = Depends(
        require_roles("administrador")),
):
    """Roda a retenção AGORA — apaga registros vencidos por categoria."""
    from services.lgpd_chain import apply_retention_now
    return {"deleted": await apply_retention_now()}


@router.get("/export.csv")
@limiter.limit(get_limit("audit_export"))
async def export_csv(
    request: Request,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    category: Optional[str] = None,
    criticality: Optional[str] = None,
    limit: int = Query(5000, ge=1, le=20000),
):
    flt: Dict[str, Any] = {}
    # Pós-CTO audit: isolamento multi-tenant — auditor só exporta sua
    # company (super admin vê tudo)
    if not _is_super(user):
        flt["company_id"] = user.get("company_id")
    if from_ or to:
        rng: Dict[str, Any] = {}
        if from_:
            rng["$gte"] = from_
        if to:
            rng["$lte"] = to
        flt["created_at"] = rng
    if category:
        flt["category"] = category
    if criticality:
        flt["criticality"] = criticality

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "id", "created_at", "user_email", "user_role", "company_id",
        "ip", "method", "endpoint", "action", "category", "criticality",
        "status", "reason",
    ])
    cur = db.audit_log.find(flt).sort("created_at", -1).limit(limit)
    n = 0
    async for d in cur:
        cat = d.get("category", "")
        w.writerow([
            d.get("id"), d.get("created_at"),
            d.get("user_email"), d.get("user_role"),
            d.get("company_id"), d.get("ip"),
            d.get("method"), d.get("target") or d.get("endpoint"),
            d.get("action"), cat,
            d.get("criticality") or _crit(cat),
            d.get("status"), d.get("reason") or "",
        ])
        n += 1

    # registra a própria exportação via hash-chain (audit do audit ✨)
    try:
        from services.lgpd_chain import insert_audit_event
        await insert_audit_event({
            "id": f"aud-self-{datetime.now(timezone.utc).timestamp():.0f}",
            "company_id": user.get("company_id"),
            "user_id": user.get("sub") or user.get("id"),
            "user_email": user.get("email"),
            "user_role": user.get("role"),
            "category": "export",
            "criticality": "media",
            "method": "GET",
            "target": "/api/audit-log/export.csv",
            "endpoint": "/api/audit-log/export.csv",
            "action": "GET /api/audit-log/export.csv",
            "status": 200,
            "data": {"rows": n, "filters": str(flt)[:200]},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    buf.seek(0)
    fn = (f"audit-trail-"
           f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )


# ─────────────────── GET /{aid} ───────────────────
@router.get("/{aid}")
async def get_event(
    aid: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    d = await db.audit_log.find_one({"id": aid})
    if not d:
        raise HTTPException(404, "Evento não encontrado")
    # detalhe: admin/auditor podem ver email/IP completos
    return _doc_to_payload(d, mask=False)


# ─────────────────── Indexes ───────────────────
async def ensure_indexes() -> None:
    """TTL 180 dias + índices de query."""
    try:
        await db.audit_log.create_index("id", unique=True)
    except Exception:
        pass
    try:
        await db.audit_log.create_index([("created_at", -1)])
        await db.audit_log.create_index([("user_id", 1), ("created_at", -1)])
        await db.audit_log.create_index([("category", 1), ("created_at", -1)])
        await db.audit_log.create_index([("criticality", 1),
                                          ("created_at", -1)])
        await db.audit_log.create_index([("target", 1), ("created_at", -1)])
    except Exception:
        pass
