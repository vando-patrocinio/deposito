"""
Seed dos 6 níveis do Universo Ligo V2.

Cada nível é uma FASE da trajetória do cliente — NÃO uma faixa de pontos.
Os nomes vêm da decisão final do CEO (FASE A.1 aprovada).

Mapping legacy → V2 (para migração não-destrutiva):
    explorador      → explorador     (mesmo)
    cometa          → viajante       (shift: nome muda, faixa idêntica)
    orbita          → cometa         (shift)
    estelar         → constelacao    (shift)
    galaxia_ouro    → galaxia        (shift)
    universo_ligo   → embaixador     (shift + regra extra: embaixador é POR CONVITE,
                                       não automático mesmo se score >= 1200)

Importante:
- `min_score` / `max_score` são âncoras INTERNAS. Não aparecem para o cliente.
- `entry_rule` documenta a transição esperada (apenas pra equipe).
- `benefits` aqui é apenas descritivo (sem APIs/comunicação ainda — Fase D+).
"""
from __future__ import annotations
from typing import List, Dict, Any

# Mapping idempotente legacy → V2. Usado pela migração.
LEGACY_TO_V2_KEY: Dict[str, str] = {
    "explorador":     "explorador",
    "cometa":         "viajante",
    "orbita":         "cometa",
    "estelar":        "constelacao",
    "galaxia_ouro":   "galaxia",
    "universo_ligo":  "embaixador",
}

# Mapping reverso (rollback)
V2_TO_LEGACY_KEY: Dict[str, str] = {v: k for k, v in LEGACY_TO_V2_KEY.items()}


