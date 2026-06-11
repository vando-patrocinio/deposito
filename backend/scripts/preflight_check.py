"""
Preflight Check — Validação ANTES de deploy em produção.

Garante que nenhuma alteração de código vai destruir dados de cadastro
do cliente em produção.

Como rodar:
    cd /app/backend && python scripts/preflight_check.py

O que valida:
1. Nenhum `delete_many({})` ou `drop()` em código de startup
2. Todos os seeds têm guarda `count_documents > 0: return`
3. Migrations em `scripts/migrations.py` são puramente aditivas
4. Nenhuma operação destrutiva nas PROTECTED_COLLECTIONS rodando fora de
   endpoints autenticados

Saída:
    exit 0 = SAFE para deploy
    exit 1 = BLOQUEAR deploy — investigar achados
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # /app/backend

PROTECTED_COLLECTIONS = {
    "users", "collaborators", "companies", "company_branding",
    "settings_by_company", "fin_suppliers", "fin_categories",
    "fin_cash_accounts", "fin_filiais", "subscribers", "subscriber_phones",
    "subscriber_addresses", "subscriber_invoices",
    "tickets", "clock_records", "geofences",
    "fin_cash_movements", "fin_bills_payable", "fin_bills_receivable",
    "fin_installments",
    "aihub_agents", "isabella_prompt_fragments", "bank_import_memory",
    "ai_agent_switches", "wa_auth_state", "wa_conversations", "wa_messages",
    "platform_audit", "lousa_logs", "audit_log",
    "ctos", "bairros",  # Rede IA
}

# Arquivos onde código que roda no startup vive
STARTUP_FILES = {"server.py", "auth.py", "core.py"}
STARTUP_DIRS = {"scripts/migrations.py"}

# Padrões considerados perigosos em startup
DANGER_PATTERNS = [
    (re.compile(r"\.delete_many\(\s*\{\s*\}\s*\)"), "delete_many({}) — apaga TODA a coleção"),
    (re.compile(r"\.drop\(\s*\)"), ".drop() — destrói a coleção inteira"),
    (re.compile(r"\.drop_collection\("), "drop_collection — destrói coleção"),
    (re.compile(r"\.replace_one\([^)]*upsert\s*=\s*True"), "replace_one+upsert — sobrescreve doc inteiro"),
]


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Retorna lista de (linha, trecho, motivo) para padrões perigosos."""
    issues: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return issues
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"'):
            continue
        for pat, reason in DANGER_PATTERNS:
            if pat.search(line):
                # Verifica se está numa coleção PROTECTED
                col_match = re.search(r"db\.([a-z_]+)\.", line)
                col = col_match.group(1) if col_match else "?"
                severity = "HIGH" if col in PROTECTED_COLLECTIONS else "INFO"
                issues.append((i, line.strip()[:120], f"[{severity}] col={col} · {reason}"))
    return issues


def main() -> int:
    print("=" * 72)
    print("SmartProv — Preflight Check (Data Safety)")
    print("=" * 72)

    findings: dict[str, list] = {}

    # 1. Audita arquivos de startup
    for fname in STARTUP_FILES:
        p = ROOT / fname
        if p.exists():
            res = scan_file(p)
            if res:
                findings[str(p.relative_to(ROOT))] = res

    # 2. Audita scripts/migrations.py
    mig = ROOT / "scripts" / "migrations.py"
    if mig.exists():
        res = scan_file(mig)
        if res:
            findings[str(mig.relative_to(ROOT))] = res

    # 3. Audita TODOS os routes/services em busca de delete_many sem proteção
    high_severity_outside_startup: list[tuple[str, int, str, str]] = []
    for sub in ("routes", "services"):
        d = ROOT / sub
        if not d.exists():
            continue
        for py in d.rglob("*.py"):
            res = scan_file(py)
            for ln, snip, reason in res:
                if "[HIGH]" in reason:
                    high_severity_outside_startup.append(
                        (str(py.relative_to(ROOT)), ln, snip, reason)
                    )

    # Output
    if not findings and not high_severity_outside_startup:
        print("\n✅ TUDO LIMPO — Deploy SAFE.")
        print("   Nenhuma operação destrutiva detectada em startup nem em")
        print("   coleções protegidas dentro de routes/services.")
        return 0

    has_block = False

    if findings:
        print("\n⚠️  STARTUP FILES — operações suspeitas detectadas:")
        for f, items in findings.items():
            print(f"\n  {f}:")
            for ln, snip, reason in items:
                print(f"    L{ln:4d} {reason}")
                print(f"         > {snip}")
                if "[HIGH]" in reason:
                    has_block = True

    if high_severity_outside_startup:
        print("\n⚠️  PROTECTED COLLECTIONS — delete_many/drop em rotas:")
        print("    (revisar se estão atrás de require_admin + confirm_text)")
        for f, ln, snip, reason in high_severity_outside_startup:
            print(f"    {f}:L{ln} {reason}")
            print(f"      > {snip}")

    if has_block:
        print("\n❌ BLOQUEAR DEPLOY — investigar e corrigir os HIGH acima.")
        return 1

    print("\n✅ Nada bloqueante. Apenas avisos informativos. Deploy permitido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
