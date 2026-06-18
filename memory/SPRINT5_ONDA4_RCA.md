# SPRINT 5 · ONDA 4 — RCA FONTES DE VERDADE

**Empresa**: `co-demo` · **Gerado**: 2026-02-19 23:13 UTC
**Mandato**: ORDEM EXECUTIVA CEO 19/02/2026 · Fase 1 obrigatória antes de migrar

## 1. AS 3 COLLECTIONS

### 1.1 `cto_ports` (263 docs)
- **Role proposto**: AUTHORITATIVE
- **Granularidade**: 1 doc por porta física da CTO
- **Status**: 262 free, 1 occupied
- **Subscribers vinculados**: 1
- **Writers identificados**:
  - `routes/cto_ports_base.py` (CRUD admin)
  - `services/network_access_canonical.py` (esta onda)
- **Schema**: id, company_id, cto_id, port_number, status,
  subscriber_id, subscriber_name, mac, sn, signal_dbm, lat, lng,
  freed_at, occupied_at, release_reason, last_updated_at
- **Qualidade**: alta — granularidade máxima, status real
- **Cobertura física**: 100% das portas conhecidas
- **Cobertura semântica**: forward-only (preenchida conforme
  técnicos finalizam OS via Lousa)

### 1.2 `subscribers.cto_id` (campo no doc)
- **Role proposto**: PROJECTION (read-fast)
- **Subscribers totais ativos**: 2.783
- **Subscribers com `cto_id` populado**: 2 (0.07%)
- **Writers identificados**:
  - `services/network_access_canonical.py` (esta onda)
  - `routes/sprint5_onda2.py` (Onda 2 Owner/Location)
- **Qualidade**: derivada — preenchida pelo canonical_writer +
  Onda 2 backfill
- **Função**: lookup direto `subscribers.find_one(id) →
  cto_id/port_number` sem join

### 1.3 `subscriber_access_points` (5.682 docs)
- **Role identificado**: OUT_OF_SCOPE
- **Schema real** (verificado): `id, company_id, atlaz_id_ponto,
  atlaz_id_plano, address, plan_name, pppoe_user, status,
  subscriber_id, subscriber_external_id, isento, created_at,
  updated_at`
- **NÃO contém**: cto_id, port_number, ont, mac, sn
- **Writers identificados**: ATLAZ webhook (external)
- **Função real**: cadastro de ENDEREÇO/PLANO importado do ATLAZ,
  NÃO fonte de verdade de CTO/porta

## 2. EVIDÊNCIA POR CRITÉRIO

| Critério | cto_ports | subscribers.cto_id | SAP |
|----------|:---------:|:------------------:|:---:|
| Cobertura física (portas conhecidas) | **100%** | n/a | 0% |
| Cobertura semântica (links vivos) | 1/263 | 2/2783 | 0/5682 |
| Granularidade | Porta | Cliente | Endereço |
| Possui status real-time | **SIM** | NÃO | NÃO |
| Possui histórico (`freed_at`/`occupied_at`) | **SIM** | NÃO | NÃO |
| Compatibilidade SmartOLT | **SIM** (mac/sn) | parcial | NÃO |
| Compatibilidade Lousa | **SIM** (completion_data) | derivada | NÃO |
| Risco de divergência se eleita autoritativa | baixo | alto (1:N) | alto |

## 3. RESPOSTA ÀS 5 PERGUNTAS DA FASE 1

| # | Pergunta | Resposta |
|--:|----------|----------|
| 1 | Quem grava em `cto_ports`? | `cto_ports_base.py` (admin) + `network_access_canonical.py` (esta onda) |
| 2 | Quem grava em `subscribers.cto_id`? | `network_access_canonical.py` + `sprint5_onda2.py` |
| 3 | Quem grava em `subscriber_access_points`? | ATLAZ webhook (externo) — **escopo diferente** |
| 4 | Maior cobertura física? | **`cto_ports`** (263 portas físicas, 100% conhecidas) |
| 5 | Maior qualidade? | **`cto_ports`** (granular, status real, histórico) |

## 4. DECISÃO TÉCNICA

```
SOURCE_OF_TRUTH = cto_ports
```

### Justificativa
1. Maior granularidade (1 doc = 1 porta física)
2. Único com status real-time (occupied/free) e timestamps
3. Único compatível diretamente com Lousa + SmartOLT
4. Writers controláveis (apenas 2 callers)
5. Risco mínimo de divergência (1 ponto de gravação canônico)

### Papel dos demais
- `subscribers.cto_id/cto_port_id/cto_port_number` → **PROJECTION**
  materializada (read-fast). Atualização sincronizada pelo
  `canonical_writer` em CADA upsert/release.
- `subscriber_access_points` → **OUT_OF_SCOPE** (escopo diferente).
  Preservada (Golden Rule), não tocada pela Onda 4.

## 5. CAMADA DE COMPATIBILIDADE (FASE 3)

Nova collection: **`network_access_canonical`**
- Mapeia em 1 doc por porta o vértice completo:
  - cliente · CTO · porta · ONU · ticket · service · técnico
- Hash SHA-256 (`canonical_hash`) sobre 8 campos canônicos
- Atualizada APENAS por `services/network_access_canonical.py`
  (helpers `upsert_link()` e `release_link()`)
- Todas as gravações em `cto_ports` via canonical_writer recebem
  marca `last_updated_via=canonical_writer` para detectar parallel
  writes legados

## 6. PRÓXIMA FASE

Fase 2 (escolha) ✅ decidida acima.
Fase 3 (camada) ✅ implementada em `services/network_access_canonical.py`.
Fase 4 (migração) executada via `POST /api/sprint5/onda4/build-canonical`.
Fases 5-6 documentadas em `SPRINT5_ONDA4_CERTIDAO.md`.
