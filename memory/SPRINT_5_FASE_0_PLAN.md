# SPRINT 5 · FASE 0 — Plano de Reconciliação Patrimonial (BLUEPRINT · NÃO EXECUTAR)

**Aprovação CEO**: pendente
**Pré-requisitos**: ✅ Ajuste 1 (Reconciliação Read-Only) · ✅ RCA Delta 98% (Cenário A) · ✅ Ajuste 2 (Split Recuperações + KPI Cobertura)
**Modo**: planejamento estático — **zero writes** até autorização explícita
**Critério de saída do gate**: Cobertura Patrimonial ≥ 95%

---

## 1. OBJETIVO

Eliminar o gap de 98% entre `smartolt_onus` (1.833) e `stok_onts` (32), criando o pipeline **`smartolt_pull_to_stok`** que nunca existiu. Após esta fase, `stok_onts` passa a refletir o parque real da rede, destravando Sprint 5.1 (Auto Balanço Patrimonial).

---

## 2. FONTES (origem)

| Collection                  | Volume co-demo | Papel no merge                                            |
|-----------------------------|---------------:|-----------------------------------------------------------|
| `smartolt_onus`             |          1.833 | Fonte autoritativa da rede viva (provisionadas hoje)      |
| `smartolt_onus_archived`    |            213 | ONUs removidas — viram `stok_onts.status=baixada_smartolt`|
| `client_equipment_history`  |             20 | Histórico equipamento↔cliente — enriquece `last_ticket_id` e `last_user`|
| `subscribers`               |          2.824 | Bind por `name`/`pppoe_user` → `location_type=cliente`, `location_id=subscriber_id` |

**Total alvo de ingestão**: 1.833 + 213 = **2.046 ONUs reais**.

---

## 3. DESTINO

Collection: **`stok_onts`** (não muda; novos docs entram lado-a-lado com os 32 existentes).

---

## 4. MAPEAMENTO DE CAMPOS

| Campo destino (`stok_onts`)            | Origem                                                                 |
|----------------------------------------|------------------------------------------------------------------------|
| `id`                                   | gerado `ont-<uuid8>` (todo doc novo já nasce com `id` populado)        |
| `company_id`                           | `smartolt_onus.company_id`                                             |
| `sn` / `scan_sn`                       | `smartolt_onus.sn`                                                     |
| `mac`                                  | `smartolt_onus.mac`                                                    |
| `model`                                | `smartolt_onus.onu_type_name`                                          |
| `pon`                                  | `smartolt_onus.board + "/" + port + "/" + onu`                         |
| `olt_id`                               | `smartolt_onus.olt_id`                                                 |
| `olt_name`                             | `smartolt_onus.olt_name`                                               |
| `zone_name`                            | `smartolt_onus.zone_name` (ex.: "CTO - 1 - 10 - 01")                   |
| `signal_1310` / `signal_1490`          | `smartolt_onus.signal_1310/1490` (snapshot do momento do import)       |
| `last_smartolt_status`                 | `smartolt_onus.status` (Online/LOS/Power fail/Offline)                 |
| `last_smartolt_admin_status`           | `smartolt_onus.administrative_status`                                  |
| `location_type`                        | regra **§ 5** abaixo                                                   |
| `location_id`                          | regra **§ 5** abaixo                                                   |
| `subscriber_id`                        | match com `subscribers` por `pppoe_user`/`name` (quando bater)         |
| `client_name`                          | `smartolt_onus.name` (ou `subscribers.name` se houver bind)            |
| `status`                               | regra **§ 6** abaixo                                                   |
| `import_source`                        | `"smartolt_pull_v1"`                                                   |
| `imported_at`                          | `datetime.now(timezone.utc).isoformat()`                               |
| `import_batch_id`                      | `"smartolt_bulk_<YYYY-MM-DD>_<hash6>"`                                 |
| `import_genesis_via`                   | `"smartolt_bulk_<YYYY-MM-DD>"`                                         |
| `imported_from_smartolt`               | `true`                                                                 |
| `unique_external_id`                   | `smartolt_onus.unique_external_id` (preserva chave única SmartOLT)     |
| `valuation_genesis_via`                | `"smartolt_pull_v1"` (não usa mais `synthetic_backfill_onda2`)         |
| `valuation_source`                     | `"catalog_estimated_v1"` (Sprint 5+: migrar para `purchase_real`)      |
| `created_at` / `updated_at`            | now UTC                                                                |
| `created_by`                           | `"smartolt_pull_v1@system"`                                            |
| `last_ticket_id`                       | de `client_equipment_history.ticket_id` (se houver match por mac/sn)   |
| `last_user`                            | de `client_equipment_history.actor_name` (se houver match)             |

