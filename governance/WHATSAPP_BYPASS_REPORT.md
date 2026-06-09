# WHATSAPP BYPASS REPORT — Sprint P0.1

> **Modo:** READ-ONLY. Nenhuma linha de código alterada nesta auditoria.
> **Data:** 2026-06-09
> **Auditor:** Agente E1

## 0. Resumo

| Métrica | Valor |
|--------|------|
| Caminhos oficiais (`safe_send_whatsapp`) | **3** chamadas reais em `services/` |
| Caminhos bypass (sidecar direto) | **12 arquivos** · ≈ **51 chamadas** |
| Gateway real cobre quanto do tráfego? | **estimado 15–25%** |
| Kill switch protege quanto? | mesmos 15–25% |
| HOMOLOG_MODE protege quanto? | mesmos 15–25% |

## 1. Mapa completo — caminhos oficiais (passam pelo gateway)

| Arquivo | Linha | Função | Endpoint relacionado |
|--------|------|--------|---------------------|
| `services/v8_4_cohort.py` | 333 | `run_pilot_cohort` | `/api/ai-center/v7/v8/causality/run-pilot` |
| `services/v8_2_first_cash.py` | 105 | `attribute_first_cash` | `/api/ai-center/v7/v8/first-cash/*` |
| `services/execution_v7.py` | 305 | `execute_v7_action` | `/api/ai-center/v7/cash/*` |

**Total oficial: 3 pontos.** Todos cobertos por: ✅ `HOMOLOG_MODE` · ✅ `kill_switch.whatsapp` · ✅ `CAUSALITY_PILOT_PHONES`.

## 2. Mapa completo — bypasses ATIVOS (sidecar direto)

| Arquivo | Função/Endpoint | Método de envio | safe_send | HOMOLOG | KillSwitch | Risco |
|---------|----------------|------------------|-----------|---------|-----------|-------|
| `routes/whatsapp_baileys.py` | `POST /api/whatsapp-baileys/send` (linha 386) | `_sidecar_post("/send")` | ❌ | ❌ | ❌ | 🔴 **CRÍTICO** |
| `routes/whatsapp_baileys.py` | `POST /api/whatsapp-baileys/send-audio` (208) | `_sidecar_post_silent("/send")` (~17 chamadas) | ❌ | ❌ | ❌ | 🔴 **CRÍTICO** |
| `routes/disparo_boleto.py` | `POST /disparo-boleto/send` (176) + `/send-single` (326) | `_sidecar_post_at(base_url,"/send",...)` | ❌ | ❌ | ❌ | 🔴 **CRÍTICO** |
| `routes/disparo_promo.py` | `POST /disparo-promo/send` (222) | `_sidecar_post("/send")` | ❌ | ❌ | ❌ | 🔴 **CRÍTICO** |
| `routes/whatsapp_campaigns.py` | `POST /campaigns/drafts/{id}/approve` (169) | `_sidecar_post_silent` | ❌ | ❌ | ❌ | 🔴 **CRÍTICO** |
| `routes/mass_messaging.py` | (não detectado import direto, mas referencia sidecar) | — | ❌ | ❌ | ❌ | 🟠 **ALTO** (a confirmar) |
| `routes/referrals.py` | `POST /r/{code}/submit` (734) + outras | `_sidecar_post_silent_at` (6×) | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `routes/wifi_hotspot.py` | venues / sessions (203, 217, 319) | `_sidecar_post_silent("/send")` | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `routes/neo_reports.py` | `POST /briefing/activate` (623), `/schedules/{sid}/run` (216) | `_sidecar_post_silent("/send","/send-document")` (4×) | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `services/pre_attendance_promo.py` | (worker pre-atendimento) | `_sidecar_post_silent("/send","/send-document")` (4×) | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `services/leo_proactive.py` | (worker autônomo Leo) | `_sidecar_post_silent` (2×) | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `services/presidente_ia_briefing.py` | (worker Presidente IA) | `_sidecar_post_silent` (2×) | ❌ | ❌ | ❌ | 🟠 **ALTO** |
| `services/lousa_coaching.py` | (auto-coach OS) | `_sidecar_post_silent` (2×) | ❌ | ❌ | ❌ | 🟡 **MÉDIO** |
| `services/retirada_workflow.py` | (workflow retirada de equipamento) | `_sidecar_post_silent` (2×) | ❌ | ❌ | ❌ | 🟡 **MÉDIO** |

> Observação: `whatsapp_baileys.py` é o módulo **público** do WA — endpoint `POST /api/whatsapp-baileys/send` é chamado pelo frontend de atendimento. Bypassa 100% das travas.

## 3. Classificação do risco — critério

- **🔴 CRÍTICO** — endpoint público / disparo em massa: pode mandar mensagem real para qualquer número assim que `HOMOLOG_MODE` for desligado, sem passar por whitelist nem kill switch.
- **🟠 ALTO** — worker autônomo / endpoint autenticado: dispara sem intervenção humana, em loop ou evento.
- **🟡 MÉDIO** — fluxo específico, baixo volume.

## 4. Resposta à pergunta-mestra

> **"Quantos caminhos conseguem enviar WhatsApp hoje?"**

**RESPOSTA:** **≥ 15** caminhos distintos identificados (3 oficiais + 12 bypass). Estima-se que **75–85% do tráfego real** de WhatsApp do SmartProv passa por caminhos que **não verificam** `HOMOLOG_MODE`, `kill_switch` ou whitelist `CAUSALITY_PILOT_PHONES`.

## 5. Consequência prática

A trava `HOMOLOG_MODE=true` que protege a operação hoje funciona porque o **sidecar Baileys** está configurado para apontar para um número técnico. Se em algum momento o sidecar real for ativado para tráfego de produção (mudança de `WA_SIDECAR_URL` ou tokens), **todos os 12 arquivos com bypass passarão a enviar mensagens reais imediatamente**, sem nenhuma das salvaguardas das blindagens V8/V9.

> O sistema está protegido hoje **por configuração**, não **por arquitetura**.

---

**Próximo passo (fora desta auditoria):** refatoração cirúrgica dos 12 bypasses para chamarem `safe_send_whatsapp`. Estimativa: 6–10h de trabalho + testes.
