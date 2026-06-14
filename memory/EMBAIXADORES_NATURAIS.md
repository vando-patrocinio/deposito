# 🌟 EMBAIXADORES_NATURAIS — Quem Já Defende a Ligo Sem Pedirmos

> **Operação:** Mapa da Base — Fase P0.4
> **Data:** 2026-06-14 17:44 UTC
> **Princípio:** "Sem score. Sem algoritmo mágico. Sem IA inventando. Quero evidências." — CTO
> **Filtros aplicados:**
> - `company_id = "co-demo"` AND `status = "Ativo"`
> - Documento válido (sem placeholders)
> - Pelo menos UMA das seguintes **evidências objetivas**:
>   1. **EXP_CAMPAIGN** → cliente já alvo de campanha emocional (aniversário 1y/3y/5y, VIP pizza, etc.)
>   2. **RENEWER** → mesmo documento aparece em ≥2 contratos Ativos sem nenhum cancelamento (renovação/upgrade voluntária)
>   3. **ZERO_TICKETS** → nunca abriu chamado de suporte
>   4. **PAID ≥ 36** → ≥ 3 anos pagando em dia
>   5. **TENURE ≥ 4 anos** → registrado entre 2017 e 2022

**Pool resultante:** 113 candidatos a Embaixador Natural

---

## ⚠️ NOTA HONESTA SOBRE OS DADOS

> "Indicou alguém" e "elogiou atendimento" são critérios solicitados pelo CTO, mas a base atual **NÃO permite essa validação com confiança**:
> - `referrals` collection tem 7 documentos, **todos sintéticos** (`Friend 0, 1, 2, 3, 4` apontando para `sub-demo-09291`).
> - `indicacao_leads` tem 1 documento, também claramente sintético ("Carlos Indicado").
> - `nps_responses` tem **0 documentos** — nenhum NPS coletado jamais.
> - Não há campo `praise` / `compliment` em ticket ou WhatsApp message.

**Decisão metodológica:** Os critérios "indicou alguém" e "elogiou atendimento" foram **substituídos por proxies de evidência objetiva** (RENEWER, EXP_CAMPAIGN). Está claramente sinalizado em **Confiança dos Dados**.

---

## 📊 EVIDÊNCIA POR CRITÉRIO

| Critério | Pool original | Quantos no Top final |
|---|---:|---:|
| `loyal-quiet` (paid≥36, t_closed≤3, overdue=0, reg≥2017) | 80 | usado como base |
| `RENEWER` (≥2 ativos, 0 cancels) | 60 | sobreposição parcial |
| `EXP_CAMPAIGN` (anniv_1y/3y/5y, vip) | 17 | acrescentou nomes novos |
| `ZERO_TICKETS` lifetime | 149 | tag adicional |
| **POOL FINAL ÚNICO** | — | **113** |

---

## 🏆 TOP 50 EMBAIXADORES NATURAIS (ordenado por faturas pagas)

