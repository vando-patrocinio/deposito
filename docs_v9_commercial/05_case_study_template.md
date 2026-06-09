# Case Study — Piloto SmartProv [Nome do Provedor]

> **STATUS:** DRAFT V9.4 — template oficial. Preencher durante e após o piloto controlado de 30 dias.
> **REGRA:** este documento **não afirma causalidade definitiva** de receita atribuída à IA. Apresenta lift medido, recortes operacionais e contexto.

---

## 0. Metadados

| Campo | Valor |
|-------|-------|
| Provedor | _[Razão Social]_ |
| Cidade/Estado | _[•]_ |
| Faixa de assinantes | _[1k–50k]_ |
| Data de início | _DD/MM/AAAA_ |
| Data de término | _DD/MM/AAAA_ |
| Sponsor técnico | _[Nome / Cargo]_ |
| Sponsor comercial | _[Nome / Cargo]_ |
| Whitelist `CAUSALITY_PILOT_PHONES` | _[N números autorizados]_ |
| `HOMOLOG_MODE` final | `true` (mantido durante todo o piloto) |

---

## 1. Sumário Executivo

_Parágrafo único de 4–6 linhas. O quê foi testado, por quanto tempo, qual o lift medido, qual a recomendação._

**Indicadores-chave (preencher ao final):**

| Indicador | Baseline (pré-piloto) | Piloto (30d) | Lift |
|-----------|----------------------|--------------|------|
| Receita atribuída (Action→Cash) | R$ _•_ | R$ _•_ | _•_ % |
| Tickets fechados com Smart Field completo | _•_ % | _•_ % | _•_ pp |
| Disponibilidade da plataforma | — | _•_ % | — |
| Tempo médio de resolução (S2) | — | _•_ h | — |

---

## 2. Contexto do Provedor

- **Operação:** _número de OS/dia, tamanho do NOC, ferramentas usadas hoje (Zabbix? Grafana? planilhas?)._
- **Dor primária:** _[ex.: receita não rastreada por ação operacional, OS fechadas sem rastro, alertas técnicos desligados do caixa]._
- **Razão para o piloto:** _[ex.: validar antes de migrar 100% da operação]_.

---

## 3. Setup Técnico

| Componente | Configuração no piloto |
|-----------|------------------------|
| `HOMOLOG_MODE` | `true` durante todos os 30 dias |
| `CAUSALITY_PILOT_PHONES` | _[lista de N números com consentimento documentado]_ |
| Sidecar WhatsApp (Baileys) | Rodando local na porta 3002 |
| Observability Twin | _[real / mock]_ (`ZABBIX_URL` + `GRAFANA_URL` setados em DD/MM) |
| Smart Field Ops | Captura: `resolution_kind`, `asset_recovered`, `signed_receipt`, `reopened_within_7d` |
| Cohorts A/B | _[N cohorts criados em `motor_ia_cohorts`]_ |

---

## 4. Metodologia

- **Tratamento vs Controle:** cohorts pareados por strata (`branch + plan_price_band + invoice_amount_band + days_overdue_band`) via `v8_4_cohort.py:pair_match`.
- **Janela de atribuição:** _[N]_ dias após o evento (configurada em `attribution_window`).
- **Métrica de lift:** Wilson CI95 + z-test two-proportions (`v8_3_causality.py:calculate_lift`).
- **Receita atribuída:** soma de `motor_ia_outcomes.actual_BRL` com `environment="causality_pilot"`.

> **Limitação explícita:** o lift medido reflete o piloto controlado deste provedor específico. Não é generalizável sem replicação.

---

## 5. Resultados Operacionais

### 5.1 Adoção do Smart Field Ops

| Semana | OS finalizadas | `resolution_kind` preenchido | `signed_receipt` preenchido | `asset_recovered` preenchido |
|--------|---------------|-------------------------------|-----------------------------|------------------------------|
| Sem 1 | _•_ | _•_ % | _•_ % | _•_ % |
| Sem 2 | _•_ | _•_ % | _•_ % | _•_ % |
| Sem 3 | _•_ | _•_ % | _•_ % | _•_ % |
| Sem 4 | _•_ | _•_ % | _•_ % | _•_ % |

### 5.2 Disponibilidade vs SLA

| Componente | SLA-alvo | Real | Δ |
|-----------|---------|------|---|
| API backend | 99,5% | _•_ % | _•_ pp |
| Sidecar WhatsApp | 98,0% | _•_ % | _•_ pp |
| Observability Twin | 99,0% | _•_ % | _•_ pp |

### 5.3 Severidades dos Incidentes

| Sev | Qtd | Tempo médio 1ª resposta | Tempo médio resolução |
|----|-----|-------------------------|------------------------|
| S1 | _•_ | _•_ | _•_ |
| S2 | _•_ | _•_ | _•_ |
| S3 | _•_ | _•_ | _•_ |

---

## 6. Resultados de Causalidade (Medição de Lift)

### 6.1 Cohort Principal

| Métrica | Tratamento (n=_•_) | Controle (n=_•_) | Lift | CI95 |
|---------|--------------------|--------------------|------|------|
| Taxa de pagamento na janela | _•_ % | _•_ % | _•_ pp | _[lo, hi]_ |
| Receita atribuída total | R$ _•_ | R$ _•_ | R$ _•_ | — |
| Tickets reabertos em 7d | _•_ % | _•_ % | _•_ pp | _[lo, hi]_ |

### 6.2 Cohorts Secundários

_Listar 2–3 recortes relevantes (ex.: por faixa de plano, por zona geográfica)._

> **Atenção redacional:** apresentar como "**lift medido neste piloto**", nunca como "**IA gera receita**". O documento `04_contrato_saas.md` (Cláusula 2.2) é taxativo nesse ponto.

---

## 7. Aprendizados Operacionais

- _[O quê funcionou bem]._
- _[O quê precisou ser ajustado durante o piloto]._
- _[Pontos de fricção com a equipe de campo]._
- _[Pontos de fricção com a base de dados do provedor]._

---

## 8. Conformidade LGPD

- Whitelist `CAUSALITY_PILOT_PHONES` somente com **consentimento documentado** dos titulares (anexo).
- `HOMOLOG_MODE=true` mantido durante todo o piloto — demais números seguem mascarados e redirecionados.
- Logs de auditoria: `motor_ia_events.CAUSALITY_PILOT_REAL_SEND` e `HOMOLOGATION_BLOCKED_REAL_PHONE` retidos.
- Incidentes de segurança no período: _[N]_.

---

## 9. Próximos Passos

- [ ] Conversão do piloto em contrato definitivo (aditivo comercial).
- [ ] Expansão da whitelist ou desligamento gradual de `HOMOLOG_MODE` mediante aprovação documentada.
- [ ] Replicação em provedor adicional (validação cruzada).
- [ ] Integração de novos módulos (a definir conforme demanda do CONTRATANTE).

---

## 10. Anexos

- A. Consentimentos LGPD dos números na whitelist.
- B. Snapshots do `connectors/status` (Observability Real) em datas-chave.
- C. Export dos cohorts (`motor_ia_cohorts`, `motor_ia_causality`).
- D. Relatórios mensais de piloto (item 6 do `02_sla.md`).

---

_Documento template DRAFT V9.4. Preencher após coleta de dados do piloto. Revisão pelo CTO obrigatória antes de qualquer divulgação externa._
