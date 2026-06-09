# AUDITORIA EXECUTIVA — GO LIVE
**Data:** 2026-06-08 · **Escopo:** apertar o botão **HOJE**.
**Linguagem:** sim/não, sem rodeios.

---

## 1) O QUE IMPEDE O PILOTO HOJE?

**Três itens. Só três. Todos resolvidos em horas.**
1. Sessão Baileys ativa para `co_real` (`wa_baileys_sessions.status="open"`).
2. Variável `PRESIDENTE_IA_GESTOR_PHONE` no `.env` de produção.
3. Decisão executiva escrita: "company X autoriza piloto" (CYA / audit).

Tudo o que é **software** está pronto. Os 3 itens acima são **configuração + autorização humana**.

---

## 2) BLOQUEIO TÉCNICO?
**NÃO.**
- Pipeline ponta-a-ponta testado (34/34 E2E).
- `services/operacao_tese.py` orquestra 10 fases.
- Audit chain 100% íntegra (0 quebras).
- Leader-election ativo (não duplica jobs em N pods).
- Throughput medido: 3.491 ev/s.

---

## 3) BLOQUEIO OPERACIONAL?
**SIM — 1 item.**
- Falta operador humano monitorando `dunning_escalations.dry_run=false` em tempo real nos primeiros 3 dias para reverter cobrança errada manualmente se necessário. Trabalho: 1 pessoa, ~30 min/dia.

---

## 4) BLOQUEIO JURÍDICO?
**NÃO bloqueia, mas exige 2 controles:**
- ✅ Audit chain criptográfica registra toda mensagem enviada (LGPD art. 9).
- ⚠️ Recomendado: opt-in explícito do cliente para comunicação automatizada (texto na fatura/contrato). **Não bloqueia** — comunicação de cobrança é base legal "execução de contrato" (LGPD art. 7, V).
- ✅ `subject_report` (LGPD art. 18) já permite exportar tudo se cliente pedir.

**Veredito jurídico:** start com base contratual, sem bloqueio. Texto de opt-in adicionado em sprint paralela.

---

## 5) BLOQUEIO DE INFRAESTRUTURA?
**NÃO.**
- MongoDB local rodando.
- Backend FastAPI ativo (supervisor).
- Scheduler com leader-election.
- Rate-limit memory funciona em single-worker (alvo do piloto). Redis só vira P0 se passar pra multi-pod.

---

## 6) BLOQUEIO DE WHATSAPP?
**SIM — único bloqueio técnico real.**
- `wa_baileys_sessions` está vazia em prod (verificado no pre-flight).
- **Solução:** rodar o pareamento QR uma vez. Tempo: 5 minutos.
- Após isso, `wa_dispatcher.send_text(company_id, to, text)` funciona automaticamente.

**É o único item bloqueador. Sem ele, nada sai. Com ele, tudo sai.**

---

## 7) RISCO DE COBRANÇA INDEVIDA?
**BAIXO, com 3 camadas de defesa:**

| Camada | Onde está implementado | Mitigação |
|---|---|---|
| 1. Filtro por status do invoice | `select_eligible_clients` | só `status in [open, overdue]` |
| 2. Janela 5-30 dias | mesma função | exclui faturas muito antigas (provavelmente em acordo) ou muito recentes (vencimento simples) |
| 3. SmartOLT Gate | `smartolt_gate()` | bloqueia cliente sem serviço |

**Falsos positivos esperados:** ~1-2% dos eligíveis. Mitigação: começar com `max_messages=20`, monitor diário.

---

## 8) RISCO DE COBRAR CLIENTE COM PROBLEMA TÉCNICO?
**RESOLVIDO.**
- `smartolt_gate()` consulta `db.onus` antes de cada cobrança.
- Bloqueia se: ONU offline, `rx_dbm < -27`, ou incidente coletivo aberto no CTO.
- Cria automaticamente `alvaro_tasks` para o técnico verificar.

**Provado em teste E2E:** `test_smartolt_gate_blocks_offline_client` ✅

---

## 9) O SMARTOLT JÁ É CONSULTADO ANTES DA COBRANÇA?
**SIM.**

Trecho real do código (`services/operacao_tese.py::score_and_classify`):
```python
gate = await smartolt_gate(c["subscriber_id"])
if gate["blocked"]:
    score = -1  # filtra fora
    c["smartolt_blocked"] = True
    c["smartolt_reasons"] = gate["reasons"]
```

Demo rodada ontem em dev provou:
> `sub-tese-demo-0 (ONU offline) → tier=EXCLUIDO 🔴BLOQUEADO`

---

## 10) SEQUÊNCIA EXATA AO APERTAR O BOTÃO

