"""Seed V15.3 — Amostra controlada de claims+outbounds em co-demo.

Cria uma amostra realista no co-demo para demonstrar o ciclo V15:
  memória + evidência + medição executiva.

Gera:
  • N1 cadastro_claims (subscriber_status) — todos passam audit
  • N2 smartolt_status claims — 80% passam, 20% falham (cliente sem ONU)
  • N3 ticket_status claims — todos passam
  • N4 financial_extended claims — mix de pass/fail (sync stale)
  • Para cada claim que passou, cria 1 outbound em aihub_wa_messages
    e bind a claim ao wam_id (consumed_by)
  • Para cada claim que falhou, registra um fallback_used em
    isabella_fallback_events
  • Todos com `created_at` espalhado nas últimas 24h

Uso:
    python3 -m scripts.seed_v153_demo --reset
"""
import argparse
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

CID = "co-demo"
SEED_TAG = "v153_seed"  # marca pra permitir reset idempotente


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


async def reset(db):
    """Remove só os documentos do seed (preserva dados reais)."""
    a = await db.isabella_factual_claims.delete_many(
        {"company_id": CID, "seed_tag": SEED_TAG})
    b = await db.aihub_wa_messages.delete_many(
        {"company_id": CID, "seed_tag": SEED_TAG})
    c = await db.isabella_fallback_events.delete_many(
        {"company_id": CID, "seed_tag": SEED_TAG})
    print(f"[reset] claims={a.deleted_count} "
          f"outbounds={b.deleted_count} fallbacks={c.deleted_count}")


