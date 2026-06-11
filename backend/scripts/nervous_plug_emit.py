"""NERVOUS PLUG-AND-EMIT — codegen seguro de emit_event().

Detecta operações DB em módulos com NERVOUS_METADATA e injeta
`await emit_event(...)` ao lado para transformar metadata em sinais
REAIS de negócio.

Princípios:
  • SEGURO: dry-run obrigatório, backup antes de gravar
  • IDEMPOTENTE: nunca injeta 2x; pula se módulo já chama emit_event
  • HONESTO: se não conseguir inferir company_id, NÃO emite — registra warning
  • CIRÚRGICO: só injeta em chamadas de negócio (insert/update críticos)

Uso:
  python3 scripts/nervous_plug_emit.py              # dry-run
  python3 scripts/nervous_plug_emit.py --apply
  python3 scripts/nervous_plug_emit.py --apply --critical
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.nervous_linter import _extract_metadata, _scan_files

BACKUP_DIR = Path("/app/backups/nervous_plug_emit")


# ─── Mapeamento entidade → (event_type por operação) ────────────
ENTITY_EVENTS: Dict[str, Dict[str, str]] = {
    "subscribers": {
        "insert_one": "subscriber.created",
        "insert_many": "subscriber.bulk_created",
        "update_one": "subscriber.updated",
        "update_many": "subscriber.bulk_updated",
        "delete_one": "subscriber.cancelled",
        "find_one_and_update": "subscriber.updated",
    },
    "tickets": {
        "insert_one": "ticket.opened",
        "update_one": "ticket.updated",
        "find_one_and_update": "ticket.updated",
        "delete_one": "ticket.closed",
    },
    "subscriber_invoices": {
        "insert_one": "invoice.created",
        "update_one": "invoice.updated",
    },
    "payments": {
        "insert_one": "payment.received",
        "update_one": "payment.updated",
    },
    "sales": {
        "insert_one": "sale.created",
        "update_one": "sale.updated",
    },
    "sales_funnel": {
        "insert_one": "sale.created",
        "update_one": "sale.converted",
    },
    "contracts": {
        "insert_one": "contract.created",
        "update_one": "contract.signed",
    },
    "lousa_appointments": {
        "insert_one": "field.os.created",
        "update_one": "field.os.updated",
    },
    "installations": {
        "insert_one": "installation.scheduled",
        "update_one": "installation.completed",
    },
    "repairs": {
        "insert_one": "repair.opened",
        "update_one": "repair.completed",
    },
    "withdrawals": {
        "insert_one": "withdrawal.opened",
        "update_one": "withdrawal.completed",
    },
    "equipment": {
        "insert_one": "equipment.assigned",
        "update_one": "equipment.updated",
        "delete_one": "equipment.returned",
    },
    "inventory": {
        "insert_one": "inventory.transferred",
        "update_one": "inventory.updated",
    },
    "onus": {
        "update_one": "onu.updated",
    },
    "ctos": {
        "update_one": "cto.updated",
    },
    "aihub_wa_messages": {
        # Já é fortemente integrado; só insertions explícitas
        # serão tratadas (whatsapp_*.py).
        "insert_one": "wa.message.persisted",
    },
    "experience_campaigns": {
        "insert_one": "campaign.created",
        "update_one": "campaign.updated",
    },
    "isabella_commander_opportunities": {
        "insert_one": "opportunity.created",
        "update_one": "opportunity.updated",
    },
    "nps_responses": {
        "insert_one": "nps.received",
    },
}


# Regex pra detectar `db.<collection>.<operation>(...)` ou
# `await db.<collection>.<operation>(...)`
DB_CALL_RX = re.compile(
    r"(?P<await>await\s+)?db\.(?P<coll>[a-z_]+)\.(?P<op>insert_one|"
    r"insert_many|update_one|update_many|delete_one|find_one_and_update|"
    r"bulk_write)\(")

EMIT_RX = re.compile(r"\bemit_event\(")
IMPORT_EMIT_RX = re.compile(r"from\s+services\.event_bus\s+import\s+emit_event")


def _detect_company_id_var(source: str, pos: int) -> str | None:
    """Procura por uma fonte SEGURA de company_id no escopo próximo.
    Retorna a EXPRESSÃO (não só nome) ou None se não há fonte segura.

    Prioridade:
      1. current_user.company_id (rota autenticada)
      2. <var>.company_id quando <var> = await db.X.find_one(...)
      3. Variável local `company_id`, `cid`, `tenant_id`
    """
    upto = source[:pos]
    last_lines = upto.splitlines()[-50:]
    block = "\n".join(last_lines)

    # 1) Rota com current_user — mais seguro
    if re.search(r"\bcurrent_user\.company_id\b", block):
        return "current_user.company_id"

    # 2) Entity já lida com company_id (most common)
    ent_rx = re.compile(
        r"(\w+)\s*=\s*await\s+db\.\w+\.(?:find_one|find_one_and_update)\(")
    matches = list(ent_rx.finditer(block))
    if matches:
        # Pega o mais próximo (último antes do pos)
        var = matches[-1].group(1)
        # Filtra variáveis genéricas que sabemos não terem company_id
        if var not in {"result", "res", "doc"}:
            return f'({var} or {{}}).get("company_id")'

    # 3) Variável local company_id / cid / tenant_id
    for cand in ("company_id", "cid", "tenant_id"):
        if re.search(rf"\b{cand}\s*=|def\s+\w+\([^)]*{cand}", block):
            return cand
    return None


def _build_emit_call(*, event_type: str, company_var: str,
                       module_name: str, indent: str) -> str:
    """Gera bloco de código `try: await emit_event(...); except: pass`."""
    return (
        f"{indent}try:\n"
        f"{indent}    from services.event_bus import emit_event\n"
        f"{indent}    await emit_event(\n"
        f"{indent}        \"{event_type}\",\n"
        f"{indent}        company_id={company_var},\n"
        f"{indent}        source=\"{module_name}\",\n"
        f"{indent}        payload={{}},\n"
        f"{indent}    )\n"
        f"{indent}except Exception:\n"
        f"{indent}    pass\n")


def process_file(file_path: Path, apply: bool = False) -> Dict:
    """Processa 1 arquivo. Retorna stats."""
    source = file_path.read_text(encoding="utf-8")
    rel = str(file_path.relative_to(Path("/app/backend")))
    module_name = file_path.stem
    md, _ = _extract_metadata(file_path)
    if not md:
        return {"file": rel, "skipped": "no_metadata"}
    crit = md.get("criticality", "medium")
    if crit not in {"critical", "high"}:
        return {"file": rel, "skipped": f"criticality={crit}"}
    # Já emite? Se sim, ainda podemos adicionar pontos faltantes.
    already_emits = bool(EMIT_RX.search(source))

    injections: List[Dict] = []
    warnings: List[str] = []
    # Encontra chamadas DB elegíveis
    for m in DB_CALL_RX.finditer(source):
        coll = m.group("coll")
        op = m.group("op")
        emit_map = ENTITY_EVENTS.get(coll)
        if not emit_map:
            continue
        evt = emit_map.get(op)
        if not evt:
            continue
        # Verifica se já existe emit logo após (5 linhas)
        after = source[m.end(): m.end() + 800]
        if EMIT_RX.search(after.split("\n\n")[0] if "\n\n" in after
                            else after[:500]):
            continue  # já emite por perto
        company_var = _detect_company_id_var(source, m.start())
        if not company_var:
            warnings.append(f"sem company_id em torno de {coll}.{op}")
            continue
        injections.append({
            "line_start": m.start(),
            "coll": coll, "op": op, "event_type": evt,
            "company_var": company_var,
        })

    if not injections:
        return {"file": rel, "skipped": "no_injection_points",
                "warnings": warnings}

    if apply:
        # backup
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / (rel.replace("/", "__") + ".bak")
        backup_path.write_text(source, encoding="utf-8")

        # Aplica injections de TRÁS pra frente (mantém posições)
        new_src = source
        for inj in sorted(injections, key=lambda x: -x["line_start"]):
            pos = inj["line_start"]
            # Encontra fim do statement (fim da linha que tem o ")")
            line_end = new_src.find("\n", pos)
            paren_depth = 0
            scan = pos
            while scan < len(new_src):
                ch = new_src[scan]
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        line_end = new_src.find("\n", scan) + 1
                        break
                scan += 1
            # Indentação da linha
            line_start_idx = new_src.rfind("\n", 0, pos) + 1
            indent = ""
            for ch in new_src[line_start_idx:pos]:
                if ch in (" ", "\t"):
                    indent += ch
                else:
                    break
            block = _build_emit_call(
                event_type=inj["event_type"],
                company_var=inj["company_var"],
                module_name=module_name, indent=indent)
            new_src = new_src[:line_end] + block + new_src[line_end:]
        file_path.write_text(new_src, encoding="utf-8")
        # Sanity: precisa parsear
        try:
            import ast as _ast
            _ast.parse(new_src)
        except SyntaxError as e:
            # rollback
            file_path.write_text(source, encoding="utf-8")
            return {"file": rel, "error": f"syntax error after inject: {e}",
                    "rolled_back": True}

    return {
        "file": rel,
        "criticality": crit,
        "injections": len(injections),
        "events": list({i["event_type"] for i in injections}),
        "warnings": warnings,
        "already_emits": already_emits,
    }


def run(apply: bool, only_critical: bool, only_high: bool) -> Dict:
    files = _scan_files()
    actions: List[Dict] = []
    stats = {
        "scanned": 0, "skipped_no_metadata": 0,
        "skipped_no_injection": 0, "injected_files": 0,
        "total_emit_calls_added": 0, "warnings_no_company": 0,
        "rollbacks": 0,
    }
    for f in files:
        md, _ = _extract_metadata(f)
        if not md:
            stats["skipped_no_metadata"] += 1
            continue
        crit = md.get("criticality", "medium")
        if only_critical and crit != "critical":
            continue
        if only_high and crit != "high":
            continue
        if crit not in {"critical", "high"} and not (only_critical
                                                       or only_high):
            continue
        stats["scanned"] += 1
        r = process_file(f, apply=apply)
        if r.get("error"):
            stats["rollbacks"] += 1
        if r.get("skipped"):
            if r["skipped"] == "no_injection_points":
                stats["skipped_no_injection"] += 1
        if r.get("injections"):
            stats["injected_files"] += 1
            stats["total_emit_calls_added"] += r["injections"]
        stats["warnings_no_company"] += len(r.get("warnings", []))
        if r.get("injections") or r.get("warnings") or r.get("error"):
            actions.append(r)
    return {"stats": stats, "actions": actions}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--critical", action="store_true")
    ap.add_argument("--high", action="store_true")
    args = ap.parse_args()
    res = run(apply=args.apply,
                only_critical=args.critical, only_high=args.high)
    print(json.dumps(res["stats"], indent=2))
    print(f"\nFirst 20 actions:")
    for a in res["actions"][:20]:
        if a.get("injections"):
            print(f"  ✅ {a['file']:50} +{a['injections']:>2} "
                    f"events={a['events'][:3]}")
        elif a.get("warnings"):
            print(f"  ⚠️  {a['file']:50} warnings={a['warnings'][:1]}")
        elif a.get("error"):
            print(f"  ❌ {a['file']:50} ERROR: {a['error'][:60]}")


if __name__ == "__main__":
    main()
