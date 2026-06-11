"""ISABELLA ACTIONS — executor de ações na Lousa via marcadores.

Como Isabella não tem function-calling nativo no fluxo conversacional,
ela emite MARCADORES no fim da resposta. O sistema:
  1. Detecta o marcador
  2. Executa a ação REAL (insert em `tickets`)
  3. Substitui o marcador pela confirmação ao cliente

Marcadores suportados:
  [AGENDAR_VISITA data=YYYY-MM-DD janela=manha|tarde motivo="texto"]
  [ABRIR_CHAMADO tipo=tecnico|comercial motivo="texto"]
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Cria tickets via marcadores [AGENDAR_VISITA] / [ABRIR_CHAMADO].",
}


import logging
import re
import uuid
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

log = logging.getLogger("ponto.isabella_actions")


# ─── Marcadores ───────────────────────────────────────────────
_AGENDAR_RX = re.compile(
    r"\[AGENDAR_VISITA\s+"
    r"data=(\d{4}-\d{2}-\d{2})\s+"
    r"janela=(manha|tarde)"
    r"(?:\s+motivo=\"([^\"]+)\")?\s*\]",
    re.IGNORECASE)

_CHAMADO_RX = re.compile(
    r"\[ABRIR_CHAMADO\s+"
    r"tipo=(tecnico|t[ée]cnico|comercial|suporte)"
    r"(?:\s+motivo=\"([^\"]+)\")?\s*\]",
    re.IGNORECASE)


WINDOWS = {
    "manha": (time(9, 0), "09h–12h"),
    "tarde": (time(13, 0), "13h–18h"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _create_visit_ticket(*, company_id: str, phone: str,
                                  subscriber_id: Optional[str],
                                  subscriber_name: Optional[str],
                                  date_iso: str,
                                  window: str,
                                  motivo: str) -> Dict[str, Any]:
    win_time, win_label = WINDOWS.get(window, WINDOWS["manha"])
    scheduled = f"{date_iso}T{win_time.strftime('%H:%M:%S')}"
    ticket_id = f"tk-{uuid.uuid4().hex[:14]}"
    short = ticket_id.replace("tk-", "TK-")[:10].upper()
    ticket = {
        "id": ticket_id,
        "short_id": short,
        "company_id": company_id,
        "type": "visita_tecnica",
        "subject": (f"Visita técnica — {motivo[:80]}"
                     if motivo else "Visita técnica solicitada via WhatsApp"),
        "description": motivo or "",
        "priority": "media",
        "status": "AGENDADO",
        "scheduled_time": scheduled,
        "scheduled_window": window,
        "scheduled_window_label": win_label,
        "scheduled_date": date_iso,
        "phone": phone,
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "source": "isabella_whatsapp",
        "created_at": _now_iso(),
        "created_by": "isabella",
    }
    await db.tickets.insert_one(ticket)
    log.info("[isabella_actions] visita criada ticket=%s phone=%s "
              "date=%s window=%s", ticket_id, phone, date_iso, window)
    return {"ticket_id": ticket_id, "short_id": short,
            "scheduled_date": date_iso, "window": window,
            "window_label": win_label,
            "br_date": _format_br_date(date_iso)}


async def _create_chamado(*, company_id: str, phone: str,
                            subscriber_id: Optional[str],
                            subscriber_name: Optional[str],
                            tipo: str,
                            motivo: str) -> Dict[str, Any]:
    tipo_norm = "tecnico" if "tec" in tipo.lower() else tipo.lower()
    ticket_id = f"tk-{uuid.uuid4().hex[:14]}"
    short = ticket_id.replace("tk-", "TK-")[:10].upper()
    ticket = {
        "id": ticket_id,
        "short_id": short,
        "company_id": company_id,
        "type": f"chamado_{tipo_norm}",
        "subject": (f"Chamado {tipo_norm} — {motivo[:80]}"
                     if motivo else f"Chamado {tipo_norm} via WhatsApp"),
        "description": motivo or "",
        "priority": "media",
        "status": "ABERTO",
        "phone": phone,
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "source": "isabella_whatsapp",
        "created_at": _now_iso(),
        "created_by": "isabella",
    }
    await db.tickets.insert_one(ticket)
    log.info("[isabella_actions] chamado criado ticket=%s phone=%s tipo=%s",
              ticket_id, phone, tipo_norm)
    return {"ticket_id": ticket_id, "short_id": short, "tipo": tipo_norm}


def _format_br_date(date_iso: str) -> str:
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        return d.strftime("%d/%m")
    except Exception:
        return date_iso


async def execute_action_markers(*, reply_text: str,
                                      company_id: str,
                                      phone: str,
                                      subscriber_id: Optional[str] = None,
                                      subscriber_name: Optional[str] = None
                                      ) -> Tuple[str, List[Dict[str, Any]]]:
    """Detecta marcadores em reply_text, executa as ações e substitui
    pelo texto de confirmação para o cliente.

    Retorna (reply_text_sem_marcadores, lista_ações_executadas).
    """
    actions_done: List[Dict[str, Any]] = []
    if not reply_text or "[" not in reply_text:
        return reply_text, actions_done

    # AGENDAR_VISITA
    async def _replace_agendar(match: re.Match) -> str:
        date_iso = match.group(1)
        window = match.group(2).lower()
        motivo = (match.group(3) or "").strip()
        try:
            result = await _create_visit_ticket(
                company_id=company_id, phone=phone,
                subscriber_id=subscriber_id,
                subscriber_name=subscriber_name,
                date_iso=date_iso, window=window, motivo=motivo)
            actions_done.append({"type": "schedule_visit", **result})
            return (f"Marquei pra {result['br_date']} entre "
                     f"{result['window_label']} — protocolo "
                     f"{result['short_id']}.")
        except Exception as e:
            log.error("[isabella_actions] AGENDAR_VISITA falhou: %s", e)
            return ("Tive um problema ao registrar agora. "
                     "Vou repassar pro time e te confirmo.")

    # ABRIR_CHAMADO
    async def _replace_chamado(match: re.Match) -> str:
        tipo = match.group(1).lower()
        motivo = (match.group(2) or "").strip()
        try:
            result = await _create_chamado(
                company_id=company_id, phone=phone,
                subscriber_id=subscriber_id,
                subscriber_name=subscriber_name,
                tipo=tipo, motivo=motivo)
            actions_done.append({"type": "open_ticket", **result})
            return (f"Abri o chamado — protocolo {result['short_id']}. "
                     f"A equipe entra em contato.")
        except Exception as e:
            log.error("[isabella_actions] ABRIR_CHAMADO falhou: %s", e)
            return "Vou repassar pro time."

    # re.sub não suporta async replace; fazemos manualmente
    out = reply_text
    # AGENDAR
    while True:
        m = _AGENDAR_RX.search(out)
        if not m:
            break
        replacement = await _replace_agendar(m)
        out = out[:m.start()] + replacement + out[m.end():]
    # CHAMADO
    while True:
        m = _CHAMADO_RX.search(out)
        if not m:
            break
        replacement = await _replace_chamado(m)
        out = out[:m.start()] + replacement + out[m.end():]
    return out.strip(), actions_done


def actions_prompt_block() -> str:
    """Bloco a injetar no system_prompt da Isabella ensinando os marcadores."""
    return """
