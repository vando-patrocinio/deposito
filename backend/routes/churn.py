"""Dashboard de Churn — análise de cancelamentos.

Estratégia de dados:
  • Usa a tabela local `tickets` (já sincronizada do Atlaz periodicamente)
  • Filtra tickets `type='retirada'` (mapeia CANCELAMENTO + RETIRADA do Atlaz)
  • Distingue CANCELAMENTO de RETIRADA via `atlaz_assunto` quando disponível
  • Considera "churn efetivo" tickets com `status='finalizada'` ou `closed_at != null`

Best practices aplicadas (pesquisa Feb/2026):
  • Múltiplas dimensões: tempo, geografia, motivo
  • Tempo médio de vida (instalação → cancelamento) — proxy via primeiro ticket
  • Não confundir "pedido de cancelamento" com "cancelamento efetivado"
  • Inclui também tickets ainda em aberto (pipeline de churn iminente)
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import chat_completion, AgentDisabledError

logger = logging.getLogger("ponto.churn")
router = APIRouter(prefix="/api/churn", tags=["churn"])


# Status finais ⇒ churn efetivado.
FINAL_STATUSES = ["finalizada", "concluida", "concluído", "concluida_offline"]
# Status pendentes ⇒ churn iminente (cliente pediu, ainda não retirou).
PENDING_STATUSES = ["pendente", "em_andamento", "agendada"]


def _strip(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                     if unicodedata.category(c) != "Mn").upper().strip()


def _classify_reason(ticket: Dict[str, Any]) -> str:
    """Inferência simples de motivo a partir de assunto/relato."""
    text = " ".join([
        str(ticket.get("atlaz_assunto") or ""),
        str((ticket.get("client_snapshot") or {}).get("relato") or ""),
    ])
    s = _strip(text)
    if not s:
        return "Não informado"
    if re.search(r"\bPRECO|VALOR|CARO|CONCORRENT|MUDOU|FATURA\b", s):
        return "Preço / Concorrência"
    if re.search(r"\bMUDANCA|MUDOU|MUDAR|ENDERECO|MORAR\b", s):
        return "Mudança de endereço"
    if re.search(r"\bLENT|VELOCIDADE|INSTAVEL|SEM SINAL|CONEX\b", s):
        return "Problema técnico"
    if re.search(r"\bATENDIMENT|SUPORTE|DEMORA|RUIM\b", s):
        return "Atendimento ruim"
    if re.search(r"\bDESEMPREG|DIFICUL|FINANC|PAGAR\b", s):
        return "Financeiro"
    if re.search(r"\bFALECIMENT|OBITO\b", s):
        return "Falecimento"
    if re.search(r"\bRETIRADA|EQUIPAMENT|ONU|ROTEADOR\b", s):
        return "Retirada de equipamento"
    return "Outros"


def _classify_kind(ticket: Dict[str, Any]) -> str:
    """Diferencia CANCELAMENTO (pedido) de RETIRADA (operação)."""
    assunto = _strip(ticket.get("atlaz_assunto") or "")
    if "CANCEL" in assunto:
        return "cancelamento"
    if "RETIRADA" in assunto or "EQUIPAMENT" in assunto:
        return "retirada"
    # fallback: se o tipo é 'retirada' mas não temos assunto → marca como cancelamento
    return "cancelamento"


def _month_key(iso: str) -> str:
    """Retorna 'YYYY-MM' a partir de uma string ISO."""
    try:
        return iso[:7]
    except Exception:
        return ""


def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/dashboard")
async def churn_dashboard(
    days: int = Query(180, ge=30, le=730),
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Dashboard consolidado de churn.

    Janela default: 180 dias (~6 meses). Máx 730 (~2 anos).

    Retorna:
      - kpis           : totais + taxa de churn estimada
      - by_month       : série mensal (últimos 12 meses fixos)
      - by_reason      : top motivos inferidos do assunto/relato
      - by_neighborhood: top bairros com mais churn
      - by_kind        : cancelamento vs. retirada de equipamento
      - avg_lifetime   : tempo médio de vida (instalação → cancelamento)
                          em dias, calculado quando há ticket de instalação
                          do mesmo `client_id`
      - recent         : últimos 20 churns finalizados (para timeline)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    base_match = {
        "company_id": cid,
        "type": "retirada",
        "created_at": {"$gte": cutoff_iso},
    }

    # 1. Lista tickets relevantes (limita para evitar load excessivo)
    tickets: List[Dict[str, Any]] = await db.tickets.find(
        base_match,
        {"_id": 0,
         "id": 1, "client_id": 1, "client_snapshot": 1, "status": 1,
         "created_at": 1, "closed_at": 1,
         "atlaz_assunto": 1, "atlaz_filial": 1,
         "atlaz_id_assinante": 1},
    ).sort("created_at", -1).to_list(5000)

    # 2. Classifica e agrega
    by_month: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    by_neigh: Dict[str, int] = {}
    by_kind = {"cancelamento": 0, "retirada": 0}
    finalized = 0
    pending = 0
    lifetimes_days: List[float] = []

    # Pré-carrega tickets de INSTALAÇÃO para calcular tempo de vida
    install_dates: Dict[str, datetime] = {}
    install_cursor = db.tickets.find(
        {"company_id": cid, "type": "instalacao"},
        {"_id": 0, "atlaz_id_assinante": 1, "client_id": 1, "created_at": 1},
    ).sort("created_at", 1)
    async for it in install_cursor:
        key = it.get("atlaz_id_assinante") or it.get("client_id")
        if key and key not in install_dates:
            dt = _parse_iso(it.get("created_at"))
            if dt:
                install_dates[str(key)] = dt

    for t in tickets:
        status = (t.get("status") or "").lower()
        is_final = status in FINAL_STATUSES
        is_pending = status in PENDING_STATUSES
        if is_final:
            finalized += 1
        elif is_pending:
            pending += 1
        # série mensal baseada na data de fechamento (ou criação se aberto)
        when = t.get("closed_at") if is_final else t.get("created_at")
        mk = _month_key(when or "")
        if mk:
            by_month[mk] = by_month.get(mk, 0) + 1
        # motivos
        reason = _classify_reason(t)
        by_reason[reason] = by_reason.get(reason, 0) + 1
        # bairro
        neigh = ((t.get("client_snapshot") or {}).get("neighborhood") or "—").strip() or "—"
        by_neigh[neigh] = by_neigh.get(neigh, 0) + 1
        # tipo
        by_kind[_classify_kind(t)] += 1
        # tempo de vida (se tiver instalação)
        key = str(t.get("atlaz_id_assinante") or t.get("client_id") or "")
        churn_dt = _parse_iso(when)
        if key and key in install_dates and churn_dt:
            delta_days = (churn_dt - install_dates[key]).total_seconds() / 86400
            if delta_days > 0:
                lifetimes_days.append(delta_days)

    # 3. Série mensal: últimos 12 meses fixos (zera meses sem churn)
    now = datetime.now(timezone.utc)
    months_series: List[Dict[str, Any]] = []
    for i in range(11, -1, -1):
        # mês corrente menos i meses
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year:04d}-{month:02d}"
        months_series.append({
            "month": key,
            "count": by_month.get(key, 0),
        })

    # 4. Total de assinantes ativos (para taxa de churn)
    try:
        total_subscribers = await db.subscribers.count_documents({"company_id": cid})
    except Exception:
        total_subscribers = 0

    # 5. KPIs
    churn_rate = 0.0
    if total_subscribers > 0:
        churn_rate = round((finalized / max(1, total_subscribers + finalized)) * 100, 2)

    avg_lifetime = round(sum(lifetimes_days) / len(lifetimes_days), 1) if lifetimes_days else None
    median_lifetime = None
    if lifetimes_days:
        sl = sorted(lifetimes_days)
        median_lifetime = round(sl[len(sl) // 2], 1)

    # 6. Recent (últimos 20 finalizados)
    recent = []
    for t in tickets[:60]:
        if (t.get("status") or "").lower() not in FINAL_STATUSES:
            continue
        recent.append({
            "ticket_id": t.get("id"),
            "client_name": (t.get("client_snapshot") or {}).get("name") or "Cliente",
            "neighborhood": (t.get("client_snapshot") or {}).get("neighborhood") or "—",
            "kind": _classify_kind(t),
            "reason": _classify_reason(t),
            "closed_at": t.get("closed_at"),
        })
        if len(recent) >= 20:
            break

    # 7. Top N de cada agregação
    def top_n(d: Dict[str, int], n: int = 10) -> List[Dict[str, Any]]:
        return [{"label": k, "count": v}
                for k, v in sorted(d.items(), key=lambda x: -x[1])[:n]]

    return {
        "window_days": days,
        "kpis": {
            "total_churn": len(tickets),
            "finalized": finalized,
            "pending": pending,
            "churn_rate_pct": churn_rate,
            "total_subscribers": total_subscribers,
            "avg_lifetime_days": avg_lifetime,
            "median_lifetime_days": median_lifetime,
            "lifetime_samples": len(lifetimes_days),
        },
        "by_month": months_series,
        "by_reason": top_n(by_reason, 8),
        "by_neighborhood": top_n(by_neigh, 10),
        "by_kind": by_kind,
        "recent": recent,
        "generated_at": now.isoformat(),
    }



@router.post("/ai-insight")
async def churn_ai_insight(
    days: int = Query(180, ge=30, le=730),
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Gera briefing executivo do dashboard usando Motor IA (Claude Sonnet 4.5).

    Reusa o `churn_dashboard()` pra coletar os dados, monta prompt enxuto
    e devolve análise em markdown pt-BR (3 seções: diagnóstico, padrões,
    recomendações). Caso o agente esteja desligado retorna 503.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    payload = await churn_dashboard(days=days, user=user)
    k = payload["kpis"]

    # Resumo compacto para o prompt (top 5 reasons/neighborhoods)
    top_reasons = ", ".join(
        f"{r['label']} ({r['count']})" for r in payload["by_reason"][:5])
    top_neigh = ", ".join(
        f"{n['label']} ({n['count']})" for n in payload["by_neighborhood"][:5])
    months_str = ", ".join(
        f"{m['month'][-2:]}={m['count']}" for m in payload["by_month"])

    prompt = f"""Você é um analista sênior de retenção de clientes para um provedor de internet (ISP).
