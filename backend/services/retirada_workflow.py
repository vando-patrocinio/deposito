"""Serviço dedicado ao fluxo de finalização de OS de RETIRADA.

Responsabilidades:
1. Enviar "COMPROVANTE DE DEVOLUÇÃO DE EQUIPAMENTO" via WhatsApp pro cliente
   ao finalizar a OS de retirada. Template é configurável por empresa via
   `aihub_settings.key=retirada_comprovante_template`.
2. Solicitar remoção da ONU no SmartOLT (best-effort) — chama o endpoint
   `/onu/delete/{external_id}` do wrapper SmartOLT. Falhas não bloqueiam o
   fechamento da OS.

Esses dois passos são chamados como `background_tasks` no close handler.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("retirada_workflow")

# Template padrão — usuário pode editar via Configurações.
DEFAULT_TEMPLATE = """COMPROVANTE DE DEVOLUÇÃO DE EQUIPAMENTO

Olá, tudo bem?

Informamos que foi realizada a retirada do equipamento de internet no endereço, referente ao serviço anteriormente contratado.

Declaramos que o equipamento foi devidamente recolhido e recebido pela nossa equipe, servindo esta mensagem como comprovante de devolução.

Cliente: {cliente}
Endereço: {endereco}
Equipamento retirado: {equipamento}
Número de série: {sn}
Data da retirada: {data}
Responsável pela retirada: {tecnico}

Agradecemos pela atenção e permanecemos à disposição para qualquer esclarecimento.

Atenciosamente,
{empresa}"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_template(company_id: str) -> str:
    """Lê o template configurado pela empresa (fallback p/ DEFAULT_TEMPLATE)."""
    doc = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": "retirada_comprovante_template"},
        {"_id": 0, "value": 1},
    )
    if doc and isinstance(doc.get("value"), str) and doc["value"].strip():
        return doc["value"]
    return DEFAULT_TEMPLATE


async def _get_company_name(company_id: str) -> str:
    """Nome fantasia da empresa (do branding)."""
    try:
        br = await db.branding.find_one(
            {"company_id": company_id},
            {"_id": 0, "company_name": 1, "name": 1},
        )
        if br:
            return br.get("company_name") or br.get("name") or "Provedor"
    except Exception:
        pass
    return "Provedor"


def _format_address(addr: Optional[Dict[str, Any]] | str) -> str:
    """Formata endereço para o template."""
    if not addr:
        return "—"
    if isinstance(addr, str):
        return addr
    parts = []
    rua = addr.get("rua") or addr.get("street") or ""
    num = addr.get("numero") or addr.get("number") or ""
    if rua:
        parts.append(f"{rua}{', ' + str(num) if num else ''}")
    bairro = addr.get("bairro") or addr.get("neighborhood")
    if bairro:
        parts.append(str(bairro))
    cidade = addr.get("cidade") or addr.get("city")
    if cidade:
        parts.append(str(cidade))
    return " · ".join(parts) if parts else "—"


def _digits_only(phone: Optional[str]) -> str:
    if not phone:
        return ""
    return "".join(c for c in str(phone) if c.isdigit())


async def send_retirada_comprovante(
    *,
    company_id: str,
    ticket: Dict[str, Any],
    technician_name: str,
    ont_mac_sn: Optional[str] = None,
) -> Dict[str, Any]:
    """Envia o comprovante de devolução via WhatsApp.

    Retorna `{"ok": bool, "phone": str, "reason": str}` — sucesso/falha.
    Erros não levantam exceção — apenas logam.
    """
    cs = ticket.get("client_snapshot") or {}
    cliente_nome = cs.get("name") or "Cliente"
    phone = _digits_only(cs.get("phone") or cs.get("whatsapp") or cs.get("celular"))
    if not phone:
        logger.info("[retirada] sem telefone cadastrado — pulando WhatsApp")
        return {"ok": False, "phone": "", "reason": "no_phone"}

    # Normaliza pra E.164 BR (adiciona 55 se vier só 11 dígitos)
    if len(phone) <= 11 and not phone.startswith("55"):
        phone = "55" + phone

    template = await _get_template(company_id)
    empresa = await _get_company_name(company_id)
    endereco = _format_address(cs.get("address") or cs.get("endereco")
                                  or cs.get("address_text"))

    # Equipamento — tenta deduzir do modelo da ONT (snapshot) ou marca genérico
    equipamento = (cs.get("ont_model") or cs.get("equipment_model")
                   or "Modem/Roteador/ONU")

    data_str = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")

    text = template.format(
        cliente=cliente_nome,
        endereco=endereco or "—",
        equipamento=equipamento,
        sn=(ont_mac_sn or "—").upper(),
        data=data_str,
        tecnico=technician_name or "Técnico",
        empresa=empresa,
    )

    # Tenta enviar via sidecar Baileys (default outbound)
    try:
        from services.wa.sidecar import _sidecar_post_silent  # type: ignore
        resp = await _sidecar_post_silent(
            "/send", {"phone": phone, "text": text},
        )
        ok = bool((resp or {}).get("ok"))
        # Espelha no log de mensagens
        try:
            await db.aihub_wa_messages.insert_one({
                "company_id": company_id, "phone": phone,
                "jid": f"{phone}@s.whatsapp.net",
                "direction": "outbound", "text": text,
                "subscriber_id": cs.get("id") or cs.get("subscriber_id"),
                "auto_reply": True, "agent": "retirada_comprovante",
                "delivery_status": "sent" if ok else "failed_send",
                "external_id": (resp or {}).get("message_id"),
                "created_at": now_iso(),
                "ticket_id": ticket.get("id"),
            })
        except Exception:
            pass
        return {"ok": ok, "phone": phone,
                "reason": "" if ok else "sidecar_failed"}
    except Exception as e:
        logger.warning("[retirada] envio WhatsApp falhou: %s", e)
        return {"ok": False, "phone": phone, "reason": str(e)}


