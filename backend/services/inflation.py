"""Serviço de consulta de índices de inflação oficiais (IPCA, IST, IGP-M).

Fonte primária: API SGS do Banco Central do Brasil (gratuita, sem autenticação).
- IPCA mensal: código 433 (IBGE)
- IGP-M mensal: código 189 (FGV)
- IST mensal: código 7833 (próprio BCB)
- IPCA acumulado 12 meses: código 13522

Endpoint padrão:
  GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json

Cache em MongoDB (collection inflation_indices) — refresh diário no worker.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx

from database import db

logger = logging.getLogger(__name__)

# Códigos SGS Banco Central
SGS_CODES = {
    "IPCA": 433,           # IPCA mensal (IBGE)
    "IPCA_12M": 13522,     # IPCA acumulado 12 meses
    "IGP-M": 189,          # IGP-M mensal (FGV)
    "IST": 7833,           # IST mensal (BCB)
}

DEFAULT_INDEX = "IPCA"   # mais comum em contratos de telecom residencial


async def fetch_sgs_series(code: int, last_n_months: int = 132) -> List[Dict]:
    """Busca série temporal do SGS-BCB nos últimos N meses.

    Default: 132 meses (~11 anos) — suficiente para reajustes retroativos.
    Retorna: [{"data": "01/04/2026", "valor": "0.49"}, ...]
    """
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
    params = {"formato": "json"}
    # Filtra os N últimos meses
    if last_n_months:
        start = (date.today() - timedelta(days=last_n_months * 31)).strftime("%d/%m/%Y")
        params["dataInicial"] = start
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(url, params=params)
            r.raise_for_status()
            return r.json() or []
    except httpx.HTTPError as e:
        logger.warning("[inflation] BCB %s falhou: %s", code, e)
        return []


async def refresh_index_cache(index_name: str = "IPCA") -> Dict:
    """Atualiza cache de um índice em inflation_indices.

    Estrutura salva:
      {
        "name": "IPCA",
        "sgs_code": 433,
        "series": [{"period": "2025-12", "value": 0.49}, ...],
        "accumulated_12m": 4.62,        # acumulado dos últimos 12 meses
        "last_period": "2026-04",
        "updated_at": "...",
      }
    """
    code = SGS_CODES.get(index_name)
    if not code:
        raise ValueError(f"Índice desconhecido: {index_name}")

    raw = await fetch_sgs_series(code, last_n_months=132)
    if not raw:
        return {}

    # Parse: data "01/04/2026" → "2026-04"; valor "0.49" → 0.49
    series = []
    for row in raw:
        try:
            d = datetime.strptime(row["data"], "%d/%m/%Y")
            period = d.strftime("%Y-%m")
            val = float(row["valor"])
            series.append({"period": period, "value": val})
        except (KeyError, ValueError):
            continue

    series.sort(key=lambda x: x["period"])

    # Calcula acumulado nos últimos 12 meses: produto de (1 + valor/100) - 1
    last_12 = series[-12:] if len(series) >= 12 else series
    factor = 1.0
    for s in last_12:
        factor *= (1 + s["value"] / 100.0)
    acc_12m = round((factor - 1) * 100, 4)

    doc = {
        "name": index_name,
        "sgs_code": code,
        "series": series,
        "accumulated_12m": acc_12m,
        "last_period": series[-1]["period"] if series else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.inflation_indices.update_one(
        {"name": index_name}, {"$set": doc}, upsert=True,
    )
    logger.info("[inflation] %s atualizado: %s pontos · acc12m=%s%%",
                index_name, len(series), acc_12m)
    return doc


async def get_index(index_name: str = DEFAULT_INDEX,
                    auto_refresh: bool = True) -> Optional[Dict]:
    """Obtém o índice do cache. Refresh automático se mais velho que 24h."""
    doc = await db.inflation_indices.find_one(
        {"name": index_name}, {"_id": 0},
    )
    if not doc and auto_refresh:
        doc = await refresh_index_cache(index_name)
    elif doc and auto_refresh:
        # Refresh se cache > 24h
        try:
            updated = datetime.fromisoformat(doc["updated_at"])
            if datetime.now(timezone.utc) - updated > timedelta(hours=24):
                doc = await refresh_index_cache(index_name)
        except Exception:
            pass
    return doc


async def get_accumulated_for_period(
    index_name: str, start_period: str, end_period: str,
) -> float:
    """Retorna inflação acumulada entre 2 períodos (YYYY-MM inclusive).

    Ex.: start=2025-05, end=2026-04 → IPCA acumulado de 12 meses.
    Retorna em % (ex.: 4.62).
    """
    doc = await get_index(index_name)
    if not doc:
        return 0.0
    series = [s for s in (doc.get("series") or [])
              if start_period <= s["period"] <= end_period]
    if not series:
        return 0.0
    factor = 1.0
    for s in series:
        factor *= (1 + s["value"] / 100.0)
    return round((factor - 1) * 100, 4)
