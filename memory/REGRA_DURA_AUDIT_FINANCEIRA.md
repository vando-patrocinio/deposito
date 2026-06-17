# Regra Dura CEO: Conferir → Analisar → Conferir novamente
*17/02/2026 · Incidente "JOELVALDO/JOSEVALDO"*

## Incidente
CEO viu mensagem da Isabella afirmando "JOELVALDO está em dia" e
suspeitou que o cliente **não existia no cadastro**. Pediu auditoria
imediata + regra dura pra afirmações financeiras.

## Auditoria técnica (resposta direta)

**JOELVALDO EXISTE no cadastro:**
- `subscribers.id=sub-7de424b4f29a`
- `external_code=ATLAZ-2065429`
- Nome legal: **JOELVALDO GUIMARAES FILHO** (CPF `39112523828`)
- Apelido WhatsApp: "Junior Rede Osasco" (confundiu CEO)
- Plano R$ 99,90/mês, vencimento dia 10, status ATIVO
- 3 faturas no histórico, **TODAS pagas**
- Última paga: 11/06/2026 · Próxima vencimento: 10/07/2026
- Sync mais recente: 17/06 06:15 UTC (~6h atrás)

A Isabella **acertou tecnicamente**. Mas a regra CEO está corretíssima:
**toda afirmação financeira precisa de prova auditável.**

## Implementação da regra dura

### `services/boleto_flow.py::_audit_subscriber_financial_status`

Antes de qualquer afirmação financeira, 3 verificações independentes:

1. **CONFERIR — Identificação:** subscriber identificado (external_code OU id)?
2. **ANALISAR — Conferência primária:** query múltipla por
   `subscriber_external_id` (string + número) E `subscriber_id`,
   produz contagem paid/open + datas
3. **CONFERIR NOVAMENTE — Freshness:** `last_sync_at` ≤ 24h?

Resultado: `audit_passed: bool` + `warnings: []`. Persistido em
`isabella_financial_audit` (collection nova) com timestamp.

### `format_invoices_message(subscriber, invoices, audit)`

**REGRA: quando `invoices=[]`, NUNCA afirma "em dia" sem `audit_passed=True`.**

#### Caminho 1 — Audit passou
Mostra **evidência explícita**:
```
Oba, JOELVALDO! 🎉

Verifiquei aqui no sistema e *você está em dia* com a Ligo:

✅ Última fatura paga em *11/06/2026*
📅 Próxima fatura vence em *10/07/2026*

Se algo não bate com seu controle pessoal, me avisa que
eu confiro de novo — pode ser cobrança de outro serviço.
```

#### Caminho 2 — Audit falhou (sync stale, sem dados, sem identificação)
**Nunca afirma nada**:
```
Oi, [nome]. 💙

Vou conferir aqui no nosso sistema o status do seu cadastro
com calma. Só um instante — qualquer divergência, eu te aviso
imediatamente.
```

Os `warnings` ficam apenas no log/DB para auditoria pelo gestor, **não vazam pro cliente**.

## Validação

| Cenário | Audit | Mensagem |
|---|---|---|
| Cliente real, em dia, sync 6h | `passed=True` | Mostra prova ✅ |
| Sync stale 72h, sem dados | `passed=False, warnings=[sync_stale, no_data]` | Pede tempo ⏳ |
| Subscriber sem external_id | `passed=False, warnings=[unidentified]` | Pede tempo ⏳ |
| Audit ausente (chamada legada) | tratado como `passed=False` | Pede tempo ⏳ |

## Logs auditáveis

Toda chamada do audit grava 1 doc em `isabella_financial_audit`:
```json
{
  "subscriber_id": "sub-7de424b4f29a",
  "subscriber_external_id": "2065429",
  "subscriber_name": "JOELVALDO GUIMARAES FILHO",
  "company_id": "co-demo",
  "checks": [
    {"check": "identification", "ok": true, "ext": "ATLAZ-2065429"},
    {"check": "primary_count", "ok": true, "paid": 3, "open": 0},
    {"check": "sync_freshness", "ok": true, "stale_h": 6.8}
  ],
  "paid_count": 3,
  "open_count": 0,
  "last_paid_date": "2026-06-11 00:36:11",
  "next_due_date": "2026-07-10",
  "sync_stale_h": 6.8,
  "audit_passed": true,
  "audited_at": "..."
}
```

Permite ao gestor reabrir QUALQUER mensagem de status financeiro e
ver exatamente quais checagens foram feitas + resultados.

## Backlog (não obrigatório, mas saudável)
- Cross-check em tempo real com Atlaz `/faturas` para casos críticos
  (cliente disputando saldo)
- Adicionar política de "double-check" para clientes que tiveram opp
  `dunning` recente: se sync foi <30min mas há sinal de inadimplência
  pendente, exibe "estou cruzando os dados, 1 minuto"
- Dashboard: card de "auditoria financeira 24h" mostrando
  `audit_passed_count` vs `audit_failed_count`
