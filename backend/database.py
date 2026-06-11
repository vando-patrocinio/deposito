"""Conexão MongoDB compartilhada por server.py e pelos route modules.

P0 CTO 11/06/2026 — Blindagem do schema da Lousa:
Toda escrita em `db.tickets` passa por `normalize_ticket_payload` /
`normalize_update_doc` (vocabulário canônico de priority/status/type).
Isso é feito via um proxy class que envolve a AsyncIOMotorCollection,
porque Motor usa __getattr__ dinâmico e atribuição direta não persiste.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
_raw_db = mongo_client[os.environ["DB_NAME"]]


class _TicketsGuard:
    """Proxy sobre db.tickets que normaliza payloads críticos antes de escrever.
    Repassa qualquer outro método (find, count_documents, aggregate, etc.) sem mexer.
    Emite evento TICKET_SCHEMA_REJECTED via raw collection quando detecta valor
    completamente fora do vocabulário canônico + aliases conhecidos.
    """

    def __init__(self, raw_coll, raw_db):
        self._raw = raw_coll
        self._raw_db = raw_db

    # Reads — passthrough total
    def __getattr__(self, name):
        return getattr(self._raw, name)

    async def _emit_rejected(self, source: str, doc: dict, rejections: list):
        """Best-effort event emit usando raw collection (sem recursão)."""
        try:
            import uuid
            from datetime import datetime, timezone
            await self._raw_db["system_events"].insert_one({
                "id": f"evt-tsr-{uuid.uuid4().hex[:12]}",
                "event_type": "TICKET_SCHEMA_REJECTED",
                "source": source,
                "company_id": doc.get("company_id"),
                "ticket_id": doc.get("id") or doc.get("payment_id"),
                "rejections": rejections,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    # Writes — interceptados
    async def insert_one(self, document, *args, **kwargs):
        from services.ticket_schema import (  # noqa: PLC0415
            detect_rejections, is_terminal_orphan, normalize_ticket_payload,
        )
        if isinstance(document, dict):
            # P0 CTO 11/06/2026: REJEITAR órfãos terminais (sem client_snapshot.name
            # E sem qualquer ref de cliente) — esses só geravam fantasmas na SALA.
            if is_terminal_orphan(document):
                await self._emit_rejected(
                    "insert_one_blocked",
                    document,
                    [{"field": "client_snapshot.name",
                      "value": None,
                      "reason": "terminal_orphan_blocked",
                      "doc_id": document.get("id"),
                      "origin": document.get("origin"),
                      "type": document.get("type")}],
                )
                # Não grava — retorna um stub com inserted_id None
                class _Stub:  # noqa: D106
                    inserted_id = None
                return _Stub()
            rej = detect_rejections(document)
            normalize_ticket_payload(document)
            if rej:
                await self._emit_rejected("insert_one", document, rej)
        return await self._raw.insert_one(document, *args, **kwargs)

    async def insert_many(self, documents, *args, **kwargs):
        from services.ticket_schema import (  # noqa: PLC0415
            detect_rejections, is_terminal_orphan, normalize_ticket_payload,
        )
        if documents:
            filtered = []
            for d in documents:
                if isinstance(d, dict):
                    if is_terminal_orphan(d):
                        await self._emit_rejected(
                            "insert_many_blocked", d,
                            [{"field": "client_snapshot.name",
                              "value": None,
                              "reason": "terminal_orphan_blocked"}],
                        )
                        continue
                    rej = detect_rejections(d)
                    normalize_ticket_payload(d)
                    if rej:
                        await self._emit_rejected("insert_many", d, rej)
                filtered.append(d)
            documents = filtered
        if not documents:
            class _Stub:  # noqa: D106
                inserted_ids = []
            return _Stub()
        return await self._raw.insert_many(documents, *args, **kwargs)

    async def update_one(self, filter_, update, *args, **kwargs):
        from services.ticket_schema import (  # noqa: PLC0415
            detect_rejections, normalize_update_doc,
        )
        if isinstance(update, dict):
            target = update.get("$set") or update
            if isinstance(target, dict):
                rej = detect_rejections(target)
                if rej:
                    await self._emit_rejected(
                        "update_one", {**filter_, **target}, rej,
                    )
            normalize_update_doc(update)
        return await self._raw.update_one(filter_, update, *args, **kwargs)

    async def update_many(self, filter_, update, *args, **kwargs):
        from services.ticket_schema import (  # noqa: PLC0415
            detect_rejections, normalize_update_doc,
        )
        if isinstance(update, dict):
            target = update.get("$set") or update
            if isinstance(target, dict):
                rej = detect_rejections(target)
                if rej:
                    await self._emit_rejected(
                        "update_many", {**filter_, **target}, rej,
                    )
            normalize_update_doc(update)
        return await self._raw.update_many(filter_, update, *args, **kwargs)

    async def find_one_and_update(self, filter_, update, *args, **kwargs):
        from services.ticket_schema import normalize_update_doc  # noqa: PLC0415
        if isinstance(update, dict):
            normalize_update_doc(update)
        return await self._raw.find_one_and_update(filter_, update, *args, **kwargs)

    async def replace_one(self, filter_, replacement, *args, **kwargs):
        from services.ticket_schema import normalize_ticket_payload  # noqa: PLC0415
        if isinstance(replacement, dict):
            normalize_ticket_payload(replacement)
        return await self._raw.replace_one(filter_, replacement, *args, **kwargs)


class _DbGuardedProxy:
    """Proxy sobre o database — intercepta acesso à coleção 'tickets'."""

    def __init__(self, raw_db):
        self._raw = raw_db
        self._tickets_guard = _TicketsGuard(raw_db["tickets"], raw_db)

    @property
    def tickets(self):
        return self._tickets_guard

    def __getitem__(self, name):
        if name == "tickets":
            return self._tickets_guard
        return self._raw[name]

    def __getattr__(self, name):
        if name == "tickets":
            return self._tickets_guard
        return getattr(self._raw, name)


db = _DbGuardedProxy(_raw_db)
