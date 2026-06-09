# 🛡️ SmartProv — Constituição do Sistema (V1.0)

> **STATUS:** ATIVA — vigora a partir de 2026-06-09.
> **AUTORIDADE:** CTO Vando (autor único). Mudanças requerem assinatura explícita do CTO em commit message com prefixo `[CONSTITUTION-AMEND]`.

---

## Preâmbulo

Esta Constituição é o documento de mais alta hierarquia do sistema SmartProv. Em caso de conflito com qualquer outro documento (PRD, CHANGELOG, ROADMAP, playbooks), **esta Constituição prevalece**.

A Constituição existe por causa do incidente de **2026-06-09**, quando 282 arquivos e ~62.235 linhas de código (incluindo todo o `AI Center · OS` e módulos derivados) foram parar em stash automático do `lint-staged` e desapareceram do working tree, simulando perda de patrimônio. Recuperação foi possível porque o git preservou. **Não vamos depender de sorte novamente.**

---

## Artigo 1 — Princípios Invioláveis

### 1.1 — Patrimônio é sagrado
Todo arquivo, rota, componente, schema, collection, integração ou regra de negócio em produção é **patrimônio do sistema** e não pode ser apagado sem trilha documental.

### 1.2 — Estado é auditável
Cada mudança estrutural deve gerar entrada em `/app/releases/CHANGELOG.md` ou `/app/releases/DECISIONS.md`. Mudanças não documentadas são consideradas **acidentais** e devem ser revertidas.

### 1.3 — Reversibilidade obrigatória
Toda mudança deve ter caminho de rollback explícito. Se não há rollback documentado, a mudança **não pode ser aplicada em produção**.

### 1.4 — UI Freeze enquanto vigorar a Fase 9
Proibido criar novas telas, módulos UI ou agentes de IA sem justificativa de ROI documentada e aprovada pelo CTO. Vigora durante toda a **Fase 9 — Prova de Mercado**.

### 1.5 — `HOMOLOG_MODE=true` é o padrão
O gateway WhatsApp opera sempre em homologação, exceto via whitelist `CAUSALITY_PILOT_PHONES`. Qualquer alteração que desligue `HOMOLOG_MODE` por padrão é **proibida**.

---

## Artigo 2 — Hierarquia Documental

```
1. /app/governance/SYSTEM_CONSTITUTION.md   ← este documento (TOPO)
2. /app/governance/ARCHITECTURE_LOCK.md     ← estrutura travada
3. /app/governance/DATABASE_LOCK.md         ← schema travado
4. /app/governance/RELEASE_LOCK.md          ← processo de release
5. /app/releases/ARCHITECTURE.md            ← arquitetura corrente
6. /app/releases/CHANGELOG.md               ← histórico
7. /app/releases/DECISIONS.md               ← ADRs
8. /app/releases/SMARTPROV_ASSET_INVENTORY.md
9. /app/releases/SMARTPROV_LOST_FEATURE_CHECK.md
10. /app/memory/PRD.md                      ← requisitos
```

---

## Artigo 3 — Direitos do Patrimônio

### 3.1 — Direito à existência rastreável
Nenhum arquivo da pasta `/app/backend/`, `/app/frontend/src/`, `/app/memory/`, `/app/releases/`, `/app/governance/` pode ser deletado sem:
- Entrada em `CHANGELOG.md` com motivo
- Aprovação documentada do CTO
- Verificação de zero referências cruzadas

### 3.2 — Direito ao backup distribuído
O sistema mantém **três níveis de backup**:
1. **Working tree** (estado atual)
2. **Git history + stashes** (atualmente 10 stashes preservados)
3. **GitHub remote** (via botão "Save to Github" — obrigação do CTO após cada milestone)

### 3.3 — Direito à auditoria
Qualquer agente, humano ou IA, deve poder consultar `/app/releases/SMARTPROV_ASSET_INVENTORY.md` para saber o que existe no sistema.

---

## Artigo 4 — Vedações Absolutas

São terminantemente **proibidas** as seguintes ações sem ordem explícita e documentada do CTO:

1. `git reset --hard` em qualquer branch.
2. `git stash drop` em qualquer stash sem antes confirmar conteúdo.
3. Deleção em massa de arquivos (>10 arquivos numa única operação).
4. Sobrescrever `App.js`, `server.py`, ou qualquer arquivo >500 linhas via `create_file` (apenas `search_replace` cirúrgico).
5. Desligar `HOMOLOG_MODE` no `.env` sem autorização escrita.
6. Alterar `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `EMERGENT_LLM_KEY` em hot-path.
7. Criar nova UI durante a Fase 9 sem justificativa de ROI aprovada.
8. Refatorações "preventivas" sem demanda funcional.

---

## Artigo 5 — Processo de Emenda

Esta Constituição **só pode ser alterada** mediante:

1. Issue documentada listando o artigo a ser alterado e o motivo.
2. Aprovação explícita do CTO em commit message `[CONSTITUTION-AMEND]`.
3. Entrada em `/app/releases/DECISIONS.md` no formato ADR.
4. Bump da versão (V1.0 → V1.1 etc) no topo deste documento.

---

## Artigo 6 — Cláusula de Encerramento

Esta Constituição entra em vigor **imediatamente** a partir da sua criação e vigora até ser explicitamente revogada ou emendada pelo CTO.

Em caso de dúvida operacional, o agente IA ou humano deve:
1. Consultar este documento.
2. Se inconclusivo, perguntar ao CTO antes de agir.
3. Nunca presumir autorização tácita.

---

**Assinatura institucional:** CTO Vando — SmartProv
**Data de promulgação:** 2026-06-09
**Versão:** V1.0
