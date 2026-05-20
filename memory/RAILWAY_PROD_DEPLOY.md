# 🚂 Railway — Deploy do WhatsApp Sidecar (Produção ligo.site)

> **Cenário**: Railway voltou após incident GCP. Re-deploy do sidecar pra ligo.site.
> **Preview continua usando sidecar local no pod Emergent** (não mexer).
> **Isolamento garantido**: `WA_SESSION_ID=isabella-prod` evita colisão com `isabella` do preview.

---

## 📋 Variáveis de ambiente — copia e cola no Railway

> **Settings → Variables → Raw editor**

```env
# === MongoDB (mesma instância da produção) ===
MONGO_URL=<COLAR_AQUI_A_STRING_DE_CONEXAO_DO_MONGO_DE_PRODUCAO>
DB_NAME=<NOME_DO_DB_PRODUCAO_IGUAL_AO_BACKEND>

# === Identificação da sessão WhatsApp ===
# isabella-prod isola produção do preview (que usa "isabella")
WA_SESSION_ID=isabella-prod

# === Networking ===
PORT=3002
WA_HOST=0.0.0.0
WA_AUTH_DIR=/data/auth_info

# === Comunicação com backend Emergent (ligo.site) ===
# Endpoint onde o sidecar manda os webhooks (mensagens recebidas)
WA_WEBHOOK_BASE=https://ligo.site/api

# === Segurança ===
# Token usado pelo backend pra falar com o sidecar
WA_SIDECAR_TOKEN=t9iwWO1PF0Eo0l39JjHqrvVGQ-EhBjWsisCR4bIomFA

# Token usado pelo sidecar pra autenticar webhooks ao backend
WA_INBOUND_TOKEN=x9G8l8jcT-t64qQ2aTAL0ayzhqNlrxcb3BnjoNuVuVI

# === Browser fingerprint (anti-bloqueio) ===
WA_BROWSER_FP=Chrome (Linux),Chrome,120.0.0

# === Ambiente ===
NODE_ENV=production
```

⚠️ **Trocar `<COLAR_AQUI_...>` pelos valores reais** antes de salvar.

---

## 🚀 Passo-a-passo no Railway

### 1. Criar projeto novo
1. https://railway.com → **+ New Project**
2. **Deploy from GitHub repo**
3. Selecionar o repositório SmartProv
4. Branch: `main` (ou a branch que o Emergent usa pra produção)

### 2. Configurar service
1. Railway detecta automaticamente o repo
2. Em **Settings → Source**:
   - **Root Directory**: `whatsapp-service`
   - **Watch Paths**: `whatsapp-service/**`
3. Em **Settings → Build**:
   - **Builder**: Dockerfile (vai detectar via `railway.json`)
4. Em **Settings → Variables → Raw editor**: cola o bloco acima
5. **Deploy**

### 3. Configurar volume persistente (CRÍTICO)
1. Em **Volumes → New Volume**
2. **Mount Path**: `/data`
3. **Size**: 1 GB
4. Restart o service pra montar

**Por quê**: o `WA_AUTH_DIR=/data/auth_info` precisa persistir entre restarts. Sem volume, toda vez que Railway reinicia, você perde a sessão e precisa scanear QR de novo.

### 4. Gerar domínio público
1. Em **Settings → Networking → Public Networking**
2. **Generate Domain** (gera algo tipo `whatsapp-sidecar-prod-xxxx.up.railway.app`)
3. **Copia essa URL**

### 5. Atualizar backend de produção
Você precisa atualizar a env `WA_SIDECAR_URL` do backend em produção (Emergent Deploy):

1. Acessa **emergentagent.com → Deployments → ligo.site**
2. **Settings → Environment Variables**
3. Adiciona/atualiza:
   ```
   WA_SIDECAR_URL=https://<NOVA_URL_GERADA>.up.railway.app
   WA_SIDECAR_TOKEN=t9iwWO1PF0Eo0l39JjHqrvVGQ-EhBjWsisCR4bIomFA
   WA_INBOUND_TOKEN=x9G8l8jcT-t64qQ2aTAL0ayzhqNlrxcb3BnjoNuVuVI
   ```