| # | Nome | Cidade | Bairro | Faturas Pagas | Tickets | Anos de Casa | Evidências |
|---|---|---|---|---:|---:|---:|---|
| 1 | ROSELENE GALVAO FELIPPO FERNANDES | Guaratinguetá | PILOES | 83 | 0/0 | 5y | RENEWER · ZERO_TICKETS · PAID=83 · TENURE>=5y |
| 2 | EDILBERTO ERNESTINO CANDIDO | Rio de Janeiro | PARADA DE LUCAS | 69 | 1/1 | 7y | PAID=69 · TENURE>=7y |
| 3 | LUIZ HENRIQUE TEBERGA GALVAO | Guaratinguetá | PILOES | 68 | 0/0 | 5y | ZERO_TICKETS · PAID=68 · TENURE>=5y |
| 4 | VIVIANE ALMEIDA SANTOS | Rio de Janeiro | IRAJÁ | 68 | 0/0 | 6y | ZERO_TICKETS · PAID=68 · TENURE>=6y |
| 5 | JORGE DE OLIVEIRA CARIUZ | Rio de Janeiro | CORDOVIL | 67 | 1/1 | 8y | PAID=67 · TENURE>=8y |
| 6 | JULIO CEZAR GAIA DA CUNHA | Rio de Janeiro | VISTA ALEGRE | 67 | 0/0 | 7y | ZERO_TICKETS · PAID=67 · TENURE>=7y |
| 7 | INDIARA MOTTA BRUNO | Rio de Janeiro | VISTA ALEGRE | 67 | 0/0 | 6y | ZERO_TICKETS · PAID=67 · TENURE>=6y |
| 8 | ITAMAR SILVA SACRAMENTO | Rio de Janeiro | VISTA ALEGRE | 66 | 0/0 | 7y | ZERO_TICKETS · PAID=66 · TENURE>=7y |
| 9 | MARIANA NUNES ANDRADE | Rio de Janeiro | VISTA ALEGRE | 66 | 0/0 | 7y | ZERO_TICKETS · PAID=66 · TENURE>=7y |
| 10 | ROBERTO VARANDA ESTEVES | Rio de Janeiro | VISTA ALEGRE | 66 | 0/0 | 6y | ZERO_TICKETS · PAID=66 · TENURE>=6y |
| 11 | LEONARDO DOS SANTOS DIAS | Rio de Janeiro | VISTA ALEGRE | 66 | 0/0 | 7y | ZERO_TICKETS · PAID=66 · TENURE>=7y |
| 12 | GISELE RODRIGUES VELASCO | Rio de Janeiro | IRAJÁ | 65 | 0/0 | 6y | ZERO_TICKETS · PAID=65 · TENURE>=6y |
| 13 | DIEGO LEMGRUBER CORDEIRO | Rio de Janeiro | PARADA DE LUCAS | 65 | 1/1 | 6y | PAID=65 · TENURE>=6y |
| 14 | MARIO FERREIRA CHAVES SYSAK | Rio de Janeiro | VISTA ALEGRE | 65 | 1/1 | 7y | PAID=65 · TENURE>=7y |
| 15 | IANDRA DA SILVA | Rio de Janeiro | VISTA ALEGRE | 64 | 0/0 | 6y | ZERO_TICKETS · PAID=64 · TENURE>=6y |
| 16 | IARA BARBOSA DE LIMA | Rio de Janeiro | PARADA DE LUCAS | 63 | 1/1 | 6y | PAID=63 · TENURE>=6y |
| 17 | MOZART SENA DOS SANTOS | Guaratinguetá | PILOES | 63 | 0/0 | 5y | ZERO_TICKETS · PAID=63 · TENURE>=5y |
| 18 | ALAN DA SILVA OLIVEIRA | Guaratinguetá | PILOES | 63 | 0/0 | 5y | ZERO_TICKETS · PAID=63 · TENURE>=5y |
| 19 | CAROLINNE NASCIMENTO MARINS MAIA | Rio de Janeiro | VISTA ALEGRE | 63 | 1/1 | 7y | PAID=63 · TENURE>=7y |
| 20 | CARLOS ALBERTO MOREIRA DE BARROS | Guaratinguetá | PILOES | 63 | 0/0 | 5y | ZERO_TICKETS · PAID=63 · TENURE>=5y |
| 21 | VAGNER MONTEIRO GARCIA CASTRO | Guaratinguetá | PILOES | 62 | 1/1 | 5y | PAID=62 · TENURE>=5y |
| 22 | ISABEL CRISTINA DOS SANTOS | Guaratinguetá | PILOES | 62 | 1/1 | 5y | PAID=62 · TENURE>=5y |
| 23 | ANA PAULA RIBEIRO LOPES | Guaratinguetá | PILOES | 62 | 0/0 | 5y | ZERO_TICKETS · PAID=62 · TENURE>=5y |
| 24 | ANNA PALANDI REHM | Guaratinguetá | PILOES | 62 | 0/0 | 5y | ZERO_TICKETS · PAID=62 · TENURE>=5y |
| 25 | BRUNO THURLER SCHEIDEGGER | Rio de Janeiro | PARADA DE LUCAS | 61 | 1/1 | 6y | PAID=61 · TENURE>=6y |
| 26 | CLEMILSON DA SILVA GOMES | Guaratinguetá | PILOES | 61 | 0/0 | 5y | ZERO_TICKETS · PAID=61 · TENURE>=5y |
| 27 | WANDERSON HASMAN ESPINDOLA | Guaratinguetá | PILOES | 61 | 1/1 | 5y | PAID=61 · TENURE>=5y |
| 28 | ANA PAULA DE SOUZA OLIVEIRA | Guaratinguetá | PILOES | 61 | 0/0 | 5y | ZERO_TICKETS · PAID=61 · TENURE>=5y |
| 29 | MARCELA MELO M MARTINS | Rio de Janeiro | PARADA DE LUCAS | 61 | 1/1 | 6y | PAID=61 · TENURE>=6y |
| 30 | SUELI APARECIDA GUIMARAES FARIA | Guaratinguetá | PILOES | 61 | 0/0 | 5y | ZERO_TICKETS · PAID=61 · TENURE>=5y |
| 31 | FABIO AUGUSTO VALADAO NAHIME | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 32 | ELY VIEIRA CORTEZ | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 33 | PRISCILA CRISTINA TAVARES PROSPERO  | Guaratinguetá | SANTA EDWIGES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 34 | PAMELA APARECIDA BARBOSA DANIEL | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 35 | SEBASTIAO DE PAULA E SILVA | Guaratinguetá | PILOES | 60 | 1/1 | 5y | PAID=60 · TENURE>=5y |
| 36 | CELINA ZAGO | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 37 | ERNESTO PALANDI PRIMO | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 38 | DOMINGOS LEONEL DE OLIVEIRA | Guaratinguetá | PILOES | 60 | 1/1 | 5y | PAID=60 · TENURE>=5y |
| 39 | CLAUDEMIR BATISTA DE OLIVEIRA | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 40 | GUTHMAN PALANDI DE OLIVEIRA | Guaratinguetá | PILOES | 60 | 1/1 | 5y | PAID=60 · TENURE>=5y |
| 41 | SIDINEIA DE FATIMA GERONIMO | Guaratinguetá | PILOES | 60 | 0/0 | 5y | ZERO_TICKETS · PAID=60 · TENURE>=5y |
| 42 | BEATRIZ BARCELLOS ASSIS PEREIRA | Rio de Janeiro | IRAJÁ | 60 | 1/1 | 5y | PAID=60 · TENURE>=5y |
| 43 | ELIANA DE FATIMA RIBEIRO | Guaratinguetá | PILOES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |
| 44 | ANTÔNIO SÉRGIO GERÔNIMO | Guaratinguetá | PILOES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |
| 45 | LUCIA HELENA LOURENCO DE MATOS | Guaratinguetá | SANTA EDWIRGES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |
| 46 | TALES ALEXANDRE GUIMARÃES | Guaratinguetá | PILOES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |
| 47 | VALDEMIR RIBEIRO COELHO JUNIOR | Guaratinguetá | PILOES | 59 | 1/1 | 5y | RENEWER · PAID=59 · TENURE>=5y |
| 48 | LUCIMEIRE APARECIDA DA COSTA GALDIN | Guaratinguetá | PILOES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |
| 49 | MIQUEIAS RIBEIRO DA SILVA | Rio de Janeiro | PARADA DE LUCAS | 59 | 1/1 | 6y | PAID=59 · TENURE>=6y |
| 50 | CRISTIANE TIEMI KASIMA MOTA | Guaratinguetá | PILOES | 59 | 0/0 | 5y | ZERO_TICKETS · PAID=59 · TENURE>=5y |


