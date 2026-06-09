"""
executor_ia.py — Braços do Presidente IA.

Implementa o ciclo:
  PRESIDENTE → CONSELHO → EXECUTOR → ROI → MEMÓRIA → APRENDIZADO

Coleções utilizadas:
  motor_ia_actions    — registro UMA por ação presidencial (sobreposta ao
                          uso histórico do motor de eventos via flag
                          `source=presidential`)
  pending_executions  — fila de execução pós-aprovação
  motor_ia_kpis       — snapshots before/after + ROI calculado
  motor_ia_corrections — diferença previsto vs real
  motor_ia_drift      — tendência de erro acumulada por categoria
  conselho_votes      — voto formal das 6 cadeiras por ação

Categorias autorizadas para executar (DRY_RUN_ONLY até flip manual):
  - REAJUSTE_IPCA
  - DISPARO_COBRANCA
  - CONTATO_LEO_PROATIVO
  - CRIACAO_OS_SMARTFIELD
  - CAMPANHA_RETENCAO

Nenhum executor roda sem `approved_by` preenchido.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger(__name__)


# ───────── Categorias autorizadas ─────────
CATEGORIAS_EXECUTAVEIS = {
    "REAJUSTE_IPCA": "Reajuste IPCA em lote",
    "DISPARO_COBRANCA": "Disparo de régua de cobrança",
    "CONTATO_LEO_PROATIVO": "Contato Leo proativo aos clientes em risco",
    "CRIACAO_OS_SMARTFIELD": "Criação de OS Smart Field para ONUs degradadas",
    "CAMPANHA_RETENCAO": "Campanha de retenção a clientes em churn previsto",
}

STATUS_FLOW = {
    "pending": ["approved", "cancelled"],
    "approved": ["executing", "cancelled"],
    "executing": ["completed", "failed"],
    "completed": [],
    "failed": ["pending"],  # permite re-tentativa
    "cancelled": [],
}


# ───────── Utilidades ─────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ─────────────────────────────────────────────
#  ETAPA 1 — REGISTRO DA AÇÃO PRESIDENCIAL
# ─────────────────────────────────────────────
async def propose_action(
    company_id: str,
    created_by: str,
    categoria: str,
    descricao: str,
    impacto_estimado_brl: float,
    prioridade: str = "MÉDIA",
    source: str = "presidente_ia",
    payload: Optional[Dict[str, Any]] = None,
    decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria uma ação presidencial com status=pending + snapshot BEFORE."""
    if categoria not in CATEGORIAS_EXECUTAVEIS:
        raise ValueError(
            f"categoria '{categoria}' não está nas autorizadas: "
            f"{list(CATEGORIAS_EXECUTAVEIS.keys())}")

    action_id = _new_id("pres-act")
    now = _now()
    action = {
        "id": action_id,
        "company_id": company_id,
        "source": source,
        "kind": "presidential",   # distingue do motor de eventos
        "categoria": categoria,
        "descricao": descricao,
        "prioridade": prioridade,
        "impacto_estimado_brl": float(impacto_estimado_brl or 0),
        "payload": payload or {},
        "decision_id": decision_id,
        "status": "pending",
        "created_at": _iso(now),
        "created_by": created_by,
        "approved_by": None,
        "approved_at": None,
        "executed_at": None,
        "completed_at": None,
        "executor_outcome": None,
        "council_consensus": None,    # preenchido após voto
        "snapshot_before_id": None,    # preenchido abaixo
        "snapshot_after_id": None,
        "roi_brl": None,
        "roi_pct": None,
        "history": [
            {"at": _iso(now), "actor": created_by,
              "event": "proposed", "to": "pending"},
        ],
    }
    await db.motor_ia_actions.insert_one(action)

    # snapshot BEFORE
    snap = await _take_snapshot(company_id, action_id, "before")
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"snapshot_before_id": snap["id"]}})

    return await get_action(action_id)


# ─────────────────────────────────────────────
#  ETAPA 2 — FILA + APROVAÇÃO
# ─────────────────────────────────────────────
async def approve_action(action_id: str, approver: str,
                            justification: str = "") -> Dict:
    """Aprovação humana. Move pending→approved e enfileira."""
    act = await _require_action(action_id)
    _ensure_transition(act["status"], "approved")
    now = _now()
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"status": "approved",
                     "approved_by": approver,
                     "approved_at": _iso(now)},
         "$push": {"history": {"at": _iso(now), "actor": approver,
                                  "event": "approved", "to": "approved",
                                  "justification": justification}}})
    # enfileira para execução
    await db.pending_executions.insert_one({
        "id": _new_id("queue"),
        "action_id": action_id,
        "company_id": act["company_id"],
        "categoria": act["categoria"],
        "enqueued_at": _iso(now),
        "picked_at": None,
        "status": "queued",
    })
    return await get_action(action_id)


