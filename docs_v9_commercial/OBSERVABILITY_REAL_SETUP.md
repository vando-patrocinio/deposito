# V9 P1 — Observability Twin Real (Setup de Credenciais)

> **STATUS:** DRAFT V9.4 — instruções operacionais para o CTO.
> **OBJETIVO:** ligar o conector Zabbix/Grafana real **sem alterar uma linha de código** — a infraestrutura técnica (`observability_twin.py`) já é mock-fallback-by-default.

---

## 1. Estado atual

Os conectores `ZabbixConnector` e `GrafanaConnector` (em `/app/backend/services/observability_twin.py`) detectam automaticamente as credenciais via `.env`:

- `is_real == True` quando **URL + (token OU user/password)** estão presentes
- `is_real == False` quando URL vazia → retorna fixtures internas determinísticas (modo MOCK)

A propriedade `is_real` é exposta no endpoint `GET /api/ai-center/observability/connectors/status`, permitindo auditoria em tempo real do estado dos conectores.

---

## 2. Como ligar em produção (passo a passo)

### Passo 1 — Editar `/app/backend/.env`

Adicionar as variáveis abaixo (não substituir nenhuma chave existente):

```bash
# ── Zabbix ──────────────────────────────────────────────
# OBRIGATÓRIO: URL do Zabbix (sem barra no final)
ZABBIX_URL=https://zabbix.seu-provedor.com.br

# OPÇÃO A (RECOMENDADA): API token Zabbix (>=5.4)
ZABBIX_API_TOKEN=cole-aqui-o-token

# OPÇÃO B (LEGADO): user + password (versões antigas)
# Use SOMENTE se a OPÇÃO A não estiver disponível.
# ZABBIX_USER=
# ZABBIX_PASSWORD=

# OPCIONAL: desligar verificação SSL (apenas em ambientes internos)
# ZABBIX_VERIFY_SSL=false


# ── Grafana ─────────────────────────────────────────────
# OBRIGATÓRIO: URL do Grafana (sem barra no final)
GRAFANA_URL=https://grafana.seu-provedor.com.br

# OBRIGATÓRIO: Service Account Token (Grafana >=9)
GRAFANA_SERVICE_ACCOUNT_TOKEN=cole-aqui-o-token

# OPCIONAL: ID da organização (se multi-org)
# GRAFANA_ORG_ID=1

# OPCIONAL: desligar verificação SSL
# GRAFANA_VERIFY_SSL=false
```

### Passo 2 — Reiniciar o backend

```bash
sudo supervisorctl restart backend
```

### Passo 3 — Verificar status dos conectores

```bash
API_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)
TOKEN="<seu jwt admin>"
curl -s -X GET "$API_URL/api/ai-center/observability/connectors/status" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Resposta esperada quando real:

```json
{
  "zabbix": {"is_real": true, "url": "https://zabbix.seu-provedor.com.br",
             "auth": "token"},
  "grafana": {"is_real": true, "url": "https://grafana.seu-provedor.com.br",
              "auth": "token"},
  "mock_mode": false
}
```

### Passo 4 — Disparar pipeline completo

```bash
curl -s -X POST "$API_URL/api/ai-center/observability/run" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

A resposta deve conter `"is_mock_mode": false`.

---

## 3. Onde obter as credenciais

### Zabbix API Token
1. Login Zabbix como Super Admin.
2. **User settings → API tokens → Create API token**.
3. Permissões mínimas: `problem.get`, `host.get`, `trigger.get`, `event.get`.
4. Copie o token (mostrado apenas uma vez).

### Grafana Service Account Token
1. Login Grafana como Org Admin.
2. **Administration → Service accounts → Add service account**.
3. Role: **Viewer** (suficiente para snapshots).
4. **Add service account token → Generate token**.
5. Copie o token (mostrado apenas uma vez).

---

## 4. Validação operacional (smoke test)

Após Passo 3, rodar a suite de testes (continua usando mocks internos para isolamento):

```bash
cd /app/backend && pytest tests/test_observability.py -v
```

Esperado: **8/8 PASS**. A suite não exige credenciais reais — ela testa apenas a lógica de correlação e fallback mock.

---

## 5. Rollback (voltar ao mock)

Se algo der errado, basta esvaziar as URLs:

```bash
# Em /app/backend/.env
ZABBIX_URL=
GRAFANA_URL=
```

`sudo supervisorctl restart backend` → conectores voltam ao modo MOCK.

---

## 6. Checklist de segurança

- [ ] Tokens armazenados **somente** em `/app/backend/.env`.
- [ ] `.env` está no `.gitignore`.
- [ ] Tokens com permissão **mínima** (read-only).
- [ ] `ZABBIX_VERIFY_SSL=true` em produção pública.
- [ ] Rotação de tokens trimestral (lembrete operacional).

---

_Documento DRAFT V9.4. Atualizar após primeira execução em produção._
