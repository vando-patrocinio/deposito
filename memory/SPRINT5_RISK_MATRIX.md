# SPRINT 5 · MATRIZ DE RISCO P0 / P1 / P2

**Gerado**: 2026-06-18 19:17 UTC · derivado da auditoria forense

## 🔴 P0 · Impedem rastreabilidade patrimonial

| # | Risco | Evidência | Impacto |
|---|-------|-----------|---------|
| P0-1 | SmartOLT × Estoque desconectados | Cobertura 0.65% (12/1833) | Patrimônio invisível para 98% do parque |
| P0-2 | Schema duplicado de portas | 0 CTOs com `ctos.ports[]` ≠ `cto_ports` | Dois caminhos de escrita podem dessincronizar |
| P0-3 | `stok_history` órfã sem ticket_id | 149 events de `auto_finalize_lousa` sem join | Não rastreia OS → estoque |
| P0-4 | Swap de ONU não rastreável | `auto_ont_swap_events` total: 0 | Trocas perdidas no histórico |
| P0-5 | Subscribers ativos sem porta | 2767 (100.0%) | Não sabe onde clientes estão na rede |
| P0-6 | 3 fontes paralelas cliente↔rede | `cto_ports` (259, 5 com sub) · `subscribers.cto_id` (1) · `subscriber_access_points` (5682, 5682 com sub) | Nenhuma é fonte canônica |

## 🟠 P1 · Importantes mas não bloqueantes

| # | Risco | Evidência | Impacto |
|---|-------|-----------|---------|
| P1-1 | Subscribers fantasma em portas | 2 portas com subscriber inexistente | Histórico fica sujo |
| P1-2 | ONTs sintéticas (backfill) | 31/32 = 96.9% | Patrimônio base não auditado |
| P1-3 | Reservas vencidas | 0 portas em status reserved > 7d | Bloqueio falso de capacidade |
| P1-4 | lousa_finalize_trace gap | -15 OS sem trace | Auditoria de Lousa incompleta |

## 🟡 P2 · Melhorias e automações

| # | Melhoria | Benefício |
|---|----------|-----------|
| P2-1 | Worker diário sync SmartOLT → stok_onts | Mantém cobertura ≥ 95% após Sprint 5 |
| P2-2 | CI gate cobertura ≥ 95% | Previne regressão |
| P2-3 | Watchtower timeline de cobertura | Visibilidade da reconciliação em tempo real |
| P2-4 | Refactor `whatsapp_baileys.py` (>5400 linhas) | Manutenibilidade |
| P2-5 | Refactor `lousa.py` (>9200 linhas) | Manutenibilidade |
