"""NERVOUS LINTER — Fase 2 + 3 (CI/CD gate).

Varre todos os módulos Python sob /app/backend/{routes,services,scripts}
e valida que cada um:
  1. Declara NERVOUS_METADATA no topo
  2. metadata é válido (domain/criticality/emits_events coerentes)
  3. Se declara emits_events=True, REALMENTE chama emit_event no código
  4. Se chama emit_event, declara emits_events=True (consistência inversa)

Modos de saída:
  - human (default): relatório legível pra terminal
  - json: machine-readable pra Presidente IA
  - ci: exit code != 0 se houver violação CRITICAL (Fase 3 CI gate)

Uso CI gate (pre-commit / GitHub Actions):
    python3 /app/backend/scripts/nervous_linter.py --mode=ci
    echo $?  # 0 = pass, 1 = fail
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.nervous_contract import (
    DEFAULT_CRITICALITY_BY_PATH, infer_criticality, validate_dict,
)

BACKEND_ROOT = Path("/app/backend")
SCAN_DIRS = ["routes", "services", "scripts"]
EXCLUDE_FILES = {"__init__.py", "nervous_contract.py",
                  "nervous_linter.py", "nervous_autodiscovery.py",
                  "nervous_score.py", "nervous_coverage.py",
                  "nervous_coverage_v2.py", "nervous_coverage_job.py",
                  "nervous_synchronizer.py", "event_bus.py",
                  "event_emitters.py", "event_signing.py"}


def _extract_metadata(file_path: Path) -> Tuple[dict | None, str | None]:
    """Lê NERVOUS_METADATA do AST do arquivo. None se ausente.
    Retorna (metadata, error_msg)."""
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception as e:
        return None, f"parse error: {e}"
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "NERVOUS_METADATA":
                    try:
                        return ast.literal_eval(node.value), None
                    except Exception as e:
                        return None, f"NERVOUS_METADATA não é literal: {e}"
    return None, None


def _calls_emit_event(file_path: Path) -> bool:
    """Heurística rápida: o arquivo contém chamada a emit_event?"""
    try:
        src = file_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return ("emit_event(" in src or "event_bus.publish" in src
            or "publish_event(" in src)


def _scan_files() -> List[Path]:
    files: List[Path] = []
    for d in SCAN_DIRS:
        root = BACKEND_ROOT / d
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if p.name in EXCLUDE_FILES:
                continue
            files.append(p)
    return sorted(files)


def lint() -> Dict[str, Any]:
    files = _scan_files()
    violations: List[Dict[str, Any]] = []
    ok_count = 0
    silent_critical: List[str] = []
    metadata_summary: Dict[str, int] = {"declared": 0, "missing": 0}
    crit_summary: Dict[str, int] = {"critical": 0, "high": 0,
                                       "medium": 0, "low": 0}

    for f in files:
        rel = str(f.relative_to(BACKEND_ROOT))
        md, err = _extract_metadata(f)
        emits_in_code = _calls_emit_event(f)
        inferred_crit = infer_criticality(rel)

        if md is None:
            metadata_summary["missing"] += 1
            severity = ("CRITICAL" if inferred_crit == "critical"
                          else "HIGH" if inferred_crit == "high"
                          else "MEDIUM" if inferred_crit == "medium"
                          else "LOW")
            violations.append({
                "file": rel,
                "error": err or "NERVOUS_METADATA ausente",
                "inferred_criticality": inferred_crit,
                "calls_emit_in_code": emits_in_code,
                "severity": severity,
            })
            if inferred_crit == "critical":
                silent_critical.append(rel)
            continue

        metadata_summary["declared"] += 1
        errors = validate_dict(md)
        crit = md.get("criticality", "medium")
        crit_summary[crit] = crit_summary.get(crit, 0) + 1

        # Coerência: declara emite mas não chama / chama mas não declara
        if md.get("emits_events") and not emits_in_code:
            errors.append(
                "declara emits_events=True mas não chama emit_event() no código")
        if (not md.get("emits_events")) and emits_in_code and crit in {"critical", "high"}:
            errors.append(
                f"chama emit_event() mas declara emits_events=False (crit={crit})")
        if errors:
            violations.append({
                "file": rel,
                "errors": errors,
                "criticality": crit,
                "severity": "CRITICAL" if crit == "critical" else "HIGH",
            })
        else:
            ok_count += 1

    total = len(files)
    declared_pct = round(metadata_summary["declared"] / max(total, 1) * 100, 2)
    return {
        "total_files": total,
        "declared": metadata_summary["declared"],
        "missing": metadata_summary["missing"],
        "metadata_coverage_pct": declared_pct,
        "ok": ok_count,
        "violations": violations,
        "silent_critical_modules": silent_critical,
        "criticality_distribution_declared": crit_summary,
    }


def _format_human(report: Dict[str, Any]) -> str:
    lines = ["╔══════════════════════════════════════════════════════════╗",
              "║  NERVOUS LINTER — Fase 2 (auditor) + Fase 3 (CI gate)  ║",
              "╚══════════════════════════════════════════════════════════╝",
              "",
              f"  Total módulos:       {report['total_files']}",
              f"  Com metadata:        {report['declared']} "
              f"({report['metadata_coverage_pct']}%)",
              f"  SEM metadata:        {report['missing']}",
              f"  Sem violação:        {report['ok']}",
              f"  Críticos SILENTES:   {len(report['silent_critical_modules'])}",
              ""]
    if report["silent_critical_modules"]:
        lines.append("  🚨 MÓDULOS CRÍTICOS SEM METADATA:")
        for f in report["silent_critical_modules"][:20]:
            lines.append(f"     • {f}")
        if len(report["silent_critical_modules"]) > 20:
            lines.append(f"     … +{len(report['silent_critical_modules'])-20}")
        lines.append("")
    crit_v = [v for v in report["violations"] if v.get("severity") == "CRITICAL"]
    if crit_v:
        lines.append(f"  🔴 VIOLAÇÕES CRITICAL ({len(crit_v)}):")
        for v in crit_v[:15]:
            errors = v.get("errors") or [v.get("error", "?")]
            lines.append(f"     {v['file']}")
            for e in errors[:2]:
                lines.append(f"       → {e}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("human", "json", "ci"),
                       default="human")
    args = ap.parse_args()

    report = lint()
    if args.mode == "json":
        print(json.dumps(report, indent=2, default=str))
        sys.exit(0)
    if args.mode == "ci":
        critical_violations = [
            v for v in report["violations"] if v.get("severity") == "CRITICAL"]
        print(_format_human(report))
        if critical_violations:
            print(f"\n❌ CI GATE BLOQUEADO: {len(critical_violations)} "
                    "violações CRITICAL.")
            sys.exit(1)
        print("\n✅ CI GATE OK")
        sys.exit(0)
    print(_format_human(report))


if __name__ == "__main__":
    main()