async def main(args):
    from database import db

    if args.reset:
        await reset(db)
        if args.only_reset:
            return

    # Snapshot ANTES
    from services.isabella_confidence import trust_score, isabella_index
    print("\n=== TRUST SCORE ANTES DO SEED ===")
    snap_before = await trust_score(company_id=CID, hours=24)
    idx_before = await isabella_index(company_id=CID, hours=24)
    print(f"  ISABELLA INDEX antes: {idx_before['isabella_index']} ({idx_before['color']})")
    print(f"  Trust antes: {snap_before['score']}")
    print(f"  Claims_total antes: {snap_before['claims_total']}")
    print(f"  Claims_passed antes: {snap_before['claims_passed']}")
    print(f"  Claims_consumed antes: {snap_before['claims_consumed']}")

    # Gera amostra
    from services.isabella_claim_generators import (
        cadastro_claim, smartolt_status_claim, ticket_status_claim,
        financial_extended_claim, log_fallback_used,
    )

    n_total = args.size
    n_cadastro = n_total // 4
    n_smartolt = n_total // 4
    n_ticket = n_total // 4
    n_financial = n_total - n_cadastro - n_smartolt - n_ticket
    print(f"\n=== Gerando amostra (total={n_total}) ===")

    consumed_ids = []  # claims que devem ser consumidos por outbounds
    fallback_count = 0

    now = datetime.now(timezone.utc)

    # CADASTRO — 100% pass (clientes ativos)
    for i in range(n_cadastro):
        sub = {
            "id": f"sub-{i:04d}",
            "name": f"Cliente Demo {i}",
            "plan_name": "100MB", "plan_speed": "100/50",
            "plan_price": 99.90, "branch": "Centro",
            "external_code": f"EXT-{i:05d}",
            "billing_method": "boleto", "due_day": 10,
        }
        r = await cadastro_claim(company_id=CID, phone=f"5511A{i:08d}",
                                   subscriber=sub)
        if r["evidence_id"]:
            await db.isabella_factual_claims.update_one(
                {"id": r["evidence_id"]},
                {"$set": {"seed_tag": SEED_TAG}})
        if r["audit_passed"]:
            consumed_ids.append((r["evidence_id"], "subscriber_status"))

    # SMARTOLT — 80% pass, 20% sem ONU (audit fail → fallback)
    for i in range(n_smartolt):
        if random.random() < 0.8:
            onu = {
                "id": f"onu-{i:04d}", "sn": f"SN{i:06d}",
                "model": "ZTE F660", "status": "online",
                "signal_text": "Very good", "signal_1310": -18.5,
                "signal_1490": -19.2, "olt_name": "OLT-01",
                "board": 1, "port": i % 16,
                "last_status_change": _iso(
                    now - timedelta(minutes=random.randint(1, 30))),
                "minutes_since_change": random.randint(1, 30),
            }
        else:
            onu = None
        r = await smartolt_status_claim(
            company_id=CID, subscriber_id=f"sub-{i:04d}", onu=onu,
        )
        if r["evidence_id"]:
            await db.isabella_factual_claims.update_one(
                {"id": r["evidence_id"]},
                {"$set": {"seed_tag": SEED_TAG}})
        if r["audit_passed"]:
            consumed_ids.append((r["evidence_id"], "smartolt_status"))
        else:
            await log_fallback_used(
                company_id=CID, phone=f"5511B{i:08d}",
                claim_type="smartolt_status", evidence_id=r["evidence_id"],
                reason="onu_not_found_for_subscriber → IA usou 'vou verificar'",
            )
            await db.isabella_fallback_events.update_one(
                {"company_id": CID, "claim_type": "smartolt_status",
                  "phone": f"5511B{i:08d}"},
                {"$set": {"seed_tag": SEED_TAG}})
            fallback_count += 1

    # TICKET — 100% pass
    for i in range(n_ticket):
        tk = {
            "_id": f"tkt-{i:04d}",
            "code": f"TKT-{i:05d}",
            "status": random.choice(["aberto", "em_atendimento", "resolvido"]),
            "title": "Sem conexão",
            "created_at": _iso(now - timedelta(hours=random.randint(1, 48))),
            "updated_at": _iso(now - timedelta(minutes=random.randint(5, 120))),
            "assigned_to": f"tech-{i % 5}",
        }
        r = await ticket_status_claim(
            company_id=CID, subscriber_id=f"sub-{i:04d}", ticket=tk,
        )
        if r["evidence_id"]:
            await db.isabella_factual_claims.update_one(
                {"id": r["evidence_id"]},
                {"$set": {"seed_tag": SEED_TAG}})
        if r["audit_passed"]:
            consumed_ids.append((r["evidence_id"], "ticket_status"))

    # FINANCIAL — 70% pass, 30% sync stale (audit fail)
    for i in range(n_financial):
        invoices = [
            {"amount": 99.90,
              "due_date": _iso(now + timedelta(days=random.randint(1, 25))),
              "status": "pending"},
        ]
        stale = random.random() < 0.3
        r = await financial_extended_claim(
            company_id=CID, subscriber_id=f"sub-{i:04d}",
            open_invoices=invoices,
            next_due_date=invoices[0]["due_date"],
            sync_freshness_hours=48.0 if stale else 2.5,
        )
        if r["evidence_id"]:
            await db.isabella_factual_claims.update_one(
                {"id": r["evidence_id"]},
                {"$set": {"seed_tag": SEED_TAG}})
        if r["audit_passed"]:
            consumed_ids.append((r["evidence_id"], "financial_extended"))
        else:
            await log_fallback_used(
                company_id=CID, phone=f"5511D{i:08d}",
                claim_type="financial_extended",
                evidence_id=r["evidence_id"],
                reason="financial_sync_stale (>24h) → IA usou 'vou verificar'",
            )
            await db.isabella_fallback_events.update_one(
                {"company_id": CID, "claim_type": "financial_extended",
                  "phone": f"5511D{i:08d}"},
                {"$set": {"seed_tag": SEED_TAG}})
            fallback_count += 1

    # Para CADA claim consumível, cria um outbound e bind
    print(f"  Claims passados pendentes consumo: {len(consumed_ids)}")
    for evid, ctype in consumed_ids:
        wam_id = f"wam-{uuid.uuid4().hex[:12]}"
        await db.aihub_wa_messages.insert_one({
            "_id": f"msg-{uuid.uuid4().hex[:12]}",
            "company_id": CID, "direction": "outbound",
            "auto_reply": True, "phone": f"5511X{random.randint(0, 99999):08d}",
            "body": f"Resposta com evidência {ctype} ({evid})",
            "wam_id": wam_id,
            "created_at": _iso(
                now - timedelta(minutes=random.randint(1, 60 * 12))),
            "seed_tag": SEED_TAG,
        })
        await db.isabella_factual_claims.update_one(
            {"id": evid},
            {"$set": {"consumed_by": wam_id,
                       "consumed_at": _iso(now)}})

    # Snapshot DEPOIS
    print("\n=== TRUST SCORE DEPOIS DO SEED ===")
    snap_after = await trust_score(company_id=CID, hours=24)
    idx_after = await isabella_index(company_id=CID, hours=24)
    print(f"  ISABELLA INDEX depois: {idx_after['isabella_index']} ({idx_after['color']})")
    print(f"  Trust depois: {snap_after['score']}")
    print(f"  Claims_total depois: {snap_after['claims_total']}")
    print(f"  Claims_passed depois: {snap_after['claims_passed']}")
    print(f"  Claims_consumed depois: {snap_after['claims_consumed']}")
    print(f"  Audit pass rate: {snap_after['audit_pass_rate']}%")
    print(f"  Delivery rate: {snap_after['delivery_rate']}%")
    print(f"  Fallbacks usados corretamente: {fallback_count}")

    print("\n=== DELTA ===")
    print(f"  Trust: {snap_before['score']} → {snap_after['score']} "
          f"(Δ {snap_after['score'] - snap_before['score']:+.1f})")
    print(f"  ISABELLA INDEX: {idx_before['isabella_index']} ({idx_before['color']}) → "
          f"{idx_after['isabella_index']} ({idx_after['color']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                          help="remove seed antigo antes de criar novo")
    parser.add_argument("--only-reset", action="store_true",
                          help="remove e sai (não cria novo)")
    parser.add_argument("--size", type=int, default=40,
                          help="quantidade total de claims (default 40)")
    args = parser.parse_args()
    asyncio.run(main(args))
