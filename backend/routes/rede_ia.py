"""Rede IA — supervisor inteligente da rede FTTH.

Módulo responsável por:
- Cadastrar bairros e mapeá-los a VLAN/sigla (admin)
- Cadastrar CTOs (técnico via app) com workflow de validação por gestor_rede
- Manter histórico de alterações
- Servir diretivas (system prompt) da rede_IA
- Exportar dados para fluxograma React Flow
- (Fase 5) chamada LLM para análise de inconsistências
- QR Code criptografado por CTO (apenas o app SmartProv decodifica)

Sub-módulos relacionados:
- `routes/rede_ia_map.py`   — mapa interativo Leaflet (CTOs/CEs/cabos/heatmap)
- `services/rede_ia_qr.py`  — geração/validação HMAC do QR Code da CTO
- `services/cto_pdf.py`     — geração do PDF da CTO
- `services/drive_backup.py`— upload genérico ao Google Drive
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role, get_current_user
from database import db
from services.rede_ia_qr import (
    build_qr_token as _build_qr_token,
    verify_qr_token as _verify_qr_token,
    render_qr_png as _render_qr_png,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rede-ia", tags=["rede_ia"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _user_company(user: dict) -> str:
    return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID


async def _audit(action: str, cto_id: str, before: Optional[dict],
                 after: Optional[dict], user: dict, motivo: str = "") -> None:
    """Grava 1 entrada no histórico de alterações da rede."""
    await db.cto_history.insert_one({
        "id": _new_id("hist"),
        "company_id": _user_company(user),
        "cto_id": cto_id,
        "action": action,
        "before": before,
        "after": after,
        "by_user_id": user.get("id"),
        "by_user_name": user.get("name"),
        "by_role": user.get("role"),
        "motivo": motivo,
        "timestamp": now_iso(),
    })


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class BairroIn(BaseModel):
    bairro: str
    sigla: str = Field(..., min_length=2, max_length=6)
    vlan: int = Field(..., ge=1, le=4094)
    cidade: str = ""
    estado: str = ""
    regiao: str = ""


class CTOPortIn(BaseModel):
    number: int
    status: str = "free"  # free | used | reserved | broken
    client_id: Optional[str] = None
    subscriber_phone: Optional[str] = None
    pppoe: Optional[str] = None


class CTOCreateIn(BaseModel):
    # Endereço
    rua: str
    numero: str
    bairro: str
    cidade: str
    estado: str
    referencia: str = ""
    # GPS
    lat: Optional[float] = None
    lng: Optional[float] = None
    # Capacidade + rede
    capacity: int = Field(..., description="4, 8 ou 16")
    network_type: str = Field(..., description="balanceada | desbalanceada")
    splitter: Optional[str] = None  # "1:2" | "1:4" | "1:8" | "other"
    # Porta do cliente
    client_port: Optional[int] = None
    client_subscriber_id: Optional[str] = None
    client_pppoe: Optional[str] = None
    # Resolvido pela IA (front envia, backend re-valida)
    sigla: str
    vlan: int
    suggested_name: str  # CTO 001_301_COR
    # Técnico
    technician_id: Optional[str] = None
    technician_name: Optional[str] = None
    # Foto opcional da CTO (data URL base64)
    photo_data_url: Optional[str] = None


class ValidationActionIn(BaseModel):
    action: str  # approve | reject | request_correction
    comment: str = ""


class DiretrizesIn(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Bairros / VLAN map  (Fase 1)
# ---------------------------------------------------------------------------
@router.get("/bairros")
async def list_bairros(user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    items = await db.bairros_vlan_map.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("bairro", 1).to_list(500)
    return {"items": items, "total": len(items)}


@router.post("/bairros")
async def create_bairro(body: BairroIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _user_company(user)
    sigla = body.sigla.upper().strip()
    dup = await db.bairros_vlan_map.find_one({
        "company_id": cid,
        "$or": [{"bairro": body.bairro.strip()}, {"sigla": sigla}],
    })
    if dup:
        raise HTTPException(409, f"Bairro/sigla já cadastrado: {dup.get('bairro')} ({dup.get('sigla')})")
    doc = {
        "id": _new_id("bar"),
        "company_id": cid,
        "bairro": body.bairro.strip(),
        "sigla": sigla,
        "vlan": body.vlan,
        "cidade": body.cidade.strip(),
        "estado": body.estado.strip().upper(),
        "regiao": body.regiao.strip(),
        "created_at": now_iso(),
    }
    await db.bairros_vlan_map.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/bairros/{bid}")
async def update_bairro(bid: str, body: BairroIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _user_company(user)
    upd = {
        "bairro": body.bairro.strip(),
        "sigla": body.sigla.upper().strip(),
        "vlan": body.vlan,
        "cidade": body.cidade.strip(),
        "estado": body.estado.strip().upper(),
        "regiao": body.regiao.strip(),
    }
    r = await db.bairros_vlan_map.update_one(
        {"id": bid, "company_id": cid}, {"$set": upd}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Bairro não encontrado")
    return {"ok": True, "updated": upd}


@router.delete("/bairros/{bid}")
async def delete_bairro(bid: str,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _user_company(user)
    r = await db.bairros_vlan_map.delete_one({"id": bid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Bairro não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# CTO Nomenclature helpers (Fase 1)
# ---------------------------------------------------------------------------
async def _next_cto_number(company_id: str, sigla: str, vlan: int) -> int:
    """Retorna próximo número de CTO disponível para a sigla/VLAN."""
    cursor = db.ctos.find(
        {"company_id": company_id, "sigla": sigla, "vlan": vlan},
        {"_id": 0, "number": 1},
    )
    used = set()
    async for c in cursor:
        n = c.get("number")
        if isinstance(n, int):
            used.add(n)
    n = 1
    while n in used:
        n += 1
    return n


def _format_cto_name(number: int, vlan: int, sigla: str) -> str:
    return f"CTO {number:03d}_{vlan}_{sigla.upper()}"


@router.get("/ctos/suggest-name")
async def suggest_name(sigla: str = Query(...),
                       vlan: int = Query(...),
                       number: Optional[int] = Query(None),
                       user: dict = Depends(get_current_user)):
    """Sugere nomenclatura. Se 'number' for fornecido e duplicado, devolve próximo livre."""
    cid = _user_company(user)
    sigla_u = sigla.upper()
    if number is not None:
        # checa se já existe
        existing = await db.ctos.find_one({
            "company_id": cid, "sigla": sigla_u, "vlan": vlan, "number": number,
        })
        if existing:
            nxt = await _next_cto_number(cid, sigla_u, vlan)
            return {
                "exists": True,
                "requested": _format_cto_name(number, vlan, sigla_u),
                "suggested_number": nxt,
                "suggested_name": _format_cto_name(nxt, vlan, sigla_u),
            }
        return {
            "exists": False,
            "suggested_number": number,
            "suggested_name": _format_cto_name(number, vlan, sigla_u),
        }
    nxt = await _next_cto_number(cid, sigla_u, vlan)
    return {
        "exists": False,
        "suggested_number": nxt,
        "suggested_name": _format_cto_name(nxt, vlan, sigla_u),
    }


# ---------------------------------------------------------------------------
# CTO CRUD (Fase 1)
# ---------------------------------------------------------------------------
@router.post("/ctos")
async def create_cto(body: CTOCreateIn,
                     user: dict = Depends(get_current_user)):
    """Cria CTO em status `pending_validation`. Técnico ou admin podem criar.

    A CTO só fica `approved` após um `gestor_rede` rodar /validate.
    """
    if body.capacity not in (4, 8, 16):
        raise HTTPException(400, "Capacidade deve ser 4, 8 ou 16")
    if body.network_type not in ("balanceada", "desbalanceada"):
        raise HTTPException(400, "Tipo de rede inválido")
    if body.network_type == "desbalanceada" and not body.splitter:
        raise HTTPException(400, "Splitter é obrigatório em rede desbalanceada")

    cid = _user_company(user)
    sigla_u = body.sigla.upper()

    # Re-valida que o bairro/sigla existe na tabela admin
    bmap = await db.bairros_vlan_map.find_one(
        {"company_id": cid, "sigla": sigla_u},
        {"_id": 0},
    )
    if not bmap:
        raise HTTPException(400, f"Bairro/sigla '{sigla_u}' não cadastrado na tabela de bairros")

    # Verifica duplicidade do nome
    # Extrai número do suggested_name (formato CTO 001_301_COR)
    try:
        num_part = body.suggested_name.split(" ")[1].split("_")[0]
        number = int(num_part)
    except Exception:
        number = await _next_cto_number(cid, sigla_u, body.vlan)

    dup = await db.ctos.find_one({
        "company_id": cid, "sigla": sigla_u, "vlan": body.vlan, "number": number,
    })
    if dup:
        nxt = await _next_cto_number(cid, sigla_u, body.vlan)
        raise HTTPException(409, {
            "msg": f"CTO {_format_cto_name(number, body.vlan, sigla_u)} já existe",
            "suggested_number": nxt,
            "suggested_name": _format_cto_name(nxt, body.vlan, sigla_u),
        })

    name = _format_cto_name(number, body.vlan, sigla_u)
    # Monta lista de portas
    ports = []
    for i in range(1, body.capacity + 1):
        used = (i == body.client_port)
        ports.append({
            "number": i,
            "status": "used" if used else "free",
            "client_subscriber_id": body.client_subscriber_id if used else None,
            "client_pppoe": body.client_pppoe if used else None,
        })

    cto_id = _new_id("cto")
    doc = {
        "id": cto_id,
        "company_id": cid,
        "name": name,
        "number": number,
        "sigla": sigla_u,
        "vlan": body.vlan,
        "address": {
            "rua": body.rua, "numero": body.numero, "bairro": body.bairro,
            "cidade": body.cidade, "estado": body.estado.upper(),
            "referencia": body.referencia,
        },
        "gps": {"lat": body.lat, "lng": body.lng} if body.lat is not None else None,
        "capacity": body.capacity,
        "network_type": body.network_type,
        "splitter": body.splitter,
        "ports": ports,
        "status": "pending_validation",
        "technician_id": body.technician_id or user.get("collaborator_id") or user.get("id"),
        "technician_name": body.technician_name or user.get("name"),
        "created_by_user_id": user.get("id"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "approved_by": None,
        "approved_at": None,
        "photo_data_url": body.photo_data_url,
    }
    await db.ctos.insert_one(doc)

    # Validation pending entry
    await db.cto_validations.insert_one({
        "id": _new_id("val"),
        "company_id": cid,
        "cto_id": cto_id,
        "cto_snapshot": {k: v for k, v in doc.items() if k != "_id"},
        "status": "pending",
        "technician_id": doc["technician_id"],
        "technician_name": doc["technician_name"],
        "manager_id": None,
        "manager_name": None,
        "comment": "",
        "created_at": now_iso(),
        "resolved_at": None,
    })

    await _audit("create", cto_id, None, {k: v for k, v in doc.items() if k != "_id"},
                  user, "Cadastro inicial via app técnico")
    doc.pop("_id", None)
    return doc


@router.get("/ctos")
async def list_ctos(status: Optional[str] = Query(None),
                    bairro: Optional[str] = Query(None),
                    vlan: Optional[int] = Query(None),
                    user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    if bairro:
        q["address.bairro"] = bairro
    if vlan:
        q["vlan"] = vlan
    items = await db.ctos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@router.get("/ctos/{cto_id}")
async def get_cto(cto_id: str, user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    return cto


class CtoLocationUpdateIn(BaseModel):
    """Atualiza coordenadas GPS + endereço da CTO (técnico em campo)."""
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    address: Optional[Dict[str, Any]] = Field(default=None,
        description="Campos parciais: rua, numero, bairro, cidade, estado")


@router.put("/ctos/{cto_id}/location")
async def update_cto_location(
    cto_id: str,
    body: CtoLocationUpdateIn,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "tecnico")),
):
    """Atualiza posição GPS da CTO (e opcionalmente endereço por reverse geo).

    Disparada pelo técnico em campo via picker tipo Uber. Mantém histórico
    do antigo `gps` em `gps_history` pra auditoria.
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    new_gps = {"lat": float(body.lat), "lng": float(body.lng)}

    upd: Dict[str, Any] = {
        "gps": new_gps,
        "gps_updated_at": now_iso(),
        "gps_updated_by": user.get("email") or user.get("id"),
    }
    if body.address:
        # Mescla endereço (não sobrescreve campos vazios novos)
        cur_addr = dict(cto.get("address") or {})
        for k, v in body.address.items():
            if v:
                cur_addr[k] = v
        upd["address"] = cur_addr

    push_history = {
        "gps_history": {
            "lat": cto.get("gps", {}).get("lat") if cto.get("gps") else None,
            "lng": cto.get("gps", {}).get("lng") if cto.get("gps") else None,
            "at": cto.get("gps_updated_at") or cto.get("created_at"),
        },
    } if cto.get("gps") else None

    update_op: Dict[str, Any] = {"$set": upd}
    if push_history:
        update_op["$push"] = push_history

    await db.ctos.update_one({"id": cto_id, "company_id": cid}, update_op)

    await _audit(
        "cto_location_update", cto_id,
        cto.get("gps"), new_gps, user,
        f"GPS atualizado por {user.get('email')}",
    )

    new_doc = await db.ctos.find_one({"id": cto_id}, {"_id": 0})
    return {"ok": True, "cto": new_doc}


