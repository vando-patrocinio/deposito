"""Disparo IA · injetor de briefing no system_prompt da Isabella.

Quando um cliente recebe uma mensagem de uma campanha Disparo IA e responde,
a Isabella precisa do CONTEXTO da campanha (briefing, tom, objeções, KPIs).
Esta função busca a campanha ativa mais recente para o telefone e devolve
um bloco de texto pra ser concatenado no system_prompt.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db

logger = logging.getLogger("disparo_ai.briefing")

# Janela de relevância: 14 dias depois do disparo, briefing ainda vale.
BRIEFING_WINDOW_DAYS = 14


async def fetch_disparo_briefing_for_phone(
    company_id: str, phone: str,
) -> Optional[str]:
    """Retorna o bloco de briefing formatado se este phone foi alvo de
    uma campanha Disparo IA nos últimos 14d. None se nada aplicável.

    Estratégia (1 query indexada por phone):
      1. Pega o mass_recipients mais recente desse phone com status sent/delivered
         numa campaign de origin=disparo_ia.
      2. Carrega a campanha (briefing, tipo, KPIs).
      3. Formata em PT-BR como instrução de sistema.
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=BRIEFING_WINDOW_DAYS)).isoformat()

    # 1) Última recipient enviada/entregue pra esse phone
    rec = await db.mass_recipients.find_one(
        {"company_id": company_id, "phone": phone,
         "status": {"$in": ["sent", "delivered"]},
         "sent_at": {"$gte": cutoff}},
        {"_id": 0, "campaign_id": 1, "sent_at": 1},
        sort=[("sent_at", -1)],
    )
    if not rec:
        return None

    # 2) Carrega a campanha — só se for Disparo IA
    camp = await db.mass_campaigns.find_one(
        {"id": rec["campaign_id"], "company_id": company_id,
         "origin": "disparo_ia"},
        {"_id": 0, "name": 1, "disparo_type": 1, "isabella_briefing": 1,
         "expected_kpis": 1, "text": 1},
    )
    if not camp or not camp.get("isabella_briefing"):
        return None

    type_label = {
        "churn_recovery":     "Recuperação de churn",
        "plan_upsell":        "Upsell de plano",
        "friendly_billing":   "Cobrança amigável",
        "nps_csat":           "Pesquisa NPS/CSAT",
        "coverage_expansion": "Expansão de bairros",
        "reactivation":       "Reativação de cancelados",
    }.get(camp.get("disparo_type") or "", camp.get("disparo_type") or "Outbound")

    sent_at = rec.get("sent_at") or ""
    sent_short = sent_at[:16].replace("T", " ") if sent_at else "recentemente"
    msg_preview = (camp.get("text") or "")[:180]

    return (
        "🎯 BRIEFING DA DISPARO IA — ESTE CLIENTE RECEBEU UMA CAMPANHA ATIVA\n"
        f"Campanha: {camp.get('name')} ({type_label})\n"
        f"Disparada em {sent_short}\n"
        f"Mensagem enviada: \"{msg_preview}\"\n"
        f"\n📋 INSTRUÇÕES ESPECÍFICAS DA DISPARO IA pra você (Isabella):\n"
        f"{camp.get('isabella_briefing')}\n"
        "\n⚠️ Siga este briefing PRIORITARIAMENTE. É o que define tom, "
        "objeções esperadas e quando escalar pra humano nesta conversa."
    )
