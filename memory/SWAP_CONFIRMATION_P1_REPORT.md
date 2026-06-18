# P1 — Solicitação de Confirmação Patrimonial via WhatsApp · RELATÓRIO
**CEO order**: 18/06/2026 · **Status**: ✅ ENTREGUE · **Testes**: 54/54 PASS

---

## 🎯 O que foi entregue

### Backend (3 endpoints)
1. **`POST /api/swap-confirmation/send/{event_id}`** (auth: gestor/admin/auditor)
   - Valida estado (`pending_confirmation` ou `sent_to_technician` — idempotente).
   - Valida ownership (event.company_id == user.company_id) → 403 se outra empresa.
   - Valida telefone do técnico cadastrado → 400 com `error=technician_without_phone` se vazio.
   - Gera `confirmation_audit_id` determinístico (SHA256).
   - Gera 3 tokens HMAC distintos (1 por choice).
   - Envia WhatsApp via Baileys sidecar com mensagem formatada + 3 links clicáveis.
   - Atualiza evento para `sent_to_technician` se envio ok.

2. **`GET /api/swap-confirmation/respond/{event_id}/{token}/{choice}`** (público com HMAC)
   - Endpoint clicável do link no WhatsApp.
   - Valida token HMAC com `compare_digest` (constante-time).
   - Retorna HTML simples de confirmação ("Sua resposta foi registrada").
   - 3 choices aceitos: `confirmed` · `disputed` · `needs_review`.

3. **`POST /api/swap-confirmation/respond`** (REST público com HMAC)
   - Mesmo fluxo do GET, para integrações.
   - Body: `{event_id, token, choice, raw_text?}`.

4. **`GET /api/swap-confirmation/list`** (auth)
   - Lista eventos da empresa com `counts_by_status`.

### Collection nova — `auto_ont_swap_confirmations` (append-only)
Cada resposta cria 1 documento com:
- `id`, `company_id`, `swap_event_id`, `confirmation_audit_id`
- `technician_id`, `ticket_id`, `ont_anterior`, `ont_atual`
- `response` (CONFIRMO/NÃO HOUVE TROCA/PRECISO REVISAR), `response_code`
- `status_set` (status final do evento)
- `timestamp`, `origin="whatsapp_patrimonial_confirmation"`
- `origin_hint` (whatsapp_link_click / api_post)
- `raw_text` (opcional)
- `idempotent_skip` (true se já tinha o mesmo status)

### Mudanças em `auto_ont_swap_events`
Status estendido para máquina de estados:
```
pending_confirmation
       ↓ (admin envia WhatsApp)
sent_to_technician
       ↓ (técnico clica link)
   ┌───┴───┬─────────────┬────────────┐
confirmed  disputed   needs_review
(some)    (review)    (review)
```
Campos novos: `confirmation_audit_id`, `confirmation_sent_at`, `confirmation_sent_by`, `confirmation_send_error`, `confirmation_phone`, `confirmation_response`, `confirmation_response_at`, `confirmation_response_origin`.

### Watchtower Diagnóstico (atualizado)
Card "Trocas de ONT · ciclo de confirmação" agora mostra:
- **5 KPIs**: Pending · WhatsApp enviado · Confirmado · Contestado · Revisar
- `total_pending` = soma de pending + sent + disputed + needs_review (confirmed NÃO conta)
- Cada evento na lista tem botão **📲 Enviar WhatsApp** que chama o endpoint `send`
- Feedback inline ("WhatsApp enviado" ou erro humano)

Data-testids:
- `swap-status-pending` · `swap-status-sent` · `swap-status-confirmed` · `swap-status-disputed` · `swap-status-review`
- `diagnostico-swap-event-{id}` · `diagnostico-swap-send-{id}` · `diagnostico-swap-feedback-{id}`

---

## 🛡️ Regras de ouro respeitadas (auditadas via testes)

| Regra CEO | Status | Evidência |
|-----------|--------|-----------|
| Aplica somente em `pending_confirmation` (ou `sent_to_technician` para reenvio) | ✅ | `test_send_rejects_already_confirmed` |
| Toda resposta grava: técnico + ticket + ONT antes/depois + resposta + timestamp + audit_id + origem | ✅ | `test_respond_confirmo_marks_confirmed` (valida 8 campos) |
| Se CONFIRMO: baixa pendência + marca confirmed | ✅ | `total_pending` exclui confirmed; evento `status="confirmed"` |
| Se NÃO HOUVE TROCA: marca disputed + mantém pendente | ✅ | `test_respond_disputed_keeps_pendency` |
| Se PRECISO REVISAR: marca needs_review + mantém pendente | ✅ | `test_respond_needs_review_keeps_pendency` |
| **Proibido alterar estoque** | ✅ | `test_no_stock_collection_touched` audita count_documents pré/pós em stok_stock, stok_history e stok_services |
| Token HMAC contra forjar | ✅ | `test_respond_with_invalid_token_403` |
| Idempotência em duplo clique | ✅ | `test_respond_idempotent_double_click` |
| Multi-tenant isolation | ✅ | `test_send_rejects_event_from_other_company` |

