"""kill_switch.py — Kill Switch global e por componente.

Coleção: `system_killswitch` (single doc per company_id, com fallback global).
Componentes suportados:
  - global_off: derruba TODA ação ativa do sistema (envios, schedulers críticos)
  - whatsapp_off: bloqueia toda saída WhatsApp (homologation gateway respeita)
  - ai_actions_off: bloqueia execução de ações autônomas
  - scheduler_off: pausa workers de schedulers (best-effort)

Uso (hot-path):
    from services.kill_switch import is_off
    if await is_off("whatsapp"): return {"blocked_by_killswitch": True}

Toggling (admin):
    POST /api/admin/killswitch/whatsapp  body: {"on": true, "reason": "..."}
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("kill_switch")

# Whitelist de componentes — adicionar aqui exige update em RELEASE_LOCK
COMPONENTS = ("global", "whatsapp", "ai_actions", "scheduler")
COLLECTION = "system_killswitch"
GLOBAL_KEY = "__GLOBAL__"  # doc-id para flag sistêmico (sem company)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_state(component: str = "global",
                    company_id: Optional[str] = None) -> Dict[str, Any]:
    """Retorna estado atual de um componente. Default = OFF=false."""
    if component not in COMPONENTS:
        raise ValueError(f"Componente desconhecido: {component}")
    key = company_id or GLOBAL_KEY
    doc = await db[COLLECTION].find_one(
        {"key": key, "component": component})
    if not doc:
        return {"key": key, "component": component, "off": False,
                "reason": None, "updated_at": None}
    return {"key": doc.get("key"),
            "component": doc.get("component"),
            "off": bool(doc.get("off", False)),
            "reason": doc.get("reason"),
            "updated_at": doc.get("updated_at"),
            "updated_by": doc.get("updated_by")}


async def is_off(component: str = "global",
                 company_id: Optional[str] = None) -> bool:
    """Atalho hot-path: True se desligado em qualquer nível.

    Hierarquia (qualquer um OFF derruba):
      1. Global do componente (key=__GLOBAL__, component=X)
      2. Global master (key=__GLOBAL__, component=global)
      3. Por empresa do componente (key=company_id, component=X) — só se passado
    """
    # 1+2: estados globais (sempre verificados)
    g_master = await get_state("global", None)
    if g_master["off"]:
        return True
    if component != "global":
        g_comp = await get_state(component, None)
        if g_comp["off"]:
            return True
    # 3: por empresa (só se company_id explícito)
    if company_id and component != "global":
        s = await get_state(component, company_id)
        if s["off"]:
            return True
    return False


async def set_state(component: str, off: bool,
                    reason: str = "",
                    updated_by: str = "system",
                    company_id: Optional[str] = None) -> Dict[str, Any]:
    """Liga/desliga um kill switch. Persiste auditoria."""
    if component not in COMPONENTS:
        raise ValueError(f"Componente desconhecido: {component}")
    key = company_id or GLOBAL_KEY
    doc = {
        "key": key,
        "component": component,
        "off": bool(off),
        "reason": (reason or "").strip()[:500],
        "updated_at": _now(),
        "updated_by": updated_by,
    }
    await db[COLLECTION].update_one(
        {"key": key, "component": component},
        {"$set": doc}, upsert=True)
    # Audit trail
    await db.audit_log.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "ts": _now(),
        "kind": "killswitch_toggle",
        "component": component,
        "key": key,
        "off": bool(off),
        "reason": doc["reason"],
        "actor": updated_by,
    })
    logger.warning("[killswitch] %s.%s = %s by %s reason=%r",
                   key, component, "OFF" if off else "ON", updated_by, reason)
    return doc


async def get_all_states(company_id: Optional[str] = None) -> Dict[str, Any]:
    """Snapshot de todos os componentes."""
    out = {}
    for c in COMPONENTS:
        out[c] = await get_state(c, company_id)
    return {"company_id": company_id, "states": out,
            "generated_at": _now()}
