# RCA · DELTA 98% SMARTOLT × ESTOQUE

**Empresa**: `co-demo`
**Data**: 2026-06-18
**Tipo**: READ-ONLY forensic audit
**Origem**: Relatório `SMARTOLT_RECONCILIATION_2026-06-18.md`

---

## 1. VEREDITO

### ✅ **CENÁRIO A confirmado**: *Nunca existiu integração SmartOLT → Estoque*

```text
SmartOLT sync (OLT → smartolt_onus)         : ATIVO desde 2026-05-15
stok_onts (pipeline novo de patrimônio)     : ATIVO desde 2026-05-27
Ponte smartolt_onus → stok_onts             : NUNCA EXISTIU
```

**Cenário B descartado** (existiu e quebrou). Não há vestígios de import quebrado, retry, dead-letter ou job parado.
**Cenário C descartado** (migração de banco). Não há vestígios de collection migrada, prefixo de tabela legada ou rename.

---

## 2. EVIDÊNCIAS

### 2.1 Pipeline SmartOLT → stok_onts não existe no código

`grep` por padrões `import_smartolt`, `bulk_import`, `smartolt_to_stok`, `sync_smartolt`, `smartolt_pull`, `smartolt_sync` no `/app/backend/` retorna apenas o **caminho inverso** (push de CTOs do app para a SmartOLT API):

| Arquivo                                | Direção                |
|----------------------------------------|------------------------|
| `routes/smartolt_push_ctos.py`         | App → SmartOLT (zones) |
| `routes/rede_ia.py`                    | App → SmartOLT (zones) |
| `services/inventory_movements.py`      | Constante de tipo apenas |
| `services/transfer_engine.py`          | Constante de tipo apenas |

**Nenhuma rota, worker, script ou job importa `smartolt_onus` para `stok_onts`.**

### 2.2 Origem real das 32 ONTs em `stok_onts`

```text
synthetic_backfill_onda2 (3 subtipos)  : 31 / 32  (96.9%)
  ├─ synthetic_unknown_genesis_backfill : 15
  ├─ synthetic_purchase_genesis_backfill: 10
  └─ synthetic_scan_genesis_backfill    : 6
None (legado pré-Onda2)                : 1 / 32
```

**100% das 32 ONTs foram criadas por backfill sintético da Onda 2** —
não por sincronização real com a SmartOLT.

### 2.3 Quem criou as 32 ONTs

```text
admin@empresa.com         : 20  (scripts/manual)
gestor@empresa.com        : 4   (manual)
ai_scan_retirada          : 2   (Lousa OCR scan)
field_equipment_return    : 1   (retorno de campo)
(None / legado)           : 5
```

**Nenhuma criação automatizada via job/cron**.
Todas humanas ou via flows do app (Lousa, retorno).

### 2.4 `stok_admin_log` não tem evento de import

```text
Eventos registrados: ['stok_reset', 'stok_reset_granular',
                      'fibra_rca_estorno',
                      'legacy_orphan_reconciliation_20260618']
```

Zero `smartolt_import`, `bulk_import`, `smartolt_sync_in`. Nunca houve
operação administrativa de importar SmartOLT.

### 2.5 Linha do tempo

```text
2026-05-15  →  Sync SmartOLT começa (1833 ONUs sincronizadas em smartolt_onus)
2026-05-27  →  Primeiras ONTs criadas em stok_onts (backfill manual Onda 2)
2026-06-16  →  Última ONT criada em stok_onts (32 acumuladas)
2026-06-18  →  Auditoria revela Δ 98%
```

Durante **34 dias** SmartOLT sincronizou 1.833 ONUs e o pipeline `stok_onts`
acumulou só 32 — todas por backfill humano/sintético.

### 2.6 `smartolt_onus_archived` (213 docs)

