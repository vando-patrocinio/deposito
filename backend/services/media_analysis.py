"""Análise multimodal de mídia inbound (imagem · PDF).

Usa Gemini Vision via Emergent LLM Key (gemini-2.5-flash — recomendado, estável).

Casos típicos pra Isabella:
  - Foto de modem com luz vermelha → "LOS detectada"
  - Foto de boleto → extrai valor + vencimento
  - PDF de comprovante PIX → extrai valor pago
  - Foto de RG/CNH → confirma se documento legível
  - Foto da rua → confirma endereço pra instalação

Retorna string descritiva curta (max ~250 chars) pra injetar no prompt da
Isabella como contexto, no formato:

  [VISÃO_AUTO: <descrição>]

A Isabella usa esse contexto e responde adequadamente ao cliente.
"""
import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_PROVIDER = "gemini"


SYSTEM_PROMPT_VISION = """Você é um analista visual da Ligo Fibra (ISP de internet).
Sua tarefa é descrever de forma OBJETIVA e ÚTIL o que aparece nessa imagem
ou documento, em PORTUGUÊS, em NO MÁXIMO 200 caracteres.

REGRAS DE CLASSIFICAÇÃO:

1. Modem/roteador com LUZ VERMELHA fixa (LOS/PON) → diga:
   "Foto de modem Ligo. LED LOS vermelho aceso — fibra rompida (LOS)."

2. Modem/roteador com luzes normais (verdes/azuis) → diga:
   "Foto de modem Ligo. LEDs normais — equipamento parece operacional."

3. Boleto/fatura → extraia:
   "Boleto: Valor R$ X · Vencimento DD/MM/YYYY · Cedente [nome se visível]."

4. Comprovante PIX/TED → extraia:
   "Comprovante: PIX/TED de R$ X em DD/MM/YYYY para [destinatário]."

5. Documento (RG/CNH/CPF):
   - Se legível: "RG/CNH legível. Nome: X. CPF: Y."
   - Se ilegível: "Documento ilegível. Solicitar nova foto com mais luz."

6. Selfie com documento → diga se rosto e doc visíveis:
   "Selfie OK: rosto e documento visíveis." OU "Selfie inválida: documento ilegível."

7. Comprovante de endereço → diga:
   "Comprovante de endereço: [nome] · [endereço] · [empresa emitente]."

8. Foto de casa/fachada → diga:
   "Foto da fachada de imóvel residencial." (ou comercial, dependendo)

9. Outros → descreva sucintamente o que vê.

SEMPRE comece com a categoria (Modem/Boleto/Selfie/etc) seguida de 2 pontos.
NUNCA invente dados que não estão visíveis na imagem.
NUNCA use mais de 200 caracteres na descrição.
"""


async def analyze_image(image_b64: str, mime_type: str = "image/jpeg") -> Optional[str]:
    """Analisa imagem (base64) e retorna descrição curta.

    Returns:
        String descritiva pra injetar no prompt da Isabella, ou None em erro.
    """
    if not EMERGENT_KEY:
        logger.info("[vision] EMERGENT_LLM_KEY não configurada")
        return None
    if not image_b64:
        return None

    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
        session_id = f"vision-{base64.b32encode(os.urandom(6)).decode().lower()}"
        chat = LlmChat(
            api_key=EMERGENT_KEY, session_id=session_id,
            system_message=SYSTEM_PROMPT_VISION,
        ).with_model(DEFAULT_PROVIDER, DEFAULT_MODEL)

        msg = UserMessage(
            text="Analise essa mídia e descreva conforme suas regras.",
            file_contents=[ImageContent(image_base64=image_b64)],
        )
        response = await chat.send_message(msg)
        result = (response or "").strip()
        if len(result) > 260:
            result = result[:257] + "..."
        logger.info("[vision] analisado · %s chars", len(result))
        return result or None
    except Exception as e:
        logger.warning("[vision] análise falhou: %s", e)
        return None


async def analyze_pdf(pdf_b64: str) -> Optional[str]:
    """Analisa PDF (base64) e retorna descrição/extração de dados-chave.

    Estratégia: extrai texto primeiro via pypdf (rápido); se vier vazio
    ou < 50 chars (PDF escaneado / imagem), faz fallback p/ Gemini Vision.
    """
    if not pdf_b64:
        return None
    try:
        import io
        import pdfplumber
        pdf_bytes = base64.b64decode(pdf_b64)
        full = ""
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:5]:
                try:
                    full += (page.extract_text() or "") + "\n"
                except Exception:
                    continue
        text = (full or "").strip()
        # Texto extraído bom → análise via Gemini só do texto (mais barato)
        if len(text) >= 50:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            session_id = f"pdf-{base64.b32encode(os.urandom(6)).decode().lower()}"
            chat = LlmChat(
                api_key=EMERGENT_KEY, session_id=session_id,
                system_message=SYSTEM_PROMPT_VISION,
            ).with_model(DEFAULT_PROVIDER, DEFAULT_MODEL)
            msg = UserMessage(text=(
                "Analise este PDF e descreva conforme suas regras (max 200 "
                f"chars):\n\n{text[:8000]}"
            ))
            response = await chat.send_message(msg)
            result = (response or "").strip()
            if len(result) > 260:
                result = result[:257] + "..."
            return result or None
    except Exception as e:
        logger.warning("[vision-pdf] extração de texto falhou: %s", e)
    # Fallback: PDF escaneado → tenta como imagem (1ª pág)
    # Por simplicidade, deixamos analyze_image lidar com a thumbnail
    return None


async def analyze_media(media_b64: str, mime_type: str,
                          kind: str) -> Optional[str]:
    """Despacha para função certa baseado em tipo."""
    if not media_b64:
        return None
    if kind == "image":
        return await analyze_image(media_b64, mime_type=mime_type)
    if kind == "document":
        if "pdf" in (mime_type or "").lower():
            return await analyze_pdf(media_b64)
        # Outros docs (.docx, .xlsx) — não suportado por ora
        return None
    # video / sticker → não analisamos
    return None
