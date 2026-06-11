"""Stok • Transferências e seleção de ONTs para OS.

Endpoints:
- GET  /api/stok/tech/{tech_id}/onts        — ONTs no estoque do técnico (Novos+Retirados)
- GET  /api/stok/client/{client_id}/onts    — ONTs vinculadas ao cliente
- GET  /api/stok/services/{sid}/preview-mac — preview da comparação estoque ↔ SmartOLT
- GET  /api/stok/pending-transfers          — lista pendentes
- POST /api/stok/pending-transfers/{id}/approve  — aprova (move ONT pro cliente)
- POST /api/stok/pending-transfers/{id}/reject   — devolve pro estoque
- GET  /api/stok/transfers/kpis             — KPIs últimos N dias

Padronização de `source` da ONT no estoque do técnico:
- `novos`   : `transferencia_almoxarife | compra_confirm | warehouse | almoxarife`
- `retirados`: `retirada | ai_scan_retirada | ai_scan_batch`
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.stok_transfers")
router = APIRouter(prefix="/api/stok", tags=["stok-transfers"])


NOVO_SOURCES = {"transferencia_almoxarife", "compra_confirm",
                  "warehouse", "almoxarife", None, ""}
RETIRADO_SOURCES = {"retirada", "ai_scan_retirada", "ai_scan_batch"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _classify_source(src: Optional[str]) -> str:
    if src in RETIRADO_SOURCES:
        return "retirados"
    return "novos"


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# Seleção de ONTs (instalação e retirada)
# ---------------------------------------------------------------------------
@router.get("/tech/{tech_id}/onts")
async def list_tech_onts(tech_id: str, group: Optional[str] = None,
                            user: dict = Depends(require_role("gestor"))):
    """Lista ONTs no estoque do técnico, separadas por origem.

    Query `group`: 'novos' | 'retirados' | None (todos)
    Exclui ONTs marcadas como `defeito_devolver_empresa` (iter153).
    """
    cid = _cid(user)
    items = await db.stok_onts.find(
        {"company_id": cid, "location_type": "tecnico", "location_id": tech_id,
         # Bloqueia ONTs defeituosas — não podem ser instaladas em outro cliente
         "status": {"$ne": "defeito_devolver_empresa"}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    novos, retirados = [], []
    for o in items:
        klass = _classify_source(o.get("source"))
        sn = o.get("scan_sn")
        view = {
            "sn": sn or None,                   # iter197 — SN canônico
            "mac": o.get("mac"),
            "model": o.get("model"),
            "scan_sn": sn,
            "source": o.get("source"),
            "status": o.get("status"),
            "withdrawn_from_client_id": o.get("withdrawn_from_client_id"),
            "withdrawn_from_client_name": o.get("withdrawn_from_client_name"),
            "withdrawn_by_email": o.get("withdrawn_by_email"),
            "withdrawn_at": o.get("withdrawn_at"),
            "created_at": o.get("created_at"),
        }
        (novos if klass == "novos" else retirados).append(view)
    out = {"novos": novos, "retirados": retirados,
           "total": len(novos) + len(retirados)}
    if group == "novos":
        return {"items": novos, "total": len(novos)}
    if group == "retirados":
        return {"items": retirados, "total": len(retirados)}
    return out


@router.get("/client/{client_id}/onts")
async def list_client_onts(client_id: str,
                              user: dict = Depends(require_role("gestor"))):
    """Lista ONTs atualmente vinculadas ao cliente (para retirada)."""
    cid = _cid(user)
    items = await db.stok_onts.find(
        {"company_id": cid, "location_type": "cliente", "location_id": client_id},
        {"_id": 0, "mac": 1, "model": 1, "scan_sn": 1, "status": 1,
          "installed_at": 1, "created_at": 1, "client_name": 1},
    ).sort("created_at", -1).to_list(50)
    # iter197 — SN canônico
    for o in items:
        o["sn"] = o.get("scan_sn") or None
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# iter154 — ONTs Defeituosas (devolução obrigatória à empresa)
# ---------------------------------------------------------------------------
class DefectiveReturnIn(BaseModel):
    """Confirmação de devolução de ONT defeituosa ao estoque da empresa."""
    notes: Optional[str] = None


@router.get("/defective-onts")
async def list_defective_onts(user: dict = Depends(require_role("gestor"))):
    """Lista todas as ONTs marcadas como DEFEITUOSAS pendentes de devolução.

    Inclui dados de origem (cliente, técnico responsável) e o defeito
    descrito pelo técnico em campo. Devolve também as já confirmadas
    como devolvidas à empresa (status=`defeito_em_analise`) com flag
    `returned=true` para o gestor acompanhar o ciclo.
    """
    cid = _cid(user)
    pending = await db.stok_onts.find(
        {"company_id": cid,
         "status": {"$in": ["defeito_devolver_empresa", "defeito_em_analise"]}},
        {"_id": 0},
    ).sort("defective_marked_at", -1).to_list(500)

    # Resolve nomes de técnicos para apresentação
    tech_ids = list({o.get("location_id") for o in pending
                       if o.get("location_type") == "tecnico" and o.get("location_id")})
    techs_map: Dict[str, str] = {}
    if tech_ids:
        techs = await db.collaborators.find(
            {"id": {"$in": tech_ids}}, {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(tech_ids))
        techs_map = {t["id"]: t.get("name") or t["id"] for t in techs}

    items: List[Dict[str, Any]] = []
    for o in pending:
        is_returned = o.get("status") == "defeito_em_analise"
        items.append({
            "mac": o.get("mac"),
            "model": o.get("model"),
            "sn": o.get("scan_sn"),
            "tech_id": o.get("location_id") if o.get("location_type") == "tecnico" else None,
            "tech_name": techs_map.get(o.get("location_id"))
                            if o.get("location_type") == "tecnico" else None,
            "withdrawn_from_client_id": o.get("withdrawn_from_client_id"),
            "withdrawn_from_client_name": o.get("withdrawn_from_client_name"),
            "withdrawn_at": o.get("withdrawn_at"),
            "defective_marked_at": o.get("defective_marked_at"),
            "defective_marked_by": o.get("defective_marked_by"),
            "defective_reason": o.get("defective_reason"),
            "returned_to_company_at": o.get("returned_to_company_at"),
            "returned_to_company_by": o.get("returned_to_company_by"),
            "returned_notes": o.get("returned_notes"),
            "returned": is_returned,
            "status": o.get("status"),
        })
    pending_count = sum(1 for it in items if not it["returned"])
    returned_count = sum(1 for it in items if it["returned"])
    return {
        "items": items,
        "total": len(items),
        "pending_return": pending_count,
        "in_analysis": returned_count,
    }


@router.post("/defective-onts/{mac}/confirm-return")
async def confirm_defective_return(mac: str, payload: DefectiveReturnIn,
                                       user: dict = Depends(require_role("gestor"))):
    """Confirma a devolução física da ONT defeituosa ao estoque da empresa.

    Move o registro de `location_type=tecnico` para `empresa` e troca o
    status para `defeito_em_analise` — fica visível no panel mas fora
    da lista de "pendente de devolução".
    """
    cid = _cid(user)
    from routes.stok import normalize_mac
    mac_n = normalize_mac(mac or "")
    if not mac_n:
        raise HTTPException(400, "MAC inválido")
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada")
    if ont.get("status") != "defeito_devolver_empresa":
        raise HTTPException(400,
            f"ONT {mac_n} não está pendente de devolução (status atual: "
            f"{ont.get('status') or 'desconhecido'})")
    actor_email = (user.get("email") or "").strip() or None
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {
            "location_type": "empresa",
            "location_id": None,
            "status": "defeito_em_analise",
            "returned_to_company_at": now_iso(),
            "returned_to_company_by": actor_email,
            "returned_notes": (payload.notes or "").strip()[:300] or None,
        }},
    )
    return {"ok": True, "mac": mac_n, "new_status": "defeito_em_analise"}


@router.post("/defective-onts/{mac}/scrap")
async def scrap_defective_ont(mac: str,
                                  user: dict = Depends(require_role("gestor"))):
    """Marca a ONT defeituosa como sucateada (descarte definitivo).

    Útil quando o defeito é irreparável e a empresa decidiu descartar.
    """
    cid = _cid(user)
    from routes.stok import normalize_mac
    mac_n = normalize_mac(mac or "")
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada")
    if ont.get("status") not in ("defeito_devolver_empresa", "defeito_em_analise"):
        raise HTTPException(400, "Só é possível sucatear ONTs em estado de defeito")
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {"status": "sucateada",
                    "scrapped_at": now_iso(),
                    "scrapped_by": (user.get("email") or "").strip() or None}},
    )
    return {"ok": True, "mac": mac_n, "new_status": "sucateada"}


@router.post("/defective-onts/{mac}/revert")
async def revert_defective_ont(mac: str,
                                  user: dict = Depends(require_role("gestor"))):
    """iter162 — Reverte uma ONT que foi marcada como defeituosa.

    Após análise, se o gestor concluir que NÃO era defeito (falso positivo),
    move a ONT de volta para o estoque da empresa com status `disponivel`,
    limpando os flags de defeito.
    """
    cid = _cid(user)
    from routes.stok import normalize_mac
    mac_n = normalize_mac(mac or "")
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada")
    if ont.get("status") not in ("defeito_devolver_empresa", "defeito_em_analise"):
        raise HTTPException(400,
            "Só é possível reverter ONTs marcadas como defeito")
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {
            "status": "disponivel",
            "location_type": "empresa",
            "location_id": None,
            "is_defective": False,
            "reverted_at": now_iso(),
            "reverted_by": (user.get("email") or "").strip() or None,
        },
         "$unset": {"defective_marked_at": "", "defective_marked_by": "",
                     "defective_reason": ""}},
    )
    return {"ok": True, "mac": mac_n, "new_status": "disponivel"}




@router.get("/services/{service_id}/preview-mac")
async def preview_mac_match(service_id: str, mac: str,
                                user: dict = Depends(require_role("gestor"))):
    """Compara um MAC do estoque com o MAC ativo do cliente no SmartOLT.

    Retorna se a transferência seria aprovada automaticamente (`match=true`)
    ou se viraria pendente (`match=false`).
    """
    cid = _cid(user)
    svc = await db.stok_services.find_one(
        {"id": service_id, "company_id": cid}, {"_id": 0, "client_id": 1,
        "client_name": 1, "type": 1, "technician_id": 1})
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    # Importa normalize_mac sob demanda (evita import circular)
    from routes.stok import normalize_mac
    mac_n = normalize_mac(mac or "")
    if not mac_n:
        raise HTTPException(400, "MAC inválido")
    sm = await db.smartolt_onus.find_one(
        {"company_id": cid, "client_id": svc["client_id"]},
        {"_id": 0, "unique_external_id": 1, "sn": 1, "status": 1, "name": 1},
    )
    smart_raw = (sm or {}).get("unique_external_id") or (sm or {}).get("sn")
    smart_mac = normalize_mac(smart_raw) if smart_raw else None
    match = bool(smart_mac and smart_mac == mac_n)
    return {
        "match": match,
        "stock_mac": mac_n,
        "smartolt_mac": smart_mac,
        "smartolt_status": (sm or {}).get("status"),
        "smartolt_name": (sm or {}).get("name"),
        "client_name": svc.get("client_name"),
        "predicted_status": "transferencia_sucesso" if match else (
            "pendente_smartolt_ausente" if not smart_mac
            else "pendente_mac_divergente"
        ),
    }


@router.get("/services/{service_id}/client-cto-port")
async def client_cto_port(service_id: str,
                              user: dict = Depends(require_role("gestor"))):
    """Retorna a porta atual do cliente da OS, se já vinculado em alguma CTO.

    Frontend usa para decidir se mostra:
    - 'Houve troca de porta?' (cliente já tem porta)
    - 'Escolha a porta' (cliente sem porta) — apenas em instalação
    - 'Porta X será liberada' (retirada)
    """
    cid = _cid(user)
    svc = await db.stok_services.find_one(
        {"id": service_id, "company_id": cid},
        {"_id": 0, "client_id": 1, "client_name": 1, "type": 1},
    )
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    client_id = svc.get("client_id")
    current = None
    free_ports: List[Dict[str, Any]] = []
    if client_id:
        cto = await db.ctos.find_one(
            {"company_id": cid, "ports.client_subscriber_id": client_id},
            {"_id": 0, "id": 1, "name": 1, "ports": 1, "vlan": 1},
        )
        if cto:
            for p in (cto.get("ports") or []):
                if p.get("client_subscriber_id") == client_id:
                    current = {
                        "cto_id": cto["id"],
                        "cto_name": cto.get("name"),
                        "cto_vlan": cto.get("vlan"),
                        "port_number": p.get("number"),
                        "client_pppoe": p.get("client_pppoe"),
                    }
                if (p.get("status") or "free") == "free":
                    free_ports.append({"number": p.get("number")})
            free_ports.sort(key=lambda x: x.get("number") or 0)
    return {
        "service_type": svc.get("type"),
        "client_id": client_id,
        "client_name": svc.get("client_name"),
        "current_port": current,
        "free_ports_same_cto": free_ports if current else [],
    }



# ---------------------------------------------------------------------------
# Transferências Pendentes (admin)
# ---------------------------------------------------------------------------
@router.get("/pending-transfers")
async def list_pending(status: str = "pending",
                         user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    items = await db.stok_pending_transfers.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(200).to_list(200)
    # Enriquece com nome do técnico
    techs: Dict[str, str] = {}
    tech_ids = list({i.get("technician_id") for i in items if i.get("technician_id")})
    if tech_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": tech_ids}}, {"_id": 0, "id": 1, "name": 1}):
            techs[c["id"]] = c.get("name")
    for it in items:
        it["technician_name"] = techs.get(it.get("technician_id"))
    return {"items": items, "total": len(items)}


class TransferDecisionIn(BaseModel):
    note: Optional[str] = None


@router.post("/pending-transfers/{pt_id}/approve")
async def approve_pending(pt_id: str, payload: TransferDecisionIn,
                            user: dict = Depends(require_role("gestor"))):
    """Aprova a transferência pendente: move a ONT do técnico para o cliente."""
    cid = _cid(user)
    pt = await db.stok_pending_transfers.find_one(
        {"id": pt_id, "company_id": cid, "status": "pending"}, {"_id": 0})
    if not pt:
        raise HTTPException(404, "Pendência não encontrada ou já decidida")
    mac_n = pt.get("stock_mac")
    if not mac_n:
        raise HTTPException(400, "Pendência sem MAC")
    # Move a ONT
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {"location_type": "cliente",
                   "location_id": pt["client_id"],
                   "client_name": pt.get("client_name"),
                   "status": "instalada",
                   "installed_at": now_iso(),
                   "approved_by_email": user.get("email"),
                   "approved_at": now_iso()},
          "$unset": {"pending_install_to_client": "",
                     "pending_install_service_id": "",
                     "pending_transfer_id": ""}},
    )
    await db.stok_pending_transfers.update_one(
        {"id": pt_id, "company_id": cid},
        {"$set": {"status": "approved",
                   "decided_at": now_iso(),
                   "decided_by_email": user.get("email"),
                   "decision_note": (payload.note or "")[:200]}},
    )
    return {"ok": True, "status": "approved"}


@router.post("/pending-transfers/{pt_id}/reject")
async def reject_pending(pt_id: str, payload: TransferDecisionIn,
                           user: dict = Depends(require_role("gestor"))):
    """Rejeita: devolve a ONT pro estoque do técnico (limpa flags pendentes)."""
    cid = _cid(user)
    pt = await db.stok_pending_transfers.find_one(
        {"id": pt_id, "company_id": cid, "status": "pending"}, {"_id": 0})
    if not pt:
        raise HTTPException(404, "Pendência não encontrada ou já decidida")
    mac_n = pt.get("stock_mac")
    # Restaura status original
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {"status": "no_estoque"},
          "$unset": {"pending_install_to_client": "",
                     "pending_install_service_id": "",
                     "pending_transfer_id": ""}},
    )
    await db.stok_pending_transfers.update_one(
        {"id": pt_id, "company_id": cid},
        {"$set": {"status": "rejected",
                   "decided_at": now_iso(),
                   "decided_by_email": user.get("email"),
                   "decision_note": (payload.note or "")[:200]}},
    )
    return {"ok": True, "status": "rejected"}


# ---------------------------------------------------------------------------
# KPIs de transferências
# ---------------------------------------------------------------------------
@router.get("/transfers/kpis")
async def transfer_kpis(days: int = 30,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    since = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()

    # Pendentes
    pending_count = await db.stok_pending_transfers.count_documents(
        {"company_id": cid, "status": "pending"})
    approved_count = await db.stok_pending_transfers.count_documents(
        {"company_id": cid, "status": "approved", "decided_at": {"$gte": since}})
    rejected_count = await db.stok_pending_transfers.count_documents(
        {"company_id": cid, "status": "rejected", "decided_at": {"$gte": since}})

    # Sucessos diretos (ONTs instaladas no período sem pendência)
    installed_direct = await db.stok_onts.count_documents({
        "company_id": cid, "status": "instalada",
        "installed_at": {"$gte": since},
        "approved_by_email": {"$exists": False},
    })

    # Retiradas no período
    withdrawn = await db.stok_onts.count_documents({
        "company_id": cid, "status": "retirada_com_tecnico",
        "withdrawn_at": {"$gte": since},
    })

    # Quality score: % de match (sucesso direto / (sucesso direto + criadas pendentes))
    total_attempts = installed_direct + pending_count + approved_count + rejected_count
    match_pct = round(
        (installed_direct / total_attempts * 100), 1
    ) if total_attempts else 0

    # Top 5 técnicos com mais pendências
    pipeline = [
        {"$match": {"company_id": cid,
                     "created_at": {"$gte": since}}},
        {"$group": {"_id": "$technician_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_pending_techs: List[Dict[str, Any]] = []
    async for row in db.stok_pending_transfers.aggregate(pipeline):
        tid = row["_id"]
        tdoc = await db.collaborators.find_one(
            {"id": tid}, {"_id": 0, "name": 1}) if tid else None
        top_pending_techs.append({
            "technician_id": tid,
            "technician_name": (tdoc or {}).get("name") or "—",
            "count": row.get("count", 0),
        })

    return {
        "period_days": days,
        "installed_direct": installed_direct,
        "pending": pending_count,
        "approved": approved_count,
        "rejected": rejected_count,
        "withdrawn": withdrawn,
        "match_pct": match_pct,
        "top_pending_techs": top_pending_techs,
    }
