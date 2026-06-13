"""IAM v2 — Catálogo de Permissions (single source of truth).

Convenção: `<module>.<action>[.<scope>]`
  - module: domínio (tickets, clients, estoque, financeiro, ...)
  - action: o que faz (view, create, edit, close, delete, ...)
  - scope:  qualificador opcional (active_only, own_only, ...)

Wildcards aceitos pelo `has_permission`:
  - `*`               → super admin (libera tudo)
  - `tickets.*`       → libera todas as actions de tickets
  - `tickets.view.*`  → libera todas as views (scoped) de tickets

Toda permission DEVE estar listada aqui. Permission key fora do catálogo
gera warning no startup do iam_v2 e bloqueia (fail-safe).
"""
from __future__ import annotations

from typing import Iterable


# ──────────────────────────────────────────────────────────────────────────
# Catálogo (lista exaustiva, inicial — pode crescer)
# ──────────────────────────────────────────────────────────────────────────

PERMISSIONS: dict[str, dict[str, str]] = {
    # ──── Tickets / Lousa / OS ─────────────────────────────────────────────
    "tickets.view":           {"label": "Ver tickets/OS",            "module": "tickets"},
    "tickets.create":         {"label": "Criar tickets/OS",          "module": "tickets"},
    "tickets.edit":           {"label": "Editar tickets",            "module": "tickets"},
    "tickets.close":          {"label": "Finalizar OS",              "module": "tickets"},
    "tickets.reopen":         {"label": "Reabrir OS finalizada",     "module": "tickets"},
    "tickets.delete":         {"label": "Excluir ticket",            "module": "tickets"},
    "tickets.assign":         {"label": "Atribuir técnico",          "module": "tickets"},
    "tickets.bulk_edit":      {"label": "Edição em massa",           "module": "tickets"},
    "lousa.view":             {"label": "Ver Lousa",                 "module": "lousa"},
    "lousa.finalize":         {"label": "Finalizar OS via Lousa",    "module": "lousa"},
    "lousa.override_geofence":{"label": "Bypass geofence",           "module": "lousa"},
    "lousa.override_photo":   {"label": "Finalizar sem foto",        "module": "lousa"},
    "lousa.manage_settings":  {"label": "Validações da OS Lousa",    "module": "lousa"},

    # ──── Clientes / Atendimento ───────────────────────────────────────────
    "clients.view":           {"label": "Ver clientes",              "module": "clients"},
    "clients.view.pii":       {"label": "Ver CPF/RG completo",       "module": "clients"},
    "clients.view.blocked":   {"label": "Ver clientes bloqueados",   "module": "clients"},
    "clients.view.overdue":   {"label": "Ver inadimplentes",         "module": "clients"},
    "clients.create":         {"label": "Cadastrar cliente",         "module": "clients"},
    "clients.edit":           {"label": "Editar cliente",            "module": "clients"},
    "clients.suspend":        {"label": "Suspender cliente",         "module": "clients"},
    "clients.reactivate":     {"label": "Reativar cliente",          "module": "clients"},
    "clients.delete":         {"label": "Excluir cliente",           "module": "clients"},

    # ──── Estoque ──────────────────────────────────────────────────────────
    "estoque.view":           {"label": "Ver estoque",               "module": "estoque"},
    "estoque.adjust":         {"label": "Ajustar saldo",             "module": "estoque"},
    "estoque.transfer":       {"label": "Transferir entre praças",   "module": "estoque"},
    "estoque.audit":          {"label": "Balanço / inventário",      "module": "estoque"},
    "estoque.low_stock":      {"label": "Receber alertas",           "module": "estoque"},

    # ──── Financeiro ───────────────────────────────────────────────────────
    "financeiro.view.aging":  {"label": "Ver aging",                 "module": "financeiro"},
    "financeiro.view.dre":    {"label": "Ver DRE",                   "module": "financeiro"},
    "financeiro.view.daily":  {"label": "Movimento do dia",          "module": "financeiro"},
    "financeiro.charge.dispatch": {"label": "Disparar cobrança",     "module": "financeiro"},
    "financeiro.refund":      {"label": "Estornar pagamento",        "module": "financeiro"},
    "financeiro.payment.confirm": {"label": "Conciliar pagamento",   "module": "financeiro"},
    "financeiro.payment.reverse": {"label": "Reverter conciliação",  "module": "financeiro"},
    "financeiro.banking":     {"label": "Operações bancárias",       "module": "financeiro"},

    # ──── Colaboradores / IAM ──────────────────────────────────────────────
    "colaboradores.view":     {"label": "Ver colaboradores",         "module": "colaboradores"},
    "colaboradores.create":   {"label": "Criar colaborador",         "module": "colaboradores"},
    "colaboradores.edit":     {"label": "Editar colaborador",        "module": "colaboradores"},
    "colaboradores.deactivate":  {"label": "Desativar colab",        "module": "colaboradores"},
    "colaboradores.terminate":   {"label": "Encerrar vínculo",       "module": "colaboradores"},
    "colaboradores.assign_profile": {"label": "Atribuir perfil",     "module": "colaboradores"},
    "colaboradores.view.face":   {"label": "Ver biometria facial",   "module": "colaboradores"},
    "colaboradores.view.clock":  {"label": "Ver ponto eletrônico",   "module": "colaboradores"},

    # ──── Dashboard ────────────────────────────────────────────────────────
    "dashboard.executive":    {"label": "Dashboard executivo",       "module": "dashboard"},
    "dashboard.operational":  {"label": "Dashboard operacional",     "module": "dashboard"},
    "dashboard.financial":    {"label": "Dashboard financeiro",      "module": "dashboard"},
    "dashboard.technical":    {"label": "Dashboard técnico",         "module": "dashboard"},

    # ──── Frota ────────────────────────────────────────────────────────────
    "frota.view":             {"label": "Ver frota",                 "module": "frota"},
    "frota.edit_vehicle":     {"label": "Editar veículo",            "module": "frota"},
    "frota.assign_driver":    {"label": "Atribuir motorista",        "module": "frota"},
    "frota.view_tracking":    {"label": "Ver rastreio",              "module": "frota"},
    "frota.view_costs":       {"label": "Ver custos da frota",       "module": "frota"},

    # ──── WhatsApp / Mensagens ─────────────────────────────────────────────
    "whatsapp.send":          {"label": "Enviar mensagens",          "module": "whatsapp"},
    "whatsapp.view_conv":     {"label": "Ver conversas",             "module": "whatsapp"},
    "whatsapp.manage_channels":  {"label": "Gerir canais",           "module": "whatsapp"},
    "whatsapp.manage_campaigns": {"label": "Gerir campanhas",        "module": "whatsapp"},
    "whatsapp.mass_dispatch": {"label": "Disparo em massa",          "module": "whatsapp"},

    # ──── IA / Motor ───────────────────────────────────────────────────────
    "ai.view_insights":       {"label": "Ver insights IA",           "module": "ai"},
    "ai.tune_prompts":        {"label": "Editar prompts",            "module": "ai"},
    "ai.manage_budget":       {"label": "Gerir budget LLM",          "module": "ai"},
    "ai.view_corrections":    {"label": "Ver correções IA",          "module": "ai"},
    "ai.train":               {"label": "Treinar modelos",           "module": "ai"},

    # ──── Sistema / Admin ──────────────────────────────────────────────────
    "system.manage_users":    {"label": "Gerir usuários",            "module": "system"},
    "system.manage_profiles": {"label": "Gerir perfis",              "module": "system"},
    "system.manage_integrations": {"label": "Gerir integrações",     "module": "system"},
    "system.view_logs":       {"label": "Ver logs",                  "module": "system"},
    "system.manage_secrets":  {"label": "Gerir segredos",            "module": "system"},
    "system.kill_switch":     {"label": "Kill switch (parada total)", "module": "system"},
    "system.deploy":          {"label": "Forçar redeploy",           "module": "system"},
    "system.manage_companies":{"label": "Gerir empresas (tenants)",  "module": "system"},

    # ──── Auditoria ────────────────────────────────────────────────────────
    "audit.view_all":         {"label": "Ver auditoria completa",    "module": "audit"},
    "audit.export":           {"label": "Exportar auditoria",        "module": "audit"},
    "audit.restore_deleted":  {"label": "Restaurar deletado",        "module": "audit"},

    # ──── Cadastro geral ───────────────────────────────────────────────────
    "cadastro.view":          {"label": "Ver cadastros",             "module": "cadastro"},
    "cadastro.edit":          {"label": "Editar cadastros",          "module": "cadastro"},
    "pracas.manage":          {"label": "Gerir praças",              "module": "cadastro"},
    "feriados.manage":        {"label": "Gerir feriados",            "module": "cadastro"},
    "plans.manage":           {"label": "Gerir planos",              "module": "cadastro"},

    # ──── Propostas / Vendas ───────────────────────────────────────────────
    "propostas.view":         {"label": "Ver propostas",             "module": "propostas"},
    "propostas.create":       {"label": "Criar proposta",            "module": "propostas"},
    "propostas.edit":         {"label": "Editar proposta",           "module": "propostas"},
    "propostas.delete":       {"label": "Excluir proposta",          "module": "propostas"},
    "sales.view_funnel":      {"label": "Ver funil de vendas",       "module": "sales"},
    "sales.manage":           {"label": "Gerir vendas",              "module": "sales"},

    # ──── Rede / OLT / CTOs ────────────────────────────────────────────────
    "rede.view":              {"label": "Ver rede",                  "module": "rede"},
    "rede.edit_cto":          {"label": "Editar CTO/porta",          "module": "rede"},
    "rede.olt_admin":         {"label": "Operar OLT",                "module": "rede"},
    "rede.run_tests":         {"label": "Rodar testes de rede",      "module": "rede"},

    # ──── Holerite / RH ────────────────────────────────────────────────────
    "rh.view_holerite_own":   {"label": "Ver próprio holerite",      "module": "rh"},
    "rh.view_holerite_all":   {"label": "Ver holerite de todos",     "module": "rh"},
    "rh.upload_holerite":     {"label": "Subir holerite",            "module": "rh"},
    "rh.view_timesheets":     {"label": "Ver timesheets",            "module": "rh"},
    "rh.approve_timesheets":  {"label": "Aprovar timesheets",        "module": "rh"},

    # ──── Indique e Ganhe ──────────────────────────────────────────────────
    "referrals.view":         {"label": "Ver programa indique",      "module": "referrals"},
    "referrals.manage":       {"label": "Gerir campanhas",           "module": "referrals"},
}


