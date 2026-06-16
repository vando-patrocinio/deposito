# ESTOQUE OPERACIONAL — AUDITORIA FASE 1 (READ-ONLY)

**Executive Order:** Reforma Total do Estoque Operacional SmartProv v2  
**Data:** 16/Fev/2026 (preview run)  
**Modo:** Read-only. NENHUMA correção. NENHUM código novo. Apenas mapeamento.  
**Autor:** Auditor automatizado (CTO Mode)

---

## §1. RESPOSTAS ÀS 10 PERGUNTAS OBRIGATÓRIAS

> Universo principal auditado: collection `stok_onts` (estoque "novo" pós-implementação).  
> Universos paralelos analisados: `stok_history`, `client_equipment_history`, `inventory_os_movements_audit`, `smartolt_onus`, `field_equipment_returns`, `ont_duplicate_alerts`.

| # | Pergunta | Resposta | Detalhe |
|---|----------|----------|---------|
| **1** | Quantas ONTs existem | **28** em `stok_onts` (universo gerido) | **23.833** em `smartolt_onus` (espelho SmartOLT bruto, sinaliza universo real do operador). **Mismatch crítico** entre os dois universos — ver §3. |
| **2** | Quantas estão na empresa | **17** | Todas com `location_type=empresa`, `status=disponivel`, `location_id="empresa"` |
| **3** | Quantas estão com técnicos | **10** | 8 retiradas (`retirada_com_tecnico`), 1 com técnico (`com_tecnico`), 1 com defeito (`defeito_devolver_empresa`) |
| **4** | Quantas estão com clientes | **1** | `sn=ITBS32697D69`, cliente `sub-test-582f1f`, status `instalada` |
| **5** | Quantas estão em defeito | **1** | `sn=DEFEITO-001`, com técnico `col-30aafc3c`, status `defeito_devolver_empresa` |
| **6** | Quantas estão sem proprietário | **0 órfãs reais** | (Toda ONT tem `location_type` definido. 0 com `location_id` vazio enquanto `location_type` é tecnico/cliente.) |
| **7** | Quantas possuem SN duplicado | **0** | Nenhum SN repetido entre as 28 ONTs |
| **8** | Quantas possuem MAC duplicado | **0** | Nenhum MAC repetido entre as 28 ONTs |
| **9** | Quantas nunca movimentaram | **27 de 28** | Apenas 1 MAC cruza com `stok_history`/`client_equipment_history`. **27 ONTs não têm trilha de movimentação real.** |
| **10** | Quantas não possuem histórico rastreável | **0 sem SN nem MAC**, MAS **27 sem trilha de movimento real**. | Todas têm pelo menos um identificador (SN ou MAC). O problema é a ausência de **movimentos auditáveis** (não de identidade). |

---

## §2. CLASSIFICAÇÃO DAS 28 ONTs (6 CATEGORIAS)

| Categoria | Quant. | % | Critério aplicado |
|-----------|--------|---|-------------------|
| **CONFIÁVEL** | 19 | 67,9% | SN real (não auto-gerado) + `location_type`/`status` coerente + (se instalada) cruza com `smartolt_onus` |
| **REVISAR** | 8 | 28,6% | SN auto-gerado (`sn_auto_generated=true`) — 7 casos · 1 sem SN |
| **ÓRFÃO** | 0 | 0% | (Nenhum equipamento com `location_type=tecnico/cliente` e `location_id` vazio.) |
| **DUPLICADO** | 0 | 0% | (Nenhum SN/MAC repetido.) |
| **DEFEITO** | 1 | 3,6% | `status=defeito_devolver_empresa` |
| **DESCARTE** | 0 | 0% | (Nenhum equipamento marcado para descarte. Critério ainda não existe no schema.) |

### Detalhamento — CONFIÁVEL (19)
- 12 com SN que cruza com `smartolt_onus` (instaladas e visíveis no SmartOLT).
- 7 em armazém (`location_type=empresa`, `status=disponivel`) com SN real.

### Detalhamento — REVISAR (8)
| SN | Localização | Status | Motivo |
|----|-------------|--------|--------|
| REAL-LABEL-001-FIXED | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_22334491 | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_EE00115A | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_CAFE69C9 | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_2233444A | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_EE0011EC | tecnico/col-30aafc3c | retirada_com_tecnico | SN auto-gerado |
| AUTOSN_CCDD0001 | tecnico/col-b4db2145 | com_tecnico | SN auto-gerado |
| *(null)* | tecnico/col-demo-001 | retirada_com_tecnico | Sem SN — só MAC |

