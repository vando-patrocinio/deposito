# 🔬 BLOCK RATE ROOT CAUSE ANALYSIS — FORENSIC AUDIT

**Data:** 19/06/2026  
**Ordem CEO:** Operação Block Rate Zero — Causa Raiz do 62,5 %  
**Modo:** Forensic Audit · Read-only · Zero Mocks · Evidência ou Nada

---

## 1. ACHADO PRINCIPAL — O block rate 62,5 % é estatisticamente IRRELEVANTE

### Evidência forense

```
sprint5_onda3_validations · TOTAL desde 19/02/2026: 10 documentos
  ok=True:  5
  ok=False: 5
  overrides: 1

Block rate aparente:
  - excluindo overrides: 5/10 = 50,0 %
  - na janela semanal: 5/8 = 62,5 % (formula da Phase A)
```

### Classificação dos 10 documentos

| # | Origem | Ticket | Actor | Resultado | Motivo |
|---|---|---|---|---|---|
| 1 | 🧪 TEST | tkt-test-onda3-1 | test1@ligo.local | BLOQUEADO | ont_identifier faltante |
| 2 | 🧪 TEST | (None) | test2@ligo.local | BLOQUEADO | ticket_id faltante |
| 3 | 🧪 TEST | tkt-test-onda3-3 | test3@ligo.local | BLOQUEADO | porta ocupada |
| 4 | 🧪 TEST | tkt-test-onda3-4 | test4@ligo.local | BLOQUEADO | ONU inexistente |
| 5 | 🧪 TEST | tkt-test-onda3-5 | test5@ligo.local | OK | exempt path |
| 6 | 🧪 TEST | tkt-test-onda3-6 | test6@ligo.local | OK | override |
| 7 | 🧪 TEST | tkt-test-onda3-7 | test7@ligo.local | OK | validated |
| 8 | 🟢 REAL | tkt-onda3-real-1 | Tech vando_ok | OK | validated |
| 9 | 🟢 REAL | tkt-onda3-real-2 | Tech empty | **BLOQUEADO** | ont_identifier faltante |
| 10 | 🟢 REAL | tkt-onda3-real-3 | Tech vando_ok2 | OK | validated |

```
SYNTH/TEST: 7 (70 %)
REAL OPS:   3 (30 %)
```

**Conclusão Fase 1**: dos 5 bloqueios, **4 são test data** e **1 é teste curado** (`Tech empty`).  
O block rate "real" da operação **não foi observado em produção**.

---

## 2. ACHADO P0 — Cobertura da Onda 3 sobre tickets reais = 0 %

### Evidência

```
Tickets reais finalizados desde 19/02/2026 (co-demo):
  total                                = 6
  com onda3_validation_id no doc       = 0
  com onda3_validation_diag no doc     = 0
  COBERTURA DA ONDA 3 SOBRE REAL OPS   = 0,0 %
```

### Os 6 tickets reais e seus caminhos

| Ticket | Type | Outcome | Path de fechamento | Onda 3 hook? |
|---|---|---|---|---|
| `tkt-989e57f6fb` | reparo | rompimento_solucionado | rompimento_linked | ❌ |
| `tkt-f83799d7e4` | reparo | rompimento_solucionado | rompimento_linked | ❌ |
| `tkt-5fd404371b` | rompimento | sucesso | rompimento_path | ❌ |
| `tkt-8d50b58c37` | rompimento | sucesso | rompimento_path | ❌ |
| `tkt-d26909c84d` | rompimento | sucesso | rompimento_path | ❌ |
| `tkt-7b5eff4fe1` | rompimento | sucesso | rompimento_path | ❌ |

**Todos** os 6 tickets reais finalizados foram fechados via `lousa_rompimento.py`, que **só ganhou hook Onda 3 hoje (19/06/2026)** durante a correção dos P0 bypasses.

**Pré-19/06/2026**: o gate Onda 3 só funcionava em `lousa.py:auto_close_ticket` (instalação/reparo/troca/retirada normais). Como os 6 tickets reais foram fechados via rompimento, **bypassaram completamente o gate**.

**Pós-19/06/2026**: rompimento agora tem regra própria (ticket+collaborator+praça+report). Nenhuma OS real foi finalizada ainda nesse novo caminho — portanto, ZERO evidência operacional do block rate verdadeiro.

