"""Isabella CEO Follow-up V2 — OPERAÇÃO ISABELLA EVOLUÇÃO FINAL V2.

Para cada turn da Isabella, grava em `ai_evaluations` (sem schema novo):

1. OUTCOME OBRIGATÓRIO (sempre 1):
   - RESOLVIDO · PLANO_DE_ACAO · VENDA · RETENCAO · COBRANCA · ACOMPANHAMENTO
2. NPS Invisível (0-10) + motivo, inferido do tom do cliente.
3. Memória Operacional:
   - argumento_sucesso · argumento_falhou
   - produto_ofertado · produto_aceito · produto_recusado
   - tom_utilizado
4. Premium Repair: ativo quando churn_score>0.6 OU VIP OU 3+ tickets em 30d.
5. Plano de Ação estruturado: objetivo · responsavel · prazo · confirmacao.
6. Aprendizado: o_que_funcionou · o_que_nao_funcionou · cliente_satisfeito.

Tudo persiste em `ai_evaluations` (coleção existente). Sem novas IAs,
sem novas coleções, sem novos dashboards. NUNCA falha o request.
"""
from __future__ import annotations
import re
import uuid
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import db


# ---------------------------------------------------------------------------
# Heurísticas linguísticas (regex compilado uma vez)
# ---------------------------------------------------------------------------

OUTCOME_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("VENDA", re.compile(
        r"\b(contratei|contratamos|aceito|aceitei|pode\s+adicionar|"
        r"vou\s+adicionar|vamos\s+contratar|cobrarei|j[áa]\s+adicionei|"
        r"upgrade\s+confirmado|combo\s+aceito)\b",
        re.IGNORECASE)),
    ("RETENCAO", re.compile(
        r"\b(continuar\s+com\s+a\s+gente|n[ãa]o\s+cancelar|mantemos|"
        r"vou\s+ficar|desisti\s+do\s+cancelamento|fica\s+ent[ãa]o)\b",
        re.IGNORECASE)),
    ("COBRANCA", re.compile(
        r"\b(2\u00aa\s*via|segunda\s+via|boleto|pix\s+enviado|"
        r"parcel(amento|ar)|negociar|negociado|liberei\s+o\s+acesso|"
        r"vou\s+pagar|paguei|comprovante)\b",
        re.IGNORECASE)),
    ("RESOLVIDO", re.compile(
        r"\b(resolvido|resolvi|tudo\s+certo|tudo\s+ok|pronto\b|"
        r"finalizado|funcionando\s+agora|voltou\s+a\s+funcionar)\b",
        re.IGNORECASE)),
    ("PLANO_DE_ACAO", re.compile(
        r"\b(plano\s+de\s+a[çc][ãa]o|vou\s+(verificar|monitorar|acompanhar|"
        r"agendar|abrir|enviar)|t[ée]cnico\s+(passa|ir[áa])|"
        r"agendamento|abrir(?:ei)?\s+os|abriremos|reparo\s+agendado)\b",
        re.IGNORECASE)),
    ("ACOMPANHAMENTO", re.compile(
        r"\b(qualquer\s+coisa\s+chame|estou\s+por\s+aqui|"
        r"acompanharei|te\s+aviso|seguimos\s+acompanhando|"
        r"vou\s+monitorar|seguir(?:emos)?\s+acompanhando)\b",
        re.IGNORECASE)),
]

# Sinais positivos x negativos do cliente para NPS invisível
NPS_POS = re.compile(
    r"\b(obrigad[ao]|valeu|excelente|maravilhoso|perfeito|"
    r"r[áa]pid[ao]|gostei|adorei|top|otimo|[óo]timo|legal|"
    r"que\s+bom|isso\s+mesmo|tudo\s+certo|resolveu)\b", re.IGNORECASE)
NPS_NEG = re.compile(
    r"\b(p[ée]ssimo|horr[ií]vel|demora(do|ndo)|n[ãa]o\s+aguent[oa]|"
    r"cancelar|reclamar|procon|absurd[ao]|ridícul[ao]|"
    r"n[ãa]o\s+resolveu|de\s+novo|ainda\s+sem|continua\s+sem|"
    r"j[áa]\s+(disse|falei)|outra\s+vez|toda\s+(hora|semana))\b",
    re.IGNORECASE)
NPS_STRONG_NEG = re.compile(
    r"\b(processar|advogado|procon|small\s*claims|cancelar\s+agora|"
    r"vou\s+sair|migrar\s+para|j[áa]\s+contratei\s+outr[ao])\b",
    re.IGNORECASE)

