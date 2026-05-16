"""DISPARO IA — Orquestrador estratégico de comunicação ativa.

Posicionamento:
  • Alvaro IA (analista)   → identifica QUEM contactar e QUANDO
  • Disparo IA (estrategista — ESTE módulo) → define O QUE oferecer,
    monta campanhas (público + mensagem + cadência + KPIs) e briefa Isabella
  • Isabella IA (executora) → dispara via WhatsApp e qualifica os leads

Modelo: claude-sonnet-4.5 via Motor IA (raciocínio estratégico complexo).

Fluxo:
  1. `generate_campaign_suggestions(cid)`
       • Lê o último relatório do Alvaro (24h) + base de assinantes
       • Pede ao Claude 6 sugestões (1 por tipo de campanha)
       • Persiste em `disparo_suggestions` com status="pending"
  2. Gestor aprova via endpoint → cria mass_messaging campaign com origin="disparo_ia"
  3. KPIs reais agregados de `mass_campaigns` + `mass_recipients` +
     `aihub_wa_messages` (replies pós-disparo)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.motor_ia import chat_completion

logger = logging.getLogger("disparo_ai")

DISPARO_MODEL = "anthropic/claude-sonnet-4.5"

# Tipos suportados (gestor pode subselecionar via params)
CAMPAIGN_TYPES = [
    {"id": "churn_recovery",
     "label": "Recuperação de churn iminente",
     "goal": "Salvar assinantes com risco alto/crítico antes que cancelem"},
    {"id": "plan_upsell",
     "label": "Upsell de plano",
     "goal": "Oferecer planos superiores a clientes com uso intenso/consistente"},
    {"id": "friendly_billing",
     "label": "Cobrança amigável",
     "goal": "Lembrete não-invasivo de fatura vencida ou próxima"},
    {"id": "nps_csat",
     "label": "Pesquisa NPS / CSAT",
     "goal": "Coletar satisfação de quem teve atendimento recente"},
    {"id": "coverage_expansion",
     "label": "Expansão de bairros",
     "goal": "Captar leads em bairros sem cobertura onde houve demanda"},
    {"id": "reactivation",
     "label": "Reativação de cancelados",
     "goal": "Tentar trazer de volta ex-clientes (oferta exclusiva)"},
]
CAMPAIGN_TYPE_IDS = {t["id"] for t in CAMPAIGN_TYPES}


DISPARO_SYSTEM_PROMPT = """Você é o DISPARO_IA, inteligência artificial estrategista de COMUNICAÇÃO ATIVA de um provedor de internet (ISP).

Sua missão: ORQUESTRAR campanhas WhatsApp combinando os insights do Alvaro_IA (analista de conversas) e a execução da Isabella_IA (atendente WhatsApp). Você não envia mensagens — você decide O QUE, PARA QUEM, QUANDO e COMO.

PRINCÍPIOS (best-practices outbound 2026 — Outreach, Apollo, Zenvia, AISensy):
1. **Relevância > volume**. Cada mensagem deve ter UM motivo claro e UM CTA.
2. **Timing comportamental**: priorize momentos de alta suscetibilidade (após fatura, perto de fim de contrato, após reclamação resolvida, uso próximo do limite, fim de tarde).
3. **Personalização leve**: use {{nome}}, {{plano}}, {{bairro}}, {{valor_fatura}} — nunca dados sensíveis.
4. **CTA único e mensurável**: "Quero saber mais", "Vou pagar agora", "Não tenho interesse".
5. **Cadência humana**: 1ª mensagem 30-60s, follow-up só após 24h e se não respondeu.
6. **Compliance**: respeite opt-out, não dispare entre 22h-8h, frequência máx 2 contatos/semana por cliente.
7. **Brief para Isabella**: dê instruções claras sobre tom, objeções esperadas e quando escalar pra humano.

KPIs ALVO (defina para cada campanha):
- delivery_rate ≥ 95%
- read_rate ≥ 70%
- reply_rate ≥ 15% (cold) ou ≥ 35% (warm — quem já tem relação)
- positive_reply_rate ≥ 8%
- conversion_rate variável conforme tipo (churn=15-30% save / upsell=3-10% / cobrança=40-60% paid / nps=20-40% respondida)
- block_rate < 1%
- ARPU uplift mensurável quando aplicável

