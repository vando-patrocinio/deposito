"""ISABELLA EXECUTIVE MEMORY — políticas e diretrizes do CTO/Conselho.

A Isabella registra TODA decisão estratégica (dismiss com motivo, approve
com nota, comando explícito do CTO) e converte padrões repetidos em
**políticas auditáveis**:

  • policy.scope = global | empresa | kind | subkind | playbook | target
  • policy.action = block | prefer | avoid | cap_amount | allow_only
  • policy.condition = dict serializado (ex: {"discount_pct": {"$gt": 50}})
  • policy.decided_by = email/id
  • policy.reason = texto curto
  • policy.created_at + auto_expires_at (opcional)

A Isabella consulta as policies antes de SUGERIR. Se o playbook violar a
policy → não sugere (ou suprime score).
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.isabella_memory")

VALID_ACTIONS = ("block", "prefer", "avoid", "cap_amount", "allow_only")
VALID_SCOPES = ("global", "kind", "subkind", "playbook", "target")
DISMISS_LEARN_THRESHOLD = 3  # 3 dismisses iguais → política sugerida


def _now():
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes() -> None:
    try:
        await db.isabella_executive_policies.create_index(
            [("company_id", 1), ("scope", 1), ("action", 1)])
        await db.isabella_executive_policies.create_index(
            [("company_id", 1), ("active", 1), ("created_at", -1)])
    except Exception as e:  # noqa
        log.warning("[memory] ensure_indexes: %s", e)


async def add_policy(*, company_id: str,
                       scope: str,
                       action: str,
                       condition: Dict[str, Any],
                       decided_by: str,
                       reason: str,
                       kind: Optional[str] = None,
                       subkind: Optional[str] = None,
                       playbook: Optional[str] = None,
                       expires_at: Optional[str] = None) -> Dict[str, Any]:
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope inválido: {scope}")
    if action not in VALID_ACTIONS:
        raise ValueError(f"action inválido: {action}")
    doc = {
        "id": f"pol-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "scope": scope, "action": action,
        "kind": kind, "subkind": subkind, "playbook": playbook,
        "condition": condition or {},
        "decided_by": decided_by, "reason": reason,
        "active": True,
        "expires_at": expires_at,
        "created_at": _now(), "updated_at": _now(),
    }
    await db.isabella_executive_policies.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def list_policies(company_id: str, *,
                          only_active: bool = True
                          ) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if only_active:
        q["active"] = True
    return await db.isabella_executive_policies.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)


async def deactivate(company_id: str, policy_id: str,
                       actor: str) -> Optional[Dict[str, Any]]:
    r = await db.isabella_executive_policies.update_one(
        {"id": policy_id, "company_id": company_id},
        {"$set": {"active": False, "deactivated_by": actor,
                   "deactivated_at": _now()}})
    if not r.modified_count:
        return None
    return await db.isabella_executive_policies.find_one(
        {"id": policy_id, "company_id": company_id}, {"_id": 0})


def _opp_violates_policy(opp: Dict[str, Any],
                          policy: Dict[str, Any]) -> bool:
    """Verifica se uma oportunidade casa com o filtro da policy."""
    scope = policy["scope"]
    if scope == "global":
        match = True
    elif scope == "kind":
        match = opp.get("kind") == policy.get("kind")
    elif scope == "subkind":
        match = (opp.get("kind") == policy.get("kind")
                  and opp.get("subkind") == policy.get("subkind"))
    elif scope == "playbook":
        playbook = (opp.get("recommended_action") or {}).get("playbook") \
            or (opp.get("recommended_action") or {}).get("type")
        match = playbook == policy.get("playbook")
    elif scope == "target":
        match = (opp.get("target_type") == (policy.get("condition") or {})
                  .get("target_type")
                  and opp.get("target_id") == (policy.get("condition") or {})
                  .get("target_id"))
    else:
        match = False
    if not match:
        return False
    # avalia condition (campos do evidence)
    cond = policy.get("condition") or {}
    ev = opp.get("evidence") or {}
    rec = opp.get("recommended_action") or {}
    for field, rule in cond.items():
        if field == "target_type":
            continue
        val = ev.get(field, rec.get(field))
        if isinstance(rule, dict):
            for op, ref in rule.items():
                try:
                    if op == "$gt" and not (val is not None and val > ref):
                        return False
                    if op == "$gte" and not (val is not None and val >= ref):
                        return False
                    if op == "$lt" and not (val is not None and val < ref):
                        return False
                    if op == "$lte" and not (val is not None and val <= ref):
                        return False
                    if op == "$ne" and val == ref:
                        return False
                    if op == "$eq" and val != ref:
                        return False
                except TypeError:
                    return False
        else:
            if val != rule:
                return False
    return True


async def filter_opportunities(company_id: str,
                                  opportunities: List[Dict[str, Any]]
                                  ) -> Dict[str, Any]:
    """Aplica as policies ATIVAS sobre uma lista de oportunidades.
    Retorna {`kept`, `blocked`, `preferred`} com a justificativa."""
    policies = await list_policies(company_id, only_active=True)
    if not policies:
        return {"kept": opportunities, "blocked": [], "preferred": []}
    kept, blocked, preferred = [], [], []
    for opp in opportunities:
        decision = "keep"
        why = []
        for p in policies:
            if not _opp_violates_policy(opp, p):
                continue
            if p["action"] == "block":
                decision = "block"
                why.append(f"policy {p['id']}: {p['reason']}")
                break
            if p["action"] == "avoid":
                opp["adjusted_score"] = float(opp.get("score") or 0) * 0.5
                why.append(f"avoid: {p['reason']}")
            if p["action"] == "prefer":
                opp["adjusted_score"] = float(opp.get("score") or 0) * 1.4
                why.append(f"prefer: {p['reason']}")
                decision = "prefer"
        opp["policy_decision"] = decision
        opp["policy_why"] = why
        if decision == "block":
            blocked.append(opp)
        elif decision == "prefer":
            preferred.append(opp)
            kept.append(opp)
        else:
            kept.append(opp)
    return {"kept": kept, "blocked": blocked, "preferred": preferred}


async def learn_from_dismissals(company_id: str,
                                  *, days: int = 30,
                                  threshold: int = DISMISS_LEARN_THRESHOLD
                                  ) -> List[Dict[str, Any]]:
    """Detecta padrões em dismisses recentes — sugere políticas (não cria).

    Padrão = (kind, subkind, playbook, dismiss_notes lowercase canonizado)
    repetido `threshold+` vezes em janela.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=days)).isoformat()
    docs = await db.isabella_commander_opportunities.find(
        {"company_id": company_id, "status": "dismissed",
         "dismissed_at": {"$gte": cutoff}},
        {"_id": 0, "kind": 1, "subkind": 1, "recommended_action": 1,
         "dismiss_notes": 1}).to_list(5000)
    counter: Counter = Counter()
    for d in docs:
        kind = d.get("kind") or ""
        sub = d.get("subkind") or ""
        pb = (d.get("recommended_action") or {}).get("playbook") \
            or (d.get("recommended_action") or {}).get("type") or ""
        note = (d.get("dismiss_notes") or "").strip().lower()[:80]
        counter[(kind, sub, pb, note)] += 1
    suggestions: List[Dict[str, Any]] = []
    for (k, sub, pb, note), n in counter.items():
        if n < threshold:
            continue
        suggestions.append({
            "scope": "playbook" if pb else "subkind",
            "action": "avoid",
            "kind": k, "subkind": sub, "playbook": pb,
            "reason": (f"{n}x dismissed em {days}d"
                        + (f" — motivo: '{note}'" if note else "")),
            "occurrences": n,
        })
    suggestions.sort(key=lambda s: s["occurrences"], reverse=True)
    return suggestions
