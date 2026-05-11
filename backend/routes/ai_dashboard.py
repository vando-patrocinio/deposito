"""IA Dashboards & Insights — centraliza tudo de IA do produto.

Endpoints:
- Overview KPIs
- Tech Spending (gastos de insumos por técnico × notas fechadas)
- Repair Map (geo-coordenadas das reclamações com sinal/tipo)
- Defective Equipment (modelos/MAC com mais ocorrências)
- Common Issues (reclamações por OLT/board/port)
- Recurring Tickets (clientes que mais reclamam)
- Insight Generator (LLM com Universal Key — Gemini Flash)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, geocode_address, now_iso, require_role
from database import db
from routes.smartolt import _norm

logger = logging.getLogger("ponto.ai_dashboard")
router = APIRouter(prefix="/api/ai/dashboard", tags=["ai_dashboard"])

# ---------- pricing & helpers ----------
PRICE_BRL = {"drop": 0.35, "esticador": 1.20, "conector_fast": 2.50,
             "cabo_rede": 0.80, "conector_rede": 1.10, "conector_fibra": 4.00}

REPAIR_TYPES = ["reparo", "troca_endereco", "troca_titularidade"]
ACTIVE_TICKET_STATUSES = ["aberta", "aguardando_atendimento", "pendente"]


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _classify_complaint(text: str) -> str:
    t = (text or "").lower()
    rules = [
        (("sem internet", "sem sinal", "não conecta", "fora", "queda"), "Sem internet"),
        (("lent", "ruim"), "Lentidão"),
        (("wifi", "wi-fi", "senha"), "Wi-Fi/Senha"),
        (("tv", "iptv"), "TV/IPTV"),
        (("trav", "instabilidade", "oscila"), "Instabilidade"),
        (("ond", "onu"), "ONT/Equipamento"),
        (("tomada", "energia", "queim"), "Energia/Tomada"),
        (("instala", "ativa"), "Instalação"),
        (("trocar", "substitu"), "Troca de equipamento"),
    ]
    for keys, label in rules:
        if any(k in t for k in keys):
            return label
    return "Outros"


async def _onu_for(cid: str, snap: dict, projection: dict) -> dict | None:
    key = _norm(snap.get("pppoe_user")) or _norm(snap.get("name"))
    if not key:
        return None
    return await db.smartolt_onus.find_one(
        {"company_id": cid, "name_norm": key}, projection)


# ---------------------------------------------------------------------------
# 1) Overview KPIs
# ---------------------------------------------------------------------------
async def _collect_overview(cid: str, days: int) -> dict:
    cutoff = _cutoff(days)
    total = await db.tickets.count_documents({"company_id": cid, "created_at": {"$gte": cutoff}})
    finalizadas = await db.tickets.count_documents(
        {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "finalizada"})
    canceladas = await db.tickets.count_documents(
        {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "cancelada"})
    abertas = await db.tickets.count_documents(
        {"company_id": cid, "status": {"$in": ACTIVE_TICKET_STATUSES}})
    techs = await db.collaborators.count_documents(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}, "active": {"$ne": False}})
    prev_pending = await db.ai_preventive_suggestions.count_documents(
        {"company_id": cid, "status": "pending"})
    prev_accepted = await db.ai_preventive_suggestions.count_documents(
        {"company_id": cid, "status": "accepted", "created_at": {"$gte": cutoff}})
    onus_total = await db.smartolt_onus.count_documents({"company_id": cid})
    onus_critical = await db.smartolt_onus.count_documents(
        {"company_id": cid, "status": "Online",
         "$or": [{"signal_1490": {"$lte": -27}}, {"signal_text": {"$in": ["Bad", "Warning"]}}]})
    notif_unread = await db.notifications.count_documents(
        {"company_id": cid, "audience_role": "gestor",
         "$or": [{"read_by": {"$exists": False}}, {"read_by": []}, {"read": False}]})
    stok_errors = await db.stok_services.count_documents(
        {"company_id": cid, "status": "erro_estoque"})
    return {
        "period_days": days,
        "tickets": {"total": total, "finalizadas": finalizadas, "canceladas": canceladas,
                    "abertas": abertas,
                    "fechamento_pct": round(100 * finalizadas / max(1, total), 1)},
        "technicians": {"ativos": techs},
        "ai_preventive": {"pending": prev_pending, "accepted_period": prev_accepted},
        "smartolt": {"onus_total": onus_total, "onus_critical": onus_critical,
                     "critical_pct": round(100 * onus_critical / max(1, onus_total), 1)},
        "alerts": {"notif_unread": notif_unread, "stok_errors": stok_errors},
    }


@router.get("/overview")
async def overview(days: int = 30, user: dict = Depends(require_role("gestor"))):
    return await _collect_overview(_cid(user), days)


# ---------------------------------------------------------------------------
# 2) Tech Spending
# ---------------------------------------------------------------------------
_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|un)\s+([a-z_]+)")
_TECH_RE = re.compile(r"Técnico ([^\[\-]+)")


async def _collect_tech_spending(cid: str, days: int) -> dict:
    cutoff = _cutoff(days)
    by_tech: Dict[str, Dict[str, Any]] = {}
    cur = db.stok_history.find(
        {"company_id": cid, "date": {"$gte": cutoff},
         "type": {"$in": ["instalacao", "retirada"]},
         "tag": "auto_finalize_lousa"},
        {"_id": 0, "user": 1, "description": 1})
    async for h in cur:
        desc = h.get("description", "")
        m = _TECH_RE.search(desc)
        tech_name = (m.group(1).strip() if m else h.get("user", "?")).strip()
        bucket = by_tech.setdefault(tech_name, {"insumos": {}, "custo_brl": 0.0, "notas_count": 0})
        bucket["notas_count"] += 1
        for qty_str, item_id in _QTY_RE.findall(desc):
            try:
                q = float(qty_str)
            except ValueError:
                continue
            bucket["insumos"][item_id] = bucket["insumos"].get(item_id, 0) + q
            bucket["custo_brl"] += q * PRICE_BRL.get(item_id, 0)

    techs_collab = await db.collaborators.find(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(200)
    name_to_id = {t["name"]: t["id"] for t in techs_collab}

    rows: List[dict] = []
    for tname, b in by_tech.items():
        finalizadas = await db.tickets.count_documents(
            {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "finalizada",
             "assigned_collaborator_id": name_to_id.get(tname)})
        rows.append({
            "tech_name": tname, "tech_id": name_to_id.get(tname),
            "notas_baixadas_estoque": b["notas_count"],
            "notas_finalizadas_lousa": finalizadas,
            "insumos_totais": {k: round(v, 1) for k, v in b["insumos"].items()},
            "custo_estimado_brl": round(b["custo_brl"], 2),
            "custo_medio_por_nota": round(b["custo_brl"] / max(1, b["notas_count"]), 2),
        })
    rows.sort(key=lambda r: r["custo_estimado_brl"], reverse=True)
    total_custo = sum(r["custo_estimado_brl"] for r in rows)
    total_notas = sum(r["notas_baixadas_estoque"] for r in rows)
    return {
        "period_days": days, "rows": rows,
        "totals": {"custo_brl": round(total_custo, 2), "notas": total_notas,
                   "custo_medio_por_nota": round(total_custo / max(1, total_notas), 2)},
        "price_table_brl": PRICE_BRL,
    }


@router.get("/tech-spending")
async def tech_spending(days: int = 30, user: dict = Depends(require_role("gestor"))):
    return await _collect_tech_spending(_cid(user), days)


# ---------------------------------------------------------------------------
# 3) Repair Map
# ---------------------------------------------------------------------------
# Concurrency limiter for opportunistic geocoding (Nominatim asks ≤1 rps;
# we keep parallel=4 with sequential city batches to stay polite).
_GEOCODE_SEM = asyncio.Semaphore(4)


async def _geocode_one(addr: str) -> tuple[Optional[float], Optional[float]]:
    """Best-effort geocode. Returns (None, None) on any failure."""
    if not addr or not addr.strip():
        return None, None
    try:
        async with _GEOCODE_SEM:
            geo = await geocode_address(addr.strip())
        return geo.lat, geo.lng
    except Exception as e:
        logger.debug("[repair-map] geocode falhou para '%s': %s", addr[:60], e)
        return None, None


@router.get("/repair-map")
async def repair_map(days: int = 30, only_finalized: bool = False,
                     auto_geocode: bool = True, max_geocode: int = 60,
                     user: dict = Depends(require_role("gestor"))):
    """Mapa de defeitos. Plotagem todas as bolhas (Lousa) com lat/lng nos últimos N dias.

    Para bolhas com endereço mas SEM lat/lng (caso comum em chamados Atlaz que
    não vêm com GPS), fazemos geocoding sob-demanda e persistimos de volta no
    documento — assim na próxima chamada já estão prontos.
    """
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid, "created_at": {"$gte": _cutoff(days)}}
    if only_finalized:
        q["status"] = "finalizada"
    out: List[dict] = []
    type_counter: Counter = Counter()
    pending_geocode: List[dict] = []  # [{ticket_id, address, raw_doc}]

    cur = db.tickets.find(q, {
        "_id": 0, "id": 1, "type": 1, "status": 1, "priority": 1,
        "client_snapshot": 1, "scheduled_time": 1, "created_at": 1, "live_signal": 1,
        "atlaz_external_id": 1})
    async for t in cur:
        snap = t.get("client_snapshot") or {}
        lat, lng = snap.get("latitude"), snap.get("longitude")
        addr = (snap.get("address") or "").strip()

        # Nenhum lat/lng mas tem endereço → enfileira para geocode
        if (lat is None or lng is None) and addr:
            pending_geocode.append({"id": t["id"], "address": addr, "ticket": t})
            continue
        if lat is None or lng is None:
            continue
        out.append(_build_repair_point(t, snap, lat, lng))
        type_counter[t.get("type") or "?"] += 1

    # Geocode opportunistic (limita pra não derrubar o endpoint)
    geocoded_count = 0
    if auto_geocode and pending_geocode:
        batch = pending_geocode[:max(1, int(max_geocode))]
        results = await asyncio.gather(
            *(_geocode_one(item["address"]) for item in batch),
            return_exceptions=False,
        )
        # Persist & include
        write_ops = []
        for item, (lat2, lng2) in zip(batch, results):
            if lat2 is None or lng2 is None:
                continue
            geocoded_count += 1
            t = item["ticket"]
            snap = t.get("client_snapshot") or {}
            out.append(_build_repair_point(t, snap, lat2, lng2))
            type_counter[t.get("type") or "?"] += 1
            write_ops.append((item["id"], lat2, lng2))
        # Update DB (parallel writes — small cost)
        if write_ops:
            await asyncio.gather(*[
                db.tickets.update_one(
                    {"id": tid, "company_id": cid},
                    {"$set": {
                        "client_snapshot.latitude": la,
                        "client_snapshot.longitude": ln,
                        "client_snapshot.geocoded_at": now_iso(),
                    }},
                ) for (tid, la, ln) in write_ops
            ])
            logger.info("[repair-map] geocoded %d/%d tickets opportunistically (cid=%s)",
                        geocoded_count, len(batch), cid)

    # Bounds + center — usa percentis P15-P85 (cobre 70% denso) pra ignorar
    # outliers extremos (chamados teste fora da operação real).
    center: Optional[List[float]] = None
    bbox: Optional[List[List[float]]] = None
    if out:
        sorted_lats = sorted(p["latitude"] for p in out)
        sorted_lngs = sorted(p["longitude"] for p in out)
        n = len(out)
        lo = int(n * 0.15)
        hi = max(lo + 1, int(n * 0.85))
        center = [sorted_lats[n // 2], sorted_lngs[n // 2]]  # mediana
        bbox = [[sorted_lats[lo], sorted_lngs[lo]],
                [sorted_lats[min(hi, n - 1)], sorted_lngs[min(hi, n - 1)]]]

    pending_remaining = max(0, len(pending_geocode) - (max_geocode if auto_geocode else 0))
    return {"period_days": days, "count": len(out), "points": out,
            "by_type": dict(type_counter.most_common()),
            "center": center, "bbox": bbox,
            "geocoded_now": geocoded_count,
            "pending_geocode": pending_remaining}


def _build_repair_point(t: dict, snap: dict, lat: float, lng: float) -> dict:
    return {
        "id": t["id"], "type": t.get("type"), "status": t.get("status"),
        "priority": t.get("priority"),
        "client_name": snap.get("name"), "address": snap.get("address"),
        "neighborhood": snap.get("neighborhood"), "phone": snap.get("phone"),
        "pppoe_user": snap.get("pppoe_user"),
        "relato": (snap.get("relato") or "")[:160],
        "category": _classify_complaint(snap.get("relato") or ""),
        "latitude": lat, "longitude": lng,
        "rx_dbm": (t.get("live_signal") or {}).get("rx_dbm"),
        "signal_quality": (t.get("live_signal") or {}).get("quality"),
        "created_at": t.get("created_at"),
        "scheduled_time": t.get("scheduled_time"),
        "atlaz_external_id": t.get("atlaz_external_id"),
    }


# ---------------------------------------------------------------------------
# 4) Defective Equipment
# ---------------------------------------------------------------------------
async def _collect_defective(cid: str, days: int) -> dict:
    from manufacturers import identify_manufacturer

    cutoff = _cutoff(days)
    tickets = await db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff},
         "type": {"$in": REPAIR_TYPES}},
        {"_id": 0, "id": 1, "client_snapshot.name": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.relato": 1, "type": 1}).to_list(2000)
    proj = {"_id": 0, "unique_external_id": 1, "name": 1, "onu_type_name": 1,
            "olt_name": 1, "board": 1, "port": 1, "signal_1490": 1, "status": 1, "sn": 1}
    by_mfr: dict[str, dict] = {}
    by_ont: dict[str, dict] = {}
    mfr_cache: dict[str, str | None] = {}
    for t in tickets:
        snap = t.get("client_snapshot") or {}
        onu = await _onu_for(cid, snap, proj)
        if not onu:
            continue
        ext_id = onu.get("unique_external_id") or onu.get("sn") or "?"
        sn = onu.get("sn") or ext_id
        # Detect manufacturer (cached per call)
        if sn not in mfr_cache:
            mfr_cache[sn] = await identify_manufacturer(sn)
        manufacturer = mfr_cache[sn] or "Desconhecido"
        bm = by_mfr.setdefault(manufacturer, {"count": 0, "macs": set()})
        bm["count"] += 1
        bm["macs"].add(ext_id)
        bo = by_ont.setdefault(ext_id, {
            "count": 0,
            "manufacturer": manufacturer,
            "model": onu.get("onu_type_name") or "Desconhecido",
            "name": onu.get("name"), "sn": sn,
            "olt": onu.get("olt_name"), "board": onu.get("board"), "port": onu.get("port"),
            "current_signal": onu.get("signal_1490"), "current_status": onu.get("status"),
            "categorias": Counter()})
        bo["count"] += 1
        bo["categorias"][_classify_complaint(snap.get("relato") or "")] += 1

    manufacturers_rows = sorted(
        [{"manufacturer": k, "ocorrencias": v["count"],
          "equipamentos_distintos": len(v["macs"])}
         for k, v in by_mfr.items()],
        key=lambda r: r["ocorrencias"], reverse=True)
    onts_rows = sorted([
        {"external_id": k, "name": v["name"],
         "manufacturer": v["manufacturer"], "model": v["model"], "sn": v["sn"],
         "olt": v["olt"], "board": v["board"], "port": v["port"],
         "current_signal": v["current_signal"], "current_status": v["current_status"],
         "ocorrencias": v["count"],
         "top_categoria": v["categorias"].most_common(1)[0][0] if v["categorias"] else None}
        for k, v in by_ont.items()
    ], key=lambda r: r["ocorrencias"], reverse=True)[:50]
    return {"period_days": days, "manufacturers": manufacturers_rows,
            "top_onts": onts_rows,
            "total_matched_tickets": sum(b["count"] for b in by_mfr.values())}


@router.get("/defective-equipment")
async def defective_equipment(days: int = 90,
                              user: dict = Depends(require_role("gestor"))):
    return await _collect_defective(_cid(user), days)


# ---------------------------------------------------------------------------
# 5) Common Issues
# ---------------------------------------------------------------------------
async def _collect_common_issues(cid: str, days: int) -> dict:
    cutoff = _cutoff(days)
    tickets = await db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "client_snapshot.relato": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.name": 1}).to_list(5000)
    cat_counter: Counter = Counter()
    olt_counter: Counter = Counter()
    pp_counter: Counter = Counter()
    proj = {"_id": 0, "olt_name": 1, "board": 1, "port": 1}
    for t in tickets:
        snap = t.get("client_snapshot") or {}
        cat_counter[_classify_complaint(snap.get("relato") or "")] += 1
        onu = await _onu_for(cid, snap, proj)
        if onu:
            olt_counter[onu.get("olt_name") or "?"] += 1
            pp_counter[f"{onu.get('olt_name', '?')} · B{onu.get('board', '?')} / P{onu.get('port', '?')}"] += 1
    return {
        "period_days": days,
        "by_category": [{"category": k, "count": v} for k, v in cat_counter.most_common()],
        "by_olt": [{"olt": k, "count": v} for k, v in olt_counter.most_common()],
        "by_port": [{"location": k, "count": v} for k, v in pp_counter.most_common(20)],
    }


@router.get("/common-issues")
async def common_issues(days: int = 30, user: dict = Depends(require_role("gestor"))):
    return await _collect_common_issues(_cid(user), days)


# ---------------------------------------------------------------------------
# 6) Recurring Tickets
# ---------------------------------------------------------------------------
async def _collect_recurring(cid: str, days: int) -> dict:
    cutoff = _cutoff(days)
    techs_collab = await db.collaborators.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
    tid_to_name = {t["id"]: t["name"] for t in techs_collab}

    by_client: Dict[str, Dict[str, Any]] = {}
    cur = db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "client_snapshot.name": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.address": 1, "assigned_collaborator_id": 1, "type": 1, "status": 1,
         "created_at": 1})
    async for t in cur:
        snap = t.get("client_snapshot") or {}
        key = _norm(snap.get("pppoe_user")) or _norm(snap.get("name") or "") or t["id"]
        b = by_client.setdefault(key, {
            "client_name": snap.get("name"), "pppoe_user": snap.get("pppoe_user"),
            "address": snap.get("address"), "tickets": [], "techs": Counter(), "types": Counter()})
        b["tickets"].append(t["id"])
        b["techs"][tid_to_name.get(t.get("assigned_collaborator_id"), "?")] += 1
        b["types"][t.get("type") or "?"] += 1

    techs_revisits: Dict[str, Dict[str, Any]] = {}
    for b in by_client.values():
        if len(b["tickets"]) < 2:
            continue
        for tech_name, n in b["techs"].items():
            if n >= 2:
                tr = techs_revisits.setdefault(tech_name, {"revisits": 0, "clients": []})
                tr["revisits"] += n - 1
                tr["clients"].append({"client": b["client_name"], "count": n,
                                      "pppoe": b["pppoe_user"]})

    clients_rows = sorted([
        {"client_name": v["client_name"], "pppoe_user": v["pppoe_user"],
         "address": v["address"], "total_tickets": len(v["tickets"]),
         "techs_envolvidos": dict(v["techs"]), "tipos": dict(v["types"])}
        for v in by_client.values() if len(v["tickets"]) >= 2
    ], key=lambda r: r["total_tickets"], reverse=True)[:50]

    techs_rows = sorted([
        {"tech_name": k, "revisits_count": v["revisits"], "top_clients": v["clients"][:5]}
        for k, v in techs_revisits.items()
    ], key=lambda r: r["revisits_count"], reverse=True)

    return {"period_days": days, "top_recurring_clients": clients_rows,
            "techs_revisits": techs_rows,
            "total_clients_with_2_plus": len(clients_rows)}


@router.get("/recurring-tickets")
async def recurring_tickets(days: int = 30,
                            user: dict = Depends(require_role("gestor"))):
    return await _collect_recurring(_cid(user), days)


# ---------------------------------------------------------------------------
# 7) Insight Generator (LLM)
# ---------------------------------------------------------------------------
class InsightRequest(BaseModel):
    dashboard: str  # "overview" | "tech_spending" | "common_issues" | "recurring" | "defective"
    context_days: int = 30


_COLLECTORS: Dict[str, Callable[[str, int], Awaitable[dict]]] = {
    "overview": _collect_overview,
    "tech_spending": _collect_tech_spending,
    "common_issues": _collect_common_issues,
    "recurring": _collect_recurring,
    "defective": _collect_defective,
}


@router.post("/insight")
async def generate_insight(payload: InsightRequest,
                           user: dict = Depends(require_role("gestor"))):
    collector = _COLLECTORS.get(payload.dashboard)
    if not collector:
        raise HTTPException(400, "dashboard inválido")
    cid = _cid(user)
    try:
        data = await collector(cid, payload.context_days)
    except Exception as e:
        raise HTTPException(500, f"Falha ao coletar dados: {e}") from e

    from services.motor_ia import chat_completion
    system_msg = (
        "Você é um analista sênior de operações de provedores de internet (FTTH). "
        "Recebe um JSON com KPIs do último período e gera 3-5 insights ACIONÁVEIS, "
        "no formato bullet em PORTUGUÊS, focados em redução de custo, qualidade de "
        "serviço e produtividade dos técnicos. Cada insight deve citar números do JSON. "
        "Não invente dados. Termine com 1 ação RECOMENDADA prioritária."
    )
    prompt = (f"Dashboard: {payload.dashboard}\nPeríodo: {payload.context_days} dias\n"
              f"Dados:\n```json\n{json.dumps(data, ensure_ascii=False, default=str)[:8000]}\n```")
    try:
        result = await chat_completion(
            cid,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4, max_tokens=900,
        )
        text = result.get("content") or ""
    except Exception as e:
        raise HTTPException(502, f"LLM falhou: {e}") from e

    rec = {
        "id": f"insight-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "dashboard": payload.dashboard,
        "context_days": payload.context_days, "generated_at": now_iso(),
        "generated_by": user.get("name"), "text": text,
    }
    await db.ai_insights.insert_one(rec)
    return {"id": rec["id"], "text": text, "dashboard": payload.dashboard}


@router.get("/insights/history")
async def insights_history(limit: int = 20,
                           user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    cur = db.ai_insights.find({"company_id": cid}, {"_id": 0}).sort("generated_at", -1).limit(limit)
    return await cur.to_list(limit)


# ---------------------------------------------------------------------------
# 8) Assets overview — pertences/EPIs por colaborador
# ---------------------------------------------------------------------------
@router.get("/assets-overview")
async def assets_overview(user: dict = Depends(require_role("gestor"))):
    """Resumo de pertences/EPIs por colaborador.
    - KPIs globais (total de itens, ativos, pendentes de assinatura, devolvidos)
    - Itens agrupados por categoria
    - Por colaborador: contagem ativa, pendente assinatura, devolvido
    """
    cid = _cid(user)
    techs = await db.collaborators.find(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "avatar_data_url": 1},
    ).to_list(500)
    tid_to = {t["id"]: t for t in techs}
    rows = await db.collaborator_assets.find(
        {"company_id": cid}, {"_id": 0},
    ).to_list(5000)
    by_collab: Dict[str, Dict[str, Any]] = {}
    by_category: Counter = Counter()
    by_status: Counter = Counter()
    pending_signature = 0
    total_qty = 0
    for r in rows:
        tid = r.get("collaborator_id")
        coll = tid_to.get(tid) or {}
        b = by_collab.setdefault(tid, {
            "collaborator_id": tid,
            "name": coll.get("name") or "?",
            "role": coll.get("role"),
            "avatar_data_url": coll.get("avatar_data_url"),
            "total": 0, "ativo": 0, "devolvido": 0,
            "danificado": 0, "perdido": 0,
            "pending_signature": 0, "signed": 0,
            "categories": Counter(),
        })
        b["total"] += 1
        st = r.get("status", "ativo")
        b[st] = b.get(st, 0) + 1
        b["categories"][r.get("category") or "outro"] += 1
        if not r.get("signed_at"):
            b["pending_signature"] += 1
            pending_signature += 1
        else:
            b["signed"] += 1
        by_category[r.get("category") or "outro"] += 1
        by_status[st] += 1
        total_qty += int(r.get("qty") or 1)

    rows_collab = sorted([
        {**v, "categories": dict(v["categories"])}
        for v in by_collab.values()
    ], key=lambda r: r["total"], reverse=True)

    return {
        "kpis": {
            "total_assets": len(rows),
            "total_qty": total_qty,
            "active": by_status.get("ativo", 0),
            "returned": by_status.get("devolvido", 0),
            "damaged": by_status.get("danificado", 0),
            "lost": by_status.get("perdido", 0),
            "pending_signature": pending_signature,
            "techs_with_assets": len(rows_collab),
        },
        "by_category": [{"category": k, "count": v}
                        for k, v in by_category.most_common()],
        "by_status": [{"status": k, "count": v}
                      for k, v in by_status.most_common()],
        "rows": rows_collab,
        "pending_losses": await _pending_losses(cid, tid_to),
    }


# Default value-by-category (BRL) used when asset has no unit_value_brl set.
_DEFAULT_VALUES = {"uniforme": 80, "epi": 150, "ferramenta": 200,
                   "veiculo": 10000, "eletronico": 500, "outro": 100}


async def _pending_losses(cid: str, tid_to: Dict[str, dict]) -> dict:
    """Lista colaboradores inativos (active=False) que ainda têm pertences
    com status='ativo'. Calcula valor estimado em BRL.
    """
    # Pull the per-company custom value table; fall back to global defaults.
    branding_doc = await db.company_branding.find_one(
        {"company_id": cid}, {"_id": 0, "default_asset_values_brl": 1})
    custom = (branding_doc or {}).get("default_asset_values_brl") or {}
    values = {**_DEFAULT_VALUES, **{k: float(v) for k, v in custom.items() if v is not None}}

    inactive = await db.collaborators.find(
        {"company_id": cid, "active": False, "atlaz_inbox": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "deactivated_at": 1, "updated_at": 1},
    ).to_list(500)
    inactive_ids = [c["id"] for c in inactive]
    if not inactive_ids:
        return {"rows": [], "total_brl": 0.0, "items_count": 0,
                "inactive_collaborators": 0,
                "default_values_brl": values}
    pending = await db.collaborator_assets.find(
        {"company_id": cid, "collaborator_id": {"$in": inactive_ids},
         "status": "ativo"},
        {"_id": 0},
    ).to_list(2000)
    by_collab: Dict[str, Dict[str, Any]] = {}
    total_value = 0.0
    for a in pending:
        unit = a.get("unit_value_brl")
        if unit is None:
            unit = values.get(a.get("category"), 100)
        line_value = float(unit) * int(a.get("qty") or 1)
        total_value += line_value
        cid2 = a["collaborator_id"]
        coll = next((c for c in inactive if c["id"] == cid2), {})
        b = by_collab.setdefault(cid2, {
            "collaborator_id": cid2,
            "name": coll.get("name") or "?",
            "role": coll.get("role"),
            "deactivated_at": coll.get("deactivated_at") or coll.get("updated_at"),
            "items": [], "value_brl": 0.0,
        })
        b["items"].append({
            "id": a["id"], "category": a.get("category"),
            "item": a.get("item"), "marca": a.get("marca"),
            "modelo": a.get("modelo"), "qty": a.get("qty"),
            "value_brl": round(line_value, 2),
            "delivered_at": a.get("delivered_at"),
        })
        b["value_brl"] += line_value
    rows = sorted([{**v, "value_brl": round(v["value_brl"], 2)}
                   for v in by_collab.values()],
                  key=lambda r: r["value_brl"], reverse=True)
    return {
        "rows": rows,
        "total_brl": round(total_value, 2),
        "items_count": len(pending),
        "inactive_collaborators": len(rows),
        "default_values_brl": values,
    }



# ---------------------------------------------------------------------------
# 9) Manufacturer quality ranking — defects per brand
# ---------------------------------------------------------------------------
@router.get("/manufacturer-quality")
async def manufacturer_quality(days: int = 90,
                                user: dict = Depends(require_role("gestor"))):
    """Ranking 'Marcas com mais defeitos no campo'.

    Cruza fabricante de cada ONU em uso (`smartolt_onus` + `manufacturer_cache`)
    com chamados Atlaz tipo 'reparo' nos últimos N dias, agregando por marca.

    Cada linha:
      - manufacturer
      - onus_in_field: total de ONUs daquela marca em uso (clientes)
      - defect_calls: chamados de reparo nos últimos N dias para clientes com
        ONU daquela marca (match por nome do cliente — o SmartOLT salva o nome
        igual ao Atlaz)
      - defect_rate: defect_calls / onus_in_field × 100 (%)
    """
    cid = _cid(user)
    cutoff = _cutoff(days)

    # Build prefix→manufacturer (KNOWN + cache)
    from manufacturers import KNOWN_PREFIXES, _ascii_prefix, _hex_prefix
    prefix_map = dict(KNOWN_PREFIXES)
    async for c in db.manufacturer_cache.find(
            {"manufacturer": {"$ne": None}},
            {"_id": 0, "prefix": 1, "manufacturer": 1}):
        if c.get("manufacturer"):
            prefix_map[c["prefix"]] = c["manufacturer"]

    # Build name_norm → manufacturer (uses same _norm() do SmartOLT sync,
    # casa pppoe_user e name removendo acentos/espaços/underscores/hífen).
    client_to_manuf: dict = {}
    async for o in db.smartolt_onus.find(
            {"company_id": cid}, {"_id": 0, "name": 1, "sn": 1, "name_norm": 1}):
        sn = (o.get("sn") or "").strip().upper()
        if not sn:
            continue
        manuf = None
        for cand in (_ascii_prefix(sn), _hex_prefix(sn)):
            if cand in prefix_map:
                manuf = prefix_map[cand]
                break
        # name_norm já está pré-calculado no sync; fallback para _norm(name)
        key = o.get("name_norm") or _norm(o.get("name") or "")
        if key:
            client_to_manuf[key] = manuf or "Desconhecido"

    # Count ONUs per manufacturer
    onus_count: Counter = Counter(client_to_manuf.values())

    # Iterate defect tickets — tenta casar por pppoe_user OU por nome (ambos normalizados)
    defect_count: Counter = Counter()
    matched_calls = unmatched_calls = 0
    async for t in db.tickets.find(
            {"company_id": cid, "type": "reparo",
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "client_snapshot": 1, "atlaz_pppoe_user": 1}):
        snap = t.get("client_snapshot") or {}
        candidates = [
            _norm(snap.get("pppoe_user") or t.get("atlaz_pppoe_user") or ""),
            _norm(snap.get("name") or ""),
        ]
        m = next((client_to_manuf[k] for k in candidates if k and k in client_to_manuf), None)
        if m:
            defect_count[m] += 1
            matched_calls += 1
        else:
            unmatched_calls += 1

    # Build ranking rows
    rows: List[dict] = []
    for manuf, n_onus in onus_count.most_common():
        defects = defect_count.get(manuf, 0)
        rate = (100.0 * defects / n_onus) if n_onus > 0 else 0
        rows.append({
            "manufacturer": manuf,
            "onus_in_field": n_onus,
            "defect_calls": defects,
            "defect_rate_pct": round(rate, 2),
        })
    # Order by rate (desc), tiebreaker by defects (desc)
    rows.sort(key=lambda r: (-r["defect_rate_pct"], -r["defect_calls"]))

    return {
        "period_days": days,
        "total_onus": sum(onus_count.values()),
        "total_defect_calls": sum(defect_count.values()),
        "matched_calls": matched_calls,
        "unmatched_calls": unmatched_calls,
        "rows": rows,
    }
