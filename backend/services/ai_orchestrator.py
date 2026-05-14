"""AI Orchestrator — Isabella consulta outras IAs antes de responder.

Antes de chamar a LLM, junta dados de:
  • Motor IA / SmartOLT — status técnico do cliente (ONU online/offline,
    pane na região, técnico responsável da praça, último chamado aberto).
  • Coach IA — script de atendimento do setor (intenção detectada).
  • Avaliador IA — última avaliação retroativa (se a anterior foi ruim,
    instrui a IA a ser mais cuidadosa).
  • Co-pilot IA — sugestão interna (não vai pro cliente, só ajuda o gestor
    em paralelo).

Retorna um bloco de texto pronto pra ser anexado ao system prompt da
Isabella, garantindo respostas informadas e específicas.

Falha SEMPRE com graciosidade — se um serviço estiver indisponível, o
bloco correspondente é omitido sem quebrar o fluxo de atendimento.
"""
from __future__ import annotations

import logging
from typing import Optional

from database import db

logger = logging.getLogger("ponto.ai_orchestrator")


async def build_orchestrated_context(company_id: str, phone: str,
                                       user_text: str,
                                       subscriber_id: Optional[str] = None) -> str:
    """Monta o bloco de contexto orquestrado consultando todas as IAs
    auxiliares. Retorna string pronta pra ser concatenada ao system prompt.
    """
    blocks: list[str] = []

    # 1) Motor IA — status técnico (ONU/OLT + técnico responsável)
    try:
        b = await _motor_ia_context(company_id, phone, user_text, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] motor_ia skip: %s", e)

    # 2) Coach IA — script do setor + tom de voz
    try:
        b = await _coach_ia_context(company_id, user_text)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] coach_ia skip: %s", e)

    # 3) Avaliador IA — última nota da IA + plano de melhoria
    try:
        b = await _avaliador_ia_context(company_id, phone)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] avaliador_ia skip: %s", e)

    if not blocks:
        return ""
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Helpers internos por agente
# ---------------------------------------------------------------------------

