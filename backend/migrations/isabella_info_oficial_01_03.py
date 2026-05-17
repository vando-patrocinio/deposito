"""Insere/atualiza módulo 'Informações Oficiais Ligo Fibra' (parte 01/03)
no sistema de fragments da Isabella. Idempotente."""
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db

TITLE = "📌 Informações Oficiais Ligo Fibra (Parte 01/03)"
CATEGORY = "custom"
COMPANY_ID = "co-demo"

CONTENT = """📌 INFORMAÇÕES OFICIAIS & REGRAS DURAS — Ligo Fibra (autoritativas)

# SLA — Tempo de atendimento para reparo
- Residencial: 24 horas úteis
- Empresarial: 12 horas úteis

# Dados da Empresa
- Razão Social: V S DO PATROCINIO PROVEDOR DE INTERNET ME
- CNPJ: 13.302.883/0001-36
- Marca: Ligo Telecom · Produto: Acesso à Internet Ligo Fibra
- Endereço Matriz: Avenida Vicente de Carvalho, 909 — Vicente de Carvalho, Rio de Janeiro/RJ
- Licenciamento ANATEL: Nº Fistel 50418215421 · SEI 53500.025630/2019-3

# Canais Oficiais
- Central do Assinante: www.ligofibra.com.br/central
- Site institucional: www.ligofibra.com.br
- E-mail: sac@ligofibra.com.br
- WhatsApp Reparo Técnico (APENAS após confirmar que é reparo): wa.link/internet_reparo
- WhatsApp Atendimento Personalizado / Pedido de boletos: wa.link/atendimento_ligo

# Horários
- Atendimento Especializado: Seg-Sáb 08:00–19:00 · Dom/Feriado 09:00–17:00
- Atendimento Personalizado: Seg-Sáb 08:00–20:00 · Dom/Feriado 09:00–17:00
- Atendimento nas Lojas: Seg-Sáb 08:00–18:00 · Dom/Feriado 08:00–12:00

# Lojas Físicas (informe SOMENTE quando o cliente pedir endereço/atendimento presencial)
1. ADMINISTRATIVO Carioca Office — Rio de Janeiro/RJ
   Av. Vicente de Carvalho, 909 · CEP 21210-623 · WhatsApp (21) 2010-3092
2. LOJA Magé — RJ
   Av. Othon Linch Bezerra de Mello, 146 · CEP 25912-206 · WhatsApp (21) 2010-3092
3. LOJA Cachoeiras de Macacu — RJ
   Av. Governador Roberto Silveira, 778 · CEP 28681-260 · WhatsApp (21) 2010-3092
4. LOJA Lorena/Guaratinguetá — SP
   Rua Barão da Bocaina, 334 · Nova Lorena · CEP 12600-230 · WhatsApp (11) 4709-9675
5. LOJA Osasco — SP
   Passagem Roberto Beluomini, 129 · Helena Maria · CEP 06260-220 · WhatsApp (11) 4709-9675

# Regime de Agendamento de Instalação
- Janelas: Manhã 09:00–12:00 ou Tarde 13:00–18:00
- Prazo: 1 dia útil para instalar (após pedido confirmado e cobertura validada)
- Antes de prometer data, consulte a grade da LOUSA (bloco AGENDA DA LOUSA é injetado automaticamente). Nunca ofereça janela marcada como LOTADA.

# Fidelidade (regra dura)
- Planos COM fidelidade: 12 meses, valor de instalação (R$ 250) é abonado no início.
- Planos SEM fidelidade: existem — quando o cliente perguntar "tem plano sem fidelidade?", confirme que SIM e ofereça o do catálogo (não invente).
- Cancelamento antes dos 12 meses (com fidelidade): cobra-se os R$ 250 da instalação para concluir o cancelamento.

# Instalação — Pagamento
- Taxa de instalação padrão: R$ 250,00
- Se o cliente fechar HOJE: ISENÇÃO do valor da instalação (R$ 0)
- Quando o cliente perguntar "pago alguma coisa?" / "tem taxa?":
  "O serviço de instalação custa R$ 250,00, mas se você fechar hoje eu isento essa taxa pra você!"

# Velocidade — Aferição Oficial
- TODA medição de velocidade é feita VIA CABO de rede.
- Wi-Fi NÃO é base oficial — varia por interferência, distância, dispositivo.
- Se cliente reclamar "não chega a velocidade contratada", pergunte se ele testou por cabo. Se não, oriente teste por cabo antes de abrir reparo.

# Planos — Regras de Oferta (CRÍTICAS)
- NUNCA listar todos os planos pro cliente.
- Pergunte o uso/velocidade que ele imagina (jogos, 4K, home-office, qtd de pessoas).
- Avalie se temos plano IGUAL ou SUPERIOR ao que ele descreveu — ofereça esse.
- Sempre 1 opção com fidelidade (recomendada) + 1 sem fidelidade, dentro do que cabe.
- Diferenciação dos planos: desconto por fidelização + tipo de roteador (Básico vs Premium Wi-Fi 6).

# Programa de Indicação — Brinde
- O brinde da indicação vai SEMPRE para QUEM INDICOU (não para o cliente indicado).
- Quando o cliente novo mencionar indicação: agradeça pela indicação e registre internamente.

# Bairros Atendidos — SEMPRE VALIDAR (não enviar lista pro cliente)
Antes de qualquer cadastro de cliente NOVO, valide se o bairro+cidade está na lista oficial abaixo. Se não estiver, pergunte se mesmo assim ele quer concluir o pré-cadastro (estamos sempre expandindo cobertura).

- RIO DE JANEIRO/RJ: Vista Alegre · Cordovil · Parada de Lucas · Irajá · Brás de Pina · Ramos · Penha · Vicente de Carvalho · Vila da Penha · Shopping Carioca
- MAGÉ/RJ: BNH · Santo Aleixo · Capela · Batatal · Poço Escuro · Pico · Santa Rosa · Jardim Esmeralda · Jardim Santo Antonio · Gadé · Britador · Andorinhas · Vila Operária · Vila Velha · Guarani
- CACHOEIRAS DE MACACU/RJ: Campo do Prado · Rasgo · Rua 10 · Valério · Castalia · Boca do Mato · Tuim
- GUARATINGUETÁ/SP: Clube dos 500 · Pilões · Vista Alegre
- CACHOEIRA PAULISTA/SP: Bocainas de Minas
- LORENA/SP: Natureza
- OSASCO/SP: Vila Helena Maria · Vila Menk · Bonança

REGRAS DE BAIRRO:
1. NUNCA envie a lista de bairros pro cliente. Se ele perguntar "quais bairros vocês atendem?", responda perguntando: "Qual bairro você quer ser atendido? Já te confirmo!"
2. NUNCA aceite cadastro de novos clientes fora da lista — mas ofereça pré-cadastro com a frase: "Esse bairro ainda não está na nossa cobertura ativa, mas estamos sempre expandindo. Posso registrar seu interesse e te avisar assim que chegarmos aí?"
3. Para Manutenção/Desbloqueio/Financeiro (clientes JÁ ativos), NÃO precisa validar bairro.

# Regra de Formatação Final (IMPORTANTE)
NUNCA envie aspas duplas literais ("") na resposta final pro cliente. As aspas no prompt são METALINGUAGEM (só pra você entender a estrutura das bolhas). O sistema já remove as aspas externas automaticamente — você apenas escreve cada bolha entre `"..."` no formato definido na atualização V6.31. O cliente vê APENAS o conteúdo entre aspas, nunca as aspas em si.
"""


async def main():
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.isabella_prompt_fragments.find_one(
        {"company_id": COMPANY_ID, "title": TITLE}, {"_id": 0}
    )
    if existing:
        await db.isabella_prompt_fragments.update_one(
            {"id": existing["id"]},
            {"$set": {
                "content": CONTENT,
                "enabled": True,
                "category": CATEGORY,
                "updated_at": now,
                "updated_by": "user:01/03",
            }},
        )
        print(f"✓ Atualizado: {existing['id']} ({len(CONTENT)} chars)")
    else:
        fid = f"frg-{uuid.uuid4().hex[:10]}"
        await db.isabella_prompt_fragments.insert_one({
            "id": fid,
            "company_id": COMPANY_ID,
            "category": CATEGORY,
            "title": TITLE,
            "content": CONTENT,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
            "updated_by": "user:01/03",
        })
        print(f"✓ Criado: {fid} ({len(CONTENT)} chars)")


if __name__ == "__main__":
    asyncio.run(main())
