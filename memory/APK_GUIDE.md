# 📱 APK do App do Colaborador — Ligo

## ✅ O que já está pronto (você não precisa fazer nada disso)
- PWA do app Ligo Colaborador validado (manifest, service worker, ícones 192/512, shortcuts)
- `/manifest.json` atualizado pra "Ligo Colaborador" / package `system.ligo.colaborador`
- `/.well-known/assetlinks.json` preparado (com placeholder de SHA-256 — preenchido depois)

---

## 🚀 Passo-a-passo (gerar APK em ~5 min)

### 1. Garantir que o preview foi REPUBLICADO pra produção
Como você acabou de mudar o `manifest.json` aqui no preview, **você precisa redeployar pra produção** pelo botão "Save & Deploy" do Emergent. Sem isso, o PWA Builder vai ler o manifest antigo de `https://ligo.system` e o APK sai com nome errado.

### 2. Acessar PWA Builder
👉 https://www.pwabuilder.com/

### 3. Colar a URL do PWA
```
https://ligo.system
```
Clica em **"Start"**.

O site vai analisar e dar um score (manifest, service worker, security). O score deveria estar bem alto agora.

### 4. Clica em "Package For Stores" (canto superior direito)

### 5. Selecionar Android
Aparecem opções (Android, Windows, iOS). Escolhe **Android**.

### 6. Configurar o APK
Preencher exatamente assim:

| Campo | Valor |
|---|---|
| **Package ID** | `system.ligo.colaborador` |
| **App name** | `Ligo Colaborador` |
| **App launcher name** | `Ligo` |
| **App version** | `1.0.0` |
| **App version code** | `1` |
| **Host** | `ligo.system` |
| **Start URL** | `/?mode=app` |
| **Theme color** | `#0f172a` |
| **Background color** | `#0f172a` |
| **Display mode** | `standalone` |
| **Status bar color** | `#0f172a` |
| **Signing key** | `New` (gerar nova keystore) |
| **Key alias** | `ligo-colaborador` |
| **Key password** | (escolha uma senha forte e GUARDE) |
| **Key country** | `BR` |
| **Key org** | `Ligo Telecom` |

⚠️ **MUITO IMPORTANTE**: Guarde a keystore (.keystore) e a senha. Sem isso você não consegue lançar atualizações futuras pela Play Store. PWA Builder oferece pra baixar a keystore — **baixa e guarda em local seguro**.

### 7. Clica em **"Download"**
Você recebe um `.zip` com:
- `app-release-signed.apk` ← **este é o APK que você instala/distribui**
- `app-release-bundle.aab` ← bundle pra Play Store
- `assetlinks.json` ← arquivo a colocar no servidor (ver passo 9)
- `signing-key-info.txt` ← contém o **SHA-256 fingerprint** do certificado
- `keystore.keystore` ← guarde com a senha

### 8. Pegar o SHA-256 fingerprint
Abra o arquivo `signing-key-info.txt` baixado, copie a linha que começa com `SHA-256:`. Vai ser algo como:
```
SHA-256: 14:6D:E9:83:C5:73:06:50:D8:EE:B9:95:2F:34:FC:64:16:A0:83:42:E6:1D:BE:A8:8A:04:96:B2:3F:CF:44:E5
```

### 9. Atualizar o assetlinks.json no preview e redeployar
Me mande esse SHA-256 que eu atualizo `/.well-known/assetlinks.json` aqui no preview e você redeploya. Isso é o que tira a barra do Chrome do app (deixa ele full-screen como um app nativo de verdade).

Sem isso o APK abre mas mostra uma barrinha do Chrome no topo dizendo "ligo.system".

### 10. Instalar o APK no celular
- Copia o `.apk` pra um Google Drive / WhatsApp do técnico
- No celular Android: habilita "Fontes desconhecidas" em **Configurações > Segurança**
- Abre o `.apk` e instala
- App aparece como **"Ligo Colaborador"** no launcher 🚀

### 11. (Opcional) Publicar na Play Store
Pra publicar oficialmente:
- Cria uma conta de desenvolvedor Play Console (US$ 25 uma única vez)
- Sobe o `.aab` (bundle, não o APK)
- Preenche listagem (screenshots, descrição, categoria "Business")
- Submete pra revisão (~2 a 7 dias)

---

## 🔁 Atualizações futuras
**O grande benefício do TWA:** quando você atualiza o app web (via deploy do Emergent), o APK instalado nos técnicos puxa a versão nova **sem precisar republicar APK**. Só precisa republicar APK em mudanças estruturais (nome, ícone, package, target SDK Android).

---

## 🆘 Troubleshooting

### Barra do Chrome aparece no topo do app
- assetlinks.json não foi configurado com o SHA-256 correto, OU
- A URL no APK não bate com a do assetlinks (mudou subdomínio?), OU
- O servidor não está servindo `/.well-known/assetlinks.json` corretamente (precisa ser `Content-Type: application/json`)

### App não abre / tela branca
- Service worker antigo em cache. No celular do técnico: **Configurações > Apps > Ligo Colaborador > Armazenamento > Limpar dados**

### "App not installed" na instalação
- Já existe um APK com mesmo package name (`system.ligo.colaborador`) no celular. Desinstale o antigo primeiro.

---

## Sobre os caminhos alternativos (caso queira)

- **Capacitor** — pra ter câmera/biometria/FCM Push nativos (não é só wrap da web). Requer Android Studio no PC.
- **Bubblewrap CLI** — equivalente ao PWA Builder via terminal. Requer Java 17 + Android SDK no PC.

O caminho TWA (PWA Builder) que escolhemos é suficiente pro Lousa Mobile porque ele já usa apenas Web APIs (geolocation, camera via input, vibrate, notifications) que rodam nativas no Chrome WebView.
