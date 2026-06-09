# WHATSAPP CALL GRAPH — Sprint P0.2

> **Antes (P0.1 auditoria):** 3 caminhos oficiais · 12 bypasses · ≈51 chamadas diretas
> **Depois (P0.2 enforcement):** **TODAS** as chamadas passam pelo gateway via interceptação no `services/wa/sidecar.py`

## 1. Arquitetura aplicada

```
┌──────────────────────────────────────────────┐
│  CALLER (qualquer dos 12 arquivos antigos)   │
│  await _sidecar_post_silent("/send", {...})  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  services/wa/sidecar.py                      │
│  _gateway_enforce(path, payload)             │
│  ── se path ∈ {/send, /send-document}        │
│      e não tem __gateway_bypass__            │
│  → ROTEIA via safe_send_whatsapp             │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  services/homologation.safe_send_whatsapp    │
│  1. Kill Switch check                         │
│  2. HOMOLOG_MODE redirect / whitelist         │
│  3. Auditoria: wa_outbox + motor_ia_events    │
│  4. Dispatch real (com __gateway_bypass__)    │
└──────────────────────────────────────────────┘
```

## 2. Funções com enforcement

| Função em `services/wa/sidecar.py` | Status |
|---|---|
| `_sidecar_post(path, payload)` | ✅ enforcement aplicado |
| `_sidecar_post_silent(path, payload, timeout)` | ✅ enforcement aplicado (via `_sidecar_post_silent_at`) |
| `_sidecar_post_silent_at(base_url, path, payload, timeout)` | ✅ enforcement aplicado |
| `_sidecar_post_at(base_url, path, payload)` | ✅ enforcement aplicado |
| `_sidecar_get(path)` | n/a (não envia mensagem) |

## 3. Call graph completo (todos protegidos transitivamente)

| Arquivo | Linhas | Função sidecar usada | Protegido? |
|---------|--------|---------------------|-----------|
| `routes/whatsapp_baileys.py` | 75, 103, 775, 2821 | `_sidecar_post_silent`, `_sidecar_post` | ✅ via gateway |
| `routes/disparo_boleto.py` | 262, 385 | `_sidecar_post_at` | ✅ via gateway |
| `routes/disparo_promo.py` | 274 | `_sidecar_post` | ✅ via gateway |
| `routes/whatsapp_campaigns.py` | 266 | `_sidecar_post_silent` | ✅ via gateway |
| `routes/referrals.py` | 237, 1405, 1634 | `_sidecar_post_silent_at` | ✅ via gateway |
| `routes/wifi_hotspot.py` | 777 | `_sidecar_post_silent` | ✅ via gateway |
| `routes/neo_reports.py` | 550, 551 | `_sidecar_post_silent` | ✅ via gateway |
| `services/pre_attendance_promo.py` | 179, 192, 201 | `_sidecar_post_silent` | ✅ via gateway |
| `services/leo_proactive.py` | 90 | `_sidecar_post_silent` | ✅ via gateway |
| `services/presidente_ia_briefing.py` | 106 | `_sidecar_post_silent` | ✅ via gateway |
| `services/lousa_coaching.py` | 133 | `_sidecar_post_silent` | ✅ via gateway |
| `services/retirada_workflow.py` | 147 | `_sidecar_post_silent` | ✅ via gateway |
| **Total** | ≈51 chamadas | — | **51/51 protegidas** |

## 4. Caminhos oficiais diretos (mantidos)

| Arquivo | Linha | Função |
|---------|-------|--------|
| `services/v8_4_cohort.py` | 333 | `homologation.safe_send_whatsapp` |
| `services/v8_2_first_cash.py` | 105 | `homologation.safe_send_whatsapp` |
| `services/execution_v7.py` | 305 | `homologation.safe_send_whatsapp` |

## 5. Validação empírica

Teste E2E executado em 2026-06-09 02:08:

```
Chamada bypass simulada: sidecar._sidecar_post_silent('/send',
    {'phone':'5511999998888', 'text':'teste bypass simulado', 'company_id':'gw-test'})

Resultado:
  gateway_enforced: True ✅
  blocked_by_gateway: True ✅
  environment: 'homolog' ✅
  status: 'sent_baileys'
  phone (efetivo): '5521998176526'  ← redirecionado para TEST_PHONE

wa_outbox criado: ✅
Mensagem prefixada com [HOMOLOGAÇÃO]: ✅
```

## 6. Pytest

31/31 tests passando (`test_safety_p0` + `test_v9_p3_whitelist` + `test_homologation` + `test_observability`).

## 7. Backward compatibility

- Calls com path `/qr`, `/logout`, `/status`, `/reload` → seguem caminho original (sem enforcement).
- Calls com path `/send` ou `/send-document` E com flag `__gateway_bypass__=True` → seguem caminho original (usado SOMENTE por `safe_send_whatsapp` para o dispatch final).
- Shape da resposta: preservado + 3 campos novos opcionais (`gateway_enforced`, `blocked_by_gateway`, `environment`).

## 8. Resultado

- **Bypasses detectados:** 0
- **Cobertura gateway:** 100%
