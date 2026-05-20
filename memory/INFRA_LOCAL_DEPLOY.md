# 🏢 SmartProv — Infra Local Profissional (On-Prem)

> Documento técnico para deploy do SmartProv no rack próprio do cliente.
> Calibrado para infra de provedor: 2x 8 Gbps simétrico · IP público · ASN próprio · UPS 24h.
> Capacidade: 200 clientes hoje · escalável até 5.000 sem mudar hardware.

---

## 🎯 Arquitetura de Alta Disponibilidade (HA)

```
                    ┌────────────────────────────────────┐
                    │       INTERNET (BGP/ASN próprio)    │
                    │  Link 1: 8 Gbps  │  Link 2: 8 Gbps  │
                    └─────────────────┬──────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          │  pfSense/MikroTik HA  │ ← failover automático
                          │   Firewall + Routing  │
                          └───────────┬───────────┘
                                      │
                          ┌───────────┴───────────┐
                          │   Switch L3 (10G)     │
                          └─────┬───────────┬─────┘
                                │           │
                ┌───────────────┘           └───────────────┐
                │                                            │
        ┌───────▼───────┐                          ┌───────▼───────┐
        │  Server PRIMARY│                          │ Server REPLICA│
        │  (Ativo)       │   ←── Replicação ───→   │ (Stand-by)    │
        │                │   Mongo Replica Set      │                │
        │ Proxmox VE 8   │   Disco rsync horário    │ Proxmox VE 8  │
        └────────────────┘                          └────────────────┘
                │                                            │
                └────────────────┬───────────────────────────┘
                                 │
                          ┌──────▼──────┐
                          │  Backup NAS │
                          │ Synology 4-bay │
                          │ RAID 6 · 24TB │
                          └─────────────┘
                                 │
                          ┌──────▼──────┐
                          │ Off-site backup│
                          │ Backblaze B2  │
                          │ R$50/mês 2TB  │
                          └─────────────┘
```

---

## 🖥️ Hardware Recomendado (200-1000 clientes)

### Cenário A — HA com 2 servidores (RECOMENDADO)

**Server Primary + Replica** (2 unidades idênticas):

| Componente | Especificação | Preço estimado |
|---|---|---|
| **CPU** | AMD EPYC 7313P (16c/32t · 3.0GHz) OR Intel Xeon Silver 4316 | R$ 8.000 |
| **RAM** | 64 GB DDR4 ECC (4x 16 GB) | R$ 3.500 |
| **Disco SO** | 2x SSD NVMe 1 TB em RAID 1 (Samsung 980 Pro / Kingston KC3000) | R$ 1.800 |
| **Disco Dados** | 4x SSD SATA 2 TB em RAID 10 = 4 TB úteis | R$ 6.000 |
| **Rede** | 2x 10 Gbps SFP+ (placa Mellanox ConnectX-3) | R$ 1.500 |
| **PSU** | Dual 750W 80+ Platinum redundante | R$ 1.500 |
| **Chassis** | Supermicro SC825 (2U rack) ou Dell PowerEdge R650 | R$ 7.000 |
| **Total/server** | | **~R$ 29.000** |
| **Total 2 servers** | | **~R$ 58.000** |

### Cenário B — Single server + backup robusto (CUSTO-BENEFÍCIO)

Se HA não é prioridade ainda (você assume janela de 1h de downtime no pior caso):

| Componente | Especificação | Preço |
|---|---|---|
| **CPU** | AMD Ryzen 9 7950X (16c/32t) | R$ 4.500 |
| **RAM** | 64 GB DDR5 (2x 32 GB) | R$ 2.000 |
| **Disco SO** | 2x SSD NVMe 500 GB RAID 1 | R$ 800 |
| **Disco Dados** | 2x SSD NVMe 2 TB RAID 1 | R$ 3.000 |
| **HDD Backup** | 2x 8 TB Seagate IronWolf RAID 1 (snapshot) | R$ 2.500 |
| **Rede** | 2x 2.5 Gbps onboard | R$ 0 |
| **PSU** | Corsair RM850x 850W 80+ Gold | R$ 1.000 |
| **Chassis** | Fractal Define 7 ou similar (tower) | R$ 1.500 |
| **Total** | | **~R$ 15.300** |

### Infraestrutura compartilhada

