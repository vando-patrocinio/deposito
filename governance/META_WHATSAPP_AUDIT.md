# META WHATSAPP API — AUDITORIA (P0.4 A5)

> **Modo:** READ-ONLY. Apenas auditoria — nenhuma alteração aplicada.
> **Data:** 2026-06-09

## 1. Onde Meta Business API é chamada

| Arquivo | Linha | Função | Endpoint Meta |
|---------|-------|--------|---------------|
| `routes/holerite.py` | 434 | `send_holerite` (envio de holerite via WA Cloud) | `POST https://graph.facebook.com/v25.0/{wa_phone_number_id}/messages` |
| `routes/mass_messaging.py` | 442 | função interna de disparo em massa (campanha Meta) | `POST https://graph.facebook.com/v25.0/{phone_number_id}/messages` |

## 2. Está ativa em produção?

| Item | Evidência |
|------|-----------|
| Collection `whatsapp_meta_creds` | ✅ existe |
| Docs em `whatsapp_meta_creds` | **1** (uma empresa com credencial registrada) |
| `enabled_whatsapp_cloud` | ❓ não verificado (escopo READ-ONLY do conteúdo do doc) |
| Collection `wa_meta_messages` | 0 docs |
| Collection `whatsapp_meta_messages` | 0 docs |
| Collection `wa_outbox` com `channel="meta"` | 0 docs |
| `mass_messaging_runs` | 0 docs |
| `holerite_log` | 0 docs |

**Conclusão:** infraestrutura **configurada** (1 credencial existe), mas **ZERO envios registrados** nas collections que normalmente seriam usadas para auditoria. Provavelmente:
- Canal foi configurado mas nunca usado em produção; OU
- Envios ocorreram mas não foram persistidos (sem audit trail próprio).

## 3. Quantos envios ocorreram nos últimos 30 dias?

**Resposta:** **0 envios auditáveis.** Não há trilha em nenhuma collection.

⚠️ Se a função foi chamada, **nada ficou registrado**. Isso é por si só um risco (sem audit trail).

## 4. Pode ser migrado para o gateway?

**SIM, mas requer wrapper específico.** O `safe_send_whatsapp` atual assume:
- Transporte = sidecar Baileys local (porta 3002)
- Shape de payload = `{"phone": ..., "text": ...}`

Meta API tem:
- Transporte = HTTPS pública (`graph.facebook.com`)
- Shape de payload = `{"messaging_product": "whatsapp", "to": ..., "type": "template|text", ...}` (mais complexo)
- Credenciais por empresa (`wa_access_token`, `wa_phone_number_id`)

**Proposta arquitetural (NÃO implementada nesta sprint):**

Refatorar `safe_send_whatsapp` para aceitar `transport: Literal["baileys", "meta"]` e despachar para o transporte certo. Mantém HOMOLOG_MODE + Kill Switch + Audit Trail comuns. Esforço estimado: **3-4h**.

## 5. Risco atual

| # | Risco | Sev |
|---|-------|-----|
| 1 | Envio via Meta API **bypassa HOMOLOG_MODE** | 🔴 ALTO se ativado |
| 2 | Envio via Meta API **bypassa Kill Switch** | 🔴 ALTO se ativado |
| 3 | Envio via Meta API **bypassa Whitelist `CAUSALITY_PILOT_PHONES`** | 🔴 ALTO se ativado |
| 4 | **Zero audit trail** próprio para envios Meta | 🟠 MÉDIO |
| 5 | Credencial `wa_access_token` em texto plano em `whatsapp_meta_creds` | 🟠 MÉDIO |

**Mitigador atual:** o canal está **dormente** (zero envios registrados nos últimos 30 dias). Risco operacional **hoje** é baixo. Risco **se ativado sem refator** é ALTO.

## 6. Recomendação

- **Curto prazo (sem código):** documentar no `RELEASE_LOCK.md` que envios Meta API estão temporariamente fora do gateway. Adicionar checagem no `admin_safety/killswitch/status` de "canal Meta ativo".
- **Médio prazo:** refatorar `safe_send_whatsapp` para multi-transport (Baileys + Meta). Permite reusar HOMOLOG/Kill/Whitelist/Audit.
- **Não migrar empiricamente sem aprovação do CTO** — pode quebrar fluxo de holerite que pode estar em produção em alguma empresa do `whatsapp_meta_creds`.
