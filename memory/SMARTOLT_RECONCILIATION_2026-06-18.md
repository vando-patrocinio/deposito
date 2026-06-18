# RECONCILIAÇÃO SMARTOLT × ESTOQUE × SUBSCRIBERS

**Empresa**: `co-demo`
**Gerado**: 2026-06-18 17:13 UTC
**Modo**: READ-ONLY · zero writes em qualquer collection
**Script**: `/app/backend/scripts/audit_smartolt_vs_estoque.py`

## 1. VEREDITO EXECUTIVO

### Δ Estoque vs SmartOLT: **97.8%** → **CRÍTICO (Sprint 5 fundacional)**
### Δ Estoque vs Subscribers ativos: **97.8%**
### Δ SmartOLT vs Subscribers ativos: **2.9%**

## 2. TABELA EXECUTIVA

| Métrica                              | Valor |
|--------------------------------------|------:|
| **SmartOLT Total** (documentos)      | 1.833 |
| SmartOLT Online                      | 1.559 |
| SmartOLT Offline                     | 10 |
| SmartOLT LOS                         | 155 |
| SmartOLT Power fail                  | 108 |
| SmartOLT outros status               | 1 |
| SmartOLT arquivadas                  | 213 |
| SmartOLT com pppoe_user              | 1 |
| SmartOLT com name (cliente livre)    | 1.832 |
| SmartOLT — universo mac∪sn único     | 2.701 |
| **Estoque Total** (`stok_onts`)      | 32 |
| Estoque Cliente                      | 1 |
| Estoque Técnico                      | 12 |
| Estoque Empresa                      | 19 |
| Estoque Defeito                      | 0 |
| Estoque outras locations             | 0 |
| Estoque — universo mac∪sn único      | 60 |
| **Interseção** (mac/sn em ambos)     | 12 |
| **SmartOLT sem Estoque**             | 2.689 |
| **Estoque sem SmartOLT**             | 48 |
| Subscribers ativos                   | 2.783 |
| Subscribers total                    | 2.824 |
| **Δ % docs Estoque vs SmartOLT**     | **98.3%** |
| **Δ % universo mac∪sn**              | **97.8%** |

## 3. RESPOSTAS ÀS 3 PERGUNTAS DO CEO

### Pergunta 1 · Onde estão as 1.833 ONUs?

Estão **exclusivamente** na collection `smartolt_onus`
(sincronizada da API SmartOLT). Nenhuma outra collection
possui essas ONUs em volume comparável:

| Collection                  | Volume co-demo |
|-----------------------------|---------------:|
| `smartolt_onus`             | 1.833 |
| `smartolt_onus_archived`    | 213 |
| `stok_onts` (pipeline novo) | 32 |
| `client_equipment_history`  | 20 |

**Conclusão**: o pipeline `stok_onts` cobre **apenas 12 de 2701 ONUs reais** (0.4%). As 1.833 são ONUs cadastradas e provisionadas no SmartOLT, mas o pipeline `stok_onts` nunca importou histórico delas.

### Pergunta 2 · Breakdown por status das 1.833 ONUs

| Status SmartOLT       | Qtd | % |
|-----------------------|----:|--:|
| Online | 1.559 | 85.1% |
| LOS | 155 | 8.5% |
| Power fail | 108 | 5.9% |
| Offline | 10 | 0.5% |
| (vazio) | 1 | 0.1% |

**Provisionadas** (administrative_status=Enabled): todas as 1.833 estão habilitadas.
**Com cliente identificado** (`pppoe_user` populado): 1 de 1.833 (0.1%) — o pppoe_user está praticamente vazio no dataset demo; identificação acontece via campo `name` livre (1.832 com nome).

### Pergunta 3 · As 32 ONTs do estoque têm rastreabilidade?

| Critério de rastreabilidade               |  Valor |
|-------------------------------------------|-------:|
| ONTs totais (`stok_onts`)                 | 32 |
| Docs com campo `id` populado              | 4 |
| Com MAC                                   | 32 |
| Com SN/scan_sn                            | 31 |
| Com `owner_id`/`owner_type`               | 0 |
| Com trilha em `stok_history` (ont_id)     | 0 |
| **% Rastreáveis**                         | **0.0%** |
| Flag `synthetic_backfill_applied`         | 31 |
| Precisam revisão humana                   | 22 |
| `stok_history` total (co-demo)            | 149 |
| `stok_history` órfã (sem ont_id)          | 149 |
| `ont_duplicate_alerts`                    | 1 |

**Veredito P3**: as 32 ONTs **NÃO têm rastreabilidade real**.
- 0 delas têm trilha amarrada via `ont_id` em `stok_history`.
- 31 foram criadas via `synthetic_backfill` (Onda 2 — origem sintética, não auditada).
- 149 eventos em `stok_history` existem mas estão **órfãos** (criados via auto-baixa Lousa, sem `ont_id` joinável).

