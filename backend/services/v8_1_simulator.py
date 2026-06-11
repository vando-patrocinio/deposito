"""
v8_1_simulator.py — V8.1 SIMULADOR OPERACIONAL HOMOLOGAÇÃO

Gera massa de teste 100% auditável (250 cenários), com:
  environment="homolog"
  service_mode="simulated"

NÃO contata clientes reais. NÃO envia WhatsApp real. Quando precisa
gerar uma "mensagem", usa exclusivamente homologation.safe_send_whatsapp
que redireciona para TEST_PHONE=5521998176526.

Idempotente via simulation_run_id (mesmo run_id ⇒ nenhuma duplicata).

Sem novas IAs, sem novos scores, sem novos dashboards. Apenas
PERSISTÊNCIA + AUDITORIA.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import random
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from database import db

logger = logging.getLogger("v8_1_simulator")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

HOMOLOG_COMPANY = "co-homolog-v8"
TEST_PHONE = "5521998176526"

# ═══════════════════════════════════════════════════════════
# Catálogos para variedade realista (estatísticos, não pessoais)
# ═══════════════════════════════════════════════════════════
INSTALL_CTOS = ["CTO-A-01", "CTO-A-02", "CTO-B-01", "CTO-B-02",
                "CTO-C-01", "CTO-C-02", "CTO-D-01"]
INSTALL_VLANS = [100, 200, 300, 400]
ONU_PREFIX = ["ALCL", "HWTC", "ZTEG", "FHTT"]

REPAIR_ROOT_CAUSES = [
    "fibra_rompida", "conector_oxidado", "onu_defeituosa",
    "config_pppoe", "interferencia_wifi", "queda_energia_local",
    "porta_olt_defeito", "cabo_drop_danificado",
    "cliente_desligou_equipamento", "splitter_saturado"]

WITHDRAW_CONDITIONS = ["bom", "regular", "danificado", "perdido"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:12]}"


def _rand_iso_past(days_back_max: int = 60) -> str:
    delta = random.randint(0, days_back_max * 24 * 60)
    return (datetime.now(timezone.utc)
            - timedelta(minutes=delta)).isoformat()


async def _pick_real_tech_id(company_id: str) -> Optional[str]:
    """Pega um collaborator real para usar como `technician_id`
    estatístico — sem comunicação."""
    cols = await db.collaborators.find({
        "company_id": company_id, "active": True
    }, {"id": 1}).to_list(50)
    if cols:
        return random.choice(cols).get("id")
    # Fallback: tenta co-demo como base estrutural
    cols = await db.collaborators.find({
        "company_id": "co-demo", "active": True
    }, {"id": 1}).to_list(50)
    if cols:
        return random.choice(cols).get("id")
    return f"col-sim-{uuid.uuid4().hex[:8]}"


async def _pick_onu_baseline(company_id: str) -> Dict[str, Any]:
    """Usa ONU real APENAS como base estrutural (sinal/serial).
    Nada relacionado a contato — só números técnicos."""
    onu = await db.smartolt_onus.find_one({
        "company_id": "co-demo",
        "signal_1310": {"$exists": True, "$nin": [None, ""]}})
    base_signal = -22.0
    if onu:
        try:
            base_signal = float(
                str(onu.get("signal_1310")).replace(",", "."))
        except (TypeError, ValueError):
            pass
    serial = (random.choice(ONU_PREFIX)
              + "".join(random.choices(
                  "0123456789ABCDEF", k=8)))
    return {"signal_baseline": base_signal, "serial": serial}


# ═══════════════════════════════════════════════════════════
# FASE 1.5 — Tag tickets reais como production_legacy
# ═══════════════════════════════════════════════════════════
async def tag_legacy_tickets(
    legacy_company_id: str = "co-demo",
) -> Dict[str, Any]:
    """Marca tickets reais existentes com environment=production_legacy
    e service_mode=null para auditoria limpa. Idempotente."""
    q = {"company_id": legacy_company_id,
         "environment": {"$exists": False}}
    n = await db.tickets.count_documents(q)
    if n == 0:
        return {"company_id": legacy_company_id, "tagged": 0,
                "already_tagged_count": await db.tickets.count_documents({
                    "company_id": legacy_company_id,
                    "environment": "production_legacy"})}
    res = await db.tickets.update_many(q, {"$set": {
        "environment": "production_legacy",
        "service_mode": None,
        "legacy_tagged_at": _now_iso()}})
    return {"company_id": legacy_company_id,
            "tagged": res.modified_count,
            "generated_at": _now_iso()}


# ═══════════════════════════════════════════════════════════
# Geradores idempotentes por simulation_run_id
# ═══════════════════════════════════════════════════════════
def _stable_ticket_id(run_id: str, kind: str, idx: int) -> str:
    """Mesmo run_id+kind+idx ⇒ mesmo ticket_id ⇒ idempotente."""
    return f"sim-{kind}-{run_id}-{idx:04d}"


def _stable_smart_id(run_id: str, kind: str, idx: int) -> str:
    return f"sf{kind[0]}-{run_id}-{idx:04d}"


async def _persist_simulated_ticket(
    company_id: str, ticket_id: str, kind: str,
    tech_id: str, started: str, finished: Optional[str],
    completion_data: Dict[str, Any], run_id: str,
    extra_ticket_fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Cria ticket associado idempotente."""
    cat_map = {"install": "INSTALL", "repair": "REPAIR",
               "withdraw": "WITHDRAW"}
    type_map = {"install": "instalacao", "repair": "reparo",
                "withdraw": "retirada"}
    doc = {
        "id": ticket_id,
        "company_id": company_id,
        "client_id": f"sim-client-{run_id}-{ticket_id[-4:]}",
        "type": type_map[kind],
        "category": cat_map[kind],
        "status": "finalizada" if finished else "aberta",
        "priority": "normal",
        "assigned_collaborator_id": tech_id,
        "assigned_to": tech_id,
        "opened_at": started,
        "closed_at": finished,
        "started_at": started,
        "finished_at": finished,
        "outcome": "sucesso" if finished else None,
        "completion_data": completion_data,
        # Marcas V8.1
        "environment": "homolog",
        "service_mode": "simulated",
        "simulation_run_id": run_id,
        "simulated": True,
        "created_at": started,
        "category_source": "v8_1_simulator",
        "source_backfill_assigned_to": "v8_1_simulator",
    }
    if extra_ticket_fields:
        doc.update(extra_ticket_fields)
    await db.tickets.update_one(
        {"id": ticket_id, "company_id": company_id},
        {"$set": doc}, upsert=True)


