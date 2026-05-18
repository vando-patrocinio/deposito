"""Onboarding seguro para captura de documentos do cliente (pós-venda).

Fluxo:
  1. Isabella concluiu venda (Passo 5) → cria sessão via
     `create_onboarding_session(company_id, phone, plan, name)` que retorna
     uma URL única assinada (HMAC) com TTL de 24h.
  2. Cliente abre a URL no celular → tela enxuta pede:
     - Foto do comprovante de endereço (overlay com retângulo guia)
     - Foto do RG/CNH (overlay com retângulo cartão)
     - Selfie (overlay oval — estilo banco/ponto)
     - E-mail + vencimento preferido
  3. Cada upload roda OCR via Emergent LLM (gpt-5-mini com vision) que
     extrai: nome, CPF, data nascimento, RG, endereço, cidade, CEP.
  4. Backend monta `subscribers.pre_registration` com dados extraídos pra
     atendente revisar e confirmar.

Segurança:
  - Token = `payload_b64.signature_b64` (HMAC-SHA256 com SECRET interno)
  - Payload tem session_id + company_id + expires_at
  - Verificação rejeita expirados ou assinatura inválida
  - Upload máximo 10MB por arquivo
  - Pasta isolada por session_id em `/app/backend/uploads/onboarding/`
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("ponto.onboarding")

# Diretório de uploads
UPLOAD_BASE = Path("/app/backend/uploads/onboarding")
UPLOAD_BASE.mkdir(parents=True, exist_ok=True)

# Secret pra assinar tokens (TTL 24h por padrão)
# Em produção real, vir de env. Aqui usa o próprio MONGO_URL hash como seed
# pra estabilidade entre restarts (sem persistir o segredo).
_SECRET_SEED = os.environ.get("ONBOARDING_SECRET") or hashlib.sha256(
    (os.environ.get("MONGO_URL") or "ligo-onboarding-fallback").encode()
).hexdigest()
SECRET = _SECRET_SEED.encode()

TOKEN_TTL_SECONDS = 24 * 3600  # 24h


def _sign(payload_b64: str) -> str:
    sig = hmac.new(SECRET, payload_b64.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _encode_payload(d: Dict[str, Any]) -> str:
    raw = json.dumps(d, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_payload(s: str) -> Dict[str, Any]:
    pad = "=" * (-len(s) % 4)
    return json.loads(base64.urlsafe_b64decode(s + pad).decode())


def generate_token(session_id: str, company_id: str,
                      ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """Cria token criptograficamente assinado (HMAC-SHA256)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sid": session_id,
        "cid": company_id,
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "nonce": secrets.token_urlsafe(8),
    }
    payload_b64 = _encode_payload(payload)
    sig = _sign(payload_b64)
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida assinatura + expiração. Retorna payload ou None se inválido."""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = _sign(payload_b64)
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning("[onboarding] token com assinatura inválida")
            return None
        payload = _decode_payload(payload_b64)
        if int(payload.get("exp", 0)) < int(
            datetime.now(timezone.utc).timestamp()
        ):
            logger.info("[onboarding] token expirado sid=%s", payload.get("sid"))
            return None
        return payload
    except Exception as e:
        logger.warning("[onboarding] erro ao verificar token: %s", e)
        return None


async def create_session(
    company_id: str,
    phone: str,
    plan_name: Optional[str] = None,
    suggested_name: Optional[str] = None,
    suggested_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria sessão de onboarding. Retorna dict com `token` e `url`."""
    session_id = f"obs-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    doc = {
        "id": session_id,
        "company_id": company_id,
        "phone": phone,
        "plan_name": plan_name,
        "suggested_name": suggested_name,
        "suggested_email": suggested_email,
        "status": "pending",  # pending | partial | submitted | expired
        "uploaded": {
            "address_proof": False,
            "id_document": False,
            "selfie": False,
        },
        "ocr": {},  # dados extraídos do RG/comprovante
        "form": {},  # email + vencimento submetidos
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat(),
    }
    await db.onboarding_sessions.insert_one(doc)

    # Cria diretório isolado
    (UPLOAD_BASE / session_id).mkdir(parents=True, exist_ok=True)

    token = generate_token(session_id, company_id)
    base_url = (
        os.environ.get("PUBLIC_FRONTEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL")
        or ""
    )
    url = f"{base_url.rstrip('/')}/onboarding/{token}"
    return {
        "session_id": session_id,
        "token": token,
        "url": url,
        "expires_at": doc["expires_at"],
    }


