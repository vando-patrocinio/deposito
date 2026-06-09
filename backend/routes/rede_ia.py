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
import asyncio
import logging
import time
import uuid
import httpx
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
@router.get("/audit/orphan-onus")
async def audit_orphan_onus(
    refresh: bool = Query(False, description="Se true, roda auditoria agora"),
    user: dict = Depends(get_current_user),
):
    """Retorna a última auditoria CTO ↔ SmartOLT da empresa.

    - Por padrão lê o último doc salvo em `cto_audits` (computado pelo job
      noturno).
    - Com `?refresh=true`, força execução agora (computa + salva + retorna).
    """
    from services.cto_audit import run_audit_for_company
    cid = _user_company(user)
    if refresh:
        return await run_audit_for_company(cid)
    last = await db.cto_audits.find_one(
        {"company_id": cid},
        {"_id": 0},
        sort=[("executed_at", -1)],
    )
    if not last:
        # Nunca rodou — roda agora
        return await run_audit_for_company(cid)
    return {
        "summary": {k: v for k, v in last.items()
                       if k not in ("orphans_sample", "ghosts_sample")},
        "orphans": last.get("orphans_sample") or [],
        "ghosts": last.get("ghosts_sample") or [],
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _user_company(user: dict) -> str:
    return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em metros entre 2 coords WGS84."""
    from math import radians, sin, cos, sqrt, asin
    R = 6371000.0  # metros
    la1, lo1, la2, lo2 = map(radians, (lat1, lng1, lat2, lng2))
    dlat, dlon = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _polyline_length_m(points: Optional[List[List[float]]]) -> float:
    """Soma haversine de uma polyline [[lat,lng], ...]. 0 se < 2 pontos."""
    if not points or len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        try:
            total += _haversine_m(
                float(points[i - 1][0]), float(points[i - 1][1]),
                float(points[i][0]), float(points[i][1]),
            )
        except (ValueError, TypeError, IndexError):
            continue
    return total


def _compute_cable_total_length(
    route_geometry: Optional[List[List[float]]],
    route_distance_m: Optional[float],
    extra_margin_m: Optional[int],
) -> Optional[float]:
    """Comprimento total do cabo:
       - Se houver geometry (trajeto andado/desenhado), soma haversine.
       - Senão usa route_distance_m (vindo do OSRM).
       - Adiciona extra_margin_m (sobras técnicas) ao final.
       Retorna None se não houver nem geometry nem distance.
    """
    margin = extra_margin_m if extra_margin_m is not None else 20
    geom_len = _polyline_length_m(route_geometry)
    base = geom_len if geom_len > 0 else (route_distance_m or 0.0)
    if base <= 0 and not route_geometry and not route_distance_m:
        return None
    return round(base + margin, 1)




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
    # iter211be — Nome da OLT SmartOLT que atende este bairro (opcional).
    # CTOs criadas com a VLAN deste bairro vão ser marcadas
    # `smartolt_eligible=True` quando este campo estiver preenchido.
    # Exemplos: RIO_HUAWEI, MAGE_ZTE, PENHA_HUAWEI, RESENDE_ZTE.
    olt_name: Optional[str] = None


class CTOPortIn(BaseModel):
    number: int
    status: str = "free"  # free | used | reserved | broken
    client_id: Optional[str] = None
    subscriber_phone: Optional[str] = None
    pppoe: Optional[str] = None


class CTOCreateIn(BaseModel):
    # Tipo do elemento: "cto" (default) | "ce" (caixa de emenda) | "cabo"
    element_type: Optional[str] = "cto"
    # Campos específicos por tipo (validados condicionalmente no handler)
    # CE: número de bandejas / emendas. CABO: capacidade de fibras + ocupação
    # + IDs dos pontos de origem/destino (ambos podem ser CTO ou CE).
    bandejas_total: Optional[int] = None
    fibras_total: Optional[int] = None
    fibras_ocupadas: Optional[int] = None
    from_element_id: Optional[str] = None
    to_element_id: Optional[str] = None
    # As-built (campo) vs projeto (planejado). Default True quando técnico
    # cadastra direto pela mobile.
    is_as_built: Optional[bool] = True
    # Foto extra (CTO aberta com portas+splitter, ou bandeja em CE, ou
    # plaqueta de identificação em CABO). Campo único string base64.
    photo_extra_data_url: Optional[str] = None
    # CE: tipo de instalação (aérea/subterrânea/câmara)
    ce_install_type: Optional[str] = None
    # CABO: tipo lógico (drop/backbone/distribuicao)
    cable_type: Optional[str] = None
    # iter183 — Roteamento + identificação física do cabo
    # FO count: 4, 6, 8, 12, 24, 48, 72, 96, 144
    fo_count: Optional[int] = None
    cable_brand: Optional[str] = None       # "Furukawa", "Prysmian", "Optitech"…
    cable_serial: Optional[str] = None      # NS do fabricante
    route_geometry: Optional[List[List[float]]] = None  # [[lat,lng],...] do OSRM
    route_distance_m: Optional[float] = None  # distância só do trajeto OSRM
    route_source: Optional[str] = None  # "osrm" | "gps" | "manual" | "auto"
    # iter186 — Sinaliza cabo lançado sem origem/destino vinculados
    is_loose: Optional[bool] = False
    extra_margin_m: Optional[int] = 20      # 10m por ponta × 2 (configurável)
    # GPS do destino (ponto livre se não houver to_element_id)
    to_lat: Optional[float] = None
    to_lng: Optional[float] = None
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
    # Capacidade + rede (obrigatório só para CTO real)
    capacity: int = Field(default=0, description="4, 8 ou 16 (só CTO)")
    network_type: str = Field(default="", description="balanceada | desbalanceada")
    splitter: Optional[str] = None  # "1:2" | "1:4" | "1:8" | "other"
    # Porta do cliente
    client_port: Optional[int] = None
    client_subscriber_id: Optional[str] = None
    client_pppoe: Optional[str] = None
    # iter179 — Número físico da caixa (etiqueta/pintura no equipamento)
    # Opcional. Quando informado, persistido para exibir no mapa/relatórios.
    box_number: Optional[str] = None
    # Resolvido pela IA (front envia, backend re-valida)
    sigla: str
    vlan: int
    suggested_name: str  # CTO 001_301_COR (mantido p/ compat)
    cto_number: Optional[int] = None  # Número informado pelo técnico (precedência)
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


@router.get("/olt-names")
async def list_olt_names(user: dict = Depends(get_current_user)):
    """iter211be — OLTs únicas em smartolt_onus, pra dropdown de bairros."""
    cid = _user_company(user)
    names = set()
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$olt_name"}},
    ]
    async for r in db.smartolt_onus.aggregate(pipe):
        if r.get("_id"):
            names.add(r["_id"])
    return {"items": sorted(names)}


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
        # iter211be — vincula bairro a uma OLT SmartOLT (opcional)
        "olt_name": (body.olt_name or "").strip().upper() or None,
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
        "olt_name": (body.olt_name or "").strip().upper() or None,
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


class BairroEnsureIn(BaseModel):
    bairro: str = Field(..., min_length=2)
    vlan: int = Field(..., ge=1, le=4094)
    cidade: str = ""
    estado: str = ""


def _auto_sigla_from(bairro: str) -> str:
    """Gera sigla de 3 letras a partir do nome do bairro: 1ª letra de
    cada palavra OU primeiras 3 do bairro composto."""
    s = (bairro or "").strip().upper()
    parts = [p for p in s.split() if p and p not in ("DE", "DA", "DO", "DOS", "DAS")]
    if len(parts) >= 3:
        cand = (parts[0][0] + parts[1][0] + parts[2][0])
    elif len(parts) == 2:
        cand = (parts[0][:2] + parts[1][0])
    elif parts:
        cand = parts[0][:3]
    else:
        cand = "GEN"
    # Remove acentos
    import unicodedata
    cand = unicodedata.normalize("NFD", cand)
    cand = "".join(c for c in cand if unicodedata.category(c) != "Mn")
    return cand[:6] or "GEN"


@router.post("/bairros/ensure-from-field")
async def ensure_bairro_from_field(
    body: BairroEnsureIn,
    user: dict = Depends(get_current_user),
):
    """Garante existência de um bairro+VLAN, criando se necessário.

    Usado pelo wizard mobile de cadastro de CTO quando o técnico já está
    em campo: ele tem o bairro detectado pelo GPS (string livre) e
    informa a VLAN. Se o par (bairro, vlan) já existe → reusa. Se não,
    cria automaticamente (sigla auto-gerada das iniciais). Permitido para
    qualquer usuário autenticado, inclusive técnicos via cid público.
    """
    cid = _user_company(user)
    bairro_in = body.bairro.strip()
    vlan = body.vlan

    # Match case/acento-insensível por bairro (mesma cidade)
    import unicodedata
    def _norm(s):
        s = unicodedata.normalize("NFD", s or "")
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.lower().strip()
    target = _norm(bairro_in)

    # 1) Procura existente com mesmo bairro+vlan
    candidates = await db.bairros_vlan_map.find(
        {"company_id": cid, "vlan": vlan}, {"_id": 0},
    ).to_list(500)
    for c in candidates:
        if _norm(c.get("bairro", "")) == target:
            return {"ok": True, "created": False, "bairro": c}

    # 2) Procura mesmo bairro com VLAN diferente (alerta)
    others = await db.bairros_vlan_map.find(
        {"company_id": cid}, {"_id": 0, "bairro": 1, "vlan": 1, "sigla": 1},
    ).to_list(500)
    same_name_other_vlan = [
        o for o in others if _norm(o.get("bairro", "")) == target
    ]

    # 3) Cria novo registro com sigla auto-gerada
    sigla = _auto_sigla_from(bairro_in)
    # Se sigla colidir, anexa número
    base_sigla = sigla
    n = 2
    while await db.bairros_vlan_map.find_one(
        {"company_id": cid, "sigla": sigla},
    ):
        sigla = f"{base_sigla[:3]}{n}"
        n += 1
        if n > 99:
            raise HTTPException(500, "Não foi possível gerar sigla única")

    doc = {
        "id": _new_id("bar"),
        "company_id": cid,
        "bairro": bairro_in,
        "sigla": sigla,
        "vlan": vlan,
        "cidade": body.cidade.strip(),
        "estado": body.estado.strip().upper(),
        "regiao": "",
        "auto_created": True,
        "created_at": now_iso(),
    }
    await db.bairros_vlan_map.insert_one(doc)
    doc.pop("_id", None)
    return {
        "ok": True,
        "created": True,
        "bairro": doc,
        "warning_other_vlans": [
            {"vlan": o["vlan"], "sigla": o.get("sigla")} for o in same_name_other_vlan
        ] if same_name_other_vlan else None,
    }


# ---------------------------------------------------------------------------
# CTO Nomenclature helpers (Fase 1)
# ---------------------------------------------------------------------------
async def _next_cto_number(company_id: str, sigla: str, vlan: int,
                              element_type: str = "cto") -> int:
    """Retorna próximo número disponível.

    iter180 — escopo de numeração é APENAS (company_id, vlan, element_type).
    Sigla foi removida do nome, então duas CTOs em bairros diferentes mas
    mesma VLAN compartilham a sequência.

    CE ignora VLAN (escopo é só (company_id, element_type)).

    O parâmetro `sigla` é mantido por retrocompat dos callers, ignorado.
    """
    elem_t = (element_type or "cto").lower()
    if elem_t == "cto":
        type_filter: Dict[str, Any] = {"$or": [
            {"element_type": "cto"},
            {"element_type": {"$exists": False}},
            {"element_type": None},
        ]}
    else:
        type_filter = {"element_type": elem_t}
    scope: Dict[str, Any] = {"company_id": company_id, **type_filter}
    if elem_t != "ce":
        scope["vlan"] = vlan
    cursor = db.ctos.find(scope, {"_id": 0, "number": 1})
    used = set()
    async for c in cursor:
        n = c.get("number")
        if isinstance(n, int):
            used.add(n)
    n = 1
    while n in used:
        n += 1
    return n


def _format_cto_name(number: int, vlan: int, sigla: str,
                       element_type: str = "cto") -> str:
    """Formata o nome do elemento de rede (iter183 — número 4 dígitos).

    CTO  → "CTO_301_0004"   (CTO + VLAN + número 4 dígitos)
    CABO → "CABO_301_0004"  (mesmo padrão da CTO)
    CE   → "CE_00001"       (CE + número 5 dígitos, sem VLAN)

    O parâmetro `sigla` continua na assinatura por retrocompat com chamadores
    antigos, mas é IGNORADO. Mantemos o argumento para não quebrar `*args`.
    """
    elem_t = (element_type or "cto").lower()
    if elem_t == "ce":
        return f"CE_{number:05d}"
    prefix_map = {"cto": "CTO", "cabo": "CABO"}
    prefix = prefix_map.get(elem_t, "CTO")
    return f"{prefix}_{vlan}_{number:04d}"


@router.get("/ctos/suggest-name")
async def suggest_name(sigla: str = Query(...),
                       vlan: int = Query(...),
                       number: Optional[int] = Query(None),
                       element_type: str = Query("cto"),
                       user: dict = Depends(get_current_user)):
    """Sugere nomenclatura. Se 'number' for fornecido e duplicado, devolve próximo livre.
    iter180 — aceita `element_type` para retornar formato correto (CTO/CE/CABO).
    """
    cid = _user_company(user)
    sigla_u = sigla.upper()
    elem_t = (element_type or "cto").lower()
    if elem_t == "cto":
        type_filter: Dict[str, Any] = {"$or": [
            {"element_type": "cto"},
            {"element_type": {"$exists": False}},
            {"element_type": None},
        ]}
    else:
        type_filter = {"element_type": elem_t}
    if number is not None:
        ex_q: Dict[str, Any] = {
            "company_id": cid, "number": number, **type_filter,
        }
        if elem_t != "ce":
            ex_q["vlan"] = vlan
        existing = await db.ctos.find_one(ex_q)
        if existing:
            nxt = await _next_cto_number(cid, sigla_u, vlan, elem_t)
            return {
                "exists": True,
                "requested": _format_cto_name(number, vlan, sigla_u, elem_t),
                "suggested_number": nxt,
                "suggested_name": _format_cto_name(nxt, vlan, sigla_u, elem_t),
            }
        return {
            "exists": False,
            "suggested_number": number,
            "suggested_name": _format_cto_name(number, vlan, sigla_u, elem_t),
        }
    nxt = await _next_cto_number(cid, sigla_u, vlan, elem_t)
    return {
        "exists": False,
        "suggested_number": nxt,
        "suggested_name": _format_cto_name(nxt, vlan, sigla_u, elem_t),
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
    elem_t = (body.element_type or "cto").lower()
    # iter180/186 — capacity/network_type só são obrigatórios para CTO real.
    # CE e CABO não têm portas/splitter — pulam essas validações.
    if elem_t == "cto":
        if body.capacity not in (4, 8, 16):
            raise HTTPException(400, "Capacidade deve ser 4, 8 ou 16")
        if body.network_type not in ("balanceada", "desbalanceada"):
            raise HTTPException(400, "Tipo de rede inválido")
        if body.network_type == "desbalanceada" and not body.splitter:
            raise HTTPException(400,
                "Splitter é obrigatório em rede desbalanceada")

    cid = _user_company(user)
    # Normaliza sigla (remove acentos): "BRÁ" → "BRA"
    import unicodedata as _u
    sigla_u = "".join(c for c in _u.normalize("NFD", body.sigla or "")
                       if _u.category(c) != "Mn").upper().strip()

    # Re-valida que o bairro/sigla existe na tabela admin
    bmap = await db.bairros_vlan_map.find_one(
        {"company_id": cid, "sigla": sigla_u},
        {"_id": 0},
    )
    if not bmap:
        raise HTTPException(400, f"Bairro/sigla '{sigla_u}' não cadastrado na tabela de bairros")

    # Verifica duplicidade do nome
    # Precedência: cto_number explícito > suggested_name > auto.
    # Suporta formatos novo "CTO_301_0004" e legado "CTO 004_301_BRA".
    if isinstance(body.cto_number, int) and body.cto_number > 0:
        number = body.cto_number
    else:
        try:
            sn = (body.suggested_name or "").upper().strip()
            if "_" in sn and " " not in sn.split("_", 1)[0]:
                # Formato novo: CTO_VLAN_NUMERO → último _ é o número
                number = int(sn.split("_")[-1])
            else:
                num_part = sn.split(" ")[1].split("_")[0]
                number = int(num_part)
        except Exception:
            number = await _next_cto_number(cid, sigla_u, body.vlan, elem_t)

    # iter186 — Escopo de duplicidade é (sigla, vlan, number, element_type).
    # CABO_JAT_0001 e CTO_JAT_0001 podem coexistir sem conflito.
    dup_filter: Dict[str, Any] = {
        "company_id": cid, "sigla": sigla_u, "vlan": body.vlan, "number": number,
    }
    if elem_t == "cto":
        dup_filter["$or"] = [
            {"element_type": "cto"},
            {"element_type": {"$exists": False}},
            {"element_type": None},
        ]
    else:
        dup_filter["element_type"] = elem_t
    dup = await db.ctos.find_one(dup_filter)
    if dup:
        nxt = await _next_cto_number(cid, sigla_u, body.vlan, elem_t)
        raise HTTPException(409, {
            "msg": f"{_format_cto_name(number, body.vlan, sigla_u, elem_t)} já existe",
            "suggested_number": nxt,
            "suggested_name": _format_cto_name(nxt, body.vlan, sigla_u, elem_t),
        })

    name = _format_cto_name(number, body.vlan, sigla_u, elem_t)
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
        "box_number": (body.box_number or "").strip() or None,
        "element_type": (body.element_type or "cto").lower(),
        "bandejas_total": body.bandejas_total,
        "fibras_total": body.fibras_total,
        "fibras_ocupadas": body.fibras_ocupadas,
        "from_element_id": body.from_element_id,
        "to_element_id": body.to_element_id,
        "is_as_built": bool(body.is_as_built),
        # iter183 — Roteamento e identificação física do cabo
        "fo_count": body.fo_count,
        "cable_brand": (body.cable_brand or "").strip() or None,
        "cable_serial": (body.cable_serial or "").strip() or None,
        "route_geometry": body.route_geometry or None,
        "route_distance_m": body.route_distance_m or None,
        "route_source": (body.route_source or None),
        "extra_margin_m": body.extra_margin_m if body.extra_margin_m is not None else 20,
        "total_length_m": _compute_cable_total_length(
            body.route_geometry,
            body.route_distance_m,
            body.extra_margin_m,
        ),
        "to_gps": ({"lat": body.to_lat, "lng": body.to_lng}
                       if body.to_lat is not None and body.to_lng is not None else None),
        "ports": ports,
        # iter186 — Cabo sem from/to é "cabo_solto" (visível no mapa em
        # laranja tracejado, sem aprovação obrigatória). Demais elementos
        # seguem o fluxo normal "pending_validation".
        "status": (
            "cabo_solto"
            if (body.element_type or "").lower() == "cabo"
            and (bool(body.is_loose)
                 or not body.from_element_id
                 or not body.to_element_id)
            else "pending_validation"
        ),
        "is_loose": bool(body.is_loose) if (body.element_type or "").lower() == "cabo" else False,
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

    # iter183 — Sincroniza Base de Portas (cto_ports) para a nova CTO
    try:
        from routes.cto_ports_base import sync_cto_all_ports
        await sync_cto_all_ports(cid, cto_id)
    except Exception as _e:
        logger.warning("[rede-ia] sync_cto_all_ports falhou na criação cto=%s: %s",
                          cto_id, _e)

    # iter211bc — Classifica elegibilidade SmartOLT:
    # CTOs com VLAN que pertença a alguma OLT SmartOLT (RIO_HUAWEI etc) são
    # marcadas pra sync futuro. CTOs em VLAN "1" ou fora do mapa SmartOLT
    # ficam apenas na Base de Portas local.
    try:
        cto_vlan = int(doc.get("vlan") or 0)
        smartolt_eligible = False
        olt_name = None
        if cto_vlan > 0:
            # Verifica se existe algum bairro cadastrado com essa VLAN e olt_name
            bairro_olt = await db.bairros_vlan_map.find_one(
                {"company_id": cid, "vlan": cto_vlan,
                  "olt_name": {"$exists": True, "$nin": [None, ""]}},
                {"_id": 0, "olt_name": 1, "sigla": 1, "bairro": 1},
            )
            if bairro_olt and bairro_olt.get("olt_name"):
                smartolt_eligible = True
                olt_name = bairro_olt["olt_name"]
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid},
            {"$set": {
                "smartolt_eligible": smartolt_eligible,
                "smartolt_olt_name": olt_name,
                "smartolt_sync_pending": smartolt_eligible,
            }},
        )
        doc["smartolt_eligible"] = smartolt_eligible
        doc["smartolt_olt_name"] = olt_name
        if smartolt_eligible:
            logger.info("[rede-ia] CTO %s marcada smartolt_eligible (OLT=%s, VLAN=%s)",
                         cto_id, olt_name, cto_vlan)
        else:
            logger.info("[rede-ia] CTO %s ficará SÓ na Base de Portas (VLAN=%s sem OLT)",
                         cto_id, cto_vlan)
    except Exception as _e:
        logger.warning("[rede-ia] classify smartolt_eligible falhou: %s", _e)

    # Validation pending entry — pular para cabo_solto (já é "auto-aprovado",
    # válido no mapa em laranja tracejado até o técnico vincular pontas)
    if doc.get("status") != "cabo_solto":
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


@router.get("/ctos/occupancy")
async def ctos_occupancy(
    threshold: float = Query(0.8, ge=0.0, le=1.0,
                                description="Limiar (0.0–1.0) para marcar como saturada"),
    user: dict = Depends(get_current_user),
):
    """Relatório de ocupação por CTO.

    Retorna, por CTO aprovada, quantas portas estão usadas vs livres e
    sinaliza as que ultrapassam `threshold` (default 80%) para alerta
    de saturação. Inclui agregações globais para o dashboard.
    """
    cid = _user_company(user)
    items = await db.ctos.find(
        {"company_id": cid, "status": "approved"},
        {"_id": 0, "id": 1, "name": 1, "sigla": 1, "vlan": 1,
         "capacity": 1, "ports": 1, "gps": 1, "address": 1},
    ).to_list(2000)

    result = []
    total_ports = 0
    total_used = 0
    saturated = 0
    full = 0
    for c in items:
        cap = int(c.get("capacity") or 0)
        ports = c.get("ports") or []
        used = sum(1 for p in ports if p.get("status") == "used")
        free = cap - used
        pct = (used / cap) if cap else 0.0
        is_full = free <= 0
        is_saturated = pct >= threshold
        total_ports += cap
        total_used += used
        if is_full:
            full += 1
        elif is_saturated:
            saturated += 1
        result.append({
            "id": c["id"],
            "name": c.get("name"),
            "sigla": c.get("sigla"),
            "vlan": c.get("vlan"),
            "capacity": cap,
            "used": used,
            "free": free,
            "percent": round(pct * 100, 1),
            "is_full": is_full,
            "is_saturated": is_saturated,
            "gps": c.get("gps"),
            "bairro": (c.get("address") or {}).get("bairro"),
        })
    # Ordena por % desc (mais críticos no topo)
    result.sort(key=lambda x: x["percent"], reverse=True)
    return {
        "items": result,
        "summary": {
            "total_ctos": len(result),
            "total_ports": total_ports,
            "total_used": total_used,
            "total_free": total_ports - total_used,
            "global_percent": round(
                (total_used / total_ports * 100) if total_ports else 0, 1,
            ),
            "saturated_count": saturated,
            "full_count": full,
            "threshold_percent": round(threshold * 100, 0),
        },
    }


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


class OnuPushIn(BaseModel):
    action: str = Field(default="reboot", pattern="^(reboot|sync|push)$")


@router.post("/onu/{onu_sn}/push")
async def onu_push(
    onu_sn: str, body: OnuPushIn,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "tecnico")),
):
    """Envia comando "push" pra ONU via SmartOLT (reboot remoto).

    Casos de uso típicos:
      • Cliente reclamou de lentidão → técnico aperta Push da Lousa Mobile
      • Pós-cadastro: ONU não pegou IP → push força resync
    """
    cid = _user_company(user)
    try:
        from services.smartolt_zones import reboot_onu
        resp = await reboot_onu(cid, onu_sn)
    except Exception as e:
        raise HTTPException(503, f"SmartOLT recusou push: {e}")
    await _audit(
        "onu_push", onu_sn, None,
        {"action": body.action, "response": resp}, user,
        f"Push ({body.action}) na ONU {onu_sn} por {user.get('email')}",
    )
    return {"ok": True, "sn": onu_sn, "action": body.action, "response": resp}


@router.post("/ctos/{cto_id}/photos/analyze")
async def cto_analyze_photo(
    cto_id: str,
    body: Dict[str, Any],
    user: dict = Depends(get_current_user),
):
    """Análise via IA (vision) de uma foto da CTO.

    Body: { "photo_index": N }  — analisa a N-ésima foto (0 = mais recente)
       OU { "data_url": "data:image/jpeg;base64,..." } — analisa direto.

    Cacheado por hash da imagem em `cto_photo_analyses`.
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid},
                                    {"_id": 0, "id": 1})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    data_url = (body or {}).get("data_url")
    ticket_id = (body or {}).get("ticket_id")
    if not data_url:
        # Tenta buscar pela foto N do histórico
        idx = int((body or {}).get("photo_index") or 0)
        photos_resp = await cto_get_photos(cto_id, user)  # type: ignore
        photos = photos_resp.get("photos") or []
        if not photos:
            raise HTTPException(400, "CTO não possui fotos para analisar")
        if idx < 0 or idx >= len(photos):
            raise HTTPException(400, f"photo_index fora do range (0..{len(photos)-1})")
        data_url = photos[idx].get("data_url")
        ticket_id = ticket_id or photos[idx].get("ticket_id")

    if not data_url or not data_url.startswith("data:image/"):
        raise HTTPException(400, "data_url inválido")

    from services.cto_photo_inspector import analyze_cto_photo
    try:
        result = await analyze_cto_photo(
            data_url=data_url, cto_id=cto_id, ticket_id=ticket_id,
            force_refresh=bool((body or {}).get("force_refresh")),
        )
    except Exception as e:
        logger.exception("Falha ao analisar foto CTO %s: %s", cto_id, e)
        raise HTTPException(500, f"Análise falhou: {e}")
    return result