# ═══════════════════════════════════════════════════════════
# FASE 2 — SIMULADORES
# ═══════════════════════════════════════════════════════════
async def simulate_installation(
    company_id: str = HOMOLOG_COMPANY, n: int = 100,
    simulation_run_id: Optional[str] = None,
    success_rate: float = 0.78,
) -> Dict[str, Any]:
    """Gera N instalações simuladas. FTC ~78% (realista)."""
    run_id = simulation_run_id or _new("run")[4:]
    created = updated = 0
    for i in range(n):
        ticket_id = _stable_ticket_id(run_id, "install", i)
        smart_id = _stable_smart_id(run_id, "install", i)
        is_success = random.random() < success_rate
        started = _rand_iso_past(30)
        # finished_at: ~95% concluídos
        finished = (datetime.fromisoformat(started)
                    + timedelta(hours=random.uniform(1, 4))
                    ).isoformat() if random.random() < 0.95 else None
        tech_id = await _pick_real_tech_id(company_id)
        onu = await _pick_onu_baseline(company_id)
        signal_before = round(onu["signal_baseline"]
                              + random.uniform(-2, 0), 2)
        signal_after = round(random.uniform(-23, -15), 2)
        cto = random.choice(INSTALL_CTOS)
        vlan = random.choice(INSTALL_VLANS)

        # Smart install completo
        smart_doc = {
            "id": smart_id, "company_id": company_id,
            "ticket_id": ticket_id,
            "client_id": f"sim-client-{run_id}-{i:04d}",
            "kind": "install",
            "status": "completed" if finished else "in_progress",
            # COMMON_FIELDS
            "service_mode": "simulated",
            "environment": "homolog",
            "technician_id": tech_id,
            "tech_id": tech_id,  # alias legado
            "started_at": started,
            "finished_at": finished,
            "customer_confirmed": is_success,
            "execution_notes": (
                "Instalação concluída com sucesso. "
                "Cliente treinado no uso do roteador."
                if is_success else
                "Instalação parcial — necessária revisita."),
            "photos_count": random.randint(3, 8),
            "geo_check_in": True,
            # INSTALLATION_FIELDS
            "signal_before": signal_before,
            "signal_after": signal_after,
            "signal_after_install_dbm": signal_after,  # alias V6
            "onu_serial": onu["serial"],
            "ont_sn": onu["serial"],  # alias V6
            "cto": cto,
            "vlan": vlan,
            "wifi_test_done": is_success,
            "speed_test_done": is_success,
            "customer_trained": is_success,
            # V6 derived
            "first_time_complete": is_success,
            "installation_quality_score":
                100 if is_success else 60,
            "reopened": not is_success and random.random() < 0.3,
            "subject": "Instalação simulada V8.1",
            "priority": "normal",
            "scheduled_at": started,
            # Auditoria V8.1
            "simulation_run_id": run_id,
            "simulated": True,
            "created_at": started,
            "updated_at": _now_iso(),
        }
        completion = {
            "sinal": signal_after,
            "ont": onu["serial"],
            "cto": cto, "vlan": vlan,
            "fotos_count": smart_doc["photos_count"],
            "observacoes": smart_doc["execution_notes"],
            "wifi_ok": smart_doc["wifi_test_done"],
            "speed_ok": smart_doc["speed_test_done"],
            "treinado": smart_doc["customer_trained"],
        }
        await _persist_simulated_ticket(
            company_id, ticket_id, "install",
            tech_id, started, finished, completion, run_id,
            extra_ticket_fields={
                "reopened": smart_doc["reopened"],
                "photos_count": smart_doc["photos_count"],
                "ont_sn": onu["serial"],
            })
        r = await db.smart_installs.update_one(
            {"id": smart_id, "company_id": company_id},
            {"$set": smart_doc}, upsert=True)
        if r.upserted_id:
            created += 1
        else:
            updated += 1
    return {
        "kind": "installation", "company_id": company_id,
        "simulation_run_id": run_id, "n_requested": n,
        "created": created, "updated_idempotent": updated,
        "target_success_rate": success_rate,
        "generated_at": _now_iso(),
    }


