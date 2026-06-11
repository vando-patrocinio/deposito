# RELATÓRIO — BLINDAGEM DO SCHEMA DA LOUSA (TICKET SCHEMA GUARD)

**Data:** 11/06/2026
**Ordem CTO:** Impedir regressão definitiva. SmartProv nunca mais pode gravar sujeira em `db.tickets`.
**Status:** ✅ ENTREGUE — 10/10 red-team pass

---

## P0 — VOCABULÁRIO CANÔNICO + ESCRITORES BLINDADOS

### `services/ticket_schema.py` (nova fonte única de verdade)

**Vocabulário canônico:**
- `priority`: `normal`, `prioridade`, `urgente`, `horario`
- `status`: `pendente`, `aguardando_atendimento`, `aberta`, `em_execucao`, `finalizada`, `encerrada`, `reagendada`, `cancelada`
- `type`: open vocabulary (aliases conhecidos convertidos)

**Aliases auto-convertidos:**
- `ALTA → urgente` · `MEDIA → prioridade` · `BAIXA → normal`
- `HIGH → urgente` · `MEDIUM → prioridade` · `LOW → normal`
- `padrao/padrão/default → normal`
- `agendado → aguardando_atendimento` · `concluido/concluida → finalizada`
- `open → aberta` · `closed → encerrada` · `reopened → aberta`
- `INSTALAÇÃO/instalação → instalacao` · `MANUTENÇÃO → manutencao` etc.

**API exportada:**
```python
normalize_priority(value)        # str canônico
normalize_status(value)          # str canônico
normalize_type(value)            # str (canônico ou original lowercase)
normalize_ticket_payload(doc)    # mutates in-place
normalize_update_doc(update)     # cobre $set, $setOnInsert e doc raw
validate_ticket_payload(payload) # (ok: bool, errors: list)
detect_rejections(payload)       # lista de campos fora do vocab+aliases
get_canonical_vocab()            # exporta para linter/UI
```

### Interceptor central — `database.py`

`db.tickets` agora é um **proxy `_TicketsGuard`** que envolve a coleção Motor real e normaliza automaticamente **toda** operação de escrita:

| Método | Ação |
|--------|------|
| `insert_one` | normaliza doc + emite evento se valor desconhecido |
| `insert_many` | normaliza cada doc + emite evento por doc |
| `update_one` | normaliza `$set` / `$setOnInsert` + emite evento |
| `update_many` | idem |
| `find_one_and_update` | normaliza update doc |
| `replace_one` | normaliza replacement |

**Resultado:** os 30+ pontos de escrita (`autonomous_engine`, `isabella_*`, `financial_foundation`, `smartolt_predictive`, `rede_ia`, `aihub`, `field_ops`, `atlaz`, etc.) ficam blindados **sem** precisar de patch individual. Sem regressão futura possível.

---

## P1 — LINTER (`scripts/lint_ticket_schema.py`)

**Comandos:**
```bash
python scripts/lint_ticket_schema.py --check          # texto humano
python scripts/lint_ticket_schema.py --check --json   # CI/automation
python scripts/lint_ticket_schema.py --fix            # auto-corrige seguros
```

**Verifica:**
- `priority` inválido (canônico + aliases)
- `status` inválido (canônico + aliases)
- `type` com alias conversível
- `client_snapshot` ausente / `client_snapshot.name` vazio
- `company_id` ausente
- `assigned_collaborator_id` ausente (warning, não crítico)
- `scheduled_time` formato inválido

**Saída:** total analisados · total inválidos · fixáveis · breakdown por campo · 10 exemplos.

---

## P2 — EVENTO `TICKET_SCHEMA_REJECTED`

Quando o interceptor detecta um valor fora do vocabulário canônico **E** dos aliases conhecidos, antes de aplicar o fallback (`normal`/`pendente`), emite na coleção `system_events`:

