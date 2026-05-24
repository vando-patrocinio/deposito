"""routes/radius.py — Módulo 2 (RADIUS/PPPoE) — MVP.

Arquitetura: HTTP-bridge. FreeRADIUS externo chama nossos endpoints via
`rlm_rest` (Auth + Accounting). CoA Disconnect é enviado direto do nosso
backend via UDP (pyrad) ao IP do NAS.

Endpoints públicos (consumidos pelo FreeRADIUS — NÃO precisam JWT,
autenticação por NAS shared-secret + IP allowlist):
  POST /api/radius/auth         — Access-Request (cleartext PAP)
  POST /api/radius/accounting   — Acct-Status-Type: Start/Stop/Interim-Update

Endpoints internos (UI / staff):
  GET    /api/radius/sessions/active           — sessões ativas
  GET    /api/radius/sessions/history          — histórico (24h default)
  POST   /api/radius/sessions/{sid}/disconnect — CoA Disconnect
  GET    /api/radius/nas                       — lista NAS cadastrados
  POST   /api/radius/nas                       — cria/atualiza NAS
  DELETE /api/radius/nas/{id}                  — remove NAS
  GET    /api/radius/dashboard                 — KPIs (ativos, hoje, falhas)

Auth do PPPoE: aproveita `subscribers` (Atlaz). Campos:
  - pppoe_user (username)
  - pppoe_pass (senha cleartext — MVP, depois migrar p/ hash)
  - status (ATIVO/SUSPENSO/CANCELADO)
  - plan.speed_mbps (limita banda via Mikrotik-Rate-Limit)
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.radius")
router = APIRouter(prefix="/api/radius", tags=["radius"])


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Models
# ===========================================================================
class NasIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    ip: str
    shared_secret: str = Field(..., min_length=4, max_length=128)
    vendor: str = "mikrotik"  # mikrotik | huawei | cisco | generic
    coa_port: int = 3799  # padrão RFC 5176
    description: str = ""


class AuthRequest(BaseModel):
    """Access-Request enviado pelo FreeRADIUS (via rlm_rest)."""
    username: str
    password: str  # PAP cleartext
    nas_ip: Optional[str] = None
    nas_identifier: Optional[str] = None
    calling_station_id: Optional[str] = None  # MAC do cliente
    called_station_id: Optional[str] = None   # MAC do NAS
    framed_protocol: Optional[str] = None     # PPP


class AcctRequest(BaseModel):
    """Accounting-Request (Start/Stop/Interim-Update)."""
    acct_status_type: str  # Start | Stop | Interim-Update | Accounting-On | Accounting-Off
    username: Optional[str] = None
    acct_session_id: Optional[str] = None
    nas_ip: Optional[str] = None
    nas_identifier: Optional[str] = None
    framed_ip: Optional[str] = None
    calling_station_id: Optional[str] = None
    acct_input_octets: int = 0
    acct_output_octets: int = 0
    acct_input_gigawords: int = 0
    acct_output_gigawords: int = 0
    acct_session_time: int = 0  # segundos
    acct_terminate_cause: Optional[str] = None


# ===========================================================================
# NAS: cadastro
# ===========================================================================
@router.get("/nas")
async def list_nas(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.radius_nas.find(
        {"company_id": cid},
        {"_id": 0, "shared_secret": 0},  # nunca expor secret
    ).sort("name", 1).to_list(200)
    return {"items": items, "count": len(items)}


@router.post("/nas")
async def create_or_update_nas(
    payload: NasIn,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)
    try:
        ipaddress.ip_address(payload.ip)
    except ValueError:
        raise HTTPException(400, "IP inválido")

    existing = await db.radius_nas.find_one({"company_id": cid, "ip": payload.ip}, {"_id": 0})
    now = _now().isoformat()
    if existing:
        await db.radius_nas.update_one(
            {"id": existing["id"]},
            {"$set": {
                "name": payload.name,
                "shared_secret": payload.shared_secret,
                "vendor": payload.vendor,
                "coa_port": payload.coa_port,
                "description": payload.description,
                "updated_at": now,
            }},
        )
        return {"ok": True, "id": existing["id"], "updated": True}
    new_id = f"nas-{uuid.uuid4().hex[:10]}"
    await db.radius_nas.insert_one({
        "id": new_id,
        "company_id": cid,
        "name": payload.name,
        "ip": payload.ip,
        "shared_secret": payload.shared_secret,
        "vendor": payload.vendor,
        "coa_port": payload.coa_port,
        "description": payload.description,
        "created_at": now,
        "updated_at": now,
        "last_seen_at": None,
    })
    return {"ok": True, "id": new_id, "created": True}


@router.delete("/nas/{nas_id}")
async def delete_nas(nas_id: str, user: dict = Depends(get_current_user)):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)
    r = await db.radius_nas.delete_one({"id": nas_id, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "NAS não encontrado")
    return {"ok": True, "deleted": True}


# ===========================================================================
# Test Connection — simula um Access-Request de um NAS específico,
# validando: shared_secret encoding, vendor dictionary, lookup de subscriber,
# montagem dos atributos de reply (Mikrotik/Cisco/Huawei).
# ===========================================================================
class NasTestIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = ""  # opcional — se vazio, usa do subscriber pra testar accept


@router.post("/nas/{nas_id}/test-connection")
async def nas_test_connection(
    nas_id: str,
    payload: NasTestIn,
    user: dict = Depends(get_current_user),
):
    """Simula um Access-Request usando o shared_secret + vendor do NAS.

    Pipeline:
      1. Codifica/decodifica o request via pyrad (valida secret + dictionary)
      2. Invoca a lógica interna de auth (mesma do endpoint público)
      3. Codifica a reply via pyrad (valida assinatura HMAC + dict do vendor)
      4. Retorna o pacote inteiro decodificado pra UI inspecionar

    Útil pra: validar shared_secret novo, conferir que policies estão sendo
    geradas corretamente pro vendor escolhido, debug de "Access-Reject"
    em produção sem precisar tocar no FreeRADIUS.
    """
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)

    nas = await db.radius_nas.find_one(
        {"id": nas_id, "company_id": cid}, {"_id": 0})
    if not nas:
        raise HTTPException(404, "NAS não encontrado")

    started = _now()
    diag: Dict[str, Any] = {
        "nas": {
            "id": nas["id"], "name": nas["name"], "ip": nas["ip"],
            "vendor": nas.get("vendor", "generic"),
            "coa_port": nas.get("coa_port", 3799),
        },
        "request": {"username": payload.username},
        "pyrad": {"available": False, "request_encoded": False,
                  "reply_encoded": False},
        "errors": [],
    }

    # Resolve subscriber pra preencher senha auto se gestor deixou em branco
    sub = await db.subscribers.find_one(
        {"pppoe_user": payload.username},
        {"_id": 0, "id": 1, "name": 1, "pppoe_pass": 1, "status": 1},
    )
    used_password = payload.password
    if not used_password and sub:
        used_password = sub.get("pppoe_pass") or ""
        diag["request"]["password_source"] = "subscriber"
    else:
        diag["request"]["password_source"] = "manual"

    # --- Etapa 1: encode/decode do Access-Request via pyrad ---
    try:
        from pyrad.client import Client
        import pyrad.packet as pkt
        diag["pyrad"]["available"] = True

        d = _load_radius_dict()
        if not d.attributes.get("User-Name"):
            diag["errors"].append("dict_load: dictionary vazio")

        c = Client(server=nas["ip"], authport=1812,
                   secret=nas["shared_secret"].encode("utf-8"), dict=d)
        req = c.CreateAuthPacket(code=pkt.AccessRequest)
        req["User-Name"] = payload.username
        # PAP password (RFC2865 §5.2 obfuscado com shared_secret + authenticator)
        req["User-Password"] = req.PwCrypt(used_password or "")
        req["NAS-IP-Address"] = nas["ip"]
        req["NAS-Identifier"] = nas["name"]
        req["Service-Type"] = 2  # Framed
        # Serializa: força o pyrad a assinar com o shared_secret
        raw = req.RequestPacket()
        diag["pyrad"]["request_encoded"] = True
        diag["pyrad"]["request_size_bytes"] = len(raw)
    except ImportError:
        diag["errors"].append("pyrad_not_installed")
    except Exception as e:
        diag["errors"].append(f"request_encode: {e}")

    # --- Etapa 2: invoca a lógica interna de auth ---
    sim_payload = AuthRequest(
        username=payload.username,
        password=used_password,
        nas_ip=nas["ip"],
        nas_identifier=nas["name"],
    )
    # Wrapper pra request.client.host (radius_auth lê isso pra log)
    class _FakeReq:
        client = type("C", (), {"host": "127.0.0.1"})()
    auth_result = await radius_auth(sim_payload, _FakeReq())  # type: ignore[arg-type]

    # --- Etapa 3: encode/decode da Reply (se accept) ---
    if (auth_result.get("result") == "accept" and diag["pyrad"]["available"]):
        try:
            import pyrad.packet as pkt
            from pyrad.client import Client
            d2 = _load_radius_dict()
            c2 = Client(server=nas["ip"], authport=1812,
                        secret=nas["shared_secret"].encode("utf-8"), dict=d2)
            r2 = c2.CreateAuthPacket(code=pkt.AccessRequest)
            r2["User-Name"] = payload.username
            r2["User-Password"] = r2.PwCrypt(used_password or "")
            reply = r2.CreateReply()
            reply.code = pkt.AccessAccept

            applied_attrs: Dict[str, Any] = {}
            skipped_attrs: List[str] = []
            for k, v in (auth_result.get("attributes") or {}).items():
                try:
                    if isinstance(v, list):
                        for vv in v:
                            reply.AddAttribute(k, vv)
                    else:
                        reply.AddAttribute(k, v)
                    applied_attrs[k] = v
                except Exception:
                    # Atributo do vendor não está no dict mínimo —
                    # registra como skipped (não falha o teste).
                    skipped_attrs.append(k)
            replyraw = reply.ReplyPacket()
            diag["pyrad"]["reply_encoded"] = True
            diag["pyrad"]["reply_size_bytes"] = len(replyraw)
            diag["pyrad"]["attrs_applied"] = list(applied_attrs.keys())
            diag["pyrad"]["attrs_skipped"] = skipped_attrs
        except Exception as e:
            diag["errors"].append(f"reply_encode: {e}")

    elapsed_ms = int((_now() - started).total_seconds() * 1000)

    return {
        "ok": auth_result.get("result") == "accept",
        "elapsed_ms": elapsed_ms,
        "result": auth_result.get("result"),  # accept | reject
        "reason": auth_result.get("reason"),
        "subscriber": {
            "id": (sub or {}).get("id"),
            "name": (sub or {}).get("name"),
            "status": (sub or {}).get("status"),
        } if sub else None,
        "radius_state": auth_result.get("radius_state"),
        "attributes": auth_result.get("attributes") or {},
        "diagnostics": diag,
    }


async def _resolve_nas_by_ip(nas_ip: str) -> Optional[dict]:
    """Best-effort: encontra NAS pelo IP de origem do request RADIUS."""
    if not nas_ip:
        return None
    return await db.radius_nas.find_one({"ip": nas_ip}, {"_id": 0})


# ===========================================================================
# AUTH endpoint (FreeRADIUS → nosso backend)
# ===========================================================================
@router.post("/auth")
async def radius_auth(payload: AuthRequest, request: Request):
    """Atende Access-Request do FreeRADIUS.

    Retorno (consumido pelo rlm_rest):
      - 200 com { result: "accept", attributes: {...} } → Access-Accept
      - 200 com { result: "reject", reason: "..." }    → Access-Reject

    O FreeRADIUS é configurado pra aplicar as `attributes` retornadas
    (ex: Mikrotik-Rate-Limit, Framed-IP-Address).
    """
    nas = await _resolve_nas_by_ip(payload.nas_ip or "")
    cid = nas.get("company_id") if nas else DEMO_COMPANY_ID
    src_ip = request.client.host if request.client else "?"

    log_base = {
        "id": f"radlog-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "auth",
        "username": payload.username,
        "nas_ip": payload.nas_ip,
        "nas_id": nas.get("id") if nas else None,
        "calling_station_id": payload.calling_station_id,
        "src_ip": src_ip,
        "at": _now().isoformat(),
    }

    # 1. Resolve subscriber pelo pppoe_user
    sub = await db.subscribers.find_one(
        {"pppoe_user": payload.username},
        {"_id": 0, "id": 1, "name": 1, "pppoe_user": 1, "pppoe_pass": 1,
         "status": 1, "company_id": 1, "plan": 1, "framed_ip": 1,
         "speed_mbps": 1, "speed_down_kbps": 1, "speed_up_kbps": 1},
    )
    if not sub:
        await db.radius_logs.insert_one(
            {**log_base, "result": "reject", "reason": "user_not_found"})
        return {"result": "reject", "reason": "Usuário não cadastrado"}

    # 2. Senha
    if (sub.get("pppoe_pass") or "") != payload.password:
        await db.radius_logs.insert_one(
            {**log_base, "result": "reject", "reason": "bad_password"})
        return {"result": "reject", "reason": "Senha incorreta"}

    # 3. Status do assinante (compat: legados pre-contratos)
    status = (sub.get("status") or "").upper()
    if status in ("CANCELADO", "BLOQUEADO", "INATIVO"):
        await db.radius_logs.insert_one({
            **log_base, "result": "reject",
            "reason": f"subscriber_status={status}",
        })
        return {
            "result": "reject",
            "reason": f"Assinante {status.lower()}",
        }

    # 3b. Estado RADIUS do CONTRATO (fonte de verdade pro aging)
    contract = await db.contracts.find_one(
        {"subscriber_id": sub.get("id"),
         "status": {"$ne": "cancelado"}},
        {"_id": 0, "id": 1, "radius_state": 1, "radius_state_reason": 1,
         "plan_id": 1},
    )
    radius_state = (contract or {}).get("radius_state") or "ATIVO"

    if radius_state in ("SUSPENSO", "CANCELADO"):
        await db.radius_logs.insert_one({
            **log_base, "result": "reject",
            "reason": f"radius_state={radius_state}",
            "contract_id": (contract or {}).get("id"),
        })
        return {
            "result": "reject",
            "reason": (contract or {}).get("radius_state_reason")
                or f"Contrato {radius_state.lower()}",
        }

    # 4. Resolve plano pelo contrato (preferido) ou snapshot do subscriber
    plan_doc = None
    if contract and contract.get("plan_id"):
        plan_doc = await db.plans.find_one(
            {"id": contract["plan_id"], "company_id": sub.get("company_id")},
            {"_id": 0})
    plan_doc = plan_doc or sub.get("plan") or {}

    def _kbps(plan_d, key_mbps, key_kbps, fallback_mbps):
        """Resolve velocidade em Kbps. Prefere Kbps (precisão Atlaz)."""
        v_kbps = plan_d.get(key_kbps)
        if v_kbps:
            return int(v_kbps)
        v_mbps = plan_d.get(key_mbps)
        if v_mbps:
            return int(float(v_mbps) * 1024)
        return int(fallback_mbps * 1024)

    speed_down = _kbps(plan_doc, "speed_down_mbps", "speed_down_kbps",
                       sub.get("speed_mbps") or 100)
    speed_up = _kbps(plan_doc, "speed_up_mbps", "speed_up_kbps",
                     (sub.get("speed_mbps") or 100) / 2)

    # 4b. Aplica REDUZIDO: troca velocidade pela do "perfil reduzido" do plano
    profile_label = (plan_doc.get("name") or "default").lower()
    if radius_state == "REDUZIDO":
        # Prefere kbps direto se existir, senão converte de mbps
        red_down = (plan_doc.get("reduced_speed_down_kbps")
                     or (plan_doc.get("speed_reduced_down_kbps"))
                     or int((plan_doc.get("speed_reduced_down_mbps") or 0.5)
                            * 1024))
        red_up = (plan_doc.get("reduced_speed_up_kbps")
                   or (plan_doc.get("speed_reduced_up_kbps"))
                   or int((plan_doc.get("speed_reduced_up_mbps") or 0.25)
                          * 1024))
        speed_down = red_down
        speed_up = red_up
        profile_label = f"{profile_label}_reduzido"

    # 4c. Franquia mensal — se atingiu, força velocidade reduzida de quota
    quota = plan_doc.get("data_quota") or {}
    # NOTE: a aferição do consumo é feita externamente (worker que soma bytes
    # de radius_sessions do mês). Aqui só aplica o cap se subscriber tem
    # `quota_exceeded=True` marcado.
    if quota.get("enabled") and sub.get("quota_exceeded"):
        speed_down = quota.get("reduced_down_kbps") or 2048
        speed_up = quota.get("reduced_up_kbps") or 2048
        profile_label = f"{profile_label}_quota"

    attrs: Dict[str, Any] = {
        "Session-Timeout": 86400,
        "Acct-Interim-Interval": 300,
    }
    vendor = (nas or {}).get("vendor", "mikrotik")

    if vendor == "mikrotik":
        # RouterOS — usa Mikrotik-Rate-Limit (rx/tx em kbps)
        attrs["Mikrotik-Rate-Limit"] = f"{speed_up}k/{speed_down}k"
        attrs["Mikrotik-Group"] = profile_label
        if radius_state == "WALLED_GARDEN":
            attrs["Mikrotik-Address-List"] = "walled-garden"
        else:
            mtk_cfg = plan_doc.get("mikrotik") or {}
            if mtk_cfg.get("address_list"):
                attrs["Mikrotik-Address-List"] = mtk_cfg["address_list"]
        mtk_cfg = plan_doc.get("mikrotik") or {}
        if mtk_cfg.get("ip_pool"):
            attrs["Mikrotik-Host-IP"] = mtk_cfg["ip_pool"]
        if mtk_cfg.get("delegated_ipv6_pool"):
            attrs["Mikrotik-Delegated-IPv6-Pool"] = mtk_cfg["delegated_ipv6_pool"]
        if mtk_cfg.get("framed_ipv6_pool"):
            attrs["Framed-IPv6-Pool"] = mtk_cfg["framed_ipv6_pool"]

    elif vendor in ("cisco_asr", "cisco"):
        # Cisco ASR 1000/9000 — ISG via Cisco-AVPair.
        # ASR não entende Mikrotik-*; aplica QoS service-policy via Cisco-AVPair.
        # Pode-se usar 2 modos:
        #   (a) Service-name (recomendado): define policy-map já configurado
        #       no ASR (BANDWIDTH_30M etc) — bem mais leve no controlplane.
        #   (b) Inline QoS shape: aplica shape direto via parent-policy.
        attrs["Service-Type"] = "Framed-User"
        attrs["Framed-Protocol"] = "PPP"

        mtk_cfg = plan_doc.get("mikrotik") or {}
        # 1. Service-name vindo do plano (preferido em produção). Cai pra
        #    `BW_<down>M_<up>M_<estado>` se não tiver service-name configurado.
        plan_service_name = (
            (plan_doc.get("cisco") or {}).get("service_name")
            or mtk_cfg.get("route_map")  # reusa campo legado
            or f"BW_{speed_down // 1024}M_{speed_up // 1024}M"
        )
        if radius_state == "REDUZIDO":
            plan_service_name = f"{plan_service_name}_REDUZIDO"
        elif radius_state == "WALLED_GARDEN":
            plan_service_name = "WALLED_GARDEN"

        # AVPair = lista de strings ("multi-valued attribute" em RADIUS)
        cisco_av: list = []
        # Ativa o service correspondente (assume policy-map já existir no ASR)
        cisco_av.append(f"subscriber:service-name={plan_service_name}")
        cisco_av.append("subscriber:command=account-logon")
        # Shape inline como fallback caso o service-name não exista no ASR
        cisco_av.append(f"ip:sub-qos-policy-in=PMAP_IN_{speed_up}K")
        cisco_av.append(f"ip:sub-qos-policy-out=PMAP_OUT_{speed_down}K")
        # WALLED_GARDEN: aplica ACL stub que redireciona pra portal
        if radius_state == "WALLED_GARDEN":
            cisco_av.append("ip:sub-acl-in=WALLED_GARDEN_IN")
            cisco_av.append("ip:sub-acl-out=WALLED_GARDEN_OUT")
        attrs["Cisco-AVPair"] = cisco_av

        # IP Pool (Framed-Pool é padrão RFC, ASR entende)
        if mtk_cfg.get("ip_pool"):
            attrs["Framed-Pool"] = mtk_cfg["ip_pool"]
        if mtk_cfg.get("framed_ipv6_pool"):
            attrs["Framed-IPv6-Pool"] = mtk_cfg["framed_ipv6_pool"]
        if mtk_cfg.get("delegated_ipv6_pool"):
            attrs["Delegated-IPv6-Prefix-Pool"] = mtk_cfg["delegated_ipv6_pool"]

    elif vendor == "huawei":
        # Huawei NE40/ME60 — Huawei-Input-Burst-Size + Huawei-Input-Average-Rate
        attrs["Huawei-Input-Average-Rate"] = speed_up * 1000  # bits/s
        attrs["Huawei-Output-Average-Rate"] = speed_down * 1000
        if radius_state == "WALLED_GARDEN":
            attrs["Huawei-Domain-Name"] = "walled-garden"
        else:
            mtk_cfg = plan_doc.get("mikrotik") or {}
            if mtk_cfg.get("address_list"):
                attrs["Huawei-Domain-Name"] = mtk_cfg["address_list"]

    else:
        # Genérico RFC2865 — apenas atributos padrão (sem QoS vendor)
        # Funciona pra autenticar mas SEM controle de banda.
        if sub.get("framed_ip"):
            attrs["Framed-IP-Address"] = sub["framed_ip"]

    if sub.get("framed_ip") and "Framed-IP-Address" not in attrs:
        attrs["Framed-IP-Address"] = sub["framed_ip"]

    await db.radius_logs.insert_one({
        **log_base, "result": "accept",
        "subscriber_id": sub.get("id"),
        "contract_id": (contract or {}).get("id"),
        "radius_state": radius_state,
        "speed_down_kbps": speed_down,
        "speed_up_kbps": speed_up,
        "profile": profile_label,
    })
    if nas:
        await db.radius_nas.update_one(
            {"id": nas["id"]},
            {"$set": {"last_seen_at": _now().isoformat()}},
        )
    return {
        "result": "accept",
        "subscriber_id": sub.get("id"),
        "subscriber_name": sub.get("name"),
        "contract_id": (contract or {}).get("id"),
        "radius_state": radius_state,
        "attributes": attrs,
    }


# ===========================================================================
# ACCOUNTING endpoint (Start / Stop / Interim-Update)
# ===========================================================================
@router.post("/accounting")
async def radius_accounting(payload: AcctRequest, request: Request):
    """Atende Accounting-Request do FreeRADIUS.

    Atualiza coleção `radius_sessions` (sessão única por Acct-Session-Id).
      - Start          → cria sessão (status=active)
      - Interim-Update → atualiza bytes/uptime
      - Stop           → fecha sessão (status=closed)
    """
    if not payload.acct_session_id:
        raise HTTPException(400, "acct_session_id obrigatório")

    nas = await _resolve_nas_by_ip(payload.nas_ip or "")
    cid = nas.get("company_id") if nas else DEMO_COMPANY_ID
    sid = payload.acct_session_id

    # Bytes: combina gigawords (cada 1 = 2^32 bytes) com octets
    bytes_in = (payload.acct_input_gigawords << 32) + payload.acct_input_octets
    bytes_out = (payload.acct_output_gigawords << 32) + payload.acct_output_octets

    sub = None
    if payload.username:
        sub = await db.subscribers.find_one(
            {"pppoe_user": payload.username},
            {"_id": 0, "id": 1, "name": 1, "company_id": 1},
        )

    now = _now()
    now_iso = now.isoformat()
    status_type = payload.acct_status_type or ""

    base_doc = {
        "acct_session_id": sid,
        "company_id": (sub or {}).get("company_id") or cid,
        "subscriber_id": (sub or {}).get("id"),
        "subscriber_name": (sub or {}).get("name"),
        "username": payload.username,
        "nas_ip": payload.nas_ip,
        "nas_id": nas.get("id") if nas else None,
        "framed_ip": payload.framed_ip,
        "calling_station_id": payload.calling_station_id,
        "last_acct_at": now_iso,
        "last_acct_type": status_type,
    }

    if status_type == "Start":
        await db.radius_sessions.update_one(
            {"acct_session_id": sid},
            {"$set": {
                **base_doc,
                "status": "active",
                "started_at": now_iso,
                "bytes_in": 0,
                "bytes_out": 0,
                "session_time": 0,
            }, "$setOnInsert": {
                "id": f"sess-{uuid.uuid4().hex[:10]}",
                "created_at": now_iso,
            }},
            upsert=True,
        )
    elif status_type == "Stop":
        await db.radius_sessions.update_one(
            {"acct_session_id": sid},
            {"$set": {
                **base_doc,
                "status": "closed",
                "ended_at": now_iso,
                "bytes_in": bytes_in,
                "bytes_out": bytes_out,
                "session_time": payload.acct_session_time,
                "terminate_cause": payload.acct_terminate_cause,
            }, "$setOnInsert": {
                "id": f"sess-{uuid.uuid4().hex[:10]}",
                "started_at": now_iso,
                "created_at": now_iso,
            }},
            upsert=True,
        )
    else:  # Interim-Update + outros
        await db.radius_sessions.update_one(
            {"acct_session_id": sid},
            {"$set": {
                **base_doc,
                "bytes_in": bytes_in,
                "bytes_out": bytes_out,
                "session_time": payload.acct_session_time,
            }, "$setOnInsert": {
                "id": f"sess-{uuid.uuid4().hex[:10]}",
                "status": "active",
                "started_at": now_iso,
                "created_at": now_iso,
            }},
            upsert=True,
        )

    if nas:
        await db.radius_nas.update_one(
            {"id": nas["id"]},
            {"$set": {"last_seen_at": now_iso}},
        )
    return {"result": "ok"}


# ===========================================================================
# Sessions: list + history + dashboard
# ===========================================================================
def _human_bytes(n: int) -> str:
    if not n:
        return "0 B"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


@router.get("/sessions/active")
async def list_active_sessions(
    search: str = "",
    nas_id: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid, "status": "active"}
    if search:
        q["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"subscriber_name": {"$regex": search, "$options": "i"}},
            {"framed_ip": {"$regex": search, "$options": "i"}},
            {"calling_station_id": {"$regex": search, "$options": "i"}},
        ]
    if nas_id:
        q["nas_id"] = nas_id

    items = await db.radius_sessions.find(
        q, {"_id": 0}).sort("started_at", -1).limit(limit).to_list(limit)
    # Enriquece com human-readable
    for s in items:
        s["bytes_in_human"] = _human_bytes(s.get("bytes_in") or 0)
        s["bytes_out_human"] = _human_bytes(s.get("bytes_out") or 0)
        if s.get("started_at"):
            try:
                started = datetime.fromisoformat(s["started_at"])
                up = (_now() - started).total_seconds()
                s["uptime_seconds"] = int(up)
            except (ValueError, TypeError):
                s["uptime_seconds"] = s.get("session_time") or 0
    return {"items": items, "count": len(items)}


@router.get("/sessions/history")
async def list_history_sessions(
    hours: int = Query(default=24, ge=1, le=720),
    search: str = "",
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    cutoff = (_now() - timedelta(hours=hours)).isoformat()
    q: Dict[str, Any] = {
        "company_id": cid,
        "status": "closed",
        "ended_at": {"$gte": cutoff},
    }
    if search:
        q["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"subscriber_name": {"$regex": search, "$options": "i"}},
        ]
    items = await db.radius_sessions.find(
        q, {"_id": 0}).sort("ended_at", -1).limit(500).to_list(500)
    for s in items:
        s["bytes_in_human"] = _human_bytes(s.get("bytes_in") or 0)
        s["bytes_out_human"] = _human_bytes(s.get("bytes_out") or 0)
    return {"items": items, "count": len(items)}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = today_start.isoformat()
    last_24h = (_now() - timedelta(hours=24)).isoformat()

    active = await db.radius_sessions.count_documents(
        {"company_id": cid, "status": "active"})
    closed_today = await db.radius_sessions.count_documents(
        {"company_id": cid, "status": "closed", "ended_at": {"$gte": today_iso}})

    auth_24h = await db.radius_logs.count_documents(
        {"company_id": cid, "type": "auth", "at": {"$gte": last_24h}})
    reject_24h = await db.radius_logs.count_documents({
        "company_id": cid, "type": "auth",
        "result": "reject", "at": {"$gte": last_24h},
    })

    # Top rejeições por motivo
    pipeline = [
        {"$match": {"company_id": cid, "type": "auth", "result": "reject",
                     "at": {"$gte": last_24h}}},
        {"$group": {"_id": "$reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_reject = []
    async for r in db.radius_logs.aggregate(pipeline):
        top_reject.append({"reason": r["_id"], "count": r["count"]})

    nas_count = await db.radius_nas.count_documents({"company_id": cid})
    return {
        "active_sessions": active,
        "closed_today": closed_today,
        "auth_24h": auth_24h,
        "reject_24h": reject_24h,
        "accept_rate": (round((auth_24h - reject_24h) * 100 / auth_24h, 1)
                        if auth_24h > 0 else None),
        "top_reject_reasons": top_reject,
        "nas_count": nas_count,
    }


# ===========================================================================
# CoA Disconnect (corta sessão imediatamente)
# ===========================================================================
@router.post("/sessions/{sid}/disconnect")
async def disconnect_session(
    sid: str,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)
    sess = await db.radius_sessions.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0})
    if not sess:
        raise HTTPException(404, "Sessão não encontrada")
    if sess.get("status") != "active":
        raise HTTPException(400, "Sessão não está ativa")

    nas = await db.radius_nas.find_one(
        {"id": sess.get("nas_id"), "company_id": cid}, {"_id": 0})
    if not nas:
        raise HTTPException(400, "NAS da sessão não está cadastrado")

    ok = await _send_coa_disconnect(nas, sess)

    # Registra log de CoA independente do resultado
    await db.radius_logs.insert_one({
        "id": f"radlog-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "coa_disconnect",
        "session_id": sid,
        "acct_session_id": sess.get("acct_session_id"),
        "username": sess.get("username"),
        "nas_ip": nas.get("ip"),
        "nas_id": nas.get("id"),
        "result": "sent" if ok else "failed",
        "actor_id": user.get("id"),
        "actor_name": user.get("name") or user.get("email"),
        "at": _now().isoformat(),
    })
    if ok:
        # Marca sessão como pending_disconnect — fica "active" até NAS confirmar
        # via Acct-Stop. Worker pode varrer e forçar close após 60s.
        await db.radius_sessions.update_one(
            {"id": sid},
            {"$set": {"pending_disconnect_at": _now().isoformat(),
                       "disconnected_by": user.get("name") or user.get("email")}},
        )
        return {"ok": True, "message": "CoA Disconnect enviado para o NAS"}
    return {"ok": False, "message": "Falha ao enviar CoA para o NAS"}


async def _send_coa_disconnect(nas: dict, session: dict) -> bool:
    """Envia pacote CoA Disconnect via UDP usando pyrad (não-bloqueante).

    Roda em executor pra não travar o event loop com o socket UDP.
    Best-effort: retorna False se falhar (loga erro).
    """
    try:
        from pyrad.client import Client
        from pyrad.dictionary import Dictionary
        import pyrad.packet as pkt
    except ImportError:
        logger.error("[radius.coa] pyrad não instalado")
        return False

    def _send_sync() -> bool:
        try:
            d = _load_radius_dict()

            c = Client(server=nas["ip"], authport=nas.get("coa_port", 3799),
                       coaport=nas.get("coa_port", 3799),
                       secret=nas["shared_secret"].encode("utf-8"),
                       dict=d)
            c.timeout = 4
            c.retries = 2
            req = c.CreateCoAPacket(code=pkt.DisconnectRequest)
            if session.get("username"):
                req["User-Name"] = session["username"]
            if session.get("acct_session_id"):
                req["Acct-Session-Id"] = session["acct_session_id"]
            if session.get("framed_ip"):
                req["Framed-IP-Address"] = session["framed_ip"]
            if session.get("calling_station_id"):
                req["Calling-Station-Id"] = session["calling_station_id"]
            # ASR/ISG: pra ter certeza de derrubar, manda também o comando
            # via Cisco-AVPair (alguns deployments exigem isso).
            vendor = (nas.get("vendor") or "").lower()
            if vendor in ("cisco_asr", "cisco"):
                try:
                    req.AddAttribute("Cisco-AVPair",
                                      "subscriber:command=account-logoff")
                except Exception:
                    # Se o dictionary não carregou Cisco, ignora — o
                    # Disconnect-Request padrão RFC já é suficiente.
                    pass
            reply = c.SendPacket(req)
            return reply.code == pkt.DisconnectACK
        except (socket.timeout, OSError) as e:
            logger.warning("[radius.coa] timeout/socket err to %s:%s — %s",
                           nas.get("ip"), nas.get("coa_port"), e)
            return False
        except Exception as e:
            logger.exception("[radius.coa] err: %s", e)
            return False

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_sync)


# Dictionary mínimo RADIUS (atributos RFC2865 + Mikrotik) — embedded
_RAD_DICT_MINIMAL = """
ATTRIBUTE       User-Name       1       string
ATTRIBUTE       User-Password   2       string
ATTRIBUTE       NAS-IP-Address  4       ipaddr
ATTRIBUTE       NAS-Port        5       integer
ATTRIBUTE       Service-Type    6       integer
ATTRIBUTE       Framed-Protocol 7       integer
VALUE           Service-Type    Login-User              1
VALUE           Service-Type    Framed-User             2
VALUE           Service-Type    Callback-Login-User     3
VALUE           Service-Type    Callback-Framed-User    4
VALUE           Service-Type    Outbound-User           5
VALUE           Service-Type    Administrative-User     6
VALUE           Service-Type    NAS-Prompt-User         7
VALUE           Service-Type    Authenticate-Only       8
VALUE           Framed-Protocol PPP                     1
VALUE           Framed-Protocol SLIP                    2
VALUE           Framed-Protocol ARAP                    3
ATTRIBUTE       Framed-IP-Address       8       ipaddr
ATTRIBUTE       Reply-Message   18      string
ATTRIBUTE       Session-Timeout 27      integer
ATTRIBUTE       Called-Station-Id       30      string
ATTRIBUTE       Calling-Station-Id      31      string
ATTRIBUTE       NAS-Identifier  32      string
ATTRIBUTE       Acct-Status-Type        40      integer
ATTRIBUTE       Acct-Input-Octets       42      integer
ATTRIBUTE       Acct-Output-Octets      43      integer
ATTRIBUTE       Acct-Session-Id 44      string
ATTRIBUTE       Acct-Session-Time       46      integer
ATTRIBUTE       Acct-Input-Gigawords    52      integer
ATTRIBUTE       Acct-Output-Gigawords   53      integer
ATTRIBUTE       Acct-Interim-Interval   85      integer
ATTRIBUTE       NAS-Port-Type   61      integer
ATTRIBUTE       Acct-Terminate-Cause    49      integer

