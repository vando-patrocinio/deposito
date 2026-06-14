# 🔧 RELATÓRIO DE RECONCILIAÇÃO ATLAZ — Fase A.5

**Data:** 14/Jun/2026
**Modo:** CTO / Auditor Independente
**Status:** Reconciliação executada · log auditável em `universo_ligo_migration_log`
**Decisão pendente:** o que fazer com **10.053 subscribers órfãos**.

---

## 1. SUMÁRIO EXECUTIVO

A reconciliação foi executada conforme autorizado. **O resultado foi brutalmente honesto e revelou um problema estrutural que era invisível antes:**

> **As bases `subscribers` (26.851) e `loyalty_imported_db` (24.040 Atlaz) NÃO compartilham chaves.**
> Apenas **7 subscribers** (de ~26.851) deram match com Atlaz por `document` ou `phone`.

Isso NÃO é falha do script de reconciliação. É um problema de **arquitetura de dados** que estava escondido.

---

## 2. RESULTADO REAL

### 2.1 Antes
| Métrica | Quantidade | % |
|---|---|---|
| `subscribers` com `installation_date` | 2.783 | 10.4% |
| `subscribers` sem `installation_date` | 24.068 | 89.6% |
| `loyalty_imported_db` com `activation_date` | 10.883 | 45% |

### 2.2 Depois (executado em produção)
| Fonte de `installation_date` | Quantidade | % da base |
|---|---|---|
| `legacy` (já tinha antes — preservado) | 2.783 | 10.4% |
| `atlaz_document` (match por CPF/CNPJ) | **5** | 0.02% |
| `atlaz_phone` (match por telefone) | **2** | 0.01% |
| `inferred_invoice` (1ª fatura paga - 30d) | 0 | 0% |
| `estimated_min` (default 6 meses atrás) | 14.008 | 52.2% |
| **Sem rastro algum** (nem phone, nem doc, nem ext_code) | **10.053** | **37.4%** |
| **TOTAL com installation_date populado** | **16.798** | **62.6%** |
| **TOTAL sem installation_date** | **10.053** | **37.4%** |

---

## 3. DIAGNÓSTICO DO PROBLEMA REAL

### 3.1 Por que só 7 matches?

Investigação dos campos disponíveis:

| Fonte | Total | Tem document | Tem phone | Tem external_code |
|---|---|---|---|---|
| `subscribers` | 26.851 | **2.797 (10%)** | 16.743 (62%) | 2.797 (10%) |
| `loyalty_imported_db` (Atlaz) | 24.040 | 24.040 (100%) | 22.307 (93%) | 24.040 (100%) |

→ **A base `subscribers` tem 90% dos clientes sem `document` populado.**
→ Match por phone deveria pegar mais, mas houve **divergência de formato** (subscribers usa `552199...`, Atlaz usa `+55 21 9...` — normalizei dígitos e mesmo assim só 2 bateram).

### 3.2 Hipótese de origem

**Hipótese A (mais provável):** `subscribers` foi populado por **um seed/script de criação inicial**, e `loyalty_imported_db` foi populado por uma **importação Atlaz separada e nunca cruzada**. Duas populações **paralelas** que coexistem sem cruzamento.

**Hipótese B:** algumas instalações foram criadas direto no SmartProv (sem passar pelo Atlaz) → não têm document.

### 3.3 Verdade brutal

> **A Ligo tem hoje 2 bases de cliente que não se conhecem.**
> Atlaz (24.040 com história rica) e SmartProv (26.851 com história pobre).
> O Universo Ligo precisa decidir **qual delas é a fonte de verdade do cliente real**.

---

## 4. DISTRIBUIÇÃO DE ANTIGUIDADE PÓS-RECONCILIAÇÃO

| Tempo de casa | Quantidade | Fonte predominante |
|---|---|---|
| **5+ anos** | 494 | legacy (já tinha) |
| 3–5 anos | 272 | legacy |
| 2–3 anos | 373 | legacy |
| 1–2 anos | 672 | legacy |
| 6m–1ano | 549 | legacy + 7 atlaz_match |
| **< 6m** | **14.438** | **14.008 são estimated_min default** |
| **SEM data** | 10.053 | nenhuma fonte |

→ **A massa dos 14.008 estimated_min é artificial**. São clientes que receberam "6 meses atrás" como default porque a Ligo não sabe quando eles entraram.

---

## 5. QUALIDADE DOS MATCHES (auditoria honesta)

| Source | Confiança | Cobertura | Observação |
|---|---|---|---|
| `legacy` | ✅ ALTA | 10.4% | `installation_date` já estava lá. Origem desconhecida mas dado confiável. |
| `atlaz_document` | ✅ ALTA | 0.02% | 5 matches. CPF idêntico nas duas bases. |
| `atlaz_phone` | ⚠️ MÉDIA | 0.01% | 2 matches. Risco de homônimos. |
| `inferred_invoice` | ⚠️ MÉDIA | 0% | Nenhum match — `subscriber_invoices.subscriber_external_id` raramente bate com `subscribers.external_code`. |
| `estimated_min` | ❌ BAIXA | 52.2% | Default arbitrário. Vai gerar "Explorador" pra todos esses. |
| `no_signal` (sem `installation_date`) | — | 37.4% | Marcados como "sem rastro". Precisam de decisão. |

