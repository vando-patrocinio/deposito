# 🤝 CONVITE_FUNDADORES_UNIVERSO_LIGO — Mecânica de Convite Humano

> **Operação:** Verdade Executiva + Curadoria Fundadores — FRENTE 3
> **Data:** 14/06/2026
> **Princípio único:** "Reconhecimento, não recompensa. Pertencimento, não promoção."
> **Escopo:** 130 fundadores (após validação Atendimento) + Lista Ouro de 17 (`experience_campaigns`).
> **Status:** Desenho do processo. ⛔ **NENHUM convite é disparado por este documento.** Aguarda autorização CTO para piloto.

---

## 🎯 OBJETIVO

Construir um processo de **convite humano, individual e cuidadoso** que comunique a esses clientes:

> "Você é parte da história da Ligo. Queremos te contar uma coisa."

E **nada além disso** no primeiro toque. Sem oferta. Sem desconto. Sem pedido. Sem QR Code. Sem link de cadastro.

---

## 1️⃣ QUEM CONVIDA?

**Em ordem de prioridade:**

| Categoria do cliente | Quem convida | Por quê |
|---|---|---|
| Lista Ouro (17, aniv_3y/5y/VIP já marcados) | **Pamela** (Guardiã da Comunidade) — voz humana, com áudio | Já há vínculo prévio; Pamela é o rosto da comunidade |
| Top 10 Fundadores (mais antigos) | **Liderança Ligo** (CEO ou diretor designado) — pessoalmente | Esses 10 representam a fundação da empresa. Merecem o convite mais alto |
| Demais 120 fundadores | **Time de Atendimento humano dedicado** (não bot) | Time conhece tom e código local |
| Embaixadores Naturais (113) | **Pamela**, em ondas | Voz coerente em escala humana |

**NUNCA convida:**
- ❌ Bot de WhatsApp genérico
- ❌ Disparo em massa via campanha
- ❌ Isabella (ela é vendedora, não anfitriã)
- ❌ Email marketing genérico
- ❌ SMS automático

---

## 2️⃣ QUANDO CONVIDA?

**Critério de timing:**

- **Não há prazo.** Convites são **gota a gota**, no máximo **3-5 por dia por convidador**.
- **Janela respeitosa:** 09h-19h, segunda a sexta. Excepcionalmente sábado de manhã. **Domingo: jamais.**
- **Evitar:**
  - Datas próximas a cobranças (cliente associa com "vão me cobrar mais")
  - Janeiro (gastos pós-festas)
  - Black Friday (ruído de promoção)
  - Período eleitoral

**Cadência sugerida do piloto:**
- Semana 1: 10 convites (Top 10 Fundadores, com liderança)
- Semana 2-3: 17 convites (Lista Ouro, com Pamela)
- Semana 4+: ondas de 20/semana entre os outros 113 embaixadores e 120 fundadores remanescentes

---

## 3️⃣ POR QUAL CANAL?

**Em ordem de preferência:**

| Canal | Quando usar | Vantagem |
|---|---|---|
| 🟢 **Ligação humana** | Top 10 Fundadores; Lista Ouro PJ | Toque mais alto. Voz humana cria vínculo emocional irreproduzível |
| 🟢 **WhatsApp pessoal** (não corporativo automatizado) | Demais 120 fundadores + embaixadores | Ritmo natural, cliente responde quando quer |
| 🟡 **Visita presencial / encontro técnico** | Quando há instalação/manutenção agendada perto da data | Surpresa positiva — combinar com OS de rotina |
| 🔴 **SMS** | Apenas como follow-up se WhatsApp não foi lido em 48h | Comunicação seca; uso restritíssimo |
| ❌ **Email** | NÃO USAR | Marca de marketing, fora de tom |
| ❌ **Push notification do app** | NÃO USAR | Tom de promoção |

---

## 4️⃣ O QUE FALA?

**Esqueleto do convite (3 partes):**

1. **Reconhecimento histórico** — "Você está com a Ligo desde [ano]."
2. **Convite ao Universo** — "Estamos construindo uma comunidade chamada Universo Ligo. Não é programa de pontos, não é clube de descontos. É uma forma de cuidar de quem fez a Ligo existir. Você é uma dessas pessoas."
3. **Pedido pequeno e voluntário** — "Posso te contar mais sobre isso em [10-15 min] quando você puder?"

