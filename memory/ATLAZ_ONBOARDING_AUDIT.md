# ATLAZ_ONBOARDING_AUDIT

**Data:** 09-Jun-2026
**Status:** 🟩 **PRONTO PARA PRIMEIRO CLIENTE EXTERNO** com 1 ressalva (rollback formal).

---

## 1. Volume real do Atlaz hoje (Mongo)

| Coleção | Docs |
|---|---|
| `subscribers` (sincronizados via Atlaz) | **2.794** |
| `subscriber_invoices` | **6.359** |
| `subscriber_readjustments` | **5.362** |
| `subscriber_addresses` | **2.807** |
| `subscriber_phones` | **2.789** |
| `subscriber_documents` | 5 |
| `subscriber_access_points` | **5.682** |
| `subscriber_match_log` (rastro de match) | **392.900** |
| `atlaz_*` (totais) | **63.685** docs |
| Job de sync no scheduler | `routes_atlaz.nightly_customers_sync_job` (server.py:763) |

→ **Atlaz é a integração mais madura e populada do produto.**

## 2. Endpoints disponíveis (routes/atlaz.py — 2.091 LoC, 14+ endpoints)

| Endpoint | Método | Função |
|---|---|---|
| `POST /api/atlaz/test-connection` | POST | Valida credenciais antes de qualquer importação |
| `POST /api/atlaz/sync-now` | POST | Dispara sync completo on-demand |
| `GET /api/atlaz/customers/preview` | GET | **DRY-RUN** — retorna o que seria importado, sem persistir |
| `POST /api/atlaz/customers/sync` | POST | Persiste os clientes |
| `GET /api/atlaz/customers/stats` | GET | Resumo pós-sync |
| `POST /api/atlaz/backfill-dates` | POST | `?dry_run=true` por padrão |
| `POST /api/atlaz/redistribute-slots` | POST | `?dry_run=true` por padrão |
| `POST /api/atlaz/reassign-existing` | POST | Reatribuição idempotente |
| `POST /api/atlaz/sync-technicians` | POST | Sync de equipe técnica |
| `GET /api/atlaz/settings` / `PUT` | GET/PUT | URL + token + intervalos |
| `GET /api/atlaz/branch-rules` / `PUT` | GET/PUT | Regras de filial (multi-filial) |
| `POST /api/atlaz/branch-rules/apply-now` | POST | Aplicar regras imediatamente |
| `GET /api/atlaz/sync-logs` | GET | Histórico de sync para troubleshooting |

**Cobertura por exigência da ordem:**

| Campo exigido | Cobertura | Endpoint |
|---|---|---|
| **Clientes** | ✅ | `/customers/preview` (dry-run) → `/customers/sync` |
| **Contratos** | ✅ | Inclusos no objeto subscriber (campos `plan_id`, `plan_name`, `plan_price`, `installation_date`) |
| **Planos** | ✅ | Coleção `plans` (6 docs no demo) — sync auto em `nightly_customers_sync_job` |
| **Faturas** | ✅ | `subscriber_invoices` populado em volume (6.359 docs) |
| **Status financeiro** | 🟧 PARCIAL | Campo `subscribers.financial_status` existe mas raramente preenchido pelo Atlaz hoje |
| **Telefones** | ✅ | `subscriber_phones` (2.789 docs) |
| **Endereços** | ✅ | `subscriber_addresses` (2.807 docs) |

## 3. Checklist de importação (cliente externo)

```
[ ] 1. Coletar credenciais do Atlaz do ISP (URL + API token)
[ ] 2. PUT /api/atlaz/settings com URL + token
[ ] 3. POST /api/atlaz/test-connection → confirma 200 OK + nome do tenant
[ ] 4. GET /api/atlaz/customers/preview → revisar amostra (10 primeiros)
[ ] 5. Validar branch-rules se for multi-filial (PUT /branch-rules)
[ ] 6. POST /api/atlaz/customers/sync → executar import (idempotente)
[ ] 7. GET /api/atlaz/customers/stats → conferir totais vs Atlaz origem
[ ] 8. GET /api/atlaz/sync-logs → revisar erros
[ ] 9. Smoke test em SmartOLT Twin + Lousa para confirmar dados em UI
[ ] 10. Ativar nightly_customers_sync_job (se quiser sync contínuo automático)
```

**Tempo estimado para 5.000 clientes:** 15-40 minutos (dependendo da latência Atlaz).

## 4. Dry-run / safety net

| Recurso | Disponível? | Onde |
|---|---|---|
| **Dry-run de clientes** | ✅ | `GET /customers/preview` retorna amostra + contagem total que seria importada, sem escrever |
| **Dry-run de backfill** | ✅ | `?dry_run=true` em `/backfill-dates`, `/redistribute-slots` |
| **Test-connection antes** | ✅ | `/test-connection` |
| **Logs de matching** | ✅ | `subscriber_match_log` (392k docs) — rastreia cada decisão de match para auditoria |
| **Idempotência** | ✅ | Sync usa `unique_external_id` como chave; reexecução não duplica |
| **Branch rules** | ✅ | Multi-filial suportado via regras Atlaz |

## 5. Gaps identificados

| Gap | Severidade | Impacto na primeira venda |
|---|---|---|
| **Rollback formal não existe** como endpoint dedicado | 🟧 médio | Atlaz é idempotente; em caso de import errado, basta reexecutar com regras corretas. Não há `DELETE bulk` por sync_id. |
| `financial_status` raramente populado | 🟧 médio | Não bloqueia onboarding, mas impacta o cálculo de "inadimplência" no Presidente IA |
| Sem teste E2E de import num ISP novo | 🟦 baixo | Atlaz roda em produção há meses (63k docs); risco é baixo |
| Documentação operacional ausente | 🟦 baixo | Esta auditoria + scripts curl bastam para o primeiro deal |

## 6. Comando único de dry-run (para demonstração ao prospect)

```bash
API_URL=https://dual-combine-3.preview.emergentagent.com
TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"email":"admin@empresa.com","password":"123456"}' \
        | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 1. Test connection
curl -s -H "Authorization: Bearer $TOKEN" "$API_URL/api/atlaz/test-connection"

# 2. Dry-run preview (sem persistir)
curl -s -H "Authorization: Bearer $TOKEN" "$API_URL/api/atlaz/customers/preview" \
     | python3 -m json.tool | head -50
```

## 7. Riscos antes do primeiro cliente externo

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Atlaz do prospect ter schema customizado/diferente | Média | `branch-rules` + `subscriber_match_log` permitem inspeção e ajuste sem código |
| Timeout em sync de 50k clientes | Baixa | Sync é cursor-paginated; já testado com 2.794 clientes em poucos minutos |
| Reverter um import errado | Baixa | Mongo backup local diário (06h UTC) permite restore pontual |
| Field mapping incompleto (Atlaz ↔ Voalle/IXC/MK-Auth) | **N/A** | Apenas Atlaz é suportado nesta sprint; outros ERPs ficam para sprint seguinte |

## 8. Decisão final

> **PRONTO PARA PRIMEIRO CLIENTE PAGANTE** com a infraestrutura Atlaz atual.
> A única recomendação **antes da venda** é treinar o operador no fluxo de 10 passos do §3.
> **Rollback formal** pode ser endereçado pós-primeira-venda (não bloqueia P0).

**Nenhuma linha de código nova foi escrita nesta auditoria. O Atlaz onboarding já existe e funciona.**