| Item | Especificação | Preço |
|---|---|---|
| **Switch L3 10G** | MikroTik CRS354 ou Cisco SG350X | R$ 8.000 |
| **NAS Backup** | Synology DS1522+ 5-bay + 4x 8TB HDD | R$ 12.000 |
| **PDU rack** | APC AP7920 (8 outlets, switched) | R$ 2.500 |
| **KVM IP** | Aten KN1108v (1 console p/ 8 servers) | R$ 5.000 |

**Investimento total HA**: **~R$ 85.000** (servers + infra · 5 anos amortizado: R$ 1.400/mês)
**Investimento total Single**: **~R$ 27.000** (5 anos: R$ 450/mês)

---

## 🐧 Stack de Software

### 1. Sistema Operacional Base
```bash
# Proxmox VE 8.2 (Debian 12 baseado · KVM + LXC)
# - Snapshots ZFS nativos
# - Backup integrado pro NAS
# - Web UI pra gestão remota
# - Replicação entre nodes nativa
```

### 2. Virtualização & Containerização

**Decisão recomendada**: **Proxmox VE + LXC containers** (não Docker direto)

Razões:
- ✅ Snapshots instantâneos antes de qualquer deploy
- ✅ Live migration entre nodes (HA real)
- ✅ ZFS pool com compressão LZ4 (economiza ~30% disco)
- ✅ Web UI poderoso (você não precisa lembrar comandos)

```
LXC Containers planejados:
├── lxc-backend       → FastAPI (4 vCPU · 8 GB RAM)
├── lxc-frontend      → Nginx + build React (1 vCPU · 1 GB)
├── lxc-mongo         → MongoDB 7.0 (4 vCPU · 16 GB RAM · ZFS)
├── lxc-whatsapp      → Baileys sidecar (2 vCPU · 2 GB · isolado)
├── lxc-caddy         → Reverse proxy + SSL (1 vCPU · 512 MB)
├── lxc-uptime-kuma   → Monitoring local (1 vCPU · 512 MB)
└── lxc-grafana-loki  → Logs centralizados (2 vCPU · 4 GB)
```

