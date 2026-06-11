"""
isabella_churn_to_sala.py — CTO P1.2 11/06/2026

Converte clientes em alto risco de churn (subscribers.churn_score >= 0.7,
status=ATIVO) em tickets de RETENÇÃO na SALA do tenant.

Idempotente:
  - Não cria 2 tickets para o mesmo `client_id` em janela de 7 dias.
  - Skip se cliente já tem ticket de retenção aberto.

Throttling:
  - Limite por execução: `MAX_PER_RUN` (default 100). Evita explodir a SALA.

Periodicidade: 1x por dia (06:00 UTC) via apscheduler.

Isabella enriquece o ticket com playbook + valor em risco (MRR mensal).
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "retention",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["retention.ticket_created"],
    "company_id_required": True,
}

import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from database import db
from services.sala_router import route_to_sala

log = logging.getLogger("isabella_churn_to_sala")

CHURN_THRESHOLD = float(os.environ.get("CHURN_TICKET_THRESHOLD", "0.7"))
DEDUPE_WINDOW_DAYS = int(os.environ.get("CHURN_DEDUPE_WINDOW_DAYS", "7"))
MAX_PER_RUN = int(os.environ.get("CHURN_TICKETS_PER_RUN", "100"))


def _build_playbook(score: float, mrr: float, name: str) -> str:
    """Mensagem Isabella pro técnico/gestor: o que fazer."""
    risk_label = "🔴 CRÍTICO" if score >= 0.85 else "🟠 ALTO"
    mrr_str = f"R$ {mrr:.2f}/mês" if mrr else "valor desconhecido"
    annual_str = f"R$ {(mrr * 12):.2f}/ano em risco" if mrr else ""
    lines = [
        f"{risk_label} — Score de churn: {score * 100:.1f}%",
        f"💰 MRR: {mrr_str}",
    ]
    if annual_str:
        lines.append(f"📉 ARR perdido se sair: {annual_str}")
    lines.append("")
    lines.append("📋 Playbook Isabella sugerido:")
    if score >= 0.85:
        lines.append("  1. Ligação ativa em até 24h (não WhatsApp). Cliente quer ser ouvido.")
        lines.append("  2. Investigar: rede, atendimento, valor. Use Identity360.")
        lines.append("  3. Ofertar: desconto temporário OU upgrade gratuito por 30 dias.")
    else:
        lines.append("  1. Mensagem WhatsApp personalizada com Isabella (não bot genérico).")
        lines.append("  2. Confirmar canal de pagamento e se há atrasos não resolvidos.")
        lines.append("  3. Se cliente responder negativamente, escalar para ligação.")
    lines.append("")
    lines.append(f"👤 Cliente: {name or '—'}")
    return "\n".join(lines)


async def _existing_retention_ticket(client_id: str, company_id: str) -> bool:
    """True se o cliente já tem ticket de retenção aberto OU criado nos últimos N dias."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=DEDUPE_WINDOW_DAYS)).isoformat()
    existing = await db.tickets.find_one({
        "client_id": client_id,
        "company_id": company_id,
        "$or": [
            {"status": {"$nin": ["closed", "cancelado", "encerrado"]}},
            {"created_at": {"$gte": cutoff_iso}},
        ],
        "category": "RETENTION",
    }, {"_id": 1})
    return existing is not None


async def run_churn_to_sala() -> Dict:
    """Job principal. Idempotente, com limite e dedupe."""
    start = datetime.now(timezone.utc)
    now_iso = start.isoformat()

    # 1. Listar candidatos (subscribers com churn alto, ativos)
    candidates_cursor = db.subscribers.find({
        "churn_score": {"$gte": CHURN_THRESHOLD},
        "status": {"$in": ["ATIVO", "ATIVA", "ATIVADO", "active"]},
    }, {
        "_id": 0, "id": 1, "name": 1, "phone": 1,
        "company_id": 1, "churn_score": 1, "monthly_value": 1, "plan": 1,
    })

    created_by_tenant: Dict[str, int] = defaultdict(int)
    skipped = 0
    seen = 0
    created_total = 0

    async for sub in candidates_cursor:
        if created_total >= MAX_PER_RUN:
            break
        seen += 1
        cid = sub.get("company_id")
        sub_id = sub.get("id")
        if not cid or not sub_id:
            skipped += 1
            continue

        # 2. Dedupe
        if await _existing_retention_ticket(sub_id, cid):
            skipped += 1
            continue

        # 3. Monta ticket
        score = float(sub.get("churn_score") or 0)
        mrr = float(sub.get("monthly_value") or 0)
        name = sub.get("name") or "—"
        priority = "ALTA" if score >= 0.85 else "MEDIA"

        ticket_doc = {
            "id": f"ret-{uuid.uuid4().hex[:14]}",
            "company_id": cid,
            "client_id": sub_id,
            "client_snapshot": {
                "name": name,
                "phone": sub.get("phone"),
                "plan": sub.get("plan"),
                "monthly_value": mrr,
            },
            "status": "aberta",
            "priority": priority,
            "title": f"Retenção · {name}",
            "description": _build_playbook(score, mrr, name),
            "type": "retencao",
            "category": "RETENTION",
            "origin": "isabella_churn_to_sala",
            "source": "isabella_churn",
            "isabella": {
                "score": round(score * 100, 1),
                "risk": "critico" if score >= 0.85 else "alto",
                "playbook_version": "v1",
                "mrr_at_risk": mrr,
                "arr_at_risk": mrr * 12 if mrr else 0,
            },
            "created_at": now_iso,
        }

        # 4. Encaminha para SALA (route_to_sala marca system_generated + sala_route_reason)
        try:
            await route_to_sala(ticket_doc, reason="isabella_followup")
        except Exception as e:
            log.warning("route_to_sala falhou para %s: %s", sub_id, e)
            skipped += 1
            continue

        # 5. Insere
        try:
            await db.tickets.insert_one(ticket_doc)
            created_by_tenant[cid] += 1
            created_total += 1
            # Evento Sistema Nervoso
            try:
                await db.system_events.insert_one({
                    "id": f"evt-{uuid.uuid4().hex[:14]}",
                    "company_id": cid,
                    "event_type": "retention.ticket_created",
                    "payload": {
                        "ticket_id": ticket_doc["id"],
                        "subscriber_id": sub_id,
                        "score": round(score, 4),
                        "mrr": mrr,
                    },
                    "created_at": now_iso,
                })
            except Exception:
                pass
        except Exception as e:
            log.warning("insert ticket falhou para %s: %s", sub_id, e)
            skipped += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    report = {
        "id": f"churnrun-{uuid.uuid4().hex[:12]}",
        "executed_at": start.isoformat(),
        "elapsed_ms": elapsed_ms,
        "candidates_seen": seen,
        "created_total": created_total,
        "created_by_tenant": dict(created_by_tenant),
        "skipped": skipped,
        "threshold": CHURN_THRESHOLD,
        "max_per_run": MAX_PER_RUN,
        "dedupe_window_days": DEDUPE_WINDOW_DAYS,
    }
    try:
        await db.isabella_churn_runs.insert_one({**report})
    except Exception:
        pass

    log.info(
        "isabella_churn_to_sala: seen=%d created=%d skipped=%d elapsed=%dms",
        seen, created_total, skipped, elapsed_ms,
    )
    return report
