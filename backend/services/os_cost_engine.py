"""IA Patrimonial · Onda IA-1.5 — Motor de CUSTO POR OS.

Combina:
  • Extração de materiais pela IA (services/ia_patrimonial_extractor.py)
  • Catálogo de preços (services/patrimonio_consolidado.PRICE_CATALOG)
  • Fallback para `completion_data` do formulário (preserva compatibilidade)
  • Estimativa de mão-de-obra por tipo de OS (rompimento > troca > inst > reparo)

Diretiva CEO 18/06/2026: "cada OS vira uma linha do DRE operacional".

Modo: READ-ONLY (não escreve em stok_history; apenas calcula custo do
material consumido e mão-de-obra).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.patrimonio_consolidado import PRICE_CATALOG
from services.ia_patrimonial_extractor import (
    extract_from_narrative, FORM_FIELD_TO_ITEM,
)

# IA usa nomes singulares; catálogo histórico usa plurais. Pontes.
IA_TO_PRICE_KEY: Dict[str, str] = {
    "drop": "drop",
    "conector_fast": "conectores_fast",
    "esticador": "esticador",
    "cabo_rede": "cabo_rede",
    "conector_rede": "conectores_rede",
    "caixa_emenda": "caixa_emenda",  # fallback se não estiver no catálogo
}

# Mão-de-obra base (R$) — premissa estimada; CEO pode ajustar
LABOR_BASE_BRL: Dict[str, float] = {
    "instalacao": 35.00,
    "reparo": 15.00,
    "retirada": 12.00,
    "troca": 25.00,
    "rompimento": 55.00,
    "preventiva": 10.00,
}


def _price_lookup(item: str) -> Optional[Dict[str, Any]]:
    key = IA_TO_PRICE_KEY.get(item, item)
    return PRICE_CATALOG.get(key)


def _cost_from_materials_list(
    materials: List[Dict[str, Any]],
) -> Tuple[float, List[Dict[str, Any]], List[str]]:
    """Calcula custo a partir de lista [{item, qty, unit, ...}, ...]."""
    total = 0.0
    lines: List[Dict[str, Any]] = []
    missing: List[str] = []
    for m in materials:
        item = (m.get("item") or "").lower()
        qty = float(m.get("qty") or 0)
        if qty <= 0 or not item:
            continue
        price = _price_lookup(item)
        if not price:
            missing.append(item)
            lines.append({
                "item": item, "qty": qty,
                "unit": m.get("unit") or "?",
                "unit_price": 0.0, "subtotal": 0.0,
                "price_source": "not_found_in_catalog",
                "confidence_price": 0.0,
            })
            continue
        unit_price = float(price.get("value", 0.0))
        subtotal = round(qty * unit_price, 2)
        total += subtotal
        lines.append({
            "item": item, "qty": qty,
            "unit": m.get("unit") or price.get("unit", "?"),
            "unit_price": unit_price, "subtotal": subtotal,
            "price_source": price.get("source", "catalog"),
            "confidence_price": price.get("confidence", 0.5),
            "confidence_extraction": m.get("confidence", 0.0),
            "extraction_source": m.get("source", "?"),
        })
    return round(total, 2), lines, missing


def _materials_from_completion_data(cd: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Constrói lista IA-compatível a partir dos campos numéricos do form."""
    out: List[Dict[str, Any]] = []
    for fkey, (item, unit) in FORM_FIELD_TO_ITEM.items():
        v = cd.get(fkey)
        if isinstance(v, (int, float)) and v > 0:
            out.append({"item": item, "qty": float(v), "unit": unit,
                         "confidence": 1.0, "source": "form_manual"})
    return out


async def compute_os_cost(
    ticket: Dict[str, Any],
    use_ia: bool = True,
    use_form_fallback: bool = True,
) -> Dict[str, Any]:
    """Calcula custo de uma OS.

    Estratégia:
      1. Se `completion_data.descricao` tem narrativa → extrai via IA.
      2. Se IA não pegar materiais E `use_form_fallback`, usa campos do form.
      3. Soma custo material + labor base por service_type.
      4. Marca a fonte (ia | form | mixed | none).
    """
    cd = ticket.get("completion_data") or {}
    narrative = (cd.get("descricao") or cd.get("observacao")
                  or ticket.get("description") or "")
    materials_ia: List[Dict[str, Any]] = []
    service_type = ticket.get("type")
    ia_used = False
    if use_ia and narrative.strip():
        ia = await extract_from_narrative(
            narrative, ticket_type_hint=ticket.get("type"))
        materials_ia = ia.get("materials_detected") or []
        service_type = ia.get("service_type") or service_type
        ia_used = bool(materials_ia)

    materials_form: List[Dict[str, Any]] = []
    if use_form_fallback and not materials_ia:
        materials_form = _materials_from_completion_data(cd)

    materials_used = materials_ia or materials_form
    fonte = "ia" if ia_used else ("form" if materials_form else "none")

    mat_total, mat_lines, missing = _cost_from_materials_list(materials_used)
    labor = LABOR_BASE_BRL.get(service_type or "reparo", 15.0)
    total = round(mat_total + labor, 2)

    return {
        "ticket_id": ticket.get("id"),
        "ticket_type": ticket.get("type"),
        "service_type_detected": service_type,
        "fonte": fonte,
        "ia_used": ia_used,
        "materials": mat_lines,
        "missing_in_catalog": missing,
        "cost_material": mat_total,
        "cost_labor_base": labor,
        "cost_total": total,
        "currency": "BRL",
    }


