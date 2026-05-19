"""Análise IA de qualidade do fechamento de bolhas.

Para cada bolha FINALIZADA, usa LLM para:
  1. Classificar o MOTIVO REAL do chamado (categoria padronizada)
  2. Avaliar se a solução aplicada resolve (correlaciona queixa × ação)
  3. Atribuir nota 0-10 de qualidade técnica
  4. Marcar bolhas com alto risco de retorno

Resultado persistido em `ticket_quality_analysis` para não reprocessar.

Modelo: gemini-2.5-flash (rápido + barato + multilíngue PT-BR).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from auth_helpers import require_role, tenant_filter
from core import db, now_iso

router = APIRouter(prefix="/api", tags=["ticket-quality"])
logger = logging.getLogger(__name__)


CATEGORIES = [
    "sem_internet",
    "internet_lenta",
    "internet_oscilando",
    "wifi_fraco",
    "instalacao_nova",
    "troca_equipamento",
    "queda_fibra",
    "problema_ip",
    "mudanca_endereco",
    "outros",
]


PROMPT_TEMPLATE = """\
Você é um auditor técnico de provedor de internet. Analise UM CHAMADO já finalizado e retorne SOMENTE JSON válido (sem markdown, sem comentário).

DADOS DO CHAMADO:
- Reclamação do cliente: "{complaint}"
- O que o técnico fez (observações + central_ont): "{action}"

Sua tarefa:
1. Classifique a `motivo_real` em UMA destas categorias (exata):
   {categories}
2. Avalie se a `solucao_resolve` (true/false): a ação do técnico provavelmente resolve a queixa? Considere conhecimento técnico de FTTH/ISP.
3. Dê uma `nota_0a10` (inteiro 0-10):
   - 10 = solução perfeita, anti-recorrência incluída
   - 8-9 = solução adequada, atende
   - 6-7 = parcial, talvez volte
   - 3-5 = solução errada ou superficial
   - 0-2 = não fez nada útil ou abandonou
4. `risco_retorno` (low/medium/high): probabilidade do cliente voltar a chamar pelo mesmo motivo.
5. `motivo_visivel`: descreva em 1 frase curta (≤90 chars) o motivo real para o gestor entender.