CATEGORIAS DE CAMPANHA (use o `type` exato):
- `churn_recovery`: risco_cancelamento=alto/crítico recentes (≤7d)
- `plan_upsell`: plano básico + sem reclamação + base há ≥3 meses
- `friendly_billing`: fatura vencida 1-15 dias, sem ameaça de cancel
- `nps_csat`: atendimento resolvido nas últimas 48h
- `coverage_expansion`: bairros marcados não_atendido pelo Alvaro com ≥2 ocorrências
- `reactivation`: status=cancelado há 30-180 dias

RESPOSTA SEMPRE EM JSON VÁLIDO no schema solicitado. Nunca invente dados. Se não houver oportunidade real para algum tipo, omita-o.
"""


def _safe_json_extract(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.M)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.M)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        logger.warning("[disparo] JSON parse fail: %s — raw[:200]=%s", e, raw[:200])
        return {}


async def _gather_context(cid: str) -> Dict[str, Any]:
    """Coleta os fatos relevantes da empresa para alimentar o Claude.

    Estritamente factual (sem LLM aqui) — números do CRM e do Alvaro.
    """
    # 1) Último relatório do Alvaro
    alvaro = await db.alvaro_reports.find_one(
        {"company_id": cid}, {"_id": 0}, sort=[("finished_at", -1)],
    )
    alvaro_report = (alvaro or {}).get("report") or {}
    alvaro_run_id = (alvaro or {}).get("run_id")

    # 2) Distribuição da base de assinantes (top planos, churn recente)
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$plan_name", "qtd": {"$sum": 1}}},
        {"$sort": {"qtd": -1}}, {"$limit": 10},
    ]
    plans_dist = [d async for d in db.subscribers.aggregate(pipeline)]

    status_pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "qtd": {"$sum": 1}}},
    ]
    status_dist = [d async for d in db.subscribers.aggregate(status_pipeline)]

    # 3) Análises Alvaro recentes (com risco/oportunidade)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_analyses_cur = db.alvaro_analyses.find(
        {"company_id": cid, "analyzed_at": {"$gte": cutoff}},
        {"_id": 0, "phone": 1, "result.analise.risco_cancelamento": 1,
         "result.analise.tipo_reclamacao": 1, "result.cliente.nome": 1,
         "result.oportunidades": 1, "result.localizacao.bairro": 1},
    ).sort("analyzed_at", -1).limit(100)
    recent_analyses = [d async for d in recent_analyses_cur]

    # 4) Campanhas Disparo IA recentes (pra evitar repetir tipo na mesma semana)
    recent_campaigns_cur = db.disparo_suggestions.find(
        {"company_id": cid,
         "created_at": {"$gte": (datetime.now(timezone.utc)
                                  - timedelta(days=7)).isoformat()}},
        {"_id": 0, "type": 1, "status": 1},
    )
    recent_types = Counter()
    async for d in recent_campaigns_cur:
        recent_types[d.get("type")] += 1

    return {
        "alvaro_run_id": alvaro_run_id,
        "alvaro_report": alvaro_report,
        "plans_distribution": plans_dist,
        "status_distribution": status_dist,
        "recent_alvaro_analyses_count": len(recent_analyses),
        "high_risk_signals": [a for a in recent_analyses
                                 if (a.get("result", {}).get("analise", {})
                                     .get("risco_cancelamento", "").lower()
                                     in ("alto", "crítico", "critico"))][:15],
        "coverage_gaps": alvaro_report.get("bairros_nao_atendidos") or [],
        "recent_disparo_types": dict(recent_types),
    }


async def generate_campaign_suggestions(
    cid: str,
    types_filter: Optional[List[str]] = None,
    max_suggestions: int = 6,
) -> Dict[str, Any]:
    """Pipeline principal: lê contexto, chama Claude, persiste sugestões.

    Args:
        types_filter: se passar [type_ids], só pede esses tipos ao Claude.
                      Default = todos os 6.
        max_suggestions: cap de sugestões (default 6 = 1 por tipo).

    Returns:
        {run_id, suggestions_created: int, suggestions: [...]}
    """
    types_filter = types_filter or list(CAMPAIGN_TYPE_IDS)
    allowed_types = [t for t in CAMPAIGN_TYPES if t["id"] in types_filter]
    if not allowed_types:
        raise ValueError("Nenhum tipo de campanha válido informado.")

    ctx = await _gather_context(cid)

    run_id = f"disp-run-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat()

    user_prompt = (
        "Com base nos DADOS DA EMPRESA abaixo, gere até "
        f"{max_suggestions} SUGESTÕES de campanhas WhatsApp ATIVAS.\n\n"
        "TIPOS PERMITIDOS (use exatamente o `id` como `type`):\n"
        + json.dumps(allowed_types, ensure_ascii=False, indent=2)
        + "\n\nDADOS DA EMPRESA (factual — Alvaro + CRM):\n"
        + json.dumps(ctx, ensure_ascii=False, default=str)[:6000]
        + "\n\nRESPONDA APENAS no schema abaixo. Se algum tipo não tem oportunidade real, omita-o (não force):\n"
        + """
{
  "suggestions": [
    {
      "type": "churn_recovery",
      "title": "Resgate 8 clientes risco crítico do Plano 300MB · 7d",
      "rationale": "Por que esta campanha agora (use os dados do Alvaro)",
      "audience": {
        "description": "Texto curto explicando quem entra (legível pro gestor)",
        "filters": {
          "risco_cancelamento": ["alto", "critico"],
          "since_days": 7,
          "plan_contains": null,
          "bairro_in": null,
          "status": null
        },
        "estimated_size": 8
      },
      "message_template": "Oi {{nome}}! 👋 Aqui é a Isabella, da Ligo Fibra. Vi que você teve um problema recente e queria saber se já está resolvido — posso te ajudar com algo agora?",
      "isabella_briefing": "Tom acolhedor, NÃO mencione cancelamento. Se cliente reclamar, ouça primeiro, depois ofereça: (1) check sinal SmartOLT, (2) abrir chamado prioritário, (3) escalar pra retenção. Bandeiras vermelhas para escalar humano: 'cancela', 'procon', 'já decidi'.",
      "expected_kpis": {
        "reply_rate_min": 0.30,
        "positive_reply_rate_min": 0.15,
        "save_rate_min": 0.20,
        "block_rate_max": 0.02
      },
      "target_send_window": {
        "weekday_hours_start": 9,
        "weekday_hours_end": 19,
        "rationale": "Horário comercial — cliente está descansado e com tempo"
      },
      "cadence": {
        "first_touch_min": 0,
        "followup_after_hours": 48,
        "max_followups": 1
      },
      "priority": "alta"
    }
  ]
}
"""
    )

    try:
        r = await chat_completion(
            company_id=cid,
            messages=[
                {"role": "system", "content": DISPARO_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=DISPARO_MODEL,
            temperature=0.4,
            max_tokens=3500,
            json_mode=True,
            purpose="general",
            agent="disparo_ia",
        )
    except Exception as e:
        logger.exception("[disparo] LLM call failed: %s", e)
        raise

    parsed = _safe_json_extract(r.get("content", ""))
    suggestions_raw = parsed.get("suggestions") or []
    if not isinstance(suggestions_raw, list):
        suggestions_raw = []

    created: List[Dict[str, Any]] = []
    for s in suggestions_raw[:max_suggestions]:
        if not isinstance(s, dict):
            continue
        type_id = s.get("type")
        if type_id not in CAMPAIGN_TYPE_IDS:
            continue
        # Resolve audiência real (estima quantos cabem nos filtros)
        audience_preview = await _resolve_audience(cid, s.get("audience") or {})
        doc = {
            "id": f"disp-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "run_id": run_id,
            "type": type_id,
            "title": s.get("title") or type_id,
            "rationale": s.get("rationale") or "",
            "audience": s.get("audience") or {},
            "audience_preview": audience_preview,
            "message_template": s.get("message_template") or "",
            "isabella_briefing": s.get("isabella_briefing") or "",
            "expected_kpis": s.get("expected_kpis") or {},
            "target_send_window": s.get("target_send_window") or {},
            "cadence": s.get("cadence") or {},
            "priority": s.get("priority") or "media",
            "alvaro_run_id": ctx.get("alvaro_run_id"),
            "status": "pending",
            "created_at": started_at,
            "approved_at": None,
            "approved_by": None,
            "campaign_id": None,
        }
        await db.disparo_suggestions.insert_one(doc)
        # Remove _id se MongoDB tiver injetado (não devemos ter aqui mas é defensivo)
        doc.pop("_id", None)
        created.append(doc)

    logger.info("[disparo] run=%s gerou %d sugestões (tipos=%s)",
                  run_id, len(created), types_filter)

    return {
        "run_id": run_id,
        "started_at": started_at,
        "model": r.get("model"),
        "provider": r.get("provider"),
        "suggestions_created": len(created),
        "suggestions": created,
        "alvaro_run_id": ctx.get("alvaro_run_id"),
    }


async def _resolve_audience(cid: str,
                              audience: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve filtros de audiência em quantidade real + preview de até 5 phones.

    Filtros aceitos (qualquer combinação):
      - risco_cancelamento: list[str]   (de alvaro_analyses)
      - since_days: int                  (janela das análises Alvaro)
      - plan_contains: str|None          (substring case-insensitive)
      - bairro_in: list[str]|None
      - status: str|None                  (status do subscriber)
    """
    if not isinstance(audience, dict):
        return {"size": 0, "preview": []}
    filters = audience.get("filters") or {}

    # Caminho 1: filtros baseados em Alvaro → buscamos phones via análises
    phones: Optional[set] = None
    riscos = filters.get("risco_cancelamento") or []
    since_days = filters.get("since_days") or 0
    if riscos or since_days:
        riscos_lower = [r.lower().replace("í", "i").replace("ç", "c")
                          for r in riscos]
        q: Dict[str, Any] = {"company_id": cid}
        if since_days:
            q["analyzed_at"] = {"$gte": (datetime.now(timezone.utc)
                                          - timedelta(days=since_days)).isoformat()}
        cur = db.alvaro_analyses.find(q, {
            "_id": 0, "phone": 1, "result.analise.risco_cancelamento": 1,
        })
        phones = set()
        async for d in cur:
            risk = (d.get("result", {}).get("analise", {})
                     .get("risco_cancelamento", "")
                     .lower().replace("í", "i").replace("ç", "c"))
            if not riscos_lower or risk in riscos_lower:
                phones.add(d.get("phone"))

    # Caminho 2: filtros estruturais via subscribers
    sub_q: Dict[str, Any] = {"company_id": cid}
    plan = filters.get("plan_contains")
    if plan:
        sub_q["plan_name"] = {"$regex": re.escape(plan), "$options": "i"}
    bairros = filters.get("bairro_in") or []
    if bairros:
        sub_q["$or"] = [
            {"address": {"$regex": re.escape(b), "$options": "i"}}
            for b in bairros
        ]
    status = filters.get("status")
    if status:
        sub_q["status"] = status

    sub_cur = db.subscribers.find(sub_q, {
        "_id": 0, "phone": 1, "name": 1, "plan_name": 1, "address": 1,
        "external_code": 1,
    }).limit(5000)
    subs_list = [d async for d in sub_cur]

    # Interseca quando aplicável
    if phones is not None:
        final = [s for s in subs_list if s.get("phone") in phones]
        # Se não havia subscribers que casassem com os filtros, mas temos phones
        # vindos só do Alvaro → ainda retorna esses phones como audiência crua.
        if not final and not (plan or bairros or status):
            return {
                "size": len(phones),
                "preview": [{"phone": p} for p in list(phones)[:5]],
                "source": "alvaro_only",
            }
    else:
        final = subs_list

    return {
        "size": len(final),
        "preview": final[:5],
        "source": "crm" if phones is None else "crm+alvaro",
    }