---

## 📊 Métricas atuais (snapshot da entrega)

> Como o fluxo acabou de ser implantado e ainda não houve campanha de envio em produção, os contadores estão zerados. O sistema está PRONTO pra absorver tráfego real.

| Métrica | Valor |
|---------|------:|
| Eventos `pending_confirmation` aguardando envio | 0 |
| Eventos `sent_to_technician` aguardando resposta | 0 |
| Confirmados (CONFIRMO) | 0 |
| Contestados (NÃO HOUVE TROCA) | 0 |
| Em revisão (PRECISO REVISAR) | 0 |
| Total em `auto_ont_swap_confirmations` | 0 |

**Para gerar tráfego real**: cada nova troca de ONT detectada (Bug #6) cria evento `pending_confirmation` automaticamente, e o gestor clica no botão "📲 Enviar WhatsApp" no Watchtower → mensagem segue.

### Evidência no Watchtower
- Endpoint: `GET /api/watchtower/estoque/diagnostico?window_hours=168`
- Path frontend: `/watchtower-estoque → aba "Diagnóstico Lousa Mobile" → card "Trocas de ONT · ciclo de confirmação"`
- Tela mostra: 5 KPIs por status · top 5 técnicos com pendências · 10 eventos mais recentes com botão de envio inline.

---

## ✅ Testes (13/13 + 41 regressão = 54/54)

```
tests/test_swap_confirmation.py:
  ✓ test_hmac_token_round_trip
  ✓ test_send_rejects_already_confirmed
  ✓ test_send_rejects_event_from_other_company
  ✓ test_send_rejects_technician_without_phone
  ✓ test_respond_confirmo_marks_confirmed
  ✓ test_respond_disputed_keeps_pendency
  ✓ test_respond_needs_review_keeps_pendency
  ✓ test_respond_with_invalid_token_403
  ✓ test_respond_with_invalid_choice_400
  ✓ test_respond_idempotent_double_click
  ✓ test_no_stock_collection_touched      ← regra de ouro CEO
  ✓ test_watchtower_shows_breakdown
  ✓ test_list_endpoint_returns_counts
```

Regressão (Onda A + B + C + RCA Fibra): **41/41 PASS**. Zero quebra.

---

## 🔗 Arquitetura do fluxo

```
[Bug #6 auto-detect ONT]
        ↓ cria evento status=pending_confirmation
[Watchtower Diagnóstico mostra pendente]
        ↓ gestor clica "📲 Enviar WhatsApp"
[POST /api/swap-confirmation/send/{id}]
        ↓ Baileys sidecar /send com 3 links HMAC
[Status → sent_to_technician]
        ↓ técnico clica 1 dos 3 links no WhatsApp
[GET /api/swap-confirmation/respond/.../{choice}]
        ↓ valida token HMAC (constant-time)
        ↓ insere auto_ont_swap_confirmations
        ↓ atualiza evento → confirmed | disputed | needs_review
[Watchtower reflete novo status no próximo refresh]
```

---

## 📁 Files

### Novos
- `/app/backend/routes/swap_confirmation.py` (300+ linhas, 4 endpoints)
- `/app/backend/tests/test_swap_confirmation.py` (13 testes)
- `/app/memory/SWAP_CONFIRMATION_P1_REPORT.md` (este documento)

### Modificados
- `/app/backend/server.py` — include_router
- `/app/backend/routes/watchtower_estoque_diagnostico.py` — `_agg_swap_pending` com breakdown por status
- `/app/frontend/src/WatchtowerEstoqueDiagnostico.jsx` — 5 KPIs + componente `SwapEventRow` com botão de envio

---

## 🎯 Próximos passos (ordem oficial)

- **P2** — Watchtower Patrimônio Consolidado + Export CSV em PayersComponents + seed E2E completo (stok_stock + smartolt + cto) para FLUXO 2 success path.
- **Sprint 5** — Owner & Location Normalization (estrutural).
- **Sprint 5.1** — Auto Balanço Patrimonial (snapshot mensal automático, CEO ordem oficial).
- **HOLD 7-14d** (já alinhado): refactor `lousa.py` (9.224 linhas) + `whatsapp_baileys.py` (>5.400 linhas).
