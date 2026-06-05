# Fleet Gateway — TCP Listener para rastreadores TK103

Recebe conexões TCP cruas dos rastreadores TK103/TK303 (e similares chineses)
e envia as posições parseadas via HTTPS para o backend SmartProv.

## Por que existe este gateway?

Os rastreadores TK103 só falam **TCP cru** (não HTTPS). O backend SmartProv
roda no Emergent (Kubernetes), que só expõe HTTP/HTTPS no path `/api`.
Por isso precisamos de um pequeno serviço em uma **VPS pública com IP fixo**
para receber os trackers e repassar via HTTPS para o backend.

```
[Tracker TK103]  ──TCP──▶  [Gateway (VPS)]  ──HTTPS──▶  [Backend SmartProv]
```

## Onde rodar?

- Qualquer VPS Linux barata (Hostinger ~R$10/mês, Contabo ~$5/mês, AWS Lightsail)
- Precisa de:
  - IP público fixo
  - 1 porta TCP aberta (escolha qualquer, sugestão `5023`)
  - Python 3.10+
  - Acesso à internet de saída (para chamar o backend via HTTPS)

## Configuração

1. Edite `config.py` ou exporte variáveis:
   ```bash
   export BACKEND_URL=https://seu-backend.com
   export FLEET_INGEST_TOKEN=cole-aqui-o-mesmo-token-do-backend
   export GATEWAY_TCP_PORT=5023
   ```

2. No backend, defina o mesmo token em `/app/backend/.env`:
   ```
   FLEET_INGEST_TOKEN=cole-o-mesmo-token-aqui
   ```

3. Em cada rastreador TK103, programe via SMS:
   ```
   adminip123456 IP_DA_VPS PORTA       # Ex: adminip123456 200.150.1.1 5023
   timer123456 30                        # Reporta a cada 30s
   gprs123456                            # Liga modo GPRS (TCP)
   ```

## Como rodar

```bash
cd /app/fleet_gateway
pip install -r requirements.txt
python tcp_listener.py
```

Ou via Docker (recomendado pra produção):

```bash
docker build -t fleet-gateway .
docker run -d --name fleet-gw -p 5023:5023 \
  -e BACKEND_URL=https://meu-backend.com \
  -e FLEET_INGEST_TOKEN=token-aqui \
  fleet-gateway
```

Ou systemd (recomendado pra VPS bare-metal):

```ini
# /etc/systemd/system/fleet-gateway.service
[Unit]
Description=SmartProv Fleet TCP Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/fleet-gateway
ExecStart=/usr/bin/python3 tcp_listener.py
Environment=BACKEND_URL=https://meu-backend.com
Environment=FLEET_INGEST_TOKEN=token-aqui
Environment=GATEWAY_TCP_PORT=5023
Restart=always

[Install]
WantedBy=multi-user.target
```

Habilite:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fleet-gateway
sudo systemctl status fleet-gateway
```

## Protocolos suportados

- **TK103** (padrão): frames `*HQ,IMEI,V1,…#` (GPRMC-like)
- **TK303**: variante mais nova com bateria/sinal
- **GT06** (Concox): suporte experimental (basta editar `tk103_parser.py`)

Frames recebidos viram POSTs HTTPS em
`POST {BACKEND_URL}/api/fleet-tracking/ingest` com payload JSON.

## Testando localmente

Você pode simular um TK103 enviando um frame:
```bash
echo '*HQ,1234567890,V1,123456,A,2334.1234,S,04612.5678,W,015.0,180,010326,FFFFFBFF#' | nc localhost 5023
```

Deve aparecer no backend a posição em `/api/fleet-tracking/positions/live`
desde que o IMEI `1234567890` esteja cadastrado.

## Comandos remotos

A cada 60s, o gateway puxa comandos pendentes:
```
GET {BACKEND_URL}/api/fleet-tracking/commands/{imei}
```

E envia o comando TK103 correspondente via TCP de volta ao tracker:
- `block` → `RELAY,1#` (bloqueia)
- `unblock` → `RELAY,0#` (libera)
- `locate_now` → `WHERE#` (pede última posição)
- `audio_listen` → `MONITOR#` (algumas variantes)

Após confirmar, faz:
```
POST {BACKEND_URL}/api/fleet-tracking/commands/{cmd_id}/ack
```
