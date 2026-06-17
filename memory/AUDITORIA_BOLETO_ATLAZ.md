# Auditoria · Boleto Atlaz → Isabella — 17/02/2026

**Solicitação CEO:** "está pegando as informações do boleto do Atlaz agora?"

## TL;DR — SIM, está. E acabei de **achar e corrigir** um bug crítico que estava silenciosamente ignorando PIX + valor com juros.

## Cadeia de dados

```
Atlaz V2 /faturas (retornar_pix=1, retornar_nfe=1)
    ↓
routes/atlaz_financeiro.py::_norm_invoice   (achata p/ schema interno EN)
    ↓
db.subscriber_invoices  (upsert)
    ↓
services/boleto_flow.py::_list_open_invoices  (lê por subscriber_external_id)
    ↓
services/boleto_flow.py::format_invoices_message  (formata WhatsApp)
    ↓
WhatsApp + PDF anexo
```

## Estado atual do cache

| Métrica | Valor |
|---|---|
| Total faturas em `subscriber_invoices` | 11.626 |
| Faturas em aberto/overdue | 6.945 |
| Último sync rodou em | 17/06/2026 04:15:29 UTC |
| Fonte | `atlaz_faturas` (V2) |

## Campos confirmados vindo do Atlaz

Cliente real auditado: **SUELI PACHECO DE MENDONCA** (`external_code=1912574`).

| Campo | Origem Atlaz | Persistido como | Auditado |
|---|---|---|---|
| `external_id` | `id` | `external_id` | ✅ `'55998067'` |
| `amount` | `valor` | `amount` | ✅ `99.9` |
| `amount_with_interest` | `valor_com_juros` | `amount_with_interest` | ✅ `102.1` |
| `interest_value` | `juros` | `interest_value` | ✅ `1.0` |
| `fine_value` | `multa` | `fine_value` | ✅ `2.0` |
| `due_date` | `data_vencimento` | `due_date` | ✅ `2026-06-10` |
| `barcode` | `linha_digitavel` | `barcode` | ✅ `75691326030140383800400259060010114730000009990` |
| `boleto_url` | `link` | `boleto_url` | ✅ URL Sicoob |
| `pix_brcode` | `pix_brcode/pix_copia_cola/pix_emv` | `pix_brcode` | ✅ EMV BRCode completo |
| `pix_qrcode_link` | `pix_qrcode_link/pix_qrcode` | `pix_qrcode_link` | ✅ URL imagem |
| `description` | `descricao` | `description` | ✅ `'500M_C/FIDELIDADE_MACACU_99,90_2025*'` |
| `nfe_url` | `nfe.link` | `nfe_url` | ✅ |

## 🚨 Bug encontrado e corrigido

### Problema
O `_norm_invoice` em `atlaz_financeiro.py` **achata** os campos do Atlaz para o **nível raiz** do doc com nomes em inglês (`amount_with_interest`, `pix_brcode`, `interest_value`, `fine_value`).

Mas a versão anterior do `format_invoices_message` lia de `raw.*` com nomes em português (`raw.valor_com_juros`, `raw.pix_copia_cola`, `raw.multa`, `raw.juros`) — **caminho que NÃO EXISTIA** no schema persistido.

### Sintoma
Mensagem do boleto NUNCA exibia:
- PIX copia-e-cola
- Valor atualizado com juros/multa
- Breakdown de encargos

Apesar de o Atlaz retornar TUDO isso (foi confirmado no auditor: `pix_brcode` populado em 0 de 11.626 docs porque ninguém lia o campo certo).

### Fix aplicado em `services/boleto_flow.py`
1. Novo helper `_inv_pick(inv, *keys)`: procura no nível raiz **E** em `raw.*` (fallback p/ docs antigos). Aceita 0 como vazio.
2. Reescrita do `format_invoices_message` usando o helper. Campos mapeados em ambos os dialetos:
   - `pix_brcode | pix_copia_cola | pix_emv | pix`
   - `amount_with_interest | valor_com_juros`
   - `fine_value | multa`
   - `interest_value | juros`
   - `boleto_url | link`
   - `barcode | linha_digitavel`
   - `description | descricao`
3. Novo campo: **QR Code do PIX como imagem** (`pix_qrcode_link`) exibido apenas se não tiver copia-e-cola.
4. Cosmético: descrição com `*` final (ex.: `500M_C/FIDELIDADE_MACACU*`) é sanitizada para não quebrar o markdown `*negrito*`.
5. Multa/juros agora exibidos como **valor em R$** (mais claro que % que vinha quebrado).

## Validação end-to-end (dado real do Atlaz)

```
*Sua 2ª via — Ligo Fibra* 💚

Olá, SUELI! Encontrei *2 faturas* em aberto no seu cadastro:

📄 *Fatura 1/2 — 500M_C/FIDELIDADE_MACACU_99,90_2025*
💵 Valor original: *R$ 99,90*
📅 Vencimento: 10/06/2026 🔴 (venceu há 7 dias)
💰 *Valor atualizado: R$ 102,10* (multa R$ 2.00 + juros R$ 1.00)
🔗 Boleto online:
https://ligofibra.atlaz.com.br/boleto/46bca71b-...
🧾 Linha digitável:
`75691.32603 01403.838004 00259.060010 1 14730000009990`
⚡ *PIX copia-e-cola:*
`00020101021226950014br.gov.bcb.pix2573pix.sicoob.com.br/qr/payload/v2/cobv/f5bc9a6d-...6304B3D0`

📄 *Fatura 2/2 — 500M_C/FIDELIDADE_MACACU_99,90_2025*
💵 Valor original: *R$ 99,90*
📅 Vencimento: 10/07/2026 🟢 (no prazo)
🔗 Boleto online: ...
🧾 Linha digitável: ...
⚡ *PIX copia-e-cola:* ...

💵 *Total original: R$ 199,80*
💰 *Total atualizado: R$ 202,00*

📎 Também estou enviando o(s) PDF(s) logo abaixo...

ℹ️ Após o pagamento, a compensação leva até *1 dia útil*...
```

## Backlog
- Métrica `boleto_pix_inline_count_24h` — quantas mensagens saíram com PIX preenchido vs sem (alarme se cair). Sinaliza problemas no sync.
- Cron job para refresh do `subscriber_invoices` 6x/dia ao invés de manual (hoje só roda quando alguém aciona o endpoint).
- Backfill: forçar `_norm_invoice` retroativo sobre as 11.626 faturas pra reaproveitar `raw.*` perdido (se houver).