=== AÇÕES EXECUTÁVEIS NA LOUSA (PRIORIDADE MÁXIMA) ===

Você AGORA pode AGENDAR visitas e ABRIR chamados DIRETAMENTE no sistema.
NÃO peça permissão pro cliente confirmar "vou abrir, ok?". DECIDA com base
no que ele já disse e EXECUTE.

PARA AGENDAR UMA VISITA TÉCNICA:
Emita o marcador no FIM da sua resposta:
  [AGENDAR_VISITA data=YYYY-MM-DD janela=manha motivo="descrição curta"]

Janelas válidas: manha (09h-12h) ou tarde (13h-18h)

Exemplo:
  Cliente: "Pode marcar pra amanhã manhã"
  Sua resposta: "Beleza, amanhã manhã. [AGENDAR_VISITA data=2026-02-11 janela=manha motivo=\"sinal não vinculado\"]"

O sistema vai SUBSTITUIR o marcador por "Marquei pra 11/02 entre 09h-12h
— protocolo TK-ABC123." quando enviar pro cliente. O marcador NUNCA aparece
pro cliente — é executado no servidor.

PARA ABRIR UM CHAMADO (sem data marcada):
  [ABRIR_CHAMADO tipo=tecnico motivo="descrição"]

Tipos válidos: tecnico, comercial, suporte

REGRAS:
1. SEMPRE consulte o bloco "AGENDA DA LOUSA" antes de escolher data/janela
   — nunca ofereça janela LOTADA.
2. NÃO emita marcador se o cliente AINDA NÃO confirmou — só após ele
   dizer "sim" / "pode marcar" / "11/06 manhã".
3. UM marcador por resposta. Se precisar agendar + chamado, faça em 2 turns.
4. NUNCA escreva o marcador como "exemplo" ao cliente — ele só serve
   pro sistema executar.
""".strip()
