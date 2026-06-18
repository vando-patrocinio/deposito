"""Tests for Isabella V16 — Fluxo PJ Dedicado.

Cobertura:
  1. Detecção PJ por CNPJ válido (high confidence)
  2. Detecção PJ por keywords (medium confidence)
  3. Detecção falsa (cliente PF normal)
  4. Config consultor: get default vazio + upsert
  5. Captura lead: dedup em 24h
  6. Lookup CNPJ integrado (enriquece lead com razão social)
  7. render_client_reply formata BR phone corretamente
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

CID = "TEST-PJ-V16"


async def _cleanup():
    from database import db
    await db.pj_consultor_config.delete_many({"company_id": CID})
    await db.pj_leads.delete_many({"company_id": CID})


async def test_detect_pj_by_cnpj():
    from services.pj_lead_router import detect_pj_signal
    r = await detect_pj_signal(text="Sou da V S DO PATROCINIO PROVEDOR DE INTERNET, CNPJ 13.302.883/0001-36, quero internet")
    assert r["is_pj"] is True
    assert r["confidence"] >= 0.95
    assert r["cnpj_digits"] == "13302883000136"
    print(f"  ✓ CNPJ válido detectado (conf={r['confidence']})")


async def test_detect_pj_by_keywords():
    from services.pj_lead_router import detect_pj_signal
    r = await detect_pj_signal(text="oi, queria contratar internet empresarial para minha empresa LTDA")
    assert r["is_pj"] is True
    assert r["confidence"] >= 0.85
    print(f"  ✓ Keywords detectadas (conf={r['confidence']}, signals={r['signals']})")


async def test_detect_residential_not_pj():
    from services.pj_lead_router import detect_pj_signal
    r = await detect_pj_signal(text="oi, minha internet caiu, pode dar uma olhada?")
    assert r["is_pj"] is False
    print(f"  ✓ PF residencial NÃO detectado como PJ")


async def test_config_default_and_upsert():
    from services.pj_lead_router import get_pj_config, upsert_pj_config
    cfg = await get_pj_config(company_id=CID)
    assert cfg["ativo"] is False
    assert cfg["company_id"] == CID
    new = await upsert_pj_config(company_id=CID, updates={
        "ativo": True,
        "consultor_nome": "Flávio Santos",
        "consultor_telefone": "5521999990000",
        "consultor_whatsapp": "5521999990000",
        "consultor_email": "flavio@ligo.com.br",
        "sla_minutos": 15,
    })
    assert new["ativo"] is True
    assert new["consultor_nome"] == "Flávio Santos"
    print(f"  ✓ Config consultor PJ upsert OK")


async def test_capture_lead_dedup():
    """2 capturas do mesmo phone em <24h não duplicam."""
    from database import db
    from services.pj_lead_router import capture_lead
    phone = f"5511{uuid.uuid4().hex[:9]}"
    det = {"is_pj": True, "confidence": 0.85, "signals": ["empresa"]}
    l1 = await capture_lead(
        company_id=CID, phone=phone, detection=det,
        user_text="quero internet empresarial",
    )
    l2 = await capture_lead(
        company_id=CID, phone=phone, detection=det,
        user_text="é urgente, preciso hoje",
    )
    assert l2.get("deduped") is True, "deveria deduplicar"
    n = await db.pj_leads.count_documents({"company_id": CID, "phone": phone})
    assert n == 1, f"esperava 1 lead, encontrou {n}"
    # 2 mensagens anexadas
    lead = await db.pj_leads.find_one({"company_id": CID, "phone": phone})
    assert len(lead["messages"]) == 2
    print(f"  ✓ Dedup 24h funciona (1 lead, 2 mensagens anexadas)")


async def test_capture_lead_with_cnpj_lookup():
    """Lead com CNPJ válido enriquece com razão social via BrasilAPI."""
    from database import db
    from services.pj_lead_router import capture_lead
    phone = f"5511{uuid.uuid4().hex[:9]}"
    # CNPJ Magazine Luiza (sempre ativo, exemplo público)
    det = {"is_pj": True, "confidence": 0.98,
           "signals": ["cnpj"], "cnpj_digits": "47960950000121"}
    lead = await capture_lead(
        company_id=CID, phone=phone, detection=det,
        user_text="quero internet pra empresa, CNPJ 47.960.950/0001-21",
    )
    # Razão social pode vir vazia se BrasilAPI offline (não bloqueia)
    assert lead["cnpj"] in ("47.960.950/0001-21", "")
    if lead["razao_social"]:
        assert "MAGAZINE" in lead["razao_social"].upper() or len(lead["razao_social"]) > 5
        print(f"  ✓ CNPJ lookup: razão={lead['razao_social'][:40]}")
    else:
        print(f"  ✓ CNPJ lookup: BrasilAPI indisponível, lead criado sem enriquecimento (fail-soft OK)")


async def test_render_client_reply():
    from services.pj_lead_router import render_client_reply
    cfg = {"consultor_nome": "Flávio Santos",
           "consultor_telefone": "5521999990000",
           "sla_minutos": 15}
    msg = render_client_reply(cfg=cfg)
    assert "Atendimento Empresarial Ligo" in msg
    assert "Flávio Santos" in msg
    assert "(21) 99999-0000" in msg, f"formato BR errado: {msg}"
    assert "15 minutos" in msg
    print(f"  ✓ render_client_reply formata BR phone + SLA")


async def main():
    print("=== Isabella V16 — Fluxo PJ Dedicado: tests ===")
    await _cleanup()
    tests = [
        test_detect_pj_by_cnpj,
        test_detect_pj_by_keywords,
        test_detect_residential_not_pj,
        test_config_default_and_upsert,
        test_capture_lead_dedup,
        test_capture_lead_with_cnpj_lookup,
        test_render_client_reply,
    ]
    passed = failed = 0
    for t in tests:
        print(f"\n-- {t.__name__}")
        try:
            await t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
    await _cleanup()
    print(f"\n=== {passed} passed · {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
