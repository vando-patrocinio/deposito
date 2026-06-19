# 📊 Painel Grafana — Operação 98 — Guia de Instalação

**Data:** 19/02/2026  
**Arquivo:** `op98_kpi_dashboard.json` (mesma pasta)  
**Objetivo:** Acompanhar os 8 KPIs operacionais da Operação 98 em tempo real, **sem
escrever código novo** — apenas configurar datasource Mongo e importar o JSON.

---

## 1. Painéis incluídos

| # | Painel | Tipo | Fonte | Threshold |
|---|--------|------|-------|-----------|
| 1 | Cobertura Operacional — co-demo | Gauge | `subscribers` agregado | 🔴 < 85 / 🟡 < 93 / 🟢 ≥ 98 |
| 2 | Subscribers OFFLINE — co-demo | Stat | `subscribers` status=OFFLINE | 🟢 0 / 🟡 500 / 🔴 2.000 |
| 3 | ONUs sem status (todos tenants) | Stat | `smartolt_onus` status=null | 🟢 0 / 🟡 1k / 🔴 5k |
| 4 | ONUs LOS recuperáveis — co-demo | Stat | `smartolt_onus` LOS/Power/Offline | 🟢 0 / 🟡 200 / 🔴 800 |
| 5 | Swap events pendentes | Stat | `auto_ont_swap_events` status=null | 🟢 0 / 🟡 50 / 🔴 200 |
| 6 | Cobertura por tenant (top 8) | Bar gauge | `subscribers` aggregate by tenant | gradient |
| 7 | Status ONUs — co-demo | Donut | `smartolt_onus` group by status | classic |
| 8 | Status Gate Reabertura (verde/vermelho) | Stat | `subscribers` % calc | binário |

---

## 2. Pré-requisitos no Grafana

### Opção A — Plugin MongoDB Datasource (recomendado)
1. Grafana 10+ com plugin `grafana-mongodb-datasource` instalado.
2. Configurar datasource:
   - **Name:** `MongoDB-SmartProv`
   - **Connection string:** `mongodb://<host>:27017` (mesmo `MONGO_URL` do backend)
   - **Database:** valor de `DB_NAME` (`/app/backend/.env`)
   - **Read-only:** ✅ (importante — Grafana SÓ deve ler)

### Opção B — Via API REST do Backend
Se o plugin Mongo não puder ser instalado, criar 5 endpoints `/api/ops/kpi/*`
no backend (fora do escopo desta Operação 98 — exige desenvolvimento). 
**Pulamos.**

---

## 3. Como Importar

```
Grafana UI →  Dashboards  →  New  →  Import
              ↓
   Upload JSON: op98_kpi_dashboard.json
              ↓
       Selecionar datasource: MongoDB-SmartProv
              ↓
                Import
```

---

## 4. Queries Mongo prontas (referência)

### 4.1 Cobertura Operacional co-demo
```javascript
db.subscribers.aggregate([
  { $match: { company_id: "co-demo" } },
  { $group: {
      _id: null,
      total: { $sum: 1 },
      active: { $sum: { $cond: [{ $in: ["$status", ["ATIVO", "ACTIVE"]] }, 1, 0] } }
  }},
  { $project: {
      _id: 0,
      coverage_pct: { $multiply: [{ $divide: ["$active", "$total"] }, 100] }
  }}
])
```

### 4.2 Subscribers OFFLINE co-demo
```javascript
db.subscribers.countDocuments({ company_id: "co-demo", status: "OFFLINE" })
```

### 4.3 ONUs sem status (todos tenants)
```javascript
db.smartolt_onus.countDocuments({ status: null })
```

### 4.4 ONUs LOS recuperáveis co-demo
```javascript
db.smartolt_onus.countDocuments({
  company_id: "co-demo",
  status: { $in: ["LOS", "Power fail", "Offline"] }
})
```

### 4.5 Auto swap events pendentes
```javascript
db.auto_ont_swap_events.countDocuments({ status: null })
```

### 4.6 Cobertura por tenant
```javascript
db.subscribers.aggregate([
  { $group: {
      _id: "$company_id",
      total: { $sum: 1 },
      active: { $sum: { $cond: [{ $in: ["$status", ["ATIVO", "ACTIVE"]] }, 1, 0] } }
  }},
  { $project: {
      tenant: "$_id",
      coverage_pct: { $multiply: [{ $divide: ["$active", "$total"] }, 100] }
  }},
  { $sort: { coverage_pct: -1 } }
])
```

---

## 5. Modo Read-Only — Garantias

O painel **apenas consulta**. Nenhuma mutação. Conforme regra Operação 98:
- ✅ Sem novo código backend
- ✅ Sem alteração de schema
- ✅ Sem schedule de write
- ✅ Sem alteração da lógica de cobertura

Se o datasource for configurado com usuário Mongo de leitura, mesmo se houver
bug no JSON, nenhum efeito colateral é possível.

---

## 6. Alertas opcionais

Sugestões de alert rules para incluir no Grafana (não no JSON pra manter
neutro):

| Alerta | Condição | Severidade | Notificação |
|--------|----------|------------|-------------|
| Cobertura caiu abaixo de 95% | painel 1 < 95 por 1h | High | Slack #ops |
| OFFLINE subiu acima de 500 | painel 2 > 500 | High | Slack #ops |
| Swap events pendentes > 200 | painel 5 > 200 | Medium | Slack #ops |
| ONUs LOS > 200 em co-demo | painel 4 > 200 | Medium | Slack #ops |

---

## 7. Roadmap (não-bloqueante)

- Adicionar painel histórico (time series) ao invés de só "agora" — exige
  índice em `created_at`/`updated_at` no Mongo.
- Adicionar painel Receita Potencial Perdida = (OFFLINE × ticket médio).
- Integrar com Prometheus se quiser alertas no AlertManager existente.

---

**Assinado:** E1 Operations Engineer  
**Aprovação:** CEO — Ordem Executiva Operação 98 / Opção "A" (19/02/2026)
