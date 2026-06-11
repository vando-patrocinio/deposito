"""Balanço de Estoque (Cycle Counting / Stock Reconciliation).

Best-practices implementadas:
- **Cycle counting** flexível: usuário escolhe escopo (empresa / praça / técnico)
- **Blind count** opcional (não revela saldo esperado durante contagem)
- **ONTs (scan MAC) + Insumos (qty)** numa mesma sessão
- **Separation of duties**: gestor inicia/conta/finaliza; só administrador
  ou super_admin aprova ajustes
- **Variance categorization**: matched, missing, extra
- **Audit trail completo**: cada scan, cada ajuste, gravado em `stok_history`
- **Frozen view** do esperado: snapshot tirado no `start`, evita
  movimentações concorrentes invalidarem o balanço.

State machine:
    counting → pending_approval → approved | cancelled
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

import logging
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, is_super_admin, now_iso, require_role
from database import db
from routes.stok import (CONSUMABLE_BY_ID, CONSUMABLE_CATALOG, CONSUMABLE_IDS,
                          _add_history, normalize_mac)

logger = logging.getLogger("ponto.balanco")

router = APIRouter(prefix="/api/stok/balanco", tags=["stok-balanco"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
ScopeType = Literal["empresa", "praca", "tecnico"]
ModeType = Literal["blind", "open"]


class BalancoStartIn(BaseModel):
    scope_type: ScopeType
    scope_id: Optional[str] = None  # praca_id ou collaborator_id (None se empresa)
    mode: ModeType = "blind"
    include_consumables: bool = True
    note: Optional[str] = None


class ScanIn(BaseModel):
    mac: str


class ConsumableCountIn(BaseModel):
    consumable_id: str
    qty: int = Field(ge=0)


class ApproveIn(BaseModel):
    # Ajustes para MACs faltantes: "perdido" (baixa) | "investigacao" (mantém com flag)
    missing_action: Literal["perdido", "investigacao"] = "perdido"
    # MACs/insumos a serem ignorados na aprovação (gestor revisou e quer pular)
    ignore_macs: List[str] = []
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _can_approve(user: dict) -> bool:
    """Separation of duties: só administrador ou super_admin aprovam."""
    if is_super_admin(user):
        return True
    return (user.get("role") or "").lower() == "administrador"


async def _expected_onts_for_scope(
    company_id: str, scope_type: str, scope_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Lista de MACs esperados naquele escopo no momento do snapshot."""
    q: Dict[str, Any] = {"company_id": company_id}
    if scope_type == "empresa":
        q["location_type"] = "empresa"
    elif scope_type == "praca":
        if not scope_id:
            raise HTTPException(400, "scope_id obrigatório para praça.")
        q["location_type"] = "empresa"
        q["praca_id"] = scope_id
    elif scope_type == "tecnico":
        if not scope_id:
            raise HTTPException(400, "scope_id obrigatório para técnico.")
        q["location_type"] = "tecnico"
        q["location_id"] = scope_id
    docs = await db.stok_onts.find(
        q, {"_id": 0, "mac": 1, "model": 1, "status": 1, "praca_id": 1,
            "location_id": 1, "location_type": 1},
    ).to_list(5000)
    return docs


async def _expected_consumables_for_scope(
    company_id: str, scope_type: str, scope_id: Optional[str],
) -> Dict[str, int]:
    """Saldo esperado de insumos no escopo."""
    if scope_type == "empresa":
        doc = await db.stok_stock.find_one(
            {"company_id": company_id, "location": "empresa"}, {"_id": 0},
        ) or {}
    elif scope_type == "tecnico":
        doc = await db.stok_stock.find_one(
            {"company_id": company_id, "location": scope_id}, {"_id": 0},
        ) or {}
    elif scope_type == "praca":
        # Para praça: agrega via stok_stock com praca_id (modelo novo) OU
        # se não houver, devolve 0s (legacy: insumos eram só empresa/técnico).
        rows = await db.stok_stock.find(
            {"company_id": company_id, "praca_id": scope_id}, {"_id": 0},
        ).to_list(50)
        acc: Dict[str, int] = {}
        for r in rows:
            for c in CONSUMABLE_IDS:
                acc[c] = acc.get(c, 0) + int(r.get(c, 0) or 0)
            # também acumula formato novo (insumo_key/quantity)
            if r.get("insumo_key") in CONSUMABLE_IDS:
                acc[r["insumo_key"]] = acc.get(r["insumo_key"], 0) + int(
                    r.get("quantity", 0) or 0)
        return {c: int(acc.get(c, 0)) for c in CONSUMABLE_IDS}
    else:
        doc = {}
    return {c: int(doc.get(c, 0) or 0) for c in CONSUMABLE_IDS}


