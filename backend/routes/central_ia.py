"""Central IA — Dashboard de KPIs + alertas proativos.

Arquitetura:
- Worker em background avalia conversas (closed ou stale 1h+) via LLM e
  grava `aihub_evaluations`: {csat, sentiment, fcr, intent, alerts, tags}.
- Endpoints agregam evaluations em KPIs (FRT, CSAT, FCR, ARR), ranking
  de atendentes (IA vs humanos), top intents, alertas ativos.
- Alertas proativos detectam: conversa sem resposta >30min, CSAT baixo
  recorrente, queda de performance de atendente.

KPIs implementados (best practices 2026):
- FRT (First Response Time) — tempo até primeira resposta
- CSAT (0-10, nota auto-avaliada pela IA)
- FCR % (First Contact Resolution — IA detecta se resolveu)
- ARR % (AI Resolution Rate — % de convs fechadas só pela IA)
- Sentiment ratio (positivo/neutro/negativo)
- Volume por atendente
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.central_ia")
router = APIRouter(prefix="/api/central-ia", tags=["central-ia"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Worker — avalia conversas via LLM
# ---------------------------------------------------------------------------
EVAL_SYSTEM = (
    "Você é um avaliador de qualidade de atendimento ao cliente de "
    "provedores de internet brasileiros. Analise a conversa e devolva "
    "EXCLUSIVAMENTE um JSON válido (sem markdown, sem prefixo) com os campos:\n"
    "- csat_score (0 a 10, número): satisfação estimada do cliente.\n"
    "- sentiment (string): 'positivo' | 'neutro' | 'negativo'.\n"
    "- fcr (boolean): true se resolveu na primeira interação.\n"
    "- resolution_outcome (string): 'resolvido' | 'escalado' | 'abandonado' | 'em_aberto'.\n"
    "- intent_category (string): categoria da demanda. Use uma das opções: "
    "'venda_nova', 'suporte_lentidao', 'suporte_sem_sinal', 'agendamento_visita', "
    "'fatura_segunda_via', 'cancelamento', 'mudanca_plano', 'outros'.\n"
    "- alerts (array de strings curtas): problemas detectados que merecem "
    "atenção do gestor. Vazio se nenhum. Ex.: 'cliente irritado', 'aguardou 15min', "
    "'informação incorreta', 'oportunidade venda'.\n"
    "- summary (string): resumo de 1 frase em PT-BR (max 120 chars)."
)


COACHING_SYSTEM = (
    "Você é um coach de atendimento sênior de provedores de internet "
    "brasileiros. Analise a conversa e gere coaching DIRETO e ACIONÁVEL "
    "para o atendente humano. Devolva EXCLUSIVAMENTE JSON com:\n"
    "- score (0-10): nota geral do atendimento.\n"
    "- strengths (array de 1-3 strings): o que o atendente fez bem (português).\n"
    "- improvements (array de 2-4 strings): pontos específicos a melhorar. "
    "  Cada item DEVE citar comportamento concreto observado (não genéricos). "
    "  Ex.: 'Você levou 18 min para a primeira resposta — meta é 5 min', "
    "       'Não cumprimentou pelo nome do cliente (Carlos), apesar de "
    "        ele ter mencionado 3x na conversa'.\n"
    "- next_action (string): 1 frase com a ação concreta para o próximo "
    "  atendimento similar. Max 140 chars.\n"
    "- tone (string): 'positivo' | 'construtivo' | 'urgente' — conforme a gravidade."
)



async def _llm_evaluate(transcript: str) -> Optional[Dict[str, Any]]:
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError:
        return None
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"eval-{uuid.uuid4().hex[:8]}",
            system_message=EVAL_SYSTEM,
        ).with_model("openai", "gpt-4o-mini")
        try:
            chat = chat.with_temperature(0.2)  # type: ignore
        except Exception:
            pass
        try:
            chat = chat.with_max_tokens(400)  # type: ignore
        except Exception:
            pass
        resp = await chat.send_message(UserMessage(text=transcript[:6000]))
        text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
        text = (text or "").strip()
        # Remove possíveis cercas markdown
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        logger.warning("[central-ia.eval] LLM falhou: %s", e)
        return None


async def _build_transcript_from_phone(cid: str, phone: str) -> Optional[str]:
    """Monta o transcript da conversa para o LLM avaliar."""
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "direction": 1, "text": 1, "created_at": 1, "auto_reply": 1},
    ).sort("created_at", 1).to_list(500)
    if len(docs) < 2:
        return None
    lines = []
    for m in docs:
        role = ("Cliente" if m["direction"] == "inbound"
                else ("Atendente_IA" if m.get("auto_reply") else "Atendente_Humano"))
        lines.append(f"{role}: {(m.get('text') or '').strip()}")
    return "\n".join(lines)


async def _evaluate_conversation(cid: str, phone: str,
                                    skip_auto_coach: bool = False) -> Optional[Dict[str, Any]]:
    """Avalia uma conversa específica e persiste em `aihub_evaluations`."""
    # Pega assignee atual
    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0}
    ) or {}
    transcript = await _build_transcript_from_phone(cid, phone)
    if not transcript:
        return None
    # Calcula FRT (First Response Time) em segundos
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "direction": 1, "created_at": 1, "auto_reply": 1},
    ).sort("created_at", 1).to_list(100)
    first_inbound = next((m for m in docs if m["direction"] == "inbound"), None)
    first_reply = next((m for m in docs
                          if m["direction"] == "outbound"
                          and m.get("created_at") > (first_inbound or {}).get("created_at", "")),
                         None) if first_inbound else None
    frt_seconds = None
    if first_inbound and first_reply:
        t1 = _parse_iso(first_inbound.get("created_at"))
        t2 = _parse_iso(first_reply.get("created_at"))
        if t1 and t2:
            frt_seconds = max(0, int((t2 - t1).total_seconds()))    # ARR — conversa resolvida só com IA?
    has_human_outbound = any(
        m["direction"] == "outbound" and not m.get("auto_reply") for m in docs
    )

    ai_result = await _llm_evaluate(transcript)
    if not ai_result:
        return None

    eval_doc = {
        "id": f"eval-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "phone": phone,
        "transcript_len": len(transcript),
        "msg_count": len(docs),
        "csat_score": float(ai_result.get("csat_score") or 0),
        "sentiment": str(ai_result.get("sentiment") or "neutro"),
        "fcr": bool(ai_result.get("fcr")),
        "resolution_outcome": str(ai_result.get("resolution_outcome") or "em_aberto"),
        "intent_category": str(ai_result.get("intent_category") or "outros"),
        "alerts": list(ai_result.get("alerts") or [])[:5],
        "summary": str(ai_result.get("summary") or "")[:300],
        "frt_seconds": frt_seconds,
        "is_ai_only": not has_human_outbound,
        "assignee_user_id": conv.get("assignee_user_id"),
        "assignee_role": conv.get("assignee_role"),
        "evaluated_at": now_iso(),
    }
    # Upsert por (company_id, phone, last_evaluation_window) — deixa simples:
    # 1 eval por conversa fechada/avaliada. Substitui se já existir.
    await db.aihub_evaluations.update_one(
        {"company_id": cid, "phone": phone, "conversation_status": "current"},
        {"$set": {**eval_doc, "conversation_status": "current"}},
        upsert=True,
    )

    # Auto-coaching: se atendente HUMANO + CSAT < 7, gera coaching
    if (not skip_auto_coach
            and eval_doc.get("assignee_user_id") and not eval_doc["is_ai_only"]
            and eval_doc["csat_score"] < 7):
        try:
            await _generate_coaching(cid, phone, transcript, eval_doc)
        except Exception as e:
            logger.warning("[central-ia.coach] falhou: %s", e)
    return eval_doc


async def _llm_coach(transcript: str, eval_doc: dict) -> Optional[Dict[str, Any]]:
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError:
        return None
    user_text = (
        f"Conversa avaliada com CSAT={eval_doc.get('csat_score')}, "
        f"sentimento={eval_doc.get('sentiment')}, "
        f"FRT={eval_doc.get('frt_seconds')}s, "
        f"FCR={'sim' if eval_doc.get('fcr') else 'não'}.\n\n"
        f"Transcript:\n---\n{transcript[:4500]}\n---\n\n"
        "Gere o coaching JSON conforme instruído."
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"coach-{uuid.uuid4().hex[:8]}",
            system_message=COACHING_SYSTEM,
        ).with_model("openai", "gpt-4o-mini")
        try:
            chat = chat.with_temperature(0.3)  # type: ignore
        except Exception:
            pass
        try:
            chat = chat.with_max_tokens(450)  # type: ignore
        except Exception:
            pass
        resp = await chat.send_message(UserMessage(text=user_text))
        text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        logger.warning("[central-ia.coach] LLM falhou: %s", e)
        return None


async def _generate_coaching(cid: str, phone: str, transcript: str,
                                eval_doc: dict) -> Optional[Dict[str, Any]]:
    """Gera 1 doc de coaching via LLM e persiste em aihub_coaching."""
    coach = await _llm_coach(transcript, eval_doc)
    if not coach:
        return None
    uid = eval_doc.get("assignee_user_id")
    u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1})
    coach_doc = {
        "id": f"coach-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "phone": phone,
        "user_id": uid,
        "user_name": (u or {}).get("name"),
        "user_email": (u or {}).get("email"),
        "score": float(coach.get("score") or 0),
        "tone": str(coach.get("tone") or "construtivo"),
        "strengths": list(coach.get("strengths") or [])[:3],
        "improvements": list(coach.get("improvements") or [])[:5],
        "next_action": str(coach.get("next_action") or "")[:200],
        "csat_at_time": eval_doc.get("csat_score"),
        "intent": eval_doc.get("intent_category"),
        "summary_eval": eval_doc.get("summary"),
        "read": False,
        "acknowledged": False,
        "created_at": now_iso(),
    }
    await db.aihub_coaching.insert_one(dict(coach_doc))
    coach_doc.pop("_id", None)
    logger.info("[central-ia.coach] gerado para %s (user=%s, csat=%s)",
                phone, (u or {}).get("name"), eval_doc.get("csat_score"))
    return coach_doc


# ---------------------------------------------------------------------------
# Worker loop — re-avalia conversas a cada 5min
# ---------------------------------------------------------------------------
_WORKER_TASK: Optional[asyncio.Task] = None
_WORKER_RUN = True
_WORKER_INTERVAL_SEC = 300  # 5min


async def _worker_tick() -> None:
    """A cada tick, pega convs com mensagens novas desde a última avaliação."""
    try:
        # Lista todas as conversas ativas (com >=2 mensagens nos últimos 7 dias)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        pipeline = [
            {"$match": {"created_at": {"$gte": cutoff}}},
            {"$group": {
                "_id": {"company_id": "$company_id", "phone": "$phone"},
                "msg_count": {"$sum": 1},
                "last_msg": {"$max": "$created_at"},
            }},
            {"$match": {"msg_count": {"$gte": 2}}},
            {"$limit": 100},
        ]
        rows = await db.aihub_wa_messages.aggregate(pipeline).to_list(100)
        evaluated = 0
        for r in rows:
            key = r["_id"]
            cid = key.get("company_id")
            phone = key.get("phone")
            if not cid or not phone:
                continue
            # Pula se eval recente (menos de 10min)
            existing = await db.aihub_evaluations.find_one(
                {"company_id": cid, "phone": phone},
                {"_id": 0, "evaluated_at": 1, "msg_count": 1},
            )
            if existing:
                t = _parse_iso(existing.get("evaluated_at"))
                if t and (datetime.now(timezone.utc) - t).total_seconds() < 600:
                    continue
                # Pula se contagem não cresceu
                if existing.get("msg_count") == r.get("msg_count"):
                    continue
            try:
                await _evaluate_conversation(cid, phone)
                evaluated += 1
            except Exception as e:
                logger.warning("[central-ia.worker] eval %s falhou: %s", phone, e)
        if evaluated:
            logger.info("[central-ia.worker] avaliou %d conversas", evaluated)
    except Exception as e:
        logger.warning("[central-ia.worker] tick falhou: %s", e)


async def _worker_loop() -> None:
    while _WORKER_RUN:
        await _worker_tick()
        await asyncio.sleep(_WORKER_INTERVAL_SEC)


async def start_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK and not _WORKER_TASK.done():
        return
    _WORKER_TASK = asyncio.create_task(_worker_loop())
    logger.info("[central-ia.worker] started (every %ss)", _WORKER_INTERVAL_SEC)


def stop_worker() -> None:
    global _WORKER_RUN
    _WORKER_RUN = False
    if _WORKER_TASK:
        _WORKER_TASK.cancel()


# ---------------------------------------------------------------------------
# Endpoint: forçar avaliação manual
# ---------------------------------------------------------------------------
@router.post("/evaluations/{phone}")
async def evaluate_now(phone: str, user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    result = await _evaluate_conversation(cid, phone)
    if not result:
        raise HTTPException(400, "Conversa muito curta ou falha na avaliação.")
    return result


@router.get("/evaluations")
async def list_evaluations(limit: int = 200,
                             user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    docs = await db.aihub_evaluations.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("evaluated_at", -1).limit(min(limit, 500)).to_list(500)
    return {"items": docs, "count": len(docs)}


# ---------------------------------------------------------------------------
# KPI Dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard/kpis")
async def get_kpis(days: int = Query(7, ge=1, le=90),
                     user: dict = Depends(require_role("gestor"))):
    """KPIs agregados nas últimas N janelas de dias."""
    cid = _cid(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    evals = await db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(2000)
    n = len(evals)
    if n == 0:
        return {
            "days": days, "total_conversations": 0,
            "csat_avg": None, "frt_avg_seconds": None,
            "fcr_rate": None, "arr_rate": None,
            "sentiment": {"positivo": 0, "neutro": 0, "negativo": 0},
            "no_data": True,
        }
    csats = [e["csat_score"] for e in evals if e.get("csat_score") is not None]
    frts = [e["frt_seconds"] for e in evals if e.get("frt_seconds") is not None]
    fcrs = sum(1 for e in evals if e.get("fcr"))
    arrs = sum(1 for e in evals if e.get("is_ai_only"))
    sentiments = {"positivo": 0, "neutro": 0, "negativo": 0}
    for e in evals:
        s = e.get("sentiment", "neutro")
        sentiments[s] = sentiments.get(s, 0) + 1
    return {
        "days": days, "total_conversations": n,
        "csat_avg": round(sum(csats) / len(csats), 2) if csats else None,
        "csat_count": len(csats),
        "frt_avg_seconds": int(sum(frts) / len(frts)) if frts else None,
        "frt_p90_seconds": (sorted(frts)[int(len(frts) * 0.9)]
                              if len(frts) >= 5 else None),
        "fcr_rate": round(fcrs / n * 100, 1) if n else None,
        "arr_rate": round(arrs / n * 100, 1) if n else None,
        "sentiment": sentiments,
        "no_data": False,
    }


@router.get("/dashboard/attendants")
async def attendants_ranking(days: int = Query(7, ge=1, le=90),
                                user: dict = Depends(require_role("gestor"))):
    """Ranking de atendentes (IA vs Humanos) por volume + qualidade."""
    cid = _cid(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    evals = await db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(2000)
    # Agrega por assignee
    by_assignee: Dict[str, Dict[str, Any]] = {}
    for e in evals:
        # Pra ARR (conversas só-IA), conta sob "Isabella (IA)"
        if e.get("is_ai_only"):
            key = "AI"
        else:
            uid = e.get("assignee_user_id") or "unassigned"
            key = uid
        bucket = by_assignee.setdefault(key, {
            "user_id": None if key in ("AI", "unassigned") else key,
            "name": ("Isabella (IA)" if key == "AI"
                       else "Sem atribuição" if key == "unassigned" else None),
            "is_ai": key == "AI",
            "count": 0, "csat_sum": 0, "csat_n": 0,
            "fcr_count": 0, "frt_sum": 0, "frt_n": 0,
            "sentiment_neg": 0,
        })
        bucket["count"] += 1
        if e.get("csat_score") is not None:
            bucket["csat_sum"] += e["csat_score"]
            bucket["csat_n"] += 1
        if e.get("fcr"):
            bucket["fcr_count"] += 1
        if e.get("frt_seconds") is not None:
            bucket["frt_sum"] += e["frt_seconds"]
            bucket["frt_n"] += 1
        if e.get("sentiment") == "negativo":
            bucket["sentiment_neg"] += 1
    # Resolve nomes dos usuários humanos
    user_ids = [k for k in by_assignee if k not in ("AI", "unassigned")]
    if user_ids:
        async for u in db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "google_picture": 1},
        ):
            if u["id"] in by_assignee:
                by_assignee[u["id"]]["name"] = u.get("name") or u["id"]
                by_assignee[u["id"]]["avatar"] = u.get("avatar_url") or u.get("google_picture")
    # Computa médias finais
    items = []
    for k, v in by_assignee.items():
        items.append({
            "user_id": v["user_id"],
            "name": v["name"] or k,
            "avatar": v.get("avatar"),
            "is_ai": v["is_ai"],
            "volume": v["count"],
            "csat_avg": round(v["csat_sum"] / v["csat_n"], 2) if v["csat_n"] else None,
            "fcr_rate": round(v["fcr_count"] / v["count"] * 100, 1) if v["count"] else None,
            "frt_avg_seconds": int(v["frt_sum"] / v["frt_n"]) if v["frt_n"] else None,
            "negative_count": v["sentiment_neg"],
        })
    items.sort(key=lambda x: (-(x["volume"] or 0), -(x.get("csat_avg") or 0)))
    return {"items": items, "days": days}


@router.get("/dashboard/intents")
async def top_intents(days: int = Query(7, ge=1, le=90),
                       user: dict = Depends(require_role("gestor"))):
    """Top motivos de contato (intents)."""
    cid = _cid(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    evals = await db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff}},
        {"_id": 0, "intent_category": 1, "csat_score": 1},
    ).to_list(2000)
    by_intent: Dict[str, Dict[str, Any]] = {}
    for e in evals:
        key = e.get("intent_category") or "outros"
        b = by_intent.setdefault(key, {"intent": key, "count": 0,
                                          "csat_sum": 0, "csat_n": 0})
        b["count"] += 1
        if e.get("csat_score") is not None:
            b["csat_sum"] += e["csat_score"]
            b["csat_n"] += 1
    items = []
    for v in by_intent.values():
        items.append({
            "intent": v["intent"], "count": v["count"],
            "csat_avg": round(v["csat_sum"] / v["csat_n"], 2) if v["csat_n"] else None,
        })
    items.sort(key=lambda x: -x["count"])
    total = sum(i["count"] for i in items) or 1
    for i in items:
        i["pct"] = round(i["count"] / total * 100, 1)
    return {"items": items[:10], "total": total}


# ---------------------------------------------------------------------------
# Alertas proativos
# ---------------------------------------------------------------------------
@router.get("/alerts")
async def list_alerts(user: dict = Depends(require_role("gestor"))):
    """Alertas proativos detectados:
    - Conversas com `alerts` array do LLM nas últimas 24h
    - Conversas sem resposta há >30min
    - Quedas de CSAT por atendente (≥3 evals com média <6 nas últimas 24h)
    """
    cid = _cid(user)
    now = datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []

    # 1) LLM-flagged alerts (últimas 24h)
    cutoff = (now - timedelta(hours=24)).isoformat()
    evals = await db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff},
         "alerts": {"$exists": True, "$ne": []}},
        {"_id": 0},
    ).sort("evaluated_at", -1).to_list(50)
    for e in evals:
        for a in e.get("alerts") or []:
            items.append({
                "id": f"a-{e['id']}-{hash(a) & 0xffff:04x}",
                "kind": "llm_flag",
                "severity": "warning",
                "phone": e.get("phone"),
                "title": a[:120],
                "subtitle": (e.get("summary") or "")[:120],
                "intent": e.get("intent_category"),
                "csat_score": e.get("csat_score"),
                "created_at": e.get("evaluated_at"),
            })

    # 2) Conversas sem resposta há >30min
    stale_cutoff = (now - timedelta(minutes=30)).isoformat()
    stale = []
    async for c in db.wa_conversations.find(
        {"company_id": cid, "status": {"$ne": "closed"},
         "assignee_role": "human"},
        {"_id": 0},
    ):
        # Pega last_message_at via aihub_wa_messages
        last = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "phone": c.get("phone")},
            {"_id": 0, "created_at": 1, "direction": 1},
            sort=[("created_at", -1)],
        )
        if last and last.get("direction") == "inbound" \
                and last.get("created_at", "") < stale_cutoff:
            stale.append((c, last))
    for c, last in stale[:30]:
        mins_ago = int((now - _parse_iso(last["created_at"])).total_seconds() / 60) \
            if _parse_iso(last["created_at"]) else 0
        items.append({
            "id": f"a-stale-{c['phone']}",
            "kind": "stale_conversation",
            "severity": "warning" if mins_ago < 120 else "critical",
            "phone": c.get("phone"),
            "title": f"Conversa sem resposta há {mins_ago} min",
            "subtitle": "Atendente atribuído não respondeu",
            "created_at": last.get("created_at"),
        })

    # 3) CSAT baixo por atendente nas últimas 24h
    user_csats: Dict[str, List[float]] = {}
    for e in evals:
        uid = e.get("assignee_user_id")
        if uid and e.get("csat_score") is not None:
            user_csats.setdefault(uid, []).append(e["csat_score"])
    for uid, scores in user_csats.items():
        if len(scores) >= 3 and (sum(scores) / len(scores)) < 6:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1})
            avg = round(sum(scores) / len(scores), 2)
            items.append({
                "id": f"a-csat-{uid}",
                "kind": "low_csat_attendant",
                "severity": "critical",
                "user_id": uid,
                "title": f"{(u or {}).get('name', 'Atendente')} com CSAT {avg} nas últimas 24h",
                "subtitle": f"{len(scores)} avaliações abaixo da média",
                "created_at": now_iso(),
            })

    # Ordena por severidade primeiro, depois created_at desc (string ISO compara OK)
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    items.sort(key=lambda x: sev_order.get(x.get("severity"), 9))
    return {"items": items[:50], "count": len(items)}


# ---------------------------------------------------------------------------
# Endpoint compacto pra Home
# ---------------------------------------------------------------------------
@router.get("/dashboard/summary")
async def dashboard_summary(user: dict = Depends(require_role("gestor"))):
    """Resumo compacto pra card de Home."""
    cid = _cid(user)
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    evals_24h = await db.aihub_evaluations.count_documents(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff_24h}}
    )
    alerts = await db.aihub_evaluations.count_documents(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff_24h},
         "alerts": {"$exists": True, "$ne": []}}
    )
    csat_docs = await db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff_24h},
         "csat_score": {"$ne": None}},
        {"_id": 0, "csat_score": 1},
    ).to_list(1000)
    csat_avg = (round(sum(d["csat_score"] for d in csat_docs) / len(csat_docs), 2)
                  if csat_docs else None)
    return {
        "evaluated_24h": evals_24h,
        "alerts_24h": alerts,
        "csat_avg_24h": csat_avg,
    }


# ---------------------------------------------------------------------------
# Coaching endpoints
# ---------------------------------------------------------------------------
@router.get("/coaching")
async def list_coaching(user_id: Optional[str] = None,
                          unread_only: bool = False,
                          include_dismissed: bool = False, limit: int = 50,
                          user: dict = Depends(require_role("auditor"))):
    """Lista coachings — INDIVIDUAL por usuário logado.

    - Auditor/colaborador comum: vê só os PRÓPRIOS coachings (filtrados por user["id"]).
    - Administrador/gestor: pode passar `user_id` no query string para ver
      coaching de qualquer atendente, ou omitir para ver os próprios.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    is_admin = user.get("role") in ("gestor", "administrador")
    target_user_id = user_id if (is_admin and user_id) else user["id"]
    q: Dict[str, Any] = {"company_id": cid, "user_id": target_user_id}
    if unread_only:
        q["read"] = {"$ne": True}
    if not include_dismissed:
        q["dismissed"] = {"$ne": True}
    docs = await db.aihub_coaching.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(min(limit, 200)).to_list(200)
    return {"items": docs, "count": len(docs),
            "viewing_user_id": target_user_id,
            "is_own": target_user_id == user["id"]}


