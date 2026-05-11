"""Churn Briefing Scheduler — geração automática diária de briefing.

Roda em loop e dispara a geração quando o relógio chega na hora-alvo
(configurável por empresa em `churn_briefing_schedule`).

Para cada empresa habilitada:
  1. Gera briefing via Motor IA (Claude Sonnet 4.5) — reusa lógica de churn.py
  2. Salva em `churn_insights` (mesma coleção que o endpoint manual)
  3. Se houver telefone configurado, envia resumo curto via WhatsApp Baileys
  4. Marca `last_run_date` pra não rodar duas vezes no mesmo dia

Config (Mongo): `churn_briefing_schedule` doc por company_id:
  {
    company_id, enabled, hour_utc (0-23), minute (0-59),
    notify_phone, window_days, last_run_date, updated_at, updated_by
  }

Default: 12:00 UTC ≈ 09:00 BRT (UTC-3).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from core import DEMO_COMPANY_ID, now_iso
from database import db
from services.motor_ia import chat_completion, AgentDisabledError

logger = logging.getLogger("churn_scheduler")

CHECK_INTERVAL_SECONDS = 60     # checa a cada 1min se hit a hora
SIDECAR_BASE = os.environ.get("WHATSAPP_SIDECAR_BASE", "http://127.0.0.1:3002")
WHATSAPP_SEND_TIMEOUT = 12.0


# ---------------------------------------------------------------------------
# Geração do briefing (versão para uso fora de request HTTP)
# ---------------------------------------------------------------------------
async def _generate_and_save(company_id: str, days: int) -> Optional[Dict[str, Any]]:
    """Reusa lógica de churn.py:churn_dashboard sem passar pelo Depends.
    Retorna o doc salvo, ou None se algum erro acontecer."""
    # Importação lazy para evitar ciclo com server.py
    from routes.churn import (
        _classify_kind, _classify_reason, _month_key, _parse_iso,
        FINAL_STATUSES, PENDING_STATUSES,
    )

    from datetime import timedelta
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_match = {
        "company_id": company_id,
        "type": "retirada",
        "created_at": {"$gte": cutoff_iso},
    }
    tickets = await db.tickets.find(
        base_match,
        {"_id": 0, "id": 1, "client_id": 1, "client_snapshot": 1, "status": 1,
         "created_at": 1, "closed_at": 1, "atlaz_assunto": 1, "atlaz_filial": 1,
         "atlaz_id_assinante": 1},
    ).sort("created_at", -1).to_list(5000)

    by_month: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    by_neigh: Dict[str, int] = {}
    by_kind = {"cancelamento": 0, "retirada": 0}
    finalized = 0
    pending = 0

    for t in tickets:
        status = (t.get("status") or "").lower()
        is_final = status in FINAL_STATUSES
        is_pending = status in PENDING_STATUSES
        if is_final:
            finalized += 1
        elif is_pending:
            pending += 1
        when = t.get("closed_at") if is_final else t.get("created_at")
        mk = _month_key(when or "")
        if mk:
            by_month[mk] = by_month.get(mk, 0) + 1
        by_reason[_classify_reason(t)] = by_reason.get(_classify_reason(t), 0) + 1
        neigh = ((t.get("client_snapshot") or {}).get("neighborhood") or "—").strip() or "—"
        by_neigh[neigh] = by_neigh.get(neigh, 0) + 1
        by_kind[_classify_kind(t)] += 1

    try:
        total_subscribers = await db.subscribers.count_documents({"company_id": company_id})
    except Exception:
        total_subscribers = 0
    churn_rate = round(
        (finalized / max(1, total_subscribers + finalized)) * 100, 2
    ) if total_subscribers > 0 else 0.0

    top_reasons_list = [{"label": k, "count": v}
                          for k, v in sorted(by_reason.items(), key=lambda x: -x[1])[:5]]
    top_neigh_list = [{"label": k, "count": v}
                        for k, v in sorted(by_neigh.items(), key=lambda x: -x[1])[:5]]

    top_reasons_str = ", ".join(f"{r['label']} ({r['count']})" for r in top_reasons_list) or "—"
    top_neigh_str = ", ".join(f"{n['label']} ({n['count']})" for n in top_neigh_list) or "—"

    prompt = f"""Você é um analista sênior de retenção de clientes para um provedor de internet.
