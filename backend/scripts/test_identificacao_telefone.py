"""OPERAÇÃO IDENTIFICAÇÃO AUTOMÁTICA — testes contra DB real.

6 cenários obrigatórios do CTO:
  1. telefone único no cadastro → identifica automaticamente · sem CPF
  2. telefone com 2 cadastros → pergunta endereço/ponto, sem CPF
  3. telefone inexistente → pode pedir CPF
  4. subscriber_id já identificado → nunca pede CPF novamente
  5. cliente informa CPF uma vez → nunca pede novamente
  6. cliente responde "sim" → continua o fluxo, não reinicia

Verificações:
  • Bloco injetado no system prompt está correto por cenário.
  • Reescrita pelo guardião remove violações.
  • Persistência `wa_conversations.identity.*` correta.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from phone_normalizer import link_phone_to_subscriber, normalize_brazilian_phone  # noqa: E402
from services.anti_cpf_guardian import (  # noqa: E402
    detect_violations,
    inject_identification_block,
    rewrite_if_violates,
    update_conversation_identity,
)


COMPANY = "co-id-auto"
PHONE_UNIQUE = "5511990000001"
PHONE_MULTI = "5511990000002"
PHONE_UNKNOWN = "5511990000003"
PHONE_HISTORY_CPF = "5511990000004"


async def setup():
    # Limpa subscribers e wa_conversations do tenant
    for c in ("subscribers", "subscriber_phones", "wa_conversations",
              "aihub_wa_messages", "ai_evaluations"):
        await db[c].delete_many({"company_id": COMPANY})

    # 1 subscriber único
    await db.subscribers.insert_one({
        "id": "sub-uniq-001", "company_id": COMPANY,
        "name": "Pamela Souza", "phones": [PHONE_UNIQUE],
        "plan_name": "Fibra 600MB", "monthly_value": 99.90,
        "status": "ACTIVE", "address": "Rua A, 123",
    })
    await db.subscriber_phones.insert_one({
        "id": f"sphone-{uuid.uuid4().hex[:10]}",
        "company_id": COMPANY, "subscriber_id": "sub-uniq-001",
        "label": "principal", "raw_number": PHONE_UNIQUE,
        "normalized_number": normalize_brazilian_phone(PHONE_UNIQUE),
        "is_whatsapp": True, "is_primary": True,
    })

    # 2 subscribers compartilhando o mesmo telefone
    for i, name in enumerate(["João Silva", "Maria Silva"]):
        await db.subscribers.insert_one({
            "id": f"sub-multi-{i}", "company_id": COMPANY,
            "name": name, "phones": [PHONE_MULTI],
            "plan_name": "Fibra 300MB", "monthly_value": 79.90,
            "status": "ACTIVE",
            "address": f"Endereço {i+1}",
        })
        await db.subscriber_phones.insert_one({
            "id": f"sphone-{uuid.uuid4().hex[:10]}",
            "company_id": COMPANY, "subscriber_id": f"sub-multi-{i}",
            "label": "principal", "raw_number": PHONE_MULTI,
            "normalized_number": normalize_brazilian_phone(PHONE_MULTI),
            "is_whatsapp": True, "is_primary": True,
        })


async def cenario_1_unique() -> dict:
    link = await link_phone_to_subscriber(PHONE_UNIQUE, COMPANY)
    block = inject_identification_block(link, history_inbound=["Estou achando lento"])
    reply_violadora = ("Pode me passar o CPF do titular para localizar "
                       "seu cadastro? Vou verificar.")
    violations = detect_violations(reply_violadora)
    safe = rewrite_if_violates(reply_violadora, link)
    identity = await update_conversation_identity(
        company_id=COMPANY, phone=PHONE_UNIQUE, link=link,
        normalized=normalize_brazilian_phone(PHONE_UNIQUE),
        history_inbound=["Estou achando lento"])
    persisted = await db.wa_conversations.find_one(
        {"company_id": COMPANY, "phone": PHONE_UNIQUE}, {"_id": 0})
    return {
        "link_subscriber_id": (link or {}).get("subscriber_id"),
        "link_subscriber_name": (link or {}).get("subscriber_name"),
        "block_excerpt": block[:300],
        "violation_detected": violations,
        "rewritten_reply": safe,
        "identity_persisted": persisted.get("identity") if persisted else None,
        "expected": {
            "link_subscriber_id_match": (link or {}).get("subscriber_id") == "sub-uniq-001",
            "block_must_contain_PROHIBITED_keyword": "PROIBIDO" in block,
            "violation_count_>=_1": len(violations) >= 1,
            "rewritten_has_no_cpf": "cpf" not in safe.lower(),
            "identity_method_is_phone": (persisted or {}).get("identity", {}).get("identification_method") == "phone",
        },
    }


async def cenario_2_multi() -> dict:
    link = await link_phone_to_subscriber(PHONE_MULTI, COMPANY)
    block = inject_identification_block(link)
    identity = await update_conversation_identity(
        company_id=COMPANY, phone=PHONE_MULTI, link=link,
        normalized=normalize_brazilian_phone(PHONE_MULTI))
    persisted = await db.wa_conversations.find_one(
        {"company_id": COMPANY, "phone": PHONE_MULTI}, {"_id": 0})
    return {
        "link_conflict": (link or {}).get("conflict"),
        "link_count": (link or {}).get("conflict_count"),
        "block_excerpt": block[:300],
        "identity_persisted": (persisted or {}).get("identity"),
        "expected": {
            "conflict_true": (link or {}).get("conflict") is True,
            "block_says_qual_endereco": "endereço" in block.lower() or "ponto" in block.lower(),
            "block_NOT_says_PROIBIDO_pedir_CPF_imediato": "PROIBIDO: pedir CPF de imediato." in block,
            "identity_multi_match_true": ((persisted or {}).get("identity", {})
                                            .get("multi_match") is True),
        },
    }


async def cenario_3_unknown() -> dict:
    link = await link_phone_to_subscriber(PHONE_UNKNOWN, COMPANY)
    block = inject_identification_block(link)
    reply = "Pode me passar o CPF do titular para localizar seu cadastro?"
    violations = detect_violations(reply)
    # Sem subscriber_id rewrite NÃO deve alterar a reply
    safe = rewrite_if_violates(reply, link)
    return {
        "link": link,
        "block_excerpt": block[:300],
        "violations": violations,
        "rewritten_equals_original": safe == reply,
        "expected": {
            "link_is_none": link is None,
            "block_mentions_pendente": "PENDENTE" in block,
            "rewrite_does_not_strip_when_no_subscriber": safe == reply,
        },
    }


async def cenario_4_no_repeat_cpf_after_identified() -> dict:
    """Mesmo telefone identificado → IA tenta pedir CPF de novo →
    guardião reescreve."""
    link = await link_phone_to_subscriber(PHONE_UNIQUE, COMPANY)
    historico = ["Estou achando lento", "sim", "obrigado"]
    reply = ("Pamela, vou verificar. Mas antes preciso do CPF para "
             "confirmar seu cadastro.")
    violations = detect_violations(reply)
    safe = rewrite_if_violates(reply, link)
    block = inject_identification_block(link, history_inbound=historico)
    return {
        "violations_before": violations,
        "reply_before": reply,
        "reply_after_rewrite": safe,
        "block_excerpt": block[:300],
        "expected": {
            "violation_detected": "pede_cpf" in violations,
            "rewrite_eliminated_cpf": "cpf" not in safe.lower(),
            "block_says_sim_significa_confirmacao": "confirmação" in block.lower() or "continue o fluxo" in block.lower(),
        },
    }


async def cenario_5_cliente_ja_enviou_cpf() -> dict:
    """Cliente JÁ enviou CPF em mensagem passada → Isabella não pode pedir."""
    historico = ["meu cpf é 123.456.789-09", "ainda nao desbloqueou"]
    # Cria histórico real no banco
    for txt in historico:
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": COMPANY, "phone": PHONE_HISTORY_CPF,
            "direction": "inbound", "text": txt,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    link = await link_phone_to_subscriber(PHONE_HISTORY_CPF, COMPANY)
    history_inbound = list(reversed(historico))
    block = inject_identification_block(link, history_inbound=history_inbound)
    identity = await update_conversation_identity(
        company_id=COMPANY, phone=PHONE_HISTORY_CPF, link=link,
        normalized=normalize_brazilian_phone(PHONE_HISTORY_CPF),
        history_inbound=history_inbound)
    persisted = await db.wa_conversations.find_one(
        {"company_id": COMPANY, "phone": PHONE_HISTORY_CPF}, {"_id": 0})
    return {
        "block_excerpt": block[:300],
        "identity_persisted": (persisted or {}).get("identity"),
        "expected": {
            "block_says_cpf_ja_informado": "JÁ INFORMADO" in block,
            "identity_cpf_confirmed_true": (persisted or {}).get("identity", {}).get("cpf_confirmed") is True,
        },
    }


async def cenario_6_sim_nao_reinicia() -> dict:
    """Cliente responde só 'sim' depois de identificado. Block deve
    instruir Isabella a interpretar como CONFIRMAÇÃO e continuar."""
    link = await link_phone_to_subscriber(PHONE_UNIQUE, COMPANY)
    block = inject_identification_block(link, history_inbound=["sim", "ok"])
    return {
        "block_excerpt": block[:400],
        "expected": {
            "block_orients_continue_flow": "CONTINUE o fluxo" in block or "continue o fluxo" in block.lower(),
            "block_lista_palavras_neutras": "sim" in block.lower() and "obrigado" in block.lower(),
        },
    }


async def main():
    await setup()
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "company_id": COMPANY,
        "cenario_1_unique": await cenario_1_unique(),
        "cenario_2_multi": await cenario_2_multi(),
        "cenario_3_unknown": await cenario_3_unknown(),
        "cenario_4_no_repeat": await cenario_4_no_repeat_cpf_after_identified(),
        "cenario_5_cpf_ja_enviado": await cenario_5_cliente_ja_enviou_cpf(),
        "cenario_6_sim_continua": await cenario_6_sim_nao_reinicia(),
    }
    # Valida todas as `expected` keys
    total_checks = 0
    total_pass = 0
    failed = []
    for cen, val in out.items():
        if not isinstance(val, dict) or "expected" not in val:
            continue
        for chk, result in val["expected"].items():
            total_checks += 1
            if result is True:
                total_pass += 1
            else:
                failed.append(f"{cen}.{chk} = {result}")
    out["summary"] = {
        "total_checks": total_checks,
        "passed": total_pass,
        "failed": total_checks - total_pass,
        "failed_list": failed,
    }
    path = "/app/docs/RELATORIO_IDENTIFICACAO_AUTOMATICA.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(out["summary"], indent=2, ensure_ascii=False))
    print(f"\n[ok] gravado em {path}")
    if failed:
        print("\nFALHAS:")
        for f in failed:
            print("  -", f)


if __name__ == "__main__":
    asyncio.run(main())
