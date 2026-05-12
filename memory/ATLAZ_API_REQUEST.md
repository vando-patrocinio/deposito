# Solicitação de Expansão da API Atlaz V2 — PontoIA

**Cliente:** Ligo Fibra (PontoIA)
**Data:** Maio/2026
**API atual:** `https://app.atlaz.com.br/api/v2`
**Documentação base:** https://app.atlaz.com.br/docs/api

---

## 🎯 Resumo executivo

Hoje a API Atlaz V2 só expõe **2 endpoints úteis** (`/listachamados` e `/criarchamado`). Isso nos obriga a operar com dados defasados/incompletos e não permite automação real de **cobrança, inadimplência, infraestrutura e KPIs** — funcionalidades centrais de um ISP moderno.

Estamos solicitando a expansão da API para suportar os fluxos descritos abaixo, todos já padrão em sistemas ISP do mercado (IXC Soft, MK-Auth, SGP, Voalle).

---

## 🔥 PRIORIDADE 0 — Bloqueadores de negócio

### 1. Autenticação Bearer / API Key
**Por quê:** querystring `?token=` é inseguro (vaza em logs de servidor, history, referers).

**Pedido:**
- Aceitar header `Authorization: Bearer <token>`
- Tokens com escopo (read-only vs read-write)
- Possibilidade de rotacionar token sem quebrar integrações ativas

---

### 2. Endpoint de Clientes (CRUD completo)

#### `GET /clientes`
**Parâmetros:**
- `page`, `per_page` (paginação)
- `status` = ativo | inadimplente | cancelado | suspenso
- `data_criacao_inicio`, `data_criacao_fim`
- `data_alteracao_inicio` (incremental sync)
- `cpf_cnpj`, `nome`, `telefone` (busca)
- `cidade`, `bairro`, `filial`

**Resposta esperada (cada cliente):**
```json
{
  "id": 12345,
  "codigo_cliente": "CLI-001",
  "nome": "Maria Silva",
  "cpf_cnpj": "12345678900",
  "tipo": "pf" | "pj",
  "telefones": ["11999999999", "1133334444"],
  "email": "maria@email.com",
  "endereco": {
    "cep": "01000-000",
    "logradouro": "Rua das Flores",
    "numero": "100",
    "complemento": "Apto 5",
    "bairro": "Centro",
    "cidade": "São Paulo",
    "uf": "SP",
    "lat": -23.55,
    "lng": -46.63
  },
  "filial_id": 1,
  "plano_id": 5,
  "plano_nome": "Fibra 500",
  "plano_preco": 99.90,
  "vencimento_dia": 10,
  "status": "ativo",
  "data_ativacao": "2024-01-15T10:00:00Z",
  "data_cancelamento": null,
  "motivo_cancelamento": null,
  "ultima_alteracao": "2025-05-01T14:30:00Z",
  "auth_pppoe_usuario": "maria.silva@ligo",
  "onu_serial": "ZTEG12345678",
  "olt_porta": "OLT01-1/2/3:5"
}
```

#### `GET /clientes/{id}`
Retorna detalhes completos do cliente.

---

### 3. Endpoint de Faturas / Boletos

#### `GET /faturas`
**Parâmetros:**
- `cliente_id` (filtra por cliente)
- `status` = `aberta` | `paga` | `vencida` | `cancelada`
- `vencimento_inicio`, `vencimento_fim`
- `dias_atraso_min`, `dias_atraso_max` (ex: `15` → vencidas há 15+ dias)

**Resposta esperada (cada fatura):**
```json
{
  "id": 98765,
  "cliente_id": 12345,
  "cliente_nome": "Maria Silva",
  "competencia": "2025-05",
  "vencimento": "2025-05-10",
  "valor": 99.90,
  "status": "vencida",
  "dias_atraso": 18,
  "linha_digitavel": "00190.00009 02398.000018 0987.654321 1 12345678900",
  "codigo_barras": "00190000090239800001809876543211123456789",
  "pix_copia_cola": "00020126360014BR.GOV.BCB.PIX0114...",
  "pix_qrcode_url": "https://app.atlaz.com.br/qr/98765.png",
  "boleto_pdf_url": "https://app.atlaz.com.br/boleto/98765.pdf",
  "data_pagamento": null,
  "data_emissao": "2025-04-25T00:00:00Z"
}
```