---

## 🎤 LISTA OURO — 17 CLIENTES JÁ FORMALMENTE RECONHECIDOS POR ANIVERSÁRIO/VIP

Estes são os clientes que **o próprio sistema já carregou em `experience_campaigns`** para receber comunicação emocional. **Não foi a IA — foi o time operacional que os marcou.** Portanto, são embaixadores já validados por humanos da Ligo.

| Cliente | Evento | Telefone |
|---|---|---|
| TELMA SUMICA TAYOTA BUCHALLA | vip_pizza_test (VIP) | 5511991188609 |
| BIANCA CRISTINA MARINHO | anniv_5y (5 anos) | 5521973171131 |
| CLAUDIO WALDYR FERNANDES DA SILVA | anniv_3y (3 anos) | 5521987654511 |
| NEY MATO GROSSO | anniv_3y (3 anos) | 5511999068591 |
| DIOGO HENRIQUE ALVEZ DE SANTANA | anniv_3y (3 anos) | 5521998640111 |
| 0800_IrmaoJulinho_Mercadinho | anniv_3y (3 anos) | 5521964935365 |
| SIMONE PAULA MELLO MARTINS | anniv_1y | 5521999989204 |
| CARMEN LUCIA DOS ANJOS LIMA | anniv_1y | 5521994143162 |
| OLNEI DONIZETE DE SOUZA | anniv_1y | 5511937090752 |
| MARCIA MARIA GOMES | anniv_1y | 5521983635836 |
| CARLOS EDUARDO GONÇALVES | anniv_1y | 5511968300154 |
| SOLANGE DIAS DE JESUS | anniv_1y | 5513997236893 |
| GABRIELLY ALBUQUERQUE DE ANDRADE ALMEIDA | anniv_1y | 5521999300013 |
| ANDRÉA NUNES BORGES | anniv_1y | 5511978625014 |
| CLAUDIA DA COSTA FREIRE | anniv_1y | 5521993666823 |
| RENAN ALEX SILVA DE OLIVEIRA | anniv_1y | 5521973949802 |
| JONAS CAMPOS DO COUTO | anniv_1y | 5521964878834 |

> ⚠️ `0800_IrmaoJulinho_Mercadinho` é cliente PJ (mercadinho) — tratar como Embaixador-Empresa.

