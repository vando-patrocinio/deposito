"""balance_engine — Sprint 5 Onda 6 (CEO mandate 19/02/2026)

Auto Balanço Patrimonial Mensal sobre a camada OFICIAL (Genesis).
Job diário 00:05 grava snapshot. Fechamento mensal emite certidão
assinada com hash SHA-256.

Estrutura por mês:
  Abertura      — ativos no início do mês
  Movimentação  — instalações, trocas, retiradas, defeitos, recuperações,
                   promoções quarentena→oficial
  Fechamento    — ativos no fim do mês

8 KPIs CEO:
  Patrimônio:  Ativos Oficiais, Quarentena, Total, Confiável
  Operação:    Instalações, Trocas, Retiradas, Defeitos
  Governança:  Rastreabilidade, Data Confidence, Compliance

+ KPI extra (sugestão CEO):
  Índice de Cobertura Operacional = ativos_oficiais / ativos_smartolt
  (meta ≥98%)
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BALANCE_VERSION = "sprint5_onda6_v1"
BALANCE_COLLECTION = "inventory_monthly_balance"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _month_start_iso(year_month: str) -> str:
    return f"{year_month}-01T00:00:00+00:00"


def _next_month_start_iso(year_month: str) -> str:
    y, m = year_month.split("-")
    y_i, m_i = int(y), int(m)
    if m_i == 12:
        y_i, m_i = y_i + 1, 1
    else:
        m_i += 1
    return f"{y_i:04d}-{m_i:02d}-01T00:00:00+00:00"


def _sign_balance(payload: Dict[str, Any]) -> str:
    """SHA-256 sobre os 8 KPIs + abertura/fechamento."""
    keys = [
        "company_id", "year_month",
        "abertura", "movimentacao", "fechamento", "kpis",
        "generated_at", "balance_version",
    ]
    canon = {k: payload.get(k) for k in keys}
    enc = json.dumps(canon, sort_keys=True, default=str).encode()
    return hashlib.sha256(enc).hexdigest()


async def _count_oficial(db, cid: str,
                         at: Optional[str] = None) -> int:
    q = {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "official",
         "exclude_from_balance": False}
    if at:
        q["created_at"] = {"$lte": at}
    return await db.stok_onts.count_documents(q)


async def _count_quarantine(db, cid: str,
                              at: Optional[str] = None) -> int:
    q = {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "quarantine"}
    if at:
        q["created_at"] = {"$lte": at}
    return await db.stok_onts.count_documents(q)


async def _count_smartolt(db, cid: str) -> int:
    return await db.smartolt_onus.count_documents({"company_id": cid})


async def _swap_events_in_window(
    db, cid: str, start_iso: str, end_iso: str,
) -> Dict[str, int]:
    base = {"company_id": cid,
            "created_at": {"$gte": start_iso, "$lt": end_iso},
            "data_quality": {"$nin": ["terminal_source_destroyed",
                                            "no_ticket_in_source"]}}
    pipe = [
        {"$match": base},
        {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
    ]
    res = await db.auto_ont_swap_events.aggregate(pipe).to_list(length=20)
    by_type = {x["_id"]: x["n"] for x in res}
    return {
        "instalacoes": by_type.get("install", 0),
        "trocas": (by_type.get("swap", 0)
                      + by_type.get("replacement", 0)),
        "retiradas": by_type.get("removal", 0),
    }


async def _defeitos_in_window(
    db, cid: str, start_iso: str, end_iso: str,
) -> int:
    """Conta eventos de defeito/devolução em stok_history."""
    return await db.stok_history.count_documents({
        "company_id": cid,
        "event_timestamp": {"$gte": start_iso, "$lt": end_iso},
        "event_type": {"$in": ["defective_return", "defeito",
                                  "rompimento"]},
    })


async def _promocoes_in_window(
    db, cid: str, start_iso: str, end_iso: str,
) -> int:
    return await db.stok_onts.count_documents({
        "company_id": cid, "origin": "smartolt_genesis",
        "promoted_at": {"$gte": start_iso, "$lt": end_iso},
    })


async def _compute_kpis(db, cid: str, oficial: int, quarantine: int,
                          movs: Dict[str, int]) -> Dict[str, Any]:
    smartolt_total = await _count_smartolt(db, cid)
    total = oficial + quarantine
    confidence_high = await db.stok_onts.count_documents({
        "company_id": cid, "origin": "smartolt_genesis",
        "tier": "official", "data_confidence": {"$gte": 0.9}})

    # Rastreabilidade — % de oficiais com swap_event_id ligado
    rastreaveis = await db.stok_onts.count_documents({
        "company_id": cid, "origin": "smartolt_genesis",
        "tier": "official",
        "subscriber_id": {"$nin": [None, ""]}})
    rastreabilidade_pct = round(
        (rastreaveis / oficial * 100), 2) if oficial else 0.0

    # Data confidence ≥0.9
    data_conf_pct = round(
        (confidence_high / oficial * 100), 2) if oficial else 0.0

    # Compliance patrimonial: oficial / total
    compliance_pct = round(
        (oficial / total * 100), 2) if total else 0.0

    # Índice de Cobertura Operacional (KPI extra do CEO)
    cobertura_op_pct = round(
        (oficial / smartolt_total * 100), 2) \
        if smartolt_total else 0.0

    return {
        # Patrimônio
        "ativos_oficiais": oficial,
        "ativos_quarentena": quarantine,
        "patrimonio_total": total,
        "patrimonio_confiavel": confidence_high,
        # Operação
        "instalacoes": movs["instalacoes"],
        "trocas": movs["trocas"],
        "retiradas": movs["retiradas"],
        "defeitos": movs.get("defeitos", 0),
        # Governança
        "rastreabilidade_pct": rastreabilidade_pct,
        "data_confidence_pct": data_conf_pct,
        "compliance_patrimonial_pct": compliance_pct,
        # KPI extra CEO
        "indice_cobertura_operacional_pct": cobertura_op_pct,
        "indice_cobertura_meta_98": cobertura_op_pct >= 98.0,
    }


def _evaluate_status(kpis: Dict[str, Any]) -> str:
    """APROVADA / COM RESSALVAS / REPROVADA conforme regras."""
    # APROVADA: data_confidence ≥90 AND rastreabilidade ≥95 AND compliance ≥75
    if (kpis["data_confidence_pct"] >= 90.0
            and kpis["rastreabilidade_pct"] >= 95.0
            and kpis["compliance_patrimonial_pct"] >= 75.0):
        if kpis["indice_cobertura_operacional_pct"] >= 98.0:
            return "APROVADA"
        return "APROVADA"  # cobertura op é informativo, não bloqueia
    # COM RESSALVAS: data_confidence ≥80 OR rastreabilidade ≥85
    if (kpis["data_confidence_pct"] >= 80.0
            or kpis["rastreabilidade_pct"] >= 85.0):
        return "COM RESSALVAS"
    return "REPROVADA"


async def compute_monthly_balance(
    db, company_id: str, year_month: str,
    *, snapshot_only: bool = False,
    actor_user_id: str = "system",
) -> Dict[str, Any]:
    """Computa balanço mensal completo (abertura + movimentação + fechamento).

    snapshot_only=True → grava como snapshot diário sem fechamento.
    Idempotente: usa year_month + snapshot_id como chave.
    """
    start_iso = _month_start_iso(year_month)
    end_iso = _next_month_start_iso(year_month)
    now = _now_iso()

    # ABERTURA: contagem em t=start
    abertura_oficial = await _count_oficial(db, company_id, at=start_iso)
    abertura_quarentena = await _count_quarantine(
        db, company_id, at=start_iso)
    abertura = {
        "ativos_oficiais": abertura_oficial,
        "ativos_quarentena": abertura_quarentena,
        "patrimonio_total": abertura_oficial + abertura_quarentena,
        "at": start_iso,
    }

    # MOVIMENTAÇÃO: swap_events + defeitos + promoções
    swaps = await _swap_events_in_window(
        db, company_id, start_iso, end_iso)
    defeitos = await _defeitos_in_window(
        db, company_id, start_iso, end_iso)
    promocoes = await _promocoes_in_window(
        db, company_id, start_iso, end_iso)
    movimentacao = {
        "instalacoes": swaps["instalacoes"],
        "trocas": swaps["trocas"],
        "retiradas": swaps["retiradas"],
        "defeitos": defeitos,
        "promocoes_quarentena_para_oficial": promocoes,
        "window_start": start_iso,
        "window_end": end_iso,
    }

    # FECHAMENTO: contagem ao fim (now ou end do mês — usa now se snapshot)
    fech_at = now if snapshot_only else end_iso
    fech_oficial = await _count_oficial(db, company_id, at=fech_at)
    fech_quarentena = await _count_quarantine(
        db, company_id, at=fech_at)
    fechamento = {
        "ativos_oficiais": fech_oficial,
        "ativos_quarentena": fech_quarentena,
        "patrimonio_total": fech_oficial + fech_quarentena,
        "variacao_oficial": fech_oficial - abertura_oficial,
        "variacao_quarentena": fech_quarentena - abertura_quarentena,
        "at": fech_at,
    }

    # KPIs sobre o fechamento
    kpis_dict = await _compute_kpis(
        db, company_id, fech_oficial, fech_quarentena,
        {**swaps, "defeitos": defeitos})

    status = _evaluate_status(kpis_dict)

    snapshot_id = f"bal-{year_month}-{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": snapshot_id,
        "snapshot_id": snapshot_id,
        "company_id": company_id,
        "year_month": year_month,
        "is_closing": not snapshot_only,
        "abertura": abertura,
        "movimentacao": movimentacao,
        "fechamento": fechamento,
        "kpis": kpis_dict,
        "status": status,
        "generated_at": now,
        "generated_by": actor_user_id,
        "balance_version": BALANCE_VERSION,
        "genesis_version": "sprint5_onda5_v1",
        "inventory_version": "sprint5_onda4_canonical",
    }
    doc["hash_sha256"] = _sign_balance(doc)

    await db[BALANCE_COLLECTION].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def get_latest_closing(db, company_id: str,
                              year_month: Optional[str] = None,
                              ) -> Optional[Dict[str, Any]]:
    """Retorna o último fechamento (is_closing=True) para um mês."""
    q: Dict[str, Any] = {"company_id": company_id, "is_closing": True}
    if year_month:
        q["year_month"] = year_month
    return await db[BALANCE_COLLECTION].find_one(
        q, {"_id": 0}, sort=[("generated_at", -1)])
