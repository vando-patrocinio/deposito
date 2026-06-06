"""Ranking de clientes mais antigos — para campanhas/promoções de fidelidade.

Endpoint admin-only que retorna os top N clientes ordenados por tempo de
contrato (`installation_date` ASC). Útil pra criar campanhas de fidelidade,
promoções VIP, brindes, etc.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db

router = APIRouter(prefix="/api", tags=["customer-loyalty"])


def _is_valid_phone(p: Optional[str]) -> bool:
    """Telefone válido: ≥10 dígitos (não conta '55' sozinho como código país)."""
    if not p:
        return False
    d = "".join(c for c in str(p) if c.isdigit())
    if not d or d == "55":
        return False
    if d.startswith("55"):
        return len(d) >= 12  # 55 + DDD + 8/9 dígitos
    return len(d) >= 10  # DDD + 8 dígitos


def _all_valid_phones(*phones) -> list[str]:
    """Retorna lista de telefones válidos da iter — útil pra phone1+2+3."""
    out: list[str] = []
    for p in phones:
        if _is_valid_phone(p):
            out.append(p)
    return out


def _is_valid_cpf_format(cpf: str) -> bool:
    """Filtro mínimo pra rejeitar CPFs placeholder do tipo 00000000000.

    Não valida dígito verificador (Atlaz/XLSX podem ter CNPJ misturado),
    só rejeita strings com 1 dígito repetido (00000…, 99999…)."""
    if not cpf or len(cpf) < 11:
        return False
    return len(set(cpf)) > 1


def _years_since(iso_date: Optional[str]) -> Optional[float]:
    if not iso_date:
        return None
    try:
        d = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        # iter215m — Datas anteriores a 1995 são lixo (epoch 1969-12-31
        # quando timestamp=0). Trata como sem-data pra não bagunçar ranking.
        if d.year < 1995:
            return None
        return round(
            (datetime.now(timezone.utc) - d).days / 365.25, 2)
    except Exception:
        return None


@router.get("/customer/loyalty-ranking")
async def loyalty_ranking(
    limit: int = Query(50, ge=1, le=5000),
    status: str = Query("ATIVO", description="Filtra por status (ou 'all')"),
    filial: Optional[str] = None,
    plan: Optional[str] = None,
    min_years: float = Query(0.0, ge=0.0),
    only_returned: bool = Query(False, description="Só clientes que voltaram"),
    user: dict = Depends(require_role("gestor")),
):
    """Retorna ranking dos clientes mais antigos (cliente há mais tempo).

    Ordena por `tenure_years` DESC. Inclui também clientes SEM data de
    instalação (Atlaz não fornece) — esses ficam no fim do ranking com
    `tenure_years=null`. Útil pra ver TODOS os clientes em um só painel."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # iter215f — Atlaz não retorna data de instalação. Não filtramos mais
    # por installation_date pra mostrar TODOS os clientes do tenant.
    # iter215m — Exclui clientes marcados com tag `loyalty_hidden`
    # (dados corrompidos no Atlaz, usuário removeu manualmente).
    q: dict = {"company_id": cid, "tags": {"$ne": "loyalty_hidden"}}
    if status and status != "all":
        q["status"] = status.upper()
    if filial:
        q["$or"] = [
            {"filial_name": filial},
            {"branch_name": filial},
            {"filial": filial},
        ]
    if plan:
        q["plan_name"] = plan

    # iter215f — sem sort no Mongo (vamos ordenar em Python depois) pra
    # não enviesar pelos nulls. Cap em 10k pra performance.
    cursor = db.subscribers.find(
        q,
        {"_id": 0, "id": 1, "name": 1, "document": 1, "phone": 1, "email": 1,
         "pppoe_user": 1, "plan_name": 1, "status": 1, "financial_status": 1,
         "installation_date": 1, "activation_date": 1, "created_at": 1,
         "filial_name": 1, "branch_name": 1, "filial": 1, "branch": 1,
         "tags": 1, "external_code": 1, "addresses": 1},
    ).limit(min(max(limit * 5, 10000), 10000))

    # iter215k — Pré-computa CPF → lista de tenures passados (XLSX
    # desativado). Usado pra somar tempo de casa de clientes que voltaram.
    past_tenures_by_cpf: dict[str, list[float]] = {}
    async for r in db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Desativado",
         "document": {"$nin": [None, ""]}},
        {"_id": 0, "document": 1, "installation_date": 1,
         "activation_date": 1, "registration_date": 1,
         "cancellation_date": 1},
    ):
        cpf = (r.get("document") or "").strip()
        if not _is_valid_cpf_format(cpf):
            continue
        inst = (r.get("installation_date") or r.get("activation_date")
                or r.get("registration_date"))
        cancel = r.get("cancellation_date")
        if not (inst and cancel):
            continue
        try:
            d1 = datetime.fromisoformat(inst.replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(cancel.replace("Z", "+00:00"))
            if d1.tzinfo is None:
                d1 = d1.replace(tzinfo=timezone.utc)
            if d2.tzinfo is None:
                d2 = d2.replace(tzinfo=timezone.utc)
            years = (d2 - d1).days / 365.25
            if 0 < years < 60:  # ignora datas absurdas
                past_tenures_by_cpf.setdefault(cpf, []).append(round(years, 2))
        except Exception:
            continue

    # iter215 — Detecta CPFs duplicados (cliente que cancelou e retornou)
    # ANTES de aplicar limit. Soma os tenures em um único ranking.
    by_cpf: dict[str, list[dict]] = {}
    raw_items: list[dict] = []
    async for row in cursor:
        years = _years_since(row.get("installation_date"))
        # iter215f — só aplica min_years quando o tempo é conhecido.
        # Se min_years > 0 e o cliente não tem data, pula (não dá pra validar).
        if min_years > 0 and (years is None or years < min_years):
            continue
        plan = (row.get("plan_name") or "").strip()
        if not plan:
            # Tenta extrair do label do primeiro endereço (Atlaz import)
            ads = row.get("addresses") or []
            if ads and isinstance(ads, list) and ads[0].get("label"):
                plan = ads[0]["label"].strip().lstrip("#").strip()
        # Skip planos 0800 (regra de negócio iter215)
        if "0800" in plan.upper():
            continue
        cpf = (row.get("document") or "").strip()
        item = {
            "id": row["id"],
            "name": row.get("name") or "",
            "document": cpf,
            "phone": row.get("phone") or "",
            "email": row.get("email") or "",
            "pppoe_user": row.get("pppoe_user") or "",
            "plan_name": plan or "—",
            "status": row.get("status") or "",
            "financial_status": row.get("financial_status") or "",
            "filial": (row.get("filial_name") or row.get("branch_name")
                          or row.get("filial") or row.get("branch") or ""),
            "external_code": row.get("external_code") or "",
            "installation_date": row.get("installation_date"),
            "tenure_years": years,
            "tags": row.get("tags") or [],
        }
        raw_items.append(item)
        if cpf:
            by_cpf.setdefault(cpf, []).append(item)

    # Mescla CPFs duplicados — soma de tenures, marca como "returned"
    seen_cpfs: set[str] = set()
    merged: list[dict] = []
    for it in raw_items:
        cpf = it["document"]
        # iter215k — Soma tenures passados (XLSX desativado) se existirem
        past_yrs = past_tenures_by_cpf.get(cpf, []) if cpf else []
        past_total = sum(past_yrs) if past_yrs else 0.0
        past_count = len(past_yrs)

        if cpf and len(by_cpf.get(cpf, [])) > 1:
            if cpf in seen_cpfs:
                continue
            seen_cpfs.add(cpf)
            group = by_cpf[cpf]
            # iter215f — soma só os tenures válidos
            valid_tenures = [g["tenure_years"] for g in group
                              if g["tenure_years"] is not None]
            total_years = sum(valid_tenures) if valid_tenures else None
            if total_years is not None:
                total_years += past_total
            elif past_total > 0:
                total_years = past_total
            # Usa o registro com mais tempo individual como "principal"
            primary = max(group, key=lambda g: g.get("tenure_years") or -1)
            merged.append({
                **primary,
                "tenure_years": (round(total_years, 2)
                                  if total_years is not None else None),
                "returned": True,
                "returned_count": len(group) + past_count,
                "past_tenure_years": round(past_total, 2) if past_total else 0,
                "is_vip": (total_years or 0) >= 5,
            })
        else:
            current = it["tenure_years"] or 0
            combined = current + past_total
            if past_count > 0:
                merged.append({
                    **it,
                    "tenure_years": round(combined, 2) if combined > 0 else None,
                    "returned": True,
                    "returned_count": past_count + 1,
                    "past_tenure_years": round(past_total, 2),
                    "is_vip": combined >= 5,
                })
            else:
                merged.append({**it, "returned": False,
                                "past_tenure_years": 0,
                                "is_vip": current >= 5})

    # iter215f — Ordena por tenure desc; clientes SEM data vão pro fim,
    # ordenados alfabeticamente. Aplica limit no fim.
    merged.sort(key=lambda x: (
        0 if x["tenure_years"] is not None else 1,   # com tempo primeiro
        -(x["tenure_years"] or 0),                    # tempo desc
        (x.get("name") or "").lower(),                # sem tempo: alfabético
    ))
    if only_returned:
        merged = [m for m in merged if m.get("returned")]
    items = merged[:limit]
    for idx, it in enumerate(items, 1):
        it["rank"] = idx
    return {
        "items": items,
        "count": len(items),
        "total_available": len(merged),
        "without_install_date": sum(
            1 for i in merged if i["tenure_years"] is None),
        "vip_count": sum(1 for i in items if i["is_vip"]),
        "returned_count": sum(1 for i in items if i.get("returned")),
    }


# ---------------------------------------------------------------------------
# iter215k — Clientes retornados: aparecem ATIVOS hoje mas têm 1+ cadastros
# desativados anteriores (descobertos via XLSX import). Útil pra:
#  - Aba "Análise de Churn" → card de winback realizado
#  - Ranking → badge 🔄
#  - Marketing: comparar com "novos clientes" (LTV maior)
# ---------------------------------------------------------------------------
@router.get("/customer/returned-clients")
async def returned_clients(
    limit: int = Query(500, ge=1, le=5000),
    user: dict = Depends(require_role("gestor")),
):
    """Lista clientes que aparecem ATIVOS hoje E ao mesmo tempo possuem
    1+ cadastros DESATIVADOS antigos no XLSX (mesmo CPF).

    Returns:
        items: [{document, name, current_plan, current_activation, ...
                 past_count, past_total_years, past_records:[...]}]
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # 1) CPFs ativos hoje (XLSX)
    ativos_cpfs: dict[str, dict] = {}
    async for r in db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Ativo",
         "document": {"$nin": [None, ""]}},
        {"_id": 0},
    ):
        cpf = (r.get("document") or "").strip()
        if _is_valid_cpf_format(cpf):
            ativos_cpfs[cpf] = r

    # 2) Cadastros desativados desses CPFs
    desativados_por_cpf: dict[str, list[dict]] = {}
    async for r in db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Desativado",
         "document": {"$in": list(ativos_cpfs.keys())}},
        {"_id": 0},
    ):
        cpf = (r.get("document") or "").strip()
        if cpf:
            desativados_por_cpf.setdefault(cpf, []).append(r)

    # 3) Monta resposta com tenure consolidado
    items: list[dict] = []
    for cpf, active in ativos_cpfs.items():
        past = desativados_por_cpf.get(cpf, [])
        if not past:
            continue
        # Soma tenures válidos
        past_years_total = 0.0
        past_records = []
        for p in past:
            inst = (p.get("installation_date") or p.get("activation_date")
                    or p.get("registration_date"))
            cancel = p.get("cancellation_date")
            yrs = None
            if inst and cancel:
                try:
                    d1 = datetime.fromisoformat(inst.replace("Z", "+00:00"))
                    d2 = datetime.fromisoformat(cancel.replace("Z", "+00:00"))
                    if d1.tzinfo is None:
                        d1 = d1.replace(tzinfo=timezone.utc)
                    if d2.tzinfo is None:
                        d2 = d2.replace(tzinfo=timezone.utc)
                    yrs = max(0, (d2 - d1).days / 365.25)
                    if 0 < yrs < 60:
                        past_years_total += yrs
                except Exception:
                    pass
            past_records.append({
                "plan_name": p.get("plan_name") or "",
                "activation_date": p.get("activation_date"),
                "cancellation_date": p.get("cancellation_date"),
                "city": p.get("city") or "",
                "tenure_years": round(yrs, 2) if yrs else None,
            })

        current_inst = (active.get("installation_date")
                         or active.get("activation_date")
                         or active.get("registration_date"))
        current_years = _years_since(current_inst) or 0
        total_loyalty_years = current_years + past_years_total

        items.append({
            "document": cpf,
            "name": active.get("name") or "",
            "phone": active.get("phone1") or "",
            "current_plan": active.get("plan_name") or "",
            "current_monthly_fee": active.get("monthly_fee"),
            "current_activation": active.get("activation_date"),
            "current_city": active.get("city") or "",
            "current_district": active.get("district") or "",
            "current_tenure_years": round(current_years, 2),
            "past_count": len(past),
            "past_total_years": round(past_years_total, 2),
            "total_loyalty_years": round(total_loyalty_years, 2),
            "past_records": past_records,
            "is_vip": total_loyalty_years >= 5,
        })

    # Ordena por tempo total de lealdade (desc)
    items.sort(key=lambda x: -x["total_loyalty_years"])
    truncated = items[:limit]
    return {
        "items": truncated,
        "count": len(truncated),
        "total": len(items),
        "total_active_in_base": len(ativos_cpfs),
        "vip_count": sum(1 for i in truncated if i["is_vip"]),
        "total_past_records": sum(i["past_count"] for i in items),
    }


@router.get("/customer/loyalty-stats")
async def loyalty_stats(user: dict = Depends(require_role("gestor"))):
    """Distribuição agregada por faixa de tempo de cliente (pra cards/charts)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    buckets = {"<1ano": 0, "1-3 anos": 0, "3-5 anos": 0, "5-10 anos": 0,
                  "10+ anos": 0}
    cursor = db.subscribers.find(
        {"company_id": cid, "status": "ATIVO",
         "installation_date": {"$exists": True, "$ne": None}},
        {"_id": 0, "installation_date": 1},
    )
    total = 0
    oldest_years = 0.0
    async for row in cursor:
        y = _years_since(row.get("installation_date"))
        if y is None:
            continue
        total += 1
        if y > oldest_years:
            oldest_years = y
        if y < 1:
            buckets["<1ano"] += 1
        elif y < 3:
            buckets["1-3 anos"] += 1
        elif y < 5:
            buckets["3-5 anos"] += 1
        elif y < 10:
            buckets["5-10 anos"] += 1
        else:
            buckets["10+ anos"] += 1
    vip_total = buckets["5-10 anos"] + buckets["10+ anos"]
    return {
        "buckets": buckets,
        "total_active": total,
        "vip_count": vip_total,
        "vip_pct": round(100 * vip_total / total, 1) if total else 0,
        "oldest_years": round(oldest_years, 1),
    }


_DEACT_CACHE: dict[str, tuple[float, dict]] = {}
_DEACT_TTL_SEC = 180  # 3 minutos


def invalidate_loyalty_caches(company_id: Optional[str] = None) -> dict:
    """Invalida todos os caches do painel Clientes Fidelidade.

    iter215w — Chamado após import XLSX pra garantir que todas as abas
    reflitam os novos dados imediatamente.
    """
    cleared_deact = 0
    if company_id:
        keys = [k for k in _DEACT_CACHE if k.startswith(f"{company_id}::")]
    else:
        keys = list(_DEACT_CACHE.keys())
    for k in keys:
        _DEACT_CACHE.pop(k, None)
        cleared_deact += 1
    return {"deactivated_cache_cleared": cleared_deact}


# ---------------------------------------------------------------------------
# Aba "Desativados" — clientes que cancelaram, agrupados por praça.
# ---------------------------------------------------------------------------
@router.get("/customer/deactivated-list")
async def deactivated_list(
    praca: Optional[str] = None,
    limit: int = Query(100, ge=1, le=10000),
    refresh: bool = Query(False, description="Força recálculo (ignora cache)"),
    user: dict = Depends(require_role("gestor")),
):
    """Lista clientes desativados, agregando 2 fontes.

    iter215v — Cache em memória de 3 minutos por (cid, praca) pra
    performance. O scan de 7k+ docs era recomputado a cada request.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cache_key = f"{cid}::{praca or '*'}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if not refresh:
        cached = _DEACT_CACHE.get(cache_key)
        if cached and (now_ts - cached[0]) < _DEACT_TTL_SEC:
            # Retorna do cache, mas ajusta o limit dinamicamente
            data = cached[1].copy()
            full = data.get("_full_items") or []
            data["items"] = full[:limit]
            data["count"] = len(data["items"])
            data.pop("_full_items", None)
            data["from_cache"] = True
            data["cache_age_sec"] = round(now_ts - cached[0])
            return data
    items: list[dict] = []
    seen_cpfs: set[str] = set()
    now = datetime.now(timezone.utc)

    # iter215n — KPIs de cancelamentos recentes (mesma fonte: XLSX + subs)
    kpi_buckets = {"30": 0, "60": 0, "90": 0, "120": 0, "365": 0}
    # iter215o — KPIs por mês de calendário (jun/26, mai/26, abr/26, mar/26)
    # e por trimestre (2º trim 26 = Abr+Mai+Jun)
    month_counts: dict[str, int] = {}  # "YYYY-MM" → count
    quarter_counts: dict[str, int] = {}  # "YYYY-Qn" → count
    # iter215n — Contagem REAL por praça (ignora limit)
    real_by_praca: dict[str, int] = {}
    # iter215r — Contagens de telefones (qualidade do contato)
    total_real = 0
    total_with_phone = 0  # com phone1 válido
    total_no_phone = 0   # sem nenhum phone válido

    def _bucket_days(days: Optional[int], cancel_dt: Optional[datetime]) -> None:
        if days is None or days < 0:
            return
        if days <= 30:
            kpi_buckets["30"] += 1
        if days <= 60:
            kpi_buckets["60"] += 1
        if days <= 90:
            kpi_buckets["90"] += 1
        if days <= 120:
            kpi_buckets["120"] += 1
        if days <= 365:
            kpi_buckets["365"] += 1
        # Calendar month + quarter
        if cancel_dt:
            ym = cancel_dt.strftime("%Y-%m")
            month_counts[ym] = month_counts.get(ym, 0) + 1
            q = (cancel_dt.month - 1) // 3 + 1
            yq = f"{cancel_dt.year}-Q{q}"
            quarter_counts[yq] = quarter_counts.get(yq, 0) + 1

    # === Fonte 1: subscribers desativados ====================================
    q_sub: dict = {"company_id": cid, "status": {"$nin": ["ATIVO", "ATIVA"]}}
    if praca:
        q_sub["$or"] = [{"filial_name": praca}, {"branch_name": praca},
                          {"filial": praca}, {"branch": praca}]
    cursor = db.subscribers.find(
        q_sub,
        {"_id": 0, "id": 1, "name": 1, "document": 1, "phone": 1, "email": 1,
         "pppoe_user": 1, "plan_name": 1, "status": 1,
         "installation_date": 1, "deactivation_date": 1,
         "cancellation_reason": 1, "filial_name": 1, "branch_name": 1,
         "filial": 1, "branch": 1, "external_code": 1, "addresses": 1},
    ).sort("deactivation_date", -1)
    async for row in cursor:
        plan = (row.get("plan_name") or "").strip()
        if not plan:
            ads = row.get("addresses") or []
            if ads and isinstance(ads, list) and ads[0].get("label"):
                plan = ads[0]["label"].strip().lstrip("#").strip()
        if "0800" in plan.upper():
            continue
        pr = (row.get("filial_name") or row.get("branch_name")
              or row.get("filial") or row.get("branch") or "—")
        cpf = (row.get("document") or "").strip()
        if cpf:
            seen_cpfs.add(cpf)
        real_by_praca[pr] = real_by_praca.get(pr, 0) + 1
        total_real += 1
        if _is_valid_phone(row.get("phone")):
            total_with_phone += 1
        else:
            total_no_phone += 1
        # Days since cancel pro KPI
        ds_cancel = None
        cancel_dt = None
        if row.get("deactivation_date"):
            try:
                cancel_dt = datetime.fromisoformat(
                    row["deactivation_date"].replace("Z", "+00:00"))
                if cancel_dt.tzinfo is None:
                    cancel_dt = cancel_dt.replace(tzinfo=timezone.utc)
                ds_cancel = (now - cancel_dt).days
                _bucket_days(ds_cancel, cancel_dt)
            except Exception:
                pass
        # iter215v — buffer fixo de até 10k pra cachear, slice no retorno
        if len(items) < 10000:
            tenure = _years_since(row.get("installation_date"))
            items.append({
                "id": row["id"],
                "name": row.get("name") or "",
                "document": cpf, "phone": row.get("phone") or "",
                "has_valid_phone": _is_valid_phone(row.get("phone")),
                "pppoe_user": row.get("pppoe_user") or "",
                "plan_name": plan or "—",
                "status": row.get("status") or "",
                "filial": pr,
                "external_code": row.get("external_code") or "",
                "installation_date": row.get("installation_date"),
                "deactivation_date": row.get("deactivation_date"),
                "cancellation_reason": row.get("cancellation_reason") or "",
                "tenure_years_before_cancel": tenure,
                "days_since_cancel": ds_cancel,
                "source": "subscribers",
            })

    # === Fonte 2: loyalty_imported_db Desativado ============================
    q_imp: dict = {"company_id": cid, "status": "Desativado"}
    if praca:
        q_imp["city"] = praca
    cursor2 = db.loyalty_imported_db.find(
        q_imp,
        {"_id": 0, "name": 1, "document": 1, "phone1": 1,
         "phone2": 1, "phone3": 1, "login": 1, "email": 1,
         "plan_name": 1, "status": 1, "installation_date": 1,
         "activation_date": 1, "registration_date": 1,
         "cancellation_date": 1, "city": 1, "district": 1,
         "monthly_fee": 1, "external_id": 1,
         "invoices_paid": 1, "invoices_overdue": 1,
         "tickets_open": 1, "tickets_closed": 1, "total_overdue": 1},
    ).sort("cancellation_date", -1)
    async for r in cursor2:
        cpf = (r.get("document") or "").strip()
        if not cpf or cpf in seen_cpfs:
            continue
        seen_cpfs.add(cpf)
        plan = (r.get("plan_name") or "").strip()
        if "0800" in plan.upper():
            continue
        pr = (r.get("city") or "—").strip()
        real_by_praca[pr] = real_by_praca.get(pr, 0) + 1
        total_real += 1
        # iter215t — agora consideramos qualquer phone1/2/3 válido
        valid_phones = _all_valid_phones(r.get("phone1"), r.get("phone2"),
                                              r.get("phone3"))
        if valid_phones:
            total_with_phone += 1
        else:
            total_no_phone += 1
        # KPI bucket
        days_since = None
        cancel_dt = None
        if r.get("cancellation_date"):
            try:
                cancel_dt = datetime.fromisoformat(
                    r["cancellation_date"].replace("Z", "+00:00"))
                if cancel_dt.tzinfo is None:
                    cancel_dt = cancel_dt.replace(tzinfo=timezone.utc)
                days_since = (now - cancel_dt).days
                _bucket_days(days_since, cancel_dt)
            except Exception:
                pass
        # iter215v — buffer fixo de até 10k pra cachear, slice no retorno
        if len(items) < 10000:
            best_install = (r.get("installation_date")
                             or r.get("activation_date")
                             or r.get("registration_date"))
            tenure_yrs = None
            if best_install and r.get("cancellation_date"):
                try:
                    a = datetime.fromisoformat(
                        best_install.replace("Z", "+00:00"))
                    b = datetime.fromisoformat(
                        r["cancellation_date"].replace("Z", "+00:00"))
                    if a.tzinfo is None:
                        a = a.replace(tzinfo=timezone.utc)
                    if b.tzinfo is None:
                        b = b.replace(tzinfo=timezone.utc)
                    tenure_yrs = round((b - a).days / 365.25, 2)
                except Exception:
                    pass
            items.append({
                "id": f"imp-{cpf}",
                "name": r.get("name") or "",
                "document": cpf,
                "phone": valid_phones[0] if valid_phones else "",
                "phones": valid_phones,  # iter215t — lista completa
                "has_valid_phone": bool(valid_phones),
                "email": r.get("email") or "",
                "pppoe_user": r.get("login") or "",
                "plan_name": plan or "—",
                "status": "INATIVO",
                "filial": pr,
                "external_code": (f"XLSX-{r.get('external_id')}"
                                    if r.get("external_id") else ""),
                "installation_date": best_install,
                "deactivation_date": r.get("cancellation_date"),
                "cancellation_reason": "",
                "tenure_years_before_cancel": tenure_yrs,
                "days_since_cancel": days_since,
                # iter215t — métricas de relacionamento
                "invoices_paid": r.get("invoices_paid") or 0,
                "invoices_overdue": r.get("invoices_overdue") or 0,
                "tickets_open": r.get("tickets_open") or 0,
                "tickets_closed": r.get("tickets_closed") or 0,
                "total_overdue": r.get("total_overdue") or 0,
                "source": "xlsx",
            })

    # iter215o — Monta KPIs de mês de calendário (atual, -1m, -2m, -3m)
    # com label pt-BR + contagem real desse mês
    MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
                  "jul", "ago", "set", "out", "nov", "dez"]

    def _month_label(year: int, month: int) -> dict:
        return {
            "year": year, "month": month,
            "ym": f"{year}-{month:02d}",
            "label": f"{MONTHS_PT[month - 1].capitalize()}/{str(year)[-2:]}",
            "count": month_counts.get(f"{year}-{month:02d}", 0),
        }

    cur_y, cur_m = now.year, now.month
    months: list[dict] = []
    for back in range(4):  # mês atual, -1, -2, -3
        y, m = cur_y, cur_m - back
        while m <= 0:
            m += 12
            y -= 1
        months.append(_month_label(y, m))

    cur_q = (cur_m - 1) // 3 + 1
    quarter_key = f"{cur_y}-Q{cur_q}"
    quarter_months_pt = MONTHS_PT[(cur_q - 1) * 3: cur_q * 3]
    quarter_label = (f"{cur_q}º Trim/{str(cur_y)[-2:]} "
                      f"({'-'.join(m.capitalize() for m in quarter_months_pt)})")
    quarter_count = quarter_counts.get(quarter_key, 0)

    # iter215v — Salva no cache (com lista COMPLETA) e retorna sliced
    result = {
        "items": items[:limit],
        "count": min(limit, len(items)),
        "total_count": total_real,
        # iter215r — qualidade do contato
        "total_with_phone": total_with_phone,
        "total_no_phone": total_no_phone,
        "by_praca": [{"praca": k, "count": v}
                       for k, v in sorted(real_by_praca.items(),
                                              key=lambda x: -x[1])],
        "recent_kpis": {
            # Rolling windows (mantido pra compat)
            "last_30d": kpi_buckets["30"],
            "last_60d": kpi_buckets["60"],
            "last_90d": kpi_buckets["90"],
            "last_120d": kpi_buckets["120"],
            "last_365d": kpi_buckets["365"],
            # iter215o — Buckets de calendário
            "current_month": months[0],
            "prev_month": months[1],
            "prev2_month": months[2],
            "prev3_month": months[3],
            "current_quarter": {
                "key": quarter_key, "label": quarter_label,
                "count": quarter_count,
            },
            "monthly_history": [
                {"ym": k, "count": v}
                for k, v in sorted(month_counts.items(), reverse=True)
            ][:13],
        },
        "from_cache": False,
        "cache_age_sec": 0,
    }
    # Cacheia a versão completa pra slicing dinâmico
    cache_copy = {**result, "_full_items": items}
    _DEACT_CACHE[cache_key] = (now_ts, cache_copy)
    # Limpa cache se ficar muito grande (mantém só 10 entradas mais recentes)
    if len(_DEACT_CACHE) > 10:
        sorted_keys = sorted(_DEACT_CACHE.keys(),
                                key=lambda k: _DEACT_CACHE[k][0])
        for k in sorted_keys[:-10]:
            _DEACT_CACHE.pop(k, None)
    return result


# ---------------------------------------------------------------------------
# Aba "Migração de Plano" — identifica oportunidades de upgrade gratuito.
# Compara plano atual (velocidade @ preço) com o melhor disponível hoje
# na mesma região/praça pelo MESMO preço (ou menor).
# ---------------------------------------------------------------------------
import re as _re


def _parse_plan_label(label: str) -> dict:
    """Extrai {region, speed_mbps, price_brl, year} de um label tipo
    'RIO_160MB_89,90_2021' ou 'MAG_500M_C/FIDELIDADE_99,90_2024'."""
    if not label:
        return {}
    upper = label.upper()
    out: dict = {}
    # Velocidade: NNNN seguido de M ou MB/MEGAS, terminado por _ . , * ou fim.
    # iter215 — usa lookahead em vez de \b (que não casa antes de _)
    m = _re.search(r"(\d{2,4})\s*M(?:EGA?S?|B)?(?=[_\s.,*/]|$)", upper)
    if m:
        out["speed_mbps"] = int(m.group(1))
    # Preço: padrão NN,NN ou NN.NN
    p = _re.search(r"(\d{2,3})[,.](\d{2})", upper)
    if p:
        out["price_brl"] = float(f"{p.group(1)}.{p.group(2)}")
    # Ano (2017-2030)
    y = _re.search(r"\b(20[12]\d)\b", upper)
    if y:
        out["year"] = int(y.group(1))
    # Região: primeiros tokens antes de '_NNN M'
    for tok in ["RIO", "MAG", "GUARA", "MAGE", "GUARATINGUETA", "SP", "RJ"]:
        if tok in upper:
            out["region"] = tok
            break
    return out


@router.get("/customer/plan-migration-opportunities")
async def plan_migration_opportunities(
    min_savings_mbps: int = Query(50, ge=10),
    limit: int = Query(200, ge=1, le=2000),
    user: dict = Depends(require_role("gestor")),
):
    """Identifica clientes ATIVOS pagando por planos antigos quando há
    planos NOVOS disponíveis pela MESMA faixa de preço com velocidade maior.

    Estratégia:
    1) Varre TODOS planos ATIVOS (de labels) e monta best-by (region, price)
    2) Pra cada cliente ATIVO, compara: se velocidade atual < best-at-same-price
       e diferença >= min_savings_mbps → marca como oportunidade.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # 1) Coleta todos os labels distintos e parseia
    pipeline = [
        {"$match": {"company_id": cid, "status": "ATIVO",
                       "addresses.0.label": {"$exists": True}}},
        {"$project": {"label": {"$arrayElemAt": ["$addresses.label", 0]}}},
        {"$group": {"_id": "$label", "count": {"$sum": 1}}},
    ]
    label_stats = {}
    async for row in db.subscribers.aggregate(pipeline):
        label_stats[row["_id"]] = row["count"]

    # 2) Indexa best plan por (region, price): velocidade máxima
    best_by_region_price: dict[tuple, dict] = {}
    for lbl, _cnt in label_stats.items():
        info = _parse_plan_label(lbl)
        # Ignora 0800 e labels sem velocidade/preço/região
        if "0800" in (lbl or "").upper():
            continue
        if not all(k in info for k in ("speed_mbps", "price_brl", "region")):
            continue
        # Considera "moderno" se ano >= 2023 (ou sem ano)
        year = info.get("year")
        modern = year is None or year >= 2023
        if not modern:
            continue
        key = (info["region"], info["price_brl"])
        cur = best_by_region_price.get(key)
        if cur is None or info["speed_mbps"] > cur["speed_mbps"]:
            best_by_region_price[key] = {**info, "label": lbl}

    # 3) Para cada cliente ATIVO, compara
    cursor = db.subscribers.find(
        {"company_id": cid, "status": "ATIVO",
         "addresses.0.label": {"$exists": True}},
        {"_id": 0, "id": 1, "name": 1, "document": 1, "phone": 1, "email": 1,
         "pppoe_user": 1, "filial_name": 1, "branch_name": 1, "filial": 1,
         "branch": 1, "external_code": 1, "installation_date": 1,
         "addresses": 1},
    )
    opps: list[dict] = []
    async for row in cursor:
        ads = row.get("addresses") or []
        if not ads:
            continue
        lbl = (ads[0].get("label") or "").strip()
        if not lbl or "0800" in lbl.upper():
            continue
        info = _parse_plan_label(lbl)
        if not all(k in info for k in ("speed_mbps", "price_brl", "region")):
            continue
        key = (info["region"], info["price_brl"])
        best = best_by_region_price.get(key)
        if not best or best["label"] == lbl.lstrip("#").strip():
            continue
        delta = best["speed_mbps"] - info["speed_mbps"]
        if delta < min_savings_mbps:
            continue
        years = _years_since(row.get("installation_date"))
        opps.append({
            "id": row["id"],
            "name": row.get("name") or "",
            "document": row.get("document") or "",
            "phone": row.get("phone") or "",
            "filial": (row.get("filial_name") or row.get("branch_name")
                          or row.get("filial") or row.get("branch") or ""),
            "external_code": row.get("external_code") or "",
            "current_plan": lbl.lstrip("#").strip(),
            "current_speed_mbps": info["speed_mbps"],
            "price_brl": info["price_brl"],
            "current_year": info.get("year"),
            "best_plan": best["label"].lstrip("#").strip(),
            "best_speed_mbps": best["speed_mbps"],
            "delta_mbps": delta,
            "tenure_years": years,
            "is_vip": (years or 0) >= 5,
        })
    # Ordena: VIPs primeiro, depois maior delta
    opps.sort(key=lambda o: (-int(o["is_vip"]), -o["delta_mbps"]))
    return {
        "items": opps[:limit],
        "count": len(opps),
        "vip_count": sum(1 for o in opps if o["is_vip"]),
        "total_savings_mbps": sum(o["delta_mbps"] for o in opps),
    }