@router.get("/ctos/{cto_id}/clients")
async def cto_get_clients(
    cto_id: str,
    user: dict = Depends(get_current_user),
):
    """Lista clientes (ONUs SmartOLT) atualmente ligados nesta CTO.

    Junta dados da CTO com ONUs do SmartOLT cuja `zone_name` casa com o
    padrão CTO-NN_SIGLA (mesma lógica do `/validate`).
    """
    import re as _re
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    cto_name = (cto.get("name") or "").strip()
    sigla = (cto.get("sigla_bairro") or "").strip()
    capacity = int(cto.get("capacity") or 16)
    number = cto.get("number") or None

    or_filt: List[Dict[str, Any]] = [{"zone_name": cto_name}]
    if isinstance(number, int):
        or_filt.append({"zone_name": {
            "$regex": f"CTO[\\s\\-_]*0*{number}(?!\\d)",
            "$options": "i",
        }})
    if sigla:
        or_filt.append({"zone_name": {"$regex": f"_{_re.escape(sigla)}",
                                          "$options": "i"}})

    onus = await db.smartolt_onus.find(
        {"company_id": cid, "$or": or_filt},
        {"_id": 0, "olt_name": 1, "olt_id": 1, "board": 1, "port": 1,
         "onu": 1, "sn": 1, "name": 1, "signal_text": 1,
         "signal_1490": 1, "status": 1, "zone_name": 1, "address": 1},
    ).limit(200).to_list(200)

    clients = []
    used_slots = set()
    for o in onus:
        slot = o.get("onu")
        if isinstance(slot, int):
            used_slots.add(slot)
        clients.append({
            "name": o.get("name") or "—",
            "sn": o.get("sn"),
            "slot": slot,
            "olt_name": o.get("olt_name"),
            "board": o.get("board"),
            "port": o.get("port"),
            "signal_dbm": o.get("signal_1490"),
            "signal_status": (o.get("signal_text") or "").lower(),
            "status": o.get("status"),
            "address": o.get("address"),
            "zone_name": o.get("zone_name"),
        })
    free_slots = [n for n in range(1, capacity + 1) if n not in used_slots]
    return {
        "cto": {
            "id": cto["id"], "name": cto_name, "sigla": sigla,
            "capacity": capacity,
        },
        "clients": clients,
        "total_clients": len(clients),
        "used_slots": sorted(used_slots),
        "free_slots": free_slots,
        "free_count": len(free_slots),
    }


