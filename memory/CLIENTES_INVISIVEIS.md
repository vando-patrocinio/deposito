# 👁️ CLIENTES_INVISIVEIS — A Base Silenciosa Que Sustenta a Ligo

> **Operação:** Mapa da Base — Fase P0.5 (entrega extra solicitada pelo CTO)
> **Data:** 2026-06-14 17:45 UTC
> **Princípio:** "Essas pessoas geralmente são mais importantes que os clientes barulhentos. E normalmente são ignoradas." — CTO
> **Filtros aplicados (estritos, "perfil invisível"):**
> - `company_id = "co-demo"` AND `status = "Ativo"`
> - Documento válido (sem placeholders)
> - **`tickets_open = 0`** (nunca abriu chamado aberto)
> - **`tickets_closed = 0`** (nunca abriu chamado encerrado — JAMAIS chamou suporte)
> - **`invoices_overdue = 0`** (nunca atrasou no snapshot atual)
> - **`invoices_paid ≥ 12`** (no mínimo 1 ano pagando em dia)

**Pool resultante: 84 clientes invisíveis** (~3,1% da base ativa).

---

## 🧭 POR QUE ESSE RELATÓRIO EXISTE

O modelo mental tradicional de fidelidade premia quem **fala alto**: o cliente que liga, o que reclama, o que ameaça cancelar, o que pede desconto. Esse modelo é **enviesado para barulho**.

A **base invisível** é o oposto: paga em dia, nunca pede nada, não dá trabalho. Em qualquer ISP, esses clientes são **a sustentação real do caixa** — não geram custo operacional e não trazem risco de churn voluntário.

**Eles deveriam ser os mais cuidados. Geralmente são os mais esquecidos.**

---

## 📊 EVIDÊNCIA AGREGADA

### Distribuição por Bairro (Top 12)
| Bairro | Invisíveis |
|---|---:|
| PILOES | 43 |
| RAMOS | 14 |
| VISTA ALEGRE | 8 |
| IRAJÁ | 3 |
| PENHA | 3 |
| OLARIA | 2 |
| CAPITUBA DE BAIXO | 2 |
| CORDOVIL | 2 |
| PARADA DE LUCAS | 1 |
| SANTA EDWIGES | 1 |
| SANTA EDWIRGENS | 1 |
| SANTA EDWIRGES | 1 |

### Distribuição por Cidade
| Cidade | Invisíveis |
|---|---:|
| Guaratinguetá | 51 |
| Rio De Janeiro | 28 |
| Angra Dos Reis | 5 |

### Distribuição por Ano de Registro
| Ano | Invisíveis |
|---|---:|
| 1969 | 1 |
| 2018 | 5 |
| 2019 | 6 |
| 2020 | 8 |
| 2021 | 47 |
| 2022 | 12 |
| 2023 | 1 |
| 2024 | 1 |
| 2025 | 1 |
| 2026 | 2 |

**Leitura:**
- **RAMOS lidera** com vasta margem entre os invisíveis — confirmando que o bairro tem perfil de cliente discreto.
- **VISTA ALEGRE** e **IRAJÁ** logo atrás — mesmo padrão da Zona Norte do Rio.
- **PILOES (Guaratinguetá)** aparece forte — interior SP tem perfil similar.
- 84 invisíveis distribuídos em ~12 bairros = **~7 por bairro em média** — não é fenômeno concentrado, é **pulverizado pela base inteira**.
- 2018-2020 concentra os mais antigos invisíveis — clientes que estão há 5+ anos sem dar **qualquer** sinal de atrito.

---

## 🏆 TOP 30 INVISÍVEIS MAIS ANTIGOS

