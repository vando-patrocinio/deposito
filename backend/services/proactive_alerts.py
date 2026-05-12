"""Proactive Alerts — sistema avisa o gestor por WhatsApp em eventos críticos
e aguarda decisão dele (sim/não/cancela).

Fluxo:
  1. Worker (SmartOLT, Sentinela, etc) chama `notify_outage(cid, outage)`
  2. Mensagem com pergunta é enviada via sidecar Baileys ao gestor da whitelist
  3. Estado é persistido em `manager_assistant_pending` com TTL 30min
  4. Quando o gestor responde, `manager_assistant.py` consulta pending e executa
     a ação correspondente (broadcast, ignore, etc).

Ações suportadas:
  - "outage_broadcast": envia aviso pré-aprovado para todos os clientes da OLT afetada
  - "outage_ignore":    apenas marca como visualizado, sem ação adicional
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from core import now_iso
from database import db

logger = logging.getLogger("proactive_alerts")

SIDECAR_BASE = os.environ.get("WHATSAPP_SIDECAR_BASE", "http://127.0.0.1:3002")
PENDING_TTL_MINUTES = 30
COOLDOWN_OUTAGE_MINUTES = 30   # não reavisar do mesmo outage por 30min


# ---------------------------------------------------------------------------
# Whitelist & envio
# ---------------------------------------------------------------------------
async def _gather_manager_phones(company_id: str) -> List[str]:
    """Mesma lógica que `manager_assistant._is_manager_phone`, mas devolve
    a lista para envio em broadcast aos gestores."""
    phones: List[str] = []
    sched = await db.churn_briefing_schedule.find_one(
        {"company_id": company_id}, {"_id": 0, "notify_phone": 1})
    if sched and sched.get("notify_phone"):
        ph = re.sub(r"\D", "", sched["notify_phone"])
        if ph:
            phones.append(ph)
    async for d in db.manager_assistant_phones.find(
            {"company_id": company_id, "enabled": True},
            {"_id": 0, "phone": 1}):
        ph = re.sub(r"\D", "", d.get("phone") or "")
        if ph and ph not in phones:
            phones.append(ph)
    return phones


async def _send_to_manager(phone: str, text: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                 json={"phone": phone, "text": text})
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            return r.status_code < 400 and bool(data.get("ok"))
    except Exception as e:
        logger.warning("[proactive] WA send falhou: %s", e)
        return False


# ---------------------------------------------------------------------------
# Pending action storage
# ---------------------------------------------------------------------------
async def _save_pending(company_id: str, phone: str, kind: str,
                          payload: Dict[str, Any]) -> str:
    pid = f"pa-{uuid.uuid4().hex[:10]}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat()
    await db.manager_assistant_pending.insert_one({
        "id": pid,
        "company_id": company_id,
        "phone": phone,
        "kind": kind,
        "payload": payload,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "resolved": False,
    })
    return pid


async def get_active_pending(company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Retorna a pending action mais recente ainda válida pra esse telefone."""
    now = datetime.now(timezone.utc).isoformat()
    doc = await db.manager_assistant_pending.find_one(
        {"company_id": company_id, "phone": phone,
         "resolved": False, "expires_at": {"$gt": now}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


async def resolve_pending(pending_id: str, decision: str,
                            executed_summary: Optional[str] = None) -> None:
    await db.manager_assistant_pending.update_one(
        {"id": pending_id},
        {"$set": {
            "resolved": True,
            "decision": decision,
            "executed_summary": executed_summary,
            "resolved_at": now_iso(),
        }},
    )


# ---------------------------------------------------------------------------
# Public API — disparado pelos workers
# ---------------------------------------------------------------------------
# Cache de snippets gerados pelo Claude (por OLT) para evitar custo repetido
_CONTEXT_CACHE: Dict[str, Dict[str, Any]] = {}
_CONTEXT_TTL_SECONDS = 600   # 10min


async def _build_outage_context(company_id: str,
                                    outage: Dict[str, Any]) -> Optional[str]:
    """Resume últimas panes da mesma OLT em até 14 dias.

    Estratégia: agrega dados brutos do Mongo → pede ao Claude para redigir
    um trecho curto em pt-BR (2-3 linhas). Fallback para template fixo se
    Claude falhar ou agente desabilitado.

    Resultado é cacheado em memória por 10min/OLT.
    """
    olt = outage.get("olt_name")
    outage_id = outage.get("id")
    if not olt:
        return None

    # Cache hit?
    cache_key = f"{company_id}:{olt}"
    cached = _CONTEXT_CACHE.get(cache_key)
    if cached and (datetime.now(timezone.utc).timestamp() - cached["ts"]) < _CONTEXT_TTL_SECONDS:
        return cached["text"]

    cutoff_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    cur = db.network_outages.find(
        {"company_id": company_id, "olt_name": olt,
         "id": {"$ne": outage_id},
         "first_detected_at": {"$gte": cutoff_14d}},
        {"_id": 0, "severity_pct": 1, "duration_minutes": 1,
         "ai_insight": 1, "status": 1, "first_detected_at": 1},
    ).sort("first_detected_at", -1).limit(20)
    rows: List[Dict[str, Any]] = []
    async for r in cur:
        rows.append(r)
    if not rows:
        return None

    n = len(rows)
    sev_vals = [float(r.get("severity_pct") or 0) for r in rows]
    sev_avg = round(sum(sev_vals) / len(sev_vals), 1) if sev_vals else 0
    durations = [int(r.get("duration_minutes") or 0)
                   for r in rows if r.get("duration_minutes")]
    avg_dur = int(sum(durations) / len(durations)) if durations else None

    causes: Dict[str, int] = {}
    for r in rows:
        ins = r.get("ai_insight") or {}
        cause = (ins.get("probable_cause") or ins.get("category") or "").strip()
        if cause:
            causes[cause] = causes.get(cause, 0) + 1
    top_cause = max(causes.items(), key=lambda x: x[1]) if causes else None

    # 1) Tenta gerar com Claude
    summary = await _claude_outage_context_summary(
        company_id, olt=olt, n=n, sev_avg=sev_avg, avg_dur=avg_dur,
        top_cause=top_cause)

    # 2) Fallback: template fixo
    if not summary:
        parts = [f"_Esta OLT teve {n} pane(s) em 14 dias_"]
        if avg_dur is not None:
            if avg_dur >= 60:
                parts.append(f"tempo médio de resolução: {avg_dur // 60}h{avg_dur % 60:02d}min")
            else:
                parts.append(f"tempo médio de resolução: {avg_dur}min")
        parts.append(f"severidade média: {sev_avg}%")
        if top_cause and top_cause[1] >= 2:
            parts.append(f"causa recorrente: _{top_cause[0]}_ ({top_cause[1]}x)")
        summary = "\n".join("• " + p for p in parts)

    _CONTEXT_CACHE[cache_key] = {
        "text": summary,
        "ts": datetime.now(timezone.utc).timestamp(),
    }
    return summary


async def _claude_outage_context_summary(
    company_id: str, *, olt: str, n: int, sev_avg: float,
    avg_dur: Optional[int], top_cause: Optional[tuple],
) -> Optional[str]:
    """Pede ao Claude para redigir o snippet em linguagem natural pt-BR.
    Retorna None se falhar (agente desabilitado, timeout, etc).

    Custo aproximado: 60-90 tokens/chamada → ~$0.0003/pane.
    """
    from services.motor_ia import chat_completion, AgentDisabledError
    avg_dur_txt = "não disponível"
    if avg_dur is not None:
        avg_dur_txt = (f"{avg_dur // 60}h{avg_dur % 60:02d}min"
                         if avg_dur >= 60 else f"{avg_dur}min")
    cause_txt = "—"
    if top_cause and top_cause[1] >= 2:
        cause_txt = f"{top_cause[0]} ({top_cause[1]}x)"

    prompt = (
        "Você é o assistente operacional de um provedor de internet. "
        "Redija 2-3 linhas curtas (máx 240 caracteres no total) sobre o histórico "
        "desta OLT, em pt-BR, com tom direto e prático, para o gestor decidir "
        "rápido. Use bullets (• ou -). Não invente dados, use apenas o que está "
        "abaixo. Se algum dado for '—' ou 'não disponível', omita-o.\n\n"
        f"OLT: {olt}\n"
        f"Panes em 14 dias: {n}\n"
        f"Severidade média: {sev_avg}%\n"
        f"Tempo médio de resolução: {avg_dur_txt}\n"
        f"Causa mais recorrente: {cause_txt}\n\n"
        "Responda APENAS com os bullets, sem cabeçalho."
    )
    try:
        result = await chat_completion(
            company_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120, temperature=0.3,
            agent="proactive_outage_context",
        )
        text = (result.get("content") or "").strip()
        # sanity check — só aceita se realmente é curto
        if 20 < len(text) < 600:
            return text
    except AgentDisabledError:
        return None
    except Exception as e:
        logger.warning("[proactive] context summary fail: %s", e)
        return None
    return None


async def notify_outage(company_id: str, outage: Dict[str, Any]) -> Optional[str]:
    """Avisa o gestor sobre nova pane SmartOLT com lista numerada de ações.
    Idempotente: usa `proactive_notified_at` no doc (anti-flood 30min)."""
    cooldown_cut = (datetime.now(timezone.utc)
                      - timedelta(minutes=COOLDOWN_OUTAGE_MINUTES)).isoformat()
    already = await db.network_outages.find_one(
        {"company_id": company_id, "key": outage.get("key"),
         "proactive_notified_at": {"$gt": cooldown_cut}},
        {"_id": 0, "id": 1},
    )
    if already:
        return None

    phones = await _gather_manager_phones(company_id)
    if not phones:
        return None

    affected = len(outage.get("affected_phones") or [])
    olt = outage.get("olt_name") or "—"
    sev = outage.get("severity_pct") or 0
    los = outage.get("los_count") or 0
    total = outage.get("total_count") or 0
    insight = (outage.get("ai_insight") or {}).get("summary") or ""

    # Lista numerada de ações disponíveis
    options = [
        {"n": 1, "action": "broadcast",     "label": f"Avisar os {affected} clientes por WhatsApp"},
        {"n": 2, "action": "lousa_alert",   "label": "Abrir alerta na Lousa (equipe técnica)"},
        {"n": 3, "action": "broadcast_and_lousa", "label": "Fazer ambos (avisar + alerta)"},
        {"n": 4, "action": "ignore",        "label": "Ignorar / já está sendo tratado"},
    ]
    if affected == 0:
        # remove opção que precisa de telefones
        options = [o for o in options if o["action"] not in
                     ("broadcast", "broadcast_and_lousa")]
        for i, o in enumerate(options, 1):
            o["n"] = i

    opts_text = "\n".join(f"*{o['n']}* — {o['label']}" for o in options)
    context_snippet = await _build_outage_context(company_id, outage)
    text = (
        f"🚨 *Pane detectada — {olt}*\n"
        f"_(SmartOLT AI · {sev}% das ONUs offline)_\n\n"
        f"• {los}/{total} ONUs em LOS\n"
        f"• {affected} cliente(s) com telefone cadastrado\n"
        + (f"• Análise IA: {insight}\n" if insight else "")
        + (f"\n📊 *Histórico recente:*\n{context_snippet}\n" if context_snippet else "")
        + "\n*O que devo fazer?*\n"
        + opts_text + "\n\n"
        + "Responda com o *número* da opção (ou _sim_ para a 1, _não_ para a última)."
    )

    delivered = []
    pending_ids = []
    for ph in phones:
        ok = await _send_to_manager(ph, text)
        if not ok:
            continue
        pid = await _save_pending(
            company_id, ph,
            kind="outage_multi",
            payload={
                "outage_id": outage.get("id"),
                "outage_key": outage.get("key"),
                "olt_name": olt,
                "affected_phones": list(outage.get("affected_phones") or [])[:200],
                "options": options,
            },
        )
        pending_ids.append(pid)
        delivered.append(ph)

    if delivered:
        await db.network_outages.update_one(
            {"id": outage.get("id")},
            {"$set": {"proactive_notified_at": now_iso(),
                       "proactive_pending_ids": pending_ids,
                       "proactive_notified_phones": delivered}},
        )
        logger.warning(
            "[proactive] outage %s — gestor(es) notificado(s): %d",
            outage.get("id"), len(delivered))
        return delivered[0]
    return None


# ---------------------------------------------------------------------------
# Execução de pending (chamado pelo manager_assistant ao receber sim/não)
# ---------------------------------------------------------------------------
async def execute_pending(company_id: str, pending: Dict[str, Any],
                            decision_text: str) -> str:
    """Executa a ação pendente. Aceita formatos:
      - Número da opção (1, 2, 3...)
      - "sim" → primeira opção (broadcast)
      - "não/cancela/ignora" → última opção (ignore)
      - Texto livre ambíguo → mantém pending, pede clarificação"""
    s = (decision_text or "").strip().lower()
    payload = pending.get("payload") or {}
    kind = pending.get("kind") or ""
    options = payload.get("options") or []

    # 1) Match por número explícito
    chosen = None
    m = re.match(r"^\s*([0-9]+)\b", s)
    if m and options:
        try:
            n = int(m.group(1))
            chosen = next((o for o in options if o.get("n") == n), None)
        except Exception:
            chosen = None

    # 2) Atalhos sim/não
    if not chosen and options:
        if re.search(r"\b(sim|yes|ok|confirma|envia|manda|aprovo|pode|vai)\b", s):
            chosen = options[0]
        elif re.search(r"\b(n[ãa]o|nao|cancela|ignora|deixa|abort|nada)", s):
            chosen = options[-1]

    if not chosen:
        # backward-compat: pending antigo sem `options`
        if not options:
            yes = re.search(r"\b(sim|yes|ok|confirma|aprovo)\b", s)
            no = re.search(r"\b(n[ãa]o|nao|cancela|ignora)", s)
            if no and not yes:
                await resolve_pending(pending["id"], decision="rejected")
                return "👍 Ok, ignorando esse alerta."
            if yes and kind == "outage_broadcast":
                sent = await _execute_outage_broadcast(company_id, payload)
                await resolve_pending(pending["id"], decision="approved",
                                          executed_summary=f"broadcast={sent}")
                return f"✅ Aviso enviado para {sent} cliente(s)."
        # Ambíguo
        if options:
            opts_text = " · ".join(f"{o['n']}={o['label'][:20]}" for o in options)
            return (f"Não entendi. Responda com o número da opção: {opts_text}. "
                      "Expira em 30 min.")
        return ("Para confirmar, responda *sim* ou *não*. Expira em 30 min.")

    # 3) Execute action
    action = chosen.get("action")
    if action == "ignore":
        await resolve_pending(pending["id"], decision="rejected",
                                executed_summary="ignored")
        return "👍 Ok, marcado como visualizado."
    if action == "broadcast":
        sent = await _execute_outage_broadcast(company_id, payload)
        await resolve_pending(pending["id"], decision="approved",
                                executed_summary=f"broadcast={sent}")
        return f"✅ Aviso enviado para {sent} cliente(s)."
    if action == "lousa_alert":
        n = await _execute_outage_lousa_alert(company_id, payload)
        await resolve_pending(pending["id"], decision="approved",
                                executed_summary=f"lousa_alerts={n}")
        return (f"✅ Alerta aberto na Lousa AI ({n} ticket(s) afetado(s)). "
                  "A equipe técnica já pode atuar.")
    if action == "broadcast_and_lousa":
        sent = await _execute_outage_broadcast(company_id, payload)
        n = await _execute_outage_lousa_alert(company_id, payload)
        await resolve_pending(pending["id"], decision="approved",
                                executed_summary=f"broadcast={sent}, lousa={n}")
        return (f"✅ {sent} cliente(s) avisado(s) + alerta na Lousa "
                  f"({n} ticket(s)). Tudo encaminhado.")
    await resolve_pending(pending["id"], decision="approved")
    return "✅ Confirmado."


async def _execute_outage_lousa_alert(company_id: str,
                                          payload: Dict[str, Any]) -> int:
    """Cria 1 alerta tipo `outage_team` na Lousa AI pra cada cliente afetado.
    Idempotente: usa upsert por (outage_id, phone)."""
    phones = payload.get("affected_phones") or []
    olt = payload.get("olt_name") or "—"
    outage_id = payload.get("outage_id")
    created = 0
    for ph in phones[:100]:
        res = await db.lousa_alerts.update_one(
            {"company_id": company_id, "kind": "outage_team",
             "outage_id": outage_id, "phone": ph},
            {"$set": {
                "headline": f"Pane {olt} — verificar cliente {ph}",
                "severity": "alta",
                "status": "active",
                "last_seen_at": now_iso(),
            },
             "$setOnInsert": {
                "id": f"alr-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "kind": "outage_team",
                "outage_id": outage_id,
                "phone": ph,
                "first_detected_at": now_iso(),
                "created_by": "proactive_alerts",
             }},
            upsert=True,
        )
        if res.upserted_id:
            created += 1
    logger.warning(
        "[proactive] lousa alerts criados: %d (OLT %s, %d phones)",
        created, olt, len(phones))
    return created


async def _execute_outage_broadcast(company_id: str,
                                       payload: Dict[str, Any]) -> int:
    """Envia mensagem padrão pra todos os telefones afetados pelo outage."""
    phones = payload.get("affected_phones") or []
    olt = payload.get("olt_name") or "região"
    if not phones:
        return 0
    text = (
        f"⚠️ Olá! Identificamos uma instabilidade na sua região ({olt}) e "
        f"nossa equipe técnica já está atuando para restabelecer o serviço "
        f"o mais rápido possível.\n\nAgradecemos a paciência e pedimos "
        f"desculpas pelo transtorno."
    )
    sent = 0
    # Envia em lote — sidecar tem rate limit interno (1.2s entre envios)
    for ph in phones:
        try:
            async with httpx.AsyncClient(timeout=8.0) as cli:
                r = await cli.post(f"{SIDECAR_BASE}/send",
                                     json={"phone": ph, "text": text})
                if r.status_code < 400:
                    sent += 1
        except Exception:
            pass
    logger.warning(
        "[proactive] outage broadcast enviado: %d/%d clientes — OLT %s",
        sent, len(phones), olt)
    return sent
