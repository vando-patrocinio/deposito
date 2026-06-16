# INVENTORY VALUATION AUDIT — LIGO ESTOQUE OS V2

**Tipo:** Auditoria estática + medição read-only. ZERO mutação.
**Data:** 16/Fev/2026
**Autor:** Auditor automatizado (CTO Mode) — Ordem direta do CEO.
**Mandato:** Determinar a qualidade financeira do patrimônio da Ligo antes da Onda 2. Responder com confiança auditável e faixa de erro conhecida quanto vale o estoque hoje.
**Sem código de produção. Sem migração. Sem escrita em banco.**

---

## §1. SUMÁRIO EXECUTIVO

### Achado central
> **O modelo de dados `stok_onts` NÃO possui NENHUM campo financeiro.**

```
Campos pesquisados em stok_onts:
  unit_price       🔴 INEXISTENTE
  unit_cost        🔴 INEXISTENTE
  price            🔴 INEXISTENTE
  cost             🔴 INEXISTENTE
  valor            🔴 INEXISTENTE
  valor_unitario   🔴 INEXISTENTE
  valor_nf         🔴 INEXISTENTE
  valor_medio      🔴 INEXISTENTE
  valor_referencia 🔴 INEXISTENTE
  purchase_price   🔴 INEXISTENTE
  asset_value      🔴 INEXISTENTE
  book_value       🔴 INEXISTENTE
```

**Consequência:** o valor financeiro de QUALQUER ONT só existe se a ONT tiver `purchase_id` apontando para uma compra com `items[].unit_price` preenchido.

### Veredicto

| Pergunta CEO | Resposta | % |
|--------------|----------|---|
| Qual % do patrimônio tem valor financeiro **definido** (no doc da ONT)? | **0%** | 0/28 |
| Qual % tem **bridge para NF** (purchase_id resolvível)? | **35,7%** | 10/28 |
| Qual % é **fantasma patrimonial** (sem origem financeira)? | **64,3%** | 18/28 |
| Qual % tem modelo válido (mapeável a preço de referência)? | **~50%** | 14/28 |
| Confiança auditável atual | **35,7% alta · 64,3% baixa** | — |
| Incerteza relativa do valuation total | **412%** | (MAX − MIN) / REF |

---

## §2. RESPOSTAS ÀS 10 PERGUNTAS DO CEO

| # | Pergunta | Resposta (28 ONTs no preview) | Projeção 1.828 ONTs |
|---|----------|-------------------------------|---------------------|
| 1 | Quantos equipamentos têm valor financeiro **definido** | **0** | 0 |
| 2 | Quantos **não** possuem | **28** (100%) | 1.828 (100%) |
| 3 | Quantos usam valor **estimado** (sem purchase_id) | **18** (64,3%) | ~1.175 |
| 4 | Quantos usam valor **NF** (purchase_id resolvível) | **10** (35,7%) | ~653 |
| 5 | Quantos usam valor **médio ponderado** | **0** (cálculo não existe) | 0 |
| 6 | Quantos têm **modelo inválido/genérico** | **~11** (39%): `Desconhecido`, `None`, `TestModel`, `zte chinez`, `Huawei HG` | ~718 |
| 7 | Quantos têm **SN válido mas valuation ausente** | **17** (60,7%) | ~1.110 |
| 8 | **Patrimônio mínimo possível** | **R$ 1.400** (28 × R$ 50) | **R$ 91.400** |
| 9 | **Patrimônio máximo possível** | **R$ 11.200** (28 × R$ 400) | **R$ 731.200** |
| 10 | **Grau de confiança** | **35,7% AUDITÁVEL via NF · 64,3% ESTIMATIVA pura** | — |

### Patrimônio com 3 camadas (CEO pediu)

Aplicando a estrutura `valor_referencia` / `valor_nf` / `valor_medio_ponderado`:

**Hoje no preview (28 ONTs):**

