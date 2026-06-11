"""COMPANY_ID PROPAGATION ANALYZER — Fase 1.

Auditoria SEM modificar código (dry-run obrigatório por design).

Para cada warning detectado pelo plug-and-emit (db_call sem company_id
no escopo), analisa qual é a FONTE SEGURA disponível:

  A) entity.company_id    — o doc lido antes tem company_id (mais comum)
  B) current_user         — rota com Depends(get_current_user)
  C) payload.company_id   — body validado contra user (precisa RBAC check)
  D) signature missing    — função interna sem cid no def
  E) UNSAFE               — não há fonte segura → manter sem emit
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.nervous_linter import _extract_metadata, _scan_files
from scripts.nervous_plug_emit import DB_CALL_RX, ENTITY_EVENTS

BACKEND = Path("/app/backend")

CURRENT_USER_RX = re.compile(r"current_user\.company_id|user\.company_id")
ENTITY_FIND_RX = re.compile(
    r"(\w+)\s*=\s*await\s+db\.\w+\.(find_one|find_one_and_update)\(")
SIGNATURE_HAS_CID_RX = re.compile(
    r"def\s+\w+\s*\([^)]*?\b(company_id|cid|tenant_id)\b[^)]*?\)")


def _classify(source: str, db_call_pos: int) -> Dict:
    """Retorna {category, suggestion, var_name}."""
    upto = source[:db_call_pos]
    last_block = "\n".join(upto.splitlines()[-50:])

    # B) Rota com current_user
    if CURRENT_USER_RX.search(last_block):
        return {"category": "B_current_user",
                "suggestion": "current_user.company_id"}

    # A) Entity já lida com company_id (escopo próximo)
    for ent_match in ENTITY_FIND_RX.finditer(last_block):
        var = ent_match.group(1)
        # Se a entity é dict, pode ter company_id
        return {"category": "A_entity_field",
                "suggestion": f'({var} or {{}}).get("company_id")',
                "var_name": var}

    # D) Signature da função atual já tem cid?
    fn_match = re.search(
        r"^[ \t]*(async\s+)?def\s+\w+\s*\([^)]*\)",
        last_block, re.MULTILINE)
    if fn_match and SIGNATURE_HAS_CID_RX.search(fn_match.group(0)):
        match = SIGNATURE_HAS_CID_RX.search(fn_match.group(0))
        return {"category": "B_sig_has_cid",
                "suggestion": match.group(1)}

    # C) payload.company_id (precisa validação adicional)
    if "payload.company_id" in last_block or "data.company_id" in last_block:
        return {"category": "C_payload_unsafe",
                "suggestion": "REQUER VALIDAÇÃO RBAC"}

    # E) Sem fonte segura
    return {"category": "E_unsafe", "suggestion": None}


def analyze() -> Dict:
    results: List[Dict] = []
    counts = {"A_entity_field": 0, "B_current_user": 0,
                "B_sig_has_cid": 0, "C_payload_unsafe": 0,
                "E_unsafe": 0}
    for f in _scan_files():
        md, _ = _extract_metadata(f)
        if not md or md.get("criticality") not in {"critical", "high"}:
            continue
        source = f.read_text(encoding="utf-8")
        rel = str(f.relative_to(BACKEND))
        for m in DB_CALL_RX.finditer(source):
            coll = m.group("coll")
            op = m.group("op")
            if coll not in ENTITY_EVENTS:
                continue
            if op not in ENTITY_EVENTS[coll]:
                continue
            # Já emite por perto?
            after = source[m.end(): m.end() + 800]
            if re.search(r"\bemit_event\(", after[:500]):
                continue
            cls = _classify(source, m.start())
            counts[cls["category"]] = counts.get(cls["category"], 0) + 1
            if cls["category"] in {"A_entity_field", "B_current_user",
                                      "B_sig_has_cid"}:
                results.append({
                    "file": rel, "coll": coll, "op": op,
                    "category": cls["category"],
                    "fixable_suggestion": cls["suggestion"],
                })
    return {"counts": counts,
              "fixable_examples": results[:30],
              "total_fixable_safe": (counts["A_entity_field"]
                                       + counts["B_current_user"]
                                       + counts["B_sig_has_cid"])}


if __name__ == "__main__":
    res = analyze()
    print(json.dumps(res["counts"], indent=2))
    print(f"\nTOTAL FIXÁVEL COM SEGURANÇA: {res['total_fixable_safe']}")
    print(f"\nAmostras (primeiras 15):")
    for r in res["fixable_examples"][:15]:
        print(f"  [{r['category']}] {r['file']:50} "
                f"{r['coll']}.{r['op']:20} → {r['fixable_suggestion']}")