# Visão derivada por módulo (pra UI de Perfis)
def list_by_module() -> dict[str, list[tuple[str, str]]]:
    by_mod: dict[str, list[tuple[str, str]]] = {}
    for key, meta in PERMISSIONS.items():
        by_mod.setdefault(meta["module"], []).append((key, meta["label"]))
    for mod in by_mod:
        by_mod[mod].sort()
    return by_mod


def is_valid(perm_key: str) -> bool:
    """True se é uma permission válida (existe no catálogo ou é wildcard)."""
    if perm_key == "*":
        return True
    if perm_key in PERMISSIONS:
        return True
    if perm_key.endswith(".*"):
        module = perm_key[:-2]
        return any(meta["module"] == module for meta in PERMISSIONS.values()) \
            or any(k.startswith(module + ".") for k in PERMISSIONS)
    return False


def sanitize(perm_keys: Iterable[str]) -> list[str]:
    """Filtra keys inválidas (log warning) e retorna lista única ordenada."""
    seen: set[str] = set()
    out: list[str] = []
    for k in perm_keys:
        k = (k or "").strip()
        if not k:
            continue
        if not is_valid(k):
            import logging
            logging.getLogger("iam_v2").warning(
                "[permissions] key fora do catálogo ignorada: %s", k,
            )
            continue
        if k not in seen:
            seen.add(k)
            out.append(k)
    return sorted(out)