**Princípios da linguagem:**
- Curto. Honesto. Sem floreios.
- **Nome próprio do cliente** (nunca "querido cliente").
- Mencionar **algo concreto local** quando souber (bairro, nome do vendedor original, evento real).
- Se a pessoa perguntar "Vou ganhar alguma coisa?" → resposta padrão: "Nada nesse primeiro momento, e nada que custe nada pra você. Quero te contar a ideia e ouvir o que você acha."

---

## 5️⃣ O QUE **NÃO** FALA?

❌ **Proibido:**
- "Programa de fidelidade"
- "Cashback"
- "Pontos"
- "Desconto exclusivo"
- "Promoção"
- "Indique e ganhe"
- "Afiliado"
- "Sistema de recompensas"
- "Bônus"
- "Comissão"
- "Embaixador" (na primeira conversa — esse status é construído, não anunciado)
- "Você foi selecionado" (soa a sorteio)
- "Você é VIP" (soa a hierarquia comercial)
- "Aproveite enquanto a vaga é limitada" (gatilho de escassez = marketing)

❌ **Nunca dizer:**
- "Acompanhe nosso ranking"
- "Tem um aplicativo novo"
- "Baixe o app para participar"
- "Compartilhe nas redes sociais"

✅ **Falar:**
- "Reconhecimento"
- "História"
- "Pertencimento"
- "Convite"
- "Comunidade"
- "Cuidado"

---

## 6️⃣ COMO REGISTRAR ACEITE?

**Após o "sim" do cliente:**

1. **Registrar manualmente** no painel `universo_ligo_invites` (collection a ser criada):
   - `subscriber_id`
   - `invited_by_user_id` (quem convidou)
   - `invited_at` (data/hora)
   - `channel` (call / wa / visita)
   - `accepted_at` (data da resposta positiva)
   - `notes` (livre, ex: "topou, pediu para ligar de novo na sexta")
2. **Sem campanha automática follow-up.** Próximo toque humano, manual, agendado pelo convidador.
3. **Sem mensagem de boas-vindas automatizada.** O primeiro retorno após o "sim" é uma ligação ou áudio pessoal.
4. **Não comunicar publicamente** o aceite — nem em redes da Ligo, nem em colab.

---

## 7️⃣ COMO REGISTRAR RECUSA?

**"Obrigado, não tenho interesse agora."**

- Resposta padrão do convidador: "Sem problema, [nome]. A gente segue cuidando da sua internet. Se mudar de ideia, é só falar."
- Registrar em `universo_ligo_invites`:
  - `declined_at`
  - `decline_reason` (livre, opcional)
- **Sem retentativa automática.** Cliente que recusou não recebe novo convite **automaticamente nunca**. Próximo toque só após **6 meses** + decisão humana.

---

## 8️⃣ COMO REGISTRAR "NÃO CHAMAR NOVAMENTE"?

**"Por favor, não me ligue mais sobre isso."** ou frase mais dura.

- Registrar em `universo_ligo_invites`:
  - `do_not_contact_universo_ligo = True` (campo TRUE definitivo)
  - `do_not_contact_at`
  - `do_not_contact_reason` (livre)
- **Esse flag NUNCA expira.** Cliente está fora da comunicação Universo Ligo de forma permanente.
- O flag **não bloqueia** comunicação operacional (boletos, suporte técnico, manutenção). Bloqueia **apenas** o canal Universo Ligo.
- O time deve **respeitar com gravidade**. Quem violar: alerta CTO imediato.

---

## 9️⃣ COMO ESCALAR CLIENTE EMOCIONADO/IRRITADO?

**Cliente emocionado positivamente** ("nossa, fiquei feliz"):
- Não vender nada no momento. Apenas: "Que bom, [nome]. Esse é exatamente o tom da coisa. Vou te chamar daqui [tempo] para conversarmos mais."
- Registrar em notes: "🟢 reação emocional positiva"
- Liderança vê esses casos no painel — candidato natural a **depoimento futuro**.

**Cliente irritado / desconfiado**:
- Não argumentar. Não defender.
- Frase de saída: "Entendo, [nome]. Foi mal incomodar. A internet segue normal e a Ligo está aqui pra você quando precisar. Tudo bem se eu não te chamar mais sobre isso?"
- Se cliente xingar: encerrar contato educadamente, registrar `do_not_contact_universo_ligo = True`, alerta automático para liderança revisar abordagem.
- **Não bloquear conta. Não reduzir prioridade de atendimento.** Cliente continua cliente normal.

