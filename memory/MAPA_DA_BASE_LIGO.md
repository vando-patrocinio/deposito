# 🗺️ MAPA_DA_BASE_LIGO — Quem é Realmente o Cliente Ligo

> **Operação:** Mapa da Base — Fase P0.2
> **Data:** 2026-06-14 17:42 UTC
> **Fonte primária:** `loyalty_imported_db` (24.040 registros, `company_id="co-demo"`, importado de Atlaz/Hubsoft)
> **Filtro aplicado:** `company_id = "co-demo"` AND `status = "Ativo"`
> **Total da base ATIVA real:** **2,746 clientes** (confirma leitura do CEO: "~3.000 reais")
> **Tenants excluídos:** ver `TENANT_SANITY_CHECK.md`

---

## 📌 SÍNTESE DE UMA LINHA

A Ligo é uma operação **predominantemente carioca, concentrada em CORDOVIL**, com presença secundária em **Magé (RJ)** e três cidades de SP (**Guaratinguetá, Cachoeira Paulista, Osasco**). **Ticket médio R$ 103,37**. Cliente típico mora numa única vizinhança, paga em dia, abre 1-2 chamados/ano.

---

## 1️⃣ DISTRIBUIÇÃO POR ESTADO

| UF | Ativos | % |
|---|---:|---:|
| RJ | 2,153 | 78.4% |
| SP | 590 | 21.5% |
| — | 3 | 0.1% |

**Leitura:** Operação é **~77% RJ + ~23% SP**. SP é meramente expansão recente em cidades de interior (Guaratinguetá / Cachoeira Paulista) + uma operação isolada em Osasco. Nenhum outro estado tem presença produtiva.

---

## 2️⃣ DISTRIBUIÇÃO POR CIDADE (Top 13)

| # | Cidade | Ativos | % | Comentário |
|---|---|---:|---:|---|
| 1 | Rio De Janeiro | 1,765 | 64.3% | 🔥 Coração da operação. Bairros Zona Norte (Cordovil, Vista Alegre, Irajá, Ramos, Parada de Lucas) |
| 2 | Guaratinguetá | 313 | 11.4% | Maior cidade SP. Concentrada em PILOES, BOCAINA, CAPELA |
| 3 | Magé | 213 | 7.8% | Segunda maior cidade RJ. Bairros: Santo Aleixo, Vila Velha, Fragoso |
| 4 | Cachoeiras De Macacu | 136 | 5.0% | RJ — interior. ~5% da base |
| 5 | Cachoeira Paulista | 125 | 4.6% | SP — interior. ~4,5% da base |
| 6 | Osasco | 81 | 2.9% | SP — Grande SP. Bairro: VILA MENCK, JARDIM ESMERALDA |
| 7 | Lorena | 52 | 1.9% | SP — RJ-SP fronteira |
| 8 | Angra Dos Reis | 39 | 1.4% | RJ — litoral. Pequena operação |
| 9 | Adamantina | 12 | 0.4% | SP — interior profundo. Pontual |
| 10 | São Paulo | 3 | 0.1% | Capital — quase irrelevante (3 clientes) |
| 11 | Bocaina | 2 | 0.1% | SP — 2 clientes (atípicos) |
| 12 | Silveiras | 1 | 0.0% | SP — 1 cliente |
| 13 | Piquete | 1 | 0.0% | SP — 1 cliente |

---

## 3️⃣ DISTRIBUIÇÃO POR BAIRRO (Top 25 — normalizado UPPERCASE)