@router.get("/ctos/{cto_id}/photos")
async def cto_get_photos(
    cto_id: str,
    user: dict = Depends(get_current_user),
):
    """Galeria de fotos da CTO — agrega:
    1. Foto original do cadastro (`ctos.photo_data_url` ou `ctos.photo`)
    2. Fotos tiradas em OSs finalizadas com `completion_data.cto_id == cto_id`
       e `kind == "cto"` no array `completion_data.fotos`.

    Retorna lista ordenada por data desc.
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid},
                                    {"_id": 0, "id": 1, "name": 1, "photo": 1,
                                      "photo_data_url": 1, "created_at": 1,
                                      "technician_name": 1})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    photos: List[Dict[str, Any]] = []
    # 1) Foto original do cadastro
    original = cto.get("photo_data_url") or cto.get("photo")
    if original:
        photos.append({
            "data_url": original,
            "source": "cadastro_inicial",
            "captured_at": cto.get("created_at"),
            "technician_name": cto.get("technician_name") or None,
            "ticket_id": None, "client_name": None,
        })

    # 2) Fotos de tickets vinculados
    cursor = db.tickets.find(
        {"company_id": cid,
         "completion_data.cto_id": cto_id,
         "completion_data.fotos": {"$exists": True}},
        {"_id": 0, "id": 1, "completion_data": 1, "client_snapshot": 1,
         "finalized_at": 1, "created_at": 1},
    ).sort("finalized_at", -1).limit(200)
    async for t in cursor:
        cd = t.get("completion_data") or {}
        for f in (cd.get("fotos") or []):
            if not isinstance(f, dict):
                continue
            if (f.get("kind") or "").lower() != "cto":
                continue
            url = f.get("dataUrl") or f.get("data_url") or f.get("url")
            if not url:
                continue
            photos.append({
                "data_url": url,
                "source": "ticket",
                "captured_at": t.get("finalized_at") or t.get("created_at"),
                "technician_name": (t.get("client_snapshot") or {})
                    .get("collaborator_name"),
                "ticket_id": t.get("id"),
                "client_name": (t.get("client_snapshot") or {}).get("name"),
            })

    # Ordena desc por captured_at
    photos.sort(key=lambda p: p.get("captured_at") or "", reverse=True)
    return {"cto_id": cto_id, "name": cto.get("name"),
              "total": len(photos), "photos": photos}


@router.get("/ctos/{cto_id}/port-swaps")
async def cto_port_swaps_history(
    cto_id: str,
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    """Histórico das últimas trocas de porta dentro de uma CTO.

    Mostra `from_port → to_port`, técnico, data, e se sincronizou com SmartOLT.
    Útil pro gestor identificar CTOs instáveis (muitas trocas = splitter
    problemático ou degradação de sinal).
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": cid},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada")

    swaps_raw = await db.cto_port_swaps.find(
        {"company_id": cid, "cto_id": cto_id},
        {"_id": 0},
    ).sort("at", -1).to_list(min(limit, 200))

    # Enriquece com nome do cliente e do colaborador (quando disponíveis)
    sub_ids = {s.get("subscriber_id") for s in swaps_raw if s.get("subscriber_id")}
    coll_ids = {s.get("collab_id") for s in swaps_raw if s.get("collab_id")}

    subs_map: Dict[str, str] = {}
    if sub_ids:
        async for s in db.subscribers.find(
            {"id": {"$in": list(sub_ids)}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1},
        ):
            subs_map[s["id"]] = s.get("name") or "—"

    colls_map: Dict[str, str] = {}
    if coll_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": list(coll_ids)}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1},
        ):
            colls_map[c["id"]] = c.get("name") or "—"

    out = []
    for s in swaps_raw:
        out.append({
            "subscriber_id": s.get("subscriber_id"),
            "client_name": subs_map.get(s.get("subscriber_id") or "", "—"),
            "from_port": s.get("from_port"),
            "to_port": s.get("to_port"),
            "from_smartolt": bool(s.get("from_smartolt")),
            "smartolt_synced": bool(s.get("smartolt_synced")),
            "collab_id": s.get("collab_id"),
            "technician_name": colls_map.get(s.get("collab_id") or "", "—"),
            "at": s.get("at"),
        })

    return {
        "cto_id": cto_id,
        "cto_name": cto.get("name"),
        "total": len(out),
        "swaps": out,
    }


