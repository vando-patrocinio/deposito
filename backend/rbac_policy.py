"""
rbac_policy.py — Sprint 2: Política de acesso global (iter221)

Em vez de editar 128 arquivos de rotas, aplicamos RBAC via middleware
único que casa o path da requisição contra uma policy declarativa.

Regras:
  - PUBLIC_PATHS: passam sem auth (webhooks, login, ingest com token)
  - AUTH_ONLY: precisam apenas JWT válido (catch-all default)
  - ROLE_RULES: prefixos que exigem perfil específico
  - DELETE/EXPORT: regra extra (audit obrigatório + admin/gestor)
"""
from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple


# ─────────────────── Públicos (sem auth) ───────────────────
# Casamento por prefix EXATO (path.startswith) ou regex.
PUBLIC_PATHS: List[str] = [
    "/api/about",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/forgot",
    "/api/auth/reset",
    "/api/auth/google-login",
    "/api/auth/magic-login",
    "/api/auth/logout",
    "/api/admin/reset-super-admin-password",
    "/api/payments/webhook/",
    "/api/webhook/",
    "/api/oauth/drive/callback",
    "/api/whatsapp-baileys/webhook",
    "/api/whatsapp-twilio/webhook",
    "/api/whatsapp-baileys/inbound",
    "/api/tech-tracking/public/",
    "/api/collab-assets/public/",
    "/api/fleet-portal/auth/",
    "/api/security-portal/auth/",
    "/api/wifi/portal",
    "/api/wifi-hotspot/portal",
    "/api/wifi-hotspot/auth",
    "/api/site/",
    "/api/branding/public",
    "/api/events/stream",
    "/api/events/stats",
    "/api/health",
    "/api/version",
    "/api/q/",   # short links /api/q/<token>
    "/api/r/",   # redirect short links
    "/api/lousa/onu-bridge/redirect/",  # iter232 — token na URL é a auth
    "/api/colaborador/",  # iter232 — app PWA estático do colaborador
    "/api/public/smartprov-ai-center",  # FASE 9 — landing pública V5.0
    "/api/rede-ia/public/",  # App PWA do técnico externo (auth via collab_id na URL)
    "/api/treasury/webhooks/asaas",
    "/docs", "/redoc", "/openapi.json",
]


# Endpoints com fluxo de auth próprio (CPF, JWT de cliente/parceiro,
# magic-link). NÃO se aplica role-rule corporativa — o handler valida
# o JWT específico. Contam como "protegidos por auth alternativa".
NON_STAFF_AUTH_PREFIXES: List[str] = [
    "/api/customer",
    "/api/cliente-portal",
    "/api/parceiro-portal",
    "/api/fleet-portal",
    "/api/security-portal",
    "/api/collaborator-auth",
    "/api/wifi-hotspot/portal",
]


