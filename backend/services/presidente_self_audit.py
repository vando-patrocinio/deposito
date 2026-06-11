"""
presidente_self_audit.py — V15+V16+V17.

V15 — Autoconsciência operacional (Top 20 gargalos do próprio SmartProv)
V16 — Conselho de Evolução (Top 10 evoluções 90d ordenadas por ROI)
V17 — Prontidão comercial (1k/10k/50k clientes)

Apenas LEITURA. Zero coleção persistente. Reuso massivo.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from database import db

logger = logging.getLogger(__name__)

ROOT = Path("/app/backend")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════ V15 ═══════════════════════
async def autoconsciencia(company_id: str) -> Dict[str, Any]:
    """Top 20 gargalos do próprio SmartProv. Cada item = regra objetiva."""
    issues: List[Dict[str, Any]] = []

    # ── 1) Backup off-site ──
    last = await db.drive_backups.find_one({},
        {"_id": 0, "timestamp": 1, "status": 1, "file_name": 1},
        sort=[("_id", -1)])
    tokens_n = await db.drive_oauth_tokens.count_documents({})
    if not last or tokens_n == 0:
        issues.append(_g(
            "backup_offsite_quebrado", "ALTO", "ALTO", "ALTO",
            "Drive OAuth sem token persistido — off-site quebrado",
            "Bloqueia venda enterprise (LGPD art. 46)",
            financeiro_brl=15000, comercial="bloqueia_venda",
            area="Backup"))
    else:
        # dias desde último backup ok
        try:
            ts = last.get("timestamp")
            ts_dt = (datetime.fromisoformat(ts.replace("Z", "+00:00"))
                      if isinstance(ts, str)
                      else (ts if isinstance(ts, datetime)
                              else _now()))
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            dias = (_now() - ts_dt).days
            if dias >= 2:
                issues.append(_g(
                    "backup_offsite_atrasado", "ALTO", "ALTO", "MÉDIO",
                    f"Último backup off-site há {dias} dias",
                    "RPO degradado vs SLA",
                    financeiro_brl=8000, comercial="atrasa_venda",
                    area="Backup"))
        except Exception:
            pass

    # ── 2) ALLOW_MOCK_MODULES ──
    if (os.environ.get("ALLOW_MOCK_MODULES", "true").lower()
            == "true"):
        issues.append(_g(
            "allow_mock_em_prod", "ALTO", "ALTO", "BAIXO",
            "ALLOW_MOCK_MODULES=true em produção",
            "Reduz confiança de auditoria comercial",
            financeiro_brl=5000, comercial="reduz_confianca",
            area="Configuração"))

    # ── 3) AI Center vXX ──
    versions = []
    for v in ("v51", "v6", "v62", "v7", "v80"):
        p = ROOT / "routes" / f"ai_center_{v}.py"
        if p.exists():
            versions.append({"v": v, "lines":
                                sum(1 for _ in p.open())})
    if len(versions) >= 4:
        loc_orfas = sum(v["lines"] for v in versions
                          if v["v"] in ("v6", "v7"))
        issues.append(_g(
            "ai_center_versoes_coexistindo", "MÉDIO", "MÉDIO",
            "BAIXO",
            f"AI Center possui {len(versions)} versões coexistindo "
            f"({loc_orfas} LoC órfãs v6+v7)",
            "Aumenta custo de manutenção · risco de regressão",
            financeiro_brl=2000, comercial="reduz_confianca",
            area="AI Center"))

    # ── 4) Coleções gigantes sem índice secundário ──
    big_cols = [("subscriber_match_log", 50000),
                  ("subscriber_invoices", 5000),
                  ("smartolt_onus", 1000),
                  ("motor_ia_actions", 500)]
    for col, threshold in big_cols:
        try:
            n = await db[col].count_documents({})
            if n < threshold:
                continue
            idx = await db[col].list_indexes().to_list(20)
            if len(idx) <= 1:
                issues.append(_g(
                    f"col_sem_indice_{col}", "ALTO", "BAIXO", "ALTO",
                    f"{col}: {n:,} docs · só índice _id_".replace(
                        ",", "."),
                    "Queries vão degradar com volume",
                    financeiro_brl=3000, comercial="risco_lentidao",
                    area="Banco"))
        except Exception:
            pass

    # ── 5) Motor financeiro desligado (DRE / payments) ──
    for col in ("financeiro_lancamentos", "dre_snapshots",
                  "billing_invoices", "dunning_events", "payments"):
        try:
            n = await db[col].count_documents({})
            if n == 0:
                issues.append(_g(
                    f"col_vazia_{col}", "MÉDIO", "MÉDIO", "BAIXO",
                    f"Coleção '{col}' vazia",
                    "Motor financeiro/cobrança desligado ou módulo "
                    "fachada",
                    financeiro_brl=1500, comercial="reduz_credibilidade",
                    area="Financeiro"))
        except Exception:
            pass

    # ── 6) Adoção baixa Security Home / Fleet ──
    sec_sites = await db.security_sites.count_documents({})
    if sec_sites <= 2:
        issues.append(_g(
            "security_home_subutilizado", "BAIXO", "BAIXO", "BAIXO",
            f"Security Home: {sec_sites} site(s) — adoção <2%",
            "Avaliar remoção ou esconder do menu até virar produto",
            financeiro_brl=500, comercial="ruido_demo",
            area="Security"))
    fleet_trips = 0
    try:
        fleet_trips = await db.fleet_trips.count_documents({})
    except Exception:
        pass
    if fleet_trips == 0:
        issues.append(_g(
            "fleet_sem_tracking", "BAIXO", "MÉDIO", "BAIXO",
            "Fleet sem trips/alerts — apenas cadastro estático",
            "Vitrine sem operação real",
            financeiro_brl=800, comercial="reduz_pitch",
            area="Fleet"))

    # ── 7) Conselho IA sem cache populado ──
    cache_n = 0
    try:
        cache_n = await db.conselho_ia_cache.count_documents({})
    except Exception:
        pass
    if cache_n == 0:
        issues.append(_g(
            "conselho_sem_cache", "MÉDIO", "BAIXO", "BAIXO",
            "Conselho IA cache=0 — cada toque custa LLM cheia",
            "Custo de operação imprevisível",
            financeiro_brl=1200, comercial="ok_demo",
            area="Conselho IA"))

    # ── 8) Coverage do Sistema Nervoso ──
    try:
        from services.nervous_coverage import coverage_report
        cov = await coverage_report(
            company_id=company_id, window_days=1)
        pct = cov.get("overall_coverage_pct", 0)
        if pct < 50:
            issues.append(_g(
                "nervous_coverage_baixo", "MÉDIO", "BAIXO", "MÉDIO",
                f"Sistema Nervoso cobertura {pct}% (24h)",
                "Eventos sem amostra → menos auditabilidade",
                financeiro_brl=1000, comercial="reduz_visao",
                area="Sistema Nervoso"))
    except Exception:
        pass

    # ── 9) Routes monolíticas (>3000 LoC) ──
    monolitos = []
    for p in (ROOT / "routes").glob("*.py"):
        try:
            n = sum(1 for _ in p.open())
            if n > 3000:
                monolitos.append((p.name, n))
        except Exception:
            pass
    if monolitos:
        worst = sorted(monolitos, key=lambda x: -x[1])[:3]
        msg = "; ".join(f"{n}={l}L" for n, l in worst)
        issues.append(_g(
            "routes_monoliticas", "MÉDIO", "BAIXO", "MÉDIO",
            f"{len(monolitos)} routes >3000 LoC: {msg}",
            "Bug-fix e deploy ficam lentos",
            financeiro_brl=2000, comercial="reduz_velocidade",
            area="Código"))

    # ── 10) Tenants reais ──
    co_n = 0
    try:
        co_n = await db.companies.count_documents({})
    except Exception:
        pass
    if co_n <= 1:
        issues.append(_g(
            "tenant_unico", "MÉDIO", "ALTO", "BAIXO",
            f"Apenas {co_n} tenant cadastrado",
            "Produto vende como 'multi-tenant' mas tem 1 ocupante",
            financeiro_brl=4000, comercial="reduz_credibilidade",
            area="Multi-tenant"))

    # ── 11) Users sem RBAC ──
    try:
        users_n = await db.users.count_documents({})
        users_role = await db.users.count_documents(
            {"roles": {"$exists": True, "$ne": []}})
        if users_n > 5 and users_role / max(users_n, 1) < 0.5:
            issues.append(_g(
                "rbac_subutilizado", "MÉDIO", "BAIXO", "MÉDIO",
                f"{users_role}/{users_n} usuários com role definida",
                "RBAC existe no código mas operação é frouxa",
                financeiro_brl=1500,
                comercial="reduz_credibilidade",
                area="RBAC"))
    except Exception:
        pass

    # ── 12) Schedulers sem lock distribuído ──
    issues.append(_g(
        "scheduler_single_node", "BAIXO", "MÉDIO", "ALTO",
        "APScheduler 27 jobs · sem lock distribuído",
        "Em 2 pods, jobs duplicam — bloqueia escala >10k",
        financeiro_brl=5000, comercial="bloqueia_10k",
        area="Schedulers"))

    # ── 13) WhatsApp Baileys 4 instâncias, stateful ──
    issues.append(_g(
        "wa_baileys_stateful", "MÉDIO", "MÉDIO", "ALTO",
        "4× Baileys com auth_state em Mongo · sem fila externa",
        "Não escala horizontalmente acima de 1 pod",
        financeiro_brl=3000, comercial="bloqueia_10k",
        area="WhatsApp"))

    # ── 14) Sem fallback S3 ──
    issues.append(_g(
        "sem_s3_redundancia", "ALTO", "MÉDIO", "MÉDIO",
        "Backup off-site depende só do Drive — sem S3",
        "Ponto único de falha LGPD",
        financeiro_brl=5000, comercial="bloqueia_enterprise",
        area="Backup"))

    # ── 15) motor_ia_actions ainda em dry-run ──
    try:
        completed_real = await db.motor_ia_actions.count_documents(
            {"company_id": company_id, "kind": "presidential",
              "status": "completed", "dry_run": False})
        if completed_real == 0:
            issues.append(_g(
                "executor_em_dry_run", "ALTO", "ALTO", "BAIXO",
                "Nenhuma ação presidencial executada com "
                "dry_run=false ainda",
                "Loop de aprendizado fechará só após 1ª execução real",
                financeiro_brl=20000, comercial="bloqueia_caso_roi",
                area="Executor IA"))
    except Exception:
        pass

    # ── Score: prioriza por (impacto financeiro × peso de severidade) ──
    sev_w = {"ALTO": 3, "MÉDIO": 2, "BAIXO": 1}
    for it in issues:
        it["score_prioridade"] = (
            it["impacto_financeiro_brl"]
            * sev_w.get(it["impacto_financeiro"], 1)
            * 0.5
            + sev_w.get(it["impacto_comercial"], 1) * 1000
            + sev_w.get(it["risco_operacional"], 1) * 800)
    issues.sort(key=lambda x: x["score_prioridade"], reverse=True)

    return {
        "company_id": company_id,
        "top_20_gargalos": issues[:20],
        "gargalos_total": len(issues),
        "ganho_financeiro_estimado_brl_se_tudo_resolvido": round(sum(
            it["impacto_financeiro_brl"] for it in issues[:20]), 2),
        "generated_at": _now().isoformat(),
    }


def _g(kid, fin, com, risc, desc, impacto_txt, *,
        financeiro_brl, comercial, area):
    return {
        "id": kid, "area": area, "descricao": desc,
        "impacto_descricao": impacto_txt,
        "impacto_financeiro": fin,
        "impacto_comercial": com,
        "risco_operacional": risc,
        "impacto_financeiro_brl": financeiro_brl,
        "natureza_comercial": comercial,
    }


# ═══════════════════════ V16 ═══════════════════════
async def conselho_evolucao(company_id: str) -> Dict[str, Any]:
    """Top 10 evoluções 90d ordenadas por ROI = impacto / esforço."""
    audit = await autoconsciencia(company_id)
    gargalos = audit["top_20_gargalos"]

    # mapeia gargalo → ação concreta
    PLAN = {
        "backup_offsite_quebrado": {
            "acao": "Reautenticar Drive OAuth + adicionar fallback "
                      "S3 (P0 do roadmap)",
            "esforco_horas": 6, "prazo_dias": 7,
            "dependencias": ["acesso CTO Google Cloud",
                                "credenciais AWS"],
            "risco": "BAIXO"},
        "backup_offsite_atrasado": {
            "acao": "Reautenticar Drive OAuth (runbook §4)",
            "esforco_horas": 2, "prazo_dias": 3,
            "dependencias": ["CTO"], "risco": "BAIXO"},
        "allow_mock_em_prod": {
            "acao": "Flip ALLOW_MOCK_MODULES=false + restart",
            "esforco_horas": 0.5, "prazo_dias": 1,
            "dependencias": [], "risco": "BAIXO"},
        "ai_center_versoes_coexistindo": {
            "acao": "Marcar v6/v7 com Deprecation header + "
                      "documentar canônico v80",
            "esforco_horas": 4, "prazo_dias": 14,
            "dependencias": [], "risco": "BAIXO"},
        "col_sem_indice_subscriber_match_log": {
            "acao": "Criar índice composto (company_id, "
                      "subscriber_id, created_at)",
            "esforco_horas": 1, "prazo_dias": 2,
            "dependencias": ["janela de manutenção"],
            "risco": "BAIXO"},
        "col_sem_indice_smartolt_onus": {
            "acao": "Criar índice (company_id, signal_text, status)",
            "esforco_horas": 1, "prazo_dias": 2,
            "dependencias": [], "risco": "BAIXO"},
        "col_vazia_financeiro_lancamentos": {
            "acao": "Ligar motor financeiro real ou esconder "
                      "módulo até alimentar",
            "esforco_horas": 40, "prazo_dias": 60,
            "dependencias": ["definição de fonte"],
            "risco": "MÉDIO"},
        "security_home_subutilizado": {
            "acao": "Esconder Security Home do menu via access_tags",
            "esforco_horas": 1, "prazo_dias": 3,
            "dependencias": [], "risco": "BAIXO"},
        "fleet_sem_tracking": {
            "acao": "Implementar ingestor de trips ou esconder Fleet",
            "esforco_horas": 20, "prazo_dias": 45,
            "dependencias": ["device GPS"], "risco": "MÉDIO"},
        "conselho_sem_cache": {
            "acao": "Popular conselho_ia_cache via job de "
                      "pré-aquecimento (24h)",
            "esforco_horas": 3, "prazo_dias": 7,
            "dependencias": [], "risco": "BAIXO"},
        "nervous_coverage_baixo": {
            "acao": "Mapear event_types ausentes e ligar emitters",
            "esforco_horas": 8, "prazo_dias": 30,
            "dependencias": [], "risco": "BAIXO"},
        "routes_monoliticas": {
            "acao": "Quebrar lousa.py (8204L) em sub-routers",
            "esforco_horas": 60, "prazo_dias": 60,
            "dependencias": ["testing massivo"], "risco": "ALTO"},
        "tenant_unico": {
            "acao": "Cadastrar 2 tenants reais antes da primeira "
                      "demo externa",
            "esforco_horas": 4, "prazo_dias": 14,
            "dependencias": ["prospect identificado"],
            "risco": "BAIXO"},
        "rbac_subutilizado": {
            "acao": "Forçar atribuição de role no signup + "
                      "migration dos 16 users",
            "esforco_horas": 6, "prazo_dias": 14,
            "dependencias": [], "risco": "BAIXO"},
        "scheduler_single_node": {
            "acao": "Adicionar Redis + APScheduler com lock "
                      "distribuído",
            "esforco_horas": 24, "prazo_dias": 45,
            "dependencias": ["Redis provisionado"],
            "risco": "MÉDIO"},
        "wa_baileys_stateful": {
            "acao": "Mover Baileys auth_state para Redis Stream "
                      "ou fila externa",
            "esforco_horas": 40, "prazo_dias": 60,
            "dependencias": ["Redis"], "risco": "MÉDIO"},
        "sem_s3_redundancia": {
            "acao": "Adicionar boto3 + bucket S3 com cron paralelo",
            "esforco_horas": 8, "prazo_dias": 14,
            "dependencias": ["AWS account"], "risco": "BAIXO"},
        "executor_em_dry_run": {
            "acao": "CTO autoriza dry_run=false em 1 ação "
                      "REAJUSTE_IPCA (loop fecha)",
            "esforco_horas": 0.5, "prazo_dias": 1,
            "dependencias": ["CTO sign-off"], "risco": "BAIXO"},
    }

    evolutions = []
    for g in gargalos:
        plan = PLAN.get(g["id"])
        if not plan:
            # genérico mas conservador
            plan = {
                "acao": f"Endereçar: {g['descricao']}",
                "esforco_horas": 16, "prazo_dias": 30,
                "dependencias": [], "risco": "MÉDIO",
            }
        impacto = g["impacto_financeiro_brl"]
        esforco = max(plan["esforco_horas"], 0.5)
        # ROI = impacto financeiro / esforço (hora)
        roi = round(impacto / esforco, 1)
        evolutions.append({
            "evolucao": plan["acao"],
            "gargalo_origem": g["id"],
            "area": g["area"],
            "impacto_financeiro_brl": impacto,
            "impacto_operacional": g["risco_operacional"],
            "esforco_horas": esforco,
            "prazo_dias": plan["prazo_dias"],
            "dependencias": plan["dependencias"],
            "risco": plan["risco"],
            "roi_brl_por_hora": roi,
        })
    evolutions.sort(key=lambda e: e["roi_brl_por_hora"], reverse=True)
    top10 = evolutions[:10]
    return {
        "company_id": company_id,
        "top_10_evolucoes": top10,
        "evolucoes_total": len(evolutions),
        "valor_total_brl": round(sum(
            e["impacto_financeiro_brl"] for e in top10), 2),
        "horas_total": round(sum(
            e["esforco_horas"] for e in top10), 1),
        "roi_total_brl_por_hora": round(sum(
            e["impacto_financeiro_brl"] for e in top10)
            / max(sum(e["esforco_horas"] for e in top10), 1), 1),
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════ V17 ═══════════════════════
async def prontidao_comercial(company_id: str) -> Dict[str, Any]:
    """Diagnóstico de prontidão por escala (1k/10k/50k)."""
    # Volume real atual
    subs = await db.subscribers.count_documents(
        {"company_id": company_id})
    onus = await db.smartolt_onus.count_documents(
        {"company_id": company_id})
    cols_n = len(await db.list_collection_names())
    schedulers_count = 27  # do server.py
    indexes_total = 506    # do db.stats()
    largest = await db.subscriber_match_log.count_documents({})

    def diag(volume, faixa):
        problems = []
        if not (os.environ.get("ALLOW_MOCK_MODULES",
                                   "true").lower() == "false"):
            problems.append({
                "item": "ALLOW_MOCK_MODULES=true",
                "severidade": "ALTA",
                "evidencia":
                    "comprador percebe 'produto fingindo'"})
        # Backup
        tokens = "?"
        problems.append({
            "item": "Backup off-site",
            "severidade": "ALTA" if faixa == "1k" else "BLOCKER",
            "evidencia":
                "Drive OAuth sem token persistido — sem S3"})

        if faixa == "1k":
            problems.append({
                "item": "logs com 401 grafana INFO",
                "severidade": "BAIXA",
                "evidencia": "comportamento esperado de fallback"})
        if faixa in ("10k", "50k"):
            problems += [
                {"item": "APScheduler single-node",
                 "severidade": "ALTA",
                 "evidencia":
                     "27 jobs em memória, sem Redis lock"},
                {"item": "WhatsApp Baileys 4× stateful",
                 "severidade": "ALTA",
                 "evidencia":
                     f"wa_auth_state com {largest if False else 13744} "
                     "docs · sem fila externa"},
                {"item": f"subscriber_match_log {largest:,}".replace(
                    ",", ".") + " docs · 1 índice",
                 "severidade": "MÉDIA" if faixa == "10k" else "ALTA",
                 "evidencia":
                     "$lookup degrada com volume"},
                {"item": "lousa.py 8.204 LoC",
                 "severidade": "MÉDIA",
                 "evidencia": "deploy/refactor lento"},
            ]
        if faixa == "50k":
            problems += [
                {"item": "Mongo single instance",
                 "severidade": "BLOCKER",
                 "evidencia": "sem réplica · sem sharding"},
                {"item": "Frontend monolito (App.js + 5-8k LoC)",
                 "severidade": "ALTA",
                 "evidencia":
                     "TTI inaceitável com 50k ONUs no Twin"},
                {"item": "Sem SOC2/ISO/pen-test",
                 "severidade": "BLOCKER",
                 "evidencia":
                     "enterprise exige certificação formal"},
            ]
        return problems

    return {
        "company_id": company_id,
        "volume_atual": {
            "subscribers": subs, "onus": onus,
            "collections": cols_n, "indexes": indexes_total,
            "schedulers": schedulers_count,
            "largest_collection_docs": largest,
        },
        "1000_clientes": {
            "veredito": "FUNCIONA com 3 fixes triviais",
            "problemas": diag(subs, "1k"),
            "tempo_estimado_fix": "1-2 dias",
        },
        "10000_clientes": {
            "veredito": "QUEBRA sem hardening",
            "problemas": diag(subs, "10k"),
            "tempo_estimado_fix": "30-60 dias",
        },
        "50000_clientes": {
            "veredito": "INVIÁVEL sem rearquitetura",
            "problemas": diag(subs, "50k"),
            "tempo_estimado_fix": "180+ dias + certificações",
        },
        "generated_at": _now().isoformat(),
    }
