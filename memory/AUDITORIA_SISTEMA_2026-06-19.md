# AUDITORIA EXECUTIVA DE SISTEMA — 2026-06-19
Modo: INSTRUMENTED PRODUCTION (code freeze / só correções)

## 1. Saúde de serviços (preview)
| Serviço | Status |
|---|---|
| backend (FastAPI) | RUNNING — responde /api/ em ~0.2s |
| frontend (CRA) | RUNNING — 200 (primeiro build lento: ~50s) |
| mongodb | RUNNING — 511 coleções, DB=test_database |
| isabella-worker 01-04 | RUNNING |
| whatsapp-service 1-4 | RUNNING mas **DESCONECTADO** (loop de QR) |

## 2. ACHADOS P0

### P0-1 — Motor de IA sem crédito (OpenRouter 402) → Isabella degradada
- 500 ocorrências de `Error code: 402 ... can only afford 9 tokens` no log.
- `motor_ia_config` tem `enabled=true` + `openrouter_api_key` e **nenhum**
  `atendimento_provider_chain`. Logo Isabella (purpose=atendimento) roteia
  100% via OpenRouter.
- **Falha de resiliência no código**: em `services/motor_ia.py` o fallback para
  chaves próprias/Emergent só ocorre quando OpenRouter *não está configurado*
  (linha 234). Se a chave existe mas responde 402/429/5xx, a exceção sobe e
  **todo o stack de IA cai** (isabella, sentinela_lousa, churn_scheduler,
  ai_training_scheduler).
- Impacto: respostas vazias/truncadas → sintoma reportado de "IA responde fora
  de contexto".

### P0-2 — Resposta da IA não chega em contatos com número oculto (@lid)
- 7 conversas em `wa_conversations` com `phone_is_lid=true` e `phone == lid`
  (ex.: 197272210022596, 158587691208798, 242253654167688).
- O envio sempre monta `"phone": phone` → sidecar gera `<lid>@s.whatsapp.net`
  (`whatsapp_baileys.py` l.2961 e sidecar l.802). Esse JID **não existe** →
  mensagem nunca é entregue.
- O sidecar já aceita JID completo (`phone.includes("@")`), falta o backend
  enviar `<lid>@lid`.

### P0-3 — Heurística de LID no prompt está errada
- `whatsapp_baileys.py` l.2257 detecta LID por prefixo `169/197/198`.
  5 das 7 conversas LID reais começam com 172/158/215/54/116/242 → não são
  detectadas e a IA insiste em pedir bairro/CEP.
- Correção: usar a flag `phone_is_lid` já persistida na conversa.

## 3. ACHADOS P1

### P1-1 — universoligo.com inacessível (infra, não código)
- DNS → Cloudflare (162.159.142.117 / 172.66.2.113).
- TLS: `alert handshake failure (552)` → certificado/Custom Hostname não
  provisionado no Cloudflare. **Ação do cliente/Cloudflare**, não há fix em código.
- Fallback: usar o domínio nativo `.emergent.host`.

### P1-2 — Sidecar WhatsApp em loop infinito de QR
- Sessão `isabella`: creds carregadas do Mongo, mas WA rejeita →
  `QR refs attempts ended` (408) → reconexão a cada ~17s.
- `auto_reconnect_job` regenera QR a cada 2 min indefinidamente (log noise +
  consumo). Esperado em preview (sessão deslogada), mas sem circuit breaker.

## 4. ACHADOS P2
- **Geocoding morto**: `lousa_map` worker `ok=0/60`, todas as chamadas ao
  Nominatim retornam 429 (sem rate limit/backoff/User-Agent próprio).
- **/api/health inexistente** (404) — healthcheck de deploy sem endpoint barato.
- `ai_training_scheduler`: 20 erros por execução (consequência do P0-1).
- Frontend: 24 warnings webpack (react-hooks/exhaustive-deps), caniuse-lite 9 meses.

## 5. Itens já resolvidos (verificados nesta auditoria)
- Refactor @lid (etapas 1,2,4): sidecar já envia `is_lid/lid/sender_pn`;
  backend persiste `phone_is_lid`/`lid`; frontend exibe badge; índice
  `stok_onts.company_id_1_mac_1` **já tem** `partialFilterExpression`.
  Falta apenas a etapa de envio (P0-2).


## 6. STATUS FINAL DAS CORREÇÕES (iter255)
| Item | Status |
|---|---|
| P0-0 `ai_orchestrator.py` SyntaxError (achado no teste) | ✅ CORRIGIDO |
| P0-2 envio para `<lid>@lid` | ✅ CORRIGIDO + testado |
| P0-3 flag `phone_is_lid` no prompt | ✅ CORRIGIDO + testado |
| P1-1 universoligo.com (Cloudflare 552) | ⛔ INFRA — ação do cliente |
| P1-2 loop de QR do sidecar | ⏸️ mantido por decisão do CEO |
| P2 geocoding Nominatim | ✅ CORRIGIDO (throttle+backoff+cooldown) |
| Extra: `/motor-ia/budget` duplicada | ✅ CORRIGIDO + testado |
| P0-1 OpenRouter 402 | ⏸️ CEO recarrega saldo (sem fallback em código) |

### Pendências recomendadas (não autorizadas ainda)
- `POST /api/whatsapp-baileys/send` devolve 502 em falha de entrega tratada e o
  Cloudflare troca por HTML → a UI perde o `detail`. Sugerido 200/409 com
  `delivery_status="failed"` no corpo.
- `/api/ai-center/homologation/status/public` devolve 401 (ruído no console).
- `tests/test_whatsapp_lid.py`: fixture não limpa `wa_lid_map` (4 falhas por
  estado sujo, não é regressão).
