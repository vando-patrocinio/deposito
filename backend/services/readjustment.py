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


def _next_readjustment_date(sub: Dict) -> Optional[datetime]:
    """Calcula próxima data de reajuste do assinante.

    base = max(installation_date, last_readjustment_at)
    next = base + 365 dias
    """
    inst = _parse_iso(sub.get("installation_date"))
    last = _parse_iso(sub.get("last_readjustment_at"))
    base = max(filter(None, [inst, last]), default=None)
    if not base:
        return None
    return base + timedelta(days=365)


async def calculate_readjustment_preview(
    subscriber: Dict, index_name: Optional[str] = None,
) -> Optional[Dict]:
    """Calcula PROJEÇÃO de reajuste sem aplicar.

    Retorna:
      {
        "subscriber_id": ..., "name": ..., "current_price": 99.90,
        "index_name": "IPCA", "accumulated_pct": 4.62,
        "new_price": 104.51, "diff": 4.61,
        "next_readjustment_at": "2027-05-18", "is_due": false,
        "base_date": "2026-05-18", "reason": "installation_date"
      }
    """
    current_price = subscriber.get("plan_price")
    if current_price is None or current_price <= 0:
        return None

    next_date = _next_readjustment_date(subscriber)
    if not next_date:
        return None

    idx_name = (index_name or subscriber.get("readjustment_index")
                or DEFAULT_INDEX).upper()
    today = datetime.now(timezone.utc)
    is_due = today >= next_date

    # Janela de inflação: 12 meses anteriores à data-base
    base = max(
        filter(None, [_parse_iso(subscriber.get("installation_date")),
                       _parse_iso(subscriber.get("last_readjustment_at"))]),
        default=None,
    )
    if not base:
        return None

    end = next_date - timedelta(days=1)
    start = base
    # Convertendo pra YYYY-MM
    start_p = start.strftime("%Y-%m")
    end_p = end.strftime("%Y-%m")

    acc_pct = await get_accumulated_for_period(idx_name, start_p, end_p)
    if acc_pct <= 0:
        # Fallback: acumulado 12m do índice (sempre disponível)
        idx = await get_index(idx_name)
        acc_pct = (idx or {}).get("accumulated_12m") or 0.0

    new_price = round(current_price * (1 + acc_pct / 100), 2)
    return {
        "subscriber_id": subscriber.get("id"),
        "name": subscriber.get("name"),
        "external_code": subscriber.get("external_code"),
        "plan_name": subscriber.get("plan_name"),
        "current_price": round(current_price, 2),
        "index_name": idx_name,
        "accumulated_pct": acc_pct,
        "new_price": new_price,
        "diff": round(new_price - current_price, 2),
        "next_readjustment_at": next_date.isoformat(),
        "is_due": is_due,
        "base_date": base.isoformat(),
        "reason": "last_readjustment_at" if subscriber.get(
            "last_readjustment_at") else "installation_date",
    }


async def apply_readjustment(
    subscriber: Dict, actor: str = "system",
    index_name: Optional[str] = None, force: bool = False,
) -> Dict:
    """Aplica reajuste no subscriber e persiste log.

    Se `force=False`, só aplica se `is_due=True` (data alcançada).
    """
    preview = await calculate_readjustment_preview(subscriber, index_name)
    if not preview:
        return {"applied": False, "reason": "no_plan_price_or_install_date"}

    if not preview["is_due"] and not force:
        return {"applied": False, "reason": "not_due_yet", "preview": preview}

    now = datetime.now(timezone.utc).isoformat()
    log_doc = {
        "id": f"radj-{uuid.uuid4().hex[:10]}",
        "subscriber_id": subscriber["id"],
        "company_id": subscriber.get("company_id"),
        "actor": actor,
        "applied_at": now,
        "previous_price": preview["current_price"],
        "new_price": preview["new_price"],
        "diff": preview["diff"],
        "index_name": preview["index_name"],
        "accumulated_pct": preview["accumulated_pct"],
        "base_date": preview["base_date"],
        "trigger": "manual" if force else "auto",
    }
    await db.subscriber_readjustments.insert_one(log_doc)

    await db.subscribers.update_one(
        {"id": subscriber["id"]},
        {"$set": {
            "plan_price": preview["new_price"],
            "last_readjustment_at": now,
            "last_readjustment_pct": preview["accumulated_pct"],
            "last_readjustment_value": preview["new_price"],
            "updated_at": now,
        }},
    )

    logger.info("[readjustment] aplicado a %s: %.2f → %.2f (%.2f%%)",
                subscriber.get("name"), preview["current_price"],
                preview["new_price"], preview["accumulated_pct"])
    return {"applied": True, "log_id": log_doc["id"], "preview": preview}


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
