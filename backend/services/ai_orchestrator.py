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


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

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

    # 0) Perfil financeiro/contratual do cliente (Isabella V6 — universo Ligo)
    try:
        b = await _customer_profile_context(company_id, phone, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] customer_profile skip: %s", e)

    # 1) Motor IA — status técnico (ONU/OLT + técnico responsável + CTO + vizinhos)
    try:
        b = await _motor_ia_context(company_id, phone, user_text, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] motor_ia skip: %s", e)

    # 1b) Incidente coletivo (rede_ia_outage_detector)
    try:
        b = await _collective_incident_context(company_id, phone, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] collective_incident skip: %s", e)

    # 1c) Histórico de chamados deste cliente (recorrência)
    try:
        b = await _customer_ticket_history_context(company_id, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] ticket_history skip: %s", e)

    # 1d) Truck Roll Guard — sinaliza se NÃO deve abrir reparo
    try:
        b = await _truck_roll_guard_context(company_id, phone, user_text, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] truck_roll_guard skip: %s", e)

    # 1e) REPARO PREMIUM — Evolução Final V2
    try:
        b = await _premium_repair_context(company_id, phone, subscriber_id)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] premium_repair skip: %s", e)

    # 1f) IDENTIDADE 360° — endereço · equipamentos · última fatura · OS
    try:
        from services.identity_360 import identity_360, format_for_isabella
        ident = await identity_360(company_id, phone)
        b = format_for_isabella(ident)
        if b:
            blocks.append(b)
    except Exception as e:
        logger.info("[orchestrator] identity_360 skip: %s", e)

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
    _ = any(kw in text for kw in [  # placeholder — V4 sempre consulta
        "sem internet", "sem conexão", "sem conexao", "caiu", "parada",
        "parou", "offline", "off line", "off-line", "lento", "lerdo",
        "oscilando", "oscilação", "instável", "instavel", "fora do ar",
        "não funciona", "nao funciona", "sem net", "internet ruim",
        "wifi não", "wifi nao", "wi-fi não", "wi-fi nao", "modem",
        "roteador", "fibra", "luz vermelha", "sinal baixo",
    ])
    # Isabella V4: SEMPRE consulta o estado técnico antes de responder.

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

    # Vizinhos na mesma CTO (Isabella V4 — visão de bairro)
    if sub:
        try:
            cto_id = sub.get("cto_id") or sub.get("ctoId")
            if cto_id:
                # Quantos vizinhos ONLINE/OFFLINE na MESMA CTO
                neigh_off = await db.subscribers.count_documents({
                    "company_id": company_id, "cto_id": cto_id,
                    "status": "OFFLINE",
                })
                neigh_total = await db.subscribers.count_documents({
                    "company_id": company_id, "cto_id": cto_id,
                })
                cto_doc = await db.ctos.find_one(
                    {"id": cto_id}, {"_id": 0, "name": 1, "health": 1})
                if cto_doc and neigh_total:
                    pct_off = round(neigh_off * 100 / neigh_total, 1)
                    lines.append(
                        f"🏘️ CTO {cto_doc.get('name', cto_id)}: "
                        f"{neigh_off}/{neigh_total} vizinhos offline ({pct_off}%)"
                        + (f" · saúde {cto_doc.get('health')}"
                           if cto_doc.get("health") else "")
                    )
        except Exception:
            pass

    lines.append(
        "AÇÃO: cite as informações relevantes ao cliente de forma natural — "
        "ex: 'Vi aqui que sua ONU está offline desde há pouco' — em vez de "
        "pedir testes genéricos."
    )
    return "\n".join(lines)


# ─────── Novos helpers Isabella V4/V5/V6 ───────

