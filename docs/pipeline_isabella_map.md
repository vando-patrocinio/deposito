# 🗺️ FASE 1 — Mapeamento Real do Pipeline Isabella

> Operação Validar Receita Real · escopo restrito ao número **21998176526**
> Gerado a partir de inspeção de código + estado real do MongoDB (sem mocks).

---

## 1. Snapshot do estado atual (DB ao vivo)

| Item | Valor real | Coleção |
|------|------------|---------|
| Subscriber-alvo | `sub-89c314c0d98f` — PAMELA NERY TESTE LIGO · ATIVO · `co-demo` · phone `5521998176526` | `subscribers` |
| Conversa | `phone=5521998176526` · `assignee_role=ai` · `routed_agent_id=agent-b3e92894d4` (Isabella) · `routed_reason=llm` | `wa_conversations` |
| Mensagens existentes | **297 inbound** / **342 outbound** para esse phone | `aihub_wa_messages` |
| Canal Twilio | **ENABLED** · `from=+5521998176526` · tenant `co-demo` | `whatsapp_twilio_creds` |
| Sessão Baileys p/ `co-demo` | **NÃO EXISTE** (única sessão aberta é `pilot-sim-72h`) | `wa_baileys_sessions` |
| Auto-reply config | `enabled=true` · `agent_name=Jerusa` (apenas fallback; router escolhe Isabella via `routing_intent`/LLM) | `aihub_settings` |
| Agente Isabella | `id=agent-b3e92894d4` · `active=true` · `company_id=co-demo` | `aihub_agents` |
| Métricas dispatcher (24h) | **0 registros** em `wa_dispatch_metrics` → canal Baileys 100% ocioso p/ `co-demo` | `wa_dispatch_metrics` |

> 🔴 **Achado #0 (bottleneck óbvio antes de stress test):** Para o tenant `co-demo` **não há sessão Baileys aberta** — todo envio outbound via Baileys retornaria `{ok:false, reason:"no_session"}`. O único canal funcional é **Twilio**. Logo, a escalabilidade hoje depende 100% de Twilio + sidecar Twilio.

---

## 2. Diagrama de fluxo (texto)

### A) Pipeline INBOUND → Isabella → OUTBOUND (canal Twilio — ativo p/ co-demo)

```
[WhatsApp Business cloud (Twilio)]
        │  HTTP POST application/x-www-form-urlencoded
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ POST /api/whatsapp-twilio/webhook?tenant=co-demo                     │
│  • @limiter.limit(webhook_inbound) → 1200/min (dev) | 120/min (prod) │
│  • X-Twilio-Signature  → HMAC-SHA1 vs auth_token (se ausente, skip)  │
│  • _get_creds(cid)     → reads whatsapp_twilio_creds                  │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
                                  ▼
                ┌────────────────────────────────────┐
                │ phone_normalizer.link_phone_       │
                │   to_subscriber(phone, cid)        │
                │  reads: subscribers                │
                └─────────────────┬──────────────────┘
                                  │ subscriber_id (ou None)
                                  ▼
                ┌────────────────────────────────────┐
                │ INSERT aihub_wa_messages           │
                │   { direction: "inbound",          │
                │     channel: "twilio",             │
                │     phone, text, message_sid,      │
                │     subscriber_id, created_at }    │
                └─────────────────┬──────────────────┘
                                  │
                                  ▼
                ┌────────────────────────────────────┐
                │ _generate_and_send_twilio_reply    │
                │                                    │
                │  1. db.aihub_settings              │
                │     {key:"whatsapp_auto_reply"}    │
                │     → if !enabled → return None    │
                │                                    │
                │  2. services.routing.              │
                │       pick_agent_for_message       │
                │     reads: wa_conversations,       │
                │            aihub_agents            │
                │     writes: wa_conversations       │
                │       (routed_agent_id, reason)    │
                │                                    │
                │  3. routes.ai_corrections.         │
                │       fetch_recent_for_prompt      │
                │                                    │
                │  4. services.ai_orchestrator.      │
                │       build_orchestrated_context   │
                │                                    │
                │  5. services.ai_history.           │
                │       fetch_history_turns          │
                │     (janela 100, token_budget 6k)  │
                │                                    │
                │  6. services.motor_ia.             │
                │       chat_completion              │
                │     → EMERGENT LLM KEY (Claude)    │
                │                                    │
                │  7. send_via_twilio                │
                │     → POST api.twilio.com/.../    │
                │       Messages.json                │
                │                                    │
                │  8. INSERT aihub_wa_messages       │
                │     {direction:"outbound",         │
                │      channel:"twilio", text,       │
                │      agent_id, agent_name,         │
                │      delivery_status, message_sid} │
                └─────────────────┬──────────────────┘
                                  │ HTTP 200 {ok, auto_reply_preview}
                                  ▼
                       [Twilio entrega ao cliente]
```

### B) Pipeline INBOUND Baileys (INATIVO para co-demo — sem sessão)