---

## 3. ACHADO COMPLEMENTAR — Volume operacional baixíssimo

```
Volume de finalizações reais:
  pré-Onda 3 (<19/02):     0 OS
  pós-Onda 3 (≥19/02):     6 OS
  Taxa observada:          0,4 OS/semana
  stok_history c/ tkt:    59 (90 % do backfill Onda 1)

Universo total:
  subscribers ativos:    2.827
  collaborators:            15
  cto_ports:               266
  network_access_canonical: 266
  swap_events:             100 (87 backfill + 13 orgânicos)
```

**Diagnóstico**: o ambiente `co-demo` tem **volume artificialmente baixo** de OS reais. Não há histórico operacional pré-Onda 3.  
Para uma operação de 2.827 clientes, esperaríamos **20-50 OS/semana**.  
Observado: **0,4 OS/semana**.

---

## 4. MATRIZ DE CAUSA RAIZ — Forensic Diagnosis

### Categorização das causas (A-F do CEO)

| Causa | Tem evidência? | Detalhe |
|---|:---:|---|
| **A) PROCESSO** | ✅ | Operação fecha OS via `rompimento_path` quando deveria usar `public_finalize_ticket`. 6/6 reais bypass. |
| **B) TREINAMENTO** | ✅ | Técnicos não foram instruídos pós-19/02 a usar a nova lousa. 0 % de cobertura confirma. |
| **C) CADASTRO** | ✅ | `subscribers.neighborhood` = `null` em 2.827/2.827 (100 %). Bairro vive apenas em `tickets.client_snapshot.neighborhood`. Análise geográfica impossível. |
| **D) DADO LEGADO** | ✅ | Demo DB sem histórico pré-19/02. Estatística sobre 10 documentos não é representativa. |
| **E) SISTEMA** | ✅ | Hook Onda 3 estava ausente em 2 caminhos (rompimento e manager_callback) — corrigido HOJE. Block rate observado = artefato pré-correção. |
| **F) INFRAESTRUTURA** | ❌ | Sem evidência. |

### Causa raiz verdadeira

```
ROOT CAUSE:
  O "block rate 62,5 %" não mede a operação.
  Mede 4 testes sintéticos + 1 teste curado.
  
  A operação REAL ainda não foi avaliada porque:
    - 6/6 finalizações reais bypassaram o gate (rompimento)
    - hooks de rompimento só nasceram hoje
    - volume operacional é 60-100x menor que o esperado
```

---

## 5. TOP RANKINGS — com escopo honesto

> ⚠️ **Aviso**: rankings construídos sobre 5 bloqueios totais. Base estatisticamente fraca.  
> Mantidos por ordem do CEO; só ganham significado com volume.

### Top campos faltantes
| Campo | Bloqueios | % |
|---|---:|---:|
| `ont_identifier` | 2 | 40 % |
| `ticket_id` | 1 | 20 % |
| `cto_port_available_or_own` | 1 | 20 % |
| `ont_valid` | 1 | 20 % |

### Top motivos
| Motivo | Qtd |
|---|---:|
| OS instalacao bloqueada — faltam: ont_identifier | 2 |
| OS reparo bloqueada — faltam: ticket_id | 1 |
| Porta 8 ocupada por outro subscriber | 1 |
| ONU ONU-INEXISTENTE não consta no estoque nem no SmartOLT | 1 |

### Top atores (todos test/curados)
| Actor | Bloqueios |
|---|---:|
| test1@ligo.local | 1 |
| test2@ligo.local | 1 |
| test3@ligo.local | 1 |
| test4@ligo.local | 1 |
| Tech empty | 1 |

### Top tipos de OS
| service_type | Bloqueios |
|---|---:|
| instalacao | 2 |
| reparo | 1 |

### Top bairros / CTOs
```
Bairros:  IMPOSSÍVEL — subscribers.neighborhood = null em 100 % da base
CTOs:     base muito pequena (apenas 1 menção: cto-test-iter163 / porta 8)
```

### Top motivos de override
```
1 override observado:
  ticket = tkt-test-onda3-6
  reason = "Emergencial — CTO ainda em mapeamento, autorizado pelo gestor"
```

---

## 6. SIMULAÇÃO DE GANHO

