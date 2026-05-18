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
    """Consulta ViaCEP e retorna endereço estruturado.

    - Aceita CEP com ou sem hífen
    - Retorna 404 se CEP não existe
    """
    digits = _digits_only(cep)
    if len(digits) != 8:
        raise HTTPException(400, "CEP precisa ter 8 dígitos")

    url = f"https://viacep.com.br/ws/{digits}/json/"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        logger.warning("[cep] erro %s", e)
        raise HTTPException(502, f"Erro consultando ViaCEP: {e}")

    if data.get("erro"):
        raise HTTPException(404, "CEP não encontrado")

    return CepResponse(
        cep=digits,
        logradouro=data.get("logradouro", "") or "",
        bairro=data.get("bairro", "") or "",
        cidade=data.get("localidade", "") or "",
        uf=data.get("uf", "") or "",
        ddd=data.get("ddd", "") or "",
        ibge=data.get("ibge", "") or "",
    )
