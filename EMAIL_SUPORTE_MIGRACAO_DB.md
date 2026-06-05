# 📧 EMAIL PRONTO — Migração Prod → Preview

> Salve esse texto, copie e cole no seu cliente de email favorito.

---

**Para:** support@emergent.sh
**Assunto:** Solicitação de Migração de Dados MongoDB - Produção para Preview

---

Olá equipe Emergent,

Preciso copiar todos os dados do MongoDB de PRODUÇÃO para o MongoDB do
ambiente de PREVIEW do meu projeto.

DETALHES DO PROJETO:
- Job ID: 0f7afc70-e3c4-4925-8f2c-a35d20f80a39
- URL de Produção: https://dual-combine-3.emergent.host
- Domínio customizado: ligo.system
- URL de Preview: https://dual-combine-3.preview.emergentagent.com
- Conta/email da plataforma: vando@ligotelecom.com

MOTIVO:
Sofri um rollback acidental no preview e perdi parte do estado de trabalho.
A produção tem todos os dados reais dos clientes, NFs e ONTs do meu provedor
de internet (Ligo Telecom). Preciso desses dados no preview para validar
novas features (iter203 Fatura Consolidada e iter204 Multi-item NF
automático) antes do próximo deploy.

SOLICITAÇÃO:
Por favor, façam a CÓPIA COMPLETA do MongoDB de produção para o MongoDB
do preview, substituindo os dados de teste atuais do preview (autorizo
o overwrite total).

DÚVIDAS:
1. Os dados de preview serão totalmente substituídos? (autorizo apagar.)
2. Qual o prazo estimado para conclusão?
3. Após a cópia, vou continuar conseguindo fazer login no preview com o
   mesmo email/senha que uso em produção (vando@ligotelecom.com)?

Aguardo retorno.

Atenciosamente,
Vando
Ligo Telecom

---

## Pré-requisitos antes de mandar:

1. ☐ Clicar em "Save to GitHub" no Emergent (proteção do estado atual do preview)
2. ☐ Verificar que o Deploy de iter203/iter204 para produção JÁ foi feito (caso queira
   que a produção tenha esse código antes da cópia inversa de dados)
3. ☐ Confirmar com sua equipe que os dados reais de clientes podem ser usados em
   preview (LGPD/conformidade)
