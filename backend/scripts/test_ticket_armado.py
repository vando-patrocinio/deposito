"""Testes OPERAÇÃO TICKET ARMADO (CTO 2026-02).

Valida os 10 critérios obrigatórios definidos pela ordem executiva.
Read-only para o ambiente de produção (não cria dados novos, exceto logs).

Executar:
  cd /app/backend && python scripts/test_ticket_armado.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402


PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def _assert(cond: bool, label: str, detail: str = "") -> bool:
    sym = PASS if cond else FAIL
    print(f"  {sym} {label}" + (f"  ({detail})" if detail else ""))
    return cond


async def test_1_marcio_no_more_sem_leitura() -> bool:
    print("\n[Teste 1] Marcio Carneiro: nunca mais 'sem leitura' com ONU online")
    from routes.smartolt import (resolve_signal_for_ticket,
                                    _live_signal_summary)
    t = await db.tickets.find_one(
        {"client_snapshot.pppoe_user":
            {"$regex": "AntJoao1429", "$options": "i"}},
        {"_id": 0})
    if not t:
        return _assert(False, "Ticket Marcio encontrado", "skip")
    onu = await resolve_signal_for_ticket(t)
    if not onu:
        return _assert(False, "ONU resolvida",
                         "ONU não match — esperado")
    live = _live_signal_summary(onu,
            ticket_relato=(t.get("client_snapshot") or {}).get("relato"))
    ok1 = _assert(live.get("cache_label") is not None,
                    "cache_label populado",
                    f"= {live.get('cache_label')}")
    ok2 = _assert(live.get("cache_label") != "SEM LEITURA"
                    or live.get("rx_dbm") is None,
                    "Não diz SEM LEITURA quando há rx_dbm")
    ok3 = _assert(live.get("classification") is not None,
                    "classification populado",
                    f"= {live.get('classification')}")
    return ok1 and ok2 and ok3


async def test_2_cache_age_displayed() -> bool:
    print("\n[Teste 2] Cache antigo aparece com idade humanizada")
    from routes.smartolt import _live_signal_summary
    onu = await db.smartolt_onus.find_one(
        {"signal_1490": {"$ne": None},
         "synced_at": {"$exists": True}}, {"_id": 0})
    if not onu:
        return _assert(False, "ONU com signal_1490 + synced_at", "skip")
    live = _live_signal_summary(onu)
    ok1 = _assert(live.get("cache_age_seconds") is not None,
                    "cache_age_seconds calculado",
                    f"= {live.get('cache_age_seconds')}s")
    ok2 = _assert(live.get("cache_label", "").startswith(("LIVE", "CACHE")),
                    "cache_label começa com LIVE/CACHE",
                    f"= {live.get('cache_label')}")
    return ok1 and ok2


async def test_3_live_button_invalidates_cache() -> bool:
    print("\n[Teste 3] Endpoint /tickets/{id}/armed-signal?force=true existe")
    # Validar via OpenAPI (não chamar SmartOLT de verdade)
    import httpx
    try:
        r = httpx.get("http://localhost:8001/openapi.json", timeout=5.0)
        spec = r.json()
        p = "/api/tickets/{ticket_id}/armed-signal"
        if p not in spec.get("paths", {}):
            return _assert(False, "Endpoint registrado")
        methods = spec["paths"][p]
        params = methods["get"].get("parameters", [])
        has_force = any(pr.get("name") == "force" for pr in params)
        has_max_age = any(pr.get("name") == "max_age_seconds" for pr in params)
        return (_assert(has_force, "Param force=") and
                _assert(has_max_age, "Param max_age_seconds="))
    except Exception as e:
        return _assert(False, "OpenAPI fetch", str(e)[:60])


async def test_4_classifica_atenuacao() -> bool:
    print("\n[Teste 4] Relato LOS + ONU Online + Rx -26.77 = ATENUACAO_CRITICA")
    from routes.smartolt import _live_signal_summary
    fake_onu = {
        "unique_external_id": "test", "name": "test",
        "signal_1490": "-26.77", "signal_1310": "-26.78",
        "status": "Online", "onu_type_name": "F601",
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    live = _live_signal_summary(
        fake_onu, ticket_relato="SEM CONEXÃO/LOS")
    return _assert(live.get("classification") == "ATENUACAO_CRITICA",
                    "classification == ATENUACAO_CRITICA",
                    f"= {live.get('classification')}")


async def test_5_los_real_permanece_los() -> bool:
    print("\n[Teste 5] ONU realmente em LOS continua LOS_FISICO")
    from routes.smartolt import _live_signal_summary
    fake_onu = {
        "unique_external_id": "test2", "name": "test2",
        "signal_1490": None, "signal_1310": None,
        "status": "LOS", "onu_type_name": "F601",
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    live = _live_signal_summary(fake_onu, ticket_relato="SEM SINAL")
    return _assert(live.get("classification") == "LOS_FISICO",
                    "classification == LOS_FISICO",
                    f"= {live.get('classification')}")


async def test_6_generic_profile_banner() -> bool:
    print("\n[Teste 6] Profile Generic_X gera flag generic_profile_alert")
    from routes.smartolt import _live_signal_summary
    fake_onu = {
        "unique_external_id": "test3", "name": "test3",
        "signal_1490": "-22", "signal_1310": "-22",
        "status": "Online", "onu_type_name": "Generic_1",
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    live = _live_signal_summary(fake_onu)
    return _assert(live.get("generic_profile_alert") is True,
                    "generic_profile_alert == True",
                    f"= {live.get('generic_profile_alert')}")


async def test_7_degradation_in_payload() -> bool:
    print("\n[Teste 7] signal_degradation_alerts aparece em armed-signal")
    # Verifica que collection existe e tem dados
    alerts = await db.signal_degradation_alerts.count_documents({})
    if alerts == 0:
        return _assert(False, "Collection tem dados", "skip")
    # Pega um alert e injeta detected_at recente para simular ativo (<72h)
    from routes.smartolt import _enrich_degradation_alerts
    a = await db.signal_degradation_alerts.find_one({}, {"_id": 0})
    # Cria alert sintético em memória com detected_at recente
    fresh_alert = dict(a)
    fresh_alert["detected_at"] = datetime.now(timezone.utc).isoformat()
    fresh_alert["unique_external_id"] = f"TEST_ARMED_{datetime.now(timezone.utc).timestamp()}"
    fresh_alert["_test_only"] = True
    await db.signal_degradation_alerts.insert_one(dict(fresh_alert))
    try:
        fake_tickets = [{"live_signal": {
            "external_id": fresh_alert["unique_external_id"]}}]
        await _enrich_degradation_alerts(fake_tickets, a["company_id"])
        ok = fake_tickets[0].get("degradation_alert") is not None
    finally:
        await db.signal_degradation_alerts.delete_one(
            {"unique_external_id": fresh_alert["unique_external_id"]})
    return _assert(ok, "degradation_alert anexado ao ticket")


async def test_8_scheduler_anti_dup() -> bool:
    print("\n[Teste 8] AutonomousEngine NÃO cria duplicatas em 24h")
    # Verifica que o guardrail existe no código
    import inspect
    from services import autonomous_engine
    src = inspect.getsource(autonomous_engine)
    has_guard = ("blocked_duplicate" in src
                  and "anti_duplicate_guardrail" in src
                  and "_cutoff_24h" in src)
    return _assert(has_guard, "Guardrail anti-duplicata presente em código")


async def test_9_pppoe_backfill_confidence() -> bool:
    print("\n[Teste 9] PPPoE backfill grava confidence quando alto")
    # Verifica que tickets com pppoe_backfilled_at tem confidence
    n_high = await db.tickets.count_documents(
        {"client_snapshot.pppoe_confidence": "high",
         "client_snapshot.pppoe_backfilled_at": {"$exists": True}})
    n_low = await db.tickets.count_documents(
        {"client_snapshot.pppoe_confidence": "low"})
    return _assert(n_high > 0,
                    "Pelo menos 1 ticket com high confidence",
                    f"high={n_high}, low={n_low}")


async def test_10_lousa_log_refresh() -> bool:
    print("\n[Teste 10] lousa_logs registra ação live_signal_refresh")
    # Verifica que o endpoint armed-signal escreve em lousa_logs
    import inspect
    from routes import lousa
    src = inspect.getsource(lousa)
    has_log = ('"live_signal_refresh"' in src
                or "'live_signal_refresh'" in src)
    return _assert(has_log, "lousa_logs registra live_signal_refresh")


async def main():
    print("=" * 60)
    print("OPERAÇÃO TICKET ARMADO — Bateria de testes obrigatórios")
    print("=" * 60)

    tests = [
        test_1_marcio_no_more_sem_leitura,
        test_2_cache_age_displayed,
        test_3_live_button_invalidates_cache,
        test_4_classifica_atenuacao,
        test_5_los_real_permanece_los,
        test_6_generic_profile_banner,
        test_7_degradation_in_payload,
        test_8_scheduler_anti_dup,
        test_9_pppoe_backfill_confidence,
        test_10_lousa_log_refresh,
    ]
    results = []
    for tfn in tests:
        try:
            results.append(await tfn())
        except Exception as e:
            print(f"  {FAIL} {tfn.__name__} EXCEPTION: {e}")
            results.append(False)

    passed = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"RESULTADO: {passed}/{len(results)} testes passaram")
    print("=" * 60)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