**Cliente confuso** ("o que é isso? é cobrança nova?"):
- Reforçar imediatamente: "**Não é cobrança. Não é nada novo na sua conta.** É só um reconhecimento por você estar com a gente há tantos anos."
- Se persistir confuso: deixar o convite para outro momento, com agradecimento.

---

## 🔟 COMO TRANSFORMAR 3-5 FUNDADORES EM DEPOIMENTO FUTURO SEM FORÇAR?

**Premissa:** depoimento **só vem depois** da pessoa já ter aceito o Universo Ligo + ter tido pelo menos 1 conversa boa.

**Critério para convite ao depoimento:**
- Reagiu emocionalmente positiva no convite inicial
- Topou continuar conversando (não recusou)
- Liderança identificou afinidade comunicacional (não tem que ser articulado — autenticidade > eloquência)

**Como pedir:**
> "[Nome], pensa numa coisa: estamos contando a história da Ligo pra mais gente — gente que tá começando agora. Posso gravar 30 segundos do que você quiser falar da Ligo, do jeito que você fala normalmente? Nada de roteiro. Você manda em casa pelo WhatsApp ou eu passo aí com um celular. Se topar."

**Princípios do pedido:**
- Pedido **explícito de consentimento**
- **Sem roteiro decorado**
- **Audio ou vídeo curto, sem produção pesada**
- **Cliente decide o local, formato e momento**
- **Direito de não publicar** mesmo depois de gravado — combinado por escrito
- **Sem pagamento, sem desconto em troca** (isso transformaria em advertorial pago)

**Onde será usado:**
- Página de marca do Universo Ligo (interna inicialmente)
- Reunião interna de Ligo (alinhamento de equipe)
- **Não publicar em campanha paga.** Conteúdo é institucional, não promocional.

**Cap inicial:** 3-5 vídeos para o lançamento. **Não escalar para 50.**

---

## 📜 3 ROTEIROS PRONTOS

> Use como **ponto de partida**, adaptando ao tom de cada convidador. **Não decorar.** Falar com naturalidade.

---

### 🟢 ROTEIRO 1 — WHATSAPP (texto + áudio curto opcional)

**Mensagem 1 — Texto:**

> Oi, [primeiro nome]. Aqui é a Pamela, da Ligo. Tudo bem?
>
> Eu queria te falar uma coisa rapidinho — não é cobrança, não é nada mudando na sua internet, fica tranquilo(a).
>
> Você está com a gente desde [ano]. A gente parou pra olhar a base de clientes da Ligo essa semana e seu nome apareceu como uma das pessoas que ajudaram a Ligo a existir.
>
> Queria te contar uma novidade que a gente tá começando agora, que tem tudo a ver com isso. Posso te chamar 5 minutinhos quando você puder? Pode ser amanhã, depois, quando der.
>
> Obrigada por estar com a gente esse tempo todo. 🩵

**Se o cliente responder "claro" / "pode chamar":**

> 🎙️ **Áudio curto (15-30s, voz da Pamela):**
> "Oi [nome], aqui é a Pamela de novo. Só queria agradecer pelo retorno. Te ligo [dia/horário combinado]. Beijo, até lá."

**Se o cliente responder "o que é?":**

> Conta no áudio mesmo — fica mais fácil. Posso?

---

### 🟢 ROTEIRO 2 — LIGAÇÃO HUMANA (top 10 fundadores, conduzida por liderança)

**Abertura:**

> "Oi, [nome]? Aqui é o(a) [seu nome], eu trabalho na Ligo. Tudo certo aí com a internet? Tô ligando por outro motivo, mas se tiver tempo agora a gente conversa — se não, marca outro horário sem problema."

**Se cliente diz "pode falar":**

> "Vou ser bem direto(a). A Ligo tá com [tempo de existência] anos. A gente parou essa semana pra olhar quem são as pessoas que fizeram a Ligo chegar até aqui. Seu nome apareceu — você é cliente da gente desde [ano]. São [N] anos.
>
> A gente tá construindo uma comunidade que chama Universo Ligo. Não é programa de pontos, não é desconto, não é nada que vai aparecer na sua conta. É um jeito da Ligo reconhecer e cuidar de quem fez ela existir. E queria te chamar pra fazer parte desde o começo.
>
> Não precisa decidir nada agora. Posso te mandar uma mensagem no WhatsApp depois com mais detalhe, e a gente conversa de novo na semana que vem se você quiser. Pode ser?"

