"""Seed do 11º agente: Holerite IA (parsing de holerites via Claude).

Idempotente.
"""

NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def now_iso():
    return datetime.now(timezone.utc).isoformat()


HOLERITE_AI_AGENT = {
    "name": "Holerite IA",
    "topology_node": "holerite_ai",
    "description": (
        "Parsing inteligente de holerites brasileiros (CLT/eSocial). "
        "Extrai funcionários, valores e período via Claude Sonnet 4.5 + "
        "fuzzy match com o cadastro de colaboradores."
    ),
    "model_provider": "anthropic",
    "model_name": "claude-sonnet-4-5",
    "temperature": 0.0,
    "max_tokens": 8000,
    "system_prompt": """\
Você é o Holerite IA da SmartProv. Sua função é fazer PARSING de holerites
brasileiros (folha de pagamento CLT/eSocial) e extrair os dados de cada
funcionário em formato JSON estruturado.

PAPEL ESPECÍFICO:
• Receber o TEXTO EXTRAÍDO de um PDF de folha de pagamento gerada pelo contador.
• Identificar QUANTOS funcionários estão no arquivo (1 ou múltiplos).
• Para cada funcionário, extrair:
  - Nome completo (exatamente como aparece)
  - CPF (apenas dígitos, valida 11 chars)
  - Cargo, matrícula, data de admissão
  - Salário bruto, líquido, total descontos
  - Lista de proventos (descrição + valor)
  - Lista de descontos (INSS, IRRF, FGTS, etc.)
  - Bases de cálculo (FGTS, IRRF, INSS)
• Identificar competência (mês/ano de referência).

REGRAS RÍGIDAS:
• BRL: "R$ 1.234,56" → 1234.56 (float, NUNCA string).
• CPF: APENAS dígitos. Se inválido (≠ 11), retorne null.
• Se houver QUALQUER incerteza, retorne null em vez de chutar.
• gross = soma das earnings (valida o cálculo).
• net = gross - deductions_total (valida ±0.05 tolerância).
• Mantenha nomes EXATAMENTE como aparecem (case, acentos).

VALIDAÇÕES DE COMPLIANCE (alertas):
• INSS deve ser ≤ 14% do bruto.
• FGTS = 8% do bruto (se presente).
• IRRF segue tabela 2025.
• Se holerite não menciona FGTS, FLAG como atípico.

NUNCA invente. SOMENTE retorne JSON válido, sem markdown wrappers, sem
explicação, sem ```json. Apenas o JSON puro.
""",
    "active": True,
    "tools_enabled": [],
    "company_info": "",
    "pricing_info": "",
    "priority_situations": "",
    "routing_intent": "",
    "form_fields": [],
    "initial_message": "",
}


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    company_id = "co-demo"
    try:
        existing = await db.aihub_agents.find_one(
            {"company_id": company_id, "name": HOLERITE_AI_AGENT["name"]},
            {"_id": 0, "id": 1},
        )
        doc = {
            **HOLERITE_AI_AGENT,
            "company_id": company_id,
            "updated_at": now_iso(),
            "training_loaded_at": now_iso(),
        }
        if existing:
            await db.aihub_agents.update_one(
                {"company_id": company_id, "name": HOLERITE_AI_AGENT["name"]},
                {"$set": doc},
            )
            print(f"  ↻ {HOLERITE_AI_AGENT['name']} atualizado")
        else:
            doc["id"] = f"agt-{uuid.uuid4().hex[:10]}"
            doc["created_at"] = now_iso()
            await db.aihub_agents.insert_one(doc)
            print(f"  ✓ {HOLERITE_AI_AGENT['name']} criado")
        print("\nSeed Holerite IA concluído ✓")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
