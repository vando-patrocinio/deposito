# ESTOQUE OPERACIONAL — ONDA 0 — BLINDAGEM DO FLUXO PRINCIPAL DE OS

**Tipo:** Auditoria estática + medição de tráfego READ-ONLY.  
**Data:** 16/Fev/2026  
**Autor:** Auditor automatizado (CTO Mode) — ordem direta do CEO.  
**Mandato:** Provar que **100% das finalizações de OS** passam por `inventory_movements.write_movement()` ou `enforce_os_inventory_movement()`.  
**Sem código. Sem migração. Apenas relatório.**

---

## §1. SUMÁRIO EXECUTIVO

| Caminho de finalização | Volume 30d | Passa guardrail? | Cor |
|--------------------------|------------|------------------|-----|
| `POST /lousa/public/tickets/{id}/finalize` (PWA público, técnico) | 122* | ✅ SIM (após Fase 0) | 🟢 |
| `POST /lousa/tickets/{id}/finalize` (autenticado JWT) | 0** | ❌ **NÃO** — chokepoint AUSENTE | 🔴 |
| `POST /lousa/tickets/{id}/admin-close` (gestor encerra) | 5 | ✅ SIM (action=encerrar) | 🟢 |
| `auto_close_service_from_ticket` (legado, em paralelo) | 127 (todas) | ❌ **NÃO** — paralelo ao guardrail | 🔴 |
| `POST /api/stok/services/{id}/close` (rota direta de service) | n/a (legado) | ❌ NÃO | 🔴 |

\* Estimado: total 127 menos os 5 admin-close.  
\*\* Tráfego é zero porque o app moderno autenticado provavelmente não está em uso real ainda — mas o **handler está exposto** e funciona sem o chokepoint.

### Veredicto

**❌ NÃO PODE entrar na Fase 3.** Existem **3 portas patrimoniais paralelas ainda abertas** no fluxo diário de OS:

1. **`finalize_ticket` (handler JWT privado)** — não tem guardrail.
2. **`auto_close_service_from_ticket` (legado de `stok.py`)** — roda em paralelo, sem trilha canônica.
3. **`/api/stok/services/{id}/close`** — rota direta de service (legado).

---

## §2. MATRIZ DE CHAMADAS (CALL GRAPH REAL)

### 2.1 Fluxo do PWA público (técnico via app PWA — sem JWT)

```
PWA (técnico)
   │
   └─→ POST /lousa/public/tickets/{id}/finalize        [lousa.py:3841]
         │
         ├─ valida ticket + outcome
         │
         ├─ 🟢 IF outcome=="sucesso" AND not is_admin_test:
         │        enforce_os_inventory_movement(...)   [Fase 0 patch — OK]
         │        ↓ grava em inventory_os_movements_audit ✅
         │
         ├─ db.tickets.update_one({"status":"finalizada"})
         │
         └─ 🔴 IF outcome=="sucesso":
                 from routes.stok import auto_close_service_from_ticket
                 await auto_close_service_from_ticket(...)
                       │
                       ├─ _move_ont_for_install   [stok.py:1402]  → stok_onts.update_one  ❌ s/ trilha
                       ├─ _move_ont_for_withdraw  [stok.py:1597]  → stok_onts.update/insert ❌ s/ trilha
                       └─ NUNCA grava em inventory_os_movements_audit
```

**Resultado:** mesmo finalização correta gera **DUAS escritas em `stok_onts`**: uma pelo guardrail e outra pelo legado. Se as duas movem para owners diferentes, o estado fica indefinido.

### 2.2 Fluxo do app autenticado (não-PWA)

```
App técnico (JWT)
   │
   └─→ POST /lousa/tickets/{id}/finalize               [lousa.py:4909]
         │
         ├─ valida ticket
         │
         ├─ db.tickets.update_one({"status":"finalizada"})
         │
         ├─ ❌ Nenhuma chamada a enforce_os_inventory_movement
         ├─ ❌ Nenhuma chamada a inventory_movements.write_movement
         │
         └─ termina sem trilha patrimonial ⚠️
```

**Resultado:** caminho **totalmente sem chokepoint**. Se este handler ganhar tráfego (ex.: novo app de técnico mobile), a Fase 2 inteira é contornada.

### 2.3 Fluxo do gestor (admin-close)

