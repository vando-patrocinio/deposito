# Backlog — Junho/2026

> Lista de features confirmadas pelo usuário pra serem implementadas no próximo ciclo.

---

## 🔵 WebPhone SIP/VoIP (integrado tipo FOCUS Chat)
**Confirmado:** 21/05/2026
**Prazo alvo:** mês que vem (Junho/2026)
**Esforço estimado:** 1-2 dias dev

### Stack escolhida
- **Frontend:** `JsSIP` (ou `SIP.js`) — WebRTC nativo, ~80KB gzip
- **Backend:** coleção `sip_credentials` no MongoDB (encriptada em repouso)
- **UI:** drawer lateral fixo (modelo FOCUS Chat, ver print do usuário)

### Compatível com qualquer PABX que tenha WSS:
- Asterisk próprio (`chan_pjsip` + WSS porta 8089)
- FreePBX / Issabel
- Provedores cloud: Total Voice, Voipo, Sippulse, Voxbeam

### O que VAMOS entregar
- [ ] Discador (Ligar / Atender / Desligar / Mute / Hold / Transfer)
- [ ] **Click-to-call** na Lousa (clicar no telefone do cliente disca direto)
- [ ] Histórico em `call_logs` (data, duração, técnico, cliente vinculado, OS vinculada)
- [ ] Status de presença sincronizado (Online / Em chamada / Ocupado)
- [ ] Notificação visual de chamada recebida (toast + ringer HTML5)
- [ ] Credenciais 1-por-usuário (cada técnico/atendente com seu ramal)
- [ ] Endpoint `GET /api/sip/credentials` (retorna só pro user logado)

### Bonus IA (consegue via Emergent LLM Key já configurada)
- [ ] **Gravação** das chamadas → upload pro MongoDB GridFS
- [ ] **Transcrição automática** via OpenAI Whisper
- [ ] **Resumo IA da chamada** (cliente reclamou de quê, técnico prometeu o quê) usando Gemini — texto vai automático pro `completion_data.observacoes` da OS

### O que o USUÁRIO precisa providenciar antes
1. ✅ Servidor SIP com WSS (Asterisk moderno serve)
2. ✅ Credenciais de teste: WSS URL + sip_user + senha + domínio
3. ⚠ (Opcional) Tronco SIP pra ligações externas

### Modelo de cobrança / multi-tenant
- Cada empresa pode ter ramais próprios (campo `company_id` na `sip_credentials`)
- Atendente/Comercial: 1 ramal cada
- Técnicos de campo: opcional (decisão do gestor)

### Como retomar quando o mês chegar
Mensagem mágica para iniciar:
> "Vamos fazer o WebPhone. Meu PABX é [Asterisk/Total Voice/etc], WSS é `wss://...`, usuário `XXX`, senha `YYY`, domínio `ZZZ`."

E em 1 dia tá no ar.

---

## Outras pendências antes do WebPhone (priorizar primeiro)

| # | Item | Prioridade | Status |
|---|------|-----------|--------|
| 1 | Multi-tenancy estrita (remover `DEMO_COMPANY_ID`) | 🔴 P0 | Não iniciado |
| 2 | Meta WhatsApp Cloud API (fallback Baileys) | 🟠 P1 | Não iniciado |
| 3 | Refactor monolíticos (`LousaAdminPanel.js`, `lousa.py`, `EstoquePanel.js`) | 🟠 P1 | Não iniciado |
| 4 | Sprint 0 (Sentry, CONVENTIONS, GH Actions) | 🟠 P1 | Não iniciado |
| 5 | "Aba Movimento layout antigo" (precisa prints do user) | 🟡 P2 | Aguardando user |
| 6 | SmartOLT API key (renovar pool, fora do escopo dev) | 🟡 P2 | Aguardando user |
| 7 | Lousa Mobile — painel OS órfãs no admin | 🟡 P2 | Aguardando decisão |