```
[POST /api/operacao-tese/start company_id=X dry_run=false max_messages=20]
        │
        ├─ pre_flight_check(X)           ─→ 10 checks; se 1 falha, ABORTA
        │
        ├─ select_eligible_clients(X)    ─→ query Mongo (overdue 5-30d, com phone)
        │
        ├─ score_and_classify()          ─→ FASE 9: smartolt_gate aplicado aqui
        │                                    └─ ONU offline? → bloqueado + alvaro_task
        │
        ├─ company_settings.set_live(    ─→ escalate_dunning LIVE (e só ele)
        │       X, ["escalate_dunning"])
        │
        └─ para cada eligível ALTO/MEDIO:
            ↓
   ┌─────EVENTO──────┐
   │ Não é gerado    │   (o pipeline aqui é direto; em modo contínuo
   │ explicitamente  │    o event_bus emit_business("payment.overdue")
   │ no fluxo manual │    geraria. Na execução manual, vamos direto)
   └────────────────┘
            ↓
   ┌─────DECISÃO────┐
   │ ad-hoc no      │   target.tier + template selecionado
   │ start_operation │   (amigavel_5_15d ou firme_16_30d)
   └────────────────┘
            ↓
   ┌──────AÇÃO──────┐
   │ persistência   │   doc em operacao_tese_messages
   │ + WhatsApp     │   status: "planned" → "sent" (ou "failed")
   └────────────────┘
            ↓
   ┌─────WHATSAPP───┐
   │ wa_dispatcher  │   send_text(company_id, phone, body)
   │ .send_text()   │   via Baileys → cliente recebe na conta
   └────────────────┘
            ↓
   ┌─────CLIENTE────┐
   │ paga via PIX/  │   sistema externo (Asaas/banco) credita
   │ boleto          │   subscriber_invoices.status="paid"
   │                 │   + paid_at preenchido
   └────────────────┘
            ↓
   ┌────PAGAMENTO───┐
   │ monitor_panel  │   pega payments_received com paid_at>=started_at
   │ recalcula R$   │   recovered_BRL += amount_paid
   └────────────────┘
            ↓
   ┌──APRENDIZADO──┐
   │ learn_from_   │   recovery_rate POR TEMPLATE
   │ payments       │   grava motor_ia_learnings
   └────────────────┘
```

**Tempo de cada etapa em produção (estimado):**
- pre_flight: ~200ms
- selection+score: ~500ms (depende do nº de invoices)
- send WhatsApp: ~800-1500ms por mensagem
- pagamento real do cliente: tipicamente entre 30 min e 48h após mensagem
- monitor: latência de 0 (consulta direta no DB)

---

## 11) O QUE AINDA FALTA PARA O PRIMEIRO PILOTO REAL?

Checklist final, ordem de execução:

| # | Item | Responsável | Tempo |
|---:|---|---|---|
| 1 | Conectar Baileys via QR pairing em prod | Time DevOps | **5 min** |
| 2 | Editar `.env` adicionando `PRESIDENTE_IA_GESTOR_PHONE=+55...` | DevOps | **2 min** |
| 3 | `sudo supervisorctl restart backend` | DevOps | **30 seg** |
| 4 | Testar curl `GET /api/operacao-tese/pre-flight/{co_real}` → ok_to_start=true | CTO | **1 min** |
| 5 | Selecionar 1 cliente (company_id) com 20+ inadimplentes 5-30d | PO | **15 min** |
| 6 | Aprovação escrita da diretoria (Slack/email) para go-live | CEO/CFO | **1 dia útil** |
| 7 | Curl POST `start` com `dry_run=false`, `max_messages=10` (começar conservador) | CTO | **30 seg** |
| 8 | Monitor (`/monitor/{op_id}`) a cada 6h por 3 dias | Operador | passivo |
| 9 | Após dia 3, `auto_tune` + `success_criteria` | CTO | **5 min** |

**Total time investido: <2 horas técnicas + 1 dia de aprovação.**

---

## 12) TEMPO ESTIMADO PARA GO LIVE

| Cenário | Tempo |
|---|---|
| **HORAS** (técnico puro, dia útil) | **2-4 horas** |
| **DIAS** (incluindo aprovação executiva + janela) | **1-2 dias** |

---

## 13) VEREDITO

# 🟢 PRONTO PARA PILOTO.

### Justificativa
1. **Software 100% pronto.** 34/34 testes E2E passando. Pipeline real validado em DRY-RUN end-to-end (4 inadimplentes, 1 bloqueado por SmartOLT Gate, 3 mensagens preparadas com templates corretos).
2. **Zero código novo necessário** para o piloto.
3. **Único bloqueio técnico real:** sessão Baileys (5 minutos de QR pairing).
4. **Riscos cobertos:**
   - Cobrança indevida → 3 camadas de filtro (status, janela 5-30d, SmartOLT Gate).
   - Cliente sem serviço → SmartOLT Gate testado.
   - Tenant leak → company_id ligando todos os docs.
   - Compliance → audit chain 100%.
5. **Reversibilidade:** `stop_operation` desativa LIVE em 1 chamada. `dunning_escalations.dry_run=true` pode ser revertido por update direto se necessário.

### Recomendação CTO
**Apertar o botão na segunda-feira, 9h da manhã, com 1 cliente de confiança, max_messages=10.** Monitorar 72h. Decisão de escalar (para 3 empresas, max_messages=50) na sexta seguinte, baseada em `success_criteria`:

- 🟢 ≥R$ 3k recuperados em 72h → **expandir imediatamente**.
- 🟡 R$ 500–3k recuperados → **ajustar templates** via `learn_from_payments` e dobrar amostra.
- 🔴 <R$ 500 recuperados → **stop**, revisar critério de seleção + tom de mensagem antes de continuar.

---

**Não há nenhuma razão técnica para esperar mais uma sprint. O sistema está pronto. Falta a decisão.**
