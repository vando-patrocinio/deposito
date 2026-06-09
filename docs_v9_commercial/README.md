# SmartProv — Pacote Comercial V9.4 (DRAFT)

> **STATUS:** DRAFT — V9.4 (Fase de Prova de Mercado)
> **USO:** Material mínimo para apresentação a 1 provedor piloto pagante.
> **PROIBIDO** uso público externo sem revisão jurídica e aprovação do CTO.

## Índice

| # | Arquivo | Finalidade Comercial | Status |
|---|---------|----------------------|--------|
| 1 | `01_landing.html` | Landing institucional técnica (one-pager). Apresentação para gestores de NOC/Operações. Foco em ROI mensurável, Smart Field Ops, Action→Cash, Observability e AI Center. | DRAFT |
| 2 | `02_sla.md` | Acordo de Nível de Serviço base. Define disponibilidade, janelas de manutenção, severidades e tempo de resposta para o piloto controlado. | DRAFT |
| 3 | `03_lgpd.md` | Termo de Tratamento de Dados Pessoais (Operador/Controlador). Compatível com LGPD Lei 13.709/2018. **Sujeito à revisão jurídica.** | DRAFT |
| 4 | `04_contrato_saas.md` | Contrato base de Licenciamento de Software como Serviço para o piloto. Inclui cláusulas comerciais, propriedade intelectual, confidencialidade e rescisão. **Sujeito à revisão jurídica.** | DRAFT |
| 5 | `05_case_study_template.md` | Template oficial de Case Study para preenchimento durante e após o piloto de 30 dias. Inclui seções de adoção, lift medido, conformidade LGPD e próximos passos. | DRAFT |
| 6 | `OBSERVABILITY_REAL_SETUP.md` | Runbook operacional para ligar `ZABBIX_URL/TOKEN` + `GRAFANA_URL/TOKEN` em produção. Backend já suporta troca automática mock↔real via env. | DRAFT |

## Regras de uso (CTO Compliance)

1. Nenhum dos documentos afirma "IA gera receita comprovadamente". Todos usam terminologia controlada:
   - "ROI mensurável"
   - "receita atribuída"
   - "piloto controlado"
   - "medição de lift"
2. Nenhum endpoint, IA, dashboard ou tela nova foi criada. **UI Freeze ativo.**
3. Documentos são estáticos em `/app/docs_v9_commercial/`.
4. `03_lgpd.md` e `04_contrato_saas.md` contêm aviso explícito: **"sujeito à revisão jurídica"**.
5. Landing técnica é institucional, não promessa.

## Fluxo de uso comercial recomendado

```
Prospect (provedor regional)
   ├── 1º contato → 01_landing.html (apresentação institucional)
   ├── Reunião técnica → demo do ambiente em HOMOLOG_MODE
   ├── Proposta → 02_sla.md (níveis e janelas)
   ├── Compliance → 03_lgpd.md (revisão jurídica do cliente)
   └── Fechamento → 04_contrato_saas.md (após ajustes legais)
```

## Próximas ações (fora do escopo desta V9.4)

- Revisão jurídica externa do `03_lgpd.md` e `04_contrato_saas.md` antes de assinar com qualquer provedor.
- ✅ **V9 P3 (whitelist `CAUSALITY_PILOT_PHONES`):** ARMADO no `backend/services/homologation.py`. Quando o CTO popular a env, números autorizados recebem envio real sem prefixo/máscara, mantendo `HOMOLOG_MODE=true`. Cobertura: 6/6 testes em `test_v9_p3_whitelist.py`.
- ✅ **V9 P1 (Observability Real):** ARMADO em `backend/services/observability_twin.py`. Quando o CTO popular `ZABBIX_URL/TOKEN` + `GRAFANA_URL/SERVICE_ACCOUNT_TOKEN` no `.env` e reiniciar o backend, conectores trocam automaticamente de mock para real. Runbook em `OBSERVABILITY_REAL_SETUP.md`.
- Preencher `05_case_study_template.md` durante/após o piloto de 30 dias.

---
_Documento gerado pela esteira V9.4 — Prova de Mercado. Versão DRAFT v1.0._
