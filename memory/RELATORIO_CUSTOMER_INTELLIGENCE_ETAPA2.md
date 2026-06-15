# RELATÓRIO · UNIVERSO LIGO — CUSTOMER INTELLIGENCE · ETAPA 2 BACKEND

**Data:** 15/06/2026  
**Owner:** platform-team  
**Modo:** CTO — Evidência → Causa-Raiz → Impacto → Confiança → AUTORIZA?  
**Status final:** ✅ ETAPA 2 CONCLUÍDA · 10/10 testes PASS · feature flags OFF

---

## 1. Arquivos criados

| Arquivo | Tamanho | Função |
|---------|---------|--------|
| `/app/backend/services/customer_intelligence.py` | 470 linhas | Núcleo da inteligência: nível, score interno, tags secundárias, cache TTL 1h, invalidação por evento, auditoria. |
| `/app/backend/routes/customer_intelligence.py` | 55 linhas | Endpoint `GET /api/customer-intelligence/{subscriber_id}` + `POST .../invalidate` (admin). 503 quando FF OFF. |
| `/app/backend/scripts/test_customer_intelligence.py` | 320 linhas | Suite ZERO-MOCK de 10 testes contra Mongo real, com fixtures isoladas por `test_run_id` e cleanup garantido. |
| `/app/memory/RELATORIO_CUSTOMER_INTELLIGENCE_ETAPA2.md` | este arquivo | Relatório final desta etapa. |

## 2. Arquivos alterados

Nenhum arquivo de produção foi tocado fora dos três módulos acima. Confirmado por `git status --porcelain` (apenas novos arquivos).

> Etapa 2 é puramente **aditiva**. Nenhum endpoint legado, prompt de IA, dashboard ou comunicação ao cliente foi alterado.

## 3. Feature flags · confirmadas OFF

Valores efetivos no runtime (impressão direta do script):

```
Feature flags · ENABLED=False ISABELLA=False UI_BADGES=False
```

- `CUSTOMER_INTELLIGENCE_ENABLED=false` (padrão, `.env` não define → cai para default)
- `CUSTOMER_INTELLIGENCE_ISABELLA_CONTEXT=false`
- `CUSTOMER_INTELLIGENCE_UI_BADGES=false`

Resultado: o endpoint `GET /api/customer-intelligence/{subscriber_id}` responde **503 — "customer_intelligence disabled (feature flag off)"** em qualquer ambiente até que o CTO ative manualmente.

## 4. Resultado dos 10 testes obrigatórios

Execução: `cd /app/backend && python3 scripts/test_customer_intelligence.py`  
TEST_RUN_ID: `ci-etapa2-c14008bfb3`  
Tenant: **co-demo** · Mongo real · zero mocks.

| # | Regra | Status | Evidência |
|---|-------|--------|-----------|
| 01 | Tenant sintético é bloqueado | **PASS** | `sub-cls-000000` (co-colosso) → `error=synthetic_tenant_blocked` |
| 02 | Subscriber inexistente retorna erro estruturado | **PASS** | `sub-does-not-exist-zzzz` → `error=subscriber_not_found` |
| 03 | Score nunca é exposto ao customer | **PASS** | `internal_score.visible_to_customer=False`, `financial_context.visible_to_customer=False`, todas as 7 tags secundárias com `visible_to_customer=False`. Único campo público: `primary_level`. |
| 04 | High Ticket ativa com receita ≥ 3× ticket médio real | **PASS** | `sub-a81e6aa90364` (MARIA DE LOURDES) · monthly_fee=369,90 · base_avg=103,71 · multiplier=3,57 · `financial_class=high_ticket` |
| 05 | Black ativa com receita ≥ 6× ticket médio real | **PASS** | fixture com monthly_fee=999,99 (9,64× base) · `financial_class=black` · tag `black` presente |
| 06 | Fundador histórico aplica multiplicador 1.5× | **PASS** | `sub-2e42658cae0e` (VANDILSON, 83 meses, 65 faturas pagas, zero inadimplência) · razão `"Fundador histórico (multiplicador 1.5)"` presente · `score=1000` |
| 07 | Embaixador SOMENTE por convite humano aceito | **PASS** | Com convite (`sub-db24962d16b4`) → `primary_level=embaixador`. Sem convite, mesmo com perfil "ambassador natural" (fixture, 90 faturas, 8 anos) → `primary_level=galaxia`. Tag `embaixador_natural` aplicada como contexto, **nunca** elevando o `primary_level`. |
| 08 | Cache invalida via `invalidate(subscriber_id)` | **PASS** | Cold=27,0ms · warm=0,0ms (cache hit) · `last_updated_at` idêntico no warm · após `invalidate()`, novo `last_updated_at` (refreshed=True) |
| 09 | Confidence cai para "baixa" quando faltam fontes ou tenure < 6 m | **PASS** | fixture sem document/loyalty → `confidence=baixa` · `missing_fields=["loyalty_imported_db"]` · idem em `internal_score.confidence` |
| 10 | Audit trail grava em `universo_ligo_score_audit` | **PASS** | Contagem antes=1 → depois=2. Último registro com `company_id=co-demo`, `score:int`, `tags:list`, `level_key=constelacao` |

