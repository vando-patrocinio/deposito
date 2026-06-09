# VAULT READINESS REPORT — Sprint P0.1

> **Modo:** READ-ONLY. Nenhum segredo migrado nem alterado.
> **Data:** 2026-06-09

## 1. Estado da infraestrutura

| Componente | Status |
|-----------|--------|
| `services/secrets_vault.py` | ✅ existe (criado V9.4) |
| Collection `secrets_vault` | ✅ existe (vazia: 0 docs) |
| Collection `secrets_vault_usage` | ❌ não existe (mencionado no escopo, mas não implementado) |
| `SECRETS_MASTER_KEY` em `.env` | ❌ **AUSENTE** |
| `cryptography` (Fernet) | ✅ instalado (v47.0.0) |
| Endpoints admin (`POST /api/admin/safety/secrets/*`) | ✅ implementados |
| Consumidores de `secrets_vault` no código (`get_secret(...)`) | ❌ **ZERO** — vault não é lido por nenhum hot-path |

> 🔴 **CONCLUSÃO:** vault é **infraestrutura existente sem consumo real**. Cofre vazio com porta sem chave.

## 2. Auditoria dos 5 segredos críticos

| Segredo | Em `.env`? | No Vault? | Duplicado? | Protegido? | Pronto p/ migração? |
|---------|-----------|-----------|-----------|-----------|---------------------|
| `EMERGENT_LLM_KEY` | ✅ (len≈30) | ❌ | ❌ | ❌ texto plano | ✅ tecnicamente |
| `WA_SIDECAR_TOKEN` | ⚠️ (len≈0) **vazio** | ❌ | ❌ | n/a vazio | n/a |
| `ASAAS_API_KEY` | ⚠️ (len≈0) **vazio** | ❌ | ❌ | n/a vazio | n/a |
| `STRIPE_API_KEY` | ✅ (len≈16) | ❌ | ❌ | ❌ texto plano | ✅ tecnicamente |
| `GOOGLE_CLIENT_SECRET` | ✅ (len≈35) | ❌ | ❌ | ❌ texto plano | ✅ tecnicamente |

> Importante: `WA_SIDECAR_TOKEN` e `ASAAS_API_KEY` estão **VAZIOS no `.env`**. Significa que a integração Asaas está **inoperante** e o sidecar não exige token de autenticação no ambiente atual.

## 3. Outros 13 segredos sensíveis em `.env`

Identificados sem proteção adicional:

```
JWT_SECRET               ADMIN_PASSWORD            AUDITOR_PASSWORD
SEED_SECRET              RESEND_API_KEY            WA_INBOUND_TOKEN
GOOGLE_DRIVE_REDIRECT_URI REDE_IA_QR_SECRET       REDE_IA_PUBLIC_SECRET
ASAAS_WEBHOOK_TOKEN      TWILIO_AUTH_TOKEN         FLEET_INGEST_TOKEN
SECURITY_INGEST_TOKEN
```

Total: **18 secrets** sensíveis em texto plano no `.env`.

## 4. Risco de uso atual

| Cenário | Severidade |
|---------|-----------|
| `.env` vazar via screenshot/PR/Slack | 🔴 CRÍTICO — 18 secrets expostos |
| Container snapshot copiado | 🔴 CRÍTICO — `.env` viaja junto |
| Rollback git acidental restaura `.env` antigo com chave revogada | 🟠 ALTO |
| Rotação de chave Stripe/Asaas exige redeploy | 🟡 MÉDIO (operacional) |

## 5. Pré-requisitos para migração ao vault

| Pré-requisito | Status |
|--------------|--------|
| `SECRETS_MASTER_KEY` gerada e em `.env` | ❌ pendente (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| Refator de **cada consumidor** dos 5 segredos para chamar `get_secret(...)` | ❌ pendente |
| Fallback `vault → .env` para compatibilidade | ⚠️ não implementado |
| Backup separado da `SECRETS_MASTER_KEY` (fora do `.env`) | ❌ não há plano |
| Teste pytest para vault round-trip | ✅ existe (`test_safety_p0.py::test_secrets_vault_round_trip`) |

## 6. Resposta à pergunta-mestra

> **"O Vault está pronto ou não?"**

**RESPOSTA:** **NÃO.**

O vault está **construído mas inerte**:

- ✅ Código de criptografia funciona (testado em pytest, 6/6 PASS).
- ❌ Chave mestre ausente → tentar `get_secret` em runtime retorna `None`.
- ❌ Nenhum consumidor real (`grep` confirma 0 imports fora do próprio módulo e dos tests).
- ❌ Zero segredos migrados.

**Resumindo:** o vault hoje é um **artefato de governança**, não uma **camada de proteção operacional**.

---

**Caminho mínimo para tornar o vault funcional (NÃO executar sem aprovação):**

1. Gerar `SECRETS_MASTER_KEY` e adicionar ao `.env` (1 minuto).
2. Restart backend (`supervisorctl restart backend`).
3. Migrar 5 segredos críticos via `POST /api/admin/safety/secrets/{name}`.
4. Refatorar consumidores: em cada call site, trocar `os.environ.get("X")` por `await get_secret("X") or os.environ.get("X")` (fallback).
5. Validar e remover do `.env`.

Esforço estimado: **3–4 horas** para os 5 segredos críticos.