### Campos NÃO importados (mantidos `None`)
- `purchase_id` — não existe origem confiável; será preenchido em Sprint 5.2 (purchase reconciliation)
- `owner_id` / `owner_type` — Sprint 5.1 (normalização owner/location)
- `valor_nf` / `valor_medio_ponderado` — Sprint 5.2

---

## 5. REGRA DE LOCATION (bind com cliente)

```
SE smartolt_onus.administrative_status == "Enabled" AND status in (Online, LOS, Power fail):
    SE existe match em subscribers via pppoe_user (case-insensitive, normalizado):
        location_type = "cliente"
        location_id   = subscribers.id
        subscriber_id = subscribers.id
    SENÃO SE existe match em subscribers via name (fuzzy ≥ 0.92 + cidade compatível):
        location_type = "cliente"
        location_id   = subscribers.id  (com flag needs_human_review=true)
    SENÃO:
        location_type = "empresa"
        location_id   = "empresa"
        needs_client_bind_review = true
SE administrative_status == "Disabled":
    location_type = "empresa"
    location_id   = "empresa"
    status        = "disponivel"
SE doc veio de smartolt_onus_archived:
    location_type = "empresa"
    location_id   = "empresa"
    status        = "baixada_smartolt"
    archived_smartolt_at = doc.archived_at (se houver)
```

---

## 6. REGRA DE STATUS

| `smartolt_onus.status` | `administrative_status` | `stok_onts.status`           |
|------------------------|-------------------------|------------------------------|
| Online                 | Enabled                 | `instalada`                  |
| LOS                    | Enabled                 | `instalada_sem_sinal`        |
| Power fail             | Enabled                 | `instalada_sem_energia`      |
| Offline                | Enabled                 | `instalada_offline`          |
| qualquer               | Disabled                | `disponivel`                 |
| (de `archived`)        | qualquer                | `baixada_smartolt`           |

---

## 7. REGRAS INVIOLÁVEIS (Golden Rule do Estoque)

1. **Não sobrescrever ONTs existentes**
   Antes de inserir, checa por: `mac` (case/sep insensible) **OU** `sn` **OU** `unique_external_id`.
   Se match → marca o doc existente com `smartolt_bind_at`, `smartolt_unique_external_id`, **sem alterar status/location atuais**. Não toca em nada que o gestor já mexeu.

2. **Não deletar nada**
   ZERO `delete_one`/`delete_many`. Discrepâncias (ex.: ONT no estoque que sumiu do SmartOLT) viram flag `smartolt_orphan_at_import=<batch_id>`, não delete.

3. **Importação idempotente**
   Re-rodar o pipeline 1.000x produz exatamente o mesmo estado final. Garantido por:
   - `import_batch_id` único por execução (mas operações são UPSERT por chave natural)
   - Chave natural composta: `(company_id, unique_external_id)` ou `(company_id, mac_normalized)`
   - `$setOnInsert` em campos imutáveis (`created_at`, `created_by`, `imported_from_smartolt`)
   - `$set` apenas em campos de telemetria (`last_smartolt_status`, `signal_*`, `updated_at`)