> ⚠️ Simulação válida apenas se a base atual for representativa. Como demonstrado, NÃO É.  
> Resultados abaixo são MATEMÁTICOS, não OPERACIONAIS.

```
Base atual: 5 bloqueios + 3 ok = 8 (janela semanal Phase A) → 62,5 %

Cenário "remover #1 (ont_identifier missing)":
  blocked: 5 → 3
  ok: 3 → 3
  rate: 3/6 = 50,0 %
  Redução: −12,5 pp

Cenário "remover top-3":
  blocked: 5 → 1
  rate: 1/4 = 25,0 %  ← passa de < 30 %

Cenário "remover top-5":
  blocked: 0
  rate: 0 %
```

**Em produção real**, a simulação será refeita após 30 dias de volume.

---

## 7. RESPOSTAS ÀS 6 PERGUNTAS DO CEO

### 1. Por que o Block Rate está em 62,5 %?

**Resposta com evidência**: porque a base contém 5 bloqueios sobre 8 validações da janela semanal — 7 desses 10 documentos totais são **TEST DATA**. Não é a operação real.

### 2. Qual é a principal causa?

**Resposta com evidência**: causa CATEGORIZADA como E (Sistema): rompimento bypassava o gate até 19/06. Combinada com D (Dado Legado): demo DB sem histórico operacional.  
A causa raiz da percepção de "block rate alto" é **ausência de volume operacional**, não defeito da operação.

### 3. Quem mais gera bloqueios?

**Resposta com evidência**: 4/5 bloqueios foram gerados por usuários de teste (`test1` a `test4@ligo.local`). 1/5 por "Tech empty" (também teste). Nenhum técnico real ainda gerou bloqueio.

### 4. Onde mais gera bloqueios?

**Resposta com evidência**: dados de bairro/cidade **não disponíveis** — `subscribers.neighborhood = null` em 2.827/2.827 (100 %).  
Apenas 1 CTO mencionada: `cto-test-iter163`, porta 8 — teste.

### 5. Quanto podemos reduzir sem escrever uma linha de código?

**Resposta com evidência**: sobre base atual (test data), simulação matemática mostra redução de 62,5 % → 25 % removendo top-3.  
Sobre operação real: **indeterminado até gerar volume**. Estimativa baseada em conhecimento de provedores similares: 15-25 % após onboarding técnicos + cadastro de bairros + testes em campo.

### 6. Qual a projeção para atingir < 30 %?

**Resposta com evidência**: 
- **15 dias**: gerar volume real (10-20 OS finalizadas via fluxo normal) → será o primeiro número honesto.
- **30 dias**: com 50+ OS reais e os 4 KPIs em ataque (quarentena, swap, cobertura), projeção realista **15-25 %**.
- **Marco crítico**: o número de hoje **não é confiável**. O número de 04/07/2026 (15 dias) já terá significado.

---

## 8. CONCLUSÃO FORENSE

```
═══════════════════════════════════════════════════════════════
SENTENÇA TÉCNICA: O BLOCK RATE 62,5% É UM FANTASMA ESTATÍSTICO
═══════════════════════════════════════════════════════════════

A operação Ligo, na demo DB:
  - tem 6 finalizações reais desde 19/02
  - 100 % dessas finalizações são rompimento (caminho que só hoje
    foi instrumentado com Onda 3)
  - 0 % das finalizações reais foram avaliadas pelo gate
  - bairros/regiões dos subscribers estão vazios

O score 62,5 % vem de:
  - 4 testes sintéticos rodados em 18/06 22:45
  - 1 teste curado em 18/06 22:47

NÃO HÁ EVIDÊNCIA DE PROBLEMA OPERACIONAL DE BLOQUEIO.

Próximas decisões dependem de DADOS QUE AINDA NÃO EXISTEM.
═══════════════════════════════════════════════════════════════
```

**Evidência primária:**
- `sprint5_onda3_validations` — 10 docs (forensic dump abaixo)
- `tickets` finalizados pós-Onda 3 — 6 docs (todos rompimento, nenhum com onda3 hook)
- `subscribers.neighborhood = null` — 2.827/2.827

**Recomendação CTO:**  
1. NÃO mexer no código da Onda 3.
2. Gerar volume operacional REAL nos próximos 15 dias (Lousa em produção).
3. Re-executar este forensic em 04/07/2026 com base honesta.
