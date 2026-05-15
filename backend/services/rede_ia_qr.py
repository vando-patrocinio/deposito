"""rede_IA — utilidades de QR Code (HMAC + geração PNG + scan)."""
import base64
import hashlib
import hmac
import io
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

QR_SECRET = os.environ.get("REDE_IA_QR_SECRET") or "smartprov-rede-ia-2026-default-secret-change-me"
QR_VERSION = "v1"
QR_PREFIX = "SPCTO"  # SmartProv CTO


def qr_sign(payload_b64: str) -> str:
    """HMAC-SHA256 sobre o payload base64 + segredo do servidor."""
    return hmac.new(
        QR_SECRET.encode("utf-8"),
        msg=payload_b64.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()[:32]


def build_qr_token(cto_id: str, company_id: str, name: str) -> str:
    """Formato: SPCTO|v1|<b64payload>|<hmac>"""
    payload = {
        "cid": company_id,
        "id": cto_id,
        "name": name,
        "ts": int(datetime.now(timezone.utc).timestamp()),
        "n": uuid.uuid4().hex[:8],
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = qr_sign(b64)
    return f"{QR_PREFIX}|{QR_VERSION}|{b64}|{sig}"


def verify_qr_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida HMAC e devolve o payload, ou None se inválido."""
    try:
        parts = (token or "").split("|")
        if len(parts) != 4:
            return None
        prefix, version, b64, sig = parts
        if prefix != QR_PREFIX or version != QR_VERSION:
            return None
        if not hmac.compare_digest(qr_sign(b64), sig):
            return None
        pad = "=" * (-len(b64) % 4)
        raw = base64.urlsafe_b64decode(b64 + pad)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def render_qr_png(token: str, box_size: int = 8, border: int = 2) -> bytes:
    """Gera PNG do QR Code com o token."""
    import qrcode
    img = qrcode.make(token, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
