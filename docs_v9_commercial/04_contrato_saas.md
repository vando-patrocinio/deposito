# Contrato Base de Licenciamento SaaS — SmartProv

> **STATUS:** DRAFT V9.4 — **sujeito à revisão jurídica.**
> Modelo-base para piloto controlado de 30 (trinta) dias com provedor parceiro.

---

## CONTRATO DE LICENCIAMENTO DE USO DE SOFTWARE COMO SERVIÇO (SaaS) — PILOTO CONTROLADO

Pelo presente instrumento particular, de um lado:

**CONTRATADA:** SmartProv (qualificação completa a inserir).
**CONTRATANTE:** [Razão Social do Provedor], CNPJ [•], com sede em [•] (qualificação completa a inserir).

Têm entre si certo e ajustado o presente contrato, mediante as cláusulas e condições a seguir.

---

### Cláusula 1ª — Objeto

1.1. A CONTRATADA concede à CONTRATANTE, em caráter **não exclusivo e intransferível**, o direito de uso, em modalidade SaaS (Software as a Service), da plataforma **SmartProv**, composta pelos módulos:

- **Smart Field Ops** — gestão e fechamento de ordens de serviço em campo.
- **Action→Cash** — pipeline operacional de reconciliação financeira e atribuição de **receita atribuída** à esteira operacional.
- **AI Center** — orquestrador de agentes operacionais.
- **Observability Twin** — camada de observabilidade técnica (integrável a Zabbix/Grafana do CONTRATANTE).

1.2. Este contrato regula um **piloto controlado** com duração de **30 (trinta) dias**, prorrogável por aditivo.

---

### Cláusula 2ª — Modelo Comercial do Piloto

2.1. O valor do piloto, forma de pagamento, e eventuais bônus por **medição de lift** serão definidos em **proposta comercial anexa** assinada pelas partes.

2.2. **Não há promessa de causalidade definitiva de receita gerada pela inteligência artificial.** O piloto tem natureza de **prova controlada** e **medição de lift**.

2.3. A conversão do piloto em contrato definitivo dependerá:

- Da disponibilidade ao SLA pactuado (`02_sla.md`);
- Da entrega do **Relatório Final do Piloto**;
- Da assinatura de aditivo comercial.

---

### Cláusula 3ª — Acesso, Whitelist e Homologação

3.1. Durante todo o piloto, o **gateway WhatsApp** opera em modo de homologação (`HOMOLOG_MODE=true`).

3.2. A liberação para envio a números reais do CONTRATANTE ocorre **exclusivamente via whitelist controlada** (`CAUSALITY_PILOT_PHONES`), mediante autorização formal do CONTRATANTE e atendimento aos requisitos LGPD (`03_lgpd.md`).

3.3. O CONTRATANTE fornecerá:

- Acesso à sua base operacional (na medida estritamente necessária);
- Credenciais Zabbix/Grafana (quando aplicável);
- Lista de números autorizados para a whitelist (mediante consentimento dos titulares).

---

### Cláusula 4ª — Propriedade Intelectual

4.1. A plataforma SmartProv, incluindo código-fonte, modelos, algoritmos, arquitetura, fluxos e a esteira Action→Cash, é de **propriedade exclusiva da CONTRATADA**.

4.2. Os **dados operacionais e pessoais** do CONTRATANTE e de seus assinantes permanecem de **propriedade do CONTRATANTE**.

4.3. A CONTRATADA pode utilizar **métricas agregadas e anonimizadas** (sem identificação do CONTRATANTE ou titulares) para fins estatísticos internos, melhoria do produto e marketing institucional, desde que respeitada a confidencialidade da Cláusula 6ª.

---

### Cláusula 5ª — Tratamento de Dados Pessoais

5.1. O tratamento de dados pessoais é regulado pelo anexo `03_lgpd.md`, parte integrante deste contrato.

5.2. A CONTRATADA atua como **OPERADOR** e a CONTRATANTE como **CONTROLADOR** dos dados pessoais, nos termos da Lei nº 13.709/2018.