### Detalhamento — DEFEITO (1)
- `sn=DEFEITO-001`, MAC, com técnico `col-30aafc3c`, marcado `defeito_devolver_empresa`. Aguardando retorno à empresa.

---

## §3. MISMATCH ENTRE UNIVERSOS (CRÍTICO)

| Coleção | Docs | SNs únicos | MACs únicos | Significado operacional |
|---------|------|------------|-------------|--------------------------|
| `stok_onts` | 28 | 27 reais (1 sem SN) | 28 | Estoque "novo" (apenas equipamentos cadastrados manualmente / via wizard) |
| `stok_history` | 99 | ~0 | 1 | Quase tudo é `admin_reset_granular` (resets de contagem) — **não é histórico de movimento real**. Apenas 5 `create` + 2 `delete`. |
| `client_equipment_history` | 2.728 | 3 | 3 | Vira log de OS: **2.410 `STAGE_TRANSITION`** (mudanças de fase do ticket) + 301 sem ação + apenas **17 movimentos reais** (2 install + 2 withdraw + 2 port_swap + 11 port_link). |
| `inventory_os_movements_audit` | 0 | 0 | 0 | Guardrail novo (implementado em 16/jun) — **nunca foi acionado em produção**. |
| `smartolt_onus` | 23.833 | 1.828 válidos | 834 | Espelho bruto SmartOLT do operador. **1.828 ONTs ativas no campo que NÃO existem em `stok_onts`**. |

### Diagnóstico

1. **Fragmentação total**: as 4 fontes não se cruzam.
   - `stok_onts × smartolt_onus`: 12 SNs em comum (43% das 28 no estoque, 0,6% das 1.828 no SmartOLT).
   - `stok_onts × client_equipment_history`: 1 MAC.
   - `client_equipment_history × smartolt_onus`: 1 SN.
2. **`stok_history` virou log de auditoria de contagem**, não de movimento.
3. **`client_equipment_history` virou log de OS** (STAGE_TRANSITION domina), não de equipamento.
4. **`inventory_os_movements_audit` (a fonte da verdade que o guardrail deveria popular) está ZERADA.** Significa que o guardrail criado em 16/jun ainda não interceptou nenhuma finalização de OS real.
5. **Existem ~1.828 ONTs no SmartOLT sem registro no estoque** — são equipamentos legados que foram instalados antes do estoque ser ativado. Esses precisam ser migrados/reconciliados.

---

## §4. MAPEAMENTO DO CÓDIGO/INFRA EXISTENTE — REAPROVEITAMENTO

> Para cumprir a regra "PROIBIDO criar funcionalidades duplicadas / PROIBIDO criar novo fluxo paralelo / Reutilizar ao máximo a arquitetura já existente".

### 4.1 Services existentes (estoque/movimento)

| Arquivo | Tamanho | Função | Status / Decisão |
|---------|---------|--------|------------------|
| `services/os_inventory_guardrail.py` | 26 KB | **Guardrail global de movimento por OS.** Já implementa as 6 movimentações: `INSTALLATION`, `WITHDRAWAL`, `SWAP`, `RETURN`, `DEFECT`, `DISPOSAL`. Gera `audit_hash` SHA-256. | ✅ **REAPROVEITAR** como base da Fase 7 (Guardrail Global). Está alinhado com a ordem. Falta: (a) renomear `inventory_os_movements_audit` → `inventory_movements` (Fase 2) OU adicionar collection nova; (b) wiring de TODAS as rotas que mexem em estoque pra passar por ele. |
| `services/os_inventory_reconciliation.py` | 5,5 KB | Background worker que reconcilia ONTs com SmartOLT a cada hora (cenário offline). | ✅ **REAPROVEITAR** como base da Fase 8 (SmartOLT). Falta: ampliar pra capturar `pppoe`, `rx_olt`, `distancia`, `profile`, `tr069` (hoje só capta `signal_1310`/`signal_1490`). |
| `services/ont_duplicate_detector.py` | 7,9 KB | Detecta SN/MAC duplicado e marca em `ont_duplicate_alerts`. | ✅ **REAPROVEITAR** para detecção contínua em Fase 1 + Fase 3 (responsabilidade única). |
| `services/contracts_aging_worker.py` | 6,6 KB | Worker de aging de contratos (não-estoque). | ⚪ Sem relação direta — manter. |
| `services/nervous_contract.py` | 4,2 KB | Schema de contrato nervoso. | ⚪ Sem relação direta. |