# ─────────────────── Role rules ───────────────────
# Tuplas (prefixo, roles permitidos). Match por longest-prefix.
# Admins SEMPRE passam (handled em rbac.require_roles).
ROLE_RULES: List[Tuple[str, Set[str]]] = [
    # ─── Financeiro: só financeiro/gestor/auditor/admin ───
    ("/api/financeiro",          {"financeiro", "gestor", "auditor"}),
    ("/api/payments",            {"financeiro", "gestor"}),
    ("/api/billing",             {"financeiro", "gestor"}),
    ("/api/dunning",             {"financeiro", "gestor"}),
    ("/api/holerites",           {"financeiro", "gestor", "auditor"}),
    ("/api/holerite",            {"financeiro", "gestor", "auditor"}),
    ("/api/bank-import",         {"financeiro", "gestor"}),
    ("/api/purchases",           {"financeiro", "gestor"}),
    ("/api/contracts",           {"financeiro", "gestor"}),
    ("/api/saas",                {"gestor", "auditor"}),
    ("/api/boleto",              {"financeiro", "gestor"}),
    ("/api/balanco",             {"financeiro", "gestor", "auditor"}),
    ("/api/atlaz",               {"financeiro", "gestor", "auditor"}),
    ("/api/atlaz-financeiro",    {"financeiro", "gestor", "auditor"}),
    ("/api/budget",              {"financeiro", "gestor"}),
    ("/api/plans",               {"financeiro", "gestor"}),
    ("/api/payment-charges",     {"financeiro", "gestor"}),
    ("/api/disparo-boleto",      {"financeiro", "gestor"}),

    # ─── IA: gestor + auditor (com rate-limit) ───
    ("/api/presidente-ia",       {"gestor", "auditor"}),
    ("/api/conselho-ia",         {"gestor", "auditor"}),
    ("/api/motor-ia",            {"gestor", "auditor"}),
    ("/api/alvaro",              {"gestor", "auditor"}),
    ("/api/central-ia",          {"gestor", "auditor", "atendimento"}),
    ("/api/rede-ia",             {"gestor", "auditor", "tecnico"}),
    ("/api/ai-training",         {"gestor"}),
    ("/api/ai-config",           {"administrador"}),
    ("/api/ai-corrections",      {"gestor", "auditor"}),
    ("/api/ai/preventive",       {"gestor", "auditor", "tecnico"}),
    ("/api/aihub",               {"gestor", "atendimento"}),
    ("/api/disparo-ia",          {"gestor"}),
    ("/api/secretaria",          {"gestor", "auditor"}),
    ("/api/neo-reports",         {"gestor", "auditor"}),
    ("/api/neo-chat",            {"gestor", "auditor", "atendimento"}),
    ("/api/copilot-ranking",     {"gestor", "auditor"}),
    ("/api/smartolt-ai",         {"gestor", "tecnico"}),
    ("/api/ai-topology",         {"gestor", "tecnico"}),
    ("/api/sentinela-lousa",     {"gestor", "auditor", "tecnico"}),
    ("/api/lousa-ai",            {"gestor", "tecnico"}),
    ("/api/loyalty-ai",          {"gestor", "atendimento"}),
    ("/api/loyalty-opportunities-ai", {"gestor", "atendimento"}),
    ("/api/checklist-ai",        {"gestor", "tecnico"}),
    ("/api/gestao-ia",           {"gestor", "auditor"}),
    ("/api/isabella",            {"gestor", "auditor"}),
    ("/api/voice",               {"gestor", "atendimento", "auditor"}),

    # ─── Operação / Lousa / Tickets ───
    # `colaborador` (tecnico em campo) precisa ler a propria lousa via mobile.
    # Endpoints destrutivos/administrativos em /api/lousa/* tem guard proprio
    # (require_role("gestor"/"administrador")), portanto o middleware so libera
    # leitura — qualquer escrita continua bloqueada pelo handler.
    ("/api/lousa",               {"gestor", "tecnico", "atendimento",
                                    "auditor", "colaborador"}),
    ("/api/tickets",             {"gestor", "tecnico", "atendimento",
                                    "auditor", "colaborador"}),
    ("/api/ticket-quality",      {"gestor", "auditor"}),
    ("/api/preventive-os",       {"gestor", "tecnico"}),
    ("/api/projects",            {"gestor", "tecnico"}),
    ("/api/propostas",           {"gestor", "atendimento"}),
    ("/api/projetos-propostas",  {"gestor", "atendimento"}),
    ("/api/appointments",        {"gestor", "atendimento", "tecnico"}),
    ("/api/sales-funnel",        {"gestor", "atendimento"}),

    # ─── Rede / OLT / CTOs / WiFi corporativo ───
    ("/api/smartolt",            {"gestor", "tecnico", "auditor"}),
    ("/api/cto-ports",           {"gestor", "tecnico"}),
    ("/api/ligo-maps",           {"gestor", "tecnico", "auditor"}),
    ("/api/onu",                 {"gestor", "tecnico"}),
    ("/api/ont-scan",            {"gestor", "tecnico"}),
    ("/api/network",             {"gestor", "tecnico"}),
    ("/api/network-test",        {"gestor", "tecnico"}),
    ("/api/network-diag",        {"gestor", "tecnico"}),
    ("/api/wifi",                {"gestor", "tecnico"}),
    ("/api/wifi-hotspot",        {"gestor", "atendimento"}),
    ("/api/radius",              {"gestor", "tecnico"}),
    ("/api/connections",         {"gestor", "tecnico"}),
    ("/api/gps-vlan-suggest",    {"gestor", "tecnico"}),

    # ─── Frota ───
    # `colaborador` (tecnico em campo) precisa odom/checklist/tracking do dia via mobile.
    ("/api/fleet",               {"gestor", "tecnico", "auditor", "colaborador"}),
    ("/api/tech-tracking",       {"gestor", "tecnico", "auditor", "colaborador"}),
    ("/api/vehicle-checklist",   {"gestor", "tecnico", "colaborador"}),
    ("/api/vehicle-silhouettes", {"gestor", "tecnico", "colaborador"}),
    ("/api/locations",           {"gestor", "tecnico", "atendimento",
                                    "auditor", "colaborador"}),
    ("/api/geofences",           {"administrador", "gestor"}),

    # ─── Ponto eletrônico / Colaboradores ───
    # `colaborador` precisa: bater ponto, ver proprio cadastro,
    # ver pertences vinculados. Endpoints de admin (criar/editar outros
    # colaboradores) continuam com guard proprio no handler.
    ("/api/collaborators",       {"administrador", "gestor", "colaborador"}),
    ("/api/clock-records",       {"gestor", "auditor", "atendimento", "colaborador"}),
    ("/api/timesheets",          {"gestor", "auditor", "financeiro"}),
    ("/api/timesheets-collective", {"gestor", "auditor", "financeiro"}),
    ("/api/collab-assets",       {"gestor", "tecnico", "colaborador"}),
    ("/api/cargo",               {"administrador", "gestor"}),

    # ─── Estoque ───
    ("/api/stok",                {"gestor", "tecnico", "auditor"}),

    # ─── Clientes / Atendimento ───
    ("/api/subscribers",         {"gestor", "atendimento", "auditor",
                                    "financeiro"}),
    ("/api/clients-segments",    {"gestor", "atendimento"}),
    ("/api/sales",               {"gestor", "atendimento"}),
    ("/api/customer-loyalty",    {"gestor", "atendimento"}),
    ("/api/loyalty",             {"gestor", "atendimento"}),
    ("/api/loyalty-dispatch",    {"gestor", "atendimento"}),
    ("/api/loyalty-insights",    {"gestor", "auditor"}),
    ("/api/loyalty-imported-db", {"gestor", "atendimento"}),
    ("/api/churn",               {"gestor", "financeiro", "auditor"}),
    ("/api/kpi-churn",           {"gestor", "auditor"}),
    ("/api/isabella-kpis",       {"gestor", "auditor"}),

    # ─── Campanhas WhatsApp / Parcerias ───
    ("/api/wa-campaigns",        {"gestor"}),
    ("/api/whatsapp-campaigns",  {"gestor"}),
    ("/api/mass-messaging",      {"gestor"}),
    ("/api/pre-attendance",      {"gestor", "atendimento"}),
    ("/api/whatsapp-baileys",    {"gestor", "atendimento", "auditor"}),
    ("/api/whatsapp-twilio",     {"administrador", "gestor"}),
    ("/api/whatsapp-meta",       {"administrador", "gestor"}),
    ("/api/whatsapp-channels",   {"administrador", "gestor"}),
    ("/api/whatsapp-config",     {"administrador", "gestor"}),
    ("/api/parcerias",           {"gestor", "atendimento"}),
    ("/api/parceria",            {"gestor", "atendimento"}),
    ("/api/referrals",           {"gestor", "atendimento", "auditor"}),
    ("/api/referral-campaign",   {"gestor"}),
    ("/api/disparo-promo",       {"gestor", "atendimento"}),
    ("/api/push",                {"administrador", "gestor"}),

    # ─── Relatórios / Diagnóstico / TV ───
    ("/api/conselho-ia/diagnostic-report",
                                  {"gestor", "auditor"}),
    ("/api/pdf-reports",         {"gestor", "auditor", "financeiro"}),
    ("/api/tv",                  {"gestor", "auditor"}),
    ("/api/tv-dashboards",       {"gestor", "auditor"}),
    ("/api/dashboard",           {"gestor", "auditor", "atendimento",
                                    "financeiro", "tecnico"}),
    ("/api/diagnostic",          {"gestor", "auditor"}),
    ("/api/diagnostic-report",   {"gestor", "auditor"}),
    ("/api/data-health",         {"administrador", "auditor"}),
    ("/api/financeiro-analytics", {"financeiro", "gestor", "auditor"}),
    ("/api/financeiro-reports",  {"financeiro", "gestor", "auditor"}),
    ("/api/financeiro-ops",      {"financeiro", "gestor"}),
    ("/api/financeiro-reajuste", {"financeiro", "gestor"}),

    # ─── Lousas/TV/sentinela ───
    ("/api/lousa-tv",            {"gestor", "auditor"}),
    ("/api/lousa-map",           {"gestor", "tecnico", "auditor"}),
    ("/api/lousa-score",         {"gestor", "auditor"}),
    ("/api/lousa-rompimento",    {"gestor", "tecnico", "auditor"}),
    ("/api/pracas",              {"administrador", "gestor"}),
    ("/api/feriados",            {"administrador", "gestor"}),
    ("/api/holidays",            {"administrador", "gestor"}),

    # ─── Drive / Backup ───
    ("/api/drive",               {"administrador", "gestor"}),
    ("/api/backup",              {"administrador"}),

    # ─── Logs / erros ───
    ("/api/client-errors",       {"administrador", "gestor", "auditor"}),
    ("/api/logs",                {"administrador", "gestor", "auditor"}),
    ("/api/audit-log",           {"administrador", "auditor"}),
    ("/api/email",               {"administrador"}),
    ("/api/scheduler",           {"administrador"}),
    ("/api/system",              {"administrador", "auditor"}),
    ("/api/oauth",               {"administrador"}),
    ("/api/ai/dashboard",        {"gestor", "auditor"}),
    ("/api/ai/insights",         {"gestor", "auditor"}),
    ("/api/auth-recovery",       {"administrador"}),
    ("/api/geocode",             {"administrador", "gestor",
                                    "tecnico", "atendimento", "auditor",
                                    "financeiro"}),
    ("/api/qr-token",            {"administrador", "gestor",
                                    "atendimento"}),

    # ─── Auth-admin (impersonate, admin-login, change-password) ───
    ("/api/auth/admin-login",    {"administrador"}),
    ("/api/auth/impersonate",    {"administrador"}),
    ("/api/auth/end-impersonation",
                                  {"administrador"}),
    ("/api/auth/impersonation-log",
                                  {"administrador", "auditor"}),
    ("/api/access-tags",         {"administrador", "auditor"}),

    # ─── Sprint 6 — Backend health (admin/auditor) ───
    ("/api/health-panel",        {"administrador", "auditor"}),

    # ─── Sprint 3 — Audit Trail (admin/auditor) ───
    ("/api/audit-log",           {"administrador", "auditor"}),

    # ─── Admin only ───
    ("/api/admin",               {"administrador"}),
    ("/api/integrations",        {"administrador"}),
    ("/api/onboarding",          {"administrador"}),
    ("/api/users",               {"administrador"}),
    ("/api/companies",           {"administrador"}),
    ("/api/branding",            {"administrador", "gestor"}),
    ("/api/settings",            {"administrador"}),
    ("/api/motor-ia/config",     {"administrador"}),
    ("/api/security-home",       {"administrador", "gestor"}),
    ("/api/retirada-template",   {"administrador", "gestor"}),
    ("/api/boleto-template",     {"administrador", "financeiro"}),
    ("/api/provider-site",       {"administrador", "gestor"}),
    ("/api/public-access",       {"administrador", "gestor"}),
]


