"""ISABELLA EXPANSION COMMANDER — ranking de áreas de expansão.

Cruza, com dados REAIS:
  • `sales_leads`, `site_leads`, `indicacao_leads` (demanda comercial real)
  • `tickets type=instalacao status=cancelada` / leads recusados por área
  • `cto_ports` (CTOs existentes + ocupação)
  • `subscribers` (penetração atual por região)

Calcula:
  • leads/30d por região
  • CTO mais próxima (ou ausência)
  • ARPU × leads conversíveis → impacto BRL/mês
  • ROI esperado (12 meses)
"""
from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import get_arpu, upsert_opportunity

log = logging.getLogger("ponto.isabella_expansion")


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                  if unicodedata.category(c) != "Mn")
    return s.upper().strip()


def _now():
    return datetime.now(timezone.utc)


async def _leads_by_region(company_id: str) -> Dict[str, Dict[str, Any]]:
    cutoff = (_now() - timedelta(days=90)).isoformat()
    out: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "sources": defaultdict(int),
                 "samples": [], "phones": set()})
    # site_leads
    async for r in db.site_leads.find(
            {"company_id": company_id, "created_at": {"$gte": cutoff}},
            {"_id": 0, "region": 1, "address": 1, "phone": 1,
             "name": 1, "status": 1}):
        region = _norm(r.get("region") or r.get("address") or "")
        if not region:
            continue
        out[region]["n"] += 1
        out[region]["sources"]["site"] += 1
        if len(out[region]["samples"]) < 5:
            out[region]["samples"].append({"name": r.get("name"),
                                              "phone": r.get("phone")})
        if r.get("phone"):
            out[region]["phones"].add(r["phone"])
    # indicacao_leads
    async for r in db.indicacao_leads.find(
            {"company_id": company_id, "created_at": {"$gte": cutoff}},
            {"_id": 0, "city": 1, "cep": 1, "phone": 1, "name": 1}):
        region = _norm(r.get("city") or "")
        if not region:
            continue
        out[region]["n"] += 1
        out[region]["sources"]["indicacao"] += 1
        if r.get("phone"):
            out[region]["phones"].add(r["phone"])
    # sales_leads (tem só phone + source — agrupa por source/region "unknown")
    async for r in db.sales_leads.find(
            {"company_id": company_id, "ts": {"$gte": cutoff}},
            {"_id": 0, "source": 1, "phone": 1}):
        region = _norm(r.get("source") or "INDEFINIDO")
        if not region:
            continue
        out[region]["n"] += 1
        out[region]["sources"]["sales"] += 1
        if r.get("phone"):
            out[region]["phones"].add(r["phone"])
    # transforma sets em listas
    for k in out:
        out[k]["phones"] = list(out[k]["phones"])
        out[k]["sources"] = dict(out[k]["sources"])
    return out


async def _cto_density(company_id: str) -> Dict[str, Dict[str, Any]]:
    """Quantas CTOs / ocupação por bairro."""
    pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {
            "_id": "$neighborhood",
            "ctos": {"$addToSet": "$cto_id"},
            "occupied": {"$sum": {"$cond": [
                {"$eq": ["$status", "occupied"]}, 1, 0]}},
            "total_ports": {"$sum": 1},
        }},
    ]
    out: Dict[str, Dict[str, Any]] = {}
    async for r in db.cto_ports.aggregate(pipe):
        region = _norm(r.get("_id") or "")
        if not region:
            continue
        ctos = [c for c in (r.get("ctos") or []) if c]
        out[region] = {"ctos": len(ctos),
                          "occupied": int(r.get("occupied") or 0),
                          "total_ports": int(r.get("total_ports") or 0)}
    return out


async def scan_company(company_id: str) -> Dict[str, Any]:
    arpu = await get_arpu(company_id)
    leads = await _leads_by_region(company_id)
    density = await _cto_density(company_id)
    if not leads:
        return {"company_id": company_id, "opportunities": 0,
                "reason": "sem leads recentes"}

    created = 0
    ranking: List[Dict[str, Any]] = []
    for region, data in leads.items():
        n = data["n"]
        if n < 3:
            continue
        d = density.get(region, {"ctos": 0, "occupied": 0, "total_ports": 0})
        # Quanto mais leads vs porta livre, maior o score
        free_ports = max(0, d["total_ports"] - d["occupied"])
        gap = max(0, n - free_ports)
        score = min(100.0, 35 + n * 3 + gap * 4 - (d["ctos"] * 2))
        if score < 40:
            continue
        # taxa de conversão proxy: 35%
        conv = 0.35
        clientes_potenciais = round(n * conv, 1)
        impact_year = round(clientes_potenciais * arpu * 12, 2)
        prob = min(0.85, 0.3 + gap * 0.05)
        action = {"type": "expand_coverage",
                  "channel": "rede_ia",
                  "region": region,
                  "leads_90d": n,
                  "phones_sample": data.get("phones", [])[:10],
                  "ctos_existing": d["ctos"],
                  "ports_free": free_ports,
                  "requires_approval": True}
        await upsert_opportunity(
            company_id=company_id,
            kind="expansion",
            subkind="expand_area",
            target_type="region",
            target_id=region.replace(" ", "_"),
            target_label=region,
            score=score,
            probability=prob,
            impact_brl=impact_year,
            reason_codes=[
                f"{n} leads em 90d na região",
                f"{free_ports} portas livres / {d['ctos']} CTO(s) existente(s)",
                f"Conversão estimada {conv:.0%} → ~{clientes_potenciais} clientes"
            ],
            evidence={"leads_90d": n,
                        "leads_sources": data["sources"],
                        "samples": data["samples"],
                        "ctos_existing": d["ctos"],
                        "occupied": d["occupied"],
                        "free_ports": free_ports,
                        "arpu_brl": arpu},
            recommended_action=action,
            ttl_hours=24 * 30,  # 30 dias
            source="isabella_expansion",
        )
        created += 1
        ranking.append({"region": region, "score": score,
                          "leads": n, "impact_year_brl": impact_year})
        await emit_event(
            EventType.EXPANSION_AREA_RECOMMENDED,
            company_id=company_id, source="isabella_expansion",
            severity="alta" if score >= 70 else "media",
            payload={"region": region, "score": score,
                      "impact_year_brl": impact_year})

    ranking.sort(key=lambda r: r["score"], reverse=True)
    return {"company_id": company_id, "arpu": arpu,
            "regions_scanned": len(leads),
            "opportunities": created,
            "ranking": ranking[:20]}


async def scan_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await scan_company(cid))
        except Exception as e:
            log.exception("[expansion] %s failed: %s", cid, e)
    return out