async def cancel_action(action_id: str, actor: str,
                            reason: str = "") -> Dict:
    act = await _require_action(action_id)
    _ensure_transition(act["status"], "cancelled")
    now = _now()
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"status": "cancelled"},
         "$push": {"history": {"at": _iso(now), "actor": actor,
                                  "event": "cancelled", "to": "cancelled",
                                  "reason": reason}}})
    # remove da fila se existir
    await db.pending_executions.update_many(
        {"action_id": action_id, "status": "queued"},
        {"$set": {"status": "cancelled",
                     "cancelled_at": _iso(now)}})
    return await get_action(action_id)


# ─────────────────────────────────────────────
#  ETAPA 3 — EXECUÇÃO (com dry_run guard)
# ─────────────────────────────────────────────
async def execute_action(action_id: str, executor: str,
                            dry_run: bool = True) -> Dict:
    """Executa a ação. dry_run=True por padrão (regra P1: 'Nada
    automático ainda'). Apenas com aprovação prévia."""
    act = await _require_action(action_id)
    if act["status"] != "approved":
        raise ValueError(
            f"ação {action_id} status='{act['status']}'. "
            "Precisa estar 'approved' para executar.")
    _ensure_transition(act["status"], "executing")

    now = _now()
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"status": "executing",
                     "executed_at": _iso(now),
                     "executor": executor,
                     "dry_run": dry_run},
         "$push": {"history": {"at": _iso(now), "actor": executor,
                                  "event": "execution_started",
                                  "to": "executing",
                                  "dry_run": dry_run}}})
    # dispatch
    handler = _EXECUTORS.get(act["categoria"])
    if handler is None:
        return await _fail(action_id,
                              f"sem handler para {act['categoria']}")
    try:
        outcome = await handler(act, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        return await _fail(action_id, repr(e))

    # snapshot AFTER + ROI
    snap_after = await _take_snapshot(act["company_id"], action_id, "after")
    roi_brl, roi_pct = await _compute_roi(act["id"])

    completed_at = _iso(_now())
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"status": "completed",
                     "completed_at": completed_at,
                     "executor_outcome": outcome,
                     "snapshot_after_id": snap_after["id"],
                     "roi_brl": roi_brl,
                     "roi_pct": roi_pct},
         "$push": {"history": {"at": completed_at, "actor": executor,
                                  "event": "execution_completed",
                                  "to": "completed",
                                  "outcome": outcome}}})
    # remove fila
    await db.pending_executions.update_many(
        {"action_id": action_id, "status": "queued"},
        {"$set": {"status": "completed",
                     "picked_at": completed_at}})

    # APRENDIZADO — registra correction (previsto vs real)
    await _record_correction(action_id)

    return await get_action(action_id)


async def _fail(action_id: str, error: str) -> Dict:
    now = _iso(_now())
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"status": "failed",
                     "executor_outcome": {"ok": False, "error": error},
                     "completed_at": now},
         "$push": {"history": {"at": now, "actor": "executor",
                                  "event": "execution_failed",
                                  "to": "failed", "error": error}}})
    logger.error("[executor_ia] action %s failed: %s", action_id, error)
    return await get_action(action_id)


# ─────────────────────────────────────────────
#  ETAPA 3/4 — SNAPSHOTS
# ─────────────────────────────────────────────
async def _take_snapshot(company_id: str, action_id: str,
                              kind: str) -> Dict:
    """Captura estado executivo atual e grava em motor_ia_kpis."""
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)

    snap = {
        "id": _new_id(f"snap-{kind}"),
        "company_id": company_id,
        "action_id": action_id,
        "kind": kind,                 # 'before' | 'after'
        "captured_at": _iso(_now()),
        "metrics": {
            "mrr_brl": rep["contexto_financeiro"]["mrr_atual_brl"],
            "ticket_medio_brl":
                rep["contexto_financeiro"]["ticket_medio_brl"],
            "clientes_ativos":
                rep["contexto_financeiro"]["clientes_ativos"],
            "president_score": rep["president_score"]["score"],
            "president_status": rep["president_score"]["status"],
            "dinheiro_em_risco_brl":
                rep["dinheiro_em_risco"]["total_brl"],
            "dinheiro_recuperavel_brl":
                rep["dinheiro_recuperavel"]["total_brl"],
            "churn_previsto_30d_brl":
                rep["previsao_30d"]["churn_previsto_brl"],
            "churn_previsto_qty":
                rep["previsao_30d"]["churn_previsto_qty"],
            "receita_prevista_30d_brl":
                rep["previsao_30d"]["receita_prevista_brl"],
        },
    }
    await db.motor_ia_kpis.insert_one(snap)
    return snap


