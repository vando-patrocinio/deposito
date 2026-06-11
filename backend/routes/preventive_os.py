"""
iter215ab — Sistema de OS Preventivas (Rede IA enche grade ociosa).

Regra: cada técnico tem meta de N OS/dia (default 12). Quando a grade
do dia tem menos OS pendentes/abertas que a meta, a rede IA pega os
top M (default 3) clientes com pior sinal SmartOLT (1310nm) que ainda
não tenham OS aberta e cria bolhas tipo='preventiva' na fila do técnico.

Critérios de match cliente↔técnico (prioridade):
  1. Mesma cidade do colaborador (collaborator.city == subscriber via
     branch/metadata.city) — preferencial.
  2. Praça (collaborator.praca_id IN subscriber metadata.praca_id).
  3. Round-robin: distribui entre técnicos da mesma company que estão
     abaixo da meta.

Trigger: cron diário 08:30 BRT + botão manual "Gerar agora" no card.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from core import DEMO_COMPANY_ID, require_role

logger = logging.getLogger("preventive_os")
router = APIRouter(prefix="/api", tags=["preventive-os"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DEFAULTS = {
    "enabled": False,                  # opt-in: gestor liga manualmente
    "target_os_per_day": 12,           # meta por técnico
    "max_preventive_per_run": 3,       # bolhas criadas por técnico abaixo da meta
    "signal_threshold_dbm": -27.0,     # sinal crítico
    "min_signal_floor_dbm": -32.0,     # ignora sinais absurdos (loss/erro)
    "match_strategy": "city",          # "city" | "praca" | "any"
    "include_weekends": False,         # domingo/sábado não roda
    "scheduled_hour": "08:30",         # horário do cron BRT
    "active_status_only": True,        # só clientes ATIVOS
    "skip_with_open_ticket": True,     # pula clientes que já têm OS aberta
}


class PreventiveSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    target_os_per_day: Optional[int] = Field(None, ge=1, le=30)
    max_preventive_per_run: Optional[int] = Field(None, ge=1, le=10)
    signal_threshold_dbm: Optional[float] = Field(None, ge=-32, le=-15)
    min_signal_floor_dbm: Optional[float] = Field(None, ge=-40, le=-25)
    match_strategy: Optional[str] = None
    include_weekends: Optional[bool] = None
    scheduled_hour: Optional[str] = None


async def _get_settings(company_id: str) -> Dict[str, Any]:
    doc = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": "preventive_os"},
        {"_id": 0, "value": 1},
    )
    val = (doc or {}).get("value") or {}
    return {**DEFAULTS, **val}


@router.get("/preventive-os/settings")
async def get_settings(user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await _get_settings(company_id)


@router.put("/preventive-os/settings")
async def update_settings(
    payload: PreventiveSettingsIn,
    user: dict = Depends(require_role("gestor")),
):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    current = await _get_settings(company_id)
    incoming = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "match_strategy" in incoming and incoming["match_strategy"] not in (
            "city", "praca", "any"):
        raise HTTPException(400, "match_strategy deve ser city|praca|any")
    new_val = {**current, **incoming}
    await db.aihub_settings.update_one(
        {"company_id": company_id, "key": "preventive_os"},
        {"$set": {
            "value": new_val,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return new_val


# ---------------------------------------------------------------------------
# Core: find critical-signal candidates + collaborators below target
# ---------------------------------------------------------------------------
def _parse_signal_str(val: Any) -> Optional[float]:
    """SmartOLT retorna `signal_1310` como string (ex.: '-28.54'). Converte
    pra float. Retorna None se inválido ou nulo."""
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except Exception:
        return None


async def _today_iso_brt() -> str:
    """Data BRT (UTC-3) no formato YYYY-MM-DD."""
    now = datetime.now(timezone.utc) - timedelta(hours=3)
    return now.strftime("%Y-%m-%d")


async def _count_pending_today(collaborator_id: str, date_iso: str) -> int:
    """Conta OS pendentes/abertas do técnico na grade do dia.

    Considera 2 critérios:
      • `scheduled_time` no dia (LIKE 'YYYY-MM-DDT...').
      • Fila SEM scheduled_time (entram no dia atual por padrão).
    """
    q = {
        "assigned_collaborator_id": collaborator_id,
        "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        "$or": [
            {"scheduled_time": {"$regex": f"^{date_iso}"}},
            {"scheduled_time": {"$in": [None, ""]}},
        ],
    }
    return await db.tickets.count_documents(q)


async def _find_critical_signal_clients(
    company_id: str, threshold: float, floor: float,
    skip_subscriber_ids: List[str], limit: int,
) -> List[Dict[str, Any]]:
    """Retorna lista de clientes com pior sinal SmartOLT, do mais
    crítico (mais negativo) pro menos. Já enriquece com dados do
    subscriber matched via name (PPPoE → name fallback)."""
    # ONUs com signal_1310 numérico, online, dentro do range válido.
    candidates: List[Dict[str, Any]] = []
    seen = set(skip_subscriber_ids or [])
    cursor = db.smartolt_onus.find(
        {
            "company_id": company_id,
            "signal_1310": {"$exists": True, "$ne": None},
            "status": "Online",
        },
        {
            "_id": 0, "name": 1, "sn": 1, "mac": 1,
            "signal_1310": 1, "signal_1490": 1, "olt_name": 1,
            "address": 1, "subscriber_id": 1, "service_ports": 1,
        },
    )
    raw: List[Dict[str, Any]] = []
    async for o in cursor:
        s = _parse_signal_str(o.get("signal_1310"))
        if s is None:
            continue
        # threshold negativo: pega TUDO pior que -27 (ex: -28, -29)
        if s > threshold:
            continue
        # floor: ignora sinais absurdamente ruins (provavelmente erro)
        if s < floor:
            continue
        raw.append({**o, "_signal_float": s})
    raw.sort(key=lambda x: x["_signal_float"])  # pior primeiro
    # Resolve subscriber pra cada ONU (best-effort, batched)
    for o in raw[:limit * 4]:  # busca ~4x pra ter folga após filtros
        sub = None
        if o.get("subscriber_id"):
            sub = await db.subscribers.find_one(
                {"id": o["subscriber_id"], "company_id": company_id},
                {"_id": 0, "id": 1, "name": 1, "phone": 1, "city": 1,
                 "branch": 1, "metadata": 1, "pppoe_user": 1,
                 "status": 1, "address": 1, "neighborhood": 1,
                 "praca_id": 1, "external_code": 1},
            )
        # fallback: match por PPPoE no nome da ONU
        if not sub and o.get("name"):
            name_norm = (o.get("name") or "").lower()
            sub = await db.subscribers.find_one(
                {"company_id": company_id,
                 "pppoe_user": {"$regex": f"^{name_norm}",
                                "$options": "i"}},
                {"_id": 0, "id": 1, "name": 1, "phone": 1, "city": 1,
                 "branch": 1, "metadata": 1, "pppoe_user": 1,
                 "status": 1, "address": 1, "neighborhood": 1,
                 "praca_id": 1, "external_code": 1},
            )
        if not sub:
            continue
        if (sub.get("status") or "").upper() != "ATIVO":
            continue
        if sub["id"] in seen:
            continue
        candidates.append({
            "onu": o,
            "subscriber": sub,
            "signal_dbm": o["_signal_float"],
        })
        seen.add(sub["id"])
        if len(candidates) >= limit:
            break
    return candidates


async def _match_collaborator(
    candidate: Dict[str, Any],
    collabs_pool: List[Dict[str, Any]],
    strategy: str,
    rr_counter: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    """Escolhe técnico pra essa OS preventiva.
    iter215al — Cascata progressiva: cidade → praça → qualquer disponível.
    Garante que sempre que houver slots, alguém recebe a bolha (vs ficar
    sem match quando city/praca não batem)."""
    sub = candidate["subscriber"]
    sub_city = (sub.get("city") or (sub.get("metadata") or {}).get("city")
                or "").strip().lower()
    sub_praca = (sub.get("praca_id")
                 or (sub.get("metadata") or {}).get("praca_id"))

    # 1) Match exato por cidade
    if strategy != "any" and sub_city:
        matches = [c for c in collabs_pool
                    if (c.get("city") or "").strip().lower() == sub_city
                    and c["_slots_left"] > 0]
        if matches:
            matches.sort(key=lambda c: rr_counter.get(c["id"], 0))
            return matches[0]
    # 2) Match por praça
    if strategy != "any" and sub_praca:
        matches = [c for c in collabs_pool
                    if (c.get("praca_id") == sub_praca
                        or sub_praca in (c.get("praca_ids_extra") or []))
                    and c["_slots_left"] > 0]
        if matches:
            matches.sort(key=lambda c: rr_counter.get(c["id"], 0))
            return matches[0]
    # 3) Fallback: qualquer técnico com slot livre (round-robin)
    avail = [c for c in collabs_pool if c["_slots_left"] > 0]
    if avail:
        avail.sort(key=lambda c: rr_counter.get(c["id"], 0))
        return avail[0]
    return None


async def _create_preventive_ticket(
    *, company_id: str, date_iso: str, candidate: Dict[str, Any],
    collaborator: Dict[str, Any], actor_email: str,
) -> Dict[str, Any]:
    sub = candidate["subscriber"]
    signal = candidate["signal_dbm"]
    onu = candidate["onu"]
    # próxima posição na fila
    last = await db.tickets.find(
        {"assigned_collaborator_id": collaborator["id"],
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "position": 1},
    ).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 0
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": ticket_id,
        "client_id": sub["id"],
        "client_snapshot": {
            "id": sub["id"],
            "name": sub.get("name"),
            "address": sub.get("address") or onu.get("address") or "",
            "neighborhood": sub.get("neighborhood") or "",
            "phone": sub.get("phone") or "",
            "latitude": None, "longitude": None,
            "relato": (f"OS PREVENTIVA — Sinal crítico {signal:.2f}dBm "
                       f"(ONU {onu.get('name') or onu.get('sn')}). "
                       f"Visita preventiva pra evitar churn."),
            "pppoe_user": sub.get("pppoe_user") or "",
            "external_code": sub.get("external_code"),
            "test_history": [],
        },
        "type": "preventiva",
        "priority": "normal",
        "scheduled_time": f"{date_iso}T10:00",  # default 10h, ajustável
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": collaborator["id"],
        "company_id": company_id,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "ai_triage_pending": False,
        "signal_at_open": {
            "signal_1310": onu.get("signal_1310"),
            "signal_1490": onu.get("signal_1490"),
            "onu_name": onu.get("name"),
            "onu_sn": onu.get("sn"),
            "olt_name": onu.get("olt_name"),
        },
        "signal_at_open_at": datetime.now(timezone.utc).isoformat(),
        "signal_at_close": None,
        "signal_at_close_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Metadados de origem
        "origin": "preventive_auto",
        "origin_meta": {
            "source": "preventive_os_cron",
            "signal_dbm_at_creation": signal,
            "generated_by": actor_email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    # SALA-routing — preventiva auto cai em SALA (11/02/2026).
    from services.sala_router import route_to_sala
    await route_to_sala(doc, reason="preventive_auto",
                          original_tech_suggested=collaborator["id"])
    await db.tickets.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _gather_collaborator_pool(
    company_id: str, date_iso: str, target: int,
    only_collaborator_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista colaboradores ativos com slots restantes (target - já_na_grade).
    iter215al — Match de role flexível: pega qualquer colaborador cuja
    role contenha 'tecnic', 'reparador' ou 'instalador' (case-insensitive).
    Cobre variantes: Tecnico, Técnico, Técnico (Atlaz), Reparador
    Instalador, técnico minúsculo, etc."""
    base_q = {"company_id": company_id, "active": True}
    if only_collaborator_id:
        base_q = {"id": only_collaborator_id}
    pool: List[Dict[str, Any]] = []
    async for c in db.collaborators.find(base_q, {
        "_id": 0, "id": 1, "name": 1, "city": 1, "praca_id": 1,
        "praca_ids_extra": 1, "company_id": 1, "active": 1, "role": 1,
    }):
        if not c.get("active"):
            continue
        role_lc = (c.get("role") or "").lower()
        # Filtra só técnicos/reparadores/instaladores. Excluir admin,
        # auxiliares, inbox, etc.
        is_tech = any(s in role_lc for s in
                       ("tecnic", "técnic", "reparador", "instalador"))
        if not is_tech and not only_collaborator_id:
            continue
        pending = await _count_pending_today(c["id"], date_iso)
        slots = max(0, target - pending)
        c["_pending_today"] = pending
        c["_slots_left"] = slots
        pool.append(c)
    return pool