@router.get("/ctos/{cto_id}/clients")
async def cto_get_clients(
    cto_id: str,
    user: dict = Depends(get_current_user),
):
    """Lista clientes REGISTRADOS nesta CTO (via fluxo de cadastro/finalização
    de OS — `ctos.ports[].client_subscriber_id`).

    Para cada porta ocupada, tenta enriquecer com sinal/status do SmartOLT
    (busca por `subscriber_id` ou `pppoe_user`).
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    cto_name = (cto.get("name") or "").strip()
    sigla = (cto.get("sigla_bairro") or cto.get("sigla") or "").strip()
    capacity = int(cto.get("capacity") or 16)
    ports = list(cto.get("ports") or [])

    used_ports = [p for p in ports if (p.get("status") or "") == "used"]
    used_slots = {int(p.get("number")) for p in used_ports
                    if isinstance(p.get("number"), int)}

    # Enriquecimento opcional: busca ONUs do SmartOLT por subscriber_id/pppoe
    subscriber_ids = [p.get("client_subscriber_id") for p in used_ports
                          if p.get("client_subscriber_id")]
    pppoes = [p.get("client_pppoe") for p in used_ports
                  if p.get("client_pppoe")]
    or_filt: List[Dict[str, Any]] = []
    if subscriber_ids:
        or_filt.append({"subscriber_id": {"$in": subscriber_ids}})
    if pppoes:
        or_filt.append({"pppoe_user": {"$in": pppoes}})
    onu_by_sub: Dict[str, Dict[str, Any]] = {}
    onu_by_pppoe: Dict[str, Dict[str, Any]] = {}
    if or_filt:
        try:
            onus = await db.smartolt_onus.find(
                {"company_id": cid, "$or": or_filt},
                {"_id": 0, "olt_name": 1, "olt_id": 1, "board": 1, "port": 1,
                 "onu": 1, "sn": 1, "name": 1, "signal_text": 1,
                 "signal_1490": 1, "status": 1, "zone_name": 1, "address": 1,
                 "subscriber_id": 1, "pppoe_user": 1},
            ).limit(500).to_list(500)
            for o in onus:
                sid = o.get("subscriber_id")
                if sid:
                    onu_by_sub[str(sid)] = o
                pp = o.get("pppoe_user")
                if pp:
                    onu_by_pppoe[str(pp).lower()] = o
        except Exception as e:
            logger.warning("[rede_ia] enriquecimento ONU falhou: %s", e)

    clients = []
    for p in used_ports:
        sid = p.get("client_subscriber_id")
        pp = p.get("client_pppoe")
        onu = (onu_by_sub.get(str(sid)) if sid else None) or \
              (onu_by_pppoe.get(str(pp).lower()) if pp else None) or {}
        clients.append({
            "name": p.get("client_name") or onu.get("name") or "—",
            "subscriber_id": sid,
            "pppoe_user": pp,
            "sn": onu.get("sn"),
            "slot": p.get("number"),  # Porta da CTO (1..capacity)
            "olt_name": onu.get("olt_name"),
            "board": onu.get("board"),
            "port": onu.get("port"),
            "signal_dbm": onu.get("signal_1490"),
            "signal_status": (onu.get("signal_text") or "").lower(),
            "status": onu.get("status"),
            "address": onu.get("address"),
            "zone_name": onu.get("zone_name"),
            "connected_at": p.get("connected_at"),
            "connected_via_ticket": p.get("connected_via_ticket"),
        })
    # Ordena por slot (porta)
    clients.sort(key=lambda c: (c.get("slot") is None,
                                  c.get("slot") if c.get("slot") is not None else 999))

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
    smartolt_resp = None
    try:
        from services.smartolt_zones import add_onu, _get_cfg
        cfg = await _get_cfg(cid)
        if cfg and cfg.get("subdomain"):
            board = str(cto.get("board") or "0")
            port = str(cto.get("port") or "0")
            smartolt_resp = await add_onu(
                cid, board=board, port=port, sn=sn_upper,
                zone_name=zone_name,
                pppoe_user=payload.pppoe_user,
                pppoe_password=payload.pppoe_pwd,
                vlan=payload.vlan,
            )
            smartolt_ok = bool(smartolt_resp)
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
async def list_pendencies(
    min_score: Optional[int] = Query(None, ge=0, le=100,
        description="Filtrar somente pendências com score Sentinela < min_score"),
    user: dict = Depends(require_role("administrador", "gestor", "gestor_rede")),
):
    cid = _user_company(user)
    items = await db.cto_validations.find(
        {"company_id": cid, "status": "pending"}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    # Enriquece cada pendência com (a) hints do SmartOLT e (b) score da
    # Sentinela IA (última validação da foto da CTO).
    import hashlib as _hashlib  # noqa: PLC0415
    for it in items:
        snap = it.get("cto_snapshot") or {}
        it["smartolt_hints"] = await _smartolt_hints_for_cto(cid, snap)
        # iter180 — vincula a Sentinela. Estratégia:
        # 1) procura pela foto exata via sha1 da data_url
        # 2) fallback: última validação do colaborador/empresa nos últimos 7d
        sent = None
        photo_url = snap.get("photo_data_url") or ""
        if photo_url.startswith("data:image"):
            try:
                b64 = photo_url.split(",", 1)[1]
                import base64 as _b64  # noqa: PLC0415
                sha1 = _hashlib.sha1(_b64.b64decode(b64)).hexdigest()
                sent = await db.cto_photo_validations.find_one(
                    {"company_id": cid, "sha1": sha1},
                    {"_id": 0, "score": 1, "action": 1, "vision": 1,
                     "gps_check": 1, "dedupe": 1, "created_at": 1, "id": 1},
                )
            except Exception:
                sent = None
        if sent is None:
            tech_id = it.get("technician_id") or it.get("collaborator_id")
            if tech_id:
                sent = await db.cto_photo_validations.find_one(
                    {"company_id": cid, "collaborator_id": tech_id},
                    {"_id": 0, "score": 1, "action": 1, "vision": 1,
                     "gps_check": 1, "dedupe": 1, "created_at": 1, "id": 1},
                    sort=[("created_at", -1)],
                )
        it["sentinela"] = sent
    # iter180 — filtro `score < min_score` (default sem filtro)
    if min_score is not None:
        items = [it for it in items
                  if isinstance((it.get("sentinela") or {}).get("score"), int)
                  and it["sentinela"]["score"] < min_score]
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

    # Quando aprovada, persiste a foto enviada pelo técnico no array
    # `ctos.photos[]` pra ficar visível no card do mapa interativo.
    if body.action == "approve":
        photo_url = (validation.get("cto_snapshot") or {}).get("photo_data_url")
        if photo_url:
            photo_entry = {
                "id": f"ph-{uuid.uuid4().hex[:10]}",
                "url": photo_url,
                "uploaded_at": now_iso(),
                "uploaded_by_name": validation.get("technician_name")
                    or "Técnico", "source": "validation_approved",
            }
            await db.ctos.update_one(
                {"id": cto_id, "company_id": cid},
                {"$push": {"photos": photo_entry}},
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
# Cable Slack Config — sobras técnicas configuráveis para lançamento de cabo
# (iter186) — usadas no step "trajeto" do wizard mobile
# ---------------------------------------------------------------------------
class CableSlackIn(BaseModel):
    slack_start_m: int = Field(default=10, ge=0, le=200,
        description="Metros de sobra técnica no início do cabo")
    slack_end_m: int = Field(default=10, ge=0, le=200,
        description="Metros de sobra técnica no fim do cabo")
    gps_min_distance_m: float = Field(default=5.0, ge=1.0, le=50.0,
        description="Distância mínima entre pontos GPS gravados")
    gps_interval_seconds: float = Field(default=3.0, ge=1.0, le=30.0,
        description="Intervalo mínimo (s) entre amostras GPS")


DEFAULT_CABLE_SLACK = {
    "slack_start_m": 10,
    "slack_end_m": 10,
    "gps_min_distance_m": 5.0,
    "gps_interval_seconds": 3.0,
}


@router.get("/settings/cable-slack")
async def get_cable_slack(user: dict = Depends(get_current_user)):
    cid = _user_company(user)
    doc = await db.rede_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0, "cable_slack": 1},
    )
    cfg = (doc or {}).get("cable_slack") or {}
    return {**DEFAULT_CABLE_SLACK, **cfg}


@router.get("/public/settings/cable-slack/{collab_id}")
async def get_cable_slack_public(collab_id: str):
    """Versão pública pro PWA mobile (técnico) buscar a config sem JWT."""
    cid = await _company_for_collaborator(collab_id)
    doc = await db.rede_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0, "cable_slack": 1},
    )
    cfg = (doc or {}).get("cable_slack") or {}
    return {**DEFAULT_CABLE_SLACK, **cfg}


@router.put("/settings/cable-slack")
async def update_cable_slack(
    body: CableSlackIn,
    user: dict = Depends(require_role(
        "administrador", "gestor", "gestor_rede",
    )),
):
    cid = _user_company(user)
    payload = body.model_dump()
    await db.rede_ia_settings.update_one(
        {"company_id": cid},
        {"$set": {
            "cable_slack": payload,
            "cable_slack_updated_at": now_iso(),
            "cable_slack_updated_by": user.get("name"),
        }},
        upsert=True,
    )
    return payload



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


@router.get("/public/client-current-port/{collab_id}")
async def public_client_current_port(collab_id: str, subscriber_id: str):
    """Retorna a porta atual do cliente em qualquer CTO da empresa.

    Frontend (LousaMobile / CtoInlineFlow) usa pra detectar quando o técnico
    está escolhendo uma porta DIFERENTE da atual e perguntar se é troca.
    """
    cid = await _company_for_collaborator(collab_id)
    cto = await db.ctos.find_one(
        {"company_id": cid, "ports.client_subscriber_id": subscriber_id},
        {"_id": 0, "id": 1, "name": 1, "ports": 1, "vlan": 1},
    )
    if not cto:
        return {"found": False}
    current = None
    for p in (cto.get("ports") or []):
        if p.get("client_subscriber_id") == subscriber_id:
            current = {
                "cto_id": cto["id"], "cto_name": cto.get("name"),
                "cto_vlan": cto.get("vlan"),
                "port_number": p.get("number"),
                "from_smartolt": bool(p.get("origin") == "smartolt"
                                      or p.get("from_smartolt")),
            }
            break
    return {"found": current is not None, "current": current}


@router.post("/public/swap-client-port/{collab_id}")
async def public_swap_client_port(collab_id: str, body: dict):
    """Troca o cliente da porta atual pra uma nova porta dentro da MESMA CTO.

    Body: { subscriber_id: str, cto_id: str, new_port: int }

    Libera a porta antiga, ocupa a nova com o mesmo client_subscriber_id e
    dispara update no SmartOLT (best-effort) caso a porta antiga viesse do
    SmartOLT (origin/from_smartolt=true).
    """
    cid = await _company_for_collaborator(collab_id)
    subscriber_id = (body or {}).get("subscriber_id")
    cto_id = (body or {}).get("cto_id")
    new_port = (body or {}).get("new_port")
    if not subscriber_id or not cto_id or not isinstance(new_port, int):
        raise HTTPException(400, "subscriber_id, cto_id e new_port são obrigatórios.")

    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": cid}, {"_id": 0},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada.")

    ports = cto.get("ports") or []
    old_port_idx = None
    new_port_idx = None
    for idx, p in enumerate(ports):
        if p.get("client_subscriber_id") == subscriber_id:
            old_port_idx = idx
        if p.get("number") == new_port:
            new_port_idx = idx

    if old_port_idx is None:
        raise HTTPException(400, "Cliente não está nesta CTO.")
    if new_port_idx is None:
        raise HTTPException(400, f"Porta {new_port} não existe nesta CTO.")
    if old_port_idx == new_port_idx:
        return {"ok": True, "noop": True}

    new_port_doc = ports[new_port_idx]
    if new_port_doc.get("client_subscriber_id"):
        raise HTTPException(
            409,
            f"Porta {new_port} já está ocupada por outro cliente.",
        )

    old_port_doc = ports[old_port_idx]
    from_smartolt = bool(old_port_doc.get("origin") == "smartolt"
                          or old_port_doc.get("from_smartolt"))
    old_port_number = old_port_doc.get("number")
    old_pppoe = old_port_doc.get("client_pppoe")

    # Liberar a porta antiga
    ports[old_port_idx] = {
        **old_port_doc,
        "status": "free",
        "client_subscriber_id": None,
        "client_pppoe": None,
        "origin": None,
        "from_smartolt": False,
    }
    # Ocupar a nova porta preservando origem (se vinha do SmartOLT)
    ports[new_port_idx] = {
        **new_port_doc,
        "status": "occupied",
        "client_subscriber_id": subscriber_id,
        "client_pppoe": old_pppoe or new_port_doc.get("client_pppoe"),
        "origin": "smartolt" if from_smartolt else (new_port_doc.get("origin") or "field"),
        "from_smartolt": from_smartolt,
        "swapped_at": datetime.now(timezone.utc).isoformat(),
        "swapped_from_port": old_port_number,
    }

    await db.ctos.update_one(
        {"id": cto_id, "company_id": cid},
        {"$set": {"ports": ports,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    # iter183 — Sync Base de Portas (porta antiga liberada + nova ocupada)
    try:
        from routes.cto_ports_base import sync_port_from_cto
        await sync_port_from_cto(cid, cto_id, old_port_number)
        await sync_port_from_cto(cid, cto_id, new_port)
    except Exception as _e:
        logger.warning("[rede-ia/port-swap] sync falhou cto=%s: %s", cto_id, _e)

    smartolt_synced = False
    smartolt_error = None
    if from_smartolt:
        try:
            sub = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": cid},
                {"_id": 0, "unique_external_id": 1, "external_id": 1,
                  "smartolt_external_id": 1},
            ) or {}
            ext_id = (sub.get("unique_external_id")
                        or sub.get("smartolt_external_id")
                        or sub.get("external_id"))
            cfg = await db.smartolt_configs.find_one(
                {"company_id": cid}, {"_id": 0},
            ) or {}
            if ext_id and cfg.get("enabled") and cfg.get("subdomain") \
                  and cfg.get("api_key"):
                from routes.smartolt import _http_post  # type: ignore

                class _CfgShim:
                    pass
                shim = _CfgShim()
                shim.subdomain = cfg["subdomain"]
                shim.api_key = cfg["api_key"]
                shim.timeout_seconds = cfg.get("timeout_seconds", 8)
                shim.company_id = cid
                # SmartOLT: endpoint "edit_onu" aceita port_no — best-effort.
                # Como cada SmartOLT pode ter campos diferentes, enviamos os
                # mais comuns; falha não bloqueia a troca local.
                resp = await _http_post(
                    shim, f"/onu/edit/{ext_id}",
                    {"port_no": new_port},
                )
                smartolt_synced = isinstance(resp, dict) and not resp.get("error")
                if not smartolt_synced:
                    smartolt_error = str(resp)[:200]
        except Exception as e:
            smartolt_error = str(e)[:200]

    # Audit log
    try:
        await db.cto_port_swaps.insert_one({
            "company_id": cid, "cto_id": cto_id, "subscriber_id": subscriber_id,
            "from_port": old_port_number, "to_port": new_port,
            "from_smartolt": from_smartolt, "smartolt_synced": smartolt_synced,
            "collab_id": collab_id, "at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return {"ok": True, "old_port": old_port_number, "new_port": new_port,
            "from_smartolt": from_smartolt, "smartolt_synced": smartolt_synced,
            "smartolt_error": smartolt_error}


@router.post("/public/bairros/ensure-from-field/{collab_id}")
async def public_ensure_bairro_from_field(collab_id: str, body: BairroEnsureIn):
    """Versão pública (técnico via PWA) de ensure-from-field."""
    cid = await _company_for_collaborator(collab_id)
    bairro_in = body.bairro.strip()
    vlan = body.vlan
    import unicodedata
    def _norm(s):
        s = unicodedata.normalize("NFD", s or "")
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.lower().strip()
    target = _norm(bairro_in)
    candidates = await db.bairros_vlan_map.find(
        {"company_id": cid, "vlan": vlan}, {"_id": 0},
    ).to_list(500)
    for c in candidates:
        if _norm(c.get("bairro", "")) == target:
            return {"ok": True, "created": False, "bairro": c}
    others = await db.bairros_vlan_map.find(
        {"company_id": cid}, {"_id": 0, "bairro": 1, "vlan": 1, "sigla": 1},
    ).to_list(500)
    same_name_other_vlan = [
        o for o in others if _norm(o.get("bairro", "")) == target
    ]
    sigla = _auto_sigla_from(bairro_in)
    base_sigla = sigla
    n = 2
    while await db.bairros_vlan_map.find_one(
        {"company_id": cid, "sigla": sigla},
    ):
        sigla = f"{base_sigla[:3]}{n}"
        n += 1
        if n > 99:
            raise HTTPException(500, "Não foi possível gerar sigla única")
    doc = {
        "id": _new_id("bar"),
        "company_id": cid,
        "bairro": bairro_in,
        "sigla": sigla,
        "vlan": vlan,
        "cidade": body.cidade.strip(),
        "estado": body.estado.strip().upper(),
        "regiao": "",
        "auto_created": True,
        "created_at": now_iso(),
    }
    await db.bairros_vlan_map.insert_one(doc)
    doc.pop("_id", None)
    return {
        "ok": True,
        "created": True,
        "bairro": doc,
        "warning_other_vlans": [
            {"vlan": o["vlan"], "sigla": o.get("sigla")} for o in same_name_other_vlan
        ] if same_name_other_vlan else None,
    }


@router.get("/public/ctos/by-id/{cto_id}")
async def public_cto_by_id(cto_id: str, collab_id: Optional[str] = Query(default=None)):
    """iter211bg — Endpoint público para o LousaMobile polling do status
    de sincronia SmartOLT após criar uma CTO. Sem auth, só requer cto_id.
    """
    cto = await db.ctos.find_one(
        {"id": cto_id},
        {"_id": 0, "id": 1, "name": 1, "vlan": 1,
          "smartolt_eligible": 1, "smartolt_olt_name": 1,
          "smartolt_sync_pending": 1, "smartolt_synced_at": 1,
          "smartolt_zone_name": 1, "smartolt_last_error": 1},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    return cto


@router.get("/public/ctos/{cto_id}/recent-status")
async def public_cto_recent_status(cto_id: str,
                                     window_days: int = Query(5, ge=0, le=90)):
    """iter199 — Verifica se a CTO foi cadastrada há menos de `window_days` dias.

    Usado pelo LousaMobile para PULAR a obrigatoriedade de foto da CTO durante
    a OS quando ela é nova (já foi fotografada no cadastro, não faz sentido
    pedir de novo).

    Pedido do usuário 10/02/2026: "crie um data para o cadastro da cto, enquanto
    a cto tiver 5 dias de cadastro não peça foto dela na OS".

    Retorna: {is_recent, days_since, created_at, window_days}
    """
    cto = await db.ctos.find_one({"id": cto_id},
                                    {"_id": 0, "created_at": 1, "name": 1})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    created = cto.get("created_at")
    if not created:
        return {"is_recent": False, "days_since": None,
                "created_at": None, "window_days": window_days}
    try:
        if isinstance(created, str):
            # Aceita tanto ISO com Z quanto sem timezone
            iso = created.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
        else:
            dt = created
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days_since = delta.total_seconds() / 86400.0
        return {
            "is_recent": days_since < window_days,
            "days_since": round(days_since, 2),
            "created_at": created if isinstance(created, str) else created.isoformat(),
            "window_days": window_days,
        }
    except Exception as e:
        logger.warning("[rede-ia] recent-status parse fail cto=%s: %s", cto_id, e)
        return {"is_recent": False, "days_since": None,
                "created_at": str(created), "window_days": window_days}


@router.get("/public/ctos/list/{collab_id}")
async def public_ctos_list(collab_id: str,
                             status: Optional[str] = Query(None),
                             lat: Optional[float] = Query(None),
                             lng: Optional[float] = Query(None),
                             radius_km: float = Query(5.0, ge=0.1, le=50.0),
                             limit: int = Query(500, ge=1, le=2000)):
    """Lista CTOs da empresa do colaborador. Usado pelo wizard mobile
    para mostrar CTOs já cadastradas no mapa e evitar duplicação.

    iter185 — Para técnicos (instalador/reparador), só retornamos CTOs
    dentro do raio (`radius_km`, default 5km) do GPS atual do técnico.
    Se o role for gestor/admin/auditor, mostra TUDO sem filtro de raio.
    """
    cid = await _company_for_collaborator(collab_id)
    col = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "role": 1, "name": 1},
    )
    role_lower = ((col or {}).get("role") or "").lower()
    is_tech = bool(
        "tecnico" in role_lower or "técnico" in role_lower
        or "instalador" in role_lower or "reparador" in role_lower
        or "campo" in role_lower
    )
    is_admin = bool(
        "admin" in role_lower or "gestor" in role_lower
        or "auditor" in role_lower or "supervisor" in role_lower
    )

    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    items = await db.ctos.find(
        q, {"_id": 0, "id": 1, "name": 1, "sigla": 1, "vlan": 1,
            "gps": 1, "capacity": 1, "ports": 1, "status": 1, "address": 1,
            "element_type": 1},
    ).limit(limit).to_list(limit)

    # Filtro por raio — só pra técnicos (não admins) com GPS válido.
    filtered_count = 0
    if is_tech and not is_admin and lat is not None and lng is not None:
        try:
            from math import radians, sin, cos, sqrt, asin
            def haversine(lat1, lng1, lat2, lng2):
                R = 6371.0  # km
                la1, lo1, la2, lo2 = map(radians, (lat1, lng1, lat2, lng2))
                dlat, dlon = la2 - la1, lo2 - lo1
                a = sin(dlat/2)**2 + cos(la1)*cos(la2)*sin(dlon/2)**2
                return 2 * R * asin(sqrt(a))
            kept: List[Dict[str, Any]] = []
            with_gps = 0
            for c in items:
                gps = c.get("gps") or {}
                cgps_lat = gps.get("lat")
                cgps_lng = gps.get("lng")
                if cgps_lat is None or cgps_lng is None:
                    continue
                with_gps += 1
                if haversine(lat, lng, cgps_lat, cgps_lng) <= radius_km:
                    kept.append(c)
            filtered_count = with_gps - len(kept)
            items = kept
        except Exception as e:
            logger.warning("[rede-ia] radius filter fail: %s", e)

    # Garante array de ports
    for c in items:
        c["ports"] = c.get("ports") or []
    return {
        "items": items, "total": len(items),
        "radius_km": radius_km if is_tech and not is_admin else None,
        "filtered_out_count": filtered_count,
        "role_filter_applied": is_tech and not is_admin and lat is not None,
    }



@router.get("/public/ctos/suggest-name/{collab_id}")
async def public_suggest_name(collab_id: str,
                                sigla: str = Query(...),
                                vlan: int = Query(...),
                                number: Optional[int] = Query(None),
                                element_type: str = Query("cto")):
    cid = await _company_for_collaborator(collab_id)
    sigla_u = sigla.upper()
    elem_t = (element_type or "cto").lower()
    # Filtro por tipo para sugestão correta (CTO 001 e CE 001 coexistem)
    if elem_t == "cto":
        type_filter: Dict[str, Any] = {"$or": [
            {"element_type": "cto"},
            {"element_type": {"$exists": False}},
            {"element_type": None},
        ]}
    else:
        type_filter = {"element_type": elem_t}
    if number is not None:
        # iter180 — nova nomenclatura: sigla saiu do critério.
        # CTO/CABO: únicos por (company, vlan, number, type)
        # CE: único por (company, number, type)
        ex_q: Dict[str, Any] = {
            "company_id": cid, "number": number, **type_filter,
        }
        if elem_t != "ce":
            ex_q["vlan"] = vlan
        existing = await db.ctos.find_one(ex_q)
        if existing:
            nxt = await _next_cto_number(cid, sigla_u, vlan, elem_t)
            return {
                "exists": True,
                "suggested_number": nxt,
                "suggested_name": _format_cto_name(nxt, vlan, sigla_u, elem_t),
            }
        return {
            "exists": False,
            "suggested_number": number,
            "suggested_name": _format_cto_name(number, vlan, sigla_u, elem_t),
        }
    nxt = await _next_cto_number(cid, sigla_u, vlan, elem_t)
    return {
        "exists": False,
        "suggested_number": nxt,
        "suggested_name": _format_cto_name(nxt, vlan, sigla_u, elem_t),
    }


# =============================================================================
# iter180 — Sentinela IA: validação automática da foto da CTO/CE
# =============================================================================
class PhotoValidateIn(BaseModel):
    photo_data_url: str = Field(..., description="data:image/jpeg;base64,...")
    lat: Optional[float] = None
    lng: Optional[float] = None
    element_type: str = "cto"


@router.post("/public/photo-validate/{collab_id}")
async def public_photo_validate(collab_id: str, body: PhotoValidateIn):
    """Validação Sentinela IA da foto enviada pelo técnico via PWA.

    Combina dedupe + GPS + Claude Sonnet 4.5 vision e devolve uma decisão
    (`approve`/`retake`/`open_ticket`). Frontend usa o `action` para
    decidir se libera o próximo passo do wizard.
    """
    from services.cto_photo_validator import validate_photo  # lazy import
    cid = await _company_for_collaborator(collab_id)
    return await validate_photo(
        data_url=body.photo_data_url,
        company_id=cid, collaborator_id=collab_id,
        element_type=body.element_type,
        lat=body.lat, lng=body.lng, persist=True,
    )


@router.post("/photo-validate")
async def auth_photo_validate(body: PhotoValidateIn,
                                  user: dict = Depends(get_current_user)):
    """Versão autenticada (uso em LousaMobile / OS via gestor logado)."""
    from services.cto_photo_validator import validate_photo  # lazy import
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await validate_photo(
        data_url=body.photo_data_url,
        company_id=cid,
        collaborator_id=user.get("collaborator_id") or user.get("id"),
        element_type=body.element_type,
        lat=body.lat, lng=body.lng, persist=True,
    )


# iter181 — Sentinela IA: threshold ajustável por empresa --------------
class SentinelaConfigIn(BaseModel):
    sentinela_min_score: int = Field(..., ge=0, le=100)


@router.get("/sentinela/config")
async def get_sentinela_config(
    user: dict = Depends(require_role("administrador", "gestor",
                                          "auditor", "gestor_rede")),
):
    """Threshold mínimo de aprovação da Sentinela IA na empresa."""
    cid = _user_company(user)
    s = await db.settings.find_one(
        {"id": cid}, {"_id": 0, "sentinela_min_score": 1}) or {}
    return {
        "sentinela_min_score": int(s.get("sentinela_min_score") or 69),
        "default": 69,
        "presets": [
            {"value": 50, "label": "Permissivo",
             "desc": "Aceita fotos com qualidade razoável (50/100)"},
            {"value": 69, "label": "Equilibrado · padrão",
             "desc": "Bom equilíbrio entre aceite e qualidade"},
            {"value": 75, "label": "Rigoroso",
             "desc": "Exige fotos boas, bem enquadradas"},
            {"value": 85, "label": "Muito rigoroso",
             "desc": "Só aceita fotos excelentes"},
        ],
    }


@router.patch("/sentinela/config")
async def patch_sentinela_config(
    body: SentinelaConfigIn,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede")),
):
    """Atualiza o threshold mínimo de aprovação da Sentinela IA."""
    cid = _user_company(user)
    await db.settings.update_one(
        {"id": cid},
        {"$set": {"sentinela_min_score": int(body.sentinela_min_score)}},
        upsert=True,
    )
    return {"ok": True, "sentinela_min_score": int(body.sentinela_min_score)}


@router.post("/public/photo-validate/{collab_id}/open-ticket")
async def public_photo_open_ticket(collab_id: str, body: dict):
    """Abre chamado de manutenção a partir do resultado da Sentinela IA.

    Body: { photo_validation_id, lat, lng, condition, summary, cto_id?, os_id? }
    """
    # iter181 — Sentinela IA config inline acima (rotas /sentinela/config)
    cid = await _company_for_collaborator(collab_id)
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "name": 1, "id": 1, "company_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    condition = (body.get("condition") or "quebrada").lower()
    title = ("CTO quebrada" if condition == "quebrada"
             else "CTO sem tampa" if condition == "sem_tampa"
             else "Foto da CTO requer revisão")
    ticket = {
        "id": f"tk-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "manutencao_rede",
        "subtype": condition,
        "priority": "alta" if condition == "quebrada" else "media",
        "title": title,
        "summary": str(body.get("summary") or "")[:240],
        "status": "open",
        "source": "sentinela_ia_cto",
        "lat": body.get("lat"), "lng": body.get("lng"),
        "created_by": collab_id,
        "created_by_name": coll.get("name"),
        "linked_cto_id": body.get("cto_id"),
        "linked_os_id": body.get("os_id"),
        "photo_validation_id": body.get("photo_validation_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.network_tickets.insert_one(ticket)
    return {"ok": True, "ticket_id": ticket["id"], "ticket": ticket}


@router.post("/public/ctos/{collab_id}")
async def public_create_cto(collab_id: str, body: CTOCreateIn):
    """Cria elemento de rede (CTO/CE/CABO) via app público do técnico."""
    elem_t_pre = (body.element_type or "cto").lower()
    # Validações genéricas (capacidade + rede) só se aplicam à CTO real.
    # CE e CABO recebem defaults seguros (capacity=8, network=balanceada)
    # mas têm validações específicas mais abaixo.
    if elem_t_pre == "cto":
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

    # Normaliza a sigla: remove acentos e maiúsculas (resiliente a versões
    # antigas do app que mandavam sigla com acento — "BRÁ" → "BRA")
    import unicodedata as _u
    _norm = "".join(c for c in _u.normalize("NFD", body.sigla or "")
                     if _u.category(c) != "Mn")
    sigla_u = _norm.upper().strip()

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

    # Validações específicas por element_type (boas práticas GIS):
    # CE precisa de número de bandejas. CABO precisa de from+to+fibras totais.
    elem_t = (body.element_type or "cto").lower()
    if elem_t == "ce":
        if not body.bandejas_total or body.bandejas_total < 1:
            raise HTTPException(400, "CE: informe o número de bandejas/emendas.")
    elif elem_t == "cabo":
        if not body.from_element_id or not body.to_element_id:
            raise HTTPException(400,
                "CABO: informe o ponto de origem e destino (CTO/CE).")
        if body.from_element_id == body.to_element_id:
            raise HTTPException(400,
                "CABO: origem e destino não podem ser o mesmo elemento.")
        if not body.fibras_total or body.fibras_total not in (2, 4, 6, 12, 24, 36, 48, 72, 96, 144):
            raise HTTPException(400,
                "CABO: capacidade de fibras inválida (use 2, 4, 6, 12, 24, 36, 48, 72, 96 ou 144).")
        # Verifica se os endpoints existem
        for ep in (body.from_element_id, body.to_element_id):
            if not await db.ctos.find_one({"id": ep, "company_id": cid}, {"_id": 0, "id": 1}):
                raise HTTPException(400,
                    f"CABO: elemento {ep} não encontrado na empresa.")

    # Precedência do número: cto_number explícito > suggested_name > auto.
    # iter180 — Parsers atualizados para nova nomenclatura:
    #   CTO  "CTO_301_004"   → split por "_", índice 2 é o número
    #   CABO "CABO_301_004"  → idem
    #   CE   "CE_00001"      → split por "_", índice 1 é o número
    if isinstance(body.cto_number, int) and body.cto_number > 0:
        number = body.cto_number
    elif elem_t == "ce":
        try:
            sn = (body.suggested_name or "").upper().strip()
            assert sn.startswith("CE_")
            number = int(sn.split("_", 1)[1].strip())
        except Exception:
            number = await _next_cto_number(cid, sigla_u, body.vlan, elem_t)
    else:
        try:
            sn = (body.suggested_name or "").upper().strip()
            # Aceita tanto novo "CTO_301_004" quanto legado "CTO 004_301_BRA"
            if "_" in sn and " " not in sn.split("_", 1)[0]:
                parts = sn.split("_")
                # "CTO" "301" "004" → número é o último (3 dígitos)
                number = int(parts[-1])
            else:
                num_part = sn.split(" ")[1].split("_")[0]
                number = int(num_part)
        except Exception:
            number = await _next_cto_number(cid, sigla_u, body.vlan, elem_t)

    # Duplicidade considera o tipo. iter180:
    # • CTO/CABO únicos por (company, vlan, number)
    # • CE únicos por (company, number)
    dup_type_filter: Dict[str, Any]
    if elem_t == "cto":
        dup_type_filter = {"$or": [
            {"element_type": "cto"},
            {"element_type": {"$exists": False}},
            {"element_type": None},
        ]}
    else:
        dup_type_filter = {"element_type": elem_t}
    dup_query: Dict[str, Any] = {
        "company_id": cid, "number": number, **dup_type_filter,
    }
    if elem_t != "ce":
        dup_query["vlan"] = body.vlan
    dup = await db.ctos.find_one(dup_query)
    if dup:
        nxt = await _next_cto_number(cid, sigla_u, body.vlan, elem_t)
        raise HTTPException(409, {
            "msg": f"{_format_cto_name(number, body.vlan, sigla_u, elem_t)} já existe",
            "suggested_number": nxt,
            "suggested_name": _format_cto_name(nxt, body.vlan, sigla_u, elem_t),
        })

    name = _format_cto_name(number, body.vlan, sigla_u,
                              (body.element_type or "cto").lower())
    # CE/CABO não têm portas físicas — armazenamos array vazio.
    if elem_t == "cto":
        ports = [{
            "number": i,
            "status": "used" if i == body.client_port else "free",
            "client_subscriber_id": body.client_subscriber_id if i == body.client_port else None,
            "client_pppoe": body.client_pppoe if i == body.client_port else None,
        } for i in range(1, body.capacity + 1)]
    else:
        ports = []

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
        "box_number": (body.box_number or "").strip() or None,
        "element_type": (body.element_type or "cto").lower(),
        "bandejas_total": body.bandejas_total,
        "ce_install_type": (body.ce_install_type or "").lower() or None,
        "fibras_total": body.fibras_total,
        "fibras_ocupadas": body.fibras_ocupadas,
        "cable_type": (body.cable_type or "").lower() or None,
        "from_element_id": body.from_element_id,
        "to_element_id": body.to_element_id,
        "is_as_built": bool(body.is_as_built),
        # iter183 — Roteamento e identificação física do cabo (público)
        "fo_count": body.fo_count,
        "cable_brand": (body.cable_brand or "").strip() or None,
        "cable_serial": (body.cable_serial or "").strip() or None,
        "route_geometry": body.route_geometry or None,
        "route_distance_m": body.route_distance_m or None,
        "extra_margin_m": body.extra_margin_m if body.extra_margin_m is not None else 20,
        "total_length_m": (
            (body.route_distance_m or 0)
            + (body.extra_margin_m if body.extra_margin_m is not None else 20)
        ) if body.route_distance_m else None,
        "to_gps": ({"lat": body.to_lat, "lng": body.to_lng}
                       if body.to_lat is not None and body.to_lng is not None else None),
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
        "photo_extra_data_url": body.photo_extra_data_url,
    }
    await db.ctos.insert_one(doc)

    # iter183 — Sincroniza Base de Portas (cto_ports) para a nova CTO
    try:
        from routes.cto_ports_base import sync_cto_all_ports
        await sync_cto_all_ports(cid, cto_id)
    except Exception as _e:
        logger.warning("[rede-ia/public] sync_cto_all_ports falhou cto=%s: %s",
                          cto_id, _e)

    # iter211bc — Classifica elegibilidade SmartOLT (idêntico ao endpoint
    # autenticado). CTOs em VLAN que pertence a SmartOLT serão sincronizadas.
    try:
        cto_vlan2 = int(doc.get("vlan") or 0)
        smartolt_eligible2 = False
        olt_name2 = None
        if cto_vlan2 > 0:
            bairro_olt2 = await db.bairros_vlan_map.find_one(
                {"company_id": cid, "vlan": cto_vlan2,
                  "olt_name": {"$exists": True, "$nin": [None, ""]}},
                {"_id": 0, "olt_name": 1},
            )
            if bairro_olt2 and bairro_olt2.get("olt_name"):
                smartolt_eligible2 = True
                olt_name2 = bairro_olt2["olt_name"]
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid},
            {"$set": {
                "smartolt_eligible": smartolt_eligible2,
                "smartolt_olt_name": olt_name2,
                "smartolt_sync_pending": smartolt_eligible2,
            }},
        )
        doc["smartolt_eligible"] = smartolt_eligible2
        doc["smartolt_olt_name"] = olt_name2
    except Exception as _e:
        logger.warning("[rede-ia/public] classify smartolt_eligible falhou: %s", _e)

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

    # iter183 — Sync Base de Portas (porta recém-vinculada via QR)
    try:
        from routes.cto_ports_base import sync_port_from_cto
        await sync_port_from_cto(cid, body.cto_id, body.port_number)
    except Exception as _e:
        logger.warning("[rede-ia/qr-bind] sync porta falhou cto=%s p=%s: %s",
                          body.cto_id, body.port_number, _e)

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
    """Apaga uma CTO + cabos relacionados. Logado em rede_ia_history.
    iter215bk — Snapshot em rede_ia_trash para suportar Undo."""
    cid = _user_company(user)
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    # Snapshot pré-delete (cabos + cto_ports) para restore
    cables_snap = await db.rede_cables.find(
        {"company_id": cid,
         "$or": [{"from_cto_id": cto_id}, {"to_cto_id": cto_id}]},
        {"_id": 0}).to_list(500)
    ports_snap = await db.cto_ports.find(
        {"cto_id": cto_id, "company_id": cid}, {"_id": 0}).to_list(500)
    actor = user.get("name") or user.get("email") or "?"
    await db.rede_ia_trash.insert_one({
        "id": f"trash-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "kind": "cto", "ref_id": cto_id,
        "label": cto.get("name") or cto_id,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "deleted_by": actor,
        "snapshot": cto,
        "cables_snapshot": cables_snap,
        "ports_snapshot": ports_snap,
    })
    cables_deleted = await db.rede_cables.delete_many(
        {"company_id": cid, "$or": [{"from_cto_id": cto_id}, {"to_cto_id": cto_id}]},
    )
    await db.ctos.delete_one({"id": cto_id, "company_id": cid})
    # iter183 — Limpa Base de Portas (cto_ports) em cascata
    try:
        delp = await db.cto_ports.delete_many({"cto_id": cto_id, "company_id": cid})
        logger.info("[rede-ia] CTO %s deletada · %d portas removidas da base",
                       cto_id, delp.deleted_count)
    except Exception as _e:
        logger.warning("[rede-ia] cto_ports cleanup falhou cto=%s: %s", cto_id, _e)
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


# =============================================================================
# iter180 — Sync de VLAN do SmartOLT → subscribers.current_vlan
# =============================================================================
@router.post("/smartolt/sync-vlan-to-subscribers")
async def sync_vlan_from_smartolt(
    dry_run: bool = Query(False, description="Se True, só simula e devolve preview"),
    user: dict = Depends(require_role("administrador", "gestor", "auditor", "gestor_rede")),
):
    """Lê `service_ports[0].vlan` de cada ONU do SmartOLT (status Online) e
    atualiza `subscribers.current_vlan` para os já conectados.

    Match strategy (em ordem):
      1. `subscribers.pppoe_user == onus.pppoe_user`
      2. `subscribers.pppoe_user == onus.name` (fallback — no SmartOLT
         o nome da ONU costuma ser o próprio PPPoE quando o campo
         `pppoe_user` da ONU não está populado)
      3. `subscribers.metadata.sn == onus.sn` (último fallback)

    Persiste: `current_vlan`, `current_vlan_synced_at`,
              `current_vlan_source = "smartolt"`,
              `current_vlan_olt = <olt_name>`,
              `current_vlan_pon = "<board>/<port>"`.
    """
    cid = _user_company(user)
    cursor = db.smartolt_onus.find(
        {"company_id": cid, "status": "Online"},
        {"_id": 0, "service_ports": 1, "pppoe_user": 1, "sn": 1,
         "olt_name": 1, "board": 1, "port": 1, "name": 1},
    )
    summary = {
        "scanned": 0, "with_vlan": 0,
        "matched_by_pppoe": 0, "matched_by_name": 0, "matched_by_sn": 0,
        "updated": 0, "unchanged": 0, "no_subscriber": 0,
        "samples": [],
    }
    async for o in cursor:
        summary["scanned"] += 1
        sp_list = o.get("service_ports") or []
        vlan_raw = None
        for sp in sp_list:
            v = (sp or {}).get("vlan")
            if v not in (None, "", "0"):
                vlan_raw = v
                break
        if not vlan_raw:
            continue
        try:
            vlan = int(str(vlan_raw).strip())
        except Exception:
            continue
        summary["with_vlan"] += 1
        sub = None
        match_kind = None
        if o.get("pppoe_user"):
            sub = await db.subscribers.find_one(
                {"company_id": cid, "pppoe_user": o["pppoe_user"]},
                {"_id": 0, "id": 1, "current_vlan": 1, "name": 1},
            )
            if sub:
                match_kind = "pppoe"
                summary["matched_by_pppoe"] += 1
        if sub is None and o.get("name"):
            # Fallback: SmartOLT muitas vezes só popula `name` (que costuma
            # ser o próprio PPPoE configurado no concentrador) deixando o
            # campo `pppoe_user` vazio.
            sub = await db.subscribers.find_one(
                {"company_id": cid, "pppoe_user": o["name"]},
                {"_id": 0, "id": 1, "current_vlan": 1, "name": 1},
            )
            if sub:
                match_kind = "name"
                summary["matched_by_name"] += 1
        if sub is None and o.get("sn"):
            sub = await db.subscribers.find_one(
                {"company_id": cid, "metadata.sn": o["sn"]},
                {"_id": 0, "id": 1, "current_vlan": 1, "name": 1},
            )
            if sub:
                match_kind = "sn"
                summary["matched_by_sn"] += 1
        if sub is None:
            summary["no_subscriber"] += 1
            continue
        if sub.get("current_vlan") == vlan:
            summary["unchanged"] += 1
            continue
        if dry_run:
            summary["updated"] += 1
        else:
            await db.subscribers.update_one(
                {"id": sub["id"]},
                {"$set": {
                    "current_vlan": vlan,
                    "current_vlan_synced_at": now_iso(),
                    "current_vlan_source": "smartolt",
                    "current_vlan_match": match_kind,
                    "current_vlan_olt": o.get("olt_name"),
                    "current_vlan_pon": f"{o.get('board')}/{o.get('port')}",
                }},
            )
            summary["updated"] += 1
        if len(summary["samples"]) < 12:
            summary["samples"].append({
                "subscriber_name": sub.get("name"),
                "match": match_kind,
                "pppoe_user": o.get("pppoe_user") or o.get("name"),
                "sn": o.get("sn"),
                "previous_vlan": sub.get("current_vlan"),
                "new_vlan": vlan,
                "olt": o.get("olt_name"),
                "pon": f"{o.get('board')}/{o.get('port')}",
            })

    # iter181 — Fallback VLAN 1 para subscribers que NÃO casaram com SmartOLT.
    # Regra do gestor: cliente que não foi encontrado na SmartOLT entra em
    # VLAN 1 como default, EXCETO se ainda tiver OS de Instalação ativa
    # (esses ficam sem VLAN — vão receber a VLAN real após instalação).
    summary["default_vlan_1_applied"] = 0
    summary["default_vlan_1_skipped_instalacao"] = 0

    # Coleta IDs de subscribers que têm OS de instalação ABERTA/EM ANDAMENTO
    # (qualquer status diferente de finalizada/cancelada).
    pending_install_subs = set()
    async for t in db.lousa_tickets.find(
        {"company_id": cid, "type": "instalacao",
         "status": {"$nin": ["finalizada", "cancelada"]}},
        {"_id": 0, "subscriber_id": 1, "client_id": 1},
    ):
        sid = t.get("subscriber_id") or t.get("client_id")
        if sid:
            pending_install_subs.add(sid)

    # Subscribers ATIVOS sem current_vlan
    sub_no_vlan_cursor = db.subscribers.find(
        {"company_id": cid,
         "current_vlan": {"$in": [None]},
         "status": {"$in": ["ATIVO", "BLOQUEADO", "SUSPENSO", "INADIMPLENTE"]}},
        {"_id": 0, "id": 1, "name": 1, "status": 1},
    )
    async for sub in sub_no_vlan_cursor:
        if sub["id"] in pending_install_subs:
            summary["default_vlan_1_skipped_instalacao"] += 1
            continue
        if dry_run:
            summary["default_vlan_1_applied"] += 1
            continue
        await db.subscribers.update_one(
            {"id": sub["id"]},
            {"$set": {
                "current_vlan": 1,
                "current_vlan_synced_at": now_iso(),
                "current_vlan_source": "default_vlan_1",
                "current_vlan_match": None,
            }},
        )
        summary["default_vlan_1_applied"] += 1
        if len(summary["samples"]) < 16:
            summary["samples"].append({
                "subscriber_name": sub.get("name"),
                "match": "default_vlan_1",
                "previous_vlan": None,
                "new_vlan": 1,
            })

    return {"ok": True, "dry_run": dry_run, **summary}


@router.get("/smartolt/vlan-change-tickets")
async def list_vlan_change_tickets(
    status: Optional[str] = Query("open"),
    user: dict = Depends(require_role("administrador", "gestor",
                                          "auditor", "gestor_rede")),
):
    """Lista tickets de mudança inesperada de VLAN (gerados pelo worker)."""
    cid = _user_company(user)
    q: Dict[str, Any] = {
        "company_id": cid, "type": "vlan_change_unexpected",
    }
    if status:
        q["status"] = status
    items = await db.network_tickets.find(q, {"_id": 0}).sort(
        "created_at", -1).limit(200).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/smartolt/vlan-history/{subscriber_id}")
async def vlan_history(subscriber_id: str,
                          user: dict = Depends(require_role("administrador",
                              "gestor", "auditor", "gestor_rede"))):
    """Histórico completo de mudanças de VLAN de um assinante."""
    cid = _user_company(user)
    items = await db.subscriber_vlan_history.find(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0},
    ).sort("changed_at", -1).limit(50).to_list(50)
    return {"items": items, "total": len(items)}


@router.get("/smartolt/vlan-coverage")
async def vlan_coverage(user: dict = Depends(require_role("administrador",
                                "gestor", "auditor", "gestor_rede"))):
    """Mostra quantos subscribers já têm `current_vlan` populado e a
    distribuição por VLAN (KPI para o card de sync)."""
    cid = _user_company(user)
    total = await db.subscribers.count_documents({"company_id": cid})
    with_vlan = await db.subscribers.count_documents(
        {"company_id": cid, "current_vlan": {"$ne": None}})
    pipeline = [
        {"$match": {"company_id": cid, "current_vlan": {"$ne": None}}},
        {"$group": {"_id": "$current_vlan", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    by_vlan = []
    async for r in db.subscribers.aggregate(pipeline):
        by_vlan.append({"vlan": r["_id"], "count": r["count"]})
    return {"total": total, "with_vlan": with_vlan,
            "coverage_pct": round((with_vlan / total * 100) if total else 0, 1),
            "by_vlan": by_vlan}



# ============================================================================
# iter183 — Cabos: roteamento (OSRM) + estatísticas por VLAN
# ============================================================================

class CableRouteIn(BaseModel):
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float
    profile: str = "foot"
    # iter187 — Waypoints intermediários (modo Google Maps-like).
    # Cada item: [lat, lng]. OSRM passa pelo trajeto na ordem dada.
    waypoints: Optional[List[List[float]]] = None


@router.post("/cables/route")
async def cable_route(body: CableRouteIn,
                          user: dict = Depends(require_role(
                              "tecnico", "gestor", "administrador",
                              "auditor", "gestor_rede"))):
    return await _osrm_route(body.from_lat, body.from_lng,
                                body.to_lat, body.to_lng, body.profile,
                                waypoints=body.waypoints)


@router.post("/public/cables/route/{collab_id}")
async def public_cable_route(collab_id: str, body: CableRouteIn):
    coll = await db.collaborators.find_one({"id": collab_id},
                                              {"_id": 0, "company_id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return await _osrm_route(body.from_lat, body.from_lng,
                                body.to_lat, body.to_lng, body.profile,
                                waypoints=body.waypoints)


async def _osrm_route(from_lat: float, from_lng: float,
                          to_lat: float, to_lng: float,
                          profile: str = "foot",
                          waypoints: Optional[List[List[float]]] = None,
                          ) -> Dict[str, Any]:
    osrm_profile = profile if profile in ("foot", "driving", "bike") else "foot"
    # Monta sequência lng,lat;lng,lat;... incluindo waypoints
    pts: List[str] = [f"{from_lng},{from_lat}"]
    if waypoints:
        for wp in waypoints:
            if isinstance(wp, (list, tuple)) and len(wp) >= 2:
                pts.append(f"{wp[1]},{wp[0]}")
    pts.append(f"{to_lng},{to_lat}")
    url = (f"https://router.project-osrm.org/route/v1/{osrm_profile}/"
            f"{';'.join(pts)}"
            f"?geometries=geojson&overview=full")
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(url)
            if r.status_code != 200:
                raise Exception(f"OSRM HTTP {r.status_code}")
            j = r.json()
            if j.get("code") != "Ok" or not j.get("routes"):
                raise Exception(f"OSRM: {j.get('message') or 'sem rota'}")
            route = j["routes"][0]
            coords = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
            return {
                "success": True,
                "geometry": coords,
                "distance_m": round(route.get("distance") or 0, 2),
                "duration_s": round(route.get("duration") or 0, 1),
                "source": "osrm",
            }
    except Exception as e:
        from math import radians, sin, cos, asin, sqrt
        R = 6371000
        dlat = radians(to_lat - from_lat)
        dlng = radians(to_lng - from_lng)
        a = sin(dlat / 2) ** 2 + cos(radians(from_lat)) \
              * cos(radians(to_lat)) * sin(dlng / 2) ** 2
        dist = 2 * R * asin(sqrt(a))
        return {
            "success": False,
            "geometry": [[from_lat, from_lng], [to_lat, to_lng]],
            "distance_m": round(dist, 2),
            "duration_s": None,
            "source": "haversine_fallback",
            "warning": f"OSRM indisponível: {e}. Usando linha reta.",
        }


@router.get("/vlans/{vlan}/stats")
async def vlan_stats(vlan: int,
                          user: dict = Depends(require_role(
                              "tecnico", "gestor", "administrador",
                              "auditor", "gestor_rede"))):
    cid = _user_company(user)
    elements = await db.ctos.find(
        {"company_id": cid, "vlan": vlan},
        {"_id": 0, "id": 1, "name": 1, "element_type": 1, "total_length_m": 1,
         "route_distance_m": 1, "capacity": 1, "ports": 1, "cable_brand": 1,
         "fo_count": 1},
    ).to_list(2000)

    by_type = {"cto": [], "ce": [], "cabo": []}
    for e in elements:
        t = (e.get("element_type") or "cto").lower()
        by_type.setdefault(t, []).append(e)

    cabos = by_type["cabo"]
    total_cable_m = sum((c.get("total_length_m") or 0) for c in cabos)
    total_route_m = sum((c.get("route_distance_m") or 0) for c in cabos)

    ports_used = 0
    ports_total = 0
    for cto in by_type["cto"]:
        ports_total += int(cto.get("capacity") or 0)
        for p in (cto.get("ports") or []):
            if p.get("status") in ("used", "ocupada", "occupied"):
                ports_used += 1

    return {
        "vlan": vlan,
        "ctos_count": len(by_type["cto"]),
        "ces_count": len(by_type["ce"]),
        "cables_count": len(cabos),
        "total_cable_m": round(total_cable_m, 2),
        "total_route_m": round(total_route_m, 2),
        "ports_used": ports_used,
        "ports_total": ports_total,
        "occupancy_pct": round((ports_used / ports_total * 100), 1)
                              if ports_total else 0.0,
    }



# ============================================================================
# iter186 — Cabos Órfãos: detecção, vínculo manual e sugestão por IA
# ============================================================================

class LinkEndpointIn(BaseModel):
    endpoint: str = Field(..., description='"from" ou "to"')
    element_id: str = Field(..., description="ID da CTO/CE para vincular")


def _cable_loose_endpoints(cab: dict,
                            existing_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Retorna lista de pontas SOLTAS do cabo, com lat/lng deduzido.

    Uma ponta é considerada SOLTA quando:
      - `*_element_id` está em null/vazio, OU
      - `*_element_id` aponta para um ID que NÃO existe mais (zumbi) —
        só detectado se `existing_ids` for fornecido.

    Cada item: {"end": "from"|"to", "lat": float, "lng": float,
                "zombie_id": str|None}  (`zombie_id` preenchido se zumbi)
    """
    out = []
    geom = cab.get("route_geometry") or []
    from_id = cab.get("from_element_id")
    to_id = cab.get("to_element_id")
    from_zombie = bool(from_id) and (existing_ids is not None and from_id not in existing_ids)
    to_zombie = bool(to_id) and (existing_ids is not None and to_id not in existing_ids)

    if not from_id or from_zombie:
        if geom:
            out.append({"end": "from", "lat": geom[0][0], "lng": geom[0][1],
                         "zombie_id": from_id if from_zombie else None})
        elif (cab.get("gps") or {}).get("lat") is not None:
            g = cab["gps"]
            out.append({"end": "from", "lat": g["lat"], "lng": g["lng"],
                         "zombie_id": from_id if from_zombie else None})
    if not to_id or to_zombie:
        if geom:
            out.append({"end": "to", "lat": geom[-1][0], "lng": geom[-1][1],
                         "zombie_id": to_id if to_zombie else None})
        elif (cab.get("to_gps") or {}).get("lat") is not None:
            g = cab["to_gps"]
            out.append({"end": "to", "lat": g["lat"], "lng": g["lng"],
                         "zombie_id": to_id if to_zombie else None})
    return out


