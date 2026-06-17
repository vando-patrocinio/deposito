"""Lookup de CNPJ via BrasilAPI (gratuito, sem auth).

Endpoint: https://brasilapi.com.br/api/cnpj/v1/{cnpj}
Fonte: Receita Federal (sincronizada). Retorna razão social, nome fantasia,
endereço completo, situação cadastral, CNAE principal, sócios.

Usado pela Isabella quando o cliente PJ envia o CNPJ pra confirmar empresa
antes de escalar pro Consultor PJ. Evita aceitar "anotado" cego.

Por que NÃO cnpj.biz (pedido inicial do CEO)?
- cnpj.biz é HTML scrape (frágil + ToS questionável)
- BrasilAPI usa dados oficiais da Receita, JSON estável, sem rate limit
  agressivo, atende ao mesmo objetivo do CEO: confirmar razão social +
  endereço a partir do CNPJ enviado pelo cliente.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger("ponto.cnpj_lookup")

BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h por CNPJ

_cache: Dict[str, Dict[str, Any]] = {}
_lock = asyncio.Lock()


def only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def is_valid_cnpj(cnpj_digits: str) -> bool:
    """Validação básica de CNPJ (módulo 11 dos 2 últimos dígitos)."""
    if len(cnpj_digits) != 14 or len(set(cnpj_digits)) == 1:
        return False
    weights_1 = [5,4,3,2,9,8,7,6,5,4,3,2]
    weights_2 = [6,5,4,3,2,9,8,7,6,5,4,3,2]
    nums = [int(c) for c in cnpj_digits]
    soma = sum(a*b for a, b in zip(nums[:12], weights_1))
    d1 = 0 if soma % 11 < 2 else 11 - (soma % 11)
    if d1 != nums[12]:
        return False
    soma = sum(a*b for a, b in zip(nums[:13], weights_2))
    d2 = 0 if soma % 11 < 2 else 11 - (soma % 11)
    return d2 == nums[13]


def format_cnpj(cnpj_digits: str) -> str:
    if len(cnpj_digits) != 14:
        return cnpj_digits
    return f"{cnpj_digits[0:2]}.{cnpj_digits[2:5]}.{cnpj_digits[5:8]}/{cnpj_digits[8:12]}-{cnpj_digits[12:14]}"


def extract_cnpj(text: str) -> Optional[str]:
    """Extrai um CNPJ válido de qualquer texto.

    Detecta padrões com pontuação (`13.302.883/0001-36`) ou só dígitos
    (`13302883000136`). Devolve só dígitos pra normalizar.
    """
    if not text:
        return None
    # Procura 14 dígitos contíguos ou padrão com pontuação
    candidates = re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{14}", text)
    for c in candidates:
        d = only_digits(c)
        if is_valid_cnpj(d):
            return d
    return None


async def lookup(cnpj: str) -> Dict[str, Any]:
    """Consulta CNPJ na BrasilAPI com cache de 24h.

    Returns:
        dict com `ok`, `cnpj`, `razao_social`, `nome_fantasia`,
        `address_full`, `municipio`, `uf`, `situacao`, `cnae_descricao`,
        ou `{ok: False, error: '...'}` em falha.
    """
    cnpj_digits = only_digits(cnpj)
    if not is_valid_cnpj(cnpj_digits):
        return {"ok": False, "error": "CNPJ inválido (dígitos verificadores não batem)."}

    now = time.time()
    cached = _cache.get(cnpj_digits)
    if cached and (now - cached["_ts"] < CACHE_TTL_SECONDS):
        return cached["data"]

    async with _lock:
        cached = _cache.get(cnpj_digits)
        if cached and (now - cached["_ts"] < CACHE_TTL_SECONDS):
            return cached["data"]
        try:
            async with httpx.AsyncClient(timeout=12.0, headers={
                "User-Agent": "Ponto-IA-Ligo/1.0 (CNPJ lookup)",
                "Accept": "application/json",
            }) as cli:
                r = await cli.get(BRASILAPI_URL.format(cnpj=cnpj_digits))
                if r.status_code == 404:
                    return {"ok": False, "error": "CNPJ não encontrado na Receita Federal."}
                r.raise_for_status()
                raw = r.json()
        except Exception as exc:
            log.warning("[cnpj_lookup] falha lookup %s: %s", cnpj_digits, exc)
            return {"ok": False, "error": f"Falha consulta CNPJ: {exc}"}

        # Normaliza payload BrasilAPI
        logradouro = raw.get("logradouro") or ""
        numero = raw.get("numero") or ""
        bairro = raw.get("bairro") or ""
        municipio = raw.get("municipio") or ""
        uf = raw.get("uf") or ""
        cep = raw.get("cep") or ""
        compl = raw.get("complemento") or ""
        address_parts = [
            f"{logradouro}, {numero}".strip(", "),
            compl.strip(),
            bairro,
            f"{municipio}/{uf}".strip("/"),
            f"CEP {cep}" if cep else "",
        ]
        address_full = " — ".join(p for p in address_parts if p)

        situacao = (raw.get("descricao_situacao_cadastral") or "").upper()
        data = {
            "ok": True,
            "cnpj": format_cnpj(cnpj_digits),
            "cnpj_digits": cnpj_digits,
            "razao_social": raw.get("razao_social") or "",
            "nome_fantasia": raw.get("nome_fantasia") or "",
            "address_full": address_full,
            "municipio": municipio,
            "uf": uf,
            "cep": cep,
            "situacao": situacao or "DESCONHECIDA",
            "cnae_descricao": raw.get("cnae_fiscal_descricao") or "",
            "porte": raw.get("porte") or "",
            "data_abertura": raw.get("data_inicio_atividade") or "",
            "telefone": raw.get("ddd_telefone_1") or "",
            "email": raw.get("email") or "",
            "is_active": situacao == "ATIVA",
        }
        _cache[cnpj_digits] = {"_ts": now, "data": data}
        return data