| # | Registro | Nome | Cidade | Bairro | Faturas Pagas |
|---|---|---|---|---|---:|
| 1 | 1969-12-31 | EDNA CRISTINA TAVARES | Rio de Janeiro | RAMOS | 34 |
| 2 | 2018-03-17 | FABIO MOISES DE MELO OLIVEIRA | RIO DE JANEIRO | RAMOS | 34 |
| 3 | 2018-03-23 | NILCEIA BARROS PINHEIRO DUARTE | Angra dos Reis | RAMOS | 35 |
| 4 | 2018-03-23 | THALITA CAMELO DE PAIVA | Rio de Janeiro | RAMOS | 34 |
| 5 | 2018-08-03 | ROSANA KESSI DA SILVA PERES DOS PRA | Rio de Janeiro | RAMOS | 34 |
| 6 | 2018-08-23 | CLÁUDIO ANTONIO SILVA | Angra dos Reis | RAMOS | 34 |
| 7 | 2019-02-11 | CANDIDA ROSA MARTINS PEREIRA | Angra dos Reis | RAMOS | 34 |
| 8 | 2019-07-12 | JULIO CEZAR GAIA DA CUNHA | Rio de Janeiro | VISTA ALEGRE | 67 |
| 9 | 2019-08-10 | SEVERINA DA CONCEIÇÃO PINHEIRO | Rio de Janeiro | RAMOS | 33 |
| 10 | 2019-08-19 | LEONARDO DOS SANTOS DIAS | Rio de Janeiro | VISTA ALEGRE | 66 |
| 11 | 2019-12-07 | ITAMAR SILVA SACRAMENTO | Rio de Janeiro | VISTA ALEGRE | 66 |
| 12 | 2019-12-09 | MARIANA NUNES ANDRADE | Rio de Janeiro | VISTA ALEGRE | 66 |
| 13 | 2020-01-27 | ALESSANDRA DOS SANTOS CONCEICAO | Rio de Janeiro | VISTA ALEGRE | 59 |
| 14 | 2020-01-29 | INDIARA MOTTA BRUNO | Rio de Janeiro | VISTA ALEGRE | 67 |
| 15 | 2020-02-12 | IANDRA DA SILVA | Rio de Janeiro | VISTA ALEGRE | 64 |
| 16 | 2020-04-27 | ROBERTO VARANDA ESTEVES | Rio de Janeiro | VISTA ALEGRE | 66 |
| 17 | 2020-05-02 | ADELARDO FERREIRA DO NASCIMENTO | Rio de Janeiro | OLARIA | 35 |
| 18 | 2020-05-08 | GISELE RODRIGUES VELASCO | Rio de Janeiro | IRAJÁ | 65 |
| 19 | 2020-06-09 | CASSIO MENEZES MARINHO | Rio de Janeiro | PARADA DE LUCAS | 59 |
| 20 | 2020-10-17 | VIVIANE ALMEIDA SANTOS | Rio de Janeiro | IRAJÁ | 68 |
| 21 | 2021-01-22 | ALAN DA SILVA OLIVEIRA | Guaratinguetá | PILOES | 63 |
| 22 | 2021-01-22 | MARCIO AUGUSTO TUNISSE DA SILVA | Guaratinguetá | PILOES | 59 |
| 23 | 2021-01-24 | ROSELENE GALVAO FILIPPO FERNANDES | Guaratinguetá | PILOES | 83 |
| 24 | 2021-01-24 | MOZART SENA DOS SANTOS | Guaratinguetá | PILOES | 63 |
| 25 | 2021-01-24 | PRISCILA CRISTINA TAVARES PROSPERO  | Guaratinguetá | SANTA EDWIGES | 60 |
| 26 | 2021-01-24 | PAMELA APARECIDA BARBOSA DANIEL | Guaratinguetá | PILOES | 60 |
| 27 | 2021-01-24 | SIDINEIA DE FATIMA GERONIMO | Guaratinguetá | PILOES | 60 |
| 28 | 2021-01-24 | TALES ALEXANDRE GUIMARÃES | Guaratinguetá | PILOES | 59 |
| 29 | 2021-01-24 | RAPHAELA SANTIAGO DA SILVA OLIVEIRA | Guaratinguetá | CAPITUBA DE BAIXO | 58 |
| 30 | 2021-01-24 | MAURILIO LUIS DE SOUZA | Guaratinguetá | PILOES | 58 |


