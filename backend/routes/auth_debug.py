"""auth_debug.py — CTO 13/06/2026.

Endpoint diagnóstico pro user/colaborador abrir DIRETO no celular e
descobrir por que está dando "Sessão expirada" / 401.

PÚBLICO (sem auth): aceita qualquer token via header OU query string
?token=xxx — não importa se válido ou não, retorna análise textual.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/auth/debug", tags=["auth-debug"])


@router.get("/whoami", response_class=HTMLResponse)
async def whoami_debug(request: Request, token: Optional[str] = None):
    """Mostra o estado de auth do request — útil pra debug remoto via celular.

    Aceita token via:
      - Header `Authorization: Bearer <token>`
      - Query string `?token=<token>`

    Retorna HTML simples legível em qualquer celular.
    """
    auth_h = request.headers.get("authorization") or ""
    bearer = auth_h[7:].strip() if auth_h.lower().startswith("bearer ") else ""
    token = (token or bearer or "").strip()

    user_email = "—"
    user_role = "—"
    user_id = "—"
    user_collab = "—"
    user_company = "—"
    decode_status = "❌ Sem token"
    decode_error = ""
    db_session_match = "—"
    db_user_found = "—"

    if token:
        decode_status = "Tentando decode..."
        try:
            from auth import decode_token
            payload = decode_token(token)
            if payload and isinstance(payload, dict):
                decode_status = "✅ Token decodificado"
                user_id = str(payload.get("sub") or payload.get("user_id") or "—")
                user_email = str(payload.get("email") or "—")
                user_role = str(payload.get("role") or "—")
                # Busca user no DB
                from database import db
                user_doc = await db.users.find_one({"id": user_id}, {"_id": 0})
                if user_doc:
                    db_user_found = "✅ Encontrado no DB"
                    user_collab = str(user_doc.get("collaborator_id") or "—")
                    user_company = str(user_doc.get("company_id") or "—")
                    db_active_sid = user_doc.get("active_session_id")
                    token_sid = payload.get("session_id") or payload.get("sid")
                    if db_active_sid and token_sid:
                        if db_active_sid == token_sid:
                            db_session_match = "✅ session_id BATE"
                        else:
                            db_session_match = (
                                f"❌ session_id do token NÃO bate com DB. "
                                f"DB={db_active_sid[:8]}... "
                                f"Token={str(token_sid)[:8]}... "
                                f"(você logou em OUTRO dispositivo? "
                                f"Logue de novo aqui)"
                            )
                    else:
                        db_session_match = "⚠️ session_id ausente"
                else:
                    db_user_found = f"❌ User_id {user_id} NÃO encontrado no DB"
            else:
                decode_status = "❌ Decode retornou vazio"
        except Exception as e:  # noqa: BLE001
            decode_status = "❌ Decode falhou"
            decode_error = str(e)[:200]

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Auth Debug</title>
      <style>
        body {{ font-family: -apple-system, sans-serif; padding:16px;
                background:#0f172a; color:#e2e8f0; }}
        h1 {{ font-size:18px; margin:0 0 16px; }}
        .row {{ background:#1e293b; padding:10px; border-radius:8px;
                 margin-bottom:8px; }}
        .label {{ color:#94a3b8; font-size:11px; text-transform:uppercase;
                  letter-spacing:1px; }}
        .value {{ color:#fff; font-size:13px; word-break:break-all;
                  margin-top:4px; font-family:monospace; }}
        .ok {{ color:#10b981; }} .err {{ color:#ef4444; }}
        .warn {{ color:#f59e0b; }}
      </style>
    </head>
    <body>
      <h1>🔍 SmartProv — Diagnóstico Auth</h1>
      <div class="row">
        <div class="label">Timestamp UTC</div>
        <div class="value">{datetime.now(timezone.utc).isoformat()}</div>
      </div>
      <div class="row">
        <div class="label">Host visto pelo backend</div>
        <div class="value">{request.headers.get('host', '—')}</div>
      </div>
      <div class="row">
        <div class="label">Token recebido (primeiros 30 chars)</div>
        <div class="value">{token[:30] + '...' if token else '—'}</div>
      </div>
      <div class="row">
        <div class="label">Decode JWT</div>
        <div class="value">{decode_status}</div>
        {f'<div class="value err">{decode_error}</div>' if decode_error else ''}
      </div>
      <div class="row">
        <div class="label">User ID</div>
        <div class="value">{user_id}</div>
      </div>
      <div class="row">
        <div class="label">User no DB</div>
        <div class="value">{db_user_found}</div>
      </div>
      <div class="row">
        <div class="label">E-mail</div>
        <div class="value">{user_email}</div>
      </div>
      <div class="row">
        <div class="label">Role</div>
        <div class="value">{user_role}</div>
      </div>
      <div class="row">
        <div class="label">company_id</div>
        <div class="value">{user_company}</div>
      </div>
      <div class="row">
        <div class="label">collaborator_id vinculado</div>
        <div class="value">{user_collab}</div>
      </div>
      <div class="row">
        <div class="label">session_id do token vs DB</div>
        <div class="value">{db_session_match}</div>
      </div>
      <hr style="border-color:#334155;margin:16px 0;">
      <div style="font-size:11px; color:#64748b;">
        Como usar: abre este endereço no mesmo navegador onde está dando
        erro. Manda print pro admin.
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