# ---------------------------------------------------------------------------
# Análise de Churn — KPIs agregados de clientes desativados.
# Quanto tempo permaneceram ativos? Média? Distribuição? Top motivos?
# ---------------------------------------------------------------------------
@router.get("/customer/churn-kpis")
async def churn_kpis(user: dict = Depends(require_role("gestor"))):
    """KPIs agregados de clientes desativados: tenure médio antes do cancel,
    distribuição em faixas, breakdown por praça e top motivos.

    iter215h — agora une 2 fontes: subscribers (INATIVO) + loyalty_imported_db
    (status=Desativado), dedup por CPF.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Total ativos: subscribers + imported_db
    active_subs = await db.subscribers.count_documents(
        {"company_id": cid, "status": "ATIVO"})
    active_imp = await db.loyalty_imported_db.count_documents(
        {"company_id": cid, "status": "Ativo"})
    active_count = max(active_subs, active_imp)  # evita dupla contagem

    tenures_months: list[float] = []
    by_praca: dict[str, list[float]] = {}
    by_reason: dict[str, int] = {}
    by_plan: dict[str, int] = {}
    buckets = {"<6 meses": 0, "6m-1ano": 0, "1-2 anos": 0,
                  "2-5 anos": 0, "5+ anos": 0}
    seen_cpfs: set[str] = set()
    deact_count = 0

    def _ingest(inst: Optional[str], deact: Optional[str],
                praca: str, reason: str, plan: str) -> None:
        nonlocal deact_count
        deact_count += 1
        tm = None
        if inst and deact:
            try:
                d1 = datetime.fromisoformat(inst.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(deact.replace("Z", "+00:00"))
                if d1.tzinfo is None:
                    d1 = d1.replace(tzinfo=timezone.utc)
                if d2.tzinfo is None:
                    d2 = d2.replace(tzinfo=timezone.utc)
                tm = (d2 - d1).days / 30.4375
            except Exception:
                pass
        if tm is not None and tm >= 0:
            tenures_months.append(tm)
            if tm < 6:
                buckets["<6 meses"] += 1
            elif tm < 12:
                buckets["6m-1ano"] += 1
            elif tm < 24:
                buckets["1-2 anos"] += 1
            elif tm < 60:
                buckets["2-5 anos"] += 1
            else:
                buckets["5+ anos"] += 1
            by_praca.setdefault(praca or "—", []).append(tm)
        by_reason[reason or "Sem motivo informado"] = \
            by_reason.get(reason or "Sem motivo informado", 0) + 1
        if plan:
            by_plan[plan] = by_plan.get(plan, 0) + 1

    # === Fonte 1: subscribers INATIVO ===
    async for row in db.subscribers.find(
        {"company_id": cid, "status": {"$nin": ["ATIVO", "ATIVA"]}},
        {"_id": 0, "document": 1, "installation_date": 1,
         "activation_date": 1, "deactivation_date": 1,
         "cancellation_reason": 1, "filial_name": 1, "branch_name": 1,
         "filial": 1, "branch": 1, "addresses": 1, "plan_name": 1},
    ):
        cpf = (row.get("document") or "").strip()
        if cpf:
            seen_cpfs.add(cpf)
        pr = (row.get("filial_name") or row.get("branch_name")
              or row.get("filial") or row.get("branch") or "—")
        plan = (row.get("plan_name") or "").strip()
        if not plan:
            ads = row.get("addresses") or []
            if ads and isinstance(ads, list) and ads[0].get("label"):
                plan = ads[0]["label"].strip().lstrip("#").strip()
        _ingest(
            row.get("installation_date") or row.get("activation_date"),
            row.get("deactivation_date"),
            pr, row.get("cancellation_reason") or "", plan,
        )

    # === Fonte 2: loyalty_imported_db Desativado (excluindo CPFs já vistos) ===
    async for r in db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Desativado"},
        {"_id": 0, "document": 1, "installation_date": 1,
         "activation_date": 1, "registration_date": 1,
         "cancellation_date": 1, "city": 1, "plan_name": 1},
    ):
        cpf = (r.get("document") or "").strip()
        if not cpf or cpf in seen_cpfs:
            continue
        seen_cpfs.add(cpf)
        inst = (r.get("installation_date") or r.get("activation_date")
                or r.get("registration_date"))
        _ingest(
            inst, r.get("cancellation_date"),
            r.get("city") or "—", "",
            (r.get("plan_name") or "").strip().lstrip("#").strip(),
        )

    avg = round(sum(tenures_months) / len(tenures_months), 1) \
        if tenures_months else 0
    sorted_t = sorted(tenures_months)
    median = (round(sorted_t[len(sorted_t) // 2], 1)
              if sorted_t else 0)
    total = active_count + deact_count
    churn_rate = round(100 * deact_count / total, 2) if total else 0

    return {
        "total_deactivated": deact_count,
        "total_active": active_count,
        "churn_rate_pct": churn_rate,
        "avg_tenure_months_before_cancel": avg,
        "median_tenure_months": median,
        "avg_tenure_years": round(avg / 12, 1),
        "buckets": buckets,
        "by_praca": [
            {"praca": k, "count": len(v),
             "avg_months": round(sum(v) / len(v), 1)}
            for k, v in sorted(by_praca.items(),
                                  key=lambda x: -len(x[1]))
        ],
        "top_reasons": [
            {"reason": k, "count": v}
            for k, v in sorted(by_reason.items(),
                                  key=lambda x: -x[1])[:10]
        ],
        # iter215h — top planos cancelados (revela vulnerabilidades)
        "top_plans_lost": [
            {"plan": k, "count": v}
            for k, v in sorted(by_plan.items(),
                                  key=lambda x: -x[1])[:15]
        ],
    }
