"""Endpoints utilitários: validação de CPF/CNPJ e consulta de CEP via ViaCEP.

Usado no cadastro de cliente (frontend) e por automações da Isabella.

ViaCEP é gratuito, sem autenticação, sem rate limit conhecido.
Algoritmo de CPF/CNPJ implementado localmente (rápido, sem custo).
"""
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/utils", tags=["utils"])


# ---------------------------------------------------------------------------
# CPF/CNPJ validation
# ---------------------------------------------------------------------------
def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def validate_cpf(cpf: str) -> bool:
    """Valida CPF pelo algoritmo oficial da Receita Federal."""
    c = _digits_only(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for i in (9, 10):
        s = sum(int(c[j]) * ((i + 1) - j) for j in range(i))
        d = (s * 10) % 11
        if d == 10:
            d = 0
        if d != int(c[i]):
            return False
    return True


def validate_cnpj(cnpj: str) -> bool:
    """Valida CNPJ pelo algoritmo oficial da Receita Federal."""
    c = _digits_only(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for length, w in ((12, weights[1:]), (13, weights)):
        s = sum(int(c[i]) * w[i] for i in range(length))
        d = 11 - s % 11
        if d >= 10:
            d = 0
        if d != int(c[length]):
            return False
    return True


class ValidateDocResponse(BaseModel):
    raw: str
    digits: str
    type: str       # "cpf" | "cnpj" | "unknown"
    valid: bool
    formatted: Optional[str] = None


@router.get("/validate-document", response_model=ValidateDocResponse)
async def validate_document(value: str):
    """Identifica e valida CPF (11d) ou CNPJ (14d).

    Frontend usa pra mostrar tag "Válido" ✅ / "Inválido" ❌ abaixo do campo.
    """
    digits = _digits_only(value)
    if len(digits) == 11:
        valid = validate_cpf(digits)
        formatted = f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}" if valid else None
        return ValidateDocResponse(raw=value, digits=digits, type="cpf",
                                   valid=valid, formatted=formatted)
    if len(digits) == 14:
        valid = validate_cnpj(digits)
        formatted = (f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/"
                     f"{digits[8:12]}-{digits[12:]}") if valid else None
        return ValidateDocResponse(raw=value, digits=digits, type="cnpj",
                                   valid=valid, formatted=formatted)
    return ValidateDocResponse(raw=value, digits=digits, type="unknown",
                               valid=False)


# ---------------------------------------------------------------------------
# CEP lookup (ViaCEP)
# ---------------------------------------------------------------------------
class CepResponse(BaseModel):
    cep: str
    logradouro: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""
    ddd: str = ""
    ibge: str = ""
    found: bool = True


@router.get("/cep/{cep}", response_model=CepResponse)
async def lookup_cep(cep: str):
    """Consulta CEP com fallback automático: cache → ViaCEP → BrasilAPI → OpenCEP.

    - Aceita CEP com ou sem hífen
    - Retorna 404 se nenhuma fonte encontrar
    - Cacheia resultado em MongoDB pra próximas consultas serem instantâneas
    """
    digits = _digits_only(cep)
    if len(digits) != 8:
        raise HTTPException(400, "CEP precisa ter 8 dígitos")

    # 1. Cache local
    cached = await db.cep_cache.find_one({"cep": digits}, {"_id": 0})
    if cached:
        return CepResponse(**{k: v for k, v in cached.items()
                              if k in CepResponse.model_fields})

    # 2. ViaCEP → 3. BrasilAPI → 4. OpenCEP
    sources = [
        ("viacep", f"https://viacep.com.br/ws/{digits}/json/"),
        ("brasilapi", f"https://brasilapi.com.br/api/cep/v2/{digits}"),
        ("opencep", f"https://opencep.com/v1/{digits}"),
    ]
    result: Optional[CepResponse] = None
    for source_name, url in sources:
        try:
            async with httpx.AsyncClient(timeout=4.0) as cli:
                r = await cli.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
            if data.get("erro"):
                continue
            # Normalizar campos entre fontes
            result = CepResponse(
                cep=digits,
                logradouro=(data.get("logradouro") or data.get("street")
                            or "").strip(),
                bairro=(data.get("bairro") or data.get("neighborhood")
                        or "").strip(),
                cidade=(data.get("localidade") or data.get("city")
                        or "").strip(),
                uf=(data.get("uf") or data.get("state") or "").strip(),
                ddd=(data.get("ddd") or "").strip(),
                ibge=(data.get("ibge") or "").strip(),
            )
            # Aceita só se tem ao menos cidade ou bairro
            if result.cidade or result.bairro:
                logger.info("[cep] %s → fonte=%s", digits, source_name)
                break
            result = None
        except (httpx.HTTPError, ValueError) as e:
            logger.debug("[cep] %s falhou: %s", source_name, e)
            continue

    if not result:
        raise HTTPException(404, "CEP não encontrado em nenhuma fonte")

    # Salva no cache (ignora erro de unique)
    try:
        await db.cep_cache.update_one(
            {"cep": digits},
            {"$set": result.model_dump()}, upsert=True,
        )
    except Exception:
        pass
    return result