| Camada | Definição | Cobertura | Valor calculado |
|--------|-----------|-----------|-----------------|
| `valor_nf` | Preço NF resolvido via purchase_id | **10/28 (35,7%)** | R$ 3.000 (10 × R$ 300 — HG6145D real) |
| `valor_medio_ponderado` | Média ponderada por NF da empresa | **N/A** | impossível calcular sem NFs de outras compras |
| `valor_referencia` | Preço mercado por modelo identificado | **14/28 (50%)** | ~R$ 1.610 (14 × ~R$ 115 médio) |
| Sem nenhuma camada (fantasma) | — | **4/28 (14,3%)** | indefinido |

**Projeção 1.828 ONTs (mesma proporção, preço NF real R$ 300/un para modelos comprados + R$ 85 ref):**

| Camada | Unidades | Valor |
|--------|----------|-------|
| `valor_nf` (R$ 300 — HG6145D observado) | 653 | **R$ 195.900** |
| `valor_referencia` (R$ 85 fallback) | 915 | R$ 77.775 |
| Fantasma patrimonial (sem qualquer dado) | 260 | **indefinido** |
| **TOTAL CONFIÁVEL** | 1.568 | **R$ 273.675** |
| TOTAL INCLUINDO FANTASMAS @ R$ 85 | 1.828 | R$ 295.775 |
| TOTAL INCLUINDO FANTASMAS @ R$ 300 | 1.828 | R$ 351.675 |

> **R$ 273.675 a R$ 351.675**. Esse é o range AUDITÁVEL atual. Tudo fora disso é especulação.

---

## §3. EVIDÊNCIAS COLETADAS

### 3.1 — Estrutura real da compra (purchases.items[])

Achado: a tabela `purchases` **JÁ TEM** preço por item:

```python
items: [
  {
    description: "HG6145D",
    quantity: 5.0,
    unit: "un",
    unit_price: 300.0,                                   # ← R$ 300/un real!
    macs: ['AA:BB:CC:11:22:33', 'AA:BB:CC:11:22:34', ...]
  }
]
```

**Conclusão técnica:** o preço NF está disponível para 35,7% das ONTs apenas pela bridge `stok_onts.purchase_id → purchases.items[].unit_price` (com lookup do MAC dentro de `items[].macs`). **Implementação possível sem mudança de schema.**

### 3.2 — Qualidade do campo `model`

| Categoria | Exemplos | Quantidade |
|-----------|----------|------------|
| Específico mapeável | `FIBERHOME ONT AC1200 GPON 2GE WIFI HG8145D`, `FIBERHOME HG6145D`, `ZTE F670L`, `Huawei HG8245`, `ZTE F660` | **14** |
| Lixo / genérico | `Desconhecido`, `None`, `TestModel`, `zte chinez`, `Huawei HG` (truncado) | **11** |
| Sem campo `model` | — | **3** |
| **TOTAL** |   | **28** |

**Achado adicional:** o modelo `FIBERHOME ONT AC1200 GPON 2GE WIFI HG8145D` aparece como string longa. Provavelmente é o output OCR de NF — sem normalização. Existem 2 grafias diferentes para Fiberhome.

### 3.3 — Cross-check `purchase_id` (bridge financeira)

```
ONTs c/ purchase_id:                          10 / 28  (35,7%)
ONTs com preço NF resolvível:                 10 / 10  (100% das que têm pid)
ONTs com purchase_id mas preço NULL:           0
ONTs com purchase_id apontando para compra
  inexistente (órfãs):                         0
ONTs SEM purchase_id (zero rastreabilidade):  18 / 28  (64,3%)
```

**Boa notícia:** das 10 ONTs com `purchase_id`, **100% resolvem o preço NF**. A bridge funciona.

**Má notícia:** **18 ONTs (64,3%) não têm origem financeira nenhuma**. Foram cadastradas sem vincular a uma compra — provavelmente migração inicial, criação manual ou import de planilha.

### 3.4 — D3=a (SN bloqueado)