# ─────────────────── IA Rate-limit ───────────────────
# Prefixos que exigem rate-limit por usuário/empresa.
# Limites: padrão 30/min, 1000/dia (sobrescrevíveis via env).
IA_RATE_LIMIT_PREFIXES: List[str] = [
    "/api/presidente-ia",
    "/api/conselho-ia",
    "/api/motor-ia",
    "/api/alvaro",
    "/api/secretaria",
    "/api/aihub",
    "/api/central-ia",
    "/api/rede-ia",
    "/api/disparo-ia",
    "/api/neo-chat",
    "/api/neo-reports",
    "/api/checklist-ai",
    "/api/ai/preventive",
    "/api/ai/dashboard",
    "/api/ai/insights",
    "/api/smartolt-ai",
    "/api/ai-topology",
    "/api/loyalty-ai",
    "/api/loyalty-opportunities-ai",
    "/api/copilot-ranking",
    "/api/sentinela-lousa",
    "/api/lousa-ai",
    "/api/voice",
    "/api/isabella",
    "/api/gestao-ia",
]


def is_ia(path: str) -> bool:
    return any(path.startswith(p) for p in IA_RATE_LIMIT_PREFIXES)


def is_non_staff_auth(path: str) -> bool:
    """Endpoints com fluxo de auth próprio (cliente/parceiro/portal).
    Não aplicamos role-rule corporativa neles."""
    for p in NON_STAFF_AUTH_PREFIXES:
        if path.startswith(p):
            return True
    return False


def is_public(path: str) -> bool:
    """True se o path é público (sem auth)."""
    if not path or not path.startswith("/api/"):
        # Frontend SPA fall-through — não é nossa zona
        return True
    for p in PUBLIC_PATHS:
        if path.startswith(p):
            return True
    return False


def required_roles_for(path: str) -> Optional[Set[str]]:
    """Devolve set de roles permitidos pra esse path (longest-prefix
    match). None = só auth necessária."""
    best: Tuple[int, Optional[Set[str]]] = (0, None)
    for prefix, roles in ROLE_RULES:
        if path.startswith(prefix) and len(prefix) > best[0]:
            best = (len(prefix), roles)
    return best[1]


# DELETE e EXPORT exigem audit + role admin/gestor
def is_destructive(method: str, path: str) -> bool:
    return method.upper() == "DELETE"


def is_export(path: str) -> bool:
    return any(s in path for s in
                 ("/export", "/download", "/pdf", "/csv", "/xlsx"))