4. **Rollback possível em ≤ 60s**
   - Cada batch grava um snapshot pré-execução em `stok_import_rollback`:
     `{batch_id, started_at, finished_at, total_inserted, total_bound, doc_ids_inserted: [...], doc_ids_bound_with_prior_state: [{id, prior: {...}}]}`
   - Endpoint admin: `POST /api/stok/import/rollback/<batch_id>` (requer super_admin + texto canônico)
   - Rollback deleta apenas docs cujo `import_batch_id == batch_id` E que **não receberam writes humanos** após o import (checa `updated_at > imported_at` + ausência em `stok_history` com `actor != system`).

5. **Audit trail completo**
   - Cada doc inserido gera um event em `stok_history`:
     `{ont_id, type: "smartolt_import", batch_id, source_doc_hash, before: null, after: {...}, actor: "smartolt_pull_v1@system"}`
   - Cada bind (match com doc existente) gera:
     `{ont_id, type: "smartolt_bind", batch_id, before: {...prior fields touched}, after: {...}, actor: "smartolt_pull_v1@system"}`
   - 1 entrada em `stok_admin_log` por batch:
     `{action: "smartolt_bulk_import", batch_id, summary: {inserted, bound, orphan_flagged, skipped, errors}, executed_by, executed_at, mode: dry_run|live}`

---

## 8. ESTRATÉGIA DE EXECUÇÃO (sub-fases)

### Sub-fase 0.1 · DRY-RUN total (READ-ONLY)
- **O quê**: roda todo o pipeline em memória, gera um relatório markdown sem tocar no DB.
- **Saída**: `/app/memory/SMARTOLT_BULK_IMPORT_DRY_RUN_<data>.md`
  - Quantos seriam inseridos novos
  - Quantos baterão por mac/sn em docs existentes (bind)
  - Quantos órfãos seriam flaggados
  - Quantos teriam `needs_client_bind_review`
  - Erros de validação (campos faltando, duplicidades de chave)
- **Critério de aceite**: 0 erros + tabela de impacto aprovada pelo CEO.
- **Tempo estimado**: 30-60s para co-demo.

### Sub-fase 0.2 · LOTE PILOTO (50 ONUs, modo live)
- **Critério de seleção dos 50**: Online + Enabled + com `pppoe_user` populado + 1 OLT específica.
- **Validações pós-execução**:
  - 50 novos docs em `stok_onts` com `import_batch_id` igual
  - 50 events em `stok_history` com `type=smartolt_import`
  - 1 entry em `stok_admin_log`
  - 1 entry em `stok_import_rollback`
  - Cobertura Patrimonial sobe ~2.7pp (de 0.65% para ~3.4%)
- **Janela de observação**: 24h
- **Rollback test**: dia seguinte, rodar rollback do batch piloto e validar restauração.

### Sub-fase 0.3 · LOTES DIÁRIOS (100/dia × 19 dias)
- **Cadência**: 1 lote/dia às 04:00 UTC (baixo tráfego)
- **Ordem de prioridade**:
  1. Online + Enabled + com pppoe (bind direto cliente)
  2. Online + Enabled + sem pppoe mas com name (bind por fuzzy name)
  3. LOS / Power fail / Offline (instaladas mas sem sinal)
  4. archived (baixadas)
- **Critério de pausa**: se Cobertura Patrimonial não subir conforme esperado por 2 dias seguidos → pausa + RCA mini.

### Sub-fase 0.4 · CLEAN-UP & FECHAMENTO
- Resolver `needs_client_bind_review` (revisão manual ou IA assistida)
- Reconciliar 48 ONTs sintéticas órfãs do estoque atual (as que não bateram com nada do SmartOLT)
- Re-rodar `audit_smartolt_vs_estoque.py` — meta: Δ ≤ 2%
- Re-rodar `compute_patrimonio_consolidado` — meta: Cobertura ≥ 95%, Patrimônio Confiável ≥ 80%

