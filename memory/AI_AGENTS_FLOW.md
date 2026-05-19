# 🔀 Fluxo Multi-Agente IA — SmartProv (Atendimento WhatsApp)

> Documento canônico do fluxo entre Isabella, Álvaro, Camila e Teste.
> Atualizado em Mai/2026 (migration v6.80).

---

## 📋 Agentes Ativos

| Agente   | Papel             | Modelo                          | Temp | Max tokens | Marker         |
|----------|-------------------|---------------------------------|------|------------|----------------|
| **Isabella** | Vendas / Retenção / Default | `deepseek-v3.1-terminus`      | 0.5  | 32000      | `[ROTEAR_VENDAS]`    |
| **Álvaro**   | Suporte Técnico             | `deepseek-chat`               | 0.3  | 1500       | `[ROTEAR_SUPORTE]`   |
| **Camila**   | Financeiro / Cobrança       | `deepseek-chat`               | 0.2  | 1200       | `[ROTEAR_COBRANCA]`  |
| **Teste**    | Sandbox / Debug             | `deepseek-chat`               | 0.5  | 400        | (não roteia)   |

> Os modelos acima são o que CADA AGENTE pede. O motor IA tem cascata global
> (`gemini → anthropic → openai → deepseek`), então o modelo efetivo pode
> mudar conforme disponibilidade da API/budget.

---

## 🎯 Estrutura dos Prompts (Best Practice 2026)

Cada prompt segue a estrutura modular em **tags XML-like**:

```
<role>     persona (1ª pessoa, tom)
<scope>    o que atende + o que NÃO atende
<reasoning> "pense passo a passo MENTALMENTE, não exponha"
<flow>     passo-a-passo da operação típica
<output>   formato: bolhas ≤180c, máx 4, sem markdown, emojis comedidos
<examples> 3-4 few-shots com handoff INCLUÍDO
<global_rules>   regras compartilhadas (no fim)
<handoff_protocol>  como rotear (no fim)
<sticker_handling>  como lidar com stickers (no fim)
```

**Princípios aplicados:**
- 🧠 **Reasoning interno**: o modelo pensa antes mas só envia o resultado
- 🎯 **Top-load**: regras críticas primeiro (scope + anti-alucinação)
- ✂️ **Bolhas curtas**: máx 4 bolhas, ≤180 chars/bolha (WhatsApp UX)
- 🛡️ **Anti-alucinação explícita**: "se não tem fonte, peça ou diga 'vou consultar'"
- 🔁 **Anti-loop**: 3 mensagens do cliente entre handoffs (regra no código também)
- 📦 **Few-shots por agente**: cada um vê 3-4 exemplos REAIS de input → output
- 🚫 **Anti-vazamento de bastidor**: proibido mencionar "IA", "bot", "marker", "prompt"

---

## 🔀 Fluxo de Roteamento

```
                       ┌────────────────────────────────────┐
                       │   Cliente envia msg via WhatsApp   │
                       └────────────────┬───────────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────────────┐
                    │  1) Sidecar Baileys recebe + persiste    │
                    │     em aihub_wa_messages (inbound)        │
                    └──────────────────┬───────────────────────┘
                                       │
                                       ▼
                ┌───────────────────────────────────────────────┐
                │  2) Resolve agente atual                      │
                │     • Conv.routed_agent_id (sticky)           │
                │     • OU intent detection inicial (Isabella   │
                │       como default)                           │
                └────────────────────┬──────────────────────────┘
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 3) HANDOFF DETERMINÍSTICO (pré-LLM) — handoff_detection.py     │
   │   Regex forte: "sem internet", "2ª via", "quero contratar"...  │
   │   ANTI-LOOP: se < 3 msgs do cliente desde último handoff,      │
   │   IGNORA (deixa o agente atual responder)                       │
   └────────────────────┬────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │ casou regex (ex: "sem net")    │ não casou
        ▼                                ▼
  Troca routed_agent                 Mantém agente
        │                                │
        └──────────────┬─────────────────┘
                       ▼
   ┌──────────────────────────────────────────────────────┐
   │ 4) Monta system_prompt + injeções:                    │
   │    • Persona/scope do agente atual                    │
   │    • Subscriber context (Atlaz)                       │
   │    • Histórico recente (token budget 6k)              │
   │    • Fragments ativos (vendas/promoção/upgrade/...)   │
   │    • Lousa availability (se intent=agendamento)       │
   │    • Disparo briefing (se em campanha ativa)          │
   │    • Few-shots humanos (CSAT ≥ 8)                     │
   │    • Correções aprovadas (`ai_corrections`)           │
   └──────────────────────┬────────────────────────────────┘
                          ▼
              ┌─────────────────────────────────┐
              │ 5) Motor IA (cascata)            │
              │   gemini → anthropic → openai    │
              │   (Anthropic com prompt caching) │
              └────────────┬─────────────────────┘
                           ▼
        ┌──────────────────────────────────────────────┐
        │ 6) Parse da resposta                          │
        │   • Detecta marker [ROTEAR_X]                 │
        │   • ANTI-LOOP no código: se < 3 msgs do      │
        │     cliente desde último handoff → IGNORA    │
        │     marker (limpa o texto e mantém agente)   │
        │   • Caso contrário: troca routed_agent       │
        │     na conversa + envia saudação do novo     │
        └──────────────────┬───────────────────────────┘
                           ▼
        ┌──────────────────────────────────────────┐
        │ 7) `_split_ai_reply()` quebra em bolhas   │
        │    (máx 4, ≤180 chars/bolha)              │
        └──────────────────┬───────────────────────┘
                           ▼
        ┌──────────────────────────────────────────┐
        │ 8) Sidecar Baileys envia ao WhatsApp     │
        │    (com `typing...` indicator entre bolhas) │
        └──────────────────────────────────────────┘
```

