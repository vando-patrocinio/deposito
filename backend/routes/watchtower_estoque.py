"""Watchtower Estoque — Dashboard Executivo Patrimonial

Sprint 1 (CEO 16/02/2026): visibilidade do patrimônio Ligo em 10 segundos.

Endpoint único `GET /api/watchtower/estoque/summary` retorna o pacote
completo agregado — 4 cards do CEO:
  1. PATRIMÔNIO TOTAL (auditável + especulativo + confiança%)
  2. ONTs por LOCAL (empresa / técnicos / clientes / defeito / descarte)
  3. QUALIDADE DOS DADOS (Grade A / B / C / D / F)
  4. ALERTAS (AUTOSN, needs_review, sem_trilha, reconciliações, duplicadas)

Definições aprovadas pelo CEO:
  - Auditável = Grades A + B
  - Especulativo = Grades C + D + F
  - Confiança = auditável / total * 100

Janela do gráfico de evolução: 12 meses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.inventory_valuation import effective_value

NERVOUS_METADATA = {
    "owner": "executive",
    "domain": "patrimonio",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

logger = logging.getLogger("watchtower.estoque")
router = APIRouter(prefix="/api/watchtower/estoque", tags=["watchtower_estoque"])


# Cache simples em memória (60s) — agregação é lenta em bases grandes
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SEC = 60


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cache_key(cid: str) -> str:
    return f"summary:{cid}"


def _cache_get(cid: str) -> Optional[Dict[str, Any]]:
    item = _cache.get(_cache_key(cid))
    if not item:
        return None
    if (_now_utc() - item["at"]).total_seconds() > _CACHE_TTL_SEC:
        return None
    return item["data"]


def _cache_set(cid: str, data: Dict[str, Any]) -> None:
    _cache[_cache_key(cid)] = {"at": _now_utc(), "data": data}


# ═══════════ Agregações (raw queries) ═══════════════════════════════════════

async def _agg_total_and_location(company_id: str) -> Dict[str, Any]:
    """Contagem por location_type."""
    pipeline = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": "$location_type", "n": {"$sum": 1}}},
    ]
    rows = await db.stok_onts.aggregate(pipeline).to_list(20)
    out = {"empresa": 0, "tecnico": 0, "cliente": 0,
           "defeito": 0, "descarte": 0, "outros": 0, "total": 0}
    for r in rows:
        loc = (r.get("_id") or "outros").lower()
        if loc not in out:
            loc = "outros"
        out[loc] = int(r.get("n") or 0)
        out["total"] += int(r.get("n") or 0)
    return out


async def _agg_grades(company_id: str) -> Dict[str, Any]:
    """Contagem por valuation_grade."""
    pipeline = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": "$valuation_grade", "n": {"$sum": 1}}},
    ]
    rows = await db.stok_onts.aggregate(pipeline).to_list(20)
    grades = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "unknown": 0}
    for r in rows:
        g = (r.get("_id") or "unknown")
        if g not in grades:
            g = "unknown"
        grades[g] = int(r.get("n") or 0)
    return grades


async def _agg_patrimony(company_id: str) -> Dict[str, Any]:
    """Soma valor por grade. Patrimônio auditável (A+B) vs especulativo (C+D+F)."""
    cursor = db.stok_onts.find(
        {"company_id": company_id,
         "location_type": {"$in": ["empresa", "tecnico", "cliente"]}},
        {"_id": 0, "valuation_grade": 1, "valor_nf": 1,
         "valor_medio_ponderado": 1, "valor_referencia": 1},
    )
    total_auditavel = 0.0
    total_especulativo = 0.0
    n_auditavel = 0
    n_especulativo = 0
    async for d in cursor:
        try:
            v = effective_value(d)
        except Exception:
            v = 0.0
        g = (d.get("valuation_grade") or "F")
        if g in ("A", "B"):
            total_auditavel += v
            n_auditavel += 1
        else:
            total_especulativo += v
            n_especulativo += 1
    total = total_auditavel + total_especulativo
    confianca = round((total_auditavel / total * 100), 1) if total > 0 else 0.0
    return {
        "total": round(total, 2),
        "auditavel": round(total_auditavel, 2),
        "especulativo": round(total_especulativo, 2),
        "confianca_pct": confianca,
        "n_auditavel": n_auditavel,
        "n_especulativo": n_especulativo,
    }


async def _agg_alerts(company_id: str) -> Dict[str, Any]:
    """Conta alertas operacionais P0."""
    cutoff_30d = (_now_utc() - timedelta(days=30)).isoformat()
    autosn = await db.stok_onts.count_documents({
        "company_id": company_id,
        "$or": [
            {"sn_auto_generated": True},
            {"mac": {"$regex": "^AUTOSN_"}},
            {"mac": {"$regex": "^MANUAL-"}},
            {"mac": {"$regex": "^SEM-MAC-"}},
        ],
    })
    needs_review = await db.stok_onts.count_documents({
        "company_id": company_id,
        "valuation_needs_human_review": True,
    })
    # sem_trilha = ONT existente mas sem nenhum doc em inventory_os_movements_audit
    # Aproximação: contar ONTs ativas que NÃO têm `valuation_genesis_at` (criadas
    # antes do hook R1.4) — proxy de "sem trilha de genesis canônica".
    sem_trilha = await db.stok_onts.count_documents({
        "company_id": company_id,
        "location_type": {"$in": ["empresa", "tecnico", "cliente"]},
        "valuation_genesis_at": {"$exists": False},
    })
    reconciliacoes_30d = await db.inventory_os_movements_audit.count_documents({
        "company_id": company_id,
        "movement_type": "reconciliation_smartolt_sync",
        "performed_at": {"$gte": cutoff_30d},
    })
    # Duplicadas: MACs repetidos (mesmo company_id)
    dup_pipe = [
        {"$match": {"company_id": company_id, "mac": {"$ne": None}}},
        {"$group": {"_id": "$mac", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$count": "duplicadas"},
    ]
    dup_rows = await db.stok_onts.aggregate(dup_pipe).to_list(2)
    duplicadas = int(dup_rows[0]["duplicadas"]) if dup_rows else 0
    return {
        "autosn": autosn,
        "needs_review": needs_review,
        "sem_trilha": sem_trilha,
        "reconciliacoes_30d": reconciliacoes_30d,
        "duplicadas": duplicadas,
        "total": autosn + needs_review + sem_trilha + reconciliacoes_30d + duplicadas,
    }


async def _agg_evolution_12m(company_id: str) -> List[Dict[str, Any]]:
    """Patrimônio mensal últimos 12 meses (proxy via created_at + valor efetivo).

    Versão 1: usa `created_at` da ONT como timestamp. Não captura
    movimentações intra-mês (futuro: usar inventory_os_movements_audit).
    """
    now = _now_utc()
    months: List[Dict[str, Any]] = []
    for offset in range(11, -1, -1):
        # primeiro dia do mês offset meses atrás
        month_anchor = (now.replace(day=1) - timedelta(days=offset * 30))
        m_year = month_anchor.year
        m_month = month_anchor.month
        # next month
        if m_month == 12:
            next_anchor = month_anchor.replace(year=m_year + 1, month=1, day=1)
        else:
            next_anchor = month_anchor.replace(month=m_month + 1, day=1)
        month_anchor_iso = month_anchor.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        next_anchor_iso = next_anchor.replace(
            hour=0, minute=0, second=0, microsecond=0).isoformat()
        # Conta ONTs criadas ATÉ o fim do mês (snapshot cumulativo)
        cum_count = await db.stok_onts.count_documents({
            "company_id": company_id,
            "created_at": {"$lt": next_anchor_iso},
        })
        # Soma valor ATÉ o fim do mês (snapshot cumulativo simplificado)
        cum_value = 0.0
        cursor = db.stok_onts.find(
            {"company_id": company_id,
             "created_at": {"$lt": next_anchor_iso}},
            {"_id": 0, "valuation_grade": 1, "valor_nf": 1,
             "valor_medio_ponderado": 1, "valor_referencia": 1},
        )
        async for d in cursor:
            try:
                cum_value += effective_value(d)
            except Exception:
                continue
        months.append({
            "month": f"{m_year:04d}-{m_month:02d}",
            "month_start": month_anchor_iso,
            "cum_count": cum_count,
            "cum_value": round(cum_value, 2),
        })
    return months


# ═══════════ Endpoint único ═════════════════════════════════════════════════

@router.get("/summary")
async def watchtower_summary(
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
    fresh: bool = Query(False, description="Ignora cache (60s)"),
    company_id_override: Optional[str] = Query(None,
        description="Apenas super_admin — força outro company_id"),
) -> Dict[str, Any]:
    """Retorna pacote executivo completo (4 cards) numa única chamada."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if company_id_override and user.get("is_super_admin"):
        cid = company_id_override
    if not fresh:
        cached = _cache_get(cid)
        if cached:
            return {**cached, "cache_hit": True}

    location, grades, patrimony, alerts, evolution = await _safe_gather(
        _agg_total_and_location(cid),
        _agg_grades(cid),
        _agg_patrimony(cid),
        _agg_alerts(cid),
        _agg_evolution_12m(cid),
    )

    # Delta mensal (último vs anterior)
    delta_value = None
    delta_pct = None
    if len(evolution) >= 2:
        prev = evolution[-2]["cum_value"]
        curr = evolution[-1]["cum_value"]
        if prev > 0:
            delta_value = round(curr - prev, 2)
            delta_pct = round((curr - prev) / prev * 100, 1)

    payload = {
        "company_id": cid,
        "generated_at": _now_utc().isoformat(),
        "cache_hit": False,
        # Card 1 — Patrimônio
        "patrimonio": {
            **patrimony,
            "delta_mom_value": delta_value,
            "delta_mom_pct": delta_pct,
            "evolution_12m": evolution,
        },
        # Card 2 — ONTs por Local
        "operacao": location,
        # Card 3 — Qualidade dos Dados
        "qualidade": {
            **grades,
            "auditavel_count": grades["A"] + grades["B"],
            "especulativo_count": grades["C"] + grades["D"] + grades["F"],
        },
        # Card 4 — Alertas
        "alertas": alerts,
    }
    _cache_set(cid, payload)
    return payload


async def _safe_gather(*coros):
    """gather + isolar erros (uma agregação que quebra não derruba o dashboard)."""
    import asyncio
    results = await asyncio.gather(*coros, return_exceptions=True)
    out = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("[watchtower] sub-agg falhou: %s", r)
            out.append({})
        else:
            out.append(r)
    return out