async def _get_existing_element_ids(cid: str) -> set:
    """iter209 — Conjunto de IDs ativos de CTO/CE (não-cabos) na empresa.

    Usado para detectar cabos com `from_element_id`/`to_element_id` apontando
    para elementos que foram deletados ("órfãos zumbi").
    """
    ids: set = set()
    async for doc in db.ctos.find(
        {"company_id": cid,
         "element_type": {"$in": ["cto", "ce"]}},
        {"_id": 0, "id": 1},
    ):
        if doc.get("id"):
            ids.add(doc["id"])
    return ids


async def _is_orphan_cable(cab: dict, existing_ids: set) -> bool:
    """Decisão centralizada: cabo é órfão?

    Por:
      - status `cabo_solto`
      - flag `is_loose=True`
      - alguma ponta `*_element_id` em null
      - alguma ponta aponta para CTO/CE que NÃO existe mais (zumbi)
    """
    if cab.get("status") == "cabo_solto":
        return True
    if cab.get("is_loose"):
        return True
    fid = cab.get("from_element_id")
    tid = cab.get("to_element_id")
    if not fid or not tid:
        return True
    if fid not in existing_ids or tid not in existing_ids:
        return True
    return False


@router.get("/cables/orphan")
async def list_orphan_cables(
    user: dict = Depends(require_role(
        "tecnico", "gestor", "administrador",
        "auditor", "gestor_rede")),
):
    """Lista todos cabos com pelo menos uma ponta solta (inclui zumbis)."""
    cid = _user_company(user)
    existing_ids = await _get_existing_element_ids(cid)
    # Pega TODOS os cabos da empresa e filtra em memória (mongodb não consegue
    # checar "id não existe em outra coleção" sem $lookup pesado).
    items = []
    async for cab in db.ctos.find(
        {"company_id": cid, "element_type": "cabo"},
        {"_id": 0},
    ):
        if not await _is_orphan_cable(cab, existing_ids):
            continue
        endpoints = _cable_loose_endpoints(cab, existing_ids)
        zombies = [e for e in endpoints if e.get("zombie_id")]
        items.append({
            "id": cab.get("id"),
            "name": cab.get("name"),
            "vlan": cab.get("vlan"),
            "sigla": cab.get("sigla"),
            "total_length_m": cab.get("total_length_m"),
            "fo_count": cab.get("fo_count"),
            "cable_type": cab.get("cable_type"),
            "status": cab.get("status"),
            "from_element_id": cab.get("from_element_id"),
            "to_element_id": cab.get("to_element_id"),
            "loose_ends": endpoints,
            "zombie_count": len(zombies),  # iter209
            "route_source": cab.get("route_source"),
            "technician_name": cab.get("technician_name"),
            "created_at": cab.get("created_at"),
        })
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/cables/orphan-near")
async def orphan_cables_near(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(30.0, ge=1.0, le=500.0),
    user: dict = Depends(get_current_user),
):
    """Retorna cabos órfãos com ponta solta a até `radius_m` do (lat,lng).
    Usado pelo wizard mobile pra sugerir vínculo ao cadastrar CTO/CE.
    """
    cid = _user_company(user)
    return await _orphan_near_impl(cid, lat, lng, radius_m)