VENDOR          Mikrotik        14988
BEGIN-VENDOR    Mikrotik
ATTRIBUTE       Mikrotik-Recv-Limit     1       integer
ATTRIBUTE       Mikrotik-Xmit-Limit     2       integer
ATTRIBUTE       Mikrotik-Group  3       string
ATTRIBUTE       Mikrotik-Rate-Limit     8       string
END-VENDOR      Mikrotik

VENDOR          Cisco   9
BEGIN-VENDOR    Cisco
ATTRIBUTE       Cisco-AVPair    1       string
ATTRIBUTE       Cisco-NAS-Port  2       string
ATTRIBUTE       Cisco-Account-Info      250     string
ATTRIBUTE       Cisco-Service-Info      251     string
ATTRIBUTE       Cisco-Command-Code      252     string
END-VENDOR      Cisco

VENDOR          Huawei  2011
BEGIN-VENDOR    Huawei
ATTRIBUTE       Huawei-Input-Burst-Size 1       integer
ATTRIBUTE       Huawei-Input-Average-Rate       2       integer
ATTRIBUTE       Huawei-Output-Average-Rate      3       integer
ATTRIBUTE       Huawei-Domain-Name      60      string
END-VENDOR      Huawei
"""


def _load_radius_dict():
    """Carrega o dictionary RADIUS mínimo (compat com pyrad 2.5.x).

    Em pyrad 2.5 o método correto é `ReadDictionary(file_like)`.
    Versões antigas (1.x) tinham `ReadString` que NÃO existe em 2.5.4.
    """
    import io
    from pyrad.dictionary import Dictionary
    d = Dictionary()
    try:
        d.ReadDictionary(io.StringIO(_RAD_DICT_MINIMAL))
    except Exception as e:  # pragma: no cover
        logger.warning("[radius.dict] load fail: %s", e)
    return d



# ===========================================================================
# Logs (auditoria)
# ===========================================================================
@router.get("/logs")
async def list_logs(
    type_filter: str = Query(default="all", alias="type"),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if type_filter != "all":
        q["type"] = type_filter
    items = await db.radius_logs.find(
        q, {"_id": 0}).sort("at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}