---

### Cláusula 6ª — Confidencialidade

6.1. As partes obrigam-se a manter sigilo sobre informações confidenciais a que tiverem acesso por força deste contrato, durante a vigência e por **2 (dois) anos** após o término.

6.2. **Não são consideradas confidenciais** informações:
- De domínio público no momento da divulgação;
- Que se tornem públicas sem culpa da parte receptora;
- Que a parte receptora já possuía comprovadamente.

---

### Cláusula 7ª — Obrigações da CONTRATADA

a) Disponibilizar a plataforma conforme SLA (`02_sla.md`);
b) Manter o gateway WhatsApp em homologação até autorização expressa para whitelist;
c) Entregar **Relatório Mensal de Piloto** com métricas operacionais e medição de lift;
d) Notificar incidentes de segurança em até 24h (vide `03_lgpd.md`);
e) Não comercializar dados do CONTRATANTE.

---

### Cláusula 8ª — Obrigações da CONTRATANTE

a) Pagar os valores acordados na proposta comercial anexa;
b) Fornecer credenciais e acessos necessários (Zabbix/Grafana, base operacional, whitelist);
c) Garantir que a whitelist `CAUSALITY_PILOT_PHONES` contém apenas titulares com **consentimento documentado**;
d) Indicar Encarregado de Dados (DPO) e ponto focal técnico;
e) Não realizar engenharia reversa nem replicar a plataforma.

---

### Cláusula 9ª — Vigência e Rescisão

9.1. **Vigência:** 30 (trinta) dias contados da assinatura, prorrogáveis.

9.2. **Rescisão imotivada:** qualquer das partes pode rescindir mediante aviso prévio de **15 (quinze) dias**.

9.3. **Rescisão motivada (sem aviso):** descumprimento material não sanado em 5 (cinco) dias úteis após notificação.

9.4. Em caso de rescisão, a CONTRATADA devolverá ou eliminará os dados conforme `03_lgpd.md` item 9.

---

### Cláusula 10 — Limitação de Responsabilidade

10.1. A responsabilidade total da CONTRATADA fica **limitada ao valor efetivamente pago** pela CONTRATANTE nos 12 (doze) meses anteriores ao evento gerador.

10.2. Nenhuma parte responde por danos indiretos, lucros cessantes ou danos morais decorrentes de:
- Falhas em serviços de terceiros (WhatsApp, Meta, provedores de cloud);
- Casos fortuitos e força maior;
- Uso indevido ou em desacordo com este contrato.

---

### Cláusula 11 — Disposições Gerais

11.1. Este contrato **não cria vínculo trabalhista, societário ou de exclusividade** entre as partes.

11.2. Alterações deverão ser formalizadas por **aditivo escrito** assinado por ambas as partes.

11.3. A nulidade de uma cláusula não invalida as demais.

---

### Cláusula 12 — Foro

12.1. Fica eleito o foro da Comarca de **[•]**, com renúncia de qualquer outro, por mais privilegiado que seja, para dirimir controvérsias oriundas deste contrato.

---

### Assinaturas

E, por estarem assim justas e contratadas, as partes assinam o presente em 2 (duas) vias de igual teor.

Local: ____________________________________  Data: ___/___/______

**CONTRATADA — SmartProv**
________________________________________
Nome: [•]
Cargo: [•]

**CONTRATANTE — [Razão Social do Provedor]**
________________________________________
Nome: [•]
Cargo: [•]

**Testemunhas:**
1. Nome: ________________________________  CPF: __________________
2. Nome: ________________________________  CPF: __________________

---

> **AVISO LEGAL — DOCUMENTO SUJEITO À REVISÃO JURÍDICA.**
> Este DRAFT V9.4 não substitui parecer jurídico. Antes da assinatura, deve ser revisado pelo jurídico da CONTRATANTE e por advogado externo da CONTRATADA.

_Documento DRAFT V9.4._