```
Gestor (JWT, role=gestor)
   │
   └─→ POST /lousa/tickets/{id}/admin-close            [lousa.py:5280]
         │
         ├─ 🟢 IF action=="encerrar":
         │        enforce_os_inventory_movement(...)   [OK]
         │        ↓ grava em inventory_os_movements_audit ✅
         │
         ├─ db.tickets.update_one({"status":"encerrada"})
         │
         ├─ IF tipo=retirada AND tem ont/ont_sn:
         │     🔴 await auto_close_service_from_ticket(...)
         │            ↓ s/ trilha canônica ❌
         │
         └─ IF tipo=instalacao AND tem ont/ont_sn:
                🔴 await auto_close_service_from_ticket(...)
                      ↓ s/ trilha canônica ❌
```

**Resultado:** mesmo passando pelo guardrail, AINDA dispara o legado em paralelo. Duplo write.

### 2.4 Reabertura de ticket

```
Admin
   │
   └─→ POST /lousa/tickets/{id}/reopen                 [lousa.py:3192]
         │
         └─ chama _revert_ticket_side_effects(...)      [lousa.py:2980+3036]
              │
              ├─ db.stok_onts.update_one(reverte status p/ "disponivel")  🔴
              └─ ❌ Nenhum movimento reverso na trilha canônica
```

**Resultado:** reabertura silenciosamente reverte estoque sem deixar movimento na trilha. Após reabrir e finalizar de novo, o estado intermediário some.

### 2.5 Rota legada de service direto

```
Qualquer chamador autorizado
   │
   └─→ POST /api/stok/services/{service_id}/close      [stok.py:1986]
         │
         ├─ executa _move_ont_for_install / _move_ont_for_withdraw
         ├─ executa stok_history.insert_one (log antigo)
         └─ ❌ Nenhum write em inventory_movements
```

**Resultado:** ponto de entrada paralelo ao app de técnico. Não conheço chamador atual mas a rota está exposta no FastAPI.

---

## §3. TRÁFEGO MEDIDO (últimos 30 dias — produção)

```
Finalizações outcome=sucesso (físicas):  127 / 30d  (≈ 4,2/dia)
  • instalações:   69 (54%)
  • reparos:       34 (27%)
  • retiradas:     20 (16%)
  • rompimentos:    4  (3%)

Com snapshot guardrail (`os_inventory_guardrail` field):    0
SEM snapshot guardrail (bypass):                          127

stok_services impacto histórico:
  • status=erro_estoque (legado falhou):     24
  • status=ativo (nunca fechou):             62  ← débito acumulado

admin-close (action=encerrar):              5 / 30d
```

> **A causa de 127/127 sem guardrail é o bug P0 já corrigido em 16/Fev.** Daqui pra frente as 127 entrariam pela trilha — MAS o legado `auto_close_service_from_ticket` continua duplicando o write em paralelo.

> **Projeção pós-Onda 0**: trilha 100% do fluxo diário. Sem Onda 0, mesmo após Fase 2, o legado seguirá poluindo `stok_onts` em paralelo, gerando dessincronia entre estado físico e trilha canônica.

---

## §4. PONTOS DE BYPASS — LISTA FINAL DA ONDA 0

| # | Arquivo | Linhas | Função | Tráfego | Risco | Ação proposta |
|---|---------|--------|--------|---------|-------|----------------|
| 1 | `routes/lousa.py` | 4909-5024 | `finalize_ticket` (handler JWT) | 0 hoje, exposto | 🔴 CRÍTICO | Inserir chokepoint idêntico ao do `public_finalize_ticket` |
| 2 | `routes/stok.py` | 2287-2500 | `auto_close_service_from_ticket` (legado bridge) | 127/30d | 🔴 CRÍTICO | Sunset gradual: marcar `@deprecated`, remover chamadas dos 3 lugares no `lousa.py` (4663, 5488, 5550) |
| 3 | `routes/stok.py` | 1402-1593 | `_move_ont_for_install` | indireto via #2 | 🔴 ALTO | Morre junto com #2 |
| 4 | `routes/stok.py` | 1597-1750 | `_move_ont_for_withdraw` | indireto via #2 | 🔴 ALTO | Morre junto com #2 |
| 5 | `routes/stok.py` | 1986 | `POST /services/{id}/close` (rota direta) | desconhecido | 🔴 ALTO | Auditar chamadores em runtime (header `X-Caller`?), depois sunset |
| 6 | `routes/lousa.py` | 2980+3036 | `_revert_ticket_side_effects` (reopen) | freq baixa, alto impacto | 🔴 ALTO | Gravar movimento reverso explícito antes de mutar `stok_onts` |