async def _customer_profile_context(company_id: str, phone: str,
                                     subscriber_id: Optional[str]) -> str:
    """Perfil financeiro + contratual do cliente para Isabella V6 (universo Ligo).
    Lê subscribers + subscriber_invoices. Não inventa dados.
    """
    sub = None
    if subscriber_id:
        sub = await db.subscribers.find_one({"id": subscriber_id},
                                              {"_id": 0})
    if not sub and phone:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "phones": {"$in": [digits]}},
            {"_id": 0})
    if not sub:
        return ""

    lines = ["=== PERFIL DO CLIENTE (Isabella V6 — Universo Ligo) ==="]
    if sub.get("name"):
        lines.append(f"Nome: {sub.get('name')}")
    if sub.get("plan_name"):
        ticket = sub.get("monthly_value") or sub.get("plan_value")
        ticket_s = f" (R$ {float(ticket):.2f})" if ticket else ""
        lines.append(f"Plano: {sub.get('plan_name')}{ticket_s}")
    if sub.get("status"):
        lines.append(f"Status: {sub.get('status')}")
    # Tempo de contrato
    if sub.get("activated_at") or sub.get("created_at"):
        try:
            from datetime import datetime, timezone as _tz
            start_s = sub.get("activated_at") or sub.get("created_at")
            if isinstance(start_s, str):
                start_dt = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
            else:
                start_dt = start_s
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=_tz.utc)
            months = max(1, int((datetime.now(_tz.utc) - start_dt).days / 30))
            lines.append(f"Cliente há {months} meses")
        except Exception:
            pass

    # Inadimplência
    try:
        overdue = await db.subscriber_invoices.count_documents({
            "company_id": company_id, "subscriber_id": sub.get("id"),
            "status": {"$in": ["overdue", "OVERDUE", "atrasado"]},
        })
        if overdue:
            lines.append(f"⚠️ {overdue} faturas em atraso")
    except Exception:
        pass

    # Recomendações de upgrade/cross-sell (Isabella V6)
    try:
        ticket = float(sub.get("monthly_value") or sub.get("plan_value") or 0)
        recs = []
        plan_name = (sub.get("plan_name") or "").lower()
        # Ligo Security
        if "security" not in plan_name and ticket >= 70:
            recs.append("Ligo Security (alarme residencial — combo com a internet)")
        # PlayHub
        if "playhub" not in plan_name and "play" not in plan_name:
            recs.append("PlayHub (streaming + canais em 1 só conta)")
        # Ligo Móvel
        if "móvel" not in plan_name and "movel" not in plan_name:
            recs.append("Ligo Móvel (chip celular com portabilidade)")
        # Upgrade de velocidade
        if "300" in plan_name or "100" in plan_name or "200" in plan_name:
            recs.append("Upgrade para plano mais rápido (1 Giga)")
        # WiFi Premium
        if "premium" not in plan_name:
            recs.append("WiFi Premium (mesh com cobertura total)")
        # IP fixo
        if not sub.get("ip_fixo"):
            recs.append("IP Fixo (para câmeras, home office, jogos)")
        # Indique e Ganhe (todos os clientes)
        recs.append("Indique e Ganhe (R$ desconto por amigo trazido)")
        if recs:
            lines.append("Oportunidades disponíveis (NÃO empurre, só recomende se fizer sentido):")
            for r in recs[:3]:
                lines.append(f"  • {r}")
    except Exception:
        pass

    if len(lines) == 1:
        return ""
    # Scores comportamentais para Isabella priorizar internamente
    try:
        scores = []
        if sub.get("churn_score") is not None:
            scores.append(f"churn={sub['churn_score']:.2f}")
        if sub.get("retention_score") is not None:
            scores.append(f"retention={sub['retention_score']:.2f}")
        if sub.get("referral_score") is not None:
            scores.append(f"referral={sub['referral_score']:.2f}")
        if sub.get("collection_score") is not None:
            scores.append(f"collection={sub['collection_score']:.2f}")
        if scores:
            lines.append("Scores internos (NÃO mostrar ao cliente): " + " · ".join(scores))
    except Exception:
        pass
    # Diretrizes Isabella ÚNICA + CEO DO CLIENTE + EVOLUÇÃO FINAL V2
    lines.append(
        "DIRETRIZES OBRIGATÓRIAS (Isabella CEO do Cliente — Evolução Final V2):\n"
        "\n"
        "1. POSSE DA CONVERSA\n"
        "   • Você é Isabella. Você é DONA do problema do cliente.\n"
        "   • NUNCA diga 'vou transferir', 'aguarde o setor', 'vou encaminhar'.\n"
        "   • Nunca cite Álvaro, Rede IA, Presidente IA, Sistema Nervoso,\n"
        "     SmartOLT Twin ou Truck Roll Guard. Toda inteligência é SUA.\n"
        "\n"
        "2. OUTCOME OBRIGATÓRIO (toda resposta deve terminar com UM):\n"
        "   ✓ RESOLVIDO       → problema resolvido nesta interação\n"
        "   ✓ PLANO_DE_ACAO   → próximo passo definido (Objetivo · Responsável · Prazo · Confirmação)\n"
        "   ✓ VENDA           → upgrade/combo aceito agora\n"
        "   ✓ RETENCAO        → cliente desistiu de cancelar\n"
        "   ✓ COBRANCA        → cobrança encaminhada (2ª via, parcelamento, pix)\n"
        "   ✓ ACOMPANHAMENTO  → seguirei acompanhando até estabilizar\n"
        "   Nunca finalize a resposta sem fechar com um destes.\n"
        "\n"
        "3. PLANO DE AÇÃO ESTRUTURADO (quando PLANO_DE_ACAO)\n"
        "   Use SEMPRE este formato literal no final da resposta:\n"
        "     • Objetivo: <o que vai acontecer>\n"
        "     • Responsável: <quem executa: técnico/financeiro/eu mesma>\n"
        "     • Prazo: <quando: hoje 14h / amanhã / em 24h>\n"
        "     • Confirmação: <como o cliente saberá que foi feito>\n"
        "\n"
        "4. MODO TÉCNICO (quando há sinal de problema na rede)\n"
        "   Responda em 4 pontos:\n"
        "     a) O que aconteceu (use o contexto técnico acima)\n"
        "     b) O que está sendo feito\n"
        "     c) Quando volta\n"
        "     d) Como evitar novamente\n"
        "   Use os dados de ONU/CTO/vizinhos. Proibido CHUTAR. Proibido INVENTAR.\n"
        "\n"
        "5. MODO COMERCIAL\n"
        "   • Resolva o problema PRIMEIRO.\n"
        "   • Avalie no máximo 1 oferta do Universo Ligo.\n"
        "   • Use os Scores para priorizar (maior score = maior prioridade).\n"
        "   • Recomende com motivo claro. Nunca empurre.\n"
        "\n"
        "6. MODO PROATIVO\n"
        "   • Se há incidente coletivo ativo, AVISE antes do cliente reclamar.\n"
        "   • Se churn_score > 0.6, foque em retenção (gere valor antes de desconto).\n"
        "   • Se collection_score > 0.6, ofereça parcelamento ou 2ª via.\n"
        "\n"
        "7. NPS INVISÍVEL\n"
        "   • NÃO peça nota ao cliente. Nunca.\n"
        "   • Identifique o tom dele (palavras, repetição, ameaças)\n"
        "     e ajuste sua resposta para virar promotor (NPS≥9).\n"
        "\n"
        "8. MEMÓRIA OPERACIONAL\n"
        "   • Quando ofertar produto, indique no texto qual produto e\n"
        "     qual o argumento (combo, segurança família, produtividade etc).\n"
        "   • Isso permite registrar o que converte vs o que falha.\n"
        "\n"
        "9. PERGUNTA INTERNA OBRIGATÓRIA\n"
        "   Antes de enviar, pergunte a si mesma:\n"
        "   'O que eu faria se este cliente fosse meu?'\n"
        "   Se a resposta não trata o cliente como dono, reescreva."
    )
    return "\n".join(lines)


