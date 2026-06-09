"""
access_tags.py — Catálogo central de tags de acesso por módulo.

╔══════════════════════════════════════════════════════════════════════╗
║  REGRA DE OURO — PARIDADE NAV ↔ ACCESS TAGS  (iter211v)              ║
║                                                                      ║
║  TODA aba ou sub-aba adicionada em `frontend/src/App.js → NAV_GROUPS`║
║  PRECISA ter UMA tag correspondente neste arquivo, com a mesma key.  ║
║                                                                      ║
║  Como verificar:                                                     ║
║    • Endpoint:   GET /api/users/access-tags/audit  (auditor)         ║
║    • Pytest:     backend/tests/test_iter211v_nav_access_tags_parity  ║
║    • Startup:    logger.warning aparece se houver divergência        ║
║                                                                      ║
║  Como adicionar uma nova aba (passo-a-passo):                        ║
║    1) Inclua `{ id: "x", label: "..." }` no NAV_GROUPS de App.js.    ║
║    2) Acrescente um item correspondente em `TAGS` abaixo com         ║
║       `key: "x"` (mesmo id), `label`, `icon`, `category`.            ║
║    3) Atualize `DEFAULT_TAGS_BY_ROLE` se quiser que algum papel já   ║
║       receba acesso por padrão.                                      ║
║    4) Rode `pytest backend/tests/test_iter211v_nav_access_tags_parity║
║       .py` — tem que passar.                                         ║
╚══════════════════════════════════════════════════════════════════════╝

Cada usuário tem uma lista de tags (campo `users.access_tags`) que controla
quais painéis ele vê na sidebar e quais ações pode executar.

Auditor (`role="auditor"`) e administrador sempre têm TODAS as tags por
convenção; o campo só é usado para gestores e papéis customizados que
precisam de granularidade.
"""
from typing import Dict, List