# ─────────────────────────────────────────────
#  ETAPA 5 — ROI
# ─────────────────────────────────────────────
async def _compute_roi(action_id: str) -> tuple[float, float]:
    """ROI = delta entre after e before, monetizado.

    Para REAJUSTE: ganho = mrr_after - mrr_before (recorrente)
    Para COBRANCA: ganho = inadimplência_recuperada
    Para LEO/RETENÇÃO: ganho = churn previsto evitado (delta)
    Para OS SMARTFIELD: ganho = dinheiro_em_risco reduzido
    """
    act = await db.motor_ia_actions.find_one({"id": action_id},
                                                  {"_id": 0})
    if not act:
        return 0.0, 0.0
    before_id = act.get("snapshot_before_id")
    after_id = act.get("snapshot_after_id")
    if not (before_id and after_id):
        return 0.0, 0.0
    before = await db.motor_ia_kpis.find_one({"id": before_id}, {"_id": 0})
    after = await db.motor_ia_kpis.find_one({"id": after_id}, {"_id": 0})
    if not (before and after):
        return 0.0, 0.0
    b = before["metrics"]
    a = after["metrics"]
    cat = act["categoria"]
    ganho = 0.0
    if cat == "REAJUSTE_IPCA":
        # diferença de MRR
        ganho = a["mrr_brl"] - b["mrr_brl"]
    elif cat == "DISPARO_COBRANCA":
        # redução de dinheiro em risco
        ganho = max(0.0,
                       b["dinheiro_em_risco_brl"]
                       - a["dinheiro_em_risco_brl"])
    elif cat in ("CONTATO_LEO_PROATIVO", "CAMPANHA_RETENCAO"):
        # churn previsto evitado
        ganho = max(0.0,
                       b["churn_previsto_30d_brl"]
                       - a["churn_previsto_30d_brl"])
    elif cat == "CRIACAO_OS_SMARTFIELD":
        # redução dinheiro em risco específico
        ganho = max(0.0,
                       b["dinheiro_em_risco_brl"]
                       - a["dinheiro_em_risco_brl"])
    base = act.get("impacto_estimado_brl") or 0.0
    pct = (ganho / base * 100.0) if base > 0 else 0.0
    return round(ganho, 2), round(pct, 1)


# ─────────────────────────────────────────────
#  ETAPA 6 — LEDGER
# ─────────────────────────────────────────────
async def get_action_ledger(action_id: str) -> Dict[str, Any]:
    """Histórico permanente de uma ação. Responde:
    quem decidiu / quem aprovou / quem executou / quanto custou /
    quanto retornou / ROI %."""
    act = await _require_action(action_id)
    snap_b = (await db.motor_ia_kpis.find_one(
        {"id": act.get("snapshot_before_id")}, {"_id": 0})
        if act.get("snapshot_before_id") else None)
    snap_a = (await db.motor_ia_kpis.find_one(
        {"id": act.get("snapshot_after_id")}, {"_id": 0})
        if act.get("snapshot_after_id") else None)
    votes = await db.conselho_votes.find(
        {"action_id": action_id}, {"_id": 0}).to_list(20)
    correction = await db.motor_ia_corrections.find_one(
        {"action_id": action_id}, {"_id": 0})
    return {
        "action": act,
        "quem_decidiu": act.get("created_by"),
        "quem_aprovou": act.get("approved_by"),
        "quem_executou": act.get("executor"),
        "decidido_em": act.get("created_at"),
        "aprovado_em": act.get("approved_at"),
        "executado_em": act.get("executed_at"),
        "concluido_em": act.get("completed_at"),
        "custo_estimado_brl": act.get("impacto_estimado_brl"),
        "retorno_brl": act.get("roi_brl"),
        "roi_pct": act.get("roi_pct"),
        "snapshot_before": snap_b,
        "snapshot_after": snap_a,
        "council_consensus": act.get("council_consensus"),
        "council_votes": votes,
        "correction": correction,
        "history": act.get("history", []),
    }


