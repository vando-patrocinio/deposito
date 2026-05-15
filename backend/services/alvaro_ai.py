"""ALVARO IA — Análise estratégica de conversas de atendimento.

Analisa conversas WhatsApp das últimas 24h e gera:
  1. Análise individual JSON (24 campos por conversa) — coleção `alvaro_analyses`
  2. Relatório consolidado diário — coleção `alvaro_reports`

Modelo: deepseek/deepseek-v3.1-terminus via OpenRouter (caller passa).
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

logger = logging.getLogger("alvaro_ai")

ALVARO_MODEL = "deepseek/deepseek-v3.1-terminus"

ALVARO_SYSTEM_PROMPT = """Você é o ALVARO_IA, uma inteligência artificial especializada em análise de atendimento ao cliente, reclamações, risco de cancelamento, qualidade operacional, expansão de cobertura e inteligência comercial.

Sua função é ler, escutar, interpretar e analisar todas as mensagens, conversas, tickets, chats, WhatsApp, e-mails e áudios transcritos de clientes.

Você deve entender o sentido real de cada mensagem, identificar a intenção do cliente, o problema principal, o nível de satisfação, o risco de cancelamento, o tipo de reclamação, o local citado, o bairro, a rua, o horário, o plano contratado e qualquer oportunidade comercial ou operacional.

Para cada conversa analisada, você deve extrair e classificar OBRIGATORIAMENTE:
1. Nome do cliente. 2. Telefone. 3. Data. 4. Horário. 5. Canal. 6. Cidade. 7. Bairro. 8. Rua. 9. Número/referência. 10. Plano. 11. Motivo principal. 12. Tipo reclamação. 13. Sentimento. 14. Urgência. 15. Risco cancelamento. 16. Nota 1-10. 17. Justificativa nota. 18. Cobertura. 19. Setor. 20. Ação. 21. Prazo. 22. Oportunidade comercial. 23. Oportunidade expansão. 24. Resumo.

CATEGORIAS de tipo_reclamacao: Internet lenta, Internet sem sinal, Queda recorrente, Instalação pendente, Mudança de endereço, Segunda via de boleto, Reclamação financeira, Cancelamento solicitado, Ameaça de cancelamento, Pedido de suporte técnico, Reclamação sobre atendimento, Reclamação sobre prazo, Reclamação sobre cobrança, Bairro não atendido, Rua sem cobertura, Interesse em contratar, Pedido de upgrade de plano, Problema com roteador, Problema com Wi-Fi, Reclamação geral, Outro.

SENTIMENTO: Muito positivo | Positivo | Neutro | Negativo | Muito negativo
URGÊNCIA: Baixa | Média | Alta | Crítica
RISCO_CANCELAMENTO:
  - Baixo: dúvida simples, sem insatisfação
  - Médio: incômodo/insatisfação moderada, sem falar em cancelar
  - Alto: reclamação intensa, recorrência, demora, comparação com concorrente
  - Crítico: fala em cancelar, trocar empresa, Procon, processar, perda total de confiança

NOTA 1-10 (pesos: Sentimento 25% / Gravidade 20% / Risco 20% / Recorrência 15% / Impacto 10% / Solução 10%):
  1-2: Muito insatisfeito, risco crítico. 3-4: Insatisfeito, problema relevante. 5: Neutro. 6: Aceitável. 7: Bom. 8-9: Muito bom. 10: Excelente.

COBERTURA: Atendido | Mal atendido | Não atendido | Desconhecido
  - Não atendido: cliente diz que empresa não atende bairro/rua
  - Mal atendido: muitas reclamações/quedas/lentidão recorrente
  - Atendido: cliente já possui serviço ou local com cobertura confirmada

SETOR: Suporte técnico | Comercial | Financeiro | Expansão de rede | Retenção | Atendimento | Gestão

