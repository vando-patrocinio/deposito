# RELATÓRIO DE EXECUÇÃO — RCA Fibra Estorno + 4 Guardrails
**Data**: 18/06/2026 · **Autorização CEO**: rca_20260618_ceo_approved · **Status**: ✅ COMPLETO

---

## 1) `fibra_12fo` — antes / depois

| Snapshot                  |    Valor |
|---------------------------|---------:|
| Antes do estorno          | **-366.356** |
| Estorno aplicado          |  +366.356 |
| **Depois do estorno**     |     **0** |

✅ Bate exatamente com o esperado (consistente com reset do auditor em 23/05).

## 2) `fibra_48fo` — antes / depois

| Snapshot                  |    Valor |
|---------------------------|---------:|
| Antes do estorno          |    **-200** |
| Estorno aplicado          |     +200 |
| **Depois do estorno**     |     **0** |

✅ Bate exatamente.

## 3) Cabos anulados (4) — `network_cables.status = anulado_admin_test_rca_20260618`

| ID                | Type | length_m | previous_status | audit_id                     | anulado_by                  |
|-------------------|:----:|---------:|-----------------|------------------------------|------------------------------|
| `cab-4f21e3e0f7`  | 12fo | 364.356  | cabo_solto      | `rca-estorno-fe391cfbeed3`   | rca_20260618_ceo_approved   |
| `cab-a530c12c0e`  | 12fo |   1.500  | cabo_solto      | `rca-estorno-b9a0a46dcbcb`   | rca_20260618_ceo_approved   |
| `cab-3f16ef51fa`  | 12fo |     500  | cabo_solto      | `rca-estorno-6099dc40a6fd`   | rca_20260618_ceo_approved   |
| `cab-afacf584d9`  | 48fo |     200  | cabo_solto      | `rca-estorno-6387b7cfd9f8`   | rca_20260618_ceo_approved   |

Campos preservados em CADA cabo: `previous_status`, `anulado_at`, `anulado_by`, `anulado_reason="ADMIN_TEST_DATA_RCA_20260618"`, `anulado_audit_id`, `anulado_rca_doc="/app/memory/FIBRA_12FO_RCA.md"`. **Documento original 100% preservado** (segmentos, serial, invoice, created_at, created_by) — só o status mudou.

## 4) Estornos em `stok_history` (4 registros) — `tag=rca_fibra_20260618`

| history_id                          | type           | consumable_id  | delta (m) | original_cable    |
|-------------------------------------|----------------|----------------|----------:|-------------------|
| `hist-rca-estorno-fe391cfbeed3`     | rede_estorno   | fibra_12fo     | **+364.356** | cab-4f21e3e0f7    |
| `hist-rca-estorno-b9a0a46dcbcb`     | rede_estorno   | fibra_12fo     |   +1.500  | cab-a530c12c0e    |
| `hist-rca-estorno-6099dc40a6fd`     | rede_estorno   | fibra_12fo     |     +500  | cab-3f16ef51fa    |
| `hist-rca-estorno-6387b7cfd9f8`     | rede_estorno   | fibra_48fo     |     +200  | cab-afacf584d9    |

Cada documento contém: `rca_doc`, `rca_ref`, `audit_id`, `original_cable_id`, `original_cable_serial`, `original_invoice`, `delta_meters_signed` (positivo = estorno), `user="rca_20260618_ceo_approved"`.

## 5) Registro master em `stok_admin_log`

| Campo                | Valor |
|----------------------|-------|
| `id`                 | `adm-rca-estorno-4d01d2ee5c88` |
| `action`             | `fibra_rca_estorno` |
| `rca_ref`            | `ADMIN_TEST_DATA_RCA_20260618` |
| `rca_doc`            | `/app/memory/FIBRA_12FO_RCA.md` |
| `executor`           | `rca_20260618_ceo_approved` |
| `cables_anulados`    | `[cab-4f21e3e0f7, cab-a530c12c0e, cab-3f16ef51fa, cab-afacf584d9]` |
| `estorno_12fo_m`     | 366.356 |
| `estorno_48fo_m`     | 200 |
| `history_ids`        | 4 IDs listados acima |
| `before`             | `{fibra_12fo: -366356, fibra_48fo: -200}` |
| `expected_after`     | `{fibra_12fo: 0, fibra_48fo: 0}` |

Trilha completa de auditoria: `stok_admin_log` → `cables_anulados[]` → `stok_history[]` → `network_cables.anulado_audit_id`. Qualquer auditor consegue navegar bottom-up ou top-down em qualquer um dos artefatos.

## 6) Zero deletes ✅

| Collection           | Antes | Depois | Deltas |
|----------------------|------:|------:|-------|
| `network_cables`     |     6 |     6 | 0 deletes · 4 updates (status) |
| `stok_history`       |     N |  N+4  | +4 inserts (`rede_estorno`) |
| `stok_stock`         |     1 |     1 | 0 deletes · 1 update ($inc atômico) |
| `stok_admin_log`     |     M |  M+1  | +1 insert (master) |