TAGS: List[Dict] = [
    # ============================== Operação ==============================
    {"key": "dashboard",         "label": "Painel Executivo",         "icon": "🏠", "category": "Operação"},
    {"key": "lousa",             "label": "Chamados (Lousa)",         "icon": "📋", "category": "Operação"},
    {"key": "estoque",           "label": "Estoque",                  "icon": "📦", "category": "Operação"},
    {"key": "projects",          "label": "Acompanhamento",           "icon": "📅", "category": "Operação"},
    {"key": "central-compras",   "label": "Central de Compras",       "icon": "🛒", "category": "Operação"},
    {"key": "radius",            "label": "RADIUS / PPPoE",           "icon": "📡", "category": "Operação"},
    {"key": "contracts",         "label": "Contratos",                "icon": "📄", "category": "Operação"},
    {"key": "payments",          "label": "Pagamentos",               "icon": "💳", "category": "Operação"},
    {"key": "site",              "label": "Site do Provedor",         "icon": "🌐", "category": "Operação"},
    {"key": "balanco",           "label": "Balanço",                  "icon": "🔄", "category": "Operação"},

    # ============================== Frota =================================
    {"key": "fleet",             "label": "Gestão de Frota",          "icon": "🚗", "category": "Frota"},
    {"key": "fleet-tracking",    "label": "Rastreamento (GPS)",       "icon": "📡", "category": "Frota"},
    {"key": "security-home",     "label": "Segurança Residencial",    "icon": "🏠", "category": "Frota"},

    # ============================ Projetos ================================
    {"key": "projetos",          "label": "Projetos",                 "icon": "📁", "category": "Projetos"},
    {"key": "propostas",         "label": "Propostas (IA)",           "icon": "📨", "category": "Projetos"},

    # =========================== Inteligência =============================
    {"key": "ai-ranking",        "label": "Avaliação IA",             "icon": "⭐", "category": "Inteligência"},
    {"key": "ai-corrections",    "label": "Correções IA",             "icon": "✏️", "category": "Inteligência"},
    {"key": "central-ia",        "label": "Central IA",               "icon": "🧠", "category": "Inteligência"},
    {"key": "rede-ia",           "label": "Rede IA (Mapa/CTO)",       "icon": "🌐", "category": "Inteligência"},
    {"key": "atendimento",       "label": "Atendimento IA / WhatsApp","icon": "💬", "category": "Inteligência"},
    {"key": "alvaro-ia",         "label": "Alvaro IA",                "icon": "🤖", "category": "Inteligência"},
    {"key": "mass-messaging",    "label": "Disparo em Massa",         "icon": "📣", "category": "Inteligência"},
    {"key": "sales-funnel",      "label": "Funil de Vendas",          "icon": "🎯", "category": "Inteligência"},

    # ============================= Cadastro ===============================
    {"key": "cadastro",          "label": "Colaboradores",            "icon": "👥", "category": "Cadastro"},
    {"key": "clientes",          "label": "Clientes (todas)",         "icon": "🏢", "category": "Cadastro"},
    {"key": "subscribers",       "label": "Assinantes",               "icon": "👤", "category": "Cadastro"},
    {"key": "plans",             "label": "Planos",                   "icon": "📋", "category": "Cadastro"},
    {"key": "contracts-disabled", "label": "Contratos desativados",   "icon": "🚫", "category": "Cadastro"},
    {"key": "clients-recent",    "label": "Clientes recentes",        "icon": "🆕", "category": "Cadastro"},
    {"key": "clients-overdue",   "label": "Clientes em atraso",       "icon": "⏰", "category": "Cadastro"},
    {"key": "clients-blocked",   "label": "Clientes bloqueados",      "icon": "🔒", "category": "Cadastro"},
    {"key": "clients-no-charges", "label": "Sem cobranças futuras",   "icon": "💸", "category": "Cadastro"},
    {"key": "clients-connected", "label": "Conectados",               "icon": "🟢", "category": "Cadastro"},
    {"key": "clients-disconnected", "label": "Desconectados",         "icon": "⚫", "category": "Cadastro"},
    {"key": "clients-attempts",  "label": "Tentativas de conexão",    "icon": "🔁", "category": "Cadastro"},
    {"key": "clients-no-contract", "label": "Sem contratos",          "icon": "📝", "category": "Cadastro"},
    {"key": "pracas",            "label": "Praças",                   "icon": "📍", "category": "Cadastro"},

    # ========================== Relatórios ================================
    {"key": "manager",           "label": "Auditoria",                "icon": "📊", "category": "Relatórios"},
    {"key": "logs",              "label": "Logs do Sistema",          "icon": "📑", "category": "Relatórios"},
    {"key": "client-errors",     "label": "Crashes Frontend",         "icon": "⚠️", "category": "Relatórios"},
    {"key": "smartolt-push",     "label": "Fila SmartOLT",            "icon": "📡", "category": "Rede"},

    # ============================== RH ====================================
    {"key": "espelho",           "label": "Ponto (espelho)",          "icon": "⏱️", "category": "RH"},
    {"key": "sheet",             "label": "Folha de Ponto",           "icon": "📅", "category": "RH"},
    {"key": "holerite",          "label": "Holerite",                 "icon": "💵", "category": "RH"},
    {"key": "feriados",          "label": "Feriados",                 "icon": "📅", "category": "RH"},

    # ========================== Financeiro ================================
    {"key": "financeiro",        "label": "Financeiro (Atlaz)",       "icon": "💰", "category": "Financeiro"},
    {"key": "billing",           "label": "Faturamento",              "icon": "🧾", "category": "Financeiro"},

    # =========================== Comercial ================================
    {"key": "budget",            "label": "Orçamento",                "icon": "🧮", "category": "Comercial"},
    {"key": "parcerias",         "label": "Parcerias",                "icon": "🎁", "category": "Comercial"},
    {"key": "referrals-admin",   "label": "Indique e Ganhe",          "icon": "🎉", "category": "Comercial"},

    # ============================ Sistema =================================
    {"key": "users",             "label": "Usuários (acessos)",       "icon": "🛡️", "category": "Sistema"},
    {"key": "motor-ia",          "label": "Motor IA",                 "icon": "⚙️", "category": "Sistema"},
    {"key": "audit-trail",       "label": "Audit Trail",              "icon": "🛡️", "category": "Sistema"},
    {"key": "lgpd-portal",       "label": "LGPD Portal",              "icon": "🛡️", "category": "Sistema"},
    {"key": "backend-health",    "label": "Saúde Técnica",            "icon": "📊", "category": "Sistema"},
    {"key": "settings",          "label": "Configurações",            "icon": "⚙️", "category": "Sistema"},
    {"key": "platform",          "label": "Plataforma (multi-empresa)", "icon": "🏛️", "category": "Sistema"},
    {"key": "backup",            "label": "Backup DB",                "icon": "💾", "category": "Sistema"},
]