Snapshot do dashboard de churn (últimos {days} dias):

- Churn total: {len(tickets)} (finalizados {finalized}, pendentes {pending})
- Taxa estimada: {churn_rate}% sobre {total_subscribers} assinantes ativos
- Pedidos vs Operação: cancelamento={by_kind['cancelamento']} / retirada={by_kind['retirada']}
- Top motivos: {top_reasons_str}
- Top bairros: {top_neigh_str}

Gere um briefing executivo em pt-BR, MÁXIMO 4 parágrafos curtos, usando markdown leve. Use estes títulos:
**Diagnóstico** (1 parágrafo do quadro atual)
**Padrões** (1 parágrafo sobre concentrações)
**Riscos** (1 parágrafo sobre pipeline pendente)
**Recomendações** (3-4 bullets acionáveis)

NÃO invente dados. Linguagem direta."""

    try:
        result = await chat_completion(
            company_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900, temperature=0.35,
            agent="churn_insight",
        )
    except AgentDisabledError:
        logger.warning("[churn-scheduler] agent churn_insight desligado p/ %s", company_id)
        return None
    except Exception as e:
        logger.exception("[churn-scheduler] falha chat_completion: %s", e)
        return None

    today = datetime.now(timezone.utc).date().isoformat()
    record_id = f"ci-{company_id}-{today}-{days}"
    doc = {
        "id": record_id,
        "company_id": company_id,
        "date": today,
        "window_days": days,
        "insight": result.get("content"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "based_on": {
            "total_churn": len(tickets),
            "churn_rate_pct": churn_rate,
            "top_reason": top_reasons_list[0]["label"] if top_reasons_list else None,
            "top_neighborhood": top_neigh_list[0]["label"] if top_neigh_list else None,
            "by_reason": top_reasons_list,
            "by_neighborhood": top_neigh_list,
            "by_kind": by_kind,
            "avg_lifetime_days": None,
        },
        "generated_at": now_iso(),
        "generated_by": "scheduler",
    }
    await db.churn_insights.update_one(
        {"id": record_id}, {"$set": doc}, upsert=True,
    )
    logger.info("[churn-scheduler] briefing gerado %s (churn=%d)", record_id, len(tickets))
    return doc


# ---------------------------------------------------------------------------
# Resumo curto para WhatsApp
# ---------------------------------------------------------------------------
def _build_whatsapp_summary(doc: Dict[str, Any]) -> str:
    """Constrói uma mensagem curta (< 800 chars) extraída do briefing.

    Estratégia: pega o trecho de **Recomendações** + KPIs principais."""
    insight = (doc.get("insight") or "").strip()
    based = doc.get("based_on") or {}
    # Extrai bullets de recomendações
    rec_match = re.search(
        r"\*\*Recomenda[cç][oõ]es\*\*[:\n]+(.+?)(?=\n\*\*|\Z)",
        insight, flags=re.DOTALL | re.IGNORECASE,
    )
    rec_text = ""
    if rec_match:
        bullets = re.findall(r"^[\-\*]\s+(.+)$", rec_match.group(1), flags=re.M)
        rec_text = "\n".join(f"• {b.strip()[:140]}" for b in bullets[:3])

    top_r = based.get("top_reason") or "—"
    top_n = based.get("top_neighborhood") or "—"
    rate = based.get("churn_rate_pct") or 0
    total = based.get("total_churn") or 0

    return (
        f"📊 *Briefing de Churn — {doc.get('date')}*\n"
        f"_(janela {doc.get('window_days')} dias · Claude Sonnet 4.5)_\n\n"
        f"• Total: *{total}* churn(s)  |  Taxa estimada: *{rate}%*\n"
        f"• Top motivo: *{top_r}*\n"
        f"• Top bairro: *{top_n}*\n\n"
        + (f"*Recomendações prioritárias:*\n{rec_text}\n\n" if rec_text else "")
        + "Veja análise completa: Central IA → Churn → Analisar com IA"
    )


async def _send_whatsapp(phone: str, text: str) -> bool:
    """Envia mensagem via sidecar Baileys. Best-effort (não bloqueia)."""
    try:
        async with httpx.AsyncClient(timeout=WHATSAPP_SEND_TIMEOUT) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                 json={"phone": phone, "text": text})
            data = {}
            try:
                data = r.json()
            except Exception:
                data = {}
            ok = r.status_code < 400 and data.get("ok")
            if not ok:
                logger.warning(
                    "[churn-scheduler] WA send falhou: status=%s body=%s",
                    r.status_code, data.get("error") or "")
            return bool(ok)
    except Exception as e:
        logger.warning("[churn-scheduler] WA send exc: %s", e)
        return False


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None


async def _process_schedule(cfg: Dict[str, Any]) -> None:
    """Decide se está na hora de rodar e executa.

    Idempotente: usa `last_run_date` (string YYYY-MM-DD) pra garantir 1x/dia.
    """
    cid = cfg.get("company_id")
    if not cid or not cfg.get("enabled"):
        return
    now = datetime.now(timezone.utc)
    target_hour = int(cfg.get("hour_utc", 12))
    target_min = int(cfg.get("minute", 0))
    today_iso = now.date().isoformat()
    if cfg.get("last_run_date") == today_iso:
        return  # já rodou hoje
    # Janela: rodamos se hora atual >= alvo
    if now.hour < target_hour or (now.hour == target_hour and now.minute < target_min):
        return

    days = int(cfg.get("window_days", 30))
    logger.info("[churn-scheduler] disparando p/ %s (janela %dd)", cid, days)
    doc = await _generate_and_save(cid, days)
    sent_phone: Optional[str] = None
    sent_ok = False
    if doc:
        phone = (cfg.get("notify_phone") or "").strip()
        if phone:
            summary = _build_whatsapp_summary(doc)
            sent_ok = await _send_whatsapp(phone, summary)
            sent_phone = phone

    # Marca como executado (mesmo se falhou — evita loop)
    await db.churn_briefing_schedule.update_one(
        {"company_id": cid},
        {"$set": {
            "last_run_date": today_iso,
            "last_run_at": now_iso(),
            "last_insight_id": doc.get("id") if doc else None,
            "last_whatsapp_sent": bool(sent_ok),
            "last_whatsapp_phone": sent_phone,
        }},
    )


async def _worker_loop():
    while True:
        try:
            cursor = db.churn_briefing_schedule.find(
                {"enabled": True}, {"_id": 0})
            async for cfg in cursor:
                try:
                    await _process_schedule(cfg)
                except Exception as e:
                    logger.exception(
                        "[churn-scheduler] erro processando %s: %s",
                        cfg.get("company_id"), e)
        except Exception as e:
            logger.exception("[churn-scheduler] worker loop err: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[churn-scheduler] worker iniciado (check %ds)",
                  CHECK_INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()


# ---------------------------------------------------------------------------
# Helpers para os endpoints REST
# ---------------------------------------------------------------------------
async def get_schedule(company_id: str) -> Dict[str, Any]:
    doc = await db.churn_briefing_schedule.find_one(
        {"company_id": company_id}, {"_id": 0})
    if not doc:
        doc = {
            "company_id": company_id,
            "enabled": False,
            "hour_utc": 12,    # 09:00 BRT
            "minute": 0,
            "notify_phone": "",
            "window_days": 30,
            "last_run_date": None,
        }
    return doc


async def save_schedule(company_id: str, data: Dict[str, Any],
                          updated_by: Optional[str] = None) -> Dict[str, Any]:
    payload = {k: v for k, v in data.items() if v is not None}
    payload["updated_at"] = now_iso()
    payload["updated_by"] = updated_by or "system"
    await db.churn_briefing_schedule.update_one(
        {"company_id": company_id},
        {"$set": payload,
         "$setOnInsert": {"company_id": company_id, "created_at": now_iso()}},
        upsert=True,
    )
    return await get_schedule(company_id)


async def run_now(company_id: str, days: int = 30) -> Optional[Dict[str, Any]]:
    """Dispara manualmente (botão "Testar agora"). Não atualiza last_run_date
    pra não bloquear a próxima execução programada."""
    return await _generate_and_save(company_id, days)
