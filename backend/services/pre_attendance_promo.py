"""
pre_attendance_promo.py — Propaganda Pré-Atendimento (iter217a)

Quando um cliente cadastrado fala com a empresa pela 1ª vez em 24h,
o sistema escolhe e dispara a melhor propaganda ANTES do agente
humano/IA assumir a conversa.

Pipeline:
  1. on_inbound() é chamado pelo handler do WhatsApp
  2. Verifica se deve disparar (cliente registrado, fora do cooldown)
  3. Filtra promos elegíveis pelo perfil do subscriber
  4. Se >1 elegível: IA (Motor IA / Claude) escolhe a melhor
     OU fallback determinístico (maior peso)
  5. Envia texto (+ imagem opcional) via sidecar Baileys
  6. Loga em `pre_attendance_dispatches`

Coleções:
  - `pre_attendance_promos`        Catálogo de propagandas
  - `pre_attendance_dispatches`    Histórico (audit + cooldown)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "atendimento",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import logging
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import db

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 24
DEFAULT_FILTER = "all"   # all | active | inactive | inadimplentes | by_plan


# ─────────────────── Helpers ───────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _placeholders(text: str, sub: Dict[str, Any]) -> str:
    """Substitui {nome}, {plano}, {primeiro_nome} no texto."""
    if not text:
        return ""
    nome = (sub.get("name") or "").strip()
    primeiro = nome.split()[0] if nome else ""
    plano = (sub.get("plan_name") or "").strip()
    return (text
              .replace("{nome}", nome or "cliente")
              .replace("{primeiro_nome}", primeiro or "cliente")
              .replace("{plano}", plano or "—"))


def _filter_matches(promo: Dict[str, Any], sub: Dict[str, Any]) -> bool:
    """Verifica se o subscriber se encaixa no alvo da promo."""
    f = (promo.get("target_filter") or DEFAULT_FILTER).lower()
    status = (sub.get("status") or "").upper()
    fin = (sub.get("financial_status") or "").lower()

    if f == "all":
        return True
    if f == "active":
        return status in ("ATIVO", "ATIVA")
    if f == "inactive":
        return status not in ("ATIVO", "ATIVA")
    if f == "inadimplentes":
        return ("inadimp" in fin) or ("atrasad" in fin)
    if f == "by_plan":
        wanted = promo.get("target_plan_ids") or []
        pid = sub.get("plan_id")
        return bool(pid and pid in wanted)
    return True


async def _was_dispatched_recently(cid: str, phone: str,
                                       hours: int = COOLDOWN_HOURS) -> bool:
    if not phone:
        return False
    cutoff = (_now() - timedelta(hours=hours)).isoformat()
    found = await db.pre_attendance_dispatches.find_one(
        {"company_id": cid, "phone": phone,
         "sent_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1},
    )
    return bool(found)


# ─────────────────── AI selection ───────────────────
async def _ai_pick_promo(promos: List[Dict[str, Any]],
                           sub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pede pra Motor IA escolher a promo com maior probabilidade
    de aceite. Em caso de falha, devolve None pra fallback."""
    if len(promos) <= 1:
        return promos[0] if promos else None
    try:
        from services.motor_ia import chat_completion
    except Exception:
        return None

    perfil = (
        f"Nome: {sub.get('name') or '—'}\n"
        f"Plano atual: {sub.get('plan_name') or '—'} "
        f"(R$ {sub.get('plan_price_brl') or 0})\n"
        f"Status: {sub.get('status') or '—'}\n"
        f"Financeiro: {sub.get('financial_status') or '—'}\n"
        f"Cidade: {sub.get('city') or '—'} / "
        f"{sub.get('uf') or '—'}\n"
        f"Tempo de casa: {sub.get('installation_date') or '—'}\n"
    )
    lista = ""
    for i, p in enumerate(promos):
        lista += (
            f"\n[{i}] título='{p.get('title')}' "
            f"peso={p.get('weight', 1)} "
            f"alvo={p.get('target_filter')} "
            f"mensagem='{(p.get('message_text') or '')[:120]}'"
        )
    prompt = (
        "Você é o motor de recomendação do SmartProv. Dado o perfil "
        "do cliente abaixo e a lista de propagandas, escolha O ÍNDICE "
        "(número entre colchetes) da propaganda com MAIOR probabilidade "
        "de receptividade. Considere: status, situação financeira, "
        "plano, e relevância da mensagem. Responda APENAS o número "
        "do índice (ex.: 2). Sem explicações.\n\n"
        f"PERFIL DO CLIENTE:\n{perfil}\n"
        f"PROPAGANDAS DISPONÍVEIS:{lista}\n\n"
        "Resposta (apenas o índice):"
    )
    try:
        out = await chat_completion(
            company_id=sub.get("company_id"),
            messages=[
                {"role": "system",
                 "content": "Recomendador de propagandas. Responda apenas o número do índice."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=20,
            temperature=0.2,
            agent="pre_attendance_promo",
        )
        raw = (out.get("content") or "").strip()
        m = re.search(r"\d+", raw)
        if not m:
            return None
        idx = int(m.group(0))
        if 0 <= idx < len(promos):
            picked = promos[idx]
            picked["_ai_idx"] = idx
            picked["_ai_raw"] = raw
            return picked
    except Exception as e:
        logger.warning("[pre-attendance] AI pick falhou: %s", e)
    return None


def _weighted_pick(promos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fallback: aleatório ponderado pelo `weight` (default 1)."""
    weights = [max(int(p.get("weight") or 1), 1) for p in promos]
    return random.choices(promos, weights=weights, k=1)[0]


# ─────────────────── Sender ───────────────────
async def _send_via_sidecar(phone: str, text: str,
                              image_url: Optional[str]
                              ) -> Dict[str, Any]:
    """Dispara via sidecar Baileys. Se houver imagem, envia como
    documento com mimetype image/*."""
    from services.wa.sidecar import _sidecar_post_silent
    if not image_url:
        return await _sidecar_post_silent(
            "/send", {"phone": phone, "text": text})

    # Baixa imagem e envia como documento (sidecar atual não tem
    # /send-image — usamos send-document com mimetype image/*)
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(image_url, follow_redirects=True)
            r.raise_for_status()
            b64 = base64.b64encode(r.content).decode("ascii")
            mt = r.headers.get("content-type", "image/jpeg").split(";")[0]
        ext = mt.split("/")[-1] or "jpg"
        # Envia documento (imagem como anexo)
        await _sidecar_post_silent("/send-document", {
            "phone": phone, "document_b64": b64,
            "filename": f"propaganda.{ext}",
            "mimetype": mt, "caption": text,
        })
        return {"ok": True, "with_image": True}
    except Exception as e:
        logger.warning("[pre-attendance] download/send img falhou: %s", e)
        # fallback: só texto
        return await _sidecar_post_silent(
            "/send", {"phone": phone, "text": text})


# ─────────────────── Public entry ───────────────────
async def try_dispatch_pre_attendance_promo(
    cid: str, subscriber_id: Optional[str], phone: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Avalia + dispara propaganda. Chamada pelo inbound handler.

    Retorna o dispatch criado, ou None se não foi disparado.
    Sempre safe — engole exceções e loga.
    """
    if not subscriber_id or not phone:
        return None
    try:
        # 1. Cooldown
        if await _was_dispatched_recently(cid, phone):
            return None

        # 2. Carrega subscriber pro filtro/AI
        sub = await db.subscribers.find_one(
            {"id": subscriber_id},
            {"_id": 0, "id": 1, "name": 1, "plan_id": 1, "plan_name": 1,
             "plan_price_brl": 1, "status": 1, "financial_status": 1,
             "city": 1, "uf": 1, "installation_date": 1,
             "company_id": 1},
        )
        if not sub:
            return None
        sub.setdefault("company_id", cid)

        # 3. Propagandas ativas elegíveis
        cur = db.pre_attendance_promos.find(
            {"company_id": cid, "active": True},
            {"_id": 0},
        )
        all_promos = await cur.to_list(200)
        elig = [p for p in all_promos if _filter_matches(p, sub)]
        if not elig:
            return None

        # 4. Seleção (IA quando houver ai_enabled em qualquer
        # promo, OU >1 promos. Caso contrário fallback ponderado)
        use_ai = any(p.get("ai_enabled") for p in elig) and len(elig) > 1
        picked = None
        ai_idx = None
        ai_raw = None
        if use_ai:
            picked = await _ai_pick_promo(elig, sub)
            if picked:
                ai_idx = picked.get("_ai_idx")
                ai_raw = picked.get("_ai_raw")
        if not picked:
            picked = _weighted_pick(elig)

        # 5. Substitui placeholders e envia
        msg = _placeholders(picked.get("message_text") or "", sub)
        if not msg.strip() and not picked.get("image_url"):
            return None

        send_res = await _send_via_sidecar(
            phone, msg, picked.get("image_url"))

        # 6. Loga dispatch + bump stats
        dispatch = {
            "id": f"pad-{uuid.uuid4().hex[:14]}",
            "company_id": cid,
            "subscriber_id": subscriber_id,
            "phone": phone,
            "promo_id": picked.get("id"),
            "promo_title": picked.get("title"),
            "sent_at": _now_iso(),
            "ai_picked": bool(use_ai and ai_idx is not None),
            "ai_idx": ai_idx,
            "ai_raw": ai_raw,
            "ok": bool(send_res.get("ok")),
            "error": send_res.get("error"),
            "with_image": bool(picked.get("image_url")),
            "replied": False,
        }
        await db.pre_attendance_dispatches.insert_one(dict(dispatch))
        await db.pre_attendance_promos.update_one(
            {"id": picked["id"]},
            {"$inc": {"stats_sent": 1},
             "$set": {"last_sent_at": _now_iso()}})
        logger.info("[pre-attendance] dispatched promo=%s to %s "
                     "(ai=%s)", picked.get("title"), phone, use_ai)
        return dispatch
    except Exception as e:
        logger.error("[pre-attendance] dispatch falhou: %s", e,
                       exc_info=True)
        return None


async def mark_reply(cid: str, phone: str) -> None:
    """Marca o último dispatch desse phone como 'replied'.
    Chamado quando vem mensagem do cliente após o disparo —
    serve pra métrica de receptividade."""
    if not phone:
        return
    try:
        cutoff = (_now() - timedelta(hours=COOLDOWN_HOURS)).isoformat()
        d = await db.pre_attendance_dispatches.find_one(
            {"company_id": cid, "phone": phone,
             "sent_at": {"$gte": cutoff}, "replied": False},
            {"_id": 0, "id": 1, "promo_id": 1},
            sort=[("sent_at", -1)],
        )
        if not d:
            return
        await db.pre_attendance_dispatches.update_one(
            {"id": d["id"]},
            {"$set": {"replied": True, "replied_at": _now_iso()}})
        if d.get("promo_id"):
            await db.pre_attendance_promos.update_one(
                {"id": d["promo_id"]},
                {"$inc": {"stats_replied": 1}})
    except Exception as e:
        logger.warning("[pre-attendance] mark_reply falhou: %s", e)
