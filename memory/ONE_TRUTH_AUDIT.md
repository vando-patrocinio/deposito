# ⚖️ ONE_TRUTH_AUDIT — Auditoria de Verdade Executiva

> **Etapa 2.5 · pré-renome (não-código)**  
> **Data:** 15/06/2026 · **Tenant:** `co-demo` (filtro `$nin SYNTHETIC_TENANTS` ativo)  
> **Status final:** 🔴 **ETAPA 3 BLOQUEADA** — 3 KPIs primários em VERMELHO  
> **Princípio CTO/CEO:** *Primeiro verdade. Depois governança. Depois execução.*

---

## 🚦 SEMÁFORO OFICIAL

| Faixa | Cor | Significado |
|---|---|---|
| **0%** exato | 🟢 VERDE | Fontes batem — pronto pra Etapa 3 |
| **0,01% – 1%** | 🟡 AMARELO | Tolerável em métrica derivada; **inaceitável em PRIMÁRIA** |
| **> 1%** | 🔴 VERMELHO | Bloqueia renomes, stubs, tagging e `test_one_truth` |

---

## 🅰️ CLIENTES

### Quantos clientes ativos?

| Fonte | Query | Valor |
|---|---|---|
| **OFICIAL** (definida em `ONE_TRUTH_MATRIX.md`) | `subscribers.count({status:{$in:["ACTIVE","ATIVO"]}, company_id:"co-demo"})` | **2.773** |
| **SECUNDÁRIA** (Atlaz · sistema externo) | `loyalty_imported_db.count({status:"Ativo", company_id:"co-demo"})` | **2.746** |
| **TERCIÁRIA** (sanidade — com `document` válido) | `subscribers.count({status:active, document:{$nin:["",null]}})` | 0 ❗ |

### Divergência
- Δ = `|2.773 − 2.746| / 2.746` = **0,98 %** → 🟡 **AMARELO**
- Em **classe PRIMÁRIA** (0%) qualquer divergência > 0 é tecnicamente quebra de contrato. 27 clientes "fantasma" entre subscribers/loyalty.
- **Adicional crítico:** `document` válido em subscribers = 0. O critério "subscribers ativos com `document` preenchido" devolve zero porque o campo `document` em `subscribers` está vazio/nulo (não foi backfilled). A reconciliação com Atlaz só funciona via `subscribers.document_assinante` ou outra chave — **ainda não mapeada**.

> **Causa-raiz:** o `subscribers.status` aceita 3 vocabulários (`ACTIVE`, `ATIVO`, `INATIVO`). A query oficial no doc dizia `status:"active"` (lowercase) → retornaria **0**. Corrigida nesta auditoria.

---

## 🅱️ RECEITA

### Receita oficial (MRR + Realizada)

| Fonte | Definição | Valor |
|---|---|---|
| **MRR · OFICIAL** | `subscribers.aggregate Σ plan_price WHERE status∈[ACTIVE,ATIVO]` | **R$ 325.241,59** (n=2.773) |
| **MRR · SECUNDÁRIA (Atlaz)** | `loyalty_imported_db.aggregate Σ monthly_fee WHERE status="Ativo"` | **R$ 277.432,78** (n=2.746) |
| **Receita Realizada (mês corrente)** | `subscriber_invoices.aggregate Σ amount WHERE status="paid" AND paid_date≥2026-06-01` | **R$ 154.577,78** (1.499 faturas) |
| **Receita Lifetime** | `subscriber_invoices.aggregate Σ amount WHERE status="paid"` | R$ 434.345,72 (`amount`) · R$ 425.286,15 (`amount_paid`) |

### Divergência
- MRR · oficial vs secundária: `|325.241,59 − 277.432,78| / 277.432,78` = **17,23 %** → 🔴 **VERMELHO**
- Lifetime `amount` vs `amount_paid`: diferença de R$ 9.059,57 (2,09%) — provavelmente juros/desconto não conciliados.
- O campo `paid_at` (assumido pelo matrix) **NÃO EXISTE** — o nome real é `paid_date`. Outra quebra de contrato silenciosa.

> **Causa-raiz da divergência de 17%:** ticket médio difere entre as bases (subscribers = R$ 117,29 vs loyalty = R$ 101,03). Há 27 clientes a mais em subscribers + 16% de inflação no preço médio. Hipóteses: (a) loyalty foi importado em snapshot anterior; (b) subscribers tem reajustes que loyalty não tem; (c) algum subscriber tem `plan_price` errado/test (1 doc `TEST_Dup_985042` foi encontrado).

---

## 🅲 TICKETS

### Quantos tickets abertos hoje?