async def _collective_incident_context(company_id: str, phone: str,
                                        subscriber_id: Optional[str]) -> str:
    """Verifica incidente coletivo ativo na região do cliente."""
    sub = None
    if subscriber_id:
        sub = await db.subscribers.find_one({"id": subscriber_id},
                                              {"_id": 0, "olt_name": 1, "cto_id": 1})
    if not sub and phone:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "phones": {"$in": [digits]}},
            {"_id": 0, "olt_name": 1, "cto_id": 1})
    if not sub:
        return ""

    inc = await db.incidents.find_one({
        "company_id": company_id,
        "status": {"$in": ["open", "OPEN", "active"]},
        "$or": [
            {"olt_name": sub.get("olt_name")},
            {"cto_id": sub.get("cto_id")},
        ],
    }, {"_id": 0, "title": 1, "severity": 1, "type": 1, "created_at": 1})
    if not inc:
        return ""
    return (
        "=== INCIDENTE COLETIVO ATIVO ===\n"
        f"Tipo: {inc.get('type', '—')} · Severidade: {inc.get('severity', '—')}\n"
        f"Detalhe: {inc.get('title', '—')}\n"
        "AÇÃO: avise o cliente que JÁ ESTAMOS resolvendo; NÃO abra reparo "
        "individual; ofereça atualização proativa quando normalizar."
    )


