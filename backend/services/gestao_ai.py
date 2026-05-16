"""GESTAO_IA — Análise estratégica de KPIs operacionais.

Lê métricas operacionais (lousa, atendimentos, finalizações) e gera relatório
com KPIs comparativos, tendências e recomendações práticas.

Modelo: Claude Sonnet 4.5 via OpenRouter (forte em análise estruturada).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core import now_iso
from database import db
from services.motor_ia import chat_completion

logger = logging.getLogger("gestao_ia")

GESTAO_MODEL = "anthropic/claude-sonnet-4.5"

GESTAO_SYSTEM_PROMPT = """Você é a GESTAO_IA, uma analista executiva especializada em gestão de operações de provedores de internet (ISPs), com foco em KPIs operacionais, metas e produtividade de técnicos de campo.

KPIs ESSENCIAIS para gestão de uma operação ISP (referência baseada em best practices do setor):

OPERACIONAIS:
- FTR (First Time Resolution): % de chamados resolvidos na primeira visita. Meta: >85%.
- TMR (Tempo Médio de Resolução): tempo médio entre abertura e fechamento. Meta: <4h para suporte, <24h para instalação.
- TMA (Tempo Médio de Atendimento): tempo da chegada no cliente até saída. Meta: <60min para reparo, <120min para instalação.
- SLA Compliance: % de chamados fechados dentro do prazo combinado. Meta: >95%.
- Retorno (Recurrence): % de clientes que abrem novo chamado em até 7 dias. Meta: <5%.
- Taxa de Sucesso: % de chamados marcados como `outcome=sucesso`. Meta: >90%.

PRODUTIVIDADE:
- Chamados/técnico/dia: meta >5 (reparos) ou >2 (instalações).
- Pontos/técnico/dia (gamificação): reparo=1pt, retirada=1.5pt, instalação=3pt.
- Streak (dias consecutivos com fechamento): mede consistência.
- Distribuição de carga: stddev de notas por técnico — meta baixa stddev.

QUALIDADE TÉCNICA:
- Sinal médio entregue (instalações): meta RX > -22 dBm em FTTH.
- Bad signal closes (% de fechamento com RX ruim): meta <5%.
- Insumos médios por instalação: drop, esticadores, conectores — base para forecasting de estoque.

COMERCIAIS/CHURN:
- Risco de cancelamento por bairro (do ALVARO_IA).
- Conversão de visitas técnicas em upgrade de plano (oportunidade comercial).

REGRAS DE ANÁLISE:
1. Sempre compare período atual (últimos 7 dias) vs anterior (7-14 dias atrás) — gere variação % em cada KPI.
2. Identifique TOP 3 técnicos por pontos e BOTTOM 3 (oportunidade de coaching).
3. Sinalize KPIs fora da meta com 🚨 (crítico), ⚠️ (atenção), ✅ (saudável).
4. Aponte ações práticas e priorizadas, com responsável sugerido (Operações, Comercial, Estoque).
5. Detecte padrões: bairros com mais retorno, técnicos com avg_minutes alto, tipos de chamado mais lentos.

