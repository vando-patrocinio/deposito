# 🔗 CUSTOMER ID LINKAGE MATRIX — 15/06/2026

Tenant: `co-demo` · só clientes reais (`excluded_from_kpi != true`, sintéticos `$nin`).  
Fonte: `scripts/customer_identity_audit.py` (read-only · re-executável).

| Fonte | Total registros | Vinculados a `subscriber_id` | Órfãos (sem FK canônica) | Cobertura | Chave usada hoje | Confiança | Risco |
|---|---|---|---|---|---|---|---|
| **subscribers** (master interno) | 2.753 ativos | n/a | n/a | n/a | `id` (UUID interno) | 🟢 alta | — |
| **loyalty_imported_db** (Atlaz, snapshot Ativo) | 2.655 documentos únicos | 0 (sem `subscriber_id` populado) | 1 sem match em subs | 0% direto / 96,44% via `document` | `document` (CPF/CNPJ) + `external_id` (UUID Atlaz · 100%) | 🟢 alta | snapshots históricos misturados (24.040 docs totais) — usar o Ativo mais recente |
| **subscribers ↔ Atlaz** (via `atlaz_external_id`) | 2.753 | **0 · 0%** | 2.753 | **0%** | falta o campo | 🔴 zero | **gargalo crítico**: sem isso, todo o JOIN cai em `document` (96%) ao invés de `external_id` (100%) |
| **aihub_wa_messages** (WhatsApp) | 42.723 msgs · 83 phones únicos | 42.190 msgs · 11 subscribers únicos | 533 msgs sem `subscriber_id` | 98,75% mensagens | `subscriber_id` resolvido de `phone` | 🟢 alta (em mensagens) / 🟡 baixa (em cobertura de base: só 11 subs ativos contactaram WA) | base de chats real é pequena — não significa falha |
| **tickets** | 385 | 4 · 1,04% | 381 sem `subscriber_id` | 1,04% canônico · 28% via Atlaz (`atlaz_id_assinante`) | `atlaz_id_assinante` + `atlaz_external_id` (108 = 28%) · `customer_name` (resto) | 🟡 média | nome livre é frágil; resolver via Atlaz pega 28%, restante exige normalização de telefone/doc |
| **subscriber_invoices** (financeiro) | 7.593 | 1 · 0,01% | 7.592 sem `subscriber_id` | 0,01% canônico · **100% via `subscriber_external_id`** | `subscriber_external_id` (100%) · `subscriber_document` (96%) | 🟢 alta (chaves Atlaz íntegras) | nenhum — só falta o JOIN para popular FK |
| **universo_ligo_invites** | 2 | 2 · 100% | 0 | 100% | `subscriber_id` direto | 🟢 alta | tamanho pequeno (curadoria humana) |
| **universo_ligo_score_audit** | 7 | 7 · 100% | 0 | 100% | `subscriber_id` direto | 🟢 alta | feature flag continua OFF — uso restrito a audit |
| **customer_intelligence (runtime)** | 7 audits | 7 · 100% | 0 | 100% | `subscriber_id` direto | 🟢 alta | flag OFF · não exposto |

## Sumário em 1 linha
**Hoje 96,44% dos clientes ativos são unificáveis por `document`. Copiar `loyalty.external_id` para `subscribers.atlaz_external_id` eleva a unificação para ≥98% e destrava tickets+invoices simultaneamente.**