---

## 9. ENDPOINTS / SCRIPTS A CRIAR

| Arquivo / Endpoint                                         | Tipo        | Função                                                           |
|------------------------------------------------------------|-------------|------------------------------------------------------------------|
| `/app/backend/scripts/smartolt_bulk_import.py`             | script CLI  | Pipeline com flags `--dry-run`, `--limit`, `--olt-id`, `--company-id` |
| `/app/backend/services/smartolt_pull_pipeline.py`          | service     | Lógica de mapping, bind, idempotência (reutilizável)             |
| `/app/backend/routes/stok_import.py`                       | rotas API   | `POST /api/stok/import/dry-run` · `POST /api/stok/import/run` · `POST /api/stok/import/rollback/{batch_id}` · `GET /api/stok/import/batches` |
| `/app/backend/tests/test_smartolt_bulk_import.py`          | tests       | 15+ casos: dry-run determinístico, idempotência, bind, rollback, edge cases |
| `/app/frontend/src/WatchtowerStokImport.jsx`               | UI gestor   | Visualizar batches, dry-runs anteriores, rollback button         |

**Total estimado de código**: ~1200 linhas Python + ~400 linhas JSX.

---

## 10. TELEMETRIA & OBSERVABILIDADE

KPIs novos no Watchtower Patrimônio Consolidado:

- **Cobertura Patrimonial** (já existe — meta 95%)
- **Cobertura sem revisão** = `intersect - needs_human_review / smartolt_total` (qualidade real)
- **Última execução de import**: timestamp, batch_id, summary
- **Discrepâncias acumuladas**: ONTs órfãs no estoque que não bateram com nada

Métricas no `stok_admin_log` por batch:
```json
{
  "batch_id": "smartolt_bulk_2026-06-19_a3f201",
  "mode": "live",
  "executed_at": "...",
  "executed_by": "user@empresa.com",
  "summary": {
    "candidates_processed": 100,
    "new_inserted": 87,
    "bound_to_existing": 11,
    "skipped_invalid": 2,
    "needs_client_bind_review": 9,
    "errors": []
  },
  "cobertura_pct_before": 3.4,
  "cobertura_pct_after": 7.8
}
```

---

## 11. ROLLBACK PLAN

### Cenário A — Rollback de 1 batch (esperado, baixo risco)
```
POST /api/stok/import/rollback/<batch_id>
Body: {"confirm_text": "ROLLBACK BATCH <batch_id>"}
```
1. Lê `stok_import_rollback` do batch.
2. Para cada doc com `import_batch_id == batch_id`:
   - Se foi INSERT puro E `updated_at == imported_at` E sem `stok_history` posterior com `actor != system` → **DELETE** (única exceção à regra de "não deletar", pois é reversão da própria operação dentro de janela 24h).
   - Se foi BIND (doc preexistente) → restaura campos do `prior` snapshot.
3. Marca o batch como `rolled_back_at=<ts>`.
4. Cria entry em `stok_admin_log` com `action=smartolt_bulk_rollback`.

### Cenário B — Rollback total (pior caso, recovery completo)
- Snapshot Mongo completo antes do start da Fase 0 (gestor da plataforma faz)
- Se algo catastrófico ocorrer: `mongorestore` do snapshot pré-fase-0.

---

## 12. CRITÉRIOS DE ACEITE POR SUB-FASE

| Sub-fase | Aceite                                                                              |
|----------|-------------------------------------------------------------------------------------|
| 0.1 Dry-run | 0 erros · CEO aprova tabela de impacto · ≥ 95% das ONUs categorizadas               |
| 0.2 Piloto  | 50/50 com audit trail · rollback testado com sucesso · 0 efeitos colaterais em OS  |
| 0.3 Lotes   | Cobertura sobe ≥ 4pp/dia · sem regressões em Watchtower · 0 alertas críticos       |
| 0.4 Fecho   | Cobertura ≥ 95% · `audit_smartolt_vs_estoque.py` retorna Δ ≤ 2% · CEO assina certidão |

