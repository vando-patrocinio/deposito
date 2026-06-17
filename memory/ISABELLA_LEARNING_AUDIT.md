# Estado do Aprendizado da Isabella — Auditoria CTO 17/02/2026

**Pergunta CEO:** Como está o aprendizado da Isabella?

## TL;DR
A Isabella **registra fatos** (3.537 aprendizados, 480 nas últimas 24h), **detecta oportunidades** (3.338 totais, 228 em 24h) e **roda auditorias** de precisão (129 audits, 26 hoje). Mas o **loop de feedback está QUEBRADO em 3 pontos** que neutralizam a evolução real do sistema.

## ✅ O que está VIVO

| Coleção | Volume total | Últimas 24h | Status |
|---|---:|---:|---|
| `motor_ia_learnings` | 3.537 | **480** | Crescendo saudável |
| `isabella_commander_opportunities` | 3.338 | **228** | Detecção ativa |
| `isabella_precision_audits` | 129 | **26** | Auditoria automática rodando |
| `isabella_queue_metrics` | 305.840 | — | Métrica fila histórica |
| `motor_ia_subscriber_scores` | 2.796 | — | Scores por cliente |

### Aprendizados por categoria (motor_ia_learnings)
- 2.530 `kind=None` (legado, não classificado)
- **857 `autonomous_decision_outcome`** (decisões com resultado medido)
- 146 `feedback_snapshot`
- 2 `uncategorized`
- 1 `revenue_confirmation`
- 1 `smartolt_enrichment`

Volume diário (7 dias):
```
17/06 → 150 (parcial)
16/06 → 540
15/06 → 520
14/06 → 240
13/06 → 600  ← pico
12/06 → 480
11/06 →  30  ← vale
10/06 → 210
```

## 🔴 3 BUGS críticos que matam a evolução

### Bug 1 — Loop de outcome NÃO está fechando
- `isabella_outcomes` tem **APENAS 4 documentos**, TODOS de 10/06.
- TODOS com `outcome=unclassified` e flag `_backfill_version=iter243` (foram criados por backfill, não por execução real).
- **Não há novos outcomes sendo registrados desde 10/06**.
- Significa: Isabella propõe ação → executa → mas o resultado **não volta** pro motor de pesos.

### Bug 2 — Motor de pesos congelado
- `isabella_playbook_weights` tem **1 único documento**:
  ```
  playbook=nps_proativo · kind=churn · attempts=4 · successes=3 ·
  weight=0.9275 · confidence=0.5 · updated_at=2026-06-10T22:43
  ```
- Outros playbooks (`upsell_proativo`, `recupera_inadimplente`, `pagamento_atrasado`, etc.) **NÃO existem na tabela** apesar de serem usados.
- Sem outcome novo (bug 1), sem ajuste de peso (bug 2). Sistema **estagnou no estado de 10/06**.

### Bug 3 — Oportunidades detectadas, NUNCA AGIDAS
- `isabella_commander_opportunities` tem **3.338 documentos**, **0 com campo `acted_at`**.
- Isabella detecta padrões 24/7 mas **nenhum vira ação concreta**.
- Resultado: 3.338 sinais de churn / oportunidade de venda / upsell sentados no banco sem acionamento.

## ⚠️ Bugs menores
- `isabella_prompt_history` tem 7 docs mas todos com `version/sha/reason=None` — versionamento do prompt está sem identificadores.
- 2.530 dos 3.537 aprendizados estão com `kind=None` (sem classificação) — perde rastreabilidade.

## Diagnóstico
A Isabella hoje opera como **"observatório passivo"**: enxerga, mede, classifica, mas **não executa nem aprende com execução**. O loop fechado (`predict → act → measure → learn → adjust`) está aberto entre `predict` e `act`.

## Próximos passos sugeridos (3 sprints curtas)

### Sprint A — Reativar loop outcome (P0, 1 dia)
1. Identificar worker que deveria criar `isabella_outcomes` quando uma oportunidade é "fechada" (resolvida, expirada ou rejeitada).
2. Re-conectar `record_success/failure` em `services/isabella_learning.py` aos pontos de execução real (churn, boleto, upsell).
3. Validar com 5–10 outcomes reais antes de rodar em massa.

### Sprint B — Ativar agência sobre oportunidades (P0, 2-3 dias)
1. Auditar por que `acted_at` nunca é setado nas 3.338 opportunities — provável race condition entre `commanders_worker` (detecta) e `executor_ia` (deveria agir).
2. Definir **regra de aprovação automática** por kind: `churn` baixo risco → IA executa direto; `churn` alto risco / `upsell` → aguarda gestor.
3. KPI: meta de **30% das opportunities agidas em 24h**.

### Sprint C — Audit de classificação (P1, 1 dia)
1. Reprocessar os 2.530 learnings com `kind=None` via `agent-Auditor` (já existe).
2. Habilitar `isabella_prompt_history` com sha+version corretos (atualmente populados pelo `prompt_loader` mas sem persistir os metadados).

## Métrica única de saúde do aprendizado
Sugiro um indicador composto **"Learning Loop Closure %"**:
```
LLC = outcomes_classificados_24h / opportunities_criadas_24h
hoje = 0 / 228 = 0% ⚠️
meta = ≥40%
```

Quando `LLC > 40%`, a Isabella está aprendendo de verdade. Hoje **está aprendendo no nível de log, não de comportamento.**
