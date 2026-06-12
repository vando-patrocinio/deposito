"""Migration: renomeia a agente de cobrança Camila → Pâmela.

Decisão de arquitetura:
  • NOME do agente (lookup em `aihub_agents.name`) e rótulos visíveis
    mudam para "Pâmela".
  • Slugs/keys internos persistidos em dados históricos ("camila",
    "camila_billing", kind "OPORTUNIDADE_RETENCAO_CAMILA") permanecem
    válidos para não quebrar registros antigos; novos eventos usam
    "pamela".

O que esta migration faz (idempotente):
  1. aihub_agents: name "Camila" → "Pâmela" em TODAS as companies,
     preservando o `id` do agente. Reaplica o prompt pamela_v2.md.
  2. wa_conversations.routed_agent_name "Camila" → "Pâmela".
  3. isabella_prompt_fragments seedados (updated_by ^seed:) das
     categorias upgrade/novidade: remove preços hardcoded apontando
     para a tabela oficial.

Uso:
  cd /app/backend && python3 migrations/rename_camila_pamela.py
  (ou MIGRATION_COMPANY_ID=co-xxx para limitar a uma company)
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

NEW_UPGRADE_CONTENT = (
    "Gatilhos de oferta de upgrade:\n"
    "- Cliente reclama 'internet lenta' MAS o sinal está OK no SmartOLT\n"
    "  → provavelmente plano insuficiente pra qtd de pessoas/dispositivos\n"
    "- Cliente menciona ter MAIS de 5 dispositivos / Smart TVs / jogos\n"
    "- Cliente está em plano de entrada há > 12 meses\n"
    "- Cliente reclama de 4K travando\n\n"
    "REGRA DE PREÇO: o valor do upgrade vem SEMPRE da tabela\n"
    "=== PREÇOS E VALORES ===. NUNCA invente valor.\n\n"
    "Frases-modelo (cada uma em bolha própria entre aspas):\n"
    "\"Pelo seu uso, parece que o plano atual está apertado.\"\n"
    "\"Posso te mostrar o upgrade que resolve isso, com o valor certinho?\"\n"
    "\"Posso ativar agora ou prefere conhecer outras opções?\""
)

NEW_NOVIDADE_CONTENT = (
    "Apresente NOVIDADES quando:\n"
    "- Cliente perguntar sobre 'roteador novo', 'Wi-Fi melhor'\n"
    "- Cliente comprou Smart TV / câmera / NAS\n"
    "- Cliente trabalha em home-office, VPN, jogos online\n"
    "- Cliente reclama de Wi-Fi fraco em vários cômodos\n\n"
    "Catálogo de novidades pra ofertar (valores SEMPRE da tabela\n"
    "=== PREÇOS E VALORES ===, NUNCA de cabeça):\n"
    "- Wi-Fi 6 (ponto adicional)\n"
    "- IP Público Fixo — para câmeras, VPN, jogos\n"
    "- Ponto Wi-Fi Plus — mais alcance\n\n"
    "Regra: apresente 1 novidade por conversa, na bolha mais natural."
)


async def run(company_id: str | None = None) -> dict:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit("MONGO_URL/DB_NAME ausentes no .env")
    cli = AsyncIOMotorClient(mongo_url)
    db = cli[db_name]
    result = {"agents_renamed": 0, "conversations_updated": 0,
                "fragments_updated": 0, "prompt_synced": []}
    try:
        q: dict = {"name": "Camila"}
        if company_id:
            q["company_id"] = company_id

        # 1. Rename agentes (preserva id)
        companies = []
        async for ag in db.aihub_agents.find(q, {"_id": 0, "company_id": 1}):
            companies.append(ag["company_id"])
        r = await db.aihub_agents.update_many(q, {"$set": {
            "name": "Pâmela",
            "description": "Financeiro (boleto, fatura, 2ª via, PIX).",
            "updated_by": "migration:rename_camila_pamela",
        }})
        result["agents_renamed"] = r.modified_count

        # 2. Reaplica prompt pamela_v2.md nas companies renomeadas
        #    (e nas que já tinham Pâmela, garante o prompt novo)
        try:
            from services.prompt_loader import sync_one
            all_pamela = await db.aihub_agents.find(
                {"name": "Pâmela"}, {"_id": 0, "company_id": 1},
            ).to_list(100)
            for ag in all_pamela:
                s = await sync_one("Pâmela", "pamela_v2.md", "V2",
                                       company_id=ag["company_id"])
                result["prompt_synced"].append(
                    {ag["company_id"]: s.get("action") or s.get("skipped")})
        except Exception as e:
            result["prompt_synced"].append({"error": str(e)})

        # 3. Conversas roteadas
        cq: dict = {"routed_agent_name": "Camila"}
        if company_id:
            cq["company_id"] = company_id
        r2 = await db.wa_conversations.update_many(
            cq, {"$set": {"routed_agent_name": "Pâmela"}})
        result["conversations_updated"] = r2.modified_count

        # 4. Fragments seedados com preço hardcoded → conteúdo sem preço
        for cat, content in (("upgrade", NEW_UPGRADE_CONTENT),
                                ("novidade", NEW_NOVIDADE_CONTENT)):
            fq: dict = {"category": cat,
                          "updated_by": {"$regex": "^seed:"}}
            if company_id:
                fq["company_id"] = company_id
            r3 = await db.isabella_prompt_fragments.update_many(
                fq, {"$set": {
                    "content": content,
                    "updated_by": "migration:rename_camila_pamela",
                }})
            result["fragments_updated"] += r3.modified_count
    finally:
        cli.close()
    print(f"rename_camila_pamela: {result}")
    return result


if __name__ == "__main__":
    cid = os.environ.get("MIGRATION_COMPANY_ID") or None
    asyncio.run(run(cid))