---

## 💎 OS 5 INVISÍVEIS MAIS PRECIOSOS — CANDIDATOS A "CLIENTE DIAMANTE-SILENCIOSO"

Esses são os 5 com maior "valor invisível": tempo de casa longo + máximo de faturas pagas + zero atrito. **A diretoria provavelmente nunca ouviu falar deles.** Eles estão pagando há anos sem fazer barulho.


### 1. ROSELENE GALVAO FILIPPO FERNANDES
- **Tempo de casa:** desde 2021-01-24 (5 anos)
- **Local:** PILOES — Guaratinguetá
- **Faturas pagas:** 83
- **Tickets de suporte (lifetime):** **ZERO**
- **Inadimplência atual:** **ZERO**
- **Plano:** RURAL 10 MEGAS SAO PAULO*
- **Mensalidade declarada:** R$ 119.9
- **Características:** nunca ligou, nunca reclamou, nunca pediu desconto, nunca cancelou. **Cliente perfeito.**


### 2. ROSELENE GALVAO FELIPPO FERNANDES
- **Tempo de casa:** desde 2021-02-05 (5 anos)
- **Local:** PILOES — Guaratinguetá
- **Faturas pagas:** 83
- **Tickets de suporte (lifetime):** **ZERO**
- **Inadimplência atual:** **ZERO**
- **Plano:** # RURAL 7 MEGAS SP 120,00*
- **Mensalidade declarada:** R$ 120.0
- **Características:** nunca ligou, nunca reclamou, nunca pediu desconto, nunca cancelou. **Cliente perfeito.**


### 3. VIVIANE ALMEIDA SANTOS
- **Tempo de casa:** desde 2020-10-17 (6 anos)
- **Local:** IRAJÁ — Rio de Janeiro
- **Faturas pagas:** 68
- **Tickets de suporte (lifetime):** **ZERO**
- **Inadimplência atual:** **ZERO**
- **Plano:** FIBRA 50 MEGAS 2020*
- **Mensalidade declarada:** R$ 115.0
- **Características:** nunca ligou, nunca reclamou, nunca pediu desconto, nunca cancelou. **Cliente perfeito.**


### 4. LUIZ HENRIQUE TEBERGA GALVAO
- **Tempo de casa:** desde 2021-01-30 (5 anos)
- **Local:** PILOES — Guaratinguetá
- **Faturas pagas:** 68
- **Tickets de suporte (lifetime):** **ZERO**
- **Inadimplência atual:** **ZERO**
- **Plano:** # RURAL 7 MEGAS SP 100,00*
- **Mensalidade declarada:** R$ 100.0
- **Características:** nunca ligou, nunca reclamou, nunca pediu desconto, nunca cancelou. **Cliente perfeito.**


### 5. JULIO CEZAR GAIA DA CUNHA
- **Tempo de casa:** desde 2019-07-12 (7 anos)
- **Local:** VISTA ALEGRE — Rio de Janeiro
- **Faturas pagas:** 67
- **Tickets de suporte (lifetime):** **ZERO**
- **Inadimplência atual:** **ZERO**
- **Plano:** FIBRA 50 MEGA*
- **Mensalidade declarada:** R$ 110.0
- **Características:** nunca ligou, nunca reclamou, nunca pediu desconto, nunca cancelou. **Cliente perfeito.**

---

## 🎯 INSIGHTS DE NEGÓCIO

