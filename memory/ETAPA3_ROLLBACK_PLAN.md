# ROLLBACK PLAN — Etapa 3 (Ligo Executive OS · Consolidation)

> **Data:** 15/06/2026 · **Aplicável até:** 15/07/2026 (janela de 30 dias)  
> **Tipo:** **REVERSÍVEL** — todas as mudanças têm caminho de volta sem perda de dados.

---

## 1. Renames + stubs

### Status atual
| Módulo canônico (NOVO) | Stub legacy (DEPRECATED) |
|---|---|
| `services/revenue_agent.py` | `services/agent_revenue.py` (stub) |
| `services/revenue_realization.py` | `services/real_revenue.py` (stub) |
| `services/ceo_briefing.py` | `services/presidente_ia_briefing.py` (stub) |

### Rollback total (revogar Etapa 3 inteira)
```bash
cd /app/backend/services
# 1. Apaga stubs
rm agent_revenue.py real_revenue.py presidente_ia_briefing.py
# 2. Renomeia os canônicos de volta para o nome original
mv revenue_agent.py agent_revenue.py
mv revenue_realization.py real_revenue.py
mv ceo_briefing.py presidente_ia_briefing.py
# 3. Reverte 1 import em ceo_briefing -> presidente_ia_briefing
#    (linha 91 hoje lê `from services import revenue_agent as rev`)
sed -i 's/from services import revenue_agent as rev/from services import agent_revenue as rev/' presidente_ia_briefing.py
# 4. Restart
sudo supervisorctl restart backend
```
**Impacto:** zero perda de dados. Volta exatamente ao estado de 15/06/2026 pré-Etapa 3.

### Rollback parcial (manter o novo nome, mas remover o stub)
Útil **somente após 30d** quando o ranking de `[DEPRECATED_CALL]` estiver vazio:
```bash
rm /app/backend/services/{agent_revenue,real_revenue,presidente_ia_briefing}.py
sudo supervisorctl restart backend
```
Qualquer import legacy lança `ModuleNotFoundError` → o ranking semanal já garante zero callers nesse ponto.

---

## 2. Tagging em `executive_ledger`

Aplicado em 2.335 docs sintéticos. Reversível pelo próprio script:

```bash
cd /app/backend
python3 scripts/tag_executive_ledger.py --rollback
```

O comando remove **apenas** os 4 campos adicionados (`synthetic_detected`, `pre_sanitize_2026_06_14`, `_tagged_at`, `_tagged_by`) usando o filtro `_tagged_by="fase_a_etapa3_sanitize"`. Não toca em mais nada.

---

## 3. `deprecated_call_log` collection

Collection nova, append-only. Para limpar tudo:
```python
await db.deprecated_call_log.delete_many({})
```
Ou para limpar entries antigos:
```python
from datetime import datetime, timezone, timedelta
cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
await db.deprecated_call_log.delete_many({"timestamp": {"$lt": cutoff}})
```

---

## 4. Garantias

- ✅ Nenhum delete físico foi feito em nenhum doc real.
- ✅ Nenhuma feature flag foi ativada.
- ✅ Nenhuma UI foi alterada.
- ✅ Customer Intelligence permanece com 3 flags OFF.
- ✅ Isabella e Pamela permanecem inalteradas.
- ✅ Toda mudança tem caminho de volta documentado e idempotente.