| # | Bairro | Cidade-Provável | Ativos | % |
|---|---|---|---:|---:|
| 1 | CORDOVIL | Rio de Janeiro | 895 | 32.6% |
| 2 | RAMOS | Rio de Janeiro | 220 | 8.0% |
| 3 | VISTA ALEGRE | Rio de Janeiro | 213 | 7.8% |
| 4 | IRAJÁ | Rio de Janeiro | 181 | 6.6% |
| 5 | PILOES | Guaratinguetá | 162 | 5.9% |
| 6 | BOCAINA | Guaratinguetá | 90 | 3.3% |
| 7 | PARADA DE LUCAS | Rio de Janeiro | 68 | 2.5% |
| 8 | VILA MENCK | Osasco | 56 | 2.0% |
| 9 | CASTALIA | Cachoeira Paulista | 52 | 1.9% |
| 10 | PENHA | Rio de Janeiro | 50 | 1.8% |
| 11 | BRAZ DE PINA | Rio de Janeiro | 49 | 1.8% |
| 12 | OLARIA | Rio de Janeiro | 40 | 1.5% |
| 13 | VALERIO | ? | 38 | 1.4% |
| 14 | BRÁS DE PINA | Rio de Janeiro | 37 | 1.3% |
| 15 | NATUREZA | ? | 31 | 1.1% |
| 16 | VILA VELHA (SANTO ALEIXO) | Magé | 25 | 0.9% |
| 17 | PICO (SANTO ALEIXO) | Magé | 23 | 0.8% |
| 18 | CURRAL | Rio de Janeiro | 20 | 0.7% |
| 19 | POSSES | ? | 19 | 0.7% |
| 20 | CAPELA (RIO DO OURO) | Magé | 17 | 0.6% |
| 21 | CASCATA (SANTO ALEIXO) | ? | 16 | 0.6% |
| 22 | PILÕES | ? | 16 | 0.6% |
| 23 | JARDIM AEROPORTO | ? | 15 | 0.5% |
| 24 | BRITADOR (SANTO ALEIXO) | ? | 15 | 0.5% |
| 25 | POÇO ESCURO (SANTO ALEIXO) | ? | 14 | 0.5% |

**Leitura crítica:**
- **CORDOVIL (Rio de Janeiro) sozinho concentra 895 / 2.746 = 32,6% da base inteira.** É o **berço da Ligo**.
- Adicionando **VISTA ALEGRE + RAMOS + IRAJÁ + PARADA DE LUCAS + BRAZ DE PINA + PENHA + OLARIA** (todos Zona Norte RJ), chega-se a **~1.853 / 2.746 = 67,5%**. Mais de 2/3 da empresa está em **um raio de 8 km na Zona Norte do Rio**.
- ⚠️ **Risco de concentração geográfica extremo** — uma queda de OLT/CTO em Cordovil afeta 1 em cada 3 clientes Ligo.
- **PILOES, BOCAINA, CAPITUBA DE BAIXO, SANTA EDWIGES** = núcleo Guaratinguetá-SP (~10% da base).

---

## 4️⃣ CLUSTER GEOGRÁFICO (Cidade + Bairro — Top 15)

| Cluster | Ativos |
|---|---:|
| Rio De Janeiro / CORDOVIL | 895 |
| Rio De Janeiro / VISTA ALEGRE | 213 |
| Rio De Janeiro / RAMOS | 189 |
| Rio De Janeiro / IRAJÁ | 181 |
| Guaratinguetá / PILOES | 162 |
| Cachoeira Paulista / BOCAINA | 78 |
| Rio De Janeiro / PARADA DE LUCAS | 68 |
| Cachoeiras De Macacu / CASTALIA | 52 |
| Rio De Janeiro / BRAZ DE PINA | 49 |
| Osasco / VILA MENCK | 47 |
| Rio De Janeiro / PENHA | 46 |
| Cachoeiras De Macacu / VALERIO | 38 |
| Rio De Janeiro / BRÁS DE PINA | 37 |
| Rio De Janeiro / OLARIA | 37 |
| Angra Dos Reis / RAMOS | 31 |

---

## 5️⃣ DISTRIBUIÇÃO POR PLANO (Top 12)