- 213 docs arquivados sem `archived_at` populado
- Arquivamento manual ou via script sem trilha de auditoria
- Não impacta o gap: as 213 + 1.833 = 2.046 ONUs reais vs 32 em estoque

---

## 3. ROOT CAUSE

```text
Causa raiz : ausência de integração patrimonial histórica.

Causa próxima : o pipeline `stok_onts` foi desenhado como pipeline novo
                (compra → scan → instalação → devolução) sem consumir o
                estado já existente da SmartOLT como fonte de genesis.

Consequência : todo o parque pré-existente (1.833 ONUs já instaladas em
               clientes via OLT) ficou invisível para o patrimônio.
```

**Não é um bug**. Não é uma quebra. É uma **lacuna arquitetural**:
o pipeline foi construído para inventário novo, sem fase 0 de
*genesis-from-network*.

---

## 4. IMPACTO NOS KPIs ATUAIS

### 4.1 KPI antigo (Watchtower Patrimônio Consolidado)

```text
Patrimônio Confiável = 27.5%
```

**Sem validade estatística**: mede sobre uma base de 32 ONTs num universo
real de 2.046 (1833 + 213). Cobertura real do KPI: **1.56%**.

### 4.2 KPI novo proposto pelo CEO

```text
Cobertura Patrimonial = ONTs no estoque ∩ ONTs no SmartOLT / SmartOLT_total

Hoje:
  intersecção mac/sn       = 12
  smartolt total (docs)    = 1.833
  cobertura                = 12 / 1833 = 0.65%

ou (universo mac∪sn):
  intersecção              = 12
  smartolt mac∪sn          = 2.701
  cobertura                = 12 / 2701 = 0.44%
```

**Meta de desbloqueio**: Cobertura ≥ **95%** para destravar Sprint 5.1.

---

## 5. AÇÕES (não executar agora — apenas planejadas)

### 5.1 Sprint 5 Fase 0 (a planejar em detalhe — Fase 3 do roadmap CEO)

```text
NOVO pipeline : smartolt_pull_to_stok
Origem        : smartolt_onus  ∪  smartolt_onus_archived  ∪  client_equipment_history
Destino       : stok_onts
Modo          : idempotente, bind por mac/sn, sem sobrescrever existentes
Auditoria     : stok_admin_log + import_genesis_via=smartolt_bulk_<data>
```

### 5.2 Guardrails para evitar reincidência

1. **CI gate**: teste que falha se Cobertura Patrimonial cair abaixo de 95%
2. **Worker diário**: novas ONUs sincronizadas no SmartOLT → fila de import
   em `stok_pending_smartolt_import` (humano aprova ou auto-importa por mac match)
3. **Watchtower**: card "Cobertura Patrimonial" como KPI primário

### 5.3 Ajuste 2 (split Recuperações) — em paralelo

Hoje `Patrimônio Consolidado` mistura:
- **Recuperação Operacional**: swaps de ONT, reuso normal de equipamento
- **Recuperação Extraordinária**: estorno RCA Fibra 364km, ajustes forenses

A RCA da Fibra **não pode** continuar contaminando o KPI operacional.
Implementação na Fase 2 deste roadmap.

---

## 6. CONCLUSÃO

- **Não há nada para reparar**. Não houve quebra.
- A integração precisa ser **criada do zero**, com fase 0 de
  *genesis-from-network* na Sprint 5.
- **Sprint 5.1 (Auto Balanço) permanece bloqueada** até Cobertura ≥ 95%.
- KPI primário muda de "Patrimônio Confiável" → **"Cobertura Patrimonial"**.

---

## 7. TRILHA

- Auditoria gerada por: `/app/backend/scripts/audit_smartolt_vs_estoque.py`
- Investigação adicional: queries read-only em `smartolt_onus`, `stok_onts`,
  `stok_admin_log`, `stok_history`, `smartolt_onus_archived`
- Modo: **READ-ONLY** (zero writes)
- Status: ✅ RCA fechada · cenário A confirmado
