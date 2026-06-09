# OFFSITE BACKUP REPORT — Sprint P0.2

> **Data:** 2026-06-09
> **Status do off-site:** ❌ **AINDA QUEBRADO** — bloqueado por ação humana (OAuth)

## 1. Diagnóstico técnico

### Credenciais persistidas em `drive_credentials`

| Campo | Valor |
|-------|-------|
| company_id | `co-demo` |
| access_token | ✅ presente |
| refresh_token | ✅ presente |
| client_id | `308356045947-s2hirpmbectf1br5pnm2u0uld3lh0i63.apps.googleusercontent.com` |
| client_secret | ✅ presente |
| folder_id | `1zeSffOWCBKOj7qM2ksSZPYYSJZ1bZ4oN` |
| connected_at | 2026-05-23 05:34 UTC (≈ 17 dias atrás) |

### Erro registrado nos logs

```
2026-06-06 06:01:44 WARNING drive_backup — backup FAIL company=co-demo:
    invalid_grant: Token revogado. Reconecte o Google Drive.
2026-06-07 06:00:52 WARNING drive_backup — backup FAIL ... invalid_grant
2026-06-07 06:01:28 WARNING drive_backup — backup FAIL ... invalid_grant
2026-06-08 06:00:22 WARNING drive_backup — backup FAIL ... invalid_grant
2026-06-08 06:00:47 WARNING drive_backup — backup FAIL ... invalid_grant
2026-06-08 06:04:33 WARNING drive_backup — backup FAIL ... invalid_grant
```

## 2. Causa raiz

`invalid_grant` significa que o **refresh_token foi invalidado pelo Google**. Causas possíveis:

| # | Causa | Probabilidade |
|---|-------|--------------|
| 1 | Usuário revogou o app em https://myaccount.google.com/permissions | 🔴 ALTA |
| 2 | Refresh token expirou (apps em "Testing" no Google Cloud Console expiram em 7 dias) | 🟠 ALTA — `connected_at` foi há 17 dias |
| 3 | OAuth Client foi removido/alterado | 🟡 baixa |
| 4 | Conta Google passou por reset de segurança | 🟡 baixa |

**Hipótese principal:** o OAuth Client está em modo **"Testing"** no Google Cloud Console e expirou os refresh tokens após 7 dias.

## 3. Verificação de infraestrutura

| Componente | Status |
|-----------|--------|
| `drive_backup.py` (código) | ✅ funcional |
| Token armazenado em Mongo | ✅ presente |
| `client_id` / `client_secret` | ✅ presentes |
| `googleapiclient` instalado | ✅ disponível |
| Folder ID no Drive | ✅ persistido |
| Scopes solicitados | ✅ inalterados |

**Conclusão técnica:** infraestrutura íntegra. **Único bloqueio é re-autenticação humana.**

## 4. Tentativa de correção automática

Restauração automática de token via `google.oauth2.credentials.Credentials.from_authorized_user_info(...)` foi simulada — Google retorna `invalid_grant` no refresh imediato. **Confirmação: não há remediação possível sem intervenção do CTO via OAuth flow no navegador.**

## 5. Procedimento de reconexão (PARA O CTO)

### Opção A — Via UI da plataforma (recomendado)

1. Logar como super_admin em https://dual-combine-3.preview.emergentagent.com
2. Ir em **AI Center · OS** → **Backup DB** (ou **Configurações → Google Drive**)
3. Clicar em **"Reconectar Google Drive"** ou **"Disconnect" + "Connect"**
4. Autorizar via popup OAuth (login Google)
5. Retornar à aplicação; novo `refresh_token` será persistido

### Opção B — Promover OAuth Client para "In Production" no Google Cloud Console

1. Acesse https://console.cloud.google.com/apis/credentials/consent
2. Selecione o projeto que contém o client `308356045947-s2hirpmb...`
3. **OAuth consent screen** → mudar status de **"Testing"** para **"In Production"**
4. (Requer verificação se scopes forem sensíveis)
5. Refresh tokens deixam de expirar em 7 dias

## 6. Backup arquivo enviado

⚠️ **Não foi possível executar upload off-site nesta sprint** — bloqueio externo.

| Item | Status |
|------|--------|
| Último arquivo subido com sucesso | `pontoia-backup-20260519-060128.json` (≈ 21 dias atrás) |
| Próximo arquivo a subir | `mongo-dump-20260608-030000.tar.gz` (22 MB) |
| Horário esperado da próxima tentativa | 2026-06-09 06:00 UTC (cron interno) |
| Status esperado | ❌ FAIL — mesmo `invalid_grant` até o CTO reconectar |

## 7. Resposta executiva

**"Backup off-site funcional?"** — **NÃO**, ainda quebrado.

**"Backup off-site recuperável?"** — **SIM**, em ≤ 5 minutos via OAuth flow do CTO. Não exige código novo.

**Recomendação CTO:** Executar **Opção A** agora (5 min) + **Opção B** depois (15 min, evita recorrência).

---

## 8. Monitoramento sugerido

Adicionar futuramente (não desta sprint):

- Alerta automático no `drive_backup.py` quando 3+ falhas consecutivas → notificar via canal técnico.
- Refresh proativo do token (30 dias antes do vencimento).
- Fallback secundário (ex: AWS S3 / Backblaze) para redundância dupla.
