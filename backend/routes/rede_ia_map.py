"""Mapa interativo FTTH — rede_IA.

Elementos da rede:
- CTOs (já existem em `ctos`) — pontos com lat/lng
- CE (Caixa de Emenda) — splice closures que agrupam CTOs próximas
- Cabos — polylines entre CE↔CTO ou CTO↔CTO, com tipo (6FO, 12FO, 24FO, drop)
- Drops — conexões individuais cliente↔CTO

Coleções novas:
- `network_ces`: {id, name, lat, lng, capacity_fo, parent_ce_id?, address, type, status}
- `network_cables`: {id, type, fo_count, segments[{lat,lng}], from_id, to_id, length_m, status}
- `network_positions`: overrides de posição manual {entity_id, type, lat, lng}

Endpoints:
- GET  /map/data              → tudo agregado para o front
- POST /ces                   → cria CE manualmente
- PUT  /ces/{id}              → edita CE
- DELETE /ces/{id}
- POST /cables                → cria cabo
- PUT  /cables/{id}
- DELETE /cables/{id}
- POST /map/auto-generate-ces → rede_IA cria CEs por geo-clustering
- POST /map/positions         → grava reposicionamento manual
- GET  /map/cto-health/{id}   → média de sinal das ONUs daquela CTO/VLAN
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import hashlib
import hmac
import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role, get_current_user
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rede-ia", tags=["rede_ia_map"])

CABLE_TYPES = ("drop", "6fo", "12fo", "24fo", "48fo", "96fo")
CE_TYPES = ("primaria", "secundaria", "terciaria", "emenda_aerea", "emenda_subterranea")

# Mapeia tipo de cabo (mapa) → ID do insumo (stok). Apenas estes geram
# auto-baixa de estoque ao serem lançados no mapa interativo.
# iter211f — incluído 48fo/96fo (catálogo de estoque já suporta).
_CABLE_TYPE_TO_STOK_ID = {
    "6fo":  "fibra_06fo",
    "12fo": "fibra_12fo",
    "24fo": "fibra_24fo",
    "48fo": "fibra_48fo",
    "96fo": "fibra_96fo",
}

# ─── Onda C P0.1 — RCA Fibra Guardrails (CEO 18/06/2026) ───────────────────
# Palavras proibidas em serial/invoice/purchase_id em produção. Previne
# contaminação de dados de teste como aconteceu em 02/06/2026 (cabo de
# 364km debitado por engano). Match case-insensitive em qualquer posição.
_FORBIDDEN_TEST_TOKENS = ("TEST", "TST", "ABCD", "DUMMY", "FAKE", "MOCK")

# Tiers de comprimento (em metros). Calibrado para fibra urbana brasileira.
_LEN_WARN_M = 5_000     # >5km — registra warning (não bloqueia)
_LEN_CONFIRM_M = 20_000  # >20km — exige confirm_unusual_length=true
_LEN_BLOCK_M = 50_000    # >50km — bloqueio para todos (exige override admin)


def _check_forbidden_tokens(*values: str) -> Optional[str]:
    """Retorna a primeira palavra proibida encontrada, ou None se limpo."""
    for v in values:
        if not v:
            continue
        upper = v.upper()
        for token in _FORBIDDEN_TEST_TOKENS:
            if token in upper:
                return f"{token} (campo='{v[:60]}')"
    return None


def _validate_cable_guardrails(body: "CableIn", user: dict,
                                computed_length_m: Optional[float]) -> None:
    """Aplica 4 guardrails antes de criar cabo. Raises HTTPException 400."""
    # Drop não tem guardrail forte (volume pequeno, custo baixo, alta
    # frequência). Só fibra é regulada aqui.
    if body.type == "drop":
        return

    # Guardrail 1 — Tokens de teste em prod
    forbidden = _check_forbidden_tokens(
        body.cable_serial, body.invoice_number, body.purchase_id)
    if forbidden:
        raise HTTPException(400, {
            "error": "guardrail_test_token_blocked",
            "human_reason": (
                "Cabo bloqueado: serial/NF/compra contém termo de teste em "
                f"produção ({forbidden}). Use dados reais ou peça override "
                "administrativo."
            ),
            "rule": "Onda C P0.1 guardrail #1",
        })

    # Guardrail 2 — Comprimento anormal (tiered)
    length = (computed_length_m or 0)
    if length >= _LEN_BLOCK_M:
        if not (body.admin_override_reason or "").strip() or \
                len((body.admin_override_reason or "").strip()) < 20:
            raise HTTPException(400, {
                "error": "guardrail_length_block",
                "human_reason": (
                    f"Cabo bloqueado: {length/1000:.1f}km excede o limite "
                    f"administrativo de {_LEN_BLOCK_M/1000:.0f}km. Para "
                    "lançar, envie 'admin_override_reason' (mín 20 chars) "
                    "justificando."
                ),
                "rule": "Onda C P0.1 guardrail #2 (block tier)",
            })
    elif length >= _LEN_CONFIRM_M:
        if not body.confirm_unusual_length:
            raise HTTPException(400, {
                "error": "guardrail_length_confirm_required",
                "human_reason": (
                    f"Cabo com {length/1000:.1f}km exige confirmação dupla. "
                    "Reenvie com 'confirm_unusual_length: true' para "
                    "confirmar o lançamento."
                ),
                "rule": "Onda C P0.1 guardrail #2 (confirm tier)",
                "length_m": length,
                "threshold_m": _LEN_CONFIRM_M,
            })

    # Guardrail 3 — purchase_id obrigatório OU admin_override_reason
    # (fibra debita patrimônio; débito sem origem fiscal é proibido).
    purchase_id_clean = (body.purchase_id or "").strip()
    override_clean = (body.admin_override_reason or "").strip()
    if not purchase_id_clean and len(override_clean) < 20:
        raise HTTPException(400, {
            "error": "guardrail_purchase_id_required",
            "human_reason": (
                "Cabo de fibra sem 'purchase_id' (compra) só pode ser "
                "lançado com 'admin_override_reason' (mín 20 chars) "
                "justificando."
            ),
            "rule": "Onda C P0.1 guardrail #3",
        })


def _length_warning_tier(length_m: Optional[float]) -> Optional[str]:
    """Tag de alerta para card 'Movimentos Anômalos' do Watchtower."""
    if not length_m or length_m < _LEN_WARN_M:
        return None
    if length_m >= _LEN_BLOCK_M:
        return "length_block_tier"
    if length_m >= _LEN_CONFIRM_M:
        return "length_confirm_tier"
    return "length_warn_tier"


async def _debit_fiber_for_cable(
    company_id: str, user: dict, cable_type: str, meters: Optional[float],
    cable_id: str, action: str = "create",
) -> Optional[dict]:
    """Lança baixa/devolução de fibra no estoque do criador do cabo.

    - Só atua em cabos de fibra contínua (6fo, 12fo, 24fo). drop/48fo/96fo são ignorados.
    - Se `user` tem `collaborator_id` (técnico/gestor_rede), debita do estoque
      DO técnico. Caso contrário (admin/gestor), debita do estoque "empresa".
    - `action`: 'create'|'delete'|'adjust' apenas logado em history.
    - Retorna `{location, consumable_id, meters, signed}` (signed=negativo p/ baixa,
      positivo p/ devolução), ou None se nada foi alterado.

    Não bloqueia se saldo for insuficiente — apenas registra a movimentação
    (fica negativo). Gestor revisa via Estoque → Histórico (tag=rede_lancamento).
    """
    cons_id = _CABLE_TYPE_TO_STOK_ID.get(cable_type)
    if not cons_id or not meters or meters <= 0:
        return None

    # Direção do ajuste
    signed = -float(meters) if action == "create" else float(meters)

    # Localização do estoque
    collab_id = user.get("collaborator_id")
    if collab_id:
        location = collab_id
        location_label = user.get("name") or "técnico"
    else:
        location = "empresa"
        location_label = "Empresa"

    # Aplica $inc (motor.update_one é atômico)
    await db.stok_stock.update_one(
        {"company_id": company_id, "location": location},
        {"$inc": {cons_id: int(round(signed))},
         "$setOnInsert": {"company_id": company_id, "location": location}},
        upsert=True,
    )

    # Histórico
    cons_label = {
        "fibra_06fo": "Fibra 06FO", "fibra_12fo": "Fibra 12FO",
        "fibra_24fo": "Fibra 24FO", "fibra_48fo": "Fibra 48FO",
        "fibra_96fo": "Fibra 96FO",
    }[cons_id]
    verb = "Baixa" if action == "create" else "Devolução" if action == "delete" else "Ajuste"
    await db.stok_history.insert_one({
        "id": f"hist-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "date": now_iso(),
        "type": "rede_lancamento",
        "description": (f"{verb} automática de {abs(int(round(signed)))}m de "
                          f"{cons_label} ({location_label}) — cabo {cable_id} "
                          f"({cable_type.upper()})"),
        "user": user.get("name", "?"),
        "tag": "rede_lancamento",
        "cable_id": cable_id,
        "action": action,
    })
    return {
        "location": location, "consumable_id": cons_id,
        "meters_signed": int(round(signed)),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CEIn(BaseModel):
    name: str
    lat: float
    lng: float
    capacity_fo: int = 24
    type: str = "secundaria"
    parent_ce_id: Optional[str] = None
    address: str = ""
    notes: str = ""


class CableSegment(BaseModel):
    lat: float
    lng: float


class CableIn(BaseModel):
    type: str = "12fo"  # drop | 6fo | 12fo | 24fo | 48fo | 96fo
    # iter211c — from/to opcionais: cabo pode começar/terminar "no ar"
    # (cabo solto). Quando faltar uma das pontas, salva como `cabo_solto`.
    from_id: Optional[str] = None
    from_type: Optional[str] = None
    to_id: Optional[str] = None
    to_type: Optional[str] = None
    segments: List[CableSegment] = []
    length_m: Optional[float] = None
    notes: str = ""
    # iter211e — Rastreabilidade do cabo: SN do fabricante + NF da compra.
    # Obrigatório para 6fo/12fo/24fo/48fo/96fo (não para drop).
    cable_serial: Optional[str] = None
    invoice_number: Optional[str] = None
    purchase_id: Optional[str] = None  # link opcional à compra na DB
    # Onda C P0.1 — RCA Fibra Guardrails (18/06/2026)
    # Confirmação extra para cabos com comprimento incomum (20-50km).
    confirm_unusual_length: bool = False
    # Justificativa administrativa quando não há purchase_id mas há débito real.
    # Mínimo 20 caracteres. Apenas administradores podem usar.
    admin_override_reason: Optional[str] = None


class PositionIn(BaseModel):
    entity_id: str
    entity_type: str  # cto | ce
    lat: float
    lng: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _company(user: dict) -> str:
    return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID


def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Distância em metros entre 2 pontos GPS."""
    R = 6371000.0
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlam = math.radians(b_lng - a_lng)
    sa = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(sa))


