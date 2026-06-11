"""
audit_alerts.py — Sprint 3 / iter222
Detectores de anomalias de segurança consumidos pelo Presidente IA.

Cada detector retorna List[Dict] no formato:
    {
        "type": "mass_export" | "mass_delete" | "rbac_abuse" | "impersonate",
        "severity": "alta" | "media" | "baixa",
        "title": str,
        "message": str,
        "evidence": dict,  # contagens e amostra
        "scope": str,  # user_id ou endpoint
    }
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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ─────────────────── Detectores ───────────────────
async def detect_mass_export(window_hours: int = 1,
                                threshold: int = 5
                                ) -> List[Dict[str, Any]]:
    """Mais de N exports do mesmo usuário em janela curta."""
    out: List[Dict[str, Any]] = []
    pipe = [
        {"$match": {
            "category": "export",
            "created_at": {"$gte": _since(window_hours)},
        }},
        {"$group": {
            "_id": {"u": "$user_id", "e": "$user_email"},
            "n": {"$sum": 1},
            "endpoints": {"$addToSet": "$target"},
        }},
        {"$match": {"n": {"$gte": threshold}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    async for r in db.audit_log.aggregate(pipe):
        u = r["_id"] or {}
        out.append({
            "type": "mass_export",
            "severity": "alta" if r["n"] >= threshold * 2 else "media",
            "title": "Exportação em massa detectada",
            "message": (
                f"{u.get('e') or u.get('u')} exportou {r['n']} relatórios "
                f"nas últimas {window_hours}h. Verifique se é legítimo."),
            "evidence": {"count": r["n"],
                            "endpoints": r["endpoints"][:5]},
            "scope": u.get("u") or "?",
        })
    return out


async def detect_mass_delete(window_hours: int = 1,
                                threshold: int = 10
                                ) -> List[Dict[str, Any]]:
    """Mais de N deletes do mesmo usuário."""
    out: List[Dict[str, Any]] = []
    pipe = [
        {"$match": {
            "category": "destructive",
            "created_at": {"$gte": _since(window_hours)},
        }},
        {"$group": {
            "_id": {"u": "$user_id", "e": "$user_email"},
            "n": {"$sum": 1},
            "endpoints": {"$addToSet": "$target"},
        }},
        {"$match": {"n": {"$gte": threshold}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    async for r in db.audit_log.aggregate(pipe):
        u = r["_id"] or {}
        out.append({
            "type": "mass_delete",
            "severity": "alta",
            "title": "Deleção em massa detectada",
            "message": (
                f"{u.get('e') or u.get('u')} deletou {r['n']} registros "
                f"nas últimas {window_hours}h. Pode indicar comprometimento "
                f"de conta ou erro humano."),
            "evidence": {"count": r["n"],
                            "endpoints": r["endpoints"][:5]},
            "scope": u.get("u") or "?",
        })
    return out


async def detect_rbac_abuse(window_hours: int = 1,
                               threshold: int = 5
                               ) -> List[Dict[str, Any]]:
    """Usuário batendo em rotas que não pode (tentativas 403 repetidas)."""
    out: List[Dict[str, Any]] = []
    pipe = [
        {"$match": {
            "category": "rbac_blocked",
            "created_at": {"$gte": _since(window_hours)},
        }},
        {"$group": {
            "_id": {"u": "$user_id", "e": "$user_email",
                      "r": "$user_role"},
            "n": {"$sum": 1},
            "endpoints": {"$addToSet": "$target"},
        }},
        {"$match": {"n": {"$gte": threshold}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    async for r in db.audit_log.aggregate(pipe):
        u = r["_id"] or {}
        out.append({
            "type": "rbac_abuse",
            "severity": "alta" if r["n"] >= 20 else "media",
            "title": "Tentativas repetidas de acesso negado",
            "message": (
                f"{u.get('e') or u.get('u')} (role={u.get('r')}) bateu "
                f"em {r['n']} endpoints proibidos nas últimas "
                f"{window_hours}h. Possível tentativa de "
                f"escalonamento de privilégio."),
            "evidence": {"count": r["n"],
                            "endpoints": r["endpoints"][:5]},
            "scope": u.get("u") or "?",
        })
    return out


async def detect_impersonate(window_hours: int = 24
                                ) -> List[Dict[str, Any]]:
    """Lista impersonations recentes (informativo)."""
    out: List[Dict[str, Any]] = []
    cur = db.audit_log.find({
        "category": "impersonate",
        "created_at": {"$gte": _since(window_hours)},
    }).sort("created_at", -1).limit(10)
    async for d in cur:
        out.append({
            "type": "impersonate",
            "severity": "media",
            "title": "Admin assumiu identidade de outro usuário",
            "message": (
                f"{d.get('user_email')} executou impersonate em "
                f"{d.get('target')} às {d.get('created_at')}."),
            "evidence": {"endpoint": d.get("target")},
            "scope": d.get("user_id") or "?",
        })
    return out


# ─────────────────── Scan all ───────────────────
async def scan_security_alerts() -> List[Dict[str, Any]]:
    """Roda todos os detectores. Chamado pelo Presidente IA.

    Pós-CTO audit: cada alerta gera um evento FORMAL no event_bus
    (com event_type da taxonomia + company_id quando disponível na
    evidência), em vez de gravar direto na collection com schema
    legado.
    """
    alerts: List[Dict[str, Any]] = []
    alerts += await detect_mass_export()
    alerts += await detect_mass_delete()
    alerts += await detect_rbac_abuse()
    alerts += await detect_impersonate()

    if not alerts:
        return alerts

    from services.event_bus import emit_event, EventType
    type_map = {
        "mass_export": EventType.AUDIT_EXPORT,
        "mass_delete": EventType.AUDIT_DELETE,
        "rbac_abuse": EventType.RBAC_DENIED,
        "impersonate": EventType.IMPERSONATE,
    }
    for a in alerts:
        # tenta extrair company_id do user_id do escopo (best-effort)
        company_id = None
        try:
            doc = await db.users.find_one(
                {"id": a.get("scope")}, {"company_id": 1})
            if doc:
                company_id = doc.get("company_id")
        except Exception:
            pass
        try:
            await emit_event(
                type_map.get(a["type"], "SECURITY_ALERT"),
                company_id=company_id,
                source="audit_alerts",
                severity=a.get("severity", "media"),
                payload={
                    "title": a.get("title"),
                    "message": a.get("message"),
                    "evidence": a.get("evidence"),
                    "scope": a.get("scope"),
                    "detector": a.get("type"),
                },
            )
        except Exception:
            pass
    return alerts


# ─────────────────── Insight diário ───────────────────
async def daily_security_insight() -> Dict[str, Any]:
    """Resumo de segurança das últimas 24h para o Presidente IA."""
    since = _since(24)
    total = await db.audit_log.count_documents({"created_at": {"$gte": since}})
    deletes = await db.audit_log.count_documents(
        {"created_at": {"$gte": since}, "category": "destructive"})
    exports = await db.audit_log.count_documents(
        {"created_at": {"$gte": since}, "category": "export"})
    blocked = await db.audit_log.count_documents(
        {"created_at": {"$gte": since}, "category": "rbac_blocked"})
    impers = await db.audit_log.count_documents(
        {"created_at": {"$gte": since}, "category": "impersonate"})

    # status: verde se nada anormal; amarelo se >X; vermelho se alertas
    status = "saudavel"
    if blocked >= 20 or exports >= 50 or deletes >= 30:
        status = "alerta"
    elif blocked >= 5 or exports >= 10 or deletes >= 5:
        status = "atencao"

    msg_parts = []
    if blocked:
        msg_parts.append(f"{blocked} tentativas de acesso negadas")
    if deletes:
        msg_parts.append(f"{deletes} deleções")
    if exports:
        msg_parts.append(f"{exports} exportações")
    if impers:
        msg_parts.append(f"{impers} impersonations")
    msg = (" · ".join(msg_parts)
           if msg_parts else "nenhuma ação sensível detectada")

    return {
        "status": status,
        "title": "Segurança & Compliance — últimas 24h",
        "message": msg,
        "counts": {
            "total": total, "deletes": deletes, "exports": exports,
            "rbac_blocked": blocked, "impersonate": impers,
        },
        "generated_at": _now_iso(),
    }