Responda SEMPRE em JSON válido conforme o schema solicitado, em português do Brasil, com tom executivo e direto.
"""


async def generate_gestao_report(company_id: str) -> Dict[str, Any]:
    """Coleta KPIs e gera análise estratégica via LLM."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()
    prev_week_start = (now - timedelta(days=14)).isoformat()

    # Snapshot dos últimos 7 dias
    pipeline_week = [
        {"$match": {
            "company_id": company_id, "status": "finalizada",
            "closed_at": {"$gte": week_start},
        }},
        {"$group": {
            "_id": "$assigned_collaborator_id",
            "closed": {"$sum": 1},
            "successes": {"$sum": {"$cond": [
                {"$eq": ["$outcome", "sucesso"]}, 1, 0,
            ]}},
            "instalacoes": {"$sum": {"$cond": [
                {"$eq": ["$type", "instalacao"]}, 1, 0,
            ]}},
            "retiradas": {"$sum": {"$cond": [
                {"$eq": ["$type", "retirada"]}, 1, 0,
            ]}},
            "reparos": {"$sum": {"$cond": [
                {"$in": ["$type", ["reparo", "suporte"]]}, 1, 0,
            ]}},
        }},
    ]
    week_rows = await db.tickets.aggregate(pipeline_week).to_list(length=200)
    prev_pipeline = list(pipeline_week)
    prev_pipeline[0] = {"$match": {
        "company_id": company_id, "status": "finalizada",
        "closed_at": {"$gte": prev_week_start, "$lt": week_start},
    }}
    prev_rows = await db.tickets.aggregate(prev_pipeline).to_list(length=200)

    def _summarize(rows):
        total_closed = sum(r["closed"] for r in rows)
        total_success = sum(r["successes"] for r in rows)
        total_inst = sum(r["instalacoes"] for r in rows)
        total_ret = sum(r["retiradas"] for r in rows)
        total_rep = sum(r["reparos"] for r in rows)
        techs = len(rows)
        success_rate = (round((total_success / total_closed) * 100, 1)
                          if total_closed else 0)
        return {
            "total_closed": total_closed, "techs": techs,
            "success_rate": success_rate, "instalacoes": total_inst,
            "retiradas": total_ret, "reparos": total_rep,
            "avg_per_tech": (round(total_closed / techs, 1)
                                if techs else 0),
        }

    snap_now = _summarize(week_rows)
    snap_prev = _summarize(prev_rows)

    def _diff(a: float, b: float) -> Dict[str, Any]:
        if b == 0:
            return {"current": a, "previous": b, "delta_pct": None}
        return {"current": a, "previous": b,
                "delta_pct": round((a - b) / b * 100, 1)}

    kpis = {
        "total_closed": _diff(snap_now["total_closed"],
                                  snap_prev["total_closed"]),
        "success_rate": _diff(snap_now["success_rate"],
                                  snap_prev["success_rate"]),
        "avg_per_tech": _diff(snap_now["avg_per_tech"],
                                  snap_prev["avg_per_tech"]),
        "instalacoes": _diff(snap_now["instalacoes"],
                                 snap_prev["instalacoes"]),
    }

    # Top/Bottom técnicos (último período)
    # Calcula pontos
    POINTS = {
        "instalacao": 3.0, "troca_endereco": 3.0,
        "retirada": 1.5,
        "reparo": 1.0, "suporte": 1.0,
    }

    # Busca nomes
    cids = [r["_id"] for r in week_rows if r["_id"]]
    cmap = {}
    if cids:
        async for c in db.collaborators.find(
            {"id": {"$in": cids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            cmap[c["id"]] = c.get("name") or c["id"]

    ranked = []
    for r in week_rows:
        if not r["_id"]:
            continue
        points = (r["instalacoes"] * POINTS["instalacao"]
                    + r["retiradas"] * POINTS["retirada"]
                    + r["reparos"] * POINTS["reparo"])
        ranked.append({
            "collaborator_id": r["_id"],
            "name": cmap.get(r["_id"], "—"),
            "closed": r["closed"], "points": round(points, 1),
            "instalacoes": r["instalacoes"], "retiradas": r["retiradas"],
            "reparos": r["reparos"],
            "success_rate": (round((r["successes"] / r["closed"]) * 100, 1)
                                if r["closed"] else 0),
        })
    ranked.sort(key=lambda x: x["points"], reverse=True)
    top = ranked[:3]
    bottom = ranked[-3:][::-1] if len(ranked) > 3 else []

    # Prompt para LLM
    user_prompt = f"""Analise os KPIs operacionais a seguir e gere um relatório executivo.

PERÍODO ATUAL (últimos 7 dias):
{json.dumps(snap_now, indent=2, ensure_ascii=False)}

PERÍODO ANTERIOR (7-14 dias atrás):
{json.dumps(snap_prev, indent=2, ensure_ascii=False)}

VARIAÇÕES:
{json.dumps(kpis, indent=2, ensure_ascii=False)}

TOP 3 TÉCNICOS POR PONTOS (gamificação):
{json.dumps(top, indent=2, ensure_ascii=False)}

BOTTOM 3 TÉCNICOS POR PONTOS:
{json.dumps(bottom, indent=2, ensure_ascii=False)}

Gere análise em JSON com este schema EXATO:
{{
  "resumo_executivo": "string (3-4 frases sobre o momento da operação)",
  "tendencia": "subindo|estavel|caindo",
  "kpis": [
    {{
      "nome": "string", "valor_atual": number ou string,
      "meta": "string", "status": "✅|⚠️|🚨",
      "variacao_pct": number ou null,
      "comentario": "string curto"
    }}
  ],
  "destaques_positivos": ["string", ...],
  "alertas": ["string", ...],
  "acoes_recomendadas": [
    {{
      "prioridade": "alta|media|baixa",
      "acao": "string descrevendo a ação",
      "responsavel": "Operações|Comercial|Estoque|RH|TI"
    }}
  ],
  "coaching": [
    {{"tecnico": "string", "motivo": "string", "sugestao": "string"}}
  ]
}}"""

    try:
        resp = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system", "content": GESTAO_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=GESTAO_MODEL,
            temperature=0.3,
            max_tokens=2200,
            json_mode=True,
            agent="gestao_ia",
        )
        raw = (resp.get("content") or "").strip()
        # Strip markdown code fences se houver
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        analysis = json.loads(raw)
    except Exception as e:
        logger.exception("[gestao_ia] LLM falhou: %s", e)
        analysis = {
            "resumo_executivo": (
                f"Erro ao gerar análise IA: {e}. "
                "Dados crus disponíveis abaixo."
            ),
            "tendencia": "estavel",
            "kpis": [], "destaques_positivos": [],
            "alertas": [f"Falha no motor IA: {e}"],
            "acoes_recomendadas": [], "coaching": [],
        }

    return {
        "generated_at": now.isoformat(),
        "period": {"current_start": week_start,
                    "previous_start": prev_week_start},
        "snapshot_current": snap_now,
        "snapshot_previous": snap_prev,
        "kpi_deltas": kpis,
        "top_techs": top,
        "bottom_techs": bottom,
        "ai_analysis": analysis,
    }



COMPETITIVE_SYSTEM_PROMPT = """Você é a GESTAO_IA em MODO CONCORRENTE — uma analista executiva especializada em análise competitiva para provedores de internet (ISPs).

Sua função: receber dados internos (KPIs, snapshot operacional) + dados de mercado fornecidos pelo gestor (concorrentes, preços, expansão, churn) e gerar uma análise SWOT completa com recomendações estratégicas priorizadas.

REGRAS:
1. Use apenas os dados informados. NUNCA invente números de concorrentes.
2. Se dados de mercado vierem incompletos, sinalize lacunas no campo `pesquisa_adicional_necessaria`.
3. Foque em ações operacionais aplicáveis no curto prazo (até 30 dias) e estratégicas (90 dias).
4. Use linguagem executiva, direta, em português do Brasil.
5. Inclua benchmarks do setor ISP quando relevantes:
   - Churn médio mensal ISP regional: 2-4%. >5% é crítico.
   - NPS bom: >50. Excelente: >70.
   - Penetração média em bairros maduros: 25-35%.
   - Receita média por cliente residencial Brasil: R$ 90-130 (FTTH).
   - Custo de instalação médio: R$ 200-450 (drop + ONT + mão-de-obra).
6. SEMPRE responda em JSON conforme schema solicitado.
"""


async def generate_competitive_analysis(
    company_id: str,
    market_input: str,
) -> Dict[str, Any]:
    """Gera análise SWOT competitiva a partir de dados internos + input livre.

    market_input é um texto livre que o gestor cola descrevendo:
      - Concorrentes nas regiões atendidas
      - Preços/planos da concorrência
      - Sinais de churn (clientes saindo para X)
      - Expansão observada (X está chegando no bairro Y)
      - Reclamações comuns no mercado
    """
    if not market_input or len(market_input.strip()) < 20:
        raise ValueError(
            "Forneça pelo menos 20 caracteres de contexto de mercado.",
        )

    # Snapshot interno simplificado — coletado direto, sem chamar LLM
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()
    pipeline = [
        {"$match": {"company_id": company_id, "status": "finalizada",
                      "closed_at": {"$gte": week_start}}},
        {"$group": {
            "_id": "$assigned_collaborator_id",
            "closed": {"$sum": 1},
            "successes": {"$sum": {"$cond": [
                {"$eq": ["$outcome", "sucesso"]}, 1, 0,
            ]}},
            "instalacoes": {"$sum": {"$cond": [
                {"$eq": ["$type", "instalacao"]}, 1, 0,
            ]}},
            "retiradas": {"$sum": {"$cond": [
                {"$eq": ["$type", "retirada"]}, 1, 0,
            ]}},
            "reparos": {"$sum": {"$cond": [
                {"$in": ["$type", ["reparo", "suporte"]]}, 1, 0,
            ]}},
        }},
    ]
    rows = await db.tickets.aggregate(pipeline).to_list(length=200)
    total_closed = sum(r["closed"] for r in rows)
    total_success = sum(r["successes"] for r in rows)
    snap = {
        "total_closed": total_closed,
        "techs": len(rows),
        "success_rate": (round((total_success / total_closed) * 100, 1)
                            if total_closed else 0),
        "instalacoes": sum(r["instalacoes"] for r in rows),
        "retiradas": sum(r["retiradas"] for r in rows),
        "reparos": sum(r["reparos"] for r in rows),
    }
    top_techs = sorted(
        [{"id": r["_id"], "closed": r["closed"],
          "instalacoes": r["instalacoes"],
          "retiradas": r["retiradas"], "reparos": r["reparos"]}
         for r in rows if r["_id"]],
        key=lambda x: x["closed"], reverse=True,
    )[:3]

    user_prompt = f"""DADOS INTERNOS (últimos 7 dias):
{json.dumps(snap, ensure_ascii=False, indent=2)}

TOP TÉCNICOS POR PONTOS (gamificação):
{json.dumps(top_techs[:3], ensure_ascii=False, indent=2)}

DADOS DE MERCADO INFORMADOS PELO GESTOR:
\"\"\"
{market_input.strip()}
\"\"\"

Gere análise SWOT competitiva em JSON com este schema EXATO:
{{
  "resumo_estrategico": "string (3-5 frases sobre nosso posicionamento competitivo)",
  "swot": {{
    "forcas": ["string", ...],
    "fraquezas": ["string", ...],
    "oportunidades": ["string", ...],
    "ameacas": ["string", ...]
  }},
  "concorrentes_identificados": [
    {{"nome": "string", "ponto_forte": "string", "ponto_fraco": "string",
      "ameaca_para_nos": "alta|media|baixa"}}
  ],
  "bairros_a_priorizar": [
    {{"bairro": "string", "razao": "string", "tipo_acao": "expansao|retencao|comercial"}}
  ],
  "acoes_curto_prazo": [
    {{"acao": "string", "impacto_esperado": "string",
      "responsavel": "Operações|Comercial|Marketing|Financeiro|TI",
      "esforco": "baixo|medio|alto"}}
  ],
  "acoes_estrategicas": [
    {{"acao": "string", "horizonte": "30d|60d|90d",
      "kpi_alvo": "string"}}
  ],
  "pesquisa_adicional_necessaria": ["string", ...],
  "verediito_final": "string (recomendação final em 1 frase)"
}}"""



# -----------------------------------------------------------------------------
# Modo Cliente Cancelando — Playbook de Retenção
# -----------------------------------------------------------------------------
RETENTION_DEFAULTS = {
    "enabled": True,
    "trigger_risk": "critico",  # alto | critico
    "discount_pct": 20,         # % desconto pré-aprovado
    "visit_window_hours": 24,
    "auto_send_whatsapp": True,
    "create_urgent_ticket": True,
    "message_template": (
        "Olá *{nome}*! 💚\n\n"
        "Vi que você está com alguma insatisfação e quero te ajudar pessoalmente.\n"
        "Como cliente importante, aprovei pra você:\n"
        "• *{discount_pct}% de desconto* no próximo ciclo\n"
        "• *Visita técnica de cortesia* em até {visit_window_hours}h\n\n"
        "Posso agendar isso agora? Me responda 'SIM' e cuidamos de tudo. 🚀"
    ),
}


async def get_retention_playbook_config(company_id: str) -> Dict[str, Any]:
    """Lê o playbook de retenção atual; cria com defaults se não existir."""
    cfg = await db.retention_playbook.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not cfg:
        return {**RETENTION_DEFAULTS, "company_id": company_id}
    return {**RETENTION_DEFAULTS, **cfg, "company_id": company_id}


async def fire_retention_playbook(
    company_id: str,
    phone: str,
    customer_name: str = None,
    risk_reason: str = "",
    source: str = "manual",
) -> Dict[str, Any]:
    """Dispara o playbook para um cliente: envia WhatsApp + cria ticket urgente
    + registra no mural de retenção."""
    import httpx

    cfg = await get_retention_playbook_config(company_id)
    if not cfg.get("enabled"):
        return {"ok": False, "reason": "Playbook desativado pelo gestor"}

    # Idempotência: se já existe ação ativa para esse phone < 24h, não duplica
    existing = await db.retention_mural.find_one({
        "company_id": company_id, "phone": phone,
        "status": {"$in": ["open", "in_progress"]},
    }, {"_id": 0, "id": 1})
    if existing:
        return {"ok": False, "reason": "Já existe retenção ativa",
                "retention_id": existing["id"]}

    rid = f"ret-{uuid.uuid4().hex[:10]}"
    nome_first = (customer_name or "Cliente").split(" ")[0]
    message = cfg["message_template"].format(
        nome=nome_first,
        discount_pct=cfg["discount_pct"],
        visit_window_hours=cfg["visit_window_hours"],
    )

    whatsapp_status = "skipped"
    if cfg.get("auto_send_whatsapp") and phone:
        try:
            digits = "".join(c for c in phone if c.isdigit())
            if digits and not digits.startswith("55"):
                digits = "55" + digits
            jid = f"{digits}@s.whatsapp.net"
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.post("http://localhost:3002/send",
                                      json={"to": jid, "text": message})
                whatsapp_status = "sent" if r.status_code in (200, 201) else "failed"
            await db.aihub_wa_messages.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": company_id, "phone": digits,
                "direction": "outbound", "text": message,
                "channel": "baileys",
                "context": "retention_playbook",
                "retention_id": rid,
                "delivery_status": whatsapp_status,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.exception("[retention] WhatsApp falhou: %s", e)
            whatsapp_status = "failed"

    ticket_id = None
    if cfg.get("create_urgent_ticket"):
        ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
        await db.tickets.insert_one({
            "id": ticket_id, "company_id": company_id,
            "type": "retencao", "priority": "urgente",
            "status": "pendente", "assigned_collaborator_id": None,
            "created_at": now_iso(), "opened_at": now_iso(),
            "client_snapshot": {
                "name": f"⚠️ RETENÇÃO: {customer_name or 'Cliente'}",
                "phone": phone, "address": "—", "neighborhood": "—",
            },
            "relato": (
                f"[RETENÇÃO AUTO] Risco {cfg['trigger_risk'].upper()}. "
                f"Motivo: {risk_reason or '—'}. Oferta enviada: "
                f"{cfg['discount_pct']}% off + visita {cfg['visit_window_hours']}h. "
                f"Aguardando resposta do cliente."
            ),
            "position": int(datetime.now(timezone.utc).timestamp() * -1000),
            "retention_id": rid,
        })

    mural_doc = {
        "id": rid, "company_id": company_id,
        "phone": phone, "customer_name": customer_name,
        "risk_reason": risk_reason, "source": source,
        "trigger_risk": cfg["trigger_risk"],
        "discount_pct": cfg["discount_pct"],
        "whatsapp_status": whatsapp_status,
        "ticket_id": ticket_id,
        "status": "open",  # open | in_progress | won | lost
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.retention_mural.insert_one(mural_doc)
    return {"ok": True, "retention_id": rid,
            "whatsapp_status": whatsapp_status, "ticket_id": ticket_id}

    try:
        resp = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system", "content": COMPETITIVE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=GESTAO_MODEL,
            temperature=0.4,
            max_tokens=4500,
            json_mode=True,
            agent="gestao_ia",
        )
        raw = (resp.get("content") or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        # Tenta parsear até o último } completo (LLM às vezes trunca)
        try:
            swot = json.loads(raw)
        except json.JSONDecodeError:
            last_brace = raw.rfind("}")
            if last_brace > 0:
                swot = json.loads(raw[:last_brace + 1])
            else:
                raise
    except Exception as e:
        logger.exception("[gestao_ia.competitive] LLM falhou: %s", e)
        raise

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_input": market_input.strip(),
        "internal_snapshot": snap,
        "swot_analysis": swot,
    }