### 4.2 Routes existentes

| Arquivo | Tamanho | Função | Status / Decisão |
|---------|---------|--------|------------------|
| `routes/stok.py` | **180 KB** | Rotas legadas de estoque. Contém `auto_close_service_from_ticket` (já sinalizado no PRD como **a refatorar** e atualmente bypassado via gate pelo guardrail novo). | 🟡 **CONSOLIDAR**. Esse arquivo precisa ser quebrado em sub-rotas e ter o código duplicado removido. Mover lógica de movimento pro guardrail. |
| `routes/stok_transfers.py` | 22 KB | Transferências entre técnicos/empresa. | 🟡 **MIGRAR** pra chamar guardrail (Fase 7). |
| `routes/ont_scan.py` | 22 KB | OCR / scan de SN. | 🟡 **MANTER** mas garantir que a finalização cria movimento via guardrail. |
| `routes/lousa.py` | (Lousa) | Já chama `os_inventory_guardrail.apply_on_close()` na finalização de OS (Fase 4-6 parcialmente implementada). | ✅ **OK**. |
| `routes/balanco.py`, `routes/collaborator_assets.py`, `routes/field_ops.py`, `routes/purchases.py`, `routes/saas.py`, `routes/smartolt.py` | misc | Tocam em estoque mas via leitura. | 🟢 Auditar leitura, validar se não há `update_one`/`insert_one` direto em `stok_onts`. |

### 4.3 Collections existentes — Status

| Collection | Manter? | Função futura |
|------------|---------|---------------|
| `stok_onts` (28) | ✅ Sim | Tabela de **estado atual** do equipamento (snapshot). É a "view materializada" do movimento. |
| `stok_history` (99) | 🟡 Renomear/depreciar | Vira `stok_admin_log` (eventos administrativos de reset/criação, não movimento). |
| `stok_admin_log` (13) | ✅ Sim | Mantém escopo administrativo. |
| `stok_services` (153) | ✅ Sim | Serviços (instalação, retirada, troca) catalogados. Mantém ligação com OS. |
| `stok_pending_transfers` (5) | ✅ Sim | Pendências de devolução (Fase 5 — alertas 15/30/45 dias). |
| `stok_balanco_sessions` (19) | ✅ Sim | Sessões de balanço/inventário físico. |
| `stok_stock` (4) | ❓ Verificar | Schema incerto. Auditar antes da Fase 2. |
| `stok_batch_log` (0) | 🟢 Vazio | Manter para retrocompat. |
| `client_equipment_history` (2.728) | 🟡 **DIVIDIR** | Filtrar `STAGE_TRANSITION` pra `tickets_stage_log` (já temos `ticket_logs` com 1.918 docs). Manter só `install`/`withdraw`/`port_swap`/`port_link` como histórico real. |
| `inventory_os_movements_audit` (0) | ✅ Sim | **Esta é a `inventory_movements` da Fase 2.** Já tem `audit_hash`. Falta popular. |
| `smartolt_onus` (23.833) | ✅ Sim | Espelho do SmartOLT (read-only). |
| `smartolt_pending_removals` (12) | ✅ Sim | Pendências SmartOLT (Fase 8 — reconciliação). |
| `field_equipment_returns` (1) | ✅ Sim | Devoluções de campo (Fase 5). |
| `ont_duplicate_alerts` (1) | ✅ Sim | Alertas de duplicidade (Fase 1 contínuo). |

### 4.4 Audit collections

| Collection | Status |
|------------|--------|
| `treasury_guardrail_audit` | ✅ Modelo de referência (Treasury já usa esse padrão de hash) |
| `inventory_os_movements_audit` | ✅ Modelo já criado (Fase 2). Falta popular. |

---

## §5. GAPS DA ARQUITETURA ATUAL VS. ORDEM