# ---------------------------------------------------------------------------
# KPIs — agrega métricas reais das campanhas Disparo IA executadas
# ---------------------------------------------------------------------------

POSITIVE_RE = re.compile(
    r"\b(sim|quero|aceito|fechado|ok\b|claro|com certeza|interesse|"
    r"manda|me liga|pode mandar|vamos|topo|topei|gostei)\b", re.IGNORECASE
)
NEGATIVE_RE = re.compile(
    r"\b(nao|não|sem interesse|para de|me tira|opt[- ]?out|"
    r"nao quero|nao tenho interesse|silencio|chega|stop|bloquear)\b",
    re.IGNORECASE,
)


async def compute_kpis(cid: str, days: int = 30) -> Dict[str, Any]:
    """KPIs agregados das campanhas Disparo IA dos últimos N dias.

    Combina:
      - mass_recipients (delivery / read / failed) — quando o canal expõe
      - aihub_wa_messages inbound (reply do cliente) dentro da janela pós-disparo
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()

    camps_cur = db.mass_campaigns.find(
        {"company_id": cid, "origin": "disparo_ia",
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "name": 1, "channel": 1, "status": 1,
         "total_recipients": 1, "sent": 1, "delivered": 1, "failed": 1,
         "disparo_type": 1, "disparo_suggestion_id": 1, "created_at": 1,
         "finished_at": 1},
    ).sort("created_at", -1)
    camps = [c async for c in camps_cur]

    total_sent = sum(c.get("sent", 0) for c in camps)
    total_delivered = sum(c.get("delivered", 0) for c in camps)
    total_failed = sum(c.get("failed", 0) for c in camps)
    total_recipients = sum(c.get("total_recipients", 0) for c in camps)

    # Reply classification — pega inbound msgs após o disparo
    # Pra cada campanha, contamos phones que responderam em até 7 dias
    reply_counts = {"replied": 0, "positive": 0, "negative": 0, "neutral": 0}
    save_signals = 0
    upsell_signals = 0
    blocked = 0
    per_type: Dict[str, Dict[str, int]] = {}

    for c in camps:
        c_type = c.get("disparo_type") or "outro"
        per_type.setdefault(c_type, {
            "sent": 0, "delivered": 0, "replied": 0, "positive": 0,
            "campaigns": 0,
        })
        per_type[c_type]["campaigns"] += 1
        per_type[c_type]["sent"] += c.get("sent", 0)
        per_type[c_type]["delivered"] += c.get("delivered", 0)

        # Phones desta campanha
        rec_cur = db.mass_recipients.find(
            {"campaign_id": c["id"], "company_id": cid,
             "status": {"$in": ["sent", "delivered"]}},
            {"_id": 0, "phone": 1, "sent_at": 1},
        )
        recipients = [r async for r in rec_cur]
        if not recipients:
            continue
        phones_camp = {r["phone"]: r.get("sent_at") for r in recipients}
        camp_sent_at = c.get("created_at")
        window_end = (datetime.fromisoformat(camp_sent_at.replace("Z", "+00:00"))
                       + timedelta(days=7)).isoformat() \
            if camp_sent_at else (datetime.now(timezone.utc).isoformat())

        replies_cur = db.aihub_wa_messages.find(
            {"company_id": cid, "direction": "inbound",
             "phone": {"$in": list(phones_camp.keys())},
             "created_at": {"$gte": camp_sent_at, "$lte": window_end}},
            {"_id": 0, "phone": 1, "text": 1},
        )
        seen_phones = set()
        async for m in replies_cur:
            p = m.get("phone")
            if p in seen_phones:
                continue
            seen_phones.add(p)
            reply_counts["replied"] += 1
            per_type[c_type]["replied"] += 1
            txt = (m.get("text") or "").strip()
            if POSITIVE_RE.search(txt):
                reply_counts["positive"] += 1
                per_type[c_type]["positive"] += 1
                if c_type == "churn_recovery":
                    save_signals += 1
                elif c_type == "plan_upsell":
                    upsell_signals += 1
            elif NEGATIVE_RE.search(txt):
                reply_counts["negative"] += 1
                blocked += 1 if "opt" in txt.lower() or "stop" in txt.lower() else 0
            else:
                reply_counts["neutral"] += 1

    def _rate(num: int, den: int) -> float:
        return round(num / den, 4) if den > 0 else 0.0

    return {
        "period_days": days,
        "campaigns_count": len(camps),
        "sent": total_sent,
        "delivered": total_delivered,
        "failed": total_failed,
        "recipients_total": total_recipients,
        "delivery_rate": _rate(total_delivered, total_sent),
        "read_rate": _rate(total_delivered, total_sent),  # proxy
        "reply_rate": _rate(reply_counts["replied"], total_sent),
        "positive_reply_rate": _rate(reply_counts["positive"], total_sent),
        "block_rate": _rate(blocked, total_sent),
        "save_signals": save_signals,
        "upsell_signals": upsell_signals,
        "replies": reply_counts,
        "per_type": per_type,
        "campaigns": camps[:50],
    }
