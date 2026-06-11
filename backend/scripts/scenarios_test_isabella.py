"""Fase 2 + 3 — 7 cenários comerciais + validação do loop inbound→outbound.

OPERAÇÃO VALIDAR RECEITA REAL — Fases 2 e 3
============================================

Cenários (todos no número 21998176526 — ÚNICO destino permitido):
  1. Cobrança         (boleto vencido)
  2. Upgrade          (cliente quer plano maior)
  3. Retenção         (cliente ameaça cancelar)
  4. Ex-cliente       (cliente já cancelado pedindo voltar)
  5. Security Home    (alarme/CFTV)
  6. PlayHub          (streaming/IPTV)
  7. Ligo Móvel       (chip celular)

Para cada cenário, validamos:
  - Inbound persistida em aihub_wa_messages
  - Outbound gerada em aihub_wa_messages (Isabella respondeu)
  - subscriber_id linkado corretamente
  - Texto da resposta coerente com o intent
  - Latência de fechamento de loop
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

ALLOWED_PHONE = "21998176526"
ALLOWED_PHONE_E164 = "+5521998176526"
TENANT = "co-demo"
SUBSCRIBER_ID = "sub-89c314c0d98f"

BACKEND_URL = (
    os.environ.get("PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
WEBHOOK_URL = f"{BACKEND_URL}/api/whatsapp-twilio/webhook?tenant={TENANT}"

SCENARIOS = [
    {
        "id": "cobranca",
        "label": "Cobrança",
        "text": "[FASE2-cobranca] Oi, minha fatura desse mês está vencida há 5 dias. Tem como me mandar a segunda via do boleto pra eu pagar hoje?",
        "expect_keywords": ["fatura", "boleto", "pagar", "vencid", "segunda", "via"],
    },
    {
        "id": "upgrade",
        "label": "Upgrade de plano",
        "text": "[FASE2-upgrade] Quero saber se vocês têm um plano mais rápido. Tô com 300 mega e quero upgrade pra 1 giga. Qual o preço?",
        "expect_keywords": ["plano", "giga", "upgrade", "valor", "preço", "mega"],
    },
    {
        "id": "retencao",
        "label": "Retenção",
        "text": "[FASE2-retencao] Já decidi cancelar a internet de vocês. O sinal cai toda hora e estou sem paciência. Como faço pra cancelar?",
        "expect_keywords": ["cancelar", "cancel", "ficar", "ofert", "desconto", "permanecer", "fideliz"],
    },
    {
        "id": "ex_cliente",
        "label": "Ex-cliente querendo voltar",
        "text": "[FASE2-ex-cliente] Eu era cliente de vocês ano passado e cancelei. Agora quero voltar. Tem como reativar meu plano antigo de 500 mega?",
        "expect_keywords": ["voltar", "reativar", "plano", "bem", "vindo", "novamente"],
    },
    {
        "id": "security",
        "label": "Security Home (alarme)",
        "text": "[FASE2-security] Vi que vocês têm sistema de alarme residencial. Quero proteger minha casa com câmeras e sensor de porta. Como funciona?",
        "expect_keywords": ["alarme", "câmera", "camera", "security", "sensor", "monitor", "segur"],
    },
    {
        "id": "playhub",
        "label": "PlayHub (streaming)",
        "text": "[FASE2-playhub] Ouvi falar do PlayHub de vocês. É um combo com Netflix e canais? Quero contratar junto com a internet.",
        "expect_keywords": ["playhub", "streaming", "netflix", "canais", "combo"],
    },
    {
        "id": "ligo_movel",
        "label": "Ligo Móvel (chip)",
        "text": "[FASE2-ligo-movel] Vocês têm chip de celular agora? Vi um anúncio do Ligo Móvel. Quero portar meu número da Vivo pra vocês.",
        "expect_keywords": ["chip", "celular", "móvel", "movel", "portar", "ligo", "linha"],
    },
]


def _payload(text: str, idx: int) -> Dict[str, str]:
    return {
        "From": f"whatsapp:{ALLOWED_PHONE_E164}",
        "To": "whatsapp:+5521998176526",
        "Body": text,
        "ProfileName": "PAMELA TESTE",
        "MessageSid": f"SM-fase2-{int(time.time())}-{idx:04d}",
        "NumMedia": "0",
        "AccountSid": "ACtest",
        "WaId": ALLOWED_PHONE,
    }


async def _fetch_latest_outbound_after(db, after_dt: datetime,
                                       timeout_s: float = 90.0) -> Dict[str, Any] | None:
    """Polling até a outbound aparecer (Isabella responde de verdade)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        doc = await db.aihub_wa_messages.find_one(
            {
                "phone": {"$regex": f"{ALLOWED_PHONE}$"},
                "direction": "outbound",
                "created_at": {"$gt": after_dt.isoformat()},
            },
            sort=[("created_at", -1)],
        )
        if doc:
            return doc
        await asyncio.sleep(1.0)
    return None