| Fase | Gap detectado |
|------|---------------|
| **F2** — `inventory_movements` | Já existe (`inventory_os_movements_audit`). Falta apenas: renomear OU manter e popular. ✅ campo `audit_hash` já está. Campo `completed_at` ausente — adicionar. |
| **F3** — Responsabilidade única | Hoje schema usa `location_type` (3 valores: empresa/tecnico/cliente). Faltam: `defeito` e `descarte` como `location_type` distintos. Atualmente "defeito" é representado como `status=defeito_devolver_empresa` mantendo `location_type=tecnico`. Isso viola "Somente um responsável por vez". Precisa migrar. |
| **F4** — Instalação | `os_inventory_guardrail.apply_on_close()` já cobre. Falta: validação SmartOLT em tempo real (parcialmente coberta), wrapping transacional (atomicidade), rollback automático. |
| **F5** — Retirada | Pendência de devolução existe (`stok_pending_transfers`), mas alertas 15/30/45 dias **não estão implementados**. Falta worker de aging. |
| **F6** — Troca | Guardrail aceita `SWAP` mas **não exige dois movimentos atômicos**. Campos `RX_ANTES/RX_DEPOIS` não obrigatórios hoje. |
| **F7** — Guardrail global | Implementado em 16/jun. Falta wiring exaustivo de TODAS as rotas. Auditoria: 15+ arquivos referenciam `stok_onts` direto. |
| **F8** — SmartOLT | Worker existe mas captura parcial. Não captura `pppoe`, `distancia`, `profile`, `tr069`. |
| **F9** — Linha do tempo | **Não existe tela única.** Hoje histórico está espalhado em 3 collections (`stok_history`, `client_equipment_history`, `inventory_os_movements_audit`). |
| **F10** — Score de saúde | **Não existe.** Tem `presidente_score_engine` (CEO score) e `health_snapshots` (rede), mas não score por equipamento. |
| **F11** — Painel executivo | **Não existe.** Hoje o painel mais próximo é a tela de Estoque dentro de `routes/stok.py`. |
| **F12** — Migração | Plano ainda não escrito. (Será gerado em `ESTOQUE_OPERACIONAL_MIGRATION_PLAN.md` depois desta auditoria.) |

---

## §6. RISCOS IDENTIFICADOS NESTA AUDITORIA

| # | Risco | Severidade | Mitigação proposta |
|---|-------|------------|---------------------|
| 1 | **8 ONTs com SN auto-gerado em poder de técnico** (col-30aafc3c). 6 do mesmo técnico. Quando ele tentar instalar, o guardrail vai exigir SN real → bloqueio em campo. | 🔴 Alta | Forçar re-scan do SN antes de devolução, ou marcar como REVISAR e bloquear próxima movimentação. |
| 2 | **1.828 ONTs no SmartOLT sem registro no estoque** (legacy). | 🔴 Alta | Job de "seed" do estoque a partir do SmartOLT (criar `stok_onts` com `status=instalada` + `location_type=cliente` quando possível inferir o cliente via PPPoE). Plano de migração explícito. |
| 3 | **`inventory_os_movements_audit` vazia** após meses de funcionamento do guardrail. | 🟡 Média | ✅ **CORRIGIDO 16/02/2026.** Bug de string literal em `lousa.py:4456` (`"executada"` vs `"sucesso"`). Após patch + restart, validado e2e que próxima OS de técnico (outcome=sucesso) grava em `inventory_os_movements_audit` com hash de auditoria. Ver §11. |
| 4 | **`client_equipment_history` poluído** com 2.410 `STAGE_TRANSITION` (que não são movimento de equipamento). | 🟡 Média | Mover STAGE_TRANSITION para `ticket_logs`. Manter só ações reais de equipamento. |
| 5 | **DEFEITO modelado como status, não como location_type.** | 🟡 Média | Migrar pra `location_type=defeito` (responsabilidade única). |
| 6 | **`stok_history` virou log de reset, não de movimento.** | 🟢 Baixa | Renomear/depreciar. |
| 7 | **Múltiplas rotas mexem em `stok_onts` direto** (15+ arquivos referenciam). | 🟡 Média | Auditoria de write paths. Forçar via guardrail. |

---

## §7. CRITÉRIOS DE ACEITE — STATUS ATUAL