# ─────────────────────────────────────────────
#  ETAPA 7 — MEMÓRIA EXECUTIVA
# ─────────────────────────────────────────────
async def consult_memory(company_id: str, categoria: str,
                              limit: int = 5) -> Dict[str, Any]:
    """Reler ações semelhantes ANTES de recomendar. Retorna ROI
    histórico médio + lista das últimas N execuções da categoria."""
    cursor = db.motor_ia_actions.find(
        {"company_id": company_id, "categoria": categoria,
         "kind": "presidential", "status": "completed"},
        {"_id": 0, "id": 1, "descricao": 1, "roi_brl": 1, "roi_pct": 1,
         "completed_at": 1, "executor_outcome": 1,
         "impacto_estimado_brl": 1}
    ).sort([("completed_at", -1)]).limit(limit)
    items = await cursor.to_list(limit)
    if not items:
        return {"categoria": categoria, "historico_n": 0,
                  "roi_medio_brl": 0.0, "roi_medio_pct": 0.0,
                  "ultimas_acoes": []}
    rois = [x.get("roi_brl") or 0.0 for x in items]
    pcts = [x.get("roi_pct") or 0.0 for x in items]
    return {
        "categoria": categoria,
        "historico_n": len(items),
        "roi_medio_brl": round(sum(rois) / len(rois), 2),
        "roi_medio_pct": round(sum(pcts) / len(pcts), 1),
        "ultimas_acoes": items,
    }


# ─────────────────────────────────────────────
#  ETAPA 8 — APRENDIZADO (corrections + drift)
# ─────────────────────────────────────────────
async def _record_correction(action_id: str) -> None:
    """Registra previsto vs real. Atualiza drift por categoria."""
    act = await db.motor_ia_actions.find_one({"id": action_id},
                                                  {"_id": 0})
    if not act:
        return
    previsto = float(act.get("impacto_estimado_brl") or 0)
    real = float(act.get("roi_brl") or 0)
    diff = real - previsto
    acerto = previsto > 0 and abs(diff) / previsto <= 0.20  # ±20%
    confianca = (1.0 - min(abs(diff) / max(previsto, 1), 1.0)
                  if previsto > 0 else 0.0)
    motivo = ""
    if real == 0:
        motivo = "ROI=0: ação dry-run ou snapshot capturou estado idêntico"
    elif diff < 0:
        motivo = "Resultado abaixo do previsto"
    elif diff > 0:
        motivo = "Resultado acima do previsto"

    correction = {
        "id": _new_id("corr"),
        "action_id": action_id,
        "company_id": act["company_id"],
        "categoria": act["categoria"],
        "hipotese": act["descricao"],
        "valor_previsto_brl": previsto,
        "valor_real_brl": real,
        "diferenca_brl": round(diff, 2),
        "acerto": bool(acerto),
        "confianca": round(confianca, 3),
        "motivo": motivo,
        "created_at": _iso(_now()),
    }
    await db.motor_ia_corrections.insert_one(correction)

    # Atualiza drift por (company_id, categoria)
    pipeline = [
        {"$match": {"company_id": act["company_id"],
                       "categoria": act["categoria"]}},
        {"$group": {
            "_id": None,
            "n": {"$sum": 1},
            "acertos": {"$sum": {"$cond": ["$acerto", 1, 0]}},
            "media_dif": {"$avg": "$diferenca_brl"},
            "media_real": {"$avg": "$valor_real_brl"},
            "media_prev": {"$avg": "$valor_previsto_brl"},
        }}
    ]
    rows = await db.motor_ia_corrections.aggregate(pipeline).to_list(1)
    if rows:
        r = rows[0]
        await db.motor_ia_drift.update_one(
            {"company_id": act["company_id"],
             "categoria": act["categoria"]},
            {"$set": {
                "company_id": act["company_id"],
                "categoria": act["categoria"],
                "amostras": r["n"],
                "taxa_acerto": (round(r["acertos"] / r["n"], 3)
                                  if r["n"] else 0),
                "media_diferenca_brl": round(r["media_dif"], 2),
                "media_previsto_brl": round(r["media_prev"], 2),
                "media_real_brl": round(r["media_real"], 2),
                "drift_pct": (round((r["media_real"] - r["media_prev"])
                                       / max(r["media_prev"], 1) * 100, 1)
                               if r["media_prev"] else 0.0),
                "updated_at": _iso(_now()),
            }},
            upsert=True)


# ─────────────────────────────────────────────
#  ETAPA 9 — CONSELHO IA COM VOTO
# ─────────────────────────────────────────────
COUNCIL_SEATS = ["ceo", "cfo", "coo", "cto", "cmo", "cro"]


