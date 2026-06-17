# Isabella Boleto Flow — Refinamento Best Practices

**Data:** 17/02/2026 (CEO P0)
**Arquivo:** `/app/backend/services/boleto_flow.py`

## Contexto
CEO solicitou refinamento do fluxo de resposta da Isabella quando o cliente pede boleto/2ª via via WhatsApp, com base em **best practices de chatbot ISP/telecom no Brasil + LGPD** (pesquisa 02/2026).

## Estado anterior
- Intent detection (regex/keywords) ✅
- Lookup multi-canal: `subscriber_phones` → `atlaz_clients_cache` → CPF fallback ✅
- Sync das faturas via Atlaz V2 `/faturas` em `subscriber_invoices` ✅
- Mensagem WhatsApp **ENXUTA**: só anunciava "vou mandar o PDF" + valor + vencimento.
- PDF anexo branded enviado em paralelo ✅
- Estado `boleto_flow_state` para CPF awaiting ✅

## Gaps identificados vs Best Practices

| # | Best Practice (fontes) | Estado anterior |
|---|---|---|
| 1 | Expor PIX/QR e linha digitável diretamente no chat | ❌ Só no PDF |
| 2 | Link clicável do boleto na mensagem | ❌ Só no PDF |
| 3 | Mostrar valor com juros/multa quando vencido | ❌ Só valor original |
| 4 | Status visual de urgência (🟢/🟡/🔴) | ❌ Texto puro |
| 5 | Descrição da cobrança (mensalidade vs multa vs avulso) | ❌ Omitida |
| 6 | Handoff proativo para negociação em atraso >15d | ❌ Não havia |
| 7 | Disclaimer pós-pagamento (até 1 dia útil) | ❌ Não havia |
| 8 | LGPD — minimização de dados sensíveis | ✅ Já não expunha CPF |

## Entregas

### `_format_linha_digitavel(barcode)`
Formata 47 dígitos no padrão FEBRABAN `XXXXX.XXXXX XXXXX.XXXXXX XXXXX.XXXXXX X XXXXXXXXXXXXXX` para o cliente digitar no internet banking.

### `_status_emoji_and_label(due_iso)`
Retorna `(emoji, label)` mapeado pelo delta de dias:
- `>7d`: 🟢 no prazo
- `0-7d`: 🟡 vence em X dias / 🟡 vence HOJE
- `<0`: 🔴 venceu há X dias

### `format_invoices_message()` reescrito
Texto agora exibe:
1. Header `*Sua 2ª via — Ligo Fibra* 💚`
2. Por fatura:
   - Descrição da cobrança (`Mensalidade`/`MULTA CONTRATUAL`/etc)
   - Valor original
   - Vencimento + emoji visual + label semântico
   - Valor atualizado com juros (`raw.valor_com_juros`) + breakdown `(multa X% + juros Y%/mês)` quando aplicável
   - Link `boleto_url` clicável
   - Linha digitável formatada FEBRABAN
   - **PIX copia-e-cola** se Atlaz expõe (`raw.pix_copia_cola | pix | pix_emv | qrcode_pix`)
3. Totais (original + atualizado) quando há >1 fatura
4. Anúncio do PDF anexo
5. **Orientação proativa**: se vencida >15d, oferece negociação ("quero negociar" → handoff para time financeiro)
6. Disclaimer pós-pagamento (até 1 dia útil)

## Validação end-to-end (com dado real do Atlaz)

Cliente `external_code=1914546` (ALVARO MARCELO, 3 faturas: 2 overdue + 1 open):

```
*Sua 2ª via — Ligo Fibra* 💚

Olá, ALVARO! Encontrei *2 faturas* em aberto no seu cadastro:

📄 *Fatura 1/2 — 0000 - TESTE - BOLETO - LIGO*
💵 Valor original: *R$ 10,00*
📅 Vencimento: 29/04/2026 🔴 (venceu há 49 dias)
🔗 Boleto online:
https://ligofibra.atlaz.com.br/boleto/ec5a6dec-...
🧾 Linha digitável:
`75691.32603 01403.838004 00245.190012 3 14310000001000`

📄 *Fatura 2/2 — Mensalidade*
💵 Valor original: *R$ 5,00*
📅 Vencimento: 10/05/2026 🔴 (venceu há 38 dias)
💰 *Valor atualizado: R$ 5,11* (multa 2.00% + juros 1.00%/mês)
🔗 Boleto online:
https://ligofibra.atlaz.com.br/boleto/71361798-...
🧾 Linha digitável:
`75691.32603 01403.838004 00222.200024 3 14420000000500`

💵 *Total original: R$ 15,00*
💰 *Total atualizado: R$ 15,11*

📎 Também estou enviando o(s) PDF(s) logo abaixo, prontos pra pagar pelo app do banco.

⚠️ Há fatura vencida há 49 dias. Se quiser *negociar ou parcelar*, é só me dizer "quero negociar" que eu te encaminho pro time financeiro. 💙

Qualquer dúvida é só me chamar! 💙
```

## Best practices fontes consultadas (web search 02/2026)
- **LGPD/Pix**: minimização de dados, finalidade explícita, mascaramento de identificadores
- **ISP/Telecom BR**: integração nativa BSS, fluxo `identificação → menu → 2ª via → PIX/QR → confirmação`, handoff em contestação
- **Conversational AI Billing**: AI para tarefas de baixo risco (status, vencimento, 2ª via), human escalation em disputa/fraude, identity beyond CPF
- Métricas a monitorar: resolution rate, escalation rate, response time, CSAT

## Backlog futuro
- **PIX copia-e-cola via Atlaz**: hoje a API `/faturas` não retorna o campo PIX (apenas linha digitável). Avaliar se a API expõe endpoint separado `/pix-cobranca` para enriquecer.
- **Confirmação de pagamento**: quando cliente diz "já paguei", consultar `paid_date` e auto-responder.
- **Handoff de negociação**: quando cliente digita "quero negociar", abrir ticket de financeiro automaticamente (integração com `routes/financeiro_ops.py`).
- **Anti-fraude**: para faturas >R$500 ou vencidas >60d, exigir 2FA leve (data nascimento ou últimos 4 do CPF) antes de enviar.
- **Métricas**: dashboard `Watchtower Atendimento` com resolution rate / escalation rate / tempo até PDF entregue.