#### `GET /faturas/{id}/boleto-pdf`
Retorna o PDF (binário) do boleto.

#### `POST /faturas/{id}/enviar-cliente`
**Body:**
```json
{
  "canal": "whatsapp" | "email" | "sms",
  "destinatario_override": "5511999999999" // opcional
}
```
Envia automaticamente o boleto pelo canal escolhido (se o Atlaz tem integração interna), OU apenas registra o envio no histórico.

**🎯 Objetivo principal:** poder enviar boleto via WhatsApp sem intervenção manual.

---

### 4. Endpoint de Status de Conexão (PPPoE / DHCP)

#### `GET /conexoes/status`
**Parâmetros:**
- `cliente_id` (opcional, se omitido retorna paginado)

**Resposta:**
```json
{
  "cliente_id": 12345,
  "online": true,
  "uptime_segundos": 86420,
  "ip_atribuido": "10.20.30.40",
  "mac_address": "00:1A:2B:3C:4D:5E",
  "ultima_conexao": "2025-05-11T22:15:00Z",
  "rx_bytes": 12345678901,
  "tx_bytes": 1234567890,
  "concentrador_id": 3,
  "concentrador_nome": "BNG-LIG-01"
}
```

#### `GET /conexoes/resumo`
Agregado em tempo real para dashboards:
```json
{
  "total_clientes_ativos": 1750,
  "online_agora": 1690,
  "offline_agora": 60,
  "percentual_online": 96.5,
  "ultima_atualizacao": "2025-05-11T22:15:30Z"
}
```

---

## ⚡ PRIORIDADE 1 — Funcionalidades de gestão

### 5. Eventos de Churn (Cancelamentos)

#### `GET /eventos/cancelamentos`
**Parâmetros:**
- `data_inicio`, `data_fim`
- `motivo` (filtro)

**Resposta:**
```json
{
  "items": [
    {
      "cliente_id": 12345,
      "cliente_nome": "Maria Silva",
      "data_cancelamento": "2025-05-10T16:00:00Z",
      "motivo_codigo": "preco_alto",
      "motivo_descricao": "Cliente alegou preço elevado",
      "plano_ativo": "Fibra 500",
      "valor_mrr_perdido": 99.90,
      "meses_de_casa": 18,
      "cidade": "São Paulo"
    }
  ],
  "total": 12,
  "mrr_total_perdido": 1450.80
}
```

---

### 6. Webhooks de Eventos (push em vez de pull)

#### `POST /webhooks` (configuração)
**Body:**
```json
{
  "url": "https://nosso-sistema.com/atlaz/webhook",
  "secret": "sk_webhook_abc123",
  "eventos": [
    "cliente.criado",
    "cliente.cancelado",
    "cliente.suspenso",
    "fatura.criada",
    "fatura.paga",
    "fatura.vencida",
    "conexao.online",
    "conexao.offline",
    "chamado.criado",
    "chamado.fechado"
  ]
}
```

**Payload enviado pelo Atlaz:**
```json
{
  "evento": "fatura.paga",
  "timestamp": "2025-05-11T14:30:00Z",
  "data": {
    "fatura_id": 98765,
    "cliente_id": 12345,
    "valor": 99.90,
    "metodo": "pix"
  }
}
```

Com assinatura HMAC-SHA256 no header `X-Atlaz-Signature`.

**Benefício:** evita polling constante (economia de quota da API), latência ~zero pra reagir a eventos.

---

### 7. Endpoint de Infraestrutura (OLTs/CTOs/PONs)

#### `GET /infraestrutura/olts`
```json
[
  {
    "id": 1,
    "nome": "OLT-CENTRO-01",
    "modelo": "ZTE C320",
    "ip_gerencia": "10.0.0.1",
    "filial_id": 1,
    "total_portas": 16,
    "portas_ativas": 14,
    "total_onus": 1280,
    "onus_online": 1245
  }
]
```

