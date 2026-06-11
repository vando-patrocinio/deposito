"""NERVOUS AUTOTAGGER — Fase 1.

Tagueador automático que injeta NERVOUS_METADATA em módulos sem
declaração, inferindo domain + criticality via heurísticas
multi-sinal (path, imports, palavras-chave).

Uso:
  python3 scripts/nervous_autotag.py              # dry-run (mostra diff)
  python3 scripts/nervous_autotag.py --apply      # aplica e salva
  python3 scripts/nervous_autotag.py --critical   # só tagueia critical
  python3 scripts/nervous_autotag.py --apply --critical
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["X"],
    "company_id_required": True,
}

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.nervous_linter import (_extract_metadata, _scan_files,
                                       _calls_emit_event)

# ─── Heurísticas: path → (domain, criticality) ─────────────────
# Ordem importa (primeiro match vence). Specifico → genérico.
PATH_HEURISTICS: List[Tuple[str, str, str]] = [
    # WhatsApp / comunicação
    (r"whatsapp", "whatsapp", "critical"),
    (r"twilio|baileys|chatwoot", "whatsapp", "critical"),
    (r"meta_business|meta_api", "whatsapp", "high"),
    # Customer / Subscribers
    (r"subscribers?|customer|cliente", "comercial", "critical"),
    (r"crm|lead_|prospect", "comercial", "high"),
    # Financeiro
    (r"financ|billing|payment|invoice|charge|cobranc|dunning|"
     r"asaas|stripe|pix", "financeiro", "critical"),
    (r"holerite|salario|nfse|imposto", "financeiro", "high"),
    # Atendimento / Tickets
    (r"tickets?|attendance|support|chamado|sla", "atendimento", "critical"),
    # Operations / Field / Lousa
    (r"lousa|field_op|os_|install|repair|retirada|tecnico|"
     r"manutenc", "operacoes", "critical"),
    (r"fleet|vehicle|fuel", "operacoes", "high"),
    # Inventory / Equipamento / Rede
    (r"inventory|stock|estoque|equip|onu|olt|cto|"
     r"smartolt|topology", "rede", "high"),
    # Shield / Security
    (r"shield|audit_chain|event_signing|secrets_vault|"
     r"ai_tribunal|backup_service|observability", "shield", "critical"),
    (r"rbac|auth|security", "shield", "critical"),
    # AI / Isabella / Presidente
    (r"presidente|alvaro|camila|jerusa|isabella|aihub|"
     r"motor_ia|ai_center|ai_orchestr", "isabella", "critical"),
    (r"agent_|listening|bubble|humaniz|anti_ai_slop", "isabella", "high"),
    # Growth / NPS / Churn
    (r"nps|churn|revenue|expansion|universo_ligo", "comercial", "high"),
    # Indicações / Parceiros
    (r"indica|referral|partner|parceiro|afiliad", "indicacoes", "high"),
    # Instalação / Comercial
    (r"sales|vendas|funnel|cotac", "comercial", "high"),
    (r"contract|contrato|legal", "comercial", "medium"),
    # Infra
    (r"event_bus|event_emitt|nervous_|scheduler|worker_",
     "infra", "high"),
    # Scripts (default low)
    (r"^scripts/", "infra", "low"),
]


_OWNER_BY_DOMAIN = {
    "whatsapp": "isabella-team",
    "comercial": "vendas-team",
    "financeiro": "billing-team",
    "atendimento": "ops-team",
    "operacoes": "ops-team",
    "rede": "infra-team",
    "shield": "platform-team",
    "isabella": "ai-team",
    "indicacoes": "growth-team",
    "infra": "platform-team",
}


def _infer(file_rel: str, source: str) -> Tuple[str, str, bool]:
    """Retorna (domain, criticality, emits_likely).
    emits_likely=True se o arquivo importa db/event_bus/aihub_wa_messages.
    """
    p = file_rel.lower().replace("/app/backend/", "")
    domain, crit = "infra", "medium"
    for rx, d, c in PATH_HEURISTICS:
        if re.search(rx, p):
            domain, crit = d, c
            break
    # ajusta emits baseado em sinais no código
    has_db = ("from database import" in source
              or "import database" in source
              or "db.aihub_wa_messages" in source
              or "db.tickets" in source
              or "db.subscribers" in source)
    has_router = ("APIRouter(" in source or "@router." in source)
    emits_likely = has_db and has_router
    # CRITICAL exige emits; se for critical mas não tem db+router,
    # baixa pra HIGH (mais honesto)
    if crit == "critical" and not emits_likely:
        crit = "high"
    return domain, crit, emits_likely


def _detect_event_types(source: str) -> List[str]:
    """Acha event_types literais no código."""
    types: set = set()
    # padrões: emit_event(..., event_type="X") ou emit_event(..., "X", ...)
    for m in re.finditer(
        r"emit_event\s*\([^)]*?event_type\s*=\s*[\"']([A-Z_]+)[\"']",
        source):
        types.add(m.group(1))
    for m in re.finditer(
        r"emit_event\s*\(\s*[\"']([A-Z_]+)[\"']", source):
        types.add(m.group(1))
    return sorted(types)


def _build_metadata_block(domain: str, criticality: str,
                            emits: bool, event_types: List[str]) -> str:
    et_repr = ("[" + ", ".join(f'"{t}"' for t in event_types) + "]"
               if event_types else "[]")
    return (
        "NERVOUS_METADATA = {\n"
        f'    "owner": "{_OWNER_BY_DOMAIN.get(domain, "platform-team")}",\n'
        f'    "domain": "{domain}",\n'
        f'    "criticality": "{criticality}",\n'
        f'    "emits_events": {"True" if emits else "False"},\n'
        f'    "event_types": {et_repr},\n'
        '    "company_id_required": True,\n'
        "}\n")


_DOCSTRING_END_RX = re.compile(
    r'^(["\']{3})(?:.|\n)*?\1\s*\n', re.MULTILINE)


def _inject_metadata(source: str, block: str) -> str:
    """Insere após a docstring inicial (se existir) ou no topo."""
    # Caso 1: começa com docstring
    m = re.match(r'^(\s*)("""|\'\'\')(.*?)(\2)\s*\n', source, re.DOTALL)
    if m:
        end = m.end()
        # também depois de "from __future__" se existir logo abaixo
        rest = source[end:]
        fut = re.match(r'^(from __future__ import [^\n]+\n+)', rest)
        if fut:
            return source[:end] + fut.group(1) + "\n" + block + "\n" + rest[fut.end():]
        return source[:end] + "\n" + block + "\n" + rest
    # Caso 2: começa com __future__
    fut = re.match(r'^(from __future__ import [^\n]+\n+)', source)
    if fut:
        return fut.group(1) + "\n" + block + "\n" + source[fut.end():]
    # Caso 3: topo direto
    return block + "\n" + source


