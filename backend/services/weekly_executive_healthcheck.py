"""Weekly Executive Healthcheck — CEO 19/06/2026

Roda toda sexta 06:00 UTC. Gera /app/memory/WEEKLY_EXECUTIVE_HEALTHCHECK.md
com snapshot dos KPIs operacionais + auditoria semanal + E2E.

Zero feature. Zero dashboard. Apenas markdown.
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient


WEEKLY_REPORT_PATH = "/app/memory/WEEKLY_EXECUTIVE_HEALTHCHECK.md"


async def _gather_kpis(db, company_id: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    d7 = (now - timedelta(days=7)).isoformat()

    # Patrimônio
    official = await db.stok_onts.count_documents(
        {"company_id": company_id, "tier": "official",
         "_e2e_synthetic": {"$ne": True}})
    quarantine = await db.stok_onts.count_documents(
        {"company_id": company_id, "tier": "quarantine"})
    perm_quar = await db.stok_onts.count_documents(
        {"company_id": company_id, "asset_status": "permanent_quarantine"})
    smartolt = await db.smartolt_onus.count_documents(
        {"company_id": company_id})

    cobertura = round(official / smartolt * 100, 2) if smartolt else 0.0
    compliance = round(official / (official + quarantine) * 100, 2) \
        if official else 0.0

    # Swaps
    swap_total = await db.auto_ont_swap_events.count_documents(
        {"company_id": company_id})
    swap_pending = await db.auto_ont_swap_events.count_documents(
        {"company_id": company_id,
         "confirmation_status": {"$in": [
             "pending_confirmation", "sent_to_technician"]}})

    # Onda 3 — produção real (excluindo sintéticos)
    onda3_total = await db.sprint5_onda3_validations.count_documents(
        {"company_id": company_id, "created_at": {"$gte": d7}})
    onda3_blocked = await db.sprint5_onda3_validations.count_documents(
        {"company_id": company_id, "ok": False,
         "created_at": {"$gte": d7}})
    onda3_real = await db.sprint5_onda3_validations.count_documents(
        {"company_id": company_id, "created_at": {"$gte": d7},
         "$nor": [
             {"actor_email": {"$regex": "test|e2e", "$options": "i"}},
             {"ticket_id": {"$regex": "test|e2e|onda3-real",
                            "$options": "i"}},
         ]})
    onda3_real_block = await db.sprint5_onda3_validations.count_documents(
        {"company_id": company_id, "ok": False,
         "created_at": {"$gte": d7},
         "$nor": [
             {"actor_email": {"$regex": "test|e2e", "$options": "i"}},
             {"ticket_id": {"$regex": "test|e2e|onda3-real",
                            "$options": "i"}},
         ]})

    block_rate_apparent = (
        round(onda3_blocked / onda3_total * 100, 1)
        if onda3_total else None)
    block_rate_real = (
        round(onda3_real_block / onda3_real * 100, 1)
        if onda3_real else None)

    # Latest audit
    latest_audit = await db.sprint5_audit_operacional.find_one(
        {"company_id": company_id}, {"_id": 0},
        sort=[("generated_at", -1)])
    audit_score = (latest_audit or {}).get("score_0_10")
    audit_status = (latest_audit or {}).get("status")

    # Phase A: prev week to compute delta
    prev_audits = await db.sprint5_audit_operacional.find(
        {"company_id": company_id}, {"_id": 0, "score_0_10": 1,
         "answers.patrim_cobertura_operacional_pct": 1,
         "generated_at": 1}
    ).sort("generated_at", -1).limit(2).to_list(length=2)
    score_delta = None
    cov_delta_pp = None
    if len(prev_audits) >= 2:
        score_delta = round(
            (prev_audits[0].get("score_0_10") or 0)
            - (prev_audits[1].get("score_0_10") or 0), 2)
        cov_delta_pp = round(
            ((prev_audits[0].get("answers") or {}).get(
                "patrim_cobertura_operacional_pct") or 0)
            - ((prev_audits[1].get("answers") or {}).get(
                "patrim_cobertura_operacional_pct") or 0), 2)

    return {
        "kpis": {
            "cobertura_operacional_pct": cobertura,
            "compliance_pct": compliance,
            "patrimonio_official": official,
            "quarantine_pending": quarantine,
            "permanent_quarantine": perm_quar,
            "smartolt_total": smartolt,
            "swap_total": swap_total,
            "swap_pending": swap_pending,
        },
        "onda3": {
            "total_7d": onda3_total,
            "blocked_7d": onda3_blocked,
            "real_7d": onda3_real,
            "real_blocked_7d": onda3_real_block,
            "block_rate_apparent_pct": block_rate_apparent,
            "block_rate_real_pct": block_rate_real,
        },
        "audit": {
            "score_0_10": audit_score,
            "status": audit_status,
            "score_delta_week": score_delta,
            "cobertura_delta_pp_week": cov_delta_pp,
        },
    }


def _render_markdown(snapshot: Dict[str, Any], now: datetime) -> str:
    k = snapshot["kpis"]
    o = snapshot["onda3"]
    a = snapshot["audit"]

    def _classify_cov(v):
        if v is None:
            return "—"
        if v >= 98:
            return "🟢 EXCELÊNCIA"
        if v >= 90:
            return "🟢 VERDE"
        if v >= 80:
            return "🟡 AMARELO"
        return "🔴 VERMELHO"

    def _classify_quar(v):
        if v is None:
            return "—"
        if v <= 30:
            return "🟢 VERDE"
        if v <= 60:
            return "🟡 AMARELO"
        return "🔴 VERMELHO"

    def _classify_swap(v):
        if v is None:
            return "—"
        if v == 0:
            return "🟢 ZERO"
        if v <= 5:
            return "🟡 ACEITÁVEL"
        return "🔴 ATENÇÃO"

    block_real_display = (
        f"{o['block_rate_real_pct']}%"
        if o["block_rate_real_pct"] is not None
        else "⚪ Sem amostra real"
    )

    lines = [
        f"# 📅 WEEKLY EXECUTIVE HEALTHCHECK",
        "",
        f"**Data:** {now.strftime('%d/%m/%Y %H:%M')} UTC  ",
        f"**Semana ISO:** {now.strftime('%Y-W%V')}  ",
        f"**Gerado por:** weekly_executive_healthcheck (cron sexta 06:00)",
        "",
        "---",
        "",
        "## 1. KPIs DA SEMANA",
        "",
        "| KPI | Valor | Status |",
        "|---|---:|:---:|",
        f"| Cobertura Operacional | {k['cobertura_operacional_pct']} % "
        f"| {_classify_cov(k['cobertura_operacional_pct'])} |",
        f"| Compliance Patrimonial | {k['compliance_pct']} % "
        f"| {_classify_cov(k['compliance_pct'])} |",
        f"| Quarentena pendente | {k['quarantine_pending']} "
        f"| {_classify_quar(k['quarantine_pending'])} |",
        f"| Swap events pending | {k['swap_pending']} "
        f"| {_classify_swap(k['swap_pending'])} |",
        f"| Score Auditoria Operacional | {a['score_0_10']}/10 "
        f"| {a['status']} |",
        f"| Block Rate Onda 3 (real) | {block_real_display} | — |",
        "",
        "---",
        "",
        "## 2. EVOLUÇÃO vs. SEMANA ANTERIOR",
        "",
    ]
    if a["score_delta_week"] is not None:
        sd = a["score_delta_week"]
        cd = a["cobertura_delta_pp_week"]
        lines.extend([
            f"- Δ Score Phase A: "
            f"**{'+' if sd >= 0 else ''}{sd}**",
            f"- Δ Cobertura Operacional: "
            f"**{'+' if cd >= 0 else ''}{cd} pp**",
        ])
    else:
        lines.append("- Sem snapshot anterior para comparação.")
    lines.extend([
        "",
        "---",
        "",
        "## 3. AUDITORIA ONDA 3 (últimos 7 dias)",
        "",
        f"- Validações totais: **{o['total_7d']}**",
        f"- Bloqueios totais: **{o['blocked_7d']}**",
        f"- Validações REAIS (excl. test/e2e): **{o['real_7d']}**",
        f"- Bloqueios REAIS: **{o['real_blocked_7d']}**",
        f"- Block rate aparente: "
        f"{o['block_rate_apparent_pct']}% "
        f"({'baseline sintético' if (o['real_7d'] or 0) < 30 else 'representativo'})",
        f"- Block rate REAL: {block_real_display}",
        "",
        "---",
        "",
        "## 4. PATRIMÔNIO",
        "",
        f"- Patrimônio oficial: **{k['patrimonio_official']}**",
        f"- Quarentena: **{k['quarantine_pending']}** "
        f"(permanent: {k['permanent_quarantine']})",
        f"- SmartOLT total: **{k['smartolt_total']}**",
        f"- Swap events totais: **{k['swap_total']}** "
        f"(pendentes: {k['swap_pending']})",
        "",
        "---",
        "",
        "## 5. STATUS GERAL",
        "",
    ])

    issues = []
    if (k["cobertura_operacional_pct"] or 0) < 95:
        issues.append("cobertura abaixo de 95 %")
    if (k["quarantine_pending"] or 0) > 60:
        issues.append("quarentena acima de 60 itens")
    if (k["swap_pending"] or 0) > 5:
        issues.append("swap pending acima de 5")
    if (o["real_7d"] or 0) < 30:
        issues.append("amostra Onda 3 real insuficiente para block rate")

    if not issues:
        lines.append("🟢 **Operação em modo nominal.** Nada exige atenção.")
    else:
        lines.append("🟡 **Pontos de atenção desta semana:**")
        lines.append("")
        for i in issues:
            lines.append(f"  - {i}")

    lines.extend([
        "",
        "---",
        "",
        f"**Selo:** `weekly-{now.strftime('%Y_W%V')}` · "
        f"gerado por cron `weekly_executive_healthcheck`",
        "",
    ])
    return "\n".join(lines)


async def generate_weekly_healthcheck(
    db, company_id: str = "co-demo"
) -> Dict[str, Any]:
    """Pode ser chamado pelo cron OU manualmente para regenerar."""
    snapshot = await _gather_kpis(db, company_id)
    now = datetime.now(timezone.utc)
    md = _render_markdown(snapshot, now)

    with open(WEEKLY_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(md)

    # Audit log
    audit_doc = {
        "id": f"wkh-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "week_iso": now.strftime("%Y-W%V"),
        "generated_at": now.isoformat(),
        "snapshot": snapshot,
        "file_path": WEEKLY_REPORT_PATH,
    }
    audit_doc["hash_sha256"] = hashlib.sha256(
        json.dumps(audit_doc, sort_keys=True, default=str).encode()
    ).hexdigest()
    await db.weekly_executive_healthchecks.insert_one(audit_doc)
    return audit_doc


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")

    async def main():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        result = await generate_weekly_healthcheck(db, "co-demo")
        print(f"✅ Generated: {WEEKLY_REPORT_PATH}")
        print(f"   hash: {result['hash_sha256'][:32]}...")
        print(f"   week: {result['week_iso']}")
    asyncio.run(main())
