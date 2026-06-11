"""Holerite Anomaly Detector — compara holerite recém-importado com o
do mês anterior do mesmo funcionário e detecta variações suspeitas.

Tipos de anomalia detectados:
1. NET_DROP        — líquido caiu mais de N% (default 10%)
2. NET_RISE        — líquido subiu mais de N% (suspeito de erro)
3. GROSS_DROP      — bruto caiu mais de N%
4. GROSS_RISE      — bruto subiu mais de N%
5. NEW_EARNING     — apareceu uma rubrica de proventos nunca vista antes
6. MISSING_EARNING — uma rubrica recorrente desapareceu
7. NEW_DEDUCTION   — apareceu desconto novo
8. INSS_HIGH       — INSS > 15% do bruto (limite legal ~14%)
9. ZERO_NET        — líquido = 0 ou negativo
10. DUPLICATE      — já existe holerite para a mesma competência+funcionário

Best practices aplicadas:
- Limiar configurável por empresa (mongo: holerite_anomaly_config).
- Detecção rápida, sem LLM (regras determinísticas — auditável).
- Severidade: warning (auditar) | critical (bloquear notificação até reviewer ok).
- Cada anomalia tem `kind`, `severity`, `message`, `details` (deltas).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("holerite_anomaly")

DEFAULTS = {
    "net_change_pct": 10.0,       # variação líquido tolerada
    "gross_change_pct": 10.0,     # variação bruto tolerada
    "inss_pct_limit": 15.0,       # INSS acima desse % é suspeito
}


def _pct_diff(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return (curr - prev) / prev * 100.0


def _earnings_keys(items: List[Dict]) -> set:
    """Normaliza descrições (lower + remove acentos) para comparação."""
    try:
        from unidecode import unidecode
    except ImportError:
        def unidecode(s):
            return s
    return {
        unidecode((it.get("description") or "").strip()).lower()
        for it in (items or []) if it.get("description")
    }


def detect(
    curr: Dict[str, Any],
    prev: Optional[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Compara dois documentos de holerite e retorna lista de anomalias."""
    cfg = {**DEFAULTS, **(cfg or {})}
    out: List[Dict[str, Any]] = []

    curr_gross = float(curr.get("gross") or 0)
    curr_net = float(curr.get("net") or 0)

    # 1. Sanity check — net válido
    if curr_net <= 0:
        out.append({
            "kind": "ZERO_NET", "severity": "critical",
            "message": "Líquido é zero ou negativo — possível erro de extração.",
            "details": {"net": curr_net},
        })

    # 2. INSS desproporcional
    inss_value = 0.0
    for d in (curr.get("deductions_breakdown") or []):
        desc = (d.get("description") or "").lower()
        if "inss" in desc:
            inss_value += float(d.get("value") or 0)
    if curr_gross > 0 and inss_value > 0:
        inss_pct = inss_value / curr_gross * 100.0
        if inss_pct > cfg["inss_pct_limit"]:
            out.append({
                "kind": "INSS_HIGH", "severity": "warning",
                "message": (
                    f"INSS de R$ {inss_value:.2f} representa "
                    f"{inss_pct:.1f}% do bruto (limite legal ~14%)."
                ),
                "details": {
                    "inss_value": round(inss_value, 2),
                    "inss_pct": round(inss_pct, 2),
                    "gross": curr_gross,
                },
            })

    # 3. Comparação com mês anterior
    if not prev:
        out.append({
            "kind": "FIRST_HOLERITE", "severity": "info",
            "message": "Primeiro holerite deste funcionário no sistema — sem comparação histórica.",
            "details": {},
        })
        return out

    prev_gross = float(prev.get("gross") or 0)
    prev_net = float(prev.get("net") or 0)

    # NET / GROSS variations
    net_pct = _pct_diff(curr_net, prev_net)
    gross_pct = _pct_diff(curr_gross, prev_gross)

    if abs(net_pct) >= cfg["net_change_pct"]:
        kind = "NET_DROP" if net_pct < 0 else "NET_RISE"
        sev = "warning" if abs(net_pct) < 25 else "critical"
        out.append({
            "kind": kind, "severity": sev,
            "message": (
                f"Líquido variou {net_pct:+.1f}% em relação ao mês anterior "
                f"(R$ {prev_net:.2f} → R$ {curr_net:.2f})."
            ),
            "details": {
                "prev_net": prev_net, "curr_net": curr_net,
                "pct": round(net_pct, 2),
            },
        })

    if abs(gross_pct) >= cfg["gross_change_pct"]:
        kind = "GROSS_DROP" if gross_pct < 0 else "GROSS_RISE"
        sev = "warning" if abs(gross_pct) < 25 else "critical"
        out.append({
            "kind": kind, "severity": sev,
            "message": (
                f"Bruto variou {gross_pct:+.1f}% em relação ao mês anterior "
                f"(R$ {prev_gross:.2f} → R$ {curr_gross:.2f})."
            ),
            "details": {
                "prev_gross": prev_gross, "curr_gross": curr_gross,
                "pct": round(gross_pct, 2),
            },
        })

    # Rubricas novas / faltantes
    curr_earns = _earnings_keys(curr.get("earnings_breakdown"))
    prev_earns = _earnings_keys(prev.get("earnings_breakdown"))
    new_earns = curr_earns - prev_earns
    missing_earns = prev_earns - curr_earns

    for desc in new_earns:
        out.append({
            "kind": "NEW_EARNING", "severity": "warning",
            "message": (
                f"Nova rubrica de provento '{desc}' não aparecia no mês "
                f"anterior — confirmar com contador."
            ),
            "details": {"description": desc},
        })
    for desc in missing_earns:
        out.append({
            "kind": "MISSING_EARNING", "severity": "warning",
            "message": (
                f"Rubrica '{desc}' que existia no mês anterior desapareceu "
                f"— verificar se houve mudança contratual."
            ),
            "details": {"description": desc},
        })

    # Descontos novos
    curr_deds = _earnings_keys(curr.get("deductions_breakdown"))
    prev_deds = _earnings_keys(prev.get("deductions_breakdown"))
    new_deds = curr_deds - prev_deds
    for desc in new_deds:
        # INSS/IRRF/FGTS são padrão, ignorar
        skip = any(k in desc for k in ("inss", "irrf", "fgts", "imposto"))
        if skip:
            continue
        out.append({
            "kind": "NEW_DEDUCTION", "severity": "warning",
            "message": (
                f"Novo desconto '{desc}' não existia no mês anterior — "
                f"confirmar com colaborador."
            ),
            "details": {"description": desc},
        })

    return out