def build_levels_seed() -> List[Dict[str, Any]]:
    """Retorna a lista exata de docs a serem inseridos em universo_ligo_levels.

    Idempotente: cada doc tem `key` único — o seed usa upsert por `key`.
    """
    return [
        {
            "key": "explorador",
            "level_id": 1,
            "name": "Explorador",
            "icon": "🌱",
            "description": (
                "Quem acaba de chegar. Está vendo se vai dar certo. "
                "A Ligo acolhe e fica em silêncio respeitoso nos primeiros 30 dias."
            ),
            "min_score": 0,
            "max_score": 99,
            "entry_rule": "Default — todo cliente que chega entra como Explorador.",
            "tempo_medio_meses_min": 0,
            "tempo_medio_meses_max": 6,
            "frase_do_cliente": "Tô vendo se vai dar certo.",
            "benefits": [
                {"label": "Acesso ao app com linha do tempo pessoal", "type": "intrinsic"},
                {"label": "Prioridade comum no suporte", "type": "intrinsic"},
            ],
            "active": True,
        },
        {
            "key": "viajante",
            "level_id": 2,
            "name": "Viajante",
            "icon": "🚶",
            "description": (
                "Passou da prova inicial. Já entende que a Ligo é estável. "
                "Começou a contar pros amigos."
            ),
            "min_score": 100,
            "max_score": 249,
            "entry_rule": "6 meses de casa + 0 inadimplência + (1 apresentação OU NPS tácito 9+).",
            "tempo_medio_meses_min": 6,
            "tempo_medio_meses_max": 18,
            "frase_do_cliente": "Tô gostando. A internet aqui é boa mesmo.",
            "benefits": [
                {"label": "Prioridade declarada no suporte", "type": "service"},
                {"label": "1 mês de Ligo+ Música no aniversário de 1 ano", "type": "perk", "trigger": "anniversary_1y"},
            ],
            "active": True,
        },
        {
            "key": "cometa",
            "level_id": 3,
            "name": "Cometa",
            "icon": "☄️",
            "description": (
                "Virou regular. A Ligo lembra dele, ele lembra da Ligo. "
                "É fonte de novos clientes na vizinhança."
            ),
            "min_score": 250,
            "max_score": 499,
            "entry_rule": "2 anos + 3 apresentações convertidas OU 18 meses + observação contínua.",
            "tempo_medio_meses_min": 18,
            "tempo_medio_meses_max": 36,
            "frase_do_cliente": "A Ligo me lembra. Eu lembro da Ligo.",
            "benefits": [
                {"label": "Ligo+ Música incluso permanente", "type": "product"},
                {"label": "Desconto automático de 5% na fatura", "type": "discount", "value_pct": 5},
                {"label": "1 passe livre por ano no suporte", "type": "service", "quota_per_year": 1},
            ],
            "active": True,
        },
        {
            "key": "constelacao",
            "level_id": 4,
            "name": "Constelação",
            "icon": "✨",
            "description": (
                "Família Ligo extensa (3+). Vira referência da Ligo no bairro. "
                "Reconhecimento público discreto (com autorização)."
            ),
            "min_score": 500,
            "max_score": 799,
            "entry_rule": "4 anos + 6 apresentações OU 3 anos + Família Ligo 5+ ativos.",
            "tempo_medio_meses_min": 36,
            "tempo_medio_meses_max": 60,
            "frase_do_cliente": "Eu virei referência da Ligo aqui no bairro.",
            "benefits": [
                {"label": "Desconto fixo de 10% na fatura", "type": "discount", "value_pct": 10},
                {"label": "Ligo+ Filmes incluso", "type": "product"},
                {"label": "1 mês grátis pra cada nova família que apresentar", "type": "perk_shareable"},
                {"label": "Convite à Celebração Anual da Comunidade", "type": "event_invite"},
            ],
            "active": True,
        },
        {
            "key": "galaxia",
            "level_id": 5,
            "name": "Galáxia",
            "icon": "🌌",
            "description": (
                "Construiu algo dentro da Ligo. Lembrado por nome dentro da empresa."
            ),
            "min_score": 800,
            "max_score": 1199,
            "entry_rule": "5 anos + 10 apresentações + NPS médio 9+.",
            "tempo_medio_meses_min": 60,
            "tempo_medio_meses_max": None,
            "frase_do_cliente": "Eu construí algo aqui.",
            "benefits": [
                {"label": "Desconto fixo de 15% na fatura", "type": "discount", "value_pct": 15},
                {"label": "Todos os Ligo+ inclusos (TV, Filmes, Música)", "type": "product"},
                {"label": "Selo Galáxia visível no perfil", "type": "badge"},
                {"label": "2 passes livres por ano", "type": "service", "quota_per_year": 2},
                {"label": "Cartão impresso anual personalizado", "type": "physical"},
                {"label": "Linha direta com a Pâmela (sem fila)", "type": "service"},
                {"label": "Verificação preferencial de viabilidade", "type": "service"},
            ],
            "active": True,
        },
        {
            "key": "embaixador",
            "level_id": 6,
            "name": "Embaixador",
            "icon": "⭐",
            "description": (
                "Convidado pela Ligo após anos de observação. Carrega a Ligo "
                "na cidade. Reconhecimento, NÃO transação. "
                "POLÍTICA INEGOCIÁVEL: status NÃO é comprado, é conquistado."
            ),
            "min_score": 1200,
            "max_score": None,
            "entry_rule": (
                "POR CONVITE EXPLÍCITO da Pâmela + gerente regional, após "
                "observação multi-anual de reputação local, acolhimento de novos "
                "Exploradores, e estabilidade. NÃO há entrada automática por score."
            ),
            "tempo_medio_meses_min": None,
            "tempo_medio_meses_max": None,
            "frase_do_cliente": "A Ligo é minha. Eu fiz parte disso.",
            "benefits": [
                {"label": "Mantém todos os benefícios do Galáxia", "type": "inherit"},
                {"label": "Cartão de Embaixador físico personalizado e numerado", "type": "physical"},
                {"label": "Linha direta com a Pâmela (prioridade absoluta)", "type": "service"},
                {"label": "Convite formal à Celebração Anual da Comunidade", "type": "event_invite"},
                {"label": "Voz consultiva anual com gerente regional", "type": "voice"},
                {"label": "Reconhecimento público pelo nome (se autorizado)", "type": "brand"},
                {"label": "Selo Embaixador visível", "type": "badge"},
            ],
            "non_benefits": [
                # POLÍTICA INEGOCIÁVEL — Embaixador não recebe estes itens:
                "Mensalidade simbólica ou plano grátis",
                "Desconto adicional ao do Galáxia",
                "Qualquer troca financeira como contrapartida do título",
            ],
            "requires_invite": True,
            "active": True,
        },
    ]


def get_level_by_score(score: float, *, has_invite: bool = False) -> str:
    """Retorna a KEY do nível para um dado score.

    Embaixador requer flag `has_invite=True` mesmo se score >= 1200.
    Sem convite, cliente fica em Galáxia indefinidamente.
    """
    if score >= 1200 and has_invite:
        return "embaixador"
    if score >= 1200 or (score >= 800):
        return "galaxia"
    if score >= 500:
        return "constelacao"
    if score >= 250:
        return "cometa"
    if score >= 100:
        return "viajante"
    return "explorador"