async def _cto_health(company_id: str, cto: Dict[str, Any]) -> Dict[str, Any]:
    """Agrega sinal das ONUs SmartOLT que casam com a CTO.

    Critério: zone_name regex match com nome/número/sigla da CTO.
    Retorna: {score, status, total, warning, critical, avg_rx_dbm}
    """
    number = cto.get("number")
    sigla = cto.get("sigla")
    cto_name = cto.get("name") or ""
    if not (number and sigla):
        return {"status": "unknown", "score": 100, "total": 0,
                "warning": 0, "critical": 0}

    patterns = [
        cto_name,
        f"CTO[\\s\\-_]*0*{number}(?!\\d)" if isinstance(number, int) else None,
        f"_{sigla}",
    ]
    patterns = [p for p in patterns if p]
    or_filt = [{"zone_name": {"$regex": p, "$options": "i"}} for p in patterns]

    onus = await db.smartolt_onus.find(
        {"company_id": company_id, "$or": or_filt},
        {"_id": 0, "signal_text": 1, "rx_power": 1, "status": 1},
    ).limit(100).to_list(100)

    total = len(onus)
    if total == 0:
        return {"status": "no_data", "score": 100, "total": 0,
                "warning": 0, "critical": 0}

    warning = 0
    critical = 0
    rx_values: List[float] = []
    for o in onus:
        sig = (o.get("signal_text") or "").lower()
        if sig in ("critical", "alarm"):
            critical += 1
        elif sig in ("warning",):
            warning += 1
        rx = o.get("rx_power")
        if isinstance(rx, (int, float)) and -40 < rx < 0:
            rx_values.append(float(rx))

    score = max(0, 100 - (critical * 30 + warning * 10))
    if critical > 0 or score < 40:
        status = "critical"
    elif warning > 0 or score < 70:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status, "score": score, "total": total,
        "warning": warning, "critical": critical,
        "avg_rx_dbm": (sum(rx_values) / len(rx_values)) if rx_values else None,
    }


# ---------------------------------------------------------------------------
# Map data
# ---------------------------------------------------------------------------
@router.get("/map/data")
async def get_map_data(user: dict = Depends(get_current_user)):
    """Retorna tudo necessário para renderizar o mapa Leaflet."""
    cid = _company(user)
    return await _collect_map_data(cid)


@router.get("/public/map/data/{collab_id}")
async def get_map_data_public(collab_id: str,
                                  lat: Optional[float] = None,
                                  lng: Optional[float] = None,
                                  radius_km: float = 5.0):
    """iter156 — Mapa público para o app do técnico (sem JWT).

    Resolve a company a partir do colaborador e devolve as MESMAS CTOs/CEs/
    cabos do mapa interativo. Quando `lat` e `lng` são informados, filtra
    elementos dentro de `radius_km` (default 5 km) — útil pra mobile.
    """
    from math import asin, cos, radians, sin, sqrt
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "company_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    cid = coll.get("company_id")
    if not cid:
        raise HTTPException(404, "Colaborador sem empresa")
    data = await _collect_map_data(cid)
    # Filtragem por raio (Haversine simples; suficiente <100 km)
    if lat is not None and lng is not None and radius_km > 0:
        def in_range(d_lat: Optional[float], d_lng: Optional[float]) -> bool:
            if d_lat is None or d_lng is None:
                return False
            φ1, φ2 = radians(lat), radians(d_lat)
            dφ = radians(d_lat - lat)
            dλ = radians(d_lng - lng)
            a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
            km = 2 * 6371 * asin(sqrt(a))
            return km <= radius_km
        data["ctos"] = [c for c in data.get("ctos", [])
                          if in_range(c.get("lat"), c.get("lng"))]
        data["ces"] = [c for c in data.get("ces", [])
                         if in_range(c.get("lat"), c.get("lng"))]
        # Cabos: mantém se ALGUM endpoint do segmento está no raio
        kept_cables = []
        for cab in data.get("cables", []):
            segs = cab.get("segments") or []
            if any(in_range(s.get("lat"), s.get("lng")) for s in segs):
                kept_cables.append(cab)
        data["cables"] = kept_cables
        data["filter_radius_km"] = radius_km
        data["filter_origin"] = {"lat": lat, "lng": lng}
    return data


