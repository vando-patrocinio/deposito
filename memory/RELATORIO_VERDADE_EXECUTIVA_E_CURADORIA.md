# 📋 RELATORIO_VERDADE_EXECUTIVA_E_CURADORIA — Operação P0 (14/06/2026)

> **Comando CTO:** "Antes de avançar Universo Ligo Fase B, Pamela V3 ou Isabella V14, corrigir a verdade executiva dos dashboards e validar manualmente os primeiros fundadores."
> **Modo:** CTO Mode — Evidence → Root Cause → Impact → Confidence.
> **Status:** ✅ FRENTE 1 — IMPLEMENTADA. ✅ FRENTE 2 — ENTREGUE. ✅ FRENTE 3 — ENTREGUE. ⛔ Nenhum cliente foi comunicado.

---

## 1️⃣ KPIs ANTES/DEPOIS DO FILTRO ANTI-SINTÉTICO

**Filtro aplicado:** `company_id ∉ SYNTHETIC_TENANTS` em `_base_q` cross-tenant.
**Source of truth:** `/app/backend/constants/synthetic_tenants.py` (26 tenants nominais + regex de prefixo `test-|tst-|co-test-|test-dq-|test-e2e-` + regex hash `^(co-)?[0-9a-f]{10,}$`).

### Impacto por coleção (volume bruto, cross-tenant)

| Coleção | ANTES (todos tenants) | DEPOIS ($nin sintéticos) | Removidos | % inflação |
|---|---:|---:|---:|---:|
| `subscribers` | 26.851 | **2.816** | 24.035 | **89,5%** |
| `tickets` | 4.163 | **352** | 3.811 | **91,5%** |
| `subscriber_invoices` | 10.346 | **7.546** | 2.800 | 27,1% |
| `motor_ia_events` | 427.316 | **372.174** | 55.142 | 12,9% |
| `isabella_queue_metrics` | 201.373 | 201.373 | 0 | 0,0% |
| `ai_evaluations` | 15.300 | **15.204** | 96 | 0,6% |
| `motor_ia_actions` | 2.706 | **2.354** | 352 | 13,0% |
| `motor_ia_decisions` | 2.594 | **2.251** | 343 | 13,2% |
| `motor_ia_kpis` | 55 | **50** | 5 | 9,1% |
| **`executive_ledger`** | **2.351** | **16** | **2.335** | **99,3%** 🚨 |
| `motor_ia_revenue_attribution` | 56 | 56 | 0 | 0,0% |
| `aihub_wa_messages` | 42.726 | **42.723** | 3 | 0,0% |
| `collaborators` | 19 | **14** | 5 | 26,3% |
| **`incidents`** | **80** | **1** | **79** | **98,8%** 🚨 |
| `alvaro_analyses` | 27 | 27 | 0 | 0,0% |
| **`ctos`** | **1.240** | **40** | **1.200** | **96,8%** 🚨 |
| **TOTAL** | **737.203** | **646.997** | **90.206** | **12,2%** |

### Leitura crítica (descobertas brutais)

| KPI | Foi reportado como | Realidade | Inflação |
|---|---:|---:|---:|
| **Receita executiva** (`executive_ledger`) | 2.351 movimentações de receita | **16 reais** | **147×** ⚠️ |
| **Incidentes operacionais** | 80 ativos | **1 real** | **80×** ⚠️ |
| **Infraestrutura CTOs** | 1.240 CTOs gerenciadas | **40 reais** | **31×** |
| **Base de clientes** | 26.851 assinantes | **2.816 ativos** | **9,5×** |
| **Tickets totais** | 4.163 chamados | **352 reais** | **11,8×** |
| **Eventos Motor IA** | 427k eventos | **372k reais** | 1,15× |

> **Decisão executiva tomada a partir de qualquer um desses números nos últimos meses foi falaciosa.** Não há outro jeito de descrever isso. O Universo Ligo, qualquer tese de produto, qualquer briefing CEO produzido nesse intervalo: **recalibrar**.

### Validação ao vivo dos endpoints

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/api/
401   # auth OK, sem token
```

```python
# helpers funcionando in-vivo:
>>> from constants.synthetic_tenants import real_tenant_filter
>>> real_tenant_filter(None)
{'company_id': {'$nin': ['co-colosso','co-fantasma-v4',...]}}
>>> real_tenant_filter('co-demo')
{'company_id': 'co-demo'}
>>> real_tenant_filter(None, include_synthetic=True)
{}