async def collect_council_votes(action_id: str) -> Dict[str, Any]:
    """Submete a ação às 6 cadeiras e grava voto formal.

    Heurísticas determinísticas (não LLM): mantém custo zero e
    auditável. Cada cadeira aprova/rejeita conforme regras objetivas
    sobre o snapshot e a ação proposta. Para uso LLM no futuro,
    basta substituir `_seat_vote_*` pela chamada ao Conselho IA.
    """
    act = await _require_action(action_id)
    before = (await db.motor_ia_kpis.find_one(
        {"id": act.get("snapshot_before_id")}, {"_id": 0})
        if act.get("snapshot_before_id") else None)
    metrics = (before or {}).get("metrics", {})

    votes: List[Dict[str, Any]] = []
    for seat in COUNCIL_SEATS:
        vote = _cast_seat_vote(seat, act, metrics)
        record = {
            "id": _new_id(f"vote-{seat}"),
            "action_id": action_id,
            "company_id": act["company_id"],
            "seat": seat,
            "vote": vote["vote"],           # 'aprovar' | 'rejeitar'
            "rationale": vote["rationale"],
            "created_at": _iso(_now()),
        }
        await db.conselho_votes.replace_one(
            {"action_id": action_id, "seat": seat},
            record, upsert=True)
        votes.append(record)

    aprovados = sum(1 for v in votes if v["vote"] == "aprovar")
    consensus = {
        "ratio": f"{aprovados}/{len(COUNCIL_SEATS)}",
        "approved_count": aprovados,
        "rejected_count": len(COUNCIL_SEATS) - aprovados,
        "divergencias": [v for v in votes if v["vote"] == "rejeitar"],
        "consenso": (
            "forte" if aprovados >= 5
            else "majoritario" if aprovados >= 4
            else "dividido" if aprovados >= 3
            else "rejeitado"),
    }
    await db.motor_ia_actions.update_one(
        {"id": action_id},
        {"$set": {"council_consensus": consensus},
         "$push": {"history": {
             "at": _iso(_now()), "actor": "conselho_ia",
             "event": "council_voted",
             "consensus": consensus["ratio"]}}})
    return {"votes": votes, "consensus": consensus}


def _cast_seat_vote(seat: str, act: Dict, metrics: Dict) -> Dict:
    """Voto heurístico por cadeira. Cada cadeira tem um foco:
    CEO=alinhamento estratégico · CFO=ROI · COO=operação · CTO=rede ·
    CMO=cliente · CRO=receita."""
    cat = act["categoria"]
    impacto = float(act.get("impacto_estimado_brl") or 0)
    mrr = float(metrics.get("mrr_brl") or 0)
    risco = float(metrics.get("dinheiro_em_risco_brl") or 0)

    if seat == "cfo":
        # CFO: aprova só se ROI estimado > 1% do MRR
        if impacto > mrr * 0.01:
            return {"vote": "aprovar",
                     "rationale": f"impacto R$ {impacto:.0f} > 1% MRR"}
        return {"vote": "rejeitar",
                "rationale": f"impacto R$ {impacto:.0f} sub-relevante "
                              f"(MRR {mrr:.0f})"}

    if seat == "cro":
        # CRO: aprova se afeta receita direta
        if cat in ("REAJUSTE_IPCA", "DISPARO_COBRANCA",
                    "CAMPANHA_RETENCAO"):
            return {"vote": "aprovar",
                     "rationale": f"{cat} ataca receita diretamente"}
        return {"vote": "aprovar",
                "rationale": f"{cat} preserva receita indireta"}

    if seat == "coo":
        # COO: rejeita se ação cria carga operacional sem capacidade
        if cat == "CRIACAO_OS_SMARTFIELD":
            payload = act.get("payload", {})
            qtd = payload.get("qtd_os") or payload.get("count") or 0
            if qtd > 100:
                return {"vote": "rejeitar",
                         "rationale": f"{qtd} OS de uma vez excede "
                                        "capacidade de campo"}
        return {"vote": "aprovar",
                "rationale": "carga operacional aceitável"}

    if seat == "cto":
        # CTO: aprova ações de rede; neutro para comerciais
        if cat == "CRIACAO_OS_SMARTFIELD":
            return {"vote": "aprovar",
                     "rationale": "ação técnica resolve degradação real"}
        return {"vote": "aprovar",
                "rationale": "sem impacto técnico negativo"}

    if seat == "cmo":
        # CMO: rejeita campanhas sem critério; aprova retenção
        if cat == "CAMPANHA_RETENCAO" and risco < 1000:
            return {"vote": "rejeitar",
                     "rationale": "risco de churn muito baixo, campanha "
                                   "queima budget"}
        return {"vote": "aprovar",
                "rationale": "alinhado ao plano de retenção/relacionamento"}

    # CEO: alinhamento estratégico (sempre que impacto > 0 e categoria
    # autorizada)
    if impacto > 0:
        return {"vote": "aprovar",
                "rationale": "alinhado ao OKR de execução presidencial"}
    return {"vote": "rejeitar",
            "rationale": "impacto não-monetizado, sem ROI estratégico"}