async def simulate_repair(
    company_id: str = HOMOLOG_COMPANY, n: int = 100,
    simulation_run_id: Optional[str] = None,
    remote_rate: float = 0.72,
) -> Dict[str, Any]:
    """Gera N reparos. 72% resolved_remotely=True (realista)."""
    run_id = simulation_run_id or _new("run")[4:]
    created = updated = 0
    for i in range(n):
        ticket_id = _stable_ticket_id(run_id, "repair", i)
        smart_id = _stable_smart_id(run_id, "repair", i)
        remote = random.random() < remote_rate
        started = _rand_iso_past(60)
        finished = (datetime.fromisoformat(started)
                    + timedelta(hours=(0.2 if remote else 4)
                                + random.uniform(0, 2))
                    ).isoformat()
        tech_id = await _pick_real_tech_id(company_id)
        root_cause = random.choice(REPAIR_ROOT_CAUSES)
        # Quando truck roll: realmente troca peça
        replaced_onu = (not remote
                        and root_cause == "onu_defeituosa")
        replaced_drop = (not remote
                         and root_cause in
                         ("fibra_rompida", "cabo_drop_danificado"))
        changed_port = (not remote
                        and root_cause == "porta_olt_defeito")
        changed_cto = (not remote
                       and root_cause == "splitter_saturado")
        # Retrabalho: 8% dos reparos
        reopened = random.random() < 0.08

        smart_doc = {
            "id": smart_id, "company_id": company_id,
            "ticket_id": ticket_id,
            "client_id": f"sim-client-{run_id}-{i:04d}",
            "kind": "repair",
            "status": "completed",
            # COMMON
            "service_mode": "simulated",
            "environment": "homolog",
            "technician_id": tech_id, "tech_id": tech_id,
            "started_at": started, "finished_at": finished,
            "customer_confirmed": not reopened,
            "execution_notes": (
                f"Reparo concluído remotamente — {root_cause}"
                if remote else
                f"Reparo presencial — causa: {root_cause}"),
            "photos_count": 0 if remote else random.randint(2, 5),
            "geo_check_in": not remote,
            # REPAIR_FIELDS
            "root_cause": root_cause,
            "replaced_onu": replaced_onu,
            "replaced_drop": replaced_drop,
            "changed_port": changed_port,
            "changed_cto": changed_cto,
            "truck_roll_avoidable": remote,
            "resolved_remotely": remote,
            # V6 derived
            "remote_attempt_first": True,
            "remote_resolved": remote,
            "truck_roll_avoided": remote,
            "reopened": reopened,
            "reopened_within_7d": reopened,
            "subject": "Reparo simulado V8.1",
            "priority": "alta" if not remote else "normal",
            "scheduled_at": started,
            "simulation_run_id": run_id, "simulated": True,
            "created_at": started, "updated_at": _now_iso(),
        }
        completion = {
            "root_cause": root_cause,
            "remote": remote,
            "replaced": {
                "onu": replaced_onu, "drop": replaced_drop,
                "port": changed_port, "cto": changed_cto},
            "observacoes": smart_doc["execution_notes"],
        }
        await _persist_simulated_ticket(
            company_id, ticket_id, "repair",
            tech_id, started, finished, completion, run_id,
            extra_ticket_fields={
                # _ensure_smart_record em company_v6 lê estes
                "resolution_kind": "remote" if remote else "onsite",
                "reopened": reopened,
                "photos_count": smart_doc["photos_count"],
            })
        r = await db.smart_repairs.update_one(
            {"id": smart_id, "company_id": company_id},
            {"$set": smart_doc}, upsert=True)
        if r.upserted_id:
            created += 1
        else:
            updated += 1
    return {
        "kind": "repair", "company_id": company_id,
        "simulation_run_id": run_id, "n_requested": n,
        "created": created, "updated_idempotent": updated,
        "target_remote_rate": remote_rate,
        "generated_at": _now_iso(),
    }