```
[WA sidecar Node.js Baileys]
        │  POST com X-WA-Token  → fail if WA_INBOUND_TOKEN mismatch
        ▼
POST /api/whatsapp-baileys/inbound
  ├─ emit_business("wa.inbound")
  ├─ filtra status@broadcast / @newsletter / @g.us
  ├─ LID resolution (wa_lid_map)
  ├─ wifi_hotspot.try_unlock_session_from_whatsapp
  ├─ phone_normalizer.link_phone_to_subscriber
  │     └─ subscriber_phone_linker.tag_unknown_phone
  │     └─ subscriber_phone_linker.try_auto_link_phone (CPF/CNPJ no texto)
  ├─ Mídia → whisper (áudio) / gemini-vision (imagem)
  ├─ INSERT aihub_wa_messages (inbound, channel:"baileys")
  ├─ UPDATE wa_conversations (last_channel_*, phone_is_lid, lid)
  └─ background_tasks.add_task(_process_inbound_ai_pipeline)
        ├─ Manager Assistant (se for gestor)
        ├─ Isabella auto-reply
        │     └─ wa_dispatcher.send_text
        │         ├─ Circuit breaker (5 falhas → 120s cooldown)
        │         ├─ Checa wa_baileys_sessions {company_id, status:"open"}
        │         │   → SE AUSENTE → {ok:false, reason:"no_session"}   ← 🔴
        │         ├─ HTTP POST BAILEYS_SIDECAR_URL/send
        │         └─ INSERT wa_dispatch_metrics
        ├─ Co-pilot IA (sugestões pro atendente humano)
        └─ INSERT aihub_wa_messages (outbound, channel:"baileys")
```

---

## 3. Coleções MongoDB tocadas pelo pipeline

### Leitura (read)
- `subscribers` → match por phone/phones/whatsapp + cpf/cnpj
- `wa_conversations` → roteamento persistente
- `aihub_agents` → catálogo de IAs + routing_intent
- `aihub_settings` (`whatsapp_auto_reply`)
- `whatsapp_twilio_creds`
- `wa_baileys_sessions`
- `wa_lid_map` (resolução LID privacy)
- `ai_corrections` (Edit & Teach)
- `aihub_wa_messages` (histórico)

### Escrita (write)
- `aihub_wa_messages` (×2 por turno: 1 inbound + 1 outbound)
- `wa_conversations` (last_channel, routed_agent_id, etc.)
- `wa_dispatch_metrics` (latência + sucesso/falha — só Baileys)
- `executive_ledger` (apenas se tarefa cobrar/upgrade/retenção)
- `wa_lid_map` (auto-mapeamento sender_pn)
- `wa_system_events` (eventos do sidecar)

---

## 4. Pontos de gargalo teóricos (a confirmar na Fase 4)

| # | Componente | Risco | Métrica |
|---|------------|-------|---------|
| G1 | Rate-limit slowapi `webhook_inbound` | em prod = 120/min/IP. Burst Twilio retry pode estourar | HTTP 429 em rajadas |
| G2 | `motor_ia.chat_completion` (Claude via Emergent LLM Key) | latência típica 1.5-4s; sequencial bloqueia handler até retorno | p50/p95/p99 |
| G3 | `send_via_twilio` httpx timeout=15s | Twilio API pode estourar (4xx por sandbox/from-to igual) | delivery_status="failed_twilio" |
| G4 | `_generate_and_send_twilio_reply` é **síncrono** dentro do webhook (≠ Baileys que usa BackgroundTasks) | webhook handler trava até LLM+Twilio retornarem. Pode timeout do Twilio (deve responder em <15s) | tempo de resposta do POST /webhook |
| G5 | Sem sessão Baileys p/ co-demo | Toda IA fora-do-Twilio falha. Operação real = só Twilio | `wa_dispatch_metrics` permanece vazio |
| G6 | `wa_dispatcher` circuit breaker é **in-memory** (não por worker) | Em multi-worker uvicorn, cada worker tem breaker próprio. Em produção sob carga, breaker pode abrir/fechar de forma inconsistente | `breaker.fails` divergente entre workers |
| G7 | `fetch_history_turns(limit=100, token_budget=6000)` | Custo crescente por turno; com 297 inbound +342 outbound já existentes, cada nova msg paga esse pedágio | tempo médio do step 5 |

---

## 5. Próximas fases (ordem do CTO)

1. ✅ **Fase 1 — Mapeamento** (este documento)
2. ⏳ **Fase 4 — Stress test** (10 / 25 / 50 / 100 mensagens) → script
   `/app/backend/scripts/stress_test_isabella.py`
3. ⏳ **Fase 2 — 7 cenários comerciais** (Cobrança, Upgrade, Retenção, Ex-cliente,
   Security Home, PlayHub, Ligo Móvel) — texto realístico, mesmo endpoint
4. ⏳ **Fase 3 — Validação do loop** (inbound→DB→LLM→outbound→DB)
5. ⏳ **Fase 5 — Relatório final** identificando o gargalo + impacto financeiro

Restrição absoluta: **número `21998176526` é o ÚNICO destino permitido**. Todas as
queries do script filtram explicitamente `phone $regex /21998176526$/` para
impedir poluição de outros clientes.
