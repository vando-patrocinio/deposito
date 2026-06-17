# Isabella · Prompt + Splitter Fix — 17/02/2026

## Bugs detectados (screenshot do CEO)
1. **Aspas literais envolvendo cada resposta** (`"Tudo certo, Pamela! 😊"`).
   Cliente recebia as aspas como parte do texto.
2. **Respostas vazias estilo "Tudo certo!"** quando cliente mandava `?`
   ou pedido genérico — sem entrega de ação.
3. **Espera de resposta "inexplicável"** — na verdade era sidecar Baileys
   caindo, mensagens do `boleto_flow` ficavam `failed_send` e cliente
   não recebia.

## Root cause

### Aspas literais
- O prompt `isabella_v13.md §1` instruía o LLM a produzir bolhas
  **entre aspas duplas**: `"Primeira bolha."` por linha.
- O `bubble_splitter` NÃO removia essas aspas — apenas `.strip()` de whitespace.
- Resultado: aspas iam direto pro cliente.

### Respostas vazias
- O prompt não tinha regra explícita contra fechamentos genéricos.
- Quando o LLM não classificava bem a intenção do cliente
  (`?`, `ok`, `tudo`), respondia com "fórmulas de polidez" sem ação.

### "Espera de resposta"
- Sidecar Baileys CH1 caiu intermitentemente. Mensagens do boleto_flow
  ficavam `failed_send`. Cliente não via a resposta do boleto e tentava
  de novo. Bug colateral: Isabella respondia ao "?" com fórmula genérica.

## Fixes aplicados

### 1. `services/bubble_splitter.py` (defensivo · regex)
- Novo `_strip_wrapping_quotes(text)`: remove aspas envolventes idempotente
  (regular `"..."`, smart `"..."`, single `'...'`, duplicadas `""..."").
- Integrado no `_clean(text)`: roda por linha antes de qualquer outro passo.
- **Idempotente**: texto sem aspas passa intacto.
- **Não remove aspas internas**: `Você disse "sem sinal"; vou verificar.`
  preserva as aspas de citação.

### 2. `prompts/isabella_v13.md`
- §1 CONTRATO DE SAÍDA reescrito: bolhas **uma por linha, SEM aspas
  envolventes**. Exemplo válido e exemplo inválido explícitos.
- §10 todos os few-shots (EXEMPLOS 1–7) reescritos sem aspas.
- §10 EXEMPLO 8 novo: como responder a mensagens curtas/ambíguas
  (`?`, `ok`, `tudo`, emoji só) **sem fechar a conversa**, sempre
  com **próxima ação clara ou pergunta objetiva**.
- §10 CONTRA-EXEMPLO 2 novo: mostra `"Tudo certo, Pamela! 😊"` como
  PROIBIDO, com explicação do erro.
- §11 Checklist final atualizado: item 4 cita "SEM aspas envolventes",
  item 6 novo: "toda bolha entrega ação concreta ou pergunta objetiva
  (nunca 'Tudo certo!' solto)".

### 3. Reload
- `prompt_loader.sync_all('co-demo')` aplicado: doc Isabella atualizado
  (sha `b3dccd8...`, version `V13_CICLO_COMPLETO`).
- Backend reiniciado pra garantir cache limpo.

## Validação

### Splitter (unitário + end-to-end)
```
input : '"Tudo certo, Pamela! 😊"'
output: ['Tudo certo, Pamela! 😊']        ← aspas removidas

input : '""Olá!""'                         ← aspas duplicadas
output: ['Olá!']

input : '"Primeira bolha."\n"Segunda bolha."'
output: ['Primeira bolha. Segunda bolha.']

input : 'Texto com "aspas internas" no meio.'  ← citação preservada
output: ['Texto com "aspas internas" no meio.']
```

### Watchdog efeito colateral
As 3 mensagens `failed_send` do `boleto_flow` para o phone
`551147099675` (causadoras da "espera") foram reenviadas
automaticamente pelo watchdog Baileys (tag `retry_via=watchdog_baileys`)
após CH1 recuperar conexão. Cliente recebeu o "Você está em dia!".

## Observação fora de escopo (P2)
- Cliente real do screenshot é "Vando Patrocinio" mas o `subscriber_phones`
  resolve para "PAMELA NERY TESTE LIGO" (`ATLAZ-778936`, cadastro de
  teste). Phone duplicado nos dados do Atlaz. Isso é problema de dados,
  não do código. Solução futura: 2FA leve (CPF) quando subscriber
  resolvido tem flag `_is_test` ou ambíguo.

## Backlog
- **Splitter**: hoje o splitter merge linhas curtas adjacentes
  (`"Primeira."` + `"Segunda."` → 1 bolha). Best practice é PRESERVAR
  quebras explícitas do LLM. Vale refatorar `_pack_into_bubbles` pra
  respeitar `\n` como separador HARD quando vier no input.
- **Identidade ambígua**: quando subscriber tem `is_test=true` ou phone
  bate múltiplos cadastros (`=== CONFLITO DE CADASTRO ===`), pedir
  últimos 4 dígitos do CPF antes de personalizar.
- **Métrica de qualidade**: rastrear `quoted_replies_count` no
  `aihub_wa_metrics` pra alarmar caso o LLM volte a quotar — o
  splitter limpa, mas seria sinal de regressão de prompt.
