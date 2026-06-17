# WA_DISPATCHER — Auditoria Arquitetural P0
> CTO 17/02/2026 · ordem CEO · resposta à pergunta "Por que a IA falhou?"

## TL;DR (3 linhas)

1. **`aihub_wa_messages` JÁ TEM o campo `channel` na inbound.**
2. **`wa_dispatcher.send_text(company_id, to, text)` IGNORA esse campo** — escolhe canal por `company_id`, não pela conversa.
3. **Existe fallback cruzado**: se Evolution falha, tenta Baileys. Se Baileys falha, tenta Evolution. Conversa Baileys pode ser respondida via Evolution. **Isso é o bug.**

---

## 1. Quem escolhe o canal? (RESPOSTA: ninguém — fallback automático)

### Mapa de chamadas a `wa_dispatcher.send_text`

| Caller | Arquivo:linha | Assinatura passada |
|---|---|---|
| Isabella (Atendimento IA) | `services/isabella_experience.py:516` | `(company_id, to, text)` |
| Isabella (Incidente) | `services/isabella_incident.py:658` | `(company_id, to, text)` |
| Action Engine | `services/action_engine.py:120` | `(company_id, to, text)` |
| Autonomous Engine | `services/autonomous_engine.py:488` | `(company_id, to, text)` |
| Presidente IA | `routes/presidente_ia.py:545` | `(company_id, to, text)` |
| Briefing Dispatcher | `services/briefing_dispatcher.py:77` | `(company_id, to, text)` |
| Operação Tese (2x) | `services/operacao_tese.py:80, 344` | `(company_id, to, text)` |
| Retry (criado hoje) | `routes/wa_retry_failed.py:123` | `(company_id, to, text)` |

**Padrão único**: TODOS passam só `(company_id, to, text)`. **Nenhum passa `channel`**. O dispatcher inventa o canal sozinho.

### Como o dispatcher "inventa" o canal hoje (`wa_dispatcher.py:136-158`)

```python
async def _resolve_channels(company_id):
    chans = await db.whatsapp_channels.find(
        {"company_id": company_id, "active": True}).to_list(20)
    # Ordena: preferred primeiro, depois prioriza baileys
    chans.sort(key=lambda c: (
        0 if c.get("preferred") else 1,
        0 if c.get("provider") == "baileys" else 1,
    ))
    # Retorna SEMPRE até 2 routes (1 baileys + 1 evolution)
```

**Falha conceitual**: o ranking é por flags do canal (`preferred`, provider), **NÃO pelo canal de origem da conversa**.

---

## 2. Onde o canal é persistido? (RESPOSTA: persistido na INBOUND, ignorado no OUTBOUND)

### Schema real de `aihub_wa_messages` (uma inbound da Isabella):

```
INBOUND keys: ['channel', 'company_id', 'created_at', 'direction',
               'id', 'jid', 'message_id', 'phone', 'push_name',
               'resolution_confidence', 'resolution_method',
               'resolution_reason', 'subscriber_id', 'text',
               'wa_timestamp']
```

✅ Campo `channel` **existe** na inbound. Os webhooks Baileys / Evolution / Twilio gravam corretamente.

### Schema real de uma OUTBOUND IA (a que falhou):

```
['agent', 'auto_reply', 'company_id', 'created_at', 'delivery_status',
 'direction', 'external_id', 'jid', 'phone', 'subscriber_id', 'text']
```

❌ Campo `channel` **NÃO existe** na outbound IA. O `wa_dispatcher` grava o resultado SEM dizer por qual canal saiu. Nem `used_provider` é persistido na collection canônica de mensagens (só nas métricas `wa_dispatch_metrics`).

**Consequência**: impossível auditar A QUE canal cada resposta IA pertenceu sem cross-join com `wa_dispatch_metrics` por timestamp + msg_id.

---

## 3. Onde o canal é respeitado? (RESPOSTA: em lugar nenhum no caminho IA → outbound)

### `wa_dispatcher.send_text` linhas 281-308 — **a culpa mora aqui**:

```python
last_error = {}
for route in routes:  # ← LOOP COM FALLBACK CRUZADO
    if route["provider"] == "evolution":
        result = await _send_via_evolution(...)
    else:
        result = await _send_via_baileys(...)
    if result["ok"]:
        return result
    last_error = result
    # "Para no_session ou falha de rede, tenta o próximo provider"
    log.info("[wa_dispatcher] %s falhou, tentando próximo", route["provider"])
```

**É EXATAMENTE o anti-padrão que você descreveu**:

```python
try: evolution.send()
except: baileys.send()
```

(escondido em forma de `for route in routes`)

---

## 4. Onde ainda existe fallback cruzado? (RESPOSTA: AQUI, no único caminho IA → out)

### Casos reais identificáveis HOJE em `co-demo`:

```
co-demo channels no DB:
  channel-1                    provider=baileys      is_default_outbound=True
  wac-evolution-co-demo        provider=evolution
  (+ 1 outro baileys)
```