## 4. BREAKDOWNS DETALHADOS

### 4.1 Estoque por location_type

| Location              | Qtd |
|-----------------------|----:|
| empresa | 19 |
| tecnico | 12 |
| cliente | 1 |

### 4.2 Estoque por status

| Status                | Qtd |
|-----------------------|----:|
| disponivel | 19 |
| retirada_com_tecnico | 10 |
| com_tecnico | 1 |
| instalada | 1 |
| defeito_devolver_empresa | 1 |

## 5. DIVERGÊNCIAS · AMOSTRAS

### SmartOLT sem Estoque (2.689 no total · amostra até 30)

- `ztegd022c3bc`
- `00ebd8a323a7`
- `fhtt6a9e99d8`
- `fhttc0659cbd`
- `fhttc07cd513`
- `80854488663a`
- `a0946a9d5259`
- `alclb212ad67`
- `fhtt6a957680`
- `fhttc07cdee4`
- `a0946a9d4cf9`
- `alclfcc5e1c3`
- `a0946a9cf921`
- `78303b72c20b`
- `dd16b3d4b31d`
- `cmsz3b72e089`
- `ztegc4bdf82f`
- `cmsz3b7344d9`
- `alclfcb15ba4`
- `e8f8d02300f7`
- `60a4b7e7c4b8`
- `fhttc0659d39`
- `fhtt6a9e97c8`
- `8085444e5b4d`
- `hwtccb7f21b4`
- `3cbd69982c74`
- `60a4b76d5c5b`
- `34fca1dd19c8`
- `e04ba6455b6d`
- `2868d2efeef8`

### Estoque sem SmartOLT (48 no total · amostra até 30)

- `zteg48f1abcd02`
- `snfhttc250ce0c`
- `aabbcc112233`
- `snfhttc250def5`
- `huaw48f1ab2c3d`
- `snfhttc250d4f7`
- `snfhttc250ded9`
- `aa112233444a`
- `48f1ab2c4e00`
- `beefcafe7b4f`
- `autosnee0011ec`
- `aa1122334491`
- `beefcafe69c9`
- `manuale14229aa77`
- `48f1ab2c4e99`
- `huaw48f1ab2c4e`
- `manual8e4e01ba89`
- `testit247mwdbfc02ac`
- `legacyff220696`
- `manual44bd4e0522`
- `testit247mw85ef878d`
- `autosn22334491`
- `aabbccddee01`
- `snfhttc250daa5`
- `iter211hsn8d1e7619b`
- `autosnee00115a`
- `zteg48f1abcd01`
- `autosn2233444a`
- `snfhttc250ce14`
- `manual65521f394a`

## 6. CRITÉRIO DE ENTRADA NA SPRINT 5

| Δ %      | Classificação                                    |
|----------|--------------------------------------------------|
| < 2%     | Sprint 5 pequena (ajustes finos)                 |
| 2 – 10%  | Sprint 5 média (lotes de reconciliação)          |
| 10 – 30% | Sprint 5 grande (revisão estrutural)             |
| ≥ 30%    | **Sprint 5 fundacional** (parar tudo e migrar)   |

## 7. PRÓXIMOS PASSOS SUGERIDOS

**Sprint 5 vira FUNDACIONAL.** Não é mais normalização de owner/location.

1. **Sprint 5 Fase 0 — Reconciliação Patrimonial**
   - `bulk_import_smartolt_to_stok`: importar todas as ONUs
     do SmartOLT para `stok_onts` em lotes de 100/dia
   - Marcar origem `imported_from_smartolt=true`,
     `import_genesis_via=smartolt_bulk_<YYYY-MM-DD>`
   - Bind via `mac`/`sn` quando bater com ONUs já existentes
   - Marcar restantes como `synthetic_smartolt_origin=true`
2. **Sprint 5 Fase 0.5 — Bind cliente**
   - SmartOLT `name`/`pppoe_user` → match contra `subscribers.name`
   - Quando bater: `location_type='cliente'`, `location_id=subscriber_id`
3. **Sprint 5 Fase 1 — Normalização owner/location**
   - Só depois das fases 0 e 0.5, com cobertura ≥ 95% das ONUs reais
4. **Bloquear Sprint 5.1 (Auto Balanço)** até o pipeline cobrir 95%+
5. **Ajuste 2 (split de Recuperações)** pode rodar em paralelo
   à Fase 0, pois é mudança de KPI no Watchtower, não migração

## 8. TRILHA E AUDITORIA

- Script: `/app/backend/scripts/audit_smartolt_vs_estoque.py`
- Modo: **READ-ONLY** (zero writes confirmado)
- Próxima execução recomendada: 1x/semana até a Sprint 5 começar; depois 1x/mês como gate de regressão
- Critério de saída do gate: Δ ≤ 2%