**Se cliente pergunta "vou ganhar alguma coisa":**

> "Nada nesse primeiro momento, e nada que custe nada pra você. O que a gente tá montando é mais sobre pertencimento e cuidado do que sobre dinheiro. Se em algum momento isso virar uma coisa que te incomode, é só falar e a gente para. Combinado?"

**Encerramento:**

> "[Nome], independente do que você decidir depois, obrigado(a) por estar com a Ligo todo esse tempo. Esse é o motivo da ligação, mais nada. Tem um bom dia."

---

### 🟢 ROTEIRO 3 — VISITA TÉCNICA / ENCONTRO PRESENCIAL

> Usar **quando há OS de manutenção/instalação programada** e o cliente está na nossa lista. Combinar com o técnico de campo.

**Briefing ao técnico de campo (interno):**

> Antes de ir à casa de [nome], leve impresso o **cartão de reconhecimento** (template abaixo). No final do atendimento técnico, em tom natural:

**Fala do técnico:**

> "Senhor(a) [nome], deixa eu te mostrar uma coisinha antes de ir. A gente tá começando aqui na Ligo um projeto que chama Universo Ligo. É pra cuidar dos clientes mais antigos da gente, e seu nome tá na lista — você tá com a gente desde [ano]. Esse cartão aqui é só um obrigado. Se quiser saber mais, alguém da Ligo vai te chamar essa semana. Foi um prazer, qualquer coisa é só ligar."

**Cartão impresso (template):**

```
                    UNIVERSO LIGO

           [Nome do cliente]
           cliente Ligo desde [ano]

           Obrigado por fazer parte
           desde o começo.

                          - Time Ligo
```

> Sem QR Code. Sem URL. Sem logo grande. Sem call-to-action. Só reconhecimento.

---

## 🛡️ REGRAS DE OURO DO PROCESSO

1. **1 toque por cliente por mês**, no máximo. Cliente não-respondente: pausar.
2. **Nada de retentativa automática.** Todo segundo toque é decidido por humano.
3. **Quem convida assina pessoalmente.** Mensagens sem nome próprio do convidador são proibidas.
4. **Auditoria semanal:** liderança lê 10 conversas aleatórias do piloto e dá feedback.
5. **Métricas internas (não públicas):** aceite, recusa, do-not-contact, sem-resposta. Sem KPI de "conversão". A intenção **não é vender mais**.
6. **Direito de desligamento total:** cliente pode pedir "tirem meu nome de tudo isso" e isso é absoluto.

---

## 📋 CHECKLIST OPERACIONAL ANTES DE ABRIR O PILOTO

- [ ] CTO aprova lista de Top 10 Fundadores (após validação Atendimento)
- [ ] Pamela treinada nos 3 roteiros
- [ ] Liderança treinada no Roteiro 2
- [ ] Collection `universo_ligo_invites` criada com índices em `subscriber_id`, `do_not_contact_universo_ligo`, `accepted_at`
- [ ] Campo `do_not_contact_universo_ligo` adicionado em `subscribers` (preventivo)
- [ ] Painel interno simples para registrar aceite/recusa/DNC (não-cliente-facing)
- [ ] Cartão impresso "Universo Ligo" produzido em 50 unidades (suficiente para piloto)
- [ ] Audit log automatico para qualquer disparo automatizado tentando usar nomes da lista (alerta CTO)
- [ ] Lista de fundadores **NÃO** exportada para CSV externo
- [ ] Lista de fundadores **NÃO** sincronizada com nenhuma ferramenta de marketing

---

## 🚫 GUARDIANS

**Pamela** é a Guardiã do tom desta comunicação. Qualquer mensagem que saia em nome do Universo Ligo passa pelos olhos dela antes da primeira semana.

**CTO** é o Guardião do limite. Qualquer tentativa de transformar isso em campanha, ranking, programa de pontos, ou afiliado **deve ser interceptada e revertida**.

**Atendimento** é o Guardião da pessoa. Cliente em atrito, cliente desconfiado, cliente em luto, cliente em mudança de vida: respeitar **sempre**.

---

## ❤️ FECHAMENTO

> Esses 130 fundadores **não devem nada à Ligo**. A Ligo é que deve a eles. O Universo Ligo só faz sentido se essa hierarquia ficar clara na voz, no tom, no gesto e nos dados.