@router.get("/public/cables/orphan-near/{collab_id}")
async def public_orphan_cables_near(
    collab_id: str,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(30.0, ge=1.0, le=500.0),
):
    """Versão pública pro PWA mobile."""
    cid = await _company_for_collaborator(collab_id)
    return await _orphan_near_impl(cid, lat, lng, radius_m)


@router.get("/cables/audit-orphans")
async def audit_orphans(
    user: dict = Depends(require_role(
        "gestor", "administrador", "auditor", "gestor_rede")),
):
    """iter209 — Auditoria detalhada das pontas órfãs.

    Retorna contagem por critério (cabo_solto, is_loose, null, zombie) para
    super-admin/auditor entender o estado da rede.
    """
    cid = _user_company(user)
    existing_ids = await _get_existing_element_ids(cid)
    counts = {"cabo_solto": 0, "is_loose": 0,
              "from_null": 0, "to_null": 0,
              "from_zombie": 0, "to_zombie": 0,
              "total_orphans": 0, "total_cables": 0}
    zombie_ids: set = set()
    async for cab in db.ctos.find(
        {"company_id": cid, "element_type": "cabo"},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "is_loose": 1,
         "from_element_id": 1, "to_element_id": 1},
    ):
        counts["total_cables"] += 1
        is_orphan = False
        if cab.get("status") == "cabo_solto":
            counts["cabo_solto"] += 1
            is_orphan = True
        if cab.get("is_loose"):
            counts["is_loose"] += 1
            is_orphan = True
        fid = cab.get("from_element_id")
        tid = cab.get("to_element_id")
        if not fid:
            counts["from_null"] += 1
            is_orphan = True
        elif fid not in existing_ids:
            counts["from_zombie"] += 1
            zombie_ids.add(fid)
            is_orphan = True
        if not tid:
            counts["to_null"] += 1
            is_orphan = True
        elif tid not in existing_ids:
            counts["to_zombie"] += 1
            zombie_ids.add(tid)
            is_orphan = True
        if is_orphan:
            counts["total_orphans"] += 1
    return {
        "counts": counts,
        "zombie_target_ids": sorted(zombie_ids),
        "existing_elements_count": len(existing_ids),
    }