async def simulate_withdrawal(
    company_id: str = HOMOLOG_COMPANY, n: int = 50,
    simulation_run_id: Optional[str] = None,
    recovery_rate: float = 0.76,
) -> Dict[str, Any]:
    """Gera N retiradas. 76% asset_recovered (realista)."""
    run_id = simulation_run_id or _new("run")[4:]
    created = updated = 0
    for i in range(n):
        ticket_id = _stable_ticket_id(run_id, "withdraw", i)
        smart_id = _stable_smart_id(run_id, "withdraw", i)
        recovered = random.random() < recovery_rate
        started = _rand_iso_past(45)
        finished = (datetime.fromisoformat(started)
                    + timedelta(hours=random.uniform(0.5, 2.5))
                    ).isoformat()
        tech_id = await _pick_real_tech_id(company_id)
        onu = await _pick_onu_baseline(company_id)
        router_sn = ("RT-"
                     + "".join(random.choices(
                         "0123456789ABCDEF", k=10)))
        condition = (random.choices(
            WITHDRAW_CONDITIONS, weights=[60, 25, 10, 5], k=1)[0]
            if recovered else "perdido")
        signed = recovered and random.random() < 0.88

        smart_doc = {
            "id": smart_id, "company_id": company_id,
            "ticket_id": ticket_id,
            "client_id": f"sim-client-{run_id}-{i:04d}",
            "kind": "withdraw",
            "status": "completed",
            # COMMON
            "service_mode": "simulated",
            "environment": "homolog",
            "technician_id": tech_id, "tech_id": tech_id,
            "started_at": started, "finished_at": finished,
            "customer_confirmed": signed,
            "execution_notes": (
                f"Retirada concluída. Equipamento {condition}."
                if recovered else
                "Equipamento NÃO recuperado (cliente sem contato)."),
            "photos_count": random.randint(1, 4) if recovered else 0,
            "geo_check_in": True,
            # WITHDRAWAL_FIELDS
            "equipment_recovered": recovered,
            "recovered_onu_serial": onu["serial"] if recovered else None,
            "recovered_router": router_sn if recovered else None,
            "signed_receipt": signed,
            "asset_condition": condition,
            # V6 derived
            "asset_recovered": recovered,
            "asset_recovery_score": 100 if recovered else 0,
            "reopened": False,
            "subject": "Retirada simulada V8.1",
            "priority": "normal",
            "scheduled_at": started,
            "simulation_run_id": run_id, "simulated": True,
            "created_at": started, "updated_at": _now_iso(),
        }
        completion = {
            "recovered": recovered,
            "condition": condition,
            "onu_sn": smart_doc["recovered_onu_serial"],
            "router_sn": smart_doc["recovered_router"],
            "signed": signed,
        }
        await _persist_simulated_ticket(
            company_id, ticket_id, "withdraw",
            tech_id, started, finished, completion, run_id,
            extra_ticket_fields={
                # _ensure_smart_record em company_v6 lê estes
                "asset_recovered": recovered,
                "signed_receipt": signed,
                "photos_count": smart_doc["photos_count"],
            })
        r = await db.smart_withdrawals.update_one(
            {"id": smart_id, "company_id": company_id},
            {"$set": smart_doc}, upsert=True)
        if r.upserted_id:
            created += 1
        else:
            updated += 1
    return {
        "kind": "withdrawal", "company_id": company_id,
        "simulation_run_id": run_id, "n_requested": n,
        "created": created, "updated_idempotent": updated,
        "target_recovery_rate": recovery_rate,
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# Orquestrador V8.1 (gera 250 cenários completos)
# ═══════════════════════════════════════════════════════════
async def run_homolog_batch(
    company_id: str = HOMOLOG_COMPANY,
    n_install: int = 100, n_repair: int = 100, n_withdraw: int = 50,
    simulation_run_id: Optional[str] = None,
    tag_legacy: bool = True,
) -> Dict[str, Any]:
    """Executa todo o ciclo V8.1 idempotente."""
    run_id = simulation_run_id or _new("run")[4:]
    legacy = None
    if tag_legacy:
        legacy = await tag_legacy_tickets("co-demo")
    inst = await simulate_installation(
        company_id, n_install, run_id)
    rep = await simulate_repair(company_id, n_repair, run_id)
    wd = await simulate_withdrawal(company_id, n_withdraw, run_id)
    return {
        "simulation_run_id": run_id,
        "company_id": company_id,
        "test_phone_redirect": TEST_PHONE,
        "legacy_tagging": legacy,
        "installation": inst,
        "repair": rep,
        "withdrawal": wd,
        "totals": {
            "smart_installs": inst["created"] + inst[
                "updated_idempotent"],
            "smart_repairs": rep["created"] + rep[
                "updated_idempotent"],
            "smart_withdrawals": wd["created"] + wd[
                "updated_idempotent"],
            "grand_total":
                (inst["created"] + inst["updated_idempotent"]
                 + rep["created"] + rep["updated_idempotent"]
                 + wd["created"] + wd["updated_idempotent"]),
        },
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 3 — Validação (recálculo dos motores existentes)
# ═══════════════════════════════════════════════════════════
async def validate_engines(
    company_id: str = HOMOLOG_COMPANY, window_days: int = 90,
) -> Dict[str, Any]:
    """Executa sync + score + smart_field + ranking SEM criar nada novo."""
    from services import company_v6
    sync = await company_v6.sync_smart_field_ops(
        company_id, window_days=window_days)
    score = await company_v6.autonomous_company_score(
        company_id, window_days=window_days)
    sk = await company_v6.smart_field_ops_kpis(
        company_id, window_days=window_days)
    twin = await company_v6.digital_twin_summary(
        company_id, window_days=window_days)
    try:
        from services import ops_v51
        techs = await ops_v51.technician_ranking(
            company_id, window_days=window_days, limit=20)
    except Exception:
        techs = []
    return {
        "company_id": company_id,
        "window_days": window_days,
        "sync_field_ops": sync,
        "company_score": score.get("score"),
        "classification": score.get("classification"),
        "components": score.get("components"),
        "smart_field_kpis": sk,
        "digital_twin_overall_score": twin.get("overall_score"),
        "technician_ranking_size": len(techs),
        "technician_avg": (
            round(sum(t["score"] for t in techs) / max(len(techs), 1), 2)
            if techs else 0),
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 4 — Relatório de cobertura final (auditoria V8.1)
# ═══════════════════════════════════════════════════════════
COMMON_FIELDS = ["service_mode", "environment", "technician_id",
                 "started_at", "finished_at", "customer_confirmed",
                 "execution_notes", "photos_count"]
INSTALL_FIELDS = ["signal_before", "signal_after", "onu_serial",
                  "cto", "vlan", "wifi_test_done",
                  "speed_test_done", "customer_trained"]
REPAIR_FIELDS = ["root_cause", "replaced_onu", "replaced_drop",
                 "changed_port", "changed_cto",
                 "truck_roll_avoidable", "resolved_remotely"]
WITHDRAW_FIELDS = ["equipment_recovered", "recovered_onu_serial",
                   "recovered_router", "signed_receipt",
                   "asset_condition"]


async def coverage_report(
    company_id: str = HOMOLOG_COMPANY,
) -> Dict[str, Any]:
    """% de preenchimento dos campos requeridos V8.1."""
    async def cov(col: str, field: str) -> Dict[str, Any]:
        total = await db[col].count_documents(
            {"company_id": company_id})
        with_val = await db[col].count_documents({
            "company_id": company_id,
            field: {"$exists": True, "$nin": [None, ""]}})
        return {"n": with_val, "total": total,
                "pct": round(with_val / max(total, 1) * 100, 2)}

    out: Dict[str, Any] = {"company_id": company_id,
                            "fields": {}}
    out["fields"]["common_in_smart_installs"] = {
        f: await cov("smart_installs", f) for f in COMMON_FIELDS}
    out["fields"]["installation"] = {
        f: await cov("smart_installs", f) for f in INSTALL_FIELDS}
    out["fields"]["common_in_smart_repairs"] = {
        f: await cov("smart_repairs", f) for f in COMMON_FIELDS}
    out["fields"]["repair"] = {
        f: await cov("smart_repairs", f) for f in REPAIR_FIELDS}
    out["fields"]["common_in_smart_withdrawals"] = {
        f: await cov("smart_withdrawals", f)
        for f in COMMON_FIELDS}
    out["fields"]["withdrawal"] = {
        f: await cov("smart_withdrawals", f)
        for f in WITHDRAW_FIELDS}

    # Validação anti-contaminação: nenhum smart_* fora de homolog
    out["safety_check"] = {
        "smart_installs_outside_homolog":
            await db.smart_installs.count_documents({
                "company_id": company_id,
                "environment": {"$ne": "homolog"}}),
        "smart_repairs_outside_homolog":
            await db.smart_repairs.count_documents({
                "company_id": company_id,
                "environment": {"$ne": "homolog"}}),
        "smart_withdrawals_outside_homolog":
            await db.smart_withdrawals.count_documents({
                "company_id": company_id,
                "environment": {"$ne": "homolog"}}),
        "wa_messages_outside_test_phone":
            await db.wa_messages_sent.count_documents({
                "company_id": company_id,
                "to_effective": {"$ne": TEST_PHONE}}),
    }
    out["generated_at"] = _now_iso()
    return out
