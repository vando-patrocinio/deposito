# 🚀 DEPLOY GUIDE — CEO Digital (Custom GPT do CEO)

> Tempo total: ~5 minutos · Reversível 100%.

## 📦 O que precisa ir pra produção

5 arquivos novos + 1 alteração + 1 import:

| Arquivo | Tipo |
|---|---|
| `backend/routes/ceo_digital.py` | **novo** · endpoints + OpenAPI |
| `backend/services/executive_memory.py` | **novo** · snapshot + course correction |
| `backend/scripts/executive_memory_snapshot.py` | **novo** · CLI |
| `backend/rbac_policy.py` | **alterado** · adicionado `/api/ceo` em `NON_STAFF_AUTH_PREFIXES` |
| `backend/server.py` | **alterado** · 2 linhas importando e registrando router |
| `scripts/deploy_ceo_digital_prod.sh` | **novo** · script de deploy idempotente |

## ⚡ Passo a passo (você + time de infra)

### 1. Save to GitHub (no painel Emergent · 1 clique)
Use o botão **"Save to GitHub"** no input do chat. Vai commitar os 6 arquivos.

### 2. No servidor de produção
```bash
ssh seu-usuario@servidor-app.ligo.systems
cd /app                                  # ou onde estiver o repo
git pull origin main                     # ou a branch que usam
chmod +x scripts/deploy_ceo_digital_prod.sh

# (opcional) trocar o token dev por um seguro só pra prod:
export CEO_BRIEFING_TOKEN_PROD=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
export PUBLIC_BACKEND_URL_PROD="https://app.ligo.systems/operacional"

# roda o deploy:
sudo -E bash scripts/deploy_ceo_digital_prod.sh
```

O script faz tudo: valida arquivos → grava `.env` → restart backend → smoke test local → smoke test público → backfill 30d.

Se algum passo falhar, ele **sai com erro** e mostra o que checar.

### 3. Pegar o token final
```bash
grep CEO_BRIEFING_TOKEN /app/backend/.env
```

## 🤖 Configurar o Custom GPT no ChatGPT

(você, no celular ou desktop)

1. `chat.openai.com` → **My GPTs → Create**
2. Nome: **Presidente IA · Ligo**
3. **Instructions** (cola):
   > Você é o Presidente IA da Ligo. Sempre que o CEO perguntar sobre estado da empresa, KPIs, riscos, oportunidades ou trajetória, chame `ceoBriefingToday` (ou `ceoBriefingNow` se ele pedir snapshot novo). Use `ceoMemory` para tendências dos últimos 30 dias e `ceoMetas` para metas anuais. Responda em português, direto, sóbrio. Sempre cite os números do `one_truth` antes de opinar. Use `course_summary` para responder rápido "estamos na rota ou não".
4. **Actions → Create new action → Import from URL**:
   ```
   https://app.ligo.systems/operacional/api/ceo/openapi.json
   ```
5. **Authentication → API Key → Auth Type: Bearer** → cola o token do passo 3.
6. Salva.

## ✅ Validação no próprio ChatGPT

Abre uma conversa no GPT que você criou e pergunta:
- *"E aí, como tá a Ligo hoje?"*
- *"A gente vai bater a meta de 3.500 clientes esse ano?"*
- *"Qual o maior risco?"*

Ele vai chamar a Action, ler os números reais (clientes=2.753, MRR=R$ 323k, course=fora da rota) e narrar.

## 🔁 Rollback

Se quiser desfazer **TUDO**:

```bash
# 1. servidor de produção:
cd /app && git revert <hash-do-commit-do-save>
sudo supervisorctl restart backend

# 2. limpar tag dos snapshots:
cd backend && python3 scripts/executive_memory_snapshot.py --rollback

# 3. apagar Custom GPT no ChatGPT (3 cliques).
```

Zero perda de dados. `president_daily` original mantido. `.env` da prod só ganhou 2 variáveis (pode remover).
