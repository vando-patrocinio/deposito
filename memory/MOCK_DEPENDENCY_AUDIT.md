# MOCK_DEPENDENCY_AUDIT

**Data:** 09-Jun-2026
**Veredito:** ✅ **`ALLOW_MOCK_MODULES=false` é seguro com 1 ressalva.**

---

## 1. O que `ALLOW_MOCK_MODULES` controla

Arquivo: `backend/rbac.py:68-85`.

- Função `_allow_mock()` lê a env var.
- `mock_guard(name)` é uma dependência FastAPI que **bloqueia o endpoint com HTTP 503** quando a flag está `false`.
- Default no código: `"true"` (preview).

## 2. Endpoints REAIS protegidos por `mock_guard` em produção

Grep exaustivo em `backend/routes/**.py`:

| Arquivo | Linha | Endpoint impactado | Comentário |
|---|---|---|---|
| `routes/security_home.py` | 81 | **TODO o router `/api/security`** (POC com 1 site cadastrado, 3 sensores, 6 alarmes) | Bloqueio = SecurityHome some da UI quando flag=false |
| `routes/presidente_ia.py` | 26 | **Apenas import** — não chamado em runtime | Nenhum endpoint bloqueado |

**Total real**: **1 módulo** (`security_home`) é afetado por flag=false.

## 3. Lugares onde a flag é apenas referenciada (sem impacto em prod)

| Arquivo | Tipo |
|---|---|
| `backend/scripts/audit_rbac_coverage.py:31` | Script offline — usa `setdefault` |
| `backend/tests/test_*.py` (10 arquivos) | Testes — usam `setdefault("ALLOW_MOCK_MODULES", "true")` para preservar comportamento dos mocks de teste; não afeta prod |

## 4. Classificação

| Categoria | Itens encontrados | Decisão |
|---|---|---|
| 🟥 **Quebra crítica** | nenhum | — |
| 🟧 **Quebra aceitável** | `security_home` (POC, 1 site, 0 receita demonstrável) | OK desligar — esconder até virar produto |
| 🟦 **Mock legítimo de homologação** | testes pytest (10 arquivos) | Mantém — não vão a produção |
| 🟪 **Mock perigoso de produção** | **nenhum encontrado** | — |

## 5. Auditoria conexa: `observability_twin.mock_mode`

Outro caminho de mock detectado fora da flag:

- `services/observability_twin.py:1397` retorna `"is_mock_mode": (not zbx_conn.is_real and not graf_conn.is_real)` quando Zabbix E Grafana estão **ambos desligados**.
- Esse é **comportamento esperado**: se nenhum dos dois está configurado, o Twin retorna fallback. Não é o mesmo mock da flag global.
- Não afeta esta decisão.

## 6. Decisão recomendada

> 🟩 **FALSE IMEDIATO** — risco zero comercial.

**Sequência operacional**:

1. Alterar `backend/.env` → `ALLOW_MOCK_MODULES=false`
2. `sudo supervisorctl restart backend`
3. Validar:
   - `GET /api/security/sites` → deve retornar **HTTP 503** (esperado, SecurityHome esconde)
   - Todos os outros 322 endpoints continuam respondendo normalmente.
4. Confirmar nenhum erro novo em `/var/log/supervisor/backend.err.log` por 10 min.
5. Marcar SecurityHome como "Roadmap futuro" na UI (ou esconder o item de menu via `access_tags`).

## 7. Reversibilidade

Trivial: alterar para `true` e reiniciar. Nenhum dado é perdido.

## 8. O que esta auditoria provou

- A flag está documentada e tem propósito claro (Sprint 1 Blindagem de Produção, iter220).
- Apenas **1 módulo real** depende dela em prod.
- Esse módulo é uma POC sem volume comercial (security_sites: 1).
- Desligar é seguro e remove o sinal de "produto não-produtivo" para o comprador.

**Não há mock perigoso em produção — pode desligar.**
