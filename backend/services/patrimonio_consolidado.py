"""Onda C P2 — Watchtower Patrimônio Consolidado.

Aprovado CEO 18/06/2026. Responde 5 perguntas em <30s:
  1) Quanto patrimônio existe hoje?
  2) Quanto vale?
  3) Quanto desse valor é auditável?
  4) Onde está?
  5) O que não consigo rastrear?

Camadas:
  - asset_category (separa do consumable_id pra Sprint 5 não retrabalhar)
  - Catálogo de preços com metadata {value, source, confidence}
  - Índice de Rastreabilidade: 5 campos × 20% (Origem, Localização,
    Responsável, Última Movimentação, Ticket/Evento)
  - Patrimônio Confiável = Rastreabilidade × Confiabilidade Financeira

NUNCA escreve em estoque. Apenas leitura agregada.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("patrimonio.consolidado")

# ─── Camada `asset_category` (independente do consumable_id) ──────────────

ASSET_CATEGORIES = {
    "ont": {"lifetime_years": 5, "depreciate": True},
    "fibra": {"lifetime_years": 10, "depreciate": True},
    "cto": {"lifetime_years": 10, "depreciate": True},
    "splitter": {"lifetime_years": 10, "depreciate": True},
    "consumivel": {"lifetime_years": None, "depreciate": False},
    "ferramenta": {"lifetime_years": 3, "depreciate": True},
    "veiculo": {"lifetime_years": 5, "depreciate": True},
}

# Catálogo inicial — source=catalog_estimated, confidence baixa
# Valores estimados em R$ (Brasil 2026). Refino vem com purchase_id real.
PRICE_CATALOG: Dict[str, Dict[str, Any]] = {
    # ONT
    "ont": {
        "value": 280.00, "unit": "unidade",
        "category": "ont",
        "source": "catalog_estimated", "confidence": 0.60,
    },
    # Fibras (por metro)
    "fibra_06fo": {"value": 3.20, "unit": "metro", "category": "fibra",
                    "source": "catalog_estimated", "confidence": 0.55},
    "fibra_12fo": {"value": 5.80, "unit": "metro", "category": "fibra",
                    "source": "catalog_estimated", "confidence": 0.55},
    "fibra_24fo": {"value": 8.40, "unit": "metro", "category": "fibra",
                    "source": "catalog_estimated", "confidence": 0.55},
    "fibra_48fo": {"value": 14.20, "unit": "metro", "category": "fibra",
                    "source": "catalog_estimated", "confidence": 0.55},
    "fibra_96fo": {"value": 24.50, "unit": "metro", "category": "fibra",
                    "source": "catalog_estimated", "confidence": 0.50},
    # Drop (por metro)
    "drop": {"value": 1.80, "unit": "metro", "category": "consumivel",
              "source": "catalog_estimated", "confidence": 0.65},
    # Conectores
    "conectores_fast": {"value": 4.80, "unit": "unidade",
                         "category": "consumivel",
                         "source": "catalog_estimated", "confidence": 0.70},
    "conectores_rede": {"value": 2.20, "unit": "unidade",
                         "category": "consumivel",
                         "source": "catalog_estimated", "confidence": 0.70},
    "conector_externo": {"value": 3.40, "unit": "unidade",
                          "category": "consumivel",
                          "source": "catalog_estimated", "confidence": 0.65},
    "conector_interno": {"value": 2.10, "unit": "unidade",
                          "category": "consumivel",
                          "source": "catalog_estimated", "confidence": 0.65},
    # Cabo de rede / Esticador
    "cabo_rede": {"value": 1.30, "unit": "metro", "category": "consumivel",
                   "source": "catalog_estimated", "confidence": 0.60},
    "esticador": {"value": 6.50, "unit": "unidade",
                   "category": "consumivel",
                   "source": "catalog_estimated", "confidence": 0.55},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _price_for(cons_id: str) -> Dict[str, Any]:
    return PRICE_CATALOG.get(cons_id) or {
        "value": 0.0, "unit": "?",
        "category": "consumivel",
        "source": "unknown", "confidence": 0.0,
    }


# ─── Pergunta 1 + 4: Quanto existe + Onde está? ───────────────────────────

async def _agg_ativos_ont(cid: str) -> Dict[str, Any]:
    """Conta ONTs por location_type + flags de qualidade."""
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$location_type", "n": {"$sum": 1}}},
    ]
    by_loc: Dict[str, int] = {}
    async for r in db.stok_onts.aggregate(pipe):
        by_loc[r["_id"] or "sem_location"] = int(r["n"])

    # Sem localização (location_id null/vazio mas com doc) 
    no_loc = await db.stok_onts.count_documents({
        "company_id": cid,
        "$or": [{"location_id": None}, {"location_id": ""},
                {"location_id": {"$exists": False}}],
    })
    # Compradas (tem purchase_id)
    bought = await db.stok_onts.count_documents({
        "company_id": cid, "purchase_id": {"$ne": None, "$exists": True}})
    # Defeito
    defective = await db.stok_onts.count_documents({
        "company_id": cid, "is_defective": True})
    # Sem trilha (sem stok_history apontando)
    # Trilha sintética (origin=synthetic_origin do Onda A)
    synthetic = await db.stok_onts.count_documents({
        "company_id": cid, "synthetic_origin": True})
    total = await db.stok_onts.count_documents({"company_id": cid})

    return {
        "total": total,
        "compradas": bought,
        "em_cliente": by_loc.get("cliente", 0),
        "em_tecnico": by_loc.get("tecnico", 0),
        "em_empresa": by_loc.get("empresa", 0),
        "em_praca": by_loc.get("praca", 0),
        "em_defeito": defective,
        "sem_localizacao": no_loc,
        "sintetica": synthetic,
        "by_location_raw": by_loc,
    }


async def _agg_consumiveis(cid: str) -> Dict[str, Any]:
    """Soma consumíveis por categoria/localização."""
    totals: Dict[str, float] = defaultdict(float)
    async for s in db.stok_stock.find({"company_id": cid}, {"_id": 0}):
        for cons_id, price_meta in PRICE_CATALOG.items():
            if cons_id == "ont":
                continue
            v = s.get(cons_id)
            if isinstance(v, (int, float)) and v > 0:
                totals[cons_id] += v
    return dict(totals)


# ─── Pergunta 2: Quanto vale? ─────────────────────────────────────────────

async def _agg_valor_patrimonial(cid: str,
                                  ativos: Dict[str, Any],
                                  consumiveis: Dict[str, float]
                                  ) -> Dict[str, Any]:
    """Valor patrimonial agregado.

    - aquisicao    = soma(qtd × preço_catalogo)
    - perdas       = valor das defeituosas/anuladas (estimado)
    - recuperacoes = soma de delta_signed positivos em estornos/recovery
    - confiabilidade_financeira = média ponderada da `confidence` de cada item
    """
    aquisicao_total = 0.0
    confidence_weighted_sum = 0.0
    confidence_weight = 0.0

    # ONTs
    ont_total = ativos["total"]
    ont_meta = _price_for("ont")
    aquisicao_ont = ont_total * ont_meta["value"]
    aquisicao_total += aquisicao_ont
    confidence_weighted_sum += aquisicao_ont * ont_meta["confidence"]
    confidence_weight += aquisicao_ont

    # Consumíveis
    aquisicao_consumiveis = 0.0
    for cons_id, qty in consumiveis.items():
        meta = _price_for(cons_id)
        v = qty * meta["value"]
        aquisicao_consumiveis += v
        confidence_weighted_sum += v * meta["confidence"]
        confidence_weight += v
    aquisicao_total += aquisicao_consumiveis

    # Perdas (estimadas): ONTs defeituosas no preço
    perdas = ativos["em_defeito"] * ont_meta["value"]

    # Recuperações: stok_history type in (recovery, rede_estorno) com delta positivo
    rec_pipe = [
        {"$match": {
            "company_id": cid,
            "type": {"$in": ["recovery", "rede_estorno"]},
            "delta_signed": {"$gt": 0},
        }},
        {"$group": {"_id": "$consumable_id", "qty": {"$sum": "$delta_signed"}}},
    ]
    recuperacoes_total = 0.0
    async for r in db.stok_history.aggregate(rec_pipe):
        cons_id = r.get("_id") or "drop"
        qty = r.get("qty") or 0
        meta = _price_for(cons_id)
        recuperacoes_total += qty * meta["value"]
    # Estornos de fibra também contam (rede_estorno usa `delta_meters_signed`)
    rec_pipe2 = [
        {"$match": {
            "company_id": cid,
            "type": "rede_estorno",
            "delta_meters_signed": {"$gt": 0},
        }},
        {"$group": {"_id": "$consumable_id",
                    "qty": {"$sum": "$delta_meters_signed"}}},
    ]
    async for r in db.stok_history.aggregate(rec_pipe2):
        cons_id = r.get("_id") or "fibra_12fo"
        qty = r.get("qty") or 0
        meta = _price_for(cons_id)
        recuperacoes_total += qty * meta["value"]

    # Depreciação linear simples (média 5a pra ONTs)
    # ONT: assume idade média 1 ano (conservador). Refina com Sprint 5.
    depreciacao_anos_media = 1.0
    depr_ont = (depreciacao_anos_media / 5.0) * aquisicao_ont
    depr_fibra = (depreciacao_anos_media / 10.0) * sum(
        consumiveis.get(c, 0) * _price_for(c)["value"]
        for c in ("fibra_06fo", "fibra_12fo", "fibra_24fo",
                  "fibra_48fo", "fibra_96fo")
    )
    depreciacao_total = depr_ont + depr_fibra

    valor_atual = aquisicao_total - depreciacao_total

    confiabilidade_financeira = (
        round(confidence_weighted_sum / confidence_weight, 4)
        if confidence_weight > 0 else 0.0
    )

    return {
        "aquisicao_total": round(aquisicao_total, 2),
        "aquisicao_ont": round(aquisicao_ont, 2),
        "aquisicao_consumiveis": round(aquisicao_consumiveis, 2),
        "depreciacao_total": round(depreciacao_total, 2),
        "valor_atual": round(valor_atual, 2),
        "perdas_estimadas": round(perdas, 2),
        "recuperacoes_total": round(recuperacoes_total, 2),
        "confiabilidade_financeira_pct": round(
            confiabilidade_financeira * 100, 1),
        "confidence_breakdown": {
            "weighted_sum": round(confidence_weighted_sum, 2),
            "weight": round(confidence_weight, 2),
        },
    }


# ─── Pergunta 3 + 5: Quanto é auditável + O que não rastreio? ─────────────

# 5 campos da trilha (20% cada)
TRACK_FIELDS = (
    ("origem", "purchase_id"),
    ("localizacao", "location_id"),
    ("responsavel", "owner_id"),
    ("ultima_movimentacao", "updated_at"),
    ("ticket_evento", "last_ticket_id"),
)


def _track_score(doc: Dict[str, Any]) -> tuple[float, List[str]]:
    """Retorna (score 0..1, lista de campos faltantes)."""
    missing = []
    present = 0
    for label, field in TRACK_FIELDS:
        v = doc.get(field)
        # Aliases razoáveis
        if not v and field == "owner_id":
            v = doc.get("technician_id") or doc.get("assigned_collaborator_id")
        if not v and field == "location_id":
            v = doc.get("location") or doc.get("location_type")
        if not v and field == "updated_at":
            v = doc.get("created_at")
        if not v and field == "last_ticket_id":
            v = doc.get("ticket_id")
        if v:
            present += 1
        else:
            missing.append(label)
    return (present / 5.0, missing)


async def _agg_rastreabilidade(cid: str) -> Dict[str, Any]:
    """Calcula índice de rastreabilidade por ONT + drill-down dos piores."""
    scores: List[float] = []
    by_score_bucket: Dict[int, int] = defaultdict(int)
    worst: List[Dict[str, Any]] = []  # top 50 piores (score baixo)
    async for o in db.stok_onts.find({"company_id": cid}, {"_id": 0}):
        s, missing = _track_score(o)
        scores.append(s)
        bucket = int(s * 5)  # 0..5 (0%, 20%, 40%, 60%, 80%, 100%)
        by_score_bucket[bucket] += 1
        if s < 1.0:
            worst.append({
                "ont_id": o.get("id"),
                "mac": o.get("mac"),
                "sn": o.get("sn"),
                "score_pct": round(s * 100),
                "missing_fields": missing,
                "location_type": o.get("location_type"),
                "is_defective": o.get("is_defective", False),
            })
    worst.sort(key=lambda x: x["score_pct"])
    total = len(scores)
    overall = (sum(scores) / total) if total else 0.0
    return {
        "total_assets": total,
        "overall_index_pct": round(overall * 100, 1),
        "distribution": {
            "0_pct":   by_score_bucket[0],
            "20_pct":  by_score_bucket[1],
            "40_pct":  by_score_bucket[2],
            "60_pct":  by_score_bucket[3],
            "80_pct":  by_score_bucket[4],
            "100_pct": by_score_bucket[5],
        },
        "tier": (
            "excelencia" if overall >= 1.0
            else "verde" if overall >= 0.98
            else "amarelo" if overall >= 0.95
            else "vermelho"
        ),
        "worst_assets": worst[:50],
    }


# ─── Patrimônio Confiável ─────────────────────────────────────────────────

def _compute_patrimonio_confiavel(rast: Dict[str, Any],
                                   valor: Dict[str, Any]) -> Dict[str, Any]:
    """Patrimônio Confiável = Rastreabilidade × Confiabilidade Financeira."""
    rast_pct = rast.get("overall_index_pct", 0) / 100.0
    fin_pct = valor.get("confiabilidade_financeira_pct", 0) / 100.0
    pat_conf_pct = round(rast_pct * fin_pct * 100, 1)
    return {
        "rastreabilidade_pct": rast.get("overall_index_pct", 0),
        "confiabilidade_financeira_pct": valor.get("confiabilidade_financeira_pct", 0),
        "patrimonio_confiavel_pct": pat_conf_pct,
        "valor_defendvel_estimado": round(
            valor.get("valor_atual", 0) * (pat_conf_pct / 100), 2),
        "tier": (
            "excelencia" if pat_conf_pct >= 95
            else "verde" if pat_conf_pct >= 80
            else "amarelo" if pat_conf_pct >= 60
            else "vermelho"
        ),
    }


# ─── Entry point ──────────────────────────────────────────────────────────

async def compute_patrimonio_consolidado(cid: str) -> Dict[str, Any]:
    """Pacote único que responde as 5 perguntas do CEO."""
    import asyncio
    ativos, consumiveis = await asyncio.gather(
        _agg_ativos_ont(cid),
        _agg_consumiveis(cid),
    )
    valor = await _agg_valor_patrimonial(cid, ativos, consumiveis)
    rast = await _agg_rastreabilidade(cid)
    confiavel = _compute_patrimonio_confiavel(rast, valor)
    return {
        "company_id": cid,
        "generated_at": _now().isoformat(),
        # P1: Quanto existe?
        "ativos": ativos,
        "consumiveis_qty": consumiveis,
        # P2: Quanto vale?
        "valor": valor,
        # P3+P5: Quanto é auditável + o que não rastreio?
        "rastreabilidade": rast,
        # KPI compound: Patrimônio Confiável
        "patrimonio_confiavel": confiavel,
        # Catálogo usado (transparência)
        "price_catalog_meta": {
            "items_count": len(PRICE_CATALOG),
            "source": "catalog_estimated_v1_20260618",
            "note": (
                "Confidence baixa (0.50-0.70) porque catálogo é estimativa. "
                "Sprint 5+ deve migrar para purchase_real via invoice."
            ),
        },
        # Asset categories (transparência para Sprint 5)
        "asset_categories": ASSET_CATEGORIES,
    }
