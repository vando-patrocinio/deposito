"""Co-Pilot Ranking — quem aplica as dicas e quem tira proveito.

Mede, por atendente humano, nas últimas N dias:
- hints_received: quantas dicas o Co-Pilot enviou em conversas que ele tinha
- hints_applied: quantas dicas viraram uma resposta outbound do atendente
  dentro de uma janela (default 30 min) depois da dica — sinal de adoção
- application_rate: hints_applied / hints_received
- csat_with_hints: média CSAT das conversas onde teve hint+aplicou
- csat_without_hints: média CSAT das conversas sem hint (mesmas datas)
- delta_csat: with - without (positivo = dica ajuda)
- score: composto 0-100 (40% application_rate + 35% delta_csat + 25% volume)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db

router = APIRouter(prefix="/api/copilot-ranking", tags=["copilot-ranking"])

APPLY_WINDOW_MIN = 30   # janela pós-dica pra considerar "aplicada"


def _iso_to_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _composite_score(application_rate: float, delta_csat: float,
                       hints_received: int, max_hints: int) -> float:
    """Score 0-100. Premia adesão, ganho de CSAT, e volume relativo."""
    application_score = min(1.0, application_rate) * 40
    # delta_csat varia de -10 (terrível) a +10 (excelente); normaliza
    delta_norm = max(-1.0, min(1.0, delta_csat / 4.0))  # +4 já é teto
    delta_score = ((delta_norm + 1) / 2) * 35   # 0..35 (-1 → 0, +1 → 35)
    volume_score = (hints_received / max_hints) * 25 if max_hints else 0
    return round(application_score + delta_score + volume_score, 1)


@router.get("/weekly")
async def weekly_ranking(days: int = Query(7, ge=1, le=30),
                            user: dict = Depends(require_role("gestor"))) -> Dict[str, Any]:
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()

    # 1. Carrega todas as hints do período + telefone + horário
    hints: List[Dict[str, Any]] = await db.aihub_wa_messages.find(
        {"company_id": cid, "direction": "internal",
         "internal_kind": "copilot_hint",
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "phone": 1, "created_at": 1},
    ).to_list(5000)

    # 2. Para cada hint, descobrir qual usuário tinha a conversa naquele momento
    # Como wa_conversations só mantém o assignee atual, usamos:
    # - assignee_user_id da conversa (snapshot atual) — aproximação aceitável
    phones_unique = list({h["phone"] for h in hints if h.get("phone")})
    convs_map: Dict[str, str] = {}
    if phones_unique:
        async for c in db.wa_conversations.find(
            {"company_id": cid, "phone": {"$in": phones_unique},
             "assignee_user_id": {"$nin": [None, ""]}},
            {"_id": 0, "phone": 1, "assignee_user_id": 1},
        ):
            convs_map[c["phone"]] = c["assignee_user_id"]

    # 3. Para cada hint, busca primeiro outbound humano após o hint na mesma conversa
    # Otimização: agrega outbounds por phone uma vez
    out_by_phone: Dict[str, List[Dict[str, Any]]] = {}
    if phones_unique:
        async for m in db.aihub_wa_messages.find(
            {"company_id": cid, "phone": {"$in": phones_unique},
             "direction": "outbound", "auto_reply": {"$ne": True},
             "sent_by_user_id": {"$nin": [None, ""]},
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "phone": 1, "created_at": 1, "sent_by_user_id": 1},
        ):
            out_by_phone.setdefault(m["phone"], []).append(m)
        for ph in out_by_phone:
            out_by_phone[ph].sort(key=lambda x: x["created_at"])

    # Por usuário, agrega hints_received e hints_applied
    per_user: Dict[str, Dict[str, Any]] = {}
    for h in hints:
        ph = h.get("phone")
        uid = convs_map.get(ph)
        if not uid:
            continue
        u = per_user.setdefault(uid, {
            "user_id": uid, "hints_received": 0, "hints_applied": 0,
            "applied_phones": set(), "phones_with_hint": set(),
        })
        u["hints_received"] += 1
        u["phones_with_hint"].add(ph)
        # Aplicou?
        h_dt = _iso_to_dt(h.get("created_at"))
        if not h_dt:
            continue
        candidates = out_by_phone.get(ph) or []
        for o in candidates:
            o_dt = _iso_to_dt(o.get("created_at"))
            if not o_dt:
                continue
            if o_dt < h_dt:
                continue
            if o.get("sent_by_user_id") != uid:
                continue
            if (o_dt - h_dt).total_seconds() <= APPLY_WINDOW_MIN * 60:
                u["hints_applied"] += 1
                u["applied_phones"].add(ph)
            break

    # 4. CSAT média por usuário (com vs sem hint)
    # Conversas com hint: phones_with_hint
    # Conversas sem hint do mesmo período: precisa lookup
    user_ids_active = list(per_user.keys())
    # CSAT por (user, phone) — todas avaliações do período
    evals: Dict[str, List[Dict[str, Any]]] = {}
    async for ev in db.aihub_evaluations.find(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff},
         "csat_score": {"$ne": None}},
        {"_id": 0, "phone": 1, "csat_score": 1, "assignee_user_id": 1},
    ):
        uid = ev.get("assignee_user_id")
        if uid:
            evals.setdefault(uid, []).append(ev)

    for uid, u in per_user.items():
        ws: List[float] = []
        wos: List[float] = []
        for ev in evals.get(uid, []):
            ph = ev.get("phone")
            score = ev.get("csat_score")
            if score is None:
                continue
            if ph in u["applied_phones"]:
                ws.append(score)
            else:
                wos.append(score)
        u["csat_with_hints"] = round(mean(ws), 2) if ws else None
        u["csat_without_hints"] = round(mean(wos), 2) if wos else None
        if u["csat_with_hints"] is not None and u["csat_without_hints"] is not None:
            u["delta_csat"] = round(u["csat_with_hints"] - u["csat_without_hints"], 2)
        else:
            u["delta_csat"] = None
        # converte sets pra contagens (não-JSON-serializable)
        u["unique_phones_with_hint"] = len(u.pop("phones_with_hint"))
        u["unique_phones_applied"] = len(u.pop("applied_phones"))

    # 5. Score composto
    max_hints = max((u["hints_received"] for u in per_user.values()), default=0)
    rows: List[Dict[str, Any]] = []
    for uid, u in per_user.items():
        application_rate = (u["hints_applied"] / u["hints_received"]
                              if u["hints_received"] else 0)
        delta = u["delta_csat"] or 0
        u["application_rate"] = round(application_rate, 3)
        u["score"] = _composite_score(application_rate, delta,
                                          u["hints_received"], max_hints)
        rows.append(u)

    # 6. Hidrata nome/email
    users_map: Dict[str, Dict[str, Any]] = {}
    if user_ids_active:
        async for u in db.users.find(
            {"id": {"$in": user_ids_active}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "avatar_url": 1,
             "google_picture": 1, "is_ai_agent": 1},
        ):
            users_map[u["id"]] = u
    for r in rows:
        u = users_map.get(r["user_id"]) or {}
        if u.get("is_ai_agent"):
            continue
        r["name"] = u.get("name") or u.get("email") or r["user_id"]
        r["email"] = u.get("email")
        r["avatar"] = u.get("avatar_url") or u.get("google_picture")

    rows = [r for r in rows if r.get("name")]
    rows.sort(key=lambda x: (-x["score"], -x["hints_received"]))

    return {
        "items": rows,
        "count": len(rows),
        "days": days,
        "apply_window_minutes": APPLY_WINDOW_MIN,
        "totals": {
            "hints_received": sum(r["hints_received"] for r in rows),
            "hints_applied": sum(r["hints_applied"] for r in rows),
            "avg_application_rate": (
                round(mean([r["application_rate"] for r in rows]), 3)
                if rows else 0
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