Abaixo está um snapshot do dashboard de churn dos últimos {days} dias. Gere um briefing executivo objetivo em pt-BR, com no MÁXIMO 4 parágrafos curtos, usando markdown leve (negrito quando relevante).

## Dados
- Churn total: {k['total_churn']} (finalizados {k['finalized']}, pendentes {k['pending']})
- Taxa de churn estimada: {k['churn_rate_pct']}% sobre {k['total_subscribers']} assinantes ativos
- Tempo médio de vida do cliente: {k['avg_lifetime_days']} dias (mediana {k['median_lifetime_days']} d, {k['lifetime_samples']} amostras)
- Pedidos vs Operação: cancelamento={payload['by_kind'].get('cancelamento')} / retirada={payload['by_kind'].get('retirada')}
- Top motivos: {top_reasons or '—'}
- Top bairros: {top_neigh or '—'}
- Cancelamentos por mês (últimos 12): {months_str}

## Estrutura da resposta (use os títulos exatos)
**Diagnóstico**: 1 parágrafo sobre o quadro atual.
**Padrões**: 1 parágrafo identificando concentrações (motivo dominante, bairros, tendência mensal).
**Riscos**: 1 parágrafo sobre pipeline pendente e perda esperada nos próximos 30 dias.
**Recomendações**: 3-4 ações priorizadas em bullet points, específicas e acionáveis.