async def _collect_map_data(cid: str) -> Dict[str, Any]:
    """Função interna que coleta os dados do mapa para uma company.

    Extraída para ser reutilizada pelo endpoint mobile do colaborador
    (mesmas CTOs/CEs/cabos do mapa interativo).

    A partir do iter148, elementos cadastrados pelo wizard mobile
    (`element_type` ∈ {"cto","ce","cabo"}) saem todos da collection
    `ctos`. Particionamos por tipo para alimentar arrays distintos no
    front (ctos puros vs CEs vs cabos).
    """
    ctos_raw_all = await db.ctos.find(
        {"company_id": cid,
         "status": {"$in": ["approved", "pending_validation", "cabo_solto"]}},
        {"_id": 0},
    ).to_list(2000)

    # Particiona por element_type — docs antigos sem o campo viram CTO
    ctos_raw = []
    ce_wizard_raw = []
    cabo_wizard_raw = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for c in ctos_raw_all:
        by_id[c.get("id")] = c
        et = (c.get("element_type") or "cto").lower()
        if et == "ce":
            ce_wizard_raw.append(c)
        elif et == "cabo":
            cabo_wizard_raw.append(c)
        else:
            ctos_raw.append(c)

    ces = await db.network_ces.find({"company_id": cid}, {"_id": 0}).to_list(500)
    cables = await db.network_cables.find({"company_id": cid}, {"_id": 0}).to_list(2000)
    overrides = await db.network_positions.find({"company_id": cid}, {"_id": 0}).to_list(2000)
    pos_map = {f"{o['entity_type']}:{o['entity_id']}": (o["lat"], o["lng"]) for o in overrides}

    ctos = []
    for c in ctos_raw:
        gps = c.get("gps") or {}
        key = f"cto:{c['id']}"
        if key in pos_map:
            lat, lng = pos_map[key]
        else:
            lat, lng = gps.get("lat"), gps.get("lng")
        if lat is None or lng is None:
            continue
        health = await _cto_health(cid, c)
        used = len([p for p in (c.get("ports") or []) if p.get("status") == "used"])
        ctos.append({
            "id": c["id"], "name": c["name"], "lat": lat, "lng": lng,
            "vlan": c.get("vlan"), "sigla": c.get("sigla"),
            "capacity": c.get("capacity"),
            "used_ports": used,
            "address": c.get("address"),
            "status": c.get("status"),
            "network_type": c.get("network_type"),
            "splitter": c.get("splitter"),
            "health": health,
            "moved_manually": key in pos_map,
            "photo_thumb": bool(c.get("photo_data_url")),
            # Saúde física da IA (Gemini Vision) — opcional
            "photo_severity": c.get("last_photo_severity"),
            "photo_tags": c.get("last_photo_tags") or [],
            "photo_summary": c.get("last_photo_summary"),
            "photo_at": c.get("last_photo_at"),
            # Galeria de fotos cadastradas (aprovadas pela validação ou
            # uploads manuais). Pedido do usuário: clique 2× na CTO no
            # mapa interativo mostra a galeria no popup.
            "photos": [
                {"id": ph.get("id"),
                  "url": ph.get("url") or ph.get("data_url"),
                  "uploaded_at": ph.get("uploaded_at"),
                  "uploaded_by_name": ph.get("uploaded_by_name"),
                  "source": ph.get("source"),
                  "caption": ph.get("caption")}
                for ph in (c.get("photos") or [])
                if (ph.get("url") or ph.get("data_url"))
            ][:8],
        })

    # Aplica overrides nas CEs também
    ces_out = []
    for ce in ces:
        key = f"ce:{ce['id']}"
        if key in pos_map:
            ce["lat"], ce["lng"] = pos_map[key]
            ce["moved_manually"] = True
        else:
            ce["moved_manually"] = False
        ces_out.append(ce)

    # iter148 — CEs cadastradas via wizard mobile (em db.ctos com element_type=ce)
    for ce in ce_wizard_raw:
        gps = ce.get("gps") or {}
        key = f"ce:{ce['id']}"
        if key in pos_map:
            lat, lng = pos_map[key]
            moved = True
        else:
            lat, lng = gps.get("lat"), gps.get("lng")
            moved = False
        if lat is None or lng is None:
            continue
        ces_out.append({
            "id": ce["id"],
            "name": ce.get("name") or "CE",
            "lat": lat, "lng": lng,
            "capacity_fo": ce.get("bandejas_total"),
            "type": ce.get("ce_install_type") or "aerea",
            "address": ce.get("address"),
            "status": ce.get("status"),
            "vlan": ce.get("vlan"),
            "sigla": ce.get("sigla"),
            "moved_manually": moved,
            "source": "wizard_mobile",
            "photo_thumb": bool(ce.get("photo_data_url")),
        })

    # iter148 — CABOs cadastrados via wizard mobile (db.ctos element_type=cabo)
    # Cada cabo tem from_element_id e to_element_id apontando para outros
    # docs em db.ctos (CTO ou CE). Resolvemos os GPS dos endpoints para
    # desenhar a polyline.
    for cabo in cabo_wizard_raw:
        f_id = cabo.get("from_element_id")
        t_id = cabo.get("to_element_id")
        f_doc = by_id.get(f_id) or {}
        t_doc = by_id.get(t_id) or {}
        f_gps = f_doc.get("gps") or {}
        t_gps = t_doc.get("gps") or {}
        # Aplica overrides quando existirem
        fkey_t = (f_doc.get("element_type") or "cto").lower()
        tkey_t = (t_doc.get("element_type") or "cto").lower()
        fkey = f"{fkey_t}:{f_id}" if f_id else None
        tkey = f"{tkey_t}:{t_id}" if t_id else None
        f_lat, f_lng = (pos_map[fkey] if fkey in pos_map
                          else (f_gps.get("lat"), f_gps.get("lng")))
        t_lat, t_lng = (pos_map[tkey] if tkey in pos_map
                          else (t_gps.get("lat"), t_gps.get("lng")))

        # iter186 — Cabo solto (sem from/to vinculado): usa primeira/última
        # coord do route_geometry como pontas; ou cabo.gps + cabo.to_gps.
        geom = cabo.get("route_geometry") or []
        if (f_lat is None or f_lng is None) and len(geom) > 0:
            f_lat, f_lng = geom[0][0], geom[0][1]
        elif (f_lat is None or f_lng is None) and cabo.get("gps"):
            f_lat, f_lng = cabo["gps"].get("lat"), cabo["gps"].get("lng")
        if (t_lat is None or t_lng is None) and len(geom) > 0:
            t_lat, t_lng = geom[-1][0], geom[-1][1]
        elif (t_lat is None or t_lng is None) and cabo.get("to_gps"):
            t_lat, t_lng = cabo["to_gps"].get("lat"), cabo["to_gps"].get("lng")

        if (f_lat is None or f_lng is None
            or t_lat is None or t_lng is None):
            continue
        # Mapeia cable_type lógico (drop/distribuicao/backbone) para
        # capacidade legada (drop/12fo/24fo) para reuso do estilo do mapa
        ct_logical = (cabo.get("cable_type") or "").lower()
        type_legacy = {
            "drop": "drop",
            "distribuicao": "12fo",
            "backbone": "24fo",
        }.get(ct_logical, "12fo")
        # Capacidade real (fibras_total) sobrepõe o tipo legado se grande
        ft = cabo.get("fibras_total") or 0
        if ft >= 48:
            type_legacy = "48fo"
        elif ft >= 96:
            type_legacy = "96fo"
        # iter186 — Segments: prioriza route_geometry (trajeto real pelas
        # ruas) sobre a reta from→to.
        if len(geom) >= 2:
            segments = [{"lat": p[0], "lng": p[1]} for p in geom]
        else:
            segments = [
                {"lat": f_lat, "lng": f_lng},
                {"lat": t_lat, "lng": t_lng},
            ]
        cables.append({
            "id": cabo["id"],
            "name": cabo.get("name"),
            "type": type_legacy,
            "fo_count": ft,
            "fibras_ocupadas": cabo.get("fibras_ocupadas") or 0,
            "cable_type_logical": ct_logical or None,
            "from_id": f_id, "from_type": fkey_t if f_id else None,
            "to_id": t_id, "to_type": tkey_t if t_id else None,
            "segments": segments,
            "status": cabo.get("status"),
            "is_loose": bool(cabo.get("is_loose"))
                or cabo.get("status") == "cabo_solto",
            "total_length_m": cabo.get("total_length_m"),
            "source": "wizard_mobile",
            "photo_thumb": bool(cabo.get("photo_extra_data_url")
                                  or cabo.get("photo_data_url")),
        })

    # Estatísticas agregadas por VLAN para o painel lateral
    vlans: Dict[int, Dict[str, Any]] = {}
    for c in ctos:
        v = c.get("vlan")
        if v is None:
            continue
        bucket = vlans.setdefault(v, {
            "vlan": v, "sigla": c.get("sigla"), "cto_count": 0,
            "critical": 0, "warning": 0, "ok": 0,
            "avg_score": 0, "scores": [],
            "subscriber_count": 0, "avg_signal_dbm": None,
            "source": "ctos",
        })
        bucket["cto_count"] += 1
        bucket["scores"].append(c["health"].get("score", 100))
        st = c["health"].get("status")
        if st in bucket:
            bucket[st] += 1
    for v, b in vlans.items():
        scores = b.pop("scores")
        b["avg_score"] = round(sum(scores) / len(scores)) if scores else 100

    # iter180 — adiciona VLANs detectadas pelo SmartOLT (via subscribers
    # com current_vlan e ONUs Online) que ainda não têm CTO cadastrada.
    # Assim a "Média de sinal por VLAN (vinda do SmartOLT)" mostra TODAS
    # as VLANs ativas no provedor — não só as já mapeadas no rede_IA.
    sub_pipeline = [
        {"$match": {"company_id": cid,
                      "current_vlan": {"$ne": None}}},
        {"$group": {"_id": "$current_vlan", "count": {"$sum": 1}}},
    ]
    async for row in db.subscribers.aggregate(sub_pipeline):
        v = row.get("_id")
        if v is None:
            continue
        bucket = vlans.setdefault(v, {
            "vlan": v, "sigla": None, "cto_count": 0,
            "critical": 0, "warning": 0, "ok": 0,
            "avg_score": 0,
            "subscriber_count": 0, "avg_signal_dbm": None,
            "source": "smartolt_only",
        })
        bucket["subscriber_count"] = row["count"]

    # iter181 — Conta clientes com PORTA CTO DESIGNADA por VLAN.
    # Cada CTO tem ports[].client_subscriber_id preenchido quando a porta
    # está ocupada por um cliente. Agrupa por VLAN da CTO.
    cto_assigned_pipeline = [
        {"$match": {"company_id": cid, "vlan": {"$ne": None}}},
        {"$project": {"_id": 0, "vlan": 1, "ports": 1}},
        {"$unwind": {"path": "$ports", "preserveNullAndEmptyArrays": False}},
        {"$match": {"ports.client_subscriber_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$vlan", "count": {"$sum": 1}}},
    ]
    async for row in db.ctos.aggregate(cto_assigned_pipeline):
        v = row.get("_id")
        if v is None:
            continue
        bucket = vlans.setdefault(v, {
            "vlan": v, "sigla": None, "cto_count": 0,
            "critical": 0, "warning": 0, "ok": 0,
            "avg_score": 0, "subscriber_count": 0,
            "avg_signal_dbm": None, "source": "ctos",
        })
        bucket["cto_assigned_count"] = row["count"]

    # Sinal médio (1490 nm — RX da OLT no cliente) por VLAN, somente
    # ONUs online. Tipicamente: -20 dBm é ótimo, < -28 dBm é crítico.
    signal_pipeline = [
        {"$match": {"company_id": cid, "status": "Online"}},
        {"$project": {"_id": 0, "service_ports": 1, "signal_1490": 1,
                        "olt_name": 1}},
    ]
    sig_acc: Dict[int, list] = {}
    # iter180 — agrupamento por OLT para o card "VLANs por OLT".
    # vlans_by_olt[olt_name][vlan] = {onus, signals[]}
    olt_acc: Dict[str, Dict[int, Dict[str, Any]]] = {}
    async for o in db.smartolt_onus.aggregate(signal_pipeline):
        sig = o.get("signal_1490")
        olt = o.get("olt_name") or "Desconhecida"
        try:
            sig_f = float(sig) if sig is not None else None
        except Exception:
            sig_f = None
        for sp in (o.get("service_ports") or []):
            vv = (sp or {}).get("vlan")
            if vv in (None, "", "0"):
                continue
            try:
                vv = int(str(vv).strip())
            except Exception:
                continue
            if sig_f is not None:
                sig_acc.setdefault(vv, []).append(sig_f)
            ob = olt_acc.setdefault(olt, {})
            vb = ob.setdefault(vv, {"vlan": vv, "onu_count": 0, "signals": []})
            vb["onu_count"] += 1
            if sig_f is not None:
                vb["signals"].append(sig_f)
    for vv, arr in sig_acc.items():
        if not arr:
            continue
        avg = round(sum(arr) / len(arr), 1)
        bucket = vlans.setdefault(vv, {
            "vlan": vv, "sigla": None, "cto_count": 0,
            "critical": 0, "warning": 0, "ok": 0,
            "avg_score": 0, "subscriber_count": 0,
            "source": "smartolt_only",
        })
        bucket["avg_signal_dbm"] = avg
        bucket["onu_online_count"] = len(arr)
        # Calcula score derivado do sinal (apenas se a VLAN não vier de
        # CTOs cadastradas). Range: 0..100 → -28 dBm = 0%, -20 dBm = 100%.
        if bucket["source"] == "smartolt_only":
            score = max(0, min(100, round((avg + 28) * 12.5)))
            bucket["avg_score"] = score
            if score < 50:
                bucket["critical"] += 1
            elif score < 75:
                bucket["warning"] += 1
            else:
                bucket["ok"] += 1

    # Ordena por subscriber_count + cto_count desc
    vlan_list = sorted(
        list(vlans.values()),
        key=lambda x: (x.get("subscriber_count", 0) + x.get("cto_count", 0) * 10),
        reverse=True,
    )

    # iter180 — Agrupamento final por OLT (para o card "VLANs por OLT")
    vlans_by_olt: List[Dict[str, Any]] = []
    for olt_name, vmap in olt_acc.items():
        olt_vlans = []
        total_onus = 0
        total_signals = []
        for vv, vb in vmap.items():
            sigs = vb["signals"]
            avg = round(sum(sigs) / len(sigs), 1) if sigs else None
            olt_vlans.append({
                "vlan": vv,
                "onu_count": vb["onu_count"],
                "avg_signal_dbm": avg,
            })
            total_onus += vb["onu_count"]
            total_signals.extend(sigs)
        olt_vlans.sort(key=lambda x: x["onu_count"], reverse=True)
        olt_avg = (round(sum(total_signals) / len(total_signals), 1)
                   if total_signals else None)
        vlans_by_olt.append({
            "olt_name": olt_name,
            "vlans": olt_vlans,
            "vlan_count": len(olt_vlans),
            "onu_count": total_onus,
            "avg_signal_dbm": olt_avg,
        })
    vlans_by_olt.sort(key=lambda x: x["onu_count"], reverse=True)

    return {
        "ctos": ctos,
        "ces": ces_out,
        "cables": cables,
        "vlans": vlan_list,
        "vlans_by_olt": vlans_by_olt,
        "center": _compute_center(ctos),
    }