async def _generate_for_company(
    company_id: str, *, dry_run: bool = False,
    actor_email: str = "system",
    only_collaborator_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Job principal — roda 1x/dia OU sob demanda.

    iter215al — `force=True` (botão manual do gestor) ignora weekend e
    sobrescreve `enabled=false`. Cron diário usa force=False (respeita
    config de fim de semana e habilitação)."""
    settings = await _get_settings(company_id)
    if not dry_run and not force and not settings.get("enabled"):
        return {"skipped": True, "reason": "disabled", "settings": settings}

    date_iso = await _today_iso_brt()
    # weekend check (só pra dry_run + cron — botão manual ignora)
    if not force and not settings.get("include_weekends"):
        dow = datetime.fromisoformat(date_iso).weekday()  # 5=sáb 6=dom
        if dow >= 5 and not dry_run:
            return {"skipped": True, "reason": "weekend",
                    "date": date_iso, "weekday": dow}

    target = int(settings.get("target_os_per_day") or 12)
    max_add = int(settings.get("max_preventive_per_run") or 3)
    threshold = float(settings.get("signal_threshold_dbm") or -27.0)
    floor = float(settings.get("min_signal_floor_dbm") or -32.0)
    strategy = settings.get("match_strategy") or "city"

    pool = await _gather_collaborator_pool(
        company_id, date_iso, target, only_collaborator_id)
    # Calcula quantos slots disponíveis (limit max_add por técnico)
    for c in pool:
        c["_max_create"] = min(c["_slots_left"], max_add)
    total_slots = sum(c["_max_create"] for c in pool)
    if total_slots <= 0:
        return {
            "skipped": True, "reason": "no_slots_available",
            "date": date_iso,
            "collaborators": [{
                "id": c["id"], "name": c.get("name"),
                "pending_today": c["_pending_today"],
                "slots_left": c["_slots_left"],
            } for c in pool],
        }

    # Lista clientes que já têm OS aberta para excluir
    skip_sub_ids: List[str] = []
    async for t in db.tickets.find(
        {"company_id": company_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "client_snapshot.id": 1, "client_id": 1},
    ):
        cs = (t.get("client_snapshot") or {})
        if cs.get("id"):
            skip_sub_ids.append(cs["id"])

    candidates = await _find_critical_signal_clients(
        company_id, threshold, floor, skip_sub_ids,
        limit=max(total_slots * 2, 10),
    )

    # Distribui candidatos entre técnicos
    rr_counter: Dict[str, int] = {c["id"]: 0 for c in pool}
    created: List[Dict[str, Any]] = []
    preview_only: List[Dict[str, Any]] = []
    for cand in candidates:
        # iter215al — Filtra pool pelos técnicos que ainda têm cota
        # `_max_create` antes de chamar o matcher. Garante que
        # max_preventive_per_run é respeitado por técnico.
        available_pool = [c for c in pool
                          if c.get("_max_create", 0) > 0
                          and c.get("_slots_left", 0) > 0]
        if not available_pool:
            break
        coll = await _match_collaborator(
            cand, available_pool, strategy, rr_counter)
        if not coll:
            break
        rr_counter[coll["id"]] = rr_counter.get(coll["id"], 0) + 1
        coll["_slots_left"] -= 1
        coll["_max_create"] -= 1
        item = {
            "collaborator_id": coll["id"],
            "collaborator_name": coll.get("name"),
            "subscriber_id": cand["subscriber"]["id"],
            "subscriber_name": cand["subscriber"].get("name"),
            "signal_dbm": cand["signal_dbm"],
            "onu_name": cand["onu"].get("name"),
            "onu_sn": cand["onu"].get("sn"),
        }
        if dry_run:
            preview_only.append(item)
        else:
            t = await _create_preventive_ticket(
                company_id=company_id, date_iso=date_iso,
                candidate=cand, collaborator=coll,
                actor_email=actor_email,
            )
            item["ticket_id"] = t["id"]
            created.append(item)

    summary = {
        "company_id": company_id,
        "date": date_iso,
        "target_os_per_day": target,
        "max_preventive_per_run": max_add,
        "signal_threshold_dbm": threshold,
        "candidates_found": len(candidates),
        "total_slots_available": total_slots,
        "collaborators_in_pool": [{
            "id": c["id"], "name": c.get("name"),
            "city": c.get("city"),
            "pending_today": c["_pending_today"],
            "slots_left_after_run": c["_slots_left"],
        } for c in pool],
        "dry_run": dry_run,
        "created": created if not dry_run else [],
        "would_create": preview_only if dry_run else [],
    }
    if not dry_run:
        # Log persistente
        await db.preventive_os_runs.insert_one({
            "id": f"prevrun-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "date": date_iso,
            "actor_email": actor_email,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "summary": {**summary, "created_count": len(created)},
        })
    return summary


# ---------------------------------------------------------------------------
# Endpoints (gestor only)
# ---------------------------------------------------------------------------
@router.post("/preventive-os/preview")
async def preview_run(user: dict = Depends(require_role("gestor"))):
    """Simula sem criar — mostra o que seria gerado hoje."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await _generate_for_company(
        company_id, dry_run=True,
        actor_email=user.get("email") or "preview",
    )


