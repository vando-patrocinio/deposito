# SLA — Acordo de Nível de Serviço SmartProv

> **STATUS:** DRAFT V9.4 — sujeito à revisão jurídica e comercial antes da assinatura.
> **APLICABILIDADE:** Piloto controlado de 30 (trinta) dias com 1 (um) provedor parceiro.

---

## 1. Definições

- **CONTRATANTE:** Provedor de internet/telecom signatário do contrato base (ver `04_contrato_saas.md`).
- **CONTRATADA:** SmartProv (operadora da plataforma).
- **PLATAFORMA:** Conjunto de módulos SmartProv: Smart Field Ops, Action→Cash, AI Center, Observability Twin.
- **PILOTO CONTROLADO:** Janela de 30 dias com tráfego restrito por whitelist (`CAUSALITY_PILOT_PHONES`) e gateway de homologação ativo.

---

## 2. Disponibilidade

| Componente | Disponibilidade alvo (mensal) | Janela de aferição |
|-----------|-------------------------------|--------------------|
| API backend (FastAPI) | 99,5% | 24/7 |
| Frontend operacional (LousaMobile, AI Center) | 99,0% | Horário comercial (06h–23h BRT) |
| Sidecar WhatsApp (Baileys local) | 98,0% — sujeito ao próprio WhatsApp | 24/7 |
| Observability Twin | 99,0% (após credenciais reais) | 24/7 |

> Indisponibilidades causadas por terceiros (WhatsApp, Zabbix, Grafana, provedores de cloud do CONTRATANTE, falhas de energia/link no NOC) **não contam** contra o SLA.

---

## 3. Janelas de Manutenção

- **Programada:** todo sábado, 02h00–05h00 BRT, com aviso de 48h.
- **Emergencial:** sem aviso prévio, com comunicação simultânea via canal oficial.

---

## 4. Severidades e Tempo de Resposta (SLA)

| Severidade | Descrição | Tempo 1ª resposta | Tempo de resolução alvo |
|-----------|-----------|-------------------|-------------------------|
| **S1 — Crítico** | Plataforma indisponível ou perda de dados. | 30 min (24/7) | 4 horas |
| **S2 — Alto** | Funcionalidade central comprometida (ex.: Action→Cash, finalize de OS). | 2 horas (horário comercial) | 1 dia útil |
| **S3 — Médio** | Funcionalidade secundária comprometida ou degradação. | 1 dia útil | 3 dias úteis |
| **S4 — Baixo** | Solicitação de melhoria ou dúvida operacional. | 2 dias úteis | A combinar |

> Tempos contados a partir do registro formal pelo canal de suporte oficial.

---

## 5. Canais de Suporte

- **Canal primário:** e-mail dedicado (a definir após assinatura).
- **Canal secundário:** WhatsApp do piloto (`5521998176526` — número técnico SmartProv).
- **Operação 24/7:** somente S1.

---

## 6. Medição e Relatórios

- Métricas operacionais coletadas em `motor_ia_events`, `motor_ia_outcomes`, `tickets.completion_data`.
- **Relatório mensal de piloto** entregue até o 5º dia útil contendo:
  - Disponibilidade real x SLA
  - Tickets processados / OS finalizadas
  - Receita atribuída pela esteira Action→Cash
  - Adoção dos campos Smart Field Ops (`resolution_kind`, `asset_recovered`, `signed_receipt`)
  - Medição de lift via cohorts (`motor_ia_cohorts`, `motor_ia_causality`)

> O relatório não afirma causalidade definitiva de receita gerada pela IA. Toda métrica de **medição de lift** é apresentada como recorte do piloto controlado.

---

## 7. Penalidades

Durante o piloto controlado (30 dias), **não há multa financeira** por descumprimento de SLA. O CONTRATANTE pode, a seu critério, rescindir o piloto sem ônus caso o SLA seja descumprido em 2 (dois) eventos S1 consecutivos no mesmo mês.

Após conversão em contrato definitivo, novas penalidades poderão ser pactuadas em aditivo.

---

## 8. Limitações Explícitas (Transparência V9.4)

- **Gateway WhatsApp** opera em `HOMOLOG_MODE=true` durante a maior parte do piloto. Liberação para tráfego real é controlada por whitelist (`CAUSALITY_PILOT_PHONES`) com autorização documentada do CONTRATANTE.
- **Observability Twin** pode operar com fontes simuladas até a entrega de credenciais Zabbix/Grafana do CONTRATANTE.
- **AI Center** não envia mensagens para clientes finais fora da whitelist.

---

## 9. Vigência

Este SLA vigora durante a vigência do contrato base (`04_contrato_saas.md`).

---

_Documento DRAFT V9.4. Sujeito à revisão comercial e jurídica._
