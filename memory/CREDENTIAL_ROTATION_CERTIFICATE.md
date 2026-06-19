# 🔑 CREDENTIAL_ROTATION_CERTIFICATE.md

**Operação:** 98 — Trilha Credenciais  
**Data de emissão:** 19/02/2026  
**Modo:** READ → ANALYZE → REPORT (sem alteração)  
**Auditor:** E1 Security Engineer  
**Status:** ✅ PLANO EMITIDO — aguarda execução manual coordenada

---

## 1. Sumário Executivo

Foram localizadas **4 credenciais fracas remanescentes** no `.env` de produção
(`/app/backend/.env`). Nenhuma alteração foi feita — o relatório apresenta o
**plano de rotação** que deve ser executado pelo time de Ops com janela de
manutenção combinada para não invalidar sessões ativas.

### Sistemas avaliados
- `/app/backend/.env` (15 variáveis classificadas)
- `db.users` (16 usuários ativos, 9 com login efetivo)
- `db.subscribers` (26.863 — fora de escopo: usuários portal cliente)
- `JWT_SECRET` — ✅ já forte (96 chars random, rotacionado em 19/02/2026 — Audit V2)

---

## 2. Credenciais fracas encontradas

| Severidade | Chave | Estado atual | Problema | Ação |
|------------|-------|--------------|----------|------|
| 🔴 **P0** | `ADMIN_PASSWORD` | 6 chars, trivial (`123456`) | senha de dicionário, low entropy | Rotar para 24 chars random |
| 🔴 **P0** | `AUDITOR_PASSWORD` | 6 chars, trivial (`123456`) | senha de dicionário, low entropy | Rotar para 24 chars random |
| 🟠 **P1** | `OWNER_PASSWORD` | 9 chars (`Vs5***@@`) | 9 chars (abaixo de 12 NIST) | Rotar para 24 chars random |
| 🟡 **P2** | `GRAFANA_PASSWORD` | 10 chars (`123***ar`) | abaixo de 12 chars | Rotar para 24 chars |

**Falsos positivos descartados:** `COOKIE_SECURE`, `COOKIE_SAMESITE`, `ALLOW_MOCK_MODULES`,
`GRAFANA_ORG_ID` (são flags `true/false/0/1/Lax`, não senhas).

### Credenciais OK
- ✅ `JWT_SECRET` — 96 chars random hex (rotação completa em 19/02/2026)
- ✅ `REDE_IA_QR_SECRET` — 48 chars random
- ✅ `SIDECAR_TOKEN` — 64 chars random
- ✅ `MONGO_URL` — sem credenciais expostas (local)

---

## 3. Estado das senhas em `db.users`

- **Total:** 16 usuários administrativos
- **Já logaram ao menos uma vez:** 9
- **Com `must_change_password=true` ativo:** 0
- **Sem `last_password_change_at` (legado):** 16 (todos — nunca foi setado)

**Implicação:** todos os 16 usuários estão tecnicamente "stale ≥ 90 dias" pois
nunca tiveram registro de troca. Como o sistema NÃO força rotação periódica,
isso é aceitável — mas em Vault/política corporativa seria flag amarela.

---

## 4. Plano de Rotação Recomendado

### Fase 1 — Senhas P0 (executar em janela de manutenção)
1. Gerar valores novos com `python3 -c "import secrets; print(secrets.token_urlsafe(20))"` (24 chars URL-safe).
2. Atualizar 3 variáveis no `.env`:
   - `ADMIN_PASSWORD`
   - `AUDITOR_PASSWORD`
   - `OWNER_PASSWORD`
3. `sudo supervisorctl restart backend`
4. Re-seedar usuário admin/auditor/owner com novo hash:
   ```bash
   curl -X POST .../api/auth/_seed/refresh   # se disponível
   # ou restart suficiente — depende do flow de seed
   ```
5. Comunicar nova senha aos 3 detentores via canal cifrado (1Password/Bitwarden).

### Fase 2 — Senhas P1/P2
6. Rotar `GRAFANA_PASSWORD` (mesma técnica). Atualizar painel Grafana via UI.

### Fase 3 — Pós-rotação
7. Validar via curl: `POST /api/auth/login` com nova senha.
8. Invalidar todas as sessões anteriores via `db.session_denylist` ou aguardando expiração natural (JWT já tem TTL).

### Cronograma sugerido
- **Janela 1 (manhã 06:00–07:00):** Fase 1 + 2 + 3 — não impacta operação ativa
- **Validação:** smoke test login admin/auditor/owner
- **Comunicação:** Slack #ops após validação

---

## 5. Riscos sem rotação

| Risco | Probabilidade | Impacto |
|-------|---------------|---------|
| Exfiltração via `.env` exposto (backup, log, dump) | Média (já mitigado por SECURITY_LOCK ART.1) | **Total bypass admin** |
| Brute force online | Mitigado por rate limit | Médio (rate limit 5/min) |
| Insider threat (dev com acesso ao `.env`) | Alta | **Total bypass admin** |

---

## 6. Certificado de Conclusão

```
+--------------------------------------------------+
|                                                  |
|  CREDENTIAL ROTATION CERTIFICATE                 |
|  Operação 98 — Trilha Credenciais                |
|                                                  |
|  CREDENCIAIS FRACAS LOCALIZADAS:    4            |
|  PLANO DE ROTAÇÃO EMITIDO:          ✅           |
|  AÇÃO PENDENTE:                     EXECUÇÃO     |
|                                                  |
|  P0 (crítico):  2 senhas (admin/auditor)         |
|  P1 (alto):     1 senha  (owner)                 |
|  P2 (médio):    1 senha  (grafana)               |
|                                                  |
|  STATUS:        AGUARDANDO JANELA DE MANUTENÇÃO  |
|                                                  |
+--------------------------------------------------+
```

**Modo:** READ-ONLY. Nenhuma senha foi alterada nesta operação.
A execução do plano exige coordenação com Ops (downtime ~5 minutos).

---

**Assinado:** E1 Security Engineer  
**Aprovação:** CEO — Ordem Executiva Operação 98 (19/02/2026)