async def analyze_doc(doc_id: str, company_id: str) -> List[Dict[str, Any]]:
    """Pega o doc, busca o anterior e roda detect(). Persiste anomalias no doc.

    Retorna a lista de anomalias.
    """
    curr = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": company_id}, {"_id": 0},
    )
    if not curr:
        return []

    eid = curr.get("employee_id")
    cm = int(curr.get("competence_month") or 0)
    cy = int(curr.get("competence_year") or 0)
    # Busca o doc mais recente ANTES desta competência (mesmo employee)
    prev_filter = {
        "company_id": company_id,
        "employee_id": eid,
        "id": {"$ne": doc_id},
        "$or": [
            {"competence_year": {"$lt": cy}},
            {"competence_year": cy, "competence_month": {"$lt": cm}},
        ],
    }
    prev = await db.payroll_documents.find_one(
        prev_filter, {"_id": 0},
        sort=[("competence_year", -1), ("competence_month", -1)],
    )

    # Checa duplicidade primeiro
    dup = await db.payroll_documents.find_one(
        {
            "company_id": company_id, "employee_id": eid,
            "competence_year": cy, "competence_month": cm,
            "id": {"$ne": doc_id}, "status": {"$ne": "revoked"},
        },
        {"_id": 0, "id": 1, "created_at": 1},
    )
    anomalies = detect(curr, prev)
    if dup:
        anomalies.insert(0, {
            "kind": "DUPLICATE", "severity": "critical",
            "message": (
                f"Já existe holerite ativo para {cm:02d}/{cy} deste "
                f"funcionário (id={dup['id']}) — verificar duplicidade."
            ),
            "details": {"duplicate_doc_id": dup["id"]},
        })

    critical_count = sum(1 for a in anomalies if a.get("severity") == "critical")
    update_fields = {
        "anomalies": anomalies,
        "anomalies_count": len(anomalies),
        "anomalies_critical": critical_count,
    }
    # ★ Auto-lock se houver anomalia crítica e doc estiver available
    if critical_count > 0 and curr.get("status") == "available":
        update_fields["status"] = "pending_review"
        update_fields["pending_review_reason"] = (
            f"{critical_count} anomalia(s) crítica(s) detectada(s) "
            f"— aprovação do RH necessária."
        )

    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": company_id},
        {"$set": update_fields},
    )
    return anomalies
