"""ai_center_v7.py — Endpoints REST V7 EXECUÇÃO REAL."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from core import require_role
from services import execution_v7 as v7

router = APIRouter(prefix="/api/ai-center/v7", tags=["execution-v7"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get(
        "company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente.")
    return cid


@router.post("/tickets/backfill-category")
async def backfill_cat(
    window_days: int = Query(90, ge=1, le=365),
    dry_run: bool = Query(False),
    user=Depends(require_role("administrador"))):
    return await v7.backfill_tickets(_co(user),
                                      window_days=window_days,
                                      dry_run=dry_run)


@router.get("/install/predict/{subscriber_id}")
async def predict_install(subscriber_id: str,
                          user=Depends(require_role("administrador",
                                                    "gestor"))):
    return await v7.predict_install_resources(_co(user),
                                               subscriber_id)


@router.get("/repair/predict/{ticket_id}")
async def predict_repair(ticket_id: str,
                         user=Depends(require_role("administrador",
                                                   "gestor"))):
    return await v7.predict_repair_outcome(_co(user), ticket_id)


@router.get("/install/audit/{install_id}")
async def audit_install(install_id: str,
                        user=Depends(require_role("administrador",
                                                  "auditor"))):
    return await v7.audit_install(_co(user), install_id)


class PaymentIn(BaseModel):
    client_id: Optional[str] = None
    amount_BRL: float = Field(..., ge=0)
    provider: str = "manual"
    payment_ref: Optional[str] = None
    paid_at: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("/payment/received")
async def payment_received(body: PaymentIn,
                           user=Depends(require_role("administrador",
                                                     "financeiro"))):
    return await v7.payment_received(
        _co(user),
        client_id=body.client_id, amount_BRL=body.amount_BRL,
        provider=body.provider, payment_ref=body.payment_ref,
        paid_at=body.paid_at, metadata=body.metadata)


@router.post("/operacao-tese/run-batch")
async def run_batch(batch_size: int = Query(10, ge=1, le=100),
                    user=Depends(require_role("administrador"))):
    return await v7.operacao_tese_run_batch(_co(user),
                                             batch_size=batch_size)


@router.get("/proof-of-value")
async def proof(window_days: int = Query(30, ge=1, le=365),
                user=Depends(require_role("administrador", "auditor",
                                          "gestor"))):
    return await v7.proof_of_value(_co(user),
                                    window_days=window_days)


@router.post("/action-to-cash/backfill-from-invoices")
async def backfill_a2c(window_days: int = Query(90, ge=1, le=365),
                       dry_run: bool = Query(True),
                       user=Depends(require_role("administrador",
                                                 "financeiro"))):
    """V7.1 G1 — fecha outcomes via invoices PAGAS. dry_run=true
    default para auditoria antes da execução real."""
    from services import v7_1_backfill
    return await v7_1_backfill.backfill_action_to_cash(
        _co(user), window_days=window_days, dry_run=dry_run)


# ═══════════════════════════════════════════════════════════
# V7.2 G1 FIX — endpoints corrigidos (schema-tolerant)
# ═══════════════════════════════════════════════════════════
@router.post("/action-to-cash/backfill-v72")
async def backfill_a2c_v72(
    window_days: int = Query(365, ge=1, le=730),
    dry_run: bool = Query(True),
    limit: int = Query(10000, ge=1, le=20000),
    user=Depends(require_role("administrador", "financeiro"))):
    """V7.2 — fix: resolve subscriber_id via actions/decisions,
    normaliza external_code (ATLAZ-prefix), aceita outcome_id."""
    from services import v7_2_revenue
    return await v7_2_revenue.backfill_action_to_cash_v72(
        _co(user), window_days=window_days,
        dry_run=dry_run, limit=limit)


@router.get("/revenue/truth")
async def revenue_truth(
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(require_role("administrador", "financeiro",
                              "auditor", "gestor"))):
    """V7.2 G1 — fonte-de-verdade da receita (3 leituras):
       revenue_total_BRL (invoices pagas), revenue_attributed_to_ai_BRL
       (motor IA fechou), revenue_organic_BRL (resto).
       Plus: corporate_realization_pct e motor_realization_pct."""
    from services import v7_2_revenue
    return await v7_2_revenue.revenue_realization_truth(
        _co(user), window_days=window_days)


# ═══════════════════════════════════════════════════════════
# V7.2.2 G2/G3 — Backfill puro de qualidade (sem novos módulos)
# ═══════════════════════════════════════════════════════════
@router.post("/data-quality/backfill-g2-g3")
async def backfill_g2_g3(
    dry_run: bool = Query(True),
    user=Depends(require_role("administrador", "auditor"))):
    """G2 (assigned_to) + G3 (category) backfill idempotente.
    Usa apenas dados existentes — sem criar novas IAs."""
    from services import v7_2_2_data_quality
    return await v7_2_2_data_quality.backfill_quality(
        _co(user), dry_run=dry_run)


@router.get("/data-quality/audit")
async def audit_v722(
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """Relatório executivo V7.2.2: recalcula motores existentes
    (company_score, technician, smart_field)."""
    from services import v7_2_2_data_quality
    return await v7_2_2_data_quality.executive_audit(
        _co(user), window_days=window_days)


# ═══════════════════════════════════════════════════════════
# V9 P2.3 — Telemetria de adoção dos campos V9 (Smart Field)
# ═══════════════════════════════════════════════════════════
@router.get("/v9/smart-field-adoption")
async def v9_adoption(
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """V9 P2.3 — cobertura 7d/30d/total + ranking técnico/equipe +
    lista pendente. Apenas leitura, sem alteração de dados."""
    from services import v7_2_2_data_quality
    return await v7_2_2_data_quality.smart_field_adoption(_co(user))


# ═══════════════════════════════════════════════════════════
# V7.3 — Backfill tickets.opened_at (G4)
# ═══════════════════════════════════════════════════════════
@router.post("/backfill-opened-at")
async def backfill_opened_at(
    dry_run: bool = Query(True),
    user=Depends(require_role("administrador", "auditor"))):
    """G4 backfill idempotente de tickets.opened_at via
    created_at → equipment_history.captured_at → closed_at-avg."""
    from services import v7_2_2_data_quality
    return await v7_2_2_data_quality.backfill_opened_at(
        _co(user), dry_run=dry_run)


@router.get("/opened-at-audit")
async def opened_at_audit(
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """Cobertura de opened_at + fontes usadas (dry-run, sem efeito)."""
    from services import v7_2_2_data_quality
    return await v7_2_2_data_quality.backfill_opened_at(
        _co(user), dry_run=True)


# ═══════════════════════════════════════════════════════════
# V8.1 — Homologação operacional completa (simulador)
# ═══════════════════════════════════════════════════════════
@router.post("/v8/homolog/run-batch")
async def v8_run_batch(
    n_install: int = Query(100, ge=0, le=1000),
    n_repair: int = Query(100, ge=0, le=1000),
    n_withdraw: int = Query(50, ge=0, le=500),
    simulation_run_id: Optional[str] = Query(None),
    tag_legacy: bool = Query(True),
    user=Depends(require_role("administrador", "auditor"))):
    """V8.1 — gera massa de teste em company_id='co-homolog-v8'
    idempotente. Não toca produção."""
    from services import v8_1_simulator
    return await v8_1_simulator.run_homolog_batch(
        n_install=n_install, n_repair=n_repair,
        n_withdraw=n_withdraw,
        simulation_run_id=simulation_run_id,
        tag_legacy=tag_legacy)


@router.get("/v8/homolog/validate")
async def v8_validate(
    window_days: int = Query(90, ge=1, le=365),
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """V8.1 — recalcula motores existentes em co-homolog-v8."""
    from services import v8_1_simulator
    return await v8_1_simulator.validate_engines(
        window_days=window_days)


@router.get("/v8/homolog/coverage")
async def v8_coverage(
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """V8.1 — % preenchimento dos campos V8.1 + anti-contaminação."""
    from services import v8_1_simulator
    return await v8_1_simulator.coverage_report()


# ═══════════════════════════════════════════════════════════
# V8.2 — Primeiro R$ atribuído ao motor IA (ciclo E→D→A→C→L)
# ═══════════════════════════════════════════════════════════
class FirstCashIn(BaseModel):
    subscriber_id: str
    invoice_id: str
    expected_BRL: float = Field(..., ge=0)
    real_phone_redacted: Optional[str] = None


@router.post("/v8/first-cash")
async def v8_first_cash(
    body: FirstCashIn,
    user=Depends(require_role("administrador", "auditor"))):
    """V8.2 — fecha ciclo Evento→Decisão→Ação→Cash→Learning para 1
    cliente real + invoice paga real. WA bloqueado/redirecionado para
    TEST_PHONE. Atribui actual_BRL real ao motor IA."""
    from services import v8_2_first_cash
    return await v8_2_first_cash.execute_first_cash_cycle(
        company_id=_co(user),
        subscriber_id=body.subscriber_id,
        invoice_id=body.invoice_id,
        expected_BRL=body.expected_BRL,
        real_phone_redacted=body.real_phone_redacted)


# ═══════════════════════════════════════════════════════════
# V8.3 — Infraestrutura de causalidade + evidências expandidas
# ═══════════════════════════════════════════════════════════
@router.get("/v8/causality/batch-validation")
async def v83_batch_validation(
    limit: int = Query(5000, ge=100, le=20000),
    user=Depends(require_role("administrador", "auditor"))):
    """V8.3 — classifica invoices PAID como ATTRIBUTED ou
    NOT_ATTRIBUTED ao motor IA. Não inventa causalidade."""
    from services import v8_3_causality
    return await v8_3_causality.batch_revenue_validation(
        _co(user), limit=limit)


@router.get("/v8/causality/calibrate-expected")
async def v83_calibrate(
    user=Depends(require_role("administrador", "auditor",
                              "financeiro"))):
    """V8.3 — auditoria de motor_ia_actions.operacao_tese_tier_c
    com expected_BRL=0. Apenas relatório (advisory_only)."""
    from services import v8_3_causality
    return await v8_3_causality.calibrate_expected_brl(_co(user))


@router.post("/v8/causality/run-pilot")
async def v83_run_pilot(
    n_treatment: int = Query(50, ge=10, le=500),
    n_control: int = Query(50, ge=10, le=500),
    window_days: int = Query(14, ge=1, le=90),
    treatment_payment_rate: float = Query(0.58, ge=0, le=1),
    control_payment_rate: float = Query(0.32, ge=0, le=1),
    cleanup: bool = Query(True),
    user=Depends(require_role("administrador", "auditor"))):
    """V8.3 — dry-run da infraestrutura causal com dados sintéticos.
    Não envia WhatsApp. Não toca clientes reais."""
    from services import v8_3_causality
    return await v8_3_causality.run_pilot(
        n_treatment=n_treatment, n_control=n_control,
        window_days=window_days,
        treatment_payment_rate=treatment_payment_rate,
        control_payment_rate=control_payment_rate,
        cleanup=cleanup, dry_run=True)


@router.get("/v8/causality/lift/{cohort_id}")
async def v83_lift(
    cohort_id: str,
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """V8.3 — calcula lift do cohort (matemática pura, sem IA)."""
    from services import v8_3_causality
    return await v8_3_causality.compute_lift(cohort_id)


# ═══════════════════════════════════════════════════════════
# V8.4 — Piloto controlado com pareamento real
# ═══════════════════════════════════════════════════════════
@router.get("/v8/v84/eligible-count")
async def v84_eligible_count(
    user=Depends(require_role("administrador", "auditor"))):
    """V8.4 — FASE 1: conta candidatos elegíveis ao piloto.
    Não persiste, não envia."""
    from services import v8_4_cohort
    elig = await v8_4_cohort.list_eligible_candidates(
        _co(user), limit=10000)
    return {"company_id": _co(user),
            "n_eligible": len(elig),
            "sample_first_5_redacted": [
                {"sub": e["subscriber_id"][:8] + "***",
                 "branch": e["branch"],
                 "plan_price": e["plan_price"],
                 "invoice_amount": e["invoice_amount"],
                 "days_overdue": e["days_overdue"],
                 "n_paid_history": e["n_paid_history"]}
                for e in elig[:5]]}


class V84PilotIn(BaseModel):
    label: str
    pilot_size: int = Field(50, ge=10, le=500)
    window_days: int = Field(14, ge=1, le=90)
    authorize_real_send: bool = False
    dispatch: bool = True
    seed: int = 42


@router.post("/v8/v84/run-pilot")
async def v84_run_pilot(
    body: V84PilotIn,
    user=Depends(require_role("administrador", "auditor"))):
    """V8.4 — orquestra cohort completo. Dispatch (se habilitado)
    passa pelo gateway homologation. authorize_real_send=False
    significa todos os envios redirecionam para TEST_PHONE."""
    from services import v8_4_cohort
    return await v8_4_cohort.run_pilot_v84(
        company_id=_co(user), label=body.label,
        pilot_size=body.pilot_size,
        window_days=body.window_days,
        authorize_real_send=body.authorize_real_send,
        dispatch=body.dispatch, seed=body.seed)


@router.post("/v8/v84/attribution/{cohort_id}")
async def v84_attribution(
    cohort_id: str,
    user=Depends(require_role("administrador", "auditor"))):
    """V8.4 — varre invoices PAID na janela e marca members."""
    from services import v8_4_cohort
    return await v8_4_cohort.attribution_window(cohort_id)


@router.get("/v8/v84/lift/{cohort_id}")
async def v84_lift(
    cohort_id: str,
    user=Depends(require_role("administrador", "auditor",
                              "gestor"))):
    """V8.4 — calcula lift + z-test + persiste motor_ia_causality."""
    from services import v8_4_cohort
    return await v8_4_cohort.calculate_lift(cohort_id)