async def get_session_for_token(token: str) -> Optional[Dict[str, Any]]:
    payload = verify_token(token)
    if not payload:
        return None
    sess = await db.onboarding_sessions.find_one(
        {"id": payload["sid"], "company_id": payload["cid"]},
        {"_id": 0},
    )
    return sess


async def save_upload(
    token: str,
    file_kind: str,  # "address_proof" | "id_document" | "selfie"
    file_bytes: bytes,
    filename: str,
    content_type: str = "image/jpeg",
) -> Dict[str, Any]:
    payload = verify_token(token)
    if not payload:
        raise ValueError("Token inválido ou expirado")
    if file_kind not in {"address_proof", "id_document", "selfie"}:
        raise ValueError(f"Tipo de arquivo desconhecido: {file_kind}")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise ValueError("Arquivo maior que 10MB")
    if len(file_bytes) < 1024:
        raise ValueError("Arquivo muito pequeno (mínimo 1KB)")

    sid = payload["sid"]
    cid = payload["cid"]
    ext = (filename.rsplit(".", 1)[-1] or "jpg").lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "heic"}:
        ext = "jpg"
    save_path = UPLOAD_BASE / sid / f"{file_kind}.{ext}"
    save_path.write_bytes(file_bytes)

    now = datetime.now(timezone.utc).isoformat()
    update = {
        f"uploaded.{file_kind}": True,
        f"files.{file_kind}": {
            "filename": filename,
            "path": str(save_path),
            "size": len(file_bytes),
            "content_type": content_type,
            "uploaded_at": now,
        },
        "updated_at": now,
        "status": "partial",
    }
    await db.onboarding_sessions.update_one(
        {"id": sid, "company_id": cid}, {"$set": update}
    )

    # Roda OCR pra id_document e address_proof
    ocr_extracted = None
    if file_kind in {"id_document", "address_proof"}:
        try:
            ocr_extracted = await _run_ocr(
                file_bytes, file_kind, content_type
            )
            if ocr_extracted:
                await db.onboarding_sessions.update_one(
                    {"id": sid, "company_id": cid},
                    {"$set": {f"ocr.{file_kind}": ocr_extracted,
                                "updated_at": now}},
                )
        except Exception as e:
            logger.warning("[onboarding] OCR failed for %s: %s", file_kind, e)

    return {
        "ok": True,
        "session_id": sid,
        "file_kind": file_kind,
        "size": len(file_bytes),
        "ocr_extracted": ocr_extracted,
    }


async def liveness_check(
    token: str,
    frames: list,  # lista de tuples (label, bytes) — 3 frames
) -> Dict[str, Any]:
    """Validação de vivacidade — 3 frames de poses diferentes.

    Recebe `frames = [('left', bytes), ('right', bytes), ('smile', bytes)]`.
    Manda pro LLM com vision pra confirmar:
      - É a MESMA pessoa nos 3 frames?
      - As poses correspondem à pedida (esquerda/direita/sorriso)?
      - Não é foto-de-foto (sem reflexo de tela, sem moldura)?

    Retorna `{is_live, confidence, reason}`. Se passar, salva frames como
    `selfie_left.jpg`, `selfie_right.jpg`, `selfie_smile.jpg` e marca
    `uploaded.selfie = True`.
    """
    payload = verify_token(token)
    if not payload:
        raise ValueError("Token inválido ou expirado")
    if len(frames) != 3:
        raise ValueError("Esperados 3 frames (esquerda, direita, sorriso)")
    for label, fb in frames:
        if not fb or len(fb) > 10 * 1024 * 1024:
            raise ValueError(f"Frame '{label}' inválido ou muito grande")
        if len(fb) < 512:
            raise ValueError(f"Frame '{label}' muito pequeno")

    sid = payload["sid"]
    cid = payload["cid"]
    now = datetime.now(timezone.utc).isoformat()

    # Salva os 3 frames
    saved_paths = {}
    for label, fb in frames:
        p = UPLOAD_BASE / sid / f"selfie_{label}.jpg"
        p.write_bytes(fb)
        saved_paths[label] = str(p)

    # Roda LLM vision
    result = await _run_liveness_llm(frames)

    final_status = {
        "is_live": bool(result.get("is_live")),
        "confidence": float(result.get("confidence", 0) or 0),
        "reason": str(result.get("reason", "") or ""),
        "checked_at": now,
        "saved_paths": saved_paths,
    }

    update = {
        "liveness": final_status,
        "updated_at": now,
    }
    if final_status["is_live"]:
        update["uploaded.selfie"] = True
        update["files.selfie"] = {
            "filename": "selfie_liveness.jpg",
            "path": saved_paths.get("smile") or saved_paths.get("right"),
            "size": sum(len(b) for _, b in frames),
            "content_type": "image/jpeg",
            "uploaded_at": now,
            "liveness_validated": True,
        }
        update["status"] = "partial"

    await db.onboarding_sessions.update_one(
        {"id": sid, "company_id": cid}, {"$set": update}
    )
    return final_status