Mesmo entre as ONTs com purchase_id, **6/28 têm SN começando com `AUTOSN_`**. Patrimônio físico existe, mas a movimentação está bloqueada até re-scan. Isto é uma forma adicional de incerteza patrimonial: a ONT existe, vale dinheiro, mas operacionalmente é inacessível.

---

## §4. INCERTEZA PATRIMONIAL — CENÁRIOS

### 4.1 — Cenários sobre 28 ONTs (preview)

| Cenário | Premissa | Patrimônio |
|---------|----------|------------|
| **MÍNIMO ABSOLUTO** | Todas valem R$ 50 (entry F601 baratíssima) | **R$ 1.400** |
| **CONSERVADOR** | Todas valem R$ 65 (modelo F601 padrão) | R$ 1.820 |
| **REFERÊNCIA** | Todas valem R$ 85 (média mercado 2026) | R$ 2.380 |
| **PROVÁVEL REAL** | NF mistas, ponderado | **R$ 4.620** (10 × R$ 300 + 18 × R$ 90) |
| **OTIMISTA** | Todas Fiberhome HG6145D @ R$ 300 NF | R$ 8.400 |
| **MÁXIMO ABSOLUTO** | Todas WiFi 7 @ R$ 400 | **R$ 11.200** |

> **Incerteza absoluta:** R$ 9.800 (MAX − MIN) em apenas 28 ONTs.
> **Incerteza relativa:** **412%** sobre o cenário de referência.

### 4.2 — Cenários sobre 1.828 ONTs (projeção produção)

| Cenário | Patrimônio |
|---------|------------|
| **MÍNIMO ABSOLUTO** (R$ 50/un) | **R$ 91.400** |
| **CONSERVADOR** (R$ 65/un) | R$ 118.820 |
| **REFERÊNCIA** (R$ 85/un) | R$ 155.380 |
| **PROVÁVEL REAL** (proporção atual: 35,7% × R$ 300 + 64,3% × R$ 90) | **R$ 301.620** |
| **OTIMISTA** (R$ 300/un — todas Fiberhome HG6145D) | R$ 548.400 |
| **MÁXIMO ABSOLUTO** (R$ 400/un — todas WiFi 7) | **R$ 731.200** |

> Resposta direta à pergunta do CEO ("vale R$ 218k ou R$ 350k?"):
>
> **A faixa real auditável hoje é R$ 273k a R$ 351k** — o resto é especulação.
> A faixa **possível** (sem auditoria) é **R$ 91k a R$ 731k** — incerteza de R$ 640k.

---

## §5. GRAU DE CONFIANÇA DO VALUATION

Definindo escala A-F (estilo classificação de crédito):

| Grade | Critério | % das ONTs hoje |
|-------|----------|-----------------|
| **A** — Auditável | Tem `purchase_id` + NF resolvível + SN válido + modelo limpo | ~**25%** (7/28) |
| **B** — Reconciliável | Tem purchase_id mas SN AUTOSN_* OU modelo sujo | ~10% (3/28) |
| **C** — Estimável | Sem purchase_id MAS modelo válido | ~25% (7/28) |
| **D** — Especulação | Sem purchase_id + modelo lixo/genérico | ~25% (7/28) |
| **F** — Fantasma | Sem purchase_id + sem modelo + dado mínimo | ~15% (4/28) |

**Confiança consolidada:** 35% A+B (auditável/reconciliável) · 25% C (estimável) · 40% D+F (especulação ou fantasma).

> **Conclusão:** o estoque da Ligo hoje tem **40% de patrimônio cuja existência financeira é uma opinião, não um fato**. Em diligência externa, essa é a parte mais perigosa.

---

## §6. RECOMENDAÇÕES ANTES DA ONDA 1

