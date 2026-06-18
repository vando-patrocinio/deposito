# AUDITORIA — Aba Estoque + Fluxo Lousa Mobile

**Data:** 18/06/2026 · **Auditor:** Agente E1 · **Empresa:** co-demo
**Solicitação CTO:** "ONT/ONU e insumos não estão sendo baixados do estoque,
colaboradores sem estoque tendo acabado de lançar estoque para ele, analise
pontas soltas, bugs, fluxo da lousa mobile."

---

## SUMÁRIO EXECUTIVO

Identifiquei **7 bugs estruturais** ativos no fluxo Estoque ↔ Lousa Mobile.
Os 3 mais críticos explicam diretamente a queixa do CTO. Recomendo
endereçá-los em sequência fixa (ordem importa por dependências):

| # | Bug | Severidade | Impacto operacional |
|---|---|---|---|
| **1** | **Transferência empresa→técnico SOMA ao saldo negativo** (não zera) | 🔴 P0 | "Colaborador sem estoque mesmo após receber" |
| **2** | **Stok_services órfãs sem ticket** (13 de 15 ativas) | 🔴 P0 | OS aparecem "pendentes" infinitamente no painel |
| **3** | **Auto_close NÃO fecha stok_service quando used_items=[]** | 🔴 P0 | OS de rompimento/reparo nunca saem do "ativo" |
| **4** | **completion_data zerado pelos técnicos** (Σ qtd=0 em 7/8 OS recentes) | 🟡 P1 | Insumos consumidos não baixam |
| **5** | **Praça mistura location com colaborador** (`praca:prc-xxx` em `stok_stock`) | 🟡 P1 | Saldo negativo "-240 drop" em praça |
| **6** | **ONT swap em reparo só detecta se técnico preencher old/new manualmente** | 🟡 P1 | Trocas de equipamento sem rastro |
| **7** | **`auto_close_legacy_observability` com ZERO records all-time** | 🟢 P2 | Sem visibilidade do flow legado |

---

## BUG #1 (P0) — Transferência empresa→técnico SOMA ao saldo negativo

### Evidência factual
Estado atual de 3 colaboradores em `co-demo`:
```
DIOGO HENRIQUE      drop=-1   conector_fast=-2  esticador=-1   conector_rede=-2  cabo_rede=-10
VANDO PATROCINIO    drop=-24  conector_fast=-4  esticador=-11  conector_rede=-2  cabo_rede=-10
praca:prc-5160      drop=-240 conector_fast=-6                                                  ⚠️
```

### Código culpado
`/app/backend/routes/stok.py` linha 1366-1371:
```python
await db.stok_stock.update_one(
    {"company_id": cid, "location": payload.technician_id},
    {"$inc": {item["id"]: payload.quantity},   # ← SOMA, não SETA
     "$setOnInsert": {...}},
    upsert=True,
)
```

### Comportamento observado
- Técnico tem `drop=-24` (quebra acumulada de OS anteriores)
- Gestor transfere 10 unidades
- Sistema executa `$inc: +10` → resultado: `-14` (ainda negativo)
- UI mobile chama `c.qty` direto → mostra "-14" ou trunca para "0"
- Técnico vê "0 estoque mesmo após receber transferência" ← **queixa do CTO**

### Fix sugerido (P0, ~1h)
Quando o transfer detectar saldo atual NEGATIVO, oferecer 2 modos:
- **Modo "Reposição"** (padrão): zera o deficit primeiro, sobra vira saldo positivo.
- **Modo "Crédito"** (atual): `$inc` mantém o deficit.

Implementação:
```python
# Lê saldo atual
tech_stock = await db.stok_stock.find_one({...})
current_qty = int(tech_stock.get(item["id"], 0)) if tech_stock else 0

if payload.mode == "reposicao" or (current_qty < 0 and payload.mode is None):
    # Zera deficit + soma o que sobrou
    new_qty = max(0, current_qty + payload.quantity)
    await db.stok_stock.update_one(
        {"company_id": cid, "location": payload.technician_id},
        {"$set": {item["id"]: new_qty}, ...},
        upsert=True,
    )
    # registra o ajuste de quebra perdoada em audit
```

Adicionar campo `mode` no `ConsumableTransferIn` + checkbox no frontend
"☑ Zerar deficit antes de creditar (recomendado)".

---

## BUG #2 (P0) — Stok_services órfãs sem ticket

### Evidência factual
Query em `stok_services` com `status=ativo`:
- **15 ativas no total**
- **13 com `ticket_id` apontando para ticket INEXISTENTE** (deletado/migrado)
- Apenas 2 com ticket real, e dessas 1 já está finalizada (`tkt-7b5eff4fe1`)