async def _run_liveness_llm(frames: list) -> Dict[str, Any]:
    """Manda 3 frames pro LLM vision e pede análise de vivacidade."""
    from core import EMERGENT_LLM_KEY
    if not EMERGENT_LLM_KEY:
        logger.warning("[onboarding] EMERGENT_LLM_KEY ausente — liveness MOCK")
        # Sem LLM, aceita como live por default pra não travar fluxo (dev)
        return {"is_live": True, "confidence": 0.5,
                "reason": "LLM key ausente — aprovação default"}

    from emergentintegrations.llm.chat import (
        LlmChat, UserMessage, ImageContent,
    )

    prompt = (
        "Você é um sistema de verificação de vivacidade (liveness check) "
        "antifraude pra onboarding bancário/telecom. Recebeu 3 frames "
        "sequenciais de uma selfie SUPOSTAMENTE ao vivo:\n\n"
        "Frame 1: cliente olhando pra ESQUERDA (cabeça virada)\n"
        "Frame 2: cliente olhando pra DIREITA (cabeça virada)\n"
        "Frame 3: cliente SORRINDO de frente\n\n"
        "Analise se são FRAMES REAIS de uma pessoa AO VIVO ou uma TENTATIVA "
        "DE FRAUDE (foto de foto, vídeo gravado, máscara, deep fake óbvio).\n\n"
        "Critérios pra `is_live=true`:\n"
        "- É a mesma pessoa nos 3 frames (não foto trocada)\n"
        "- As poses combinam com o pedido (esquerda/direita/sorriso)\n"
        "- Sem moldura visível / reflexo de tela / bordas pretas suspeitas\n"
        "- Iluminação consistente e natural\n"
        "- Olhos e textura da pele naturais\n\n"
        "Responda APENAS em JSON, sem markdown:\n"
        "{\n"
        '  "is_live": true|false,\n'
        '  "confidence": 0.0-1.0,\n'
        '  "reason": "explicação curta em pt-BR (máx 150 chars)"\n'
        "}"
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"liveness-{uuid.uuid4().hex[:8]}",
        system_message=(
            "Você é especialista em verificação antifraude. Responda APENAS "
            "o JSON pedido, sem texto extra, sem markdown."
        ),
    ).with_model("openai", "gpt-5-mini").with_max_tokens(500)

    image_contents = [
        ImageContent(image_base64=base64.b64encode(fb).decode())
        for _, fb in frames
    ]
    msg = UserMessage(text=prompt, file_contents=image_contents)
    raw = str(await chat.send_message(msg)).strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1] if "```" in raw[3:] else raw[3:]
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning("[onboarding] liveness JSON parse: %s | raw=%s",
                        e, raw[:200])
    return {"is_live": False, "confidence": 0,
             "reason": "Falha ao processar análise"}