**Nenhuma deleção em nenhuma collection.** Tudo via update ou insert. Idempotente via `_audit_id_for(cable_id)` determinístico (SHA256).

## 7) Guardrails implantados e testados ✅

### Guardrail #1 — Tokens proibidos
Em **`POST /api/rede/cables`** (rede_ia_map.py:773+), valida `cable_serial`, `invoice_number`, `purchase_id`:
- Palavras: `TEST`, `TST`, `ABCD`, `DUMMY`, `FAKE`, `MOCK` (case-insensitive, substring match).
- Drop é isento (volume pequeno, alta freq).
- Resposta: `400 {error: "guardrail_test_token_blocked", human_reason, rule}`.
- **Testes**: 5/5 PASS.

### Guardrail #2 — Tiers de comprimento
Calibrado para fibra urbana brasileira:
| Comprimento | Ação | Code |
|-------------|------|------|
| `< 5km`     | OK (sem flag) | — |
| `5–20km`    | Warning silencioso, registra `guardrail_length_tier=length_warn_tier` | — |
| `20–50km`   | Bloqueia salvo `confirm_unusual_length=true` | `guardrail_length_confirm_required` |
| `> 50km`    | Bloqueia salvo `admin_override_reason` (≥20 chars) | `guardrail_length_block` |

**364 km jamais passaria** — bloqueio administrativo automático. **Testes**: 6/6 PASS.

### Guardrail #3 — `purchase_id` ou override
Cabo de fibra (não-drop) sem `purchase_id` exige `admin_override_reason` (≥20 chars). Caso contrário: `400 guardrail_purchase_id_required`. **Testes**: 3/3 PASS.

### Guardrail #4 — Card Watchtower "Movimentos Anômalos"
Adicionado ao endpoint `GET /api/watchtower/estoque/diagnostico` em `anomalous_movements`:
- **cables_anomalous**: cabos com `guardrail_length_tier != null` (todos > 5km).
- **cables_anulados**: cabos com status `anulado_admin_test_rca_*`.
- **estornos**: stok_history `type=rede_estorno` últimos 7d.
- **admin_overrides**: cabos com `admin_override_reason` setado.

Frontend: card `data-testid="diagnostico-card-anomalous"` em `/app/frontend/src/WatchtowerEstoqueDiagnostico.jsx` com 4 KPIs + listas drill-down. **Testes**: 1/1 PASS (E2E via diagnostico endpoint).

**Total de testes**: **15/15** novos guardrails + **26/26** regressão (Onda A+B+C) = **41/41 PASS**.

---

## Arquivos modificados / criados

### Backend
- `/app/backend/routes/rede_ia_map.py` — adicionado `_FORBIDDEN_TEST_TOKENS`, `_LEN_*`, `_validate_cable_guardrails`, `_length_warning_tier`, integração em `create_cable` + extensão de `CableIn` (campos `confirm_unusual_length`, `admin_override_reason`).
- `/app/backend/routes/watchtower_estoque_diagnostico.py` — adicionado `_agg_anomalous_movements` + integração no payload.
- `/app/backend/scripts/rca_fibra_estorno.py` (NOVO) — script idempotente dry-run/execute do estorno.
- `/app/backend/tests/test_rca_fibra_guardrails.py` (NOVO) — 15 testes.

### Frontend
- `/app/frontend/src/WatchtowerEstoqueDiagnostico.jsx` — adicionado card "Movimentos Anômalos" com 4 KPIs e drill-down de cabos anulados.

### Memory / Docs
- `/app/memory/FIBRA_12FO_RCA.md` (criado anteriormente) — RCA forensic.
- `/app/memory/RCA_ESTORNO_RELATORIO_FINAL.md` (este documento).

---

## Próximas etapas (aprovadas pelo CEO)

- **P0.2**: Recompute dry-run dos técnicos negativos (`col-30aafc3c`, `col-b4db2145`) → entregar `TECNICOS_NEGATIVOS_DIFF.md`.
- **P0.3**: Export CSV dos 56 órfãos (técnico, cliente, data, último ticket, motivo, status anterior).
- Após validação humana dos 3 P0s: P1 (Confirmação patrimonial via WhatsApp) → P2 (Watchtower Patrimônio Consolidado) → Sprint 5 (Owner & Location Normalization).

## Métricas finais

| Métrica                            | Antes      | Depois     |
|------------------------------------|-----------:|-----------:|
| `fibra_12fo` (empresa)             |  -366.356  |       **0** |
| `fibra_48fo` (empresa)             |     -200   |       **0** |
| Cabos contaminados em produção     |    4       |       4 (anulados) |
| Cobertura de guardrails            |    0       |     **4 ativos** |
| Tempo médio para detectar contaminação | ∞ (descoberto por audit manual) | ≤24h (Watchtower) |
| Testes verdes                      |   26/26    |     **41/41** |

**Resultado**: trilha patrimonial fechada, vazamento histórico estornado, prevenção implantada.