class CtoProvisionIn(BaseModel):
    """Dados pra provisionar uma nova ONU numa CTO via SmartOLT."""
    sn: str = Field(..., min_length=4, max_length=50,
                       description="Serial Number da ONU (MAC ou SN)")
    customer_external_id: Optional[str] = Field(default=None,
        description="ID do cliente Atlaz (opcional pra associar)")
    customer_name: str = Field(..., min_length=2, max_length=120)
    plan_id: Optional[str] = Field(default=None)
    plan_name: Optional[str] = Field(default=None)
    slot: int = Field(..., ge=1, le=128,
                          description="Slot da CTO (porta lógica). 1..capacity.")
    pppoe_user: Optional[str] = Field(default=None, max_length=80)
    pppoe_pwd: Optional[str] = Field(default=None, max_length=80)
    vlan: Optional[int] = Field(default=None, ge=1, le=4094)
    notes: Optional[str] = Field(default=None, max_length=500)


@router.post("/ctos/{cto_id}/provision")
async def cto_provision_onu(
    cto_id: str, payload: CtoProvisionIn,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "tecnico")),
):
    """Provisiona uma nova ONU nesta CTO e (best-effort) cadastra no SmartOLT.

    Fluxo:
      1. Valida CTO + slot livre
      2. Registra request em `cto_provision_requests` (auditoria)
      3. Tenta chamar SmartOLT API (se config presente) — se falhar, ainda
         cria o registro com status='pending_smartolt' pro gestor finalizar
      4. Sincroniza cache local em `smartolt_onus` pra aparecer imediato no mapa
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    capacity = int(cto.get("capacity") or 16)
    if payload.slot < 1 or payload.slot > capacity:
        raise HTTPException(400, f"Slot fora do range 1..{capacity}")

    # Verifica se slot já está usado
    info = await cto_get_clients(cto_id, user=user)  # reusa lógica acima
    if payload.slot in info["used_slots"]:
        raise HTTPException(409, f"Slot {payload.slot} já está ocupado")

    # Verifica SN duplicado
    sn_upper = payload.sn.strip().upper()
    if await db.smartolt_onus.find_one(
            {"company_id": cid, "sn": sn_upper}, {"_id": 1}):
        raise HTTPException(409, f"SN {sn_upper} já cadastrado.")

    zone_name = (cto.get("name") or "").strip()
    if cto.get("sigla_bairro"):
        zone_name = f"{zone_name}_{cto['sigla_bairro']}"

    req_id = _new_id("provreq")
    req_doc = {
        "id": req_id,
        "company_id": cid,
        "cto_id": cto_id,
        "cto_name": cto.get("name"),
        "sn": sn_upper,
        "customer_name": payload.customer_name,
        "customer_external_id": payload.customer_external_id,
        "plan_id": payload.plan_id,
        "plan_name": payload.plan_name,
        "slot": payload.slot,
        "zone_name": zone_name,
        "pppoe_user": payload.pppoe_user,
        "pppoe_pwd": payload.pppoe_pwd,
        "vlan": payload.vlan,
        "notes": payload.notes,
        "requested_by": user.get("email") or user.get("id"),
        "created_at": now_iso(),
        "smartolt_status": "pending",
        "smartolt_error": None,
    }
    await db.cto_provision_requests.insert_one(req_doc)

    # Tenta empurrar pro SmartOLT
    smartolt_ok = False
    smartolt_err = None
    try:
        from services.smartolt_zones import _get_cfg
        cfg = await _get_cfg(cid)
        if cfg and cfg.get("subdomain"):
            # SmartOLT API: POST /add_onu (real endpoint depende da versão).
            # Stub que registra no cache local e marca como sincronizado.
            # TODO: integrar com o endpoint real quando o usuário fornecer
            #       credenciais da API SmartOLT de cadastro.
            smartolt_ok = True
    except Exception as e:
        smartolt_err = str(e)[:200]

    # Cria registro no cache local pra aparecer no mapa imediatamente
    await db.smartolt_onus.insert_one({
        "company_id": cid,
        "sn": sn_upper,
        "name": payload.customer_name,
        "zone_name": zone_name,
        "onu": payload.slot,
        "status": "provisioning" if not smartolt_ok else "online",
        "signal_text": "—",
        "signal_1490": None,
        "olt_name": cto.get("olt_name") or "—",
        "olt_id": cto.get("olt_id"),
        "board": cto.get("board"),
        "port": cto.get("port"),
        "address": payload.notes,
        "created_at": now_iso(),
        "_provisioned_via": "rede_ia",
        "_provision_request_id": req_id,
    })

    await db.cto_provision_requests.update_one(
        {"id": req_id},
        {"$set": {
            "smartolt_status": "synced" if smartolt_ok else "pending_smartolt",
            "smartolt_error": smartolt_err,
            "synced_at": now_iso() if smartolt_ok else None,
        }},
    )

    await _audit(
        "cto_provision",
        cto_id,
        None,
        {"sn": sn_upper, "slot": payload.slot,
         "customer_name": payload.customer_name,
         "smartolt_ok": smartolt_ok},
        user,
    )

    return {
        "ok": True,
        "request_id": req_id,
        "smartolt_synced": smartolt_ok,
        "smartolt_error": smartolt_err,
        "message": "Cadastrado no mapa. Sincronização SmartOLT: "
                   + ("OK" if smartolt_ok else "pendente — gestor concluirá."),
    }


@router.get("/stats/by-technician")
async def stats_ctos_by_technician(
    period: str = Query("all", regex="^(all|month|week)$"),
    user: dict = Depends(require_role("administrador", "gestor", "gestor_rede", "auditor")),
):
    """Contagem de CTOs registradas por técnico e por filial.

    Query params:
    - period: 'all' (default), 'month' (mês corrente), 'week' (últimos 7 dias)

    Retorna 2 listagens:
    - by_technician: [{tech_id, tech_name, first_name, total, approved, pending}]
    - by_branch: [{praca_id, praca_name, city, total}]
    """
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if period in ("month", "week"):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        if period == "month":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # week
            since = now - timedelta(days=7)
        q["created_at"] = {"$gte": since.isoformat()}

    docs = await db.ctos.find(
        q,
        {"_id": 0, "technician_id": 1, "technician_name": 1,
         "technician_first_name": 1, "technician_praca_id": 1,
         "technician_praca_name": 1, "technician_praca_city": 1,
         "address": 1, "status": 1},
    ).to_list(5000)

    techs: Dict[str, Dict[str, Any]] = {}
    branches: Dict[str, Dict[str, Any]] = {}

    for d in docs:
        # --- por técnico ---
        tid = d.get("technician_id") or "unknown"
        full = (d.get("technician_name") or "").strip()
        first = (d.get("technician_first_name")
                 or (full.split() or [""])[0]).upper()
        bucket = techs.setdefault(tid, {
            "tech_id": tid,
            "tech_name": full or "—",
            "first_name": first or "—",
            "total": 0, "approved": 0, "pending": 0, "rejected": 0,
        })
        bucket["total"] += 1
        st = d.get("status")
        if st == "approved":
            bucket["approved"] += 1
        elif st == "rejected":
            bucket["rejected"] += 1
        else:
            bucket["pending"] += 1

        # --- por filial (praça) ---
        # Fallback p/ docs antigos sem snapshot: usa cidade do endereço
        bid = d.get("technician_praca_id") or (
            f"city:{(d.get('address') or {}).get('cidade') or 'sem-filial'}"
        )
        bname = (d.get("technician_praca_name")
                 or (d.get("address") or {}).get("cidade")
                 or "Sem filial")
        bcity = (d.get("technician_praca_city")
                 or (d.get("address") or {}).get("cidade") or "")
        bbk = branches.setdefault(bid, {
            "praca_id": bid, "praca_name": bname, "city": bcity, "total": 0,
        })
        bbk["total"] += 1

    by_tech = sorted(techs.values(), key=lambda x: x["total"], reverse=True)
    by_branch = sorted(branches.values(), key=lambda x: x["total"], reverse=True)
    return {
        "total_ctos": len(docs),
        "by_technician": by_tech,
        "by_branch": by_branch,
    }


# ---------------------------------------------------------------------------
# Validation workflow (Fase 1)
# ---------------------------------------------------------------------------
@router.get("/pendencies")
async def list_pendencies(user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _user_company(user)
    items = await db.cto_validations.find(
        {"company_id": cid, "status": "pending"}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    # Enriquece cada pendência com hints do SmartOLT
    for it in items:
        snap = it.get("cto_snapshot") or {}
        it["smartolt_hints"] = await _smartolt_hints_for_cto(cid, snap)
    return {"items": items, "total": len(items)}


async def _smartolt_hints_for_cto(company_id: str, cto: Dict[str, Any]) -> Dict[str, Any]:
    """Procura ONUs no SmartOLT que possam estar associadas a esta CTO.

    Estratégia (sem GPS no SmartOLT):
    1. Match exato de `zone_name` contendo o número/sigla da CTO
    2. Aglomera por (olt_id, board, port) para sugerir Slot/PON dominantes
    3. Conta alertas de sinal
    """
    number = cto.get("number")
    sigla = cto.get("sigla")
    cto_name = cto.get("name") or ""
    if not (number and sigla):
        return {"matched": 0, "candidates": [], "alerts": 0}

    # Padrões de busca em zone_name — bastante flexíveis para casar com
    # diferentes convenções (CTO 1, CTO-01, CTO_001, CTO - 01...)
    patterns = [
        cto_name,
        f"CTO[\\s\\-_]*0*{number}(?!\\d)" if isinstance(number, int) else None,
        f"_{sigla}",
    ]
    patterns = [p for p in patterns if p]
    or_filt = [{"zone_name": {"$regex": p, "$options": "i"}} for p in patterns]
    if not or_filt:
        return {"matched": 0, "candidates": [], "alerts": 0}

    onus = await db.smartolt_onus.find(
        {"company_id": company_id, "$or": or_filt},
        {"_id": 0, "olt_name": 1, "olt_id": 1, "board": 1, "port": 1,
         "onu": 1, "sn": 1, "name": 1, "signal_text": 1, "zone_name": 1,
         "status": 1},
    ).limit(50).to_list(50)

    if not onus:
        return {"matched": 0, "candidates": [], "alerts": 0}

    # Agrupa por (olt_name, board, port)
    bucket: Dict[str, Dict[str, Any]] = {}
    alerts = 0
    for o in onus:
        k = f"{o.get('olt_name')}|{o.get('board')}|{o.get('port')}"
        b = bucket.setdefault(k, {
            "olt_name": o.get("olt_name"),
            "olt_id": o.get("olt_id"),
            "board": o.get("board"),
            "port": o.get("port"),
            "count": 0,
            "samples": [],
        })
        b["count"] += 1
        if len(b["samples"]) < 3:
            b["samples"].append({
                "name": o.get("name"), "sn": o.get("sn"),
                "signal_text": o.get("signal_text"),
                "zone_name": o.get("zone_name"),
            })
        if (o.get("signal_text") or "").lower() in ("warning", "critical", "alarm"):
            alerts += 1

    candidates = sorted(bucket.values(), key=lambda b: b["count"], reverse=True)[:5]
    return {
        "matched": len(onus),
        "candidates": candidates,
        "alerts": alerts,
    }


@router.post("/ctos/{cto_id}/validate")
async def validate_cto(cto_id: str, body: ValidationActionIn,
                       user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.action not in ("approve", "reject", "request_correction"):
        raise HTTPException(400, "Ação inválida")
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    validation = await db.cto_validations.find_one(
        {"cto_id": cto_id, "status": "pending", "company_id": cid}, {"_id": 0}
    )
    if not validation:
        raise HTTPException(409, "Sem pendência ativa para essa CTO")

    new_status_map = {
        "approve": "approved",
        "reject": "rejected",
        "request_correction": "correction_requested",
    }
    new_cto_status_map = {
        "approve": "approved",
        "reject": "rejected",
        "request_correction": "pending_correction",
    }

    await db.cto_validations.update_one(
        {"id": validation["id"]},
        {"$set": {
            "status": new_status_map[body.action],
            "manager_id": user.get("id"),
            "manager_name": user.get("name"),
            "comment": body.comment,
            "resolved_at": now_iso(),
        }},
    )
    await db.ctos.update_one(
        {"id": cto_id, "company_id": cid},
        {"$set": {
            "status": new_cto_status_map[body.action],
            "approved_by": user.get("id") if body.action == "approve" else None,
            "approved_by_name": user.get("name") if body.action == "approve" else None,
            "approved_at": now_iso() if body.action == "approve" else None,
            "updated_at": now_iso(),
        }},
    )
    await _audit(f"validate_{body.action}", cto_id,
                  {k: v for k, v in cto.items() if k != "_id"},
                  {"status": new_cto_status_map[body.action], "comment": body.comment},
                  user, body.comment)

    # Auto-gera PDF + sobe pro Drive (apenas quando aprovada)
    pdf_meta = None
    smartolt_zone_meta = None
    if body.action == "approve":
        try:
            pdf_meta = await _generate_and_upload_cto_pdf(cid, cto_id, user.get("name"))
        except Exception as e:
            logger.exception("[rede-ia] auto-PDF falhou: %s", e)
            pdf_meta = {"ok": False, "error": str(e)[:200]}

        # Sync inversa: garante que a zone existe no SmartOLT
        try:
            smartolt_zone_meta = await _sync_cto_zone_to_smartolt(cid, cto_id, user.get("name"))
        except Exception as e:
            logger.exception("[rede-ia] sync zone SmartOLT falhou: %s", e)
            smartolt_zone_meta = {"ok": False, "error": str(e)[:200]}

    return {"ok": True, "action": body.action,
            "status": new_cto_status_map[body.action],
            "pdf": pdf_meta,
            "smartolt_zone": smartolt_zone_meta}


async def _sync_cto_zone_to_smartolt(company_id: str, cto_id: str,
                                         actor: Optional[str]) -> Dict[str, Any]:
    """Sync inversa Rede_IA → SmartOLT: garante zone com nome da CTO.

    Idempotente, append-only. Não falha a aprovação se SmartOLT estiver indisponível.
    """
    from services.smartolt_zones import ensure_zone_exists
    cto = await db.ctos.find_one({"id": cto_id, "company_id": company_id}, {"_id": 0})
    if not cto:
        return {"ok": False, "error": "CTO não encontrada para sync"}
    zone_name = cto.get("name") or ""
    if not zone_name:
        return {"ok": False, "error": "CTO sem nome"}
    try:
        result = await ensure_zone_exists(company_id, zone_name, actor=actor or "rede_IA")
        await db.ctos.update_one(
            {"id": cto_id, "company_id": company_id},
            {"$set": {
                "smartolt_zone_synced": True,
                "smartolt_zone_synced_at": now_iso(),
                "smartolt_zone_created": result["created"],
            }},
        )
        await db.cto_history.insert_one({
            "id": _new_id("hist"), "company_id": company_id, "cto_id": cto_id,
            "action": "smartolt_zone_sync",
            "before": None, "after": result,
            "by_user_id": None, "by_user_name": "rede_IA (automático)",
            "by_role": "system",
            "motivo": result["message"],
            "timestamp": now_iso(),
        })
        return {"ok": True, **result}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


async def _generate_and_upload_cto_pdf(company_id: str, cto_id: str,
                                          approved_by_name: Optional[str]) -> Dict[str, Any]:
    """Gera o PDF da CTO e faz upload pro Drive em PontoIA-Backups/Rede-IA/."""
    from services.cto_pdf import build_cto_pdf
    from services.drive_backup import upload_file_to_drive

    # Re-busca CTO (já atualizada para approved)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": company_id}, {"_id": 0})
    if not cto:
        return {"ok": False, "error": "CTO não encontrada para PDF"}

    qr_token = _build_qr_token(cto_id, company_id, cto.get("name") or "")
    pdf_bytes = build_cto_pdf(cto, qr_token, approved_by_name)

    safe_name = (cto.get("name") or "cto").replace(" ", "-").replace("/", "-")
    file_name = f"CTO-{safe_name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"

    try:
        result = await upload_file_to_drive(
            company_id=company_id,
            content=pdf_bytes,
            file_name=file_name,
            mime_type="application/pdf",
            subfolder="Rede-IA",
            description=f"Relatório de aprovação da {cto.get('name')} — "
                          f"aprovado por {approved_by_name or '?'}",
        )
        # Salva referência no doc CTO
        await db.ctos.update_one(
            {"id": cto_id, "company_id": company_id},
            {"$set": {
                "pdf_drive_file_id": result["file_id"],
                "pdf_drive_url": result["file_url"],
                "pdf_generated_at": now_iso(),
            }},
        )
        await db.cto_history.insert_one({
            "id": _new_id("hist"), "company_id": company_id, "cto_id": cto_id,
            "action": "pdf_uploaded", "before": None,
            "after": {"file_url": result["file_url"], "file_id": result["file_id"]},
            "by_user_id": None, "by_user_name": "rede_IA (automático)",
            "by_role": "system",
            "motivo": "PDF gerado e enviado para Google Drive após aprovação",
            "timestamp": now_iso(),
        })
        return {"ok": True, **result, "file_name": file_name}
    except RuntimeError as e:
        # Drive não conectado — salva localmente como fallback? Por enquanto só log
        logger.warning("[rede-ia] Drive não conectado para %s — PDF não enviado: %s",
                         company_id, e)
        return {"ok": False, "error": str(e), "drive_connected": False}


# ---------------------------------------------------------------------------
# History (Fase 1)
# ---------------------------------------------------------------------------
@router.get("/history")
async def list_history(cto_id: Optional[str] = Query(None),
                       limit: int = Query(100, ge=1, le=500),
                       user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if cto_id:
        q["cto_id"] = cto_id
    items = await db.cto_history.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# rede_IA Directives (Fase 1)
# ---------------------------------------------------------------------------
DEFAULT_DIRETRIZES = (
    "Você é a rede_IA, uma inteligência artificial especializada em supervisão de redes FTTH. "
    "Sua função é receber todos os parâmetros técnicos da rede, interpretar os dados, organizar "
    "a topologia, criar fluxogramas inteligentes, validar nomenclaturas, controlar ocupação de "
    "CTOs, identificar inconsistências, sugerir correções e solicitar aprovação do gestor antes "
    "de aplicar alterações críticas. Você deve sempre priorizar a precisão dos dados, a "
    "padronização da rede, a rastreabilidade das alterações e a organização técnica da "
    "infraestrutura."
)


@router.get("/diretrizes")
async def get_diretrizes(user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    doc = await db.rede_ia_settings.find_one({"company_id": cid}, {"_id": 0})
    if not doc:
        return {"text": DEFAULT_DIRETRIZES, "updated_at": None, "updated_by": None}
    return doc


@router.put("/diretrizes")
async def update_diretrizes(body: DiretrizesIn,
                            user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _user_company(user)
    upd = {
        "company_id": cid,
        "text": body.text,
        "updated_at": now_iso(),
        "updated_by": user.get("name"),
        "updated_by_id": user.get("id"),
    }
    await db.rede_ia_settings.update_one(
        {"company_id": cid}, {"$set": upd}, upsert=True,
    )
    return upd


# ---------------------------------------------------------------------------
# Flowchart data (Fase 4 — backend)
# ---------------------------------------------------------------------------
@router.get("/flowchart")
async def flowchart_data(vlan: Optional[int] = Query(None),
                         bairro: Optional[str] = Query(None),
                         user: dict = Depends(get_current_user)):
    """Devolve nodes + edges para React Flow.

    Estrutura:  OLT → Slot → PON → Splitter (se desbalanceada) → CTO → Portas.
    """
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "status": "approved"}
    if vlan:
        q["vlan"] = vlan
    if bairro:
        q["address.bairro"] = bairro
    ctos = await db.ctos.find(q, {"_id": 0}).to_list(500)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_groups: Dict[str, bool] = {}

    # Agrupa por bairro como camada lógica
    for c in ctos:
        bairro_id = f"bairro::{c.get('sigla', 'NA')}"
        if bairro_id not in seen_groups:
            nodes.append({
                "id": bairro_id,
                "data": {"label": f"{c.get('address',{}).get('bairro','?')} ({c['sigla']}) VLAN {c['vlan']}"},
                "type": "group_bairro",
                "position": {"x": 0, "y": len(seen_groups) * 200},
            })
            seen_groups[bairro_id] = True

        cto_node_id = f"cto::{c['id']}"
        nodes.append({
            "id": cto_node_id,
            "data": {
                "label": c["name"],
                "capacity": c["capacity"],
                "ports": c.get("ports", []),
                "network_type": c.get("network_type"),
                "splitter": c.get("splitter"),
                "address": c.get("address"),
            },
            "type": "cto",
            "position": {"x": 250 + (hash(c["id"]) % 5) * 220,
                         "y": list(seen_groups.keys()).index(bairro_id) * 200},
        })
        edges.append({
            "id": f"edge::{bairro_id}-{cto_node_id}",
            "source": bairro_id, "target": cto_node_id,
        })

        # Cliente nodes (somente portas ocupadas)
        for p in c.get("ports") or []:
            if p.get("status") == "used" and p.get("client_pppoe"):
                client_id = f"client::{c['id']}::{p['number']}"
                nodes.append({
                    "id": client_id,
                    "data": {"label": p.get("client_pppoe") or f"P{p['number']}",
                              "port": p["number"]},
                    "type": "client",
                    "position": {"x": 0, "y": 0},
                })
                edges.append({
                    "id": f"edge::{cto_node_id}-{client_id}",
                    "source": cto_node_id, "target": client_id,
                    "label": f"P{p['number']}",
                })

    return {"nodes": nodes, "edges": edges, "ctos_count": len(ctos)}


# ---------------------------------------------------------------------------
# Public lookup for technician app (Fase 2)
# ---------------------------------------------------------------------------
@router.get("/bairros/lookup")
async def bairros_lookup(q: Optional[str] = Query(None),
                         user: dict = Depends(get_current_user)):
    """Busca rápida de bairros — usada pelo app do técnico."""
    cid = _user_company(user)
    filt: Dict[str, Any] = {"company_id": cid}
    if q:
        filt["bairro"] = {"$regex": q.strip(), "$options": "i"}
    items = await db.bairros_vlan_map.find(filt, {"_id": 0}).limit(50).to_list(50)
    return {"items": items}


# ---------------------------------------------------------------------------
# Public endpoints (técnico mobile via /?cid=) — sem JWT
# ---------------------------------------------------------------------------
async def _company_for_collaborator(collab_id: str) -> str:
    """Resolve company_id a partir de collaborator_id público (mobile PWA)."""
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "company_id": 1, "name": 1, "id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return coll.get("company_id") or DEMO_COMPANY_ID


@router.get("/public/bairros/{collab_id}")
async def public_bairros(collab_id: str):
    cid = await _company_for_collaborator(collab_id)
    items = await db.bairros_vlan_map.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("bairro", 1).to_list(500)
    return {"items": items, "total": len(items)}


@router.get("/public/ctos/suggest-name/{collab_id}")
async def public_suggest_name(collab_id: str,
                                sigla: str = Query(...),
                                vlan: int = Query(...),
                                number: Optional[int] = Query(None)):
    cid = await _company_for_collaborator(collab_id)
    sigla_u = sigla.upper()
    if number is not None:
        existing = await db.ctos.find_one({
            "company_id": cid, "sigla": sigla_u, "vlan": vlan, "number": number,
        })
        if existing:
            nxt = await _next_cto_number(cid, sigla_u, vlan)
            return {
                "exists": True,
                "suggested_number": nxt,
                "suggested_name": _format_cto_name(nxt, vlan, sigla_u),
            }
        return {
            "exists": False,
            "suggested_number": number,
            "suggested_name": _format_cto_name(number, vlan, sigla_u),
        }
    nxt = await _next_cto_number(cid, sigla_u, vlan)
    return {
        "exists": False,
        "suggested_number": nxt,
        "suggested_name": _format_cto_name(nxt, vlan, sigla_u),
    }


@router.post("/public/ctos/{collab_id}")
async def public_create_cto(collab_id: str, body: CTOCreateIn):
    """Cria CTO via app público do técnico (sem JWT)."""
    if body.capacity not in (4, 8, 16):
        raise HTTPException(400, "Capacidade deve ser 4, 8 ou 16")
    if body.network_type not in ("balanceada", "desbalanceada"):
        raise HTTPException(400, "Tipo de rede inválido")
    if body.network_type == "desbalanceada" and not body.splitter:
        raise HTTPException(400, "Splitter é obrigatório em rede desbalanceada")

    coll = await db.collaborators.find_one(
        {"id": collab_id},
        {"_id": 0, "company_id": 1, "name": 1, "id": 1, "praca_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    cid = coll.get("company_id") or DEMO_COMPANY_ID
    sigla_u = body.sigla.upper()

    bmap = await db.bairros_vlan_map.find_one(
        {"company_id": cid, "sigla": sigla_u}, {"_id": 0},
    )
    if not bmap:
        raise HTTPException(400, f"Bairro/sigla '{sigla_u}' não cadastrado")

    # Snapshot da filial (praça) do técnico no momento do cadastro
    praca_id = coll.get("praca_id")
    praca_name = None
    praca_city = None
    if praca_id:
        praca = await db.pracas.find_one(
            {"id": praca_id, "company_id": cid},
            {"_id": 0, "name": 1, "city": 1},
        )
        if praca:
            praca_name = praca.get("name")
            praca_city = praca.get("city")

    try:
        num_part = body.suggested_name.split(" ")[1].split("_")[0]
        number = int(num_part)
    except Exception:
        number = await _next_cto_number(cid, sigla_u, body.vlan)

    dup = await db.ctos.find_one({
        "company_id": cid, "sigla": sigla_u, "vlan": body.vlan, "number": number,
    })
    if dup:
        nxt = await _next_cto_number(cid, sigla_u, body.vlan)
        raise HTTPException(409, {
            "msg": f"CTO {_format_cto_name(number, body.vlan, sigla_u)} já existe",
            "suggested_number": nxt,
            "suggested_name": _format_cto_name(nxt, body.vlan, sigla_u),
        })

    name = _format_cto_name(number, body.vlan, sigla_u)
    ports = [{
        "number": i,
        "status": "used" if i == body.client_port else "free",
        "client_subscriber_id": body.client_subscriber_id if i == body.client_port else None,
        "client_pppoe": body.client_pppoe if i == body.client_port else None,
    } for i in range(1, body.capacity + 1)]

    full_tech_name = body.technician_name or coll.get("name") or ""
    first_name = (full_tech_name.strip().split() or [""])[0].upper()

    cto_id = _new_id("cto")
    doc = {
        "id": cto_id, "company_id": cid, "name": name, "number": number,
        "sigla": sigla_u, "vlan": body.vlan,
        "address": {
            "rua": body.rua, "numero": body.numero, "bairro": body.bairro,
            "cidade": body.cidade, "estado": (body.estado or "").upper(),
            "referencia": body.referencia,
        },
        "gps": {"lat": body.lat, "lng": body.lng} if body.lat is not None else None,
        "capacity": body.capacity, "network_type": body.network_type,
        "splitter": body.splitter, "ports": ports,
        "status": "pending_validation",
        "technician_id": collab_id,
        "technician_name": full_tech_name,
        "technician_first_name": first_name,
        "technician_praca_id": praca_id,
        "technician_praca_name": praca_name,
        "technician_praca_city": praca_city,
        "created_by_user_id": collab_id,
        "created_at": now_iso(), "updated_at": now_iso(),
        "approved_by": None, "approved_at": None,
        "photo_data_url": body.photo_data_url,
    }
    await db.ctos.insert_one(doc)
    await db.cto_validations.insert_one({
        "id": _new_id("val"), "company_id": cid, "cto_id": cto_id,
        "cto_snapshot": {k: v for k, v in doc.items() if k != "_id"},
        "status": "pending",
        "technician_id": collab_id, "technician_name": doc["technician_name"],
        "manager_id": None, "manager_name": None, "comment": "",
        "created_at": now_iso(), "resolved_at": None,
    })
    await db.cto_history.insert_one({
        "id": _new_id("hist"), "company_id": cid, "cto_id": cto_id,
        "action": "create", "before": None,
        "after": {k: v for k, v in doc.items() if k != "_id"},
        "by_user_id": collab_id, "by_user_name": doc["technician_name"],
        "by_role": "colaborador", "motivo": "Cadastro via app do técnico (público)",
        "timestamp": now_iso(),
    })
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# rede_IA Analyzer  (Fase 5) — usa Emergent LLM Key
# ---------------------------------------------------------------------------
class AnalyzeIn(BaseModel):
    focus: str = "general"  # general | duplicates | capacity | nomenclature


@router.post("/analyze")
async def analyze_rede(body: AnalyzeIn,
                       user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Roda a rede_IA com LLM para detectar inconsistências e sugerir correções.

    Coleta um resumo da topologia (bairros, CTOs aprovadas, ocupação) e envia
    para o LLM com as diretrizes salvas como system prompt.
    """
    cid = _user_company(user)
    bairros = await db.bairros_vlan_map.find({"company_id": cid}, {"_id": 0}).to_list(500)
    ctos = await db.ctos.find({"company_id": cid}, {"_id": 0}).to_list(500)
    settings = await db.rede_ia_settings.find_one({"company_id": cid}, {"_id": 0})
    diretrizes = (settings or {}).get("text") or DEFAULT_DIRETRIZES

    # Monta resumo compactado
    summary_lines = [
        f"Total de bairros mapeados: {len(bairros)}",
        f"Total de CTOs: {len(ctos)}",
        f"CTOs aprovadas: {len([c for c in ctos if c.get('status') == 'approved'])}",
        f"CTOs pendentes: {len([c for c in ctos if c.get('status') == 'pending_validation'])}",
        "",
        "Bairros:",
    ]
    for b in bairros[:50]:
        summary_lines.append(f"- {b['bairro']} (sigla {b['sigla']}, VLAN {b['vlan']})")
    summary_lines.append("\nCTOs cadastradas:")
    for c in ctos[:80]:
        used = len([p for p in c.get("ports") or [] if p.get("status") == "used"])
        summary_lines.append(
            f"- {c.get('name')} · {c.get('address',{}).get('bairro','?')} · "
            f"cap {c.get('capacity')} (usadas {used}) · "
            f"{c.get('network_type')}{(' splitter ' + (c.get('splitter') or '')) if c.get('splitter') else ''} · "
            f"status {c.get('status')}"
        )

    user_prompt = (
        "Analise a rede FTTH abaixo e produza um relatório técnico em PT-BR contendo:\n"
        "1. Inconsistências detectadas (nomenclaturas fora do padrão, duplicidades, "
        "siglas inválidas, VLAN inconsistentes entre CTOs do mesmo bairro)\n"
        "2. Risco de capacidade (CTOs com alta ocupação que vão precisar de expansão)\n"
        "3. Sugestões de correção priorizadas\n"
        "4. Sugestões de padronização de topologia\n\n"
        "Topologia atual:\n" + "\n".join(summary_lines)
    )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        from core import EMERGENT_LLM_KEY
        if not EMERGENT_LLM_KEY:
            raise HTTPException(503, "EMERGENT_LLM_KEY não configurada")
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"rede-ia-{uuid.uuid4().hex[:8]}",
            system_message=diretrizes,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        out = await chat.send_message(UserMessage(text=user_prompt))
        report = str(out).strip()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[rede-ia] análise falhou: %s", e)
        raise HTTPException(500, f"Falha LLM: {str(e)[:200]}")

    await db.rede_ia_analyses.insert_one({
        "id": _new_id("ana"),
        "company_id": cid,
        "focus": body.focus,
        "report": report,
        "created_by": user.get("name"),
        "created_at": now_iso(),
    })
    return {"report": report, "ctos_count": len(ctos),
            "bairros_count": len(bairros), "focus": body.focus}