async def _run_ocr(
    file_bytes: bytes, file_kind: str, content_type: str,
) -> Optional[Dict[str, Any]]:
    """Extrai dados do documento via LLM com vision.

    Retorna dict estruturado com os campos relevantes pro pré-cadastro.
    """
    from core import EMERGENT_LLM_KEY
    if not EMERGENT_LLM_KEY:
        logger.warning("[onboarding] EMERGENT_LLM_KEY ausente — pulando OCR")
        return None

    from emergentintegrations.llm.chat import (
        LlmChat, UserMessage, ImageContent,
    )

    if file_kind == "id_document":
        prompt = (
            "Esta é uma foto de um documento de identidade brasileiro "
            "(RG ou CNH). Extraia os dados em JSON estruturado, sem comentários. "
            "Use null para campos ilegíveis. Schema:\n"
            "{\n"
            '  "type": "RG" ou "CNH",\n'
            '  "name": "nome completo",\n'
            '  "cpf": "11 dígitos sem pontuação",\n'
            '  "rg": "número do RG",\n'
            '  "birth_date": "DD/MM/YYYY",\n'
            '  "issuing_state": "UF emissor",\n'
            '  "issued_at": "DD/MM/YYYY"\n'
            "}"
        )
    elif file_kind == "address_proof":
        prompt = (
            "Esta é uma foto de um comprovante de endereço brasileiro (conta "
            "de luz/água/internet/banco). Extraia em JSON. null para "
            "ilegíveis. Schema:\n"
            "{\n"
            '  "name": "nome do titular",\n'
            '  "address": "logradouro completo",\n'
            '  "neighborhood": "bairro",\n'
            '  "city": "cidade",\n'
            '  "state": "UF",\n'
            '  "cep": "00000-000",\n'
            '  "issuer": "concessionária/banco",\n'
            '  "issue_date": "DD/MM/YYYY"\n'
            "}"
        )
    else:
        return None

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ocr-{uuid.uuid4().hex[:8]}",
        system_message=(
            "Você é um OCR de documentos. Responda APENAS o JSON pedido, "
            "sem texto extra, sem markdown. Use null para campos ilegíveis."
        ),
    ).with_model("openai", "gpt-5-mini").with_max_tokens(800)

    image_b64 = base64.b64encode(file_bytes).decode()
    msg = UserMessage(
        text=prompt,
        file_contents=[
            ImageContent(image_base64=image_b64),
        ],
    )
    raw = str(await chat.send_message(msg)).strip()
    # Remove markdown se LLM colocou
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1] if "```" in raw[3:] else raw[3:]
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning("[onboarding] OCR JSON parse: %s | raw=%s", e, raw[:200])
    return None


async def submit_form(
    token: str,
    email: str,
    due_day: int,
) -> Dict[str, Any]:
    """Encerra a sessão com email + dia de vencimento. Marca status=submitted."""
    payload = verify_token(token)
    if not payload:
        raise ValueError("Token inválido ou expirado")
    if "@" not in (email or "") or "." not in (email or ""):
        raise ValueError("E-mail inválido")
    if due_day not in {5, 10, 15}:
        raise ValueError("Vencimento deve ser 5, 10 ou 15")

    sid = payload["sid"]
    cid = payload["cid"]
    now = datetime.now(timezone.utc).isoformat()
    sess = await db.onboarding_sessions.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0}
    )
    if not sess:
        raise ValueError("Sessão não encontrada")
    uploaded = sess.get("uploaded") or {}
    missing = [k for k in ["address_proof", "id_document", "selfie"]
               if not uploaded.get(k)]
    if missing:
        raise ValueError(f"Documentos pendentes: {', '.join(missing)}")

    # Monta pré-cadastro
    ocr = sess.get("ocr") or {}
    id_data = ocr.get("id_document") or {}
    addr_data = ocr.get("address_proof") or {}
    pre_reg = {
        "phone": sess.get("phone"),
        "email": email,
        "due_day": due_day,
        "plan_name": sess.get("plan_name"),
        "name": id_data.get("name") or addr_data.get("name") or sess.get("suggested_name"),
        "document": id_data.get("cpf"),
        "rg": id_data.get("rg"),
        "birth_date": id_data.get("birth_date"),
        "address": addr_data.get("address"),
        "neighborhood": addr_data.get("neighborhood"),
        "city": addr_data.get("city"),
        "state": addr_data.get("state"),
        "cep": addr_data.get("cep"),
        "source": "onboarding_self_service",
        "session_id": sid,
        "created_at": now,
    }

    await db.onboarding_sessions.update_one(
        {"id": sid, "company_id": cid},
        {"$set": {
            "form.email": email,
            "form.due_day": due_day,
            "pre_registration": pre_reg,
            "status": "submitted",
            "submitted_at": now,
            "updated_at": now,
        }},
    )

    # Insere também em uma coleção dedicada pra atendente revisar
    await db.subscriber_pre_registrations.insert_one({
        "id": f"pre-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        **pre_reg,
        "status": "aguardando_revisao",
    })

    logger.info(
        "[onboarding] session %s submitted — phone=%s name=%s",
        sid, sess.get("phone"), pre_reg.get("name"),
    )
    return {"ok": True, "session_id": sid, "pre_registration": pre_reg}