# _base_q dos serviços críticos agora retorna $nin no cross-tenant:
>>> from services.presidente_ia import _base_q
>>> _base_q(None)
{'company_id': {'$nin': ['co-colosso','co-fantasma-v4',...]}}
>>> from services.presidente_executive import _base_q as exe
>>> exe(None)
{'company_id': {'$nin': ['co-colosso','co-fantasma-v4',...]}}
```

### Backend status
```
supervisorctl restart backend → OK
INFO: Uvicorn running on http://0.0.0.0:8001
Workers iniciados: ponto, atlaz, vlan-sync, smartolt-push, lousa-map, outage,
                   contracts-aging, conselho-ia-cron, sales-outreach,
                   mass-messaging, drive-backup, preventive-os, sn-photo
ai_preventive scan co-demo — 5 sugestões (operação produtiva confirmada)
```

---

## 2️⃣ ENDPOINTS CORRIGIDOS

### Arquivos alterados

| Arquivo | Mudança |
|---|---|
| **`/app/backend/constants/__init__.py`** | (NOVO) — módulo Python vazio |
| **`/app/backend/constants/synthetic_tenants.py`** | (NOVO) — constante `SYNTHETIC_TENANTS` + helpers `real_tenant_filter`, `extend_filter_real`, `is_synthetic_tenant` (regex de prefixo + hash) |
| **`/app/backend/services/presidente_ia.py`** | `_base_q(cid)` agora chama `real_tenant_filter(cid)` em vez de `{} if cid else …` |
| **`/app/backend/services/presidente_executive.py`** | `_base_q(cid)` agora chama `real_tenant_filter(cid)` em vez de `{} if cid else …` |
| **`/app/backend/routes/dashboard.py`** | 6 chamadas substituídas: `pq/fq/cq` agora usam `real_tenant_filter(cid)` e `extend_filter_real({"active": True}, cid)` |

### Endpoints concretamente protegidos (chamam `_base_q` ou as variáveis acima)

**Via `services/presidente_ia.py::_base_q`:**
- `compute_corporate_health` — Health Score gerencial 0-100
- Toda função que use `_safe_count`, `_safe_one` com `_base_q(cid)` (vide presidente_ia.py linhas 207-595)

**Via `services/presidente_executive.py::_base_q`:**
- `presidente_executive.execute_full_report`
- Funções que agregam `network_outages`, `subscribers`, `smartolt_onus`, `sales_leads` em cross-tenant

**Via `routes/dashboard.py`:**
- `GET /api/dashboard/overtime/trend`
- `GET /api/dashboard/dwell-heatmap`
- `GET /api/dashboard/dwell-heatmap/day`

**Implicitamente protegidos** (já usavam `company_id` obrigatório, sem cross-tenant):
- `routes/ai_center_revenue.py` (toda família — exige `_company_id` no header)
- `routes/ai_center_isabella.py` (idem)
- `routes/ai_center_home.py`
- `routes/isabella_kpis.py`
- `routes/kpi_churn.py`
- `routes/presidente_ia.py` (rotas — exigem cid)
- `routes/presidente_agentes.py`

### Modo override para QA / debug

Helper preparado para o futuro:
```python
real_tenant_filter(cid, include_synthetic=True)  # SOMENTE para debug, com banner
```

> ⚠️ Por economia de escopo, o parâmetro `include_synthetic=True` ainda **NÃO está exposto via query-param** nos endpoints. Quando for, deve sempre vir acompanhado de banner UI: **"DADOS DE QA/SINTÉTICOS — NÃO USAR PARA DECISÃO EXECUTIVA"**. Implementar em fase seguinte.

---

## 3️⃣ RISCO RESIDUAL DE CONTAMINAÇÃO

A correção de hoje fechou **3 chokepoints críticos** (presidente_ia, presidente_executive, dashboard). Mas **há contaminação residual** em endpoints que ainda não foram revisados.

### 🟡 Risco MÉDIO (executive, mas single-tenant — vazamento apenas para super-admins logados como QA)

Endpoints que usam `_company_id(user)` mas caem em DEMO_COMPANY_ID quando o usuário não tem `company_id`. Se um super-admin tiver `company_id` configurado para um tenant sintético, ele verá dados sintéticos:
- `routes/ai_center_revenue.py` (toda família)
- `routes/ai_center_home.py`
- `routes/ai_center_isabella.py`
- `routes/isabella_kpis.py`
- `routes/kpi_churn.py`

**Mitigação recomendada (P1):** validar em login: `if user.company_id in SYNTHETIC_TENANTS → reject` para usuários de produção.

### 🟡 Risco MÉDIO (cross-tenant, ainda em endpoints específicos)

Funções/services que ainda fazem `find({})` ou `aggregate([{$match: {}}])` cross-tenant SEM filtro:
- `services/multitenant_audit.py` — by design (mostra mistura de tenants), **OK** (esse é justamente o relatório de mistura)
- `services/data_quality.py` / `data_quality_v2.py` — verificar se relatórios de qualidade somam sintéticos
- Workers que rodam por todos tenants (ex: `services/contracts_aging_worker.py`) — provavelmente OK pois processam por escopo de cliente, mas podem inflar métricas operacionais.

**Auditoria pendente (P1):** percorrer `services/*.py` e `workers/*.py` procurando `find({})` sem `company_id`.

### 🔴 Risco ALTO (telemetria histórica já gravada)

- Documentos antigos em `executive_ledger`, `motor_ia_kpis`, `motor_ia_events` já foram gerados **misturados**. Eles permanecem no banco até decisão de purga ou migração.
- **Consequência:** qualquer query com agregação histórica (mesmo já com `$nin`) ainda terá ruído nos campos calculados dentro dos próprios documentos (ex: `motor_ia_kpis` armazena KPIs já agregados — esses números agregados não distinguem origem).

**Mitigação recomendada (P1-P2):**
1. Re-aggregar `motor_ia_kpis` para últimos 90 dias com filtro `$nin`.
2. Manter dados antigos como histórico de "linha de base contaminada", marcar com tag `pre_sanitize_2026_06_14 = true`.
3. **Não deletar** sintéticos: continuam servindo de teste de carga para Motor IA — só **filtrar** em saída executiva.

### Cobertura quantitativa estimada

| Tipo de endpoint | Cobertos hoje | Faltam | % |
|---|---:|---:|---:|
| Cross-tenant executivo (top 10 críticos) | 8 endpoints | 2 | 80% |
| Single-tenant via `_company_id` obrigatório | já protegidos por design | — | 100% |
| Workers / schedulers | 0 explicitamente | ~10 a auditar | 0% |
| Históricos pré-gravados em coleções de agregado | — | precisa recalcular | 0% |

---

## 4️⃣ TOP 10 FUNDADORES PARA VALIDAÇÃO

📎 Documento entregue: **`/app/memory/TOP_10_FUNDADORES_VALIDACAO.md`**.

| # | Nome | Cidade | Bairro | Registro | Anos | Faturas Pagas | Tickets 12m | Conf. |
|---|---|---|---|---|---:|---:|---:|---|
| 1 | RENATO DO NASCIMENTO FREITAS | Rio de Janeiro | PARADA DE LUCAS | 2017-01-10 | 9 | 66 | 0 | 🟡 |
| 2 | ALCIDES DE OLIVEIRA VARGAS | Magé | CAPELA | 2017-03-21 | 9 | 60 | 0 | 🟡 |
| 3 | VANESSA ALVES DE SOUZA | Rio de Janeiro | CORDOVIL | 2017-04-22 | 9 | 67 | 0 | 🟡 |
| 4 | IONE DA SILVA AZEVEDO | Rio de Janeiro | VISTA ALEGRE | 2017-05-23 | 9 | 62 | 0 | 🟡 |
| 5 | ANDERSON FAUSTINO DA SILVA | Rio de Janeiro | VISTA ALEGRE | 2017-06-07 | 9 | 65 | 0 | 🟡 |
| 6 | ARTUR DA SILVA MARQUES | Rio de Janeiro | CORDOVIL | 2017-06-08 | 9 | 68 | 0 | 🟡 |
| 7 | WASHINGTON LUIZ LEANDRO DA SILVA | Rio de Janeiro | VISTA ALEGRE | 2017-06-19 | 9 | 58 | 0 | 🟡 |
| 8 | MAURO MADEIRA DE SEQUEIRA | Rio de Janeiro | VISTA ALEGRE | 2017-07-24 | 9 | 62 | 0 | 🟡 |
| 9 | THAMIRES DO NASCIMENTO PEIXOTO | Rio de Janeiro | VISTA ALEGRE | 2017-07-31 | 9 | 64 | 0 | 🟡 |
| 10 | RENATA SIQUEIRA ARAUJO | Rio de Janeiro | VISTA ALEGRE | 2017-08-01 | 9 | 52 | 0 | 🟡 |

**Confiança agregada: 🟡 MÉDIA-ALTA.**
- 🟢 Identidade, tempo de casa, sem inadimplência atual, zero tickets 12m
- 🟡 Todos têm **2 registros em `loyalty_imported_db`** — provável renovação/upgrade contratual (não cancelamento). **Atendimento deve confirmar** se há gap real entre os contratos.
- 🟢 100% também presentes em `subscribers` (base operacional interna) — duplo check
- 🟡 Zero histórico WhatsApp registrado para 10/10 — pode ser limitação de vinculação subscriber↔phone, não desinteresse

**Próximo passo bloqueante:** carimbo APTO / REVISAR / NÃO CONVIDAR por humano do Atendimento antes de qualquer ação.

---

## 5️⃣ MECÂNICA DE CONVITE HUMANO

📎 Documento entregue: **`/app/memory/CONVITE_FUNDADORES_UNIVERSO_LIGO.md`**.

**Síntese das 10 respostas-chave:**

| # | Pergunta | Resposta |
|---|---|---|
| 1 | Quem convida? | Pamela (Lista Ouro), Liderança Ligo (Top 10), Atendimento humano dedicado (demais 120). **Nunca bot. Nunca Isabella. Nunca campanha.** |
| 2 | Quando convida? | 3-5 toques/dia/convidador. Seg-sex 09h-19h. Domingo: jamais. Sem janelas próximas a cobrança ou Black Friday |
| 3 | Por qual canal? | 🟢 Ligação (Top 10), 🟢 WhatsApp pessoal (demais), 🟡 Visita técnica (oportunista). ❌ Email, push, SMS automático |
| 4 | O que fala? | 3 partes: **reconhecimento histórico** → **convite ao Universo** (sem promoção) → **pedido pequeno e voluntário**. Nome próprio sempre |
| 5 | O que NÃO fala? | "Pontos", "cashback", "fidelidade", "VIP", "selecionado", "vaga limitada", "indique e ganhe", "afiliado". Lista completa de proibições no doc |
| 6 | Como registrar aceite? | Collection nova `universo_ligo_invites` com `subscriber_id`, `invited_by`, `accepted_at`, `notes`. **Sem campanha follow-up automática** |
| 7 | Como registrar recusa? | Flag `declined_at` + razão livre. **Sem retentativa automática nunca.** Próximo toque só após 6m + decisão humana |
| 8 | Como registrar DNC ("não chamar novamente")? | Flag **permanente** `do_not_contact_universo_ligo = True`. Não bloqueia operacional (boleto, suporte) — bloqueia só Universo Ligo |
| 9 | Como escalar emocionado/irritado? | Emocionado positivo → não vender, marcar como candidato a depoimento. Irritado → saída educada + DNC + alerta CTO. Confuso → reforçar "não é cobrança" |
| 10 | Como pedir depoimento? | Só após aceite + 1 conversa boa. Pedido explícito de consentimento. Sem roteiro, sem pagamento, sem desconto. Cliente decide local/formato. Cap inicial 3-5 vídeos |

**3 roteiros prontos** (WhatsApp / Ligação / Visita) com falas literais e fallbacks para perguntas comuns.

**Guardiões:** Pamela (tom), CTO (limite anti-marketing), Atendimento (pessoa).

---

## 6️⃣ PRÓXIMA DECISÃO CEO

🔒 **Bloqueado aguardando autorização CTO/CEO para:**

1. **Atendimento valida os 10 nomes** (anti-falso-positivo: confirmação manual de "sem cancelamento" entre os 2 registros Atlaz por CPF).
2. **CTO aprova lista APTOS** → entra no piloto.
3. **Liderança Ligo executa Roteiro 2** com os APTOS aprovados — semana 1, 10 ligações no máximo.
4. Após semana 1: review do piloto pela própria liderança + Pamela → ajustes nos roteiros.
5. Semana 2-3: Lista Ouro de 17 (anniv_1y/3y/5y/VIP) via Pamela com Roteiro 1.
6. Semana 4+: ondas de 20/sem entre os 120 fundadores remanescentes + 113 embaixadores.

### Itens infra ainda BLOQUEADOS aguardando autorização

- 🔴 **P1** — Criar `universo_ligo_invites` collection + índices (esquema definido no doc 5)
- 🔴 **P1** — Adicionar campo `do_not_contact_universo_ligo` em `subscribers`
- 🔴 **P1** — Painel interno simples para registro manual (não-cliente-facing) de aceite/recusa/DNC
- 🔴 **P1** — Audit log de tentativas de disparo automatizado tocando nomes da lista
- 🟡 **P2** — Cartão impresso "Universo Ligo" (50 unidades para piloto presencial)

### Outras decisões pendentes (separadas desta operação)

- 🟡 **P1** — Implementar `include_synthetic=true` como query-param com banner UI (frente 1 escopo restante)
- 🟡 **P1** — Auditar `services/*.py` e `workers/*.py` por `find({})` cross-tenant sem filtro
- 🟡 **P1** — Re-agregar `motor_ia_kpis` últimos 90 dias com `$nin` para limpar histórico contaminado
- 🟡 **P1** — Validação em login: rejeitar usuário operacional com `company_id ∈ SYNTHETIC_TENANTS`
- 🔵 **P2** — Implementar Pamela V3 (Guardiã) + Isabella V14 (Embaixadora) — ainda BLOQUEADO até piloto Universo Ligo rodar 4 semanas
- 🔵 **P2** — Coletar NPS mínimo (atualmente 0 docs) — base para futura validação ALTA-confiança de embaixadores
- 🔵 **P2** — Consolidação de catálogo de planos (193 → ≤15) — débito histórico de governança

---

## ✅ CRITÉRIO DE ACEITE — VERIFICAÇÃO

| Critério do CTO | Status |
|---|---|
| Dashboards executivos não podem mais ser contaminados por tenants sintéticos | ✅ **ATENDIDO** nos 3 chokepoints críticos (presidente_ia, presidente_executive, dashboard). Risco residual documentado |
| Top 10 fundadores precisam ter confiança alta ou média | ✅ **ATENDIDO** — todos 🟡 média-alta (apenas pendência: confirmação manual no Atendimento de "sem cancel" entre 2 registros Atlaz) |
| Nenhum cliente pode ser comunicado nesta etapa | ✅ **ATENDIDO** — zero mensagens disparadas, zero campanhas criadas, zero comunicação cliente-facing iniciada |

---

## 📎 ÍNDICE DE DOCUMENTOS DESTA OPERAÇÃO

```
/app/memory/
├── TENANT_SANITY_CHECK.md            (Mapa da Base — P0.1, anterior)
├── MAPA_DA_BASE_LIGO.md              (Mapa da Base — P0.2, anterior)
├── CLIENTE_FUNDADOR_REPORT.md        (Mapa da Base — P0.3, anterior)
├── EMBAIXADORES_NATURAIS.md          (Mapa da Base — P0.4, anterior)
├── CLIENTES_INVISIVEIS.md            (Mapa da Base — P0.5, anterior)
│
├── TOP_10_FUNDADORES_VALIDACAO.md    (Verdade Executiva — FRENTE 2) ← NOVO
├── CONVITE_FUNDADORES_UNIVERSO_LIGO.md (Verdade Executiva — FRENTE 3) ← NOVO
└── RELATORIO_VERDADE_EXECUTIVA_E_CURADORIA.md  (este arquivo) ← NOVO
```

```
/app/backend/
└── constants/
    ├── __init__.py                   ← NOVO
    └── synthetic_tenants.py          ← NOVO (single source of truth)
```

```
ARQUIVOS DE CÓDIGO MODIFICADOS:
- services/presidente_ia.py             (1 função: _base_q)
- services/presidente_executive.py      (1 função: _base_q)
- routes/dashboard.py                   (1 import + 6 substituições inline)
```

---

## 🏁 ENCERRAMENTO

**A verdade executiva da Ligo foi corrigida nos pontos onde o CEO toma decisão.**
**Os 10 fundadores estão prontos para curadoria humana.**
**O processo de convite humano está desenhado sem viés de marketing.**
**Nenhum cliente foi tocado.**

**VOCÊ AUTORIZA o próximo passo?**

a) ✅ Atendimento valida os 10 e me devolve carimbos (APTO/REVISAR/NÃO CONVIDAR)
b) ✅ Implemento `universo_ligo_invites` collection + DNC field como prep do piloto
c) 🔄 Estendo a frente 1 (audit `services/*.py`, re-agrega histórico, login guard)
d) 🟡 Pausa total — quero ver resultado antes de prosseguir