async def _motor_ia_context(company_id: str, phone: str, user_text: str,
                              subscriber_id: Optional[str]) -> str:
    """Consulta Motor IA + SmartOLT para responder questões técnicas com
    dados reais. Detecta intenção 'sem internet/cai/lento' e enriquece a
    resposta com:
      - Status atual da ONU (offline/baixo sinal/normal)
      - Técnico responsável da praça do cliente
      - Último chamado aberto (se houver)
      - Pane regional ativa (se houver)
    """
    text = (user_text or "").lower()
    is_tech_issue = any(kw in text for kw in [
        "sem internet", "sem conexão", "sem conexao", "caiu", "parada",
        "parou", "offline", "off line", "off-line", "lento", "lerdo",
        "oscilando", "oscilação", "instável", "instavel", "fora do ar",
        "não funciona", "nao funciona", "sem net", "internet ruim",
        "wifi não", "wifi nao", "wi-fi não", "wi-fi nao", "modem",
        "roteador", "fibra", "luz vermelha", "sinal baixo",
    ])
    if not is_tech_issue:
        return ""

    lines = ["=== CONTEXTO TÉCNICO (Motor IA + SmartOLT) ==="]
    lines.append(
        "O cliente reportou um problema técnico. Use os dados abaixo para "
        "dar uma resposta ESPECÍFICA — não peça pra reiniciar o equipamento "
        "se você JÁ SABE o que está errado."
    )

    # Busca dados do assinante
    sub = None
    if subscriber_id:
        sub = await db.subscribers.find_one({"id": subscriber_id}, {"_id": 0})
    if not sub and phone:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "phones": {"$in": [digits]}},
            {"_id": 0},
        )

    # 1) Pane regional via SmartOLT AI
    try:
        from services.smartolt_ai import get_outage_for_phone
        outage = await get_outage_for_phone(company_id, phone)
        if outage:
            lines.append(
                f"⚠️ PANE REGIONAL ATIVA: OLT {outage.get('olt_name')} · "
                f"Placa {outage.get('board')} · Porta {outage.get('port')} — "
                f"{outage.get('los_count')}/{outage.get('total_count')} clientes "
                f"afetados. Equipe técnica já notificada."
            )
    except Exception:
        pass

    # 2) Status individual da ONU (se temos assinante)
    if sub:
        pppoe = sub.get("pppoe") or sub.get("pppoe_user") or sub.get("login")
        if pppoe:
            try:
                from services.smartolt_client import find_onu_by_pppoe
                onu = await find_onu_by_pppoe(company_id, pppoe)
                if onu:
                    status_label = "ONLINE" if onu.get("online") else "OFFLINE"
                    sig = onu.get("rx_power") or onu.get("signal_dbm")
                    if sig is not None:
                        try:
                            sig_n = float(sig)
                            status_label += f" · Sinal: {sig_n:.1f} dBm"
                            if sig_n < -27:
                                status_label += " (BAIXO — provável problema no cabo/conector)"
                        except Exception:
                            pass
                    lines.append(f"📡 ONU do cliente: {status_label}")
            except Exception:
                pass

    # 3) Técnico responsável da praça
    if sub and sub.get("praca_id"):
        praca = await db.pracas.find_one({"id": sub["praca_id"]}, {"_id": 0, "name": 1, "city": 1})
        # Última lousa do técnico da praça
        if praca:
            tickets = await db.lousa_tickets.find(
                {"company_id": company_id, "praca_id": sub["praca_id"],
                 "status": {"$in": ["em_andamento", "aberta", "agendada"]}},
                {"_id": 0, "collaborator_name": 1, "type": 1, "status": 1},
            ).limit(3).to_list(3)
            if tickets:
                names = list({t.get("collaborator_name") for t in tickets if t.get("collaborator_name")})
                if names:
                    lines.append(
                        f"👷 Técnicos da praça {praca.get('name')} em campo agora: "
                        + ", ".join(names[:3])
                    )

    # 4) Último chamado do cliente
    if sub:
        last_ticket = await db.lousa_tickets.find_one(
            {"company_id": company_id, "client_snapshot.id": sub.get("id")},
            {"_id": 0, "type": 1, "status": 1, "created_at": 1, "id": 1,
             "collaborator_name": 1},
            sort=[("created_at", -1)],
        )
        if last_ticket:
            lines.append(
                f"📋 Último chamado deste cliente: "
                f"{last_ticket.get('type', '—')} · "
                f"status: {last_ticket.get('status', '—')} · "
                f"técnico: {last_ticket.get('collaborator_name', '—')}"
            )

    if len(lines) == 2:
        return ""  # nenhuma info útil encontrada → não polui o prompt
    lines.append(
        "AÇÃO: cite as informações relevantes ao cliente de forma natural — "
        "ex: 'Vi aqui que sua ONU está offline desde há pouco' — em vez de "
        "pedir testes genéricos."
    )
    return "\n".join(lines)


async def _coach_ia_context(company_id: str, user_text: str) -> str:
    """Coach IA — script de atendimento do setor + tom de voz da empresa.
    Lê coleção `coach_scripts` (se existir) ou usa fallback genérico.
    """
    try:
        script = await db.coach_scripts.find_one(
            {"company_id": company_id, "active": True},
            {"_id": 0, "tone": 1, "rules": 1},
        )
        if not script:
            return ""
        lines = ["=== ORIENTAÇÃO DO COACH IA ==="]
        if script.get("tone"):
            lines.append(f"Tom de voz: {script['tone']}")
        rules = script.get("rules") or []
        if rules:
            lines.append("Regras-chave deste atendimento:")
            for r in rules[:5]:
                lines.append(f"  • {r}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        return ""


async def _avaliador_ia_context(company_id: str, phone: str) -> str:
    """Avaliador IA — verifica se a IA recebeu nota baixa em conversas
    recentes e instrui a ser mais cuidadosa.
    """
    try:
        last_eval = await db.ai_evaluations.find_one(
            {"company_id": company_id, "phone": phone},
            {"_id": 0, "score": 1, "feedback": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        if not last_eval:
            return ""
        score = last_eval.get("score") or 0
        try:
            score_n = float(score)
        except Exception:
            score_n = 0
        if score_n >= 7:
            return ""  # boa avaliação anterior → não polui o prompt
        return (
            "=== ALERTA DO AVALIADOR IA ===\n"
            f"Sua última resposta neste contato recebeu nota {score_n}/10. "
            f"Feedback: {last_eval.get('feedback', '—')}\n"
            "Capriche desta vez — seja mais específica, evite respostas genéricas."
        )
    except Exception:
        return ""