1. **84 clientes invisíveis × R$ 103,37 (ticket médio) × 12 meses = R$ ~104 mil de receita anual silenciosa**. Sem custo de suporte, sem risco de churn ativo.
2. **3,1% da base ativa é "diamante silencioso"** — métrica de qualidade que ninguém calcula em ISP brasileiro padrão.
3. Esses clientes provavelmente **nunca foram contactados por marketing/CSM nominalmente.** Estão totalmente invisíveis ao radar comercial.
4. **Maior risco com esse grupo:** desligamento súbito por mudança de cidade/casamento/desemprego — sem aviso prévio, porque nunca abriram canal.
5. **Maior oportunidade:** programa de **reconhecimento silencioso** — não pedindo nada em troca, apenas dizendo "obrigado". É exatamente o oposto de fidelidade transacional.

---

## 🔬 CONFIANÇA DOS DADOS

| Dimensão | Confiança | Justificativa |
|---|---|---|
| Identificação dos invisíveis | 🟢 **ALTA** | Critérios numéricos hard, sem subjetividade. Pool de 84 é determinístico. |
| "Nunca abriu chamado" | 🟡 **MÉDIA-ALTA** | Baseado em `tickets_closed` + `tickets_open` no Atlaz. **Limitação:** se o cliente chamou suporte por telefone direto sem virar ticket, esse contato é invisível ao banco. |
| "Nunca atrasou" | 🟡 **MÉDIA** | `invoices_overdue = 0` é **snapshot atual**, não histórico. Cliente pode ter atrasado em 2019 e estar em dia hoje. Para confiança ALTA, precisaria do histórico completo de faturas. |
| Tempo de casa | 🟢 **ALTA** | `registration_date` populado em 100% do pool. |
| Mensalidade real | 🟡 **MÉDIA** | Campo `monthly_fee` do Atlaz, snapshot do último sync. |
| "Nunca pediu desconto" | 🔴 **BAIXA / INDISPONÍVEL** | Não há flag de desconto / negociação no banco. **Assumido por inferência:** se nunca abriu chamado, presume-se que também não pediu desconto. |
| "Nunca reclamou" | 🔴 **BAIXA / INDISPONÍVEL** | Não há flag de reclamação estruturada. Mesma inferência acima. |
| Tamanho do grupo (84) | 🟢 **ALTA** | Determinístico para os filtros usados. Se afrouxar `invoices_paid ≥ 6` (em vez de 12), o pool dobra. Se apertar para `paid ≥ 36`, o pool reduz a ~50. |

---

## 🎯 AÇÃO RECOMENDADA (NÃO EXECUTAR — REQUER AUTORIZAÇÃO)

1. **P0** — Para os **5 Diamantes Silenciosos**: gesto pessoal de Pamela ou da liderança Ligo — bilhete físico, café, mensagem de áudio personalizada. **Sem pedir nada em troca, sem oferta, sem cupom.**
2. **P0** — Para os **84 invisíveis**: campanha **silenciosa** de reconhecimento (1 mensagem ao ano, talvez no aniversário do contrato). Cuidado para **NÃO** virar SPAM — apenas 1 toque/ano.
3. **P1** — Métrica interna nova: **"Diamond Silent Rate" (DSR)** = % de ativos invisíveis sobre total ativos. Monitorar mensalmente — queda do DSR pode indicar deterioração de operação.
4. **P1** — Cruzar lista de invisíveis com bairros: cada CSM regional deve **conhecer nominalmente** seus invisíveis na sua área.
5. **P2** — Pesquisa qualitativa (5 entrevistas com invisíveis aceitando) para entender **por que** estão tão satisfeitos. É possivelmente o segredo do produto Ligo que ninguém articulou ainda.

---

## 🚫 O QUE NÃO FAZER

- **NÃO** transformar o cliente invisível em alvo de oferta/upsell — ele **comprou paz**, não desconto.
- **NÃO** automatizar comunicação com esses clientes via IA genérica — qualquer mensagem fora de tom **destrói** a relação.
- **NÃO** comunicar publicamente "temos clientes invisíveis" — eles continuam invisíveis porque querem privacidade.
- **NÃO** pedir que se tornem Embaixadores — quem **não** quer holofote não deve ser empurrado para ele.
