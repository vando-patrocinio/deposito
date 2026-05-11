"""Backend do Ponto do Colaborador — orquestrador thin.

Endpoints estão organizados em /app/backend/routes/:
  - users.py      → /api/auth/* + /api/users/*
  - pracas.py     → /api/pracas/*
  - clock.py      → /api/collaborators/*, /api/geofences/*, /api/clock-records/*,
                    /api/timesheets/*, /api/dashboard/overtime/{year}/{month}
  - locations.py  → /api/locations/*
  - dashboard.py  → /api/dashboard/overtime/trend, range, dwell-heatmap
  - admin.py      → /api/settings, /api/email/*, /api/scheduler/*, /api/holidays/*,
                    /api/system/*, /api/geocode*

Helpers compartilhados em core.py; cliente Mongo em database.py;
push (VAPID + envio) em push_service.py.

Aqui ficam apenas: criação do app, lifecycle, scheduler, jobs e CORS.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from auth import ensure_auth_indexes, seed_default_users
from core import now_iso  # noqa: F401  (mantém para compat eventual)
from database import db, mongo_client as client
from push_service import (
    broadcast_dwell_alerts,
    ensure_push_indexes,
    get_or_create_vapid,
)
from routes import (
    admin as routes_admin,
    atlaz as routes_atlaz,
    clock as routes_clock,
    collab_auth as routes_collab_auth,
    dashboard as routes_dashboard,
    events as routes_events,
    locations as routes_locations,
    logs as routes_logs,
    lousa as routes_lousa,
    pracas as routes_pracas,
    push as routes_push,
    saas as routes_saas,
    smartolt as routes_smartolt,
    ai_preventive as routes_ai_preventive,
    ai_dashboard as routes_ai_dashboard,
    aihub as routes_aihub,
    motor_ia as routes_motor_ia,
    smartolt_ai as routes_smartolt_ai,
    ai_topology as routes_ai_topology,
    copilot_ranking as routes_copilot_ranking,
    plans as routes_plans,
    voice as routes_voice,
    whatsapp_baileys as routes_wa_baileys,
    central_ia as routes_central_ia,
    subscribers as routes_subscribers,
    branding as routes_branding,
    collaborator_assets as routes_collab_assets,
    vehicle_checklist as routes_vehicle_checklist,
    stok as routes_stok,
    users as routes_users,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("ponto")


# -------------------------------------------------------------------------
# Indexes
# -------------------------------------------------------------------------
async def ensure_indexes() -> None:
    await db.collaborators.create_index("id", unique=True)
    await db.collaborators.create_index("cpf", unique=True)
    await db.geofences.create_index("id", unique=True)
    await db.geofences.create_index("collaborator_id")
    await db.clock_records.create_index("id", unique=True)
    await db.clock_records.create_index([("collaborator_id", 1), ("date", -1)])
    await db.settings.create_index("id", unique=True)
    await db.location_logs.create_index([("collaborator_id", 1), ("recorded_at", -1)])
    await db.location_logs.create_index("recorded_at")
    await db.holidays.create_index([("year", 1), ("scope", 1), ("date", 1)], unique=True)
    await db.pracas.create_index("name")
    await db.system_alerts.create_index("at")
    await db.tickets.create_index("id", unique=True)
    await db.tickets.create_index([("assigned_collaborator_id", 1), ("status", 1)])
    await db.notifications.create_index("id", unique=True)
    await db.notifications.create_index([("company_id", 1), ("created_at", -1)])
    await db.ticket_logs.create_index("id", unique=True)
    await db.ticket_logs.create_index([("ticket_id", 1), ("at", -1)])
    await db.ticket_logs.create_index([("company_id", 1), ("at", -1)])
    await db.atlaz_config.create_index("company_id", unique=True)
    await db.atlaz_sync_logs.create_index([("company_id", 1), ("at", -1)])
    await db.tickets.create_index([("company_id", 1), ("atlaz_external_id", 1)])
    # Estoque (stok) — coleções isoladas
    await db.stok_onts.create_index([("company_id", 1), ("mac", 1)], unique=True)
    await db.stok_onts.create_index("location_id")
    await db.stok_stock.create_index([("company_id", 1), ("location", 1)], unique=True)
    await db.stok_services.create_index("id", unique=True)
    await db.stok_services.create_index([("company_id", 1), ("status", 1)])
    await db.stok_services.create_index("ticket_id")
    await db.stok_history.create_index([("company_id", 1), ("date", -1)])
    # SmartOLT — cache de ONUs e config
    await db.smartolt_config.create_index("company_id", unique=True)
    await db.smartolt_onus.create_index(
        [("company_id", 1), ("unique_external_id", 1)], unique=True,
    )
    await db.smartolt_onus.create_index([("company_id", 1), ("name_norm", 1)])
    # AI Preventive
    await db.ai_preventive_config.create_index("company_id", unique=True)
    await db.ai_preventive_suggestions.create_index([("company_id", 1), ("created_at", -1)])
    await db.ai_preventive_suggestions.create_index([("company_id", 1), ("status", 1)])
    # Notifications
    await db.notifications.create_index([("company_id", 1), ("audience_role", 1), ("read", 1)])
    await db.notifications.create_index([("company_id", 1), ("created_at", -1)])


# -------------------------------------------------------------------------
# Scheduler & Jobs
# -------------------------------------------------------------------------
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")


async def monthly_email_job() -> None:
    from core import get_settings
    s = await get_settings()
    if not s.monthly_email_enabled:
        logger.info("[monthly] desativado")
        return
    today = datetime.now(timezone.utc)
    year, month = today.year, today.month
    colls = await db.collaborators.find({}, {"_id": 0}).to_list(1000)
    sent = 0
    for c in colls:
        out = await routes_clock.send_timesheet_email(c, year, month)
        if out.get("sent"):
            sent += 1
    logger.info(f"[monthly] enviados {sent}/{len(colls)} de {month:02d}/{year}")


async def holidays_refresh_job() -> None:
    cur_year = datetime.now(timezone.utc).year
    for y in (cur_year, cur_year + 1):
        try:
            await db.holidays.delete_many({"year": y, "scope": "national"})
            await routes_admin.get_cached_holidays(y, "national")
            logger.info("[holidays] refresh ano=%s OK", y)
        except Exception as e:
            logger.exception("[holidays] refresh ano=%s falhou: %s", y, e)


async def location_logs_cleanup_job() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    res = await db.location_logs.delete_many({"recorded_at": {"$lt": cutoff}})
    if res.deleted_count:
        logger.info("[location_logs_cleanup] removidos %s registros antigos", res.deleted_count)


async def dwell_push_job() -> None:
    try:
        result = await routes_locations.dwell_analysis(hours=8, radius_m=60.0, min_dur_min=30, use_ai=False)
        alerts = result.get("alerts", [])
        if alerts:
            sent = await broadcast_dwell_alerts(db, alerts)
            if sent.get("sent", 0) > 0:
                logger.info("[dwell_push_job] enviados %s push(es) (%s alertas novos)",
                            sent["sent"], sent.get("new_alerts", 0))
    except Exception as e:
        logger.warning("[dwell_push_job] falha: %s", e)


# -------------------------------------------------------------------------
# Seed demo (somente se collection vazia)
# -------------------------------------------------------------------------
async def _seed_demo_if_empty() -> None:
    count = await db.collaborators.count_documents({})
    if count > 0:
        return
    now = now_iso()
    demo = routes_clock.Collaborator(
        id="col-demo-001",
        name="Carlos Almeida",
        cpf="123.456.789-00",
        email="carlos@example.com",
        phone="+55 11 99999-0001",
        role="Colaborador de Campo",
        company="Operação SP",
        schedule=routes_clock.WorkSchedule(),
        avatar_data_url=None,
        reference_face=None,
        created_at=now,
        updated_at=now,
    )
    doc = demo.model_dump()
    doc["company_id"] = "co-demo"
    await db.collaborators.insert_one(doc)
    logger.info("Seed demo collaborator inserido (col-demo-001)")


async def _seed_demo_tickets() -> None:
    """Cria bolhas de exemplo para o colaborador demo (idempotente)."""
    if await db.tickets.count_documents({"assigned_collaborator_id": "col-demo-001"}) > 0:
        return
    samples = [
        ("João Almeida", "Vila Mariana", "Rua Domingos de Morais, 1234, São Paulo", "+5511988880001",
         "Internet cai repetidamente após as 19h.", "prioridade", "reparo", None),
        ("Fernanda Lima", "Moema", "Av. Ibirapuera, 2030, São Paulo", "+5511988880002",
         "Agendado para às 10h.", "horario", "instalacao", "2026-05-09T10:00:00"),
        ("Ricardo Pereira", "Pinheiros", "Rua dos Pinheiros, 500, São Paulo", "+5511988880003",
         "Velocidade muito abaixo do contratado.", "normal", "reparo", None),
        ("Patrícia Gomes", "Tatuapé", "Rua Tuiuti, 780, São Paulo", "+5511988880004",
         "Sem sinal desde ontem à noite.", "normal", "reparo", None),
        ("Marcos Tavares", "Vila Madalena", "Rua Wisard, 405, São Paulo", "+5511988880009",
         "Solicitou cancelamento — retirar equipamentos.", "normal", "retirada", None),
    ]
    import uuid as _uuid
    docs = []
    for i, s in enumerate(samples):
        name, neighborhood, address, phone, relato, priority, ttype, sched = s
        docs.append({
            "id": f"tkt-{_uuid.uuid4().hex[:10]}",
            "client_id": str(_uuid.uuid4()),
            "client_snapshot": {
                "name": name, "address": address, "neighborhood": neighborhood,
                "phone": phone, "latitude": None, "longitude": None,
                "relato": relato, "test_history": [],
            },
            "type": ttype, "priority": priority, "scheduled_time": sched,
            "position": i, "status": "pendente",
            "assigned_collaborator_id": "col-demo-001",
            "company_id": "co-demo",
            "opened_at": None, "closed_at": None, "closed_by": None,
            "close_location": None, "outcome": None,
            "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
            "completion_data": None, "admin_action": None, "admin_notes": None,
            "created_at": now_iso(),
        })
    await db.tickets.insert_many(docs)
    logger.info("Seed: %s bolhas inseridas para col-demo-001", len(docs))


# -------------------------------------------------------------------------
# FastAPI app + Lifecycle
# -------------------------------------------------------------------------
app = FastAPI(title="Ponto do Colaborador")


@app.on_event("startup")
async def _startup() -> None:
    await ensure_indexes()
    await ensure_auth_indexes(db)
    await ensure_push_indexes(db)
    await routes_saas.ensure_demo_company()
    await seed_default_users(db)
    await get_or_create_vapid(db)
    await _seed_demo_if_empty()
    await _seed_demo_tickets()
    scheduler.start()
    scheduler.add_job(monthly_email_job, CronTrigger(day="last", hour=23, minute=30),
                      id="monthly_email", replace_existing=True)
    scheduler.add_job(holidays_refresh_job, CronTrigger(day="1", hour=3, minute=0),
                      id="holidays_refresh", replace_existing=True)
    scheduler.add_job(location_logs_cleanup_job, CronTrigger(hour="*/6", minute=10),
                      id="location_cleanup", replace_existing=True)
    scheduler.add_job(dwell_push_job, "interval", minutes=2,
                      id="dwell_push", replace_existing=True)
    asyncio.create_task(holidays_refresh_job())
    asyncio.create_task(location_logs_cleanup_job())
    routes_atlaz.start_worker()
    await routes_smartolt.start_worker()
    await routes_ai_preventive.start_worker()
    await routes_aihub.start_worker()
    await routes_central_ia.start_worker()
    # SmartOLT AI worker — detecta outages a cada 90s
    from services.smartolt_ai import start_worker as start_smartolt_ai
    start_smartolt_ai()
    asyncio.create_task(routes_plans.adjustment_scheduler_worker())
    logger.info("Scheduler iniciado.")


@app.on_event("shutdown")
async def _shutdown() -> None:
    scheduler.shutdown(wait=False)
    routes_atlaz.stop_worker()
    client.close()


# Backward-compat re-export para imports lazy em routes/
dashboard_overtime = routes_clock.dashboard_overtime  # routes/dashboard.py importa daqui


# Inclui todos os routers (cada um já vem com prefix="/api")
app.include_router(routes_users.router)
app.include_router(routes_pracas.router)
app.include_router(routes_clock.router)
app.include_router(routes_locations.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_admin.router)
app.include_router(routes_push.router)
app.include_router(routes_collab_auth.router)
app.include_router(routes_logs.router)
app.include_router(routes_lousa.router)
app.include_router(routes_atlaz.router)
app.include_router(routes_events.router)
app.include_router(routes_saas.router)
app.include_router(routes_saas.webhook_router)
app.include_router(routes_stok.router)
app.include_router(routes_smartolt.router)
app.include_router(routes_ai_preventive.router)
app.include_router(routes_ai_dashboard.router)
app.include_router(routes_aihub.router)
app.include_router(routes_motor_ia.router)
app.include_router(routes_smartolt_ai.router)
app.include_router(routes_ai_topology.router)
app.include_router(routes_copilot_ranking.router)
app.include_router(routes_voice.router)
app.include_router(routes_wa_baileys.router)
app.include_router(routes_central_ia.router)
app.include_router(routes_subscribers.router)
app.include_router(routes_plans.router)
app.include_router(routes_branding.router)
app.include_router(routes_collab_assets.router)
app.include_router(routes_vehicle_checklist.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
