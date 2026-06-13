"""IAM v2 — Runtime helpers (placeholder até USE_NEW_IAM=1).

Inativo enquanto flag = 0. Em ETAPA 5 (Login refatorado), aqui mora:
  - `get_current_user(request) → AuthedUser`
  - device fingerprint resolver
  - session lookup com cache
  - JWT issuance/verification

⚠️  Função `get_current_user` é stub. Em produção (flag=1) será o único
ponto de entrada de autenticação — substitui `auth.make_dependencies`.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import Request, HTTPException

logger = logging.getLogger("iam_v2.runtime")


def device_fingerprint(request: Request) -> str:
    """Calcula fingerprint determinístico (SHA-256) a partir da request.

    Inputs: user-agent + ip + accept-language. Estável para mesmo browser
    em mesma rede. NÃO é PII (hash one-way).
    """
    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    al = request.headers.get("accept-language", "")
    raw = f"{ua}|{ip}|{al}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def get_current_user(request: Request):
    """STUB — em flag=0, levanta erro pra evitar uso acidental.

    Em flag=1 (após ETAPA 5), faz:
      1. Decode JWT → jti
      2. Lookup `db.sessions` by jti + revoked_at=None
      3. Lookup Identity, Membership, Profile (1 round-trip agregado)
      4. Compose AuthedUser
      5. Async update last_seen_at
    """
    from . import NEW_IAM_ENABLED
    if not NEW_IAM_ENABLED:
        raise HTTPException(
            500,
            "iam_v2.runtime.get_current_user chamado em modo legacy. "
            "Use auth.make_dependencies() do módulo legado.",
        )
    raise NotImplementedError(
        "iam_v2.runtime.get_current_user será implementado em ETAPA 5"
    )
