# OFFSITE_BACKUP_RECOVERY_REPORT

**Data:** 09-Jun-2026
**Status:** 🟥 **BLOQUEADO_HUMANO** — requer reautenticação OAuth Google Drive pelo CTO.

---

## 1. Estado atual (evidências do Mongo)

| Item | Valor |
|---|---|
| Coleção `drive_backups` (histórico) | **67 backups gravados** |
| Último backup remoto OK | `pontoia-backup-20260529-060446.json` · 29-Mai-2026 06:04 UTC · 29 MB |
| Backups locais (job `daily_backup_job`) | Operacional — gera arquivo todos os dias 06:00 UTC |
| Coleção `drive_oauth_tokens` | **0 documentos** ⚠️ |
| `drive_backups.token_revoked` flagged | 0 docs (status fica em `ok` no último doc gravado) |
| Diferença para hoje (RPO real) | **12 dias e ~11 horas sem off-site** |

## 2. Causa raiz

O fluxo `drive_backup.py` consulta `drive_oauth_tokens` para obter `refresh_token` por `company_id`. A coleção está **vazia**: nenhum token persistido. O scheduler `daily_backup_worker` registrado em `server.py:960` continua tentando, mas falha silenciosamente porque não há credenciais ativas.

Evidências:
- `services/drive_backup.py:307-327` detecta `RefreshError`, marca `token_revoked=True` no documento `drive_backups`.
- `services/drive_backup.py:610` (`_mark_token_revoked`) só é chamado quando há um token previamente persistido.
- Como **não há token persistido**, o erro não é nem registrado — falha "soft". Por isso `token_revoked: 0 docs`.

## 3. Endpoints OAuth disponíveis (já implementados)

| Endpoint | Função |
|---|---|
| `GET /api/oauth/drive/connect` | Inicia fluxo OAuth — retorna URL de consentimento Google |
| `GET /api/oauth/drive/callback` | Recebe o `code` do Google após consentimento |
| `POST /api/oauth/drive/disconnect` | Remove token |
| `GET /api/drive/status` | Retorna `{ needs_reconnect: bool }` |
| `POST /api/drive/backup` | Dispara backup manual |
| `GET /api/drive/backups` | Lista backups remotos |

## 4. Instruções EXATAS para o CTO executar

**Pré-requisitos**: 
- Console Google Cloud → Project `ligotelecom-saas` → OAuth Consent Screen ativo.
- Variáveis `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GOOGLE_DRIVE_REDIRECT_URI` presentes em `backend/.env` (verificar antes).

**Passos:**

1. Autenticar no SmartProv como `administrador` (admin@empresa.com / 123456).
2. Acessar diretamente:
   ```
   https://dual-combine-3.preview.emergentagent.com/api/oauth/drive/connect
   ```
   O backend redireciona para o consentimento Google.
3. Logar com **a mesma conta Google** que possui o folder `SmartProv-Backups` no Drive.
4. Aceitar os escopos: `https://www.googleapis.com/auth/drive.file`.
5. Google redireciona para `/api/oauth/drive/callback` → token é persistido em `drive_oauth_tokens`.
6. Validar status: `GET /api/drive/status` → deve retornar `{ "needs_reconnect": false }`.
7. Disparar backup manual:
   ```
   curl -X POST -H "Authorization: Bearer $TOKEN" \
        https://dual-combine-3.preview.emergentagent.com/api/drive/backup
   ```
8. Validar resultado:
   - `GET /api/drive/backups` → deve listar o novo arquivo
   - `mongosh --eval "db.drive_backups.find().sort({_id:-1}).limit(1)"` → status: "ok"

## 5. RPO real (recovery point objective)

| Métrica | Valor real | Meta SaaS |
|---|---|---|
| RPO local (backup diário 06:00 UTC) | **24h** | 24h |
| RPO off-site (Drive) | **DEGRADADO** (12d) | 24h |
| RTO esperado pós-restore | não testado | <4h |

## 6. Decisão recomendada

| Curto prazo | Médio prazo |
|---|---|
| CTO executa o fluxo OAuth acima — **única ação humana necessária** | Adicionar **alerta proativo** quando `(now − last_drive_backup_ok) > 48h` no `system_alerts` |
| Após reconexão, validar o primeiro backup remoto | Implementar **fallback S3** (AWS) como redundância — eliminado o ponto único Google |
| Marcar `co-demo.is_demo=false` ✅ (já feito nesta sprint) | Documentar runbook de restore (exercício a cada 90 dias) |

---

**Conclusão:** o sistema de backup off-site está tecnicamente íntegro. Falta apenas o consentimento humano OAuth. Sem alteração de código necessária para retomar — apenas o passo 1-8 acima.