@router.post("/cables/audit-orphans/repair")
async def audit_orphans_repair(
    user: dict = Depends(require_role(
        "gestor", "administrador", "auditor", "gestor_rede")),
):
    """iter209 — Limpa referências zumbi e marca cabos como `is_loose=true`.

    Cabos com `from_element_id`/`to_element_id` apontando para CTO/CE que não
    existem mais são corrigidos: o campo é setado para `null` + flag
    `is_loose=true` + `status="cabo_solto"`. Idempotente.
    """
    cid = _user_company(user)
    existing_ids = await _get_existing_element_ids(cid)
    repaired = 0
    details: List[Dict[str, Any]] = []
    async for cab in db.ctos.find(
        {"company_id": cid, "element_type": "cabo"},
        {"_id": 0},
    ):
        fid = cab.get("from_element_id")
        tid = cab.get("to_element_id")
        upd: Dict[str, Any] = {}
        if fid and fid not in existing_ids:
            upd["from_element_id"] = None
            details.append({"cable_id": cab.get("id"),
                             "end": "from", "removed_zombie": fid})
        if tid and tid not in existing_ids:
            upd["to_element_id"] = None
            details.append({"cable_id": cab.get("id"),
                             "end": "to", "removed_zombie": tid})
        if upd:
            upd["is_loose"] = True
            upd["status"] = "cabo_solto"
            upd["updated_at"] = now_iso()
            await db.ctos.update_one(
                {"id": cab["id"], "company_id": cid},
                {"$set": upd},
            )
            await _audit("update", cab["id"], cab, {**cab, **upd}, user,
                         "iter209 cleanup: zombies removidos")
            repaired += 1
    return {"repaired_cables": repaired, "details": details[:50]}


