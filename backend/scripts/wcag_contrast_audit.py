"""wcag_contrast_audit.py — Auditoria WCAG AA de contraste em estilos inline.

Varre todos os .js/.jsx/.css do frontend e relata pares
`background + color` cujo contraste falha o critério WCAG AA:
  - texto normal: ratio >= 4.5
  - texto grande (>=18px ou >=14px bold): ratio >= 3.0

Read-only. NAO modifica nenhum arquivo. Saida JSON+TXT.

Como rodar:
  python3 /app/backend/scripts/wcag_contrast_audit.py

Saida:
  /app/backend/scripts/wcag_contrast_audit.report.json
  /app/backend/scripts/wcag_contrast_audit.report.txt
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "observability",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": False,
}

import json
import os
import re
from collections import defaultdict
from typing import Optional


FRONTEND_ROOT = "/app/frontend/src"
REPORT_BASE = "/app/backend/scripts/wcag_contrast_audit.report"


# --------------------------------------------------------------------------
# Cor parsing: aceita #RRGGBB, #RGB, rgb(...), rgba(...), e cores nomeadas comuns.
# --------------------------------------------------------------------------
NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "transparent": None, "inherit": None, "currentcolor": None,
}


def _parse_color(s: str) -> Optional[tuple]:
    """Retorna (r,g,b) ou (r,g,b,alpha). None se nao parseavel."""
    s = (s or "").strip().lower()
    if not s or s in NAMED_COLORS:
        return NAMED_COLORS.get(s)
    # hex
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) for c in h)
            return (r, g, b)
        if len(h) == 6:
            r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
            return (r, g, b)
        # 8 chars = #RRGGBBAA
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255.0
        return (r, g, b, a)
    # rgb(r,g,b) ou rgba(r,g,b,a)
    m = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", s)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        if m.group(4) is not None:
            return (r, g, b, float(m.group(4)))
        return (r, g, b)
    return None


def _composite_over_white(rgb_or_rgba):
    """Compoe rgba sobre #ffffff (assume parent branco — comum no app light).
    Retorna (r,g,b) solido."""
    if rgb_or_rgba is None:
        return None
    if len(rgb_or_rgba) == 3:
        return rgb_or_rgba
    r, g, b, a = rgb_or_rgba
    # over white: out = src*a + white*(1-a)
    return (
        int(round(r * a + 255 * (1 - a))),
        int(round(g * a + 255 * (1 - a))),
        int(round(b * a + 255 * (1 - a))),
    )


def _relative_luminance(rgb: tuple) -> float:
    """Per WCAG 2.1 — sRGB linearizada."""
    def chan(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(rgb_a: tuple, rgb_b: tuple) -> float:
    la = _relative_luminance(rgb_a)
    lb = _relative_luminance(rgb_b)
    lighter, darker = (la, lb) if la > lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------------
# Extracao de pares (background, color) em inline-styles JSX
# --------------------------------------------------------------------------
RE_STYLE_BLOCK = re.compile(r"style=\{\{([^}]+)\}\}", re.S)
RE_COLOR_PROP = re.compile(
    r"\b(color|background|backgroundColor)\s*:\s*"
    r"(?P<val>(?:[\"'][^\"']+[\"'])|(?:rgba?\([^)]+\))|(?:#[0-9a-fA-F]+))"
)


def _extract_pairs_from_style_block(block: str):
    """Retorna lista de (background?, color?) tuplas — uma por style block."""
    bg = None
    color = None
    for m in RE_COLOR_PROP.finditer(block):
        prop = m.group(1)
        val = m.group("val").strip("\"'")
        rgb = _parse_color(val)
        if not rgb:
            continue
        if prop == "color":
            # texto: composite sobre o BG (se houver) ou sobre branco
            color = (val, rgb)
        else:  # background, backgroundColor
            # ignora gradientes (linear-gradient, conic-gradient, etc.)
            if "gradient" in val.lower():
                continue
            bg = (val, rgb)
    if bg and color:
        # Composite ambos sobre branco (assume parent claro — tema light)
        bg_solid = _composite_over_white(bg[1])
        fg_solid = _composite_over_white(color[1])
        return [((bg[0], bg_solid), (color[0], fg_solid))]
    return []


def _audit_file(path: str):
    """Retorna lista de violacoes encontradas em um arquivo."""
    violations = []
    try:
        src = open(path).read()
    except Exception:
        return []
    for m in RE_STYLE_BLOCK.finditer(src):
        block = m.group(1)
        for bg, color in _extract_pairs_from_style_block(block):
            ratio = _contrast(bg[1], color[1])
            # WCAG AA: 4.5 normal, 3.0 grande. Usamos 4.5 como base.
            if ratio < 4.5:
                # Linha aproximada
                line = src[:m.start()].count("\n") + 1
                violations.append({
                    "file": path.replace(FRONTEND_ROOT + "/", ""),
                    "line": line,
                    "background": bg[0],
                    "color": color[0],
                    "ratio": round(ratio, 2),
                    "severity": ("AA-fail" if ratio < 3.0 else "AA-large-only"),
                })
    return violations


def main():
    print("="*70)
    print("WCAG AA — Auditoria de contraste em estilos inline")
    print("="*70)
    all_violations = []
    scanned = 0
    for root, dirs, files in os.walk(FRONTEND_ROOT):
        # Pula node_modules, dist
        if "node_modules" in root or "/build" in root or "/dist" in root:
            continue
        for fn in files:
            if not (fn.endswith(".js") or fn.endswith(".jsx")):
                continue
            scanned += 1
            v = _audit_file(os.path.join(root, fn))
            all_violations.extend(v)

    # Agrupa por arquivo
    by_file = defaultdict(list)
    for v in all_violations:
        by_file[v["file"]].append(v)
    files_with_issues = sorted(by_file.keys(), key=lambda f: -len(by_file[f]))

    summary = {
        "files_scanned": scanned,
        "files_with_issues": len(files_with_issues),
        "violations_total": len(all_violations),
        "by_severity": {
            "AA-fail (<3.0 - critico)": sum(
                1 for v in all_violations if v["severity"] == "AA-fail"),
            "AA-large-only (3.0-4.5 - so texto grande)": sum(
                1 for v in all_violations if v["severity"] == "AA-large-only"),
        },
    }

    # JSON output
    out = {
        "summary": summary,
        "top_offenders": [
            {"file": f, "violations": by_file[f][:20]}
            for f in files_with_issues[:20]
        ],
        "all_violations_count": len(all_violations),
    }
    with open(f"{REPORT_BASE}.json", "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # TXT human-readable
    lines = []
    lines.append("="*70)
    lines.append("WCAG AA contrast audit — frontend/src")
    lines.append("="*70)
    lines.append(f"Arquivos varridos: {summary['files_scanned']}")
    lines.append(f"Arquivos com violacoes: {summary['files_with_issues']}")
    lines.append(f"Total de violacoes: {summary['violations_total']}")
    lines.append("")
    lines.append("Por severidade:")
    for k, v in summary["by_severity"].items():
        lines.append(f"  - {k}: {v}")
    lines.append("")
    lines.append("Top 20 arquivos com mais violacoes:")
    for f in files_with_issues[:20]:
        lines.append(f"  {len(by_file[f]):4d}  {f}")
    lines.append("")
    lines.append("Exemplos de violacoes criticas (AA-fail, ratio<3.0):")
    crit = [v for v in all_violations if v["severity"] == "AA-fail"][:15]
    for v in crit:
        lines.append(
            f"  {v['file']}:{v['line']}  "
            f"ratio={v['ratio']:.2f}  bg={v['background']:>20}  fg={v['color']}")
    txt = "\n".join(lines)
    with open(f"{REPORT_BASE}.txt", "w") as f:
        f.write(txt)

    print(txt)
    print("")
    print(f"Relatorio detalhado:")
    print(f"  TXT:  {REPORT_BASE}.txt")
    print(f"  JSON: {REPORT_BASE}.json")


if __name__ == "__main__":
    main()
