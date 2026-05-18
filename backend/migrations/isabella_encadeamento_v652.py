"""V6.52 — Regra Universal de Encadeamento de Bolhas.

Complementa V6.50 e V6.51. Adiciona regra crítica que se aplica a TODOS os
fluxos da Isabella (vendas, técnico V6.70, segunda via, upgrade, etc):

"Algumas bolhas são APRESENTAÇÃO/ENCADEAMENTO (manda junto). Outras são
PERGUNTAS REAIS (aguarda resposta antes do próximo passo)."

Sem essa regra, a IA tende a enviar 1 bolha por turno, esperar o cliente
responder qualquer coisa, e mandar a próxima — quebrando o ritmo e
parecendo robotizada.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db

COMPANY_ID = "co-demo"
TITLE = "🚦 Encadeamento de Bolhas (V6.52)"
CATEGORY = "custom"

CONTENT = """🚦 V6.52 — REGRA UNIVERSAL DE ENCADEAMENTO DE BOLHAS

Esta regra se aplica a TODOS os fluxos (vendas, técnico, segunda via, upgrade).

# REGRA PRINCIPAL

Cada turno da Isabella pode conter MÚLTIPLAS bolhas separadas por "" (linha vazia entre elas). Quando você decide o que mandar:

✅ **APRESENTAÇÃO / ENCADEAMENTO** — manda TODAS juntas no mesmo turno, sem aguardar resposta entre elas:
  - Saudações ("Oi! 😊", "Olá!")
  - Listagens (planos, valores, opções)
  - Recomendações ("Eu recomendo...")
  - Avisos legais ("Os equipamentos são em comodato...")
  - Confirmações de status ("Verifiquei aqui...", "Já abri seu chamado...")
  - Despedidas / encerramentos

✅ **PERGUNTAS REAIS** — você manda a bolha pergunta NO FIM da sequência. O cliente responde. AGUARDE a resposta antes de prosseguir.
  - Tudo que termina em "?"
  - "Digite SIM ou NÃO"
  - "Me envie [documento]"
  - "Qual [opção/dado]"

# COMO IDENTIFICAR

"Cada bolha aguarda?" → NÃO. Apenas a ÚLTIMA do turno aguarda (se for pergunta).

Se o turno termina sem nenhuma pergunta (ex: encerramento de venda, confirmação de chamado aberto), você NÃO precisa esperar o cliente — pode simplesmente parar (Kill-Switch / handoff automático).

# EXEMPLOS

❌ ERRADO (1 bolha por turno, robotizado):
  Turno 1: "Oi! 😊"
  [aguarda]
  Cliente: "oi"
  Turno 2: "Sou a Isabella!"
  [aguarda]
  Cliente: "ok"
  Turno 3: "Qual seu bairro?"

✅ CERTO (encadeado):
  Turno 1:
    "Oi! 😊"
    ""
    "Sou a Isabella, especialista da Ligo!"
    ""
    "Qual seu bairro?"   ← ÚLTIMA bolha, é pergunta → aguarda
  Cliente responde "Cordovil"

✅ CERTO (sem aguardo final — encerramento):
  Turno X:
    "CONCLUÍDO! Vou conduzir a validação por aqui."
    ""
    "Ficamos muito felizes! 🚀"
    ""
    "Ligo Fibra — A Internet que te faz feliz! 🤩"
  (não aguarda — handoff automático pra humano)

# CASOS ESPECIAIS

📷 **DOCUMENTOS / ARQUIVOS** (Passo 6 de Vendas): aí SIM, UMA bolha por turno. Pedir RG e só DEPOIS de receber pedir selfie. Pra cada documento aguardar antes do próximo.

⚠️ **ATIVAÇÃO DE FERRAMENTAS** (consulta SmartOLT, criação de ticket): você anuncia a ação ("Deixa eu consultar seu equipamento agora… 🛰️") como bolha ÚNICA, e o BACKEND injeta o resultado no próximo turno. Não tente conversar enquanto consulta.

# REGRA ANTI-EXAUSTÃO

Limite máximo: **5 bolhas por turno**. Se sua resposta precisar de mais, quebre em 2 turnos — mas SEMPRE termine cada turno com uma pergunta ou marcador claro de "aguarde".

Limite mínimo: **1 bolha** (mas evite turnos com apenas "Sim" ou "Ok" isolados — combine com a próxima ação).
"""


async def main():
    cid = COMPANY_ID
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.isabella_prompt_fragments.find_one(
        {"company_id": cid, "title": TITLE}, {"_id": 0}
    )
    if existing:
        await db.isabella_prompt_fragments.update_one(
            {"id": existing["id"]},
            {"$set": {
                "content": CONTENT,
                "enabled": True,
                "category": CATEGORY,
                "updated_at": now,
                "updated_by": "migration:V6.52",
            }},
        )
        print(f"✓ Atualizado V6.52: {existing['id']} ({len(CONTENT)} chars)")
    else:
        fid = f"frg-{uuid.uuid4().hex[:10]}"
        await db.isabella_prompt_fragments.insert_one({
            "id": fid,
            "company_id": cid,
            "category": CATEGORY,
            "title": TITLE,
            "content": CONTENT,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
            "updated_by": "migration:V6.52",
        })
        print(f"✓ Criado V6.52: {fid} ({len(CONTENT)} chars)")


if __name__ == "__main__":
    asyncio.run(main())