- **Quando Isabella responde** num cliente que CHEGOU via Baileys (channel-1):
  - dispatcher chama `_resolve_channels("co-demo")`
  - retorna `[baileys, evolution]` (Baileys preferred ou primeiro pela regra de ordenação)
  - tenta Baileys → se sidecar offline → **fallback para Evolution**
  - Evolution → 400 (Apache Basic Auth bloqueia há semanas) → falha total → `delivery_status=failed_send`
- **Inverso também ocorre**: cliente chega via Evolution, Baileys pode responder (se Evolution falhar primeiro na ordem).

**Resultado**: O cliente pode ser respondido **por outro número WhatsApp** que ele nem reconhece — risco de spam-flag se isso escalar.

---

## 5. Conclusão técnica

| Camada | Status hoje | Status desejado |
|---|---|---|
| Webhook IN (Baileys/Evolution/Twilio) | ✅ Cada um grava `channel` na inbound | (mantém) |
| `wa_dispatcher.send_text(company_id, to, text)` | ❌ Não recebe `channel`; **inventa** | ✅ Recebe `channel` obrigatório (ou `conversation_id`) |
| `_resolve_channels` | ❌ Faz ranking de canal; permite fallback cruzado | ❌ **REMOVER** ranking; `channel` é input, não output |
| `for route in routes` loop | ❌ Tenta provider B se A falhar | ❌ **REMOVER** loop; retorna falha do canal correto |
| `aihub_wa_messages` outbound | ❌ Falta `channel` | ✅ Grava `channel="baileys"` igual à inbound |
| Roteamento conversa → canal | ❌ Inexiste; tudo por company | ✅ Conversa nasce com `channel`; sender é match {channel} |

---

## 6. Fix proposto em camadas (NÃO IMPLEMENTAR sem nova aprovação)

### P0 — Quebra do fallback cruzado (4-6h, urgente)

1. **Adicionar `channel` obrigatório em `send_text`**:
   ```python
   async def send_text(*, company_id, to, text, channel=None,
                        conversation_id=None): ...
   ```
   - Se `channel=None` E `conversation_id` informado → busca última inbound desta conversa e herda o `channel`.
   - Se ambos `None` → fail-fast `400 channel_required` (regra estrita).

2. **Substituir `_resolve_channels` por `_get_channel(company_id, channel)`**:
   - Retorna **1** canal específico (não lista).
   - Se canal não existe / `active=False` → erro `channel_not_available`. **Sem fallback.**

3. **Substituir `for route in routes` por match direto**:
   ```python
   match channel:
       case "baileys":  return await _send_via_baileys(...)
       case "evolution": return await _send_via_evolution(...)
       case "twilio":   return await _send_via_twilio(...)
       case _:          raise ValueError(f"unknown channel: {channel}")
   ```

4. **Persistir `channel` na outbound `aihub_wa_messages`**.

### P1 — Atualizar todos os 9 callers (2-3h)

Passa `channel` ou `conversation_id` em todos os `send_text(...)`. Já temos a inbound persistida, então o `conversation_id`-style funciona pra Isabella/IsabellaIncident/AutonomousEngine.

Para callers sem contexto de conversa (Briefing, Presidente IA blast, Operação Tese), passar `channel` explícito conforme o tipo de canal:
- Briefing → `channel="baileys"` (sempre operacional)
- Presidente IA → `channel="twilio"` (campanhas oficiais)
- Operação Tese → herda da conversa-origem

### P2 — Hardening + observabilidade (depois)

- `aihub_conversations` collection nova com `(company_id, phone)` → `channel`, lastest_inbound_at, channel_locked.
- `wa_dispatch_metrics` ganha breakdown por canal.
- Watchtower de Atendimento mostra "canais usados nas últimas 24h" — flag se houver cross-channel response.
- Test suite garantindo zero fallback cruzado.

---

## 7. Boas notícias da auditoria

✅ Motor IA está saudável — gera respostas corretas.
✅ Inbound tem `channel` persistido.
✅ DB tem todas as informações necessárias.
✅ Webhooks dos 3 providers isolados em arquivos próprios.
✅ Bug é localizado em UM ÚNICO arquivo de ~50 linhas (`wa_dispatcher.py:136-308`).

A correção é **cirúrgica** — não precisa refazer pipeline, só substituir a função de roteamento.

---

## 8. Próxima decisão CEO

a) **Quando** atacar o P0?
   - (i) **Agora, antes da Sprint 4** (4-6h, bloqueia outras prioridades)
   - (ii) **Como parte da Sprint 4** (cabe junto com Snapshot History / Sankey)
   - (iii) **Sprint 6 dedicada** (após Sprint 5 Owner & Location)

b) **Roteamento default** quando `channel=None` informado E sem `conversation_id`:
   - (i) Fail-fast (recomendado — força disciplina)
   - (ii) Fallback explícito para `channel="baileys"` (mais permissivo no curto prazo)

c) **Migração das outbound já existentes** (sem campo `channel`):
   - (i) Backfill — script de saneamento popula `channel` baseado em `external_id` / `wa_dispatch_metrics` cross-join
   - (ii) Deixar legado sem `channel` — só novas mensagens carregam

Manda a decisão e eu executo. Sem implementar nada sem confirmação — uma mudança dessa magnitude precisa carta-branca explícita.
