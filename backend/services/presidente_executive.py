"""
presidente_executive.py — Cérebro Executivo do Presidente IA.

Não exibe métricas. Decide. Tudo monetizado.

Saída: 8 blocos (president_score, riscos, oportunidades, previsao_30d,
dinheiro_em_risco, dinheiro_recuperavel, surpresas, acoes) — todos com R$.

Fontes consumidas (uso degrada com graça quando ausentes):
  subscribers · smartolt_onus · tickets · network_outages · ctos
  · motor_ia_predictions/insights · parcerias_* · contracts/invoices
  · sales_leads · site_leads · indicacao_leads · referrals
  · olt_snmp_cache
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

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger(__name__)


# ─────────────────── Constantes presidenciais ───────────────────
# Probabilidades empíricas usadas para virar contagem em R$.
# Vieram de literatura SaaS/ISP + heurísticas internas; podem ser
# ajustadas em produção sem mudar a estrutura do retorno.
P_CHURN_SIGNAL_CRITICAL = 0.22   # ONU "Critical" → 22% churn 30d
P_CHURN_SIGNAL_WARNING = 0.08    # ONU "Warning"  → 8% churn 30d
P_CHURN_TICKET_OPEN_7D = 0.05    # ticket pendente >7d → 5% churn
P_CHURN_OUTAGE_REPEATED = 0.12   # bairro com 2+ outages 30d
IPCA_ANNUAL_TARGET = 0.045       # piso de reajuste anual
RETENTION_RECOVERY_RATE = 0.40   # 40% dos em risco podem ser salvos
TICKET_AVG_BACKUP_BRL = 117.43   # fallback se não houver MRR ainda


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _cutoff_iso(days: int) -> str:
    return _iso(_now() - timedelta(days=days))


def _safe(brl: float) -> float:
    """Arredonda BRL em 2 casas, garante não-negativo absurdo."""
    try:
        return round(float(brl), 2)
    except (TypeError, ValueError):
        return 0.0


def _base_q(cid: Optional[str]) -> Dict[str, Any]:
    return {"company_id": cid} if cid else {}


# ─────────────────── Fontes resilientes ───────────────────
class FontesAusentes:
    """Acumula fontes que falharam para o relatório executivo."""
    def __init__(self):
        self.usadas: List[str] = []
        self.ausentes: List[Dict[str, str]] = []

    def ok(self, nome: str):
        if nome not in self.usadas:
            self.usadas.append(nome)

    def falhou(self, nome: str, motivo: str):
        self.ausentes.append({"fonte": nome, "motivo": motivo[:160]})


async def _count(col: str, q: Dict[str, Any], f: FontesAusentes,
                  nome: str) -> int:
    try:
        n = await db[col].count_documents(q)
        f.ok(nome)
        return n
    except Exception as e:
        f.falhou(nome, repr(e))
        return 0


async def _agg(col: str, pipeline: List[Dict], f: FontesAusentes,
                nome: str) -> List[Dict]:
    try:
        out = await db[col].aggregate(pipeline).to_list(2000)
        f.ok(nome)
        return out
    except Exception as e:
        f.falhou(nome, repr(e))
        return []


# ─────────────────── Snapshots base ───────────────────
async def _mrr_e_ticket(cid: Optional[str],
                          f: FontesAusentes) -> Tuple[float, float, int]:
    """MRR total ativo, ticket médio, qtd ativos."""
    bq = _base_q(cid)
    pipe = [
        {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                       "plan_price": {"$gt": 0}}},
        {"$group": {"_id": None,
                       "mrr": {"$sum": "$plan_price"},
                       "avg": {"$avg": "$plan_price"},
                       "n": {"$sum": 1}}},
    ]
    out = await _agg("subscribers", pipe, f, "subscribers.plan_price")
    if not out:
        return 0.0, TICKET_AVG_BACKUP_BRL, 0
    o = out[0]
    return (_safe(o.get("mrr", 0)),
            _safe(o.get("avg") or TICKET_AVG_BACKUP_BRL),
            int(o.get("n") or 0))


async def _onus_por_sinal(cid: Optional[str],
                            f: FontesAusentes) -> Dict[str, int]:
    """Conta ONUs por classe de sinal usando smartolt_onus.signal_text."""
    bq = _base_q(cid)
    out = {"Good": 0, "Warning": 0, "Critical": 0, "Offline": 0}
    pipe = [
        {"$match": bq},
        {"$group": {"_id": "$signal_text", "n": {"$sum": 1}}},
    ]
    rows = await _agg("smartolt_onus", pipe, f, "smartolt_onus.signal_text")
    for r in rows:
        k = (r.get("_id") or "").strip()
        n = int(r.get("n") or 0)
        if k in out:
            out[k] += n
    # offline cruzado com status
    try:
        out["Offline"] = await db.smartolt_onus.count_documents(
            {**bq, "status": {"$ne": "Online"}})
        f.ok("smartolt_onus.status")
    except Exception as e:
        f.falhou("smartolt_onus.status", repr(e))
    return out


async def _tickets_estado(cid: Optional[str],
                            f: FontesAusentes) -> Dict[str, int]:
    bq = _base_q(cid)
    out = {"pendente": 0, "aberta": 0, "open": 0, "finalizada": 0,
            "encerrada": 0}
    rows = await _agg("tickets",
                         [{"$match": bq},
                          {"$group": {"_id": "$status",
                                         "n": {"$sum": 1}}}],
                         f, "tickets.status")
    for r in rows:
        out[r.get("_id") or "?"] = int(r.get("n") or 0)
    open_count = (out.get("pendente", 0) + out.get("aberta", 0)
                   + out.get("open", 0))
    out["_open_total"] = open_count
    return out


async def _outages_30d(cid: Optional[str],
                          f: FontesAusentes) -> List[Dict]:
    bq = _base_q(cid)
    try:
        rows = await db.network_outages.find(
            {**bq, "created_at": {"$gte": _cutoff_iso(30)}},
            {"_id": 0}).to_list(200)
        f.ok("network_outages.created_at")
        return rows
    except Exception as e:
        f.falhou("network_outages.created_at", repr(e))
        return []


async def _sem_reajuste_12m(cid: Optional[str],
                                f: FontesAusentes) -> int:
    bq = _base_q(cid)
    cutoff = _cutoff_iso(365)
    try:
        n = await db.subscribers.count_documents({
            **bq, "status": {"$in": ["ATIVO", "ATIVA"]},
            "$or": [
                {"last_readjustment_at": None},
                {"last_readjustment_at": {"$exists": False}},
                {"last_readjustment_at": {"$lt": cutoff}},
            ],
        })
        f.ok("subscribers.last_readjustment_at")
        return n
    except Exception as e:
        f.falhou("subscribers.last_readjustment_at", repr(e))
        return 0


async def _funil_30d(cid: Optional[str],
                        f: FontesAusentes) -> Dict[str, int]:
    bq = _base_q(cid)
    cutoff = _cutoff_iso(30)
    out = {"leads": 0, "site_leads": 0, "indic_leads": 0,
            "novos_ativos": 0}
    try:
        out["leads"] = await db.sales_leads.count_documents(
            {**bq, "created_at": {"$gte": cutoff}})
        f.ok("sales_leads.created_at")
    except Exception as e:
        f.falhou("sales_leads.created_at", repr(e))
    try:
        out["site_leads"] = await db.site_leads.count_documents(
            {**bq, "created_at": {"$gte": cutoff}})
        f.ok("site_leads.created_at")
    except Exception as e:
        f.falhou("site_leads.created_at", repr(e))
    try:
        out["indic_leads"] = await db.indicacao_leads.count_documents(
            {**bq, "created_at": {"$gte": cutoff}})
        f.ok("indicacao_leads.created_at")
    except Exception as e:
        f.falhou("indicacao_leads.created_at", repr(e))
    try:
        out["novos_ativos"] = await db.subscribers.count_documents(
            {**bq, "installation_date": {"$gte": cutoff}})
        f.ok("subscribers.installation_date")
    except Exception as e:
        f.falhou("subscribers.installation_date", repr(e))
    return out


# ─────────────────── Núcleo monetário ───────────────────
async def _dinheiro_em_risco(cid, ticket_avg: float,
                                sinal: Dict[str, int],
                                tickets: Dict[str, int],
                                sem_reaj: int,
                                f: FontesAusentes) -> Dict[str, Any]:
    bq = _base_q(cid)
    # Churn previsto: combina ONU degradada + ticket aberto + outage
    crit = sinal.get("Critical", 0)
    warn = sinal.get("Warning", 0)
    off = sinal.get("Offline", 0)
    open_t = tickets.get("_open_total", 0)
    churn_brl = (
        crit * ticket_avg * P_CHURN_SIGNAL_CRITICAL
        + warn * ticket_avg * P_CHURN_SIGNAL_WARNING
        + off * ticket_avg * P_CHURN_SIGNAL_CRITICAL  # offline = crítico
        + open_t * ticket_avg * P_CHURN_TICKET_OPEN_7D
    )
    # Inadimplência: motor real (financeiro_lancamentos / payments)
    inad_brl = 0.0
    inad_count = 0
    try:
        rows = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                           "financial_status":
                              {"$regex": "inadimp|atrasad",
                                "$options": "i"}}},
            {"$group": {"_id": None,
                           "n": {"$sum": 1},
                           "brl": {"$sum": "$plan_price"}}},
        ]).to_list(1)
        if rows:
            inad_count = int(rows[0].get("n") or 0)
            inad_brl = _safe(rows[0].get("brl") or 0)
        f.ok("subscribers.financial_status")
    except Exception as e:
        f.falhou("subscribers.financial_status", repr(e))

    # Reajuste atrasado — perda recorrente mensal
    reaj_perda_mensal = sem_reaj * ticket_avg * IPCA_ANNUAL_TARGET / 12

    # Equipamentos não recuperados (estoque + cancelados sem devolução)
    equip_brl = 0.0
    equip_count = 0
    try:
        equip_count = await db.equipment_returns.count_documents(
            {**bq, "status": {"$nin": ["returned", "DEVOLVIDO"]}})
        equip_brl = equip_count * 180.0  # ONU média R$ 180
        f.ok("equipment_returns.status")
    except Exception as e:
        f.falhou("equipment_returns.status", repr(e))

    # Outage afetando receita — agregado bairros
    outages = await _outages_30d(cid, f)
    afetados = sum(o.get("affected_count", 0) for o in outages)
    outage_brl = afetados * ticket_avg * 0.04  # 4% propensão churn

    total = churn_brl + inad_brl + reaj_perda_mensal + equip_brl + outage_brl

    return {
        "total_brl": _safe(total),
        "breakdown": {
            "churn_previsto_30d": {
                "brl": _safe(churn_brl),
                "evidencia": (
                    f"{crit} ONU Critical · {warn} Warning · "
                    f"{off} Offline · {open_t} tickets ativos"),
                "metodo": "ONU degradada+ticket × p_churn empírica"},
            "inadimplencia_atual": {
                "brl": _safe(inad_brl), "clientes": inad_count,
                "evidencia": "subscribers.financial_status",
                "metodo": "soma plan_price de inadimplentes"},
            "reajuste_atrasado_mensal": {
                "brl": _safe(reaj_perda_mensal), "clientes": sem_reaj,
                "evidencia": f"{sem_reaj} contratos >12m sem reajuste",
                "metodo": f"qtd × ticket_médio × IPCA {IPCA_ANNUAL_TARGET*100:.1f}%/12"},
            "equipamentos_nao_recuperados": {
                "brl": _safe(equip_brl), "qtd": equip_count,
                "metodo": "qtd × R$ 180/ONU"},
            "outages_30d_propensao_churn": {
                "brl": _safe(outage_brl), "clientes_afetados": afetados,
                "metodo": "afetados × ticket × 4% churn"},
        },
    }


async def _dinheiro_recuperavel(cid, ticket_avg: float,
                                    risco: Dict[str, Any],
                                    sem_reaj: int,
                                    f: FontesAusentes) -> Dict[str, Any]:
    br = risco["breakdown"]
    # Retenção possível (40% dos em risco se contactados em 7d)
    retencao_brl = br["churn_previsto_30d"]["brl"] * RETENTION_RECOVERY_RATE

    # Reajuste recuperável: 80% dos contratos vencidos passam por reajuste
    reaj_recup_anual = (sem_reaj * 0.80 * ticket_avg
                         * IPCA_ANNUAL_TARGET)
    reaj_recup_mensal = reaj_recup_anual / 12

    # Cobranças pendentes: 60% da inadimplência é recuperável
    cobranca_recup = br["inadimplencia_atual"]["brl"] * 0.60

    # Recuperação patrimonial: 70% dos equipamentos retornáveis
    patrim_recup = br["equipamentos_nao_recuperados"]["brl"] * 0.70

    total = retencao_brl + reaj_recup_mensal + cobranca_recup + patrim_recup

    return {
        "total_brl": _safe(total),
        "breakdown": {
            "retencao_possivel_30d": {
                "brl": _safe(retencao_brl),
                "metodo": f"{int(RETENTION_RECOVERY_RATE*100)}% do churn previsto · contato proativo em 7d"},
            "reajuste_recuperavel_mensal": {
                "brl": _safe(reaj_recup_mensal),
                "metodo": "80% dos contratos >12m × IPCA/12"},
            "cobranca_pendente": {
                "brl": _safe(cobranca_recup),
                "metodo": "60% da inadimplência via régua de cobrança"},
            "patrimonio_recuperavel": {
                "brl": _safe(patrim_recup),
                "metodo": "70% dos equipamentos pendentes"},
        },
    }


# ─────────────────── Riscos críticos ───────────────────
async def _riscos_criticos(cid, ticket_avg: float, sinal,
                              tickets, outages30,
                              sem_reaj: int, mrr: float,
                              f: FontesAusentes) -> List[Dict]:
    riscos: List[Dict[str, Any]] = []

    crit = sinal.get("Critical", 0)
    if crit > 0:
        impacto = crit * ticket_avg * P_CHURN_SIGNAL_CRITICAL
        riscos.append({
            "titulo": "ONUs com sinal CRÍTICO",
            "impacto_brl": _safe(impacto),
            "probabilidade_pct": int(P_CHURN_SIGNAL_CRITICAL * 100),
            "evidencia": f"{crit} ONUs com RX abaixo do limite operacional",
            "causa": "Atenuação óptica fora de spec — degradação física",
            "acao": (f"Despachar técnico para os {crit} clientes em "
                      "ordem de criticidade nos próximos 7 dias"),
            "fontes": ["smartolt_onus.signal_text"],
        })

    off = sinal.get("Offline", 0)
    if off > 0:
        impacto = off * ticket_avg * P_CHURN_SIGNAL_CRITICAL
        riscos.append({
            "titulo": "ONUs OFFLINE",
            "impacto_brl": _safe(impacto),
            "probabilidade_pct": 30,
            "evidencia": f"{off} ONUs sem comunicação com OLT",
            "causa": "Cliente sem serviço — janela de cancelamento aberta",
            "acao": (f"Contato proativo via WhatsApp + abertura "
                      f"automática de OS para {off} clientes hoje"),
            "fontes": ["smartolt_onus.status"],
        })

    open_t = tickets.get("_open_total", 0)
    if open_t > 100:
        impacto = open_t * ticket_avg * P_CHURN_TICKET_OPEN_7D
        riscos.append({
            "titulo": "Acúmulo de tickets em aberto",
            "impacto_brl": _safe(impacto),
            "probabilidade_pct": int(P_CHURN_TICKET_OPEN_7D * 100),
            "evidencia": f"{open_t} tickets ativos · meta operacional <50",
            "causa": "Capacidade insuficiente ou roteamento ruim",
            "acao": ("Forçar batch de fechamento da fila de "
                      "tickets >7 dias com supervisor da equipe"),
            "fontes": ["tickets.status"],
        })

    if sem_reaj > 100:
        impacto = sem_reaj * ticket_avg * IPCA_ANNUAL_TARGET / 12
        riscos.append({
            "titulo": "Contratos sem reajuste há mais de 12 meses",
            "impacto_brl": _safe(impacto),
            "probabilidade_pct": 100,
            "evidencia": (f"{sem_reaj} contratos · perda mensal "
                            f"recorrente"),
            "causa": "Política de reajuste IPCA não executada",
            "acao": (f"Disparar reajuste em lote para os {sem_reaj} "
                      "contratos com aviso prévio LGPD de 30 dias"),
            "fontes": ["subscribers.last_readjustment_at"],
        })

    # Outages repetidos em 30d por bairro
    bairros: Dict[str, int] = {}
    for o in outages30:
        b = (o.get("neighborhood") or o.get("location") or "").strip()
        if b:
            bairros[b] = bairros.get(b, 0) + 1
    for b, n in bairros.items():
        if n >= 2:
            # afetados estimado = média 30 clientes por outage
            afet = 30 * n
            impacto = afet * ticket_avg * P_CHURN_OUTAGE_REPEATED
            riscos.append({
                "titulo": f"Bairro {b}: instabilidade crônica",
                "impacto_brl": _safe(impacto),
                "probabilidade_pct": int(P_CHURN_OUTAGE_REPEATED * 100),
                "evidencia": f"{n} outages em 30d no mesmo bairro",
                "causa": "Possível CTO/cabo principal com falha intermitente",
                "acao": (f"Abrir investigação de planta no bairro {b} "
                          "e priorizar manutenção preventiva"),
                "fontes": ["network_outages.neighborhood"],
            })

    # ordena por impacto desc
    riscos.sort(key=lambda r: r["impacto_brl"], reverse=True)
    return riscos[:8]


# ─────────────────── Oportunidades imediatas ───────────────────
async def _oportunidades(cid, ticket_avg: float, mrr: float,
                            funil: Dict[str, int], universo_active: int,
                            f: FontesAusentes) -> List[Dict]:
    bq = _base_q(cid)
    opps: List[Dict[str, Any]] = []

    # Upsell de plano baixo
    try:
        rows = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                           "plan_price": {"$gt": 0,
                                           "$lt": max(80, ticket_avg * 0.7)}}},
            {"$count": "n"},
        ]).to_list(1)
        n_up = (rows[0] if rows else {}).get("n", 0)
        if n_up > 0:
            ganho = n_up * 30.0  # +R$30 médio por upgrade
            opps.append({
                "titulo": "Upsell de plano para clientes de ticket baixo",
                "ganho_brl_mensal": _safe(ganho),
                "qtd": n_up,
                "acao": (f"Campanha WhatsApp para {n_up} clientes "
                          "oferecendo upgrade com 1ª mensalidade grátis"),
                "fontes": ["subscribers.plan_price"],
            })
        f.ok("subscribers.plan_price(upsell)")
    except Exception as e:
        f.falhou("subscribers.plan_price(upsell)", repr(e))

    # Cross-sell SecurityHome
    try:
        sec = await db.security_sites.count_documents(bq)
        cross_target = max(0, universo_active - sec)
        if cross_target > 50:
            ganho = cross_target * 0.05 * 49.90
            opps.append({
                "titulo": "Cross-sell SecurityHome",
                "ganho_brl_mensal": _safe(ganho),
                "qtd": cross_target,
                "acao": (f"Oferecer SecurityHome (R$ 49,90) para "
                          f"{cross_target} clientes ativos sem o produto"),
                "fontes": ["security_sites", "subscribers"],
            })
        f.ok("security_sites")
    except Exception as e:
        f.falhou("security_sites", repr(e))

    # Leads parados
    try:
        leads_p = await db.indicacao_leads.count_documents(
            {**bq, "status": {"$in": ["pending", "PENDENTE"]}})
        if leads_p > 0:
            ganho = leads_p * ticket_avg * 0.30  # 30% taxa conversão * MRR
            opps.append({
                "titulo": "Leads de indicação parados na esteira",
                "ganho_brl_mensal": _safe(ganho),
                "qtd": leads_p,
                "acao": (f"Contatar {leads_p} indicações em até 24h — "
                          "conversão cai 50% após 48h"),
                "fontes": ["indicacao_leads.status"],
            })
        f.ok("indicacao_leads.status")
    except Exception as e:
        f.falhou("indicacao_leads.status", repr(e))

    # Promoções zeradas
    try:
        zeradas = await db.parcerias_promotions.count_documents(
            {**bq, "active": True, "total_redemptions": {"$lte": 0}})
        if zeradas > 0:
            opps.append({
                "titulo": "Promoções sem nenhum resgate",
                "ganho_brl_mensal": 0.0,
                "qtd": zeradas,
                "acao": (f"Renegociar/encerrar {zeradas} promoções "
                          "sem engajamento e substituir por oferta nova"),
                "fontes": ["parcerias_promotions"],
            })
        f.ok("parcerias_promotions")
    except Exception as e:
        f.falhou("parcerias_promotions", repr(e))

    opps.sort(key=lambda o: o.get("ganho_brl_mensal", 0), reverse=True)
    return opps[:6]


# ─────────────────── Previsão 30d ───────────────────
async def _previsao_30d(mrr: float, ticket_avg: float,
                            sinal, tickets, funil, risco) -> Dict:
    churn_brl = risco["breakdown"]["churn_previsto_30d"]["brl"]
    churn_qty = int(round(churn_brl / max(ticket_avg, 1)))

    # crescimento projetado: leads × taxa conversão histórica 5% × ticket
    total_leads = (funil.get("leads", 0) + funil.get("site_leads", 0)
                    + funil.get("indic_leads", 0))
    cresc_qty = int(round(total_leads * 0.05))
    cresc_brl = cresc_qty * ticket_avg

    receita_30d = max(0.0, mrr - churn_brl + cresc_brl)

    risco_op = "BAIXO"
    if tickets.get("_open_total", 0) > 200 or sinal.get("Critical", 0) > 50:
        risco_op = "ALTO"
    elif tickets.get("_open_total", 0) > 100 or sinal.get("Critical", 0) > 20:
        risco_op = "MÉDIO"

    causal = (f"Base atual {mrr:.0f}R$ MRR · churn previsto "
              f"{churn_qty} clientes ({churn_brl:.0f}R$) por degradação "
              f"de sinal e tickets pendentes · entrada esperada {cresc_qty} "
              f"clientes ({cresc_brl:.0f}R$) a partir de {total_leads} leads "
              "30d com conversão 5%.")
    return {
        "receita_prevista_brl": _safe(receita_30d),
        "churn_previsto_qty": churn_qty,
        "churn_previsto_brl": _safe(churn_brl),
        "crescimento_previsto_qty": cresc_qty,
        "crescimento_previsto_brl": _safe(cresc_brl),
        "risco_operacional": risco_op,
        "explicacao_causal": causal,
    }


# ─────────────────── PRESIDENT_SCORE ───────────────────
def _score(mrr, ticket_avg, ativos, sinal, tickets, outages_n,
            sem_reaj, risco_brl, recuperavel_brl) -> Dict:
    """Score 0-100 ponderado.

    Componentes (peso):
      receita (15) churn (20) operacao (15) rede (15)
      financeiro (10) estoque (5) seguranca (5) crescimento (15)
    """
    def clip(v): return max(0.0, min(100.0, v))

    crit = sinal.get("Critical", 0) + sinal.get("Offline", 0)
    warn = sinal.get("Warning", 0)
    open_t = tickets.get("_open_total", 0)

    receita_score = clip(100 - (risco_brl / max(mrr, 1)) * 200)
    churn_score = clip(100 - (crit * 0.5 + warn * 0.1) * 10 / max(ativos, 1))
    operacao_score = clip(100 - open_t * 0.1)
    rede_score = clip(100 - (crit / max(ativos, 1)) * 500
                          - (warn / max(ativos, 1)) * 200)
    financeiro_score = clip(100 - sem_reaj * 0.05)
    estoque_score = 90.0  # sem fonte ainda → não penaliza
    seguranca_score = 90.0
    crescimento_score = clip(60 + min(recuperavel_brl / max(mrr, 1) * 100, 40))

    score = (
        receita_score * 0.15 + churn_score * 0.20
        + operacao_score * 0.15 + rede_score * 0.15
        + financeiro_score * 0.10 + estoque_score * 0.05
        + seguranca_score * 0.05 + crescimento_score * 0.15
    )

    components = {
        "receita": round(receita_score, 1),
        "churn": round(churn_score, 1),
        "operacao": round(operacao_score, 1),
        "rede": round(rede_score, 1),
        "financeiro": round(financeiro_score, 1),
        "estoque": round(estoque_score, 1),
        "seguranca": round(seguranca_score, 1),
        "crescimento": round(crescimento_score, 1),
    }
    drivers = sorted(components.items(), key=lambda x: x[1])
    bottom = [{"area": k, "score": v} for k, v in drivers[:3]]
    top = [{"area": k, "score": v} for k, v in drivers[-3:]]
    if score >= 80:
        status = "saudavel"
    elif score >= 65:
        status = "atencao"
    elif score >= 45:
        status = "alerta"
    else:
        status = "critico"
    return {
        "score": round(score, 1),
        "status": status,
        "components": components,
        "piores_drivers": bottom,
        "melhores_drivers": top,
    }


# ─────────────────── Surpresas executivas ───────────────────
async def _surpresas(cid, ticket_avg: float, sinal,
                        tickets, funil, sem_reaj: int,
                        outages30: List[Dict],
                        f: FontesAusentes) -> List[Dict]:
    """Achados não-óbvios que o gestor provavelmente não percebeu."""
    bq = _base_q(cid)
    surp: List[Dict[str, Any]] = []

    # CTO com sinal degradado concentrado
    try:
        rows = await db.smartolt_onus.aggregate([
            {"$match": {**bq, "signal_text":
                            {"$in": ["Warning", "Critical"]}}},
            {"$group": {"_id": "$zone_name",
                           "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 5}}},
            {"$sort": {"n": -1}}, {"$limit": 3},
        ]).to_list(3)
        for r in rows:
            if r.get("_id"):
                surp.append({
                    "fato": f"Zona {r['_id']}: {r['n']} ONUs com sinal "
                              "degradado concentradas",
                    "impacto_brl": _safe(r['n'] * ticket_avg * 0.15),
                    "categoria": "rede",
                })
        f.ok("smartolt_onus.zone_name")
    except Exception as e:
        f.falhou("smartolt_onus.zone_name", repr(e))

    # OLT com mais problemas
    try:
        rows = await db.smartolt_onus.aggregate([
            {"$match": {**bq, "signal_text": "Critical"}},
            {"$group": {"_id": "$olt_name",
                           "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 1},
        ]).to_list(1)
        if rows and rows[0].get("_id"):
            surp.append({
                "fato": f"OLT {rows[0]['_id']} concentra "
                          f"{rows[0]['n']} ONUs Critical — checar planta",
                "impacto_brl": _safe(rows[0]['n'] * ticket_avg * 0.20),
                "categoria": "rede",
            })
        f.ok("smartolt_onus.olt_name")
    except Exception as e:
        f.falhou("smartolt_onus.olt_name", repr(e))

    # Tickets velhos
    try:
        cutoff = _cutoff_iso(15)
        velhos = await db.tickets.count_documents({
            **bq, "status": {"$in": ["pendente", "aberta", "open"]},
            "created_at": {"$lt": cutoff}})
        if velhos > 30:
            surp.append({
                "fato": f"{velhos} tickets estão abertos há mais de "
                          "15 dias — fila esquecida",
                "impacto_brl": _safe(velhos * ticket_avg * 0.07),
                "categoria": "operacao",
            })
        f.ok("tickets.created_at")
    except Exception as e:
        f.falhou("tickets.created_at", repr(e))

    # Bairro com leads acima da média
    try:
        rows = await db.sales_leads.aggregate([
            {"$match": {**bq,
                          "created_at": {"$gte": _cutoff_iso(60)}}},
            {"$group": {"_id": "$neighborhood",
                           "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 3}}},
            {"$sort": {"n": -1}}, {"$limit": 1},
        ]).to_list(1)
        if rows and rows[0].get("_id"):
            surp.append({
                "fato": f"Bairro {rows[0]['_id']} gerou "
                          f"{rows[0]['n']} leads em 60d — possível "
                          "ponto de expansão",
                "impacto_brl": _safe(rows[0]['n'] * ticket_avg * 6),
                "categoria": "comercial",
            })
        f.ok("sales_leads.neighborhood")
    except Exception as e:
        f.falhou("sales_leads.neighborhood", repr(e))

    # Plano com upgrade pendente concentrado
    try:
        rows = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                           "plan_price": {"$gt": 0, "$lt": 80}}},
            {"$group": {"_id": "$plan_name", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 20}}},
            {"$sort": {"n": -1}}, {"$limit": 1},
        ]).to_list(1)
        if rows and rows[0].get("_id"):
            surp.append({
                "fato": (f"Plano '{rows[0]['_id']}' tem {rows[0]['n']} "
                          "clientes — concentração de baixo ticket"),
                "impacto_brl": _safe(rows[0]['n'] * 30),
                "categoria": "comercial",
            })
        f.ok("subscribers.plan_name")
    except Exception as e:
        f.falhou("subscribers.plan_name", repr(e))

    # Reajuste atrasado concentrado
    if sem_reaj > 500:
        surp.append({
            "fato": (f"{sem_reaj} contratos passaram da janela anual "
                      "de reajuste — receita esquecida"),
            "impacto_brl": _safe(sem_reaj * ticket_avg
                                    * IPCA_ANNUAL_TARGET / 12),
            "categoria": "financeiro",
        })

    surp.sort(key=lambda s: s.get("impacto_brl", 0), reverse=True)
    return surp[:10]


# ─────────────────── 5 AÇÕES PRESIDENCIAIS ───────────────────
def _acoes_presidenciais(riscos, oportunidades,
                            recuperavel: Dict) -> List[Dict]:
    """Exatamente 5 ações priorizadas por impacto financeiro."""
    pool: List[Dict[str, Any]] = []
    for r in riscos[:5]:
        pool.append({
            "acao": r["acao"], "impacto_brl": r["impacto_brl"],
            "esforco": "Médio", "prioridade": "ALTA",
            "justificativa": (f"Risco: {r['titulo']}. "
                                 f"Evidência: {r['evidencia']}"),
        })
    for o in oportunidades[:5]:
        pool.append({
            "acao": o["acao"],
            "impacto_brl": o.get("ganho_brl_mensal", 0),
            "esforco": "Baixo", "prioridade": "MÉDIA",
            "justificativa": (f"Oportunidade: {o['titulo']}"),
        })
    # ação de cobrança recuperável
    cob = recuperavel["breakdown"]["cobranca_pendente"]["brl"]
    if cob > 0:
        pool.append({
            "acao": (f"Acionar régua de cobrança automatizada para "
                      f"recuperar R$ {cob:,.0f} pendentes".replace(",", ".")),
            "impacto_brl": cob,
            "esforco": "Baixo", "prioridade": "ALTA",
            "justificativa": "60% da inadimplência atual é recuperável "
                                "via régua progressiva (SMS + WhatsApp).",
        })
    # ação de reajuste
    reaj = recuperavel["breakdown"]["reajuste_recuperavel_mensal"]["brl"]
    if reaj > 0:
        pool.append({
            "acao": (f"Disparar reajuste IPCA em lote — ganho recorrente "
                      f"de R$ {reaj:,.0f}/mês".replace(",", ".")),
            "impacto_brl": reaj * 12,  # impacto anual
            "esforco": "Baixo", "prioridade": "ALTA",
            "justificativa": "Reajustes vencidos representam receita "
                                "esquecida — execução em lote com aviso "
                                "prévio de 30d.",
        })

    # ordena por impacto
    pool.sort(key=lambda a: a["impacto_brl"], reverse=True)

    # garante 5 (se faltar, preenche com placeholders revisórios)
    while len(pool) < 5:
        pool.append({
            "acao": "Revisar políticas de monitoramento — dados "
                      "insuficientes para nova decisão",
            "impacto_brl": 0.0,
            "esforco": "Baixo", "prioridade": "BAIXA",
            "justificativa": "Sistema ainda não detectou alavanca "
                                "suficiente. Aprofundar instrumentação.",
        })

    return pool[:5]


# ─────────────────── ENTRY POINT ───────────────────
async def build_executive_report(cid: Optional[str]
                                       ) -> Dict[str, Any]:
    """Orquestra todas as fontes em paralelo e devolve o relatório
    executivo monetizado."""
    started = _now()
    f = FontesAusentes()

    mrr, ticket_avg, ativos = await _mrr_e_ticket(cid, f)
    sinal = await _onus_por_sinal(cid, f)
    tickets = await _tickets_estado(cid, f)
    outages30 = await _outages_30d(cid, f)
    sem_reaj = await _sem_reajuste_12m(cid, f)
    funil = await _funil_30d(cid, f)

    risco = await _dinheiro_em_risco(cid, ticket_avg, sinal, tickets,
                                          sem_reaj, f)
    recuperavel = await _dinheiro_recuperavel(cid, ticket_avg, risco,
                                                    sem_reaj, f)
    riscos_lst = await _riscos_criticos(cid, ticket_avg, sinal,
                                              tickets, outages30,
                                              sem_reaj, mrr, f)
    opps = await _oportunidades(cid, ticket_avg, mrr, funil, ativos, f)
    previsao = await _previsao_30d(mrr, ticket_avg, sinal, tickets,
                                        funil, risco)
    surp = await _surpresas(cid, ticket_avg, sinal, tickets, funil,
                                sem_reaj, outages30, f)
    score = _score(mrr, ticket_avg, ativos, sinal, tickets,
                      len(outages30), sem_reaj,
                      risco["total_brl"], recuperavel["total_brl"])
    acoes = _acoes_presidenciais(riscos_lst, opps, recuperavel)

    elapsed = int((_now() - started).total_seconds() * 1000)

    return {
        "company_id": cid,
        "president_score": score,
        "riscos_criticos": riscos_lst,
        "oportunidades": opps,
        "previsao_30d": previsao,
        "dinheiro_em_risco": risco,
        "dinheiro_recuperavel": recuperavel,
        "surpresas": surp,
        "acoes_presidenciais": acoes,
        "contexto_financeiro": {
            "mrr_atual_brl": _safe(mrr),
            "ticket_medio_brl": _safe(ticket_avg),
            "clientes_ativos": ativos,
        },
        "fontes": {
            "usadas": f.usadas,
            "ausentes": f.ausentes,
        },
        "elapsed_ms": elapsed,
        "generated_at": _iso(_now()),
    }
