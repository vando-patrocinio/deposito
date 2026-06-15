# Auditoria Atlaz API v2 — Disparo de Boleto via WhatsApp

**Remetente:** CTO — Universo Ligo / SmartProv
**Data:** 2026-02
**Fonte oficial auditada:** `https://app.atlaz.com.br/docs/api` + OpenAPI YAML (`https://app.atlaz.com.br/openapi/atlaz-api-v2.yaml`, 1.117 linhas)
**Confiança:** HIGH (auditoria linha-por-linha do OpenAPI 3.1.0 oficial)

---

## 1. Inventário REAL da API Atlaz v2

A API v2 expõe **7 endpoints + 2 webhooks inbound**. Não há mais nada.

| # | Endpoint | Método | Tag | Status no nosso código |
|---|---|---|---|---|
| 1 | `/consultacliente` | GET | Clientes | ❌ **NÃO usamos** (mas resolve Issue #2) |
| 2 | `/listaclientes` | GET | Clientes | ✅ usamos, **sem `atualizado_desde`** |
| 3 | `/faturas` | GET | Faturas | ✅ usamos, **sem `retornar_pix=1`** |
| 4 | `/listachamados` | GET | Chamados | ✅ usamos |
| 5 | `/criarchamado` | POST | Chamados | ❌ não usamos |
| 6 | `/desbloquear` | POST | Ações | ❌ não usamos |
| 7 | `/derrubarponto` | POST | Ações | ❌ não usamos |
| W1 | Webhook **WhatsApp Notification** | Atlaz → nós | Webhooks | ❌ **não implementado** |
| W2 | Webhook **SMS Notification** | Atlaz → nós | Webhooks | ❌ não implementado |

**Autenticação:** parâmetro `token` (query/body), obtido em *Painel → Configurações → Recursos*.
**Base URL:** `https://app.atlaz.com.br/api/v2`.
**Convenção:** campo `success` retorna como **string** `"true"`/`"false"` (não booleano).

---

## 2. PARTE A — Ações Internas (Universo Ligo): Executar HOJE, zero pedido ao Atlaz

### A.1 [P0] Habilitar PIX inline em `/faturas` — conversão pagamento +200-300%

**Evidência:** o endpoint `/faturas` aceita `retornar_pix=1` e devolve `pix_brcode` (copia-e-cola) + `pix_qrcode_link`.

**Ação:** alterar `/app/backend/routes/atlaz_financeiro.py` para sempre incluir `retornar_pix=1` (e `retornar_nfe=1` quando aplicável).

**Esforço:** 1h. **Risco:** zero.

---

### A.2 [P0] Resolver Issue #2 (Sprint 1.1) usando `/consultacliente`

**Evidência:** `GET /consultacliente?cpf_cnpj=...` ou `?telefone=...&testar_com_e_sem_nono_digito=true` retorna `id_assinante` + `pontos_de_acesso[].username` (PPPoE) + `id_plano`.

**Ação:** backfill `subscribers.atlaz_subscriber_code` (e `atlaz_id_ponto`) executando lookup reverso para os 97,5% de assinantes sem mapping.

**Esforço:** 4-6h (script + indexação). **Risco:** baixo (read-only).

**Impacto:** desbloqueia histórico financeiro completo para a Isabella, sem aguardar Atlaz.

---

### A.3 [P0] Habilitar delta sync em `/listaclientes`

**Evidência:** parâmetro oficial `atualizado_desde=YYYY-MM-DD`.

**Ação:** trocar nosso job de 22h por delta sync incremental (a cada 15min).

**Esforço:** 2h. **Risco:** zero.

**Impacto:** dado fresco no `atlaz_clients_cache` em quase tempo real; -95% custo de polling.

---

### A.4 [P0] Implementar receiver do **Webhook WhatsApp Notification (inbound)**

**Evidência (OpenAPI):** Atlaz envia POST com payload pronto:
```json
{
  "token": "...",
  "telefone": "5511912345678",
  "mensagem": "Atlaz: ...",
  "arquivo_url": "https://.../boleto.pdf",
  "arquivo_tipo": "pdf",
  "linha_digitavel": "...",
  "pix_brcode": "..."
}
```

**Ação:** criar endpoint `POST /api/atlaz/notify/whatsapp`:
- Valida `token` contra `ATLAZ_WEBHOOK_TOKEN` em `.env`.
- Verifica opt-in interno (`outbound_optin`).
- Despacha via WhatsApp (Baileys ou Evolution).
- Responde HTTP 200.

**Esforço:** 4h. **Risco:** baixo.

**Impacto:** **estrutural** — paramos de fazer polling e o Atlaz nos avisa exatamente quando e o que disparar, com PIX já embutido. Mesmo modelo para SMS (W2).

---

### A.5 [P1] Backfill canônico `subscribers.atlaz_optin_cobranca`

**Evidência:** API Atlaz não expõe campo de opt-in (gap real, ver Parte B).

**Ação:** maquinaria interna nossa — guardar opt-in em `subscribers.outbound_optin` capturado via fluxo de boas-vindas + dupla opt-in.

**Esforço:** 6h. **Risco:** mitigação LGPD.

---

### A.6 [P1] Adotar `link_recibo` e `valor_com_juros` para mensagem após pagamento

**Evidência:** `/faturas` retorna `link_recibo` (PDF), `valor_com_juros`, `valor_pago`, `data_pagamento`.

**Ação:** atualizar template do `boleto_flow` para enviar mensagem de confirmação com `link_recibo` quando `data_pagamento != null`.

**Esforço:** 1h. **Risco:** zero.

---

## 3. PARTE B — Pedido Formal Atlaz: Gaps REAIS (não existem hoje)

Estes são pedidos **legítimos** após auditoria. Cada item abaixo foi confirmado como ausente na API v2 atual.

### B.1 [P0] CRUD completo de Chamado (hoje só tem CRIAR)

| Operação | Status hoje | Pedido |
|---|---|---|
| Criar | ✅ `POST /criarchamado` | — |
| Listar | ✅ `GET /listachamados` | — |
| **Detalhar** | ❌ inexistente | `GET /chamado/{id}` |
| **Responder** | ❌ inexistente | `POST /chamado/{id}/resposta` |
| **Transferir** (handoff) | ❌ inexistente | `POST /chamado/{id}/transferir` |
| **Fechar** | ❌ inexistente | `POST /chamado/{id}/fechar` |
| **Anotação interna** | ❌ inexistente | `POST /chamado/{id}/anotacao` |

**Justificativa:** sem isso, IA Isabella (Audit P0 Item 7 — `handoff_to_human`) não tem como agir no Atlaz. Hoje ela só lê.

---

### B.2 [P0] 2ª Via com NOVO vencimento + recálculo dinâmico

**Estado atual:** `/faturas` retorna `valor_com_juros` com base no vencimento **original**. Não há como pedir novo vencimento e regerar boleto + PIX.

**Pedido:**
```
POST /faturas/{id}/segundavia
Body: { token, nova_data_vencimento }
Resp: {
  linha_digitavel, pix_brcode, pix_qrcode_link,
  link (PDF), valor_total, multa, juros,
  novo_vencimento
}
```

**Justificativa:** cliente em atraso clica no link e o boleto vence em horas. Reclamações na ouvidoria.

---

### B.3 [P0] Endpoints de Negociação (Audit Isabella Item 8 — `negotiation_rules`)

| Endpoint sugerido | Função |
|---|---|
| `POST /faturas/{id}/promessa_pagamento` | registrar promessa com data |
| `GET /assinante/{id}/promessas_pagamento` | histórico (anti-fraude) |
| `POST /faturas/{id}/desconto` | aplicar desconto autorizado |
| `POST /faturas/{id}/parcelamento` | parcelar título |

**Justificativa:** sem isso, IA não pode negociar autonomamente sem expor a empresa a risco financeiro.

---

### B.4 [P0] Campo `optin_cobranca` em `assinante`

**Estado atual:** o objeto `AssinanteResumo` tem apenas `id_assinante`, `nome`, `cpf_cnpj`, `dia_de_vencimento`, `email`, `telefone`. **Sem flag de consentimento.**

**Pedido:** acrescentar ao schema `AssinanteResumo`:
```yaml
optin_cobranca: { type: boolean }
optin_marketing: { type: boolean }
canal_preferido: { enum: [whatsapp, email, sms, ligacao] }
horario_permitido: { type: object, properties: { inicio, fim, timezone } }
dnd: { type: boolean }
```

**Justificativa:** LGPD Art. 7º + Marco Civil. Hoje despachamos sem prova de consentimento documentado no provedor de origem do dado.

---

### B.5 [P1] Webhooks Outbound: `fatura.paga`, `fatura.cancelada`, `chamado.respondido`, `chamado.fechado`

**Estado atual:** os 2 webhooks existentes (W1/W2) são **somente para notificar comunicação** (cobrança a disparar). Não há webhooks de mudança de estado.

**Pedido:**
```
POST /webhooks/subscribe
Body: {
  callback_url, secret,
  events: [
    "fatura.paga", "fatura.cancelada", "fatura.gerada",
    "chamado.respondido", "chamado.fechado", "chamado.transferido",
    "assinante.bloqueado", "assinante.desbloqueado",
    "contrato.suspenso", "contrato.reativado"
  ]
}
```
Assinatura HMAC SHA-256 no header `X-Atlaz-Signature` + retry exponencial (1m / 5m / 15m / 1h).

**Justificativa:** sem isso, mesmo com delta sync, há janela de minutos em que disparamos cobrança a quem acabou de pagar.

---

### B.6 [P1] Conciliação PIX em tempo real

**Pedido:** evento `pix.recebido` no webhook subscription B.5 com payload `{ fatura_id, txid, valor, pagador_documento, data_credito }`.

**Justificativa:** fechamento automático de tickets de cobrança e atualização de KPI em segundos, não horas.

---

### B.7 [P1] Confirmação de entrega no Atlaz (auditoria fiscal/ouvidoria)

**Pedido:**
```
POST /faturas/{id}/notificacoes
Body: {
  token, canal: "whatsapp"|"sms"|"email",
  status: "entregue"|"lida"|"falha",
  message_id, timestamp, telefone_destino
}
```

**Justificativa:** registra no histórico do cliente no Atlaz que a cobrança foi notificada — peça-chave em disputa de ouvidoria / Procon.

---

### B.8 [P2] Endpoints estruturais para contexto 360º (Audit Isabella Item 6 — `interactions`)

| Endpoint sugerido | Função |
|---|---|
| `GET /assinante/{id}/atendimentos` | timeline unificada |
| `GET /assinante/{id}/contratos` | contratos ativos + histórico |
| `GET /assinante/{id}/equipamentos` | ONT/CPE atual |
| `GET /assinante/{id}/consumo` | banda/uptime 30d |
| `GET /assinante/{id}/visitas` | visitas técnicas |
| `GET /planos` | catálogo |
| `GET /filiais` | multi-empresa |
| `GET /tecnicos` | reassign de OS |

---

### B.9 [P2] Flag `registrado_cip` na fatura

**Pedido:** acrescentar a `/faturas[].fatura`:
```yaml
registrado_cip: { type: boolean }
banco_emissor: { type: string }
convenio: { type: string }
nosso_numero: { type: string }
```

**Justificativa:** identificar se o boleto liquida na CIP (banco) ou é avulso/promissória.

---

## 4. Resumo executivo

### O que entendemos **errado** antes desta auditoria
- Achávamos que PIX, consulta por CPF/telefone e delta sync não existiam. **Existem.**
- Achávamos que precisávamos pedir webhook outbound de cobrança. **Atlaz já notifica inbound — basta receber.**

### O que de fato precisa ser pedido ao Atlaz (resumo)
| Prioridade | Item |
|---|---|
| **P0** | CRUD completo de chamado (responder, transferir, fechar, detalhar) |
| **P0** | 2ª via com novo vencimento e recálculo |
| **P0** | Endpoints de negociação (promessa, desconto, parcelamento) |
| **P0** | Campo `optin_cobranca` + preferências no schema `Assinante` |
| **P1** | Webhooks outbound de estado (`fatura.paga`, `chamado.respondido`, etc.) |
| **P1** | Evento `pix.recebido` (conciliação) |
| **P1** | `POST /faturas/{id}/notificacoes` (rastreabilidade fiscal) |
| **P2** | Endpoints de contexto 360º (atendimentos, contratos, equipamentos, consumo, visitas, planos, filiais, técnicos) |
| **P2** | Flag `registrado_cip` |

### O que podemos fazer **hoje** sem depender do Atlaz
1. PIX inline em `/faturas` (`retornar_pix=1`).
2. Backfill Issue #2 via `/consultacliente?cpf_cnpj=`.
3. Delta sync via `atualizado_desde`.
4. Implementar receiver de Webhook WhatsApp inbound (Atlaz já entrega tudo pronto, inclusive PIX e PDF).
5. Opt-in interno em `subscribers.outbound_optin` enquanto Atlaz não expõe.
6. Usar `link_recibo` para confirmação pós-pagamento.

---

## 5. Compromissos da Universo Ligo

- Implementar HMAC SHA-256 nos webhooks novos.
- Respeitar `dnd` e `optin_cobranca=false` quando expostos.
- Honrar `horario_permitido` por cliente.
- Reportar entregas (`POST /faturas/{id}/notificacoes`) sempre que o endpoint existir.

---

## 6. Contato técnico

- **CTO Universo Ligo:** [a preencher pelo CEO]
- **E-mail técnico:** [a preencher]
- **Documento de referência interno:** `/app/memory/ATLAZ_API_REQUEST_BOLETO.md`

---

*Documento revisado em CTO Mode após auditoria do OpenAPI oficial. Evidência → Causa Raiz → Impacto → Confidence: HIGH.*
