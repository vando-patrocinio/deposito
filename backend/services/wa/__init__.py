"""Pacote de serviços auxiliares do WhatsApp/Baileys.

Originalmente esses helpers estavam em routes/whatsapp_baileys.py (4100+ linhas).
Foram extraídos pra facilitar manutenção e testes unitários.

Módulos:
  - sidecar.py     : comunicação HTTP com o Node.js Baileys sidecar
  - text_utils.py  : utilitários de processamento de texto (split, normalize)
  - auto_reply.py  : pipeline de resposta automática IA (Isabella/Alvaro/Camila)
"""