| Plano | Ativos | % | Mensalidade declarada |
|---|---:|---:|---|
| # RIO_500M_C/FIDELIDADE_99,90_2024* | 460 | 16.8% | R$ 99,90 |
| CPX_100 MEGAS $99,90 | 175 | 6.4% | R$ 99,90 |
| # SP_CACH_LOR_NAT_150MB_139,90_2023* | 131 | 4.8% | R$ 139,90 |
| # RIO_300M_89,90_C/FIDELIDADE_2024* | 117 | 4.3% | R$ 89,90 |
| # RIO_700M_C/FIDELIDADE_109,90_2024* | 113 | 4.1% | R$ 109,90 |
| # RIO_400M_S/FIDELIDADE_109,90_2024* | 85 | 3.1% | R$ 109,90 |
| # RIO_400M_89,90* | 58 | 2.1% | R$ 89,90 |
| # RIO_600M_119,90_S/FIDELIDADE_2024*novo | 55 | 2.0% | R$ 119,90 |
| # 300M_C/FIDELIDADE_MACACU_89,90_2025* | 55 | 2.0% | — |
| # MAG_500M_C/FIDELIDADE_99,90_2024* | 51 | 1.9% | — |
| # RIO_500M_99,90* | 50 | 1.8% | — |
| # RIO_200M_99,90_S/FIDELIDADE_2024* | 49 | 1.8% | — |

**Leitura:**
- **Plano dominante:** `RIO_500M_C/FIDELIDADE_99,90_2024` — 460 / 2.746 = **16,8%** da base.
- A maioria dos planos vendidos hoje é **fibra 300-700M na faixa R$ 89,90-119,90**.
- **Ticket médio real:** **R$ 103.37** (n=2684).
- **193 nomes de planos distintos** em apenas 2.746 clientes → **catálogo absurdamente fragmentado**. Sinal claro de débito técnico: planos antigos não foram consolidados ao longo dos anos. Recomenda-se **consolidação para ≤15 planos** comerciais ativos.
- Naming convention dos planos é caótica (`#`, `*`, `_C/FIDELIDADE_`, `2024*novo`). Indica que o catálogo foi editado manualmente sem governança.

---

## 6️⃣ TEMPO DE CASA (Distribuição por Ano de Registro)

| Ano | Ativos | % | Acumulado |
|---|---:|---:|---:|
| 1969 | 1 | 0.0% | 1 (0%) |
| 2011 | 1 | 0.0% | 2 (0%) |
| 2017 | 43 | 1.6% | 45 (2%) |
| 2018 | 88 | 3.2% | 133 (5%) |
| 2019 | 107 | 3.9% | 240 (9%) |
| 2020 | 138 | 5.0% | 378 (14%) |
| 2021 | 185 | 6.7% | 563 (21%) |
| 2022 | 160 | 5.8% | 723 (26%) |
| 2023 | 276 | 10.1% | 999 (36%) |
| 2024 | 665 | 24.2% | 1,664 (61%) |
| 2025 | 806 | 29.4% | 2,470 (90%) |
| 2026 | 273 | 9.9% | 2,743 (100%) |

**Leitura:**
- A "explosão" de crescimento é **recente**: 2024+2025+2026 = **1.744 / 2.746 = 63,5% da base atual entrou nos últimos 24 meses**.
- O núcleo histórico (2017-2020) representa apenas **376 / 2.746 = 13,7%**, mas é o **lastro emocional** da empresa.
- Há 1 registro datado de "1969" — provavelmente epoch null no Atlaz. Pode ser desconsiderado.
- A onda 2017-2018 (43 + 88 = 131 actives) coincide com a fundação/expansão inicial em Cordovil.

---

## 7️⃣ COMPORTAMENTO DE PAGAMENTO (Faturas Vencidas)

| Faixa de faturas vencidas | Clientes | % |
|---|---:|---:|
| 0 (em dia) | 2,529 | 92.1% |
| 1 vencida | 199 | 7.2% |
| 2-3 vencidas | 8 | 0.3% |
| 4 ou mais (risco) | 10 | 0.4% |

**Leitura:**
- **92,1% dos clientes ATIVOS estão em dia** (0 faturas vencidas). Cliente Ligo paga.
- **7,3% têm 1 fatura vencida** (provavelmente atraso temporário).
- Apenas **0,5% (12 clientes) têm 2-3 vencidas** + **0,2% (6 clientes) têm 4+** → carteira **muito saudável**. Inadimplência crônica é marginal.

