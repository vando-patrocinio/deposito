"""Backend do Ponto do Colaborador — orquestrador thin.

================================================================
SmartProv — ISP Suite
Copyright (c) 2025-2026  V S DO PATROCINIO PROVEDOR DE INTERNET ME
CNPJ: 13.302.883/0001-36  ·  vando@ligotelecom.com
All rights reserved. Proprietary software — see /LICENSE.
Unauthorized copy, reverse engineering or redistribution is prohibited
under Lei 9.609/98 e Lei 9.610/98 (Brasil).
================================================================

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
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
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
    ai_config as routes_ai_config,
    atlaz as routes_atlaz,
    atlaz_webhooks as routes_atlaz_webhooks,
    ligo_tv as routes_ligo_tv,
    clock as routes_clock,
    collab_auth as routes_collab_auth,
    dashboard as routes_dashboard,
    events as routes_events,
    locations as routes_locations,
    logs as routes_logs,
    lousa as routes_lousa,
    lousa_manager_callbacks as routes_lousa_callbacks,
    mobile_health as routes_mobile_health,
    pracas as routes_pracas,
    push as routes_push,
    saas as routes_saas,
    smartolt as routes_smartolt,
    network_diag as routes_network_diag,
    ai_preventive as routes_ai_preventive,
    ai_dashboard as routes_ai_dashboard,
    aihub as routes_aihub,
    motor_ia as routes_motor_ia,
    conselho_ia as routes_conselho_ia,
    presidente_ia as routes_presidente_ia,
    presidente_agentes as routes_presidente_agentes,
    lousa_sala as routes_lousa_sala,
    lousa_sala_config as routes_lousa_sala_config,
    aihub_prompts as routes_aihub_prompts,
    user_magic_links as routes_user_magic_links,
    sala_orphan_health as routes_sala_orphan_health,
    isabella_churn as routes_isabella_churn,
    treasury as routes_treasury,
    audit_log_panel as routes_audit_log,
    backend_health_routes as routes_backend_health,
    warroom as routes_warroom,
    diagnostic_report as routes_diagnostic_report,
    pre_attendance as routes_pre_attendance,
    whatsapp_campaigns as routes_wa_campaigns,
    diagnostic as routes_diagnostic,
    smartolt_ai as routes_smartolt_ai,
    ai_topology as routes_ai_topology,
    copilot_ranking as routes_copilot_ranking,
    sentinela_lousa as routes_sentinela_lousa,
    lousa_ai as routes_lousa_ai,
    colosso as routes_colosso,
    colosso_financeiro as routes_colosso_fin,
    isabella_lousa as routes_isabella_lousa,
    isabella_memory_inspector as routes_isabella_memory,
    plans as routes_plans,
    voice as routes_voice,
    whatsapp_baileys as routes_wa_baileys,
    whatsapp_business_hours as routes_wa_business_hours,
    whatsapp_channels as routes_wa_channels,
    central_ia as routes_central_ia,
    rede_ia as routes_rede_ia,
    rede_ia_map as routes_rede_ia_map,
    rede_ia_kmz as routes_rede_ia_kmz,
    rede_ia_signals as routes_rede_ia_signals,
    cto_ports_base as routes_cto_ports_base,
    radius as routes_radius,
    contracts as routes_contracts,
    clients_segments as routes_clients_segments,
    lousa_map as routes_lousa_map,
    payment_charges as routes_payment_charges,
    provider_site as routes_provider_site,
    fleet as routes_fleet,
    fleet_tracking as routes_fleet_tracking,
    fleet_portal as routes_fleet_portal,
    security_home as routes_security_home,
    parceria as routes_parceria,
    referrals as routes_referrals,
    churn as routes_churn,
    subscribers as routes_subscribers,
    branding as routes_branding,
    checklist_ai as routes_checklist_ai,
    collaborator_assets as routes_collab_assets,
    vehicle_checklist as routes_vehicle_checklist,
    field_ops as routes_field_ops,
    isabella_field as routes_isabella_field,
    isabella_commanders as routes_isabella_commanders,
    isabella_pj as routes_isabella_pj,
    isabella_watchtower as routes_isabella_watchtower,
    universo_ligo as routes_universo_ligo,
    universo_ligo_curadoria as routes_universo_ligo_curadoria,
    customer_intelligence as routes_customer_intelligence,
    shield as routes_shield,
    nervous_foundation as routes_nervous_foundation,
    whatsapp_twilio as routes_whatsapp_twilio,
    pdf_reports as routes_pdf_reports,
    whatsapp_meta as routes_whatsapp_meta,
    holerite as routes_holerite,
    feriados as routes_feriados,
    stok as routes_stok,
    balanco as routes_balanco,
    onboarding as routes_onboarding,
    users as routes_users,
    secretaria as routes_secretaria,
    drive as routes_drive,
    ai_corrections as routes_ai_corrections,
    appointments as routes_appointments,
    budget as routes_budget,
    integrations as routes_integrations,
    ai_training as routes_ai_training,
    connections as routes_connections,
    financeiro as routes_financeiro,
    financeiro_ops as routes_financeiro_ops,
    financeiro_analytics as routes_financeiro_analytics,
    financeiro_reports as routes_financeiro_reports,
    atlaz_financeiro as routes_atlaz_financeiro,
    alvaro as routes_alvaro,
    alvaro_os_summary as routes_alvaro_os_summary,
    gps_vlan_suggest as routes_gps_vlan_suggest,
    smartolt_push_ctos as routes_smartolt_push_ctos,
    rede_cell as routes_rede_cell,
    sprint5_onda1 as routes_sprint5_onda1,
    sprint5_onda2 as routes_sprint5_onda2,
    sprint5_onda3 as routes_sprint5_onda3,
    sprint5_onda4 as routes_sprint5_onda4,
    sprint5_onda5 as routes_sprint5_onda5,
    sprint5_onda6 as routes_sprint5_onda6,
    sprint5_swap_events as routes_sprint5_swap_events,
    sprint5_audit_operacional as routes_sprint5_audit_op,
    sprint5_e2e_validator as routes_sprint5_e2e,
    whatsapp_config as routes_whatsapp_config,
    wa_test_mode as routes_wa_test_mode,
    mass_messaging as routes_mass_messaging,
    disparo_ia as routes_disparo_ia,
    disparo_boleto as routes_disparo_boleto,
    boleto_template as routes_boleto_template,
    projects as routes_projects,
    isabella_prompt as routes_isabella_prompt,
    isabella_negotiation as routes_isabella_negotiation,
    interactions as routes_interactions,
    pricing_catalog as routes_pricing_catalog,
    gestao_ia as routes_gestao_ia,
    isabella_kpis as routes_isabella_kpis,
    sales_funnel as routes_sales_funnel,
    tv_dashboards as routes_tv_dashboards,
    utils as routes_utils,
    financeiro_reajuste as routes_financeiro_reajuste,
    public_access as routes_public_access,
    disparo_promo as routes_disparo_promo,
    bank_import as routes_bank_import,
    wifi as routes_wifi,
    wifi_hotspot as routes_wifi_hotspot,
    billing as routes_billing,
    retirada_template as routes_retirada_template,
    os_validation_toggles as routes_os_validation_toggles,
    tech_tracking as routes_tech_tracking,
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
    # Sprint 5 Onda 5: partialFilterExpression para evitar conflito com mac=null
    await db.stok_onts.create_index(
        [("company_id", 1), ("mac", 1)], unique=True,
        partialFilterExpression={"mac": {"$exists": True, "$type": "string"}},
    )
    await db.stok_onts.create_index("location_id")
    # iter162 — indexes para queries de defeituosa e auditoria SN
    await db.stok_onts.create_index([("company_id", 1), ("status", 1)])
    await db.stok_onts.create_index([("company_id", 1), ("location_type", 1),
                                       ("location_id", 1), ("status", 1)])
    # Tracking GPS dos técnicos (iter157)
    await db.tech_locations.create_index([("company_id", 1), ("collab_id", 1),
                                            ("captured_at", -1)])
    await db.tech_locations.create_index([("company_id", 1), ("captured_at", -1)])
    # Auditoria SN da Retirada (iter161)
    await db.withdraw_sn_audit.create_index([("company_id", 1), ("created_at", -1)])
    await db.withdraw_sn_audit.create_index([("company_id", 1),
                                                ("technician_id", 1),
                                                ("created_at", -1)])
    await db.withdraw_sn_audit.create_index([("company_id", 1), ("reason", 1)])
    # Histórico de Equipamento por Cliente (iter163)
    await db.client_equipment_history.create_index("id", unique=True)
    await db.client_equipment_history.create_index([
        ("company_id", 1), ("client_id", 1), ("captured_at", -1),
    ])
    await db.client_equipment_history.create_index([
        ("company_id", 1), ("client_id", 1), ("action", 1),
    ])
    # Alertas de ONT Duplicada (iter164)
    await db.ont_duplicate_alerts.create_index("id", unique=True)
    await db.ont_duplicate_alerts.create_index([
        ("company_id", 1), ("status", 1), ("detected_at", -1),
    ])
    # iter176 — Correções de OCR
    await db.stok_ocr_corrections.create_index([
        ("company_id", 1), ("created_at", -1),
    ])
    await db.stok_ocr_corrections.create_index([
        ("company_id", 1), ("ont_model", 1),
    ])
    await db.stok_stock.create_index([("company_id", 1), ("location", 1)], unique=True)
    await db.stok_services.create_index("id", unique=True)
    await db.stok_services.create_index([("company_id", 1), ("status", 1)])
    await db.stok_services.create_index("ticket_id")
    await db.stok_history.create_index([("company_id", 1), ("date", -1)])
    # Balanço de estoque
    await db.stok_balanco_sessions.create_index("id", unique=True)
    await db.stok_balanco_sessions.create_index([("company_id", 1), ("status", 1), ("created_at", -1)])
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
scheduler = AsyncIOScheduler(
    timezone="America/Sao_Paulo",
    # P0.2 Scheduler Hardening — protege TODOS os jobs contra misfire por
    # downtime do processo (causa do gap de backup 07/jun). Aplica
    # uniformemente em todos os add_job sem alterar frequências.
    job_defaults={
        "misfire_grace_time": 3600,  # 1h de janela pra recuperar job perdido
        "coalesce": True,            # combina múltiplos misfires em 1 execução
        "max_instances": 1,          # evita execução concorrente do mesmo job
    },
)


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
    # CTO 13/06/2026 — antes só rodava se collection vazia. Agora também
    # restaura `col-demo-001` se foi deletado mas user vinculado ainda
    # existe (vínculo órfão = "Olá —" + schedule undefined no PWA).
    exists = await db.collaborators.find_one({"id": "col-demo-001"}, {"_id": 1})
    if exists:
        return
    now = now_iso()
    demo = routes_clock.Collaborator(
        id="col-demo-001",
        name="Carlos Almeida",
        cpf="00000000001",
        email="colaborador@empresa.com",
        phone="+55 11 99999-0001",
        role="Colaborador de Campo",
        cargo="tecnico",
        company="Operação SP",
        schedule=routes_clock.WorkSchedule(),
        clock_in_enabled=False,
        avatar_data_url=None,
        reference_face=None,
        created_at=now,
        updated_at=now,
    )
    doc = demo.model_dump()
    doc["company_id"] = "co-demo"
    try:
        await db.collaborators.insert_one(doc)
        logger.info("Seed demo collaborator inserido (col-demo-001)")
    except Exception as e:  # noqa: BLE001
        logger.warning("Seed col-demo-001 falhou (provavel duplicate): %s", e)


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

# ── Fingerprint de propriedade (não remover — Lei 9.609/98, 9.610/98) ──
# Adiciona endpoint /api/about + header X-Powered-By + marca o DB.
# Centralizado em backend/identity.py.
from identity import about_payload, x_powered_by_value, OWNER, _BOOT_AT


@app.get("/api/about", tags=["public"])
async def public_about():
    """Retorna a identidade do produto e fingerprint criptográfico.

    Endpoint público, sem auth — serve como prova de origem do software.
    """
    return about_payload()


@app.middleware("http")
async def _add_powered_by_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Powered-By"] = x_powered_by_value()
    return response


# ─────────────────── Sprint 13 — Auto-emit no Event Bus ───────────────────
from middleware.auto_emit_middleware import auto_emit_middleware
app.middleware("http")(auto_emit_middleware)


# ─────────────────── Sprint 2 — RBAC global (iter221) ───────────────────
@app.middleware("http")
async def _rbac_middleware(request: Request, call_next):
    """Aplica RBAC por path. Decisão antes de bater no router.

    Fluxo:
      1. path público (PUBLIC_PATHS) -> passa
      2. extrai JWT do header. 401 se ausente/inválido.
      3. consulta required_roles_for(path). Se None, basta auth.
      4. valida role do user contra o set. 403 se não bate.
      5. logs DELETE em audit_log automaticamente.
    """
    from fastapi.responses import JSONResponse
    from rbac_policy import (
        is_public, required_roles_for, is_destructive, is_export,
        is_ia, is_non_staff_auth,
    )
    import time as _t

    path = request.url.path or ""
    method = request.method or ""
    _t0 = _t.time()
    # captura IP do cliente (atrás de proxy Kubernetes)
    fwd = request.headers.get("x-forwarded-for") or ""
    client_ip = (fwd.split(",")[0].strip()
                   if fwd else (request.client.host if request.client
                                  else ""))
    user_agent = (request.headers.get("user-agent") or "")[:200]

    # 1) Públicos passam
    if is_public(path):
        return await call_next(request)

    # 2) Extrai JWT
    auth_h = request.headers.get("authorization") or ""
    token = auth_h[7:] if auth_h.lower().startswith("bearer ") else ""
    user = None
    if token:
        try:
            from auth import decode_token
            payload = decode_token(token)
            user = payload if isinstance(payload, dict) else None
        except Exception:
            user = None

    # Endpoints fora do /api passam (frontend SPA)
    if not path.startswith("/api/"):
        return await call_next(request)

    # CTO 13/06/2026 — Endpoints com fluxo de auth PRÓPRIO (cliente CPF,
    # parceiro magic-link, fleet/security portal, colaborador PWA, etc.)
    # devem passar sem JWT corporativo. O handler valida o token alternativo
    # via Depends. Sem este bypass, /api/customer/login retornava 401
    # "Não autenticado" porque o middleware exigia JWT antes do handler.
    if is_non_staff_auth(path):
        return await call_next(request)

    if not user:
        # Sem token válido — bloqueia tudo do /api/ (exceto publics)
        return JSONResponse(
            {"detail": "Não autenticado"}, status_code=401)

    # 3) Role check (pula em endpoints com fluxo próprio - portais)
    if not is_non_staff_auth(path):
        roles = required_roles_for(path)
        if roles is not None:
            u_role = user.get("role") or "colaborador"
            is_super = bool(user.get("is_super_admin"))
            if not is_super and u_role != "administrador" \
                    and u_role not in roles:
                # log do bloqueio RBAC (Sprint 3 + chain Sprint 4)
                try:
                    import uuid as _uuid
                    from datetime import datetime as _dt, timezone as _tz
                    from services.lgpd_chain import insert_audit_event
                    await insert_audit_event({
                        "id": f"aud-{_uuid.uuid4().hex[:14]}",
                        "company_id": user.get("company_id"),
                        "user_id": user.get("sub") or user.get("id"),
                        "user_email": user.get("email"),
                        "user_role": u_role,
                        "category": "rbac_blocked",
                        "criticality": "media",
                        "method": method,
                        "target": path,
                        "endpoint": path,
                        "action": f"{method} {path}",
                        "status": 403,
                        "reason": (
                            f"role={u_role} não está em "
                            f"{sorted(list(roles))}"),
                        "ip": client_ip,
                        "user_agent": user_agent,
                        "data": {},
                        "created_at": _dt.now(_tz.utc).isoformat(),
                    })
                except Exception:
                    pass
                return JSONResponse(
                    {"detail": "Você não tem permissão para "
                                  "acessar este recurso."},
                    status_code=403)

    # 4) Rate-limit em rotas de IA (best-effort, in-memory)
    if is_ia(path):
        try:
            from rbac import rate_limit as _rl
            _dep = _rl(per_minute=int(os.environ.get(
                "IA_RATE_PER_MIN", "30") or 30),
                          per_day=int(os.environ.get(
                              "IA_RATE_PER_DAY", "1000") or 1000),
                          scope="ia")
            try:
                await _dep(request, user)
            except Exception as e:
                from fastapi import HTTPException as _HE
                if isinstance(e, _HE):
                    # registra rate-limit
                    try:
                        import uuid as _uuid
                        from datetime import datetime as _dt, \
                            timezone as _tz
                        from services.lgpd_chain import insert_audit_event
                        await insert_audit_event({
                            "id": f"aud-{_uuid.uuid4().hex[:14]}",
                            "company_id": user.get("company_id"),
                            "user_id": user.get("sub") or user.get("id"),
                            "user_email": user.get("email"),
                            "user_role": user.get("role"),
                            "category": "ai_rate_limited",
                            "criticality": "baixa",
                            "method": method, "target": path,
                            "endpoint": path,
                            "action": f"{method} {path}",
                            "status": 429,
                            "reason": str(e.detail),
                            "ip": client_ip, "user_agent": user_agent,
                            "data": {}, "created_at":
                                _dt.now(_tz.utc).isoformat(),
                        })
                    except Exception:
                        pass
                    return JSONResponse(
                        {"detail": e.detail}, status_code=e.status_code)
                raise
        except Exception:
            pass

    # 5) Audit log para DELETE + EXPORT + CONFIG + IMPERSONATE +
    # LOGIN_ADMIN
    _is_delete = is_destructive(method, path)
    _is_export = is_export(path)
    _is_cfg = (method in ("PUT", "POST", "PATCH") and (
        path.startswith("/api/settings") or
        path.startswith("/api/branding") or
        path.startswith("/api/integrations") or
        path.startswith("/api/motor-ia/config")))
    _is_ai_cfg = (method in ("PUT", "POST", "PATCH", "DELETE") and (
        path.startswith("/api/ai-config")))
    _is_impersonate = path.startswith("/api/auth/impersonate")
    _is_login_admin = path == "/api/auth/admin-login" and method == "POST"

    needs_audit = (_is_delete or _is_export or _is_cfg or _is_ai_cfg
                     or _is_impersonate or _is_login_admin)
    if needs_audit:
        if _is_delete:
            cat, crit = "destructive", "alta"
        elif _is_export:
            cat, crit = "export", "media"
        elif _is_ai_cfg:
            cat, crit = "ai_config_change", "alta"
        elif _is_cfg:
            cat, crit = "config_change", "alta"
        elif _is_impersonate:
            cat, crit = "impersonate", "alta"
        else:
            cat, crit = "login_admin", "media"
        try:
            import uuid as _uuid
            from datetime import datetime as _dt, timezone as _tz
            from services.lgpd_chain import insert_audit_event
            await insert_audit_event({
                "id": f"aud-{_uuid.uuid4().hex[:14]}",
                "company_id": user.get("company_id"),
                "user_id": user.get("sub") or user.get("id"),
                "user_email": user.get("email"),
                "user_role": user.get("role"),
                "category": cat,
                "criticality": crit,
                "method": method,
                "target": path,
                "endpoint": path,
                "action": f"{method} {path}",
                "status": 200,
                "ip": client_ip,
                "user_agent": user_agent,
                "data": {},
                "created_at": _dt.now(_tz.utc).isoformat(),
            })
        except Exception:
            pass

    response = await call_next(request)
    # registra latência para o painel de saúde
    try:
        from services.backend_health import record_request
        record_request(path, response.status_code,
                          (_t.time() - _t0) * 1000.0)
    except Exception:
        pass
    return response

# Rate limiting global via slowapi
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from services.rate_limit import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
async def _startup() -> None:
    await ensure_indexes()
    await ensure_auth_indexes(db)
    await ensure_push_indexes(db)
    # iter212a — TTL + indexes do Fleet Tracking
    try:
        from routes.fleet_tracking import ensure_indexes as _ft_idx
        from routes.fleet_portal import ensure_indexes as _fp_idx
        from routes.security_home import ensure_indexes as _sh_idx
        from routes.parceria import ensure_indexes as _pa_idx
        from routes.audit_log_panel import ensure_indexes as _al_idx
        from services.event_bus import ensure_indexes as _eb_idx
        from services.executive_scheduler import start_scheduler
        await _ft_idx()
        await _fp_idx()
        await _sh_idx()
        await _pa_idx()
        await _al_idx()
        await _eb_idx()
        start_scheduler()
    except Exception as _e:
        logger.warning("[startup] fleet/security/parceria indexes falhou: %s", _e)

    # Sincroniza prompts versionados no Git com o aihub_agents.
    try:
        from services.prompt_loader import sync_all as _sync_prompts
        _results = await _sync_prompts()
        logger.info("[startup] prompt_loader: %s", _results)
    except Exception as _e:
        logger.warning("[startup] prompt_loader falhou: %s", _e)
    # Migrations aditivas (idempotentes — só adicionam campos/índices,
    # nunca apagam). Ver /app/memory/DATA_PERSISTENCE.md.
    try:
        from scripts.migrations import run_pending_migrations
        result = await run_pending_migrations(db)
        if result["applied"]:
            logger.info("[startup] migrations aplicadas: %s",
                          result["applied"])
        if result["failed"]:
            logger.error("[startup] migrations falharam: %s",
                            result["failed"])
    except Exception as e:
        logger.exception("[startup] erro ao rodar migrations: %s", e)
    # iter211v — Paridade NAV_GROUPS ↔ access_tags catálogo
    try:
        from nav_tabs_registry import audit_against_catalog
        from access_tags import TAGS as _AT_TAGS
        _audit = audit_against_catalog([t["key"] for t in _AT_TAGS])
        if not _audit["in_sync"]:
            logger.warning(
                "[startup] iter211v — abas em NAV_GROUPS sem tag em "
                "access_tags.py: %s. Adicione em /app/backend/access_tags.py.",
                _audit["missing_in_catalog"],
            )
        else:
            logger.info(
                "[startup] iter211v — paridade NAV↔access_tags OK "
                "(%d abas mapeadas, %d tags extra/legacy)",
                _audit["nav_total"], len(_audit["extra_in_catalog"]),
            )
    except Exception as e:
        logger.warning("[startup] iter211v — falha no audit de tags: %s", e)
    await routes_saas.ensure_demo_company()
    await seed_default_users(db)
    await get_or_create_vapid(db)
    await _seed_demo_if_empty()
    await _seed_demo_tickets()
    # Fingerprint de propriedade no banco (sobrevive a clone de MongoDB)
    try:
        await db.system_settings.update_one(
            {"_id": "owner_fingerprint"},
            {"$set": {
                "company": OWNER["company"],
                "cnpj": OWNER["cnpj"],
                "email": OWNER["email"],
                "copyright": OWNER["copyright"],
                "license": OWNER["license"],
                "last_boot_at": _BOOT_AT,
            }, "$setOnInsert": {"created_at": _BOOT_AT}},
            upsert=True,
        )
    except Exception as e:
        logger.warning("[startup] não foi possível gravar owner_fingerprint: %s", e)

    # ─── OPERAÇÃO ESCALA HTTP: ELECTION LOOP (CTO fix 12/06/2026) ───
    # Bug anterior: try_acquire_leader() era chamado UMA VEZ no startup.
    # Se um restart sujo deixava lock zumbi, TODOS os workers viravam
    # FOLLOWER permanente e jobs/workers (Atlaz sync, Baileys watchdog,
    # holidays, dwell push, autonomy, backup) ficavam órfãos até o
    # próximo deploy. Agora cada worker roda uma election loop; quando
    # vira leader (após lock expirar), promove-se e inicia os jobs de
    # forma idempotente. A renovação acontece naturalmente porque
    # try_acquire_leader() atualiza expires_at quando holder == self.
    _leader_state = {"started": False}

    async def _start_leader_jobs() -> None:
        if _leader_state["started"]:
            return
        _leader_state["started"] = True
        logger.info(
            "[startup] LEADER worker (pid=%s) — iniciando schedulers e "
            "background tasks", os.getpid())
        scheduler.start()
        scheduler.add_job(monthly_email_job, CronTrigger(day="last", hour=23, minute=30),
                          id="monthly_email", replace_existing=True)
        # OLT SNMP polling — atualiza cache a cada 5min
        try:
            from services.olt_polling_scheduler import setup_olt_polling
            setup_olt_polling(scheduler)
        except Exception as e:
            logger.warning("[startup] olt_polling falhou: %r", e)
        # OPERAÇÃO 90% — Sistema Nervoso 100% (refresh dos synthesized 1h)
        try:
            from services import nervous_coverage_job as _ncj
            _ncj.register(scheduler)
        except Exception as e:
            logger.warning("[startup] nervous_coverage_job falhou: %r", e)
        # OPERAÇÃO CAIXA REAL — fechamento diário 23:59 + indexes
        try:
            from services import presidente_cash as _cash
            await _cash.ensure_indexes()
            _cash.register_scheduler(scheduler)
        except Exception as e:
            logger.warning("[startup] presidente_cash falhou: %r", e)

        # SPRINT 5 ONDA 6 — Auto Balanço Patrimonial (snapshot diário 00:05)
        try:
            async def _onda6_daily_snapshot():
                from services.balance_engine import (
                    compute_monthly_balance, _month_key)
                from datetime import datetime as _dt, timezone as _tz
                from database import db as _db
                ym = _month_key(_dt.now(_tz.utc))
                # Para cada empresa ativa: snapshot
                companies = await _db.companies.find(
                    {}, {"_id": 0, "id": 1}).to_list(length=200)
                for c in companies:
                    try:
                        await compute_monthly_balance(
                            _db, c["id"], ym,
                            snapshot_only=True,
                            actor_user_id="cron_onda6")
                    except Exception as ex:
                        logger.warning(
                            "[onda6.cron] %s falhou: %s", c.get("id"), ex)
            scheduler.add_job(
                _onda6_daily_snapshot,
                CronTrigger(hour=0, minute=5),
                id="onda6_daily_snapshot", replace_existing=True)
            logger.info("[startup] onda6_daily_snapshot agendado 00:05 UTC")
        except Exception as e:
            logger.warning(
                "[startup] onda6 scheduler falhou: %r", e)

        # OPERAÇÃO MATURIDADE COMERCIAL — reconciliador 03:00
        try:
            from services import cash_reconciler as _rec
            _rec.register_scheduler(scheduler)
        except Exception as e:
            logger.warning("[startup] cash_reconciler falhou: %r", e)
        # P0 CEO 17/02/2026 — Watchdog Baileys: monitora sidecar e
        # auto-reenvia mensagens failed_send/failed_timeout quando o
        # sidecar volta a `state=connected`. Sem fallback cruzado.
        try:
            from services import wa_sidecar_watchdog as _waw
            _waw.register_scheduler(scheduler)
        except Exception as e:
            logger.warning("[startup] wa_sidecar_watchdog falhou: %r", e)
        # SPRINT A CEO 17/02/2026 — Outcome Recorder: fecha o learning
        # loop classificando opportunities `expired` em
        # success/failure/partial/unknown a partir de SINAIS REAIS no DB
        # e ajusta os pesos do motor `isabella_playbook_weights`.
        try:
            from services import isabella_outcome_recorder as _ior
            _ior.register_scheduler(scheduler)
        except Exception as e:
            logger.warning("[startup] isabella_outcome_recorder falhou: %r",
                           e)
        # SPRINT B CEO 17/02/2026 — Opportunity Executor: bridge entre
        # commanders_worker e ação real. Drena `pending` sem
        # `requires_approval` em ciclos de 10min, cap 20/tick.
        # Kill switch: OPPORTUNITY_EXECUTOR_DRY_RUN=1
        #              OPPORTUNITY_EXECUTOR_DISABLED=1
        try:
            from services import opportunity_executor as _oxe
            _oxe.register_scheduler(scheduler)
        except Exception as e:
            logger.warning("[startup] opportunity_executor falhou: %r", e)
        scheduler.add_job(holidays_refresh_job, CronTrigger(day="1", hour=3, minute=0),
                          id="holidays_refresh", replace_existing=True)
        # iter241 — Snapshot diário do President Score às 03:00
        try:
            from services.score_recovery import daily_snapshot_job as _score_snap
            scheduler.add_job(_score_snap, CronTrigger(hour=3, minute=15),
                              id="president_score_daily_snapshot",
                              replace_existing=True)
        except Exception as _e:
            logger.warning("[startup] score_recovery snapshot job falhou: %r", _e)
        # iter242 — Snapshot diário do PRESIDENT_SCORE_ENGINE (12 áreas) 03:30
        try:
            from services.presidente_score_engine import (
                daily_snapshot_job as _eng_snap)
            scheduler.add_job(_eng_snap, CronTrigger(hour=3, minute=30),
                              id="president_score_engine_daily",
                              replace_existing=True)
        except Exception as _e:
            logger.warning("[startup] score_engine cron falhou: %r", _e)
        scheduler.add_job(location_logs_cleanup_job, CronTrigger(hour="*/6", minute=10),
                          id="location_cleanup", replace_existing=True)
        scheduler.add_job(dwell_push_job, "interval", minutes=2,
                          id="dwell_push", replace_existing=True)
        # iter216b — WiFi Hotspot: marca sessões pending_whatsapp expiradas
        # (>2min) como abandoned + retarget WhatsApp 48h depois
        from routes.wifi_hotspot import (
            mark_abandoned_sessions_job, retarget_abandoned_sessions_job,
        )
        scheduler.add_job(mark_abandoned_sessions_job, "interval", minutes=2,
                          id="wifi_mark_abandoned", replace_existing=True)
        scheduler.add_job(retarget_abandoned_sessions_job, "interval", hours=1,
                          id="wifi_retarget_48h", replace_existing=True)
        # ── Onda B (CEO 2026-06-18) — Late close worker + reconciliação ──
        # Late close worker: roda a cada 5min, fecha stok_services em "ativo"
        # cujo ticket está finalizado há > 60s. Rede de segurança contra
        # qualquer falha do auto_close inicial.
        from services.late_close_worker import scheduled_late_close_tick
        scheduler.add_job(scheduled_late_close_tick, "interval", minutes=5,
                          id="stok_late_close_5m", replace_existing=True,
                          max_instances=1)
        # Cron diário 03:00 UTC — reconciliação de stok_services órfãs
        # (ticket não existe mais). Idempotente, sem delete, com alerta.
        from services.stok_reconcile_job import (
            daily_reconcile_orphans_job,
        )
        scheduler.add_job(daily_reconcile_orphans_job,
                          CronTrigger(hour=3, minute=0),
                          id="stok_orphan_reconcile_daily",
                          replace_existing=True, max_instances=1)
        # Onda C P1 V2.0 — Confirmação Patrimonial SLA Worker (CEO 18/06/2026)
        # Roda a cada 30min: lembrete 4h + escalonamento 24h.
        from services.patrimonial_confirmation_worker import (
            patrimonial_sla_tick,
        )
        scheduler.add_job(patrimonial_sla_tick, "interval", minutes=30,
                          id="patrimonial_sla_30m",
                          replace_existing=True, max_instances=1)
        # FASE 10 sprint final V5.0 — Autonomy scheduler integrado
        if os.environ.get("AUTONOMY_SCHEDULER_DISABLED", "0") != "1":
            from services import autonomy_scheduler_jobs as _autosch
            scheduler.add_job(_autosch.drives, "interval", minutes=30,
                               id="autonomy_drives_30m", replace_existing=True,
                               max_instances=1)
            scheduler.add_job(_autosch.reconcile, "interval", hours=4,
                               id="autonomy_reconcile_4h",
                               replace_existing=True, max_instances=1)
            scheduler.add_job(_autosch.briefing_07h,
                               CronTrigger(hour=7, minute=0),
                               id="autonomy_briefing_07h",
                               replace_existing=True)
            scheduler.add_job(_autosch.briefing_12h,
                               CronTrigger(hour=12, minute=0),
                               id="autonomy_briefing_12h",
                               replace_existing=True)
            scheduler.add_job(_autosch.briefing_18h,
                               CronTrigger(hour=18, minute=0),
                               id="autonomy_briefing_18h",
                               replace_existing=True)
            scheduler.add_job(_autosch.self_healing_auto,
                               "interval", hours=1,
                               id="autonomy_self_heal_1h",
                               replace_existing=True,
                               max_instances=1)
            logger.info("[startup] autonomy scheduler jobs registered "
                          "(drives/30m, reconcile/4h, briefings 07/12/18, "
                          "self_heal/1h)")
        # Atlaz: sync de assinantes diário às 22h00 (America/Sao_Paulo)
        scheduler.add_job(routes_atlaz.nightly_customers_sync_job,
                          CronTrigger(hour=22, minute=0),
                          id="atlaz_customers_sync_nightly", replace_existing=True)
        # Integrations: auto-reconnect canais mortos a cada 2 min
        scheduler.add_job(routes_integrations.auto_reconnect_job,
                          "interval", minutes=2,
                          id="integrations_auto_reconnect", replace_existing=True)
        # Baileys: watchdog detecta socket zumbi e força reload preventivo
        from routes.whatsapp_baileys import baileys_watchdog_job
        scheduler.add_job(baileys_watchdog_job,
                          "interval", minutes=2,
                          id="baileys_watchdog", replace_existing=True)
        # Baileys: restart preventivo diário 04:00 (evita memory leak, garante uptime)
        from routes.whatsapp_baileys import baileys_nightly_restart_job
        scheduler.add_job(baileys_nightly_restart_job,
                          CronTrigger(hour=4, minute=0),
                          id="baileys_nightly_restart", replace_existing=True)
        # iter205c — Backup diário do MongoDB 03:00 UTC, rotação 7 últimos
        from routes.backup import daily_backup_job, weekly_migrate_job
        scheduler.add_job(daily_backup_job,
                          CronTrigger(hour=3, minute=0),
                          id="mongo_daily_backup", replace_existing=True)
        # iter205g — Migração automática semanal PROD → este ambiente (domingo 04:00 UTC)
        scheduler.add_job(weekly_migrate_job,
                          CronTrigger(day_of_week="sun", hour=4, minute=0),
                          id="mongo_weekly_migrate", replace_existing=True)
        # CTO 11/06/2026: health check de tickets órfãos (a cada 15 min)
        from services.sala_orphan_health import run_orphan_health_check
        scheduler.add_job(run_orphan_health_check, "interval", minutes=15,
                          id="sala_orphan_health", replace_existing=True,
                          max_instances=1, coalesce=True)
        # CTO P1.2 11/06/2026: Isabella → SALA por churn (diário 06:00 UTC)
        from services.isabella_churn_to_sala import run_churn_to_sala
        scheduler.add_job(run_churn_to_sala, CronTrigger(hour=6, minute=0),
                          id="isabella_churn_to_sala", replace_existing=True,
                          max_instances=1, coalesce=True)
        asyncio.create_task(holidays_refresh_job())
        asyncio.create_task(location_logs_cleanup_job())
        routes_atlaz.start_worker()
        await routes_smartolt.start_worker()
        await routes_ai_preventive.start_worker()
        # iter186 — Vision AI auto-link de cabos órfãos (cron noturno)
        await routes_rede_ia.start_vision_worker()
        await routes_aihub.start_worker()
        await routes_central_ia.start_worker()
        # SmartOLT AI worker — detecta outages a cada 90s
        from services.smartolt_ai import start_worker as start_smartolt_ai
        start_smartolt_ai()
        # iter180 — SmartOLT VLAN sync worker: detecta mudanças de VLAN e
        # emite ticket vlan_change_unexpected
        from services.smartolt_vlan_sync import start_worker as start_vlan_sync
        start_vlan_sync()
        from services.sentinela_lousa import start_worker as start_sentinela_lousa
        start_sentinela_lousa()
        from services.lousa_ai_triagem import start_worker as start_lousa_ai
        start_lousa_ai()
        # iter211bd — Worker que empurra CTOs locais para o SmartOLT
        # (chama add_zone) — só atua em CTOs marcadas smartolt_eligible=True.
        routes_smartolt_push_ctos.start_worker()
        # Lousa Map — geocoding noturno de tickets sem coordenadas
        await routes_lousa_map.start_worker()
        # Outage Detector — detecta rupturas em massa e abre bolha automática
        from services.rede_ia_outage_detector import start_worker as start_outage
        await start_outage()
        # Contracts Aging Worker — aplica REDUZIDO/WALL_GARDEN/SUSPENSO conforme
        # invoices vencidas + dispara CoA pra reaplicar perfil no Mikrotik
        from services.contracts_aging_worker import worker_loop as _aging_loop
        asyncio.create_task(_aging_loop())
        from services.churn_scheduler import start_worker as start_churn_scheduler
        start_churn_scheduler()
        # iter215bx — Cron do Conselho Estratégico IA (8h BRT)
        from services.conselho_ia_scheduler import (
            start_worker as start_conselho_ia_cron)
        start_conselho_ia_cron()
        from services.readjustment_scheduler import (
            start_worker as start_readjustment_scheduler,
        )
        start_readjustment_scheduler()
        from services.ai_training_scheduler import (
            start_worker as start_ai_training_scheduler,
        )
        start_ai_training_scheduler()
        # Sales outreach worker — Isabella IA proativa em leads de wifi self-service
        from services.sales_outreach import (
            start_worker as start_sales_outreach,
        )
        await start_sales_outreach()
        routes_mass_messaging.start_worker()
        # Cron: auto-marca contas a pagar vencidas — diário 03:00
        from routes.financeiro_ops import auto_mark_overdue
        scheduler.add_job(auto_mark_overdue, CronTrigger(hour=3, minute=0),
                          id="fin_overdue_daily", replace_existing=True)
        # Cron: sync Atlaz financeiro — a cada 2 horas
        from routes.atlaz_financeiro import auto_sync_atlaz_financeiro
        scheduler.add_job(auto_sync_atlaz_financeiro,
                          CronTrigger(minute=15, hour="*/2"),
                          id="atlaz_fin_auto_sync", replace_existing=True)
        # Cron: auditoria CTO ↔ SmartOLT — diário 03:15
        from services.cto_audit import nightly_audit_job
        scheduler.add_job(nightly_audit_job, CronTrigger(hour=3, minute=15),
                          id="cto_audit_nightly", replace_existing=True)
        # Cron: REAJUSTE ANUAL automático — diário 04:00, aplica reajustes vencidos
        async def _readjustment_daily_all_companies():
            from services.inflation import refresh_index_cache, SGS_CODES
            from services.readjustment import apply_all_due
            # 1) atualiza índices de inflação
            for name in SGS_CODES.keys():
                try:
                    await refresh_index_cache(name)
                except Exception as e:
                    logger.warning("[readjustment-cron] refresh %s falhou: %s",
                                   name, e)
            # 2) aplica reajustes pendentes em cada empresa
            async for c in db.companies.find({}, {"_id": 0, "id": 1}):
                try:
                    r = await apply_all_due(c["id"], actor="cron")
                    if r.get("applied"):
                        logger.info("[readjustment-cron] %s: %s aplicados (+R$ %.2f)",
                                    c["id"], r["applied"], r["total_revenue_increase"])
                except Exception as e:
                    logger.warning("[readjustment-cron] empresa %s falhou: %s",
                                   c.get("id"), e)
        scheduler.add_job(_readjustment_daily_all_companies,
                          CronTrigger(hour=4, minute=0),
                          id="readjustment_daily", replace_existing=True)
        # Cron: NOTIFICAÇÃO WhatsApp 30d antes do reajuste — diário 09:00
        async def _readjustment_notify_all_companies():
            from services.readjustment_notifications import (
                notify_upcoming_readjustments,
            )
            async for c in db.companies.find({}, {"_id": 0, "id": 1}):
                try:
                    r = await notify_upcoming_readjustments(c["id"], days_ahead=30)
                    if r.get("sent"):
                        logger.info("[readjustment-notify-cron] %s: %s WhatsApps "
                                    "enviados", c["id"], r["sent"])
                except Exception as e:
                    logger.warning("[readjustment-notify-cron] %s falhou: %s",
                                   c.get("id"), e)
        scheduler.add_job(_readjustment_notify_all_companies,
                          CronTrigger(hour=9, minute=0),
                          id="readjustment_notify_daily", replace_existing=True)
        # Cron: ALVARO IA daily — análise consolidada às 06:00 (próximas 24h)
        async def _alvaro_daily_all_companies():
            from services.alvaro_ai import run_daily_analysis
            async for cdoc in db.companies.find({}, {"_id": 0, "id": 1}):
                cid = cdoc.get("id")
                if not cid:
                    continue
                try:
                    await run_daily_analysis(cid, hours_back=24)
                except Exception as e:
                    logger.warning("[alvaro] daily run company=%s falhou: %s", cid, e)
        scheduler.add_job(_alvaro_daily_all_companies,
                          CronTrigger(hour=6, minute=0),
                          id="alvaro_ia_daily", replace_existing=True)
        # Cron: DISPARO IA daily — 06:30 (30min após o Alvaro fechar o relatório)
        # Gera sugestões de campanhas automaticamente para cada company.
        async def _disparo_daily_all_companies():
            from services.disparo_ai import generate_campaign_suggestions
            async for cdoc in db.companies.find({}, {"_id": 0, "id": 1}):
                cid = cdoc.get("id")
                if not cid:
                    continue
                try:
                    result = await generate_campaign_suggestions(
                        cid, max_suggestions=6,
                    )
                    logger.info(
                        "[disparo_ia] daily run company=%s gerou %d sugestões",
                        cid, result.get("suggestions_created", 0),
                    )
                except Exception as e:
                    logger.warning(
                        "[disparo_ia] daily run company=%s falhou: %s", cid, e,
                    )
        scheduler.add_job(_disparo_daily_all_companies,
                          CronTrigger(hour=6, minute=30),
                          id="disparo_ia_daily", replace_existing=True)
        asyncio.create_task(routes_plans.adjustment_scheduler_worker())
        # Cron: BILLING DUNNING — todo dia 07:00 avalia régua de cobrança em todas
        # as empresas. Não envia mensagens reais ainda (apenas grava eventos);
        # essa flag será habilitada por empresa quando Meta WhatsApp Cloud estiver
        # estável (Módulo P1 do roadmap ISP).
        async def _billing_dunning_all_companies():
            from routes.billing import _evaluate_dunning_for_company
            async for cdoc in db.companies.find({}, {"_id": 0, "id": 1}):
                cid = cdoc.get("id")
                if not cid:
                    continue
                try:
                    result = await _evaluate_dunning_for_company(cid, actor_email="system_cron")
                    logger.info(
                        "[billing] dunning company=%s events=%d invoices=%d",
                        cid, result.get("events_triggered", 0),
                        result.get("invoices_evaluated", 0),
                    )
                except Exception as e:
                    logger.warning("[billing] dunning company=%s falhou: %s", cid, e)
        scheduler.add_job(_billing_dunning_all_companies,
                          CronTrigger(hour=7, minute=0),
                          id="billing_dunning_daily", replace_existing=True)
        # NEO • Relatórios Agendados — dispatcher a cada 5 min
        from routes.neo_reports import dispatch_due_schedules_job
        scheduler.add_job(dispatch_due_schedules_job,
                          "interval", minutes=5,
                          id="neo_reports_dispatcher", replace_existing=True)
        from services.drive_backup import daily_backup_worker as drive_daily_worker
        asyncio.create_task(drive_daily_worker())
        # iter215ab — Preventive OS worker (verifica a cada minuto se é
        # 08:30 BRT pra empresas com preventive_os.enabled=True)
        from routes.preventive_os import preventive_os_daily_worker
        asyncio.create_task(preventive_os_daily_worker())
        # iter215am — Worker que analisa fotos de ONT (retirada/troca sem SN
        # SmartOLT) com Claude Sonnet 4.6 e atualiza estoque do técnico.
        from services.sn_photo_worker import sn_photo_worker
        asyncio.create_task(sn_photo_worker())
        # Isabella Incident Commander — varredura preditiva de incidentes
        # coletivos (CTO/bairro/ONU) a cada 15 min sobre dados reais.
        from services.isabella_incident import isabella_incident_worker
        asyncio.create_task(isabella_incident_worker())
        # Isabella Commanders (Churn/Dunning/Revenue/Twin/Expansion + Conselho)
        # — varredura unificada a cada 30 min + reunião diária do conselho.
        from services.isabella_commanders_worker import isabella_commanders_worker
        asyncio.create_task(isabella_commanders_worker())
        # Synthetic Tenant Guard — blindagem contra inflação por sintéticos.
        # Roda a cada 1h, classifica tenants novos e alerta CTO via system_alerts.
        try:
            from workers.synthetic_tenant_guard import worker_loop as _stg_loop
            asyncio.create_task(_stg_loop(interval_sec=3600))
        except Exception as e:
            logger.warning("[startup] synthetic_tenant_guard: %s", e)
        # CTO 2026-02 — Worker de Reconciliação OS (Q4=b). Reprocessa
        # tickets `pendente_conciliacao` quando SmartOLT volta.
        try:
            from services.os_inventory_reconciliation import worker_loop as _osrec
            asyncio.create_task(_osrec())
        except Exception as e:
            logger.warning("[startup] os_inventory_reconciliation: %s", e)
        # Migração one-shot — unifica OpenRouter keys em motor_ia_config
        try:
            from services.openrouter_unify_migration import run_once as _ourun
            asyncio.create_task(_ourun())
        except Exception as e:
            logger.warning("[startup] openrouter_unify: %s", e)
        # Shield indexes (audit chain / event signing anti-replay / observ.)
        try:
            from services.audit_chain import ensure_indexes as _aci
            from services.event_signing import ensure_indexes as _esi
            from services.observability import ensure_indexes as _oi
            from services.shield_daily_audit import (
                ensure_indexes as _sda_idx, register_scheduler as _sda_reg)
            from services.message_aggregator import ensure_indexes as _ma_idx
            from services.wa_reply_scheduler import (
                ensure_indexes as _wrs_idx,
                start_worker as _wrs_start)
            from services.customer_memory import (
                ensure_indexes as _cm_idx)
            from services.isabella_confidence import (
                ensure_indexes as _ic_idx,
                register_scheduler as _ic_reg)
            from services.pj_lead_router import (
                ensure_indexes as _pj_idx)
            from services.nervous_autodiscovery import (
                ensure_indexes as _nva_idx, register_scheduler as _nva_reg)
            from services.orphan_event_watcher import (
                ensure_indexes as _oew_idx, register_scheduler as _oew_reg)
            asyncio.create_task(_aci())
            asyncio.create_task(_esi())
            asyncio.create_task(_oi())
            asyncio.create_task(_sda_idx())
            asyncio.create_task(_ma_idx())
            asyncio.create_task(_wrs_idx())
            asyncio.create_task(_wrs_start())
            asyncio.create_task(_cm_idx())
            asyncio.create_task(_ic_idx())
            _ic_reg(scheduler)
            asyncio.create_task(_pj_idx())
            asyncio.create_task(_nva_idx())
            asyncio.create_task(_oew_idx())
            _sda_reg(scheduler)
            _nva_reg(scheduler)
            _oew_reg(scheduler)
        except Exception as e:
            logger.warning("[startup] shield indexes: %s", e)
        # NOTE: o worker da isabella_queue foi SEPARADO em processo dedicado
        # (programa supervisor `isabella-worker`). NÃO inicialize aqui — webhook
        # HTTP deve ficar isolado do processamento LLM/Twilio.
        logger.info("Scheduler iniciado.")

    async def _leader_election_loop() -> None:
        from services.scheduler_lock import try_acquire_leader
        import asyncio as _a
        first_tick = True
        while True:
            try:
                is_leader = await try_acquire_leader()
                if is_leader and not _leader_state["started"]:
                    try:
                        await _start_leader_jobs()
                    except Exception as e:
                        logger.exception(
                            "[election] _start_leader_jobs falhou: %s", e)
                        _leader_state["started"] = False
                elif not is_leader and first_tick:
                    logger.info(
                        "[startup] FOLLOWER worker (pid=%s) — leader já "
                        "eleito; tentará reassumir a cada 15s se lock "
                        "expirar", os.getpid())
            except Exception as e:
                logger.warning("[election] tick falhou: %s", e)
            first_tick = False
            await _a.sleep(15)

    asyncio.create_task(_leader_election_loop(), name="leader-election")


@app.on_event("shutdown")
async def _shutdown() -> None:
    # CTO 12/06/2026 fix: libera o lock para que o próximo restart
    # eleja leader limpo (evita FOLLOWER permanente em todos workers).
    try:
        from services.scheduler_lock import release_leader
        await release_leader()
    except Exception as _e:
        logger.warning("[shutdown] release_leader falhou: %s", _e)
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        routes_atlaz.stop_worker()
    except Exception:
        pass
    try:
        routes_mass_messaging.stop_worker()
    except Exception:
        pass
    client.close()


# Backward-compat re-export para imports lazy em routes/
dashboard_overtime = routes_clock.dashboard_overtime  # routes/dashboard.py importa daqui


# Inclui todos os routers (cada um já vem com prefix="/api")
app.include_router(routes_users.router)
app.include_router(routes_rede_cell.router)
app.include_router(routes_rede_cell.watch_router)
from routes import ia_patrimonial as routes_ia_patrimonial  # noqa: E402
app.include_router(routes_ia_patrimonial.router)
app.include_router(routes_ia_patrimonial.watch_cost_router)
from routes import audit_users as routes_audit_users  # noqa: E402
app.include_router(routes_audit_users.router)
from routes import os_lifecycle as routes_os_lifecycle  # noqa: E402
app.include_router(routes_os_lifecycle.router)
from routes import access_profiles as routes_access_profiles  # noqa: E402
app.include_router(routes_access_profiles.router)
from routes import ai_center_v51 as routes_ai_center_v51  # noqa: E402
app.include_router(routes_ai_center_v51.router)
from routes import ceo_digital as routes_ceo_digital  # noqa: E402
app.include_router(routes_ceo_digital.router)
from routes import ai_center_observability as routes_observ  # noqa: E402
app.include_router(routes_observ.router)
from routes import ai_center_homologation as routes_homo  # noqa: E402
app.include_router(routes_homo.router)
# ─── Safety Admin (Kill Switch + Backup + Vault) ─────────────
from routes import admin_safety as routes_admin_safety  # noqa: E402
app.include_router(routes_admin_safety.router)

from routes import admin_password_reset as routes_admin_pwd_reset  # noqa: E402
app.include_router(routes_admin_pwd_reset.router)

from routes import admin_wa_sidecar as routes_admin_wa_sidecar  # noqa: E402
app.include_router(routes_admin_wa_sidecar.router)

from routes import auth_debug as routes_auth_debug  # noqa: E402
app.include_router(routes_auth_debug.router)
# ─── Integration Credentials (Grafana/Zabbix via Vault) ──────
from routes import admin_integrations as routes_admin_int  # noqa: E402
app.include_router(routes_admin_int.router)
# ─── OLT Registry (SNMP direto V-SOL) ────────────────────────
from routes import olt_registry as routes_olt_reg  # noqa: E402
app.include_router(routes_olt_reg.router)
# ─────────────────────────────────────────────────────────────
from routes import ai_center_v6 as routes_ai_center_v6  # noqa: E402
app.include_router(routes_ai_center_v6.router)
from routes import ai_center_v7 as routes_ai_center_v7  # noqa: E402
app.include_router(routes_ai_center_v7.router)
# Integra scheduler V5.1 quando o APScheduler global existir
try:
    from services import scheduler_v51 as _sched_v51  # noqa: E402
    import server as _srv_self  # noqa: E402
    if hasattr(_srv_self, "scheduler"):
        _sched_v51.start_scheduler(_srv_self.scheduler)
except Exception as _e:
    import logging as _logging
    _logging.getLogger("server").warning(
        "V5.1 scheduler not started: %r", _e)
app.include_router(routes_pracas.router)
app.include_router(routes_clock.router)
app.include_router(routes_locations.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_admin.router)
app.include_router(routes_colosso.router)
app.include_router(routes_colosso_fin.router)
app.include_router(routes_colosso_fin.id_router)
app.include_router(routes_isabella_lousa.router)
app.include_router(routes_isabella_memory.router)

# iter232 — App estático do Colaborador (PWA standalone, served em /api/colaborador/)
try:
    from fastapi.staticfiles import StaticFiles
    import os as _os
    _colab_dir = _os.path.join(_os.path.dirname(__file__), "static", "colaborador")
    if _os.path.isdir(_colab_dir):
        app.mount("/api/colaborador",
                   StaticFiles(directory=_colab_dir, html=True),
                   name="colaborador_app")
except Exception as _e:
    import logging as _lg
    _lg.getLogger("ponto").warning("[colaborador] mount falhou: %s", _e)
# iter205 — Backup MongoDB endpoints (super-admin only)
from routes import backup as routes_backup  # noqa: E402
app.include_router(routes_backup.router)
app.include_router(routes_ai_config.router)
app.include_router(routes_push.router)
app.include_router(routes_collab_auth.router)
app.include_router(routes_logs.router)
app.include_router(routes_lousa.router)
app.include_router(routes_lousa_callbacks.router)
app.include_router(routes_mobile_health.router)
from routes import lousa_tv as routes_lousa_tv  # noqa: E402
app.include_router(routes_lousa_tv.router)
from routes import lousa_rompimento as routes_lousa_rompimento  # noqa: E402
app.include_router(routes_lousa_rompimento.router)
from routes import customer_loyalty as routes_customer_loyalty  # noqa: E402
app.include_router(routes_customer_loyalty.router)
from routes import loyalty_imported_db as routes_loyalty_db  # noqa: E402
app.include_router(routes_loyalty_db.router)
# iter215ab — Preventive OS (OS auto-criadas pra encher grade ociosa)
from routes import preventive_os as routes_preventive_os  # noqa: E402
app.include_router(routes_preventive_os.router)
from routes import loyalty_ai as routes_loyalty_ai  # noqa: E402
app.include_router(routes_loyalty_ai.router)
from routes import loyalty_opportunities_ai as routes_loyalty_opp_ai  # noqa: E402
app.include_router(routes_loyalty_opp_ai.router)
from routes import loyalty_dispatch as routes_loyalty_dispatch  # noqa: E402
app.include_router(routes_loyalty_dispatch.router)
from routes import loyalty_insights as routes_loyalty_insights  # noqa: E402
app.include_router(routes_loyalty_insights.router)
app.include_router(routes_atlaz.router)
app.include_router(routes_events.router)
app.include_router(routes_saas.router)
app.include_router(routes_saas.webhook_router)
app.include_router(routes_stok.router)
# iter211ac — ErrorBoundary log endpoint (client crashes)
from routes import client_errors as routes_client_errors  # noqa: E402
app.include_router(routes_client_errors.router)
app.include_router(routes_balanco.router)
app.include_router(routes_projects.router)
app.include_router(routes_wifi.router)
app.include_router(routes_wifi_hotspot.router)
app.include_router(routes_billing.router)
app.include_router(routes_pdf_reports.router)
app.include_router(routes_smartolt.router)
app.include_router(routes_network_diag.router)
app.include_router(routes_ai_preventive.router)
app.include_router(routes_ai_dashboard.router)
app.include_router(routes_aihub.router)
app.include_router(routes_motor_ia.router)
app.include_router(routes_conselho_ia.router)
app.include_router(routes_presidente_ia.router)
app.include_router(routes_presidente_agentes.router)
app.include_router(routes_lousa_sala.router)
app.include_router(routes_lousa_sala_config.router)
app.include_router(routes_aihub_prompts.router)
app.include_router(routes_user_magic_links.router)
app.include_router(routes_sala_orphan_health.router)
app.include_router(routes_isabella_churn.router)
app.include_router(routes_isabella_pj.router)
app.include_router(routes_isabella_watchtower.router)
app.include_router(routes_treasury.router)
app.include_router(routes_audit_log.router)
app.include_router(routes_backend_health.router)
app.include_router(routes_warroom.router)
# Sprints 10/11/12 — feedback loop, predictions, learnings + leader
from routes import motor_ia_intel as routes_motor_ia_intel  # noqa: E402
from routes import operacao_tese as routes_operacao_tese  # noqa: E402
from routes import ai_center_revenue as routes_ai_center_revenue  # noqa: E402
from routes import ai_center_data_quality as routes_ai_center_dq  # noqa: E402
from routes import ai_center_nervous_system as routes_ai_center_ns  # noqa: E402
from routes import ai_center_smartolt_twin as routes_ai_center_twin  # noqa: E402
from routes import ai_center_home as routes_ai_center_home  # noqa: E402
from routes import ai_center_isabella as routes_ai_center_isabella  # noqa: E402
from routes import ai_center_knowledge_graph as routes_ai_center_kg  # noqa: E402
from routes import ai_center_alvaro as routes_ai_center_alvaro  # noqa: E402
from routes import ai_center_alvaro_v5 as routes_ai_center_alvaro_v5  # noqa: E402
from routes import ai_center_failure_risk as routes_ai_center_frs  # noqa: E402
from routes import ai_center_multitenant as routes_ai_center_mt  # noqa: E402
from routes import ai_center_financial as routes_ai_center_fin  # noqa: E402
from routes import public_smartprov as routes_public_smartprov  # noqa: E402
from routes import ai_center_autonomous as routes_ai_center_auto  # noqa: E402
from routes import ai_center_blockers as routes_ai_center_blk  # noqa: E402
from routes import ai_center_predictive as routes_ai_center_pred  # noqa: E402
from routes import ai_center_v62 as routes_ai_center_v62  # noqa: E402
from routes import ai_center_cash as routes_ai_center_cash  # noqa: E402
from routes import ai_center_v80 as routes_ai_center_v80  # noqa: E402
app.include_router(routes_motor_ia_intel.router)
app.include_router(routes_operacao_tese.router)
app.include_router(routes_ai_center_revenue.router)
app.include_router(routes_ai_center_dq.router)
app.include_router(routes_ai_center_ns.router)
app.include_router(routes_ai_center_twin.router)
app.include_router(routes_ai_center_home.router)
app.include_router(routes_ai_center_isabella.router)
app.include_router(routes_ai_center_kg.router)
app.include_router(routes_ai_center_alvaro.router)
app.include_router(routes_ai_center_alvaro_v5.router)
app.include_router(routes_ai_center_frs.router)
app.include_router(routes_ai_center_mt.router)
app.include_router(routes_ai_center_fin.router)
app.include_router(routes_public_smartprov.router)
app.include_router(routes_ai_center_auto.router)
app.include_router(routes_ai_center_blk.router)
app.include_router(routes_ai_center_pred.router)
app.include_router(routes_ai_center_v62.router)
app.include_router(routes_ai_center_cash.router)
app.include_router(routes_ai_center_v80.router)
app.include_router(routes_diagnostic_report.router)
app.include_router(routes_pre_attendance.router)
app.include_router(routes_wa_campaigns.router)
app.include_router(routes_diagnostic.router)
app.include_router(routes_smartolt_ai.router)
app.include_router(routes_ai_topology.router)
app.include_router(routes_copilot_ranking.router)
app.include_router(routes_sentinela_lousa.router)
app.include_router(routes_lousa_ai.router)
app.include_router(routes_voice.router)
app.include_router(routes_wa_baileys.router)
app.include_router(routes_wa_business_hours.router)
app.include_router(routes_isabella_prompt.router)
app.include_router(routes_isabella_negotiation.router)
app.include_router(routes_interactions.router)
app.include_router(routes_pricing_catalog.router)
app.include_router(routes_central_ia.router)
app.include_router(routes_rede_ia.router)
app.include_router(routes_rede_ia_map.router)
app.include_router(routes_rede_ia_kmz.router)
app.include_router(routes_rede_ia_signals.router)
app.include_router(routes_cto_ports_base.router)
app.include_router(routes_radius.router)
app.include_router(routes_contracts.router)
app.include_router(routes_clients_segments.router)
app.include_router(routes_lousa_map.router)
app.include_router(routes_payment_charges.router)
app.include_router(routes_provider_site.router)
app.include_router(routes_fleet.router)
app.include_router(routes_fleet_tracking.router)
app.include_router(routes_fleet_portal.router)
app.include_router(routes_fleet_portal.admin_router)
app.include_router(routes_security_home.router)
app.include_router(routes_security_home.portal_router)
app.include_router(routes_parceria.router)
app.include_router(routes_parceria.partner_router)
app.include_router(routes_parceria.client_router)
app.include_router(routes_referrals.router)
app.include_router(routes_budget.router)
app.include_router(routes_churn.router)
app.include_router(routes_subscribers.router)
app.include_router(routes_plans.router)
app.include_router(routes_branding.router)
app.include_router(routes_collab_assets.router)
app.include_router(routes_vehicle_checklist.router)
app.include_router(routes_field_ops.router)
app.include_router(routes_isabella_field.router)
app.include_router(routes_isabella_commanders.router)
app.include_router(routes_universo_ligo.router)
app.include_router(routes_universo_ligo_curadoria.router)
app.include_router(routes_customer_intelligence.router)
app.include_router(routes_shield.router)
app.include_router(routes_nervous_foundation.router)
app.include_router(routes_whatsapp_twilio.router)
app.include_router(routes_whatsapp_meta.router)
app.include_router(routes_holerite.router)
app.include_router(routes_feriados.router)
app.include_router(routes_checklist_ai.router)
app.include_router(routes_secretaria.router)
app.include_router(routes_drive.router)
app.include_router(routes_ai_corrections.router)
app.include_router(routes_appointments.router)
app.include_router(routes_integrations.router)
app.include_router(routes_ai_training.router)
app.include_router(routes_connections.router)
app.include_router(routes_financeiro.router)
app.include_router(routes_financeiro_ops.router)
app.include_router(routes_financeiro_analytics.router)
app.include_router(routes_financeiro_reports.router)
app.include_router(routes_atlaz_financeiro.router)
app.include_router(routes_atlaz_webhooks.router)
app.include_router(routes_ligo_tv.router)
app.include_router(routes_alvaro.router)
app.include_router(routes_sprint5_onda1.router)
app.include_router(routes_sprint5_onda2.router)
app.include_router(routes_sprint5_onda3.router)
app.include_router(routes_sprint5_onda4.router)
app.include_router(routes_sprint5_onda5.router)
app.include_router(routes_sprint5_onda6.router)
app.include_router(routes_sprint5_swap_events.router)
app.include_router(routes_sprint5_audit_op.router)
app.include_router(routes_sprint5_e2e.router)
app.include_router(routes_alvaro_os_summary.router)
app.include_router(routes_gps_vlan_suggest.router)
app.include_router(routes_smartolt_push_ctos.router)
app.include_router(routes_whatsapp_config.router)
app.include_router(routes_wa_test_mode.router)
app.include_router(routes_wa_channels.router)
app.include_router(routes_mass_messaging.router)
app.include_router(routes_disparo_ia.router)
app.include_router(routes_disparo_boleto.router)
app.include_router(routes_boleto_template.router)
app.include_router(routes_gestao_ia.router)
app.include_router(routes_isabella_kpis.router)
app.include_router(routes_sales_funnel.router)
app.include_router(routes_onboarding.router)
app.include_router(routes_tv_dashboards.router)
app.include_router(routes_utils.router)
app.include_router(routes_financeiro_reajuste.router)
app.include_router(routes_public_access.router)
app.include_router(routes_disparo_promo.router)
app.include_router(routes_bank_import.router)
from routes import data_health as routes_data_health  # noqa: E402
app.include_router(routes_data_health.router)
from routes import purchases as routes_purchases  # noqa: E402
app.include_router(routes_purchases.router)
from routes import neo_reports as routes_neo_reports  # noqa: E402
app.include_router(routes_neo_reports.router)
from routes import neo_chat as routes_neo_chat  # noqa: E402
app.include_router(routes_neo_chat.router)
from routes import ont_scan as routes_ont_scan  # noqa: E402
app.include_router(routes_ont_scan.router)
from routes import stok_transfers as routes_stok_transfers  # noqa: E402
app.include_router(routes_stok_transfers.router)
from routes import projetos_propostas as routes_projetos_propostas  # noqa: E402
app.include_router(routes_projetos_propostas.router)
from routes import network_test as routes_network_test  # noqa: E402
app.include_router(routes_network_test.router)
app.include_router(routes_retirada_template.router)
app.include_router(routes_os_validation_toggles.router)
app.include_router(routes_tech_tracking.router)
from routes import kpi_churn as routes_kpi_churn  # noqa: E402
app.include_router(routes_kpi_churn.router)
from routes import ligo_maps as routes_ligo_maps  # noqa: E402
app.include_router(routes_ligo_maps.router)
# Sprint 1 (CEO 16/02/2026) — Watchtower Estoque (Dashboard Patrimonial Executivo)
from routes import watchtower_estoque as routes_watchtower_estoque  # noqa: E402
app.include_router(routes_watchtower_estoque.router)
from routes import watchtower_estoque_diagnostico as routes_watchtower_estoque_diag  # noqa: E402
app.include_router(routes_watchtower_estoque_diag.router)
from routes import swap_confirmation as routes_swap_confirmation  # noqa: E402
app.include_router(routes_swap_confirmation.router)
from routes import watchtower_patrimonio_consolidado as routes_pat_cons  # noqa: E402
app.include_router(routes_pat_cons.router)
# CTO 17/02/2026 — Retry de mensagens IA com falha do sidecar Baileys
from routes import wa_retry_failed as routes_wa_retry_failed  # noqa: E402
app.include_router(routes_wa_retry_failed.router)
from routes import wa_watchdog as routes_wa_watchdog  # noqa: E402
app.include_router(routes_wa_watchdog.router)
from routes import isabella_learning_health as routes_isabella_lh  # noqa: E402
app.include_router(routes_isabella_lh.router)


# ============================================================
# Security Headers Middleware
# ============================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adiciona headers de segurança em TODAS as respostas.

    Protege contra: clickjacking, MIME-sniffing, XSS reflexivo, downgrade HTTPS.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(self), microphone=(self), camera=(self), payment=()",
        )
        # CSP relaxado pra não quebrar SPA atual (sem nonces dinâmicos).
        # Bloqueia frames externos e mantém compatibilidade com inline-styles
        # do Tailwind + React.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.preview.emergentagent.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "connect-src 'self' https: wss:; "
            "frame-ancestors 'none';",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)
from services.observability import MetricsMiddleware as _ShieldObsMW
app.add_middleware(_ShieldObsMW)


# ============================================================
# CORS — bloqueio padrão; whitelist em CORS_ORIGINS
# ============================================================
def _parse_origins() -> tuple[list, bool]:
    raw = (os.environ.get("CORS_ORIGINS") or "").strip()
    if not raw or raw == "*":
        # Wildcard explícito (compat). Aviso visível nos logs.
        logging.getLogger("security").warning(
            "CORS_ORIGINS está vazio ou '*' — em produção, defina domínios específicos."
        )
        return (["*"], False)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return (origins, True)


_cors_origins, _cors_safe = _parse_origins()
app.add_middleware(
    CORSMiddleware,
    # `allow_credentials=True` exige origins explícitos (não pode ser `*`)
    allow_credentials=_cors_safe,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-RateLimit-Remaining"],
)
