"""Disparo manual de boletos próximos do vencimento.

Endpoint:
- POST /api/disparo-ia/boletos/preview    → calcula candidatos sem enviar
- POST /api/disparo-ia/boletos/send       → dispara mensagens reais via Baileys
- GET  /api/disparo-ia/boletos/history    → histórico dos últimos envios

Lógica:
1. Filtra `subscriber_invoices` com status aberto + `due_date` dentro da
   janela informada (default: hoje a hoje+3 dias).
2. Cruza com `atlaz_clients_cache` para pegar o telefone.
3. Usa o mesmo formatador do `boleto_flow` (com link + linha digitável).
4. Throttle automático: 1 msg a cada 2 segundos (configurável).
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import now_iso, require_role
from database import db
from services.boleto_flow import (
    _format_brl, _format_due, format_invoices_message,
)

logger = logging.getLogger("ponto.disparo_boleto")
router = APIRouter(prefix="/api/disparo-ia/boletos",
                    tags=["disparo-ia-boletos"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PreviewIn(BaseModel):
    """Filtros para listar candidatos."""
    days_until_due_min: int = Field(default=0, ge=-30, le=30,
        description="Dias até vencer (mínimo). 0=hoje, negativo=já vencidas")
    days_until_due_max: int = Field(default=3, ge=-30, le=30,
        description="Dias até vencer (máximo). 3=vence em até 3 dias")
    only_overdue: bool = Field(default=False,
        description="Se True, ignora min/max e pega só vencidas")


class SendIn(PreviewIn):
    """Mesmo filtro de Preview + parâmetros de envio."""
    throttle_seconds: float = Field(default=2.0, ge=0.5, le=30,
        description="Pausa entre mensagens (segundos)")
    custom_intro: Optional[str] = Field(default=None,
        description="Texto pra anteceder a mensagem padrão de boleto")
    dry_run: bool = Field(default=False,
        description="Se True, não envia de verdade — só simula")


def _normalize_phone(p: str) -> Optional[str]:
    if not p:
        return None
    digits = re.sub(r"\D", "", str(p))
    if not digits:
        return None
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 15:
        return None
    return digits


async def _build_candidates(cid: str, body: PreviewIn) -> List[Dict[str, Any]]:
    """Lista clientes elegíveis com suas faturas alvo."""
    today = datetime.now(timezone.utc).date()
    if body.only_overdue:
        date_min, date_max = today - timedelta(days=365), today - timedelta(days=1)
    else:
        date_min = today + timedelta(days=body.days_until_due_min)
        date_max = today + timedelta(days=body.days_until_due_max)

    # Faturas em aberto (não pagas) dentro da janela
    invs = await db.subscriber_invoices.find(
        {
            "company_id": cid,
            "status": {"$in": ["open", "pending", "overdue",
                                  "aberto", "pendente", "atrasado"]},
            "paid_date": None,
            "boleto_url": {"$ne": None, "$exists": True},
            "due_date": {
                "$gte": date_min.isoformat(),
                "$lte": date_max.isoformat(),
            },
        },
        {"_id": 0},
    ).sort("due_date", 1).limit(5000).to_list(5000)

    # Agrupa por subscriber_external_id
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invs:
        ext = str(inv.get("subscriber_external_id") or "")
        if not ext:
            continue
        groups.setdefault(ext, []).append(inv)

    # Cruza com cache Atlaz pra pegar telefone
    candidates = []
    for ext, fats in groups.items():
        acc = await db.atlaz_clients_cache.find_one(
            {"company_id": cid, "external_id": ext}, {"_id": 0},
        )
        if not acc:
            continue
        phone = _normalize_phone(acc.get("phone"))
        if not phone:
            continue
        total = sum(float(f.get("amount") or 0) for f in fats)
        candidates.append({
            "external_id": ext,
            "name": acc.get("name") or "Cliente",
            "phone": phone,
            "document": acc.get("document"),
            "invoices_count": len(fats),
            "total_amount": total,
            "total_amount_fmt": _format_brl(total),
            "earliest_due": fats[0].get("due_date"),
            "earliest_due_fmt": _format_due(fats[0].get("due_date")),
            "_invoices": fats,  # uso interno
        })
    # Maior valor primeiro
    candidates.sort(key=lambda c: c["total_amount"], reverse=True)
    return candidates


def _user_company(user: dict) -> str:
    return user.get("company_id") or "co-demo"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/preview")
async def preview_boletos_dispatch(
    body: PreviewIn,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Retorna lista de clientes que receberiam o disparo, SEM enviar."""
    cid = _user_company(user)
    candidates = await _build_candidates(cid, body)
    return {
        "ok": True,
        "total_clientes": len(candidates),
        "total_faturas": sum(c["invoices_count"] for c in candidates),
        "valor_total": sum(c["total_amount"] for c in candidates),
        "valor_total_fmt": _format_brl(
            sum(c["total_amount"] for c in candidates)
        ),
        "candidates": [
            {k: v for k, v in c.items() if k != "_invoices"}
            for c in candidates[:200]  # devolve até 200 pra UI
        ],
    }