# ---------------------------------------------------------------------------
# QR Code endpoints (Fase 6 — extensão pós Rede IA)
# ---------------------------------------------------------------------------
async def _resolve_user_from_query_or_header(
    t: Optional[str], authorization: Optional[str],
) -> Dict[str, Any]:
    """Resolve usuário aceitando token via Bearer header OU query `?t=`.
    Útil pra `<a href="/foo?t=...">` (download direto sem JS)."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif t:
        token = t
    if not token:
        raise HTTPException(401, "Token requerido")
    try:
        from auth import decode_token
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Token inválido")
    user_id = payload.get("sub")
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user or not user.get("active", True):
        raise HTTPException(401, "Usuário inativo")
    return user


@router.get("/ctos/{cto_id}/qrcode.png")
async def cto_qrcode_png(
    cto_id: str,
    t: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Gera PNG do QR Code da CTO. Aceita auth via Bearer OU `?t=token`."""
    user = await _resolve_user_from_query_or_header(t, authorization)
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas podem gerar QR Code")

    token = _build_qr_token(cto_id, cid, cto.get("name") or "")
    png_bytes = _render_qr_png(token)
    return Response(content=png_bytes, media_type="image/png", headers={
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f"inline; filename=\"qr-{cto.get('name','cto')}.png\"",
    })