Exemplo:
```
OS-279340 · type=instalacao · tech=col-demo-001
   ticket=tkt-cf4ae991c7 → None (ticket não existe)
OS-0C8D30 · type=instalacao · tech=col-demo-001
   ticket=tkt-fa23e9d16a → None
... (repete 11x)
```

### Causa raiz
- `auto_open_service_for_ticket` cria `stok_services` quando técnico abre OS.
- **Tickets foram apagados** (algum job de limpeza? Reset de demo? Soft-delete?)
- A função NÃO tem cascade que limpe stok_services órfãs.

### Fix sugerido (P0, ~30min)
**Worker de reconciliação noturno**:
```python
async def reconcile_orphan_stok_services():
    """Marca stok_services como 'orfa' quando o ticket associado não existe."""
    async for s in db.stok_services.find({"status": "ativo", "ticket_id": {"$exists": True}}):
        t = await db.tickets.find_one({"id": s["ticket_id"], "company_id": s["company_id"]})
        if not t:
            await db.stok_services.update_one(
                {"id": s["id"]},
                {"$set": {"status": "orfa_sem_ticket", "orphaned_at": now_iso()}},
            )
```

Rodar 1x e agendar diário. Status `orfa_sem_ticket` é exibido na UI como
"OS órfã — ticket não encontrado" + ação "Encerrar".

---

## BUG #3 (P0) — Auto-close não fecha stok_service quando used_items=[]

### Evidência factual
Ticket `tkt-7b5eff4fe1` (rompimento de TEST_Cliente Rompimento):
- Criado: `2026-06-08T22:54:11.037`
- Stok_service auto-criado: `2026-06-08T22:54:11.141` ✓
- Ticket finalizado (`outcome=sucesso`): `2026-06-08T22:54:14.319`
- **Stok_service AINDA `status=ativo`** sem flag `auto_closed` ou `ticket_finalized` ← bug

### Causa raiz suspeitada
O ticket tem `qtd_drop=0, esticadores=0, ... ont=None`. O flow:
1. `public_finalize_ticket` chama `enforce_os_inventory_movement` (guardrail).
2. Como `outcome=sucesso` e tipo `rompimento` NÃO está em `OS_TYPES_PHYSICAL`
   (= `("instalacao", "retirada", "troca", "reparo")`), o guardrail PROVAVELMENTE
   retorna `allowed=True` sem movimento, OU bloqueia.
3. Depois deveria chamar `auto_close_service_from_ticket` (linha 4854 `lousa.py`).
4. **Coleção `auto_close_legacy_observability` = 0 records all-time** → função
   nunca foi chamada para esse ticket (ou a observability foi adicionada DEPOIS
   do close, mas mesmo close anteriores deveriam ter algum trace).

### Hipóteses (preciso testar uma de cada vez)
- **H1**: `enforce_os_inventory_movement` lança HTTPException 403 para
  `rompimento` (não físico) e a finalize retorna 403 → ticket fica
  finalizado por OUTRO caminho? Improvável dado que finalized_at está setado.
- **H2**: O try/except em `lousa.py:4853-4864` engole a exception silenciosa.
  Mas import works fine localmente, ent não é import error.
- **H3**: O fluxo de finalize tem `manager_callback_required` ou outro
  short-circuit que pula o auto_close.
- **H4**: Algum middleware/decorator está abortando o request após o
  `update_one(tickets)` (linha 4689) e antes do auto_close (4854).

### Fix sugerido (P0, ~3h — requer instrumentação)
1. **Instrumentar `public_finalize_ticket`** com logger.info("PHASE:X")
   em 6 pontos críticos (entrou guardrail, saiu guardrail, antes auto_close,
   dentro auto_close, antes return).
2. **Forçar 1 close de rompimento via curl** e ler logs.
3. **Aplicar fix dirigido** (provavelmente reorganizar try/except para
   propagar a exception OU fazer observability gravar SEMPRE antes do close).
4. **Worker complementar**: a cada 5min, qualquer `stok_services` ativo cujo
   ticket associado está `finalizada` há > 60s → fecha automaticamente
   com motivo "auto_close_late_reconciliation".

---

## BUG #4 (P1) — Técnicos não preenchem consumíveis

### Evidência factual
8 últimos tickets finalizados:
- 1 com dados válidos (`tkt-640d8e0d19` reparo · drop=23, esticadores=10, conectores_fast=2)
- **7 com TODOS os campos = 0** (rompimento + reparo)