# ─────────────────────────────────────────────
#  ETAPA 10 — ESTADO DA PRESIDÊNCIA (9 perguntas)
# ─────────────────────────────────────────────
async def state_of_presidency(company_id: str,
                                   period_days: int = 30) -> Dict[str, Any]:
    """Responde as 9 perguntas obrigatórias da ordem P1."""
    cutoff = _iso(_now() - timedelta(days=period_days))
    q = {"company_id": company_id, "kind": "presidential",
         "created_at": {"$gte": cutoff}}

    async def _count(extra):
        return await db.motor_ia_actions.count_documents({**q, **extra})

    total = await _count({})
    aprovadas = await _count({"status": {"$in":
                                            ["approved", "executing",
                                             "completed", "failed"]}})
    executadas = await _count({"executed_at": {"$ne": None}})
    completadas = await _count({"status": "completed"})
    falhadas = await _count({"status": "failed"})

    # Resultados monetários
    pipe_roi = [
        {"$match": {**q, "status": "completed"}},
        {"$group": {"_id": None,
                       "ganho_total": {"$sum": "$roi_brl"},
                       "n": {"$sum": 1}}}
    ]
    roi_row = await db.motor_ia_actions.aggregate(pipe_roi).to_list(1)
    ganho_total = round(roi_row[0]["ganho_total"], 2) if roi_row else 0.0

    # Dinheiro salvo: soma roi onde categoria é defensiva
    pipe_salvo = [
        {"$match": {**q, "status": "completed",
                       "categoria": {"$in":
                                       ["DISPARO_COBRANCA",
                                         "CONTATO_LEO_PROATIVO",
                                         "CAMPANHA_RETENCAO",
                                         "CRIACAO_OS_SMARTFIELD"]}}},
        {"$group": {"_id": None,
                       "salvo": {"$sum": "$roi_brl"}}}
    ]
    salvo_row = await db.motor_ia_actions.aggregate(pipe_salvo).to_list(1)
    dinheiro_salvo = (round(salvo_row[0]["salvo"], 2)
                       if salvo_row else 0.0)

    # Dinheiro novo: soma roi onde categoria é receita
    pipe_novo = [
        {"$match": {**q, "status": "completed",
                       "categoria": "REAJUSTE_IPCA"}},
        {"$group": {"_id": None, "novo": {"$sum": "$roi_brl"}}}
    ]
    novo_row = await db.motor_ia_actions.aggregate(pipe_novo).to_list(1)
    dinheiro_novo = round(novo_row[0]["novo"], 2) if novo_row else 0.0

    # Falhas — última 3
    falhas_cursor = db.motor_ia_actions.find(
        {**q, "status": "failed"},
        {"_id": 0, "id": 1, "categoria": 1, "descricao": 1,
         "executor_outcome": 1, "completed_at": 1}
    ).sort([("completed_at", -1)]).limit(3)
    falhas = await falhas_cursor.to_list(3)

    # Aprendizado — agregado de drift
    drifts = await db.motor_ia_drift.find(
        {"company_id": company_id}, {"_id": 0}
    ).to_list(20)

    # Top 3 categorias por taxa de acerto
    drifts_ord = sorted(drifts,
                          key=lambda d: d.get("taxa_acerto", 0),
                          reverse=True)
    aprendizado = []
    for d in drifts_ord[:3]:
        aprendizado.append({
            "categoria": d["categoria"],
            "amostras": d["amostras"],
            "taxa_acerto_pct": round(d["taxa_acerto"] * 100, 1),
            "drift_pct": d["drift_pct"],
            "media_real_brl": d["media_real_brl"],
        })

    # O que farei diferente — baseado em drifts negativos
    farei_diferente = []
    for d in drifts:
        if (d.get("amostras", 0) >= 2
                and d.get("taxa_acerto", 1) < 0.6):
            farei_diferente.append({
                "categoria": d["categoria"],
                "ajuste": (f"Recalibrar projeções: real está "
                            f"{d['drift_pct']:+.1f}% vs previsto, "
                            f"acerto {d['taxa_acerto']*100:.0f}% em "
                            f"{d['amostras']} amostras"),
            })

    return {
        "company_id": company_id,
        "periodo_dias": period_days,
        "perguntas": {
            "1_recomendei": total,
            "2_aprovado": aprovadas,
            "3_executado": executadas,
            "4_gerou_resultado": completadas,
            "5_dinheiro_entrou_brl": dinheiro_novo,
            "6_dinheiro_salvo_brl": dinheiro_salvo,
            "7_deu_errado": {
                "qtd": falhadas,
                "ultimas": falhas,
            },
            "8_aprendi": aprendizado,
            "9_farei_diferente": farei_diferente,
        },
        "totais": {
            "ganho_total_brl": ganho_total,
            "acoes_total": total,
            "acoes_completadas": completadas,
            "taxa_execucao_pct": (round(executadas / total * 100, 1)
                                    if total else 0.0),
            "taxa_sucesso_pct": (round(completadas / max(executadas, 1)
                                          * 100, 1)),
        },
        "generated_at": _iso(_now()),
    }


