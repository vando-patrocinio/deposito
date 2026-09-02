"""Emergent Object Storage — armazenamento persistente de uploads e PDFs.

Arquivos gravados no disco do pod são perdidos a cada deploy/restart do
Kubernetes. Este módulo grava no object storage gerenciado e mantém
FALLBACK DE LEITURA no disco para os registros antigos (holerites,
onboarding, imagens rápidas já salvos antes da migração).

Convenção de caminho: `smartprov/<dominio>/<...>` (sem barra inicial).
Caminhos gravados no Mongo levam o prefixo `objstore://` para diferenciar
de caminhos locais legados.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import requests

logger = logging.getLogger("ponto.objstore")

_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() \
    or "https://integrations.emergentagent.com"
STORAGE_URL = _BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "smartprov"
SCHEME = "objstore://"

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "heic": "image/heic",
    "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
}

_storage_key: Optional[str] = None


def content_type_for(ext: str) -> str:
    return MIME_TYPES.get((ext or "").lower().lstrip("."),
                           "application/octet-stream")


def init_storage(force: bool = False) -> str:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    r = requests.post(f"{STORAGE_URL}/init",
                       json={"emergent_key": EMERGENT_KEY}, timeout=30)
    r.raise_for_status()
    _storage_key = r.json()["storage_key"]
    return _storage_key


def _put_sync(path: str, data: bytes, content_type: str) -> str:
    for attempt in (0, 1):
        key = init_storage(force=bool(attempt))
        r = requests.put(f"{STORAGE_URL}/objects/{path}",
                          headers={"X-Storage-Key": key,
                                   "Content-Type": content_type},
                          data=data, timeout=120)
        if r.status_code == 404 and attempt == 0:
            continue
        r.raise_for_status()
        return r.json().get("path") or path
    raise RuntimeError("objstore: upload falhou após reinit")


def _get_sync(path: str) -> Tuple[bytes, str]:
    for attempt in (0, 1):
        key = init_storage(force=bool(attempt))
        r = requests.get(f"{STORAGE_URL}/objects/{path}",
                          headers={"X-Storage-Key": key}, timeout=60)
        if r.status_code == 404 and attempt == 0:
            continue
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type",
                                         "application/octet-stream")
    raise FileNotFoundError(path)


async def put_object(path: str, data: bytes, content_type: str) -> str:
    """Grava no object storage e devolve a referência `objstore://<path>`."""
    stored = await asyncio.to_thread(_put_sync, path, data, content_type)
    return f"{SCHEME}{stored}"


async def get_object(ref: str) -> Tuple[bytes, str]:
    """Lê uma referência do object storage (`objstore://...` ou path puro)."""
    path = ref[len(SCHEME):] if ref.startswith(SCHEME) else ref
    return await asyncio.to_thread(_get_sync, path)


async def read_ref(ref: str, legacy_path: Optional[Path] = None
                    ) -> Optional[bytes]:
    """Lê arquivo pela referência gravada no Mongo.

    - `objstore://...` → object storage
    - caminho local legado (ou `legacy_path`) → disco, quando ainda existir
    Devolve None quando o arquivo não existe em nenhum dos dois.
    """
    if ref and ref.startswith(SCHEME):
        try:
            data, _ = await get_object(ref)
            return data
        except Exception as e:
            logger.warning("[objstore] leitura falhou ref=%s: %s", ref, e)
            return None
    for candidate in (Path(ref) if ref else None, legacy_path):
        if candidate:
            try:
                if candidate.exists():
                    return candidate.read_bytes()
            except Exception:
                continue
    return None