async def _orphan_near_impl(cid: str, lat: float, lng: float,
                                  radius_m: float) -> Dict[str, Any]:
    existing_ids = await _get_existing_element_ids(cid)
    candidates = []
    async for cab in db.ctos.find(
        {"company_id": cid, "element_type": "cabo"},
        {"_id": 0},
    ):
        if not await _is_orphan_cable(cab, existing_ids):
            continue
        for ep in _cable_loose_endpoints(cab, existing_ids):
            d = _haversine_m(lat, lng, ep["lat"], ep["lng"])
            if d <= radius_m:
                candidates.append({
                    "cable_id": cab.get("id"),
                    "cable_name": cab.get("name"),
                    "vlan": cab.get("vlan"),
                    "sigla": cab.get("sigla"),
                    "fo_count": cab.get("fo_count"),
                    "total_length_m": cab.get("total_length_m"),
                    "end": ep["end"],
                    "end_lat": ep["lat"],
                    "end_lng": ep["lng"],
                    "distance_m": round(d, 1),
                    "zombie_id": ep.get("zombie_id"),  # iter209
                })
    candidates.sort(key=lambda x: x["distance_m"])
    return {"items": candidates, "total": len(candidates)}


@router.post("/cables/{cable_id}/link-endpoint")
async def link_cable_endpoint(
    cable_id: str,
    body: LinkEndpointIn,
    user: dict = Depends(require_role(
        "tecnico", "gestor", "administrador",
        "auditor", "gestor_rede")),
):
    """Vincula ponta `from` ou `to` do cabo a uma CTO/CE existente.
    Se ambas as pontas ficarem vinculadas, status sai de `cabo_solto`
    e passa para `pending_validation` (aprovação normal).
    """
    cid = _user_company(user)
    if body.endpoint not in ("from", "to"):
        raise HTTPException(400, "endpoint deve ser 'from' ou 'to'")

    cab = await db.ctos.find_one(
        {"id": cable_id, "company_id": cid, "element_type": "cabo"},
        {"_id": 0},
    )
    if not cab:
        raise HTTPException(404, "Cabo não encontrado")

    target = await db.ctos.find_one(
        {"id": body.element_id, "company_id": cid,
         "element_type": {"$in": ["cto", "ce"]}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1},
    )
    if not target:
        raise HTTPException(404, "CTO/CE alvo não encontrado")

    field = "from_element_id" if body.endpoint == "from" else "to_element_id"
    upd: Dict[str, Any] = {field: target["id"], "updated_at": now_iso()}

    # Atualiza route_geometry pra começar/terminar exatamente no GPS da CTO/CE
    geom = cab.get("route_geometry") or []
    tgps = target.get("gps") or {}
    if geom and tgps.get("lat") is not None:
        if body.endpoint == "from":
            geom = [[tgps["lat"], tgps["lng"]], *geom[1:]]
        else:
            geom = [*geom[:-1], [tgps["lat"], tgps["lng"]]]
        upd["route_geometry"] = geom

    # Verifica se as 2 pontas ficaram vinculadas
    new_from = (cab.get("from_element_id")
                if body.endpoint != "from" else target["id"])
    new_to = (cab.get("to_element_id")
              if body.endpoint != "to" else target["id"])
    if new_from and new_to:
        upd["is_loose"] = False
        upd["status"] = "pending_validation"
        # Cria entrada de validação (igual ao create normal)
        await db.cto_validations.insert_one({
            "id": _new_id("val"),
            "company_id": cid,
            "cto_id": cable_id,
            "cto_snapshot": {**cab, **upd},
            "status": "pending",
            "technician_id": cab.get("technician_id"),
            "technician_name": cab.get("technician_name"),
            "manager_id": None,
            "manager_name": None,
            "comment": "Cabo vinculado após lançamento solto",
            "created_at": now_iso(),
            "resolved_at": None,
        })

    await db.ctos.update_one(
        {"id": cable_id, "company_id": cid},
        {"$set": upd},
    )
    await _audit("update", cable_id, cab, {**cab, **upd}, user,
                 f"Vínculo de ponta '{body.endpoint}' → {target['name']}")

    return {
        "ok": True,
        "cable_id": cable_id,
        "endpoint": body.endpoint,
        "linked_to": {"id": target["id"], "name": target["name"]},
        "status": upd.get("status") or cab.get("status"),
        "is_loose": upd.get("is_loose", cab.get("is_loose", True)),
    }


@router.post("/cables/orphan-suggest")
async def cables_orphan_suggest(
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede", "auditor")),
):
    """Sugere vínculos para cada cabo órfão com confiança 0-100.
    Heurística (rápida, sem LLM) baseada em:
      - Distância da ponta solta à CTO/CE candidata
      - Igualdade de VLAN/sigla
      - Bairro coincidente

    Retorna [{cable_id, end, suggested_element_id, element_name,
              distance_m, confidence, reasons}]
    """
    cid = _user_company(user)
    # Carrega cabos órfãos
    orphan_cursor = db.ctos.find(
        {"company_id": cid, "element_type": "cabo",
         "$or": [
             {"status": "cabo_solto"},
             {"is_loose": True},
         ]},
        {"_id": 0},
    )
    orphans = []
    async for o in orphan_cursor:
        orphans.append(o)

    # Carrega CTOs/CEs aprovadas/pending pra usar como candidatos
    elements = await db.ctos.find(
        {"company_id": cid,
         "element_type": {"$in": ["cto", "ce"]},
         "status": {"$in": ["approved", "pending_validation"]}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "vlan": 1,
         "sigla": 1, "address": 1, "element_type": 1},
    ).to_list(2000)

    suggestions = []
    for cab in orphans:
        for ep in _cable_loose_endpoints(cab):
            best = None
            best_score = -1
            best_reasons: List[str] = []
            for el in elements:
                g = el.get("gps") or {}
                if g.get("lat") is None or g.get("lng") is None:
                    continue
                d = _haversine_m(ep["lat"], ep["lng"],
                                  g["lat"], g["lng"])
                if d > 100:  # ignora elementos a mais de 100m
                    continue
                # Score: 100 - d (cada metro perde 1 ponto, max 100m)
                # + 15 se mesma VLAN, +10 se mesma sigla, +5 se mesmo bairro
                score = max(0.0, 100.0 - d)
                reasons = [f"{round(d,1)}m da ponta solta"]
                if cab.get("vlan") and el.get("vlan") == cab.get("vlan"):
                    score += 15
                    reasons.append(f"mesma VLAN {el['vlan']}")
                if cab.get("sigla") and el.get("sigla") == cab.get("sigla"):
                    score += 10
                    reasons.append(f"mesma sigla {el['sigla']}")
                cab_bairro = (cab.get("address") or {}).get("bairro")
                el_bairro = (el.get("address") or {}).get("bairro")
                if cab_bairro and el_bairro and cab_bairro == el_bairro:
                    score += 5
                    reasons.append(f"mesmo bairro {el_bairro}")
                if score > best_score:
                    best_score = score
                    best = el
                    best_reasons = reasons
            if best:
                # Normaliza confidence pra 0-100 (max teórico ~130)
                conf = min(100, round(best_score / 1.3, 0))
                suggestions.append({
                    "cable_id": cab.get("id"),
                    "cable_name": cab.get("name"),
                    "end": ep["end"],
                    "end_lat": ep["lat"],
                    "end_lng": ep["lng"],
                    "suggested_element_id": best["id"],
                    "suggested_element_name": best["name"],
                    "suggested_element_type":
                        (best.get("element_type") or "cto").lower(),
                    "distance_m": round(
                        _haversine_m(ep["lat"], ep["lng"],
                                      best["gps"]["lat"],
                                      best["gps"]["lng"]), 1),
                    "confidence": int(conf),
                    "reasons": best_reasons,
                })

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return {"items": suggestions, "total": len(suggestions)}



# ============================================================================
# iter186 — IA Visão (Claude Sonnet 4.5) para leitura de plaqueta do cabo
# ============================================================================