# ──────────────────────────────────────────────────────────────────────────
# Profile templates (seeds)
# ──────────────────────────────────────────────────────────────────────────

# Mapeia legacy role → permissions iniciais (shim ADR-003)
LEGACY_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "administrador": ["*"],
    "auditor": ["*"],  # tudo (read-only por convenção)
    "gestor": [
        "tickets.*", "clients.*", "estoque.*", "lousa.*",
        "frota.*", "whatsapp.*", "ai.view_insights", "ai.view_corrections",
        "dashboard.executive", "dashboard.operational", "dashboard.financial",
        "colaboradores.view", "colaboradores.edit",
        "colaboradores.deactivate", "colaboradores.assign_profile",
        "cadastro.*", "propostas.*", "sales.*",
        "rh.view_holerite_all", "rh.view_timesheets", "rh.approve_timesheets",
        "referrals.*", "audit.view_all",
    ],
    "atendimento": [
        "tickets.view", "tickets.create", "tickets.edit", "tickets.assign",
        "clients.view", "clients.view.overdue", "clients.create", "clients.edit",
        "whatsapp.send", "whatsapp.view_conv",
        "dashboard.operational", "propostas.view", "propostas.create",
        "sales.view_funnel", "referrals.view",
    ],
    "tecnico": [
        "lousa.view", "lousa.finalize",
        "tickets.view", "tickets.close",
        "estoque.view",
        "frota.view", "frota.view_tracking",
        "rede.view", "rede.run_tests",
        "rh.view_holerite_own",
    ],
    "financeiro": [
        "financeiro.*", "clients.view", "clients.view.overdue",
        "dashboard.financial", "rh.view_holerite_all", "rh.view_timesheets",
    ],
    "colaborador": [
        "lousa.view", "lousa.finalize",
        "rh.view_holerite_own",
    ],
}


def permissions_for_legacy_role(role: str) -> list[str]:
    """Retorna as permissions associadas a um role legado.
    Wildcards expandidos para keys reais quando o profile é serializado.
    """
    return list(LEGACY_ROLE_PERMISSIONS.get(role, []))