RETORNE SOMENTE JSON neste formato:
{{"motivo_real": "...", "motivo_visivel": "...", "solucao_resolve": true/false, "nota_0a10": N, "risco_retorno": "low|medium|high"}}
"""


def _build_action_text(t: dict) -> str:
    cd = t.get("completion_data") or {}
    parts = []
    for k in ("observations", "laudo", "what_was_done"):
        v = cd.get(k)
        if v:
            parts.append(str(v))
    central = t.get("central_ont") or {}
    if central.get("sinal") is not None:
        parts.append(f"sinal_rx={central.get('sinal')} dBm")
    if cd.get("sn"):
        parts.append(f"SN={cd.get('sn')}")
    return " | ".join(parts).strip() or "(sem detalhes)"


def _build_complaint_text(t: dict) -> str:
    parts = []
    for k in ("subject", "title", "description", "issue", "client_complaint"):
        v = t.get(k)
        if v:
            parts.append(str(v))
    return " · ".join(parts).strip() or "(sem queixa registrada)"


async def _analyze_one(t: dict) -> dict | None:
    """Chama LLM com retry simples. Retorna dict do schema ou None."""
    try:
        from services.motor_ia import chat_completion
    except Exception:
        return None

    complaint = _build_complaint_text(t)
    action = _build_action_text(t)
    if complaint == "(sem queixa registrada)" and action == "(sem detalhes)":
        return None

    prompt = PROMPT_TEMPLATE.format(
        complaint=complaint[:500],
        action=action[:800],
        categories=", ".join(CATEGORIES),
    )
    try:
        r = await chat_completion(
            company_id=t.get("company_id") or "co-demo",
            messages=[
                {"role": "system",
                 "content": "Você é auditor técnico. Responda SÓ JSON válido."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1, max_tokens=300, purpose="ticket-quality-analysis",
            force_provider="gemini",
            force_model="gemini-2.5-flash",
        )
    except Exception as e:
        logger.info("[ticket-quality] LLM call falhou ticket=%s: %s",
                    t.get("id"), e)
        return None

    raw = (r.get("content") or "").strip()
    # Strip markdown se o modelo teimar
    if raw.startswith("```"):
        raw = raw.strip("` \n")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except Exception:
        # Tenta extrair primeiro JSON
        import re
        m = re.search(r"\{[^{}]*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None

    # Sanitiza
    motivo = str(data.get("motivo_real") or "outros").lower()
    if motivo not in CATEGORIES:
        motivo = "outros"
    try:
        nota = max(0, min(10, int(data.get("nota_0a10", 0))))
    except Exception:
        nota = 0
    risco = str(data.get("risco_retorno") or "medium").lower()
    if risco not in {"low", "medium", "high"}:
        risco = "medium"
    return {
        "motivo_real": motivo,
        "motivo_visivel": str(data.get("motivo_visivel") or "")[:200],
        "solucao_resolve": bool(data.get("solucao_resolve")),
        "nota_0a10": nota,
        "risco_retorno": risco,
        "model": r.get("model"),
        "analyzed_at": now_iso(),
    }


async def analyze_pending_tickets(company_id: str,
                                    days_back: int = 14,
                                    limit: int = 50) -> dict:
    """Pega bolhas finalizadas dentro da janela que ainda NÃO foram analisadas
    e roda IA. Idempotente: já analisadas são puladas."""
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    # Pega bolhas finalizadas
    cur = db.tickets.find(
        {"company_id": company_id, "status": "finalizada",
         "closed_at": {"$gte": since}},
        {"_id": 0, "id": 1, "subject": 1, "title": 1, "description": 1,
         "issue": 1, "client_complaint": 1, "assigned_collaborator_id": 1,
         "completion_data": 1, "central_ont": 1, "company_id": 1,
         "closed_at": 1, "outcome": 1},
    ).sort("closed_at", -1).limit(limit * 3)
    tickets = await cur.to_list(limit * 3)

    # Filtra os que ainda não têm análise
    existing_ids = await db.ticket_quality_analysis.distinct(
        "ticket_id",
        {"ticket_id": {"$in": [t["id"] for t in tickets]}},
    )
    pending = [t for t in tickets if t["id"] not in existing_ids][:limit]
    if not pending:
        return {"analyzed": 0, "skipped": len(tickets), "errors": 0}

    analyzed = errors = 0
    for t in pending:
        try:
            res = await _analyze_one(t)
            if not res:
                errors += 1
                continue
            doc = {
                "ticket_id": t["id"],
                "company_id": company_id,
                "collaborator_id": t.get("assigned_collaborator_id"),
                "closed_at": t.get("closed_at"),
                **res,
            }
            await db.ticket_quality_analysis.replace_one(
                {"ticket_id": t["id"]}, doc, upsert=True,
            )
            analyzed += 1
        except Exception as e:
            logger.info("[ticket-quality] erro ticket=%s: %s", t.get("id"), e)
            errors += 1
        await asyncio.sleep(0.1)
    return {"analyzed": analyzed, "skipped": len(tickets) - len(pending),
            "errors": errors}


@router.post("/lousa/quality/run-analysis")
async def run_quality_analysis(
    user: dict = Depends(require_role("gestor")),
    days_back: int = 14, limit: int = 50,
):
    """Dispara análise IA dos fechamentos pendentes (rate limit pelo limit)."""
    cid = user.get("company_id") or "co-demo"
    result = await analyze_pending_tickets(cid, days_back=days_back, limit=limit)
    return {"ok": True, **result}


@router.get("/lousa/quality/closure-report")
async def closure_report(
    user: dict = Depends(require_role("gestor")),
    days_back: int = 7,
    auto_analyze: bool = True,
):
    """Relatório agregado de motivos de fechamento + qualidade IA.

    Retorna:
      - top_motivos: [{motivo, count, nota_media, pct_resolve}]
      - score_geral: nota média do período (0-10)
      - by_technician: [{collaborator_id, name, count, nota_media, alto_risco}]
      - high_risk: lista de bolhas com risco alto de retorno
    """
    cid = user.get("company_id") or "co-demo"
    q = tenant_filter(user)
    collabs = await db.collaborators.find(q, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    name_by_cid = {c["id"]: c.get("name", "—") for c in collabs}

    # Auto-analisa até 30 bolhas novas (rate limited)
    if auto_analyze:
        try:
            await analyze_pending_tickets(cid, days_back=days_back, limit=30)
        except Exception as e:
            logger.info("[ticket-quality] auto_analyze skip: %s", e)

    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    rows = await db.ticket_quality_analysis.find(
        {"company_id": cid, "closed_at": {"$gte": since}},
        {"_id": 0},
    ).to_list(20000)

    if not rows:
        return {
            "days_back": days_back,
            "total_analyzed": 0,
            "score_geral": None,
            "top_motivos": [],
            "by_technician": [],
            "high_risk": [],
        }

    # Top motivos
    motivo_count: Counter = Counter()
    motivo_nota: dict = {}
    motivo_resolve: dict = {}
    for r in rows:
        m = r.get("motivo_real") or "outros"
        motivo_count[m] += 1
        motivo_nota.setdefault(m, []).append(r.get("nota_0a10", 0))
        motivo_resolve.setdefault(m, []).append(
            1 if r.get("solucao_resolve") else 0,
        )
    top_motivos = []
    for m, c in motivo_count.most_common(10):
        notas = motivo_nota[m]
        resolves = motivo_resolve[m]
        top_motivos.append({
            "motivo": m,
            "motivo_label": MOTIVO_LABELS.get(m, m),
            "count": c,
            "nota_media": round(sum(notas) / len(notas), 1) if notas else None,
            "pct_resolve": round(100.0 * sum(resolves) / len(resolves), 1)
                            if resolves else None,
        })

    # Por técnico
    by_tech: dict = {}
    for r in rows:
        tid = r.get("collaborator_id") or "—"
        if tid not in by_tech:
            by_tech[tid] = {
                "collaborator_id": tid,
                "name": name_by_cid.get(tid, "—"),
                "count": 0, "notas": [], "alto_risco": 0,
            }
        by_tech[tid]["count"] += 1
        by_tech[tid]["notas"].append(r.get("nota_0a10", 0))
        if r.get("risco_retorno") == "high":
            by_tech[tid]["alto_risco"] += 1
    by_tech_list = []
    for d in by_tech.values():
        notas = d.pop("notas")
        d["nota_media"] = round(sum(notas) / len(notas), 1) if notas else None
        by_tech_list.append(d)
    by_tech_list.sort(key=lambda x: (-x.get("count", 0)))

    score_geral = round(
        sum(r.get("nota_0a10", 0) for r in rows) / len(rows), 1,
    )

    # Bolhas de alto risco (top 8)
    high_risk_docs = [r for r in rows if r.get("risco_retorno") == "high"]
    high_risk_docs.sort(key=lambda x: x.get("nota_0a10", 0))
    high_risk = []
    for r in high_risk_docs[:8]:
        high_risk.append({
            "ticket_id": r.get("ticket_id"),
            "motivo_visivel": r.get("motivo_visivel"),
            "motivo": r.get("motivo_real"),
            "motivo_label": MOTIVO_LABELS.get(r.get("motivo_real"),
                                                r.get("motivo_real")),
            "nota_0a10": r.get("nota_0a10"),
            "collaborator_name": name_by_cid.get(r.get("collaborator_id"), "—"),
            "closed_at": r.get("closed_at"),
        })

    return {
        "days_back": days_back,
        "total_analyzed": len(rows),
        "score_geral": score_geral,
        "top_motivos": top_motivos,
        "by_technician": by_tech_list,
        "high_risk": high_risk,
    }


MOTIVO_LABELS = {
    "sem_internet": "Sem internet (queda total)",
    "internet_lenta": "Internet lenta",
    "internet_oscilando": "Internet oscilando",
    "wifi_fraco": "Wi-Fi fraco",
    "instalacao_nova": "Instalação nova",
    "troca_equipamento": "Troca de equipamento",
    "queda_fibra": "Queda/corte de fibra",
    "problema_ip": "Problema de IP/Configuração",
    "mudanca_endereco": "Mudança de endereço",
    "outros": "Outros",
}
