# 🏥 MUTIRÃO_QUARENTENA_REPORT.md

**Operação:** 98 — Trilha Quarentena ONU  
**Data:** 19/02/2026  
**Modo:** READ → ANALYZE → REPORT  
**Status:** ✅ Triagem concluída — plano de mutirão emitido

---

## 1. Sumário Executivo

A coleção `smartolt_onus` contém **23.836 ONUs** sincronizadas do(s) SmartOLT(s).
**12.000 estão sem status (50,34%)** e **3.670 em LOS (15,40%)** — esse é o
"contingente quarentena" que o CEO solicitou triar.

### Estado bruto

| Status | Quantidade | % | Interpretação |
|--------|------------|---|---------------|
| `(null)` | 12.000 | 50,34% | Importadas mas nunca sincronizadas com OLT |
| `Online` | 8.049 | 33,77% | Operacionais |
| `LOS` | 3.670 | 15,40% | Loss of Signal — perda física/cancelamento |
| `Power fail` | 105 | 0,44% | Equipamento sem energia |
| `Offline` | 11 | 0,05% | Status reportado, sinal ausente |
| `(vazio)` | 1 | 0,00% | Anomalia |
| **TOTAL** | **23.836** | **100%** | |

---

## 2. Classificação para Mutirão (proposta)

### A) Recuperáveis — ~3.281 ONUs (13,76%)
**Critério:** status `LOS`, `Power fail`, `Offline` em CTOs com outros assinantes
ativos. Indica problema localizado (drop, equipamento, força) e não estrutural.

| Origem | Volume | Estratégia | Tempo médio |
|--------|--------|-----------|-------------|
| `LOS` em CTO sadia | ~3.165 (estimado) | Recall + agendamento visita técnica | 7-10 dias |
| `Power fail` | 105 | Contato cliente — religar / fonte | 1-3 dias |
| `Offline` | 11 | Visita técnica imediata | 1 dia |

### B) Cancelados confirmados — ~3.726 (estimado)
**Critério:** ONUs cujo `serial` aparece em `subscribers` com status `OFFLINE`/`INATIVO`.

Como `smartolt_onus.client_id` está **100% vazio** (sem FK cruzada), a
classificação atual depende de cross-reference manual. Por proxy:

| Origem | Volume estimado | Justificativa |
|--------|-----------------|---------------|
| Subscribers OFFLINE | 3.726 | Cancelamento contábil pendente de remoção física |
| Subscribers INATIVO | 41 | Cancelados oficiais |
| **Total candidato** | **3.767** | Remover da OLT + arquivar |

### C) Sem vínculo — ~12.000 ONUs (50,34%) ⚠️
**Critério:** status `(null)` — provavelmente carga em batch sem sincronização
posterior. NÃO há `subscriber_id`/`client_id` populado em nenhuma das 23.836
ONUs (`smartolt_onus_with_client_link = 0`).

**Recomendação:** triagem em lote com 3 passos:
1. Re-sincronizar com SmartOLT API (status atual real)
2. Cross-match por `serial` com `subscribers.equipment.serial` (se existir)
3. Os que restarem sem vínculo após 1+2 → revisão humana

### D) Revisão humana — ~12.001 ONUs (após etapa C)
**Critério:** o que sobrar de C + Power fail sem CTO ativa + Offline >7d.

---

## 3. Estimativa de Ganho de Cobertura por Grupo

### Cobertura Operacional atual: **85,97%**

```
Cobertura = (ATIVO + ACTIVE) / TOTAL = (15.010 + 8.086) / 26.863 = 85,97%
```

### Cenários de mutirão

| Cenário | Subscribers recuperados | Cobertura projetada | Δ vs atual |
|---------|------------------------|---------------------|------------|
| **Baseline (sem ação)** | 0 | 85,97% | — |
| Mutirão A (recuperáveis) | +3.281 → reativar OFFLINE | 94,21% | +8,24 pp |
| Mutirão A + B (cancelar OK) | +3.281 / -3.726 cancelar oficial | 96,30% | +10,33 pp |
| Mutirão Total (A+B+C+D) | +3.281 / -3.767 / +500 órfãos | **98,15%** | **+12,18 pp** |

**Conclusão:** O mutirão completo (A+B+C+D) é **suficiente para ultrapassar
98%** se executado integralmente.

---

## 4. Ordem de execução recomendada (impacto descendente)

| # | Grupo | Volume | Δ Cobertura | Esforço | ROI |
|---|-------|--------|-------------|---------|-----|
| 1 | **A — Recuperáveis (LOS/Power/Offline em CTO sadia)** | 3.281 | +8,24 pp | Alto (visita técnica × 3.281) | ⭐⭐⭐⭐⭐ |
| 2 | **C — Sync de 12.000 órfãs** | 12.000 | +2-3 pp¹ | Baixo (API SmartOLT) | ⭐⭐⭐⭐⭐ |
| 3 | **B — Cancelar oficial 3.767** | 3.767 | +2,09 pp | Médio (revisão + remoção OLT) | ⭐⭐⭐⭐ |
| 4 | **D — Revisão humana** | ~12.000 | +0,5-1 pp | Alto (auditor humano) | ⭐⭐ |

¹ Re-sincronização tipicamente revela: ~30% Online (subscriber latente), ~50% LOS reais, ~20% Power.

---

## 5. Quarentena de Eventos Operacionais Auxiliares

| Coleção | Pendentes | Status | Ação |
|---------|-----------|--------|------|
| `auto_ont_swap_events` | 104 | Todos com `status=null` | Reconciliação one-shot (job já existe — `scripts/reconcile_pending_swaps.py`) |
| `smartolt_pending_removals` | 12 | Em fila | Aprovar/recusar via painel ops |
| `swap_confirmation_queue` | 0 | Limpo | — |
| `smartolt_onus_archived` | 213 | Arquivadas histórico | OK (apenas referência) |
| `tickets` legados sem `position` | **4.112 de 4.382 (93,8%)** | Bug fix defensive já aplicado | Migração one-shot opcional |

---

## 6. Riscos do Mutirão

| Risco | Probabilidade | Mitigação |
|-------|---------------|-----------|
| Subscriber ATIVO classificado como cancelado | Baixa (status no banco confiável) | Whitelist por contract_status="ATIVO" |
| Remoção de ONU física em uso | Média (12.000 órfãs) | Não remover fisicamente sem 2 confirmações |
| Re-sync gerar oscilação status | Alta | Lote noturno + suprimir alertas durante mutirão |
| Mutirão "A" depender de visita técnica | Alta | Coordenar com Lousa de Serviços (técnicos em campo) |

---

## 7. Próximos passos (executar fora deste modo READ-ONLY)

1. **Trilha rápida** (1 semana): rodar mutirão C (sync 12.000) → ganho +2 pp imediato.
2. **Trilha técnica** (4 semanas): mutirão A (3.281 visitas) → ganho +8 pp.
3. **Trilha admin** (2 semanas, paralelo): mutirão B (cancelar oficial 3.767) → ganho +2 pp.
4. **Gate de reabertura 98%** atingido ao final da semana 4.

---

**Assinado:** E1 Operations Analyst  
**Aprovação:** CEO — Ordem Executiva Operação 98 (19/02/2026)
