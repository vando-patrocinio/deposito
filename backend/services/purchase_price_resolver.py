"""Onda IA-1.6 — Resolver de preço REAL a partir de purchases.

Calcula custo médio ponderado (CMP) dos itens consumíveis a partir das
compras registradas (`purchases.items`), substituindo o catálogo estimado
quando há dado real disponível.

Matching item canônico ← description livre via palavras-chave:
  drop, fast, esticador, cabo_rede, conector_rede, caixa_emenda

Confiança do preço:
  • > 5 compras nos últimos 180d → confidence 1.0
  • 2-5 compras → 0.85
  • 1 compra → 0.65
  • 0 compras → cai pro PRICE_CATALOG estimado (0.55-0.70)

Cache simples em memória (TTL ~5min) pra não martelar Mongo.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

# Aliases para matching de description → item canônico
DESC_KEYWORDS: Dict[str, List[str]] = {
    "drop": ["drop", "drop-fo", "dropfo", "drop fibra"],
    "conector_fast": ["fast", "conector fast", "fast sc", "fast apc", "scapc"],
    "esticador": ["esticador", "alça preformada", "preformada"],
    "cabo_rede": ["cabo rede", "cabo de rede", "cat5", "cat5e", "cat6",
                   "patch cord"],
    "conector_rede": ["conector rede", "rj45", "conector rj45"],
    "caixa_emenda": ["caixa de emenda", "caixa emenda", "splice box"],
}


def _classify_description(desc: str) -> Optional[str]:
    txt = (desc or "").lower()
    for canon, kws in DESC_KEYWORDS.items():
        for kw in kws:
            if kw in txt:
                return canon
    return None


_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 300  # 5 min


async def get_real_prices(company_id: str,
                            window_days: int = 180) -> Dict[str, Dict[str, Any]]:
    """Retorna prices reais por item canônico:
      { "drop": { "value": 1.73, "source": "purchase_cmp",
                  "confidence": 0.85, "samples": 3,
                  "last_purchase_at": "...", "suppliers": [...] }, ... }
    """
    cache_key = f"{company_id}:{window_days}"
    now_ts = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    # Soma quantidade × valor unitário por item canônico
    agg: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"qty": 0.0, "value": 0.0, "samples": 0,
                  "suppliers": set(), "last_at": ""})
    async for p in db.purchases.find({
        "company_id": company_id,
        "invoice_date": {"$gte": cutoff[:10]},
    }, {"_id": 0, "items": 1, "supplier_name": 1, "invoice_date": 1}):
        for it in (p.get("items") or []):
            desc = str(it.get("description") or "")
            canon = _classify_description(desc)
            if not canon:
                continue
            try:
                qty = float(it.get("quantity") or 0)
                unit_val = float(it.get("unit_value") or it.get("value") or 0)
                if unit_val == 0:
                    total_val = float(it.get("total_value") or 0)
                    if qty > 0 and total_val > 0:
                        unit_val = total_val / qty
            except (ValueError, TypeError):
                continue
            if qty <= 0 or unit_val <= 0:
                continue
            d = agg[canon]
            d["qty"] += qty
            d["value"] += qty * unit_val
            d["samples"] += 1
            sup = p.get("supplier_name")
            if sup:
                d["suppliers"].add(sup)
            inv_date = p.get("invoice_date") or ""
            if inv_date > d["last_at"]:
                d["last_at"] = inv_date

    out: Dict[str, Dict[str, Any]] = {}
    for canon, d in agg.items():
        if d["qty"] <= 0:
            continue
        cmp_price = round(d["value"] / d["qty"], 2)
        if d["samples"] >= 5:
            conf = 1.0
        elif d["samples"] >= 2:
            conf = 0.85
        else:
            conf = 0.65
        out[canon] = {
            "value": cmp_price, "source": "purchase_cmp",
            "confidence": conf, "samples": d["samples"],
            "suppliers": sorted(d["suppliers"]),
            "last_purchase_at": d["last_at"],
        }

    _CACHE[cache_key] = {"ts": now_ts, "data": out}
    return out


async def get_blended_catalog(company_id: str) -> Dict[str, Dict[str, Any]]:
    """Funde preço REAL (purchases) com PRICE_CATALOG estimado.

    Real ganha quando confidence ≥ 0.65.
    """
    from services.patrimonio_consolidado import PRICE_CATALOG

    real = await get_real_prices(company_id)
    blended: Dict[str, Dict[str, Any]] = {}
    for k, v in PRICE_CATALOG.items():
        blended[k] = dict(v)
    # Map IA name → catalog name
    bridge = {
        "drop": "drop",
        "conector_fast": "conectores_fast",
        "esticador": "esticador",
        "cabo_rede": "cabo_rede",
        "conector_rede": "conectores_rede",
    }
    for canon, real_v in real.items():
        cat_key = bridge.get(canon, canon)
        blended[cat_key] = {
            **blended.get(cat_key, {}),
            **real_v,
            "unit": blended.get(cat_key, {}).get("unit", "?"),
            "category": blended.get(cat_key, {}).get("category", "consumivel"),
        }
    return blended


# ─── Confiabilidade do Custo (5 critérios) ────────────────────────────────

def compute_cost_confidence(ticket: Dict[str, Any],
                              cost_breakdown: Dict[str, Any]) -> Dict[str, Any]:
    """Score 0-100% baseado em 5 critérios (CEO 18/06/2026)."""
    crit = {}
    # 1. Material identificado
    crit["material_identificado"] = bool(cost_breakdown.get("materials"))
    # 2. Ticket vinculado a OS (sempre true se cost_breakdown veio de um ticket)
    crit["ticket_vinculado"] = bool(cost_breakdown.get("ticket_id"))
    # 3. Estoque rastreado (preços vieram de purchase, não estimado)
    crit["estoque_rastreado"] = any(
        (m.get("price_source") or "").startswith("purchase")
        for m in (cost_breakdown.get("materials") or [])
    )
    # 4. Técnico identificado
    crit["tecnico_identificado"] = bool(
        ticket.get("assigned_collaborator_id") or
        ticket.get("field_origin_collaborator_id"))
    # 5. Patrimônio rastreado (ONT com ont_id em stok_history — proxy)
    cd = ticket.get("completion_data") or {}
    crit["patrimonio_rastreado"] = bool(
        cd.get("ont") or cd.get("ont_sn") or ticket.get("ont_id_actual"))

    score = round(sum(1 for v in crit.values() if v) / 5 * 100, 1)
    if score >= 80:
        tier = "alta"
    elif score >= 60:
        tier = "media"
    elif score >= 40:
        tier = "baixa"
    else:
        tier = "critica"
    return {
        "score_pct": score, "tier": tier, "criteria": crit,
        "label": "BETA · use apenas para tendência" if score < 60
                  else "use com cuidado" if score < 80
                  else "confiável",
    }
