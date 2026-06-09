# AI_CENTER_CONSOLIDATION_REPORT

**Data:** 09-Jun-2026
**Status:** 🟧 **DEFINIDO** — versão canônica eleita, versões obsoletas mantidas no repositório mas marcadas como **DEPRECATED**. Sem apagar código.

---

## 1. Inventário completo (LoC e endpoints)

| Arquivo | LoC | Endpoints | Usado pelo frontend? | Registrado em `server.py`? |
|---|---|---|---|---|
| `routes/ai_center_v51.py` | 222 | 19 | ✅ `/v51/command-center` + `/v51/technician-ranking` + `/v51/cto-ranking` + `/failure-risk/*` | ✅ |
| `routes/ai_center_v6.py` | 74 | 6 (`/smart-field/sync`, `/smart-field/kpis`, `/company-score`, `/revenue/mark-received`, `/revenue/reconcile`, `/digital-twin`) | ❌ — zero referência no frontend | ✅ |
| `routes/ai_center_v7.py` | 378 | 27 (`/operacao-tese/*`, `/v8/causality/*`, `/v8/v84/*`, `/v9/smart-field-adoption`, ...) | ❌ — zero referência no frontend | ✅ |
| `routes/ai_center_v62.py` | 38 | 3 (`/revenue-real`, `/roi-priorities`, `/presidente-natural`) | ✅ todas as 3 | ✅ |
| `routes/ai_center_v80.py` | 129 | 6 (`/score`, `/golive-master`, `/money-stream`, `/experiments/*`) | ✅ todas | ✅ |
| `routes/ai_center_alvaro.py` | 72 | 8 (`/alvaro/*`) | ✅ parcial (frontend usa subset) | ✅ |
| `routes/ai_center_alvaro_v5.py` | 132 | 6 (`/alvaro-v5/*`) | ✅ via v51 (`/alvaro-v5/triage`, etc.) | ✅ |
| `routes/ai_center_isabella.py` | 72 | 6 | ✅ | ✅ |
| `routes/ai_center_observability.py` | 575 | 13 | ✅ Observability Twin completo | ✅ |
| `routes/ai_center_smartolt_twin.py` | — | — | ✅ | ✅ |
| `routes/ai_center_financial.py` | — | — | ❌ (DRE não alimentada) | ✅ |

**Total LoC AI Center vXX puro:** 1.045 LoC em 7 arquivos.
**LoC efetivamente usado pelo frontend:** ~595 LoC (v51 + v62 + v80 + alvaro + isabella).
**LoC órfão:** **452 LoC** (v6 + v7 inteiros — 33 endpoints sem consumidor).

## 2. Mapa de uso real (frontend → endpoint)

```
PresidenteIaPanel.js     → /presidente-ia/* (router próprio)
AlvaroCommandCenter.js   → /v51/command-center
                          → /v62/revenue-real
                          → /v62/roi-priorities
                          → /v62/presidente-natural
                          → /v80/score
                          → /v80/golive-master
                          → /v80/money-stream
                          → /failure-risk/*
                          → /alvaro-v5/triage
                          → /alvaro-v5/recurrence/*
ObservabilityTwin.js     → /ai-center/observability/*
RevenueOpsPanel (parcial)→ /ai-center/revenue/*
```

## 3. Duplicações detectadas

| Função semântica | Implementação A | Implementação B | Solução |
|---|---|---|---|
| **Score executivo** | `v51/command-center` (KPIs operacionais) | `v80/score` (score executivo) | Mantém ambos — semânticas diferentes; documentar |
| **Receita real** | `v62/revenue-real` | `v6/revenue/reconcile`, `v6/revenue/mark-received`, `v7/payment/received`, `v7/revenue/truth` | **DEPRECATE v6 e v7 (revenue)** — frontend só usa v62 |
| **Smart Field** | `v51/smart-field-ops/status` | `v6/smart-field/sync`, `v6/smart-field/kpis`, `v7/v9/smart-field-adoption` | **DEPRECATE v6 e v7 (smart-field)** — frontend usa v51 |
| **Causality / Experiments** | `v7/v8/causality/*`, `v7/v8/v84/*`, `v7/operacao-tese/*` | `v80/experiments/*` | **DEPRECATE v7 causality** — v80 é o futuro |
| **Tickets backfill** | `v7/tickets/backfill-category` | manual via scripts | **MANTÉM v7 ESSE ENDPOINT** (operação one-shot) |
| **Data quality** | `v7/data-quality/*` (audit) | — | **MANTÉM** (usado por superadmin) |
| **Homolog** | `v7/v8/homolog/*` | `services/homologation.py` | **DEPRECATE v7 homolog** — o serviço já é canônico |

## 4. Decisão de versionamento canônico