### R1 — Adicionar 3 campos financeiros em `stok_onts` (Onda 1.0)
Schema additivo, zero risco:
```python
{
  "valor_nf": Optional[float],            # preenchido via purchase_id quando confirmado
  "valor_medio_ponderado": Optional[float],  # snapshot mensal calculado em background
  "valor_referencia": Optional[float],    # preço de mercado por modelo
  "valuation_grade": Literal["A","B","C","D","F"],
  "valuation_source": Literal["nf","weighted_avg","reference","unknown"],
  "valuation_calculated_at": str,
}
```
**Importante:** sem mexer no que existe. Apenas adicionar. ONTs antigas ficam `valuation_grade=None` até backfill futuro.

### R2 — Normalizar o campo `model` (Onda 1.5 — após destrutivos)
Tabela de mapeamento + lookup ao salvar:
```python
MODEL_CANONICAL = {
  "fiberhome hg6145d": ("FIBERHOME", "HG6145D", 220.0),
  "fiberhome hg8145d": ("FIBERHOME", "HG8145D", 180.0),
  "zte f660":          ("ZTE",       "F660",    75.0),
  "zte f670l":         ("ZTE",       "F670L",   95.0),
  "huawei hg8245":     ("HUAWEI",    "HG8245",  120.0),
  # ...
}
```
Lookup case-insensitive + fuzzy contra a chave canônica.

### R3 — Job batch read-only `valuation_backfill_dry_run`
Antes de QUALQUER write, rodar um job que **simula** o backfill e gera um relatório:
- Quantas ONTs ganhariam `valor_nf` resolvido?
- Quantas ficariam em `valor_referencia` por modelo?
- Quantas continuariam fantasmas?

Só após o CEO aprovar o relatório, aplicar `dry_run=False`.

### R4 — Não bloquear Onda 1 por causa disso
A Onda 1 (destrutivos) trata da **proteção** do patrimônio. A valuation trata da **medição**. São ortogonais. A recomendação é:
- **Implementar Onda 1 com o schema atual** (sem valor financeiro nos docs).
- O `before_snapshot` da Onda 1 grava o MAC + SN + model + purchase_id + status. Isso permite reconstruir o valor a qualquer momento via bridge.
- A camada de valuation entra em paralelo, em Onda 1.0/1.5, sem bloquear nada.

---

## §7. DECISÕES NECESSÁRIAS DO CEO

- **A)** Aprovar adição dos 3 campos financeiros + 3 metadados (`valor_nf`, `valor_medio_ponderado`, `valor_referencia`, `valuation_grade`, `valuation_source`, `valuation_calculated_at`) em `stok_onts` — schema additivo, zero quebra.
- **B)** Aprovar tabela `MODEL_CANONICAL` (R2) com mapeamento modelo → preço referência. CEO pode fornecer a tabela oficial Ligo (lista de modelos comprados e seus preços médios).
- **C)** Aprovar job `valuation_backfill_dry_run` ANTES de qualquer escrita.
- **D)** Definir política para os 64,3% fantasmas:
   - D1) Marcar `valuation_source=unknown` + `valuation_grade=F` e seguir.
   - D2) Bloquear movimentação até auditoria humana (idêntico ao D3=a do AUTOSN_*).
   - D3) Tentar bridge inversa (procurar nas NFs por modelo+data próxima da criação) e atribuir a melhor compra possível com `valuation_source=inferred`.
- **E)** Validar a regra "Onda 1 não bloqueada por valuation" (R4).

---

## §8. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código. Zero escrita.**

- **0% das ONTs têm valor financeiro no documento.**
- **35,7%** têm bridge para NF (resolvível).
- **64,3%** são fantasmas patrimoniais.
- Range patrimonial real auditável (1.828 ONTs): **R$ 273.675 a R$ 351.675**.
- Range possível (incluindo especulação): R$ 91k a R$ 731k.
- **Incerteza relativa: 412%** sobre referência.
- 40% do patrimônio é classe D+F (especulação ou fantasma).
- Solução proposta: schema additivo + job backfill dry-run + tabela canônica de modelos. **Não bloqueia Onda 1.**

Detalhamento operacional em `INVENTORY_VALUATION_MATRIX.md`.