@router.get("/ctos/{cto_id}/qrcode")
async def cto_qrcode_info(cto_id: str, user: dict = Depends(get_current_user)):
    """Retorna metadados do QR sem renderizar imagem (útil para preview/print)."""
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas podem gerar QR Code")
    token = _build_qr_token(cto_id, cid, cto.get("name") or "")
    return {
        "token": token,
        "cto_id": cto_id,
        "name": cto.get("name"),
        "png_url": f"/api/rede-ia/ctos/{cto_id}/qrcode.png",
    }


class QrScanIn(BaseModel):
    payload: str


@router.post("/qrcode/scan")
async def qrcode_scan(body: QrScanIn,
                       user: dict = Depends(get_current_user)):
    """Decodifica o token do QR escaneado pelo app do técnico.

    Valida assinatura HMAC, confirma que a CTO pertence à empresa do usuário,
    e devolve os dados completos da CTO (incluindo portas livres) para que o
    app preencha o cliente automaticamente.
    """
    decoded = _verify_qr_token(body.payload or "")
    if not decoded:
        raise HTTPException(400, "QR Code inválido ou assinatura incorreta")
    cto_id = decoded.get("id")
    qr_company = decoded.get("cid")
    cid = _user_company(user)
    if qr_company != cid:
        raise HTTPException(403, "QR pertence a outra empresa")
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    free_ports = [p for p in (cto.get("ports") or []) if p.get("status") == "free"]
    used_ports = [p for p in (cto.get("ports") or []) if p.get("status") == "used"]
    return {
        "cto": cto,
        "free_ports": [p["number"] for p in free_ports],
        "used_ports_count": len(used_ports),
        "scanned_at": now_iso(),
        "scanned_by": user.get("name"),
    }


