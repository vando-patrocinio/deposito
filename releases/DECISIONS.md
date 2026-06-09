# SmartProv — DECISIONS (ADRs)

> Architectural Decision Records. Subordinado a `SYSTEM_CONSTITUTION.md`.
> Cada decisão arquitetural relevante deve ter um ADR aqui.

Formato: cada ADR tem ID sequencial, status (PROPOSTO / ACEITO / SUPERSEDED), data e seções **Contexto / Decisão / Consequências**.

---

## ADR-0001 — Adotar `HOMOLOG_MODE=true` como padrão failsafe

**Status:** ACEITO
**Data:** 2026-06-06
**Versão:** V8.3.1

### Contexto
O sistema dispara mensagens WhatsApp para clientes reais via sidecar Baileys. Sem proteção, qualquer bug ou teste mal-feito pode enviar mensagens em massa indevidas a base real, violando LGPD e gerando dano reputacional.

### Decisão
- Variável `HOMOLOG_MODE` no `.env` com default `"true"`.
- Quando ativa: toda mensagem é mascarada, prefixada com `[HOMOLOGAÇÃO SMARTPROV]` e roteada para `TEST_PHONE = 5521998176526`.
- Gateway único `services.homologation.safe_send_whatsapp()` — sem caminho paralelo permitido.

### Consequências
- ✅ Zero mensagens vazadas em produção durante desenvolvimento.
- ✅ Auditoria completa via evento `HOMOLOGATION_BLOCKED_REAL_PHONE`.
- ⚠️ Para piloto real exige liberação cirúrgica (ver ADR-0005).

---

## ADR-0002 — Multi-tenancy obrigatória via `company_id`

**Status:** ACEITO
**Data:** 2026-06-01

### Contexto
SmartProv opera múltiplos provedores no mesmo banco. Vazamento de dados entre tenants é incidente P0.

### Decisão
- Todo documento Tier 1/2/3 carrega `company_id` (obrigatório).
- Toda query DEVE incluir `company_id` no filtro.
- Tests `test_multi_tenant_isolation` em cada módulo crítico.

### Consequências
- ✅ Isolamento garantido por convenção + testes.
- ⚠️ Custo: 1 índice extra por collection.

---

## ADR-0003 — Patrimônio rastreável via Stash Safety Net

**Status:** ACEITO
**Data:** 2026-06-09 (pós-incidente)

### Contexto
Em 2026-06-09 o hook `lint-staged` fez stash automático de 282 arquivos / +62.235 linhas (incluindo todo o AI Center · OS). Trabalho desapareceu silenciosamente do working tree. Recuperação foi possível porque o git preserva stashes indefinidamente.

### Decisão
- Manter os 10 stashes `lint-staged automatic backup` intactos (não dropar sem confirmação).
- Antes de qualquer `git stash drop`, executar `git stash show --stat` e validar conteúdo.
- Adicionar verificação periódica: `git stash list | wc -l ≥ 1` (alerta se cair a zero sem justificativa).
- Documentar todos os stashes em `SMARTPROV_ASSET_INVENTORY.md`.

### Consequências
- ✅ Trabalho recuperável mesmo após perda no working tree.
- ⚠️ Disco extra consumido por stashes não-utilizados (~50MB negligenciável).
- 🔵 Plano futuro: desabilitar `lint-staged` ou movê-lo para `post-commit` hook (não pre-commit).

---

## ADR-0004 — Gateway único de WhatsApp

**Status:** ACEITO
**Data:** 2026-06-06

### Contexto
Múltiplos integradores de WhatsApp historicamente (Baileys, Twilio, Meta Business API). Sem gateway, é fácil bypassar segurança.

### Decisão
- TODA saída de WhatsApp passa por `services.homologation.safe_send_whatsapp()`.
- Sidecar Baileys :3002 é o único transporte ativo em homolog.
- Twilio fica como backup mas com mesma camada de homologação.

### Consequências
- ✅ Auditoria centralizada (`wa_outbox`, `wa_messages_sent`).
- ✅ Compliance LGPD por construção.
- ⚠️ Performance: 1 hop extra (negligenciável).

---

## ADR-0005 — Whitelist `CAUSALITY_PILOT_PHONES` para piloto real

**Status:** ACEITO
**Data:** 2026-06-09 (V9.4)

### Contexto
Para validar causalidade da IA em mercado real, alguns números autorizados precisam receber mensagens REAIS (sem prefixo de homologação, sem máscara). Mas desligar `HOMOLOG_MODE` globalmente seria irresponsável.

### Decisão
- Variável `CAUSALITY_PILOT_PHONES` (CSV de números).
- Quando número está na whitelist: envio real, `environment="causality_pilot"`, evento `CAUSALITY_PILOT_REAL_SEND`.
- `HOMOLOG_MODE` permanece `true` invariante.
- Demais números continuam mascarados.

### Consequências
- ✅ Piloto causal possível sem expor base completa.
- ✅ Métricas isoladas (`causality_pilot` ≠ `production`).
- ⚠️ Requer consentimento LGPD documentado por número.

---

## ADR-0006 — Conector Observability Twin com fallback mock↔real

**Status:** ACEITO
**Data:** 2026-06-05

### Contexto
Zabbix/Grafana requerem credenciais do CONTRATANTE. Aguardar credenciais para desenvolver atrasa entrega.

### Decisão
- `ZabbixConnector.is_real` = bool baseado em env vars presentes.
- Quando `is_real=False`: retorna fixtures determinísticas (modo MOCK).
- Endpoint `GET /api/ai-center/observability/connectors/status` expõe estado.

### Consequências
- ✅ Desenvolvimento sem credenciais.
- ✅ Ativação automática quando env é populada.
- ⚠️ Tests usam mock sempre (testes E2E reais ficam para piloto).

---

## ADR-0007 — Governança documental como blindagem patrimonial

**Status:** ACEITO
**Data:** 2026-06-09

### Contexto
Após o incidente do stash, o CTO solicitou blindagem definitiva: nenhum trabalho pode mais sumir silenciosamente.

### Decisão
- Criar `/app/governance/` com 4 documentos lock (Constitution, Architecture, Database, Release).
- Criar `/app/releases/` com 5 documentos de tracking (Changelog, Decisions, Architecture, Inventory, LostFeatureCheck).
- Adotar Constitution como documento de mais alta hierarquia.
- Toda mudança estrutural agora exige entrada documental.

### Consequências
- ✅ Patrimônio rastreável (cada arquivo crítico documentado).
- ✅ Onboarding de novo agente IA dramaticamente mais rápido.
- ⚠️ Custo: disciplina de manter documentos atualizados.
- 🔵 Futuro: pre-commit hooks que ENFORCE existência de entrada em CHANGELOG para mudanças estruturais.

---

## Template para próximos ADRs

```markdown
## ADR-XXXX — Título curto

**Status:** PROPOSTO / ACEITO / SUPERSEDED
**Data:** YYYY-MM-DD
**Versão:** vX.Y (se aplicável)

### Contexto
(O quê / por quê a decisão precisa ser tomada)

### Decisão
(O quê foi decidido)

### Consequências
- ✅ Positivas
- ⚠️ Negativas / tradeoffs
- 🔵 Próximos passos
```