async def _scope_label(company_id: str, scope_type: str, scope_id: Optional[str]) -> str:
    if scope_type == "empresa":
        return "Empresa (estoque geral)"
    if scope_type == "praca":
        p = await db.fin_filiais.find_one(
            {"company_id": company_id, "id": scope_id}, {"_id": 0, "name": 1})
        return f"Praça: {p['name']}" if p else f"Praça {scope_id}"
    if scope_type == "tecnico":
        c = await db.collaborators.find_one(
            {"company_id": company_id, "id": scope_id}, {"_id": 0, "name": 1})
        return f"Técnico: {c['name']}" if c else f"Técnico {scope_id}"
    return scope_type


async def _load_session(session_id: str, company_id: str) -> dict:
    s = await db.stok_balanco_sessions.find_one(
        {"id": session_id, "company_id": company_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Balanço não encontrado.")
    return s


def _compute_variance(expected_macs: List[str], scanned_macs: List[str]) -> dict:
    exp = {m.upper() for m in expected_macs}
    sc = {m.upper() for m in scanned_macs}
    matched = sorted(exp & sc)
    missing = sorted(exp - sc)
    extra = sorted(sc - exp)
    total_exp = len(exp)
    accuracy = round(((len(matched) / total_exp) * 100), 1) if total_exp else 100.0
    return {
        "matched": matched, "missing": missing, "extra": extra,
        "expected_count": total_exp, "scanned_count": len(sc),
        "accuracy_pct": accuracy,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/start")
async def start_balanco(payload: BalancoStartIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Bloqueia se já houver sessão em counting/pending_approval pro mesmo escopo
    existing = await db.stok_balanco_sessions.find_one({
        "company_id": cid, "scope_type": payload.scope_type,
        "scope_id": payload.scope_id,
        "status": {"$in": ["counting", "pending_approval"]},
    }, {"_id": 0, "id": 1, "status": 1})
    if existing:
        raise HTTPException(409, f"Já existe um balanço em andamento para este escopo (id={existing['id']}, status={existing['status']}). Finalize ou cancele primeiro.")

    expected_onts = await _expected_onts_for_scope(cid, payload.scope_type, payload.scope_id)
    expected_consumables = await _expected_consumables_for_scope(
        cid, payload.scope_type, payload.scope_id) if payload.include_consumables else {}
    label = await _scope_label(cid, payload.scope_type, payload.scope_id)

    sid = f"BAL-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "id": sid, "company_id": cid,
        "scope_type": payload.scope_type, "scope_id": payload.scope_id,
        "scope_label": label,
        "mode": payload.mode,
        "include_consumables": payload.include_consumables,
        "status": "counting",
        "note": payload.note,
        "created_by_email": user.get("email"),
        "created_by_name": user.get("name") or user.get("email"),
        "created_at": now_iso(),
        # Snapshot do esperado (congelado no momento do start)
        "expected_macs": [o["mac"].upper() for o in expected_onts],
        "expected_ont_details": expected_onts,
        "expected_consumables": expected_consumables,
        # Resultados parciais
        "scanned_macs": [],
        "counted_consumables": {},
        # Auditoria
        "finalized_at": None, "approved_at": None,
        "approved_by_email": None, "approved_by_name": None,
        "cancelled_at": None, "cancelled_by": None,
    }
    await db.stok_balanco_sessions.insert_one(dict(doc))
    await _add_history(
        "balanco_start",
        f"{sid} — Balanço iniciado · escopo: {label} · modo: {payload.mode} · {len(expected_onts)} ONT(s) esperadas",
        user.get("name", "?"), "balanco", cid,
    )
    doc.pop("expected_ont_details", None)  # detalhes só no GET /{id}
    return doc


@router.get("/list")
async def list_balancos(limit: int = 100, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_balanco_sessions.find(
        {"company_id": cid},
        {"_id": 0, "expected_ont_details": 0},  # detalhes pesados só no GET /{id}
    ).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return docs


@router.get("/{session_id}")
async def get_balanco(session_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    # Modo cego: oculta a lista de MACs esperados/contagens enquanto em counting
    if s["mode"] == "blind" and s["status"] == "counting":
        s_safe = dict(s)
        s_safe.pop("expected_macs", None)
        s_safe.pop("expected_ont_details", None)
        s_safe.pop("expected_consumables", None)
        s_safe["expected_count"] = len(s.get("expected_macs") or [])  # só o total
        return s_safe
    # Modo aberto OU já finalizado: devolve tudo + variance se possível
    if s["status"] in ("pending_approval", "approved", "cancelled"):
        s["variance"] = _compute_variance(
            s.get("expected_macs") or [], s.get("scanned_macs") or [])
    return s


@router.post("/{session_id}/scan")
async def scan_balanco(session_id: str, payload: ScanIn,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    if s["status"] != "counting":
        raise HTTPException(400, f"Não é possível adicionar scans (status={s['status']}).")
    mac = normalize_mac(payload.mac)
    if not mac or len(mac) < 11:  # XX:XX:XX:XX:XX:XX = 17 chars; mais leniente
        raise HTTPException(400, "MAC inválido.")
    if mac in (s.get("scanned_macs") or []):
        return {"ok": True, "duplicate": True, "mac": mac,
                "scanned_count": len(s.get("scanned_macs") or [])}
    await db.stok_balanco_sessions.update_one(
        {"id": session_id, "company_id": cid},
        {"$addToSet": {"scanned_macs": mac},
         "$push": {"scan_log": {
            "mac": mac, "scanned_at": now_iso(),
            "scanned_by": user.get("name") or user.get("email"),
        }}},
    )
    expected_set = set(s.get("expected_macs") or [])
    match = mac in expected_set
    return {
        "ok": True, "duplicate": False, "mac": mac, "matched": match,
        "scanned_count": len(s.get("scanned_macs") or []) + 1,
    }


@router.post("/{session_id}/consumable")
async def count_consumable(session_id: str, payload: ConsumableCountIn,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    if s["status"] != "counting":
        raise HTTPException(400, f"Não é possível atualizar contagens (status={s['status']}).")
    if payload.consumable_id not in CONSUMABLE_IDS:
        raise HTTPException(400, "Insumo inválido.")
    await db.stok_balanco_sessions.update_one(
        {"id": session_id, "company_id": cid},
        {"$set": {f"counted_consumables.{payload.consumable_id}": payload.qty}},
    )
    return {"ok": True, "consumable_id": payload.consumable_id, "qty": payload.qty}


@router.post("/{session_id}/finalize")
async def finalize_balanco(session_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    if s["status"] != "counting":
        raise HTTPException(400, f"Já finalizado (status={s['status']}).")
    variance = _compute_variance(
        s.get("expected_macs") or [], s.get("scanned_macs") or [])
    await db.stok_balanco_sessions.update_one(
        {"id": session_id, "company_id": cid},
        {"$set": {
            "status": "pending_approval",
            "finalized_at": now_iso(),
            "finalized_by_email": user.get("email"),
            "finalized_by_name": user.get("name") or user.get("email"),
            "variance": variance,
        }},
    )
    await _add_history(
        "balanco_finalize",
        f"{session_id} — Contagem finalizada · {variance['accuracy_pct']}% acurácia · "
        f"{len(variance['matched'])} OK, {len(variance['missing'])} faltantes, {len(variance['extra'])} extras",
        user.get("name", "?"), "balanco", cid,
    )
    return {"ok": True, "status": "pending_approval", "variance": variance}


@router.post("/{session_id}/approve")
async def approve_balanco(session_id: str, payload: ApproveIn,
                           user: dict = Depends(require_role("gestor"))):
    if not _can_approve(user):
        raise HTTPException(403, "Apenas administrador ou super admin podem aprovar balanços (separation of duties).")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    if s["status"] != "pending_approval":
        raise HTTPException(400, f"Só é possível aprovar balanços com status pending_approval (atual={s['status']}).")
    variance = s.get("variance") or _compute_variance(
        s.get("expected_macs") or [], s.get("scanned_macs") or [])

    ignore = {m.upper() for m in (payload.ignore_macs or [])}
    adjustments: List[dict] = []

    # 1) Tratar MACs faltantes (estavam no sistema, não foram escaneados)
    for mac in variance["missing"]:
        if mac in ignore:
            continue
        if payload.missing_action == "perdido":
            # Baixa: status=perdido, location_type=baixa
            res = await db.stok_onts.update_one(
                {"company_id": cid, "mac": mac},
                {"$set": {
                    "status": "perdido",
                    "balanco_lost_at": now_iso(),
                    "balanco_lost_session": session_id,
                }},
            )
            if res.modified_count:
                adjustments.append({"mac": mac, "action": "marked_lost"})
        else:  # investigacao
            await db.stok_onts.update_one(
                {"company_id": cid, "mac": mac},
                {"$set": {
                    "balanco_flag": "investigacao",
                    "balanco_flag_session": session_id,
                    "balanco_flag_at": now_iso(),
                }},
            )
            adjustments.append({"mac": mac, "action": "flagged_investigation"})

    # 2) MACs extras (escaneados mas não estavam no sistema p/ aquele escopo)
    #    NÃO criamos ONTs automaticamente — apenas registramos auditoria.
    #    Gestor revisa caso a caso (provavelmente MAC errado ou de outra praça).
    for mac in variance["extra"]:
        if mac in ignore:
            continue
        adjustments.append({"mac": mac, "action": "extra_logged_only"})

    # 3) Ajustes de insumos (counted - expected)
    consumable_adjustments: List[dict] = []
    if s.get("include_consumables"):
        for cons_id in CONSUMABLE_IDS:
            counted = int((s.get("counted_consumables") or {}).get(cons_id, 0))
            expected = int((s.get("expected_consumables") or {}).get(cons_id, 0))
            diff = counted - expected
            if diff == 0:
                continue
            # Aplica diff na location correspondente ao escopo
            loc = None
            extra_fields: Dict[str, Any] = {}
            if s["scope_type"] == "empresa":
                loc = "empresa"
            elif s["scope_type"] == "tecnico":
                loc = s.get("scope_id")
            elif s["scope_type"] == "praca":
                # Para praça: armazena com praca_id (modelo novo)
                loc = f"praca:{s.get('scope_id')}"
                extra_fields["praca_id"] = s.get("scope_id")
            if loc:
                await db.stok_stock.update_one(
                    {"company_id": cid, "location": loc},
                    {"$set": {cons_id: counted, **extra_fields,
                              "company_id": cid, "location": loc}},
                    upsert=True,
                )
                consumable_adjustments.append({
                    "consumable_id": cons_id, "expected": expected,
                    "counted": counted, "diff": diff,
                })

    await db.stok_balanco_sessions.update_one(
        {"id": session_id, "company_id": cid},
        {"$set": {
            "status": "approved",
            "approved_at": now_iso(),
            "approved_by_email": user.get("email"),
            "approved_by_name": user.get("name") or user.get("email"),
            "approve_note": payload.note,
            "missing_action": payload.missing_action,
            "applied_adjustments": adjustments,
            "applied_consumable_adjustments": consumable_adjustments,
        }},
    )
    await _add_history(
        "balanco_approve",
        f"{session_id} — Balanço APROVADO · {len(adjustments)} ajuste(s) ONT + "
        f"{len(consumable_adjustments)} ajuste(s) insumo · ação faltantes={payload.missing_action}",
        user.get("name", "?"), "balanco", cid,
    )
    return {
        "ok": True, "status": "approved",
        "adjustments": adjustments,
        "consumable_adjustments": consumable_adjustments,
    }


@router.post("/{session_id}/cancel")
async def cancel_balanco(session_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await _load_session(session_id, cid)
    if s["status"] in ("approved", "cancelled"):
        raise HTTPException(400, f"Balanço já {s['status']}.")
    await db.stok_balanco_sessions.update_one(
        {"id": session_id, "company_id": cid},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": now_iso(),
            "cancelled_by": user.get("name") or user.get("email"),
        }},
    )
    await _add_history(
        "balanco_cancel",
        f"{session_id} — Balanço cancelado por {user.get('name', '?')}",
        user.get("name", "?"), "balanco", cid,
    )
    return {"ok": True, "status": "cancelled"}