# Produtos do Universo Ligo (para Memória Operacional)
PRODUCTS = {
    "ligo_security": re.compile(r"\b(ligo\s*security|alarme|security\s+home)\b", re.IGNORECASE),
    "playhub": re.compile(r"\b(playhub|streaming|canais)\b", re.IGNORECASE),
    "ligo_movel": re.compile(r"\b(ligo\s*m[óo]vel|chip|portabilidade)\b", re.IGNORECASE),
    "wifi_premium": re.compile(r"\b(wifi\s+premium|mesh|wi-?fi\s+premium)\b", re.IGNORECASE),
    "ip_fixo": re.compile(r"\b(ip\s+fixo)\b", re.IGNORECASE),
    "upgrade_velocidade": re.compile(r"\b(upgrade|1\s*giga|aumentar\s+velocidade|plano\s+mais\s+r[áa]pido)\b", re.IGNORECASE),
    "indique_ganhe": re.compile(r"\b(indique\s+e\s+ganhe|programa\s+de\s+indica)\b", re.IGNORECASE),
}

# Argumentos de venda mais usados — identificados depois para curadoria
SALES_ARGS = {
    "combo_desconto": re.compile(r"\b(combo|desconto|economiza|junto\s+com)\b", re.IGNORECASE),
    "seguranca_familia": re.compile(r"\b(fam[íi]lia|crian[çc]as|seguran[çc]a)\b", re.IGNORECASE),
    "produtividade": re.compile(r"\b(home\s+office|trabalho|jogos|estabilidade)\b", re.IGNORECASE),
    "premium_experience": re.compile(r"\b(experi[êe]ncia|qualidade|premium|sem\s+travar)\b", re.IGNORECASE),
    "fidelidade": re.compile(r"\b(cliente\s+(antigo|fiel)|h[áa]\s+\d+\s+(anos|meses))\b", re.IGNORECASE),
    "indique_amigo": re.compile(r"\b(amigo|indicar|R\$\s*\d+\s+de\s+desconto)\b", re.IGNORECASE),
}

