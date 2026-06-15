# Solicitação Formal — Endpoints Atlaz para Disparo de Boleto via WhatsApp

**Remetente:** CTO — Universo Ligo / SmartProv
**Destinatário:** Equipe de Produto/API Atlaz
**Data:** 2026-02
**Assunto:** Pedido de evolução da API v2 para suportar disparo de cobrança via WhatsApp em conformidade com LGPD e melhores práticas PIX/CIP.

---

## 1. Contexto

A Universo Ligo opera um motor de disparo automatizado de boletos pelo WhatsApp (módulo `disparo_boleto`), integrado à Atlaz via API v2 (`https://app.atlaz.com.br/api/v2`).

**Endpoints atualmente consumidos:**
| Endpoint | Uso atual |
|---|---|
| `GET /listaclientes` | Cache local de telefones (`atlaz_clients_cache`) |
| `GET /listachamados` | Histórico de tickets para IA Isabella |
| `GET /faturas` | Faturas em aberto (campos: `valor`, `vencimento`, `linha_digitavel`, `link`) |

**Volume:** ~XX mil mensagens/mês, base de XX mil assinantes.

**Lacunas críticas identificadas** (impacto financeiro, jurídico e operacional):

1. Telefone do cache não traz `opt-in` de cobrança → **risco LGPD/Marco Civil**.
2. Faturas não expõem **PIX (copia-e-cola + QR Code)** → conversão pagamento−mobile prejudicada.
3. Não há endpoint de **2ª via** com recálculo de juros/multa → enviamos boleto vencido com valor errado.
4. URL do PDF (`link`) **expira em horas** → cliente clica e o link quebra.
5. Sem webhook `fatura.paga` → disparamos cobrança para quem já pagou (cache 22h de atraso).
6. Sem confirmação de entrega no Atlaz → quebra na rastreabilidade fiscal/auditoria.

---

## 2. Solicitações P0 — Críticas (sem isso, entregamos com erro ou em desconformidade legal)

### 2.1 Contatos do cliente com flags de consentimento
```
GET /api/v2/clientes/{id}/contatos
```
**Resposta esperada:**
```json
{
  "contatos": [
    {
      "id": "ctt_1",
      "tipo": "whatsapp",
      "telefone": "+5511999998888",
      "principal": true,
      "whatsapp_validado": true,
      "optin_cobranca": true,
      "optin_marketing": false,
      "dnd": false,
      "atualizado_em": "2026-02-10T12:34:56Z"
    }
  ]
}
```
**Por que:** Hoje pegamos o primeiro telefone do cache, sem garantia de validade ou opt-in. Risco jurídico real (LGPD Art. 7º + Marco Civil + Resolução CGI).

---

### 2.2 PIX inline na fatura
```
GET /api/v2/faturas/{id}/pix
```
**Resposta esperada:**
```json
{
  "fatura_id": "FAT-123",
  "pix_copia_cola": "00020126...6304ABCD",
  "pix_qrcode_base64": "iVBORw0KGgoAAAA...",
  "pix_txid": "TX2026021012345",
  "pix_chave": "12345678000199",
  "pix_expiracao": "2026-02-15T23:59:59-03:00",
  "valor": 149.90
}
```
**Por que:** Conversão boleto→pagamento aumenta 3-5× quando o cliente paga via PIX direto pelo WhatsApp, sem precisar digitar linha digitável de 47 dígitos.

---

### 2.3 2ª via com recálculo de juros e multa
```
POST /api/v2/faturas/{id}/segunda-via
```
**Body:**
```json
{ "nova_data_vencimento": "2026-02-20" }
```
**Resposta esperada:**
```json
{
  "fatura_id": "FAT-123-V2",
  "fatura_original_id": "FAT-123",
  "linha_digitavel": "23793...",
  "codigo_barras": "23791...",
  "pdf_url": "https://atlaz-cdn/.../FAT-123-V2.pdf",
  "pdf_ttl_seconds": 604800,
  "pix_copia_cola": "0002012...",
  "valor_principal": 149.90,
  "juros": 1.20,
  "multa": 3.00,
  "valor_total": 154.10,
  "novo_vencimento": "2026-02-20"
}
```
**Por que:** Hoje enviamos boleto vencido com valor original. Cliente reclama na ouvidoria; perdemos liquidez.

---

### 2.4 PDF do boleto com URL estável
```
GET /api/v2/faturas/{id}/pdf
```
- Retornar `application/pdf` **ou** URL pré-assinada com TTL ≥ 7 dias.
- Header `Cache-Control: max-age=604800` aceitável.

**Por que:** O campo `link` atual quebra em horas; cliente abre o WhatsApp horas depois e o link já não funciona.

---

## 3. Solicitações P1 — Eliminar envios incorretos

