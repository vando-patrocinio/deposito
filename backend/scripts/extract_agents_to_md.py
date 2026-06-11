"""
EXTRACT AGENTS → MD (governança Git, P0 ordem do CTO 11/06/2026)

Para cada agente em aihub_agents (co-demo), grava o conteúdo
"core" (sem o bundle de humanização) como prompts/<slug>_v1.md.

NÃO sobrescreve isabella_v12.md (já versionada).
NÃO inclui o agente "Teste" (sandbox).

Saída: arquivos .md + tabela de slugs/versões para colar no
prompt_loader.AGENT_PROMPTS.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import unicodedata

sys.path.insert(0, "/app/backend")

from database import db
from services.humanization_blocks import BLOCK_END, BLOCK_START

PROMPTS_DIR = "/app/backend/prompts"
SKIP_NAMES = {"Isabella", "Teste"}


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n


def strip_block(text: str) -> str:
    pat = re.compile(
        rf"{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}\s*",
        re.DOTALL,
    )
    return pat.sub("", text or "").strip()


HEADER_TPL = """# {label} — Prompt Canônico V1

> **Fonte de verdade do prompt.** Versionado no GitHub.
> Cada `git push` desta pasta sobrescreve o `system_prompt` no
> `aihub_agents.{label}` na próxima boot do backend
> ou via endpoint `POST /api/aihub/prompts/{label}/reload-prompt`.
>
> Bundle de humanização (DIRECT-FIRST / ANTI-SLOP / etc.) é
> aplicado automaticamente pelo `prompt_loader.apply()` ao salvar.
> NÃO inclua os marcadores `HUMANIZATION_BLOCKS_V1_*` aqui.

"""


async def main():
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    rows = []
    async for a in db.aihub_agents.find(
        {"company_id": "co-demo"},
        {"_id": 0, "name": 1, "system_prompt": 1},
    ):
        name = a["name"]
        if name in SKIP_NAMES:
            continue
        slug = slugify(name)
        fname = f"{slug}_v1.md"
        path = os.path.join(PROMPTS_DIR, fname)
        if os.path.exists(path):
            print(f"⏭  {name}: já existe ({fname})")
            rows.append((name, fname, "V1"))
            continue
        core = strip_block(a.get("system_prompt") or "")
        if not core:
            print(f"⚠  {name}: prompt vazio, pulando.")
            continue
        body = HEADER_TPL.format(label=name) + core + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        rows.append((name, fname, "V1"))
        print(f"✓  {name} → {fname} ({len(core)} chars)")

    print("\n=== AGENT_PROMPTS sugerido ===")
    for name, fname, ver in rows:
        print(
            f'    {{"agent_name": "{name}", '
            f'"file": "{fname}", "version": "{ver}"}},'
        )


if __name__ == "__main__":
    asyncio.run(main())
