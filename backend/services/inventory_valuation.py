"""
services/inventory_valuation.py — CTO 16/02/2026 — R1 Valuation Schema.

Motor de valuation patrimonial. Determina o valor financeiro de cada ONT
seguindo a ordem de prioridade aprovada pelo CEO:

  1. valor_nf                 (Grade A — NF encontrada)
  2. valor_medio_ponderado    (Grade B — purchase encontrada / média ponderada da empresa)
  3. MODEL_CANONICAL          (Grade C — modelo conhecido)
  4. valor_referencia         (Grade D — fallback genérico)
  5. (Grade E)                (inferência por similaridade — placeholder)
  6. (Grade F)                (revisão humana obrigatória — `valuation_needs_human_review=true`)

ESCOPO R1.1: motor + tabela MODEL_CANONICAL. Schema additivo ainda NÃO escreve em
banco. R1.2 (dry-run) lê e simula. R1.3 (apply) faz update_many. R1.4 hookará
no _genesis_*/_purchase_confirm. Cada etapa requer autorização CEO separada.

CAMPOS QUE SERÃO ADICIONADOS EM stok_onts (R1.3, ainda NÃO aplicado):
    valor_nf:                  float | None
    valor_medio_ponderado:     float | None
    valor_referencia:          float | None
    valuation_grade:           Literal["A","B","C","D","E","F"] | None
    valuation_source:          Literal["nf","weighted_avg","model_canonical","reference","inferred","unknown"] | None
    valuation_calculated_at:   str (ISO) | None
    valuation_needs_human_review: bool   (True só p/ Grade F)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from database import db

logger = logging.getLogger("inventory_valuation")


# ═══════════ Constantes canônicas ════════════════════════════════════════════

ValuationGrade = Literal["A", "B", "C", "D", "E", "F"]
ValuationSource = Literal[
    "nf", "weighted_avg", "model_canonical",
    "reference", "inferred", "unknown",
]

# Fallback global quando NADA é resolvido (Grade D).
DEFAULT_REFERENCE_PRICE = 85.0

# Strings de modelo que devem ser tratadas como "lixo" → Grade F direto.
MODEL_GARBAGE_PATTERNS = [
    r"^$",                  # vazio
    r"^none$",              # literal "None"
    r"^null$",              # literal "null"
    r"^undefined$",
    r"^desconhecid[oa]$",
    r"^testmodel$",
    r"^test$",
    r"^xxx+$",
    r"^\?+$",
    r"^.{1,2}$",            # 1-2 chars (truncados/lixo)
]
_GARBAGE_RE = re.compile("|".join(MODEL_GARBAGE_PATTERNS), re.IGNORECASE)


# ─── Tabela canônica de modelos (CEO 16/02/2026 — decisão Q1=c híbrido) ──────
# Cada chave é uma SUBSTRING (case-insensitive) que pode aparecer no campo
# `model` ou em strings longas oriundas de OCR de NF.
# Quando a tabela oficial Ligo for fornecida, basta substituir esta constante.
MODEL_CANONICAL: Dict[str, Tuple[str, str, float]] = {
    # ── Fiberhome ──
    "fiberhome hg6145d":     ("FIBERHOME", "HG6145D",  220.0),
    "hg6145d":               ("FIBERHOME", "HG6145D",  220.0),
    "fiberhome hg8145d":     ("FIBERHOME", "HG8145D",  180.0),
    "hg8145d":               ("FIBERHOME", "HG8145D",  180.0),
    "fiberhome hg8145v5":    ("FIBERHOME", "HG8145V5", 180.0),
    "hg8145v5":              ("FIBERHOME", "HG8145V5", 180.0),
    "fiberhome":             ("FIBERHOME", "GENERIC",  150.0),   # genérico Fiberhome
    # ── ZTE ──
    "zte f601":              ("ZTE",       "F601",      65.0),
    "f601":                  ("ZTE",       "F601",      65.0),
    "zte f660":              ("ZTE",       "F660",      75.0),
    "f660":                  ("ZTE",       "F660",      75.0),
    "zte f670l":             ("ZTE",       "F670L",     95.0),
    "f670l":                 ("ZTE",       "F670L",     95.0),
    "zte":                   ("ZTE",       "GENERIC",   75.0),
    # ── Huawei ──
    "huawei hg8245":         ("HUAWEI",    "HG8245",   120.0),
    "hg8245":                ("HUAWEI",    "HG8245",   120.0),
    "huawei hg8546":         ("HUAWEI",    "HG8546M",  145.0),
    "hg8546":                ("HUAWEI",    "HG8546M",  145.0),
    "huawei":                ("HUAWEI",    "GENERIC",  120.0),
    # ── Genéricos por tecnologia ──
    "wifi 7":                ("GENERIC",   "WIFI7",    380.0),
    "wifi7":                 ("GENERIC",   "WIFI7",    380.0),
    "wifi 6":                ("GENERIC",   "WIFI6",    250.0),
    "wifi6":                 ("GENERIC",   "WIFI6",    250.0),
}


# ═══════════ Funções utilitárias ═════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_model(raw: Optional[str]) -> str:
    """Lowercase + colapsa whitespace + trim. Sem remoção de acentos."""
    if not raw:
        return ""
    return " ".join(str(raw).lower().split())


def is_model_garbage(raw: Optional[str]) -> bool:
    """True se o modelo é claramente lixo (placeholder, vazio, truncado)."""
    norm = _normalize_model(raw)
    if not norm:
        return True
    return bool(_GARBAGE_RE.fullmatch(norm))


def lookup_model_canonical(
    raw: Optional[str],
) -> Optional[Tuple[str, str, float]]:
    """Retorna (brand, model_clean, price) ou None se não casar.

    Lookup por substring case-insensitive. Procura a chave MAIS LONGA que
    apareça dentro de `raw` (greedy) para preferir matches específicos sobre
    genéricos (`fiberhome hg6145d` antes de `fiberhome`).
    """
    if is_model_garbage(raw):
        return None
    norm = _normalize_model(raw)
    # Ordena chaves por tamanho desc para greedy match.
    for key in sorted(MODEL_CANONICAL.keys(), key=len, reverse=True):
        if key in norm:
            return MODEL_CANONICAL[key]
    return None


# ═══════════ Resolução do valor NF via purchases (Grade A) ═══════════════════

async def resolve_nf_price(
    *, company_id: str, purchase_id: Optional[str], mac: Optional[str],
) -> Optional[float]:
    """Tenta achar `unit_price` na NF (purchases.items) via purchase_id+mac.

    Returns: float ou None se não conseguir resolver com confiança.
    """
    if not purchase_id:
        return None
    p = await db.purchases.find_one(
        {"id": purchase_id, "company_id": company_id},
        {"_id": 0, "items": 1, "total": 1, "unit_price": 1},
    )
    if not p:
        return None
    items = p.get("items") or []
    # Match exato por MAC dentro do array items[].macs
    if mac and items:
        for it in items:
            macs = it.get("macs") or []
            if mac in macs or mac.upper() in [m.upper() for m in macs]:
                up = it.get("unit_price") or it.get("price")
                if up and float(up) > 0:
                    return float(up)
    # Fallback: 1º item da NF tem unit_price
    if items:
        it0 = items[0]
        up = it0.get("unit_price") or it0.get("price")
        if up and float(up) > 0:
            return float(up)
    # Fallback: total dividido pela qtd de itens (média da compra)
    total = p.get("total")
    if total and items:
        try:
            return float(total) / max(1, len(items))
        except Exception:
            return None
    return None


# ═══════════ Cálculo do valor médio ponderado (Grade B) ══════════════════════

async def compute_weighted_avg(*, company_id: str) -> Optional[float]:
    """Calcula o valor médio ponderado da empresa baseado em NFs Grade A.

    weighted_avg = Σ(unit_price × qty) / Σ(qty)
    """
    pipe = [
        {"$match": {"company_id": company_id, "type": "ont"}},
        {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
        {"$match": {"items.unit_price": {"$gt": 0}}},
        {"$group": {
            "_id": None,
            "total_value": {"$sum": {"$multiply": [
                {"$ifNull": ["$items.unit_price", 0]},
                {"$ifNull": ["$items.quantity", 0]},
            ]}},
            "total_qty": {"$sum": {"$ifNull": ["$items.quantity", 0]}},
        }},
    ]
    rows = await db.purchases.aggregate(pipe).to_list(1)
    if not rows:
        return None
    r = rows[0]
    qty = r.get("total_qty") or 0
    if qty <= 0:
        return None
    return float(r["total_value"]) / float(qty)


# ═══════════ Motor principal de classificação ════════════════════════════════

async def resolve_valuation(
    ont: Dict[str, Any],
    *,
    weighted_avg_cache: Optional[float] = None,
) -> Dict[str, Any]:
    """Determina os 6 campos de valuation para uma ONT.

    Args:
      ont: documento da ONT (precisa de `company_id`, `purchase_id` opcional,
           `mac` opcional, `model` opcional).
      weighted_avg_cache: valor médio ponderado pré-calculado (otimização para
           lotes — evita 1 query por ONT).

    Returns:
      Dict com os 6 campos prontos para `$set` em stok_onts:
      {
        "valor_nf": float | None,
        "valor_medio_ponderado": float | None,
        "valor_referencia": float,
        "valuation_grade": "A"|"B"|"C"|"D"|"F",
        "valuation_source": str,
        "valuation_calculated_at": iso,
        "valuation_needs_human_review": bool,
      }
    """
    cid = ont.get("company_id")
    mac = ont.get("mac")
    purchase_id = ont.get("purchase_id")
    raw_model = ont.get("model") or ont.get("modelo")

    valor_nf: Optional[float] = None
    valor_medio_ponderado: Optional[float] = None
    valor_referencia: float = DEFAULT_REFERENCE_PRICE
    grade: ValuationGrade = "F"
    source: ValuationSource = "unknown"

    # ── 1. Grade A — NF resolvível ────────────────────────────────────────
    if cid and purchase_id:
        try:
            valor_nf = await resolve_nf_price(
                company_id=cid, purchase_id=purchase_id, mac=mac)
        except Exception as e:
            logger.warning("[valuation] resolve_nf_price erro %s/%s: %s",
                           cid, purchase_id, e)

    # ── 2. Grade B — purchase existe mas NF não resolveu → weighted avg ──
    if valor_nf is None and purchase_id:
        if weighted_avg_cache is not None:
            valor_medio_ponderado = weighted_avg_cache
        else:
            try:
                valor_medio_ponderado = await compute_weighted_avg(
                    company_id=cid)
            except Exception as e:
                logger.warning("[valuation] weighted_avg erro %s: %s",
                               cid, e)

    # ── 3. Grade C — modelo canônico ─────────────────────────────────────
    canonical = lookup_model_canonical(raw_model)
    canonical_price = canonical[2] if canonical else None

    # ── Decisão de grade ──────────────────────────────────────────────────
    if valor_nf is not None and valor_nf > 0:
        grade = "A"
        source = "nf"
        valor_referencia = canonical_price or DEFAULT_REFERENCE_PRICE
    elif valor_medio_ponderado is not None and valor_medio_ponderado > 0:
        grade = "B"
        source = "weighted_avg"
        valor_referencia = canonical_price or DEFAULT_REFERENCE_PRICE
    elif canonical_price is not None:
        grade = "C"
        source = "model_canonical"
        valor_referencia = canonical_price
    elif not is_model_garbage(raw_model):
        # Modelo existe e não é lixo, mas não casa com nenhuma chave canônica.
        grade = "D"
        source = "reference"
        valor_referencia = DEFAULT_REFERENCE_PRICE
    else:
        # Fantasma absoluto: sem NF, sem purchase, sem modelo válido.
        grade = "F"
        source = "unknown"
        valor_referencia = DEFAULT_REFERENCE_PRICE

    return {
        "valor_nf": valor_nf,
        "valor_medio_ponderado": valor_medio_ponderado,
        "valor_referencia": valor_referencia,
        "valuation_grade": grade,
        "valuation_source": source,
        "valuation_calculated_at": _now_iso(),
        "valuation_needs_human_review": grade == "F",
    }


def effective_value(valuation: Dict[str, Any]) -> float:
    """Retorna o melhor valor disponível seguindo a prioridade CEO."""
    if valuation.get("valor_nf"):
        return float(valuation["valor_nf"])
    if valuation.get("valor_medio_ponderado"):
        return float(valuation["valor_medio_ponderado"])
    return float(valuation.get("valor_referencia") or DEFAULT_REFERENCE_PRICE)


# ═══════════ Bootstrap de índices (R1.1) ═════════════════════════════════════

async def ensure_indexes() -> Dict[str, bool]:
    """Cria os índices recomendados (idempotente).

    - destructive_actions_audit: {company_id, executed_at desc}
    - destructive_actions_audit: {action_type, executed_at desc}
    - stok_onts: {company_id, valuation_grade}  (Watchtower futura)
    """
    out: Dict[str, bool] = {}
    try:
        await db.destructive_actions_audit.create_index(
            [("company_id", 1), ("executed_at", -1)],
            name="da_company_executed_idx",
        )
        out["da_company_executed_idx"] = True
    except Exception as e:
        logger.warning("[idx] da_company_executed_idx: %s", e)
        out["da_company_executed_idx"] = False
    try:
        await db.destructive_actions_audit.create_index(
            [("action_type", 1), ("executed_at", -1)],
            name="da_action_executed_idx",
        )
        out["da_action_executed_idx"] = True
    except Exception as e:
        logger.warning("[idx] da_action_executed_idx: %s", e)
        out["da_action_executed_idx"] = False
    try:
        await db.stok_onts.create_index(
            [("company_id", 1), ("valuation_grade", 1)],
            name="onts_company_valgrade_idx",
        )
        out["onts_company_valgrade_idx"] = True
    except Exception as e:
        logger.warning("[idx] onts_company_valgrade_idx: %s", e)
        out["onts_company_valgrade_idx"] = False
    return out
