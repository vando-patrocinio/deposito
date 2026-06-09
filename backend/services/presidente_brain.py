"""
presidente_brain.py — Cérebro executivo V12+V13+V14.

V12 — Causality Engine
V13 — Digital Twin Empresarial
V14 — Autopilot Simulation (top 10 decisões)

100% reuso. Nada cria coleção persistente nova (apenas leitura).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


# ═════════════════════════════════════════════════════
#  V12 — CAUSALITY ENGINE
# ═════════════════════════════════════════════════════
# Por categoria: qual snapshot field é o efeito esperado, e qual o
# sentido (max=ganho, min=redução).
CATEGORY_EFFECT = {
    "REAJUSTE_IPCA": ("mrr_brl", "max", "Aumento de MRR recorrente"),
    "DISPARO_COBRANCA":
        ("dinheiro_em_risco_brl", "min",
            "Redução de receita em risco por inadimplência"),
    "CONTATO_LEO_PROATIVO":
        ("churn_previsto_30d_brl", "min",
            "Redução de churn previsto 30d"),
    "CAMPANHA_RETENCAO":
        ("churn_previsto_30d_brl", "min",
            "Redução de churn previsto 30d"),
    "CRIACAO_OS_SMARTFIELD":
        ("dinheiro_em_risco_brl", "min",
            "Redução de risco por degradação de sinal"),
}


async def _competing_actions(action: Dict) -> List[Dict]:
    """Outras ações concluídas que se sobrepõem no tempo desta."""
    started = action.get("executed_at")
    finished = action.get("completed_at")
    if not (started and finished):
        return []
    q = {
        "company_id": action["company_id"],
        "kind": "presidential",
        "id": {"$ne": action["id"]},
        "status": "completed",
        "executed_at": {"$lte": finished},
        "completed_at": {"$gte": started},
    }
    cur = db.motor_ia_actions.find(
        q, {"_id": 0, "id": 1, "categoria": 1,
             "roi_brl": 1, "completed_at": 1}).limit(20)
    return await cur.to_list(20)


async def _historic_taxa_acerto(company_id: str,
                                     categoria: str) -> float:
    """Lê taxa_acerto histórica da categoria em motor_ia_drift."""
    d = await db.motor_ia_drift.find_one(
        {"company_id": company_id, "categoria": categoria},
        {"_id": 0, "taxa_acerto": 1, "amostras": 1})
    if not d:
        return 0.5
    base = float(d.get("taxa_acerto") or 0)
    # mais amostras → mais confiável
    n = int(d.get("amostras") or 0)
    weight = min(n / 10.0, 1.0)
    return base * weight + 0.5 * (1 - weight)


async def causality_for_action(action_id: str) -> Dict[str, Any]:
    """Calcula atribuição causal para 1 ação executada."""
    act = await db.motor_ia_actions.find_one(
        {"id": action_id}, {"_id": 0})
    if not act:
        raise ValueError(f"ação {action_id} não encontrada")
    if act.get("status") != "completed":
        return {
            "action_id": action_id, "categoria": act.get("categoria"),
            "status": act.get("status"),
            "causality_score": 0,
            "msg": "ação ainda não completed — sem atribuição causal",
        }
    bef = (await db.motor_ia_kpis.find_one(
        {"id": act.get("snapshot_before_id")}, {"_id": 0})
        if act.get("snapshot_before_id") else None)
    aft = (await db.motor_ia_kpis.find_one(
        {"id": act.get("snapshot_after_id")}, {"_id": 0})
        if act.get("snapshot_after_id") else None)
    if not (bef and aft):
        return {
            "action_id": action_id, "categoria": act.get("categoria"),
            "causality_score": 0,
            "msg": "snapshots before/after ausentes",
        }
    cat = act.get("categoria")
    if cat not in CATEGORY_EFFECT:
        return {"action_id": action_id, "categoria": cat,
                  "causality_score": 0,
                  "msg": "categoria sem regra causal cadastrada"}
    field, direction, descricao = CATEGORY_EFFECT[cat]
    b_val = float(bef["metrics"].get(field) or 0)
    a_val = float(aft["metrics"].get(field) or 0)
    impacto_esperado = float(act.get("impacto_estimado_brl") or 0)
    if direction == "max":
        impacto_real = a_val - b_val
    else:
        impacto_real = b_val - a_val

    interval_min = 0.0
    if act.get("executed_at") and act.get("completed_at"):
        ex = datetime.fromisoformat(act["executed_at"])
        co = datetime.fromisoformat(act["completed_at"])
        interval_min = round((co - ex).total_seconds() / 60.0, 2)

    competing = await _competing_actions(act)
    acerto_hist = await _historic_taxa_acerto(
        act["company_id"], cat)

    # confiança causal — 4 fatores
    f_sinal = 0
    if impacto_esperado > 0 and impacto_real != 0:
        ratio = impacto_real / impacto_esperado
        # ratio ideal ~1.0 → confiança máxima; muito menor ou negativo
        # → baixa
        f_sinal = max(0.0, min(1.0, 1.0 - abs(1.0 - ratio)))
    f_isolamento = (1.0 / (1 + len(competing)))  # menos concorrentes
                                                     # → mais isolado
    f_historico = acerto_hist
    f_temporal = 1.0 if interval_min <= 60 else (0.7 if interval_min
                                                        <= 1440
                                                        else 0.3)
    score = round(
        100 * (f_sinal * 0.40 + f_isolamento * 0.20
                + f_historico * 0.25 + f_temporal * 0.15), 1)

    causa_mais_provavel = cat if score >= 50 else (
        "INCONCLUSIVO_VARIAVEIS_CONCORRENTES" if competing
        else "INCONCLUSIVO_SINAL_FRACO")

    return {
        "action_id": action_id,
        "categoria": cat,
        "descricao_efeito": descricao,
        "field_observado": field,
        "valor_antes": round(b_val, 2),
        "valor_depois": round(a_val, 2),
        "impacto_esperado_brl": round(impacto_esperado, 2),
        "impacto_real_brl": round(impacto_real, 2),
        "intervalo_minutos": interval_min,
        "variaveis_concorrentes": competing,
        "fatores": {
            "sinal": round(f_sinal, 3),
            "isolamento": round(f_isolamento, 3),
            "historico_acerto": round(f_historico, 3),
            "temporalidade": round(f_temporal, 3),
        },
        "causality_score": score,
        "causa_mais_provavel": causa_mais_provavel,
        "veredicto": (
            "CAUSA_FORTE" if score >= 80
            else "CAUSA_PROVAVEL" if score >= 60
            else "CAUSA_FRACA" if score >= 40
            else "INDETERMINADO"),
    }


async def causality_summary_30d(company_id: str) -> Dict[str, Any]:
    cutoff = _iso(_now() - timedelta(days=30))
    cur = db.motor_ia_actions.find(
        {"company_id": company_id, "kind": "presidential",
         "status": "completed",
         "completed_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "categoria": 1}).limit(100)
    rows = await cur.to_list(100)
    out = []
    by_cat: Dict[str, List[float]] = {}
    for r in rows:
        c = await causality_for_action(r["id"])
        out.append(c)
        by_cat.setdefault(c["categoria"], []).append(
            c["causality_score"])
    agg = []
    for cat, scores in by_cat.items():
        agg.append({
            "categoria": cat, "amostras": len(scores),
            "score_medio": round(sum(scores) / len(scores), 1),
        })
    agg.sort(key=lambda x: x["score_medio"], reverse=True)
    return {"company_id": company_id,
            "periodo_dias": 30,
            "acoes_analisadas": len(out),
            "por_acao": out,
            "por_categoria": agg}


# ═════════════════════════════════════════════════════
#  V13 — DIGITAL TWIN EMPRESARIAL
# ═════════════════════════════════════════════════════
async def digital_twin_subscriber(
        subscriber_id: str) -> Dict[str, Any]:
    """Retorna o grafo completo de um cliente."""
    sub = await db.subscribers.find_one(
        {"$or": [{"id": subscriber_id},
                  {"external_id": subscriber_id}]},
        {"_id": 0})
    if not sub:
        raise ValueError(f"cliente {subscriber_id} não encontrado")

    cid = sub.get("company_id")
    sid = sub.get("id")

    # ONU + sinal
    onu = await db.smartolt_onus.find_one(
        {"$or": [{"subscriber_id": sid},
                  {"customer_id": sid},
                  {"external_id": subscriber_id}]},
        {"_id": 0, "id": 1, "name": 1, "signal_text": 1,
         "signal_1310": 1, "signal_1490": 1, "status": 1,
         "olt_name": 1, "zone_name": 1, "pon": 1})

    # CTO
    cto = None
    if sub.get("cto_id"):
        cto = await db.ctos.find_one(
            {"id": sub["cto_id"]},
            {"_id": 0, "id": 1, "name": 1, "address": 1,
             "ports_used": 1, "ports_total": 1})

    # Técnico que instalou (smart_installs)
    install = await db.smart_installs.find_one(
        {"subscriber_id": sid}, {"_id": 0, "technician": 1,
                                    "technician_id": 1,
                                    "installed_at": 1, "result": 1})

    # Tickets
    tickets_cur = db.tickets.find(
        {"subscriber_id": sid}, {"_id": 0, "id": 1, "status": 1,
                                  "title": 1, "created_at": 1,
                                  "closed_at": 1}).sort(
                                      [("created_at", -1)]).limit(20)
    tickets = await tickets_cur.to_list(20)
    tickets_open = sum(1 for t in tickets
                          if t.get("status") in ("pendente",
                                                  "aberta", "open"))

    # Financeiro
    invoices_cur = db.subscriber_invoices.find(
        {"subscriber_id": sid}, {"_id": 0, "id": 1, "due_date": 1,
                                  "amount": 1, "paid_at": 1,
                                  "status": 1}).sort(
                                      [("due_date", -1)]).limit(24)
    invoices = await invoices_cur.to_list(24)
    pago = sum(float(i.get("amount") or 0)
                for i in invoices if i.get("paid_at"))
    em_aberto = sum(float(i.get("amount") or 0)
                     for i in invoices
                     if not i.get("paid_at")
                     and i.get("status") != "cancelled")

    # WhatsApp últimas conversas
    wa_cur = db.wa_conversations.find(
        {"subscriber_id": sid}, {"_id": 0, "id": 1, "last_at": 1,
                                  "direction": 1, "tag": 1}).sort(
                                      [("last_at", -1)]).limit(10)
    wa = await wa_cur.to_list(10)

    # Reparos / OS Smart Field
    repairs_cur = db.smart_repairs.find(
        {"subscriber_id": sid}, {"_id": 0, "id": 1, "kind": 1,
                                  "status": 1, "created_at": 1,
                                  "technician": 1}).sort(
                                      [("created_at", -1)]).limit(10)
    repairs = await repairs_cur.to_list(10)

    # LTV e custo
    plan_price = float(sub.get("plan_price") or 0)
    months_active = 0
    if sub.get("installation_date"):
        try:
            i_dt = datetime.fromisoformat(sub["installation_date"])
            months_active = max(1, int((_now() - i_dt).days / 30))
        except Exception:
            months_active = 1
    ltv_brl = plan_price * months_active
    custo_estimado = 60 * len(repairs) + 35 * tickets_open + 30
    lucro_liquido = round(pago - custo_estimado, 2)

    # Motivo raiz mais provável (heurística)
    motivos = []
    if onu and onu.get("signal_text") == "Critical":
        motivos.append("Sinal crítico — degradação física")
    if tickets_open > 3:
        motivos.append(f"Excesso de tickets ({tickets_open})")
    if em_aberto > plan_price * 2:
        motivos.append(f"Inadimplência R$ {em_aberto:.0f}")
    if not motivos:
        motivos.append("Sem motivo raiz aparente — cliente estável")

    return {
        "subscriber": {
            "id": sid,
            "name": sub.get("name"),
            "document": sub.get("document"),
            "status": sub.get("status"),
            "plan_name": sub.get("plan_name"),
            "plan_price_brl": plan_price,
            "installation_date": sub.get("installation_date"),
            "company_id": cid,
        },
        "rede": {
            "onu": onu,
            "cto": cto,
            "olt_name": (onu or {}).get("olt_name"),
            "zone_name": (onu or {}).get("zone_name"),
        },
        "atendimento": {
            "tickets_total_30d": len(tickets),
            "tickets_em_aberto": tickets_open,
            "tickets": tickets,
            "wa_conversations": wa,
        },
        "tecnico_instalador": install,
        "manutencoes": repairs,
        "financeiro": {
            "pago_total_brl": round(pago, 2),
            "em_aberto_brl": round(em_aberto, 2),
            "faturas_24m": len(invoices),
            "ultimas_faturas": invoices[:6],
        },
        "ltv_estimado_brl": round(ltv_brl, 2),
        "custo_estimado_brl": round(custo_estimado, 2),
        "lucro_liquido_brl": lucro_liquido,
        "meses_ativo": months_active,
        "motivo_raiz_mais_provavel": motivos[0],
        "fatores_risco": motivos,
        "generated_at": _iso(_now()),
    }


async def digital_twin_global(company_id: str) -> Dict[str, Any]:
    """Visão agregada da empresa digital — totais por domínio."""
    pipe_subs = [
        {"$match": {"company_id": company_id,
                       "status": {"$in": ["ATIVO", "ATIVA"]}}},
        {"$group": {"_id": None,
                       "n": {"$sum": 1},
                       "mrr": {"$sum": "$plan_price"}}}
    ]
    s = await db.subscribers.aggregate(pipe_subs).to_list(1)
    onus = await db.smartolt_onus.count_documents(
        {"company_id": company_id})
    onus_crit = await db.smartolt_onus.count_documents(
        {"company_id": company_id, "signal_text": "Critical"})
    ctos_n = await db.ctos.count_documents({"company_id": company_id})
    tech_active = await db.smart_installs.distinct(
        "technician_id", {"company_id": company_id})
    return {
        "company_id": company_id,
        "clientes_ativos": (s[0]["n"] if s else 0),
        "mrr_brl": round((s[0]["mrr"] if s else 0), 2),
        "onus_total": onus,
        "onus_critical": onus_crit,
        "ctos_total": ctos_n,
        "tecnicos_distintos": len(tech_active),
        "generated_at": _iso(_now()),
    }


# ═════════════════════════════════════════════════════
#  V14 — AUTOPILOT SIMULATION
# ═════════════════════════════════════════════════════
async def autopilot_top10(company_id: str) -> Dict[str, Any]:
    """Top 10 decisões ordenadas por valor esperado.
    Reuso: presidente_executive (5 ações) + governador.cobranca
    (metas em risco) + drift (histórico de acerto)."""
    from services.presidente_executive import build_executive_report
    from services.governador_ia import cobranca_resultado
    from services.executor_ia import (CATEGORIAS_EXECUTAVEIS,
                                         consult_memory)

    rep = await build_executive_report(company_id)
    prioridades = rep.get("acoes_presidenciais", [])
    cob = await cobranca_resultado(company_id)

    drifts = await db.motor_ia_drift.find(
        {"company_id": company_id}, {"_id": 0}).to_list(50)
    drift_by_cat = {d["categoria"]: d for d in drifts}

    decisions: List[Dict[str, Any]] = []

    # Decisões vindas das prioridades do executivo
    for i, p in enumerate(prioridades):
        cat = _infer_category(p["acao"])
        d_info = drift_by_cat.get(cat or "", {}) if cat else {}
        confidence = (round(d_info.get("taxa_acerto", 0.5) * 100, 0)
                       if d_info else 50)
        mem = (await consult_memory(company_id, cat)
                if cat and cat in CATEGORIAS_EXECUTAVEIS
                else {"historico_n": 0,
                       "roi_medio_brl": 0})
        impacto = float(p.get("impacto_brl") or 0)
        risco = "BAIXO"
        if cat == "CAMPANHA_RETENCAO" and confidence < 50:
            risco = "ALTO"
        elif impacto > 50000:
            risco = "MÉDIO"
        esforco = (p.get("esforco") or "MÉDIO").upper()
        prazo_d = 7 if p.get("prioridade") == "ALTA" else 30
        roi_esp = impacto * (confidence / 100.0)
        valor_esp = roi_esp
        decisions.append({
            "rank_origem": i + 1,
            "decisao": p["acao"],
            "categoria_executor": cat,
            "executavel": bool(cat
                                  and cat in CATEGORIAS_EXECUTAVEIS),
            "impacto_financeiro_brl": round(impacto, 2),
            "risco": risco,
            "confianca_pct": confidence,
            "esforco": esforco,
            "prazo_dias": prazo_d,
            "roi_esperado_brl": round(roi_esp, 2),
            "valor_esperado_brl": round(valor_esp, 2),
            "historico_amostras": mem["historico_n"],
            "historico_roi_medio_brl": mem.get("roi_medio_brl", 0.0),
            "justificativa": p.get("justificativa", ""),
            "origem": "prioridade_executiva",
        })

    # Decisões vindas das metas em risco
    for c in cob:
        if c["diagnostico"] not in ("em_risco", "atrasada"):
            continue
        impacto = max(0.0,
                         (c["target"] or 0) - (c["current"] or 0))
        decisions.append({
            "rank_origem": None,
            "decisao": (f"Acelerar meta {c['metric']} → "
                          f"alvo {c['target']} (atual "
                          f"{c['current']})"),
            "categoria_executor": None,
            "executavel": False,
            "impacto_financeiro_brl": round(impacto, 2),
            "risco": ("ALTO" if c["progress_pct"] < 30
                       else "MÉDIO"),
            "confianca_pct": 60,
            "esforco": "ALTO",
            "prazo_dias": 14,
            "roi_esperado_brl": round(impacto * 0.6, 2),
            "valor_esperado_brl": round(impacto * 0.6, 2),
            "historico_amostras": 0,
            "historico_roi_medio_brl": 0.0,
            "justificativa": (f"Meta {c['area']} responsável "
                                f"{c['ia_responsavel']} em "
                                f"{c['diagnostico']}"),
            "origem": "meta_em_risco",
        })

    # Ordena por valor esperado e limita 10
    decisions.sort(
        key=lambda d: d["valor_esperado_brl"], reverse=True)
    top = decisions[:10]
    return {
        "company_id": company_id,
        "geradas": len(decisions),
        "top10": top,
        "valor_esperado_total_brl": round(
            sum(d["valor_esperado_brl"] for d in top), 2),
        "generated_at": _iso(_now()),
        "se_autopilot_autorizado": (
            "Se autorizado a agir agora, "
            f"executaria as {len(top)} decisões acima na ordem "
            f"listada — valor esperado total R$ "
            f"{sum(d['valor_esperado_brl'] for d in top):,.0f}"
        ).replace(",", "."),
    }


def _infer_category(acao_texto: str) -> Optional[str]:
    t = (acao_texto or "").lower()
    if "reajuste" in t or "ipca" in t:
        return "REAJUSTE_IPCA"
    if ("cobrança" in t or "cobranca" in t or "dunning" in t
            or "régua" in t or "inadimp" in t):
        return "DISPARO_COBRANCA"
    if "leo" in t or "proativo" in t or ("contato" in t
                                              and "client" in t):
        return "CONTATO_LEO_PROATIVO"
    if "retenção" in t or "retencao" in t or "campanha" in t:
        return "CAMPANHA_RETENCAO"
    if ("os" in t and ("smart" in t or "preventiva" in t))\
            or "onu" in t or "técnico" in t or "tecnico" in t:
        return "CRIACAO_OS_SMARTFIELD"
    return None
