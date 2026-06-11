"""
blockers_audit.py — V6.0 Bloco 2
Painel executivo: "POR QUE A IA NÃO ESTÁ AGINDO?"
Lista bloqueadores REAIS com impacto financeiro mensurado.
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

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
import os

from database import db


def _now(): return datetime.now(timezone.utc)


async def _blocked_actions_summary(company_id: str,
                                     days: int = 7) -> Dict[str, Any]:
    """Quantifica ações bloqueadas e receita represada."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                     "created_at": {"$gte": cutoff},
                     "status": {"$in": ["blocked_transport",
                                          "blocked_data",
                                          "queued_no_credentials"]}}},
        {"$lookup": {"from": "motor_ia_decisions",
                       "localField": "decision_id",
                       "foreignField": "decision_id",
                       "as": "d"}},
        {"$unwind": "$d"},
        {"$group": {"_id": "$status",
                     "n": {"$sum": 1},
                     "BRL": {"$sum": "$d.expected_BRL"}}},
    ]
    rows = await db.motor_ia_actions.aggregate(pipe).to_list(50)
    total_n = sum(r["n"] for r in rows)
    total_BRL = sum(r["BRL"] for r in rows)
    return {
        "blocked_total": total_n,
        "blocked_BRL": round(total_BRL, 2),
        "by_status": [{"status": r["_id"], "count": r["n"],
                        "BRL": round(r["BRL"], 2)}
                       for r in rows],
    }


async def _credential_blockers(company_id: str) -> List[Dict[str, Any]]:
    """Bloqueios de credencial / configuração."""
    from services import transport_check as tx
    wa = await tx.wa_status(company_id)

    out: List[Dict[str, Any]] = []
    if not wa["can_send"]:
        # Receita financeira represada estimada via ações bloqueadas WA
        blocked = await _blocked_actions_summary(company_id, days=7)
        wa_blocked_BRL = sum(
            x["BRL"] for x in blocked["by_status"]
            if x["status"] in ("blocked_transport",
                                  "queued_no_credentials"))
        for b in wa["blockers"]:
            out.append({
                "kind": "credential",
                "blocker": b,
                "category": "WhatsApp · Operação Tese",
                "impact_BRL_week": round(wa_blocked_BRL, 2),
                "actions_blocked": blocked["blocked_total"],
                "priority": "P0" if b in (
                    "WA_SIDECAR_TOKEN", "BAILEYS_SIDECAR_URL",
                    "PRESIDENTE_IA_GESTOR_PHONE") else "P1",
                "how_to_resolve": _resolve_hint(b),
                "evidence": [
                    {"type": "session_status",
                      "value": wa.get("session_status")},
                    {"type": "sidecar_reachable",
                      "value": wa["checks"]["sidecar_reachable"]},
                ],
            })
    return out


def _resolve_hint(blocker: str) -> str:
    m = {
        "WA_SIDECAR_TOKEN":            "Definir env var WA_SIDECAR_TOKEN no backend/.env",
        "BAILEYS_SIDECAR_URL":         "Definir env var BAILEYS_SIDECAR_URL com URL pública do sidecar Baileys",
        "PRESIDENTE_IA_GESTOR_PHONE":  "Definir env var PRESIDENTE_IA_GESTOR_PHONE (formato +5511...)",
        "session_status_open":         "Scanear QR Code no Baileys e abrir sessão (status=open em wa_baileys_sessions)",
        "sidecar_reachable":           "Verificar se sidecar Baileys está no ar (curl $BAILEYS_SIDECAR_URL/health)",
    }
    return m.get(blocker, "Verificar log")