ALL_TAG_KEYS = {t["key"] for t in TAGS}

# Aliases retrocompatíveis: tags antigas viram tags novas (silenciosamente)
# para não quebrar dados de usuários já cadastrados.
_LEGACY_ALIASES: Dict[str, str] = {
    "painel": "dashboard",
    "central_compras": "central-compras",
    "atendimento_wa": "atendimento",
    "ia_avaliacao": "ai-ranking",
    "ponto": "sheet",
    "auditoria": "manager",
}


# Tags padrão concedidas a cada papel quando o usuário é criado e ainda não
# tem `access_tags` salvo (compat com seed antigo).
DEFAULT_TAGS_BY_ROLE: Dict[str, List[str]] = {
    "auditor":       list(ALL_TAG_KEYS),
    "administrador": list(ALL_TAG_KEYS),
    "gestor": [
        # Operação (gestor padrão)
        "dashboard", "lousa", "estoque", "projects", "central-compras",
        "radius", "contracts", "payments", "site", "balanco",
        # Frota e Projetos
        "fleet", "fleet-tracking", "security-home", "projetos", "propostas",
        # Inteligência
        "ai-ranking", "ai-corrections", "central-ia", "rede-ia",
        "atendimento", "alvaro-ia", "mass-messaging", "sales-funnel",
        # Cadastro
        "cadastro", "clientes", "subscribers", "plans",
        "contracts-disabled", "clients-recent", "clients-overdue",
        "clients-blocked", "clients-no-charges", "clients-connected",
        "clients-disconnected", "clients-attempts", "clients-no-contract",
        "pracas",
        # RH e Comercial
        "espelho", "sheet", "feriados", "budget", "parcerias", "referrals-admin",
    ],
    "gestor_rede": [
        "dashboard", "rede-ia", "pracas", "cadastro", "manager",
    ],
    "financeiro": [
        "dashboard", "financeiro", "billing", "payments",
        "manager", "logs", "budget",
    ],
    "colaborador": [],  # técnicos não acessam o sistema web
}


def sanitize_tags(tags) -> List[str]:
    """Filtra/valida lista de tags vinda do front. Mantém apenas keys válidas
    (aplica aliases legados) e remove duplicados preservando ordem."""
    if not isinstance(tags, (list, tuple)):
        return []
    seen = set()
    out: List[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        key = t.strip().lower()
        # Aplica alias legado
        key = _LEGACY_ALIASES.get(key, key)
        if key in ALL_TAG_KEYS and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def effective_tags(user: dict) -> List[str]:
    """Retorna tags efetivas: auditor/administrador sempre = ALL.
    Outros papéis: usa o campo `access_tags` se existir; senão cai no
    default do papel."""
    role = (user or {}).get("role")
    if role in ("auditor", "administrador"):
        return list(ALL_TAG_KEYS)
    tags = user.get("access_tags")
    if isinstance(tags, list) and tags:
        return sanitize_tags(tags)
    return list(DEFAULT_TAGS_BY_ROLE.get(role, []))
