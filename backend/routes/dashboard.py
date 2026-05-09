"""Endpoints do Painel/Dashboard executivo, tendência e heatmap.

`dashboard_overtime` (mês simples) e o helper `compute_timesheet`
permanecem em server.py — aqui importamos lazy para evitar import circular.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core import (
    DEMO_COMPANY_ID,
    build_stay_clusters,
    effective_company_id,
    get_current_user,
    get_settings,
    haversine_m,
    is_super_admin,
)
from database import db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _tenant_cid(user: dict) -> Optional[str]:
    """Retorna company_id efetivo (None p/ super admin sem override = cross-tenant)."""
    return effective_company_id(user)


@router.get("/overtime/trend")
async def overtime_trend(months: int = 6, user: dict = Depends(get_current_user)):
    """Tendência de HE dos últimos N meses + projeção do mês corrente."""
    from server import dashboard_overtime  # lazy import (mantido em server.py)

    cid = _tenant_cid(user)
    today = datetime.now(timezone.utc)
    cur_y, cur_m, cur_d = today.year, today.month, today.day
    months = max(1, min(int(months), 24))
    series = []
    for i in range(months - 1, -1, -1):
        m = cur_m - i
        y = cur_y
        while m <= 0:
            m += 12
            y -= 1
        try:
            d = await dashboard_overtime(y, m, company_id=cid)
        except HTTPException:
            continue
        last_day = calendar.monthrange(y, m)[1]
        if y == cur_y and m == cur_m:
            ratio = last_day / max(cur_d, 1)
            projected_min = round(d["total_overtime_min"] * ratio)
            projected_brl = round(d["total_paid_brl"] * ratio, 2)
            is_current = True
        else:
            projected_min = d["total_overtime_min"]
            projected_brl = d["total_paid_brl"]
            is_current = False
        series.append({
            "year": y, "month": m,
            "label": f"{m:02d}/{y}",
            "total_overtime_min": d["total_overtime_min"],
            "total_paid_brl": d["total_paid_brl"],
            "projected_overtime_min": projected_min,
            "projected_paid_brl": projected_brl,
            "is_current": is_current,
        })

    cur = next((s for s in series if s["is_current"]), None)
    debit_ranking = []
    if cur:
        d = await dashboard_overtime(cur["year"], cur["month"], company_id=cid)
        debit_ranking = sorted(
            [r for r in d["rows"] if r["balance_min"] < 0],
            key=lambda r: r["balance_min"],
        )[:5]

    cfg = await get_settings(cid)
    budget = float(getattr(cfg, "he_monthly_budget_brl", 0.0) or 0.0)
    threshold = float(getattr(cfg, "he_alert_threshold_pct", 30.0) or 30.0)
    alerts: list[dict] = []
    if cur:
        realized = float(cur["total_paid_brl"] or 0.0)
        projected = float(cur["projected_paid_brl"] or 0.0)
        if budget > 0 and projected > budget:
            pct = ((projected - budget) / budget) * 100.0
            alerts.append({
                "level": "danger",
                "id": "budget_exceeded",
                "title": f"Projeção indica estouro do orçamento de HE em {cur['label']}",
                "message": (
                    f"Projeção: R$ {projected:.2f} · Orçamento: R$ {budget:.2f} "
                    f"({pct:+.1f}% acima)."
                ),
                "projected": projected, "budget": budget, "percent_over": round(pct, 1),
            })
        elif budget > 0 and projected >= budget * 0.9:
            pct = (projected / budget) * 100.0
            alerts.append({
                "level": "warning",
                "id": "budget_close",
                "title": f"Atenção: HE projetada de {cur['label']} em {pct:.0f}% do orçamento",
                "message": f"Projeção: R$ {projected:.2f} · Orçamento: R$ {budget:.2f}.",
                "projected": projected, "budget": budget, "percent": round(pct, 1),
            })
        if realized > 0 and projected > realized * (1 + threshold / 100.0):
            jump = ((projected - realized) / realized) * 100.0
            alerts.append({
                "level": "warning",
                "id": "projection_jump",
                "title": f"Projeção {jump:+.0f}% acima do realizado até agora",
                "message": (
                    f"Custo realizado até hoje: R$ {realized:.2f} · "
                    f"projeção do mês: R$ {projected:.2f} (limite alerta: {threshold:.0f}%)."
                ),
                "realized": realized, "projected": projected, "jump_pct": round(jump, 1),
            })

    return {
        "months": months,
        "series": series,
        "top_debit": debit_ranking,
        "alerts": alerts,
        "budget_brl": budget,
        "threshold_pct": threshold,
    }


@router.get("/overtime/range")
async def overtime_range(year_from: int, month_from: int, year_to: int, month_to: int, mode: str = "monthly",
                         user: dict = Depends(get_current_user)):
    """Resumo de HE em intervalo arbitrário (mode='monthly' ou 'accumulated')."""
    from server import dashboard_overtime  # lazy
    cid = _tenant_cid(user)

    def _norm(y: int, m: int) -> tuple[int, int]:
        if m < 1 or m > 12 or y < 2000 or y > 2999:
            raise HTTPException(400, "Período inválido")
        return y, m
    yf, mf = _norm(year_from, month_from)
    yt, mt = _norm(year_to, month_to)
    if (yt, mt) < (yf, mf):
        yf, mf, yt, mt = yt, mt, yf, mf

    today = datetime.now(timezone.utc)
    cur_y, cur_m, cur_d = today.year, today.month, today.day
    series: list[dict] = []
    y, m = yf, mf
    safety = 0
    while (y, m) <= (yt, mt) and safety < 36:
        safety += 1
        try:
            d = await dashboard_overtime(y, m, company_id=cid)
        except HTTPException:
            d = {"total_overtime_min": 0, "total_paid_brl": 0.0, "rows": []}
        last_day = calendar.monthrange(y, m)[1]
        is_current = (y == cur_y and m == cur_m)
        if is_current:
            ratio = last_day / max(cur_d, 1)
            projected_min = round(d["total_overtime_min"] * ratio)
            projected_brl = round(d["total_paid_brl"] * ratio, 2)
        else:
            projected_min = d["total_overtime_min"]
            projected_brl = d["total_paid_brl"]
        series.append({
            "year": y, "month": m, "label": f"{m:02d}/{y}",
            "total_overtime_min": d["total_overtime_min"],
            "total_paid_brl": d["total_paid_brl"],
            "projected_overtime_min": projected_min,
            "projected_paid_brl": projected_brl,
            "is_current": is_current,
        })
        m += 1
        if m > 12:
            m = 1
            y += 1

    last_in_range = series[-1] if series else None
    debit = []
    if last_in_range:
        try:
            d_last = await dashboard_overtime(last_in_range["year"], last_in_range["month"], company_id=cid)
            debit = sorted(
                [r for r in d_last["rows"] if r["balance_min"] < 0],
                key=lambda r: r["balance_min"],
            )[:5]
        except HTTPException:
            debit = []

    return {
        "mode": mode if mode in ("monthly", "accumulated") else "monthly",
        "year_from": yf, "month_from": mf, "year_to": yt, "month_to": mt,
        "series": series,
        "top_debit": debit,
    }


@router.get("/dwell-heatmap")
async def dwell_heatmap(year: int, month: int, user: dict = Depends(get_current_user)):
    """Consolida horas paradas por praça/cerca em um mês."""
    if month < 1 or month > 12 or year < 2000:
        raise HTTPException(400, "Período inválido")
    cid = _tenant_cid(user)
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    pq: dict = {} if cid is None else {"company_id": cid}
    pracas = await db.pracas.find(pq, {"_id": 0}).to_list(2000)
    praca_by_id = {p["id"]: p for p in pracas}
    fq: dict = {"active": True} if cid is None else {"active": True, "company_id": cid}
    fences = await db.geofences.find(fq, {"_id": 0}).to_list(5000)

    def _nearest_praca(lat: float, lng: float) -> Optional[str]:
        best_pid, best_d = None, None
        for f in fences:
            d = haversine_m(lat, lng, f["lat"], f["lng"])
            if d <= max(250.0, float(f.get("radius", 50)) + 50):
                if best_d is None or d < best_d:
                    best_d = d
                    pid = None
                    for p in pracas:
                        if p.get("name") and f.get("name") and p["name"].lower() == f["name"].lower():
                            pid = p["id"]
                            break
                    best_pid = pid
        if best_pid is None:
            for p in pracas:
                if p.get("lat") and p.get("lng"):
                    d = haversine_m(lat, lng, float(p["lat"]), float(p["lng"]))
                    if d <= 5000 and (best_d is None or d < best_d):
                        best_d, best_pid = d, p["id"]
        return best_pid

    cq: dict = {} if cid is None else {"company_id": cid}
    colls = await db.collaborators.find(cq, {"_id": 0, "id": 1, "name": 1, "praca_id": 1}).to_list(5000)
    by_praca: dict[str, dict] = {}
    by_day = [0] * (last_day + 1)
    for c in colls:
        track = await db.location_logs.find(
            {"collaborator_id": c["id"], "recorded_at": {"$gte": start, "$lte": end}},
            {"_id": 0, "lat": 1, "lng": 1, "recorded_at": 1},
        ).sort("recorded_at", 1).to_list(50000)
        if not track:
            continue
        stays = build_stay_clusters(track, radius_m=80.0, min_dur_min=30)
        for s in stays:
            if not s["is_alert"]:
                continue
            pid = _nearest_praca(s["center_lat"], s["center_lng"]) or c.get("praca_id") or "sem_praca"
            pname = (praca_by_id.get(pid) or {}).get("name") or "Sem praça"
            slot = by_praca.setdefault(pid, {
                "praca_id": pid, "praca_name": pname,
                "total_minutes": 0, "stays": 0,
                "by_collab": {},
            })
            slot["total_minutes"] += s["duration_min"]
            slot["stays"] += 1
            cb = slot["by_collab"].setdefault(c["id"], {"name": c["name"], "minutes": 0, "stays": 0})
            cb["minutes"] += s["duration_min"]
            cb["stays"] += 1
            try:
                day = datetime.fromisoformat(s["start"].replace("Z", "+00:00")).day
                if 1 <= day <= last_day:
                    by_day[day] += s["duration_min"]
            except Exception:
                pass

    rows = []
    for slot in by_praca.values():
        slot["by_collab"] = sorted(
            [{"collaborator_id": k, **v} for k, v in slot["by_collab"].items()],
            key=lambda x: x["minutes"], reverse=True,
        )
        rows.append(slot)
    rows.sort(key=lambda r: r["total_minutes"], reverse=True)

    return {
        "year": year, "month": month, "last_day": last_day,
        "rows": rows,
        "by_day": [{"day": i, "minutes": by_day[i]} for i in range(1, last_day + 1)],
        "total_minutes": sum(r["total_minutes"] for r in rows),
    }


@router.get("/dwell-heatmap/day")
async def dwell_heatmap_day(year: int, month: int, day: int, user: dict = Depends(get_current_user)):
    """Lista todas as estadias (>= 30 min) ocorridas em um dia específico,
    com colaborador, praça aproximada, horários e centro do cluster.
    Pensado para o drill-down do heatmap."""
    if month < 1 or month > 12 or year < 2000 or day < 1 or day > 31:
        raise HTTPException(400, "Período inválido")
    cid = _tenant_cid(user)
    last_day = calendar.monthrange(year, month)[1]
    if day > last_day:
        raise HTTPException(400, "Dia além do mês")
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    day_end = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    pq: dict = {} if cid is None else {"company_id": cid}
    pracas = await db.pracas.find(pq, {"_id": 0}).to_list(2000)
    praca_by_id = {p["id"]: p for p in pracas}
    fq: dict = {"active": True} if cid is None else {"active": True, "company_id": cid}
    fences = await db.geofences.find(fq, {"_id": 0}).to_list(5000)

    def _nearest_praca(lat: float, lng: float) -> Optional[str]:
        best_pid, best_d = None, None
        for f in fences:
            d = haversine_m(lat, lng, f["lat"], f["lng"])
            if d <= max(250.0, float(f.get("radius", 50)) + 50):
                if best_d is None or d < best_d:
                    best_d = d
                    pid = None
                    for p in pracas:
                        if p.get("name") and f.get("name") and p["name"].lower() == f["name"].lower():
                            pid = p["id"]
                            break
                    best_pid = pid
        if best_pid is None:
            for p in pracas:
                if p.get("lat") and p.get("lng"):
                    d = haversine_m(lat, lng, float(p["lat"]), float(p["lng"]))
                    if d <= 5000 and (best_d is None or d < best_d):
                        best_d, best_pid = d, p["id"]
        return best_pid

    cq: dict = {} if cid is None else {"company_id": cid}
    colls = await db.collaborators.find(cq, {"_id": 0, "id": 1, "name": 1, "praca_id": 1, "avatar_data_url": 1}).to_list(5000)
    out_stays: list[dict] = []
    for c in colls:
        track = await db.location_logs.find(
            {"collaborator_id": c["id"], "recorded_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0, "lat": 1, "lng": 1, "recorded_at": 1},
        ).sort("recorded_at", 1).to_list(50000)
        if not track:
            continue
        stays = build_stay_clusters(track, radius_m=80.0, min_dur_min=30)
        for s in stays:
            if not s["is_alert"]:
                continue
            pid = _nearest_praca(s["center_lat"], s["center_lng"]) or c.get("praca_id") or "sem_praca"
            pname = (praca_by_id.get(pid) or {}).get("name") or "Sem praça"
            out_stays.append({
                "collaborator_id": c["id"],
                "collaborator_name": c["name"],
                "praca_id": pid,
                "praca_name": pname,
                "center_lat": s["center_lat"],
                "center_lng": s["center_lng"],
                "start": s["start"],
                "end": s["end"],
                "duration_min": s["duration_min"],
                "points": s["points"],
            })
    out_stays.sort(key=lambda x: x["duration_min"], reverse=True)
    total = sum(s["duration_min"] for s in out_stays)
    return {
        "year": year, "month": month, "day": day,
        "total_minutes": total,
        "stays": out_stays,
    }
