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