# ─────────────────────────────────────────────
#  Listagem / leitura
# ─────────────────────────────────────────────
async def list_actions(company_id: str,
                          status: Optional[str] = None,
                          limit: int = 50) -> List[Dict]:
    q = {"company_id": company_id, "kind": "presidential"}
    if status:
        q["status"] = status
    cursor = db.motor_ia_actions.find(q, {"_id": 0}).sort(
        [("created_at", -1)]).limit(limit)
    return await cursor.to_list(limit)


async def list_queue(company_id: str) -> List[Dict]:
    cursor = db.pending_executions.find(
        {"company_id": company_id, "status": "queued"},
        {"_id": 0}).sort([("enqueued_at", 1)])
    return await cursor.to_list(100)


async def get_action(action_id: str) -> Dict:
    return await db.motor_ia_actions.find_one({"id": action_id},
                                                   {"_id": 0})


async def _require_action(action_id: str) -> Dict:
    act = await get_action(action_id)
    if not act:
        raise ValueError(f"ação {action_id} não encontrada")
    return act


def _ensure_transition(current: str, target: str) -> None:
    allowed = STATUS_FLOW.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"transição inválida: '{current}' → '{target}'. "
            f"Permitidas: {allowed}")


# ─────────────────────────────────────────────
#  EXECUTORES (5 categorias autorizadas)
#  Todos respeitam dry_run=True por padrão.
# ─────────────────────────────────────────────
async def _exec_reajuste_ipca(act: Dict, dry_run: bool) -> Dict:
    payload = act.get("payload", {})
    cid = act["company_id"]
    cutoff = _iso(_now() - timedelta(days=365))
    q_target = {
        "company_id": cid,
        "status": {"$in": ["ATIVO", "ATIVA"]},
        "$or": [
            {"last_readjustment_at": None},
            {"last_readjustment_at": {"$exists": False}},
            {"last_readjustment_at": {"$lt": cutoff}},
        ],
        "plan_price": {"$gt": 0},
    }
    candidatos = await db.subscribers.count_documents(q_target)
    pct = float(payload.get("ipca_pct") or 0.045)
    if dry_run:
        return {"ok": True, "dry_run": True,
                  "candidatos": candidatos, "pct": pct,
                  "msg": (f"[DRY-RUN] aplicaria {pct*100:.1f}% em "
                            f"{candidatos} contratos")}
    # Real: marca pretensão (a aplicação efetiva fica no motor de
    # reajuste já existente em services/readjustment_*)
    now = _iso(_now())
    res = await db.subscribers.update_many(
        q_target,
        {"$set": {"readjustment_pending_pct": pct,
                     "readjustment_pending_at": now,
                     "readjustment_proposed_by": act["id"]}})
    return {"ok": True, "dry_run": False,
            "matched": res.matched_count,
            "modified": res.modified_count, "pct": pct}