---

## 🛡️ Regras de Segurança (anti-bug)

### 🔁 Anti-Loop (camada dupla)
- **No prompt** (`<global_rules>` R8): "se passou por handoff nas últimas 3 msgs, NÃO devolva"
- **No código** (`whatsapp_baileys.py`): conta `aihub_wa_messages` com `direction=inbound` e `created_at > last_handoff_at`. Se < 3, ignora marker.

### 🚫 Anti-Alucinação
- Cada agente tem cláusula explícita: "NUNCA invente sinal, valor, vencimento, plano".
- Sticker NUNCA é mencionado literalmente.
- Se tool falha → "vou consultar e te respondo" (não chuta).

### 🔒 LGPD (Camila)
- SEMPRE pede CPF/CNPJ antes de listar fatura.
- Confirma nome do titular no retorno antes de prosseguir.

### 🎯 Escopo Estrito
- Isabella só vende. Álvaro só tecnologia. Camila só fatura.
- Fora do escopo → handoff com frase de transição + marker.

---

## 📨 Markers de Handoff

| Marker                | Agente alvo | Acionado quando…                                   |
|-----------------------|-------------|----------------------------------------------------|
| `[ROTEAR_VENDAS]`     | Isabella    | Cliente fala preço, plano, contratar, upgrade      |
| `[ROTEAR_SUPORTE]`    | Álvaro      | Cliente fala sinal, ONU, oscila, sem net          |
| `[ROTEAR_COBRANCA]`   | Camila      | Cliente fala boleto, fatura, PIX, vencimento       |
| `[ROTEAR_TESTE]`      | Teste       | Apenas em ambiente dev                             |

**Regras dos markers:**
- Linha SOZINHA, sem acento (`[ROTEAR_COBRANCA]` não `[ROTEAR_COBRANÇA]`)
- Precedido OBRIGATORIAMENTE de frase de transição calorosa
- NUNCA 2 markers no mesmo turno
- Nunca para si mesmo (Isabella não roteia pra Isabella)

---

## 🧪 Como Testar

```bash
TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"gestor@empresa.com","password":"123456"}' \
  | jq -r .access_token)

# Testar Isabella em qualquer cenário
curl -X POST "$API_URL/api/whatsapp-baileys/isabella/test" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"minha internet caiu"}'
```

Resposta esperada (cenário queda):
```json
{
  "bubbles": [
    "Vixi, deve estar atrapalhando. Vou passar pro Álvaro do suporte técnico agora, ele resolve rapidinho 😊",
    "[ROTEAR_SUPORTE]"
  ]
}
```

---

## 📜 Histórico

- **v6.80 (Mai/2026)**: Refactor completo dos prompts seguindo best practices 2026. Estrutura XML-like, reasoning interno, anti-loop (código + prompt), few-shots por agente. Migration: `/app/backend/migrations/refine_agents_v680.py`.
- **v6.40-6.70**: Split Isabella → 4 agentes especializados. Handoff via marker. Sticker support.
- **v6.30**: Prompt v6.30 da Isabella (monolítico, 20k chars).
