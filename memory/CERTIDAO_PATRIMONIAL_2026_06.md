# CERTIDÃO PATRIMONIAL · 2026-06

**Empresa**: `co-demo` · **Emitida**: 2026-02-19 23:45 UTC
**Status**: ✅ **APROVADA**
**Versão**: balance_engine=`sprint5_onda6_v1` · genesis=`sprint5_onda5_v1`
**Hash SHA-256**: `c3ea113a1d8cb433b9d344692420c479da15525764ee2a08114e2c192e36c05d`
**Snapshot ID**: `bal-2026-06-89f5353d75`

> **Esta é a PRIMEIRA linha de base patrimonial confiável da operação da Ligo.**

---

## 1. ABERTURA (2026-06-01)

| Categoria | Quantidade |
|-----------|-----------:|
| Ativos Oficiais | 0 |
| Ativos Quarentena | 0 |
| Patrimônio Total | 0 |

(estado pré-Sprint 5 — sem patrimônio rastreável)

## 2. MOVIMENTAÇÃO (junho/2026)

| Tipo | Quantidade |
|------|-----------:|
| Instalações | 13 |
| Trocas | 37 |
| Retiradas | 2 |
| Defeitos | 3 |
| Promoções quarentena → oficial | 0 |
| **+ Genesis Import (Onda 5)** | **+1.830** (1.443 oficiais + 387 quarentena) |

## 3. FECHAMENTO (2026-07-01)

| Categoria | Quantidade | Variação |
|-----------|-----------:|---------:|
| Ativos Oficiais | **1.443** | **+1.443** |
| Ativos Quarentena | 387 | +387 |
| Patrimônio Total | **1.830** | +1.830 |

## 4. KPIs OFICIAIS (8 + 1 do CEO)

### Patrimônio
| KPI | Valor |
|-----|------:|
| Ativos Oficiais | **1.443** |
| Ativos Quarentena | 387 |
| Patrimônio Total | **1.830** |
| Patrimônio Confiável (`data_confidence ≥0.9`) | **1.443** (100%) |

### Operação
| KPI | Valor |
|-----|------:|
| Instalações | 13 |
| Trocas | 37 |
| Retiradas | 2 |
| Defeitos | 3 |

### Governança
| KPI | Valor |
|-----|------:|
| Rastreabilidade | **100.00%** |
| Data Confidence ≥0.9 | **100.00%** |
| Compliance Patrimonial | 78.85% |

### KPI extra CEO
| KPI | Valor | Meta | Status |
|-----|------:|-----:|:------:|
| Índice de Cobertura Operacional (oficiais/SmartOLT) | **78.72%** | ≥98% | ⚠️ Abaixo da meta |

> O índice ≥98% será atingido conforme as 387 ONUs em quarentena
> forem promovidas via worker da Fase 5.2C (operação contínua).

## 5. AVALIAÇÃO DE STATUS

Regra de classificação aplicada:
- **APROVADA**: data_confidence ≥90 AND rastreabilidade ≥95 AND compliance ≥75 ✅
- COM RESSALVAS: data_confidence ≥80 OR rastreabilidade ≥85
- REPROVADA: caso contrário

**Resultado: APROVADA** (100% · 100% · 78.85%)

## 6. ASSINATURA E INTEGRIDADE

```
hash_sha256:       c3ea113a1d8cb433b9d344692420c479da15525764ee2a08114e2c192e36c05d
generated_at:      2026-06-18T23:45:16.520044+00:00
generated_by:      system (usr-2100548587 / admin@empresa.com)
balance_version:   sprint5_onda6_v1
genesis_version:   sprint5_onda5_v1
inventory_version: sprint5_onda4_canonical
```

Qualquer alteração nos KPIs ou no fechamento muda o hash —
detectabilidade total de violação de integridade.

## 7. AUTOMAÇÃO

- Cron diário **00:05 UTC** → `_onda6_daily_snapshot` registrado em
  `server.py` (AsyncIOScheduler `CronTrigger(hour=0, minute=5)`).
- Endpoint manual: `POST /api/sprint5/onda6/close-month?year_month=2026-06&confirm=true`.

## 8. ANTES vs DEPOIS DA SPRINT 5

| Métrica | Antes Sprint 5 | Depois Sprint 5 |
|---------|---------------:|----------------:|
| ONUs rastreáveis | 32 | **1.443** |
| Patrimônio confiável | 27.5% | **100%** sobre oficiais |
| Rastreabilidade | 45.6% | **100%** |
| Origem conhecida | 0% | **100%** |
| Cobertura real | 0% | **78.72%** (gradual) |

## 9. PROVA OPERACIONAL

Qualquer pessoa pode consultar agora:
- `GET /api/sprint5/onda4/resolve/{subscriber_id}` →
  Cliente → CTO → Porta → ONU → Ticket → Técnico (UMA fonte canônica)
- `GET /api/sprint5/onda6/latest` →
  Certidão JSON com hash SHA-256
- `GET /api/sprint5/onda6/history` →
  Histórico de fechamentos

---

**Certidão emitida automaticamente** por
`POST /api/sprint5/onda6/close-month?year_month=2026-06&confirm=true`
em 2026-02-19 23:45 UTC.

**Status final: ✅ APROVADA**
