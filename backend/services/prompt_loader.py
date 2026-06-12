"""PROMPT LOADER — Fonte de verdade no GitHub.

Carrega prompts versionados de `/app/backend/prompts/*.md` e sincroniza
com o `system_prompt` em `aihub_agents`. Idempotente: só atualiza o DB
se o conteúdo do arquivo mudou.

Mapping (agente → arquivo):
  Isabella → prompts/isabella_v12.md

Como funciona:
  • Arquivo .md é a fonte. Frontmatter opcional ignorado (`> linhas`).
  • O conteúdo é embrulhado com os blocos canônicos de humanização
    (humanization_blocks.apply) antes de salvar.
  • Hash SHA-1 do arquivo é gravado em aihub_agents.prompt_source_sha
    para detectar mudança sem recomparar texto inteiro.

Triggers:
  1. Startup do backend (via lifespan).
  2. POST /api/aihub/agents/{name}/reload-prompt (endpoint admin).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Carrega prompts do GitHub (arquivos versionados).",
}

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from services import humanization_blocks as hb

log = logging.getLogger("ponto.prompt_loader")

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prompts")

# Mapeamento agente → arquivo de prompt + versão
# Toda a frota IA versionada em Git (P0 11/06/2026).
AGENT_PROMPTS: List[Dict[str, str]] = [
    {"agent_name": "Isabella",        "file": "isabella_v13.md",     "version": "V13_CICLO_COMPLETO"},
    {"agent_name": "Alvaro",          "file": "alvaro_v2.md",        "version": "V2"},
    {"agent_name": "Pâmela",          "file": "pamela_v2.md",        "version": "V2"},
    {"agent_name": "Jerusa",          "file": "jerusa_v1.md",        "version": "V1"},
    {"agent_name": "Vendas",          "file": "vendas_v1.md",        "version": "V1"},
    {"agent_name": "Orquestrador",    "file": "orquestrador_v1.md",  "version": "V1"},
    {"agent_name": "Avaliador",       "file": "avaliador_v1.md",     "version": "V1"},
    {"agent_name": "Motor IA",        "file": "motor_ia_v1.md",      "version": "V1"},
    {"agent_name": "Co-Pilot IA",     "file": "co_pilot_ia_v1.md",   "version": "V1"},
    {"agent_name": "SmartOLT AI",     "file": "smartolt_ai_v1.md",   "version": "V1"},
    {"agent_name": "Coach IA",        "file": "coach_ia_v1.md",      "version": "V1"},
    {"agent_name": "Sentinela Lousa", "file": "sentinela_lousa_v1.md","version": "V1"},
    {"agent_name": "Aprendizado",     "file": "aprendizado_v1.md",   "version": "V1"},
    {"agent_name": "Lousa Triagem",   "file": "lousa_triagem_v1.md", "version": "V1"},
    {"agent_name": "Holerite IA",     "file": "holerite_ia_v1.md",   "version": "V1"},
]


def _read_file(name: str) -> Optional[str]:
    path = os.path.join(PROMPTS_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _strip_md_quote_lines(text: str) -> str:
    """Remove `> ...` lines (citações markdown) que são metadados."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("> "):
            continue
        out.append(line)
    return "\n".join(out).strip()


async def sync_one(agent_name: str, file: str,
                       version: str,
                       company_id: str = "co-demo") -> Dict[str, Any]:
    """Sincroniza UM agente a partir do arquivo .md."""
    raw = _read_file(file)
    if raw is None:
        return {"agent": agent_name, "skipped": "file_not_found",
                "file": file}

    body = _strip_md_quote_lines(raw)
    sha = _sha1(body)
    final_prompt = hb.apply(body)

    doc = await db.aihub_agents.find_one(
        {"company_id": company_id, "name": agent_name},
        {"_id": 0, "prompt_source_sha": 1})
    current_sha = (doc or {}).get("prompt_source_sha")
    if current_sha == sha:
        return {"agent": agent_name, "action": "noop_same_sha",
                "sha": sha, "version": version}

    now = datetime.now(timezone.utc).isoformat()
    res = await db.aihub_agents.update_one(
        {"company_id": company_id, "name": agent_name},
        {"$set": {
            "system_prompt": final_prompt,
            "prompt_version": version,
            "prompt_source_file": file,
            "prompt_source_sha": sha,
            "prompt_applied_at": now,
            "updated_at": now,
            "updated_by": "prompt_loader",
        }},
        upsert=False,
    )
    log.info("[prompt_loader] sync %s ← %s (sha=%s) matched=%d",
              agent_name, file, sha[:10], res.matched_count)
    return {"agent": agent_name, "action": "updated", "sha": sha,
              "version": version, "file": file,
              "matched": res.matched_count,
              "modified": res.modified_count}


async def sync_all(company_id: str = "co-demo") -> List[Dict[str, Any]]:
    """Sincroniza todos os agentes mapeados.
    Chamado no startup do backend."""
    results = []
    for cfg in AGENT_PROMPTS:
        try:
            r = await sync_one(cfg["agent_name"], cfg["file"],
                                  cfg["version"], company_id)
            results.append(r)
        except Exception as e:
            log.exception("[prompt_loader] sync %s falhou: %s",
                            cfg["agent_name"], e)
            results.append({"agent": cfg["agent_name"],
                              "error": str(e)})
    return results
