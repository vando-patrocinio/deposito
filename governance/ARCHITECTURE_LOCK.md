# 🔒 SmartProv — ARCHITECTURE LOCK (V1.0)

> Hierarquicamente subordinado a `SYSTEM_CONSTITUTION.md`.
> **Travas estruturais** que não podem ser violadas sem emenda constitucional.

---

## 1. Topologia de Serviços (TRAVADA)

```
┌────────────────────────────────────────────────────────────┐
│  Kubernetes Pod (Emergent preview / Railway production)    │
│                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │  Frontend    │   │  Backend     │   │  MongoDB     │    │
│  │  React :3000 │←→│  FastAPI:8001│←→│  :27017      │    │
│  │  (hot reload)│   │  (uvicorn)   │   │  (local)     │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
│                            ↓                               │
│                  ┌──────────────────┐                      │
│                  │  WhatsApp        │                      │
│                  │  Baileys Sidecar │                      │
│                  │  Node :3002      │                      │
│                  └──────────────────┘                      │
│                                                            │
└────────────────────────────────────────────────────────────┘
        ↑
        │  Kubernetes ingress (rotas /api/* → :8001)
        │
   https://dual-combine-3.preview.emergentagent.com
```

### Travas

- Backend **DEVE** rodar em `0.0.0.0:8001` via supervisor (chave `backend`).
- Frontend **DEVE** rodar em `:3000` via supervisor (chave `frontend`).
- Baileys sidecar **DEVE** rodar em `:3002` via supervisor (chaves `whatsapp-service*`).
- MongoDB **DEVE** ser acessado via `MONGO_URL` do `.env` (sem fallback).
- Todas as rotas de API **DEVEM** ser prefixadas com `/api`.

---

## 2. Estrutura de Diretórios (TRAVADA)

```
/app
├── backend/
│   ├── routes/          ← endpoints REST/SSE (160 arquivos)
│   ├── services/        ← lógica de negócio (135 arquivos)
│   ├── tests/           ← pytest (240 arquivos)
│   ├── server.py        ← entrypoint FastAPI (NÃO sobrescrever via create_file)
│   ├── database.py      ← cliente Mongo único
│   └── .env             ← variáveis sensíveis (NUNCA commitar segredos)
├── frontend/
│   ├── src/             ← componentes React/JSX (374 arquivos)
│   ├── public/
│   └── .env             ← REACT_APP_BACKEND_URL (protegido)
├── governance/          ← este diretório (locks invioláveis)
├── releases/            ← changelog, ADRs, inventários
├── memory/              ← PRD, CHANGELOG, test_credentials, etc.
└── docs_v9_commercial/  ← drafts comerciais V9.4 (DRAFT)
```

### Travas

- Criação de novas pastas raiz **proibida** sem emenda constitucional.
- Mover arquivos entre `services/` e `routes/` requer entrada em `DECISIONS.md`.
- Estrutura interna de `routes/` segue convenção: 1 arquivo = 1 grupo lógico, prefixo `ai_center_*` reservado para AI Center.

---

## 3. Convenções de Código (TRAVADAS)

### Backend (Python/FastAPI)

| Item | Convenção |
|------|-----------|
| Router | `APIRouter(prefix="/api/...", tags=[...])` |
| Async DB | `AsyncIOMotorClient` exclusivamente |
| ObjectId | `PyObjectId` (não retornar `_id` raw) |
| Datetime | `datetime.now(timezone.utc)` (proibido `utcnow()`) |
| Env vars | `os.environ.get('KEY')` sem default (fail fast) |
| Logging | `logging.getLogger("ponto.<module>")` |

### Frontend (React)

| Item | Convenção |
|------|-----------|
| Import API URL | `process.env.REACT_APP_BACKEND_URL` |
| Componentes UI | `shadcn/ui` em `/app/frontend/src/components/ui/` |
| data-testid | Obrigatório em todo elemento interativo |
| Toast | `sonner` (não outras libs) |
| Estado global | React Context (sem Redux) |
| Export | Named para componentes; default para páginas |

---

## 4. Padrões de Integração (TRAVADOS)

| Integração | Local | Status | Gateway |
|-----------|-------|--------|---------|
| WhatsApp Baileys | Node sidecar :3002 | ATIVO (homolog) | `services/homologation.py` (ÚNICO) |
| WhatsApp Twilio | Backup | ATIVO | `routes/whatsapp_*` |
| Atlaz (ISP-CRM) | Externo | ATIVO | `services/atlaz_*` |
| SmartOLT | Externo | ATIVO | `services/smartolt_*` |
| Zabbix | Externo | MOCK (aguarda credenciais) | `services/observability_twin.py` |
| Grafana | Externo | MOCK (aguarda credenciais) | `services/observability_twin.py` |
| Anthropic Claude | LLM | ATIVO | `emergentintegrations` |
| OpenAI | LLM | ATIVO | `emergentintegrations` |
| Stripe | Pagamento | ATIVO (test mode) | `routes/billing*` |
| Asaas | Pagamento BR | CONFIGURADO | `routes/asaas*` |
| Resend | E-mail | ATIVO | `routes/email*` |

### Trava de gateway WhatsApp

**TODA** saída de WhatsApp **DEVE** passar por `services.homologation.safe_send_whatsapp()`. Nenhum outro caminho é permitido. Violadores serão considerados bug crítico.

---

## 5. Travas de Bootstrap

O `server.py` registra exatamente **156 routes** (auditado em 2026-06-09). Diferenças nesse número exigem:

1. Entrada em `CHANGELOG.md` se intencional.
2. Investigação imediata se acidental (provavelmente perda de patrimônio).

Comando de verificação:

```bash
python3 -c "
import re
with open('/app/backend/server.py') as f: src=f.read()
tokens=set()
for b in re.findall(r'from routes import \(([^)]+)\)', src, re.DOTALL):
    for line in b.replace('\n',',').split(','):
        t=line.strip().split(' as ')[0].strip()
        if t and not t.startswith('#'): tokens.add(t)
for s in re.findall(r'from routes\.([a-zA-Z_0-9]+) import', src): tokens.add(s)
for s in re.findall(r'from routes import ([a-zA-Z_0-9 ,]+?)(?:\s+#|$)', src, re.MULTILINE):
    for t in s.split(','):
        t=t.strip().split(' as ')[0].strip()
        if t: tokens.add(t)
print(len(tokens))
"
```

Resultado esperado: **156**.

---

## 6. Travas de Frontend

O `App.js` deve manter no `NAV_GROUPS` (auditado em 2026-06-09) os seguintes **13 itens críticos** do grupo "Sistema":

- `users`, `motor-ia`
- `conselho-ia` (Presidente IA), `warroom` (Sala de Guerra)
- `ai-center` (AI Center · OS) ← **CRÍTICO**
- `cto-command` (Centro de Comando IA)
- `revenue-ops`, `data-quality`, `nervous-system`, `smartolt-twin`
- `audit-trail`, `lgpd-portal`, `backend-health`
- `settings`, `platform`, `backup`

**Perda de qualquer um desses itens é evento P0 e dispara investigação imediata.**

---

**Versão:** V1.0 — 2026-06-09
**Próxima auditoria obrigatória:** ao primeiro release.
