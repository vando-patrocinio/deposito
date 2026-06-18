# AUDITORIA PRAÇA x TÉCNICO — Onda C P1 (READ-ONLY)

> Gerado em: **2026-06-18 07:03:45 UTC**
> Script: `/app/backend/scripts/audit_praca_tecnico.py` · **ZERO writes** · regra de ouro Onda C respeitada

## 📊 Sumário Global

| Empresa | Técnicos | Praças | stok_stock | ONTs | Svc ativo | Svc órfã |
| --- | --- | --- | --- | --- | --- | --- |
| co-demo | 13 | 3 | 4 | 32 | 1 | 56 |

### Totais de inconsistências (todas as empresas)

| Categoria | Quantidade |
| --- | --- |
| 🔴 Saldos negativos | 12 |
| 🟠 Locations duplicadas | 0 |
| 🚨 Praça misturada com técnico (mesmo ID) | 0 |
| 🟡 ONTs órfãs (location_id inexistente) | 0 |
| 🟠 Serviços ativos sem técnico | 0 |
| 🟡 ONTs defeituosas sem motivo | 0 |
| ⚪ Serviços órfãos restantes (pós-Onda A) | 56 |

---

## 🏢 Empresa `co-demo`

### Estoque empresa (saldo atual)

| Consumível | Saldo |
| --- | --- |
| cabo_rede | 0 |
| conector_fast | 0 |
| conector_fibra | 0 |
| conector_rede | 0 |
| drop | 155 |
| esticador | 0 |
| fibra_06fo | 0 |
| fibra_12fo | -366356 |
| fibra_24fo | 0 |
| fibra_48fo | -200 |
| fibra_96fo | 0 |

### 🔴 Saldos NEGATIVOS (12 ocorrências)

| Location | Consumível | Quantidade |
| --- | --- | --- |
| col-30aafc3c | Conector de rede | -2 |
| col-30aafc3c | Cabo de rede | -10 |
| col-30aafc3c | Conector fast | -2 |
| col-30aafc3c | Esticador | -1 |
| col-b4db2145 | Conector de rede | -2 |
| col-b4db2145 | Cabo de rede | -10 |
| col-b4db2145 | Conector fast | -4 |
| col-b4db2145 | Esticador | -11 |
| empresa | Fibra 12FO | -366356 |
| empresa | Fibra 48FO | -200 |
| praca:prc-5160ebf92d | Drop | -240.0 |
| praca:prc-5160ebf92d | Conector fast | -6.0 |

### ⚪ Stok_services órfãos remanescentes (56)

Status `orfa_sem_ticket` (marcação Onda A). NÃO devem ser deletados — apenas auditados manualmente. Já estão fora do fluxo operacional.

| Service ID | Tipo | Ticket | Técnico |
| --- | --- | --- | --- |
| OS-529F42 | instalacao | tkt-0faf8219bb | — |
| OS-E89B09 | instalacao | tkt-d4c52886a4 | — |
| OS-7ADD69 | instalacao | tkt-7de4887042 | — |
| OS-B597C0 | instalacao | tkt-2117ab3826 | — |
| OS-1DC864 | reparo | tkt-bee0878d91 | — |
| OS-8FF525 | instalacao | tkt-c2112b1ebd | — |
| OS-0A5031 | reparo | tkt-f5737215b0 | — |
| OS-27598B | reparo | tkt-51832f4e0d | — |
| OS-2033A1 | reparo | tkt-fd58a4c03a | — |
| OS-47FE4D | reparo | tkt-16e1132b08 | — |
| OS-1DE3A0 | reparo | tkt-6d7d86d7fe | — |
| OS-66F079 | reparo | tkt-27648cf0ae | — |
| OS-249087 | reparo | tkt-987c96cee6 | — |
| OS-6C0C76 | retirada | tkt-763b785766 | — |
| OS-52AE26 | reparo | tkt-114aaeb890 | — |
| OS-660CBF | instalacao | tkt-84e8d724f1 | — |
| OS-25A731 | reparo | tkt-7838b58ab2 | — |
| OS-9F27BD | reparo | tkt-e0f51ecfbd | — |
| OS-E914D6 | reparo | tkt-d07c050fe4 | — |
| OS-77CEA9 | reparo | tkt-9c57304420 | — |
| OS-A6958D | reparo | tkt-770a51e26d | — |
| OS-234F62 | reparo | tkt-4bad4c4487 | — |
| OS-A02AF2 | reparo | tkt-7c8e4defcc | — |
| OS-41083C | reparo | tkt-807c8b0de4 | — |
| OS-E38FA4 | reparo | tkt-937c02318e | — |

---

## 📋 Próximos passos (sem alterar DB)

1. **Saldos negativos**: investigar transferências manuais sem audit prévio.
2. **Locations duplicadas**: candidatos a merge na Sprint 5 (migração estrutural).
3. **Praça x Técnico misturados**: corrigir IDs (renomear na origem) — só após review humano.
4. **ONTs órfãs**: linkar a um técnico/praça válido OU mover para empresa via UI.
5. **Serviços sem técnico**: revisar manualmente no painel de estoque.
6. **Defeituosas sem motivo**: backfill via UI (campo `defective_reason`).

> ⚠️ NENHUMA dessas correções deve ser feita por script automático. Sprint 5 (Owner & Location Normalization) tratará migração estrutural após review CTO.