# Tom usado pela Isabella
TONE_FIRM = re.compile(r"\b(garantimos|vamos\s+resolver|assumo|farei|tomaremos)\b", re.IGNORECASE)
TONE_EMPATHIC = re.compile(r"\b(imagino|entendo|sinto\s+muito|compreendo|sei\s+que)\b", re.IGNORECASE)
TONE_TECHNICAL = re.compile(r"\b(onu|cto|sinal|dbm|olt|pppoe|fibra|porta|placa)\b", re.IGNORECASE)
TONE_COMMERCIAL = re.compile(r"\b(plano|upgrade|combo|oferta|desconto|indique)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_outcome(reply: str) -> str:
    """Retorna SEMPRE 1 outcome. ACOMPANHAMENTO é o default seguro.

    1) Se a Isabella escreveu literalmente 'Outcome: X' no final, usa essa tag.
    2) Senão, faz match heurístico priorizando outcomes específicos.
    """
    if not reply:
        return "ACOMPANHAMENTO"
    # 1) Tag explícita escrita pela Isabella (diretriz V2)
    m = re.search(
        r"outcome[:\s]+(?P<tag>RESOLVIDO|PLANO[_ ]DE[_ ]ACAO|VENDA|RETENCAO|COBRANCA|ACOMPANHAMENTO)",
        reply, re.IGNORECASE)
    if m:
        tag = m.group("tag").upper().replace(" ", "_").replace("ACAO", "ACAO")
        return tag
    # 2) Heurística por padrões
    for tag, pat in OUTCOME_PATTERNS:
        if pat.search(reply):
            return tag
    return "ACOMPANHAMENTO"


def _infer_nps(user_text: str, prev_user_texts: Optional[List[str]] = None,
                isabella_reply: Optional[str] = None,
                outcome: Optional[str] = None) -> Tuple[int, str]:
    """NPS invisível (0-10) + motivo curto.

    Versão V3 (2026-02 — Operação Relacionamento 360°):
    - Não mais penaliza "contato recorrente" cegamente: cliente recorrente
      pode estar bem-atendido (e merece NPS alto se a Isabella acolhe).
    - Aplica BONUS quando outcome é RESOLVIDO/RETENCAO/VENDA/PLANO_DE_ACAO.
    - Aplica BONUS quando a resposta da Isabella demonstra acolhimento
      explícito ("sei que é chato", "vou cuidar pessoalmente", "imagino o
      aperto", etc).
    """
    text = user_text or ""
    reply = isabella_reply or ""
    score = 7
    motivo_parts: List[str] = []

    pos = len(NPS_POS.findall(text))
    neg = len(NPS_NEG.findall(text))
    strong = bool(NPS_STRONG_NEG.search(text))

    if strong:
        score = 1
        motivo_parts.append("ameaça churn/judicial")
    else:
        score += pos * 1
        score -= neg * 2
        if pos:
            motivo_parts.append(f"{pos} sinal(is) positivo(s)")
        if neg:
            motivo_parts.append(f"{neg} sinal(is) negativo(s)")

    # BONUS por outcome positivo da Isabella (V3)
    if outcome in ("RESOLVIDO", "VENDA"):
        score += 2
        motivo_parts.append(f"outcome {outcome}")
    elif outcome in ("RETENCAO", "PLANO_DE_ACAO"):
        score += 1
        motivo_parts.append(f"outcome {outcome}")

    # BONUS por acolhimento explícito na resposta (V3)
    if re.search(r"\b(sei que é (chato|cansativo|incômodo)|imagino|"
                  r"vou cuidar pessoalmente|deixa\s+(comigo|com a gente)|"
                  r"vou resolver|pode contar comigo)\b",
                  reply, re.IGNORECASE):
        score += 1
        motivo_parts.append("acolhimento explícito")

    # Saudação pura sem queixa → neutro 7
    if not pos and not neg and len(text.strip()) < 20:
        score = 7
        motivo_parts.append("interação curta neutra")

    score = max(0, min(10, score))
    return score, "; ".join(motivo_parts) or "neutro"


def _extract_operational_memory(user_text: str, reply: str,
                                 outcome: str) -> Dict[str, Any]:
    """Identifica produto ofertado/aceito/recusado, argumento e tom.
    Sem LLM — heurística determinística sobre o texto."""
    reply_low = (reply or "")
    user_low = (user_text or "")
    mem: Dict[str, Any] = {
        "produto_ofertado": None,
        "produto_aceito": None,
        "produto_recusado": None,
        "argumento_sucesso": None,
        "argumento_falhou": None,
        "tom_utilizado": [],
    }

    # Detecta produto ofertado pela Isabella
    for prod, pat in PRODUCTS.items():
        if pat.search(reply_low):
            mem["produto_ofertado"] = prod
            break

    # Aceite/recusa do cliente
    if mem["produto_ofertado"]:
        if re.search(r"\b(aceito|aceitei|pode\s+adicionar|quero|sim,?\s+(pode|quero))\b",
                      user_low, re.IGNORECASE):
            mem["produto_aceito"] = mem["produto_ofertado"]
        if re.search(r"\b(n[ãa]o\s+(quero|tenho\s+interesse)|recuso|depois|sem\s+condi[çc][õo]es|n[ãa]o,?\s+obrigad)\b",
                      user_low, re.IGNORECASE):
            mem["produto_recusado"] = mem["produto_ofertado"]

    # Argumento (extrai do reply da Isabella)
    arg_found: Optional[str] = None
    for arg_name, pat in SALES_ARGS.items():
        if pat.search(reply_low):
            arg_found = arg_name
            break
    if arg_found:
        if outcome == "VENDA" or mem["produto_aceito"]:
            mem["argumento_sucesso"] = arg_found
        elif mem["produto_recusado"]:
            mem["argumento_falhou"] = arg_found

    # Tom utilizado
    if TONE_FIRM.search(reply_low):
        mem["tom_utilizado"].append("firme")
    if TONE_EMPATHIC.search(reply_low):
        mem["tom_utilizado"].append("empático")
    if TONE_TECHNICAL.search(reply_low):
        mem["tom_utilizado"].append("técnico")
    if TONE_COMMERCIAL.search(reply_low):
        mem["tom_utilizado"].append("comercial")
    if not mem["tom_utilizado"]:
        mem["tom_utilizado"] = ["neutro"]

    return mem


def _extract_action_plan(reply: str) -> Optional[Dict[str, Any]]:
    """Parseia Plano de Ação estruturado quando a Isabella usa o formato.
    Aceita formatos livres:
      - 'objetivo: ...'
      - 'responsável: ...'
      - 'prazo: ...'
      - 'confirmação: ...'
    Caso não encontre nenhum campo, retorna None.
    """
    if not reply:
        return None
    text = reply.lower()
    plan: Dict[str, Any] = {}

    m = re.search(r"objetivo[:\-]\s*([^\n\.]+)", text, re.IGNORECASE)
    if m:
        plan["objetivo"] = m.group(1).strip()[:200]

    m = re.search(r"respons[áa]vel[:\-]\s*([^\n\.]+)", text, re.IGNORECASE)
    if m:
        plan["responsavel"] = m.group(1).strip()[:120]

    m = re.search(r"prazo[:\-]\s*([^\n\.]+)", text, re.IGNORECASE)
    if m:
        plan["prazo"] = m.group(1).strip()[:120]

    m = re.search(r"confirma[çc][ãa]o[:\-]\s*([^\n\.]+)", text, re.IGNORECASE)
    if m:
        plan["confirmacao"] = m.group(1).strip()[:200]

    # Heurística: detecta "técnico passa amanhã/em X horas"
    if "prazo" not in plan:
        m = re.search(r"(em\s+\d+\s+(min|horas?|dias?)|amanh[ãa]|hoje\s+(ainda|mesmo)|at[ée]\s+\d+h)",
                       reply, re.IGNORECASE)
        if m:
            plan["prazo"] = m.group(0).strip()[:120]

    if "responsavel" not in plan:
        if re.search(r"\b(t[ée]cnico|equipe\s+t[ée]cnica)\b", reply, re.IGNORECASE):
            plan["responsavel"] = "equipe técnica"
        elif re.search(r"\b(financeiro|cobran[çc]a)\b", reply, re.IGNORECASE):
            plan["responsavel"] = "financeiro"
        elif re.search(r"\b(eu\s+mesma|isabella|cuidarei)\b", reply, re.IGNORECASE):
            plan["responsavel"] = "isabella"

    return plan or None


async def _detect_premium_repair(company_id: str,
                                  subscriber_id: Optional[str]) -> Dict[str, Any]:
    """Detecta se o cliente está em REPARO PREMIUM:
       churn_score > 0.6 OU VIP OU 3+ tickets em 30d.
    """
    result = {"active": False, "reasons": []}
    if not subscriber_id:
        return result

    sub = await db.subscribers.find_one(
        {"id": subscriber_id},
        {"_id": 0, "churn_score": 1, "vip": 1, "tier": 1,
         "monthly_value": 1, "plan_value": 1, "plan_price": 1}
    )
    if not sub:
        return result

    # Churn
    try:
        churn = float(sub.get("churn_score") or 0)
        # Aceita escalas 0-1 e 0-100
        if churn > 1:
            churn = churn / 100.0
        if churn > 0.6:
            result["active"] = True
            result["reasons"].append(f"churn={churn:.2f}")
    except Exception:
        pass

    # VIP / tier
    if sub.get("vip") is True or (sub.get("tier") or "").lower() in ("vip", "premium", "platinum"):
        result["active"] = True
        result["reasons"].append("vip")

    # Ticket alto (>= R$ 200/mês = VIP de fato)
    try:
        ticket = float(sub.get("monthly_value") or sub.get("plan_value") or sub.get("plan_price") or 0)
        if ticket >= 200:
            result["active"] = True
            result["reasons"].append(f"ticket=R${ticket:.0f}")
    except Exception:
        pass

    # 3+ tickets em 30d
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        n = await db.tickets.count_documents({
            "company_id": company_id,
            "$or": [
                {"client_id": subscriber_id},
                {"subscriber_id": subscriber_id},
                {"client_snapshot.id": subscriber_id},
            ],
            "created_at": {"$gte": cutoff},
        })
        if n >= 3:
            result["active"] = True
            result["reasons"].append(f"tickets_30d={n}")
    except Exception:
        pass

    return result


def _build_learning(outcome: str, nps: int,
                    memory: Dict[str, Any]) -> Dict[str, Any]:
    """Gera o bloco APRENDIZADO (5 perguntas obrigatórias do CTO)."""
    cliente_satisfeito = nps >= 7
    houve_venda = outcome == "VENDA" or bool(memory.get("produto_aceito"))
    houve_retencao = outcome == "RETENCAO"

    funcionou: List[str] = []
    nao_funcionou: List[str] = []

    if memory.get("argumento_sucesso"):
        funcionou.append(f"argumento {memory['argumento_sucesso']}")
    if memory.get("produto_aceito"):
        funcionou.append(f"oferta {memory['produto_aceito']}")
    if outcome in ("RESOLVIDO", "VENDA", "RETENCAO", "COBRANCA") and cliente_satisfeito:
        funcionou.append(f"outcome {outcome} com NPS {nps}")
    if outcome == "ACOMPANHAMENTO" and not cliente_satisfeito:
        nao_funcionou.append("acompanhamento sem resolução clara")
    if memory.get("argumento_falhou"):
        nao_funcionou.append(f"argumento {memory['argumento_falhou']}")
    if memory.get("produto_recusado"):
        nao_funcionou.append(f"oferta {memory['produto_recusado']} recusada")
    if nps <= 3:
        nao_funcionou.append(f"NPS baixíssimo ({nps})")

    return {
        "cliente_satisfeito": cliente_satisfeito,
        "houve_venda": houve_venda,
        "houve_retencao": houve_retencao,
        "o_que_funcionou": funcionou,
        "o_que_nao_funcionou": nao_funcionou,
    }


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

async def register_followup(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    phone: str,
    user_text: str,
    isabella_reply: str,
    context_used: str,
) -> Dict[str, Any]:
    """Classifica o turn da Isabella e persiste tudo em ai_evaluations.

    NUNCA falha o request. Toda exceção é capturada e silenciada.
    """
    reply = isabella_reply or ""
    user_text = user_text or ""

    # Outcome obrigatório
    outcome = _classify_outcome(reply)

    # NPS invisível — busca conversas anteriores do mesmo phone para detectar
    # recorrência sem perguntar
    prev_user_texts: List[str] = []
    try:
        cur = db.aihub_wa_messages.find(
            {"company_id": company_id, "phone": phone, "direction": "inbound"},
            {"_id": 0, "text": 1}
        ).sort("created_at", -1).limit(5)
        prev_user_texts = [m.get("text", "") async for m in cur]
    except Exception:
        prev_user_texts = []

    nps_score, nps_motivo = _infer_nps(user_text, prev_user_texts,
                                            isabella_reply=reply,
                                            outcome=outcome)

    # Memória Operacional
    memory = _extract_operational_memory(user_text, reply, outcome)

    # Plano de Ação estruturado
    action_plan = _extract_action_plan(reply) if outcome == "PLANO_DE_ACAO" else None

    # Premium Repair
    premium = await _detect_premium_repair(company_id, subscriber_id)

    # Aprendizado (5 perguntas do CTO)
    learning = _build_learning(outcome, nps_score, memory)

    # outcomes "boolean" (retro-compat com a V1 já gravada)
    reply_low = reply.lower()
    user_low = user_text.lower()
    outcomes_legacy = {
        "resolveu": outcome == "RESOLVIDO",
        "plano_acao": outcome == "PLANO_DE_ACAO",
        "vendeu": outcome == "VENDA",
        "reteve": outcome == "RETENCAO",
        "cobrou": outcome == "COBRANCA",
        "acompanhamento": outcome == "ACOMPANHAMENTO",
        "indicou": "indique e ganhe" in reply_low or "programa de indica" in reply_low,
        "ofertou": bool(memory.get("produto_ofertado")),
        "problema_tecnico": any(k in user_low for k in
                                 ("sem internet", "caiu", "offline", "lento", "fibra", "sinal", "onu")),
        "avisou_proativo": "já estamos" in reply_low or "ja estamos" in reply_low,
    }

    doc = {
        "id": f"eval-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "phone": phone,
        "user_text": user_text[:500],
        "isabella_reply": reply[:1000],
        "context_length": len(context_used or ""),
        "context_blocks": (context_used or "").count("==="),
        "created_at": _now_iso(),
        "ai_attributed": "Isabella",
        # CAMPOS V2 EVOLUÇÃO FINAL
        "outcome": outcome,
        "nps_inferido": nps_score,
        "nps_motivo": nps_motivo,
        "memoria_operacional": memory,
        "plano_acao": action_plan,
        "premium_repair": premium,
        "aprendizado": learning,
        # retro-compat
        "outcomes": outcomes_legacy,
        "tags": [k for k, v in outcomes_legacy.items() if v] + [outcome.lower()],
    }

    try:
        await db.ai_evaluations.insert_one(doc)
    except Exception:
        pass

    # Conversão: marca isabella_opportunities convertida
    if outcomes_legacy["vendeu"] and subscriber_id:
        try:
            await db.isabella_opportunities.update_many(
                {"company_id": company_id, "subscriber_id": subscriber_id,
                 "status": {"$nin": ["converted", "lost"]}},
                {"$set": {"status": "converted",
                          "converted_at": _now_iso(),
                          "outcome_eval_id": doc["id"]}})
        except Exception:
            pass
    elif memory.get("produto_recusado") and subscriber_id:
        try:
            await db.isabella_opportunities.update_many(
                {"company_id": company_id, "subscriber_id": subscriber_id,
                 "kind": {"$regex": memory["produto_recusado"]},
                 "status": {"$nin": ["converted", "lost"]}},
                {"$set": {"status": "lost",
                          "lost_at": _now_iso(),
                          "lost_reason": memory.get("argumento_falhou") or "recusa cliente"}})
        except Exception:
            pass

    return doc
