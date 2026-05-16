# 🚀 Deploy do WhatsApp Sidecar (Baileys) em produção

O sidecar Node.js precisa rodar em um servidor separado da Emergent porque o
deploy nativo da Emergent não roda múltiplos processos. Use **Railway** (mais
simples) ou **Render** (também bom). Custo: ~R$25–35/mês.

---

## 🥇 Caminho recomendado: Railway (5 minutos)

### Passo 1 — Criar repositório só com o sidecar

No seu computador, dentro de `/app/whatsapp-service`, faça:

```bash
git init
git add .
git commit -m "WhatsApp sidecar Baileys 7"
gh repo create smartprov-wa --private --source=. --push
# OU pelo site do GitHub: cria repo "smartprov-wa" e faz push
```

### Passo 2 — Deploy no Railway

1. Acesse https://railway.app/new
2. Clique em **"Deploy from GitHub repo"** → seleciona `smartprov-wa`
3. Railway detecta o `Dockerfile` automaticamente. Clica **Deploy**
4. Em **Settings → Volumes**: adicione um volume com mount path `/data` (1GB grátis)
5. Em **Variables**, adicione:
   - `WA_WEBHOOK_BASE` = `https://dual-combine-3.emergent.host/api`
   - `WA_INBOUND_TOKEN` = (gere um token aleatório — `openssl rand -hex 32`)
   - `WA_SIDECAR_TOKEN` = (outro token — também `openssl rand -hex 32`)
6. Em **Settings → Networking → Generate Domain**: copie a URL gerada
   (algo tipo `https://smartprov-wa-production.up.railway.app`)

### Passo 3 — Configurar a Emergent (produção) com a URL

No painel da Emergent, vá em **Deploy → Variables** e adicione no backend:

- `WA_SIDECAR_URL` = `https://smartprov-wa-production.up.railway.app`
- `WA_SIDECAR_TOKEN` = (mesmo valor que você gerou no passo 2)
- `WA_INBOUND_TOKEN` = (mesmo valor que você gerou no passo 2)

Faça **redeploy** do backend no Emergent.

### Passo 4 — Validar

1. Acesse `https://dual-combine-3.emergent.host`
2. Vá em **Atendimento IA → Configuração → Conectar WhatsApp por QR Code**
3. O QR deve aparecer em poucos segundos
4. Escaneie com seu WhatsApp Business
5. Pronto!

---

## 🥈 Alternativa: Render

Mesma coisa, mas:

1. https://dashboard.render.com/blueprints/new
2. Conecta o repo
3. Render detecta o `render.yaml` e cria tudo automático
4. Custo: USD$7/mês (plano starter — necessário pro disk persistente)
5. Cole a URL do Render no `WA_SIDECAR_URL` da Emergent

---

## 💡 Dicas importantes

### Persistência da sessão
O volume montado em `/data` salva os arquivos `auth_info/` do Baileys. Se você
**não montar** o volume, toda vez que a plataforma reiniciar o container você
vai precisar escanear o QR Code novamente.

### Segurança
O `WA_SIDECAR_TOKEN` protege o endpoint público — só quem tiver o token pode
chamar `/send`, `/qr`, etc. Sem ele, qualquer pessoa que descobrir a URL pode
mandar mensagens pelo seu WhatsApp.

### Webhook (mensagens recebidas)
O sidecar precisa **chamar de volta** o backend FastAPI a cada mensagem
recebida. Por isso `WA_WEBHOOK_BASE` deve apontar pra URL pública da Emergent
(`https://dual-combine-3.emergent.host/api`).

### Custos estimados
- Railway: USD$5 free credit/mês + uso (geralmente cabe no free tier)
- Render: USD$7/mês (plano starter — único com disk)
- Fly.io: USD$5/mês com volume

### Logs em produção
Railway/Render mostram os logs em tempo real no dashboard. Se algo quebrar,
abra a aba **Logs** e procure por `ERROR` ou `disconnected`.