@router.post("/preventive-os/run-now")
async def run_now(user: dict = Depends(require_role("gestor"))):
    """Roda agora (cria as bolhas). Botão manual → ignora weekend e
    sobrescreve `enabled=false` (gestor sabe o que está fazendo)."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await _generate_for_company(
        company_id, dry_run=False, force=True,
        actor_email=user.get("email") or "manual",
    )


@router.get("/preventive-os/history")
async def history(
    limit: int = 30,
    user: dict = Depends(require_role("gestor")),
):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    rows: List[Dict[str, Any]] = []
    async for r in db.preventive_os_runs.find(
        {"company_id": company_id},
        {"_id": 0, "id": 1, "date": 1, "ran_at": 1, "actor_email": 1,
         "summary.created_count": 1, "summary.candidates_found": 1,
         "summary.total_slots_available": 1,
         "summary.dry_run": 1},
    ).sort("ran_at", -1).limit(min(limit, 200)):
        rows.append(r)
    return {"items": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Cron worker — chamado por server.py no startup
# ---------------------------------------------------------------------------
async def preventive_os_daily_worker():
    """Loop infinito: checa a cada minuto se é hora de rodar (08:30 BRT)
    pra cada company com preventive_os.enabled=True. Idempotente — não
    roda 2x no mesmo dia pra mesma company."""
    import asyncio
    logger.info("[preventive-os] worker iniciado")
    last_run_date: Dict[str, str] = {}
    while True:
        try:
            now_brt = datetime.now(timezone.utc) - timedelta(hours=3)
            hhmm = now_brt.strftime("%H:%M")
            date_iso = now_brt.strftime("%Y-%m-%d")
            # Lê todas as configs ativas
            async for cfg in db.aihub_settings.find(
                {"key": "preventive_os", "value.enabled": True},
                {"_id": 0, "company_id": 1, "value": 1},
            ):
                cid = cfg["company_id"]
                target_hour = (cfg.get("value") or {}).get(
                    "scheduled_hour") or "08:30"
                if hhmm != target_hour:
                    continue
                if last_run_date.get(cid) == date_iso:
                    continue
                try:
                    summary = await _generate_for_company(
                        cid, dry_run=False, actor_email="cron_daily")
                    logger.info("[preventive-os] cron company=%s created=%d",
                                cid, len(summary.get("created", [])))
                    last_run_date[cid] = date_iso
                except Exception as e:
                    logger.exception(
                        "[preventive-os] cron company=%s falhou: %s", cid, e)
        except Exception as e:
            logger.exception("[preventive-os] worker erro: %s", e)
        await asyncio.sleep(60)  # check a cada 1min