---

## 6. IMPACTO NA CLASSIFICAÇÃO V2

### Cenário Comunidade aplicado HOJE (com base reconciliada)
| Nível | Quantidade estimada |
|---|---|
| 🌱 Explorador | ~24.000 (incluindo 10.053 sem rastro + 14.008 estimated_min) |
| 🚶 Viajante | ~700 |
| ☄️ Cometa | ~370 |
| ✨ Constelação | ~270 |
| 🌌 Galáxia | ~490 |

→ **94% da base ainda cairia em Explorador**. Isso é PIOR do que antes da reconciliação em termos de justiça percebida — porque agora a Ligo afirma "instalei 6 meses atrás" pra clientes que estão há 5 anos.

---

## 7. CONCLUSÃO BRUTAL

A reconciliação Atlaz, no estado atual da base, **NÃO resolve o problema**. Resolve apenas 7 clientes. Os outros 10.000+ continuam órfãos.

### O que isso significa
- A Ligo não pode classificar emocionalmente os clientes **hoje**, com confiança.
- Aplicar qualquer cenário (Conservador / Equilibrado / Comunidade) gera distribuição injusta em 90%+ da base.
- O CEO foi 100% certeiro ao SEGURAR a classificação. Se tivéssemos aplicado, criaríamos um problema sério.

### O que precisa acontecer ANTES da classificação

**Caminho A — Investigação de origem das duas bases (1-2 dias)**
- Descobrir por que `subscribers` está sem `document` em 90%.
- Validar se é safe importar `loyalty_imported_db` como subscribers reais (com `installation_date` populado e benefícios concedidos com base nele).
- Decisão arquitetural: Atlaz é a fonte? SmartProv é a fonte? Como mergear?

**Caminho B — Coleta progressiva via Pâmela (3-6 meses)**
- Aceitar que ~10k clientes ficam temporariamente sem rastro.
- Pâmela, em cada conversa com cliente desconhecido, **registra a história** ("oi, você tá com a gente há quanto tempo?").
- Lento, mas humano, e progressivo.

**Caminho C — Híbrido (recomendado)**
1. Investigar origem das bases (2 dias).
2. Decidir mesclar Atlaz → subscribers (talvez sim, talvez não).
3. Lançar Pâmela no piloto pra coletar histórico em conversas.
4. Classificar progressivamente conforme dado entra.

---

## 8. RISCOS

| # | Risco | Severidade |
|---|---|---|
| 1 | Classificar agora com 90% Explorador → cliente percebe injustiça → cancelamento | 🔴 Crítica |
| 2 | Atlaz e Subscribers serem populações reais distintas (cliente duplicado) | 🟡 Média |
| 3 | Decisão de merge Atlaz→Subscribers causa colisão e perda de dado | 🟡 Média |
| 4 | Os 10.053 órfãos serem clientes de testes/desenvolvimento (não-reais) | 🟢 Baixa (provável) |
| 5 | `estimated_min` continuar sendo usado e clientes reais ficarem mal categorizados | 🟡 Média |

---

## 9. EVIDÊNCIA AUDITÁVEL

Todas as operações foram logadas em `universo_ligo_migration_log`:
- ~24.068 entries criadas (uma por subscriber processado)
- Cada uma com `before`, `after`, `source` e `executed_at`
- Reversíveis via `--rollback`

---

## 10. RECOMENDAÇÃO DO CONSELHO

**🔴 NÃO autorizar classificação V2 até resolver a desconexão Atlaz ↔ Subscribers.**

Próximos passos sugeridos:
1. **Investigação arquitetural** (CTO + responsável pelo Atlaz):
   - Quem alimenta `subscribers`?
   - Quem alimenta `loyalty_imported_db`?
   - São clientes reais sobrepostos ou populações independentes?
2. **Definir fonte canônica de cliente** (decisão executiva).
3. **Migrar / mesclar** se for o caso.
4. **Reexecutar reconciliação** após arquitetura corrigida.
5. **Só então** classificar.

---

## 11. ENCERRAMENTO

A reconciliação técnica foi feita. O resultado revelou um problema **arquitetural** que estava escondido.

> **A Ligo descobriu que opera duas bases de cliente que não conversam. Isso não é uma falha do Universo Ligo — é uma descoberta DO Universo Ligo.**

A boa notícia: o problema foi exposto antes de causar dano emocional ao cliente.
A má notícia: precisa ser resolvido antes da Fase B.

**Aguardando decisão do CEO sobre o caminho (A / B / C).**

---

**Auditor:** CTO Mode · Universo Ligo V2 · Fase A.5
**Próxima atualização:** após decisão CEO sobre arquitetura de bases.