### 3. Reverse Proxy & TLS
**Caddy 2.7+** (substitui nginx · SSL automático Let's Encrypt)

```caddy
ligo.site {
    reverse_proxy lxc-frontend:80
}
api.ligo.site {
    reverse_proxy lxc-backend:8001
}
wa.ligo.site {
    reverse_proxy lxc-whatsapp:3001
    header /webhook {
        # rate limit Meta webhooks
        X-RateLimit-Limit "100"
    }
}
admin.ligo.site {
    # acesso admin apenas pela rede interna
    @internal client_ip 192.168.0.0/16
    handle @internal {
        reverse_proxy lxc-uptime-kuma:3001
    }
    respond "Forbidden" 403
}
```

### 4. Banco de Dados

**MongoDB 7.0 com Replica Set** (3 membros se HA, 1 se single):

```yaml
# /etc/mongod.conf
storage:
  dbPath: /mnt/zfs-data/mongodb
  wiredTiger:
    engineConfig:
      cacheSizeGB: 8       # 50% da RAM disponível pro container
replication:
  replSetName: smartprov-rs
security:
  authorization: enabled
  keyFile: /etc/mongo-keyfile
```

**Backup strategy**:
- **Snapshot ZFS** a cada 1h (zero downtime)
- **mongodump** diário pro NAS
- **rsync incremental** semanal pro Backblaze B2 (off-site)

### 5. Monitoring (sem custo extra)

```yaml
Stack:
  - Uptime Kuma         → /status.ligo.site (status público + alertas)
  - Grafana + Loki      → logs centralizados
  - Prometheus + Node Exporter → métricas hardware
  - Telegram bot        → alerta crítico em 30s
```

**Alertas críticos** (configuração entregue):
- Servidor down > 30s
- WhatsApp sidecar offline > 2min
- CPU > 80% por 5min
- RAM > 90% por 5min
- Disco > 85%
- Falha de RAID
- Backup falhou (sem snapshot nas últimas 6h)
- Mongo replica lag > 30s

### 6. Backup automatizado

```bash
# Cron: 6 níveis de backup
0 */1 * * *   zfs snapshot pool/data@hourly-$(date +%H)         # 1h snapshot ZFS
0 2 * * *     mongodump --uri="..." --out=/mnt/nas/$(date +%F)  # backup NAS
0 3 * * 0     rsync /mnt/nas/ b2://smartprov-backup/            # semanal off-site
0 4 1 * *     /opt/scripts/test-restore.sh                       # teste restore mensal
```

---

## 🌐 Conectividade & DNS

### Configuração de DNS (Registro.br ou Cloudflare DNS)

```
ligo.site                A     200.x.x.x       (seu IP público fixo)
www.ligo.site            CNAME ligo.site
api.ligo.site            A     200.x.x.x
wa.ligo.site             A     200.x.x.x
admin.ligo.site          A     200.x.x.x       (restrito por IP)
status.ligo.site         A     200.x.x.x
```

### BGP Multihoming (você tem ASN!)

Você tem 2 links de 8 Gbps. Como tem ASN próprio:

```
- Anunciar prefixo BGP via AS-Path para os 2 upstreams
- Failover automático em ~30s se 1 link cair
- LACP NÃO precisa (BGP cuida)
- Configurar no pfSense/MikroTik:
  ip route bgp-advertise prefix=200.x.x.0/24
```

Isso te dá **uptime de internet superior a 99.99%** porque os 2 ISPs upstream cobrem 1 ao outro automaticamente.

### Firewall (pfSense ou MikroTik)

```
Regras essenciais:
✅ INBOUND:
   - 80/443 → Caddy (público)
   - 22 → SSH (apenas IP da sua casa + VPN)
   - Wireguard VPN → acesso admin

❌ BLOCK:
   - 27017 (Mongo) — só interna
   - 8001 (Backend) — só atrás do Caddy
   - 3001 (WhatsApp) — só atrás do Caddy
   - 5432, 3306, etc

🛡️ Mitigation:
   - Fail2Ban no SSH
   - CloudFlare proxy DNS (anti-DDoS gratuito até 100GB/mês)
   - Rate limit no Caddy: 100 req/min por IP
```

---

## 📦 Procedimento de migração (Cloud → On-Prem)

### Fase 1 — Setup paralelo (1 dia)
1. Instalar Proxmox no Server Primary
2. Criar ZFS pool: `zpool create data raidz2 sda sdb sdc sdd`
3. Provisionar LXCs vazias com IPs internos
4. Configurar Caddy com domínios `*-staging.ligo.site`
5. Subir cópia do código via `git clone`
6. Testar tudo isoladamente

### Fase 2 — Migração de dados (4-6h, janela de manutenção)
1. **Banner em produção**: "Sistema em manutenção das 02h às 06h"
2. **Snapshot final** do Atlas/Mongo atual (mongodump)
3. **Transferir** dump para NAS local
4. **Restore** no Mongo on-prem (`mongorestore`)
5. **Validar contagem de docs** por coleção (script automático)
6. **Apontar DNS** para o IP local
7. **Aguardar propagação** (TTL 5min)
8. **Smoke tests**: login, create bill, send WA test
9. **Remover banner** + comunicar conclusão

### Fase 3 — Cutover do WhatsApp (1h)
1. Subir sidecar LXC `lxc-whatsapp`
2. Escanear QR code da sessão Isabella
3. Validar mensagem de teste
4. **Manter o sidecar Railway/Render como standby** por 7 dias (rollback fácil)

### Fase 4 — Pós-migração (1 semana)
- Monitorar Sentry/Grafana diariamente
- Testar restore de backup
- Documentar runbooks
- Treinar você (ou equipe) em comandos Proxmox básicos

---

## 💰 TCO comparativo 5 anos

| Cenário | Investimento inicial | Custo mensal | TCO 5 anos |
|---|---|---|---|
| **Cloud completa atual** (Railway+Atlas+Vercel+Bb2) | R$ 0 | R$ 300 | R$ 18.000 |
| **VPS gerenciado** (Hetzner CX42) | R$ 0 | R$ 80 | R$ 4.800 |
| **On-prem Single Server** (Cenário B) | R$ 15.300 | R$ 50 (luz+B2) | R$ 18.300 |
| **On-prem HA** (Cenário A) | R$ 85.000 | R$ 80 (luz+B2) | R$ 89.800 |

**Insight**: financeiramente, on-prem só ganha em 7-10 anos. Mas você ganha em **soberania de dados**, **performance local**, **independência** e **possibilidade de virar SaaS de revenda**.

---

## 🚀 Vantagem competitiva — virar SaaS de revenda

Com essa infra + ASN, você tem condição de:

```
1. Hospedar SmartProv pra 10-50 outros ISPs regionais menores que o seu
2. Cobrar R$ 500-2000/mês por cliente (multi-tenant real)
3. Diferencial: "infra brasileira em provedor brasileiro com ASN"
4. Vender com argumentos de LGPD, latência, soberania
5. Receita potencial: 20 clientes × R$ 1.000 = R$ 20k/mês recorrente
```

**Pré-requisito**: completar Sprint 1 do `TECHNICAL_ROADMAP.md` (multi-tenancy real).

---

## 📋 Checklist de execução

### Fase preparação (1 semana antes de comprar hardware)
- [ ] Confirmar Mongo Atlas tem backup atualizado < 24h
- [ ] Documentar todos os .env atuais (cloud)
- [ ] Listar todos os domínios DNS atuais
- [ ] Comprar Backblaze B2 (~R$50/mês) e fazer 1º teste de upload
- [ ] Definir IP fixo do rack (já tem) e validar rota BGP

### Compra & instalação (2 semanas)
- [ ] Encomendar hardware (lead time 7-14 dias)
- [ ] Provisionar rack (energia, refrigeração, cabeamento)
- [ ] Instalar Proxmox no Primary
- [ ] Configurar BGP nos upstreams
- [ ] Configurar Caddy + Let's Encrypt

### Migração (1 noite)
- [ ] Banner manutenção 02-06h
- [ ] mongodump + transfer + restore
- [ ] Apontar DNS
- [ ] Smoke tests
- [ ] WhatsApp QR scan
- [ ] Comunicar conclusão

### Pós-migração (1 mês)
- [ ] Monitorar Sentry/Grafana diariamente
- [ ] Testar restore semanalmente
- [ ] Treinar você (ou equipe) em Proxmox
- [ ] Considerar Sprint 1+ do TECHNICAL_ROADMAP.md (multi-tenant pra revenda)

---

## ⚠️ Riscos a mitigar

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Pico de raio frita placa | Média | Aterramento + DPS rack + seguro hardware |
| Disco SSD falha (3-5 anos uso) | Alta | RAID 10 + snapshots ZFS + monitoring SMART |
| Você fica doente/viaja sem internet | Média | KVM IP + VPN + script auto-recovery + 2 pessoas treinadas |
| MongoDB corrupta | Baixa | Backup horário + teste mensal de restore |
| DDoS gigantesco | Média | Cloudflare proxy (anti-DDoS grátis até 100GB) |
| Falha de cooling | Baixa | Sensor temperatura + alerta + ventilação redundante |
| Fonte queima | Média | PSU dual-redundante no Cenário A |
| Sysadmin amador → root mistake | **Alta** | **Snapshots ZFS antes de qualquer comando crítico** |

---

## 🎓 Curva de aprendizado (se você for o sysadmin)

| Tópico | Tempo p/ dominar | Material |
|---|---|---|
| Proxmox VE básico | 1 semana | Docs oficiais + YouTube |
| Linux server (Ubuntu/Debian) | 2 semanas | LinuxFoundation free course |
| MongoDB admin | 1 semana | MongoDB University (free) |
| ZFS storage | 3 dias | iXsystems documentation |
| BGP routing (se ainda não sabe) | 2 semanas | Você já tem ASN, então provavelmente já |
| Backup & DR | 1 semana | Restic + Backblaze docs |
| Monitoring (Grafana/Loki) | 1 semana | Grafana Labs tutorials |

**Total estimado**: **2 meses part-time** pra ficar autônomo. Antes disso, eu (ou consultor) acompanha.

---

## 📞 Próximos passos sugeridos

1. **Decidir entre Cenário A (HA) ou B (single + backup robusto)**
2. **Aprovar este documento** ou pedir ajustes
3. **Iniciar Sprint 0 do TECHNICAL_ROADMAP.md** EM PARALELO (Sentry, CI, conventions)
4. **Solicitar cotação de hardware** com fornecedores (Server Dell, HP, Supermicro)
5. **Agendar janela de migração** (recomendado: sábado madrugada)