# ─── Agregadores para Watchtower ──────────────────────────────────────────

async def compute_cost_kpis(cid: str, days: int = 30) -> Dict[str, Any]:
    """KPIs agregados de custo de OS para o Watchtower.

    Retorna:
      • Custo médio por tipo
      • Top 5 técnicos por custo médio
      • Top 5 bairros/zonas
      • Total do período (proxy para DRE operacional)
    """
    from database import db
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = {
        "company_id": cid,
        "status": {"$in": ["finalizada", "encerrada"]},
        "closed_at": {"$gte": cutoff},
    }
    tickets = await db.tickets.find(q, {"_id": 0}).to_list(1000)

    by_type: Dict[str, Dict[str, float]] = {}
    by_tech: Dict[str, Dict[str, float]] = {}
    by_zone: Dict[str, Dict[str, float]] = {}
    total_mat = 0.0
    total_labor = 0.0
    total_os = 0
    total_ia_used = 0

    for t in tickets:
        c = await compute_os_cost(t, use_ia=True, use_form_fallback=True)
        ttype = c.get("service_type_detected") or t.get("type") or "?"
        cost = c.get("cost_total") or 0.0
        cost_mat = c.get("cost_material") or 0.0
        cost_lab = c.get("cost_labor_base") or 0.0
        total_mat += cost_mat
        total_labor += cost_lab
        total_os += 1
        if c.get("ia_used"):
            total_ia_used += 1
        # By type
        d = by_type.setdefault(ttype, {"count": 0, "sum": 0.0, "sum_mat": 0.0})
        d["count"] += 1
        d["sum"] += cost
        d["sum_mat"] += cost_mat
        # By technician
        tech_id = (t.get("assigned_collaborator_id") or
                    t.get("field_origin_collaborator_id") or "?")
        dt = by_tech.setdefault(tech_id, {"count": 0, "sum": 0.0})
        dt["count"] += 1
        dt["sum"] += cost
        # By zone (bairro / praca)
        cs = t.get("client_snapshot") or {}
        zone = (cs.get("bairro") or cs.get("praca")
                 or cs.get("city") or "?")
        dz = by_zone.setdefault(zone, {"count": 0, "sum": 0.0})
        dz["count"] += 1
        dz["sum"] += cost

    def _avg(d: Dict[str, float]) -> float:
        return round(d["sum"] / d["count"], 2) if d.get("count") else 0.0

    by_type_out = [
        {"service_type": k, "count": v["count"],
         "avg_cost": _avg(v),
         "avg_material": round(v["sum_mat"] / v["count"], 2) if v["count"] else 0.0,
         "total_cost": round(v["sum"], 2)}
        for k, v in sorted(by_type.items(), key=lambda x: -x[1]["sum"])
    ]
    by_tech_out = [
        {"collaborator_id": k, "count": v["count"], "avg_cost": _avg(v),
         "total_cost": round(v["sum"], 2)}
        for k, v in sorted(by_tech.items(), key=lambda x: -x[1]["sum"])[:5]
    ]
    by_zone_out = [
        {"zone": k, "count": v["count"], "avg_cost": _avg(v),
         "total_cost": round(v["sum"], 2)}
        for k, v in sorted(by_zone.items(), key=lambda x: -x[1]["sum"])[:5]
    ]

    return {
        "company_id": cid, "window_days": days,
        "total_os": total_os,
        "total_ia_used": total_ia_used,
        "ia_coverage_pct": round(total_ia_used / max(total_os, 1) * 100, 1),
        "total_material_brl": round(total_mat, 2),
        "total_labor_brl": round(total_labor, 2),
        "total_brl": round(total_mat + total_labor, 2),
        "by_type": by_type_out,
        "top_techs": by_tech_out,
        "top_zones": by_zone_out,
        "model_default": "ia_patrimonial+catalog_estimated",
    }