#### `GET /infraestrutura/ctos`
```json
[
  {
    "id": 23,
    "nome": "CTO-RUA-DAS-FLORES",
    "lat": -23.55,
    "lng": -46.63,
    "capacidade": 16,
    "ocupacao": 12,
    "olt_porta": "OLT-CENTRO-01:1/2/3"
  }
]
```

---

### 8. Atualizações de Chamados (fechar/cancelar/reagendar)

⚠ **HOJE NÃO EXISTE.** Bloqueia automação total da Lousa.

#### `POST /chamados/{id}/atualizar`
**Body:**
```json
{
  "novo_status": "finalizado",
  "data_fechamento": "2025-05-11T15:30:00Z",
  "observacao": "Instalação concluída. ONU sinal -22dBm.",
  "tecnico_id": 7,
  "anexos": ["url1.jpg", "url2.jpg"]
}
```

#### `POST /chamados/{id}/reagendar`
```json
{
  "nova_data": "2025-05-13T09:00:00Z",
  "motivo": "Cliente solicitou"
}
```

#### `POST /chamados/{id}/cancelar`
```json
{
  "motivo": "Cliente desistiu",
  "cancelado_por": "gestor_id"
}
```

**Benefício:** automatiza o que hoje é manual no painel web do Atlaz.

---

### 9. Endpoint de Planos

#### `GET /planos`
```json
[
  {
    "id": 5,
    "nome": "Fibra 500",
    "download_mbps": 500,
    "upload_mbps": 250,
    "preco": 99.90,
    "ativo": true,
    "total_assinantes": 850
  }
]
```

---

## 📊 PRIORIDADE 2 — KPIs e Analytics

### 10. Endpoint de KPIs (read-only, agregado)

#### `GET /kpis/resumo`
**Parâmetros:** `data_inicio`, `data_fim`, `filial_id` (opcional)

```json
{
  "periodo": { "inicio": "2025-05-01", "fim": "2025-05-31" },
  "clientes": {
    "ativos_inicio_periodo": 1745,
    "ativos_fim_periodo": 1750,
    "novos": 12,
    "cancelados": 7,
    "churn_rate_percentual": 0.40,
    "ltv_medio": 2400.00
  },
  "financeiro": {
    "mrr_total": 175000.00,
    "arr_estimado": 2100000.00,
    "ticket_medio": 100.00,
    "faturamento_realizado": 168000.00,
    "inadimplencia_valor": 7000.00,
    "inadimplencia_percentual": 4.0
  },
  "infraestrutura": {
    "uptime_rede_percentual": 99.85,
    "incidentes_total": 4,
    "tempo_medio_resolucao_horas": 1.8,
    "ocupacao_pon_media_percentual": 78
  },
  "atendimento": {
    "chamados_abertos": 23,
    "chamados_fechados_no_periodo": 142,
    "sla_atendido_percentual": 92,
    "nps_medio": 8.2,
    "csat_medio": 4.5
  }
}
```

---

### 11. Endpoint de Histórico de Pagamentos

#### `GET /pagamentos`
**Parâmetros:** `data_inicio`, `data_fim`, `cliente_id`, `metodo`

```json
[
  {
    "id": 1001,
    "fatura_id": 98765,
    "cliente_id": 12345,
    "data_pagamento": "2025-05-11T14:30:00Z",
    "valor_pago": 99.90,
    "metodo": "pix" | "boleto" | "cartao" | "dinheiro",
    "conciliado": true
  }
]
```

---

### 12. Endpoint de Métricas de Rede (SNMP / NetFlow agregado)

#### `GET /rede/trafego`
**Parâmetros:** `olt_id`, `agregacao` = `hora` | `dia`

```json
[
  {
    "timestamp": "2025-05-11T14:00:00Z",
    "downstream_gbps": 12.5,
    "upstream_gbps": 3.2,
    "pico_simultaneo": 13.1,
    "clientes_simultaneos": 1690
  }
]
```

---

## 🛠 Requisitos não-funcionais

### Rate Limits
- Mínimo **1000 req/min por token** para integrações de tempo real.
- Header `X-RateLimit-Remaining` em todas as respostas.