async def _exec_disparo_cobranca(act: Dict, dry_run: bool) -> Dict:
    cid = act["company_id"]
    q_target = {"company_id": cid,
                  "status": {"$in": ["ATIVO", "ATIVA"]},
                  "financial_status":
                      {"$regex": "inadimp|atrasad", "$options": "i"}}
    candidatos = await db.subscribers.count_documents(q_target)
    if dry_run:
        return {"ok": True, "dry_run": True,
                  "candidatos": candidatos,
                  "msg": (f"[DRY-RUN] enviaria régua de cobrança a "
                            f"{candidatos} inadimplentes")}
    # Real: cria registro de cobrança batch
    batch_id = _new_id("dunning")
    await db.dunning_events.insert_one({
        "id": batch_id, "company_id": cid,
        "action_id": act["id"], "kind": "regua_batch",
        "created_at": _iso(_now()),
        "target_count": candidatos, "status": "queued",
    })
    return {"ok": True, "dry_run": False,
            "batch_id": batch_id, "candidatos": candidatos}


async def _exec_contato_leo(act: Dict, dry_run: bool) -> Dict:
    """Leo Proativo nos clientes em risco previstos pelo Presidente."""
    cid = act["company_id"]
    payload = act.get("payload", {})
    limit = int(payload.get("limit") or 50)
    # Top N clientes degradados
    rows = await db.smartolt_onus.find(
        {"company_id": cid,
         "signal_text": {"$in": ["Critical", "Warning"]}},
        {"_id": 0, "subscriber_id": 1, "id": 1,
         "signal_text": 1, "name": 1}
    ).limit(limit).to_list(limit)
    if dry_run:
        return {"ok": True, "dry_run": True,
                  "candidatos": len(rows),
                  "msg": (f"[DRY-RUN] Leo contataria {len(rows)} "
                            "clientes proativamente")}
    # Real: enfileira mensagens
    enqueued = 0
    for r in rows:
        await db.leo_proactive_queue.insert_one({
            "id": _new_id("leo"), "company_id": cid,
            "action_id": act["id"],
            "subscriber_id": r.get("subscriber_id") or r.get("id"),
            "reason": f"signal_{r.get('signal_text', '')}",
            "queued_at": _iso(_now()), "status": "queued",
        })
        enqueued += 1
    return {"ok": True, "dry_run": False, "enqueued": enqueued}


async def _exec_criar_os_smartfield(act: Dict, dry_run: bool) -> Dict:
    cid = act["company_id"]
    rows = await db.smartolt_onus.find(
        {"company_id": cid, "signal_text": "Critical"},
        {"_id": 0, "subscriber_id": 1, "id": 1, "name": 1}
    ).limit(100).to_list(100)
    if dry_run:
        return {"ok": True, "dry_run": True,
                  "candidatos": len(rows),
                  "msg": (f"[DRY-RUN] abriria {len(rows)} OS "
                            "preventivas para ONUs Critical")}
    created = 0
    for r in rows:
        await db.smart_repairs.insert_one({
            "id": _new_id("os"),
            "company_id": cid, "action_id": act["id"],
            "subscriber_id": r.get("subscriber_id") or r.get("id"),
            "kind": "preventiva_sinal_critical",
            "status": "queued", "created_at": _iso(_now()),
        })
        created += 1
    return {"ok": True, "dry_run": False, "created": created}


async def _exec_campanha_retencao(act: Dict, dry_run: bool) -> Dict:
    cid = act["company_id"]
    payload = act.get("payload", {})
    target = int(payload.get("target") or 50)
    rows = await db.smartolt_onus.find(
        {"company_id": cid,
         "signal_text": {"$in": ["Critical", "Warning"]}},
        {"_id": 0, "subscriber_id": 1, "id": 1}
    ).limit(target).to_list(target)
    if dry_run:
        return {"ok": True, "dry_run": True,
                  "candidatos": len(rows),
                  "msg": (f"[DRY-RUN] campanha de retenção a "
                            f"{len(rows)} clientes em risco")}
    enqueued = 0
    for r in rows:
        await db.mass_messaging_queue.insert_one({
            "id": _new_id("ret"), "company_id": cid,
            "action_id": act["id"],
            "subscriber_id": r.get("subscriber_id") or r.get("id"),
            "campaign": "retencao_risco_sinal",
            "queued_at": _iso(_now()), "status": "queued",
        })
        enqueued += 1
    return {"ok": True, "dry_run": False, "enqueued": enqueued}


_EXECUTORS = {
    "REAJUSTE_IPCA": _exec_reajuste_ipca,
    "DISPARO_COBRANCA": _exec_disparo_cobranca,
    "CONTATO_LEO_PROATIVO": _exec_contato_leo,
    "CRIACAO_OS_SMARTFIELD": _exec_criar_os_smartfield,
    "CAMPANHA_RETENCAO": _exec_campanha_retencao,
}