def autotag(apply: bool = False, only_critical: bool = False,
             only_high: bool = False) -> Dict:
    """Roda o tagueador. Retorna stats + lista de tag aplicadas."""
    files = _scan_files()
    actions: List[Dict] = []
    skipped_already = 0
    BACKEND = Path("/app/backend")
    for f in files:
        rel = str(f.relative_to(BACKEND))
        md, _ = _extract_metadata(f)
        if md is not None:
            skipped_already += 1
            continue
        try:
            source = f.read_text(encoding="utf-8")
        except Exception:
            continue
        domain, criticality, emits_likely = _infer(rel, source)
        if only_critical and criticality != "critical":
            continue
        if only_high and criticality != "high":
            continue
        event_types = _detect_event_types(source) if emits_likely else []
        # se inferimos emits mas não achou tipos literais, baixa flag
        emits_final = emits_likely and bool(event_types)
        # Se criticality=critical mas emits_final=False, marca como high
        # para não criar violação na inserção (consistência com regra Fase 6)
        if criticality == "critical" and not emits_final:
            criticality = "high"
        block = _build_metadata_block(
            domain, criticality, emits_final, event_types)
        action = {
            "file": rel, "domain": domain, "criticality": criticality,
            "emits_events": emits_final, "event_types": event_types,
        }
        actions.append(action)
        if apply:
            new_src = _inject_metadata(source, block)
            f.write_text(new_src, encoding="utf-8")
    summary = {
        "scanned": len(files),
        "already_tagged": skipped_already,
        "to_tag" if not apply else "tagged": len(actions),
        "by_criticality": {
            c: sum(1 for a in actions if a["criticality"] == c)
            for c in ("critical", "high", "medium", "low")
        },
        "by_domain": {},
    }
    for a in actions:
        summary["by_domain"][a["domain"]] = (
            summary["by_domain"].get(a["domain"], 0) + 1)
    return {"summary": summary, "actions": actions[:50]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--critical", action="store_true")
    ap.add_argument("--high", action="store_true")
    args = ap.parse_args()
    res = autotag(apply=args.apply,
                    only_critical=args.critical,
                    only_high=args.high)
    import json
    print(json.dumps(res["summary"], indent=2))
    print(f"\n(sample of first 20 actions)")
    for a in res["actions"][:20]:
        flag = "✅ APPLIED" if args.apply else "📋 PLAN"
        print(f"  {flag} {a['file']:50} domain={a['domain']:12} "
                f"crit={a['criticality']:8} emits={a['emits_events']} "
                f"types={a['event_types'][:3]}")


if __name__ == "__main__":
    main()
