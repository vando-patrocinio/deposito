"""Disponibilidade da Lousa Kanban — consulta agenda real para a Isabella.

A Isabella nunca deve oferecer uma data/janela que já esteja LOTADA na grade
da Lousa. Este serviço consulta os tickets agendados nos próximos 7 dias
úteis e devolve um bloco de contexto a ser injetado no prompt da IA.

Janela operacional:
- Seg–Sáb: 09:00–12:00 e 13:00–18:00
- Dom/Feriado: OFF (não oferecer)

Regra de saturação:
- Cada técnico ativo da empresa tem capacidade nominal de
  3 visitas/manhã e 4 visitas/tarde.
- Janela vira LOTADA quando os tickets agendados na janela cobrem
  ≥ 90% da capacidade total dos técnicos disponíveis.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger("ponto.lousa_availability")

WEEKDAY_PT = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]
DATE_EMOJI = {
    1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
    6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 0: "0️⃣",
}

WINDOWS = [
    ("manha", "09:00–12:00", 9, 12),
    ("tarde", "13:00–18:00", 13, 18),
]


def date_to_emoji(d: date) -> str:
    """Converte uma data em emoji de dígitos do dia (ex.: 17 → 1️⃣7️⃣)."""
    day = d.day
    digits = [int(c) for c in str(day)]
    return "".join(DATE_EMOJI.get(x, "") for x in digits)


def _next_business_days(n: int = 7, *, start: Optional[date] = None) -> List[date]:
    """Retorna próximos N dias úteis (seg-sáb), pulando domingos."""
    start = start or date.today()
    out: List[date] = []
    cur = start
    while len(out) < n:
        # weekday(): seg=0...dom=6 — pulamos só domingos
        if cur.weekday() != 6:
            out.append(cur)
        cur += timedelta(days=1)
    return out


async def _count_busy_in_window(company_id: str, day_iso: str,
                                  start_h: int, end_h: int) -> int:
    """Conta tickets agendados que pegam essa janela em day_iso."""
    win_from = f"{day_iso}T{start_h:02d}:00:00"
    win_to = f"{day_iso}T{end_h:02d}:00:00"
    # tickets com scheduled_time dentro da janela, ainda ativos/agendados
    q = {
        "scheduled_time": {"$gte": win_from, "$lt": win_to},
        "status": {"$nin": ["cancelada", "reagendada"]},
    }
    # Filtra por tenant — se company_id for fornecido
    if company_id:
        q["$or"] = [
            {"company_id": company_id},
            {"company_id": {"$exists": False}},  # legado
        ]
    return await db.tickets.count_documents(q)


async def _active_technicians_count(company_id: str) -> int:
    """Quantos técnicos ativos a empresa tem (capacidade nominal)."""
    q: Dict = {
        "$or": [
            {"active": True},
            {"active": {"$exists": False}},
        ],
        "role": {"$in": ["tecnico", "técnico", "TECNICO"]},
    }
    if company_id:
        q["company_id"] = company_id
    cnt = await db.collaborators.count_documents(q)
    return max(cnt, 1)  # nunca zero, evita divisão por zero


async def get_availability_for_prompt(company_id: str,
                                        days: int = 7) -> str:
    """Monta bloco de contexto pra Isabella consultar antes de oferecer data."""
    try:
        techs = await _active_technicians_count(company_id)
        cap_morning = techs * 3   # 3 visitas/manhã/técnico
        cap_afternoon = techs * 4  # 4 visitas/tarde/técnico

        lines: List[str] = [
            "=== AGENDA DA LOUSA (próximos dias úteis) ===",
            "Você é OBRIGADA a consultar esta grade antes de oferecer qualquer",
            "data/janela. NUNCA prometa um horário marcado como LOTADO.",
            f"Capacidade por dia: manhã {cap_morning} visitas, tarde {cap_afternoon} visitas.",
            "",
        ]
        for d in _next_business_days(days):
            day_iso = d.isoformat()
            wkd = WEEKDAY_PT[d.weekday()]
            label = f"{d.strftime('%d/%m')} ({wkd})"
            slots = []
            for win_id, win_label, sh, eh in WINDOWS:
                busy = await _count_busy_in_window(company_id, day_iso, sh, eh)
                cap = cap_morning if win_id == "manha" else cap_afternoon
                # >= 90% lotado
                ratio = busy / cap if cap else 1
                if ratio >= 0.9:
                    slots.append(f"{win_label} LOTADO")
                else:
                    livre = cap - busy
                    slots.append(f"{win_label} {livre} vagas")
            lines.append(f"- {label}: " + " · ".join(slots))
        lines.append("")
        lines.append("REGRAS DE AGENDAMENTO:")
        lines.append("1. Use a data/janela COM VAGAS — nunca uma marcada LOTADO.")
        lines.append("2. Ao confirmar com cliente, use emoji do dia (ex.: dia 17 → 1️⃣7️⃣).")
        lines.append("3. Domingo está fora (não oferecer).")
        lines.append("4. Em caso de TODAS as janelas LOTADAS, ofereça o próximo dia disponível.")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("[lousa_availability] falha: %s", e)
        return ""


def detects_scheduling_intent(text: str) -> bool:
    """Heurística leve pra ativar a injeção só quando faz sentido."""
    t = (text or "").lower()
    triggers = (
        "agend", "marcar", "marca uma", "marca pra",
        "visita técnica", "visita tecnica",
        "instala", "passar aí", "passar ai", "técnico", "tecnico",
        "qual horário", "qual horario",
        "vem amanhã", "vem amanha", "que dia",
    )
    return any(k in t for k in triggers)