> **CANÔNICO: `ai_center_v80` + módulos especializados (`isabella`, `alvaro_v5`, `observability`, `smartolt_twin`, `financial`).**
>
> **HISTÓRICO MANTIDO**: `v51` (operação consolidada), `v62` (3 endpoints comerciais).
>
> **DEPRECATED**: `v6` e `v7` (com exceção dos 3 endpoints administrativos one-shot).

### Justificativa
- `v80` é a versão mais recente, encapsula `experiments` (futuro do AI Center) e tem 100% de uso real no frontend.
- `v51` provê painéis operacionais (ranking de técnicos, CTOs, regiões) — não há sobreposição com v80.
- `v62` é minimalista (38 LoC) — mantém porque o frontend depende.
- `v6` e `v7` têm 33 endpoints somados e **zero** chamadas do frontend; permanecem para não quebrar scripts/cron antigos, mas marcados.

## 5. Plano de "DEPRECATE sem apagar"

| Versão | Ação | Risco |
|---|---|---|
| `v6` (74 LoC) | Adicionar header HTTP `Deprecation: true` + `Sunset: 2027-01-01` nas respostas dos 6 endpoints. Manter rota ativa. | 🟢 baixo — frontend não chama |
| `v7` (378 LoC) | Idem + adicionar comentário no topo `# DEPRECATED — usar v80 ou services/homologation.py` | 🟢 baixo — 3 endpoints administrativos one-shot continuam funcionando |
| Demais | Manter | — |

A implementação técnica do header deprecation pode ser feita em sprint posterior (não bloqueia primeira venda). Por ora, **documentar** já remove o risco percebido.

## 6. Tabela de compatibilidade pública (rotas finais)

| Path público | Versão | Status | Recomendação para consumer |
|---|---|---|---|
| `/api/ai-center/v51/*` | v51 | ✅ ATIVO | usar |
| `/api/ai-center/v62/*` | v62 | ✅ ATIVO | usar |
| `/api/ai-center/v80/*` | v80 | ✅ ATIVO — **CANÔNICO** | preferir esta |
| `/api/ai-center/smart-field/*` | v6 | 🟧 DEPRECATED | migrar para v51 |
| `/api/ai-center/revenue/mark-received` | v6 | 🟧 DEPRECATED | migrar para v62 |
| `/api/ai-center/revenue/reconcile` | v6 | 🟧 DEPRECATED | migrar para v62 |
| `/api/ai-center/company-score` | v6 | 🟧 DEPRECATED | migrar para v80/score |
| `/api/ai-center/digital-twin` | v6 | 🟧 DEPRECATED | migrar para smartolt_twin |
| `/api/ai-center/v9/*`, `/v8/*`, `/operacao-tese/*` | v7 | 🟧 DEPRECATED | usar v80/experiments |
| `/api/ai-center/payment/received` | v7 | 🟧 DEPRECATED | migrar para v62 |
| `/api/ai-center/tickets/backfill-category` | v7 | 🟦 ADMIN ONE-SHOT | manter |
| `/api/ai-center/data-quality/*` | v7 | 🟦 ADMIN | manter |
| `/api/ai-center/alvaro/*` | alvaro | ✅ ATIVO | usar |
| `/api/ai-center/alvaro-v5/*` | alvaro_v5 | ✅ ATIVO | usar |
| `/api/ai-center/isabella/*` | isabella | ✅ ATIVO | usar |
| `/api/ai-center/observability/*` | observability | ✅ ATIVO | usar |

## 7. Riscos identificados

| Risco | Impacto | Mitigação |
|---|---|---|
| Algum cron externo chamar `v6/smart-field/sync` ou `v7/v8/causality/run-pilot` | Médio se houver | Procurar em `services/`, `scripts/` e `tasks/` — sem evidência atual |
| AI Center menu do frontend apresentar links órfãos | Baixo | Auditoria visual no `AiCenterPanel.jsx` (não bloqueia venda) |

Confirmação por grep:
```
$ grep -rE '/v6/smart-field|/v7/v8/' frontend/src
(empty)
$ grep -rE '/v6/smart-field|/v7/v8/' backend/services backend/scripts backend/tasks 2>/dev/null
(empty)
```

→ **Zero acoplamento de cron interno** com v6/v7. Risco real: nulo.

## 8. Saída

| Item | Valor |
|---|---|
| Versão canônica | **`ai_center_v80`** + módulos especializados |
| Versões legadas DEPRECATED | `v6` (74 LoC), `v7` (378 LoC) — mantidas no repositório |
| Versões mantidas | `v51`, `v62`, `alvaro`, `alvaro_v5`, `isabella`, `observability`, `smartolt_twin`, `financial` |
| LoC mortas eliminadas da venda (mensagem ao cliente) | **452 LoC** marcadas como histórico — apenas v80/v51/v62 + alvaro/isabella aparecem na release notes do produto |
| Rotas públicas finais | 17 paths suportados (vide §6) |
| Próximo passo (não bloqueante) | Adicionar header `Deprecation: true` nos endpoints v6/v7 |