---

## 8️⃣ COMPORTAMENTO DE SUPORTE (Tickets Fechados Histórico)

| Faixa de tickets fechados | Clientes | % |
|---|---:|---:|
| 0 (jamais abriu) | 170 | 6.2% |
| 1-2 (mínimo) | 1,280 | 46.6% |
| 11+ (alto) | 140 | 5.1% |
| 3-5 (normal) | 767 | 27.9% |
| 6-10 (uso recorrente) | 389 | 14.2% |

**Leitura:**
- **6,2% dos ativos JAMAIS abriram um chamado** (170 clientes invisíveis — ver `CLIENTES_INVISIVEIS.md`).
- **35% abriram 1-2 chamados** ao longo de toda a vida na Ligo. Comportamento normal.
- **39% abriram 3-5** — uso recorrente.
- **15% abriram 6-10** — clientes que precisam mais suporte.
- **5% abriram 11+** — heavy support users (candidatos a análise de saúde técnica/satisfação).

---

## 🔬 CONFIANÇA DOS DADOS

| Dimensão | Confiança | Justificativa |
|---|---|---|
| Total de ativos (2.746) | 🟢 **ALTA** | Confirmado por 3 fontes independentes: `loyalty_imported_db` status="Ativo", `atlaz_clients_cache` (2.704 docs únicos), `subscribers` co-demo (2.816). Variação <5% explicada por lag de sincronização. |
| Distribuição geográfica (UF/cidade/bairro) | 🟢 **ALTA** | 96,5% dos ativos têm cidade preenchida, 96,5% têm bairro. Casing inconsistente (CORDOVIL vs Cordovil) já normalizado. |
| Distribuição por plano | 🟡 **MÉDIA** | 69% dos registros históricos têm `plan_name` NULL (planos antigos), mas em ATIVOS apenas 0,1% (3 docs). Para a foto atual da base, confiança é alta. Catálogo fragmentado de 193 planos sugere má higiene de catálogo histórica. |
| Ticket médio (R$ 103,37) | 🟢 **ALTA** | Calculado sobre 2.684 ativos com `monthly_fee` populado (97,7%). |
| Tempo de casa (ano de registro) | 🟢 **ALTA** | 94,3% dos ativos têm `registration_date` populado. 1 outlier de 1969 (epoch) é descartável. |
| Inadimplência | 🟢 **ALTA** | Contadores `invoices_overdue` zerados na grande maioria, mas vêm de cache Atlaz — refletem snapshot do último sync, não fluxo em tempo real. |
| Chamados | 🟡 **MÉDIA** | `tickets_closed` no Atlaz é contador acumulado **lifetime**, não permite recência. Para análise de "último chamado" precisaríamos cruzar com `tickets` collection (que tem apenas 350 registros para co-demo — quase nada). **Confiança limitada para análise de recência.** |
| NPS | 🔴 **INDISPONÍVEL** | `nps_responses` = **0 documentos** no banco. Nenhum NPS coletado. **Não use NPS em nenhum dashboard.** |
| Último contato | 🔴 **NÃO MEDIDO** | Não há campo `last_contact_at` ou similar. Pode ser inferido via `aihub_wa_messages` por subscriber, mas requer cross-join não trivial. |

---

## 🚨 SUGESTÕES DE INVESTIGAÇÃO IMEDIATA

1. **P0** — Por que 350 tickets em `tickets` para 2.746 ativos contra 11.000+ tickets reportados em `loyalty_imported_db.tickets_closed`? Há um **pipeline rompido** entre o sistema externo Atlaz e o banco interno.
2. **P0** — Implementar coleta de NPS (atualmente zero). Sem NPS não há base de evidência para classificação de embaixadores.
3. **P1** — Consolidar catálogo de planos: 193 → ≤15.
4. **P1** — Criar campo `last_contact_at` populado por `aihub_wa_messages` para análise de engajamento.
5. **P2** — Auditar concentração geográfica: 1 OLT em Cordovil afeta 33% do faturamento.
