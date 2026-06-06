# SmartProv — Design Guidelines (Manual 2026-06)

**REGRA GLOBAL PERMANENTE.** Toda tela nova, toda alteração e toda mensagem
gerada pela IA deve respeitar este manual. Aplica-se retroativamente ao
sistema inteiro.

---

## 1. Identidade visual

- Plataforma SaaS corporativa madura — não é landing page nem protótipo.
- Sobriedade, elegância, clareza, organização, profissionalismo.
- Visual rico (cheio), mas sem ruído.
- Densidade visual adequada — telas vazias são **proibidas**.

## 2. Paleta institucional (tokens em `/app/frontend/src/index.css`)

| Token CSS                | Valor       | Uso                                    |
| ------------------------ | ----------- | -------------------------------------- |
| `--brand-primary`        | `#4b1d7a`   | Roxo institucional (ação principal)    |
| `--brand-primary-hover`  | `#3b1661`   | Hover do roxo                          |
| `--secondary`            | `#f28c28`   | Laranja institucional (apoio, raro)    |
| `--text-primary`         | `#1f2933`   | Grafite escuro                         |
| `--text-secondary`       | `#5f6b7a`   | Cinza médio                            |
| `--text-muted`           | `#8a94a3`   | Cinza claro                            |
| `--bg-app`               | `#f8fafc`   | Fundo principal (branco frio)          |
| `--bg-surface`           | `#ffffff`   | Superfície de cards/painéis            |
| `--bg-surface-2`         | `#f1f5f9`   | Superfície secundária                  |
| `--border-default`       | `#e2e8f0`   | Borda sutil padrão                     |
| `--success`              | `#237a4b`   | Verde discreto                         |
| `--warning`              | `#9a6700`   | Âmbar discreto                         |
| `--danger`               | `#b42318`   | Vermelho sóbrio                        |

**Uso:** o roxo é usado com moderação — apenas em ações principais,
estado ativo da sidebar, destaques estratégicos. O laranja é apoio raro.

## 3. Tipografia

**Família única**: **Inter** (300/400/500/600/700/800).
Mono: JetBrains Mono (código apenas).

| Hierarquia        | Tamanho             | Peso |
| ----------------- | ------------------- | ---- |
| Título de página  | 28–32px             | 700  |
| Subtítulo página  | 15–16px             | 400/500 |
| Título de seção   | 20–24px             | 650/700 |
| Título de card    | 16–18px             | 600  |
| Texto normal      | 14–15px             | 400  |
| Texto auxiliar    | 12–13px             | 400  |
| Label form        | 13–14px             | 500  |
| Botão             | 14–15px             | 600  |

## 4. Componentes base

Usar SEMPRE os do `/app/frontend/src/ui.js`:
`Card`, `Button`, `Field`, `StatusBadge`, `Metric`, `Icon`, `Row`.

E classes CSS de `index.css`:
`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger`,
`.input`, `.surface`, `.pill`, `.pill--success`, `.stat-card`, `.eyebrow`.

Não criar variantes locais. Não duplicar estilos com pequenas variações.

## 5. PROIBIÇÕES DURAS

1. **Emojis em qualquer lugar do sistema.** Inclui menus, botões, títulos,
   modais, cards, mensagens da IA, toasts, alertas, empty states.
   Exceção única: **Lousa Mobile** (app do técnico em campo) pode usar
   ícones Lucide grandes/coloridos por legibilidade rápida em rua.
2. Misturar fontes (somente Inter).
3. Cores fora dos tokens.
4. Gradientes chamativos.
5. Sombras exageradas.
6. Botões com estilos diferentes sem necessidade.
7. Páginas vazias / "tela em branco".
8. Mensagens informais ("Opa!", "Beleza!", etc.).
9. Lorem Ipsum quando houver contexto real.

## 6. Mensagens automáticas e IA

**Tom**: profissional, objetivo, consultivo. Sem emojis. Sem gírias.

Padrão correto:
> "Cadastro atualizado com sucesso."
> "Cliente incluído na fila de atendimento."
> "Não foi possível concluir a operação. Verifique os dados e tente
> novamente."

Padrão incorreto:
> "🎉 Tudo certo!"
> "Opa, algo deu errado."
> "Beleza, salvamos aqui!"

## 7. Layout padrão de página

Toda página deve ter, quando aplicável:

1. **Cabeçalho** — título + subtítulo + ações à direita.
2. **Resumo** — cards de KPI/indicadores.
3. **Área principal** — tabela, gráfico, formulário ou módulo.
4. **Área complementar** — filtros, histórico, recomendações.

Se faltar dado real, usar **empty state profissional** (não tela vazia).

## 8. Auditoria visual (antes de finalizar qualquer feature)

Checklist obrigatório:

- [ ] Segue identidade global?
- [ ] Usa fonte Inter?
- [ ] Usa tokens CSS (sem hex hardcoded fora do `index.css`)?
- [ ] Botões usam `.btn` + variant?
- [ ] Cards usam `<Card>` ou `.surface`?
- [ ] Estado ativo da sidebar funciona?
- [ ] Cabeçalho da página está presente?
- [ ] Página cheia, sem espaço morto?
- [ ] **Zero emojis** (exceto Lousa Mobile)?
- [ ] Linguagem profissional?
- [ ] Responsivo desktop + tablet + mobile?

## 9. Roadmap de migração visual (fases)

- **FASE 1** — Fundação (concluída 2026-06): tokens institucionais, Inter
  unificado, Tailwind consumindo CSS variables, sidebar sem emoji.
- **FASE 2** — Módulo Fidelidade (concluída 2026-06): 145 emojis removidos
  em 8 componentes; ícones Lucide adicionados nas sub-abas (Crown,
  ArrowLeftRight, Users, TrendingDown, Database, Brain, MapPin, Heart).
- **FASE 3** — Limpeza global (concluída 2026-06): 1853 emojis removidos
  em 194 arquivos `/app/frontend/src/`. Aspas tipográficas (`“”`) aplicadas
  em 82 trechos de JSX text. Exceções aprovadas: `LousaMobile.js` e
  `LousaMobileBoss.js` (app do técnico em campo).
- **FASE 4** — Próximas iterações: ajustes finos por módulo (charts com
  paleta institucional roxo+laranja, refinamento dos modais, labels
  profissionais nas mensagens da IA, AppShell + dashboard headers).
- **FASE 5** — Lousa Mobile (UX específica em campo, ícones Lucide
  grandes/coloridos por legibilidade rápida).

## 10. Esta regra é PERMANENTE

Antes de qualquer nova implementação, consultar este manual.
Em caso de dúvida, manter consistência > criatividade local.
