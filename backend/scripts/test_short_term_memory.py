"""OPERAÇÃO MEMÓRIA DE CURTO PRAZO — 10 testes obrigatórios.

Para cada palavra-resposta: simula última pergunta da Isabella + a
resposta curta + uma reply LLM "malcomportada" que tenta abrir fluxo
comercial. Valida que o guardião RECUPERA contexto.
"""
from __future__ import annotations
import asyncio, json, os, sys, uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from services.short_term_memory_guard import (  # noqa: E402
    analyze_short_term_context, inject_memory_block,
    enforce_memory_on_reply, log_memory_event,
)


COMPANY = "co-mem-test"
PHONE = "5511990099999"


SHORT_REPLIES = ["Quero", "Sim", "Pode", "Ok", "Amanhã",
                  "Agora", "Isso", "Ela", "Confirmo", "Certo"]

ISABELLA_QUESTION = ("Quer que eu resolva por aqui agora ou prefere "
                     "agendar atendente às 08:00?")

BAD_LLM_REPLY = ("Entendi! Aproveitando, posso te apresentar o PlayHub? "
                 "Ou se preferir, temos o Ligo Security e o chip 5G. "
                 "Que tal um upgrade no plano também?")


async def _seed_history(user_text: str) -> None:
    await db.aihub_wa_messages.delete_many({"company_id": COMPANY, "phone": PHONE})
    now = datetime.now(timezone.utc)
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-cli-{uuid.uuid4().hex[:6]}",
        "company_id": COMPANY, "phone": PHONE,
        "direction": "inbound", "text": "minha internet está sem sinal",
        "created_at": now.isoformat()})
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-isa-{uuid.uuid4().hex[:6]}",
        "company_id": COMPANY, "phone": PHONE,
        "direction": "outbound", "text": ISABELLA_QUESTION,
        "created_at": now.isoformat()})
    # Mensagem curta atual
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-cur-{uuid.uuid4().hex[:6]}",
        "company_id": COMPANY, "phone": PHONE,
        "direction": "inbound", "text": user_text,
        "created_at": now.isoformat()})


async def main():
    await db.ai_evaluations.delete_many(
        {"company_id": COMPANY, "kind": "SHORT_TERM_MEMORY"})
    results = []
    for ans in SHORT_REPLIES:
        await _seed_history(ans)
        analysis = await analyze_short_term_context(
            company_id=COMPANY, phone=PHONE, user_text=ans)
        block = inject_memory_block(analysis)
        enf = enforce_memory_on_reply(analysis, BAD_LLM_REPLY)
        await log_memory_event(
            company_id=COMPANY, phone=PHONE, subscriber_id=None,
            analysis=analysis, enforcement=enf)
        passed = (
            analysis["is_short_reply"] and
            analysis["last_isabella_question"] is not None and
            enf["context_error"] and  # detectou erro comercial
            enf["context_recovered"] and
            "playhub" not in enf["reply"].lower() and
            "ligo security" not in enf["reply"].lower() and
            "upgrade" not in enf["reply"].lower() and
            "chip 5g" not in enf["reply"].lower()
        )
        results.append({
            "answer": ans,
            "is_short": analysis["is_short_reply"],
            "open_topic": analysis["open_topic"],
            "last_q_detected": bool(analysis["last_isabella_question"]),
            "block_excerpt": block[:150],
            "rewritten": enf["reply"][:200],
            "context_recovered": enf["context_recovered"],
            "context_error": enf["context_error"],
            "violations": enf["violations"],
            "pass": passed,
        })

    # Teste correção do cliente
    await db.aihub_wa_messages.delete_many({"company_id": COMPANY, "phone": PHONE})
    await db.aihub_wa_messages.insert_one({
        "id": f"isa-{uuid.uuid4().hex[:6]}",
        "company_id": COMPANY, "phone": PHONE,
        "direction": "outbound",
        "text": "Aproveitando, quer conhecer o PlayHub?",
        "created_at": datetime.now(timezone.utc).isoformat()})
    correction = await analyze_short_term_context(
        company_id=COMPANY, phone=PHONE,
        user_text="não foi isso que eu perguntei")
    block_corr = inject_memory_block(correction)
    correction_test = {
        "is_correction": correction["is_correction"],
        "block_excerpt": block_corr[:200],
        "pass": (correction["is_correction"] and
                  "CORRIGIU" in block_corr),
    }

    # Persistidos em ai_evaluations
    n_log = await db.ai_evaluations.count_documents(
        {"company_id": COMPANY, "kind": "SHORT_TERM_MEMORY"})
    n_recovered = await db.ai_evaluations.count_documents(
        {"company_id": COMPANY, "kind": "SHORT_TERM_MEMORY",
         "context_recovered": True})
    n_error = await db.ai_evaluations.count_documents(
        {"company_id": COMPANY, "kind": "SHORT_TERM_MEMORY",
         "context_error": True})

    passed = sum(1 for r in results if r["pass"]) + (1 if correction_test["pass"] else 0)
    total = len(results) + 1

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "company": COMPANY,
        "passed": passed, "total": total,
        "ai_evaluations_logged": n_log,
        "context_recovered_logged": n_recovered,
        "context_error_logged": n_error,
        "results": results,
        "correction_test": correction_test,
    }
    path = "/app/docs/RELATORIO_SHORT_TERM_MEMORY.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"Result: {passed}/{total}")
    for r in results:
        print(f"  {'✅' if r['pass'] else '❌'} \"{r['answer']}\" → recovered={r['context_recovered']} reply: \"{r['rewritten'][:80]}\"")
    print(f"  {'✅' if correction_test['pass'] else '❌'} correção do cliente")
    print(f"\nai_evaluations entries: log={n_log} recovered={n_recovered} error={n_error}")
    print(f"\n[ok] {path}")


if __name__ == "__main__":
    asyncio.run(main())
