"""Serviço de Reajuste Anual de Planos.

REGRAS REGULATÓRIAS (Anatel/SCM):
1. Periodicidade mínima: 12 meses após instalação ou último reajuste
2. Índice contratado: IPCA (padrão), IST, IGP-M ou IGP-DI
3. Cliente deve ser notificado com antecedência

LÓGICA:
- `installation_date` no subscriber define data-base
- `readjustment_index` (default IPCA) define qual índice usar
- Próximo reajuste = max(installation_date, last_readjustment_at) + 1 ano
- Valor novo = valor atual × (1 + inflação_acumulada_12m / 100)
- Log persistido em `subscriber_readjustments` (auditoria)
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from database import db
from services.inflation import (
    DEFAULT_INDEX,
    get_accumulated_for_period,
    get_index,
)

logger = logging.getLogger(__name__)


def _parse_iso(value) -> Optional[datetime]:
    """Aceita datetime, ISO string, ou None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _add_years(d: datetime, years: int) -> datetime:
    """Soma N anos preservando dia/mês (29/02 vira 28/02 em ano comum)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 fev em ano não bissexto
        return d.replace(year=d.year + years, day=28)


def compute_pending_anniversaries(sub: Dict) -> List[datetime]:
    """Lista TODAS as datas de aniversário (data-base + N anos)
    que já venceram e ainda não foram aplicadas.

    Exemplo: instalação 27/01/2021, last_readjustment_at = None,
    hoje = 06/02/2026 → retorna [27/01/2022, 27/01/2023, 27/01/2024,
    27/01/2025, 27/01/2026].

    Se houver `last_readjustment_at`, começa a contar a partir dele.
    """
    inst = _parse_iso(sub.get("installation_date"))
    last = _parse_iso(sub.get("last_readjustment_at"))
    base = last or inst
    if not base:
        return []

    today = datetime.now(timezone.utc)
    pending: List[datetime] = []
    for n in range(1, 30):  # até 30 anos
        anniv = _add_years(base, n)
        if anniv > today:
            break
        pending.append(anniv)
    return pending


def _next_readjustment_date(sub: Dict) -> Optional[datetime]:
    """Próxima virada (vencida ou futura).

    - Se houver virada vencida não aplicada, retorna a PRIMEIRA vencida.
    - Senão, retorna a próxima virada futura (base + 1 ano).
    """
    inst = _parse_iso(sub.get("installation_date"))
    last = _parse_iso(sub.get("last_readjustment_at"))
    base = last or inst
    if not base:
        return None
    pending = compute_pending_anniversaries(sub)
    if pending:
        return pending[0]
    # Nenhuma pendente: a próxima ainda futura
    today = datetime.now(timezone.utc)
    for n in range(1, 30):
        anniv = _add_years(base, n)
        if anniv > today:
            return anniv
    return base + timedelta(days=365)


async def _ipca_for_window(idx_name: str, start: datetime, end: datetime) -> float:
    """Calcula inflação acumulada entre 2 datas no índice escolhido.

    Janela: do mês seguinte ao `start` até o mês de `end` (inclusivo).
    Retorna em % (ex.: 4.62 = 4.62%).
    """
    # start = data-base (mês a NÃO incluir), end = data da virada
    # Janela correta: 12 meses imediatamente antes de `end`
    start_p = (_add_years(end, -1)).strftime("%Y-%m")
    end_p = end.strftime("%Y-%m")
    return await get_accumulated_for_period(idx_name, start_p, end_p)


async def calculate_readjustment_preview(
    subscriber: Dict, index_name: Optional[str] = None,
) -> Optional[Dict]:
    """Calcula PROJEÇÃO de reajuste sem aplicar.

    Suporta CASCATA: se houver múltiplas viradas anuais pendentes
    (cliente sem reajuste há vários anos), calcula o efeito acumulado
    aplicando o IPCA dos 12 meses anteriores a cada virada.

    Retorna:
      {
        "subscriber_id": ..., "name": ..., "current_price": 99.90,
        "index_name": "IPCA",
        "pending_count": 4,                       # qtas viradas vencidas
        "pending_anniversaries": ["2022-01-26", ...],
        "cascade": [                              # detalhamento por virada
          {"anniversary": "2022-01-26", "accumulated_pct": 10.06,
           "from_price": 99.90, "to_price": 109.95},
          ...
        ],
        "accumulated_pct_total": 25.31,           # efeito composto total
        "new_price": 125.18, "diff": 25.28,
        "next_readjustment_at": "2027-01-26",     # próxima futura
        "is_due": true,
        "base_date": "2021-01-27",
        "reason": "installation_date" | "last_readjustment_at"
      }
    """
    current_price = subscriber.get("plan_price")
    if current_price is None or current_price <= 0:
        return None

    inst = _parse_iso(subscriber.get("installation_date"))
    last = _parse_iso(subscriber.get("last_readjustment_at"))
    base = last or inst
    if not base:
        return None

    idx_name = (index_name or subscriber.get("readjustment_index")
                or DEFAULT_INDEX).upper()

    pending = compute_pending_anniversaries(subscriber)
    is_due = bool(pending)

    # Calcula cascata
    cascade = []
    price_running = float(current_price)
    for anniv in pending:
        acc_pct = await _ipca_for_window(idx_name, base, anniv)
        if acc_pct <= 0:
            # Fallback: usa acumulado 12m corrente do índice
            idx = await get_index(idx_name)
            acc_pct = (idx or {}).get("accumulated_12m") or 0.0
        from_p = round(price_running, 2)
        to_p = round(price_running * (1 + acc_pct / 100), 2)
        cascade.append({
            "anniversary": anniv.date().isoformat(),
            "accumulated_pct": acc_pct,
            "from_price": from_p,
            "to_price": to_p,
        })
        price_running = to_p

    # Próxima virada futura (após todas pendentes)
    if pending:
        next_after = _add_years(pending[-1], 1)
    else:
        # Calcula a próxima virada que ainda é futura
        next_after = _next_readjustment_date(subscriber) or base

    new_price = round(price_running, 2)
    total_pct = round(((new_price / float(current_price)) - 1) * 100, 4) \
        if current_price else 0.0

    return {
        "subscriber_id": subscriber.get("id"),
        "name": subscriber.get("name"),
        "external_code": subscriber.get("external_code"),
        "plan_name": subscriber.get("plan_name"),
        "current_price": round(float(current_price), 2),
        "index_name": idx_name,
        "pending_count": len(pending),
        "pending_anniversaries": [a.date().isoformat() for a in pending],
        "cascade": cascade,
        "accumulated_pct_total": total_pct,
        # Compat: campos antigos esperados por outros consumers
        "accumulated_pct": total_pct,
        "new_price": new_price,
        "diff": round(new_price - float(current_price), 2),
        "next_readjustment_at": next_after.isoformat(),
        "is_due": is_due,
        "base_date": base.isoformat(),
        "reason": "last_readjustment_at" if last else "installation_date",
    }


async def apply_readjustment(
    subscriber: Dict, actor: str = "system",
    index_name: Optional[str] = None, force: bool = False,
) -> Dict:
    """Aplica reajuste(s) pendente(s) no subscriber em cascata.

    Se `force=False`, só aplica se houver virada vencida (`is_due=True`).
    Se houver múltiplas viradas pendentes, aplica TODAS em cascata e
    grava um log por virada em `subscriber_readjustments`.
    """
    preview = await calculate_readjustment_preview(subscriber, index_name)
    if not preview:
        return {"applied": False, "reason": "no_plan_price_or_install_date"}

    if not preview["is_due"] and not force:
        return {"applied": False, "reason": "not_due_yet", "preview": preview}

    now_iso = datetime.now(timezone.utc).isoformat()
    cascade = preview.get("cascade") or []
    if not cascade and force:
        # force=True sem pendentes: aplica acumulado_12m do índice
        idx = await get_index(preview["index_name"])
        acc = (idx or {}).get("accumulated_12m") or 0.0
        from_p = preview["current_price"]
        to_p = round(from_p * (1 + acc / 100), 2)
        cascade = [{
            "anniversary": now_iso.split("T")[0],
            "accumulated_pct": acc,
            "from_price": from_p, "to_price": to_p,
        }]

    if not cascade:
        return {"applied": False, "reason": "no_pending_cascade",
                "preview": preview}

    log_ids = []
    for step in cascade:
        log_doc = {
            "id": f"radj-{uuid.uuid4().hex[:10]}",
            "subscriber_id": subscriber["id"],
            "company_id": subscriber.get("company_id"),
            "actor": actor,
            "applied_at": now_iso,
            "anniversary_date": step["anniversary"],
            "previous_price": step["from_price"],
            "new_price": step["to_price"],
            "diff": round(step["to_price"] - step["from_price"], 2),
            "index_name": preview["index_name"],
            "accumulated_pct": step["accumulated_pct"],
            "base_date": preview["base_date"],
            "trigger": "manual" if force else "auto",
        }
        await db.subscriber_readjustments.insert_one(log_doc)
        log_ids.append(log_doc["id"])

    final_price = cascade[-1]["to_price"]
    final_anniv = cascade[-1]["anniversary"]
    # last_readjustment_at = data da última virada aplicada (ISO)
    try:
        last_anniv_iso = datetime.fromisoformat(final_anniv).replace(
            tzinfo=timezone.utc).isoformat()
    except ValueError:
        last_anniv_iso = now_iso

    await db.subscribers.update_one(
        {"id": subscriber["id"]},
        {"$set": {
            "plan_price": final_price,
            "last_readjustment_at": last_anniv_iso,
            "last_readjustment_pct": preview["accumulated_pct_total"],
            "last_readjustment_value": final_price,
            "updated_at": now_iso,
        }},
    )

    logger.info("[readjustment] %s viradas aplicadas em %s: %.2f → %.2f (%.2f%%)",
                len(cascade), subscriber.get("name"),
                preview["current_price"], final_price,
                preview["accumulated_pct_total"])
    return {
        "applied": True, "log_ids": log_ids,
        "applied_count": len(cascade),
        "preview": preview,
        "final_price": final_price,
    }


async def list_due_subscribers(company_id: str,
                                horizon_days: int = 0) -> List[Dict]:
    """Lista assinantes com reajuste devido (ou que vão vencer em N dias).

    horizon_days=0 → só os já vencidos
    horizon_days=30 → vencidos + os que vencem nos próximos 30 dias
    """
    cursor = db.subscribers.find(
        {"company_id": company_id,
         "installation_date": {"$exists": True, "$ne": None},
         "status": {"$in": ["ATIVO", "ativo"]}},
        {"_id": 0},
    )
    today = datetime.now(timezone.utc)
    horizon = today + timedelta(days=horizon_days)
    items: List[Dict] = []
    async for sub in cursor:
        next_date = _next_readjustment_date(sub)
        if not next_date or next_date > horizon:
            continue
        preview = await calculate_readjustment_preview(sub)
        if preview:
            items.append(preview)
    return items


async def apply_all_due(company_id: str, actor: str = "system") -> Dict:
    """Aplica reajuste em TODOS os assinantes vencidos (cron-friendly)."""
    due = await list_due_subscribers(company_id, horizon_days=0)
    applied = 0
    total_diff = 0.0
    for item in due:
        sub = await db.subscribers.find_one({"id": item["subscriber_id"]},
                                             {"_id": 0})
        if not sub:
            continue
        result = await apply_readjustment(sub, actor=actor)
        if result.get("applied"):
            applied += 1
            total_diff += (item.get("diff") or 0.0)
    return {
        "total_due": len(due),
        "applied": applied,
        "total_revenue_increase": round(total_diff, 2),
    }