def _compute_center(ctos: List[Dict[str, Any]]) -> Dict[str, float]:
    """Retorna o centro geográfico médio das CTOs (para fitBounds)."""
    if not ctos:
        return {"lat": -22.9068, "lng": -43.1729}  # Rio fallback
    lats = [c["lat"] for c in ctos]
    lngs = [c["lng"] for c in ctos]
    return {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}


# ---------------------------------------------------------------------------
# CE CRUD
# ---------------------------------------------------------------------------
@router.post("/ces")
async def create_ce(body: CEIn,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.type not in CE_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use: {CE_TYPES}")
    cid = _company(user)
    doc = {
        "id": f"ce-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "name": body.name,
        "lat": body.lat, "lng": body.lng,
        "capacity_fo": body.capacity_fo,
        "type": body.type,
        "parent_ce_id": body.parent_ce_id,
        "address": body.address,
        "notes": body.notes,
        "status": "active",
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("name"),
    }
    await db.network_ces.insert_one(doc)
    doc.pop("_id", None)
    await _notify_managers(cid, {
        "event": "ce_created",
        "title": f"Nova CE criada: {body.name}",
        "message": (f"{user.get('name','Alguém')} criou a Caixa de Emenda '{body.name}' "
                     f"({body.type}, {body.capacity_fo} FO) no mapa."),
        "ref_id": doc["id"], "ref_type": "ce",
        "actor": user.get("name"),
    })
    return doc


@router.put("/ces/{ce_id}")
async def update_ce(ce_id: str, body: CEIn,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    upd = body.model_dump()
    upd["updated_at"] = now_iso()
    r = await db.network_ces.update_one(
        {"id": ce_id, "company_id": cid}, {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "CE não encontrada")
    return {"ok": True}


@router.delete("/ces/{ce_id}")
async def delete_ce(ce_id: str,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    ce_doc = await db.network_ces.find_one(
        {"id": ce_id, "company_id": cid}, {"_id": 0})
    if not ce_doc:
        raise HTTPException(404, "CE não encontrada")
    cables_snap = await db.network_cables.find(
        {"company_id": cid,
         "$or": [{"from_id": ce_id}, {"to_id": ce_id}]},
        {"_id": 0}).to_list(500)
    from datetime import datetime, timezone
    actor = user.get("name") or user.get("email") or "?"
    await db.rede_ia_trash.insert_one({
        "id": f"trash-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "kind": "ce", "ref_id": ce_id,
        "label": ce_doc.get("name") or ce_id,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "deleted_by": actor,
        "snapshot": ce_doc,
        "cables_snapshot": cables_snap,
    })
    # remove cabos ligados
    await db.network_cables.delete_many({"company_id": cid,
                                            "$or": [{"from_id": ce_id}, {"to_id": ce_id}]})
    await db.network_ces.delete_one({"id": ce_id, "company_id": cid})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cable CRUD
# ---------------------------------------------------------------------------
@router.post("/cables")
async def create_cable(body: CableIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.type not in CABLE_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use: {CABLE_TYPES}")
    # iter211e — SN e NF obrigatórios para cabos de fibra (não-drop)
    if body.type != "drop":
        if not (body.cable_serial or "").strip():
            raise HTTPException(400,
                "SN do cabo é obrigatório para cabos de fibra "
                f"({body.type.upper()}).")
        if not (body.invoice_number or "").strip():
            raise HTTPException(400,
                "Nota fiscal é obrigatória para cabos de fibra "
                f"({body.type.upper()}).")
    cid = _company(user)
    fo_map = {"drop": 1, "6fo": 6, "12fo": 12, "24fo": 24, "48fo": 48, "96fo": 96}
    segments = [s.model_dump() for s in body.segments]
    # Calcula comprimento automaticamente se não foi fornecido
    length_m = body.length_m
    if length_m is None and len(segments) >= 2:
        length_m = _calculate_cable_length(segments)

    # Onda C P0.1 — RCA Fibra Guardrails (CEO 18/06/2026)
    # Aplica DEPOIS do cálculo de length_m para validar valor real.
    _validate_cable_guardrails(body, user, length_m)
    length_tier = _length_warning_tier(length_m)

    doc = {
        "id": f"cab-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": body.type,
        "fo_count": fo_map.get(body.type, 12),
        "from_id": body.from_id, "from_type": body.from_type,
        "to_id": body.to_id, "to_type": body.to_type,
        "segments": segments,
        "length_m": length_m,
        "notes": body.notes,
        # iter211e — Rastreabilidade
        "cable_serial": (body.cable_serial or "").strip() or None,
        "invoice_number": (body.invoice_number or "").strip() or None,
        "purchase_id": body.purchase_id,
        # Onda C P0.1 — guardrail audit (override e tier de comprimento)
        "guardrail_length_tier": length_tier,
        "admin_override_reason": (
            (body.admin_override_reason or "").strip() or None),
        "admin_override_by": (
            user.get("name") if (body.admin_override_reason or "").strip() else None),
        # iter211c — cabo sem from/to vira `cabo_solto`
        "status": ("cabo_solto"
                    if not body.from_id or not body.to_id else "active"),
        "is_loose": (not body.from_id) or (not body.to_id),
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("name"),
    }
    await db.network_cables.insert_one(doc)
    doc.pop("_id", None)
    # Auto-baixa de estoque (6fo/12fo/24fo) no estoque do criador.
    debit = await _debit_fiber_for_cable(
        cid, user, body.type, length_m, doc["id"], action="create")
    if debit:
        await db.network_cables.update_one(
            {"id": doc["id"]}, {"$set": {"stok_debit": debit}})
        doc["stok_debit"] = debit
    # Notifica gestores de rede
    def _peer_label(_id, _type):
        if not _id or not _type:
            return "ponta solta"
        return f"{_type.upper()} {_id[:8]}"
    await _notify_managers(cid, {
        "event": "cable_created",
        "title": f"Novo cabo {body.type.upper()} criado",
        "message": (f"{user.get('name','Alguém')} criou um cabo {body.type.upper()} de "
                     f"{round(length_m or 0)}m entre {_peer_label(body.from_id, body.from_type)} "
                     f"e {_peer_label(body.to_id, body.to_type)}."),
        "ref_id": doc["id"], "ref_type": "cable",
        "actor": user.get("name"),
    })
    return doc


def _calculate_cable_length(segments: List[Dict[str, Any]]) -> float:
    """Soma Haversine entre todos os segmentos consecutivos."""
    total = 0.0
    for i in range(len(segments) - 1):
        a, b = segments[i], segments[i + 1]
        total += _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
    return round(total, 1)


@router.put("/cables/{cable_id}")
async def update_cable(cable_id: str, body: CableIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    # Carrega o cabo atual para calcular diff de estoque (tipo ou comprimento podem ter mudado)
    prev = await db.network_cables.find_one(
        {"id": cable_id, "company_id": cid}, {"_id": 0})
    if not prev:
        raise HTTPException(404, "Cabo não encontrado")
    fo_map = {"drop": 1, "6fo": 6, "12fo": 12, "24fo": 24, "48fo": 48, "96fo": 96}
    segments = [s if isinstance(s, dict) else s.model_dump() for s in body.segments]
    length_m = body.length_m
    if length_m is None and len(segments) >= 2:
        length_m = _calculate_cable_length(segments)
    upd = body.model_dump()
    upd["fo_count"] = fo_map.get(body.type, 12)
    upd["segments"] = segments
    upd["length_m"] = length_m
    upd["updated_at"] = now_iso()
    r = await db.network_cables.update_one(
        {"id": cable_id, "company_id": cid}, {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Cabo não encontrado")
    # Ajusta estoque: devolve o antigo e debita o novo (mesmo location)
    prev_type = prev.get("type")
    prev_len = prev.get("length_m") or 0
    if prev_type in _CABLE_TYPE_TO_STOK_ID and prev_len > 0:
        await _debit_fiber_for_cable(cid, user, prev_type, prev_len, cable_id, action="delete")
    if body.type in _CABLE_TYPE_TO_STOK_ID and (length_m or 0) > 0:
        new_debit = await _debit_fiber_for_cable(
            cid, user, body.type, length_m, cable_id, action="create")
        if new_debit:
            await db.network_cables.update_one(
                {"id": cable_id}, {"$set": {"stok_debit": new_debit}})
    return {"ok": True, "length_m": length_m}


@router.delete("/cables/{cable_id}")
async def delete_cable(cable_id: str,
                        user: dict = Depends(require_role(
                            "administrador", "gestor", "gestor_rede", "auditor"))):
    cid = _company(user)
    prev = await db.network_cables.find_one(
        {"id": cable_id, "company_id": cid}, {"_id": 0})
    if not prev:
        raise HTTPException(404, "Cabo não encontrado")
    from datetime import datetime, timezone
    actor = user.get("name") or user.get("email") or "?"
    await db.rede_ia_trash.insert_one({
        "id": f"trash-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "kind": "cable", "ref_id": cable_id,
        "label": prev.get("label") or f"Cabo {prev.get('type', '')}",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "deleted_by": actor,
        "snapshot": prev,
    })
    await db.network_cables.delete_one({"id": cable_id, "company_id": cid})
    # Devolve o material ao estoque (refund)
    if prev.get("type") in _CABLE_TYPE_TO_STOK_ID \
            and (prev.get("length_m") or 0) > 0:
        await _debit_fiber_for_cable(
            cid, user, prev["type"], prev.get("length_m"), cable_id, action="delete")
    return {"ok": True}


# iter215bk — Lixeira + Restore para o Mapa Interativo
@router.get("/trash")
async def list_trash(
    user: dict = Depends(require_role("administrador", "gestor", "gestor_rede")),
):
    """Lista CTOs/CEs/Cabos apagados (últimos 50)."""
    cid = _company(user)
    items = await db.rede_ia_trash.find(
        {"company_id": cid}, {"_id": 0, "snapshot": 0, "cables_snapshot": 0,
                                 "ports_snapshot": 0},
    ).sort("deleted_at", -1).limit(50).to_list(50)
    return {"items": items, "count": len(items)}


@router.post("/restore/{trash_id}")
async def restore_from_trash(
    trash_id: str,
    user: dict = Depends(require_role("administrador", "gestor", "gestor_rede")),
):
    """Restaura um item da lixeira (CTO/CE/Cabo + dependências em cascata)."""
    cid = _company(user)
    rec = await db.rede_ia_trash.find_one(
        {"id": trash_id, "company_id": cid}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Item da lixeira não encontrado")
    kind = rec["kind"]
    snap = rec.get("snapshot") or {}
    restored = {"kind": kind, "label": rec.get("label")}
    if kind == "cto":
        await db.ctos.insert_one(dict(snap))
        for cab in rec.get("cables_snapshot") or []:
            await db.rede_cables.insert_one(dict(cab))
        for port in rec.get("ports_snapshot") or []:
            await db.cto_ports.insert_one(dict(port))
        restored["cables_restored"] = len(rec.get("cables_snapshot") or [])
        restored["ports_restored"] = len(rec.get("ports_snapshot") or [])
    elif kind == "ce":
        await db.network_ces.insert_one(dict(snap))
        for cab in rec.get("cables_snapshot") or []:
            await db.network_cables.insert_one(dict(cab))
        restored["cables_restored"] = len(rec.get("cables_snapshot") or [])
    elif kind == "cable":
        await db.network_cables.insert_one(dict(snap))
    else:
        raise HTTPException(400, f"Tipo desconhecido: {kind}")
    await db.rede_ia_trash.delete_one({"id": trash_id})
    restored["restored"] = True
    return restored


class BulkDeleteIn(BaseModel):
    cable_ids: Optional[List[str]] = None      # IDs específicos
    cable_types: Optional[List[str]] = None    # filtro por tipo (6fo,12fo,24fo…)
    since: Optional[str] = None                 # ISO date — created_at >= since
    until: Optional[str] = None                 # ISO date — created_at <= until
    refund_stock: bool = True                   # devolve material ao estoque
    confirm_token: Optional[str] = None         # exige texto "APAGAR LANCAMENTOS"


@router.post("/cables/bulk-delete")
async def bulk_delete_cables(body: BulkDeleteIn,
                              user: dict = Depends(require_role("auditor"))):
    """Apaga lançamentos de cabo em lote — EXCLUSIVO do auditor.

    Modos:
    - `cable_ids` preenchido → deleta apenas esses (auditoria individual)
    - Senão, aplica filtros `cable_types` + `since` + `until` (varredura)
    - `refund_stock=True` (default) devolve fibras 6/12/24FO ao estoque
    - Requer `confirm_token == "APAGAR LANCAMENTOS"` para varredura sem IDs
    """
    cid = _company(user)
    # Monta query
    q: Dict[str, Any] = {"company_id": cid}
    if body.cable_ids:
        q["id"] = {"$in": body.cable_ids}
    else:
        # Varredura — exige token
        if body.confirm_token != "APAGAR LANCAMENTOS":
            raise HTTPException(400,
                "Para apagar em massa, envie confirm_token='APAGAR LANCAMENTOS'.")
        if body.cable_types:
            q["type"] = {"$in": body.cable_types}
        if body.since or body.until:
            rng: Dict[str, Any] = {}
            if body.since:
                rng["$gte"] = body.since
            if body.until:
                rng["$lte"] = body.until
            q["created_at"] = rng

    # Carrega todos antes de deletar (precisa pra refund)
    to_delete = await db.network_cables.find(
        q, {"_id": 0, "id": 1, "type": 1, "length_m": 1,
            "created_by": 1, "created_at": 1}).to_list(5000)
    if not to_delete:
        return {"ok": True, "deleted": 0, "refunded": []}

    # Apaga
    ids = [c["id"] for c in to_delete]
    await db.network_cables.delete_many({"company_id": cid, "id": {"$in": ids}})

    # Refund estoque (best-effort, não derruba se falhar)
    refunded: List[dict] = []
    if body.refund_stock:
        for c in to_delete:
            if c.get("type") in _CABLE_TYPE_TO_STOK_ID \
                    and (c.get("length_m") or 0) > 0:
                try:
                    r = await _debit_fiber_for_cable(
                        cid, user, c["type"], c.get("length_m"),
                        c["id"], action="delete")
                    if r:
                        refunded.append({"cable_id": c["id"], **r})
                except Exception as e:
                    logger.warning("[bulk-delete] refund %s falhou: %s", c["id"], e)

    # Audit log explicito
    summary = (f"Auditor {user.get('name')} apagou {len(ids)} lançamento(s) "
               f"({'IDs específicos' if body.cable_ids else 'varredura'}). "
               f"Refund: {len(refunded)} cabos de fibra devolvidos.")
    await db.stok_history.insert_one({
        "id": f"hist-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "date": now_iso(),
        "type": "rede_bulk_delete",
        "description": summary,
        "user": user.get("name", "auditor"),
        "tag": "rede_lancamento",
        "cable_ids": ids,
    })
    logger.warning("[rede_ia] %s", summary)
    return {"ok": True, "deleted": len(ids), "refunded": refunded,
            "cable_ids": ids}


# ---------------------------------------------------------------------------
# Position overrides (drag to reposition)
# ---------------------------------------------------------------------------
@router.get("/map/fiber-kpi")
async def fiber_kpi(days: int = Query(7, ge=1, le=365),
                     user: dict = Depends(require_role(
                         "administrador", "gestor", "gestor_rede", "auditor"))):
    """KPIs de fibra lançada no mapa interativo (últimos N dias).

    Retorna total geral, breakdown por tipo (6FO/12FO/24FO), por técnico/origem,
    e série temporal por dia (para gráfico).
    """
    from datetime import timedelta
    cid = _company(user)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    cur = db.network_cables.find(
        {"company_id": cid, "created_at": {"$gte": since},
         "type": {"$in": list(_CABLE_TYPE_TO_STOK_ID.keys())}},
        {"_id": 0, "type": 1, "length_m": 1, "created_by": 1,
         "stok_debit": 1, "created_at": 1},
    )
    by_type: Dict[str, float] = {"6fo": 0, "12fo": 0, "24fo": 0}
    by_user: Dict[str, float] = {}
    timeline: Dict[str, float] = {}  # 'YYYY-MM-DD' -> meters
    total_m = 0.0
    count = 0
    async for c in cur:
        L = float(c.get("length_m") or 0)
        if L <= 0:
            continue
        total_m += L
        count += 1
        by_type[c["type"]] = by_type.get(c["type"], 0) + L
        u = c.get("created_by") or "—"
        by_user[u] = by_user.get(u, 0) + L
        day = (c.get("created_at") or "")[:10]
        if day:
            timeline[day] = timeline.get(day, 0) + L

    # Preenche dias sem lançamentos (eixo X contínuo)
    timeline_full = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        timeline_full.append({"date": d, "meters": int(round(timeline.get(d, 0)))})

    return {
        "days": days,
        "total_meters": int(round(total_m)),
        "cables_count": count,
        "by_type": {k: int(round(v)) for k, v in by_type.items()},
        "by_user": [
            {"name": k, "meters": int(round(v))}
            for k, v in sorted(by_user.items(), key=lambda x: -x[1])
        ][:10],
        "timeline": timeline_full,
    }


@router.get("/map/fiber-alerts")
async def fiber_alerts(threshold_m: int = Query(200, ge=0, le=10000),
                        user: dict = Depends(require_role(
                            "administrador", "gestor", "gestor_rede", "auditor"))):
    """Identifica locais com saldo de fibra (6/12/24FO) abaixo do threshold.

    Verifica `stok_stock` para 'empresa' + cada colaborador (técnico de rede).
    Retorna lista de alertas com {location, location_label, consumable_id, qty, threshold}.
    """
    cid = _company(user)
    # Carrega todos os locais de estoque
    rows = await db.stok_stock.find(
        {"company_id": cid}, {"_id": 0}).to_list(500)
    # Mapa de collaborator_id → nome (para humanizar)
    colab_names = {}
    async for c in db.collaborators.find(
            {"company_id": cid}, {"_id": 0, "id": 1, "name": 1}):
        colab_names[c["id"]] = c["name"]

    alerts: List[Dict[str, Any]] = []
    for r in rows:
        loc = r.get("location") or ""
        loc_label = ("Empresa" if loc == "empresa"
                     else colab_names.get(loc, f"Estoque {loc}"))
        for cons_id in ("fibra_06fo", "fibra_12fo", "fibra_24fo"):
            qty = int(r.get(cons_id, 0) or 0)
            # Só alerta se houve atividade (qty > 0 em algum momento, ou negativo).
            # Skipa locais que nunca tiveram fibra (sem saldo registrado).
            if cons_id not in r:
                continue
            if qty <= threshold_m:
                alerts.append({
                    "location": loc, "location_label": loc_label,
                    "consumable_id": cons_id,
                    "consumable_label": cons_id.replace("fibra_", "Fibra ").upper().replace("FIBRA ", "Fibra "),
                    "qty": qty, "threshold": threshold_m,
                    "severity": "critical" if qty < 0 else
                                  "warning" if qty < threshold_m / 2 else "info",
                })
    # Ordena: críticos primeiro, depois por saldo
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 3), a["qty"]))
    return {"threshold": threshold_m, "alerts": alerts}


@router.post("/map/positions")
async def save_position(body: PositionIn,
                         user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.entity_type not in ("cto", "ce"):
        raise HTTPException(400, "Entity type deve ser 'cto' ou 'ce'")
    cid = _company(user)
    doc = {
        "company_id": cid,
        "entity_id": body.entity_id,
        "entity_type": body.entity_type,
        "lat": body.lat,
        "lng": body.lng,
        "updated_at": now_iso(),
        "updated_by": user.get("name"),
    }
    await db.network_positions.update_one(
        {"company_id": cid, "entity_id": body.entity_id, "entity_type": body.entity_type},
        {"$set": doc}, upsert=True,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auto-generate CEs (rede_IA)
# ---------------------------------------------------------------------------
@router.post("/map/auto-generate-ces")
async def auto_generate_ces(radius_m: float = Query(200.0, ge=50, le=2000),
                             user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Agrupa CTOs próximas em CEs automaticamente (cluster geográfico).

    Algoritmo: para cada CTO sem CE atribuída, encontra vizinhas no raio
    `radius_m`. Cria 1 CE no centroide do cluster.
    Também cria cabos `24fo` ligando CE → CTOs do cluster.
    """
    cid = _company(user)
    ctos = await db.ctos.find(
        {"company_id": cid, "status": "approved", "gps.lat": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "sigla": 1, "vlan": 1},
    ).to_list(1000)

    if not ctos:
        return {"ok": False, "msg": "Nenhuma CTO aprovada com GPS"}

    # Cabos existentes: skipa CTOs já conectadas
    existing_to_ids = set()
    async for cab in db.network_cables.find({"company_id": cid}, {"_id": 0, "to_id": 1}):
        existing_to_ids.add(cab["to_id"])

    visited: set = set()
    new_ces: List[Dict[str, Any]] = []
    new_cables: List[Dict[str, Any]] = []

    for i, c in enumerate(ctos):
        if c["id"] in visited:
            continue
        gps = c.get("gps") or {}
        if gps.get("lat") is None:
            continue
        cluster = [c]
        visited.add(c["id"])
        for j in range(i + 1, len(ctos)):
            c2 = ctos[j]
            if c2["id"] in visited:
                continue
            gps2 = c2.get("gps") or {}
            if gps2.get("lat") is None:
                continue
            d = _haversine_m(gps["lat"], gps["lng"], gps2["lat"], gps2["lng"])
            if d <= radius_m and c.get("sigla") == c2.get("sigla"):
                cluster.append(c2)
                visited.add(c2["id"])

        # Centroide
        lat_c = sum((cl.get("gps") or {}).get("lat", 0) for cl in cluster) / len(cluster)
        lng_c = sum((cl.get("gps") or {}).get("lng", 0) for cl in cluster) / len(cluster)
        ce_doc = {
            "id": f"ce-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "name": f"CE-{c.get('sigla','GEN')}-{len(new_ces)+1:03d}",
            "lat": lat_c, "lng": lng_c,
            "capacity_fo": 24,
            "type": "secundaria",
            "parent_ce_id": None,
            "address": "",
            "notes": f"Auto-gerada pela rede_IA · cluster com {len(cluster)} CTOs",
            "status": "active",
            "auto_generated": True,
            "created_at": now_iso(), "updated_at": now_iso(),
            "created_by": "rede_IA (automático)",
        }
        new_ces.append(ce_doc)

        # Cria cabos CE → cada CTO
        for cl in cluster:
            if cl["id"] in existing_to_ids:
                continue
            gps_cl = cl.get("gps") or {}
            new_cables.append({
                "id": f"cab-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "type": "24fo",
                "fo_count": 24,
                "from_id": ce_doc["id"], "from_type": "ce",
                "to_id": cl["id"], "to_type": "cto",
                "segments": [
                    {"lat": ce_doc["lat"], "lng": ce_doc["lng"]},
                    {"lat": gps_cl["lat"], "lng": gps_cl["lng"]},
                ],
                "length_m": _haversine_m(ce_doc["lat"], ce_doc["lng"],
                                            gps_cl["lat"], gps_cl["lng"]),
                "notes": "Auto-gerado pela rede_IA",
                "status": "active",
                "auto_generated": True,
                "created_at": now_iso(), "updated_at": now_iso(),
                "created_by": "rede_IA (automático)",
            })

    if new_ces:
        await db.network_ces.insert_many(new_ces)
    if new_cables:
        await db.network_cables.insert_many(new_cables)

    return {
        "ok": True,
        "ces_created": len(new_ces),
        "cables_created": len(new_cables),
        "ctos_clustered": len(visited),
        "radius_m": radius_m,
    }


# ---------------------------------------------------------------------------
# Public shareable map (read-only)  — token HMAC
# ---------------------------------------------------------------------------
PUBLIC_SECRET = os.environ.get("REDE_IA_PUBLIC_SECRET") or \
    os.environ.get("REDE_IA_QR_SECRET") or "smartprov-rede-ia-public-default-secret"
PUBLIC_PREFIX = "SPMAP"
PUBLIC_VERSION = "v1"


def _public_sign(b64: str) -> str:
    return hmac.new(PUBLIC_SECRET.encode("utf-8"), b64.encode("utf-8"),
                      hashlib.sha256).hexdigest()[:32]


def _build_public_token(company_id: str, vlan_filter: Optional[int] = None,
                          ttl_days: int = 30) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "cid": company_id,
        "vlan": vlan_filter,
        "ts": now,
        "exp": now + (ttl_days * 86400),
        "n": uuid.uuid4().hex[:8],
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = _public_sign(b64)
    return f"{PUBLIC_PREFIX}|{PUBLIC_VERSION}|{b64}|{sig}"


def _verify_public_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = (token or "").split("|")
        if len(parts) != 4:
            return None
        prefix, ver, b64, sig = parts
        if prefix != PUBLIC_PREFIX or ver != PUBLIC_VERSION:
            return None
        if not hmac.compare_digest(_public_sign(b64), sig):
            return None
        pad = "=" * (-len(b64) % 4)
        raw = base64.urlsafe_b64decode(b64 + pad)
        payload = json.loads(raw.decode("utf-8"))
        # Verifica expiração
        exp = payload.get("exp")
        if exp is not None:
            now = int(datetime.now(timezone.utc).timestamp())
            if now > exp:
                return None
        return payload
    except Exception:
        return None


class PublicTokenIn(BaseModel):
    vlan: Optional[int] = None
    ttl_days: int = Field(30, ge=1, le=365)


@router.post("/map/public/token")
async def create_public_token(body: PublicTokenIn,
                                user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Gera token público compartilhável com TTL (padrão 30 dias)."""
    cid = _company(user)
    token = _build_public_token(cid, body.vlan, body.ttl_days)
    expires_at = (datetime.now(timezone.utc).timestamp() + body.ttl_days * 86400)
    return {
        "token": token,
        "share_url": f"/rede-publica?t={token}",
        "company_id": cid,
        "vlan_filter": body.vlan,
        "ttl_days": body.ttl_days,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    }


@router.get("/map/public/{token}")
async def public_map_data(token: str):
    """Devolve dados sanitizados do mapa para visualização pública.

    NÃO expõe: endereços completos, foto, ONUs detalhadas, técnicos, gestor.
    EXPÕE: localização aproximada (lat/lng), saúde resumida, capacidade,
    tipo (CTO/CE), VLAN (bairro).
    """
    decoded = _verify_public_token(token)
    if not decoded:
        raise HTTPException(403, "Token público inválido ou expirado")
    cid = decoded.get("cid")
    vlan_filter = decoded.get("vlan")

    q_cto: Dict[str, Any] = {"company_id": cid, "status": "approved"}
    if vlan_filter:
        q_cto["vlan"] = vlan_filter

    ctos_raw = await db.ctos.find(q_cto, {"_id": 0}).to_list(1000)
    ces = await db.network_ces.find({"company_id": cid}, {"_id": 0}).to_list(500)
    cables = await db.network_cables.find({"company_id": cid}, {"_id": 0}).to_list(2000)

    overrides = await db.network_positions.find({"company_id": cid}, {"_id": 0}).to_list(2000)
    pos_map = {f"{o['entity_type']}:{o['entity_id']}": (o["lat"], o["lng"]) for o in overrides}

    # Versão sanitizada das CTOs
    ctos: List[Dict[str, Any]] = []
    for c in ctos_raw:
        gps = c.get("gps") or {}
        key = f"cto:{c['id']}"
        if key in pos_map:
            lat, lng = pos_map[key]
        else:
            lat, lng = gps.get("lat"), gps.get("lng")
        if lat is None or lng is None:
            continue
        health = await _cto_health(cid, c)
        ctos.append({
            "id": c["id"],
            "name": c["name"],  # CTO 001_301_COR é OK público (não tem CPF)
            "lat": lat, "lng": lng,
            "vlan": c.get("vlan"),
            "sigla": c.get("sigla"),
            "capacity": c.get("capacity"),
            # NÃO expõe used_ports nem endereço completo, só bairro
            "bairro": (c.get("address") or {}).get("bairro"),
            "health_status": health.get("status"),
        })

    # CEs sanitizadas
    ces_pub: List[Dict[str, Any]] = []
    for ce in ces:
        key = f"ce:{ce['id']}"
        if key in pos_map:
            ce_lat, ce_lng = pos_map[key]
        else:
            ce_lat, ce_lng = ce.get("lat"), ce.get("lng")
        ces_pub.append({
            "id": ce["id"], "name": ce.get("name"),
            "lat": ce_lat, "lng": ce_lng,
            "type": ce.get("type"),
        })

    # Cabos sanitizados (sem notes)
    cables_pub = [{
        "id": cb["id"], "type": cb["type"], "fo_count": cb.get("fo_count"),
        "from_id": cb["from_id"], "from_type": cb["from_type"],
        "to_id": cb["to_id"], "to_type": cb["to_type"],
        "segments": cb.get("segments") or [],
    } for cb in cables]

    # Estatísticas agregadas (sem nome de cliente nem CPF)
    by_bairro: Dict[str, int] = {}
    for c in ctos:
        b = c.get("bairro") or "?"
        by_bairro[b] = by_bairro.get(b, 0) + 1

    return {
        "ctos": ctos, "ces": ces_pub, "cables": cables_pub,
        "center": _compute_center(ctos),
        "ctos_count": len(ctos),
        "by_bairro": [{"bairro": k, "count": v}
                       for k, v in sorted(by_bairro.items(), key=lambda x: -x[1])],
        "vlan_filter": vlan_filter,
        "public": True,
    }


# ---------------------------------------------------------------------------
# Notifications — gestor de rede recebe ao criar/alterar elementos do mapa
# ---------------------------------------------------------------------------
async def _notify_managers(company_id: str, evt: Dict[str, Any]) -> None:
    """Cria notificação in-app para gestor_rede + dispara WhatsApp se configurado.

    Não bloqueia em caso de erro — é fire-and-forget.
    """
    try:
        doc = {
            "id": f"notif-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "event": evt.get("event"),
            "title": evt.get("title"),
            "message": evt.get("message"),
            "ref_id": evt.get("ref_id"),
            "ref_type": evt.get("ref_type"),
            "actor": evt.get("actor"),
            "read": False,
            "created_at": now_iso(),
        }
        await db.network_notifications.insert_one(doc)
        # Dispara WhatsApp para gestor_rede com telefone configurado
        await _whatsapp_notify_managers(company_id, evt)
    except Exception as e:
        logger.warning("[map-notif] falha %s", e)


async def _whatsapp_notify_managers(company_id: str, evt: Dict[str, Any]) -> None:
    """Envia WhatsApp para todos os usuários gestor_rede com phone preenchido."""
    try:
        # Busca gestores
        managers = await db.users.find(
            {"company_id": company_id,
             "role": {"$in": ["gestor_rede", "gestor", "administrador"]},
             "notify_map_events": True,
             "phone": {"$ne": None, "$exists": True}},
            {"_id": 0, "phone": 1, "name": 1, "role": 1},
        ).to_list(20)
        if not managers:
            return
        # Tenta usar provider configurado (twilio ou meta)
        msg = f"🗺 *Rede IA*\n{evt.get('title','')}\n\n{evt.get('message','')}\n\n_Por: {evt.get('actor','?')}_"
        for m in managers:
            phone = (m.get("phone") or "").lstrip("+").replace(" ", "")
            if not phone:
                continue
            try:
                # Tenta Twilio primeiro
                from services.twilio_whatsapp import send_whatsapp as twilio_send  # type: ignore
                await twilio_send(company_id, phone, msg)
            except Exception:
                try:
                    from services.whatsapp_meta import send_whatsapp_text as meta_send  # type: ignore
                    await meta_send(company_id, phone, msg)
                except Exception as e2:
                    logger.info("[map-notif wpp] sem provider WhatsApp: %s", e2)
    except Exception as e:
        logger.info("[map-notif wpp] %s", e)


@router.get("/notifications")
async def list_notifications(unread_only: bool = Query(False),
                              limit: int = Query(50, ge=1, le=200),
                              user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if unread_only:
        q["read"] = False
    items = await db.network_notifications.find(q, {"_id": 0}).sort(
        "created_at", -1,
    ).to_list(limit)
    unread = await db.network_notifications.count_documents(
        {"company_id": cid, "read": False},
    )
    return {"items": items, "unread": unread, "total": len(items)}


class MarkReadIn(BaseModel):
    notification_id: Optional[str] = None
    mark_all: bool = False


@router.post("/notifications/mark-read")
async def mark_read(body: MarkReadIn,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    if body.mark_all:
        r = await db.network_notifications.update_many(
            {"company_id": cid, "read": False},
            {"$set": {"read": True, "read_at": now_iso(),
                       "read_by": user.get("name")}},
        )
        return {"ok": True, "modified": r.modified_count}
    if body.notification_id:
        r = await db.network_notifications.update_one(
            {"id": body.notification_id, "company_id": cid},
            {"$set": {"read": True, "read_at": now_iso(),
                       "read_by": user.get("name")}},
        )
        if r.matched_count == 0:
            raise HTTPException(404, "Notificação não encontrada")
        return {"ok": True}
    raise HTTPException(400, "Forneça notification_id ou mark_all=true")