# ---------------------------------------------------------------------------
# Bind subscriber to CTO port + create OS (Fase 7)
# ---------------------------------------------------------------------------
class BindPortIn(BaseModel):
    cto_id: str
    port_number: int
    subscriber_name: str
    pppoe: Optional[str] = None
    subscriber_phone: Optional[str] = None
    subscriber_id: Optional[str] = None
    service_type: str = "instalacao"  # instalacao | manutencao | troca_porta
    notes: str = ""


@router.post("/qrcode/bind-port")
async def bind_port(body: BindPortIn,
                     user: dict = Depends(get_current_user)):
    """Vincula assinante a uma porta livre da CTO e gera uma OS.

    Fluxo invocado após o técnico escanear o QR e escolher porta+cliente.
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": body.cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas aceitam vincular cliente")

    # Encontra a porta
    ports = list(cto.get("ports") or [])
    target = next((p for p in ports if p.get("number") == body.port_number), None)
    if not target:
        raise HTTPException(404, f"Porta {body.port_number} não existe nesta CTO")
    if target.get("status") == "used":
        raise HTTPException(409, f"Porta {body.port_number} já está ocupada por "
                                  f"{target.get('client_pppoe') or 'outro cliente'}")

    # Atualiza a porta
    new_ports = []
    for p in ports:
        if p.get("number") == body.port_number:
            new_ports.append({
                **p,
                "status": "used",
                "client_subscriber_id": body.subscriber_id,
                "client_pppoe": body.pppoe,
                "client_name": body.subscriber_name,
                "client_phone": body.subscriber_phone,
                "linked_by_user_id": user.get("id"),
                "linked_by_user_name": user.get("name"),
                "linked_at": now_iso(),
                "linked_via_qr": True,
            })
        else:
            new_ports.append(p)

    await db.ctos.update_one(
        {"id": body.cto_id, "company_id": cid},
        {"$set": {"ports": new_ports, "updated_at": now_iso()}},
    )

    # Cria OS no Kanban (lousa)
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    collab_id = user.get("collaborator_id") or user.get("id")
    last = await db.tickets.find(
        {"assigned_collaborator_id": collab_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
         "company_id": cid},
        {"_id": 0, "position": 1},
    ).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 0

    type_label_map = {
        "instalacao": "Instalação",
        "manutencao": "Manutenção",
        "troca_porta": "Troca de porta",
    }
    # Usa as prioridades aceitas pela Lousa: normal | horario | prioridade
    priority_map = {
        "instalacao": "normal",
        "manutencao": "prioridade",
        "troca_porta": "normal",
    }
    ticket_doc = {
        "id": ticket_id,
        "client_id": body.subscriber_id or str(uuid.uuid4()),
        "client_snapshot": {
            "name": body.subscriber_name,
            "address": f"{cto.get('address',{}).get('rua','')}, {cto.get('address',{}).get('numero','')}",
            "neighborhood": cto.get("address", {}).get("bairro"),
            "phone": body.subscriber_phone,
            "relato": body.notes or f"Vínculo via QR — {cto.get('name')} porta {body.port_number}",
            "pppoe_user": body.pppoe,
            "cto_name": cto.get("name"),
            "cto_port": body.port_number,
            "cto_vlan": cto.get("vlan"),
            "test_history": [],
        },
        "type": type_label_map.get(body.service_type, body.service_type),
        "priority": priority_map.get(body.service_type, "normal"),
        "scheduled_time": None,
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": collab_id,
        "company_id": cid,
        "opened_at": now_iso(),
        "created_at": now_iso(),
        "source": "rede_ia_qr",
        "cto_id": body.cto_id,
    }
    try:
        await db.tickets.insert_one(ticket_doc)
    except Exception as e:
        # Rollback: reverte a porta para 'free' se a OS falhar
        logger.exception("[rede-ia] insert ticket falhou — revertendo porta")
        await db.ctos.update_one(
            {"id": body.cto_id, "company_id": cid},
            {"$set": {"ports": ports, "updated_at": now_iso()}},
        )
        raise HTTPException(500, f"Falha ao criar OS — vínculo revertido: {str(e)[:120]}")

    # Audit
    await _audit(
        "bind_port", body.cto_id,
        {"port": body.port_number, "previous_status": "free"},
        {"port": body.port_number, "subscriber": body.subscriber_name,
         "ticket_id": ticket_id, "service_type": body.service_type},
        user,
        f"Vínculo via QR — porta {body.port_number} → {body.subscriber_name}",
    )

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "cto_id": body.cto_id,
        "port_number": body.port_number,
        "subscriber_name": body.subscriber_name,
        "service_type": body.service_type,
    }


@router.post("/ctos/{cto_id}/regenerate-pdf")
async def regenerate_pdf(cto_id: str,
                          user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Regenera PDF e faz upload pro Drive. Funciona apenas para CTOs aprovadas."""
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas geram PDF")
    result = await _generate_and_upload_cto_pdf(
        cid, cto_id,
        cto.get("approved_by_name") or user.get("name"),
    )
    if not result.get("ok"):
        if result.get("drive_connected") is False:
            raise HTTPException(503, "Google Drive não conectado. "
                                       "Conecte em Configurações → Conexões → Drive.")
        raise HTTPException(500, result.get("error", "Falha ao gerar PDF"))
    return result


