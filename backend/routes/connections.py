"""Card unificado de Conexões — agregador de todas as integrações externas.

Centraliza visualização e edição de credenciais (com mascaramento) das 8
integrações do SmartProv. Cada integração já tem sua própria coleção de
config — este módulo é só uma camada de leitura/escrita uniforme.

Integrações cobertas:
  • atlaz         → db.atlaz_config
  • smartolt      → db.smartolt_config
  • twilio        → db.twilio_config (settings.twilio_*)
  • meta          → db.meta_whatsapp_config
  • openrouter    → settings.openrouter_*
  • resend        → settings.resend_api_key
  • stripe        → settings.stripe_*
  • google_drive  → settings.google_drive_*
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.connections")
router = APIRouter(prefix="/api/connections", tags=["connections"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask(key: Optional[str]) -> Optional[str]:
    """Mascara uma chave: 'sk-or-v1-abc...xyz' -> 'sk-o…0xyz'."""
    if not key:
        return None
    k = str(key)
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:4]}…{k[-4:]}"


async def _get_settings_doc(company_id: str) -> Dict[str, Any]:
    """Lê settings (coleção `settings`, 1 doc por empresa)."""
    return await db.settings.find_one({"company_id": company_id}, {"_id": 0}) or {}


# ---------------------------------------------------------------------------
# Definições das integrações
# ---------------------------------------------------------------------------
INTEGRATION_DEFS = [
    {
        "id": "atlaz",
        "name": "Atlaz V2",
        "kind": "ERP / Chamados",
        "doc_url": "https://app.atlaz.com.br/docs/api",
        "collection": "atlaz_config",
        "fields": [
            {"key": "api_key", "label": "API Key (Token)", "secret": True},
            {"key": "tenant_domain", "label": "Domínio do Painel", "secret": False,
             "placeholder": "https://ligofibra.atlaz.com.br"},
            {"key": "enabled", "label": "Ativo", "type": "boolean"},
        ],
    },
    {
        "id": "smartolt",
        "name": "SmartOLT",
        "kind": "OLT / Sinal ONU",
        "doc_url": "https://docs.smartolt.com/",
        "collection": "smartolt_config",
        "fields": [
            {"key": "api_key", "label": "X-Token", "secret": True},
            {"key": "subdomain", "label": "Subdomínio", "secret": False,
             "placeholder": "ligofibra"},
            {"key": "enabled", "label": "Ativo", "type": "boolean"},
        ],
    },
    {
        "id": "twilio",
        "name": "Twilio WhatsApp",
        "kind": "Mensageria",
        "doc_url": "https://www.twilio.com/docs/whatsapp",
        "collection": "twilio_config",
        "fields": [
            {"key": "account_sid", "label": "Account SID", "secret": False},
            {"key": "auth_token", "label": "Auth Token", "secret": True},
            {"key": "whatsapp_number", "label": "Número WhatsApp", "secret": False,
             "placeholder": "+14155238886"},
            {"key": "enabled", "label": "Ativo", "type": "boolean"},
        ],
    },
    {
        "id": "meta",
        "name": "Meta WhatsApp Cloud",
        "kind": "Mensageria",
        "doc_url": "https://developers.facebook.com/docs/whatsapp/cloud-api",
        "collection": "meta_whatsapp_config",
        "fields": [
            {"key": "access_token", "label": "Access Token", "secret": True},
            {"key": "phone_number_id", "label": "Phone Number ID", "secret": False},
            {"key": "business_account_id", "label": "Business Account ID", "secret": False},
            {"key": "verify_token", "label": "Webhook Verify Token", "secret": True},
            {"key": "enabled", "label": "Ativo", "type": "boolean"},
        ],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter (LLM)",
        "kind": "Inteligência Artificial",
        "doc_url": "https://openrouter.ai/docs",
        "collection": "settings",
        "field_prefix": "openrouter_",
        "fields": [
            {"key": "api_key", "label": "API Key", "secret": True,
             "placeholder": "sk-or-v1-..."},
            {"key": "model", "label": "Modelo", "secret": False,
             "placeholder": "deepseek/deepseek-v4-flash"},
            {"key": "enabled", "label": "Ativo", "type": "boolean"},
        ],
    },
    {
        "id": "resend",
        "name": "Resend",
        "kind": "E-mail Transacional",
        "doc_url": "https://resend.com/docs",
        "collection": "settings",
        "field_prefix": "",
        "fields": [
            {"key": "resend_api_key", "label": "API Key", "secret": True,
             "placeholder": "re_..."},
            {"key": "sender_email", "label": "E-mail Remetente", "secret": False},
            {"key": "sender_name", "label": "Nome Remetente", "secret": False},
        ],
    },
    {
        "id": "stripe",
        "name": "Stripe",
        "kind": "Pagamento Assinatura SaaS",
        "doc_url": "https://stripe.com/docs/api",
        "collection": "settings",
        "field_prefix": "stripe_",
        "fields": [
            {"key": "api_key", "label": "Secret Key", "secret": True,
             "placeholder": "sk_live_..."},
            {"key": "webhook_secret", "label": "Webhook Signing Secret", "secret": True,
             "placeholder": "whsec_..."},
        ],
    },
    {
        "id": "google_drive",
        "name": "Google Drive",
        "kind": "Armazenamento",
        "doc_url": "https://developers.google.com/drive/api",
        "collection": "settings",
        "field_prefix": "google_drive_",
        "fields": [
            {"key": "client_id", "label": "Client ID", "secret": False},
            {"key": "client_secret", "label": "Client Secret", "secret": True},
            {"key": "folder_id", "label": "Folder ID Raiz", "secret": False},
        ],
    },
]


# ---------------------------------------------------------------------------
# Leitura unificada
# ---------------------------------------------------------------------------
async def _read_one(integ: Dict[str, Any], company_id: str,
                    settings_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Lê uma integração, mascarando campos secretos."""
    collection = integ["collection"]
    prefix = integ.get("field_prefix")

    if collection == "settings":
        # campos vem do doc de settings, prefixados ou não
        raw = settings_doc
        values: Dict[str, Any] = {}
        for f in integ["fields"]:
            doc_key = f"{prefix}{f['key']}" if prefix is not None else f["key"]
            v = raw.get(doc_key)
            if f.get("secret"):
                values[f["key"]] = _mask(v)
                values[f["key"] + "_set"] = bool(v)
            else:
                values[f["key"]] = v
        # Status: ativa se tiver pelo menos uma secret válida
        has_secret = any(
            raw.get(f"{prefix}{f['key']}" if prefix is not None else f["key"])
            for f in integ["fields"] if f.get("secret")
        )
        last_sync_at = None
    else:
        raw = await db[collection].find_one({"company_id": company_id}, {"_id": 0}) or {}
        values = {}
        for f in integ["fields"]:
            v = raw.get(f["key"])
            if f.get("secret"):
                values[f["key"]] = _mask(v)
                values[f["key"] + "_set"] = bool(v)
            else:
                values[f["key"]] = v
        has_secret = any(
            raw.get(f["key"]) for f in integ["fields"] if f.get("secret")
        )
        last_sync_at = raw.get("last_sync_at") or raw.get("last_auto_sync_bubbles_at")

    enabled = bool(values.get("enabled")) if "enabled" in values else has_secret
    return {
        "id": integ["id"],
        "name": integ["name"],
        "kind": integ["kind"],
        "doc_url": integ["doc_url"],
        "enabled": enabled,
        "configured": has_secret,
        "last_sync_at": last_sync_at,
        "fields": integ["fields"],
        "values": values,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/")
async def list_connections(user: dict = Depends(require_role("administrador"))):
    """Lista todas as integrações com status e valores mascarados."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    settings_doc = await _get_settings_doc(company_id)
    out: List[Dict[str, Any]] = []
    for integ in INTEGRATION_DEFS:
        out.append(await _read_one(integ, company_id, settings_doc))
    return {"connections": out}


class UpdateConnectionPayload(BaseModel):
    values: Dict[str, Any]


@router.put("/{integration_id}")
async def update_connection(integration_id: str, payload: UpdateConnectionPayload,
                            user: dict = Depends(require_role("administrador"))):
    """Atualiza valores de uma integração específica.

    Comportamento de segurança:
      • Se um campo secreto vier vazio (""), MANTÉM o valor atual (não apaga).
      • Se vier preenchido, sobrescreve.
      • Para limpar, mande explicitamente {"clear": true} no campo.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    integ = next((i for i in INTEGRATION_DEFS if i["id"] == integration_id), None)
    if not integ:
        raise HTTPException(404, f"Integração desconhecida: {integration_id}")

    collection = integ["collection"]
    prefix = integ.get("field_prefix")
    incoming = payload.values or {}

    # Monta o $set
    update_set: Dict[str, Any] = {}
    for f in integ["fields"]:
        if f["key"] not in incoming:
            continue
        new_val = incoming[f["key"]]
        # Secret vazio = manter atual; não inclui no update
        if f.get("secret") and (new_val == "" or new_val is None):
            continue
        doc_key = (f"{prefix}{f['key']}"
                   if (collection == "settings" and prefix is not None)
                   else f["key"])
        if f.get("type") == "boolean":
            update_set[doc_key] = bool(new_val)
        else:
            update_set[doc_key] = new_val

    if not update_set:
        return {"ok": True, "updated": 0, "message": "Nada para atualizar."}

    update_set["updated_at"] = now_iso()

    if collection == "settings":
        await db.settings.update_one(
            {"company_id": company_id}, {"$set": update_set}, upsert=True,
        )
    else:
        update_set["company_id"] = company_id
        await db[collection].update_one(
            {"company_id": company_id}, {"$set": update_set}, upsert=True,
        )

    # Log de auditoria
    await db.connection_audit.insert_one({
        "company_id": company_id,
        "integration_id": integration_id,
        "actor_email": user.get("email"),
        "fields_changed": list(update_set.keys()),
        "at": now_iso(),
    })

    return {"ok": True, "updated": len(update_set) - 1}  # -1 = updated_at
