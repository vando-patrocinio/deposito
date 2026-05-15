"""Rede IA — supervisor inteligente da rede FTTH.

Módulo responsável por:
- Cadastrar bairros e mapeá-los a VLAN/sigla (admin)
- Cadastrar CTOs (técnico via app) com workflow de validação por gestor_rede
- Manter histórico de alterações
- Servir diretivas (system prompt) da rede_IA
- Exportar dados para fluxograma React Flow
- (Fase 5) chamada LLM para análise de inconsistências
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role, get_current_user
from database import db

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
    return {"ok": True, "action": body.action, "status": new_cto_status_map[body.action]}


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