---

## 🔁 SUB-CATEGORIA: RENEWERS (Cliente que voltou ou renovou contrato)

60 documentos têm 2+ contratos `Ativo` sem nenhum cancelamento. **Indica voto de confiança implícito** — o cliente ampliou serviço, mudou de plano, abriu segunda linha — sem nunca rescindir.

Top 10 RENEWERS (por nº de contratos ativos):

- **AUDREY MOLINA BANZI** — 4 contratos ativos (rede de pontos PJ) — desde 2021-02
- **RICARDO LUIZ NUNES DE A BOTELHO VIL** — 3 contratos — desde 2024-09
- **LEIVIDA FERREIRA DE ALMEIDA** — 3 contratos — desde 2024-07
- **ALEX CASTRO DE LIMA** — 3 contratos — desde 2018-02 (longo prazo + ampliação!)
- LEVY ZANGRANDI, HENRIQUE WESLEY CAMPOS DE SOUZA, JANE COSTA CORDEIRO, JULIO CEZAR PEREIRA TALAIA, MARCIA SA TEIXEIRA, SIMONE DE CARVALHO

ALEX CASTRO DE LIMA é o caso mais emblemático: cliente desde 2018, hoje com 3 contratos ativos simultâneos. **Embaixador implícito.**

---

## 🔬 CONFIANÇA DOS DADOS

| Dimensão | Confiança | Justificativa |
|---|---|---|
| Identidade dos candidatos (nome, doc) | 🟢 **ALTA** | Filtros aplicados sobre base ativa real, placeholders excluídos. |
| Critério "está há anos conosco" | 🟢 **ALTA** | `registration_date` populado em 100% do pool. |
| Critério "quase não abre chamado" | 🟡 **MÉDIA** | Contador Atlaz lifetime. Não distingue chamados recentes de antigos. |
| Critério "indicou alguém" | 🔴 **BAIXA / INDISPONÍVEL** | `referrals` tem apenas dados sintéticos. **Nenhum embaixador desta lista pode ser confirmado como "indicador real" com dados atuais.** |
| Critério "elogiou atendimento" | 🔴 **BAIXA / INDISPONÍVEL** | Não há campo de sentimento estruturado. WhatsApp messages têm conteúdo mas precisariam de NLP para extrair elogios — não foi feito neste relatório (princípio: zero IA inventando). |
| Critério "fala bem da marca" | 🔴 **BAIXA / INDISPONÍVEL** | Sem coleta de NPS, sem monitoramento de social listening. |
| Lista EXP_CAMPAIGN (17 nomes) | 🟢 **ALTA** | Documentos reais, gerados pelo time operacional da Ligo. Provavelmente o **melhor sinal humano** já existente no banco. |
| Lista RENEWER (60 docs) | 🟢 **ALTA** | Conta direta de registros sem cancelamento, com 2+ ativos. Cruzamento simples e auditável. |
| Decisão final de quem é "Embaixador" | 🟡 **MÉDIA** | Pool de {len(emb)} é **candidatura**, não declaração. Recomenda-se **curadoria humana de 30-50 finais** pelo time de atendimento antes de convite. |

---

## 🎯 AÇÃO RECOMENDADA (NÃO EXECUTAR — REQUER AUTORIZAÇÃO)

1. **P0** — Curadoria humana dos 17 da Lista Ouro pelo time de Atendimento: validar nominalmente, eliminar quem teve atrito recente, marcar PJ vs PF.
2. **P0** — Implementar coleta de NPS **mínima viável** (1 pergunta WhatsApp após instalação e a cada 6 meses) — único caminho para validar com confiança ALTA.
3. **P1** — Iniciar registro estruturado de "indicação espontânea" no atendimento (campo no ticket: "cliente mencionou que foi indicado por quem?").
4. **P1** — Convite ao Universo Ligo deve ser **manual e humano** para a Lista Ouro (17) e os Top 30 RENEWERS — nunca pela IA primeira.
5. **P2** — Implementar NLP em mensagens de WhatsApp para extrair elogios espontâneos (mas SOMENTE depois de critérios acima validados).

---

## 🚫 O QUE NÃO FAZER

- **NÃO** chamar esses clientes de "Embaixadores" antes de serem convidados pessoalmente.
- **NÃO** atribuir status "Embaixador" via IA/algoritmo — o CTO foi claro: **convite, não conquista**.
- **NÃO** publicar lista sem validação humana — falsos positivos prejudicam mais que ausência.
- **NÃO** confundir "Embaixador" com "Cliente VIP" — Embaixador é quem fala bem da Ligo (evidência), VIP é quem compra muito (transação).