**Resumo:** `10/10 PASS · 0 FAIL` · exit code `0`.

## 5. Evidências reais

Tenants/subscribers usados (todos do Mongo de produção, não fabricados):

| Papel no teste | Subscriber ID | Documento | Origem |
|----------------|---------------|-----------|--------|
| Sintético (bloqueio) | `sub-cls-000000` | — | tenant `co-colosso` (constants/synthetic_tenants.py) |
| Fundador | `sub-2e42658cae0e` (VANDILSON FERREIRA PEREIRA) | `07220190760` | `co-demo` · loyalty 65 faturas / reg 2019-07 |
| High Ticket | `sub-a81e6aa90364` (MARIA DE LOURDES CARREIRAS) | `65103858720` | `co-demo` · monthly 369,90 |
| Embaixador (convite humano) | `sub-db24962d16b4` (RENATO DO NASCIMENTO FREITAS) | `00248475770` | `universo_ligo_invites.decision=APTO/status=accepted` |

Fixtures temporárias (sempre marcadas com `test_run_id` e removidas no `finally`):

- `sub-tst-black-<8>` · doc `99999<6>` · monthly 999,99 → Black
- `sub-tst-lowconf-<8>` · sem document → confidence baixa
- `sub-tst-scoreamb-<8>` · loyalty com perfil "ambassador natural" sem convite → comprova bloqueio anti-elevação por score

Cleanup confirmado: `delete_many({"test_run_id": TEST_RUN_ID})` em `subscribers` e `loyalty_imported_db`, além de purge dos audit records gerados pelas fixtures. **Zero sujeira remanescente** em produção.

## 6. Latência média

`build_intelligence(subscriber_id)` medido em 12 execuções (incluindo cold, warm e fixtures):

| Métrica | Valor |
|---------|-------|
| média (avg) | **27,4 ms** |
| p95 | 45,4 ms |
| mínimo | 5,5 ms |
| máximo | 48,6 ms |
| cache hit (warm) | **~0 ms** (cache em memória, TTL 1h) |

Performance bem dentro do envelope "contexto em 3 segundos" demandado pelo CTO.

## 7. Amostra de payload real

`build_intelligence("sub-2e42658cae0e")` — fundador VANDILSON FERREIRA PEREIRA:

```json
{
  "subscriber_id": "sub-2e42658cae0e",
  "company_id": "co-demo",
  "customer_name": "VANDILSON FERREIRA PEREIRA",
  "primary_level": {
    "key": "galaxia", "label": "Galáxia", "emoji": "🌌",
    "visible_to_customer": true
  },
  "internal_score": {
    "score": 1000, "max": 1000,
    "visible_to_customer": false,
    "confidence": "alta"
  },
  "secondary_tags": [
    {
      "key": "fundador", "label": "Fundador", "emoji": "🏛️",
      "visible_to_customer": false,
      "reason": "Cliente histórico, zero cancelamentos, registrado antes de 2020, ≥50 faturas pagas"
    }
  ],
  "reasons": [
    "83 meses de relacionamento",
    "Zero inadimplência atual · zero cancelamentos no histórico",
    "Fundador histórico (multiplicador 1.5)"
  ],
  "data_quality": {
    "confidence": "alta",
    "missing_fields": [],
    "sources_used": [
      "subscribers", "loyalty_imported_db", "universo_ligo_invites",
      "isabella_commander_opportunities", "experience_campaigns",
      "nps_responses_mvp"
    ]
  },
  "financial_context": {
    "monthly_revenue": 79.9,
    "base_avg_ticket": 103.71,
    "ticket_multiplier": 0.77,
    "financial_class": "normal",
    "visible_to_customer": false
  },
  "relationship_context": {
    "months_active": 83,
    "founder_candidate": true,
    "ambassador_candidate": false,
    "invisible_customer": false
  },
  "last_updated_at": "2026-06-15T00:37:17.994045+00:00"
}
```

