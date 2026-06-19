# 🎯 BLOCK RATE — 30-DAY OPERATIONAL ACTION PLAN

**Data:** 19/06/2026  
**Janela:** 19/06/2026 → 19/07/2026  
**Princípio:** Sem código novo. Sem refactor. Apenas operação + medição.  
**Modo:** INSTRUMENTED PRODUCTION

---

## Princípio orientador

A análise forense provou que o block rate de 62,5 % é dado de teste. A operação real ainda **não foi medida**. O plano de 30 dias tem **3 metas em sequência**:

1. **Gerar volume operacional honesto** (15 dias)
2. **Medir block rate real** (entre dia 15 e 22)
3. **Atacar a causa raiz medida** (últimos 8 dias)

---

## Quadro de ações

| # | Ação | Responsável | Prazo | KPI esperado | Redução projetada |
|---|---|---|---:|---|---:|
| **A1** | Onboarding dos 15 técnicos no fluxo Onda 3 (Lousa). Reunião de 1h por turma. Quem não fez o onboarding não fecha OS. | Gestor de Operação | dia 3 | 15/15 técnicos certificados | sem impacto direto, habilita medição |
| **A2** | Comunicar aos técnicos: **OS de instalação/reparo/troca/retirada agora exigem ONT, CTO e Porta no fechamento**. Plataforma bloqueia se faltar dado. | Gestor de Operação | dia 3 | 0 bypasses futuros | habilita medição honesta |
| **A3** | Backfill de `subscribers.neighborhood` a partir de `tickets.client_snapshot.neighborhood`. **Não é código novo** — é script de leitura sobre dados existentes. Pode ser feito por SQL/Mongo direto. | Squad Patrimônio (1h) | dia 5 | ≥ 80 % subscribers com bairro | habilita análise geo |
| **A4** | Mutirão de Quarentena: gestor revisa 30 ONUs/dia usando a tela existente. | Gestor de Operação | dia 30 | 115 → < 30 | cobertura 93,84 → 97 % |
| **A5** | Confirmar os 13 swap_events `pending_confirmation` reais via WhatsApp com técnicos. | Gestor de Operação | dia 14 | 13 → 0 | compliance patrimonial +0,7 pp |
| **A6** | Rodar Phase A toda sexta 06:00 com snapshot histórico. **Já existe endpoint** — basta agendar cron manualmente (`crontab -e`) ou executar manualmente. | Gestor / DevOps | dia 7 (primeira execução) | 4 pontos no timeline em 30d | habilita comparação |
| **A7** | Auditoria por amostragem: gestor seleciona 5 OS reais finalizadas/dia, verifica se `onda3_validation_diag` está populado. Se não estiver, identificou bypass não previsto. | Gestor de Operação | contínuo | bypass detectados em 30d | qualifica a Sprint 5 |
| **A8** | **Marco 15 dias (04/07/2026)**: reexecutar este forensic. Se base ≥ 30 OS reais, calcular block rate REAL. | CTO + Gestor | dia 15 | nova baseline honesta | decisão data-driven |
| **A9** | **Marco 30 dias (19/07/2026)**: análise final. Se block rate ≥ 30 %, identificar top motivos com base estatística e propor intervenção operacional (não código). | CTO + CEO | dia 30 | block rate < 30 % | meta cumprida |

---

## Cronograma

```
SEMANA 1 (dias 1-7)
  A1 — Onboarding técnicos                ████████
  A2 — Comunicação Onda 3 ativa           ████████
  A3 — Backfill bairros                       ████
  A6 — Primeira execução Phase A semanal             ██

SEMANA 2 (dias 8-14)
  A4 — Mutirão Quarentena (lote 1)        ████████████
  A5 — Confirmar 13 swaps                 ████████████
  A7 — Auditoria amostragem               ════════════
  A6 — Phase A semanal #2                            ██

SEMANA 3 (dias 15-22)
  A8 — Marco 15 dias: forensic v2         ████
  A4 — Mutirão Quarentena (lote 2)        ████████████
  A6 — Phase A semanal #3                            ██

SEMANA 4 (dias 23-30)
  A9 — Análise final block rate           ████████
  A4 — Mutirão Quarentena (lote 3)        ████████████
  A6 — Phase A semanal #4                            ██
  RELATÓRIO FINAL                              ████████
```

---

## Indicadores diários sugeridos para o gestor

```
1. Quantas OS reais foram fechadas hoje pela Onda 3?
   Meta semana 1:  ≥ 5
   Meta semana 4:  ≥ 20

2. Quantas OS foram bloqueadas hoje?
   Não é problema. É sinal de que o gate está vivo.

3. Quantas ONUs saíram da quarentena hoje?
   Meta diária: 4 (= 30 ONUs/semana)

4. Quantos overrides foram aplicados hoje?
   Anomalia: se > 30 % das finalizações, investigar.

5. Quantos swap_events foram confirmados hoje?
   Meta acumulada: 13 → 0 em 14 dias.
```

---

## Critérios de sucesso (dia 30)

| KPI | Hoje | Meta dia 30 | Verificação |
|---|---:|---:|---|
| Quarentena pendente | 115 | < 30 | `GET /api/sprint5/quarantine/stats` |
| Swap events pending | 13 | 0 | `db.auto_ont_swap_events.count(pending)` |
| Cobertura Operacional | 93,84 % | ≥ 98 % | Gauge Phase D |
| Block rate Onda 3 | 62,5 % (teste) | < 30 % (real) | Phase A weekly |
| OS reais finalizadas no caminho oficial | 0 | ≥ 50 | `sprint5_onda3_validations` filtrado |
| Subscribers com `neighborhood` | 0 % | ≥ 80 % | mongo count |
| Bypasses detectados na auditoria amostragem | 0 | 0 | logs do gestor |

---

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Operação não gera volume suficiente em 15 dias | Postergar marco A8 para dia 22. Não inventar dados. |
| Técnicos resistem ao novo fluxo | A1 com 2 sessões + acompanhamento. Override gestor é a válvula. |
| Backfill bairros gera duplicidades | A3 lê só `client_snapshot.neighborhood` e popula se subscriber estiver vazio. Zero risco de sobrescrita. |
| Gestor não consegue revisar 30 quarentenas/dia | Reduzir para 15/dia. Meta < 30 vira meta < 60. |

---

## O que **NÃO** vamos fazer

- ❌ Mudar a fórmula do Phase A para mascarar block_rate
- ❌ Excluir test data automaticamente (manter o sinal para audit)
- ❌ Construir dashboard de "block_rate ao vivo"
- ❌ Criar feature de auto-correção
- ❌ Abrir Sprint 6
- ❌ Refactor de lousa.py ou whatsapp_baileys.py

---

## Próximos pontos de decisão CEO

- **dia 7**: revisar primeira Phase A semanal pós-onboarding
- **dia 15**: assinar (ou não) re-medição honesta do block rate
- **dia 30**: assinar conclusão da janela INSTRUMENTED PRODUCTION

---

**Status do plano:** Aprovado pelo CTO. Aguardando assinatura do CEO para iniciar.