4. **Redeploy** (Emergent reinicia o backend)

---

## ✅ Validação (após Railway + Emergent redeploy)

### Teste 1 — Sidecar Railway respondendo
```bash
curl https://<NOVA_URL>.up.railway.app/health
# Esperado: {"ok":true,"state":"connecting",...}
```

### Teste 2 — Backend conectado ao sidecar
1. Login admin em ligo.site
2. Vai em **Atendimento → WhatsApp** (ou similar)
3. **Deve aparecer o QR code**

### Teste 3 — Scanear QR
1. WhatsApp Business do número Isabella → ⋮ → Aparelhos conectados
2. **Conectar um aparelho** → aponta câmera pro QR
3. Em ~5s: status `connecting` → `connected`

### Teste 4 — Mensagem real
1. Manda mensagem do seu celular pessoal pro WhatsApp Isabella
2. Em ~30s deve aparecer no painel Atendimento de ligo.site
3. IA Isabella deve responder sozinha (se router ligado)

---

## 🛡 Isolamento Preview × Produção

| Ambiente | Sidecar | WA_SESSION_ID | Backend URL aponta pra |
|---|---|---|---|
| **Preview** (dual-combine-3.preview...) | Local no pod Emergent (porta 3002) | `isabella` | `http://localhost:3002` |
| **Produção** (ligo.site) | Railway novo | `isabella-prod` | `https://<NOVA>.up.railway.app` |

**Resultado**: nunca mais brigam pela mesma sessão WhatsApp.
A sessão `isabella` do preview e a `isabella-prod` da produção são contas WhatsApp **independentes** — você precisa scanear cada uma com um celular diferente, OU com o mesmo celular mas como 2 aparelhos linkados separadamente.

---

## 💰 Custo Railway estimado

| Item | Custo |
|---|---|
| Container Node 256MB-512MB RAM 24/7 | ~US$ 4-7/mês |
| Volume persistente 1GB | ~US$ 0.25/mês |
| Largura de banda (~50GB/mês) | ~US$ 0 (free tier) |
| **Total** | **~US$ 5-8/mês (R$ 25-40)** |

Free tier oferece US$ 5/mês de crédito → fica praticamente grátis até 200 clientes ativos.

---

## 🚨 Plano de contingência

Se Railway cair de novo:
1. Sidecar local no preview continua funcionando (independente)
2. Você pode **rapidamente** apontar produção pra ele temporariamente:
   - Emergent Deploy → `WA_SIDECAR_URL=https://dual-combine-3.preview.emergentagent.com:3002`
   - ⚠️ Não recomendado para tráfego real, só emergência
3. Solução definitiva no `INFRA_LOCAL_DEPLOY.md` quando estiver pronta

---

## 📝 Anotar após deploy

Quando concluir, preencha aqui:

- [ ] **Railway URL gerada**: `https://___________________.up.railway.app`
- [ ] **Data do deploy**: `__/__/2026`
- [ ] **QR Code scaneado**: ✅ / ❌
- [ ] **Primeira mensagem teste recebida em**: `__:__:__`
- [ ] **Status final**: ✅ funcionando / ❌ pendente
- [ ] **Backend `WA_SIDECAR_URL` atualizada**: ✅ / ❌

---

## 🔐 Segurança — tokens gerados

```
WA_SIDECAR_TOKEN: t9iwWO1PF0Eo0l39JjHqrvVGQ-EhBjWsisCR4bIomFA
WA_INBOUND_TOKEN: x9G8l8jcT-t64qQ2aTAL0ayzhqNlrxcb3BnjoNuVuVI
```

⚠️ **NÃO COMMITAR esses tokens no GitHub público.**
Já estão **fora** do código — só vivem nas env vars do Railway e do Emergent Deploy.

Se um token vazar:
1. Gera novo: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`
2. Atualiza nas 2 plataformas (Railway + Emergent)
3. Restart ambos services
