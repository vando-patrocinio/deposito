# 🔍 IDENTIDADE ÚNICA — AUDIT (read-only · 15/06/2026)

> Fonte do número: `python3 /app/backend/scripts/customer_identity_audit.py` · tenant `co-demo` · `excluded_from_kpi != true` · sintéticos via `$nin`.

## Resposta direta às 9 perguntas obrigatórias

| # | Pergunta | Resposta |
|---|---|---|
| 1 | Clientes ativos reais | **2.753** |
| 2 | Têm `document` | **2.752 · 99,96%** |
| 3 | Têm `phone` | **2.700 · 98,07%** |
| 4 | Têm vínculo WhatsApp (msgs com `subscriber_id` resolvido) | **42.190 msgs · 98,75%** · mas **só 11 subscribers únicos** (apenas 83 phones únicos com tráfego) |
| 5 | Têm `external_id` Atlaz em `subscribers` | **0 · 0,00%** ← gargalo principal |
| 6 | Têm tickets vinculáveis por chave Atlaz | **108 tickets · 28%** (campo `atlaz_id_assinante`) · subscriber_id resolvido em só 4 (1,04%) |
| 7 | Têm faturas vinculáveis | **7.296 com `subscriber_document` (96%)** + **7.593 com `subscriber_external_id` (100%)** · subscriber_id resolvido em só 1 (0,01%) |
| 8 | Têm score Universo Ligo vinculável | **2 invites + 7 score_audit · 100% com `subscriber_id`** |
| 9 | Têm Customer Intelligence vinculável | **7 audits · 100% com `subscriber_id`** (feature flag continua OFF) |

## Match Atlaz por documento (snapshot Ativo)

- `subscribers.document` ativos: **2.752**
- `loyalty.document` ativos: **2.655**
- Match: **2.654 · 96,44%**
- Subs órfãos (sem Atlaz): **98** (lag de import — mesmos do ONE_TRUTH_CORRECTION)
- Loyalty órfão (sem subscriber): **1**

## Diagnóstico instantâneo

- **Universo Ligo, Customer Intelligence, WhatsApp**: 100% / 98% — não bloqueiam Pamela V3 / Isabella V14.
- **Tickets e Faturas**: têm os campos espelho (`atlaz_id_assinante`, `subscriber_external_id`) com **100% de cobertura** — falta apenas resolver para `subscriber_id` canônico via JOIN.
- **Chave mágica**: `loyalty.external_id` (UUID Atlaz, 100%) ↔ `subscribers.atlaz_external_id` (0% hoje). Copiar esse campo em UMA operação destrava `tickets` + `invoices` simultaneamente.

→ **Bloqueador real único**: `subscribers.atlaz_external_id = 0%`. Resolver isso, e o ecossistema sobe para >97% sem ações manuais por cliente.
