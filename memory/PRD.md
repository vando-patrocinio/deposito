# PRD — SmartProv / Ligo Suite

## Problem Statement
Enterprise 2026 ISP Billing & Network Suite ("SmartProv" / Ligo) to replace Atlaz.
Modules: Native Billing, NFCom, PPPoE/RADIUS, SmartOLT TR-069, Fleet Management,
Referral Program ("Indique e Ganhe"), Multi-tenant WiFi Hotspot, SecurityHome
(Verisure-style), Loyalty/Partnership ("Parcerias") marketplace.

User language: **Português (PT-BR)** — always respond in Portuguese.

## Architecture
- React frontend + FastAPI backend + MongoDB
- Multi-tenant
- Magic-link auth for Partner PWA; CPF login for `/cliente` portal
- WhatsApp via Baileys sidecars
- Image generation via Nano Banana (Emergent LLM Key)

## Modules Status
- ✅ Network Mapping (auto-register CTO)
- ✅ Fleet Tracking (3-step Wizard, offline sync, geofences, merged location logs)
- ✅ Parcerias/Promoções: Partner PWA (magic links + QR scanner), Client viewer, Landing Page `/seja-parceiro`
- ✅ Premium `/cliente` portal (CPF, animated gradients)
- ✅ Multi-tenant WiFi Hotspot
- 🟡 SecurityHome MVP (Contact ID parser + Asaas pending)
- 🔴 NFCom Integration (not started)
- 🔴 WhatsApp Channel 1 502 error (P0 blocker for retargeting)

## Recent Changes (2026-02 fork)
- **Iter 236 (2026-02-05)**: Partner Portal login redesign — full-bleed photoreal image of happy entrepreneurs (`/partner-login-bg.png`, generated via Nano Banana), glass/translucent card moved to bottom-right corner. File: `frontend/src/parceria/PartnerPortalApp.js`.

## Backlog
### P0
- WhatsApp Channel 1 QR 502 error (sidecar port 3002)
- Finalize Landing Page `/seja-parceiro` polish (rotated card + logo size — pending verification)

### P1
- Admin panel to approve Parceria leads → convert to partners with magic links
- SecurityHome: Contact ID parser + Asaas integration
- NFCom integration
- Billing readjustment pre-notice cron
- Dunning real (WhatsApp/SMS)
- Unblock-request admin panel
- Asaas Payment Gateway (awaiting user API key)
- Fleet GPS chip M2M billing (blocked: user has no operator yet)
- Auto-import Accounts Payable from bank/boletos (blocked: source TBD)
- Grafana + OLT SNMP monitoring (awaiting token)

### P2
- Extract WhatsApp group contacts via Baileys
- Monitor client IP on CTO via ping/SNMP

## Known Issues
- Missing filial data in manual Sicoob imports
- User often tests in production (`ligo.system`) instead of preview — must use "Save to GitHub → Deploy"
- `whatsapp_baileys.py` >5100 lines — refactor candidate

## Test Credentials
See `/app/memory/test_credentials.md`