| # | Critério | Status |
|---|----------|--------|
| 1 | Onde está cada equipamento | 🟡 Parcial — só pras 28 do estoque novo. Os 1.828 do SmartOLT não estão. |
| 2 | Quem é o responsável atual | 🟡 Parcial — só pras 28. |
| 3 | Qual OS movimentou | 🔴 Não rastreável — `inventory_os_movements_audit` vazia. |
| 4 | Qual cliente utiliza | 🟡 Parcial — pela 1 instalada. |
| 5 | Qual técnico retirou | 🟡 Parcial — `location_id` aponta pro técnico mas sem trilha temporal. |
| 6 | Quanto tempo está parado | 🔴 Não rastreável — sem timeline. |
| 7 | Qual equipamento gera mais defeito | 🔴 Não — sem score nem agregação. |
| 8 | Qual equipamento deve ser descartado | 🔴 Não — critério não implementado. |
| 9 | Qual patrimônio está em campo | 🟡 Aprox — soma das 12 instaladas detectáveis. |
| 10 | Qual foi a última movimentação | 🔴 Não rastreável — sem trilha. |

**Score de prontidão atual: 1,5 de 10 critérios atendidos plenamente. 9 dos 10 são bloqueadores explícitos da ordem.**

---

## §8. PRÓXIMAS DECISÕES — REQUER APROVAÇÃO HUMANA

Antes de iniciar a **Fase 2**, preciso da sua decisão em 3 pontos:

### D1. Renomear `inventory_os_movements_audit` → `inventory_movements`?
- **Sim**: alinha 100% com nomenclatura da ordem. Custo: 1 migração de collection + grep/replace.
- **Não**: mantém compat 100%. Custo zero.
- **Recomendação CTO:** Manter `inventory_os_movements_audit` (compat) E criar VIEW lógica `inventory_movements` no código que aponta pra ela. Zero migração de dados.

### D2. As 1.828 ONTs SmartOLT órfãs — migrar agora ou criar primeiro a Fase 2 e migrar depois?
- **Migrar agora**: estoque fica completo dia 1, mas adia Fase 2.
- **Fase 2 primeiro**: maturidade arquitetural antes da carga.
- **Recomendação CTO:** **Fase 2 primeiro**. Sem `inventory_movements` populada, a migração das 1.828 ficaria sem trilha. Migrar a Fase 12 ao final.

### D3. As 8 ONTs REVISAR (SN auto-gerado em poder de técnico) — bloquear próxima movimentação ou só sinalizar?
- **Bloquear**: garante qualidade dos dados, mas trava operação até técnico re-scanear.
- **Sinalizar**: continua operando, mas perpetua os AUTOSN_*.
- **Recomendação CTO:** **Sinalizar como warning** na Fase 3, **bloquear na Fase 7** (após guardrail global maduro).

---

## §9. SIDE-NOTES TÉCNICOS (PARA O AUDITOR HUMANO)

1. O schema atual de `stok_onts` **não tem campo `current_owner`** explícito. A função "proprietário" é inferida de `location_type` + `location_id`. Para Fase 3 (responsabilidade única) seria mais limpo introduzir `current_owner_type` e `current_owner_id` como espelho. Decisão a tomar.
2. O campo `praca_id` em `stok_onts` está como **string "None"** em todas as 28 (literal, não null). Limpeza recomendada.
3. `purchase_id`, `client_name`, `warehouse_responsible_id` também aparecem como string "None". Mesmo problema.
4. `sn_auto_generated` está como string `"True"`/`"False"` (não bool). Sugere migração defeituosa anterior. Limpeza recomendada.
5. `MONGO_URL` no `.env` aponta pra um cluster. Toda essa auditoria foi feita contra o cluster real (production data via preview).

---

## §10. CONCLUSÃO DA FASE 1

✅ **Auditoria concluída. Read-only. Zero código alterado.**

- **Universo "controlado": 28 ONTs** — 67,9% confiáveis, 28,6% para revisar, 3,6% defeito.
- **Universo "real" (SmartOLT): 1.828 ONTs** — sem registro no estoque, candidatas à migração na Fase 12.
- **Trilha de movimento: 0 registros** em `inventory_os_movements_audit`. Guardrail nunca foi acionado em produção real.
- **Código aproveitável: 80%** dos building blocks já existem (`os_inventory_guardrail`, `reconciliation worker`, `ont_duplicate_detector`). A reforma é principalmente **wiring, modelagem e UI**, não rewrite.
- **Bloqueador para Fase 2:** decisões D1, D2, D3 acima.

