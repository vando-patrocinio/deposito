"""Programa de Indicações ("Indique e Ganhe") com gamificação.

Modelo de negócio:
- Cada assinante ATIVO ganha um `referral_code` único (gerado on-demand).
- O assinante compartilha o link `/r/{code}` com amigos via WhatsApp.
- Amigo abre o link → preenche nome + WhatsApp → vira lead na collection
  `sales_leads` (source="referral") e dispara mensagem WhatsApp automática
  via Isabella IA pra conversão imediata.
- Quando o lead vira subscriber e atinge status "INSTALADO" / "ATIVO":
    • Cria registro em `referral_rewards` com R$ 50 disponível
    • Atualiza `referrals.status` = "installed"
- Cliente acessa app mobile (`/cliente`) — login por CPF — vê:
    • Lista de indicações + status
    • Saldo disponível (rewards.status=available)
    • Botão "Solicitar PIX/desconto" (gera `referral_payouts` p/ aprovação)
    • Gamificação: tiers 5, 10, 20, 30 instalações

Collections:
- `referrals`: link → friend record (1 row por amigo indicado)
- `referral_rewards`: 1 row por reward creditado (R$ 50)
- `referral_payouts`: pedidos de pagamento (PIX ou desconto fatura)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "growth-team",
    "domain": "indicacoes",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["subscriber.updated"],
    "company_id_required": True,
}

import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from services.rate_limit import limiter, get_limit
from database import db

logger = logging.getLogger("ponto.referrals")
router = APIRouter(prefix="/api", tags=["referrals"])


# --------------------------------------------------------------------------- #
# Constants / Tiers de gamificação
# --------------------------------------------------------------------------- #
REWARD_PER_INSTALL_BRL = 50.0
# Meta de incentivo: 30 instalações = R$ 500 extras (bonus)
GOAL_TARGET_INSTALLS = 30
GOAL_BONUS_BRL = 500.0
# Bônus de 2º nível: quando um amigo-de-amigo (lead indicado pelo seu
# próprio indicado) instala, o "indicador-avô" ganha R$ 10 extra.
LEVEL2_REWARD_BRL = 10.0
# Bônus por streak: 4 semanas consecutivas com pelo menos 1 instalação.
STREAK_BONUS_BRL = 25.0
STREAK_TARGET_WEEKS = 4
TIERS = [
    {"level": 1, "min_installs": 5,  "label": "Bronze",   "prize": "Brinde Bronze (caneca, mochila ou kit Ligo)"},
    {"level": 2, "min_installs": 10, "label": "Prata",    "prize": "Brinde Prata (kit gourmet ou voucher R$ 100)"},
    {"level": 3, "min_installs": 20, "label": "Ouro",     "prize": "Brinde Ouro (TV 32\" ou voucher R$ 300)"},
    {"level": 4, "min_installs": 30, "label": "Diamante", "prize": "Concorre ao prêmio Diamante (smartphone ou viagem)"},
]


def _norm_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return None
    if not digits.startswith("55") and 10 <= len(digits) <= 11:
        digits = "55" + digits
    if not (12 <= len(digits) <= 13):
        return None
    return digits


def _norm_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", str(cpf or ""))


def _is_valid_cpf(cpf_digits: str) -> bool:
    """Valida dígitos verificadores de CPF (mod 11).

    Rejeita CPFs com todos os dígitos iguais (000.., 111.., etc — placeholders
    comuns em bancos sujos).
    """
    if len(cpf_digits) != 11 or not cpf_digits.isdigit():
        return False
    if len(set(cpf_digits)) == 1:
        return False
    # 1º DV
    s = sum(int(cpf_digits[i]) * (10 - i) for i in range(9))
    dv1 = (s * 10) % 11
    if dv1 == 10:
        dv1 = 0
    if dv1 != int(cpf_digits[9]):
        return False
    # 2º DV
    s = sum(int(cpf_digits[i]) * (11 - i) for i in range(10))
    dv2 = (s * 10) % 11
    if dv2 == 10:
        dv2 = 0
    return dv2 == int(cpf_digits[10])


def _is_valid_cnpj(cnpj_digits: str) -> bool:
    """Valida dígitos verificadores de CNPJ (mod 11)."""
    if len(cnpj_digits) != 14 or not cnpj_digits.isdigit():
        return False
    if len(set(cnpj_digits)) == 1:
        return False
    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_2 = [6] + weights_1
    s1 = sum(int(cnpj_digits[i]) * weights_1[i] for i in range(12))
    dv1 = s1 % 11
    dv1 = 0 if dv1 < 2 else 11 - dv1
    if dv1 != int(cnpj_digits[12]):
        return False
    s2 = sum(int(cnpj_digits[i]) * weights_2[i] for i in range(13))
    dv2 = s2 % 11
    dv2 = 0 if dv2 < 2 else 11 - dv2
    return dv2 == int(cnpj_digits[13])


def _gen_code(length: int = 8) -> str:
    """Código curto, fácil de digitar — base32-like sem ambíguos (0/O/1/I)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class FriendSubmit(BaseModel):
    friend_name: str = Field(..., min_length=2, max_length=120)
    friend_phone: str = Field(..., min_length=10, max_length=20)
    friend_neighborhood: Optional[str] = Field(None, max_length=120)


class CustomerLogin(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=14)


class PixKeyUpdate(BaseModel):
    pix_key: str = Field(..., min_length=4, max_length=120)
    pix_key_type: str = Field(..., pattern="^(cpf|cnpj|email|phone|aleatoria)$")


class PayoutRequest(BaseModel):
    method: str = Field(..., pattern="^(pix|invoice_discount)$")
    amount: float = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=300)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _get_or_create_referral_code(cid: str, subscriber_id: str) -> str:
    """Idempotente — devolve `referral_code` do subscriber ou gera um novo."""
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid},
        {"_id": 0, "referral_code": 1},
    )
    if sub and sub.get("referral_code"):
        return sub["referral_code"]
    # Gera código único (até 10 tentativas)
    for _ in range(10):
        code = _gen_code()
        # Verifica unicidade em ambas as coleções (subscribers + collaborators)
        exists_sub = await db.subscribers.find_one(
            {"referral_code": code}, {"_id": 1},
        )
        exists_col = await db.collaborators.find_one(
            {"referral_code": code}, {"_id": 1},
        )
        if not exists_sub and not exists_col:
            await db.subscribers.update_one(
                {"id": subscriber_id, "company_id": cid},
                {"$set": {"referral_code": code, "updated_at": now_iso()}},
            )
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "subscriber.updated",
                    company_id=cid,
                    source="referrals",
                    payload={},
                )
            except Exception:
                pass
            return code
    raise HTTPException(500, "Falha ao gerar código de indicação único")


async def _get_or_create_collab_referral_code(cid: str, collab_id: str) -> str:
    """Idempotente — devolve `referral_code` do colaborador ou gera um novo.
    Mesma pool de códigos dos subscribers — checa unicidade em ambas as collections."""
    col = await db.collaborators.find_one(
        {"id": collab_id, "company_id": cid},
        {"_id": 0, "referral_code": 1},
    )
    if col and col.get("referral_code"):
        return col["referral_code"]
    for _ in range(10):
        code = _gen_code()
        exists_sub = await db.subscribers.find_one(
            {"referral_code": code}, {"_id": 1},
        )
        exists_col = await db.collaborators.find_one(
            {"referral_code": code}, {"_id": 1},
        )
        if not exists_sub and not exists_col:
            await db.collaborators.update_one(
                {"id": collab_id, "company_id": cid},
                {"$set": {"referral_code": code, "updated_at": now_iso()}},
            )
            return code
    raise HTTPException(500, "Falha ao gerar código de indicação único")


