# 🔬 BLOCK RATE — REAL PRODUCTION REPORT

**Data:** 19/06/2026  
**Janela:** últimos 30 dias (19/05 → 19/06/2026)  
**Ordem CEO:** "Excluir qualquer dado sintético"  
**Modo:** Forensic v2 · Read-only

---

## 1. PARTICIONAMENTO DA AMOSTRA

```
Universo: sprint5_onda3_validations (últimos 30d) = 10 documentos

CLASSIFICAÇÃO POR ORIGEM:
  TEST          → 7  (test1@...-test7@ligo.local)
  TEST_CURADO   → 3  (tkt-onda3-real-1/2/3 + Tech vando_ok/empty)
  DEMO          → 0
  E2E           → 0  (não geram validações Onda 3)
  PRODUÇÃO REAL → 0  ← ZERO

DEPOIS DE EXCLUIR DADOS SINTÉTICOS:
  Validações = 0
  Bloqueios  = 0
  Block rate = NÃO COMPUTÁVEL (divisão por zero)
```

---

## 2. TOP 20 BLOQUEIOS REAIS

```
═════════════════════════════════════════════════════════════
NÃO HÁ BLOQUEIOS REAIS A REPORTAR.
A AMOSTRA DE PRODUÇÃO TEM TAMANHO ZERO.
═════════════════════════════════════════════════════════════
```

### Por que zero?

- 6 tickets reais foram finalizados nos últimos 30 dias.
- Todos passaram por `rompimento_path` ou `rompimento_linked`.
- Esses caminhos só ganharam hook Onda 3 hoje (19/06/2026, P0 fixes).
- Cobertura efetiva da Onda 3 sobre tickets reais = **0,0 %**.

---

## 3. RANKINGS COM ESCOPO HONESTO

> Conforme ordem CEO ("excluir sintético"), os rankings ficam **VAZIOS**.  
> Os 5 bloqueios da base original estão em `BLOCK_RATE_ROOT_CAUSE_ANALYSIS.md`  
> e foram classificados como BASELINE SINTÉTICO.

### Por técnico
*(produção real: nenhum técnico ainda gerou bloqueio observado)*

### Por bairro
*(impossível — `subscribers.neighborhood` = `null` em 2.827/2.827)*

### Por cidade
*(impossível — `subscribers.city` não populado)*

### Por tipo de OS
*(produção real: 0 bloqueios)*

### Por item faltante
*(produção real: 0 bloqueios)*

### Por data
*(produção real: 0 bloqueios em 30 dias)*

### Por frequência
*(produção real: 0 ocorrências)*

---

## 4. DIAGNÓSTICO DEFINITIVO

```
═════════════════════════════════════════════════════════════
A LIGO (co-demo) NÃO TEM AINDA UMA OPERAÇÃO DE OS
INSTRUMENTADA PELA ONDA 3.

O QUE EXISTE:
  ✅ A infraestrutura do gate
  ✅ Os hooks em todos os caminhos (corrigidos hoje)
  ✅ A auditoria semanal funcionando
  ✅ A simulação E2E 6/6 PASS
  ✅ O patrimônio rastreado (93,84 % cobertura)

O QUE NÃO EXISTE AINDA:
  ❌ Volume de OS reais passando pelo gate
  ❌ Histórico operacional pré-Onda 3
  ❌ Dados de bairro/cidade em subscribers
  ❌ Métricas de block rate com significado
═════════════════════════════════════════════════════════════
```

---

## 5. CRITÉRIO DE SUCESSO DESTE RELATÓRIO

✅ Confirmou que o block rate atual **não tem base estatística**.  
✅ Confirmou que a Onda 3 está pronta para receber tráfego.  
✅ Confirmou que `subscribers.neighborhood` é o gargalo geo (resolvível por backfill).  
✅ Confirmou que as métricas só ganharão significado após ≥ 50 OS reais.

---

## 6. PRÓXIMO MARCO

📅 **04/07/2026** — re-executar com base honesta (objetivo: ≥ 30 OS reais no gate).

📅 **19/07/2026** — análise final 30 dias.

---

**Evidência primária** (preservada para auditoria):
- Dump completo `sprint5_onda3_validations`: 10 docs
- 6 tickets reais com path `rompimento_*` sem `onda3_validation_diag`
- 0 docs com `actor_email` pertencendo a colaborador real cadastrado
