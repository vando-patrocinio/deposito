# SPRINT 5 · CTO + PORTA + CLIENTE — AUDITORIA FORENSE

**Empresa**: `co-demo` · **Gerado**: 2026-06-18 19:17 UTC
**Modo**: READ-ONLY · zero writes

## 1. RESUMO EXECUTIVO

- **CTOs cadastradas**: 40
- **Portas (`cto_ports`)**: 259
- **Subscribers totais**: 2.824
- **Subscribers ATIVOS**: 2.768

### Achados críticos

| Métrica                                       |   Qtd | % subs ativos |
|-----------------------------------------------|------:|--------------:|
| Subs ativos SEM porta vinculada               | 2.767 | 100.0% |
| Porta com subscriber INATIVO/INEXISTENTE      | 2 | — |
| Portas ocupadas sem subscriber_id             | 0 | — |
| Subscriber_id em porta sem registro existente | 2 | — |
| Portas com 2+ subs (duplicidade)              | 0 | — |
| Reservas vencidas > 7d                        | 0 | — |
| Schema mismatch ctos.ports[] vs cto_ports     | 0 | — |

## 2. STATUS DAS PORTAS (cto_ports)

| Status        |   Qtd |   % |
|---------------|------:|----:|
| free | 256 | 98.8% |
| occupied | 3 | 1.2% |

## 3. SCHEMA DUPLICADO — `ctos.ports[]` × `cto_ports`

O modelo tem **duas fontes de verdade** para portas:
- `ctos.ports[]` (array embed dentro de cada CTO)
- `cto_ports` (collection separada, 259 docs)

**0 CTOs** com divergência entre as duas fontes (amostra até 10):

_(sem divergências)_

⚠️ **Risco P0**: dois caminhos de escrita podem dessincronizar. Determinar fonte canônica ANTES de qualquer outro fix.

## 4. DUPLICIDADES E ÓRFÃOS

### 4.1 Portas com 2+ subscribers (amostra até 20)

_(nenhuma)_

### 4.2 Subscribers fantasma em cto_ports (2)

Portas têm `subscriber_id` que não existe na collection `subscribers`.
Causa provável: cliente removido sem liberar a porta.

- `test-iter196b-cli`
- `test-iter196-cli`

## 5. PERGUNTAS DO CEO (respostas)

| Pergunta                                           | Resposta |
|----------------------------------------------------|----------|
| Quantos clientes ATIVOS estão SEM CTO/porta?       | **2.767** (100.0%) |
| Quantas portas ocupadas incorretamente (sem sub)?  | **0** |
| Quantas portas com subscriber inválido?            | **2** |
| Quantas portas em conflito (2+ subs)?              | **0** (amostra) |
| Quantas reservas vencidas?                         | **0** |
| Schema canônico está definido?                     | **NÃO** (0 CTOs divergentes) |

## 6. CONCLUSÃO

**TERCEIRA FONTE DETECTADA**: `subscriber_access_points` (5.682 docs, 5.682 com subscriber_id). É outro caminho cliente↔rede ainda não consolidado com `cto_ports`/`subscribers`.

**Integridade CTO/Porta: 🔴 CRÍTICO** (100.0% dos ativos sem porta)

**Gates falhando para Sprint 5:**
- ❌ Integridade Porta < 95% (atual: 0.0%)
- ❌ Subscribers fantasma em portas (2)