async def _customer_ticket_history_context(company_id: str,
                                            subscriber_id: Optional[str]) -> str:
    """Recorrência de chamados deste cliente — se >3 nos últimos 30 dias,
    sinaliza que provavelmente é problema crônico (não despachar tech genérico).
    """
    if not subscriber_id:
        return ""
    from datetime import datetime, timedelta, timezone as _tz
    cutoff = (datetime.now(_tz.utc) - timedelta(days=30)).isoformat()
    n = 0
    try:
        n = await db.tickets.count_documents({
            "company_id": company_id,
            "$or": [
                {"subscriber_id": subscriber_id},
                {"client_id": subscriber_id},
                {"client_snapshot.id": subscriber_id},
            ],
            "created_at": {"$gte": cutoff},
        })
    except Exception:
        return ""
    if n < 3:
        return ""
    return (
        "=== ALERTA RECORRÊNCIA ===\n"
        f"Este cliente abriu {n} chamados nos últimos 30 dias. "
        "Provavelmente é problema CRÔNICO (CTO/cabo/conector). "
        "AÇÃO: NÃO peça reinício de modem. Escale para análise técnica de causa-raiz."
    )


async def _truck_roll_guard_context(company_id: str, phone: str,
                                     user_text: str,
                                     subscriber_id: Optional[str]) -> str:
    """Truck Roll Avoidance — quando o cliente fala em problema técnico,
    avalia se HÁ evidência de que precisa visita ou se dá pra resolver
    remotamente.
    """
    text = (user_text or "").lower()
    is_tech = any(kw in text for kw in [
        "sem internet", "caiu", "offline", "lento", "fibra", "modem",
        "roteador", "sinal", "wifi", "wi-fi", "não funciona",
        "nao funciona", "fora do ar",
    ])
    if not is_tech:
        return ""
    if not subscriber_id:
        return ""

    sub = await db.subscribers.find_one(
        {"id": subscriber_id},
        {"_id": 0, "pppoe": 1, "pppoe_user": 1, "login": 1, "cto_id": 1})
    if not sub:
        return ""

    onu_online = None
    onu_signal = None
    try:
        pppoe = sub.get("pppoe") or sub.get("pppoe_user") or sub.get("login")
        if pppoe:
            from services.smartolt_client import find_onu_by_pppoe
            onu = await find_onu_by_pppoe(company_id, pppoe)
            if onu:
                onu_online = bool(onu.get("online"))
                sig = onu.get("rx_power") or onu.get("signal_dbm")
                if sig is not None:
                    try:
                        onu_signal = float(sig)
                    except Exception:
                        pass
    except Exception:
        pass

    cto_off_pct = None
    try:
        if sub.get("cto_id"):
            off = await db.subscribers.count_documents({
                "company_id": company_id, "cto_id": sub["cto_id"],


async def _premium_repair_context(company_id: str, phone: str,
                                    subscriber_id: Optional[str]) -> str:
    """REPARO PREMIUM — Evolução Final V2.

    Ativa quando: churn_score>0.6 OU vip OU 3+ tickets em 30d OU ticket>=R$200.
    Quando ativo, dá ordens claras à Isabella para mudar o comportamento.
    """
    sub = None
    if subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": subscriber_id},
            {"_id": 0, "churn_score": 1, "vip": 1, "tier": 1, "name": 1,
             "monthly_value": 1, "plan_value": 1, "plan_price": 1, "plan_name": 1})
    if not sub and phone:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "phones": {"$in": [digits]}},
            {"_id": 0, "id": 1, "churn_score": 1, "vip": 1, "tier": 1,
             "name": 1, "monthly_value": 1, "plan_value": 1, "plan_price": 1,
             "plan_name": 1})
    if not sub:
        return ""

    reasons: list[str] = []
    # Churn
    try:
        churn = float(sub.get("churn_score") or 0)
        if churn > 1:
            churn = churn / 100.0
        if churn > 0.6:
            reasons.append(f"churn_score={churn:.2f}")
    except Exception:
        pass
    # VIP/tier
    tier = (sub.get("tier") or "").lower()
    if sub.get("vip") is True or tier in ("vip", "premium", "platinum"):
        reasons.append(f"VIP({tier or 'flag'})")
    # Ticket alto
    try:
        ticket = float(sub.get("monthly_value") or sub.get("plan_value") or sub.get("plan_price") or 0)
        if ticket >= 200:
            reasons.append(f"ticket=R${ticket:.0f}")
    except Exception:
        pass
    # Recorrência 30d
    try:
        from datetime import datetime, timedelta, timezone as _tz
        cutoff = (datetime.now(_tz.utc) - timedelta(days=30)).isoformat()
        n = await db.tickets.count_documents({
            "company_id": company_id,
            "$or": [
                {"client_id": sub.get("id") or subscriber_id},
                {"subscriber_id": sub.get("id") or subscriber_id},
                {"client_snapshot.id": sub.get("id") or subscriber_id},
            ],
            "created_at": {"$gte": cutoff},
        })
        if n >= 3:
            reasons.append(f"tickets_30d={n}")
    except Exception:
        pass

    if not reasons:
        return ""

    return (
        "=== REPARO PREMIUM ATIVO ===\n"
        f"Motivos: {' · '.join(reasons)}\n"
        "PRIORIDADE MÁXIMA. Comportamento OBRIGATÓRIO:\n"
        "  • Assuma a responsabilidade explicitamente ('Eu vou cuidar disso pessoalmente').\n"
        "  • Diagnóstico detalhado — cite ONU/CTO/vizinhos por nome.\n"
        "  • Próximos passos numerados (1., 2., 3.) com prazo em horas.\n"
        "  • NÃO repita perguntas que o cliente já respondeu nesta sessão.\n"
        "  • Reduza atrito: ofereça soluções antes de pedir confirmações.\n"
        "  • Encerre SEMPRE com PLANO_DE_ACAO completo (Objetivo · Responsável · Prazo · Confirmação).\n"
    )


                "status": "OFFLINE"})
            tot = await db.subscribers.count_documents({
                "company_id": company_id, "cto_id": sub["cto_id"]})
            if tot:
                cto_off_pct = off * 100 / tot
    except Exception:
        pass

    # Decisão de truck roll
    if onu_online is True and (onu_signal is None or onu_signal >= -25):
        return (
            "=== TRUCK ROLL GUARD: NÃO ABRA REPARO ===\n"
            f"ONU ONLINE · sinal {('%.1f dBm' % onu_signal) if onu_signal is not None else 'OK'}"
            + (f" · CTO {cto_off_pct:.0f}% offline" if cto_off_pct else "")
            + ".\n"
            "AÇÃO: oriente o cliente a reiniciar o modem (cabo de força 30s). "
            "NÃO abra OS — investigue antes. Se persistir, peça uma foto do "
            "modem e da luz da fibra."
        )
    if onu_online is False or (onu_signal is not None and onu_signal < -27):
        return (
            "=== TRUCK ROLL GUARD: SUSPEITO DE PROBLEMA REAL ===\n"
            f"ONU offline ou sinal degradado (sig={onu_signal}). "
            f"{('CTO ' + str(round(cto_off_pct)) + '%% offline → possível corte coletivo') if cto_off_pct and cto_off_pct > 30 else ''}\n"
            "AÇÃO: se >30% da CTO offline, NÃO abra reparo individual — "
            "trate como queda coletiva. Senão, abra OS com prioridade alta."
        )
    return ""


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