async def request_smartolt_remove(
    *,
    company_id: str,
    ticket: Dict[str, Any],
    smartolt_onu: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Solicita remoção da ONU no SmartOLT.

    Best-effort: se o SmartOLT estiver desabilitado ou a chamada falhar,
    apenas marca um pending na coleção `smartolt_pending_removals` pra o
    gestor processar manualmente.
    """
    ext_id = (smartolt_onu or {}).get("unique_external_id")
    pending_doc: Dict[str, Any] = {
        "company_id": company_id,
        "ticket_id": ticket.get("id"),
        "client_id": (ticket.get("client_snapshot") or {}).get("id"),
        "client_name": (ticket.get("client_snapshot") or {}).get("name"),
        "external_id": ext_id,
        "created_at": now_iso(),
        "status": "pending",
    }

    if not ext_id:
        pending_doc["reason"] = "no_external_id"
        try:
            await db.smartolt_pending_removals.insert_one(pending_doc)
        except Exception:
            pass
        return {"ok": False, "reason": "no_external_id"}

    try:
        cfg = await db.smartolt_configs.find_one(
            {"company_id": company_id}, {"_id": 0},
        ) or {}
        if not (cfg.get("enabled") and cfg.get("subdomain") and cfg.get("api_key")):
            pending_doc["reason"] = "smartolt_disabled"
            await db.smartolt_pending_removals.insert_one(pending_doc)
            return {"ok": False, "reason": "smartolt_disabled"}

        from routes.smartolt import _http_post  # type: ignore

        class _CfgShim:
            pass
        shim = _CfgShim()
        shim.subdomain = cfg["subdomain"]
        shim.api_key = cfg["api_key"]
        shim.timeout_seconds = cfg.get("timeout_seconds", 8)

        # Endpoint público SmartOLT: POST /onu/delete/{external_id}
        resp = await _http_post(shim, f"/onu/delete/{ext_id}")
        ok = isinstance(resp, dict) and not resp.get("error")
        if ok:
            # Marca como removida pra o gestor não precisar conferir manualmente
            try:
                await db.smartolt_onus.update_one(
                    {"unique_external_id": ext_id, "company_id": company_id},
                    {"$set": {"removed_at": now_iso(),
                              "removed_via_ticket": ticket.get("id")}},
                )
            except Exception:
                pass
            return {"ok": True, "external_id": ext_id}
        pending_doc["reason"] = "smartolt_api_error"
        pending_doc["api_response"] = str(resp)[:500]
        await db.smartolt_pending_removals.insert_one(pending_doc)
        return {"ok": False, "reason": "smartolt_api_error"}
    except Exception as e:
        logger.warning("[retirada] SmartOLT remove falhou: %s", e)
        pending_doc["reason"] = f"exception:{e}"
        try:
            await db.smartolt_pending_removals.insert_one(pending_doc)
        except Exception:
            pass
        return {"ok": False, "reason": str(e)}


async def get_template(company_id: str) -> str:
    """Helper público pra Settings UI."""
    return await _get_template(company_id)


async def set_template(company_id: str, template: str) -> None:
    """Helper público pra Settings UI persistir um template editado."""
    await db.aihub_settings.update_one(
        {"company_id": company_id, "key": "retirada_comprovante_template"},
        {"$set": {"value": template, "updated_at": now_iso()}},
        upsert=True,
    )
