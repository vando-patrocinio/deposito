# SPRINT 5 · PLANO DE EXECUÇÃO POR ONDAS (BLUEPRINT)

**Gerado**: 2026-06-18 19:17 UTC · derivado de auditoria + risk matrix
**Status**: aguardando Go/No-Go do CEO antes de qualquer execução

## REGRA INVIOLÁVEL

Nenhuma onda pode começar sem:
1. Relatório ANTES (snapshot do estado)
2. Plano de rollback (snapshot Mongo + reverte por batch_id)
3. Testes (pytest cobrindo casos críticos)
4. Critério de sucesso quantificado
5. Relatório DEPOIS (delta + validação dos gates)

## ONDA 1 · Correções P0

**Objetivo**: corrigir os 5 P0 da matriz sem migração de schema.

### O.1.1 — Vincular stok_history ao ticket_id (P0-3)
- Fix em `auto_finalize_lousa`: passar `ticket_id` ao criar `stok_history`
- Backfill de 149 events órfãos via parse de `description` (extrair OS-XXX)
- Critério: 100% dos events futuros com `ticket_id`; 80%+ dos órfãos backfillados
- ETA: 1 dia

### O.1.2 — Definir fonte canônica de portas (P0-2)
- Decisão técnica: `cto_ports` collection vira fonte única
- `ctos.ports[]` vira projection read-only (computado on-the-fly)
- Critério: 0 writes em `ctos.ports[]`; todos os reads consolidados
- ETA: 3 dias

### O.1.3 — Implementar auto_ont_swap_events (P0-4)
- Worker já existe (`auto_ont_swap_events` collection com 0 docs)
- Reativar trigger no fluxo de finalização Lousa quando `completion_data.ont` ≠ último ONT do cliente
- Critério: 100% das trocas (ONT mudou no fechamento) geram event
- ETA: 2 dias

## ONDA 2 · Normalização Owner / Location

**Objetivo**: criar schema canônico cliente↔CTO↔porta↔ONU.

- `subscribers` ganha campos `cto_id`, `cto_port_id`, `cto_port_number`
- Backfill cruzando `cto_ports.subscriber_id` ↔ `subscribers.id`
- Gate: integridade ≥ 95% após backfill
- ETA: 5 dias

## ONDA 3 · CTO + Porta obrigatória nos fluxos

- Lousa Mobile: instalação e troca exigem `cto_id` + `port_number` no completion_data
- Validador rejeita finalização sem isso
- Reparo: confirma CTO/porta atual (mesmo que não troque)
- ETA: 3 dias

## ONDA 4 · SmartOLT → Estoque (Sprint 5 Fase 0)

**Blueprint pronto**: `/app/memory/SPRINT_5_FASE_0_PLAN.md`
- Dry-run → piloto 50 → lotes 100/dia × 19d → cleanup
- Gate: cobertura ≥ 95%
- ETA: 27 dias (cron)

## ONDA 5 · Watchtower & KPIs

- Card Cobertura Patrimonial (já existe — Ajuste 2)
- Cards novos: Integridade CTO, Integridade Porta, Integridade SmartOLT
- Timeline de cobertura semanal
- ETA: 3 dias

## ONDA 6 · Auto Balanço Patrimonial (Sprint 5.1)

**Pré-requisitos** (todos ≥ 95%):
- Cobertura Patrimonial
- Integridade CTO
- Integridade Porta
- Integridade SmartOLT

- Snapshot mensal automatizado
- Certidão Patrimonial assinada
- ETA: 5 dias (após gates)

## CRONOGRAMA CONSOLIDADO

```
Onda 1 (P0):     6 dias   ████████████
Onda 2 (Owner):  5 dias        ██████████
Onda 3 (CTO/p):  3 dias              ██████
Onda 4 (SmOLT): 27 dias       ██████████████████████████████████████████████████████
Onda 5 (KPIs):   3 dias                                                            ██████
Onda 6 (Balão):  5 dias                                                                  ██████████
                                                                                                 ─ ~7 semanas
```

## CRITÉRIO FINAL DE SPRINT 5 (definição de pronto)

O sistema responde com segurança:
- ✅ Qual cliente está em qual CTO
- ✅ Qual porta está ocupada e por quem
- ✅ Qual ONU está em cada cliente
- ✅ Onde está cada ONT (cliente/empresa/técnico/defeito)
- ✅ Quem movimentou (técnico/sistema/admin)
- ✅ Quando movimentou (timestamp UTC)
- ✅ Por qual OS (ticket_id linkado)
- ✅ Quanto vale (valuation_value baseado em compra ou catálogo)
- ✅ Se pode entrar no Auto Balanço (4 gates ≥ 95%)