| Fonte | Query | Valor |
|---|---|---|
| **OFICIAL (matrix dizia)** | `tickets.count({status:"open", company_id:"co-demo"})` | **0** ❗ |
| **OFICIAL CORRIGIDA** (vocabulário real) | `tickets.count({status:{$in:["aberta","pendente"]}, company_id:"co-demo"})` | **355** |
| **SECUNDÁRIA** (`state` em vez de `status`) | `tickets.count({state:"open", company_id:"co-demo"})` | 0 |
| **Total co-demo (todos status)** | `tickets.count({company_id:"co-demo"})` | 375 |
| **Polução sintética** (referência) | `tickets.count({company_id:{$in:SYNTHETIC_TENANTS}})` | **3.811** |

Distribuição real em `co-demo`:
- `pendente` = 353 · `finalizada` = 12 · `encerrada` = 8 · `aberta` = 2 → **375 totais**

### Divergência
- Query do matrix vs realidade: matrix retornaria **0**; realidade são **355** abertos. Δ = **100%** → 🔴 **VERMELHO** (contrato semântico quebrado).
- Polução sintética 3.811 tickets em outros tenants — 10× a base real. Risco se um endpoint cross-tenant escapar do filtro `$nin`.

> **Causa-raiz:** ticket_schema canônico do projeto usa `aberta/pendente/encerrada/finalizada` (PT-BR), mas o `ONE_TRUTH_MATRIX.md` foi escrito com vocabulário inglês (`open/closed`). O `services/ticket_schema.py` já normaliza writes, mas a matriz oficial **não foi atualizada** — qualquer dev seguindo o doc vai produzir uma query que retorna zero.

---

## 🅳 INADIMPLÊNCIA

| Fonte | Query | Valor |
|---|---|---|
| **OFICIAL** (Atlaz) | `loyalty.aggregate Σ(monthly_fee × invoices_overdue) WHERE invoices_overdue>0` | **R$ 23.490,68** (217 clientes · 271 faturas atrasadas no agregado) |
| **SECUNDÁRIA** (faturas reais) | `subscriber_invoices.aggregate Σ amount WHERE status="overdue"` | **R$ 62.485,08** (593 faturas) |
| **TERCIÁRIA** (faturas em aberto não vencidas) | `subscriber_invoices.aggregate Σ amount WHERE status="open"` | R$ 287.069,89 (2.735 faturas) |

### Divergência
- Oficial vs secundária: `|23.490,68 − 62.485,08| / 62.485,08` = **62,41 %** → 🔴 **VERMELHO**

> **Causa-raiz da divergência de 62%:**
> - O agregado `monthly_fee × invoices_overdue` (Atlaz) calcula um **valor médio** baseado na mensalidade atual × quantidade de parcelas atrasadas — mas as parcelas reais podem ter valores distintos (juros/multa/reajuste).
> - `subscriber_invoices` é o **valor real** que entra no balanço — é a fonte que o financeiro usa. Atlaz é referencial.
> - Conclusão: a fonte oficial para inadimplência **deve ser `subscriber_invoices`**, não `loyalty`. O `ONE_TRUTH_MATRIX.md` precisa ser corrigido.

---

## 🅴 FUNDADORES

| Fonte | Critério | Valor | Confiança |
|---|---|---|---|
| **OFICIAL (cálculo)** | `loyalty: status=Ativo · reg<2020 · paid≥50 · overdue=0 · histórico sem cancel` | **130** | 🟢 ALTA |
| **DECLARADA** | `/app/memory/CLIENTE_FUNDADOR_REPORT.md` (130 documentos validados) | **130** | 🟢 ALTA |
| **OPERACIONAL** (já convidados como fundador) | `universo_ligo_invites.invite_source="fundador" AND decision="APTO" AND status∈[accepted,invited_pending]` | **1** | ⚠️ Apenas RENATO DO NASCIMENTO FREITAS validado pela curadoria até agora |

### Divergência
- Cálculo vs declarada: **0,00 %** → 🟢 **VERDE**
- Cálculo vs convidados pela curadoria: 130 → 1 → **99,2 % do potencial ainda não foi convidado pela operação humana** (esperado e correto — o convite é manual).

---

## 🅵 EMBAIXADORES

| Fonte | Critério | Valor | Confiança |
|---|---|---|---|
| **OFICIAL** (definição PRIMÁRIA) | `universo_ligo_invites.find({decision:"APTO", status:"accepted", DNC:false})` | **1** | 🟢 ALTA — convite humano explícito |
| **SECUNDÁRIA** | `universo_ligo_levels.count({level_key:"embaixador"})` | **0** | Coleção vazia / não populada |
| **CANDIDATOS NATURAIS** (NÃO confirmados) | `/app/memory/EMBAIXADORES_NATURAIS.md` | 130 | 🟡 MÉDIA — aguardam convite humano |

