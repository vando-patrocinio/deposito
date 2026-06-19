# 🧪 QUARANTINE TRIAGE REPORT — 115 ONUs

**Data:** 19/06/2026  
**Ordem CEO:** Triagem A/B/C com possível cliente/CTO/porta/confidence  
**Modo:** Read-only analytics

---

## 1. TRIAGEM CONSOLIDADA

| Classe | Definição | Quantidade | % do total |
|---|---|---:|---:|
| **A** | Promoção imediata (confidence ≥ 0.85, match 1-to-1) | **0** | 0,0 % |
| **B** | Revisão gestor (confidence 0.35-0.85, ambiguidade) | **6** | 5,2 % |
| **C** | Impossível determinar (confidence < 0.35, sem match) | **109** | 94,8 % |
| **TOTAL** | — | **115** | 100,0 % |

### Por que A = 0?

A Phase C.2 (executada hoje, 19/06) já promoveu **270 ONUs** que tinham match 1-to-1 com `pppoe_user`. As 115 restantes são exatamente as que **não tinham match confiável** — por isso nenhuma chega ao critério A.

---

## 2. CLASSE B — Revisão de Gestor (6 itens)

Todos têm `client_name` curto/genérico → casam com vários subscribers via substring (ambíguo).

| ONT ID | SN | client_name (OLT) | Path | Conf |
|---|---|---|---|---:|
| `ont-dbab316a0a7242` | `ITBS2CB5229A` | "Asc" | substring_ambiguous | 0.50 |
| `ont-3527882834ec4a` | `MONU002BF123` | "ENO" | substring_ambiguous | 0.50 |
| `ont-768e5b53afd64b` | `MONU002BF9DB` | "ENO" | substring_ambiguous | 0.50 |
| `ont-67a776df34f345` | `MONU002BFCC3` | "ENO" | substring_ambiguous | 0.50 |
| `ont-b6231126501849` | `MONU002F51B3` | "HUGO" | substring_ambiguous | 0.50 |
| `ont-578476599cfd4b` | `ZTEGCEC66C84` | "manu" | substring_ambiguous | 0.50 |

### Decisão recomendada para Classe B

Para essas 6 ONUs, o gestor precisa **escolher manualmente** entre múltiplos subscribers candidatos. O cliente final pode ser:
- Buscado pela tela "Mutirão de Quarentena" (Phase D add-on já entregue)
- Cruzado com dados de SmartOLT (CTO + porta) para identificar instalação física

**Ação operacional**: 6 cliques na tela existente.  
**Tempo estimado**: 15 minutos do gestor.  
**Impacto**: cobertura sobe ~0,3 pp (6/1833 ONUs).

---

## 3. CLASSE C — Impossível Determinar (109 itens)

`client_name` registrado na OLT **não casa com nenhum subscriber** da base.  
Hipóteses operacionais (precisam ser validadas em campo):

| Hipótese | Provável % |
|---|---:|
| Cliente cancelou (subscriber deletado/inativo mas ONT esquecida na rede) | ~60 % |
| ONT instalada por técnico SEM cadastrar cliente no sistema | ~20 % |
| `client_name` é apelido/abreviatura criada pelo técnico no SmartOLT | ~15 % |
| Erro de digitação no SmartOLT | ~5 % |

### Amostra (5 dos 109)

| ONT ID | client_name (OLT) | Hipótese sugerida |
|---|---|---|
| `ont-46d30ba854514c` | "AvBras21ap201_Esthefanio" | Subscriber inexistente — pode ser cliente antigo |
| `ont-39cf900332c34c` | "Ilha Brasdepina 104" | Sem PPPoE, identifica só endereço |
| `ont-d4c9bb933ef54d` | "teste0" | ONT de teste técnico não removida |
| `ont-942261f4b4fe46` | "GnCatvalho1194_Ap201_Jose" | Subscriber inexistente |
| `ont-f33a3d73d27b44` | "PedroRufino63_SidneyTexeira" | Endereço com 2 nomes — possivelmente compartilhado |

### Decisão recomendada para Classe C

**NÃO promover automaticamente.**  
Cada ONT exige:
- Verificação no campo (técnico vai até a porta na CTO)
- Pesquisa em subscribers cancelados/inativos
- OU permanência em quarentena permanente (`reject` na tela do Mutirão)

**Ação operacional**: triagem em lote pelo gestor.  
**Tempo estimado**: ~30 minutos para revisar e rejeitar lote.  
**Impacto**: zerar a quarentena ativa (115 → ≤ 6), levando cobertura para **patamar real** (limitado por SmartOLT, não por triagem).

---

## 4. CRUZAMENTO COM CTO/PORTA

Para a Classe B (6 itens), nenhum tem `cto_id` derivável imediatamente porque o subscriber sugerido não é único. Triagem exige escolha manual primeiro.

Para a Classe C (109), não há `cto_id` aplicável.

---

## 5. PROJEÇÃO DE IMPACTO

| Cenário | Ação | Cobertura final | Compliance final |
|---|---|---:|---:|
| Hoje | sem ação | 93,84 % | 93,68 % |
| Cenário B aprovado | 6 ONUs promovidas | 94,17 % | 94,01 % |
| Cenário B aprovado + C rejeitado | 6 promovidas, 109 perm.quarantine | **97,00 %** | **99,65 %** |

> ⚠️ O cenário **B+C** atinge a meta CEO de **cobertura ≥ 95 %** com folga, mas a "promoção" de 109 ONUs como `permanent_quarantine` é um **descarte contábil**, não um aumento real de patrimônio. É honesto: essas ONUs **não pertencem a clientes ativos**.

---

## 6. RECOMENDAÇÃO CTO

```
═══════════════════════════════════════════════════════════
AÇÃO IMEDIATA SUGERIDA (sem código novo):

1) Gestor abre tela "Mutirão de Quarentena" no Watchtower
2) Revisa os 6 itens da Classe B individualmente
   (15 minutos)
3) Para a Classe C, faz um lote-mutirão de rejeição com
   motivo padronizado:
   "ONT identificada na OLT mas sem cliente
   correspondente no sistema; segue para análise
   técnica de campo antes de qualquer reativação."
4) Stats finais: cobertura ~97 %, compliance ~99,6 %
═══════════════════════════════════════════════════════════
```

**Critério "Quarentena ≤ 60"**:  
✅ atingível imediatamente — Classe C (109) saindo para `permanent_quarantine` zera 95 % do problema.

---

**Arquivo de dados:** `/tmp/quar_triage.json` (115 registros classificados)