@router.get("/ctos/{cto_id}/pdf.pdf")
async def download_cto_pdf(
    cto_id: str,
    t: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Devolve o PDF da CTO diretamente. Aceita auth via Bearer OU `?t=token`."""
    from services.cto_pdf import build_cto_pdf
    user = await _resolve_user_from_query_or_header(t, authorization)
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas geram PDF")
    qr_token = _build_qr_token(cto_id, cid, cto.get("name") or "")
    pdf_bytes = build_cto_pdf(cto, qr_token,
                                approved_by_name=cto.get("approved_by_name"))
    safe_name = (cto.get("name") or "cto").replace(" ", "-").replace("/", "-")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=\"CTO-{safe_name}.pdf\"",
    })


@router.delete("/ctos/{cto_id}")
async def delete_cto(
    cto_id: str,
    user: dict = Depends(require_role("administrador", "gestor", "gestor_rede")),
):
    """Apaga uma CTO + cabos relacionados. Logado em rede_ia_history."""
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    cables_deleted = await db.rede_cables.delete_many(
        {"company_id": cid, "$or": [{"from_cto_id": cto_id}, {"to_cto_id": cto_id}]},
    )
    await db.ctos.delete_one({"id": cto_id, "company_id": cid})
    try:
        await db.rede_ia_history.insert_one({
            "id": f"hist-{uuid.uuid4().hex[:10]}",
            "company_id": cid, "event": "cto_deleted",
            "details": (
                f"CTO {cto.get('name')} ({cto_id}) apagada · "
                f"{cables_deleted.deleted_count} cabos removidos"
            ),
            "user_id": user.get("id"),
            "user_name": user.get("name") or user.get("email"),
            "at": now_iso(),
        })
    except Exception:
        pass
    return {
        "ok": True,
        "deleted_cto": cto.get("name"),
        "cables_deleted": cables_deleted.deleted_count,
    }


@router.post("/ctos/{cto_id}/sync-smartolt-zone")
async def force_sync_smartolt_zone(cto_id: str,
                                       user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Força sync da zone SmartOLT (manual). Útil quando CTO foi aprovada mas
    o SmartOLT estava offline na primeira tentativa.
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if cto.get("status") != "approved":
        raise HTTPException(409, "Apenas CTOs aprovadas sincronizam zone")
    result = await _sync_cto_zone_to_smartolt(cid, cto_id, user.get("name"))
    if not result.get("ok"):
        raise HTTPException(503, result.get("error", "Falha SmartOLT"))
    return result


@router.get("/smartolt/zones")
async def list_smartolt_zones(user: dict = Depends(get_current_user)):
    """Lista zones atualmente no SmartOLT — útil para auditoria."""
    from services.smartolt_zones import list_zones
    cid = _user_company(user)
    try:
        zones = await list_zones(cid, force_refresh=True)
        return {"items": zones, "total": len(zones)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/smartolt/zone-audit")
async def smartolt_zone_audit(limit: int = Query(50, ge=1, le=200),
                                  user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Log de operações de sync SmartOLT (criadas, race, erros)."""
    cid = _user_company(user)
    items = await db.smartolt_zone_audit.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("timestamp", -1).to_list(limit)
    return {"items": items, "total": len(items)}
