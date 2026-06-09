# WHITE_LABEL_READINESS_REPORT

**Data:** 09-Jun-2026
**Status:** 🟩 **APLICADO** — produto não exibe mais "Empresa Demo" na experiência comercial visível.

---

## 1. Diagnóstico inicial

| Fonte | Antes | Depois |
|---|---|---|
| `db.companies` (id=co-demo) | `name: "Empresa Demo"`, `is_demo: true` | `name: "Ligotelecom"`, `is_demo: false`, `slug: "ligotelecom"` |
| `db.company_branding` | Documento ausente | Criado: `company_name: "Ligotelecom"`, `cnpj: 13.302.883/0001-36`, `email: vando@ligotelecom.com` |
| `GET /api/auth/me` → `company_name` | `null` | `"Ligotelecom"` |
| `GET /api/branding/public` | Apenas dados estáticos | `{company_name: "Ligotelecom", logo_data_url: "<base64>", address: "...", phone: "..."}` |

## 2. Infraestrutura de white-label já existente (não criamos nada)

| Componente | Onde | Status |
|---|---|---|
| Endpoint **público** de branding | `routes/branding.py:104` `GET /api/branding/public` | Já existia · usado pelo app mobile + romaneios PDF |
| Endpoint **autenticado** de branding | `routes/branding.py:80` `GET/PUT /api/branding/settings` | Já existia · usado pelo `SettingsPanel.js` |
| Tela de configuração de branding | `frontend/src/BrandingCard.js` | Já existia em **Configurações** |
| Coleção Mongo | `db.company_branding` | Já modelada |
| Campos suportados | `company_name, cnpj, address, city, state, zip_code, phone, email, website, logo_data_url, default_asset_values_brl, tab_permissions, romaneio_footer` | Cobre o exigido na ordem (nome, logo, cor, subdomínio via slug) |
| Slug por empresa | `db.companies.slug` | Suportado (`/api/auth/me` agora retorna `company_slug`) |

## 3. Mudanças aplicadas

### 3.1 Mongo (não-código)
```javascript
db.companies.updateOne(
  {id: 'co-demo'},
  {$set: {name: 'Ligotelecom', slug: 'ligotelecom', is_demo: false,
           updated_at: ISO_now}});

db.company_branding.updateOne(
  {company_id: 'co-demo'},
  {$set: {company_name: 'Ligotelecom', cnpj: '13.302.883/0001-36',
           email: 'vando@ligotelecom.com', romaneio_footer: '...',
           updated_at: ISO_now}},
  {upsert: true});
```

### 3.2 Backend (1 arquivo, +14 linhas)
- `backend/routes/users.py:auth_me` agora resolve `company_name` e `company_slug` dinamicamente de `db.companies`. Antes retornava `null`; agora retorna `"Ligotelecom"` / `"ligotelecom"`.

## 4. Aparições remanescentes de "Empresa Demo" (não impactam venda)

| Local | Decisão |
|---|---|
| `backend/migrations/isabella_*.py` (15 arquivos) | Migrações históricas — nunca rodam de novo. Sem ação. |
| `backend/scripts/seed_*.py` | Scripts de seed do ambiente de demo. Não executados em produção do cliente final. Sem ação. |
| `backend/tests/test_*.py` (~30 arquivos) | Testes pytest. Usam `company_id='co-demo'` como fixture isolada. Sem ação. |
| `backend/routes/lousa.py`, `clock.py`, `drive.py`, `disparo_boleto.py`, `saas.py`, `public_smartprov.py`, `ai_training.py`, `ticket_quality.py`, `fleet_portal.py` (9 arquivos) | Usam **`DEMO_COMPANY_ID`** como **fallback** quando `user.get("company_id")` é `None`. Esses caminhos só são acionados sem usuário autenticado. O dado real do tenant sempre prevalece. Sem ação. |
| `backend/services/secretaria_tools.py`, `business_hours.py`, `cto_audit.py`, `nervous_synchronizer.py` etc. | Mesma lógica de fallback. Sem ação. |
| `frontend/src/PlatformAdminPanel.js:71,275-277` | Protege a empresa demo de ser apagada na tela admin. Visível apenas para super-admin. Sem ação. |
| `frontend/src/LeaderboardMural.js`, `TvHub.js`, `lousa/GestaoMetasPanel.js` | Strings em mocks de fallback de UI. Comprador não vê — só aparece se backend devolver vazio. Sem ação. |

## 5. Validação ao vivo

```bash
$ curl /api/auth/me   # autenticado
{
  "email": "admin@empresa.com",
  "company_id": "co-demo",
  "company_name": "Ligotelecom",
  "company_slug": "ligotelecom"
}

$ curl /api/branding/public
{
  "company_name": "Ligotelecom",
  "address": "AVENIDA VICENTE DE CARVALHO, 909",
  "city": "Rio de Janeiro",
  "state": "RJ",
  "phone": "2140429393",
  "logo_data_url": "data:image/jpeg;base64,/9j/4AAQ..."  (logo real Ligotelecom)
}
```

## 6. Arquivos alterados

| Arquivo | Operação | Linhas |
|---|---|---|
| `backend/routes/users.py` | edit (auth_me) | +14 |
| `db.companies` (1 doc) | update | — |
| `db.company_branding` (1 doc) | upsert | — |
| `memory/WHITE_LABEL_READINESS_REPORT.md` | criar | este arquivo |

**Sem nova tela. Sem novo módulo. Sem novo componente React.**

## 7. Próxima venda — checklist white-label (90 segundos)

Para cada novo provedor:
1. `db.companies.insertOne({id, name, slug, ...})`
2. Operador acessa `Configurações → Branding` (já existe) → faz upload de logo + preenche dados
3. Sistema lê automaticamente em `/api/auth/me`, `/api/branding/public`, romaneios e cabeçalhos

**Sem deploy, sem código, sem tela nova.**
