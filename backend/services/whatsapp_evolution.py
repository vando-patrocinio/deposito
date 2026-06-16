"""Evolution API WhatsApp provider (adapter).

CTO 15/06/2026 (cto_inbox ordem CEO): adicionar Evolution API como provedor
opcional ao lado dos sidecars Baileys. Cada canal escolhe `provider`:
    - "baileys"   (default, sidecars Node.js locais)
    - "evolution" (Evolution API v2, self-hosted Docker)

Este módulo apenas expõe um cliente httpx para os 5 endpoints essenciais.
A persistência de credenciais (URL, api_key, instance_name) fica em
`whatsapp_channels` por canal. O roteamento provider->adapter está em
`routes/whatsapp_channels.py`.
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

import base64 as _b64
import json as _json
from typing import Optional

import httpx


class EvolutionUnreachable(Exception):
    """Erro 502/HTML do proxy (ex.: Apache Basic Auth) interceptando a Evolution."""


def _parse_json_or_raise(r: httpx.Response, endpoint: str) -> dict:
    """Parse JSON da Evolution OU levanta EvolutionUnreachable com mensagem útil.

    Apache na frente da Evolution devolve HTML (login form 401) → não é JSON e
    o `r.json()` quebra com `JSONDecodeError`. Aqui detectamos e devolvemos
    erro estruturado pro endpoint mapear pra 502 limpo.
    """
    ct = (r.headers.get("content-type") or "").lower()
    if "json" in ct or r.text.strip().startswith("{"):
        try:
            return r.json() if r.content else {}
        except _json.JSONDecodeError:
            pass
    head = r.text[:160].replace("\n", " ")
    raise EvolutionUnreachable(
        f"Evolution `{endpoint}` retornou HTTP {r.status_code} não-JSON "
        f"(prefixo: '{head}…'). Provavelmente está atrás de proxy (Apache) "
        "exigindo Basic Auth. Configure `evolution_basic_auth` no canal "
        "(formato `usuario:senha`) ou remova a proteção do proxy."
    )


class EvolutionClient:
    """Cliente httpx para Evolution API v2.

    Auth: header `apikey: <global_api_key>`.
    Opcional: `basic_auth` (string `user:pass`) injetado como Basic Auth
    header — útil quando a Evolution está atrás de Apache/nginx com
    proteção Basic Auth.
    Phone number format: digits only com country code, ex `5511999999999`.
    """

    def __init__(self, base_url: str, api_key: str,
                  instance_name: str, timeout: float = 15.0,
                  basic_auth: Optional[str] = None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.instance_name = (instance_name or "").strip()
        self.timeout = timeout
        self.basic_auth = (basic_auth or "").strip() or None
        if not self.base_url or not self.api_key or not self.instance_name:
            raise ValueError("Evolution: base_url, api_key e instance_name são obrigatórios")

    @property
    def headers(self) -> dict:
        h = {"apikey": self.api_key, "Content-Type": "application/json"}
        if self.basic_auth:
            tok = _b64.b64encode(self.basic_auth.encode("utf-8")).decode("ascii")
            h["Authorization"] = f"Basic {tok}"
        return h

    async def create_instance(self, webhook_url: Optional[str] = None) -> dict:
        """Cria a instance (idempotente — se já existir, Evolution retorna 403).

        Se webhook_url for fornecido, configura o webhook por instance após
        criar (POST /webhook/set/{instance}).
        """
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            try:
                r = await cli.post(
                    f"{self.base_url}/instance/create",
                    headers=self.headers,
                    json={
                        "instanceName": self.instance_name,
                        "qrcode": True,
                        "integration": "WHATSAPP-BAILEYS",
                    },
                )
                created = _parse_json_or_raise(r, "/instance/create")
                # 403 ou 409 = já existe; consideramos OK.
                if r.status_code not in (200, 201, 403, 409):
                    r.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (403, 409):
                    raise
                created = {"already_exists": True}

            if webhook_url:
                await cli.post(
                    f"{self.base_url}/webhook/set/{self.instance_name}",
                    headers=self.headers,
                    json={
                        "webhook": {
                            "enabled": True,
                            "url": webhook_url,
                            "byEvents": False,
                            "base64": False,
                            "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"],
                        }
                    },
                )
            return created

    async def get_qr(self) -> dict:
        """GET /instance/connect/{instance} → retorna {base64, pairingCode?}.

        O campo base64 já vem com prefixo `data:image/png;base64,`.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.get(
                f"{self.base_url}/instance/connect/{self.instance_name}",
                headers=self.headers,
            )
            r.raise_for_status()
            data = _parse_json_or_raise(r, "/instance/connect")
            # Normaliza shape pro consumidor: {qr_base64, raw}
            qr = data.get("base64") or data.get("code")
            return {"qr_base64": qr, "raw": data}

    async def status(self) -> dict:
        """GET /instance/connectionState/{instance}.

        Retorna `{instance: {instanceName, state}}` em v2. state ∈
        {open, close, connecting}.
        Normalizamos pra: {state, connected, raw}.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.get(
                f"{self.base_url}/instance/connectionState/{self.instance_name}",
                headers=self.headers,
            )
            r.raise_for_status()
            data = _parse_json_or_raise(r, "/instance/connectionState")
            inst = data.get("instance") or data
            state = inst.get("state") or inst.get("status")
            return {
                "state": state,
                "connected": state == "open",
                "raw": data,
            }

    async def send_text(self, number: str, text: str) -> dict:
        """POST /message/sendText/{instance}."""
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(
                f"{self.base_url}/message/sendText/{self.instance_name}",
                headers=self.headers,
                json={"number": self._normalize_number(number), "text": text},
            )
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}

    async def logout(self) -> dict:
        """DELETE /instance/logout/{instance}."""
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.delete(
                f"{self.base_url}/instance/logout/{self.instance_name}",
                headers=self.headers,
            )
            # 200 ou 404 (já estava deslogada) são OK
            if r.status_code not in (200, 404):
                r.raise_for_status()
            return r.json() if r.content else {"ok": True}

    @staticmethod
    def _normalize_number(raw: str) -> str:
        """Normaliza pra dígitos puros: '+55 (11) 99999-9999' -> '5511999999999'."""
        if not raw:
            return raw
        return "".join(ch for ch in str(raw) if ch.isdigit())