### Divergência
- Oficial vs secundária: **0%** (definição é única — convite humano) → 🟢 **VERDE**
- Atenção semântica: a coleção `universo_ligo_levels` existe mas está vazia em `co-demo` — não é uma fonte concorrente. **A regra "Embaixador SÓ por convite humano aceito" está respeitada na produção.**

---

## 🧮 TABELA FINAL — ONE TRUTH MATRIX (estado atual)

| KPI | FONTE OFICIAL | VALOR OFICIAL | FONTE SECUNDÁRIA | VALOR SECUNDÁRIA | DIVERGÊNCIA | STATUS |
|---|---|---|---|---|---|---|
| Clientes Ativos | `subscribers (status∈ACTIVE/ATIVO)` | 2.773 | `loyalty_imported_db (status=Ativo)` | 2.746 | **0,98 %** | 🟡 **AMARELO** |
| Receita (MRR) | `Σ subscribers.plan_price` | R$ 325.241,59 | `Σ loyalty.monthly_fee` | R$ 277.432,78 | **17,23 %** | 🔴 **VERMELHO** |
| Receita Realizada (mês) | `subscriber_invoices (status=paid, paid_date≥01/06)` | R$ 154.577,78 | — (sem fonte concorrente) | — | n/a | ⚠️ MONO-FONTE |
| Tickets Abertos | `tickets (status∈aberta/pendente)` | 355 | `tickets (state=open)` (matrix legado) | 0 | **100 %** (vocabulário) | 🔴 **VERMELHO** |
| Inadimplência | `subscriber_invoices (status=overdue)` | R$ 62.485,08 | `loyalty (monthly_fee × invoices_overdue)` | R$ 23.490,68 | **62,41 %** | 🔴 **VERMELHO** |
| Fundadores | Critério loyalty (5 filtros) | 130 | `CLIENTE_FUNDADOR_REPORT.md` | 130 | **0,00 %** | 🟢 **VERDE** |
| Embaixadores | `universo_ligo_invites (APTO+accepted+!DNC)` | 1 | `universo_ligo_levels (vazio)` | 0 | **0,00 %** | 🟢 **VERDE** |

### Resumo do semáforo
- 🟢 **2 verdes** · Fundadores · Embaixadores
- 🟡 **1 amarelo** · Clientes Ativos (0,98%)
- 🔴 **3 vermelhos** · Receita (17%) · Tickets (100%) · Inadimplência (62%)

---

## 🛑 BLOQUEIO DA ETAPA 3 — JUSTIFICATIVA

Conforme critério CEO/CTO: **qualquer KPI vermelho** congela Etapa 3 (renomes, stubs, tag dual em `executive_ledger`, `test_one_truth`).

**Status atual:** 3 KPIs em vermelho + 1 em amarelo · **Etapa 3 BLOQUEADA**.

Antes de renomear qualquer módulo executivo, é preciso:
1. Reescrever o `ONE_TRUTH_MATRIX.md` com o **vocabulário real do banco** (não o pretendido).
2. Trocar a fonte oficial de **Inadimplência** para `subscriber_invoices` (real) — e remover `loyalty` como concorrente.
3. Reconciliar a divergência de **27 clientes** + **R$ 47,8k de MRR** entre `subscribers` e `loyalty` (provável fixture residual + reajustes não propagados).
4. Validar `paid_date` como campo canônico de realização (substituir `paid_at` em qualquer doc/código).

---

## 🔧 AÇÕES RECOMENDADAS (não-código nesta etapa)

### Para destravar o AMARELO (Clientes · 0,98%)

| Ação | Impacto | Esforço |
|---|---|---|
| Identificar os 27 clientes em `subscribers` que NÃO estão em `loyalty` (cruzar por `document`) e classificá-los: importação manual? cadastro avulso? teste residual? | Decide se é Verdade Operacional ou ruído | 30 min de query + planilha |
| Backfill do `subscribers.document` (atualmente vazio) com cruzamento por `name+email+phone` contra `loyalty_imported_db` | Permite reconciliação por chave única no futuro | P1 — script idempotente |

### Para destravar VERMELHO #1 (Receita · 17,23%)

| Ação | Impacto | Esforço |
|---|---|---|
| Reconciliar `subscribers.plan_price` × `loyalty.monthly_fee` no nível de cada cliente. Listar discrepâncias > 10%. | Mostra se é reajuste, fixture ou erro de cadastro | Script de diff |
| Definir **fonte ÚNICA oficial** para "MRR atual": a operação aceita 2 candidatos hoje, é preciso escolher 1 (recomendado: `subscribers`, porque é write-master da Ligo, e `loyalty` é importado). | Elimina ambiguidade definitiva | Decisão CTO |
| Remover/marcar 1 doc `TEST_Dup_985042` (plan_name começando com `TEST_`) em subscribers de `co-demo` | Higiene | 1 min |