@router.get("/coaching/by-user")
async def coaching_by_user(days: int = Query(7, ge=1, le=90),
                              user: dict = Depends(require_role("gestor"))):
    """Agrupa coachings por atendente — útil pra ranking de aprendizado."""
    cid = _cid(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    docs = await db.aihub_coaching.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(500)
    by_user: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        uid = d.get("user_id") or "unknown"
        b = by_user.setdefault(uid, {
            "user_id": uid, "user_name": d.get("user_name"),
            "count": 0, "score_sum": 0,
            "tones": {"positivo": 0, "construtivo": 0, "urgente": 0},
            "unread": 0, "ack": 0,
        })
        b["count"] += 1
        b["score_sum"] += d.get("score") or 0
        tone = d.get("tone", "construtivo")
        b["tones"][tone] = b["tones"].get(tone, 0) + 1
        if not d.get("read"):
            b["unread"] += 1
        if d.get("acknowledged"):
            b["ack"] += 1
    items = []
    for v in by_user.values():
        items.append({
            "user_id": v["user_id"],
            "user_name": v["user_name"],
            "count": v["count"],
            "avg_score": round(v["score_sum"] / v["count"], 2) if v["count"] else 0,
            "tones": v["tones"], "unread": v["unread"], "ack": v["ack"],
        })
    items.sort(key=lambda x: -x["count"])
    return {"items": items, "days": days}


@router.get("/coaching/for-conversation/{phone}")
async def coaching_for_conversation(phone: str,
                                       user: dict = Depends(require_role("auditor"))):
    """Coachings desta conversa específica para o usuário logado (popup do chat)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.aihub_coaching.find(
        {"company_id": cid, "phone": phone, "user_id": user["id"],
         "dismissed": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1).limit(5).to_list(5)
    return {"items": docs, "count": len(docs),
             "unread": sum(1 for d in docs if not d.get("read"))}


class CoachingActionIn(BaseModel):
    coaching_id: str
    action: str  # "read" | "acknowledged" | "dismiss"


@router.post("/coaching/action")
async def coaching_action(payload: CoachingActionIn,
                            user: dict = Depends(require_role("auditor"))):
    cid = _cid(user)
    if payload.action not in ("read", "acknowledged", "dismiss"):
        raise HTTPException(400, "action inválida.")
    # Restrição: usuários comuns só atualizam seus próprios coachings
    is_admin = user.get("role") in ("gestor", "administrador")
    coach_doc = await db.aihub_coaching.find_one(
        {"id": payload.coaching_id, "company_id": cid}, {"_id": 0}
    )
    if not coach_doc:
        raise HTTPException(404, "Coaching não encontrado.")
    if not is_admin and coach_doc.get("user_id") != user.get("id"):
        raise HTTPException(403, "Sem permissão para alterar coaching de outro usuário.")
    update: Dict[str, Any] = {"updated_at": now_iso()}
    if payload.action == "read":
        update["read"] = True
    elif payload.action == "acknowledged":
        update["read"] = True
        update["acknowledged"] = True
        update["acknowledged_at"] = now_iso()
    elif payload.action == "dismiss":
        update["read"] = True
        update["dismissed"] = True
    await db.aihub_coaching.update_one(
        {"id": payload.coaching_id, "company_id": cid},
        {"$set": update},
    )
    return {"ok": True}


class GenerateCoachingIn(BaseModel):
    phone: str


@router.post("/coaching/generate")
async def generate_coaching_now(payload: GenerateCoachingIn,
                                  user: dict = Depends(require_role("gestor"))):
    """Força geração de coaching para uma conversa específica."""
    cid = _cid(user)
    ev = await _evaluate_conversation(cid, payload.phone, skip_auto_coach=True)
    if not ev:
        raise HTTPException(400, "Conversa muito curta ou avaliação falhou.")
    if ev.get("is_ai_only"):
        raise HTTPException(400,
                            "Conversa atendida só pela IA — coaching é para humanos.")
    if not ev.get("assignee_user_id"):
        raise HTTPException(400, "Conversa sem atendente atribuído.")
    transcript = await _build_transcript_from_phone(cid, payload.phone)
    if not transcript:
        raise HTTPException(400, "Sem transcript suficiente.")
    coach = await _generate_coaching(cid, payload.phone, transcript, ev)
    if not coach:
        raise HTTPException(502, "LLM coach falhou.")
    return coach