### Causa raiz
- Os campos consumíveis em `LousaMobile.js:4275-4321` são exibidos para TODOS
  os tipos de OS, MAS começam com valor 0 e o técnico pode finalizar sem alterar.
- **Não há validação obrigatória**: se a OS é tipo "instalação" → pelo menos drop
  e conectores deveriam ser > 0; se é "retirada" → talvez 0 seja ok mas precisa
  marcar "sem insumos".

### Fix sugerido (P1, ~2h)
Adicionar validação por TIPO no botão Finalizar:
```js
const isPhysical = ["instalacao","troca","ponto_adicional","reparo"].includes(ticket.type);
const sumConsumables = qtd_drop + esticadores + conectores_fast + cabo_rede + conectores_rede;
if (isPhysical && sumConsumables === 0) {
  if (!window.confirm(
    "Você está fechando uma OS física sem informar nenhum insumo.\n\n" +
    "Confirma que NÃO usou drop, esticador, conector ou cabo?"
  )) return;
}
```

E logar `cd.no_consumables_confirmed=true` quando o técnico confirmar — gestor
vê isso no Watchtower Estoque com flag específica.

---

## BUG #5 (P1) — Mistura location praça + colaborador em `stok_stock`

### Evidência factual
```
location="empresa"                  ← warehouse principal
location="col-30aafc3c"             ← colaborador
location="praca:prc-5160ebf92d"    ← praça (formato com prefixo)
```

### Por que é problema
- `public_get_collaborator_stock` busca por `location=collaborator_id` direto.
- `transfer_consumable` aceita `technician_id` mas não valida prefix.
- Algum lugar (purchases?) está criando docs com `location="praca:xxx"`
  e bagunçando o modelo.

### Fix sugerido (P1, ~1h)
- Separar em 2 coleções: `stok_stock_warehouses` (empresa+praça) e `stok_stock_techs` (colaboradores).
- OU adicionar campo `location_type` ∈ `{empresa, praca, tecnico}` e validar.

---

## BUG #6 (P1) — Troca de ONT em reparo sem rastro automático

### Evidência factual
- `equipment_swap` só é detectado se técnico explicitamente marcar
  `isSwap=ON` e preencher `old_ont_mac` + `new_ont_mac` no app.
- Auto-detecção via SmartOLT cache existe mas é frágil (tempo de propagação).

### Impacto
- Técnico troca ONT durante reparo sem registrar → ONT antiga fica como
  "instalada" no cliente, ONT nova fica como "com_tecnico" sem evidência.
- ONT antiga começa a aparecer "online" no SmartOLT como cliente que NÃO
  é mais dela → bug de rastreabilidade.

### Fix sugerido (P1, ~2h)
- Quando técnico digita um MAC/SN NO CAMPO "ont" e a OS é de reparo, o backend
  compara contra a ONT atualmente em uso pelo cliente. Se for diferente,
  **automaticamente** abre o flow de equipment_swap (old=ONT atual, new=ONT escaneada).
- Adicionar prompt no app: "Detectei que você escaneou uma ONT diferente da
  que o cliente tinha. É uma troca?" [Sim, troquei] [Não, foi erro].

---

## BUG #7 (P2) — Observability sem records

### Evidência factual
`auto_close_legacy_observability` = 0 documents all-time, mas pelo menos
`OS-E6AED7` (close auto-realizado em 13/06) provou que a função roda.

### Causa provável
A observability foi adicionada DEPOIS do close. Mas mesmo assim, nenhum close
posterior gerou record — indicando que a função NÃO está sendo chamada
desde então (relacionado ao Bug #3).

### Fix
Resolver Bug #3 primeiro. A observability vai voltar a gravar.

---

## RECOMENDAÇÃO DE EXECUÇÃO

Sugiro encarar em **3 ondas**:

### Onda A — quick wins operacionais (P0, ~2h)
- Bug #1 (transferência → zerar deficit)
- Bug #2 (worker de órfãs)

### Onda B — fix do flow core (P0, ~3h)
- Bug #3 (auto-close não fecha) — requer instrumentação + fix dirigido
- Bug #7 vem de brinde

### Onda C — endurecimento operacional (P1, ~4h)
- Bug #4 (validar consumíveis no mobile)
- Bug #5 (separar praça/técnico)
- Bug #6 (auto-detect troca de ONT)

**Total estimado: ~9h em 3 sessões.**

Recomendação CTO: começar pela **Onda A** (libera técnicos a operar sem
sair sem estoque imediato + limpa o painel de OS-fantasmas), validar com
o técnico Vando ou Diogo, e depois ir pra Onda B.
