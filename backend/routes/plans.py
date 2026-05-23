"""Planos comerciais do provedor (ISP) — CRUD usado em Clientes.

Cada plano tem velocidade, valor mensal e percentual de acréscimo anual de
inflação (reajuste contratual). É referenciado por `plan_id` no subscriber.

Coleção: `plans` — {id, company_id, name, speed_label, speed_down_mbps,
                     speed_up_mbps, monthly_price, annual_adjustment_pct,
                     description, active, created_at, updated_at}.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.plans")
router = APIRouter(prefix="/api/plans", tags=["plans"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PlanIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    speed_label: Optional[str] = Field(default=None, max_length=40)
    speed_down_mbps: Optional[int] = Field(default=None, ge=1, le=100000)
    speed_up_mbps: Optional[int] = Field(default=None, ge=1, le=100000)
    monthly_price: float = Field(..., ge=0)
    annual_adjustment_pct: float = Field(default=0, ge=0, le=100)
    description: Optional[str] = Field(default=None, max_length=600)
    active: bool = True
    # Premium gating — array de features que esse plano libera. Drive de upsell.
    # Atualmente reconhecidas: "wifi_self_service" (troca SSID/senha via UI ou
    # WhatsApp), "speed_test_remote", "static_ip", "vpn_access", "priority_support".
    premium_features: List[str] = Field(default_factory=list)


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    speed_label: Optional[str] = None
    speed_down_mbps: Optional[int] = None
    speed_up_mbps: Optional[int] = None
    monthly_price: Optional[float] = None
    annual_adjustment_pct: Optional[float] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    premium_features: Optional[List[str]] = None


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _derive_speed_label(payload_dict: dict) -> Optional[str]:
    """Se o usuário não informou label, deriva de speed_down_mbps."""
    label = payload_dict.get("speed_label")
    if label:
        return label
    mb = payload_dict.get("speed_down_mbps")
    if mb:
        if mb >= 1000 and mb % 1000 == 0:
            return f"{mb // 1000} Giga"
        return f"{mb} Mega"
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
async def list_plans(
    active: Optional[bool] = None,
    user: dict = Depends(require_role("gestor")),
):
    cid = _cid(user)
    flt: Dict = {"company_id": cid}
    if active is not None:
        flt["active"] = active
    rows = await db.plans.find(flt, {"_id": 0}).sort("monthly_price", 1).to_list(500)
    return {"items": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Rotas ESTÁTICAS (precisam vir antes das parametrizadas `/{plan_id}`
# para FastAPI não tratar 'scheduled-adjustments' como id).
# ---------------------------------------------------------------------------
@router.get("/scheduled-adjustments")
async def list_scheduled_adjustments(status: Optional[str] = None,
                                      user: dict = Depends(require_role("gestor"))):
    """Lista todos os reajustes agendados (filtráveis por status)."""
    cid = _cid(user)
    flt: Dict = {"company_id": cid}
    if status:
        flt["status"] = status
    rows = await db.plan_adjustments_scheduled.find(
        flt, {"_id": 0}).sort("scheduled_for", 1).to_list(200)
    return {"items": rows, "count": len(rows)}


@router.delete("/scheduled-adjustments/{sch_id}")
async def cancel_scheduled_adjustment(sch_id: str,
                                       user: dict = Depends(require_role("administrador"))):
    """Cancela um reajuste agendado (só funciona se ainda `pending`)."""
    cid = _cid(user)
    doc = await db.plan_adjustments_scheduled.find_one(
        {"company_id": cid, "id": sch_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Agendamento não encontrado.")
    if doc.get("status") != "pending":
        raise HTTPException(409,
            f"Não é possível cancelar — status atual: {doc.get('status')}.")
    await db.plan_adjustments_scheduled.update_one(
        {"company_id": cid, "id": sch_id},
        {"$set": {"status": "cancelled",
                   "cancelled_at": now_iso(),
                   "cancelled_by": user.get("email") or user.get("id")}})
    return {"ok": True, "id": sch_id, "status": "cancelled"}


@router.post("")
async def create_plan(payload: PlanIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    # Não permite nome duplicado por empresa
    existing = await db.plans.find_one(
        {"company_id": cid, "name": payload.name})
    if existing:
        raise HTTPException(409, f"Já existe plano com nome '{payload.name}'.")
    doc = payload.model_dump()
    doc["speed_label"] = _derive_speed_label(doc)
    doc.update({
        "id": f"plan-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("email") or user.get("id"),
    })
    await db.plans.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/{plan_id}")
async def get_plan(plan_id: str,
                    user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    p = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Plano não encontrado.")
    return p


@router.put("/{plan_id}")
async def update_plan(plan_id: str, payload: PlanUpdate,
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    p = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Plano não encontrado.")
    update_fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "name" in update_fields and update_fields["name"] != p.get("name"):
        existing = await db.plans.find_one(
            {"company_id": cid, "name": update_fields["name"],
             "id": {"$ne": plan_id}})
        if existing:
            raise HTTPException(409, "Já existe outro plano com esse nome.")
    if "speed_down_mbps" in update_fields and not update_fields.get("speed_label"):
        update_fields["speed_label"] = _derive_speed_label(update_fields)
    update_fields["updated_at"] = now_iso()
    update_fields["updated_by"] = user.get("email") or user.get("id")
    await db.plans.update_one(
        {"company_id": cid, "id": plan_id}, {"$set": update_fields})
    p2 = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    return p2


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str,
                       user: dict = Depends(require_role("administrador"))):
    cid = _cid(user)
    # Bloqueia exclusão se há assinantes usando o plano
    using = await db.subscribers.count_documents(
        {"company_id": cid, "plan_id": plan_id})
    if using > 0:
        raise HTTPException(409,
                            f"{using} assinante(s) usam esse plano. "
                            "Inative o plano ou migre-os antes de excluir.")
    result = await db.plans.delete_one(
        {"company_id": cid, "id": plan_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Plano não encontrado.")
    return {"ok": True, "deleted_id": plan_id}


# ---------------------------------------------------------------------------
# Simulador de reajuste anual
# ---------------------------------------------------------------------------
class AdjustmentIn(BaseModel):
    """Override opcional do percentual. Default usa o plan.annual_adjustment_pct."""
    pct_override: Optional[float] = Field(default=None, ge=0, le=100)
    only_active_subscribers: bool = True


def _active_status_filter(only_active: bool) -> dict:
    """Subscribers em status comerciais (que pagam mensalidade) quando filtrado."""
    if not only_active:
        return {}
    return {"status": {"$in": ["ATIVO", "INADIMPLENTE", "EM_INSTALACAO"]}}


@router.post("/{plan_id}/adjustment/preview")
async def preview_adjustment(plan_id: str, payload: AdjustmentIn = AdjustmentIn(),
                              user: dict = Depends(require_role("gestor"))):
    """Calcula impacto do reajuste SEM aplicar. Retorna assinantes afetados,
    receita atual, nova receita e delta mensal/anual."""
    cid = _cid(user)
    plan = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plano não encontrado.")

    pct = payload.pct_override if payload.pct_override is not None \
        else float(plan.get("annual_adjustment_pct") or 0)
    if pct <= 0:
        raise HTTPException(400, "Percentual de reajuste deve ser maior que zero. "
                                 "Configure o reajuste anual no plano ou passe pct_override.")

    current_price = float(plan.get("monthly_price") or 0)
    new_price = round(current_price * (1 + pct / 100), 2)
    delta_per_subscriber = round(new_price - current_price, 2)

    sub_filter = {"company_id": cid, "plan_id": plan_id,
                   **_active_status_filter(payload.only_active_subscribers)}
    affected = await db.subscribers.count_documents(sub_filter)

    # Amostra de até 8 assinantes para exibir no modal
    sample = []
    async for s in db.subscribers.find(
            sub_filter,
            {"_id": 0, "id": 1, "name": 1, "external_code": 1,
             "nickname": 1, "branch": 1, "status": 1}).limit(8):
        sample.append(s)

    current_monthly = round(current_price * affected, 2)
    new_monthly = round(new_price * affected, 2)
    delta_monthly = round(new_monthly - current_monthly, 2)

    return {
        "plan": {"id": plan["id"], "name": plan["name"],
                  "speed_label": plan.get("speed_label"),
                  "current_price": current_price,
                  "configured_pct": plan.get("annual_adjustment_pct") or 0},
        "pct_applied": pct,
        "new_price": new_price,
        "delta_per_subscriber": delta_per_subscriber,
        "affected_subscribers": affected,
        "only_active_subscribers": payload.only_active_subscribers,
        "current_monthly_revenue": current_monthly,
        "new_monthly_revenue": new_monthly,
        "delta_monthly_revenue": delta_monthly,
        "delta_annual_revenue": round(delta_monthly * 12, 2),
        "sample_subscribers": sample,
    }


@router.post("/{plan_id}/adjustment/apply")
async def apply_adjustment(plan_id: str, payload: AdjustmentIn = AdjustmentIn(),
                            user: dict = Depends(require_role("administrador"))):
    """Aplica o reajuste: atualiza `monthly_price` no plano e o snapshot
    `plan_price` em todos os assinantes daquele plano. Registra a operação
    em `plan_adjustments_log` para auditoria."""
    cid = _cid(user)
    plan = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plano não encontrado.")

    pct = payload.pct_override if payload.pct_override is not None \
        else float(plan.get("annual_adjustment_pct") or 0)
    if pct <= 0:
        raise HTTPException(400, "Percentual de reajuste deve ser maior que zero.")

    current_price = float(plan.get("monthly_price") or 0)
    new_price = round(current_price * (1 + pct / 100), 2)

    sub_filter = {"company_id": cid, "plan_id": plan_id,
                   **_active_status_filter(payload.only_active_subscribers)}
    affected = await db.subscribers.count_documents(sub_filter)

    # 1) Atualiza preço do plano
    await db.plans.update_one(
        {"company_id": cid, "id": plan_id},
        {"$set": {"monthly_price": new_price,
                   "last_adjustment_at": now_iso(),
                   "last_adjustment_pct": pct,
                   "updated_at": now_iso(),
                   "updated_by": user.get("email") or user.get("id")}})

    # 2) Atualiza snapshot nos assinantes
    if affected > 0:
        await db.subscribers.update_many(
            sub_filter,
            {"$set": {"plan_price": new_price, "updated_at": now_iso()}})

    # 3) Registra operação no log
    log_doc = {
        "id": f"padj-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "plan_id": plan_id,
        "plan_name": plan.get("name"),
        "previous_price": current_price,
        "new_price": new_price,
        "pct_applied": pct,
        "affected_subscribers": affected,
        "only_active": payload.only_active_subscribers,
        "applied_at": now_iso(),
        "applied_by": user.get("email") or user.get("id"),
        "applied_by_name": user.get("name"),
    }
    await db.plan_adjustments_log.insert_one(dict(log_doc))
    log_doc.pop("_id", None)

    return {"ok": True, **log_doc}


@router.get("/{plan_id}/adjustment/history")
async def adjustment_history(plan_id: str,
                              user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    rows = await db.plan_adjustments_log.find(
        {"company_id": cid, "plan_id": plan_id}, {"_id": 0}
    ).sort("applied_at", -1).limit(20).to_list(20)
    return {"items": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Reajustes AGENDADOS — aplicação automática em data futura.
# ---------------------------------------------------------------------------
class ScheduleAdjustmentIn(BaseModel):
    """`scheduled_for` é uma data ISO (YYYY-MM-DD ou ISO completo).
    Marco Civil exige aviso de 30 dias — `min_days` valida isso."""
    scheduled_for: str = Field(..., description="ISO date (ex 2026-06-01)")
    pct_override: Optional[float] = Field(default=None, ge=0, le=100)
    only_active_subscribers: bool = True
    min_days: Optional[int] = Field(default=None, ge=0, le=365,
                                      description="Bloqueia se data está a menos de X dias")
    note: Optional[str] = Field(default=None, max_length=400)


@router.post("/{plan_id}/adjustment/schedule")
async def schedule_adjustment(plan_id: str, payload: ScheduleAdjustmentIn,
                               user: dict = Depends(require_role("administrador"))):
    """Agenda um reajuste pra data futura. Worker aplica automaticamente
    quando chegar a data. Pode ser cancelado antes via DELETE."""
    cid = _cid(user)
    plan = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plano não encontrado.")

    # Valida data
    try:
        # Aceita YYYY-MM-DD ou ISO completo
        d_part = payload.scheduled_for.split("T")[0]
        target_date = datetime.fromisoformat(d_part).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Data inválida. Use YYYY-MM-DD.") from exc

    now = datetime.now(timezone.utc)
    days_ahead = (target_date - now).days
    if days_ahead < 0:
        raise HTTPException(400, "A data agendada está no passado.")
    if payload.min_days is not None and days_ahead < payload.min_days:
        raise HTTPException(400,
            f"Marco Civil exige aviso prévio de {payload.min_days} dias. "
            f"A data agendada está a apenas {days_ahead} dias.")

    pct = payload.pct_override if payload.pct_override is not None \
        else float(plan.get("annual_adjustment_pct") or 0)
    if pct <= 0:
        raise HTTPException(400, "Percentual de reajuste deve ser maior que zero.")

    doc = {
        "id": f"psch-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "plan_id": plan_id,
        "plan_name": plan.get("name"),
        "scheduled_for": target_date.isoformat(),
        "pct": pct,
        "only_active_subscribers": payload.only_active_subscribers,
        "note": payload.note,
        "status": "pending",  # pending → applied | cancelled | failed
        "created_at": now_iso(),
        "created_by": user.get("email") or user.get("id"),
        "created_by_name": user.get("name"),
    }
    await db.plan_adjustments_scheduled.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"ok": True, **doc}


async def _apply_scheduled(sched: dict) -> bool:
    """Aplica um agendamento (chamado pelo worker). Retorna True se ok."""
    cid = sched["company_id"]
    plan_id = sched["plan_id"]
    pct = float(sched["pct"])
    only_active = bool(sched.get("only_active_subscribers", True))

    plan = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not plan:
        await db.plan_adjustments_scheduled.update_one(
            {"id": sched["id"]},
            {"$set": {"status": "failed", "failed_at": now_iso(),
                       "failure_reason": "Plano não existe mais."}})
        return False

    current_price = float(plan.get("monthly_price") or 0)
    new_price = round(current_price * (1 + pct / 100), 2)
    sub_filter = {"company_id": cid, "plan_id": plan_id,
                   **_active_status_filter(only_active)}
    affected = await db.subscribers.count_documents(sub_filter)

    await db.plans.update_one(
        {"company_id": cid, "id": plan_id},
        {"$set": {"monthly_price": new_price,
                   "last_adjustment_at": now_iso(),
                   "last_adjustment_pct": pct,
                   "updated_at": now_iso()}})
    if affected > 0:
        await db.subscribers.update_many(
            sub_filter,
            {"$set": {"plan_price": new_price, "updated_at": now_iso()}})

    # Log no log normal + marca o agendamento como applied
    log_doc = {
        "id": f"padj-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "plan_id": plan_id,
        "plan_name": plan.get("name"),
        "previous_price": current_price, "new_price": new_price,
        "pct_applied": pct, "affected_subscribers": affected,
        "only_active": only_active,
        "applied_at": now_iso(),
        "applied_by": "scheduler",
        "applied_by_name": "Reajuste agendado",
        "scheduled_id": sched["id"],
    }
    await db.plan_adjustments_log.insert_one(dict(log_doc))
    await db.plan_adjustments_scheduled.update_one(
        {"id": sched["id"]},
        {"$set": {"status": "applied", "applied_at": now_iso(),
                   "applied_log_id": log_doc["id"],
                   "applied_new_price": new_price,
                   "applied_affected": affected}})
    logger.info("[plans] Reajuste agendado %s aplicado: %s → %s (%d clientes)",
                sched["id"], current_price, new_price, affected)
    return True


async def adjustment_scheduler_worker():
    """Worker em background. A cada 5min verifica pendentes vencidos e aplica."""
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            due = []
            async for s in db.plan_adjustments_scheduled.find(
                    {"status": "pending", "scheduled_for": {"$lte": now}},
                    {"_id": 0}):
                due.append(s)
            for sched in due:
                try:
                    await _apply_scheduled(sched)
                except Exception:
                    logger.exception("[plans] Erro aplicando agendamento %s",
                                       sched.get("id"))
                    await db.plan_adjustments_scheduled.update_one(
                        {"id": sched["id"]},
                        {"$set": {"status": "failed", "failed_at": now_iso()}})
        except Exception:
            logger.exception("[plans] Erro no worker de agendamentos")
        await asyncio.sleep(300)  # 5min


# ---------------------------------------------------------------------------
# Notificação WhatsApp do reajuste agendado (cumpre aviso prévio contratual)
# ---------------------------------------------------------------------------
class NotifyAdjustmentIn(BaseModel):
    template: Optional[str] = Field(default=None, max_length=1200,
        description="Custom template (usa placeholders {nome}, {plano}, {valor_atual}, {valor_novo}, {pct}, {data})")
    dry_run: bool = False


@router.post("/scheduled-adjustments/{sch_id}/notify")
async def notify_scheduled_adjustment(sch_id: str,
                                       payload: NotifyAdjustmentIn = NotifyAdjustmentIn(),
                                       user: dict = Depends(require_role("administrador"))):
    """Envia mensagem WhatsApp de aviso prévio a todos os assinantes
    afetados pelo reajuste agendado. Marca o agendamento com
    `notified_at` quando envia. Pode ser executado mais de uma vez se
    quiser reforçar (mas grava no log)."""
    cid = _cid(user)
    sched = await db.plan_adjustments_scheduled.find_one(
        {"company_id": cid, "id": sch_id}, {"_id": 0})
    if not sched:
        raise HTTPException(404, "Agendamento não encontrado.")
    if sched.get("status") != "pending":
        raise HTTPException(409,
            f"Só pode notificar agendamentos PENDING. Status atual: {sched.get('status')}.")

    plan = await db.plans.find_one(
        {"company_id": cid, "id": sched["plan_id"]}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plano do agendamento foi excluído.")

    pct = float(sched["pct"])
    current_price = float(plan.get("monthly_price") or 0)
    new_price = round(current_price * (1 + pct / 100), 2)
    sch_date = sched["scheduled_for"][:10]
    only_active = bool(sched.get("only_active_subscribers", True))

    template = payload.template or (
        "Olá, {nome}! 👋\n\n"
        "Conforme cláusula contratual de reajuste anual, sua mensalidade do "
        "plano *{plano}* será ajustada em *{data}*:\n\n"
        "💰 De *R$ {valor_atual}* para *R$ {valor_novo}* (reajuste de +{pct}%)\n\n"
        "Este é o aviso prévio (mínimo 30 dias) exigido por contrato. "
        "Em caso de dúvidas, é só chamar aqui no WhatsApp! 😊"
    )

    sub_filter = {"company_id": cid, "plan_id": sched["plan_id"],
                   **_active_status_filter(only_active)}
    subs = []
    async for s in db.subscribers.find(sub_filter,
            {"_id": 0, "id": 1, "name": 1, "nickname": 1, "external_code": 1}):
        subs.append(s)

    sent = 0
    failed = 0
    skipped_no_phone = 0
    sent_to = []

    # Importa lazy para evitar ciclo
    from routes.whatsapp_baileys import SIDECAR_BASE
    import httpx

    for sub in subs:
        # Pega telefone primário
        phone_doc = await db.subscriber_phones.find_one(
            {"company_id": cid, "subscriber_id": sub["id"], "is_primary": True},
            {"_id": 0, "normalized_number": 1})
        if not phone_doc:
            skipped_no_phone += 1
            continue
        phone = phone_doc["normalized_number"]
        nome = sub.get("nickname") or (sub.get("name") or "").split()[0] or "Cliente"
        body = template.format(
            nome=nome,
            plano=plan["name"],
            valor_atual=f"{current_price:.2f}".replace(".", ","),
            valor_novo=f"{new_price:.2f}".replace(".", ","),
            pct=f"{pct:g}",
            data=datetime.fromisoformat(sch_date).strftime("%d/%m/%Y"),
        )

        if payload.dry_run:
            sent_to.append({"phone": phone, "name": sub.get("name"),
                              "preview": body[:80]})
            continue

        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.post(f"{SIDECAR_BASE}/send",
                                    json={"phone": phone, "text": body})
                if r.status_code == 200 and r.json().get("ok"):
                    sent += 1
                    sent_to.append({"phone": phone, "name": sub.get("name")})
                    # Grava no log de mensagens da Lousa
                    await db.aihub_wa_messages.insert_one({
                        "company_id": cid, "phone": phone,
                        "jid": f"{phone}@s.whatsapp.net",
                        "direction": "outbound",
                        "text": body,
                        "created_at": now_iso(),
                        "auto_reply": False,
                        "sent_by_user_id": user.get("id"),
                        "subscriber_id": sub["id"],
                        "context": "adjustment_notice",
                        "scheduled_id": sch_id,
                    })
                else:
                    failed += 1
        except Exception:
            failed += 1
            logger.exception("[plans] Falha enviando notice WA pra %s", phone)

    if not payload.dry_run:
        await db.plan_adjustments_scheduled.update_one(
            {"id": sch_id, "company_id": cid},
            {"$set": {
                "notified_at": now_iso(),
                "notified_by": user.get("email") or user.get("id"),
                "notified_count": sent,
                "notified_failed": failed,
                "notified_skipped_no_phone": skipped_no_phone,
            }})

    return {
        "ok": True, "dry_run": payload.dry_run,
        "total_subscribers": len(subs),
        "sent": sent, "failed": failed,
        "skipped_no_phone": skipped_no_phone,
        "sent_to": sent_to[:20],
    }


# ---------------------------------------------------------------------------
# Helper: hidrata plano dentro de subscriber (usado por subscribers.py)
# ---------------------------------------------------------------------------
async def get_plan_dict(company_id: str, plan_id: Optional[str]) -> Optional[dict]:
    if not plan_id:
        return None
    return await db.plans.find_one(
        {"company_id": company_id, "id": plan_id}, {"_id": 0})