### Para destravar VERMELHO #2 (Tickets · vocabulário)

| Ação | Impacto | Esforço |
|---|---|---|
| Reescrever a seção de tickets do `ONE_TRUTH_MATRIX.md` para `status ∈ {aberta, pendente, encerrada, finalizada}` (PT-BR canônico do `ticket_schema.py`) | Alinha doc com código | 15 min |
| Padronizar TODOS os dashboards executivos para o vocabulário PT-BR (sem mapeamento dinâmico) | Garante 0% divergência futura | P0 imediato |

### Para destravar VERMELHO #3 (Inadimplência · 62%)

| Ação | Impacto | Esforço |
|---|---|---|
| Promover `subscriber_invoices` como **fonte oficial** de inadimplência e demover `loyalty` para "referência externa Atlaz" (não usada em decisão) | Resolve a divergência | Decisão CTO + atualização do matrix |
| Atualizar `presidente_executive.dinheiro_em_risco_brl` e `revenue_realization.inadimplencia` para ler de `subscriber_invoices.status='overdue'` (depois da decisão acima) | Alinha código com matrix corrigida | Etapa 3 |

---

## 📝 ANEXOS

### A. Comandos executados nesta auditoria
```bash
cd /app/backend && python3 /tmp/one_truth_audit.py
```
Saída: 6 KPIs, 18 queries, 100% contra Mongo real `co-demo`. **Zero mocks.**

### B. Coleções consultadas
- `subscribers` (status, plan_price, document)
- `loyalty_imported_db` (status, monthly_fee, registration_date, invoices_paid/overdue)
- `subscriber_invoices` (status, amount, amount_paid, paid_date, due_date)
- `tickets` (status, state)
- `universo_ligo_invites` (decision, status, invite_source, do_not_contact_universo_ligo)
- `universo_ligo_levels` (existe e está vazia em co-demo)
- `motor_ia_revenue_attribution` (referenciada no matrix, não auditada nesta rodada)

### C. Documentos cruzados
- `/app/memory/ONE_TRUTH_MATRIX.md` (matriz original — agora marcada como "DESATUALIZADA: vocabulário fora do banco")
- `/app/memory/CLIENTE_FUNDADOR_REPORT.md` (130 fundadores declarados — bate com cálculo)
- `/app/memory/EMBAIXADORES_NATURAIS.md` (130 candidatos naturais)

### D. Riscos NÃO abordados nesta etapa (próxima rodada)
- Receita por **agente IA** (`motor_ia_revenue_attribution`) vs `subscriber_invoices.paid_date` — não cruzados.
- **Previsão 30d** (`forecast_30d`) — preditiva (até 5% tolerância) — não testada.
- **Atendimentos Isabella** (`aihub_wa_messages`) — não auditada nesta rodada.
- **CTOs críticas / Incidentes** — fora do escopo desta Etapa 2.5.

---

## 🎯 RECOMENDAÇÃO FINAL AO CEO

> **NÃO autorizar Etapa 3 ainda.**
>
> Sugestão de sequência:
> 1. CEO/CTO ratifica as 4 ações recomendadas acima (todas não-código exceto 1 script de diff e 1 update de docs).
> 2. Rodar a auditoria novamente após as correções de documentação.
> 3. Quando o painel ficar **🟢 / 🟢 / 🟢 / 🟢 / 🟢 / 🟢** (todos VERDES ou no máximo 1 AMARELO em derivada), abrir nova ordem `VOCÊ AUTORIZA?` para Etapa 3.
>
> *Verdade primeiro. Governança depois. Execução por último.*

---

## 📌 RECADO REGISTRADO — "POR QUE ESTE CLIENTE IMPORTA?"

Anotado como funcionalidade futura (NÃO implementar agora). Especificação preliminar registrada:

```
Quando atendente abrir ficha do cliente:

⭐ FUNDADOR
- Cliente desde 2015
- 67 faturas pagas
- 0 cancelamentos
- 0 inadimplência
Motivo: Fundador validado pela curadoria Universo Ligo.
```

Esta tela consumirá o payload já existente de `services/customer_intelligence.py`
(Etapa 2 BACKEND fechada) — sem inventar nenhum dado novo, apenas humanizando o
que já está calculado e versionado em `universo_ligo_score_audit`.

**Acionamento:** somente após `CUSTOMER_INTELLIGENCE_UI_BADGES=true` ser autorizado pelo CEO.

---

**FIM DA ETAPA 2.5 — AGUARDANDO DECISÃO DO CEO.**
