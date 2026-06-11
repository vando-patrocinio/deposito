# CONSTITUIÇÃO DO SISTEMA NERVOSO — V3.1

> Versão: 3.1 · Data: 2026-02-10 · Substitui V3.0
> Oficializa 42 tipos de evento que estavam emitindo em produção sem registro.

## 📋 RESUMO

- **V3.0** declarava 38 event_types em 10 domínios.
- **Auditoria** detectou 42 tipos extras já emitindo (130k+ eventos/30d).
- **V3.1** absorve os tipos legítimos, padroniza nomenclatura e marca os
  órfãos para remoção/fusão.

## 🆕 DOMÍNIOS V3.1 (12 — adicionados 2)

| Domínio | V3.0 | V3.1 |
|---|---|---|
| comercial / instalações / financeiro / atendimento | ✓ | ✓ |
| whatsapp / indicações / parceiros / estoque | ✓ | ✓ |
| rede / operações | ✓ | ✓ |
| **isabella** (novo) | — | ✓ |
| **shield** (novo) | — | ✓ |

## 📦 EVENT_TYPES OFICIALIZADOS V3.1

### Domínio `isabella` (autonomous engine · 18 tipos)
- `dunning.step.recommended` — Isabella recomenda passo de cobrança
- `revenue.opportunity.detected` — Receita adicional detectada
- `opportunity.created` — Oportunidade comercial criada
- `universo.score.updated` — Score Universo Ligo atualizado
- `churn.risk.scored` — Risco de churn calculado
- `twin.failure.predicted` — Digital Twin previu falha
- `expansion.area.recommended` — Expansão geográfica recomendada
- `experience.campaign.drafted` — Campanha Universo Ligo em rascunho
- `experience.campaign.approved` — Campanha aprovada
- `experience.event.executed` — Evento de experiência executado
- `council.meeting.held` — Reunião do Conselho IA
- `AI_OUTCOME` — Outcome de decisão IA registrado
- `field.isabella.stock.alert` — Alerta de estoque
- `field.isabella.crew.recommend` — Recomendação de equipe
- `ATENDIMENTO_CHANCE_UPGRADE` — Atendimento detectou upgrade
- `ATENDIMENTO_CHANCE_INDICACAO` — Atendimento detectou indicação
- `ATENDIMENTO_RISCO_CANCELAMENTO` — Atendimento detectou risco
- `incident.mass.notify` — Notificação massiva de incidente

### Domínio `shield` (security · 4 tipos)
- `RBAC_DENIED` — Tentativa de acesso negada
- `DATA_QUALITY_DROP` — Queda em data quality detectada
- `shield.audit.completed` — Auditoria diária concluída
- `shield.regression.detected` — Regressão de segurança detectada

### Domínio `rede` (network · 1 tipo)
- `ONU_LOW_SIGNAL` — ONU com sinal baixo detectada

### Domínio `indicacoes` (referrals · 1 tipo)
- `REFERRAL_OPPORTUNITY` — Oportunidade de indicação

## 🗑️ TIPOS REMOVIDOS / DEPRECATED V3.1
*(nenhum por ora — todos os 42 extras tinham uso legítimo)*

## ✅ COBERTURA V3.1
- Total declarado: 38 (V3.0) + 24 (novos oficializados) = **62 event_types**
- Distinct emitidos: 80 → 62 legítimos + 18 ainda órfãos a investigar
- Domínios ativos: 12

## 🔒 REGRA DE ALTERAÇÃO
Qualquer novo event_type DEVE:
1. Ser declarado primeiro nesta constituição (via PR).
2. Estar mapeado em `services/nervous_coverage.EXPECTED_BY_DOMAIN`.
3. Ter NERVOUS_METADATA do módulo emissor com este tipo em `event_types`.
4. Passar pelo `nervous_linter.py` em modo `ci`.

Sem isso, o tipo será marcado como ÓRFÃO no próximo snapshot daily.
