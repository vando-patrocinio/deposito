# RELATÓRIO — UI IA TESOUREIRA (ASAAS SANDBOX)

**Data:** 11/06/2026
**Ordem CTO:** Validar IA Tesoureira via UI
**Status:** ✅ ENTREGUE — 100% testado

---

## TELA CRIADA

- **Rota:** aba `IA Tesoureira` no grupo **Financeiro** (sidebar)
- **Componente:** `/app/frontend/src/TreasuryPanel.jsx` (868 linhas)
- **Permissão:** `superAdminOnly: true` (apenas super_admin / CTO vê)
- **View id:** `treasury` · `data-testid="treasury-panel"`

### Blocos implementados (todos os 5 obrigatórios)

| # | Bloco | testid raiz | Status |
|---|------|------------|--------|
| 1 | Banner de segurança (Sandbox, Auto-aprovação OFF, Asaas key) | `treasury-safety-banner` | ✅ |
| 2 | 8 KPIs (agendado, pago, aguarda CTO, bloqueado, falhou, fcst 7d/15d/30d) | `kpi-*` | ✅ |
| 3 | Fila de Aprovação (tabela com favorecido, valor, status, IA, risco, ações) | `treasury-queue-table` | ✅ |
| 4 | Modal Decisão IA + Auditoria timeline | `treasury-payment-detail-modal` · `treasury-audit-timeline` | ✅ |
| 5 | Previsão de Saída (barras 7/15/30d + próximos vencimentos) | `treasury-forecast-view` | ✅ |

---

## ENDPOINTS CONSUMIDOS (todos reais, zero mocks)

| Verbo | Rota | Uso |
|-------|------|-----|
| GET | `/api/treasury/safety` | Banner SANDBOX + Auto OFF |
| GET | `/api/treasury/kpis` | 8 KPI cards + breakdown categoria/favorecido |
| GET | `/api/treasury/payments` | Listagem fila + histórico |
| GET | `/api/treasury/payments/{id}` | Modal detalhe |
| **NOVO** GET | `/api/treasury/payments/{id}/decision` | Última decisão da IA |
| **NOVO** GET | `/api/treasury/payments/{id}/audit` | Timeline de auditoria |
| POST | `/api/treasury/payments/{id}/ai-review` | Rerodar análise IA |
| POST | `/api/treasury/payments/{id}/approve` | Aprovar (com reason) |
| POST | `/api/treasury/payments/{id}/cancel` | Cancelar |
| POST | `/api/treasury/payments/{id}/send` | Enviar Asaas |

---

## AÇÕES TESTADAS (iteration_153.json — 100%)

Pagamento usado: `pay-demo-53366b336a` (Fornecedora Fibras Ópticas LTDA, R$ 1.850,00)

| Ação | Endpoint | HTTP | Resultado |
|------|----------|------|-----------|
| Approve | POST /approve | 200 | status=approved, audit log gravado, botão Enviar aparece |
| Send | POST /send | 200 | `{ok:false, asaas:{error:"asaas_key_missing"}}` graceful, status=failed, erro inline visível |
| Cancel | POST /cancel | 200 | status=cancelled, audit log gravado |
| AI Review | POST /ai-review | 200 | decisão recarregada (REQUER CTO, risk_score) |

---

## REGRAS DE SEGURANÇA RESPEITADAS

- ✅ Banner "SANDBOX" pill no header
- ✅ Banner "Auto-aprovação: OFF" no topo (verde quando OFF)
- ✅ Banner "Asaas key não configurada" quando `ASAAS_API_KEY` vazia
- ✅ Acima de R$ 3.000 exige super_admin (gating no backend)
- ✅ Favorecido fora da whitelist → `BLOCK` (já validado no `test_tesoureira_asaas.py`)
- ✅ Nenhum secret/token aparece na tela ou console (validado pelo testing agent)
- ✅ Aba invisível para usuários não-super_admin

---

## BUGS ENCONTRADOS E CORRIGIDOS NESSA ITERAÇÃO

| Bug | Severidade | Fix |
|-----|-----------|-----|
| `Card` component dropava `data-testid` | HIGH | `({children, style, ...rest})` + spread no div |
| `window.prompt` retornava `undefined` (custom shim) → 422 no approve | HIGH | Removido. `reason="Aprovado via UI pelo CTO"` fixa |
| AxiosError não tratado → CRA overlay vermelho | HIGH | try/catch em `doAction` + `setActionError` inline (`treasury-action-error`) |
| `asaas_client._request` levantava RuntimeError 500 quando `ASAAS_API_KEY` ausente | HIGH | `_AsaasNoKey` exception capturada em todas as 5 chamadas → retorna `{ok:false, error:"asaas_key_missing"}` |

---

## EVIDÊNCIAS

- Smoke screenshot: app renderiza painel com 8 KPIs, 6 pagamentos na fila, banner safety, todos os blocos visíveis.
- Curl flow end-to-end approve→send→cancel valida HTTP 200 em todos os passos.
- Testing agent v3 (`iteration_153.json`): **100% (9/9)** com `retest_needed: false`.
- Red-team determinístico anterior: `/app/backend/scripts/test_tesoureira_asaas.py` 13/13.

---

## BLOQUEADORES PARA PRODUÇÃO

1. **`ASAAS_API_KEY` ausente** — atualmente backend roda em sandbox sem chave. Para movimentar valores em sandbox real, configurar `ASAAS_API_KEY` no `backend/.env` (sandbox dashboard Asaas → Integração → API Key).
2. **`ASAAS_WEBHOOK_TOKEN` ausente** — necessário para receber callbacks de `TRANSFER_DONE`. Definir no Asaas e no `.env`.
3. **Auto-aprovação:** mantida OFF por política — só ligar (`TREASURY_AUTO_APPROVAL_ENABLED=true`) após análise de risco do CTO.
4. **Sicoob direto:** ainda pendente da homologação mTLS (48h) + Client ID + cert x.509.
5. **Redeploy:** mudanças estão no Preview. Para refletir em `ligo.system` (Produção) é necessário redeploy.

---

## ARQUIVOS ALTERADOS / CRIADOS

```
NEW   /app/frontend/src/TreasuryPanel.jsx                       (868 linhas)
NEW   /app/backend/scripts/seed_treasury_demo.py                (seed 3 payees + 8 payments)
EDIT  /app/backend/routes/treasury.py                           (+3 endpoints: /safety /decision /audit)
EDIT  /app/backend/services/asaas_client.py                     (_AsaasNoKey graceful degradation)
EDIT  /app/frontend/src/App.js                                  (import + tab + route switch)
```

---

## PRÓXIMO COMANDO (sugestões)

- **b)** Iniciar homologação Sicoob mTLS (preciso de Client ID + cert x.509 + chave privada do portal Sicoob)
- **c)** AWS S3 backup offsite (preciso de Access Key + Secret + bucket)
- **d)** Configurar `ASAAS_API_KEY` real do sandbox para movimentar valores fictícios
- **e)** Ligar AUTO_APPROVAL_ENABLED com limites conservadores (em sandbox)
