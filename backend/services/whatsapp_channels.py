"""WhatsApp Multi-Channel manager.

Cada empresa pode conectar até 4 números WhatsApp ("canais") ao mesmo sistema
de agentes IA (Isabella, Alvaro, Pâmela). Os agentes funcionam em qualquer
canal — o canal é só uma identificação visual ("vendas", "suporte", etc.)
mostrada nas conversas.

Arquitetura:
- 4 sidecars Node.js Baileys rodando em portas 3002, 3003, 3004, 3005
- Cada sidecar tem `WA_SESSION_ID` distinto (isolamento de auth state no Mongo)
- Backend mantém metadata em `whatsapp_channels` collection
- Inbound webhook stampa `channel_id` na mensagem
- Outbound aceita `channel_id` opcional; padrão = canal default

Collection schema (`whatsapp_channels`):
    {
        id: "channel-{N}",         # channel-1..channel-4
        company_id: str,
        channel_name: str,          # alias customizado pelo admin (ex: "Vendas")
        port: int,                  # 3002..3005 (relevante só pra Baileys)
        session_id: str,            # WA_SESSION_ID do sidecar Baileys
        is_default_outbound: bool,  # canal padrão para envios proativos
        phone_number: str|None,     # preenchido após QR scan (cache do `me`)
        last_status: str|None,      # cache do último status conhecido
        provider: "baileys"|"evolution",  # CTO 15/06/2026 — provedor ativo
        evolution_url: str|None,     # Evolution API base URL
        evolution_api_key: str|None, # apikey global do Evolution
        evolution_instance_name: str|None, # nome da instance no Evolution
        created_at: iso8601,
        updated_at: iso8601,
    }
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "whatsapp",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
from datetime import datetime, timezone
from typing import List, Optional

# Mapeamento fixo channel_id -> porta do sidecar (alinhado com supervisor confs)
CHANNEL_PORTS: dict[str, int] = {
    "channel-1": 3002,
    "channel-2": 3003,
    "channel-3": 3004,
    "channel-4": 3005,
}
CHANNEL_IDS = list(CHANNEL_PORTS.keys())
MAX_CHANNELS = len(CHANNEL_PORTS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def base_url_for(channel_id: str) -> str:
    """URL HTTP do sidecar correspondente ao channel_id.

    Prioridade de resolução:
      1) env `WA_SIDECAR_URL_CH1` / `..._CH2` / `..._CH3` / `..._CH4`
         (PRODUÇÃO: cada sidecar rodando em Railway/Render/Fly.io com URL
         distinta — CTO 13/06/2026)
      2) env `WA_SIDECAR_URL` (legado: só channel-1)
      3) fallback `http://127.0.0.1:<port>` (PREVIEW/local — supervisor)

    Fallback ao canal-1 se channel_id desconhecido.
    """
    cid = channel_id if channel_id in CHANNEL_PORTS else "channel-1"
    env_key = {
        "channel-1": "WA_SIDECAR_URL_CH1",
        "channel-2": "WA_SIDECAR_URL_CH2",
        "channel-3": "WA_SIDECAR_URL_CH3",
        "channel-4": "WA_SIDECAR_URL_CH4",
    }[cid]
    url = (os.environ.get(env_key) or "").strip()
    if url:
        return url.rstrip("/")
    if cid == "channel-1":
        legacy = (os.environ.get("WA_SIDECAR_URL") or "").strip()
        if legacy:
            return legacy.rstrip("/")
    port = CHANNEL_PORTS[cid]
    return f"http://127.0.0.1:{port}"


def _doc_to_public(doc: dict) -> dict:
    """Remove _id, padroniza shape para a UI."""
    if not doc:
        return doc
    out = {k: v for k, v in doc.items() if k != "_id"}
    return out


async def ensure_channels_seeded(db, company_id: str) -> None:
    """Garante 4 entries de canal pra empresa (cria placeholders se faltar)."""
    coll = db["whatsapp_channels"]
    existing_ids = set()
    async for d in coll.find({"company_id": company_id}, {"id": 1}):
        existing_ids.add(d.get("id"))

    now = now_iso()
    inserts = []
    for idx, cid in enumerate(CHANNEL_IDS):
        if cid in existing_ids:
            continue
        # Canal-1 herda o número já conectado historicamente (caso exista)
        inserts.append({
            "id": cid,
            "company_id": company_id,
            "channel_name": f"Canal {idx + 1}",
            "port": CHANNEL_PORTS[cid],
            "session_id": "isabella" if cid == "channel-1" else cid,
            "is_default_outbound": cid == "channel-1",
            "phone_number": None,
            "last_status": None,
            "provider": "baileys",  # CTO 15/06/2026 — default seguro
            "evolution_url": None,
            "evolution_api_key": None,
            "evolution_instance_name": None,
            "created_at": now,
            "updated_at": now,
        })
    if inserts:
        await coll.insert_many(inserts)


async def list_channels(db, company_id: str) -> List[dict]:
    """Lista os 4 canais da empresa (seed automático se ausentes)."""
    await ensure_channels_seeded(db, company_id)
    out = []
    async for d in db["whatsapp_channels"].find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("port", 1):
        out.append(d)
    return out


async def get_channel(db, company_id: str, channel_id: str) -> Optional[dict]:
    doc = await db["whatsapp_channels"].find_one(
        {"company_id": company_id, "id": channel_id}, {"_id": 0},
    )
    return doc


async def rename_channel(db, company_id: str, channel_id: str,
                          channel_name: str) -> Optional[dict]:
    channel_name = (channel_name or "").strip()
    if not channel_name:
        return None
    await db["whatsapp_channels"].update_one(
        {"company_id": company_id, "id": channel_id},
        {"$set": {"channel_name": channel_name, "updated_at": now_iso()}},
    )
    return await get_channel(db, company_id, channel_id)


async def set_default_outbound(db, company_id: str,
                                channel_id: str) -> Optional[dict]:
    """Marca um canal como default outbound; desmarca os demais."""
    coll = db["whatsapp_channels"]
    await coll.update_many(
        {"company_id": company_id},
        {"$set": {"is_default_outbound": False, "updated_at": now_iso()}},
    )
    await coll.update_one(
        {"company_id": company_id, "id": channel_id},
        {"$set": {"is_default_outbound": True, "updated_at": now_iso()}},
    )
    return await get_channel(db, company_id, channel_id)


async def get_default_outbound_channel(db, company_id: str) -> str:
    """Retorna o channel_id marcado como default outbound (ou channel-1)."""
    doc = await db["whatsapp_channels"].find_one(
        {"company_id": company_id, "is_default_outbound": True}, {"id": 1},
    )
    return (doc or {}).get("id") or "channel-1"


async def update_channel_runtime(db, company_id: str, channel_id: str,
                                  *, phone_number: Optional[str] = None,
                                  status: Optional[str] = None) -> None:
    """Atualiza cache de phone/status quando o sidecar reporta no /status."""
    upd: dict = {"updated_at": now_iso()}
    if phone_number is not None:
        upd["phone_number"] = phone_number
    if status is not None:
        upd["last_status"] = status
    if len(upd) == 1:
        return
    await db["whatsapp_channels"].update_one(
        {"company_id": company_id, "id": channel_id},
        {"$set": upd}, upsert=False,
    )


VALID_PROVIDERS = ("baileys", "evolution")


async def set_provider_config(db, company_id: str, channel_id: str,
                                provider: str,
                                evolution_url: Optional[str] = None,
                                evolution_api_key: Optional[str] = None,
                                evolution_instance_name: Optional[str] = None,
                                ) -> Optional[dict]:
    """Atualiza provider + credenciais Evolution de um canal.

    Para provider='evolution', os 3 campos evolution_* são obrigatórios.
    Para provider='baileys', limpa os campos Evolution.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"provider inválido. use {VALID_PROVIDERS}")

    set_doc: dict = {"provider": provider, "updated_at": now_iso()}
    if provider == "evolution":
        if not (evolution_url and evolution_api_key and evolution_instance_name):
            raise ValueError(
                "Evolution requer evolution_url + evolution_api_key + evolution_instance_name"
            )
        set_doc["evolution_url"] = evolution_url.rstrip("/")
        set_doc["evolution_api_key"] = evolution_api_key
        set_doc["evolution_instance_name"] = evolution_instance_name
    else:
        # baileys → limpa Evolution config pra não confundir
        set_doc["evolution_url"] = None
        set_doc["evolution_api_key"] = None
        set_doc["evolution_instance_name"] = None

    await db["whatsapp_channels"].update_one(
        {"company_id": company_id, "id": channel_id},
        {"$set": set_doc},
    )
    return await get_channel(db, company_id, channel_id)
