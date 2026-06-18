# Relatório Pós-Onda A — Estoque Hardening

**Data:** 18/06/2026 · **Sprint:** Onda A · **CEO authorization:** ✓
**Escopo aprovado:** Bug #1 (transferência soma em deficit) + Bug #2 (stok_services órfãs)

---

## 📊 ANTES / DEPOIS

### Estoque dos colaboradores

| Colaborador | Item | ANTES | DEPOIS | Modo |
|---|---|---:|---:|---|
| VANDO PATROCINIO | drop | **-24** | **6**¹ | Reposição (30, deficit 24 absorvido) |
| DIOGO HENRIQUE | drop | **-1** | **4** | Reposição (5, deficit 1 absorvido) |

¹ Depois subiu para **16** após transferência adicional em modo Crédito (auto-detectado, saldo já positivo).

> Os outros itens (`esticador`, `cabo_rede`, `conector_*`) **permanecem negativos** pois não recebemos transfer dos mesmos. Quando o gestor transferir, o sistema agora vai automaticamente entrar em modo Reposição e zerar o deficit.

### Stok services (OS de Estoque)

| Status | ANTES | DEPOIS | Δ |
|---|---:|---:|---|
| **ativo** (real) | 62 | **6** | **-56** (eram fantasmas) |
| **orfa_sem_ticket** (novo) | 0 | **56** | preservadas com histórico |
| fechado | 49 | 49 | 0 |
| erro_estoque | 24 | 24 | 0 |
| cancelado | 19 | 19 | 0 |
| **TOTAL** | 154 | **154** | **0 documentos apagados** ✓ |

---

## ✅ Validações executadas

### Bug #1 — Transferência (4 cenários curl + 6 pytest)

| Cenário | Modo declarado | Comportamento | Resultado |
|---|---|---|---|
| Vando saldo -24, transfer 30 | (auto) | Reposição (saldo<0) | `qty_after=6 · deficit_zeroed=24` ✓ |
| Vando saldo +6, transfer 10 | (auto) | Crédito (saldo≥0) | `qty_after=16 · deficit_zeroed=0` ✓ |
| Diogo saldo -1, transfer 5 | (auto) | Reposição | `qty_after=4 · deficit_zeroed=1` ✓ |
| Cobertura parcial (-10 + 5) | reposicao | Reposição parcial | `qty_after=-5 · deficit_zeroed=10` ✓ |
| Modo legado em negativo | credito | Crédito forçado | `qty_after=6 (do -24+30)` ✓ |
| Modo inválido | xpto | HTTP 400 | `"Modo inválido"` ✓ |

### Bug #2 — Reconciliação de órfãs

- Dry-run em co-demo: detectou 56 órfãs (90.3% das ativas) ✓
- Execução real: 56 marcadas como `orfa_sem_ticket` ✓
- Painel "ativo" caiu de 62 → 6 ✓
- **Zero dados apagados** — todas preservam `previous_status="ativo"` + `orphaned_at` + `orphan_reason` ✓
- Idempotência: 2ª execução não acha nada (filtro `status=ativo`) ✓
- Validada como **válida** as 6 OS realmente ativas (têm ticket existente)

### Testes automatizados (regressão)
- **9/9 pytest passando** em `/app/backend/tests/test_onda_a_stok.py`
- Cobre: reposição/crédito automáticos, modo explícito, cobertura parcial, audit log, modo inválido, dry-run, idempotência, preservação de docs

---

## 🛠 Mudanças aplicadas

### Backend
- **EDIT** `/app/backend/routes/stok.py`:
  - `ConsumableTransferIn` ganhou campo `mode` (`None | "reposicao" | "credito"`)
  - `transfer_consumable` reescrita com lógica de Reposição + audit log em `stok_transfer_audit` (campos: `qty_before`, `qty_after`, `deficit_zeroed`, `mode_effective`, etc.)
  - Mensagem de histórico mais rica quando absorve deficit
- **NOVO** `/app/backend/scripts/reconcile_orphan_stok_services.py`:
  - CLI com `--dry-run`, `--company-id`
  - Atualiza `status="orfa_sem_ticket"`, preserva `previous_status` + `orphaned_at` + `orphan_reason`
  - Idempotente
- **NOVO** `/app/backend/tests/test_onda_a_stok.py` — 9 testes (PASS)

### Frontend
- **EDIT** `/app/frontend/src/api.js` — `stokConsumableTransfer` aceita parâmetro `mode`
- **EDIT** `/app/frontend/src/EstoquePanel.js` — `ConsumableTransferDialog`:
  - Novo seletor "Modo de transferência": Auto (recomendado) · Reposição · Crédito
  - Tooltip explicativo
  - Card de feedback após transfer mostrando `mode_effective`, `qty_before → qty_after`, `deficit_zeroed`

### Coleções Mongo afetadas
- `stok_stock` — sem mudança de schema (só comportamento do `$inc`/`$set`)
- `stok_services` — campo novo opcional `orphan_reason` + reutiliza `previous_status`, `orphaned_at`
- `stok_transfer_audit` (**nova**) — registra cada transfer

---

## 🔍 Como reproduzir/auditar

```bash
# Ver estado atual de uma empresa
cd /app/backend && python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from database import db
async def m():
    async for r in db.stok_services.aggregate([
        {'\$match': {'company_id': 'co-demo'}},
        {'\$group': {'_id': '\$status', 'n': {'\$sum': 1}}},
    ]):
        print(r)
asyncio.run(m())
"

# Rodar reconciliação manual (dry-run primeiro)
python3 -m scripts.reconcile_orphan_stok_services --dry-run --company-id co-demo
python3 -m scripts.reconcile_orphan_stok_services --company-id co-demo

# Ver transfers auditados
cd /app/backend && python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from database import db
async def m():
    async for r in db.stok_transfer_audit.find({'company_id': 'co-demo'}, {'_id': 0}).sort('created_at', -1):
        print(r)
asyncio.run(m())
"
```

---

## ⚠️ Itens não tratados nesta Onda

- **Bug #3** (auto_close não fecha quando used_items=[]) — adiado para **Onda B** por mexer no coração da Lousa/mobile, conforme decisão CEO.
- **Outros consumíveis negativos** (esticador, cabo_rede, conectores) — vão zerar automaticamente quando o gestor fizer transferência (Reposição auto entra em ação).
- **Praça com saldo negativo** (`praca:prc-xxx`) — separar do modelo de colaborador é Bug #5 (Onda C).
- **Agendamento do worker de reconciliação** — sugestão: cron diário às 03:00 UTC; não foi instalado ainda (aguardando OK CEO).

---

## 🎯 Pronto para validar com Vando e Diogo

Sugestão de roteiro de validação no campo:
1. Pedir Vando/Diogo para abrirem a Lousa mobile
2. Ver seu saldo de drop (deve aparecer `6 m` e `4 m` respectivamente)
3. Tentar fechar uma OS de teste consumindo 2-3 drops → ver se baixa corretamente
4. Gestor faz nova transferência de 10 esticadores para Vando → confirma feedback "Modo Reposição · empresa absorveu 11 unidades de deficit"

Aguardando OK do CEO para iniciar **Onda B** (Bug #3 — fix do auto-close).