---

## 13. RISCOS & MITIGAÇÕES

| Risco                                                  | Severidade | Mitigação                                                          |
|--------------------------------------------------------|------------|--------------------------------------------------------------------|
| Bind errado entre ONT e cliente (falso match name)     | 🟠 alto   | `needs_human_review` em fuzzy < 1.0 + revisão visual antes de "cliente" |
| Importar duplicatas (mesma ONU dois batches)           | 🟠 alto   | Chave natural `unique_external_id` + index único + UPSERT          |
| Sobrescrever ONTs que gestor já gerenciava manualmente | 🔴 crít.  | NUNCA sobrescreve campos — apenas adiciona telemetria SmartOLT     |
| Quebrar fluxo da Lousa Mobile (que lê stok_onts)       | 🟡 médio  | Sub-fase 0.2 com 50 ONUs em horário noturno + monitorar logs Lousa |
| Disparar `auto_ont_swap_events` por confusão de MAC    | 🟡 médio  | Gate `imported_from_smartolt=true` ignora detector de swap nas 24h |
| Cobertura subir mas Patrimônio Confiável cair          | 🟢 baixo  | Esperado — Sprint 5.1 (owner) recupera; documentar como expected   |

---

## 14. CRONOGRAMA ESTIMADO

| Atividade                                  | Duração     | Quem      |
|--------------------------------------------|-------------|-----------|
| Codar pipeline + tests + endpoints + UI    | 3 dias      | dev       |
| Sub-fase 0.1 (dry-run) + aprovação CEO     | 1 dia       | dev + CEO |
| Sub-fase 0.2 (piloto 50) + janela 24h      | 2 dias      | dev + CEO |
| Sub-fase 0.3 (19 dias × 100/dia)           | 19 dias     | cron      |
| Sub-fase 0.4 (clean-up + certidão)         | 2 dias      | dev + CEO |
| **TOTAL**                                   | **~27 dias**| —         |

---

## 15. CHECKLIST PRÉ-EXECUÇÃO (Go/No-Go do CEO)

- [ ] CEO leu e aprovou este plano
- [ ] Snapshot Mongo completo realizado (Cenário B de rollback)
- [ ] Sub-fase 0.1 (dry-run) executada e relatório aprovado
- [ ] Index único criado em `stok_onts.(company_id, unique_external_id)`
- [ ] Index único criado em `stok_onts.(company_id, mac_normalized)` (não-sparse)
- [ ] Testes do pipeline passando (15/15)
- [ ] Worker do `auto_ont_swap_events` configurado para ignorar `imported_from_smartolt=true` nas primeiras 24h
- [ ] Janela de observação anunciada para a equipe (sem novos cadastros manuais durante o lote piloto)

---

## 16. APÊNDICE — Definição de "match por mac/sn"

Normalização canônica (mesma usada em `audit_smartolt_vs_estoque.py`):

```python
def _norm_id(v: str | None) -> str | None:
    if not v:
        return None
    return "".join(c for c in str(v).lower() if c.isalnum())
```

Exemplos:
- `"C0:25:2F:26:87:41"` → `"c0252f268741"`
- `"ITBS32697D69"`      → `"itbs32697d69"`

Match positivo se **qualquer** das chaves normalizadas (mac, sn, unique_external_id) bate.

---

## 17. TRILHA

- **Documento gerado em**: 2026-06-18 (pós Ajuste 1 + RCA + Ajuste 2)
- **Versão**: v1.0 — blueprint para aprovação CEO
- **Próxima ação**: aguardar Go/No-Go do CEO. Se Go → criar PR com sub-fase 0.1 (dry-run) primeiro.
- **NÃO**: criar arquivos de código, rodar imports, criar índices, ou modificar collections **antes** da aprovação explícita.