### 3.1 Webhook `fatura.paga`
```
POST /api/v2/webhooks/subscribe
```
**Body:**
```json
{
  "callback_url": "https://api.universoligo.com/api/atlaz/webhooks",
  "events": [
    "fatura.paga",
    "fatura.cancelada",
    "fatura.gerada",
    "cliente.optout_atualizado"
  ],
  "secret": "..."
}
```
- Assinatura HMAC SHA-256 no header `X-Atlaz-Signature`.
- Retry exponencial 1m / 5m / 15m / 1h.

**Por que:** Cache de 22h faz dispararmos cobrança para quem pagou às 08h59 do mesmo dia. Embaraço operacional recorrente.

---

### 3.2 Delta sync de faturas
```
GET /api/v2/faturas?modified_after=2026-02-10T08:00:00Z&status=aberto
```
- Suportar `modified_after` (ISO 8601) e `cursor` para paginação.

**Por que:** Reduz custo de polling em ~95% e nos permite enviar sempre com dado fresco.

---

### 3.3 Preferências de canal e horário do cliente
```
GET /api/v2/clientes/{id}/preferencias
```
**Resposta esperada:**
```json
{
  "canal_preferido": "whatsapp",
  "horario_permitido": { "inicio": "09:00", "fim": "20:00", "timezone": "America/Sao_Paulo" },
  "idioma": "pt-BR",
  "dias_permitidos": ["seg","ter","qua","qui","sex","sab"]
}
```
**Por que:** Conformidade com Marco Civil Art. 7º (autonomia do usuário) + reduz reclamações.

---

## 4. Solicitações P2 — Rastreabilidade fiscal e conciliação

### 4.1 Confirmação de entrega no Atlaz
```
POST /api/v2/faturas/{id}/notificacoes
```
**Body:**
```json
{
  "canal": "whatsapp",
  "status": "entregue",
  "message_id": "wamid.HBgN...",
  "timestamp": "2026-02-10T14:32:10-03:00",
  "telefone_destino": "+5511999998888"
}
```
**Por que:** Registra no histórico do cliente Atlaz que a cobrança foi notificada — peça-chave para auditoria fiscal e ouvidoria.

---

### 4.2 Webhook `pix.recebido` para conciliação em tempo real
```
Evento: pix.recebido
```
**Body:**
```json
{
  "fatura_id": "FAT-123",
  "txid": "TX2026021012345",
  "valor": 154.10,
  "data_credito": "2026-02-10T14:35:00-03:00",
  "pagador_documento": "12345678901"
}
```
**Por que:** Conciliação automática + fechamento imediato de tickets de cobrança aberta.

---

### 4.3 Flag `registrado_cip` no boleto
```
GET /api/v2/faturas/{id}
```
**Acrescentar ao payload:**
```json
{
  "registrado_cip": true,
  "banco_emissor": "001",
  "convenio": "12345",
  "nosso_numero": "00000000123456789"
}
```
**Por que:** Sabermos se o boleto vai liquidar via banco (CIP) ou se é avulso/promissória.

---

## 5. Resumo executivo

| Prioridade | Endpoint | Impacto esperado |
|---|---|---|
| **P0** | `GET /clientes/{id}/contatos` com `optin_cobranca` | Risco LGPD eliminado |
| **P0** | `GET /faturas/{id}/pix` | Conversão pagamento **+200-300%** |
| **P0** | `POST /faturas/{id}/segunda-via` | Reclamações ouvidoria **−80%** |
| **P0** | `GET /faturas/{id}/pdf` (TTL ≥ 7d) | Quebra de link → zero |
| **P1** | Webhook `fatura.paga` | Disparo para quem já pagou → zero |
| **P1** | `GET /faturas?modified_after=` | Custo polling **−95%** |
| **P1** | `GET /clientes/{id}/preferencias` | Conformidade Marco Civil |
| **P2** | `POST /faturas/{id}/notificacoes` | Rastreabilidade fiscal |
| **P2** | Webhook `pix.recebido` | Conciliação automática |
| **P2** | Flag `registrado_cip` | Distinção bancária |

---

## 6. Compromissos da Universo Ligo

- Implementar autenticação de webhooks com HMAC SHA-256.
- Respeitar `dnd` e `optin_cobranca=false` (mensagem nunca disparada).
- Honrar `horario_permitido` do cliente.
- Reportar `notificacoes` ao Atlaz sempre que a mensagem for entregue.
- Auditoria pública das taxas de entrega/leitura/pagamento por cohort.

---

## 7. Contato técnico

- **CTO Universo Ligo:** [a preencher pelo CEO]
- **E-mail técnico:** [a preencher]
- **Documentação interna:** este arquivo, mantido em `/app/memory/ATLAZ_API_REQUEST_BOLETO.md`

---

*Documento gerado em CTO Mode — Evidência → Causa Raiz → Impacto → Confidence (HIGH).*
