# GO LIVE — Baileys WhatsApp Production

**Tempo estimado:** 3 minutos do humano + 30s para confirmar.

## Pré-requisitos no servidor de PROD
- Sidecar Baileys rodando: `curl http://localhost:3002/health` → `{"ok":true,"state":...}`
- Backend FastAPI online
- MongoDB acessível com a empresa `co-demo` (ou o tenant alvo) já cadastrada

## Passo a passo

### 1. Abra o painel admin
```
{REACT_APP_BACKEND_URL}/admin
```
Login com conta `SUPER_ADMIN_EMAILS` (admin@empresa.com).

### 2. Navegue para o módulo WhatsApp
Menu lateral → **Atendimento IA** → **Sessões WhatsApp** (ou rota direta `/admin/whatsapp/qr`).

### 3. Selecione a empresa piloto
Dropdown topo direito → **Empresa Demo** (`co-demo`).

### 4. Clique em "Conectar nova sessão"
Sistema chama `POST /api/whatsapp/baileys/session/start` → o sidecar gera um QR Code.
QR Code aparece em ~3s na tela.

### 5. Escaneie o QR
- Abra WhatsApp Business no celular do gestor (deve ser o número operacional, não pessoal)
- Menu (3 pontos) → "Aparelhos conectados" → "Conectar um aparelho"
- Escaneie o QR mostrado no painel

### 6. Confirme estado=open
Painel deve mudar para verde "Sessão ativa" em ~5s.
No banco:
```bash
mongosh test_database --eval 'db.wa_baileys_sessions.findOne({company_id:"co-demo"})'
```
Deve retornar `status: "open"`.

### 7. Dispare o lote BLINDADO V2
```bash
cd /app/backend
python scripts/dispatch_blindados.py
```
**Resultado esperado:** 83 mensagens enviadas, 81-82 com status=`sent`, 1-2 bounce.

### 8. Monitore em 6h
```bash
# Quantos pagaram após o disparo?
python -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    run = await db.operacao_tese_runs.find_one(sort=[('started_at',-1)])
    print('Run:', run['id'])
    # Faturas pagas DESDE o início da operação
    paid_after = await db.subscriber_invoices.count_documents({
        'status':'paid','paid_date':{'\$gte': run['started_at']}})
    print(f'Faturas pagas pós-disparo: {paid_after}')
asyncio.run(main())
"
```

### 9. Relatório final (72h depois)
```bash
python scripts/run_pilot.py final --op <op_id>
```

## ROLLBACK — se algo der errado

### Pausar disparos
```bash
mongosh test_database --eval '
db.wa_baileys_sessions.updateOne(
  {company_id:"co-demo"},
  {$set:{status:"paused"}})
'
```
`wa_dispatcher.send_text` vai retornar `no_session` imediatamente.

### Encerrar operação
```bash
curl -X POST "$REACT_APP_BACKEND_URL/api/operacao-tese/stop/<op_id>" \
     -H "Authorization: Bearer $TOKEN"
```

## Variáveis no .env que precisam estar setadas

```env
WA_SIDECAR_URL=http://localhost:3002
WA_SIDECAR_TOKEN=<token gerado pelo sidecar>
BAILEYS_SIDECAR_URL=http://localhost:3002    # mesma URL, usado por wa_dispatcher.py
PRESIDENTE_IA_GESTOR_PHONE=+55<DDD><número>  # opcional, recebe alerta de início
```

Sem `BAILEYS_SIDECAR_URL` o dispatcher retorna `BAILEYS_SIDECAR_URL_missing` mesmo
com sessão `open`. Verifique antes de disparar.