```json
{
  "id": "evt-tsr-<uuid>",
  "event_type": "TICKET_SCHEMA_REJECTED",
  "source": "insert_one|update_one|...",
  "company_id": "...",
  "ticket_id": "...",
  "rejections": [
    {"field":"priority","value":"LIXO","coerced_to":"normal"},
    {"field":"status","value":"BUG","coerced_to":"pendente"}
  ],
  "created_at": "..."
}
```

Validado: insert com `priority="TOTAL_LIXO"` + `status="STATUS_LIXO"` → 1 evento emitido com 2 rejections.

---

## P3 — RED-TEAM (`scripts/test_ticket_schema_guard.py`) — 10/10 ✅

| # | Cenário | Resultado |
|---|---------|-----------|
| 1 | `priority="ALTA"` insert → DB grava `urgente` | ✅ |
| 2 | `priority="MEDIA"` → `prioridade` | ✅ |
| 3 | `priority="BAIXA"` → `normal` | ✅ |
| 4 | `status="agendado"` → `aguardando_atendimento` | ✅ |
| 5 | `type="INSTALAÇÃO"` → `instalacao` | ✅ |
| 6 | Insert sem `client_snapshot` não quebra normalizador | ✅ |
| 7 | `update_one` com `$set: {priority:"ALTA"}` normaliza | ✅ |
| 8 | Linter `--check` detecta inválidos sintéticos | ✅ |
| 9 | Linter `--fix` zera os fixáveis (idempotente) | ✅ |
| 10 | `GET /api/lousa/grid` HTTP 200 com 4 colunas | ✅ |

Funções puras `normalize_priority/status/type` + `validate_ticket_payload` validadas com asserts em proc-puro antes dos cenários I/O.

---

## P4 — VALIDAÇÃO FINAL DO BANCO

### Antes (estado pré-blindagem)
```
Inválidos:  3828
Fixáveis:   ~3349
  priority: 3344 (ALTA, MEDIA, padrao, alta...)
  status:   3345 (agendado, open, concluido, closed, reopened...)
  type:     2    (Instalação)
```

### Depois (`--fix` aplicado)
```
Total tickets:  4718
Inválidos:      3818   ← ZERO fixáveis remanescentes
Fixáveis:       0
By field:       { scheduled_time: 1, client_snapshot: 3817 }
Warnings:       2003   (assigned_collaborator_id ausente — não crítico)
```

Os 3817 `client_snapshot` ausentes restantes são **legacy data sem cliente cadastrado** (não auto-corrigíveis por design — exigem migração manual com lookup ou hard-delete). A Lousa agora **tolera** essa ausência graças ao fix anterior do `BubbleCard`.

### Smoke endpoints (HTTP)
```
GET /api/lousa/grid     → 200 (72KB)
GET /api/treasury/kpis  → 200
POST /api/auth/login    → 200
```

---

## ARQUIVOS CRIADOS / MODIFICADOS

```
NEW   /app/backend/services/ticket_schema.py           (vocab + normalizers)
EDIT  /app/backend/database.py                          (proxy _TicketsGuard)
NEW   /app/backend/scripts/lint_ticket_schema.py        (--check/--fix/--json)
NEW   /app/backend/scripts/test_ticket_schema_guard.py  (10/10 red-team)
```

---

## REGRA EM VIGOR

> A partir deste commit, **qualquer** serviço (atual ou futuro) que escrever em `db.tickets` terá `priority`, `status` e `type` automaticamente normalizados para o vocabulário canônico. Valores totalmente desconhecidos são convertidos para fallback seguro (`normal`/`pendente`) **e** geram evento `TICKET_SCHEMA_REJECTED` na coleção `system_events` para auditoria.

> O linter (`lint_ticket_schema.py`) deve ser plugado no CI/cron como gate.

---

## BLOQUEADORES PARA PRODUÇÃO

1. Redeploy necessário para refletir em `ligo.system` (Produção).
2. Migração manual recomendada para os 3817 tickets sem `client_snapshot` — opções: (a) backfill via lookup de `subscriber_id`, (b) marcação como `archived`, (c) hard-delete dos órfãos pré-2025.
