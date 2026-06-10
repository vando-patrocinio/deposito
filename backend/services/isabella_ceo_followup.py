"""Isabella CEO Follow-up — registra outcome em ai_evaluations (estrutura existente).

Para cada conversa concluída, grava:
  • resolveu? · vendeu? · reteve? · indicou?
  • gerou_OS? · evitou_OS? (via truck_roll_guard)
  • score atualizado do cliente

Reutiliza ai_evaluations (não cria coleção nova).
"""
from __future__ import annotations
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from database import db


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def register_followup(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    phone: str,
    user_text: str,
    isabella_reply: str,
    context_used: str,
) -> Dict[str, Any]:
    """Classifica o outcome da conversa por heurística do texto da Isabella
    e persiste em ai_evaluations.
    """
    reply_low = (isabella_reply or "").lower()
    user_low = (user_text or "").lower()

    outcomes = {
        "resolveu": bool(re.search(r"\bresolvido\b|\bresolvi\b|pronto\b|tudo certo\b", reply_low)),
        "plano_acao": bool(re.search(r"plano de a[çc][ãa]o\b|vou (verificar|monitorar|acompanhar)", reply_low)),
        "vendeu": bool(re.search(r"contrat(?:ei|amos|ar)\b|vou adicionar\b|cobrarei\b", reply_low)),
        "reteve": bool(re.search(r"continuar com a gente|n[ãa]o cancelar|mantemos seu plano", reply_low)),
        "indicou": bool(re.search(r"indique e ganhe|programa de indica", reply_low)),
        "ofertou": bool(re.search(r"playhub|security|ligo m[óo]vel|wifi premium|ip fixo|upgrade", reply_low)),
        "problema_tecnico": bool(re.search(r"sem internet|caiu|offline|lento|fibra|sinal|onu", user_low)),
        "avisou_proativo": bool(re.search(r"j[áa] estamos|identificamos uma pane|incidente", reply_low)),
    }

    doc = {
        "id": f"eval-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "phone": phone,
        "user_text": user_text[:500],
        "isabella_reply": (isabella_reply or "")[:1000],
        "outcomes": outcomes,
        "context_length": len(context_used or ""),
        "context_blocks": (context_used or "").count("==="),
        "created_at": _now_iso(),
        "ai_attributed": "Isabella",
        "tags": [k for k, v in outcomes.items() if v],
    }
    try:
        await db.ai_evaluations.insert_one(doc)
    except Exception:
        pass

    # Atualiza isabella_opportunities como converted se outbound indica venda
    if outcomes["vendeu"] and subscriber_id:
        try:
            await db.isabella_opportunities.update_many(
                {"company_id": company_id, "subscriber_id": subscriber_id,
                 "status": {"$nin": ["converted", "lost"]}},
                {"$set": {"status": "converted",
                          "converted_at": _now_iso()}})
        except Exception:
            pass

    return doc
