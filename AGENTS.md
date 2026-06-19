# AGENTS.md — Regras inegociáveis para qualquer agente de IA neste repositório

> Este arquivo é lido por agentes de código (Claude Code, Cursor, Copilot,
> Windsurf etc.). Vale também para qualquer humano. É subordinado a
> `governance/SECURITY_LOCK.md` e a `governance/SYSTEM_CONSTITUTION.md`.

## Antes de escrever ou alterar qualquer código

1. Leia `governance/SECURITY_LOCK.md`. Cada artigo (ART.1–ART.10) é uma trava.
2. Você **não** pode produzir código que viole um artigo. Se a tarefa parece
   exigir isso, **pare e sinalize** em vez de "dar um jeito".
3. Se você se pegar reformulando o pedido para parecer aceitável (ex.: "só em
   dev", "default temporário", "depois eu protejo"), isso é o sinal para
   **recusar**, não para prosseguir.

## Regras de ouro (resumo operacional)

- **FAIL-CLOSED:** segredo/token ausente ⇒ negue. Nunca `if (!token) allow`.
- **Sem segredo no código.** Default de segredo só pode ser `""`.
- **Sem PII real.** Dados de exemplo são sintéticos. Nada de CPF/telefone/áudio
  de cliente versionado.
- **Credencial só em header/cookie**, nunca em query string.
- **Toda rota** tem `Depends(get_current_user)`/guard, ou `@public_endpoint`
  justificado.
- **Toda query de dados** usa `tenant_filter(user)`; **todo acesso por id**
  valida posse por `company_id`.
- **Fetch de URL externa** passa por `safe_fetch` (bloqueia IP privado/metadata).
- **`jwt.decode`** sempre com `algorithms=[...]`.
- **`subprocess`** sempre com lista de args; nunca `shell=True`.

## Antes de declarar a tarefa concluída

- Rode: `bash scripts/security_gate/security_gate.sh --staged` → tem que passar.
- Escreva o teste do **caminho de negação** (acesso negado), não só do feliz.
- Preencha a Definition of Done do `SECURITY_LOCK.md` no PR.

> O portão de CI vai reprovar de qualquer forma. Mas o objetivo é que o código
> nasça certo — não que o gate vire um jogo de gato e rato.