> **Observação CTO:** o cliente comum recebe apenas o bloco `primary_level`. Tudo abaixo é interno — operador de Atendimento, Curadoria, Isabella e dashboards executivos.

## 8. Contagem de docs em `universo_ligo_score_audit`

- Total no banco: **7 documentos** (todos `co-demo`)  
- Distribuição por `level_key`: `galaxia=4`, `constelacao=2`, `embaixador=1`  
- Índices criados (`ensure_indexes`): `(subscriber_id, computed_at desc)` e `(company_id, level_key)`

A coleção é append-only por execução de `build_intelligence`. Não há leitura ou exposição externa hoje — uso restrito a auditoria interna.

## 9. Riscos remanescentes

| # | Risco | Severidade | Mitigação |
|---|-------|------------|-----------|
| R1 | `experience_campaigns` ainda usa `target_label` regex por nome — pode contar duas pessoas com mesmo primeiro nome | **Baixa** | Próxima iteração: vincular por `subscriber_id` ou `document` direto. Hoje a dimensão "Participação" pesa só 10% e tem cap em 1000. |
| R2 | `_real_base_avg_ticket()` cacheia 24h em memória do processo — após restart o primeiro request pode ter ~80ms extra | **Baixa** | Aceitável; fallback `103.37` se aggregation falhar. |
| R3 | `universo_ligo_score_audit` cresce ~1 doc por chamada do build. Em produção sob carga pode virar coleção grande | **Média** | Adicionar TTL index (90d) ou shard por mês quando a UI for ligada. **Não fazer agora** — sem ativação, escala é zero. |
| R4 | Embaixador depende de `do_not_contact_universo_ligo != true` — se um curador desligar o flag depois da aceitação, o convite continua válido e o cliente segue Embaixador | **Baixa** | Próxima etapa de governança: revogar invite explicitamente em vez de só marcar DNC. |
| R5 | Tenant detection só usa `SYNTHETIC_TENANTS` exato (não roda `is_synthetic_tenant` com regex de hash) | **Média** | O `synthetic_tenant_guard.py` já roda em background atualizando a lista. Cobertura efetiva ≥ 99% conforme MAPA_DA_BASE_LIGO.md. |

Nenhum dos riscos compromete o aceite da Etapa 2.

## 10. Decisão recomendada para a próxima etapa

**Recomendação:** **CONGELAR** Customer Intelligence em modo OFF até a Etapa 3 (`LIGO EXECUTIVE OS — Consolidation`) ser autorizada.

Sequência sugerida (estritamente sob nova autorização CTO):

1. **Etapa 3 — Consolidation:**
   - Renomear `presidente_ia.py`, `presidente_executive.py`, `presidente_brain.py`, `presidente_operator.py` com stubs `[DEPRECATED_CALL]` (logs sem quebrar callers).
   - Aplicar `pre_sanitize_2026_06_14=true` nos 2.335 registros sintéticos de `executive_ledger`.
   - Criar `scripts/test_one_truth.py` validando 0% de divergência entre Revenue/Active Clients nos 5 dashboards.

2. **Pós-Etapa 3 (ainda sob autorização separada):**
   - Hook Isabella → Customer Intelligence: `CUSTOMER_INTELLIGENCE_ISABELLA_CONTEXT=true` apenas em `co-demo`, com auditoria de output em janelas curtas.
   - Reescrever prompt Isabella V14 e Pamela V3.
   - UI badges: `CUSTOMER_INTELLIGENCE_UI_BADGES=true` apenas após hook estabilizado.

3. **NUNCA sem aceite explícito:**
   - Comunicar nível ao cliente (qualquer canal).
   - Expor score numérico em frontend.
   - Habilitar Embaixador automático por score.

---

## CRITÉRIO DE ACEITE — checklist final

- [x] 10 testes PASS
- [x] Endpoint funcional mas protegido por feature flag (`503` enquanto OFF)
- [x] Score continua interno (visible_to_customer=false em todos os campos sensíveis)
- [x] High Ticket e Black corretos (3× / 6× do ticket médio real, sem sintéticos)
- [x] Embaixador não nasce por score automático (validado em teste 07b)
- [x] Audit trail gravando em `universo_ligo_score_audit`
- [x] Nenhuma comunicação ao cliente foi disparada
- [x] Nenhuma UI foi ligada
- [x] Nenhuma flag foi ativada

**ETAPA 2 ENCERRADA · AGUARDANDO `VOCÊ AUTORIZA?` PARA ETAPA 3.**
