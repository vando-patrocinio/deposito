# NOTICE — Identificação de Propriedade Intelectual

Este software é de propriedade exclusiva de:

**V S DO PATROCINIO PROVEDOR DE INTERNET ME**
- CNPJ: 13.302.883/0001-36
- Contato: vando@ligotelecom.com
- Produto: SmartProv (Suite ISP — Billing, Network, Fleet, AI)

Copyright © 2025-2026. Todos os direitos reservados.

Consulte o arquivo [LICENSE](./LICENSE) para os termos completos de uso.

---

## Marcação de propriedade embutida no sistema

Para fins de rastreamento e prova de autoria, este sistema embute
**múltiplos fingerprints** que sobrevivem a clones, forks e edições:

1. **Cabeçalho `# Copyright (c) ...`** no topo dos arquivos-fonte principais
   (`server.py`, `App.js`, `database.py` etc.)
2. **Endpoint público `/api/about`** retorna nome, CNPJ e hash assinado
3. **Cabeçalho HTTP `X-Powered-By: SmartProv © 13.302.883/0001-36`**
   adicionado em todas as respostas
4. **Meta tag `<meta name="owner">`** no `index.html` do frontend
5. **Hash criptográfico** baseado em CNPJ + timestamp de boot, retornado
   em `/api/about` como evidência de instância autêntica
6. **Marca discreta no banco MongoDB** (`_meta.owner` na collection
   `system_settings`) — sobrevive a clones de banco

Remoção ou alteração desses identificadores configura violação contratual.