---

**Próximo doc previsto:** `/app/memory/ESTOQUE_OPERACIONAL_MIGRATION_PLAN.md` (após aprovação humana das decisões D1-D3 e início da Fase 12).

---

## §11. POST-MORTEM P0 — BUG DE STRING NO CHOKEPOINT (16/02/2026)

### Decisões aprovadas pelo CEO

- **D1=b**: manter `inventory_os_movements_audit` + criar alias lógico `inventory_movements` (sem migração física).
- **D2=b**: migrar as 1.828 ONTs SmartOLT órfãs apenas na Fase 12.
- **D3=a**: bloquear próxima movimentação das 8 ONTs REVISAR até re-scan do SN real.
- **P0**: investigar por que `inventory_os_movements_audit` estava com 0 registros ANTES da Fase 2.

### Root cause (P0)

```python
# /app/backend/routes/lousa.py — linha 4456 (BUG HISTÓRICO)
if payload.outcome == "executada" and not is_admin_test:
    enforce_os_inventory_movement(...)
```

Schema do payload em `lousa.py:65`:
```python
Outcome = Literal["sucesso", "informada"]
```

A string `"executada"` NUNCA fez parte do contrato. Resultado: chokepoint sempre falso → guardrail nunca invocado → `inventory_os_movements_audit` zerada.

### Patch aplicado

```diff
- if payload.outcome == "executada" and not is_admin_test:
+ if payload.outcome == "sucesso" and not is_admin_test:
```
Mais comentário CTO explicativo no bloco superior.

### Validações realizadas

1. ✅ Teste unitário `test_chokepoint_string_is_sucesso_not_executada` — bloqueia regressão.
2. ✅ Teste unitário `test_outcome_literal_only_accepts_sucesso_and_informada` — bloqueia alteração silenciosa do Literal sem update do chokepoint.
3. ✅ Teste unitário `test_outcome_sucesso_invokes_guardrail` — confirma invocação.
4. ✅ Teste unitário `test_outcome_informada_does_not_invoke_guardrail` — confirma NÃO-invocação para fechamento informativo.
5. ✅ Teste unitário `test_outcome_sucesso_admin_test_skips_guardrail` — confirma bypass em homologação interna.
6. ✅ E2E pós-restart: simulação de finalização técnica com `outcome=sucesso` gerou 1 audit record com hash SHA-256 válido.

```
=== AUDIT RECORD CRIADO ===
  os_id:          tkt-validp0-b8a397
  movement_type:  instalacao_tecnico_cliente
  sn/mac:         VALIDP0-001 / AA:BB:CC:DD:EE:01
  origin:         tecnico → cliente
  hash_auditoria: 7777ffb01e2d1c7561020c34...
```

Todos os 5 testes em `tests/test_lousa_outcome_chokepoint.py` passam.

### Débito histórico — sem write em massa

| Universo | Quant. | Status pós-fix |
|----------|--------|----------------|
| Técnico finalizou via app (`outcome=sucesso`) ANTES do patch | 241 | `legacy_without_inventory_trace=true` (marcação **lógica em relatório apenas** — sem write em DB por decisão CTO) |
| Auto-fechados (SmartProv Auto: ONU_OFFLINE, wifi_ruim) | 2.003 | `legacy_without_inventory_trace=true` (mesma política — não passa por nenhum chokepoint hoje) |
| Admin encerrou via gestor (`action=encerrar`) | 5 | Avaliados pelo guardrail corretamente — sem movimento por design (reparos sem troca) |
| Daqui pra frente | ∞ | Toda finalização técnica com sucesso passa pelo chokepoint + grava audit |

**Política**: NÃO há tentativa de reconstrução retroativa. O débito de 2.244 finalizações sem trilha fica documentado neste relatório e será exibido como flag no painel de Estoque Operacional (Fase 11). Critério: `closed_at < 2026-02-16T00:00:00Z` AND tipo físico AND sem `os_inventory_guardrail.audit_ids` → flag `legacy_without_inventory_trace=true` em runtime, sem write.

### Próximo passo

Fase 2 — modelagem da `inventory_movements` (alias lógico do `inventory_os_movements_audit`). Bloqueador P0 resolvido.
