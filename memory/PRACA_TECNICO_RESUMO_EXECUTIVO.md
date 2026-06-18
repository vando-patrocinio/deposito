# RESUMO EXECUTIVO — Auditoria Praça x Técnico
**Empresa única detectada**: `co-demo` · **Data**: 18/06/2026 · **Fonte**: `/app/memory/PRAÇA_TECNICO_AUDIT.md`

> Leitura para decisão estratégica antes da Sprint 5 (Owner & Location Normalization).

---

## 🎯 Veredito executivo

**5 das 7 categorias estão limpas.** O risco patrimonial está concentrado em **2 categorias**:

1. **Saldos negativos** (12 ocorrências) — VAZAMENTO REAL EM CURSO.
2. **Stok_services órfãos remanescentes** (56) — TRABALHO DE CAMPO SEM TICKET (audit, não vazamento).

E dentro dos saldos negativos, há **1 anomalia gritante**: `empresa.fibra_12FO = -366.356`. Isso não é "déficit pequeno" — é bug de unidade ou contabilidade ilegal. Tem que ser entendido ANTES da Sprint 5, senão você migra estrutura em cima de números podres.

---

## 📊 Resumo por categoria

| # | Categoria | Qtd | Impacto financeiro | Impacto operacional | Impacto na auditoria | Complexidade de correção |
|---|-----------|-----|--------------------|---------------------|----------------------|--------------------------|
| 1 | 🔴 **Saldos negativos `empresa` (fibra)** | 2 | **CRÍTICO** — `fibra_12FO=-366.356` e `fibra_48FO=-200` (estimativa: dezenas de milhares de R$ em fibra "consumida" sem entrada) | Médio — bobinas de fibra são gerenciadas em rolos físicos; o número não reflete realidade | **ALTO** — esse número faz qualquer balanço explodir | **MÉDIA** — exige RCA da entrada/saída (provável erro de unidade ou consumo sem ordem) |
| 2 | 🔴 **Saldos negativos em técnico** (`col-30aafc3c`, `col-b4db2145`) | 8 | Baixo a Médio — conectores/cabo/esticadores em déficit pequeno (-1 a -11 por item) | **ALTO** — técnico está "operando" com mochila negativa: ou faltou registrar reposição, ou o débito foi feito sem entrega física | Médio — pode mascarar furto formiga ou retrabalho sem nota | **BAIXA** — reposição via UI + assinatura digital fecha o item |
| 3 | 🟠 **Saldo negativo em praça** (`praca:prc-5160ebf92d`) | 2 | Baixo (-240m drop · -6 conectores fast) | **ALTO** — praça está "entregando" mais do que recebeu; pode ser técnico tomando direto da praça sem dar saída | Médio — quebra a rastreabilidade Empresa→Praça→Técnico→Cliente | **MÉDIA** — reset do saldo + processo de retirada da praça com OS |
| 4 | ⚪ **Stok_services órfãos** (`orfa_sem_ticket`) | 56 | Indireto — cada serviço órfão pode representar instalação/reparo que aconteceu fora do trilho oficial (perda de receita ou trabalho não cobrado) | **ALTO** — 56 OS no limbo é volume operacional significativo (provavelmente legado pré-Onda A/B) | **ALTO** — sem ticket pai, não há cliente atribuído nem comprovação de execução | **BAIXA por item · ALTA agregada** — exige varredura humana caso a caso (sem deletar) |
| 5 | 🟠 Locations duplicadas | 0 | — | — | — | — |
| 6 | 🚨 Praça misturada com técnico | 0 | — | — | — | — |
| 7 | 🟡 ONTs órfãs | 0 | — | — | — | — |
| 8 | 🟠 Serviços ativos sem técnico | 0 | — | — | — | — |
| 9 | 🟡 ONTs defeituosas sem motivo | 0 | — | — | — | — |

---

## 🔍 Análise crítica

### 🔴 Anomalia #1 — `empresa.fibra_12FO = -366.356`
- 366 mil unidades negativas de fibra 12FO. Em metros isso é ~366 km de fibra "consumida".
- Em saldo de bobina (geralmente 4km-8km/rolo), seriam ~50-90 rolos faltando — impossível fisicamente.
- **Diagnóstico provável**: erro de unidade num import legado OU operação de débito sem credit equivalente OU bug de cálculo num projeto anterior (Onda A trata reposição, mas não revisa históricos).
- **Ação**: query forense em `stok_movements` filtrando por `consumable_id=fibra_12fo` ordenado por valor absoluto descendente — encontrar o(s) lançamento(s) que explicam o buraco.

### 🔴 Anomalia #2 — Técnicos com mochila negativa
- `col-30aafc3c` e `col-b4db2145` operando com saldo negativo nos 4 consumíveis mais usados (conector rede, cabo, conector fast, esticador).
- Padrão: **mesmo conjunto de itens** em ambos os técnicos. Sugere bug sistêmico (talvez Onda A ainda não retroagiu sobre todos os tickets antigos) e não desvio individual.
- **Ação**: rodar `_recompute_technician_stock(col-30aafc3c)` e `_recompute_technician_stock(col-b4db2145)` em dry-run, comparar.

### ⚪ 56 órfãos remanescentes — legado da Onda A
- Onda A marcou esses serviços com `orfa_sem_ticket` (sem deletar, conforme regra de ouro).
- Tipos: predominância de `reparo` (~70%) — comum em legado quando reparos eram criados sem nota.
- **Ação**: revisão humana via painel de estoque; não bloqueia Sprint 5 desde que continuem marcados.

---

## 🎯 Recomendação de execução

### P0 (antes de qualquer migração estrutural)
1. **Investigar e corrigir `empresa.fibra_12FO` e `fibra_48FO`** — RCA via `stok_movements`. Decisão: ajuste manual auditável (CEO assina ata de correção patrimonial).
2. **Recompute de mochila dos 2 técnicos negativos** — dry-run, validar diff, executar com audit log.

### P1 (após P0)
3. **Implementar "Solicitação de confirmação patrimonial via WhatsApp"** para ONT Swap (aprovado pelo CEO).
4. **Triagem dos 56 órfãos** — script de export para CSV (read-only) → revisão humana fora do sistema.

### P2 (Sprint 5)
5. **Owner & Location Normalization** — só DEPOIS de fechar P0 e P1. Migrar estrutura em cima de números limpos.

---

## 📈 Por que isso importa

Migrar estrutura de DB (Sprint 5) sem zerar o `fibra_12FO=-366.356` significa carregar um buraco patrimonial de centenas de milhares de reais para o novo schema. Quanto mais cedo a RCA, mais barato. O sistema agora tem ferramentas pra fazer isso com segurança:
- **Auditoria Praça x Técnico** (read-only, on-demand).
- **6-Phase Trace** (Onda B) pra acompanhar movimentações em tempo real.
- **Watchtower Diagnóstico** (Onda C P1) pra ver workers e saúde.
- **Bug #4 + Bug #6** (Onda C P0) pra impedir novos vazamentos.

Falta apenas **fechar o buraco existente** antes de remodelar.