**Total Onda 0:** 6 pontos · 4 arquivos · ~250-400 linhas afetadas.

---

## §5. PLANO DE CORREÇÃO ONDA 0 (sem código nesta fase)

### Etapa 1 — Patch surgical de 1 linha + 1 import (Onda 0a)
Adicionar o mesmo chokepoint da linha 4456 no `finalize_ticket` privado:
```python
guardrail_result = None
if payload.outcome == "sucesso":
    from services.os_inventory_guardrail import (
        enforce_os_inventory_movement, explain_block,
    )
    # ... idêntico ao public_finalize_ticket
```
**Esforço:** 15 min · **Risco:** zero (espelha código já validado) · **Cobertura ganho:** 0% → 100% deste handler.

### Etapa 2 — Sunset do `auto_close_service_from_ticket` (Onda 0b)
1. Marcar `@deprecated` na docstring + warning runtime.
2. Confirmar que o guardrail novo já cobre 100% dos casos que o legado cobria (instalação, retirada, troca, defeito). Onde houver gap, **estender o guardrail**, não manter o legado.
3. Remover as 3 chamadas do `lousa.py` (linhas 4663, 5488, 5550) **uma a uma**, validando cada uma em produção por 24h.
4. Quando tráfego = 0 por 7 dias, deletar fisicamente a função.

**Esforço:** 2-3 dias com observação · **Risco:** médio (pode quebrar fluxos edge-case) · **Cobertura:** elimina double-write.

### Etapa 3 — Investigar `/api/stok/services/{id}/close` (Onda 0c)
- Logar todos os callers em produção por 7 dias (header / referer).
- Se 0 callers → deletar rota.
- Se há callers → migrar para chamar `enforce_os_inventory_movement` antes da execução.

**Esforço:** 1 semana observação + 1 dia patch · **Risco:** baixo.

### Etapa 4 — Movimento reverso explícito no reopen (Onda 0d)
- Em `_revert_ticket_side_effects`, antes de mutar `stok_onts`, chamar `inventory_movements.write_movement(...)` com `movement_type="manual_transfer_*"` (ou criar um novo `"ticket_reopen_revert"`) explicando a reversão.

**Esforço:** 30 min · **Risco:** baixo.

---

## §6. CRITÉRIO DE ACEITE DA ONDA 0

A Onda 0 está concluída quando:

1. ✅ Todos os 4 handlers de finalização (`finalize_ticket`, `public_finalize_ticket`, `admin_close_ticket`, `reopen`) **chamam** o guardrail/helper canônico.
2. ✅ `auto_close_service_from_ticket` está **deprecated** e **0 callers** em produção por 7 dias seguidos.
3. ✅ `/api/stok/services/{id}/close` está deletado ou também canalizado.
4. ✅ Próximas 24h após patch: `count_documents({"os_inventory_guardrail":{"$exists":True}, "status":"finalizada"}) / count_documents({"status":"finalizada", "closed_at":{"$gte":patch_date}})` = 1.0.

---

## §7. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código. Zero migração.**

- **6 pontos de bypass identificados** no fluxo diário de OS.
- **3 são CRÍTICOS** (`finalize_ticket` privado, `auto_close_service_from_ticket`, `/services/{id}/close`).
- **2 são ALTOS** (`_move_ont_for_*` helpers do legado).
- **1 é ALTO** (`_revert_ticket_side_effects` no reopen).
- **Tráfego diário do fluxo principal: 4,2 OS/dia.** Daqui em diante a Onda 0 garante trilha 100%.
- **Etapas 0a-0d esboçadas** com esforço estimado, risco e critério de aceite mensurável.

### Decisões necessárias do CEO

- A) **Aprovar Onda 0a (patch 15 min em `finalize_ticket` privado)** primeiro — risco zero, ganho imediato.
- B) Aprovar Onda 0a+0b (sunset do legado) em sequência — recomendação CTO.
- C) Adicionar/remover ponto da matriz antes da execução.
- D) Outra prioridade.
