"""Patch — remove a "Triagem Rápida" antiga do system_prompt da Isabella.

Motivo (17/Fev/2026): a Isabella ignorou o módulo V6.70 (que diz pra
consultar SmartOLT e nunca pedir reset em LOS) porque o `system_prompt`
ainda continha o bloco "Triagem Rápida" antigo: "Por favor, desligue a
ONT e o roteador por 30 segundos." — conflito direto.

Cliente: Vando Patrocinio · phone 5521998176526 — Isabella pediu "bairro
pra checar incidente" e depois "desligue a ONT" mesmo com o cliente
identificado, ONU Online com sinal Very good.

Este patch substitui o bloco "Triagem Rápida ... Coleta visual" por uma
referência clara ao V6.70. A "Triagem Rápida" só faz sentido para casos
em que NÃO temos SmartOLT (clientes não cadastrados) — então simplifica.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db

COMPANY_ID = "co-demo"

OLD_BLOCK_START = "Triagem Rápida\n1) Sem internet (queda)"
OLD_BLOCK_END_MARKER = "Pode me enviar 2 fotos da ONT/roteador"  # fim do bloco

NEW_BLOCK = """Triagem Técnica — IMPORTANTE
🚨 NUNCA peça reset de modem/ONT como primeira ação. O sistema já tem o
módulo "🔧 Diagnóstico Técnico Inteligente (V6.70)" injetado, que faz
consulta REAL no SmartOLT e decide o caminho:
  - ONLINE com sinal bom → troubleshooting de Wi-Fi/aparelho
  - LOS (fibra rompida) → bolha de reparo automática + agendamento
  - Offline → transfere pra Atendimento Especializado
  - Power Fail → ofereça agendamento

Quando o sistema NÃO injetar o bloco "VERIFICAÇÃO DA CONEXÃO" (cliente
não cadastrado), peça o CPF antes de qualquer outra coisa.

NUNCA invente "incidente na região" — só mencione incidente se o sistema
injetar bloco oficial "INCIDENTE EM ANDAMENTO".

SLA & Janelas
- Residencial: 24 horas úteis
- Empresarial: 12 horas úteis
- Contato 09:00-12:00 → visita 13:00-18:00 do mesmo dia
- Contato 13:00-18:00 → visita 09:00-12:00 do dia útil seguinte
- SEMPRE consulte o módulo AGENDA DA LOUSA injetado no contexto antes
  de oferecer data. Nunca prometa janela LOTADA.

Coleta visual (apenas em caso de evidência adicional)
"Pode me enviar 2 fotos da ONT/roteador: frente (LEDs) e traseira (cabos)? 📸\""""


async def main():
    cid = COMPANY_ID
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": "Isabella"}, {"_id": 0, "system_prompt": 1}
    )
    if not agent:
        print("ERRO: agente Isabella não encontrado")
        return
    sp = agent.get("system_prompt") or ""
    start_idx = sp.find(OLD_BLOCK_START)
    if start_idx < 0:
        print("Bloco antigo NÃO encontrado — nada a fazer (já patchado?)")
        return
    end_marker_idx = sp.find(OLD_BLOCK_END_MARKER, start_idx)
    if end_marker_idx < 0:
        print("Marcador final NÃO encontrado")
        return
    # Encontra o fim da linha após o marcador
    end_line_idx = sp.find("? 📸\"", end_marker_idx)
    if end_line_idx < 0:
        # Fallback: até próxima quebra grande
        end_line_idx = sp.find("\n\nFechamento", end_marker_idx)
    if end_line_idx < 0:
        end_line_idx = sp.find("\n\n", end_marker_idx + 200)
    if end_line_idx < 0:
        print("Não conseguiu delimitar o fim do bloco")
        return
    # Inclui o trecho ? 📸"
    end_line_idx = end_line_idx + len('? 📸"')

    new_sp = sp[:start_idx] + NEW_BLOCK + sp[end_line_idx:]
    print(f"Antes: {len(sp)} chars · Depois: {len(new_sp)} chars")
    print(f"Removido: {len(sp) - len(new_sp) + len(NEW_BLOCK)} chars do bloco antigo")
    print(f"Inserido: {len(NEW_BLOCK)} chars de redirecionamento ao V6.70")

    await db.aihub_agents.update_one(
        {"company_id": cid, "name": "Isabella"},
        {"$set": {
            "system_prompt": new_sp,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": "migration:remove_old_triagem",
        }},
    )
    print("✓ system_prompt da Isabella atualizado")


if __name__ == "__main__":
    asyncio.run(main())
