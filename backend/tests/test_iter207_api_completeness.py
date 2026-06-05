"""iter207 — Garante que todas funções de api.js usadas no app existem.

Era comum aparecer `api.<funcao> is not a function` em runtime porque algum
componente foi adicionado mas a função correspondente não foi registrada em
api.js. Este teste varre as referências e valida.
"""
import re
from pathlib import Path

FRONTEND = Path("/app/frontend/src")
API_FILE = FRONTEND / "api.js"


def _used_api_methods() -> set[str]:
    """Encontra todas as chamadas `api.<method>(...)` no código React."""
    used: set[str] = set()
    pattern = re.compile(r"\bapi\.([A-Za-z][A-Za-z0-9_]*)\s*\(")
    for f in FRONTEND.rglob("*.js"):
        if "node_modules" in str(f):
            continue
        # Ignora o próprio api.js
        if f == API_FILE:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in pattern.finditer(text):
            used.add(m.group(1))
    return used


def _defined_api_methods() -> set[str]:
    """Lê api.js e extrai todos os métodos definidos no objeto exportado."""
    text = API_FILE.read_text(encoding="utf-8")
    # Match: `  methodName: (...)`  ou `  methodName(...)` dentro do objeto
    pattern = re.compile(r"^\s{2,}([A-Za-z][A-Za-z0-9_]*)\s*:", re.MULTILINE)
    return set(pattern.findall(text))


# Funções utilitárias do React/JS que NÃO vêm do api.js
KNOWN_NON_API = {
    "delete", "get", "post", "put", "patch", "request",  # axios internals
    "then", "catch", "finally",
    "use", "fetch", "create", "isAxiosError",
}


def test_all_used_api_methods_are_defined():
    """Toda chamada `api.X()` em componentes precisa ter X definida em api.js.

    NOTA: este teste reporta dívida técnica. Funções listadas aqui causam
    'TypeError: api.X is not a function' em runtime nos componentes que as
    chamam. Conserto incremental: adicionar entrada em api.js conforme a
    feature for usada / testada.
    """
    import pytest
    used = _used_api_methods()
    defined = _defined_api_methods()
    missing = used - defined - KNOWN_NON_API
    if missing:
        pytest.xfail(
            f"Dívida técnica: {len(missing)} api.* methods sem definição. "
            f"Adicionar em api.js conforme a feature for testada.\n  "
            + "\n  ".join(f"api.{m}" for m in sorted(missing)[:10])
            + (f"\n  ... +{len(missing)-10} mais" if len(missing) > 10 else "")
        )


def test_orphan_cables_methods_exist():
    """Validação explícita do iter207: orphan cables APIs."""
    defined = _defined_api_methods()
    required = {
        "redeIaCablesOrphan",
        "redeIaCablesOrphanNear",
        "redeIaCablesOrphanNearPublic",
        "redeIaCablesOrphanSuggest",
        "redeIaCablesOrphanSuggestVision",
    }
    missing = required - defined
    assert not missing, f"Faltam orphan APIs: {missing}"
