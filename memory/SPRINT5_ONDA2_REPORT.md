# SPRINT 5 · ONDA 2 — NORMALIZAÇÃO OWNER/LOCATION

**Empresa**: `co-demo` · **Executado**: 2026-02-19 (UTC)
**Mandato**: CEO 18/06/2026 — Sprint 5 Onda 2
**Status**: ✅ **APLICADO** com sucesso (idempotente)

## OBJETIVO
Criar esquema canônico cliente ↔ CTO ↔ porta no doc `subscribers` e curar órfãos.

## CAMPOS ADICIONADOS EM `subscribers`
| Campo                  | Tipo        | Descrição |
|------------------------|-------------|-----------|
| `cto_id`               | string      | ID canônico da CTO onde o cliente está |
| `cto_port_id`          | string      | ID canônico da porta (`{cto_id}-p{N}`) |
| `cto_port_number`      | int         | Número da porta (1..n) |
| `cto_port_assigned_at` | ISO datetime| Quando foi vinculado |
| `cto_port_source`      | string      | Fonte do vínculo (ex.: `sprint5_onda2_backfill`) |
| `owner_normalized_at`  | ISO datetime| Marca da execução da Onda 2 |

## RESULTADO DA EXECUÇÃO

| Métrica                        | Antes | Depois |
|--------------------------------|------:|-------:|
| Subscribers ativos             | 2.783 | 2.783 |
| Subs com `cto_id` populado     |     1 |     2 |
| Subs com `cto_port_id`         |     0 |     1 |
| `cto_ports` ocupadas           |     3 |     1 |
| Portas com subscriber fantasma |     2 |     0 |
| Órfãos curados (NÃO deletados) |     — |     2 |

### Cura de órfãos
2 portas (`test-iter196-cto-p5`, `test-iter196-cto-p7`) tinham
`subscriber_id` apontando para clientes inexistentes
(`test-iter196-cli`, `test-iter196b-cli`).
**Ação**: liberadas com `release_reason=sprint5_onda2_orphan_subscriber`.
**Golden Rule respeitada**: zero deletes.

### Índices criados (idempotentes)
- `subscribers.cto_id_1` (sparse)
- `subscribers.cto_port_id_1` (sparse)

## ENDPOINTS DISPONÍVEIS
- `GET  /api/sprint5/onda2/status` — métricas atuais
- `GET  /api/sprint5/onda2/preview` — dry-run
- `POST /api/sprint5/onda2/normalize-owner-location?dry_run=false`
- `GET  /api/sprint5/onda2/audit-log?batch_id=...&limit=100`

Acesso: `administrador` / `gestor` (super_admin bypass funciona).

## AUDIT TRAIL
Collection `sprint5_audit_log` — 4 eventos no batch
`o2b-f4e41448535846`:
1. `subscriber.cto_link_set` → sub-c1a6d684e0 (Vando)
2. `cto_port.orphan_released` → cto_port test-iter196-cto-p5
3. `cto_port.orphan_released` → cto_port test-iter196-cto-p7
4. `wave.completed` → resumo do batch

## COBERTURA ATUAL
**0.04%** — esperado e esclarecido:

> A cobertura real do gate Onda 2 (≥95%) só será atingida **APÓS** a Onda 4
> (Genesis SmartOLT). Hoje só temos 3 portas ocupadas no banco; ~1.800 ONUs
> faltam ser importadas via reconciliação SmartOLT → Estoque.

## PRÓXIMO PASSO RECOMENDADO
- **Onda 3** — Tornar `cto_id` + `port_number` obrigatórios nos fluxos
  Lousa (install/repair/swap/retrieval). Valida no completion_data.
- **Onda 4** — Genesis import (~1.800 ONUs) — vai elevar a cobertura
  Owner/Location drasticamente.

## REGRESSÃO / CONTROLE
- ✅ Idempotente: 2ª execução retornou 0 updates.
- ✅ Dry-run: confirma plano sem alterar nada.
- ✅ Audit log com `batch_id` rastreável.
- ✅ Zero deletes.
