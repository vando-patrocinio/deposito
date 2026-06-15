"""EXECUTIVE MEMORY — snapshot diário + course correction.

Reusa ONE TRUTH + president_daily (upsert por date_key).
Não cria coleção nova. Não duplica KPI. Não toca em Pamela/Isabella/CI.

Saída persistida em president_daily.{one_truth, compare, course_correction}.
Reversível: campos têm marca `_em_added_by="ceo_digital_v1"`.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "ceo_digital",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database import db
from constants.synthetic_tenants import SYNTHETIC_TENANTS

logger = logging.getLogger(__name__)

ADDED_BY = "ceo_digital_v1"
SUBS_ACTIVE = {"$in": ["ACTIVE", "ATIVO", "active", "ativo"]}
SUBS_INACTIVE = {"$in": ["INATIVO", "inativo", "canceled", "CANCELED"]}
TICKETS_OPEN = {"$in": ["aberta", "pendente",
                          "aguardando_atendimento", "em_atendimento"]}
TICKETS_CLOSED = {"$in": ["encerrada", "finalizada", "cancelada"]}
INVOICE_OVERDUE = {"$in": ["overdue", "OVERDUE", "atrasado"]}
INVOICE_PAID = {"$in": ["paid", "RECEIVED", "CONFIRMED", "Pago"]}


# ───────────────────────── METAS 2026 ─────────────────────────
# Trajetória anual oficial (CEO 14/06/2026). Base: snapshot 15/06/2026.
# Tudo expresso como GANHO ANUAL (12 meses).
METAS_2026 = {
    "clientes_ativos": {"baseline": 2753, "target": 3500, "direction": "up"},
    "mrr": {"baseline": 325241.59, "target": 450000.0, "direction": "up"},
    "inadimplencia_brl": {"baseline": 62485.08, "target": 31000.0,
                           "direction": "down"},
    "embaixadores": {"baseline": 1, "target": 50, "direction": "up"},
    "fundadores_aptos": {"baseline": 2, "target": 30, "direction": "up"},
}
BASELINE_DATE = "2026-06-15"


# ───────────────────────── ONE TRUTH SNAPSHOT ─────────────────────────
async def _one_truth(cid: str, day_iso: str) -> dict:
    """Coleta indicadores oficiais para um dia.

    day_iso é YYYY-MM-DD: usado para janelas "criado_no_dia" / "fechado_no_dia".
    Snapshots como `clientes_ativos` e `mrr` são always "now" (point-in-time).
    """
    base = {"company_id": cid, "excluded_from_kpi": {"$ne": True}}
    day_start = f"{day_iso}T00:00:00"
    day_end = f"{day_iso}T23:59:59"

    # Snapshot point-in-time (estado atual da empresa)
    clientes_ativos = await db.subscribers.count_documents(
        {**base, "status": SUBS_ACTIVE})

    pipe_mrr = [{"$match": {**base, "status": SUBS_ACTIVE}},
                {"$group": {"_id": None,
                              "mrr": {"$sum": {"$ifNull": ["$plan_price", 0]}}}}]
    r = await db.subscribers.aggregate(pipe_mrr).to_list(1)
    mrr = round(float(r[0]["mrr"]) if r else 0.0, 2)

    pipe_inad = [{"$match": {"company_id": cid, "status": INVOICE_OVERDUE}},
                 {"$group": {"_id": None,
                               "brl": {"$sum": {"$ifNull": ["$amount", 0]}},
                               "n": {"$sum": 1}}}]
    r2 = await db.subscriber_invoices.aggregate(pipe_inad).to_list(1)
    inad_brl = round(float(r2[0]["brl"]) if r2 else 0.0, 2)
    inad_n = int(r2[0]["n"]) if r2 else 0

    tickets_abertos = await db.tickets.count_documents(
        {"company_id": cid, "status": TICKETS_OPEN})

    # Janelas "fluxo do dia" (criado/fechado entre 00:00 e 23:59 do day_iso)
    novos = await db.subscribers.count_documents({
        **base, "created_at": {"$gte": day_start, "$lte": day_end}})
    cancelados = await db.subscribers.count_documents({
        **base, "status": SUBS_INACTIVE,
        "updated_at": {"$gte": day_start, "$lte": day_end}})
    tickets_fechados = await db.tickets.count_documents({
        "company_id": cid, "status": TICKETS_CLOSED,
        "updated_at": {"$gte": day_start, "$lte": day_end}})

    fundadores = await db.universo_ligo_invites.count_documents({
        "company_id": cid, "invite_source": "fundador",
        "decision": "APTO"})
    embaixadores = await db.universo_ligo_invites.count_documents({
        "company_id": cid, "decision": "APTO", "status": "accepted",
        "do_not_contact_universo_ligo": {"$ne": True}})

    return {
        "clientes_ativos": clientes_ativos,
        "mrr": mrr,
        "inadimplencia_brl": inad_brl,
        "inadimplencia_n_faturas": inad_n,
        "tickets_abertos": tickets_abertos,
        "tickets_fechados_no_dia": tickets_fechados,
        "novos_clientes_no_dia": novos,
        "cancelamentos_no_dia": cancelados,
        "fundadores_aptos": fundadores,
        "embaixadores": embaixadores,
        "_collected_at": datetime.now(timezone.utc).isoformat(),
    }


# ───────────────────────── COMPARE ─────────────────────────
def _delta(now_val: float, then_val: float) -> dict:
    abs_d = round(now_val - then_val, 2)
    pct = round((abs_d / then_val * 100) if then_val else 0.0, 2)
    return {"abs": abs_d, "pct": pct, "from": then_val, "to": now_val}


async def _value_at_date(cid: str, date_key: str, field: str) -> float:
    """Lê valor histórico de president_daily.one_truth.{field} mais próximo do date_key.

    Se não houver doc no dia, pega o mais recente até essa data.
    """
    doc = await db.president_daily.find_one(
        {"company_id": cid, "date_key": {"$lte": date_key},
         "one_truth": {"$exists": True}},
        sort=[("date_key", -1)])
    if not doc:
        return 0.0
    return float(((doc.get("one_truth") or {}).get(field)) or 0.0)


async def _compare(cid: str, today: dict, today_key: str) -> dict:
    """Compara cada KPI vs ontem, 7d, 30d, baseline (meta)."""
    fields = ["clientes_ativos", "mrr", "inadimplencia_brl",
              "tickets_abertos", "embaixadores", "fundadores_aptos"]
    out: dict[str, dict] = {}
    ref = datetime.strptime(today_key, "%Y-%m-%d").date()
    targets = {
        "ontem": (ref - timedelta(days=1)).isoformat(),
        "7d": (ref - timedelta(days=7)).isoformat(),
        "30d": (ref - timedelta(days=30)).isoformat(),
    }
    for f in fields:
        block = {}
        now_val = float(today.get(f) or 0)
        for label, dk in targets.items():
            then = await _value_at_date(cid, dk, f)
            block[label] = _delta(now_val, then)
        # vs baseline (15/06/2026)
        if f in METAS_2026:
            block["baseline"] = _delta(now_val, METAS_2026[f]["baseline"])
            block["meta"] = METAS_2026[f]["target"]
        out[f] = block
    return out


# ───────────────────────── COURSE CORRECTION ─────────────────────────
def _classify(delta_30d_abs: float, monthly_target: float,
                direction: str) -> str:
    """Classifica em adiantado/no_rumo/atrasado/critico/melhorando/piorando."""
    if direction == "up":
        if monthly_target == 0:
            return "estavel"
        ratio = delta_30d_abs / monthly_target
        if ratio >= 1.10:
            return "adiantado"
        if ratio >= 0.80:
            return "no_rumo"
        if ratio >= 0.20:
            return "atrasado"
        return "critico"
    else:  # direction == "down"
        if monthly_target == 0:
            return "estavel"
        # Aqui o monthly_target já é NEGATIVO (queda esperada)
        ratio = delta_30d_abs / monthly_target
        if ratio >= 1.10:
            return "adiantado"
        if ratio >= 0.80:
            return "no_rumo"
        if ratio >= 0.20:
            return "melhorando"
        if delta_30d_abs > 0:  # piorou (subiu)
            return "piorando"
        return "atrasado"


def _course_correction(today: dict, compare: dict) -> dict:
    """Calcula status por KPI com base em delta 30d vs meta mensal necessária.

    monthly_target = (target - baseline) / 12.
    Para 'down' ele é negativo (queda esperada por mês).
    """
    out: dict[str, Any] = {}
    for kpi, meta in METAS_2026.items():
        block_cmp = compare.get(kpi) or {}
        d30 = (block_cmp.get("30d") or {}).get("abs") or 0.0
        gap_total = meta["target"] - meta["baseline"]  # +ou-
        monthly_needed = gap_total / 12.0
        status = _classify(d30, monthly_needed, meta["direction"])
        # Projeção em 90 dias se mantermos o ritmo dos últimos 30
        projected_in_90d = float(today.get(kpi) or 0) + d30 * 3
        out[kpi] = {
            "delta_30d_abs": round(d30, 2),
            "monthly_needed_abs": round(monthly_needed, 2),
            "ratio": round((d30 / monthly_needed), 3) if monthly_needed else None,
            "status": status,
            "projected_90d": round(projected_in_90d, 2),
            "target": meta["target"],
            "direction": meta["direction"],
        }
    return out


def _course_summary(course: dict) -> str:
    """Mensagem curta: estamos na rota em 90d?"""
    on_track = []
    behind = []
    for kpi, c in course.items():
        if c["status"] in ("adiantado", "no_rumo", "melhorando"):
            on_track.append(kpi)
        else:
            behind.append(kpi)
    if not behind:
        return ("✅ ON TRACK · em 90d ao ritmo atual a Ligo atinge "
                "ou supera as 5 metas anuais.")
    return (f"⚠ FORA DA ROTA · {len(behind)} de {len(course)} KPIs em "
            f"atraso/crítico ({', '.join(behind)}). On-track: "
            f"{', '.join(on_track) or '(nenhum)'}.")


# ───────────────────────── PUBLIC API ─────────────────────────
async def snapshot_today(cid: str, day_iso: str | None = None) -> dict:
    """Coleta + persiste em president_daily (upsert por company_id+date_key)."""
    if cid in SYNTHETIC_TENANTS:
        raise ValueError(f"refusing snapshot for synthetic tenant {cid}")
    now = datetime.now(timezone.utc)
    today_key = day_iso or now.date().isoformat()

    one_truth = await _one_truth(cid, today_key)

    # Para o compare, salvamos PRIMEIRO o one_truth do dia, DEPOIS comparamos
    await db.president_daily.update_one(
        {"company_id": cid, "date_key": today_key},
        {"$set": {"one_truth": one_truth,
                   "_em_added_by": ADDED_BY,
                   "_em_added_at": now.isoformat()},
         "$setOnInsert": {"id": f"pd-{cid}-{today_key}",
                            "company_id": cid, "date_key": today_key,
                            "generated_at": now.isoformat()}},
        upsert=True)

    cmp_block = await _compare(cid, one_truth, today_key)
    course = _course_correction(one_truth, cmp_block)
    summary = _course_summary(course)

    await db.president_daily.update_one(
        {"company_id": cid, "date_key": today_key},
        {"$set": {"compare": cmp_block,
                   "course_correction": course,
                   "course_summary": summary,
                   "metas_oficiais": METAS_2026,
                   "_em_added_by": ADDED_BY}})

    return {"date_key": today_key, "one_truth": one_truth,
            "compare": cmp_block, "course_correction": course,
            "course_summary": summary}


async def backfill_history(cid: str, days: int = 30) -> dict:
    """Backfill aproximado para os últimos N dias.

    Como NÃO temos o estado histórico real (não viajamos no tempo), preenchemos
    apenas o `one_truth` SNAPSHOT atual em cada `date_key` ausente, marcado como
    `_em_backfilled=True`. O `compare` vai mostrar deltas zero para os
    dias backfilled — esperado e documentado. A partir de hoje, cada snapshot
    diário será REAL e os deltas viram úteis em 1-2 dias.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    today_truth = await _one_truth(cid, today.isoformat())
    written = 0
    for d in range(days, 0, -1):
        date_key = (today - timedelta(days=d)).isoformat()
        existing = await db.president_daily.find_one(
            {"company_id": cid, "date_key": date_key, "one_truth": {"$exists": True}})
        if existing:
            continue
        await db.president_daily.update_one(
            {"company_id": cid, "date_key": date_key},
            {"$set": {"one_truth": today_truth,
                       "_em_added_by": ADDED_BY,
                       "_em_backfilled": True,
                       "_em_backfilled_at": now.isoformat()},
             "$setOnInsert": {"id": f"pd-{cid}-{date_key}",
                                "company_id": cid, "date_key": date_key}},
            upsert=True)
        written += 1
    return {"backfilled_days": written, "total_requested": days}


async def rollback(cid: str | None = None) -> dict:
    """Remove só os campos adicionados pelo executive_memory."""
    flt = {"_em_added_by": ADDED_BY}
    if cid:
        flt["company_id"] = cid
    res = await db.president_daily.update_many(
        flt,
        {"$unset": {"one_truth": "", "compare": "",
                     "course_correction": "", "course_summary": "",
                     "metas_oficiais": "",
                     "_em_added_by": "", "_em_added_at": "",
                     "_em_backfilled": "", "_em_backfilled_at": ""}})
    # Apaga docs que SÓ tinham campos do executive_memory (criados pelo backfill)
    drop = await db.president_daily.delete_many(
        {"_em_backfilled": True, "saude": {"$exists": False}})
    return {"unset_modified": res.modified_count,
            "deleted_backfill_only": drop.deleted_count}
