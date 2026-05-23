"""wifi.py — Troca de Wi-Fi self-service (atendente UI + WhatsApp self-service).

Premium feature: só assinantes em planos com `premium_features` contendo
`wifi_self_service` podem trocar. Apenas ONUs gerenciadas pelo SmartOLT
(`subscriber.smartolt_onu_id` preenchido) são elegíveis.

Endpoints:
  - GET    /api/wifi/subscriber/{sid}/status         — status ONU + flags premium
  - POST   /api/wifi/subscriber/{sid}/link-onu       — vincula manualmente
  - POST   /api/wifi/subscriber/{sid}/auto-match     — tenta auto-match por PPPoE
  - DELETE /api/wifi/subscriber/{sid}/link-onu       — desvincula
  - POST   /api/wifi/subscriber/{sid}/change         — troca SSID/senha (gated)
  - GET    /api/wifi/subscriber/{sid}/logs           — histórico de mudanças
  - POST   /api/wifi/subscriber/{sid}/reboot-onu     — proxy pro reboot SmartOLT

Salvaguardas:
  - Hard limit: 1 troca/24h (atendente humano pode forçar via flag)
  - Notificação ao gestor a cada troca (via `notifications` collection)
  - Auditoria total em `wifi_change_logs` (sem persistir plaintext de senha)
  - ONU offline => 409
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db
from routes.smartolt import _get_config, _http_post, _norm

logger = logging.getLogger("ponto.wifi")
router = APIRouter(prefix="/api/wifi", tags=["wifi"])

# Featue flag canónica reconhecida pelos plans premium.
FEATURE_WIFI = "wifi_self_service"

# Rate limit: 1 troca/24h via WhatsApp self-service; atendente pode forçar.
RATE_LIMIT_WINDOW_HOURS = 24
RATE_LIMIT_MAX = 1

# Validações SSID/senha (WPA2 PSK exige 8-63 chars).
SSID_RE = re.compile(r"^[\x20-\x7E]{1,32}$")  # ASCII printable, 1-32 chars
PASSWORD_MIN = 8
PASSWORD_MAX = 63

# Statuses SmartOLT que consideramos "tecnicamente capaz de receber comando":
ONU_STATUS_ONLINE = {"online", "Online", "ON"}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class LinkOnuIn(BaseModel):
    smartolt_onu_id: str = Field(..., min_length=2, max_length=200)


class WifiChangeIn(BaseModel):
    ssid_24: Optional[str] = Field(default=None, max_length=32)
    password_24: Optional[str] = Field(default=None,
                                       min_length=PASSWORD_MIN,
                                       max_length=PASSWORD_MAX)
    ssid_5: Optional[str] = Field(default=None, max_length=32)
    password_5: Optional[str] = Field(default=None,
                                      min_length=PASSWORD_MIN,
                                      max_length=PASSWORD_MAX)
    # Quando True, aplica os mesmos valores nos dois rádios; o input pode
    # vir só com ssid_24/password_24 setado.
    apply_to_both: bool = False
    # Atendente humano pode forçar uma 2ª troca no mesmo dia.
    force: bool = False
    # Override do source quando chamado pelo Álvaro IA (WhatsApp).
    source: str = "atendente"  # atendente | whatsapp_alvaro | portal_cliente
    # Override do wifi_port no SmartOLT — varia por modelo de ONU.
    # Default razoável pra residencial GPON: 2.4G=wifi_0/1, 5G=wifi_0/5.
    # Quando a config global tiver port-mapping por vendor, isso fica no
    # smartolt_config.wifi_port_map[vendor].
    wifi_port_24: str = "wifi_0/1"
    wifi_port_5: str = "wifi_0/5"
    # Authentication mode pro WPA. WPA2 é o default seguro/padrão.
    authentication_mode: str = "WPA2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    if is_super_admin(user):
        return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID
    return user.get("company_id") or DEMO_COMPANY_ID


async def _get_subscriber(sid: str, cid: str) -> dict:
    sub = await db.subscribers.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    return sub


async def _plan_has_feature(plan_id: Optional[str], cid: str,
                             feature: str) -> bool:
    if not plan_id:
        return False
    plan = await db.plans.find_one(
        {"company_id": cid, "id": plan_id},
        {"_id": 0, "premium_features": 1},
    )
    if not plan:
        return False
    return feature in (plan.get("premium_features") or [])


async def _onu_by_id(cid: str, onu_id: str) -> Optional[dict]:
    return await db.smartolt_onus.find_one(
        {"company_id": cid, "unique_external_id": onu_id}, {"_id": 0})


async def _summarize_onu(onu: dict) -> Dict[str, Any]:
    """Resumo compacto pro card do cliente (status, sinal, modelo)."""
    if not onu:
        return {}
    rx = onu.get("signal_1490") or onu.get("signal_1310")
    try:
        rx_f = float(rx) if rx is not None else None
    except (TypeError, ValueError):
        rx_f = None
    return {
        "external_id": onu.get("unique_external_id"),
        "name": onu.get("name"),
        "sn": onu.get("sn"),
        "model": onu.get("onu_type_name"),
        "olt": onu.get("olt_name"),
        "status": onu.get("status"),
        "is_online": onu.get("status") in ONU_STATUS_ONLINE,
        "rx_dbm": rx_f,
        "rx_text": onu.get("signal_text"),
        "last_status_change": onu.get("last_status_change"),
        "administrative_status": onu.get("administrative_status"),
    }


async def _recent_changes_count(sid: str, cid: str,
                                window_hours: int = RATE_LIMIT_WINDOW_HOURS,
                                ) -> int:
    """Conta TENTATIVAS (success ou falha) na janela. Considera só
    source != atendente — atendente humano sempre pode forçar.

    Contar falhas também previne martelagem: cliente abusivo que tenta
    50× rapidinho não consegue bypassar via "mas todas falharam" se o
    SmartOLT real estiver lento/intermitente.
    """
    since = (datetime.now(timezone.utc)
             - timedelta(hours=window_hours)).isoformat()
    return await db.wifi_change_logs.count_documents({
        "company_id": cid,
        "subscriber_id": sid,
        "source": {"$ne": "atendente"},
        "ts": {"$gte": since},
    })


async def _log_change(cid: str, sid: str, sub: dict, payload: WifiChangeIn,
                     actor: dict, before: Dict[str, str],
                     after: Dict[str, str],
                     success: bool, error_reason: Optional[str] = None,
                     tr069_ms: Optional[int] = None) -> None:
    log = {
        "id": f"wfl-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "subscriber_id": sid,
        "subscriber_name": sub.get("name"),
        "smartolt_onu_id": sub.get("smartolt_onu_id"),
        "source": payload.source,
        "actor_email": actor.get("email"),
        "actor_name": actor.get("name"),
        "ssid_before": before,  # {"24":..,"5":..}
        "ssid_after": after,
        "password_changed": bool(payload.password_24 or payload.password_5),
        "apply_to_both": payload.apply_to_both,
        "force": payload.force,
        "tr069_response_time_ms": tr069_ms,
        "success": success,
        "error_reason": error_reason,
        "ts": now_iso(),
    }
    try:
        await db.wifi_change_logs.insert_one(log)
    except Exception as e:
        logger.warning("[wifi] log fail: %s", e)
    # Notification pro gestor (não bloqueia em caso de erro)
    try:
        await db.notifications.insert_one({
            "id": f"ntf-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "type": "wifi_change",
            "severity": "info" if success else "warning",
            "title": (
                f"Wi-Fi trocado · {sub.get('name')}" if success
                else f"Falha ao trocar Wi-Fi · {sub.get('name')}"
            ),
            "body": (
                f"Source: {payload.source} · "
                f"by {actor.get('email') or 'system'} · "
                f"{'forced' if payload.force else 'normal'}"
            ),
            "subscriber_id": sid,
            "ts": now_iso(),
            "read": False,
        })
    except Exception as e:
        logger.warning("[wifi] notif fail: %s", e)


def _validate_ssid(ssid: Optional[str]) -> None:
    if ssid is None:
        return
    if not ssid.strip():
        raise HTTPException(400, "SSID não pode ser vazio.")
    if not SSID_RE.match(ssid):
        raise HTTPException(
            400, "SSID inválido: use apenas caracteres imprimíveis ASCII "
                 "(1-32 chars, sem emoji nem acento).")


async def _smartolt_form_post(cfg, path: str,
                              form: Dict[str, str]) -> Dict[str, Any]:
    """POST form-data ao SmartOLT (endpoints set_wifi_port_* usam form, não JSON).

    Reproduz a mesma checagem de rate-limit/circuit-breaker do `_http_post`
    de smartolt.py, mas envia form ao invés de JSON.
    """
    from routes.smartolt import (
        _is_rate_limited, _mark_rate_limited, _base_url,
    )
    if cfg.company_id:
        rl = await _is_rate_limited(cfg.company_id)
        if rl:
            raise HTTPException(
                429, f"SmartOLT em pausa por rate-limit até {rl}.")
    url = f"{_base_url(cfg)}{path}"
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.post(url, headers={"X-Token": cfg.api_key},
                                data=form)
        if r.status_code == 403:
            if cfg.company_id:
                await _mark_rate_limited(cfg.company_id, 3600)
            raise HTTPException(429, "SmartOLT 403 — sync pausado por 1h.")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Endpoints — vinculação ONU↔Subscriber
# ---------------------------------------------------------------------------
@router.get("/subscriber/{sid}/status")
async def subscriber_wifi_status(sid: str,
                                  user: dict = Depends(get_current_user)):
    """Status agregado pra o card do cliente.

    Retorna:
      - subscriber.smartolt_onu_id (e summary da ONU se vinculada)
      - plan premium features (sabemos se cliente é "premium")
      - rate limit (trocas nas últimas 24h)
      - estado computado: "ready" / "premium_required" / "no_onu" / "onu_offline"
    """
    cid = _cid(user)
    sub = await _get_subscriber(sid, cid)
    onu_id = sub.get("smartolt_onu_id")
    onu_summary = {}
    if onu_id:
        onu = await _onu_by_id(cid, onu_id)
        if onu:
            onu_summary = await _summarize_onu(onu)
    plan_premium = await _plan_has_feature(sub.get("plan_id"), cid, FEATURE_WIFI)
    recent = await _recent_changes_count(sid, cid)
    # Computa estado
    if not onu_id or not onu_summary:
        state = "no_onu"
    elif not plan_premium:
        state = "premium_required"
    elif not onu_summary.get("is_online"):
        state = "onu_offline"
    elif recent >= RATE_LIMIT_MAX:
        state = "rate_limited"
    else:
        state = "ready"
    return {
        "subscriber_id": sid,
        "plan_id": sub.get("plan_id"),
        "plan_premium": plan_premium,
        "premium_feature": FEATURE_WIFI,
        "smartolt_onu_id": onu_id,
        "onu": onu_summary,
        "recent_changes_24h": recent,
        "rate_limit_max": RATE_LIMIT_MAX,
        "state": state,
    }


@router.post("/subscriber/{sid}/link-onu")
async def link_onu(sid: str, payload: LinkOnuIn,
                   user: dict = Depends(get_current_user)):
    """Vincula manualmente uma ONU do SmartOLT a este assinante."""
    if user.get("role") not in ("gestor", "administrador", "auditor") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/auditor.")
    cid = _cid(user)
    await _get_subscriber(sid, cid)  # valida existência + tenant
    onu = await _onu_by_id(cid, payload.smartolt_onu_id)
    if not onu:
        raise HTTPException(404, "ONU não encontrada no cache SmartOLT.")
    # Garante exclusividade — uma ONU por assinante. Se outra estava vinculada,
    # avisa via response.
    prior = await db.subscribers.find_one(
        {"company_id": cid, "smartolt_onu_id": payload.smartolt_onu_id,
         "id": {"$ne": sid}},
        {"_id": 0, "id": 1, "name": 1},
    )
    await db.subscribers.update_one(
        {"id": sid, "company_id": cid},
        {"$set": {"smartolt_onu_id": payload.smartolt_onu_id,
                  "smartolt_onu_linked_at": now_iso(),
                  "smartolt_onu_linked_by": user.get("email"),
                  "updated_at": now_iso()}},
    )
    if prior:
        # Limpa link no antigo (não deixa órfão).
        await db.subscribers.update_one(
            {"id": prior["id"], "company_id": cid},
            {"$unset": {"smartolt_onu_id": "",
                        "smartolt_onu_linked_at": "",
                        "smartolt_onu_linked_by": ""},
             "$set": {"updated_at": now_iso()}},
        )
    return {
        "ok": True,
        "subscriber_id": sid,
        "smartolt_onu_id": payload.smartolt_onu_id,
        "onu": await _summarize_onu(onu),
        "displaced_prior_subscriber": prior or None,
    }


@router.delete("/subscriber/{sid}/link-onu")
async def unlink_onu(sid: str, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("gestor", "administrador", "auditor") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/auditor.")
    cid = _cid(user)
    sub = await _get_subscriber(sid, cid)
    await db.subscribers.update_one(
        {"id": sid, "company_id": cid},
        {"$unset": {"smartolt_onu_id": "",
                    "smartolt_onu_linked_at": "",
                    "smartolt_onu_linked_by": ""},
         "$set": {"updated_at": now_iso()}},
    )
    return {"ok": True, "subscriber_id": sid,
            "previous_onu_id": sub.get("smartolt_onu_id")}


@router.post("/subscriber/{sid}/auto-match")
async def auto_match(sid: str, user: dict = Depends(get_current_user)):
    """Tenta auto-match por PPPoE username (campo `subscribers.pppoe_user`
    ou `username` ou tag `atlaz_pppoe_user`) contra `smartolt_onus.name_norm`.
    """
    if user.get("role") not in ("gestor", "administrador", "auditor") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/auditor.")
    cid = _cid(user)
    sub = await _get_subscriber(sid, cid)
    # Tenta múltiplas fontes do PPPoE user (varia por instalação).
    pppoe_candidates = []
    for k in ("pppoe_user", "pppoe_username", "username",
              "atlaz_pppoe_user", "external_code"):
        v = sub.get(k)
        if v and isinstance(v, str):
            pppoe_candidates.append(v.strip())
    # Também tenta o nome.
    if sub.get("name"):
        pppoe_candidates.append(sub["name"].strip())
    if sub.get("nickname"):
        pppoe_candidates.append(sub["nickname"].strip())
    onu = None
    matched_by = None
    for cand in pppoe_candidates:
        norm = _norm(cand)
        if not norm:
            continue
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm}, {"_id": 0})
        if onu:
            matched_by = cand
            break
    if not onu:
        return {"ok": False, "reason": "no_match",
                "tried_candidates": pppoe_candidates}
    await db.subscribers.update_one(
        {"id": sid, "company_id": cid},
        {"$set": {"smartolt_onu_id": onu.get("unique_external_id"),
                  "smartolt_onu_linked_at": now_iso(),
                  "smartolt_onu_linked_by": "auto_match",
                  "smartolt_onu_matched_by": matched_by,
                  "updated_at": now_iso()}},
    )
    return {
        "ok": True,
        "matched_by": matched_by,
        "smartolt_onu_id": onu.get("unique_external_id"),
        "onu": await _summarize_onu(onu),
    }


# ---------------------------------------------------------------------------
# Endpoints — troca de Wi-Fi
# ---------------------------------------------------------------------------
@router.post("/subscriber/{sid}/change")
async def change_wifi(sid: str, payload: WifiChangeIn,
                       user: dict = Depends(get_current_user)):
    """Troca SSID/senha do Wi-Fi via TR-069 do SmartOLT.

    Gating:
      1. Subscriber tem smartolt_onu_id
      2. Plan tem `wifi_self_service` em premium_features
      3. ONU está online (caso contrário, 409)
      4. Rate limit: 1 troca/24h (force=True bypassa, mas apenas atendente)
    """
    cid = _cid(user)
    sub = await _get_subscriber(sid, cid)

    onu_id = sub.get("smartolt_onu_id")
    if not onu_id:
        raise HTTPException(409, "Assinante não tem ONU SmartOLT vinculada.")

    # Premium gate
    plan_premium = await _plan_has_feature(sub.get("plan_id"), cid, FEATURE_WIFI)
    if not plan_premium:
        raise HTTPException(402, {
            "code": "PREMIUM_REQUIRED",
            "message": "Esse plano não inclui Wi-Fi self-service. "
                       "Faça upgrade pra um plano Premium.",
            "feature": FEATURE_WIFI,
        })

    # Force só pelo atendente humano
    if payload.force and payload.source != "atendente":
        raise HTTPException(403, "force=True só é permitido pelo atendente.")

    # Rate limit (não conta source=atendente, eles têm trilha completa)
    if payload.source != "atendente" and not payload.force:
        recent = await _recent_changes_count(sid, cid)
        if recent >= RATE_LIMIT_MAX:
            raise HTTPException(429, {
                "code": "RATE_LIMITED",
                "message": (
                    f"Limite de {RATE_LIMIT_MAX} troca(s) por "
                    f"{RATE_LIMIT_WINDOW_HOURS}h atingido. "
                    "Aguarde ou peça assistência ao atendente humano."
                ),
                "recent_changes_24h": recent,
            })

    # Resolve ONU e valida online
    onu = await _onu_by_id(cid, onu_id)
    if not onu:
        raise HTTPException(404, "ONU vinculada não está mais no cache "
                                  "SmartOLT (foi removida ou sumiu).")
    if onu.get("status") not in ONU_STATUS_ONLINE:
        raise HTTPException(409, {
            "code": "ONU_OFFLINE",
            "message": "ONU offline no momento. Aguarde voltar online.",
            "onu_status": onu.get("status"),
        })

    # Validações de input
    _validate_ssid(payload.ssid_24)
    _validate_ssid(payload.ssid_5)
    if payload.apply_to_both:
        # Se apply_to_both, exige pelo menos ssid_24/password_24
        if not (payload.ssid_24 or payload.password_24):
            raise HTTPException(400, "apply_to_both exige ssid_24/password_24.")
        payload.ssid_5 = payload.ssid_5 or payload.ssid_24
        payload.password_5 = payload.password_5 or payload.password_24

    if not any([payload.ssid_24, payload.password_24,
                payload.ssid_5, payload.password_5]):
        raise HTTPException(400, "Nada a alterar — informe ao menos um campo.")

    # Snapshot "before" — vem do cache; se não tiver, fica vazio
    before = {
        "24": onu.get("wifi_ssid_24") or "",
        "5": onu.get("wifi_ssid_5") or "",
    }
    after = {
        "24": payload.ssid_24 or before["24"],
        "5": payload.ssid_5 or before["5"],
    }

    # Carrega config SmartOLT
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")

    # Aplica troca via SmartOLT TR-069 — best-effort.
    # SmartOLT REST endpoint real: POST /api/onu/set_wifi_port_lan/{external_id}
    # com form-data: wifi_port, ssid, password, authentication_mode, dhcp.
    # Nota: o endpoint exige SSID e PASSWORD juntos no mesmo request — se
    # quiser trocar só a senha, preservamos o SSID atual do cache local.
    import time as _time
    started_ms = int(_time.time() * 1000)
    success = True
    error_reason: Optional[str] = None
    try:
        rpcs: List[Dict[str, Any]] = []
        # Banda 2.4GHz
        if payload.ssid_24 or payload.password_24:
            rpcs.append({
                "band": "24",
                "form": {
                    "wifi_port": payload.wifi_port_24,
                    "ssid": payload.ssid_24 or before["24"] or "MinhaRede",
                    "password": payload.password_24 or "",
                    "authentication_mode": payload.authentication_mode,
                    "dhcp": "No control",
                },
            })
        # Banda 5GHz
        if payload.ssid_5 or payload.password_5:
            rpcs.append({
                "band": "5",
                "form": {
                    "wifi_port": payload.wifi_port_5,
                    "ssid": payload.ssid_5 or before["5"] or "MinhaRede_5G",
                    "password": payload.password_5 or "",
                    "authentication_mode": payload.authentication_mode,
                    "dhcp": "No control",
                },
            })
        # Path único pro SmartOLT — set_wifi_port_lan é o modo residencial
        # padrão (sem VLAN, sem trunk). Se ISP usa modo Access/Hybrid, vai
        # precisar mudar config global (TODO próxima sprint).
        path = f"/onu/set_wifi_port_lan/{onu_id}"
        for rpc in rpcs:
            # Se password vazia (cliente só quer trocar SSID), remove do form
            # — SmartOLT permite ssid sem password (mantém anterior).
            if not rpc["form"]["password"]:
                rpc["form"].pop("password")
            try:
                resp = await _smartolt_form_post(cfg, path, rpc["form"])
                if not resp.get("status"):
                    success = False
                    error_reason = (
                        f"band {rpc['band']}: "
                        f"{resp.get('error') or resp.get('response') or 'sem status'}"
                    )
                    break
            except HTTPException as he:
                # Circuit-breaker (429), 403 ou erro de rate-limit do SmartOLT
                # — registra log antes de re-raise pra trilha auditoria fica
                # completa mesmo nesses casos.
                success = False
                detail = he.detail
                if isinstance(detail, dict):
                    detail = detail.get("message") or str(detail)
                error_reason = (
                    f"band {rpc['band']} smartolt_http_exc "
                    f"{he.status_code}: {detail}"
                )
                break
            except httpx.HTTPStatusError as e:
                success = False
                error_reason = (
                    f"band {rpc['band']} HTTP {e.response.status_code}: "
                    f"{e.response.text[:160]}"
                )
                break
    except Exception as e:
        success = False
        error_reason = f"smartolt_exception: {e}"
        logger.exception("[wifi] change_wifi falhou para sid=%s", sid)

    elapsed_ms = int(_time.time() * 1000) - started_ms

    # Atualiza cache local pra refletir nova SSID (SmartOLT vai re-sincar depois)
    if success:
        cache_update = {"updated_at_local": now_iso()}
        if payload.ssid_24:
            cache_update["wifi_ssid_24"] = payload.ssid_24
        if payload.ssid_5:
            cache_update["wifi_ssid_5"] = payload.ssid_5
        try:
            await db.smartolt_onus.update_one(
                {"company_id": cid, "unique_external_id": onu_id},
                {"$set": cache_update},
            )
        except Exception:
            pass

    # Auditoria + notification
    await _log_change(cid, sid, sub, payload, user, before, after,
                       success, error_reason, elapsed_ms)

    if not success:
        raise HTTPException(502, {
            "code": "TR069_FAILED",
            "message": "SmartOLT recusou ou falhou no comando TR-069.",
            "reason": error_reason,
            "elapsed_ms": elapsed_ms,
        })

    return {
        "ok": True,
        "subscriber_id": sid,
        "smartolt_onu_id": onu_id,
        "ssid_before": before,
        "ssid_after": after,
        "password_changed": bool(payload.password_24 or payload.password_5),
        "tr069_response_time_ms": elapsed_ms,
        "source": payload.source,
    }


@router.get("/subscriber/{sid}/logs")
async def list_wifi_logs(sid: str, limit: int = 50,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    await _get_subscriber(sid, cid)  # valida existência + tenant
    cur = db.wifi_change_logs.find(
        {"company_id": cid, "subscriber_id": sid},
        {"_id": 0},
    ).sort("ts", -1).limit(min(max(limit, 1), 200))
    items = await cur.to_list(200)
    return {"items": items, "count": len(items)}


@router.post("/subscriber/{sid}/reboot-onu")
async def reboot_onu_proxy(sid: str,
                            user: dict = Depends(get_current_user)):
    """Reboot da ONU vinculada — proxy pro endpoint smartolt já existente.

    Apenas atendente (gestor/admin/auditor) — clientes via WhatsApp não
    podem rebootar livremente (Álvaro IA já tem fluxo próprio com gating).
    """
    if user.get("role") not in ("gestor", "administrador", "auditor") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/auditor.")
    cid = _cid(user)
    sub = await _get_subscriber(sid, cid)
    onu_id = sub.get("smartolt_onu_id")
    if not onu_id:
        raise HTTPException(409, "Sem ONU SmartOLT vinculada.")
    cfg = await _get_config(cid)
    if not cfg.enabled:
        raise HTTPException(400, "SmartOLT desabilitado.")
    try:
        resp = await _http_post(cfg, f"/onu/reboot/{onu_id}")
    except Exception as e:
        raise HTTPException(502, f"SmartOLT erro: {e}") from e
    ok = bool(resp.get("status"))
    await db.smartolt_actions.insert_one({
        "id": f"sma-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "reboot",
        "external_id": onu_id,
        "subscriber_id": sid,
        "actor_user": user.get("email") or user.get("id"),
        "actor_user_id": user.get("id"),
        "source": "wifi_card",
        "result_ok": ok,
        "result_raw": resp,
        "created_at": now_iso(),
    })
    if not ok:
        raise HTTPException(502, f"SmartOLT recusou: {resp.get('error') or resp}")
    return {"ok": True, "subscriber_id": sid, "external_id": onu_id}


# ---------------------------------------------------------------------------
# Endpoints PÚBLICOS — chamados pelo Álvaro IA (WhatsApp) sem JWT.
# Segurança: o subscriber só pode ser operado por quem provar conhecer o
# telefone dele (matching contra `subscribers.phones[].raw_number`).
# ---------------------------------------------------------------------------
class WifiChangeByPhoneIn(BaseModel):
    phone: str
    company_id: Optional[str] = None
    ssid: str = Field(..., max_length=32)
    password: Optional[str] = Field(default=None,
                                    min_length=PASSWORD_MIN,
                                    max_length=PASSWORD_MAX)
    apply_to_both: bool = True
    source: str = "whatsapp_alvaro"


class UpgradeLeadIn(BaseModel):
    phone: str
    subscriber_id: Optional[str] = None
    company_id: Optional[str] = None
    plan_hint: Optional[str] = None
    source: str = "whatsapp_alvaro_wifi_request"


def _normalize_phone(raw: str) -> str:
    """Normaliza pra dígitos puros (estratégia simples; mesmo padrão dos
    outros módulos que fazem match por telefone)."""
    return re.sub(r"\D", "", raw or "")


async def _resolve_subscriber_by_phone(cid: str, phone: str) -> Optional[dict]:
    """Match best-effort por telefone — usa coleção `subscriber_phones`."""
    norm = _normalize_phone(phone)
    if not norm:
        return None
    # Match direto pelo normalized_number (campo já normalizado pela ingestão)
    ph = await db.subscriber_phones.find_one(
        {"company_id": cid, "normalized_number": norm},
        {"_id": 0, "subscriber_id": 1},
    )
    if not ph:
        # Match parcial (com/sem prefixo país)
        candidates = [norm, norm.lstrip("55"), "55" + norm]
        ph = await db.subscriber_phones.find_one(
            {"company_id": cid, "normalized_number": {"$in": candidates}},
            {"_id": 0, "subscriber_id": 1},
        )
    if not ph:
        return None
    return await db.subscribers.find_one(
        {"id": ph["subscriber_id"], "company_id": cid}, {"_id": 0})


async def _phone_belongs_to_subscriber(cid: str, sid: str,
                                        phone: str) -> bool:
    norm = _normalize_phone(phone)
    if not norm:
        return False
    candidates = {norm, norm.lstrip("55"), "55" + norm}
    cur = db.subscriber_phones.find(
        {"company_id": cid, "subscriber_id": sid},
        {"_id": 0, "normalized_number": 1},
    )
    async for p in cur:
        n = p.get("normalized_number") or ""
        if n in candidates:
            return True
        # endswith match (DDD+número)
        if n and (n.endswith(norm) or norm.endswith(n)):
            return True
    return False


@router.get("/public/subscriber/{sid}/status")
async def public_status(sid: str, company_id: Optional[str] = None):
    """Versão pública usada pelo Álvaro IA. Lê-only e sem dados sensíveis."""
    cid = company_id or DEMO_COMPANY_ID
    sub = await db.subscribers.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    onu_id = sub.get("smartolt_onu_id")
    onu_summary = {}
    if onu_id:
        onu = await _onu_by_id(cid, onu_id)
        if onu:
            onu_summary = await _summarize_onu(onu)
    plan_premium = await _plan_has_feature(sub.get("plan_id"), cid, FEATURE_WIFI)
    recent = await _recent_changes_count(sid, cid)
    if not onu_id or not onu_summary:
        state = "no_onu"
    elif not plan_premium:
        state = "premium_required"
    elif not onu_summary.get("is_online"):
        state = "onu_offline"
    elif recent >= RATE_LIMIT_MAX:
        state = "rate_limited"
    else:
        state = "ready"
    return {
        "subscriber_id": sid,
        "plan_premium": plan_premium,
        "smartolt_onu_id": onu_id,
        "onu": {k: onu_summary.get(k) for k in
                ("model", "status", "is_online", "rx_dbm")},
        "state": state,
    }


@router.post("/public/subscriber/{sid}/change-by-phone")
async def public_change_by_phone(sid: str, payload: WifiChangeByPhoneIn):
    """Troca Wi-Fi via Álvaro IA. Valida ownership pelo telefone.

    Segurança em camadas:
      1. phone presente em `subscribers.phones[].raw_number` do sid
      2. Plano tem premium feature `wifi_self_service`
      3. ONU vinculada + online
      4. Rate limit 1/24h (whatsapp_alvaro source)
    """
    cid = payload.company_id or DEMO_COMPANY_ID
    sub = await db.subscribers.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    # Match phone ↔ subscriber (coleção subscriber_phones)
    if not await _phone_belongs_to_subscriber(cid, sid, payload.phone):
        raise HTTPException(403, "Telefone não autorizado pra este assinante.")
    # Constrói o payload interno e delega pro change_wifi
    inner = WifiChangeIn(
        ssid_24=payload.ssid,
        password_24=payload.password,
        apply_to_both=payload.apply_to_both,
        source=payload.source,
        force=False,
    )
    # Constrói "user" sintético — chama internamente. Mesmo gates aplicam.
    norm_in = _normalize_phone(payload.phone)
    synthetic_user = {
        "email": f"whatsapp:{norm_in}",
        "name": sub.get("name") or "Cliente WhatsApp",
        "role": "whatsapp_client",
        "company_id": cid,
    }
    return await change_wifi(sid, inner, synthetic_user)


@router.post("/public/upgrade-lead")
async def public_upgrade_lead(payload: UpgradeLeadIn):
    """Registra lead de upgrade — funil de vendas (Isabella vai puxar).

    Dedup: não cria duplicata se já existe lead 'new' do mesmo phone na
    última 1h (mesmo cid). Best-effort — não bloqueia caso falhe.
    """
    cid = payload.company_id or DEMO_COMPANY_ID
    sub = None
    if payload.subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": payload.subscriber_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "plan_id": 1},
        )
    if not sub:
        sub = await _resolve_subscriber_by_phone(cid, payload.phone)
    # Dedup window 1h — evita lead spam
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    dup = await db.sales_leads.find_one(
        {"company_id": cid, "phone": payload.phone,
         "status": "new", "ts": {"$gte": since}},
        {"_id": 0, "id": 1},
    )
    if dup:
        return {"ok": True, "lead_id": dup["id"], "deduplicated": True,
                "subscriber_id": (sub or {}).get("id")}
    lead = {
        "id": f"lead-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "phone": payload.phone,
        "subscriber_id": (sub or {}).get("id"),
        "subscriber_name": (sub or {}).get("name"),
        "current_plan_id": (sub or {}).get("plan_id"),
        "plan_hint": payload.plan_hint,
        "source": payload.source,
        "reason": "wifi_self_service_request",
        "status": "new",
        "ts": now_iso(),
    }
    try:
        await db.sales_leads.insert_one(dict(lead))
    except Exception as e:
        logger.warning("[wifi] upgrade-lead insert fail: %s", e)
    return {"ok": True, "lead_id": lead["id"],
            "subscriber_id": lead["subscriber_id"]}


# ---------------------------------------------------------------------------
# Admin endpoints — gestão de leads (Isabella IA outreach)
# ---------------------------------------------------------------------------
@router.get("/leads")
async def list_leads(status: Optional[str] = None, limit: int = 50,
                       user: dict = Depends(get_current_user)):
    """Lista leads do funil Wi-Fi self-service (admin/gestor only)."""
    if user.get("role") not in ("gestor", "administrador", "auditor") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/auditor.")
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid,
                          "source": "whatsapp_alvaro_wifi_request"}
    if status:
        q["status"] = status
    cur = db.sales_leads.find(q, {"_id": 0}).sort("ts", -1).limit(
        min(max(limit, 1), 200))
    items = await cur.to_list(200)
    # KPIs
    total = await db.sales_leads.count_documents(
        {"company_id": cid, "source": "whatsapp_alvaro_wifi_request"})
    by_status: Dict[str, int] = {}
    async for d in db.sales_leads.aggregate([
        {"$match": {"company_id": cid,
                     "source": "whatsapp_alvaro_wifi_request"}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]):
        by_status[d["_id"] or "unknown"] = d["n"]
    return {"items": items, "count": len(items),
            "total": total, "by_status": by_status}


@router.post("/leads/process-now")
async def trigger_outreach_now(user: dict = Depends(get_current_user)):
    """Dispara o worker de outreach manualmente (admin debug)."""
    if user.get("role") not in ("gestor", "administrador") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    from services.sales_outreach import process_pending_leads
    stats = await process_pending_leads()
    return {"ok": True, "stats": stats}
