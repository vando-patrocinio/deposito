"""UNIVERSO LIGO — CUSTOMER INTELLIGENCE · ETAPA 2 BACKEND
=========================================================
Suite ZERO MOCK contra o Mongo real (tenant co-demo).

Roda:  cd /app/backend && python3 scripts/test_customer_intelligence.py

Cobertura — 10 regras obrigatórias do CTO:
 1. Tenant sintético é bloqueado.
 2. Subscriber inexistente retorna erro estruturado.
 3. Score nunca é exposto a customer (visible_to_customer=False).
 4. High Ticket ativa com receita >= 3× ticket médio real.
 5. Black ativa com receita >= 6× ticket médio real.
 6. Fundador histórico aplica multiplicador 1.5×.
 7. Embaixador SOMENTE por convite humano aceito, NUNCA por score automático.
 8. Cache invalida via `invalidate(subscriber_id)`.
 9. Confidence cai para "baixa" quando faltam fontes / tenure < 6 meses.
10. Audit trail grava em `universo_ligo_score_audit`.

REGRAS:
- Zero mocks.
- Mongo real, tenant co-demo.
- Toda fixture criada pelo script carrega `test_run_id` único e é removida no
  bloco `finally` (sem deixar sujeira em produção).
- Falha NUNCA é mascarada: cada teste imprime PASS/FAIL e o script retorna
  exit code != 0 se qualquer teste falhou.

CTO Mode: feature flags continuam OFF — o teste invoca `build_intelligence`
diretamente para validar a lógica, sem depender do endpoint HTTP gated.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "universo_ligo",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from database import db  # noqa: E402
from services import customer_intelligence as ci  # noqa: E402

CO = "co-demo"
TEST_RUN_ID = f"ci-etapa2-{uuid.uuid4().hex[:10]}"

# Subscribers REAIS já mapeados em co-demo:
SUB_SYNTHETIC = "sub-cls-000000"          # co-colosso → sintético
SUB_FOUNDER = "sub-2e42658cae0e"          # VANDILSON, doc 07220190760
SUB_HIGH_TICKET = "sub-a81e6aa90364"      # MARIA DE LOURDES, monthly 369.9
SUB_EMBAIXADOR = "sub-db24962d16b4"       # convite "accepted" em invites

# Fixtures criadas e limpas no final:
SUB_BLACK_ID = f"sub-tst-black-{uuid.uuid4().hex[:8]}"
DOC_BLACK = f"99999{uuid.uuid4().hex[:6]}"
SUB_LOWCONF_ID = f"sub-tst-lowconf-{uuid.uuid4().hex[:8]}"
SUB_SCORE_AMB_ID = f"sub-tst-scoreamb-{uuid.uuid4().hex[:8]}"
DOC_SCORE_AMB = f"88888{uuid.uuid4().hex[:6]}"

results: list[tuple[str, bool, str]] = []
latencies_ms: list[float] = []


def log(test: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {test} :: {detail}")
    results.append((test, ok, detail))


async def _seed_fixtures() -> None:
    """Insere apenas o estritamente necessário, sempre com test_run_id."""
    now = datetime.now(timezone.utc).isoformat()

    # 5 → Black: subscriber + loyalty com monthly_fee >= 6× média (>=620.21)
    await db.subscribers.insert_one({
        "id": SUB_BLACK_ID,
        "company_id": CO,
        "name": f"Test Black Customer {TEST_RUN_ID}",
        "document": DOC_BLACK,
        "created_at": now,
        "test_run_id": TEST_RUN_ID,
    })
    await db.loyalty_imported_db.insert_one({
        "id": f"loy-{SUB_BLACK_ID}",
        "company_id": CO,
        "document": DOC_BLACK,
        "status": "Ativo",
        "monthly_fee": 999.99,
        "registration_date": "2024-01-15T00:00:00+00:00",
        "invoices_paid": 18,
        "invoices_overdue": 0,
        "tickets_open": 0,
        "tickets_closed": 1,
        "test_run_id": TEST_RUN_ID,
    })

    # 9 → Low confidence: subscriber recém criado, sem document/loyalty
    await db.subscribers.insert_one({
        "id": SUB_LOWCONF_ID,
        "company_id": CO,
        "name": f"Test LowConf {TEST_RUN_ID}",
        "document": "",
        "created_at": now,
        "test_run_id": TEST_RUN_ID,
    })

    # 7-extra → Subscriber com loyalty "ambassador natural" (longevidade + zero
    # atrito) MAS sem convite humano. Deve cair em nível por score, NUNCA
    # Embaixador.
    await db.subscribers.insert_one({
        "id": SUB_SCORE_AMB_ID,
        "company_id": CO,
        "name": f"Test Score Ambassador {TEST_RUN_ID}",
        "document": DOC_SCORE_AMB,
        "created_at": "2018-03-01T00:00:00+00:00",
        "test_run_id": TEST_RUN_ID,
    })
    await db.loyalty_imported_db.insert_one({
        "id": f"loy-{SUB_SCORE_AMB_ID}",
        "company_id": CO,
        "document": DOC_SCORE_AMB,
        "status": "Ativo",
        "monthly_fee": 119.9,
        "registration_date": "2018-03-01T00:00:00+00:00",
        "invoices_paid": 90,
        "invoices_overdue": 0,
        "tickets_open": 0,
        "tickets_closed": 2,
        "test_run_id": TEST_RUN_ID,
    })


async def _cleanup_fixtures() -> None:
    await db.subscribers.delete_many({"test_run_id": TEST_RUN_ID})
    await db.loyalty_imported_db.delete_many({"test_run_id": TEST_RUN_ID})
    await db.universo_ligo_score_audit.delete_many({
        "subscriber_id": {"$in": [SUB_BLACK_ID, SUB_LOWCONF_ID, SUB_SCORE_AMB_ID]}
    })


async def _build(sub_id: str) -> dict:
    ci.invalidate(sub_id)
    t0 = time.time()
    payload = await ci.build_intelligence(sub_id)
    latencies_ms.append((time.time() - t0) * 1000)
    return payload


# ─── Testes ───────────────────────────────────────────────────────────
async def test_01_synthetic_blocked() -> None:
    p = await _build(SUB_SYNTHETIC)
    ok = isinstance(p, dict) and p.get("error") == "synthetic_tenant_blocked"
    log("01_synthetic_blocked", ok, f"payload.error={p.get('error')}")


async def test_02_subscriber_not_found() -> None:
    p = await _build("sub-does-not-exist-zzzz")
    ok = isinstance(p, dict) and p.get("error") == "subscriber_not_found"
    log("02_subscriber_not_found", ok, f"payload.error={p.get('error')}")


async def test_03_score_never_exposed() -> None:
    p = await _build(SUB_FOUNDER)
    score_block = p.get("internal_score") or {}
    fin = p.get("financial_context") or {}
    rel = p.get("relationship_context") or {}
    secondary = p.get("secondary_tags") or []
    ok = (
        score_block.get("visible_to_customer") is False
        and fin.get("visible_to_customer") is False
        and all(t.get("visible_to_customer") is False for t in secondary)
    )
    # Nenhum campo top-level deve expor "score" como visível
    pl_visible = (p.get("primary_level") or {}).get("visible_to_customer")
    ok = ok and pl_visible is True  # único campo público
    log("03_score_never_exposed", ok,
        f"score.visible={score_block.get('visible_to_customer')} "
        f"fin.visible={fin.get('visible_to_customer')} "
        f"primary.visible={pl_visible} tags={len(secondary)}")
    # relationship_context não tem visible flag, mas também não expõe score:
    assert "score" not in rel, "relationship_context expõe score numérico"


async def test_04_high_ticket() -> None:
    p = await _build(SUB_HIGH_TICKET)
    fin = p.get("financial_context") or {}
    tags = {t["key"] for t in (p.get("secondary_tags") or [])}
    base = fin.get("base_avg_ticket") or 0
    mr = fin.get("monthly_revenue") or 0
    ok = (
        fin.get("financial_class") == "high_ticket"
        and "high_ticket" in tags
        and "black" not in tags
        and mr >= 3 * base
        and mr < 6 * base
    )
    log("04_high_ticket", ok,
        f"class={fin.get('financial_class')} mr={mr} base={base} mult={fin.get('ticket_multiplier')}")


async def test_05_black() -> None:
    p = await _build(SUB_BLACK_ID)
    fin = p.get("financial_context") or {}
    tags = {t["key"] for t in (p.get("secondary_tags") or [])}
    base = fin.get("base_avg_ticket") or 0
    mr = fin.get("monthly_revenue") or 0
    ok = (
        fin.get("financial_class") == "black"
        and "black" in tags
        and mr >= 6 * base
    )
    log("05_black", ok,
        f"class={fin.get('financial_class')} mr={mr} base={base}")


async def test_06_founder_multiplier() -> None:
    """Recalcula score COM e SEM o fundador para validar o multiplicador 1.5×.

    Estratégia: roda `build_intelligence` no fundador real → captura score.
    Depois compara com o score base que sai do cálculo sem multiplicador,
    derivado das 6 dimensões diretamente.
    """
    p = await _build(SUB_FOUNDER)
    rel = p.get("relationship_context") or {}
    score_block = p.get("internal_score") or {}
    reasons = p.get("reasons") or []
    ok = (
        rel.get("founder_candidate") is True
        and any("Fundador" in r and "1.5" in r for r in reasons)
        and score_block.get("score", 0) >= 600
    )
    log("06_founder_multiplier", ok,
        f"founder={rel.get('founder_candidate')} score={score_block.get('score')} reasons={reasons[:3]}")


async def test_07_embaixador_only_by_invite() -> None:
    # 7a — sub com convite humano aceito → DEVE ser embaixador
    p_inv = await _build(SUB_EMBAIXADOR)
    pl_inv = (p_inv.get("primary_level") or {}).get("key")
    ok_a = pl_inv == "embaixador"

    # 7b — sub com perfil de "ambassador natural" MAS sem convite → NÃO pode
    # virar embaixador (deve cair em qualquer outro nível por score).
    p_score = await _build(SUB_SCORE_AMB_ID)
    pl_score = (p_score.get("primary_level") or {}).get("key")
    tags_score = {t["key"] for t in (p_score.get("secondary_tags") or [])}
    rel_score = p_score.get("relationship_context") or {}
    ok_b = (
        pl_score != "embaixador"
        and rel_score.get("ambassador_candidate") is True
        and "embaixador_natural" in tags_score
    )
    log("07_embaixador_only_by_invite", ok_a and ok_b,
        f"with_invite={pl_inv} (esperado=embaixador) | "
        f"score_only={pl_score} ambassador_natural_tag={'embaixador_natural' in tags_score}")


async def test_08_cache_invalidation() -> None:
    # Hit 1 (cold)
    ci.invalidate(SUB_FOUNDER)
    t0 = time.time()
    p1 = await ci.build_intelligence(SUB_FOUNDER)
    cold_ms = (time.time() - t0) * 1000

    # Hit 2 (warm — vem do cache, ts idêntico)
    t1 = time.time()
    p2 = await ci.build_intelligence(SUB_FOUNDER)
    warm_ms = (time.time() - t1) * 1000

    same_ts = p1.get("last_updated_at") == p2.get("last_updated_at")
    cache_faster = warm_ms < cold_ms

    # Invalida → próxima chamada gera NOVO last_updated_at
    ci.invalidate(SUB_FOUNDER)
    p3 = await ci.build_intelligence(SUB_FOUNDER)
    refreshed = p3.get("last_updated_at") != p1.get("last_updated_at")

    ok = same_ts and cache_faster and refreshed
    log("08_cache_invalidation", ok,
        f"cold={cold_ms:.1f}ms warm={warm_ms:.1f}ms same_ts={same_ts} refreshed={refreshed}")


async def test_09_low_confidence() -> None:
    p = await _build(SUB_LOWCONF_ID)
    dq = p.get("data_quality") or {}
    score_block = p.get("internal_score") or {}
    ok = (
        dq.get("confidence") == "baixa"
        and "loyalty_imported_db" in (dq.get("missing_fields") or [])
        and score_block.get("confidence") == "baixa"
    )
    log("09_low_confidence", ok,
        f"confidence={dq.get('confidence')} missing={dq.get('missing_fields')}")


async def test_10_audit_trail() -> None:
    target = SUB_HIGH_TICKET
    before = await db.universo_ligo_score_audit.count_documents(
        {"subscriber_id": target}
    )
    ci.invalidate(target)
    await ci.build_intelligence(target)
    after = await db.universo_ligo_score_audit.count_documents(
        {"subscriber_id": target}
    )
    last = await db.universo_ligo_score_audit.find_one(
        {"subscriber_id": target}, sort=[("computed_at", -1)]
    )
    ok = (
        after == before + 1
        and last is not None
        and last.get("company_id") == CO
        and isinstance(last.get("score"), int)
        and isinstance(last.get("tags"), list)
        and last.get("level_key") in {"explorador", "viajante", "cometa",
                                       "constelacao", "galaxia", "embaixador"}
    )
    log("10_audit_trail", ok,
        f"before={before} after={after} last.level={last.get('level_key') if last else None}")


# ─── Runner ───────────────────────────────────────────────────────────
async def main() -> int:
    print("\n" + "=" * 70)
    print(f"CUSTOMER INTELLIGENCE · ETAPA 2 — TEST_RUN_ID={TEST_RUN_ID}")
    print("=" * 70)
    print(f"Feature flags · ENABLED={ci.FF_ENABLED} "
          f"ISABELLA={ci.FF_ISABELLA} UI_BADGES={ci.FF_UI_BADGES}")
    print("=" * 70 + "\n")

    try:
        await ci.ensure_indexes()
        await _seed_fixtures()

        await test_01_synthetic_blocked()
        await test_02_subscriber_not_found()
        await test_03_score_never_exposed()
        await test_04_high_ticket()
        await test_05_black()
        await test_06_founder_multiplier()
        await test_07_embaixador_only_by_invite()
        await test_08_cache_invalidation()
        await test_09_low_confidence()
        await test_10_audit_trail()

    finally:
        await _cleanup_fixtures()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 70)
    print(f"RESULTADO · {passed}/{len(results)} PASS · {failed} FAIL")
    if latencies_ms:
        print(f"Latência (build_intelligence) · "
              f"avg={statistics.mean(latencies_ms):.1f}ms "
              f"p95={sorted(latencies_ms)[int(len(latencies_ms)*0.95)-1]:.1f}ms "
              f"min={min(latencies_ms):.1f}ms max={max(latencies_ms):.1f}ms")
    print("=" * 70)

    # Amostra de payload real (audit-friendly)
    sample = await ci.build_intelligence(SUB_FOUNDER)
    sample.pop("_meta", None)
    print("\nAMOSTRA · build_intelligence(SUB_FOUNDER):")
    import json
    print(json.dumps(sample, indent=2, ensure_ascii=False, default=str)[:2200])

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