async def main() -> None:
    print("═" * 66)
    print("OPERAÇÃO VALIDAR RECEITA REAL — Fases 2 + 3")
    print("═" * 66)
    print(f"  Phone alvo (ÚNICO):  {ALLOWED_PHONE_E164}")
    print(f"  Tenant:              {TENANT}")
    print(f"  Subscriber:          {SUBSCRIBER_ID}")
    print(f"  Endpoint:            {WEBHOOK_URL}")
    print(f"  Cenários:            {len(SCENARIOS)}")
    print("═" * 66)

    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, sc in enumerate(SCENARIOS):
            print(f"\n━━━ Cenário {i+1}/7: {sc['label']} ({sc['id']}) ━━━")
            mark = datetime.now(timezone.utc)
            t0 = time.perf_counter()
            try:
                r = await client.post(WEBHOOK_URL, data=_payload(sc["text"], i))
                http_ok = r.status_code == 200
            except Exception as e:  # noqa: BLE001
                http_ok = False
                r = None
                print(f"  ❌ HTTP exception: {e}")

            inbound = await db.aihub_wa_messages.find_one(
                {
                    "phone": {"$regex": f"{ALLOWED_PHONE}$"},
                    "direction": "inbound",
                    "text": sc["text"],
                },
                sort=[("created_at", -1)],
            )

            outbound = await _fetch_latest_outbound_after(db, mark, timeout_s=90)
            dt_total = time.perf_counter() - t0

            reply_text = (outbound or {}).get("text", "")
            reply_lower = reply_text.lower()
            kw_hits = [kw for kw in sc["expect_keywords"]
                       if kw.lower() in reply_lower]
            ok_subscriber = (inbound or {}).get("subscriber_id") == SUBSCRIBER_ID
            ok_outbound_subscriber = (outbound or {}).get("subscriber_id") == SUBSCRIBER_ID

            status = "✅" if (inbound and outbound and ok_subscriber and ok_outbound_subscriber and len(kw_hits) >= 1) else "🟡" if (inbound and outbound) else "🔴"
            print(f"  {status} HTTP={getattr(r, 'status_code', 'ERR')}  "
                  f"loop_dt={dt_total:.1f}s")
            print(f"  📥 inbound salva={bool(inbound)}  "
                  f"subscriber_match={ok_subscriber}")
            print(f"  📤 outbound salva={bool(outbound)}  "
                  f"subscriber_match={ok_outbound_subscriber}")
            print(f"  🎯 keyword_hits={kw_hits} (esperado ≥1 de {sc['expect_keywords']})")
            if reply_text:
                print(f"  💬 reply: {reply_text[:160]}{'…' if len(reply_text) > 160 else ''}")

            results.append({
                "scenario_id": sc["id"],
                "label": sc["label"],
                "input_text": sc["text"],
                "http_status": getattr(r, "status_code", -1) if r else -1,
                "loop_total_s": round(dt_total, 2),
                "inbound_persisted": bool(inbound),
                "outbound_persisted": bool(outbound),
                "inbound_subscriber_linked": ok_subscriber,
                "outbound_subscriber_linked": ok_outbound_subscriber,
                "reply_text": reply_text[:600],
                "reply_keyword_hits": kw_hits,
                "loop_closed": bool(inbound and outbound),
                "status_emoji": status,
            })

            await asyncio.sleep(2.5)  # cool-down entre cenários

    # Resumo Fase 3 — loop validation
    closed = sum(1 for x in results if x["loop_closed"])
    full_ok = sum(1 for x in results if x["status_emoji"] == "✅")
    print("\n" + "═" * 66)
    print("RESUMO FASES 2 + 3")
    print("═" * 66)
    print(f"  Total cenários:           {len(results)}")
    print(f"  Loop fechado (in+out):    {closed}/{len(results)}")
    print(f"  Loop fechado + keyword OK: {full_ok}/{len(results)}")
    for r in results:
        print(f"  {r['status_emoji']}  {r['label']:<28} "
              f"loop={r['loop_total_s']:>5}s  "
              f"kw={len(r['reply_keyword_hits'])}")

    out_path = "/app/docs/fase2_3_scenarios_result.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "phone_alvo": ALLOWED_PHONE_E164,
            "tenant": TENANT,
            "executado_em": datetime.now(timezone.utc).isoformat(),
            "scenarios": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Resultado salvo em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
