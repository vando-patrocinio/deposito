"""sprint5_audit_operacional — Auditoria Operacional Semanal (CEO 19/02/2026)

"Exame de sangue" da operação. Sábado 06:00 UTC.
Responde 15 perguntas críticas em 3 blocos (Lousa + Patrimônio + Rede)
+ nota 0-10 + status APROVADA/COM RESSALVAS/REPROVADA.

Endpoints (prefix /api/sprint5/audit-operacional):
  POST /run-weekly        — executa agora
  GET  /latest            — último relatório
  GET  /history           — histórico
"""

NERVOUS_METADATA = {"owner": "infra-team", "domain": "patrimonio",
                    "criticality": "high", "company_id_required": True}

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from core import require_role
from database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/audit-operacional",
                       tags=["sprint5", "audit-operacional"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    return user.get("company_id") or "co-demo"


async def _build_weekly_report(cid: str) -> Dict[str, Any]:
    """Constrói as 15 respostas + nota."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()

    # ─────── LOUSA ───────
    onda3_blocked = await db.sprint5_onda3_validations.count_documents(
        {"company_id": cid, "ok": False, "created_at": {"$gte": week_start}})
    onda3_overrides = await db.sprint5_onda3_validations.count_documents(
        {"company_id": cid, "ok": True,
         "diag.override_used": True, "created_at": {"$gte": week_start}})
    finaliz_sem_ont = await db.sprint5_onda3_validations.count_documents(
        {"company_id": cid, "ok": False,
         "diag.missing": "ont_identifier",
         "created_at": {"$gte": week_start}})
    finaliz_sem_cto = await db.sprint5_onda3_validations.count_documents(
        {"company_id": cid, "ok": False, "diag.missing": "cto_id",
         "created_at": {"$gte": week_start}})
    finaliz_sem_port = await db.sprint5_onda3_validations.count_documents(
        {"company_id": cid, "ok": False, "diag.missing": "port_number",
         "created_at": {"$gte": week_start}})
    swaps_pending = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid,
         "confirmation_status": {"$in": ["pending_confirmation",
                                                "sent_to_technician"]}})

    # ─────── PATRIMÔNIO ───────
    promocoes = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "promoted_at": {"$gte": week_start}})
    ativos_sem_local = await db.stok_onts.count_documents(
        {"company_id": cid, "tier": "official",
         "$or": [{"location_id": {"$in": [None, ""]}},
                    {"location_id": {"$exists": False}}]})
    ativos_sem_resp = await db.stok_onts.count_documents(
        {"company_id": cid, "tier": "official",
         "subscriber_id": {"$in": [None, ""]}})
    oficial = await db.stok_onts.count_documents(
        {"company_id": cid, "tier": "official"})
    smartolt = await db.smartolt_onus.count_documents(
        {"company_id": cid})
    cobertura_op = round((oficial / smartolt * 100), 2) \
        if smartolt else 0.0
    compliance = round(
        (oficial / (oficial + await db.stok_onts.count_documents(
            {"company_id": cid, "tier": "quarantine"})) * 100), 2) \
        if oficial else 0.0

    # ─────── REDE ───────
    canonical_ont_link = await db.network_access_canonical.count_documents(
        {"company_id": cid, "status": "occupied",
         "$or": [{"ont_sn": {"$nin": [None, ""]}},
                    {"ont_mac": {"$nin": [None, ""]}}]})
    canonical_occupied = await db.network_access_canonical.count_documents(
        {"company_id": cid, "status": "occupied"})
    porta_sem_ont = canonical_occupied - canonical_ont_link
    smartolt_sem_estoque = await db.smartolt_onus.count_documents(
        {"company_id": cid, "sn": {"$nin": [None, ""]}}) - oficial
    smartolt_sem_estoque = max(smartolt_sem_estoque, 0)

    questions = {
        # Lousa
        "lousa_os_bloqueadas_semana": onda3_blocked,
        "lousa_overrides_realizados": onda3_overrides,
        "lousa_finalizacoes_sem_ont": finaliz_sem_ont,
        "lousa_finalizacoes_sem_cto": finaliz_sem_cto,
        "lousa_finalizacoes_sem_porta": finaliz_sem_port,
        "lousa_swaps_pending_confirmacao": swaps_pending,
        # Patrimônio
        "patrim_promocoes_quarentena_oficial": promocoes,
        "patrim_ativos_sem_localizacao": ativos_sem_local,
        "patrim_ativos_sem_responsavel": ativos_sem_resp,
        "patrim_cobertura_operacional_pct": cobertura_op,
        "patrim_compliance_pct": compliance,
        # Rede
        "rede_porta_ocupada_sem_ont_link": porta_sem_ont,
        "rede_smartolt_sem_estoque": smartolt_sem_estoque,
    }

    # ─────── NOTA 0-10 ───────
    score = 10.0
    if cobertura_op < 95:
        score -= (95 - cobertura_op) / 10
    if onda3_blocked > 0 and (onda3_blocked + onda3_overrides) > 0:
        block_rate = (onda3_blocked / (onda3_blocked + onda3_overrides))
        if block_rate > 0.3:
            score -= 1.0
    if ativos_sem_resp > 0:
        score -= min(ativos_sem_resp / 100, 2.0)
    if porta_sem_ont > 0:
        score -= min(porta_sem_ont / 50, 1.5)
    if compliance < 75:
        score -= 1.0
    score = round(max(score, 0.0), 2)

    if score >= 8.5:
        status_label = "APROVADA"
    elif score >= 6.5:
        status_label = "COM RESSALVAS"
    else:
        status_label = "REPROVADA"

    report_id = f"audop-{now.strftime('%Y_W%V')}-{uuid.uuid4().hex[:8]}"
    doc: Dict[str, Any] = {
        "id": report_id,
        "company_id": cid,
        "week_iso": now.strftime("%Y-W%V"),
        "week_start": week_start,
        "week_end": now.isoformat(),
        "answers": questions,
        "score_0_10": score,
        "status": status_label,
        "generated_at": _now_iso(),
        "generated_by": "audit_operacional_v1",
    }
    doc["hash_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True, default=str).encode()
    ).hexdigest()
    await db.sprint5_audit_operacional.insert_one(doc)
    return doc


@router.post("/run-weekly")
async def run_weekly(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = _user_company(user)
    return await _build_weekly_report(cid)


@router.get("/latest")
async def latest(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    doc = await db.sprint5_audit_operacional.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("generated_at", -1)])
    return doc or {"empty": True}


@router.get("/history")
async def history(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    items = await db.sprint5_audit_operacional.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("generated_at", -1).limit(limit).to_list(length=limit)
    return {"items": items, "count": len(items)}