async def _send_isabella_to_friend(cid: str, owner_first_name: str,
                                     friend_phone: str, friend_name: str,
                                     lead_id: str) -> None:
    """Dispara mensagem Isabella imediatamente — conversão de imediato."""
    from services.wa.sidecar import _sidecar_post_silent_at
    from services.whatsapp_channels import (
        base_url_for, get_default_outbound_channel,
    )
    try:
        ch_id = await get_default_outbound_channel(db, cid)
    except Exception:
        ch_id = "channel-1"
    base_url = base_url_for(ch_id)

    first_friend = (friend_name or "").split()[0].title() or "tudo bem"
    text = (
        f"Oi {first_friend}! 👋 Aqui é a *Isabella* da Ligo Fibra.\n\n"
        f"O(a) *{owner_first_name}* te indicou pra nossa promoção de internet "
        f"de verdade — fibra óptica direto na tua casa, sem fidelidade, com "
        f"instalação rápida e Wi-Fi forte até na laje.\n\n"
        f"Quando você instalar, eu mesma aviso o(a) {owner_first_name} pra "
        f"vocês comemorarem juntos 🤗 — e ele(a) ainda ganha *R$ 50* no PIX "
        f"como agradecimento.\n\n"
        f"Posso te passar os planos disponíveis na sua região? 🚀"
    )
    try:
        await _sidecar_post_silent_at(
            base_url, "/send", {"phone": friend_phone, "text": text},
            timeout=20.0,
        )
        # Persiste outbound + reset session pra Isabella começar do zero
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": friend_phone,
            "text": text,
            "channel": "baileys",
            "channel_id": ch_id,
            "agent_name": "Isabella",
            "auto_reply": True,
            "delivery_status": "sent",
            "metadata": {
                "source": "referral_program",
                "lead_id": lead_id,
                "referrer_first_name": owner_first_name,
            },
            "created_at": now_iso(),
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=cid,
                source="referrals",
                payload={},
            )
        except Exception:
            pass
        # Atualiza routed_agent_id pra Isabella já dominar a conversa
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": friend_phone},
            {"$set": {
                "routed_agent_id": "isabella",
                "last_channel_id": ch_id,
                "updated_at": now_iso(),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning("[referrals] send-isabella failed: %s", e)


async def _compute_stats(cid: str, subscriber_id: str) -> Dict[str, Any]:
    """Computa KPIs do subscriber pra exibir no app do cliente."""
    pipeline = [
        {"$match": {"owner_subscriber_id": subscriber_id, "company_id": cid}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
        }},
    ]
    by_status: Dict[str, int] = {}
    async for row in db.referrals.aggregate(pipeline):
        by_status[row["_id"]] = row["count"]
    total_indicated = sum(by_status.values())
    installed = by_status.get("installed", 0)
    contracted = by_status.get("contracted", 0)
    contacted = by_status.get("contacted", 0) + by_status.get("converting", 0)

    # Rewards agg
    rew_pipeline = [
        {"$match": {"owner_subscriber_id": subscriber_id, "company_id": cid}},
        {"$group": {
            "_id": "$status",
            "total": {"$sum": "$amount"},
            "count": {"$sum": 1},
        }},
    ]
    earned_total = 0.0
    available = 0.0
    paid_out = 0.0
    pending = 0.0
    async for row in db.referral_rewards.aggregate(rew_pipeline):
        st = row["_id"]
        if st == "available":
            available = float(row["total"])
        elif st == "paid":
            paid_out = float(row["total"])
        elif st == "pending_approval":
            pending = float(row["total"])
        earned_total += float(row["total"])

    # Tier atual: maior tier cuja barrier `min_installs` foi atingida
    current_tier = None
    next_tier = None
    for t in TIERS:
        if installed >= t["min_installs"]:
            current_tier = t
        elif next_tier is None:
            next_tier = t
    return {
        "total_indicated": total_indicated,
        "installed": installed,
        "contracted": contracted,
        "in_progress": contacted,
        "conversion_pct": round((installed / total_indicated * 100) if total_indicated else 0, 1),
        "earned_total_brl": earned_total,
        "available_brl": available,
        "paid_out_brl": paid_out,
        "pending_brl": pending,
        "by_status": by_status,
        "current_tier": current_tier,
        "next_tier": next_tier,
        "tiers": TIERS,
        "missing_for_next": (next_tier["min_installs"] - installed) if next_tier else 0,
    }


def _motivation_for(stats: Dict[str, Any], first_name: str) -> str:
    """Frase motivacional contextual — sextas/sábados/domingos puxam mais forte."""
    weekday = datetime.now(timezone.utc).weekday()  # 0=seg, 6=dom
    is_weekend = weekday in (4, 5, 6)
    installed = stats.get("installed", 0)
    missing = stats.get("missing_for_next") or 0
    next_t = stats.get("next_tier")
    if installed == 0:
        if is_weekend:
            return (f"🚀 {first_name}, fim de semana é a hora! Cada amigo que "
                    f"instalar te garante R$ 50 no PIX. Bora começar?")
        return (f"Olá {first_name}! Indique 1 amigo agora e ganhe R$ 50 quando "
                f"ele instalar. Compartilhe seu link já!")
    if missing == 1 and next_t:
        return (f"🔥 Falta SÓ 1 instalação pra você virar nível {next_t['label']} "
                f"e ganhar {next_t['prize']}!")
    if is_weekend and stats.get("available_brl", 0) > 0:
        return (f"💸 {first_name}, você tem R$ {stats['available_brl']:.2f} "
                f"disponível pra sacar no PIX! Indique mais 1 e adicione "
                f"R$ 50 ao seu saldo.")
    if next_t:
        return (f"Você está a {missing} instalação(ões) do nível "
                f"{next_t['label']} ({next_t['prize']}). Continua firme! 💪")
    return (f"🏆 Parabéns {first_name}! Você atingiu o nível máximo. "
            f"Cada nova indicação ainda te dá R$ 50 no PIX.")


def _app_link_for_cid(cid: str) -> str:
    """URL pública do app do cliente. Usa env quando disponível."""
    import os
    base = os.environ.get("PUBLIC_APP_URL") or os.environ.get("CORS_ORIGINS", "")
    if base and "," in base:
        base = base.split(",")[0].strip()
    if not base or not base.startswith("http"):
        base = "https://app.ligo.fibra"
    return f"{base.rstrip('/')}/cliente"


def _customer_token(subscriber_id: str) -> str:
    """Token simples assinado por uuid — não é JWT, é só um ID opaco
    re-derivável (subscriber_id em base32 + 12 bytes secret)."""
    salt = secrets.token_urlsafe(16)
    return f"{subscriber_id}.{salt}"


def _decode_customer_token(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    sub_id, _salt = token.split(".", 1)
    return sub_id or None


async def _require_customer(request: Request) -> Dict[str, Any]:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Token ausente")
    token = auth.split(" ", 1)[1]
    sub_id = _decode_customer_token(token)
    if not sub_id:
        raise HTTPException(401, "Token inválido")
    sub = await db.subscribers.find_one(
        {"id": sub_id}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(401, "Assinante não encontrado")
    return sub


@router.get("/referrals/assets/{slug}.png")
async def public_asset(slug: str):
    """Serve uma imagem do programa Indique e Ganhe (estático, pública)."""
    from fastapi.responses import FileResponse, Response
    from services.referral_imagegen import (
        asset_path, has_asset, generate_slot, IMAGE_SLOTS,
    )
    if slug not in IMAGE_SLOTS:
        raise HTTPException(404, "Slug desconhecido")
    if not has_asset(slug):
        # Lazy generation no primeiro request
        r = await generate_slot(slug)
        if not r.get("ok"):
            # Devolve 204 (placeholder client) em vez de 500
            return Response(status_code=204)
    return FileResponse(
        asset_path(slug), media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/referrals/admin/regenerate-assets")
async def admin_regenerate_assets(
    force: bool = False,
    user=Depends(require_role("administrador", "gestor")),
):
    """Gera/regenera todas as ilustrações Ligo Fibra do programa.

    Use ?force=true pra forçar regenerar mesmo se já existem.
    """
    from services.referral_imagegen import (
        ensure_all_assets, generate_slot, IMAGE_SLOTS,
    )
    if force:
        # gera 1 por 1 com force (paralelo a 4 imagens não vale a pena)
        results = {}
        for s in IMAGE_SLOTS:
            results[s] = await generate_slot(s, force=True)
        return results
    return await ensure_all_assets()


@router.get("/referrals/assets/milestone/{subscriber_id}/{tier_level}.png")
async def public_milestone(subscriber_id: str, tier_level: int):
    """Card de milestone personalizado pra compartilhar nas redes sociais.

    Idempotente: 1 imagem por (subscriber_id, tier_level) — gerada no 1º
    request e cacheada.
    """
    from fastapi.responses import FileResponse, Response
    from services.referral_imagegen import (
        milestone_path, has_milestone, generate_milestone_card,
        MILESTONE_PROMPTS,
    )
    if tier_level not in MILESTONE_PROMPTS:
        raise HTTPException(404, "Tier inválido")
    sub = await db.subscribers.find_one(
        {"id": subscriber_id}, {"_id": 0, "name": 1, "company_id": 1},
    )
    if not sub:
        raise HTTPException(404, "Cliente não encontrado")
    first = (sub.get("name") or "").split()[0].title() or "Cliente"
    if not has_milestone(subscriber_id, tier_level):
        r = await generate_milestone_card(subscriber_id, tier_level, first)
        if not r.get("ok"):
            return Response(status_code=204)
    return FileResponse(
        milestone_path(subscriber_id, tier_level), media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/customer/milestone-cards")
async def customer_milestone_cards(customer=Depends(_require_customer)):
    """Retorna os tiers conquistados pelo cliente + share URLs."""
    cid = customer["company_id"]
    installs = await db.referrals.count_documents({
        "company_id": cid, "owner_subscriber_id": customer["id"],
        "status": "installed",
    })
    cards = []
    for t in TIERS:
        achieved = installs >= t["min_installs"]
        first = (customer.get("name") or "").split()[0].title()
        share_text = (
            f"🎉 {first} conquistou nível {t['label']} no Indique e Ganhe da "
            f"Ligo Fibra com {t['min_installs']} instalações indicadas! "
            f"💸 Vem indicar também: "
        )
        cards.append({
            "tier_level": t["level"],
            "label": t["label"],
            "min_installs": t["min_installs"],
            "prize": t["prize"],
            "achieved": achieved,
            "image_url": (
                f"/api/referrals/assets/milestone/"
                f"{customer['id']}/{t['level']}.png"
            ) if achieved else None,
            "share_text": share_text if achieved else None,
            "share_link": (
                f"/r/{customer.get('referral_code','')}"
            ) if achieved else None,
        })
    return {"cards": cards, "installs": installs}


# --------------------------------------------------------------------------- #
# Endpoints públicos (sem auth) — landing page do amigo
# --------------------------------------------------------------------------- #
@router.get("/referrals/collab/public/{collab_id}")
async def public_collab_referral(collab_id: str, request: Request):
    """Endpoint público (sem JWT) consumido pelo app PWA do colaborador.
    Retorna o código de indicação dele + URL de compartilhamento + stats."""
    col = await db.collaborators.find_one(
        {"id": collab_id},
        {"_id": 0, "company_id": 1, "name": 1, "id": 1, "referral_code": 1},
    )
    if not col:
        raise HTTPException(404, "Colaborador não encontrado")
    cid = col.get("company_id")
    code = await _get_or_create_collab_referral_code(cid, collab_id)

    # Stats: indicações feitas por este colaborador
    cur = db.referrals.find(
        {"company_id": cid, "owner_subscriber_id": collab_id,
          "owner_type": "collaborator"},
        {"_id": 0, "id": 1, "status": 1, "reward_status": 1,
          "friend_name": 1, "created_at": 1, "installed_at": 1},
    ).sort("created_at", -1).limit(20)
    items: List[Dict[str, Any]] = []
    total = 0
    installed = 0
    async for r in cur:
        total += 1
        if r.get("status") == "installed":
            installed += 1
        items.append({
            "id": r.get("id"),
            "friend_name": r.get("friend_name"),
            "status": r.get("status"),
            "reward_status": r.get("reward_status"),
            "created_at": r.get("created_at"),
            "installed_at": r.get("installed_at"),
        })

    # Saldo (R$ creditados, pendentes, pagos) — usa mesmo schema dos subscribers
    available = 0.0
    pending = 0.0
    paid = 0.0
    async for rew in db.referral_rewards.find(
        {"company_id": cid, "owner_subscriber_id": collab_id},
        {"_id": 0, "status": 1, "amount": 1},
    ):
        amt = float(rew.get("amount") or 0)
        st = rew.get("status")
        if st == "available":
            available += amt
        elif st == "pending_approval":
            pending += amt
        elif st == "paid":
            paid += amt

    # URL de compartilhamento (Origin do request)
    origin = str(request.base_url).rstrip("/")
    share_url = f"{origin}/r/{code}"

    # Ranking GLOBAL: posição entre todos que já tiveram >= 1 instalação
    # (mistura subscribers + collaborators — mesmo pool de owner_subscriber_id).
    # Tiebreak: mais instalações desempata; depois mais cedo (created_at).
    pipe = [
        {"$match": {"company_id": cid, "status": "installed"}},
        {"$group": {"_id": "$owner_subscriber_id",
                     "installs": {"$sum": 1},
                     "first_at": {"$min": "$installed_at"}}},
        {"$sort": {"installs": -1, "first_at": 1}},
    ]
    ranking_position: Optional[int] = None
    ranking_total = 0
    pos = 0
    async for row in db.referrals.aggregate(pipe):
        pos += 1
        ranking_total += 1
        if row["_id"] == collab_id:
            ranking_position = pos

    return {
        "code": code,
        "share_url": share_url,
        "owner_first_name": (col.get("name") or "").split()[0].title(),
        "stats": {
            "total": total,
            "installed": installed,
            "available_brl": round(available, 2),
            "pending_brl": round(pending, 2),
            "paid_brl": round(paid, 2),
        },
        "ranking": {
            "position": ranking_position,
            "total_referrers": ranking_total,
        },
        "goal": {
            "target_installs": GOAL_TARGET_INSTALLS,
            "current_installs": installed,
            "remaining": max(0, GOAL_TARGET_INSTALLS - installed),
            "bonus_brl": GOAL_BONUS_BRL,
            "pct": min(100, round((installed / GOAL_TARGET_INSTALLS) * 100, 1))
                    if GOAL_TARGET_INSTALLS else 0,
            "reached": installed >= GOAL_TARGET_INSTALLS,
        },
        "recent": items,
        "reward_per_install_brl": REWARD_PER_INSTALL_BRL,
    }


@router.get("/r/{code}/info")
async def public_referral_info(code: str):
    """Info do indicador pra renderizar o hero da landing.
    Busca primeiro em subscribers; se não achar, busca em collaborators
    (técnicos com Indique e Ganhe ativo via app)."""
    code = (code or "").strip().upper()
    sub = await db.subscribers.find_one(
        {"referral_code": code}, {"_id": 0, "name": 1, "company_id": 1, "id": 1},
    )
    if sub:
        first = (sub.get("name") or "").split()[0].title()
        return {
            "code": code,
            "owner_first_name": first,
            "owner_type": "subscriber",
            "company_name": "Ligo Fibra",
        }
    col = await db.collaborators.find_one(
        {"referral_code": code}, {"_id": 0, "name": 1, "company_id": 1, "id": 1},
    )
    if col:
        first = (col.get("name") or "").split()[0].title()
        return {
            "code": code,
            "owner_first_name": first,
            "owner_type": "collaborator",
            "company_name": "Ligo Fibra",
        }
    raise HTTPException(404, "Código de indicação inválido")


@router.get("/referrals/public/mural")
async def public_referral_mural() -> Dict[str, Any]:
    """KPIs públicos pra tela de login do App do Cliente — sem auth.

    Retorna números agregados (anonimizados) para social proof / motivação:
      - total_paid_brl: tudo já creditado (available + pending + paid)
      - total_referrers: indicadores ativos (com >=1 reward)
      - installs_month: instalações no mês corrente
      - paid_month_brl: total creditado no mês
      - top3_masked: top 3 indicadores anonimizados do mês
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0,
                                 microsecond=0).isoformat()

    # Total geral pago/disponível (todas as empresas — single-tenant Ligo em prod)
    pipe_total = [
        {"$match": {"status": {"$in": ["available", "pending_approval", "paid"]}}},
        {"$group": {"_id": None,
                     "total_brl": {"$sum": "$amount"},
                     "cnt": {"$sum": 1}}},
    ]
    total_doc = None
    async for r in db.referral_rewards.aggregate(pipe_total):
        total_doc = r
    total_paid = float((total_doc or {}).get("total_brl", 0))
    total_rewards_count = int((total_doc or {}).get("cnt", 0))

    # Indicadores únicos (já ganharam pelo menos 1 reward)
    referrers = await db.referral_rewards.distinct("owner_subscriber_id")
    total_referrers = len(referrers)

    # Mês corrente
    pipe_month = [
        {"$match": {"status": {"$in": ["available", "pending_approval", "paid"]},
                     "created_at": {"$gte": month_start}}},
        {"$group": {"_id": "$owner_subscriber_id",
                     "total_brl": {"$sum": "$amount"},
                     "cnt": {"$sum": 1}}},
    ]
    month_owners: List[Dict[str, Any]] = []
    async for row in db.referral_rewards.aggregate(pipe_month):
        month_owners.append({
            "owner": row["_id"],
            "total_brl": float(row["total_brl"]),
            "count": int(row["cnt"]),
        })
    paid_month = sum(r["total_brl"] for r in month_owners)
    installs_month = sum(r["count"] for r in month_owners)

    # Top 3 do mês anonimizados
    top = sorted(month_owners, key=lambda r: r["total_brl"], reverse=True)[:3]
    top3: List[Dict[str, Any]] = []
    for idx, t in enumerate(top, 1):
        sub = await db.subscribers.find_one(
            {"id": t["owner"]}, {"_id": 0, "name": 1},
        )
        name = ((sub or {}).get("name") or "Cliente Ligo").strip()
        first = name.split()[0] if name else "Cliente"
        anon = (first[0] + "***" + first[-1]) if len(first) > 2 else first
        top3.append({
            "rank": idx,
            "name_masked": anon,
            "installs": t["count"],
            "total_brl": t["total_brl"],
        })

    return {
        "total_paid_brl": total_paid,
        "total_referrers": total_referrers,
        "total_rewards_count": total_rewards_count,
        "installs_month": installs_month,
        "paid_month_brl": paid_month,
        "top3_masked": top3,
        "month_label": now.strftime("%m/%Y"),
        "reward_per_install_brl": 50.0,
    }



@router.post("/r/{code}/submit")
async def public_referral_submit(code: str, payload: FriendSubmit):
    """Amigo submete dados → cria lead + dispara Isabella imediatamente.
    Resolve owner em subscribers OU collaborators (Indique e Ganhe técnico)."""
    code = (code or "").strip().upper()
    owner_type = "subscriber"
    sub = await db.subscribers.find_one(
        {"referral_code": code},
        {"_id": 0, "id": 1, "company_id": 1, "name": 1},
    )
    if not sub:
        col = await db.collaborators.find_one(
            {"referral_code": code},
            {"_id": 0, "id": 1, "company_id": 1, "name": 1},
        )
        if not col:
            raise HTTPException(404, "Código de indicação inválido")
        sub = col
        owner_type = "collaborator"
    cid = sub["company_id"]
    owner_id = sub["id"]
    phone = _norm_phone(payload.friend_phone)
    if not phone:
        raise HTTPException(400, "Telefone inválido")

    # Dedup: 1 indicação por (owner, phone) — evita spam
    existing = await db.referrals.find_one({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "friend_phone": phone,
    }, {"_id": 0, "id": 1, "status": 1})
    if existing:
        return {"ok": True, "deduped": True, "referral_id": existing["id"],
                "status": existing["status"]}

    referral_id = f"ref-{uuid.uuid4().hex[:10]}"
    lead_id = f"lead-{uuid.uuid4().hex[:10]}"

    # Cria registro de referral
    await db.referrals.insert_one({
        "id": referral_id,
        "company_id": cid,
        "owner_subscriber_id": owner_id,
        "owner_type": owner_type,
        "friend_name": payload.friend_name.strip(),
        "friend_phone": phone,
        "friend_neighborhood": (payload.friend_neighborhood or "").strip() or None,
        "status": "contacted",
        "lead_id": lead_id,
        "created_subscriber_id": None,
        "reward_amount": REWARD_PER_INSTALL_BRL,
        "reward_status": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    # Cria lead pra Isabella tomar conta
    await db.sales_leads.insert_one({
        "id": lead_id,
        "company_id": cid,
        "phone": phone,
        "subscriber_name": payload.friend_name.strip(),
        "subscriber_id": None,
        "neighborhood": payload.friend_neighborhood,
        "source": "referral",
        "status": "contacted",
        "referrer_subscriber_id": owner_id,
        "referral_id": referral_id,
        "ts": now_iso(),
        "outreach_sent_at": now_iso(),
        "updated_at": now_iso(),
    })

    # Dispara WhatsApp Isabella imediatamente (best-effort)
    owner_first = (sub.get("name") or "").split()[0].title()
    await _send_isabella_to_friend(cid, owner_first, phone,
                                     payload.friend_name.strip(), lead_id)

    return {"ok": True, "referral_id": referral_id, "lead_id": lead_id}


# --------------------------------------------------------------------------- #
# Endpoints do Cliente (auth via CPF → token simples)
# --------------------------------------------------------------------------- #
@router.post("/customer/login")
async def customer_login(payload: CustomerLogin):
    cpf = _norm_cpf(payload.cpf)
    if len(cpf) not in (11, 14):
        raise HTTPException(400, "CPF/CNPJ inválido. Use 11 dígitos.")

    # Valida dígitos verificadores — bloqueia placeholders (000.., 111..) e
    # CPFs malformados antes mesmo de bater no banco.
    if len(cpf) == 11 and not _is_valid_cpf(cpf):
        raise HTTPException(400, "CPF inválido. Verifique os dígitos.")
    if len(cpf) == 14 and not _is_valid_cnpj(cpf):
        raise HTTPException(400, "CNPJ inválido. Verifique os dígitos.")

    # Variantes formatadas pra tentar match em bases que armazenam com pontuação
    formatted_cpf = (f"{cpf[0:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:11]}"
                       if len(cpf) == 11 else cpf)
    formatted_cnpj = (
        f"{cpf[0:2]}.{cpf[2:5]}.{cpf[5:8]}/{cpf[8:12]}-{cpf[12:14]}"
        if len(cpf) == 14 else cpf)
    variants = [cpf, formatted_cpf, formatted_cnpj]

    sub = await db.subscribers.find_one({
        "$or": [
            {"cpf": {"$in": variants}},
            {"cnpj": {"$in": variants}},
            {"document": {"$in": variants}},
            {"cpf_cnpj": {"$in": variants}},
            {"tax_id": {"$in": variants}},
        ],
    }, {"_id": 0})
    if not sub:
        # Diagnóstico: existem subscribers na base?
        total = await db.subscribers.estimated_document_count()
        if total == 0:
            raise HTTPException(404,
                "Base de assinantes vazia neste ambiente. Cadastre um assinante "
                "primeiro no painel administrativo.")
        raise HTTPException(404,
            "CPF não encontrado em nossa base. "
            f"Confira o número digitado (você usou {len(cpf)} dígitos) "
            "ou entre em contato com a Ligo para verificar seu cadastro.")
    cid = sub.get("company_id")
    code = await _get_or_create_referral_code(cid, sub["id"])
    return {
        "ok": True,
        "token": _customer_token(sub["id"]),
        "subscriber": _customer_profile_dict(sub, code),
    }


@router.get("/customer/me")
async def customer_me(customer=Depends(_require_customer)):
    cid = customer["company_id"]
    code = await _get_or_create_referral_code(cid, customer["id"])
    return _customer_profile_dict(customer, code)


# iter215be — QR Code SEGURO: token efêmero (60s), sem dados pessoais.
# Bug crítico anterior: o fallback do PWA gerava JSON com nome+CPF em
# texto puro, legível por qualquer câmera. Agora o QR só contém um
# token opaco; quem escanear sem ser o app parceiro autenticado não
# consegue ver nada além de uma string aleatória que expira em 60s.
@router.get("/qr-token")
@limiter.limit(get_limit("qr_issue"))
async def issue_qr_token(request: Request,
                          customer=Depends(_require_customer)):
    """Emite um token efêmero (60s) para o QR Code do cliente.

    Rate-limited a 20 req/min por IP (iter215be) — evita um cliente
    travado num loop ficar gerando milhares de tokens.

    O conteúdo do QR é APENAS este token aleatório. Os dados
    pessoais ficam guardados no backend e são entregues somente ao
    parceiro autenticado via `/customer/qr-resolve/{token}`.
    """
    from datetime import datetime, timedelta, timezone
    import os as _os
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=60)
    await db.customer_qr_ephemeral.insert_one({
        "token": token,
        "subscriber_id": customer["id"],
        "company_id": customer.get("company_id"),
        "created_at": now,
        "expires_at": expires_at,
    })
    # iter215bm — QR vira URL pra que câmera comum abra o site Ligo.
    # App parceiro extrai o token via /q/<token>.
    base = _os.environ.get(
        "LIGO_QR_BASE_URL", "https://ligofibra.com.br").rstrip("/")
    return {
        "qr_payload": f"{base}/q/{token}",
        "expires_in": 60,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/customer/qr-resolve/{token}")
@limiter.limit(get_limit("qr_resolve"))
async def resolve_qr_token(
    request: Request,
    token: str,
    user: dict = Depends(require_role("gestor", "parceiro", "administrador")),
):
    """Resolve um token de QR Code escaneado por um parceiro autenticado.

    Rate-limited a 30 req/min por IP (iter215be) — defesa em camadas
    contra brute-force de tokens (embora 2^192 combinações tornem isso
    impraticável).

    Retorna dados do cliente APENAS se o token estiver válido (não
    expirado). Tokens são single-use (apagados após resolução).
    """
    from datetime import datetime, timezone
    # iter215bm — Suporta múltiplos formatos:
    #   "https://ligofibra.com.br/q/<token>"  (novo)
    #   "LIGO:<token>"                          (legado)
    #   "<token>"                               (puro)
    clean = (token or "").strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        try:
            from urllib.parse import urlparse
            p = urlparse(clean).path or ""
            if p.startswith("/q/"):
                clean = p[3:]
            elif p.startswith("/q2/"):
                # V2 (Fernet) — não cai nesse endpoint, redireciona pro scan
                # parceiro autenticado. Aqui só rejeitamos.
                raise HTTPException(400,
                    "QR criptografado: use /api/parceiro-portal/scan.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "QR inválido.") from None
    elif clean.startswith("LIGO:"):
        clean = clean[5:]
    rec = await db.customer_qr_ephemeral.find_one({"token": clean})
    if not rec:
        raise HTTPException(404, "QR Code inválido ou já consumido.")
    expires_at = rec.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(
            expires_at.replace("Z", "+00:00"))
    if expires_at and expires_at.tzinfo is None:
        # Mongo retorna datetime naive — assume UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expires_at and expires_at < now:
        await db.customer_qr_ephemeral.delete_one({"token": clean})
        raise HTTPException(410, "QR Code expirado. Peça ao cliente "
                                 "para reabrir o QR.")
    # Busca subscriber
    sub = await db.subscribers.find_one(
        {"id": rec["subscriber_id"]}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    # Single-use: invalida o token após uso (defesa contra screenshot)
    await db.customer_qr_ephemeral.delete_one({"token": clean})
    return {
        "name": sub.get("name"),
        "document": sub.get("document") or sub.get("cpf"),
        "plan_name": sub.get("plan_name"),
        "status": sub.get("status"),
        "filial": sub.get("branch") or sub.get("filial_name"),
        "installation_date": sub.get("installation_date"),
    }


def _customer_profile_dict(sub: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Snapshot canônico do perfil exibido no app `/cliente`.

    Inclui status, documento e filial pra renderizar a tela Minha Ligo
    sem precisar de chamadas extras.
    """
    # iter215bd — "Tempo de cliente" NUNCA pode cair em `created_at` porque
    # esse é o timestamp de importação do Atlaz (cria registros recentes
    # em massa). Prioridade real: installation_date → activation_date →
    # subscriber_since. Se nenhum existir, retorna None e o cliente fica
    # exibido como "Cliente Ligo" sem o contador.
    tenure_date = (
        sub.get("installation_date")
        or sub.get("activation_date")
        or sub.get("subscriber_since")
    )
    return {
        "id": sub["id"],
        "name": sub.get("name"),
        "nickname": sub.get("nickname"),
        "phone": sub.get("phone"),
        "pix_key": sub.get("pix_key"),
        "pix_key_type": sub.get("pix_key_type"),
        "referral_code": code,
        "plan_name": sub.get("plan_name"),
        "plan_price_brl": sub.get("plan_price_brl") or sub.get("plan_price"),
        "status": sub.get("status"),
        "document": sub.get("document") or sub.get("cpf") or sub.get("cnpj")
            or sub.get("cpf_cnpj") or sub.get("tax_id"),
        "filial_name": sub.get("filial_name") or sub.get("branch_name")
            or sub.get("filial"),
        # iter215 — pra exibir "tempo de cliente" no ClientQRModal
        "installation_date": tenure_date,
    }


@router.get("/customer/referrals")
async def customer_list_referrals(customer=Depends(_require_customer)):
    cid = customer["company_id"]
    items: List[dict] = []
    async for r in db.referrals.find(
        {"company_id": cid, "owner_subscriber_id": customer["id"]},
        {"_id": 0},
    ).sort("created_at", -1):
        items.append(r)
    return {"items": items}


@router.get("/customer/stats")
async def customer_stats(customer=Depends(_require_customer)):
    cid = customer["company_id"]
    stats = await _compute_stats(cid, customer["id"])
    first = (customer.get("name") or "Amigo(a)").split()[0].title()
    stats["motivation"] = _motivation_for(stats, first)
    stats["streak"] = await _compute_streak(cid, customer["id"])
    stats["projection"] = await _compute_projection(cid, customer["id"], stats)
    return stats


async def _compute_projection(cid: str, owner_id: str,
                                stats: Dict[str, Any]) -> Dict[str, Any]:
    """Estimativa data-driven de ganhos nos próximos 30 dias.

    Estratégia:
      • Pega os últimos 60 dias do cliente — calcula indicações/semana e
        taxa de conversão (installed / total).
      • Se < 5 indicações no histórico, usa baseline da empresa.
      • Projeta: weeks×avg_per_week × conversion_rate × R$50 + estimativa
        de bônus de streak (R$ 25 a cada 4 semanas) + L2 se aplicável.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=60)).isoformat()

    # Indicações do próprio cliente nos últimos 60d
    own_count = await db.referrals.count_documents({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "created_at": {"$gte": cutoff},
    })
    own_installed = await db.referrals.count_documents({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "created_at": {"$gte": cutoff}, "status": "installed",
    })

    if own_count >= 5:
        avg_per_week = own_count / 8.57  # 60d ≈ 8.57 weeks
        conv_rate = (own_installed / own_count) if own_count else 0.0
        source = "personal"
    else:
        # Baseline da empresa (mas evita CTR de 100% absurdo)
        comp_count = await db.referrals.count_documents({
            "company_id": cid, "created_at": {"$gte": cutoff},
        })
        comp_installed = await db.referrals.count_documents({
            "company_id": cid, "created_at": {"$gte": cutoff},
            "status": "installed",
        })
        # Indicações ativas por semana / contadores
        active_referrers = await db.referrals.aggregate([
            {"$match": {"company_id": cid, "created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$owner_subscriber_id"}},
            {"$count": "n"},
        ]).to_list(1)
        n_referrers = (active_referrers[0]["n"] if active_referrers else 1) or 1
        avg_per_week = (comp_count / n_referrers) / 8.57 if comp_count else 0.5
        conv_rate = (comp_installed / comp_count) if comp_count else 0.40
        source = "baseline"

    # Sanity floors/ceilings
    avg_per_week = max(0.3, min(avg_per_week, 10.0))
    conv_rate = max(0.10, min(conv_rate, 0.95))

    projected_indications_30d = avg_per_week * 4.0
    projected_installs_30d = projected_indications_30d * conv_rate
    projected_base_brl = projected_installs_30d * REWARD_PER_INSTALL_BRL
    # Estimativa streak: se sustentar 4 semanas com ≥1 install, +R$ 25
    estimated_cycles = 1 if projected_installs_30d >= 4 else 0
    projected_streak_brl = estimated_cycles * STREAK_BONUS_BRL
    projected_total = projected_base_brl + projected_streak_brl

    return {
        "source": source,
        "avg_per_week": round(avg_per_week, 1),
        "conversion_pct": round(conv_rate * 100, 1),
        "projected_indications_30d": round(projected_indications_30d, 0),
        "projected_installs_30d": round(projected_installs_30d, 1),
        "projected_base_brl": round(projected_base_brl, 2),
        "projected_streak_brl": projected_streak_brl,
        "projected_total_brl": round(projected_total, 2),
    }


@router.put("/customer/pix-key")
async def customer_set_pix(payload: PixKeyUpdate,
                            customer=Depends(_require_customer)):
    await db.subscribers.update_one(
        {"id": customer["id"]},
        {"$set": {
            "pix_key": payload.pix_key.strip(),
            "pix_key_type": payload.pix_key_type,
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True}


@router.post("/customer/payout-request")
async def customer_payout_request(payload: PayoutRequest,
                                    customer=Depends(_require_customer)):
    cid = customer["company_id"]
    stats = await _compute_stats(cid, customer["id"])
    available = stats["available_brl"]
    if payload.amount > available + 0.001:
        raise HTTPException(400,
            f"Saldo disponível R$ {available:.2f} insuficiente "
            f"para o valor solicitado R$ {payload.amount:.2f}")
    if payload.method == "pix" and not customer.get("pix_key"):
        raise HTTPException(400, "Cadastre uma chave PIX antes de solicitar.")
    payout_id = f"pay-{uuid.uuid4().hex[:10]}"
    await db.referral_payouts.insert_one({
        "id": payout_id,
        "company_id": cid,
        "owner_subscriber_id": customer["id"],
        "method": payload.method,
        "amount": payload.amount,
        "notes": payload.notes,
        "status": "pending",  # pending → approved → paid OR rejected
        "pix_key_snapshot": customer.get("pix_key"),
        "pix_key_type_snapshot": customer.get("pix_key_type"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    # Reserva o valor: marca rewards available até cobrir o pedido como pending_approval
    remaining = payload.amount
    cursor = db.referral_rewards.find({
        "company_id": cid, "owner_subscriber_id": customer["id"],
        "status": "available",
    }).sort("created_at", 1)
    async for rew in cursor:
        if remaining <= 0:
            break
        amt = float(rew.get("amount") or 0)
        if amt <= remaining + 0.001:
            await db.referral_rewards.update_one(
                {"id": rew["id"]},
                {"$set": {"status": "pending_approval", "payout_id": payout_id,
                          "updated_at": now_iso()}},
            )
            remaining -= amt
    return {"ok": True, "payout_id": payout_id, "status": "pending"}


@router.get("/customer/leaderboard")
async def customer_leaderboard(customer=Depends(_require_customer)):
    """Wall of Fame anônimo — FOMO e competição sem expor identidade."""
    cid = customer["company_id"]
    # Janela: 1º dia do mês corrente (UTC)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0,
                                microsecond=0).isoformat()

    # 1) Indicadores ativos no mês + valor total ganho
    pipe_month = [
        {"$match": {"company_id": cid,
                     "created_at": {"$gte": month_start},
                     "status": {"$in": ["available", "pending_approval", "paid"]}}},
        {"$group": {"_id": "$owner_subscriber_id",
                     "total_brl": {"$sum": "$amount"},
                     "rewards_count": {"$sum": 1}}},
    ]
    by_owner: List[Dict[str, Any]] = []
    async for row in db.referral_rewards.aggregate(pipe_month):
        by_owner.append({
            "owner": row["_id"],
            "total_brl": float(row["total_brl"]),
            "count": int(row["rewards_count"]),
        })

    total_referrers_month = len(by_owner)
    over_200 = sum(1 for r in by_owner if r["total_brl"] >= 200)
    total_paid_month = sum(r["total_brl"] for r in by_owner)

    # 2) Top 5 anônimos
    top = sorted(by_owner, key=lambda r: r["total_brl"], reverse=True)[:5]
    leaderboard: List[Dict[str, Any]] = []
    for idx, t in enumerate(top, 1):
        sub = await db.subscribers.find_one(
            {"id": t["owner"]}, {"_id": 0, "name": 1},
        )
        name = ((sub or {}).get("name") or "Anônimo").strip()
        # Anonimiza: 1º char + *** + último char do primeiro nome
        first = name.split()[0] if name else "Anônimo"
        anon = (first[0] + "***" + first[-1]) if len(first) > 2 else first
        leaderboard.append({
            "rank": idx,
            "name_masked": anon,
            "installs": t["count"],
            "total_brl": t["total_brl"],
            "is_you": t["owner"] == customer["id"],
        })

    # 3) Posição do cliente atual (mesmo fora do top 5)
    me_pos = next((r["rank"] for r in leaderboard if r["is_you"]), None)
    if not me_pos:
        # acha posição completa
        sorted_all = sorted(by_owner, key=lambda r: r["total_brl"], reverse=True)
        for idx, t in enumerate(sorted_all, 1):
            if t["owner"] == customer["id"]:
                me_pos = idx
                break

    # 4) Badge sazonal por mês
    seasonal_badge = None
    seasonal_map = {
        12: {"emoji": "🎄", "title": "Indicador do Natal 2026",
              "desc": "Top 3 em dezembro ganha bônus de R$ 100"},
        11: {"emoji": "🛍️", "title": "Black Friday Indicador",
              "desc": "5 instalações em novembro = bônus dobrado"},
        6:  {"emoji": "🎃", "title": "São João Top Indicador",
              "desc": "Top 5 em junho concorre a TV 50\""},
    }
    seasonal_badge = seasonal_map.get(now.month)

    return {
        "month_label": now.strftime("%m/%Y"),
        "total_referrers_month": total_referrers_month,
        "over_200_count": over_200,
        "total_paid_month_brl": total_paid_month,
        "leaderboard": leaderboard,
        "my_position": me_pos,
        "seasonal_badge": seasonal_badge,
    }


# --------------------------------------------------------------------------- #
# Admin endpoints (gestor aprova payouts)
# --------------------------------------------------------------------------- #
@router.get("/referrals/admin/payouts")
async def admin_list_payouts(
    user=Depends(require_role("administrador", "gestor", "auditor", "financeiro")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items: List[dict] = []
    async for p in db.referral_payouts.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(200):
        # Joina nome do cliente
        sub = await db.subscribers.find_one(
            {"id": p.get("owner_subscriber_id")},
            {"_id": 0, "name": 1, "external_code": 1, "phone": 1},
        )
        p["owner_name"] = (sub or {}).get("name")
        p["owner_external_code"] = (sub or {}).get("external_code")
        p["owner_phone"] = (sub or {}).get("phone")
        items.append(p)
    return {"items": items}


@router.post("/referrals/admin/payouts/{payout_id}/approve")
async def admin_approve_payout(
    payout_id: str,
    user=Depends(require_role("administrador", "gestor", "financeiro")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await db.referral_payouts.find_one(
        {"id": payout_id, "company_id": cid}, {"_id": 0},
    )
    if not p:
        raise HTTPException(404, "Solicitação não encontrada")
    if p["status"] != "pending":
        raise HTTPException(400, f"Status atual: {p['status']}")
    await db.referral_payouts.update_one(
        {"id": payout_id},
        {"$set": {"status": "paid", "approved_by": user.get("email"),
                  "paid_at": now_iso(), "updated_at": now_iso()}},
    )
    await db.referral_rewards.update_many(
        {"payout_id": payout_id, "status": "pending_approval"},
        {"$set": {"status": "paid", "updated_at": now_iso()}},
    )
    # ─── Isabella Loop #3: avisa o cliente que o PIX foi liberado ──────────
    owner = await db.subscribers.find_one(
        {"id": p["owner_subscriber_id"]}, {"_id": 0, "name": 1},
    )
    owner_first = ((owner or {}).get("name") or "").split()[0].title() or "Olá"
    if p["method"] == "pix":
        msg = (
            f"💸 *{owner_first}*, seu PIX de "
            f"*R$ {float(p['amount']):.2f}* foi aprovado pela Ligo!\n\n"
            f"Chave: `{p.get('pix_key_snapshot')}`\n\n"
            f"Já tá caindo na sua conta. Obrigado por indicar a Ligo 💚"
        )
    else:
        msg = (
            f"✅ *{owner_first}*, seu desconto de "
            f"*R$ {float(p['amount']):.2f}* foi aprovado!\n\n"
            f"O valor será abatido automaticamente na sua próxima fatura. 🎉"
        )
    await _notify_referrer(cid, p["owner_subscriber_id"], msg,
                            meta={"event": "payout_paid",
                                  "payout_id": payout_id})
    # Sprint 19 — emit referral.converted
    try:
        from services.event_emitters import emit_business
        await emit_business(
            kind="referral.converted", actor=user,
            payload={"payout_id": payout_id,
                       "owner_subscriber_id": p.get("owner_subscriber_id"),
                       "amount": float(p.get("amount", 0)),
                       "method": p.get("method")},
            severity="media", source="referrals.approve_payout")
    except Exception:
        pass
    return {"ok": True}


@router.post("/referrals/admin/payouts/{payout_id}/reject")
async def admin_reject_payout(
    payout_id: str,
    user=Depends(require_role("administrador", "gestor", "financeiro")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await db.referral_payouts.find_one(
        {"id": payout_id, "company_id": cid}, {"_id": 0},
    )
    if not p:
        raise HTTPException(404, "Solicitação não encontrada")
    await db.referral_payouts.update_one(
        {"id": payout_id},
        {"$set": {"status": "rejected", "rejected_by": user.get("email"),
                  "rejected_at": now_iso(), "updated_at": now_iso()}},
    )
    # Reverte rewards pra "available"
    await db.referral_rewards.update_many(
        {"payout_id": payout_id, "status": "pending_approval"},
        {"$set": {"status": "available", "updated_at": now_iso(),
                  "payout_id": None}},
    )
    return {"ok": True}


async def _notify_referrer(cid: str, owner_subscriber_id: str,
                            text: str, meta: Optional[Dict[str, Any]] = None
                           ) -> None:
    """Envia mensagem WhatsApp transacional pro indicador (fecha o loop).

    Usado em 3 momentos:
      1. Amigo instala → "🎉 Maria, o Carlos acabou de instalar..."
      2. Indicador atinge tier (Bronze/Prata/Ouro/Diamante) → "🏆 Parabéns!"
      3. Payout aprovado → "💸 PIX de R$ 50 a caminho da sua conta"

    Best-effort — falhas não bloqueiam a operação principal.
    """
    from services.wa.sidecar import _sidecar_post_silent_at
    from services.whatsapp_channels import (
        base_url_for, get_default_outbound_channel,
    )
    sub = await db.subscribers.find_one(
        {"id": owner_subscriber_id, "company_id": cid},
        {"_id": 0, "phone": 1, "name": 1},
    )
    if not sub:
        # Fallback: pode ser um COLABORADOR (técnico) com Indique e Ganhe
        sub = await db.collaborators.find_one(
            {"id": owner_subscriber_id, "company_id": cid},
            {"_id": 0, "phone": 1, "name": 1},
        )
    if not sub or not sub.get("phone"):
        return
    phone = _norm_phone(sub["phone"])
    if not phone:
        return
    try:
        ch_id = await get_default_outbound_channel(db, cid)
    except Exception:
        ch_id = "channel-1"
    base_url = base_url_for(ch_id)
    try:
        await _sidecar_post_silent_at(
            base_url, "/send", {"phone": phone, "text": text}, timeout=15.0,
        )
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": phone,
            "text": text,
            "channel": "baileys",
            "channel_id": ch_id,
            "agent_name": "Isabella",
            "auto_reply": True,
            "delivery_status": "sent",
            "metadata": {"source": "referral_loop", **(meta or {})},
            "created_at": now_iso(),
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=(sub or {}).get("company_id"),
                source="referrals",
                payload={},
            )
        except Exception:
            pass
    except Exception as e:
        logger.warning("[referrals] notify-referrer failed: %s", e)


def _tier_for(installs: int) -> Optional[Dict[str, Any]]:
    """Retorna o tier mais alto atingido (ou None se < 5)."""
    reached = None
    for t in TIERS:
        if installs >= t["min_installs"]:
            reached = t
    return reached


async def _compute_streak(cid: str, owner_id: str) -> Dict[str, Any]:
    """Calcula streak de semanas consecutivas com ≥1 instalação.

    Considera a semana ISO (year-week) do `installed_at` de cada referral
    instalada. Streak ativa = sequência terminando na semana corrente OU
    na anterior (perdoa 7 dias). Reset = ≥ 2 semanas sem instalar.
    """
    week_set: set = set()
    cursor = db.referrals.find({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "status": "installed",
    }, {"_id": 0, "installed_at": 1})
    async for r in cursor:
        iso = r.get("installed_at") or ""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except Exception:
            continue
        y, w, _ = dt.isocalendar()
        week_set.add((y, w))
    if not week_set:
        return {"streak_weeks": 0, "streak_active": False,
                "weeks_done_this_streak": 0,
                "needed_to_finish": STREAK_TARGET_WEEKS,
                "next_bonus_brl": STREAK_BONUS_BRL}
    # Ordena por (year, week) decrescente, conta sequência
    sorted_weeks = sorted(week_set, reverse=True)
    now_y, now_w, _ = datetime.now(timezone.utc).isocalendar()
    most_recent = sorted_weeks[0]
    # Streak só conta se a última instalação foi nesta ou na semana anterior
    diff_weeks = ((now_y - most_recent[0]) * 52) + (now_w - most_recent[1])
    if diff_weeks > 1:
        return {"streak_weeks": 0, "streak_active": False,
                "weeks_done_this_streak": 0,
                "needed_to_finish": STREAK_TARGET_WEEKS,
                "next_bonus_brl": STREAK_BONUS_BRL}
    # Conta semanas consecutivas (cada par seguinte deve ter diff de exatamente 1)
    streak = 1
    prev = most_recent
    for w in sorted_weeks[1:]:
        gap = ((prev[0] - w[0]) * 52) + (prev[1] - w[1])
        if gap == 1:
            streak += 1
            prev = w
        else:
            break
    return {
        "streak_weeks": streak,
        "streak_active": True,
        "weeks_done_this_streak": streak % STREAK_TARGET_WEEKS,
        "needed_to_finish": max(0, STREAK_TARGET_WEEKS - (streak % STREAK_TARGET_WEEKS or STREAK_TARGET_WEEKS)),
        "next_bonus_brl": STREAK_BONUS_BRL,
        "completed_cycles": streak // STREAK_TARGET_WEEKS,
    }


async def _maybe_credit_streak_bonus(cid: str, owner_id: str) -> Optional[float]:
    """Credita bônus de R$ 25 quando completa múltiplo de 4 semanas.

    Idempotente: usa `referral_streak_bonuses` collection com key
    (owner_id, cycles) pra garantir 1 pagamento por ciclo.
    """
    streak = await _compute_streak(cid, owner_id)
    cycles = streak.get("completed_cycles", 0)
    if cycles <= 0:
        return None
    # Já creditou esse ciclo?
    existing = await db.referral_streak_bonuses.find_one({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "cycle_number": cycles,
    }, {"_id": 1})
    if existing:
        return None
    # Cria reward + marcador idempotente
    rew_id = f"rew-{uuid.uuid4().hex[:10]}"
    await db.referral_rewards.insert_one({
        "id": rew_id,
        "company_id": cid,
        "owner_subscriber_id": owner_id,
        "amount": STREAK_BONUS_BRL,
        "status": "available",
        "currency": "BRL",
        "source": "streak_bonus",
        "level": 1,
        "metadata": {"cycle_number": cycles,
                      "streak_weeks": streak["streak_weeks"]},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    await db.referral_streak_bonuses.insert_one({
        "company_id": cid,
        "owner_subscriber_id": owner_id,
        "cycle_number": cycles,
        "reward_id": rew_id,
        "amount": STREAK_BONUS_BRL,
        "created_at": now_iso(),
    })
    # Notifica via WhatsApp
    sub = await db.subscribers.find_one(
        {"id": owner_id}, {"_id": 0, "name": 1},
    )
    first = ((sub or {}).get("name") or "").split()[0].title() or "Olá"
    msg = (
        f"🔥 *{first}*, streak quente!\n\n"
        f"Você indicou amigos que instalaram em *{STREAK_TARGET_WEEKS} "
        f"semanas seguidas* — bônus *R$ {STREAK_BONUS_BRL:.2f}* creditado "
        f"no seu saldo!\n\n"
        f"Continua firme — cada 4 semanas consecutivas te dá outro R$ 25. 💸"
    )
    await _notify_referrer(cid, owner_id, msg,
                            meta={"event": "streak_bonus",
                                  "cycle": cycles})
    return STREAK_BONUS_BRL


@router.post("/referrals/admin/blast-invite")
async def admin_blast_invite(
    request: Request,
    user=Depends(require_role("administrador", "gestor")),
):
    """Dispara convite em massa pros assinantes ATIVOS apresentarem o app
    do cliente. Roda em background — usa o canal default outbound.

    Idempotente parcial: cada subscriber recebe no máximo 1 convite
    (campo `referral_invite_sent_at` evita re-envio). Aceita `?force=1`
    pra resetar.
    """
    import asyncio as _asyncio
    cid = user.get("company_id") or DEMO_COMPANY_ID
    force = (request.query_params.get("force") or "").lower() in ("1", "true")

    # Conta candidatos primeiro pra dar feedback imediato
    q: Dict[str, Any] = {
        "company_id": cid,
        "status": {"$in": ["ATIVO", "ATIVA", "INSTALADO"]},
        "phone": {"$exists": True, "$nin": [None, ""]},
    }
    if not force:
        q["referral_invite_sent_at"] = {"$in": [None, False]}
    candidates = await db.subscribers.count_documents(q)
    if candidates == 0:
        return {"ok": True, "queued": 0,
                "message": "Nenhum assinante ATIVO pendente. Use ?force=1 pra re-enviar."}

    # Dispara em background pra não travar HTTP
    _asyncio.create_task(_run_blast_invite(cid, force))
    return {"ok": True, "queued": candidates,
            "message": f"Disparo iniciado em background para {candidates} assinante(s).",
            "force": force}


async def _run_blast_invite(cid: str, force: bool) -> None:
    """Worker em background — itera assinantes ATIVOS e envia convite."""
    import asyncio as _asyncio
    from services.wa.sidecar import _sidecar_post_silent_at
    from services.whatsapp_channels import (
        base_url_for, get_default_outbound_channel,
    )
    try:
        ch_id = await get_default_outbound_channel(db, cid)
    except Exception:
        ch_id = "channel-1"
    base_url = base_url_for(ch_id)
    app_link = _app_link_for_cid(cid)

    q: Dict[str, Any] = {
        "company_id": cid,
        "status": {"$in": ["ATIVO", "ATIVA", "INSTALADO"]},
        "phone": {"$exists": True, "$nin": [None, ""]},
    }
    if not force:
        q["referral_invite_sent_at"] = {"$in": [None, False]}

    sent = 0
    errors = 0
    async for sub in db.subscribers.find(q, {"_id": 0}):
        phone = _norm_phone(sub.get("phone") or "")
        if not phone:
            continue
        first = (sub.get("name") or "").split()[0].title() or "Olá"
        # Garante referral_code (gera se não tiver)
        try:
            code = await _get_or_create_referral_code(cid, sub["id"])
        except Exception:
            code = ""
        ref_link = app_link.replace("/cliente", f"/r/{code}") if code else app_link
        msg = (
            f"Oi *{first}*! 👋 Aqui é a *Ligo*.\n\n"
            f"Agora você ganha *R$ 50* no PIX por cada amigo que instalar "
            f"a fibra com a sua indicação! 🚀\n\n"
            f"📱 *Seu app de indicação*: {app_link}\n"
            f"   (entra com seu CPF)\n\n"
            f"🔗 *Seu link pra compartilhar*: {ref_link}\n\n"
            f"E mais: bônus de R$ 25 a cada 4 semanas indicando 🔥, R$ 10 "
            f"extras se seu indicado indicar alguém, e brindes a cada 5/10/20 "
            f"instalações.\n\n"
            f"Bora começar? 💸"
        )
        try:
            r = await _sidecar_post_silent_at(
                base_url, "/send", {"phone": phone, "text": msg},
                timeout=15.0,
            )
            if r.get("ok"):
                sent += 1
                await db.subscribers.update_one(
                    {"id": sub["id"]},
                    {"$set": {"referral_invite_sent_at": now_iso()}},
                )
                await db.aihub_wa_messages.insert_one({
                    "id": f"wam-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "direction": "outbound",
                    "phone": phone,
                    "text": msg,
                    "channel": "baileys",
                    "channel_id": ch_id,
                    "agent_name": "Isabella",
                    "auto_reply": True,
                    "delivery_status": "sent",
                    "metadata": {"source": "referral_blast_invite",
                                  "subscriber_id": sub["id"]},
                    "created_at": now_iso(),
                })
            else:
                errors += 1
        except Exception as e:
            errors += 1
            logger.warning("[referrals] blast invite fail %s: %s", phone, e)
        await _asyncio.sleep(1.2)  # throttle: ~50/min

    logger.info("[referrals] blast invite done: sent=%d errors=%d",
                  sent, errors)


@router.get("/referrals/admin/dashboard")
async def admin_dashboard(
    user=Depends(require_role("administrador", "gestor", "auditor", "financeiro")),
):
    """KPIs de crescimento e engajamento do programa Indique e Ganhe.

    Janelas: 30 dias (atual) vs 30 dias anteriores → growth_pct.
    """
    from datetime import timedelta
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    d30 = (now - timedelta(days=30)).isoformat()
    d60 = (now - timedelta(days=60)).isoformat()

    async def _count(coll: str, q: Dict[str, Any]) -> int:
        return await db[coll].count_documents(q)

    # Período atual: últimos 30d
    cur_indications = await _count("referrals",
        {"company_id": cid, "created_at": {"$gte": d30}})
    cur_installs = await _count("referrals",
        {"company_id": cid, "installed_at": {"$gte": d30}, "status": "installed"})
    # Período anterior: 30-60d atrás
    prev_indications = await _count("referrals",
        {"company_id": cid, "created_at": {"$gte": d60, "$lt": d30}})
    prev_installs = await _count("referrals",
        {"company_id": cid, "installed_at": {"$gte": d60, "$lt": d30},
          "status": "installed"})

    def _growth(cur: int, prev: int) -> float:
        if prev == 0:
            return 100.0 if cur > 0 else 0.0
        return round(((cur - prev) / prev) * 100, 1)

    # Totais all-time
    total_indications = await _count("referrals", {"company_id": cid})
    total_installs = await _count("referrals",
        {"company_id": cid, "status": "installed"})

    # R$ creditado + R$ pago
    paid_agg = await db.referral_rewards.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "total": {"$sum": "$amount"}, "n": {"$sum": 1}}},
    ]).to_list(20)
    available_brl = 0.0
    paid_brl = 0.0
    pending_brl = 0.0
    for row in paid_agg:
        if row["_id"] == "available":
            available_brl = float(row["total"])
        elif row["_id"] == "paid":
            paid_brl = float(row["total"])
        elif row["_id"] == "pending_approval":
            pending_brl = float(row["total"])
    total_credited = available_brl + paid_brl + pending_brl

    # Engajamento: indicadores únicos ativos no mês
    active_referrers_cur = await db.referrals.aggregate([
        {"$match": {"company_id": cid, "created_at": {"$gte": d30}}},
        {"$group": {"_id": "$owner_subscriber_id"}},
        {"$count": "n"},
    ]).to_list(1)
    n_active_cur = (active_referrers_cur[0]["n"] if active_referrers_cur else 0)

    active_referrers_prev = await db.referrals.aggregate([
        {"$match": {"company_id": cid, "created_at": {"$gte": d60, "$lt": d30}}},
        {"$group": {"_id": "$owner_subscriber_id"}},
        {"$count": "n"},
    ]).to_list(1)
    n_active_prev = (active_referrers_prev[0]["n"] if active_referrers_prev else 0)

    # Base elegível: assinantes ATIVOS com referral_code
    eligible = await _count("subscribers",
        {"company_id": cid,
          "status": {"$in": ["ATIVO", "ATIVA", "INSTALADO"]},
          "referral_code": {"$exists": True}})
    base_active = await _count("subscribers",
        {"company_id": cid, "status": {"$in": ["ATIVO", "ATIVA", "INSTALADO"]}})
    penetration_pct = round((eligible / base_active * 100) if base_active else 0, 1)

    # Conversion rate (instalações ÷ indicações no período)
    conv_pct_cur = round((cur_installs / cur_indications * 100)
                          if cur_indications else 0, 1)

    # Top 5 indicadores do mês (não anônimo — admin vê tudo)
    top_pipeline = [
        {"$match": {"company_id": cid, "installed_at": {"$gte": d30},
                     "status": "installed"}},
        {"$group": {"_id": "$owner_subscriber_id",
                     "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top: List[Dict[str, Any]] = []
    async for row in db.referrals.aggregate(top_pipeline):
        sub = await db.subscribers.find_one(
            {"id": row["_id"]}, {"_id": 0, "name": 1, "phone": 1,
                                   "external_code": 1},
        )
        top.append({
            "subscriber_id": row["_id"],
            "name": (sub or {}).get("name"),
            "phone": (sub or {}).get("phone"),
            "external_code": (sub or {}).get("external_code"),
            "installs_30d": int(row["count"]),
            "earned_30d_brl": int(row["count"]) * REWARD_PER_INSTALL_BRL,
        })

    # Série diária pros últimos 30d (sparkline)
    daily_indications: Dict[str, int] = {}
    daily_installs: Dict[str, int] = {}
    async for r in db.referrals.find({"company_id": cid,
                                       "created_at": {"$gte": d30}},
                                      {"_id": 0, "created_at": 1}):
        day = (r.get("created_at") or "")[:10]
        if day:
            daily_indications[day] = daily_indications.get(day, 0) + 1
    async for r in db.referrals.find({"company_id": cid,
                                       "installed_at": {"$gte": d30},
                                       "status": "installed"},
                                      {"_id": 0, "installed_at": 1}):
        day = (r.get("installed_at") or "")[:10]
        if day:
            daily_installs[day] = daily_installs.get(day, 0) + 1

    # Monta series ordenada de 30 dias
    sparkline = []
    for i in range(30, 0, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        sparkline.append({
            "date": d,
            "indications": daily_indications.get(d, 0),
            "installs": daily_installs.get(d, 0),
        })

    return {
        "period": "30d",
        "indications": {
            "current": cur_indications, "previous": prev_indications,
            "growth_pct": _growth(cur_indications, prev_indications),
        },
        "installs": {
            "current": cur_installs, "previous": prev_installs,
            "growth_pct": _growth(cur_installs, prev_installs),
        },
        "conversion_pct_30d": conv_pct_cur,
        "active_referrers": {
            "current": n_active_cur, "previous": n_active_prev,
            "growth_pct": _growth(n_active_cur, n_active_prev),
        },
        "totals_all_time": {
            "indications": total_indications,
            "installs": total_installs,
            "credited_brl": round(total_credited, 2),
            "paid_brl": round(paid_brl, 2),
            "pending_brl": round(pending_brl, 2),
            "available_brl": round(available_brl, 2),
        },
        "base": {
            "active_subscribers": base_active,
            "eligible_referrers": eligible,
            "penetration_pct": penetration_pct,
        },
        "top_referrers_30d": top,
        "sparkline_30d": sparkline,
    }


# --------------------------------------------------------------------------- #
# Engagement Anti-Churn: detecta indicadores ativos que sumiram
# --------------------------------------------------------------------------- #
ENGAGEMENT_REMIND_AFTER_DAYS = 7      # alerta quando passa 7d sem indicar
ENGAGEMENT_COOLDOWN_DAYS = 14          # max 1 alerta a cada 14d


async def run_referral_engagement_alerts(cid: Optional[str] = None
                                            ) -> Dict[str, Any]:
    """Detecta indicadores que estavam ativos mas sumiram — manda WhatsApp.

    Critérios:
      - Cliente teve ≥ 2 indicações no histórico geral
      - Última indicação foi há mais de 7 dias
      - Ritmo histórico era ≤ 7 dias entre indicações (era engajado)
      - Não recebeu alerta nos últimos 14 dias (cooldown)

    Retorna {"scanned": N, "alerted": M, "skipped_cooldown": K}.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff_inactive = (now - timedelta(days=ENGAGEMENT_REMIND_AFTER_DAYS)).isoformat()
    cooldown_iso = (now - timedelta(days=ENGAGEMENT_COOLDOWN_DAYS)).isoformat()

    # Filtro por empresa (None = todas)
    match_subs = {"referral_code": {"$exists": True}}
    if cid:
        match_subs["company_id"] = cid

    scanned = 0
    alerted = 0
    skipped_cooldown = 0

    async for sub in db.subscribers.find(
        match_subs,
        {"_id": 0, "id": 1, "company_id": 1, "name": 1, "phone": 1,
          "last_engagement_alert_at": 1},
    ):
        scanned += 1
        sub_cid = sub["company_id"]
        sub_id = sub["id"]
        # Cooldown
        last_alert = sub.get("last_engagement_alert_at")
        if last_alert and last_alert > cooldown_iso:
            skipped_cooldown += 1
            continue
        # Histórico
        all_refs = await db.referrals.find(
            {"company_id": sub_cid, "owner_subscriber_id": sub_id},
            {"_id": 0, "created_at": 1, "status": 1},
        ).sort("created_at", -1).to_list(100)
        if len(all_refs) < 2:
            continue
        last_ref_at = all_refs[0]["created_at"]
        if last_ref_at >= cutoff_inactive:
            continue  # ainda ativo
        # Calcula ritmo histórico médio (dias entre indicações)
        dates = []
        for r in all_refs:
            try:
                dates.append(datetime.fromisoformat(
                    r["created_at"].replace("Z", "+00:00")))
            except Exception:
                pass
        if len(dates) < 2:
            continue
        deltas = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
        avg_gap = sum(deltas) / len(deltas)
        if avg_gap > 7:
            continue  # nunca foi muito engajado — não vale alerta

        # Calcula dias parado
        try:
            last_dt = datetime.fromisoformat(last_ref_at.replace("Z", "+00:00"))
            days_inactive = (now - last_dt).days
        except Exception:
            days_inactive = ENGAGEMENT_REMIND_AFTER_DAYS

        # Conta installs pra personalizar copy
        installs = sum(1 for r in all_refs if r.get("status") == "installed")
        first = (sub.get("name") or "").split()[0].title() or "Olá"
        avg_per_week = 7.0 / max(avg_gap, 1)

        copy_template = (
            "Oi! 👋 Vi seu post sobre internet — sabia que tem uma promo "
            "de fibra com instalação rápida na nossa região? "
            "Se quiser, te mando o link: {link}"
        )
        link = f"{_app_link_for_cid(sub_cid).replace('/cliente','')}/r/{sub.get('referral_code','')}"

        # Mensagem motivacional + copy pronto
        msg = (
            f"👀 *{first}*, sentimos sua falta no *Indique e Ganhe*!\n\n"
            f"Você costumava indicar ~*{avg_per_week:.1f}* amigos por semana "
            f"(e já tem *{installs}* instalações no histórico 💪), mas tá "
            f"há *{days_inactive} dias* sem mexer.\n\n"
            f"Quer um copy pronto pra mandar agora?\n\n"
            f"_{copy_template.replace('{link}', link)}_\n\n"
            f"É só copiar, colar no WhatsApp e mandar pros amigos. 🚀\n"
            f"Seu link: {link}"
        )
        await _notify_referrer(sub_cid, sub_id, msg,
                                meta={"event": "engagement_alert",
                                      "days_inactive": days_inactive,
                                      "avg_gap_days": round(avg_gap, 1)})
        # Marca cooldown
        await db.subscribers.update_one(
            {"id": sub_id},
            {"$set": {"last_engagement_alert_at": now.isoformat(),
                      "updated_at": now_iso()}},
        )
        alerted += 1

    logger.info("[referrals] engagement alerts: scanned=%d alerted=%d cd=%d",
                  scanned, alerted, skipped_cooldown)
    return {
        "scanned": scanned, "alerted": alerted,
        "skipped_cooldown": skipped_cooldown,
        "ran_at": now.isoformat(),
    }


@router.post("/referrals/admin/run-engagement-alerts")
async def admin_run_engagement_alerts(
    user=Depends(require_role("administrador", "gestor")),
):
    """Endpoint manual pra trigger imediato (debug/teste)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await run_referral_engagement_alerts(cid)


async def _maybe_credit_goal_bonus(cid: str, owner_id: str,
                                    owner_type: str) -> Optional[float]:
    """Credita R$ 500 ao colaborador quando atinge a META de 30 instalações.

    Idempotente: usa `referral_goal_bonuses` collection com key
    (owner_id, target_installs) pra garantir 1 pagamento por meta.
    Aplica-se SOMENTE a owner_type=collaborator (técnicos têm a meta
    cravada em GOAL_TARGET_INSTALLS = 30 → GOAL_BONUS_BRL = R$ 500).
    Subscribers já têm os tiers (Bronze/Prata/Ouro/Diamante).
    """
    if owner_type != "collaborator":
        return None
    installs = await db.referrals.count_documents({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "status": "installed",
    })
    if installs < GOAL_TARGET_INSTALLS:
        return None
    # Já creditou essa meta?
    existing = await db.referral_goal_bonuses.find_one({
        "company_id": cid, "owner_subscriber_id": owner_id,
        "target_installs": GOAL_TARGET_INSTALLS,
    }, {"_id": 1})
    if existing:
        return None
    rew_id = f"rew-{uuid.uuid4().hex[:10]}"
    await db.referral_rewards.insert_one({
        "id": rew_id,
        "company_id": cid,
        "owner_subscriber_id": owner_id,
        "amount": GOAL_BONUS_BRL,
        "status": "available",
        "currency": "BRL",
        "source": "goal_bonus",
        "level": 1,
        "metadata": {"target_installs": GOAL_TARGET_INSTALLS,
                      "installs_at_credit": installs},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    await db.referral_goal_bonuses.insert_one({
        "company_id": cid,
        "owner_subscriber_id": owner_id,
        "target_installs": GOAL_TARGET_INSTALLS,
        "reward_id": rew_id,
        "amount": GOAL_BONUS_BRL,
        "created_at": now_iso(),
    })
    logger.info("[referrals] GOAL bonus R$ %s credited to collab=%s "
                "(%s installs)", GOAL_BONUS_BRL, owner_id, installs)
    return GOAL_BONUS_BRL


# --------------------------------------------------------------------------- #
# Hook: chamado quando um subscriber muda pra status INSTALADO/ATIVO
# --------------------------------------------------------------------------- #
async def credit_referral_if_applies(cid: str, subscriber: Dict[str, Any]) -> None:
    """Idempotente — credita R$ 50 ao indicador quando o indicado instala.

    Chamado pelo PATCH /subscribers/{id} quando status muda pra
    ATIVO/INSTALADO. Não dispara mais de 1x por indicação (dedup por
    referral_id + reward_status).
    """
    phone = _norm_phone(subscriber.get("phone") or "")
    sub_id = subscriber.get("id")
    if not (phone or sub_id):
        return
    # Acha referral correspondente (por phone ou subscriber_id)
    q: Dict[str, Any] = {"company_id": cid,
                          "reward_status": {"$in": ["pending", None]}}
    or_terms = []
    if phone:
        or_terms.append({"friend_phone": phone})
    if sub_id:
        or_terms.append({"created_subscriber_id": sub_id})
    if or_terms:
        q["$or"] = or_terms
    ref = await db.referrals.find_one(q, {"_id": 0})
    if not ref:
        return
    # Marca como installed + credita reward
    await db.referrals.update_one(
        {"id": ref["id"]},
        {"$set": {"status": "installed",
                  "reward_status": "credited",
                  "created_subscriber_id": sub_id,
                  "installed_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    owner_type = ref.get("owner_type", "subscriber")
    # Marca o novo subscriber como "indicado por X" — habilita multi-nível
    # SOMENTE quando o indicador é um subscriber (técnicos não criam cadeia L2)
    if owner_type == "subscriber":
        await db.subscribers.update_one(
            {"id": sub_id, "company_id": cid},
            {"$set": {"referred_by_subscriber_id": ref["owner_subscriber_id"],
                      "updated_at": now_iso()}},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "subscriber.updated",
                company_id=(ref or {}).get("company_id"),
                source="referrals",
                payload={},
            )
        except Exception:
            pass
    reward_id = f"rew-{uuid.uuid4().hex[:10]}"
    await db.referral_rewards.insert_one({
        "id": reward_id,
        "company_id": cid,
        "owner_subscriber_id": ref["owner_subscriber_id"],
        "referral_id": ref["id"],
        "amount": REWARD_PER_INSTALL_BRL,
        "status": "available",
        "currency": "BRL",
        "source": "install",
        "metadata": {"owner_type": owner_type},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    logger.info("[referrals] reward R$ %s credited to owner=%s "
                  "(type=%s) ref=%s",
                  REWARD_PER_INSTALL_BRL, ref["owner_subscriber_id"],
                  owner_type, ref["id"])

    # ─── Multi-nível L2 só pra subscribers (R$ 10 ao "avô") ─────────────────
    if owner_type == "subscriber":
        direct_indicator = await db.subscribers.find_one(
            {"id": ref["owner_subscriber_id"]},
            {"_id": 0, "referred_by_subscriber_id": 1, "name": 1},
        )
        grandparent_id = (direct_indicator or {}).get("referred_by_subscriber_id")
        if grandparent_id:
            l2_reward_id = f"rew-{uuid.uuid4().hex[:10]}"
            await db.referral_rewards.insert_one({
                "id": l2_reward_id,
                "company_id": cid,
                "owner_subscriber_id": grandparent_id,
                "referral_id": ref["id"],
                "level": 2,
                "amount": LEVEL2_REWARD_BRL,
                "status": "available",
                "currency": "BRL",
                "source": "level2",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
            # Notifica o avô via WhatsApp Isabella Loop
            gp = await db.subscribers.find_one(
                {"id": grandparent_id}, {"_id": 0, "name": 1},
            )
            gp_first = ((gp or {}).get("name") or "").split()[0].title() or "Olá"
            direct_first = ((direct_indicator or {}).get("name") or "").split()[0].title() or "alguém"
            msg_l2 = (
                f"🎁 *{gp_first}*, ganho duplo!\n\n"
                f"O(a) *{direct_first}* (que você indicou) acabou de fazer "
                f"uma nova indicação que instalou. Você ganha *R$ "
                f"{LEVEL2_REWARD_BRL:.2f}* de bônus multi-nível por isso!\n\n"
                f"💸 Saldo Indique e Ganhe atualizado."
            )
            await _notify_referrer(cid, grandparent_id, msg_l2,
                                    meta={"event": "level2_credit",
                                          "referral_id": ref["id"]})
            logger.info("[referrals] L2 reward R$ %s credited to grandparent=%s",
                          LEVEL2_REWARD_BRL, grandparent_id)

    # ─── Isabella Loop #1: avisa o indicador que o amigo instalou ────────────
    # Busca em subscribers OU collaborators (depende do owner_type)
    if owner_type == "collaborator":
        owner = await db.collaborators.find_one(
            {"id": ref["owner_subscriber_id"]},
            {"_id": 0, "name": 1},
        )
    else:
        owner = await db.subscribers.find_one(
        {"id": ref["owner_subscriber_id"]},
        {"_id": 0, "name": 1},
    )
    owner_first = ((owner or {}).get("name") or "").split()[0].title() or "Olá"
    friend_first = (ref.get("friend_name") or "").split()[0].title() or "seu amigo"
    msg = (
        f"🎉 *{owner_first}*, ótima notícia! O(a) *{friend_first}* acabou de "
        f"instalar a fibra que você indicou.\n\n"
        f"💸 +R$ {REWARD_PER_INSTALL_BRL:.2f} foi creditado no seu saldo "
        f"do *Indique e Ganhe*.\n\n"
        f"Você pode resgatar via PIX no seu app: "
        f"{_app_link_for_cid(cid)}"
    )
    await _notify_referrer(cid, ref["owner_subscriber_id"], msg,
                            meta={"event": "install", "referral_id": ref["id"]})

    # ─── Isabella Loop #2: tier-up (subscribers) OU meta de R$ 500 (colaboradores) ───
    installs_count = await db.referrals.count_documents({
        "company_id": cid,
        "owner_subscriber_id": ref["owner_subscriber_id"],
        "status": "installed",
    })
    if owner_type == "collaborator":
        # Colaborador atingiu a META de 30 instalações → R$ 500 extras
        try:
            credited = await _maybe_credit_goal_bonus(
                cid, ref["owner_subscriber_id"], owner_type)
        except Exception as e:
            logger.warning("[referrals] goal bonus fail: %s", e)
            credited = None
        if credited:
            msg_goal = (
                f"🎉🏆 *{owner_first}*, META BATIDA!\n\n"
                f"Você acabou de atingir *{GOAL_TARGET_INSTALLS} instalações* "
                f"no Indique e Ganhe!\n\n"
                f"💰 *R$ {GOAL_BONUS_BRL:.0f} de bônus* foi creditado "
                f"no seu saldo. Fala com a equipe pra resgatar via PIX. 🚀"
            )
            await _notify_referrer(cid, ref["owner_subscriber_id"], msg_goal,
                                    meta={"event": "goal_reached",
                                          "target_installs": GOAL_TARGET_INSTALLS})
    else:
        tier = _tier_for(installs_count)
        if tier and tier["min_installs"] == installs_count:
            msg2 = (
                f"🏆 *{owner_first}*, você atingiu o nível *{tier['label']}* "
                f"({installs_count} instalações!).\n\n"
                f"Prêmio liberado: *{tier['prize']}*.\n\n"
                f"Vamos combinar a entrega — fala com a nossa equipe quando "
                f"quiser. 💎"
            )
            await _notify_referrer(cid, ref["owner_subscriber_id"], msg2,
                                    meta={"event": "tier_up",
                                          "tier_level": tier["level"]})

    # ─── Streak bonus: 4 semanas consecutivas com 1+ instalação ──────────────
    try:
        await _maybe_credit_streak_bonus(cid, ref["owner_subscriber_id"])
    except Exception as e:
        logger.warning("[referrals] streak bonus fail: %s", e)



# ═══════════════════════════════════════════════════════════════════════════
# Campanha de Indicação — Configuração (mensagem + imagem padrão)
# ═══════════════════════════════════════════════════════════════════════════
# Doc único por company_id em `referral_campaign_config`. Lido pelo app
# do cliente (sem auth de admin) para popular o ShareCard com a mensagem
# oficial + imagem da campanha; editado pelo admin via card no painel.

_DEFAULT_CAMPAIGN_IMAGE_URL = (
    "https://customer-assets.emergentagent.com/job_dual-combine-3/artifacts/"
    "3ylhpgb1_ligo%202026%2C%2022_12_17.png"
)
_DEFAULT_CAMPAIGN_MESSAGE = (
    "Eu já sou cliente LIGO e indico! 💜🧡\n\n"
    "Fala com a equipe pelo link que estou te mandando e pede a sua "
    "instalação também. Vale muito a pena!"
)


class CampaignConfigPayload(BaseModel):
    """Payload de PUT — apenas campos opcionais (parcial)."""
    message: Optional[str] = Field(default=None, max_length=2000)
    # Aceita data URL (base64, ~5MB max) OU URL http(s) público.
    image_data_url: Optional[str] = Field(default=None, max_length=8_000_000)


def _campaign_defaults() -> Dict[str, Any]:
    return {
        "message": _DEFAULT_CAMPAIGN_MESSAGE,
        "image_data_url": _DEFAULT_CAMPAIGN_IMAGE_URL,
        "is_default": True,
        "updated_at": None,
        "updated_by": None,
    }


@router.get("/referral-campaign/config")
async def get_referral_campaign_config(request: Request):
    """Retorna a config da campanha (mensagem + imagem padrão).

    Endpoint LEITURA pública (sem auth) — chamado pelo app do cliente.
    Multi-tenant: usa company_id do cliente logado se enviado via header
    `X-Company-Id`, senão cai no DEMO_COMPANY_ID.
    """
    cid = request.headers.get("X-Company-Id") or DEMO_COMPANY_ID
    doc = await db.referral_campaign_config.find_one(
        {"company_id": cid}, {"_id": 0, "company_id": 0},
    )
    if not doc:
        return _campaign_defaults()
    # Garante chaves essenciais (compat com docs antigos / parciais)
    defaults = _campaign_defaults()
    for k, v in defaults.items():
        doc.setdefault(k, v)
    doc["is_default"] = False
    return doc


@router.put("/referral-campaign/config")
async def put_referral_campaign_config(
    payload: CampaignConfigPayload,
    user=Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Atualiza mensagem e/ou imagem da campanha. Admin only."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update: Dict[str, Any] = {
        "updated_at": now_iso(),
        "updated_by": user.get("email"),
    }
    if payload.message is not None:
        msg = payload.message.strip()
        if not msg:
            raise HTTPException(400, "Mensagem não pode ser vazia.")
        update["message"] = msg
    if payload.image_data_url is not None:
        img = payload.image_data_url.strip()
        if img and not (img.startswith("data:image/")
                          or img.startswith("http://")
                          or img.startswith("https://")):
            raise HTTPException(400,
                "image_data_url deve ser data URL (data:image/...) ou http(s).")
        update["image_data_url"] = img
    if "message" not in update and "image_data_url" not in update:
        raise HTTPException(400, "Nada para atualizar.")

    await db.referral_campaign_config.update_one(
        {"company_id": cid},
        {"$set": {**update, "company_id": cid}},
        upsert=True,
    )
    doc = await db.referral_campaign_config.find_one(
        {"company_id": cid}, {"_id": 0, "company_id": 0},
    )
    defaults = _campaign_defaults()
    for k, v in defaults.items():
        doc.setdefault(k, v)
    doc["is_default"] = False
    return doc


@router.delete("/referral-campaign/config")
async def reset_referral_campaign_config(
    user=Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Restaura a campanha para os defaults de fábrica (mensagem + arte LIGO)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.referral_campaign_config.delete_one({"company_id": cid})
    return _campaign_defaults()
