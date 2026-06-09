# LGPD — Termo de Tratamento de Dados Pessoais

> **STATUS:** DRAFT V9.4 — **sujeito à revisão jurídica.**
> Este documento é um **anexo** ao Contrato SaaS (`04_contrato_saas.md`) e regula o tratamento de dados pessoais nos termos da **Lei nº 13.709/2018 (LGPD)**.

---

## 1. Partes e Papéis

- **CONTROLADOR:** o provedor de internet/telecom (CONTRATANTE), titular da relação com seus assinantes e responsável pelas decisões sobre o tratamento.
- **OPERADOR:** SmartProv (CONTRATADA), que realiza o tratamento em nome do CONTROLADOR, dentro dos limites desta política e do contrato base.

A SmartProv **não comercializa** dados pessoais e **não trata** dados pessoais fora das finalidades aqui descritas.

---

## 2. Finalidades do Tratamento

A SmartProv tratará dados pessoais exclusivamente para:

1. Operação dos módulos contratados: **Smart Field Ops, Action→Cash, AI Center, Observability Twin**.
2. Atendimento técnico e operacional dos chamados (tickets, ordens de serviço, finalização de OS).
3. **Medição de lift** e geração de relatórios estatísticos e operacionais — sem identificação pessoal nos relatórios entregues.
4. Comunicação operacional via WhatsApp através do **gateway de homologação** ou, mediante autorização específica, da whitelist controlada (`CAUSALITY_PILOT_PHONES`).

---

## 3. Categorias de Dados Tratados

| Categoria | Exemplos | Base Legal (Art. 7º LGPD) |
|-----------|----------|---------------------------|
| Identificação | Nome, telefone, e-mail, CPF (quando aplicável) | Execução de contrato com titular / Legítimo interesse |
| Localização aproximada | Endereço de instalação, coordenadas da OS | Execução de contrato |
| Operacional | Tickets, OS, status de chamado, equipamentos recuperados | Execução de contrato / Legítimo interesse |
| Comunicação | Mensagens trocadas via gateway WhatsApp em homologação | Consentimento + Execução de contrato |

> **Não são tratados dados sensíveis** (origem racial, saúde, biometria, etc.) pela SmartProv no escopo desta plataforma.

---

## 4. Princípios Aplicados (Art. 6º LGPD)

A SmartProv adota:

- **Finalidade:** uso restrito às finalidades do item 2.
- **Necessidade:** minimização de dados — somente o estritamente necessário.
- **Adequação:** dados compatíveis com a finalidade.
- **Transparência:** o CONTROLADOR pode auditar registros a qualquer momento.
- **Segurança:** medidas técnicas e administrativas (item 6).
- **Não discriminação:** o piloto controlado não usa dados para fins discriminatórios.
- **Responsabilização e prestação de contas:** logs de auditoria mantidos por no mínimo 12 (doze) meses.

---

## 5. Direitos dos Titulares (Art. 18 LGPD)

O CONTROLADOR é o ponto único de contato com os titulares. A SmartProv prestará apoio em até **5 (cinco) dias úteis** para:

- Confirmação da existência de tratamento
- Acesso aos dados
- Correção de dados incompletos/inexatos
- Anonimização, bloqueio ou eliminação
- Portabilidade
- Eliminação dos dados tratados com consentimento
- Informação sobre compartilhamento
- Revogação de consentimento

---

## 6. Segurança da Informação

Medidas mínimas adotadas pela SmartProv como OPERADOR:

- Acesso à plataforma autenticado (JWT) e segregado por perfil.
- Banco de dados MongoDB com credenciais via variáveis de ambiente — sem hardcoding.
- Gateway WhatsApp em `HOMOLOG_MODE=true` por padrão — toda saída é mascarada, auditada e roteada para o número técnico (`5521998176526`), exceto whitelist controlada.
- Auditoria de eventos sensíveis em `motor_ia_events` e `motor_ia_actions`.
- Backups operacionais regulares.

> Medidas adicionais (criptografia em repouso, pentest, ISO 27001) **serão pactuadas em aditivo** conforme exigência do CONTROLADOR.

---

## 7. Subcontratados (Sub-operadores)

A SmartProv poderá utilizar:

- **WhatsApp / Meta** — entrega de mensagens via Baileys (gateway local).
- **MongoDB / provedor de cloud** — armazenamento operacional.
- **Zabbix / Grafana** — observabilidade (quando credenciais forem fornecidas pelo CONTROLADOR).

Qualquer novo sub-operador será comunicado ao CONTROLADOR com **30 (trinta) dias** de antecedência.

---

## 8. Incidentes de Segurança

Em caso de incidente envolvendo dados pessoais, a SmartProv comunicará o CONTROLADOR em até **24 (vinte e quatro) horas** a partir do conhecimento, com:

- Descrição da natureza do incidente
- Dados envolvidos
- Titulares afetados (estimativa)
- Medidas adotadas/recomendadas

O CONTROLADOR é responsável pela comunicação à ANPD e aos titulares, conforme Art. 48 LGPD.

---

## 9. Retenção e Eliminação

- Dados operacionais: retidos durante a vigência do contrato + **6 (seis) meses** para fins de auditoria.
- Logs técnicos: **12 (doze) meses**.
- Encerramento do contrato: dados eliminados ou devolvidos ao CONTROLADOR em até **30 (trinta) dias**, mediante solicitação formal.

---

## 10. Encarregado de Dados (DPO)

- **DPO do CONTROLADOR:** a ser indicado pelo provedor.
- **Ponto focal de Privacidade da SmartProv:** a ser indicado na assinatura do contrato.

---

## 11. Foro e Lei Aplicável

Lei nº 13.709/2018 (LGPD) e legislação correlata brasileira. Foro a ser definido no contrato base.

---

> **AVISO LEGAL — DOCUMENTO SUJEITO À REVISÃO JURÍDICA.**
> Este DRAFT V9.4 não substitui parecer jurídico formal. Antes da assinatura, deve ser revisado pelo departamento jurídico do CONTRATANTE e por advogado externo da SmartProv.

_Documento DRAFT V9.4._