@router.post("/send")
async def send_boletos_dispatch(
    body: SendIn,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Dispara mensagens de boleto via WhatsApp Baileys (Railway).

    Operação ASSÍNCRONA: cria registro em `disparo_boleto_runs` e processa
    em background. Resposta imediata = run_id para acompanhar progresso.
    """
    cid = _user_company(user)
    candidates = await _build_candidates(cid, body)
    if not candidates:
        return {"ok": True, "total": 0, "msg": "Nenhum cliente elegível."}

    run_id = f"disprun-{uuid.uuid4().hex[:10]}"
    run_doc = {
        "id": run_id,
        "company_id": cid,
        "started_at": now_iso(),
        "started_by": user.get("email"),
        "filters": body.model_dump(),
        "total_candidates": len(candidates),
        "sent": 0, "failed": 0, "skipped": 0,
        "dry_run": body.dry_run,
        "status": "running",
        "results": [],
    }
    await db.disparo_boleto_runs.insert_one(run_doc)

    # Dispara processamento em background
    asyncio.create_task(_process_dispatch(
        cid, run_id, candidates, body,
    ))

    return {
        "ok": True,
        "run_id": run_id,
        "total_candidates": len(candidates),
        "estimated_seconds": int(len(candidates) * body.throttle_seconds),
        "dry_run": body.dry_run,
    }


async def _process_dispatch(cid: str, run_id: str,
                              candidates: List[Dict[str, Any]],
                              body: SendIn) -> None:
    """Roda em background — envia 1 por 1 com throttle."""
    from routes.whatsapp_baileys import _sidecar_post  # lazy import

    sent = 0
    failed = 0
    skipped = 0
    results: List[Dict[str, Any]] = []

    for cand in candidates:
        phone = cand["phone"]
        subscriber_synth = {
            "name": cand["name"],
            "external_code": cand["external_id"],
        }
        try:
            message = format_invoices_message(
                subscriber_synth, cand["_invoices"]
            )
            if body.custom_intro:
                message = f"{body.custom_intro.strip()}\n\n{message}"

            if body.dry_run:
                results.append({
                    "phone": phone, "name": cand["name"],
                    "status": "dry_run", "preview": message[:120],
                })
                sent += 1
            else:
                resp = await _sidecar_post(
                    "/send", {"phone": phone, "text": message}
                )
                if resp.get("ok"):
                    sent += 1
                    msg_id = resp.get("message_id")
                    # Persiste a msg outbound no histórico de conversa
                    await db.aihub_wa_messages.insert_one({
                        "company_id": cid, "phone": phone,
                        "jid": f"{phone}@s.whatsapp.net",
                        "direction": "outbound", "text": message,
                        "agent": "disparo_boleto",
                        "delivery_status": "sent",
                        "external_id": msg_id,
                        "disparo_run_id": run_id,
                        "created_at": now_iso(),
                    })
                    results.append({
                        "phone": phone, "name": cand["name"],
                        "status": "sent", "message_id": msg_id,
                    })
                else:
                    failed += 1
                    results.append({
                        "phone": phone, "name": cand["name"],
                        "status": "failed",
                        "error": resp.get("error", "unknown"),
                    })
        except Exception as e:
            failed += 1
            results.append({
                "phone": phone, "name": cand["name"],
                "status": "failed", "error": str(e)[:200],
            })

        # Atualiza progresso a cada 5 envios
        if (sent + failed + skipped) % 5 == 0:
            await db.disparo_boleto_runs.update_one(
                {"id": run_id},
                {"$set": {"sent": sent, "failed": failed,
                          "skipped": skipped}},
            )

        # Throttle
        if body.throttle_seconds > 0:
            await asyncio.sleep(body.throttle_seconds)

    # Finaliza
    await db.disparo_boleto_runs.update_one(
        {"id": run_id},
        {"$set": {
            "sent": sent, "failed": failed, "skipped": skipped,
            "finished_at": now_iso(),
            "status": "completed",
            "results": results[-200:],  # últimos 200 só
        }},
    )
    logger.info(
        "[disparo_boleto] run=%s finalizado: sent=%d failed=%d",
        run_id, sent, failed,
    )


@router.get("/runs/{run_id}")
async def get_run_status(
    run_id: str,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = _user_company(user)
    run = await db.disparo_boleto_runs.find_one(
        {"id": run_id, "company_id": cid}, {"_id": 0}
    )
    if not run:
        raise HTTPException(404, "Run não encontrada")
    return run


@router.get("/history")
async def list_history(
    limit: int = 20,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = _user_company(user)
    runs = await db.disparo_boleto_runs.find(
        {"company_id": cid},
        {"_id": 0, "results": 0},  # remove results pesados
    ).sort("started_at", -1).limit(limit).to_list(limit)
    return {"items": runs, "total": len(runs)}
