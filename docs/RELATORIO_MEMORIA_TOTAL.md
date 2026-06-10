# OPERAÇÃO MEMÓRIA TOTAL — Relatório Executivo

**Data:** 2026-02-10
**Diretor responsável:** Isabella (Customer Success Director)
**Status:** ✅ Concluído e validado em produção (banco real, política Zero-Mocks)

---

## Bugs eliminados

### 🔴 Bug #1 — Truncate ao contrário (perda da conversa atual)
`services/ai_history.py` iterava o histórico do **mais antigo para o mais
recente** e dava `break` ao primeiro estouro do budget de tokens. Resultado:
em conversas longas (>30 turnos), a Isabella só via mensagens **antigas**
e perdia exatamente o que o cliente tinha acabado de dizer.

**Correção:** iteração invertida — começa pelo turno mais recente,
acumula até preencher o budget de 6000 tokens, depois reverte para ordem
cronológica. Garante que as últimas mensagens **nunca** sejam descartadas.

Janela ampliada de 100 → 200 mensagens (cap real continua sendo
token-budget).

### 🔴 Bug #2 — Sem memória de 15/30/60 dias
Não existia retrieval de longo prazo. A Isabella só lia
`aihub_wa_messages` recentes. OS abertas há 20 dias, NPS de uma semana,
eventos de truck-roll-avoided não chegavam ao prompt.

**Correção:** novo serviço `services/long_term_memory.py` que consulta
**5 collections reais** por janela cronológica:

| Janela | Pergunta respondida                     |
| ------ | --------------------------------------- |
| 15d    | "o que aconteceu recentemente?"         |
| 30d    | "qual o padrão do último mês?"          |
| 60d    | "ele é cliente recorrente em problemas?"|

Fontes: `aihub_wa_messages`, `ai_evaluations`, `tickets`,
`executive_ledger`, `subscribers`, `wa_conversations`.

---

## Arquivos alterados

```
services/ai_history.py         (rewrite do algoritmo de truncate)
services/long_term_memory.py   (NOVO — 260 linhas)
routes/whatsapp_twilio.py      (inject do bloco long-term no system prompt)
scripts/test_memory_pipeline.py (NOVO — 4 testes Zero-Mocks)
```

---

## Pipeline final do system prompt da Isabella

```
[BASE PROMPT]
+ [Dados do cliente]                       (subscriber_ctx)
+ === GUARDIÃO ANTI-CPF ===               (anti_cpf_guardian)
+ === MEMÓRIA DE CURTO PRAZO ===          (short_term_memory_guard)
+ === MEMÓRIA HISTÓRICA DO ASSINANTE ===  (long_term_memory) ← NOVO
+ === CORREÇÕES RECENTES ===              (ai_corrections)
+ === CONTEXTO ORQUESTRADO ===            (ai_orchestrator)
+ [history_turns ASC, 200 msgs / 6k tokens] ← agora preserva as recentes
+ [user_text atual]
```

---

## Validação Zero-Mocks executada

`python3 /app/backend/scripts/test_memory_pipeline.py`

```
[1] HISTORY KEEPS RECENT MESSAGES         ✅
  - phone com 41.974 msgs reais
  - últimas mensagens presentes nos turns
[2] LONG-TERM MEMORY SUMMARY              ✅
  - janelas 15/30/60d retornam estrutura completa
[3] LONG-TERM MEMORY BLOCK INJECTION      ✅
  - bloco 2.739 chars (cabe folgado em 8k)
[4] SHORT REPLY MANTÉM HISTÓRICO          ✅
  - 26 turnos disponíveis (13 cliente + 13 Isabella)
```

Smoke test end-to-end com phone real:
- `5521998176526` (41k mensagens)
- Total enviado ao LLM: **14.109 chars** (~3.5K tokens)
- Long-term block: presente, 5 outcomes da janela 15d com NPS≈6
- History: 26 turnos balanceados

---

## Impacto para a operação

1. Isabella nunca mais "esquece" o que disse 3 minutos atrás na mesma
   conversa — o turno atual sempre faz parte do contexto.
2. Quando o cliente fala "olha aquele problema do mês passado", a
   Isabella **já sabe** qual OS, qual técnico, qual o NPS dado.
3. Cross-sell deixa de ser cego: a memória mostra histórico financeiro
   (truck-roll-avoided, etc) para decisões de retenção.

---

## Não vai mais quebrar
- Token budget é respeitado (corta o passado, nunca o presente).
- `context_reset_at` continua honrado (teste de gestor não afetado).
- Falha em qualquer fonte do long-term degrada com `logger.warning` —
  resposta da Isabella não trava.