### Paginação Cursor-based
- Trocar `?page=X&per_page=Y` por `?cursor=ABC&limit=Y` (mais eficiente para datasets grandes).

### Compressão
- Aceitar `Accept-Encoding: gzip, br` (reduz payload 5×).

### Documentação OpenAPI 3.1
- Publicar `https://app.atlaz.com.br/api/v2/openapi.json` para auto-geração de clientes (Postman, Swagger UI, etc.).

### Ambiente de homologação
- Subdomínio separado `https://homologa.atlaz.com.br/api/v2` com dados fictícios — pra testar sem afetar produção.

### Webhook retry
- Retry exponencial (5×) com backoff (1s, 5s, 30s, 2min, 10min) caso o webhook retorne erro 5xx.

---

## 📋 Resumo dos endpoints solicitados

| Prioridade | Endpoint | Método | Status hoje |
|---|---|---|---|
| P0 | `/clientes` | GET/POST | ❌ Não existe |
| P0 | `/clientes/{id}` | GET | ❌ Não existe |
| P0 | `/faturas` | GET | ❌ Não existe |
| P0 | `/faturas/{id}/boleto-pdf` | GET | ❌ Não existe |
| P0 | `/faturas/{id}/enviar-cliente` | POST | ❌ Não existe |
| P0 | `/conexoes/status` | GET | ❌ Não existe |
| P0 | `/conexoes/resumo` | GET | ❌ Não existe |
| P0 | Auth via Bearer | — | ❌ Hoje é querystring |
| P1 | `/eventos/cancelamentos` | GET | ❌ Não existe |
| P1 | `/webhooks` | POST | ❌ Não existe |
| P1 | `/infraestrutura/olts` | GET | ❌ Não existe |
| P1 | `/infraestrutura/ctos` | GET | ❌ Não existe |
| P1 | `/chamados/{id}/atualizar` | POST | ❌ Não existe |
| P1 | `/chamados/{id}/reagendar` | POST | ❌ Não existe |
| P1 | `/chamados/{id}/cancelar` | POST | ❌ Não existe |
| P1 | `/planos` | GET | ❌ Não existe |
| P2 | `/kpis/resumo` | GET | ❌ Não existe |
| P2 | `/pagamentos` | GET | ❌ Não existe |
| P2 | `/rede/trafego` | GET | ❌ Não existe |
| — | `/listachamados` | GET | ✅ Existe |
| — | `/criarchamado` | POST | ✅ Existe |

---

## 🎯 O que isso vai destravar do lado do PontoIA

| Funcionalidade | Endpoint(s) necessários |
|---|---|
| **Enviar boleto por WhatsApp** | `/faturas`, `/faturas/{id}/boleto-pdf`, `/faturas/{id}/enviar-cliente` |
| **Saber quem está online em tempo real** | `/conexoes/status`, `/conexoes/resumo` |
| **Listar clientes inadimplentes automaticamente** | `/faturas?status=vencida` |
| **Painel de churn com motivos** | `/eventos/cancelamentos` |
| **Dashboard de KPIs ISP** | `/kpis/resumo` |
| **Sync incremental de clientes** | `/clientes?data_alteracao_inicio=...` |
| **Notificar cliente ao vencer fatura** | webhook `fatura.vencida` |
| **Notificar cliente cortado/religado** | webhook `cliente.suspenso` / `cliente.ativo` |
| **Mapa de ocupação da rede** | `/infraestrutura/ctos` |
| **Automatizar fechamento de chamado** | `/chamados/{id}/atualizar` |

---

## Próximos passos

1. **Atlaz nos confirma** quais endpoints já existem internamente (talvez alguns só não estão documentados).
2. **Atlaz prioriza** P0 → P1 → P2.
3. **Atlaz publica** OpenAPI spec atualizado.
4. **PontoIA implementa** integrações conforme cada lote é liberado.

Estamos à disposição para chamadas técnicas com a equipe Atlaz para refinar a especificação de cada endpoint.

**Contato técnico (PontoIA):** Vando Patrocínio