RESPONDA SEMPRE EM JSON VÁLIDO conforme o schema solicitado. Nunca invente dados que não estejam na conversa. Use "não informado" quando o campo não existir. Use "desconhecido" quando houver dúvida. Identifique sinais indiretos de cancelamento (ironia, irritação, cobranças repetidas, comparação com concorrente) mesmo sem a palavra "cancelar". Escreva sempre em português do Brasil.
"""


def _build_conversation_text(messages: List[Dict[str, Any]]) -> str:
    """Concatena mensagens da conversa num bloco legível pelo Alvaro."""
    parts = []
    for m in messages:
        direction = m.get("direction", "?")
        speaker = "CLIENTE" if direction == "inbound" else "ATENDIMENTO"
        ts = (m.get("created_at") or "")[:16].replace("T", " ")
        text = (m.get("text") or "").strip()
        if not text:
            mt = m.get("media_type")
            if mt:
                text = f"[mídia: {mt}]"
            else:
                continue
        parts.append(f"[{ts}] {speaker}: {text}")
    return "\n".join(parts)


def _safe_json_extract(raw: str) -> Dict[str, Any]:
    """Extrai JSON de uma resposta do LLM (lida com ```json fences e prosa)."""
    if not raw:
        return {}
    # Remove code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.M)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.M)
    # Pega o primeiro objeto JSON balanceado
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        logger.warning("[alvaro] JSON parse fail: %s — raw[:200]=%s", e, raw[:200])
        return {}


async def analyze_single_conversation(
    company_id: str,
    phone: str,
    conv_meta: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Analisa uma única conversa e retorna o JSON estruturado da Alvaro IA."""
    convo_text = _build_conversation_text(messages)
    if not convo_text.strip():
        return {}

    # Contexto do cliente (se identificado via subscriber)
    subscriber_block = ""
    sub_id = conv_meta.get("subscriber_id")
    if sub_id:
        sub = await db.subscribers.find_one(
            {"id": sub_id, "company_id": company_id},
            {"_id": 0, "name": 1, "plan_name": 1, "address": 1,
             "branch": 1, "status": 1, "external_code": 1},
        )
        if sub:
            subscriber_block = (
                f"\n=== DADOS DO CLIENTE (sistema) ===\n"
                f"Nome: {sub.get('name')}\n"
                f"Plano: {sub.get('plan_name') or 'não informado'}\n"
                f"Endereço: {sub.get('address') or 'não informado'}\n"
                f"Filial: {sub.get('branch') or 'não informado'}\n"
                f"Status: {sub.get('status') or 'não informado'}\n"
                f"Código: {sub.get('external_code') or 'não informado'}\n"
            )

    push_name = conv_meta.get("push_name") or ""
    last_msg = messages[-1] if messages else {}
    last_ts = (last_msg.get("created_at") or "")[:19]
    data = last_ts[:10] or "não informado"
    horario = last_ts[11:16] or "não informado"

    user_prompt = (
        f"Analise a CONVERSA abaixo e retorne o JSON estruturado da análise individual.\n\n"
        f"=== METADADOS ===\n"
        f"ID conversa: {phone}\n"
        f"Telefone: +{phone}\n"
        f"Push name (WhatsApp): {push_name}\n"
        f"Canal: WhatsApp (Baileys)\n"
        f"Data: {data} | Horário última msg: {horario}\n"
        f"{subscriber_block}"
        f"\n=== CONVERSA ===\n{convo_text[:8000]}\n\n"
        f"Retorne APENAS o JSON no schema:\n"
        '{\n'
        '  "tipo_analise": "conversa_individual",\n'
        '  "id_conversa": "",\n'
        '  "data": "", "horario": "", "canal": "",\n'
        '  "cliente": {"nome": "", "telefone": "", "identificador": ""},\n'
        '  "localizacao": {"cidade": "", "bairro": "", "rua": "", "numero_ou_referencia": "", "status_cobertura": ""},\n'
        '  "plano": {"nome_plano": "", "velocidade": "", "valor": ""},\n'
        '  "analise": {"intencao_principal": "", "motivo_principal_contato": "", "tipo_reclamacao": "", "resumo_da_conversa": "", "sentimento": "", "urgencia": "", "risco_cancelamento": "", "nota_1_a_10": 0, "justificativa_nota": "", "problema_recorrente": false, "impacto_regional": "", "possivel_cancelamento": false},\n'
        '  "acoes_recomendadas": {"setor_responsavel": "", "acao_imediata": "", "prazo_recomendado": "", "observacao": ""},\n'
        '  "oportunidades": {"oportunidade_comercial": "", "oportunidade_expansao": ""}\n'
        '}'
    )

    try:
        r = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system", "content": ALVARO_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=ALVARO_MODEL,
            temperature=0.2,
            max_tokens=2000,
            json_mode=True,
            purpose="general",
            agent="alvaro_ai",
        )
    except Exception as e:
        logger.exception("[alvaro] LLM call failed phone=%s: %s", phone, e)
        return {}

    parsed = _safe_json_extract(r.get("content", ""))
    if not parsed:
        return {}
    # Garante metadados consistentes (caso o modelo não preencha)
    parsed.setdefault("tipo_analise", "conversa_individual")
    parsed.setdefault("id_conversa", phone)
    parsed.setdefault("data", data)
    parsed.setdefault("horario", horario)
    parsed.setdefault("canal", "WhatsApp")
    cli = parsed.setdefault("cliente", {})
    if not cli.get("telefone"):
        cli["telefone"] = f"+{phone}"
    if not cli.get("identificador"):
        cli["identificador"] = sub_id or push_name
    parsed["_model"] = r.get("model")
    parsed["_provider"] = r.get("provider")
    return parsed


async def generate_consolidated_report(
    company_id: str,
    analyses: List[Dict[str, Any]],
    periodo_label: str,
) -> Dict[str, Any]:
    """Agrega N análises individuais num relatório consolidado.

    Etapa 1: estatísticas determinísticas (counters, médias).
    Etapa 2: LLM gera recomendações + resumo executivo a partir do consolidado.
    """
    if not analyses:
        return {
            "tipo_analise": "relatorio_consolidado",
            "periodo_analisado": periodo_label,
            "total_conversas": 0,
            "resumo_executivo": "Nenhuma conversa analisada no período.",
        }

    notas: List[float] = []
    riscos = Counter()
    bairros = Counter()
    ruas = Counter()
    bairros_nao_atendidos: List[str] = []
    bairros_mal_atendidos: List[str] = []
    planos = Counter()
    plano_reclamacao = Counter()
    horarios = Counter()
    tipos_reclamacao = Counter()
    locais_risco: Dict[str, int] = {}
    motivos_cancel: List[str] = []
    criticos: List[Dict[str, Any]] = []
    oportunidades_com: List[str] = []
    oportunidades_exp: List[str] = []

    for a in analyses:
        an = a.get("analise") or {}
        loc = a.get("localizacao") or {}
        pl = a.get("plano") or {}
        op = a.get("oportunidades") or {}
        cli = a.get("cliente") or {}

        try:
            nota = float(an.get("nota_1_a_10") or 0)
        except (TypeError, ValueError):
            nota = 0
        if nota > 0:
            notas.append(nota)

        risco = (an.get("risco_cancelamento") or "").strip().lower()
        if risco in ("baixo", "médio", "medio", "alto", "crítico", "critico"):
            risco_norm = (risco.replace("ç", "c").replace("í", "i")
                              .replace("é", "e"))
            riscos[risco_norm] += 1

        bairro = (loc.get("bairro") or "").strip()
        if bairro and bairro.lower() not in ("não informado", "nao informado", "desconhecido", ""):
            bairros[bairro] += 1
            cob = (loc.get("status_cobertura") or "").lower()
            if cob == "não atendido" or cob == "nao atendido":
                bairros_nao_atendidos.append(bairro)
            elif cob == "mal atendido":
                bairros_mal_atendidos.append(bairro)

        rua = (loc.get("rua") or "").strip()
        if rua and rua.lower() not in ("não informado", "nao informado", "desconhecido", ""):
            ruas[rua] += 1

        plano = (pl.get("nome_plano") or "").strip()
        if plano and plano.lower() not in ("não informado", "nao informado", ""):
            planos[plano] += 1
            if risco in ("alto", "crítico", "critico") or nota and nota <= 4:
                plano_reclamacao[plano] += 1

        hora = (a.get("horario") or "")[:2]
        if hora and hora.isdigit():
            horarios[hora + "h"] += 1

        tipo = (an.get("tipo_reclamacao") or "").strip()
        if tipo and tipo.lower() not in ("não informado", "nao informado", ""):
            tipos_reclamacao[tipo] += 1

        if bairro and risco in ("alto", "crítico", "critico"):
            locais_risco[bairro] = locais_risco.get(bairro, 0) + 1

        if risco in ("crítico", "critico"):
            criticos.append({
                "telefone": cli.get("telefone"),
                "nome": cli.get("nome"),
                "motivo": an.get("motivo_principal_contato"),
                "nota": nota,
            })
            if an.get("motivo_principal_contato"):
                motivos_cancel.append(an["motivo_principal_contato"])

        if op.get("oportunidade_comercial"):
            v = op["oportunidade_comercial"]
            if v and v.lower() not in ("não informado", "nao informado", "", "nenhuma"):
                oportunidades_com.append(v)
        if op.get("oportunidade_expansao"):
            v = op["oportunidade_expansao"]
            if v and v.lower() not in ("não informado", "nao informado", "", "nenhuma"):
                oportunidades_exp.append(v)

    media = round(sum(notas) / len(notas), 2) if notas else 0
    notas_sorted = sorted(notas)
    n = len(notas_sorted)
    piores = notas_sorted[: max(1, n // 5)] if n else []
    melhores = notas_sorted[-max(1, n // 5):] if n else []
    media_piores = round(sum(piores) / len(piores), 2) if piores else 0
    media_melhores = round(sum(melhores) / len(melhores), 2) if melhores else 0

    locais_risco_top = sorted(locais_risco.items(), key=lambda x: -x[1])[:10]

    # Etapa 2: LLM gera resumo executivo + recomendações
    factual_block = json.dumps({
        "total_conversas": len(analyses),
        "media_geral_notas": media,
        "media_piores": media_piores,
        "media_melhores": media_melhores,
        "risco_cancelamento": dict(riscos),
        "top_bairros": bairros.most_common(10),
        "top_ruas": ruas.most_common(10),
        "bairros_nao_atendidos": list(set(bairros_nao_atendidos))[:15],
        "bairros_mal_atendidos": list(set(bairros_mal_atendidos))[:15],
        "top_planos": planos.most_common(10),
        "top_planos_reclamacao": plano_reclamacao.most_common(10),
        "top_horarios": horarios.most_common(10),
        "top_tipos_reclamacao": tipos_reclamacao.most_common(10),
        "locais_risco_alto": locais_risco_top,
        "amostra_motivos_cancelamento": motivos_cancel[:15],
        "n_criticos": len(criticos),
        "oportunidades_comerciais_amostra": oportunidades_com[:10],
        "oportunidades_expansao_amostra": oportunidades_exp[:10],
    }, ensure_ascii=False)

    rec_prompt = (
        f"Recebeu o consolidado factual abaixo de {len(analyses)} conversas WhatsApp das últimas 24h.\n"
        "Gere APENAS o JSON de recomendações com base nos dados (nunca invente nada).\n\n"
        f"DADOS:\n{factual_block}\n\n"
        "Retorne JSON:\n"
        '{\n'
        '  "recomendacoes": {\n'
        '    "suporte_tecnico": ["..."], "comercial": ["..."],\n'
        '    "financeiro": ["..."], "expansao_rede": ["..."], "gestao": ["..."]\n'
        '  },\n'
        '  "resumo_executivo": "Parágrafo de 4-6 frases destacando os pontos críticos do dia, padrões geográficos, risco de churn e ações prioritárias."\n'
        '}'
    )

    rec_data: Dict[str, Any] = {"recomendacoes": {}, "resumo_executivo": ""}
    try:
        r2 = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system", "content": ALVARO_SYSTEM_PROMPT},
                {"role": "user", "content": rec_prompt},
            ],
            model=ALVARO_MODEL,
            temperature=0.3,
            max_tokens=1500,
            json_mode=True,
            purpose="general",
            agent="alvaro_ai",
        )
        parsed = _safe_json_extract(r2.get("content", ""))
        if parsed:
            rec_data = parsed
    except Exception as e:
        logger.warning("[alvaro] recommendations LLM fail: %s", e)
        rec_data["resumo_executivo"] = (
            f"Período analisado: {periodo_label}. {len(analyses)} conversas. "
            f"Nota média {media}. {riscos.get('critico', 0)} casos críticos."
        )

    return {
        "tipo_analise": "relatorio_consolidado",
        "periodo_analisado": periodo_label,
        "total_conversas": len(analyses),
        "media_geral_notas": media,
        "media_piores_resultados": media_piores,
        "media_melhores_resultados": media_melhores,
        "criterio_piores_resultados": "Notas de 1 a 4, risco alto/crítico ou 20% menores notas",
        "criterio_melhores_resultados": "Notas de 8 a 10 ou 20% maiores notas",
        "total_risco_cancelamento": {
            "baixo": riscos.get("baixo", 0),
            "medio": riscos.get("medio", 0),
            "alto": riscos.get("alto", 0),
            "critico": riscos.get("critico", 0),
        },
        "top_bairros_reclamacoes": [{"bairro": k, "qtd": v} for k, v in bairros.most_common(10)],
        "top_ruas_reclamacoes": [{"rua": k, "qtd": v} for k, v in ruas.most_common(10)],
        "bairros_nao_atendidos": list(set(bairros_nao_atendidos))[:20],
        "bairros_mal_atendidos": list(set(bairros_mal_atendidos))[:20],
        "top_planos_com_mais_contato": [{"plano": k, "qtd": v} for k, v in planos.most_common(10)],
        "top_planos_com_mais_reclamacoes": [{"plano": k, "qtd": v} for k, v in plano_reclamacao.most_common(10)],
        "top_horarios_com_mais_contato": [{"hora": k, "qtd": v} for k, v in horarios.most_common(10)],
        "top_tipos_reclamacao": [{"tipo": k, "qtd": v} for k, v in tipos_reclamacao.most_common(10)],
        "locais_maior_risco_cancelamento": [{"bairro": k, "qtd": v} for k, v in locais_risco_top],
        "principais_motivos_cancelamento": list(set(motivos_cancel))[:10],
        "clientes_risco_critico": criticos[:30],
        "oportunidades_comerciais": list(set(oportunidades_com))[:15],
        "oportunidades_expansao": list(set(oportunidades_exp))[:15],
        "recomendacoes": rec_data.get("recomendacoes", {}),
        "resumo_executivo": rec_data.get("resumo_executivo", ""),
    }


async def run_daily_analysis(company_id: str, hours_back: int = 24) -> Dict[str, Any]:
    """Pipeline completo: pega conversas das últimas N horas, analisa cada uma,
    persiste e gera o relatório consolidado.

    Retorna o relatório consolidado (também persiste em alvaro_reports).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_iso = cutoff.isoformat()

    # 1) Descobre conversas ativas nas últimas 24h (que receberam pelo menos
    #    1 mensagem inbound no período)
    pipeline = [
        {"$match": {
            "company_id": company_id,
            "created_at": {"$gte": cutoff_iso},
            "direction": "inbound",
        }},
        {"$group": {"_id": "$phone", "last_at": {"$max": "$created_at"}}},
        {"$sort": {"last_at": -1}},
        {"$limit": 200},  # safety cap
    ]
    cur = db.aihub_wa_messages.aggregate(pipeline)
    phones = [d["_id"] async for d in cur]

    analyses: List[Dict[str, Any]] = []
    failures: List[str] = []
    run_id = f"alv-run-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat()

    for phone in phones:
        # Carrega últimas 30 msgs da conversa (cap pra evitar prompt gigante)
        msgs = await db.aihub_wa_messages.find(
            {"company_id": company_id, "phone": phone},
            {"_id": 0},
        ).sort("created_at", -1).limit(30).to_list(30)
        msgs.reverse()  # cronológico
        if not msgs:
            continue

        # Metadata da conversa
        conv = await db.wa_conversations.find_one(
            {"company_id": company_id, "phone": phone},
            {"_id": 0, "subscriber_id": 1, "push_name": 1, "assignee_role": 1},
        ) or {}

        try:
            result = await analyze_single_conversation(
                company_id, phone, conv, msgs,
            )
        except Exception as e:
            logger.exception("[alvaro] analyze fail phone=%s: %s", phone, e)
            failures.append(phone)
            continue

        if not result:
            failures.append(phone)
            continue

        # Persiste
        doc = {
            "id": f"alv-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "run_id": run_id,
            "phone": phone,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }
        await db.alvaro_analyses.insert_one(doc)
        analyses.append(result)

    # 2) Relatório consolidado
    periodo_label = (
        f"{cutoff.strftime('%Y-%m-%d %H:%M')} → "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    consolidated = await generate_consolidated_report(
        company_id, analyses, periodo_label,
    )

    finished_at = datetime.now(timezone.utc).isoformat()
    report_doc = {
        "id": f"alv-rep-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "run_id": run_id,
        "period_hours": hours_back,
        "started_at": started_at,
        "finished_at": finished_at,
        "phones_processed": len(phones),
        "analyses_ok": len(analyses),
        "analyses_failed": len(failures),
        "report": consolidated,
    }
    await db.alvaro_reports.insert_one(report_doc)
    logger.info(
        "[alvaro] daily run %s ok=%d fail=%d", run_id, len(analyses), len(failures),
    )
    return {
        "run_id": run_id,
        "phones_processed": len(phones),
        "analyses_ok": len(analyses),
        "analyses_failed": len(failures),
        "report_id": report_doc["id"],
        "report": consolidated,
    }