NÃO invente dados que não estão no snapshot. Se algum dado for zero, sinalize. Use linguagem direta, sem clichês corporativos."""

    try:
        result = await chat_completion(
            cid,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.35,
            agent="churn_insight",
        )
    except AgentDisabledError as e:
        from fastapi import HTTPException
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(502, f"Motor IA falhou: {e}") from e

    based_on = {
        "total_churn": k["total_churn"],
        "churn_rate_pct": k["churn_rate_pct"],
        "top_reason": payload["by_reason"][0]["label"] if payload["by_reason"] else None,
        "top_neighborhood": payload["by_neighborhood"][0]["label"] if payload["by_neighborhood"] else None,
        "by_reason": payload["by_reason"][:5],
        "by_neighborhood": payload["by_neighborhood"][:5],
        "by_kind": payload["by_kind"],
        "avg_lifetime_days": k["avg_lifetime_days"],
    }
    today = datetime.now(timezone.utc).date().isoformat()
    record_id = f"ci-{cid}-{today}-{days}"
    doc = {
        "id": record_id,
        "company_id": cid,
        "date": today,
        "window_days": days,
        "insight": result.get("content"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "based_on": based_on,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": user.get("name") or user.get("email") or "system",
    }
    # Upsert: 1 registro por dia x janela
    await db.churn_insights.update_one(
        {"id": record_id}, {"$set": doc}, upsert=True,
    )

    return {
        "ok": True,
        "id": record_id,
        "insight": result.get("content"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "window_days": days,
        "based_on": based_on,
    }


@router.get("/ai-insight/history")
async def churn_ai_insight_history(
    limit: int = Query(30, ge=1, le=100),
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Lista briefings históricos salvos (mais recentes primeiro)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.churn_insights.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "date": 1, "window_days": 1,
         "model": 1, "based_on": 1, "generated_at": 1, "generated_by": 1},
    ).sort("generated_at", -1).limit(limit)
    items = await cur.to_list(limit)
    return {"items": items, "count": len(items)}


@router.get("/ai-insight/{insight_id}")
async def churn_ai_insight_get(
    insight_id: str,
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Retorna um briefing histórico específico."""
    from fastapi import HTTPException
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.churn_insights.find_one(
        {"id": insight_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Briefing não encontrado.")
    return doc


@router.post("/ai-insight/compare")
async def churn_ai_insight_compare(
    base_id: str = Query(..., description="ID do briefing mais recente"),
    against_id: str = Query(..., description="ID do briefing anterior"),
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Gera comparação narrativa entre dois briefings via Claude."""
    from fastapi import HTTPException
    cid = user.get("company_id") or DEMO_COMPANY_ID
    base = await db.churn_insights.find_one(
        {"id": base_id, "company_id": cid}, {"_id": 0})
    prev = await db.churn_insights.find_one(
        {"id": against_id, "company_id": cid}, {"_id": 0})
    if not base or not prev:
        raise HTTPException(404, "Briefing(s) não encontrado(s).")

    def _kpi_line(d: Dict[str, Any]) -> str:
        bo = d.get("based_on") or {}
        reasons = ", ".join(
            f"{r['label']} ({r['count']})" for r in (bo.get("by_reason") or [])[:5])
        neighs = ", ".join(
            f"{n['label']} ({n['count']})" for n in (bo.get("by_neighborhood") or [])[:5])
        return (f"data={d.get('date')}, janela={d.get('window_days')}d, "
                  f"churn_total={bo.get('total_churn')}, "
                  f"taxa={bo.get('churn_rate_pct')}%, "
                  f"vida_média={bo.get('avg_lifetime_days')}d, "
                  f"top_motivos=[{reasons}], top_bairros=[{neighs}], "
                  f"split={bo.get('by_kind')}")

    prompt = (
        "Você é um analista de retenção. Compare dois snapshots do dashboard "
        "de churn e responda em pt-BR com no MÁXIMO 3 parágrafos curtos.\n\n"
        f"**Atual** — {_kpi_line(base)}\n\n"
        f"**Anterior** — {_kpi_line(prev)}\n\n"
        "Estruture a resposta com os títulos:\n"
        "**Evolução dos números**: variação de churn total, taxa e tempo de vida.\n"
        "**Mudança de padrões**: motivos/bairros que entraram ou saíram do top, sinais novos.\n"
        "**O que fazer diferente agora**: 2-3 recomendações baseadas APENAS na mudança observada.\n\n"
        "Use setas ↑/↓ para indicar variações numéricas. Se algum dado é nulo, sinalize."
    )

    try:
        result = await chat_completion(
            cid,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700, temperature=0.35,
            agent="churn_insight",
        )
    except AgentDisabledError as e:
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"Motor IA falhou: {e}") from e

    return {
        "ok": True,
        "comparison": result.get("content"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "base_id": base_id,
        "against_id": against_id,
    }