async def _data_blockers(company_id: str) -> List[Dict[str, Any]]:
    """Bloqueios de dados: company_id órfão, plan_price faltando, ONU sem zone."""
    out: List[Dict[str, Any]] = []
    # 1) Subscribers sem plan_price (ações dependem disso)
    sub_no_price = await db.subscribers.count_documents({
        "company_id": company_id,
        "$or": [{"plan_price": {"$exists": False}},
                 {"plan_price": 0}, {"plan_price": None}]})
    if sub_no_price > 0:
        out.append({
            "kind": "data_quality",
            "blocker": "subscribers_without_plan_price",
            "category": "Cadastro Financeiro",
            "count": sub_no_price,
            "impact_BRL_week": 0.0,
            "actions_blocked": sub_no_price,
            "priority": "P1",
            "how_to_resolve": ("Rodar `python -m scripts.backfill_financial fix` "
                                "para popular preço via mediana de invoices"),
        })

    # 2) Subscribers ATIVO sem telefone
    sub_no_phone = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "$or": [{"phone": {"$exists": False}},
                 {"phone": ""}, {"phone": None}]})
    if sub_no_phone > 0:
        out.append({
            "kind": "data_quality",
            "blocker": "active_subscribers_without_phone",
            "category": "Contato WhatsApp",
            "count": sub_no_phone,
            "impact_BRL_week": 0.0,
            "actions_blocked": sub_no_phone,
            "priority": "P2",
            "how_to_resolve": ("Atualizar telefone via integração SmartOLT "
                                "ou enriquecer cadastro"),
        })

    # 3) Órfãos company_id
    from services import multitenant_audit as mt
    orph = await mt.audit_orphans()
    if orph["summary"]["total_orphans"] > 0:
        out.append({
            "kind": "data_quality",
            "blocker": "orphan_company_id",
            "category": "Multi-tenant",
            "count": orph["summary"]["total_orphans"],
            "impact_BRL_week": 0.0,
            "actions_blocked": 0,
            "priority": "P1",
            "how_to_resolve": ("Rodar `python -m scripts.audit_multitenant fix`"),
        })
    return out


async def _api_blockers(company_id: str) -> List[Dict[str, Any]]:
    """APIs offline (Mongo, Baileys sidecar, integrações externas)."""
    out: List[Dict[str, Any]] = []
    # Mongo health
    try:
        await db.command("ping")
    except Exception as e:  # noqa: BLE001
        out.append({
            "kind": "api",
            "blocker": "mongodb_down",
            "category": "Banco de Dados",
            "priority": "P0",
            "impact_BRL_week": -1,
            "how_to_resolve": "Restart MongoDB service",
            "error": str(e)[:120],
        })

    # Verificar últimos erros do scheduler nas últimas 24h
    return out


async def full_audit(company_id: str) -> Dict[str, Any]:
    """Painel executivo único: lista bloqueadores reais ordenados."""
    cred = await _credential_blockers(company_id)
    data = await _data_blockers(company_id)
    apis = await _api_blockers(company_id)

    all_blockers = cred + data + apis
    # ordena por prioridade
    pri_order = {"P0": 0, "P1": 1, "P2": 2}
    all_blockers.sort(key=lambda x: (pri_order.get(x.get("priority"), 9),
                                         -x.get("impact_BRL_week", 0)))

    total_blocked_BRL = sum(b.get("impact_BRL_week", 0) or 0
                              for b in all_blockers)
    total_actions_blocked = sum(b.get("actions_blocked", 0) or 0
                                  for b in all_blockers)
    p0 = sum(1 for b in all_blockers if b.get("priority") == "P0")
    p1 = sum(1 for b in all_blockers if b.get("priority") == "P1")

    actions_summary = await _blocked_actions_summary(company_id, days=7)

    headline = (
        f"{len(all_blockers)} bloqueador(es) · P0={p0} · P1={p1} · "
        f"{actions_summary['blocked_total']} ações represadas · "
        f"R$ {actions_summary['blocked_BRL']:,.2f} congelados na semana"
    )

    return {
        "generated_at": _now().isoformat(),
        "company_id": company_id,
        "headline": headline,
        "summary": {
            "total_blockers": len(all_blockers),
            "p0_count": p0,
            "p1_count": p1,
            "blocked_actions_7d": actions_summary["blocked_total"],
            "blocked_revenue_BRL_7d": actions_summary["blocked_BRL"],
            "total_impact_estimate_BRL": round(total_blocked_BRL, 2),
        },
        "blockers": all_blockers,
        "actions_summary_7d": actions_summary,
    }
