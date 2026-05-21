"""
access_tags.py — Catálogo central de tags de acesso por módulo.

Cada usuário tem uma lista de tags (campo `users.access_tags`) que controla
quais painéis ele vê na sidebar e quais ações pode executar.

Auditor (`role="auditor"`) sempre tem TODAS as tags por convenção; o
campo só é usado para gestores/administradores que precisam de granularidade.

Categorias servem só para a UI agrupar os chips visualmente.
"""
from typing import List, Dict


TAGS: List[Dict] = [
    # Operação
    {"key": "painel",           "label": "Painel Executivo",   "icon": "🏠", "category": "Operação"},
    {"key": "lousa",            "label": "Lousa (OS)",          "icon": "📋", "category": "Operação"},
    {"key": "estoque",          "label": "Estoque",             "icon": "📦", "category": "Operação"},
    {"key": "balanco",          "label": "Balanço",             "icon": "🔄", "category": "Operação"},
    {"key": "central_compras",  "label": "Central de Compras",  "icon": "🛒", "category": "Operação"},

    # Inteligência
    {"key": "rede_ia",          "label": "Rede IA (Mapa/CTO)",  "icon": "🌐", "category": "Inteligência"},
    {"key": "atendimento_wa",   "label": "Atendimento WhatsApp","icon": "💬", "category": "Inteligência"},
    {"key": "ia_avaliacao",     "label": "Avaliação / Correções IA", "icon": "🤖", "category": "Inteligência"},

    # Cadastro
    {"key": "colaboradores",    "label": "Colaboradores",       "icon": "👥", "category": "Cadastro"},
    {"key": "clientes",         "label": "Clientes",            "icon": "🏢", "category": "Cadastro"},
    {"key": "pracas",           "label": "Praças",              "icon": "📍", "category": "Cadastro"},

    # Relatórios & RH
    {"key": "auditoria",        "label": "Auditoria",           "icon": "📊", "category": "Relatórios"},
    {"key": "logs",             "label": "Logs do Sistema",     "icon": "📑", "category": "Relatórios"},
    {"key": "ponto",            "label": "Ponto Eletrônico",    "icon": "⏰", "category": "RH"},
    {"key": "holerite",         "label": "Holerite",            "icon": "💵", "category": "RH"},
    {"key": "feriados",         "label": "Feriados",            "icon": "📅", "category": "RH"},

    # Financeiro
    {"key": "financeiro",       "label": "Financeiro (Atlaz)",  "icon": "💰", "category": "Financeiro"},
]

ALL_TAG_KEYS = {t["key"] for t in TAGS}

# Tags padrão concedidas a cada papel quando o usuário é criado e ainda não
# tem `access_tags` salvo (compat com seed antigo).
DEFAULT_TAGS_BY_ROLE: Dict[str, List[str]] = {
    "auditor":       list(ALL_TAG_KEYS),   # auditor já tem tudo
    "administrador": list(ALL_TAG_KEYS),
    "gestor": [
        "painel", "lousa", "estoque", "balanco", "central_compras",
        "rede_ia", "atendimento_wa", "ia_avaliacao",
        "colaboradores", "clientes", "pracas",
        "ponto", "feriados",
    ],
    "gestor_rede": [
        "painel", "rede_ia", "pracas", "colaboradores", "auditoria",
    ],
    "financeiro": ["painel", "financeiro", "auditoria", "logs"],
    "colaborador": [],  # técnicos não acessam o sistema web
}


def sanitize_tags(tags) -> List[str]:
    """Filtra/valida lista de tags vinda do front. Mantém apenas keys válidas
    e remove duplicados preservando ordem."""
    if not isinstance(tags, (list, tuple)):
        return []
    seen = set()
    out: List[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        key = t.strip().lower()
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