async def _analyze_cable_plaqueta_with_ai(
    cable_doc: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Manda a foto da plaqueta do cabo (photo_extra_data_url) pro Claude
    Sonnet 4.5 Vision e pede pra extrair o nome da CTO/CE escrita lá.
    Depois faz match com a lista de candidatos.

    Retorna {extracted_text, matched_element_id, matched_element_name,
             vision_confidence, reasoning} ou None se sem foto/falha.
    """
    photo = (cable_doc.get("photo_extra_data_url")
             or cable_doc.get("photo_data_url"))
    if not photo or not photo.startswith("data:image"):
        return None

    # Extrai o base64 puro do data URL
    try:
        b64 = photo.split(",", 1)[1]
    except Exception:
        return None

    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
        from core import EMERGENT_LLM_KEY
        if not EMERGENT_LLM_KEY:
            logger.warning("[plaqueta-ai] EMERGENT_LLM_KEY não configurada")
            return None

        candidate_names = [c.get("name") for c in candidates[:30] if c.get("name")]
        system_msg = (
            "Você é um analista de redes FTTH especializado em ler plaquetas "
            "de identificação de equipamentos (CTOs, CEs e cabos). Extraia "
            "EXATAMENTE o nome do equipamento/cabo escrito na plaqueta da foto. "
            "Responda SEMPRE em JSON válido com este formato:\n"
            '{"detected_name":"<texto exato>","confidence":0-100,'
            '"raw_text":"<todo texto visível>","reasoning":"<por quê>"}\n'
            "Se não conseguir ler ou não houver plaqueta, retorne "
            '{"detected_name":null,"confidence":0,"raw_text":"","reasoning":"..."}'
        )
        user_text = (
            "Examine a foto desta plaqueta de cabo de fibra ótica e extraia "
            "o nome/identificação da CTO ou CE escrita nela. "
            f"Nomes possíveis na rede: {', '.join(candidate_names[:15])}. "
            "Procure por padrões como 'CTO_VLAN_NUMERO', 'CTO XXX', "
            "'CE_NNNNN', siglas de bairro (JAT, PIT, BRA), VLANs (301, 1). "
            "Retorne JSON válido."
        )
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"plaqueta-{cable_doc.get('id') or 'x'}",
            system_message=system_msg,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        msg = UserMessage(
            text=user_text,
            file_contents=[ImageContent(image_base64=b64)],
        )
        out = await chat.send_message(msg)
        raw = str(out).strip()

        # Tenta extrair JSON do response (LLM às vezes embrulha em ```)
        import json as _json
        import re as _re
        m = _re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return {
                "extracted_text": None,
                "vision_confidence": 0,
                "raw_text": raw,
                "reasoning": "Resposta da IA sem JSON válido",
            }
        try:
            parsed = _json.loads(m.group(0))
        except _json.JSONDecodeError:
            return {
                "extracted_text": None,
                "vision_confidence": 0,
                "raw_text": raw,
                "reasoning": "JSON malformado da IA",
            }

        detected = (parsed.get("detected_name") or "").strip()
        conf = int(parsed.get("confidence") or 0)
        if not detected:
            return {
                "extracted_text": None,
                "vision_confidence": conf,
                "raw_text": parsed.get("raw_text") or "",
                "reasoning": parsed.get("reasoning") or "",
            }

        # Match: nome exato > substring > similaridade simples
        det_up = detected.upper().replace(" ", "_").replace("-", "_")
        best = None
        best_score = 0
        for c in candidates:
            nm = (c.get("name") or "").upper()
            if not nm:
                continue
            if nm == det_up:
                best = c
                best_score = 100
                break
            # Substring match (CTO_301_004 ⊂ CTO_301_0004)
            if det_up in nm or nm in det_up:
                if best_score < 85:
                    best = c
                    best_score = 85
            # Match parcial pelo número final
            try:
                det_num = int(det_up.split("_")[-1])
                nm_num = int(nm.split("_")[-1])
                if det_num == nm_num and det_up[:3] == nm[:3]:
                    if best_score < 70:
                        best = c
                        best_score = 70
            except (ValueError, IndexError):
                pass

        if best:
            # Confiança final = média entre vision_confidence e match score
            final_conf = int((conf + best_score) / 2)
            return {
                "extracted_text": detected,
                "matched_element_id": best.get("id"),
                "matched_element_name": best.get("name"),
                "vision_confidence": final_conf,
                "raw_text": parsed.get("raw_text") or detected,
                "reasoning": (
                    f"IA leu '{detected}'. Match com '{best.get('name')}' "
                    f"(score {best_score})."
                ),
            }
        return {
            "extracted_text": detected,
            "matched_element_id": None,
            "matched_element_name": None,
            "vision_confidence": conf,
            "raw_text": parsed.get("raw_text") or detected,
            "reasoning": f"IA leu '{detected}' mas não casa com nenhum elemento da rede.",
        }
    except Exception as e:
        logger.warning("[plaqueta-ai] falha: %s", e)
        return None


@router.post("/cables/{cable_id}/analyze-plaqueta")
async def cable_analyze_plaqueta(
    cable_id: str,
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede", "auditor")),
):
    """Analisa foto da plaqueta do cabo com Claude Sonnet 4.5 Vision
    e retorna o melhor candidato de vínculo."""
    cid = _user_company(user)
    cab = await db.ctos.find_one(
        {"id": cable_id, "company_id": cid, "element_type": "cabo"},
        {"_id": 0},
    )
    if not cab:
        raise HTTPException(404, "Cabo não encontrado")

    candidates = await db.ctos.find(
        {"company_id": cid,
         "element_type": {"$in": ["cto", "ce"]},
         "status": {"$in": ["approved", "pending_validation"]}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "vlan": 1,
         "sigla": 1, "element_type": 1},
    ).to_list(1000)

    ai = await _analyze_cable_plaqueta_with_ai(cab, candidates)
    if not ai:
        raise HTTPException(400,
            "Cabo sem foto de plaqueta ou IA indisponível")
    return ai


@router.post("/cables/orphan-suggest-with-vision")
async def cables_orphan_suggest_with_vision(
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede", "auditor")),
):
    """Sugere vínculos com IA Visão (Claude Sonnet 4.5) lendo a plaqueta
    de cada cabo órfão. Mais lento (1 chamada LLM por cabo com foto) mas
    muito mais preciso que a heurística geo. Cabos sem foto caem na
    heurística normal.
    """
    cid = _user_company(user)
    orphans = await db.ctos.find(
        {"company_id": cid, "element_type": "cabo",
         "$or": [
             {"status": "cabo_solto"},
             {"is_loose": True},
         ]},
        {"_id": 0},
    ).to_list(500)
    candidates = await db.ctos.find(
        {"company_id": cid,
         "element_type": {"$in": ["cto", "ce"]},
         "status": {"$in": ["approved", "pending_validation"]}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "vlan": 1,
         "sigla": 1, "address": 1, "element_type": 1},
    ).to_list(2000)

    suggestions = []
    for cab in orphans:
        ai = await _analyze_cable_plaqueta_with_ai(cab, candidates)
        if not ai or not ai.get("matched_element_id"):
            continue
        # Define qual ponta vincular: a mais próxima do elemento detectado
        target_el = next(
            (c for c in candidates
             if c.get("id") == ai["matched_element_id"]),
            None,
        )
        if not target_el or not (target_el.get("gps") or {}).get("lat"):
            continue
        loose = _cable_loose_endpoints(cab)
        if not loose:
            continue
        best_end = None
        best_dist = float("inf")
        for ep in loose:
            d = _haversine_m(ep["lat"], ep["lng"],
                              target_el["gps"]["lat"],
                              target_el["gps"]["lng"])
            if d < best_dist:
                best_dist = d
                best_end = ep
        if not best_end:
            continue
        suggestions.append({
            "cable_id": cab.get("id"),
            "cable_name": cab.get("name"),
            "end": best_end["end"],
            "end_lat": best_end["lat"],
            "end_lng": best_end["lng"],
            "suggested_element_id": ai["matched_element_id"],
            "suggested_element_name": ai["matched_element_name"],
            "suggested_element_type":
                (target_el.get("element_type") or "cto").lower(),
            "distance_m": round(best_dist, 1),
            "confidence": int(ai["vision_confidence"]),
            "source": "vision_ai",
            # iter186 — Painel "Confiança visual": preview da foto + OCR + GPS
            "photo_url": (cab.get("photo_extra_data_url")
                          or cab.get("photo_data_url")),
            "extracted_text": ai.get("extracted_text"),
            "raw_text": ai.get("raw_text"),
            "ai_reasoning": ai.get("reasoning"),
            "target_lat": (target_el.get("gps") or {}).get("lat"),
            "target_lng": (target_el.get("gps") or {}).get("lng"),
            "reasons": [
                f"IA leu plaqueta: '{ai['extracted_text']}'",
                ai.get("reasoning") or "",
                f"{round(best_dist, 1)}m da ponta {best_end['end']}",
            ],
        })

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return {"items": suggestions, "total": len(suggestions)}


# ============================================================================
# iter186 — Cron noturno: auto-vínculo de cabos órfãos com Vision IA
# Roda 1x por dia (3h da manhã). Auto-vincula confiança ≥ 90%; cria
# pending_review pra confiança 50-89% (visível no painel admin).
# ============================================================================

class VisionAutoLinkConfig(BaseModel):
    enabled: bool = True
    auto_link_threshold: int = Field(default=90, ge=50, le=100,
        description="Confiança ≥ X auto-vincula sem revisão")
    review_threshold: int = Field(default=50, ge=0, le=99,
        description="Confiança entre review_threshold e auto_link"
                        " vira pending_review")
    run_hour_utc: int = Field(default=6, ge=0, le=23,
        description="Hora UTC do dia para rodar (default 6h UTC = 3h BRT)")


DEFAULT_VISION_AUTO = {
    "enabled": True,
    "auto_link_threshold": 90,
    "review_threshold": 50,
    "run_hour_utc": 6,
}


@router.get("/cables/auto-vision/config")
async def get_vision_auto_config(
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede")),
):
    cid = _user_company(user)
    doc = await db.rede_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0, "vision_auto": 1},
    )
    cfg = (doc or {}).get("vision_auto") or {}
    return {**DEFAULT_VISION_AUTO, **cfg}


@router.put("/cables/auto-vision/config")
async def update_vision_auto_config(
    body: VisionAutoLinkConfig,
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede")),
):
    cid = _user_company(user)
    payload = body.model_dump()
    await db.rede_ia_settings.update_one(
        {"company_id": cid},
        {"$set": {
            "vision_auto": payload,
            "vision_auto_updated_at": now_iso(),
            "vision_auto_updated_by": user.get("name"),
        }},
        upsert=True,
    )
    return payload


@router.post("/cables/auto-vision/run-now")
async def run_vision_auto_now(
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede")),
):
    """Força execução manual do scan (sem esperar 3h da manhã)."""
    cid = _user_company(user)
    return await _vision_auto_scan_company(cid)


@router.get("/cables/auto-vision/pending-review")
async def list_vision_pending_review(
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede", "auditor")),
):
    """Cabos com sugestão IA pendente de revisão (confiança média)."""
    cid = _user_company(user)
    items = await db.cable_vision_reviews.find(
        {"company_id": cid, "status": "pending_review"},
        {"_id": 0},
    ).sort("confidence", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.post("/cables/auto-vision/{review_id}/approve")
async def approve_vision_review(
    review_id: str,
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede")),
):
    cid = _user_company(user)
    rev = await db.cable_vision_reviews.find_one(
        {"id": review_id, "company_id": cid}, {"_id": 0},
    )
    if not rev:
        raise HTTPException(404, "Revisão não encontrada")
    # Aplica vínculo
    body = LinkEndpointIn(
        endpoint=rev["end"], element_id=rev["suggested_element_id"],
    )
    await link_cable_endpoint(rev["cable_id"], body, user)
    await db.cable_vision_reviews.update_one(
        {"id": review_id, "company_id": cid},
        {"$set": {
            "status": "approved", "resolved_at": now_iso(),
            "resolved_by": user.get("name"),
        }},
    )
    return {"ok": True}


@router.post("/cables/auto-vision/{review_id}/reject")
async def reject_vision_review(
    review_id: str,
    user: dict = Depends(require_role(
        "gestor", "administrador", "gestor_rede")),
):
    cid = _user_company(user)
    r = await db.cable_vision_reviews.update_one(
        {"id": review_id, "company_id": cid},
        {"$set": {
            "status": "rejected", "resolved_at": now_iso(),
            "resolved_by": user.get("name"),
        }},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Revisão não encontrada")
    return {"ok": True}


async def _vision_auto_scan_company(cid: str) -> Dict[str, Any]:
    """Executa o scan de Vision IA para 1 empresa.
    - Auto-vincula cabos com confiança ≥ auto_link_threshold
    - Salva os de confiança média em cable_vision_reviews
    Retorna estatísticas do scan.
    """
    doc = await db.rede_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0, "vision_auto": 1},
    )
    cfg = {**DEFAULT_VISION_AUTO, **((doc or {}).get("vision_auto") or {})}
    if not cfg.get("enabled"):
        return {"skipped": True, "reason": "disabled"}

    auto_thr = int(cfg.get("auto_link_threshold") or 90)
    rev_thr = int(cfg.get("review_threshold") or 50)

    orphans = await db.ctos.find(
        {"company_id": cid, "element_type": "cabo",
         "$or": [{"status": "cabo_solto"}, {"is_loose": True}]},
        {"_id": 0},
    ).to_list(500)
    candidates = await db.ctos.find(
        {"company_id": cid,
         "element_type": {"$in": ["cto", "ce"]},
         "status": {"$in": ["approved", "pending_validation"]}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "vlan": 1,
         "sigla": 1, "element_type": 1},
    ).to_list(2000)

    auto_linked = 0
    pending = 0
    skipped = 0
    for cab in orphans:
        # Pula se já processado recentemente (status review pending)
        already = await db.cable_vision_reviews.find_one(
            {"company_id": cid, "cable_id": cab.get("id"),
             "status": "pending_review"},
            {"_id": 0, "id": 1},
        )
        if already:
            continue
        ai = await _analyze_cable_plaqueta_with_ai(cab, candidates)
        if not ai or not ai.get("matched_element_id"):
            skipped += 1
            continue
        target_el = next(
            (c for c in candidates if c.get("id") == ai["matched_element_id"]),
            None,
        )
        if not target_el:
            skipped += 1
            continue
        loose = _cable_loose_endpoints(cab)
        if not loose:
            skipped += 1
            continue
        # Define ponta mais próxima do elemento detectado
        best_end = None
        best_dist = float("inf")
        tgps = target_el.get("gps") or {}
        for ep in loose:
            d = _haversine_m(ep["lat"], ep["lng"],
                              tgps.get("lat") or 0,
                              tgps.get("lng") or 0)
            if d < best_dist:
                best_dist = d
                best_end = ep
        conf = int(ai.get("vision_confidence") or 0)
        if conf >= auto_thr and best_end:
            # Auto-vínculo!
            try:
                cab2 = await db.ctos.find_one(
                    {"id": cab["id"], "company_id": cid}, {"_id": 0},
                )
                if not cab2:
                    continue
                field = ("from_element_id" if best_end["end"] == "from"
                         else "to_element_id")
                upd = {field: target_el["id"], "updated_at": now_iso()}
                new_from = (cab2.get("from_element_id")
                            if best_end["end"] != "from" else target_el["id"])
                new_to = (cab2.get("to_element_id")
                          if best_end["end"] != "to" else target_el["id"])
                if new_from and new_to:
                    upd["is_loose"] = False
                    upd["status"] = "pending_validation"
                    await db.cto_validations.insert_one({
                        "id": _new_id("val"),
                        "company_id": cid,
                        "cto_id": cab["id"],
                        "cto_snapshot": {**cab2, **upd},
                        "status": "pending",
                        "technician_id": cab2.get("technician_id"),
                        "technician_name": cab2.get("technician_name"),
                        "manager_id": None,
                        "manager_name": None,
                        "comment": (
                            f"Auto-vínculo Vision IA (conf {conf}%) — "
                            f"plaqueta lida: '{ai.get('extracted_text')}'"
                        ),
                        "created_at": now_iso(),
                        "resolved_at": None,
                    })
                await db.ctos.update_one(
                    {"id": cab["id"], "company_id": cid},
                    {"$set": upd},
                )
                # Registra log de auto-vinculação
                await db.cable_vision_reviews.insert_one({
                    "id": _new_id("vrev"),
                    "company_id": cid,
                    "cable_id": cab["id"],
                    "cable_name": cab.get("name"),
                    "end": best_end["end"],
                    "suggested_element_id": target_el["id"],
                    "suggested_element_name": target_el.get("name"),
                    "extracted_text": ai.get("extracted_text"),
                    "raw_text": ai.get("raw_text"),
                    "reasoning": ai.get("reasoning"),
                    "confidence": conf,
                    "distance_m": round(best_dist, 1),
                    "status": "auto_linked",
                    "created_at": now_iso(),
                    "resolved_at": now_iso(),
                    "resolved_by": "system",
                })
                auto_linked += 1
            except Exception as e:
                logger.warning("[vision-auto] auto-link falhou %s: %s",
                                cab.get("id"), e)
                skipped += 1
        elif conf >= rev_thr and best_end:
            # Salva pra review manual
            await db.cable_vision_reviews.insert_one({
                "id": _new_id("vrev"),
                "company_id": cid,
                "cable_id": cab["id"],
                "cable_name": cab.get("name"),
                "end": best_end["end"],
                "end_lat": best_end["lat"],
                "end_lng": best_end["lng"],
                "suggested_element_id": target_el["id"],
                "suggested_element_name": target_el.get("name"),
                "extracted_text": ai.get("extracted_text"),
                "raw_text": ai.get("raw_text"),
                "reasoning": ai.get("reasoning"),
                "confidence": conf,
                "distance_m": round(best_dist, 1),
                "photo_url": (cab.get("photo_extra_data_url")
                              or cab.get("photo_data_url")),
                "status": "pending_review",
                "created_at": now_iso(),
            })
            pending += 1
        else:
            skipped += 1

    summary = {
        "scanned": len(orphans),
        "auto_linked": auto_linked,
        "pending_review": pending,
        "skipped": skipped,
        "ran_at": now_iso(),
    }
    # Salva último resultado pra exibir no painel
    await db.rede_ia_settings.update_one(
        {"company_id": cid},
        {"$set": {"vision_auto_last_run": summary}},
        upsert=True,
    )
    logger.info("[vision-auto] %s — auto=%s pending=%s skipped=%s",
                cid, auto_linked, pending, skipped)
    return summary


_VISION_WORKER_TASK: Optional[asyncio.Task] = None
_VISION_WORKER_RUN = True


async def _vision_worker_loop() -> None:
    """Loop noturno. Roda uma vez por dia na hora configurada (default 6h UTC).
    """
    last_run_day: Dict[str, str] = {}
    while _VISION_WORKER_RUN:
        try:
            now_utc = datetime.now(timezone.utc)
            today = now_utc.strftime("%Y-%m-%d")
            cur_hour = now_utc.hour
            cfgs = await db.rede_ia_settings.find(
                {"vision_auto.enabled": True},
                {"_id": 0, "company_id": 1, "vision_auto": 1},
            ).to_list(50)
            for raw in cfgs:
                cid = raw.get("company_id")
                if not cid:
                    continue
                cfg = raw.get("vision_auto") or {}
                target_hour = int(cfg.get("run_hour_utc") or 6)
                if cur_hour != target_hour:
                    continue
                if last_run_day.get(cid) == today:
                    continue
                last_run_day[cid] = today
                try:
                    res = await _vision_auto_scan_company(cid)
                    logger.info("[vision-auto] daily scan %s = %s", cid, res)
                except Exception as e:
                    logger.warning("[vision-auto] %s falhou: %s", cid, e)
        except Exception as e:
            logger.warning("[vision-auto] tick falhou: %s", e)
        await asyncio.sleep(600)  # checa a cada 10 minutos


async def start_vision_worker() -> None:
    global _VISION_WORKER_TASK  # noqa: PLW0603
    if _VISION_WORKER_TASK and not _VISION_WORKER_TASK.done():
        return
    _VISION_WORKER_TASK = asyncio.create_task(_vision_worker_loop())
    logger.info("[vision-auto] worker iniciado (run a cada 10min, scan diário)")


async def stop_vision_worker() -> None:
    global _VISION_WORKER_RUN  # noqa: PLW0603
    _VISION_WORKER_RUN = False
    if _VISION_WORKER_TASK:
        _VISION_WORKER_TASK.cancel()

