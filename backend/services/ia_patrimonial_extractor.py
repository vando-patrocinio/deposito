"""IA Patrimonial · Onda 1 · Parser Narrativo (SHADOW MODE).

Mandato CEO 18/06/2026:
  • Técnico só escreve o que aconteceu. IA interpreta e converte em
    movimentação patrimonial.
  • Modelo: shadow primeiro. Ler OS finalizadas, comparar com formulário,
    medir confiança antes de ir live.

Escopo desta entrega (Onda IA-1):
  • Engine de extração (Claude Sonnet 4.5 + catálogo de aliases pt-BR)
  • Endpoint POST /api/lousa/tickets/{id}/ai-extract-materials
  • Script shadow que processa OS fechadas, compara com `completion_data`
    do formulário, gera relatório markdown.
  • ZERO writes em stok_history / movimentação. Apenas leitura + análise.

NÃO faz parte desta onda:
  • Tela "Confirma leitura" na Lousa Mobile (hold)
  • Engine de movimentação automática
  • Item discovery em produção
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db


# ─── Catálogo de aliases pt-BR ────────────────────────────────────────────
# IA é boa mas determinismo de matching ainda vale ouro. O catálogo cobre as
# expressões mais comuns do técnico de campo brasileiro de ISP FTTH.

ITEM_CATALOG: Dict[str, Dict[str, Any]] = {
    "drop": {
        "aliases": ["drop", "drop fo", "dropfo", "drop fibra", "cabo drop",
                     "drope", "dropie", "metro de drop", "metragem"],
        "unit": "m",
        "regex_qty": r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?|mt)\b",
    },
    "conector_fast": {
        "aliases": ["fast", "conector fast", "fast connector", "fasconector",
                     "conector rápido", "conector rapido", "fast sc",
                     "fast apc", "scapc fast"],
        "unit": "unidade",
        "regex_qty": r"(\d+)\s*(?:conectores?\s+)?fast",
    },
    "esticador": {
        "aliases": ["esticador", "esticadores", "esticador de drop",
                     "alça", "alca preformada", "esticador metálico",
                     "estikador"],
        "unit": "unidade",
        "regex_qty": r"(\d+)\s*esticador",
    },
    "cabo_rede": {
        "aliases": ["cabo rede", "cabo de rede", "cat5", "cat5e", "cat6",
                     "patch cord", "rj45 cabo", "cabo lan"],
        "unit": "m",
        "regex_qty": r"(\d+(?:[.,]\d+)?)\s*m(?:etros?)?\s*(?:de\s+)?(?:cabo\s+)?(?:rede|lan|cat)",
    },
    "conector_rede": {
        "aliases": ["conector rede", "rj45", "conector rj45", "rj45 macho"],
        "unit": "unidade",
        "regex_qty": r"(\d+)\s*(?:conectores?\s+)?(?:rede|rj45)",
    },
    "caixa_emenda": {
        "aliases": ["caixa de emenda", "caixa emenda", "cto", "emenda óptica",
                     "splitter box"],
        "unit": "unidade",
        "regex_qty": r"(\d+)\s*caixas?\s*(?:de\s+)?emenda",
    },
}

ITEM_NORMALIZE = {alias.lower(): item_id
                   for item_id, meta in ITEM_CATALOG.items()
                   for alias in meta["aliases"]}


# ─── Service-type classifier (palavra-chave + IA) ─────────────────────────

SERVICE_KEYWORDS: Dict[str, List[str]] = {
    "instalacao":   ["instalei", "instalação", "instalado", "instalei a onu",
                      "configurei a ont", "ativei o cliente", "primeira",
                      "instalado pela primeira vez"],
    "reparo":       ["reparei", "consertei", "refiz", "troquei o drop",
                      "limpei conector", "normalizei", "reparo",
                      "voltou a navegar", "voltou internet"],
    "retirada":     ["retirei", "retirada", "cancelamento", "desinstalei",
                      "removi a onu"],
    "troca":        ["troquei a onu", "troquei a ont", "troca de onu",
                      "ont substituída", "trocou equipamento", "swap"],
    "rompimento":   ["rompimento", "fibra rompida", "rompida", "obras",
                      "carro derrubou", "raio"],
    "preventiva":   ["preventiva", "preventivo", "manutenção preventiva",
                      "limpeza preventiva"],
}


def _classify_service_type(text: str, ticket_type_hint: Optional[str]) -> Tuple[str, float]:
    txt = (text or "").lower()
    scores: Dict[str, int] = {k: 0 for k in SERVICE_KEYWORDS}
    for st, kws in SERVICE_KEYWORDS.items():
        for kw in kws:
            if kw in txt:
                scores[st] += 1
    # Bonus: tipo do ticket original
    if ticket_type_hint and ticket_type_hint in scores:
        scores[ticket_type_hint] += 1
    top = max(scores.items(), key=lambda x: x[1])
    total = sum(scores.values())
    if total == 0:
        return (ticket_type_hint or "reparo", 0.0)
    conf = round(top[1] / max(total, 1), 2)
    return (top[0], conf)


# ─── Regex extractor (heurístico determinístico) ──────────────────────────

def _regex_extract_materials(text: str) -> List[Dict[str, Any]]:
    """Extrai materiais via regex + catálogo. Confiança média 0.75-0.95."""
    text_norm = (text or "").lower()
    out: List[Dict[str, Any]] = []
    for item_id, meta in ITEM_CATALOG.items():
        rx = meta.get("regex_qty")
        if not rx:
            continue
        # Encontra todas as ocorrências
        seen_quantities: List[float] = []
        for m in re.finditer(rx, text_norm, flags=re.IGNORECASE):
            try:
                q = float(m.group(1).replace(",", "."))
                if q > 0 and q < 10000:  # sanity bound
                    seen_quantities.append(q)
            except (ValueError, IndexError):
                continue
        # Verifica também alias-only match (sem qty explícito) — pula
        if seen_quantities:
            total_q = sum(seen_quantities)
            out.append({
                "item": item_id,
                "qty": total_q,
                "unit": meta["unit"],
                "confidence": 0.85 if len(seen_quantities) == 1 else 0.78,
                "source": "regex_catalog",
                "raw_matches": seen_quantities,
            })
    return out


# ─── SN extractor ─────────────────────────────────────────────────────────

SN_RX = re.compile(r"(?i)\b((?:HWTC|FHTT|ITBS|ZNTS|GPLT|XPON|EPON|CIGG|ALCL)[\w-]{6,18})\b")


def _extract_serials(text: str) -> List[str]:
    if not text:
        return []
    out = []
    for m in SN_RX.finditer(text):
        sn = m.group(1).upper()
        if sn not in out:
            out.append(sn)
    return out[:5]


# ─── LLM call (Claude Sonnet 4.5 via emergent llm key) ────────────────────

async def _ia_refine(text: str, regex_hits: List[Dict[str, Any]],
                       ticket_type_hint: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pede para a IA refinar/validar a extração. Retorna None se falhar."""
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key or not text:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: PLC0415
        system = (
            "Você é um agente de auditoria patrimonial de ISP FTTH brasileiro. "
            "Dado o relato de campo de um técnico, identifique: "
            "(1) tipo do serviço: instalacao|reparo|retirada|troca|rompimento|preventiva; "
            "(2) materiais usados (lista de objetos com item, qty, unit); "
            "(3) serial(is) de ONT mencionados; "
            "(4) se há indicação de defeito no equipamento (true/false/null). "
            "Use o catálogo padrão: drop (m), conector_fast (un), esticador (un), "
            "cabo_rede (m), conector_rede (un), caixa_emenda (un). "
            "Se algum item NÃO estiver no catálogo, retorne em "
            'warnings: ["item_novo: nome detectado"]. '
            "Responda em JSON puro (sem markdown, sem comentários): "
            '{"service_type":"...","materials":[{"item":"...","qty":N,"unit":"...","confidence":0..1}],'
            '"ont_new_sn":"...","ont_old_sn":"...","has_defect_signal":true|false|null,'
            '"warnings":["..."],"reasoning":"3-5 palavras"}'
        )
        hint_extra = f"Hint tipo OS: {ticket_type_hint}\n" if ticket_type_hint else ""
        hint_extra += f"Pré-detecção regex: {json.dumps(regex_hits, ensure_ascii=False)}\n"
        user_msg = (
            f"{hint_extra}"
            f"Relato do técnico:\n---\n{text[:1500]}\n---\n"
            "Devolva o JSON puro."
        )
        sess = f"iapat-{uuid.uuid4().hex[:8]}"
        chat = LlmChat(api_key=key, session_id=sess,
                        system_message=system).with_model(
            "anthropic", "claude-sonnet-4-5-20250929")
        raw = await chat.send_message(UserMessage(text=user_msg))
        txt = (raw or "").strip()
        if "```" in txt:
            txt = txt.split("```", 2)[1]
            if txt.startswith("json"):
                txt = txt[4:]
        i, j = txt.find("{"), txt.rfind("}")
        if i < 0 or j <= i:
            return None
        return json.loads(txt[i:j+1])
    except Exception:  # noqa: BLE001
        return None


# ─── Engine principal ─────────────────────────────────────────────────────

async def extract_from_narrative(
    text: str,
    ticket_type_hint: Optional[str] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Pipeline read-only: classifica serviço + extrai materiais + SN.

    Returns:
        {
          "service_type": "reparo",
          "service_type_confidence": 0.85,
          "materials_detected": [...],
          "ont_new_sn": None,
          "ont_old_sn": None,
          "has_defect_signal": None,
          "warnings": [...],
          "method": "regex+llm" | "regex" | "llm",
        }
    """
    if not text or not text.strip():
        return {
            "service_type": ticket_type_hint or "reparo",
            "service_type_confidence": 0.0,
            "materials_detected": [],
            "ont_new_sn": None, "ont_old_sn": None,
            "has_defect_signal": None,
            "warnings": ["narrativa vazia"],
            "method": "empty",
        }

    # 1. Regex/heurístico (sempre roda — barato, determinístico)
    regex_materials = _regex_extract_materials(text)
    regex_serials = _extract_serials(text)
    st, st_conf = _classify_service_type(text, ticket_type_hint)

    # 2. LLM refina (se disponível)
    llm_data: Optional[Dict[str, Any]] = None
    if use_llm:
        llm_data = await _ia_refine(text, regex_materials, ticket_type_hint)

    # 3. Merge
    if llm_data:
        materials = []
        for m in llm_data.get("materials") or []:
            if not m.get("item"):
                continue
            item_id = ITEM_NORMALIZE.get(
                str(m["item"]).lower(), str(m["item"]).lower())
            try:
                qty = float(m.get("qty", 0))
            except (TypeError, ValueError):
                qty = 0
            if qty <= 0:
                continue
            materials.append({
                "item": item_id,
                "qty": qty,
                "unit": m.get("unit") or ITEM_CATALOG.get(
                    item_id, {}).get("unit", "unidade"),
                "confidence": float(m.get("confidence", 0.8)),
                "source": "llm",
            })
        if not materials and regex_materials:
            materials = regex_materials
        return {
            "service_type": llm_data.get("service_type") or st,
            "service_type_confidence": max(st_conf, 0.85)
                if llm_data.get("service_type") else st_conf,
            "materials_detected": materials,
            "ont_new_sn": llm_data.get("ont_new_sn") or
                (regex_serials[0] if regex_serials else None),
            "ont_old_sn": llm_data.get("ont_old_sn") or
                (regex_serials[1] if len(regex_serials) > 1 else None),
            "has_defect_signal": llm_data.get("has_defect_signal"),
            "warnings": llm_data.get("warnings") or [],
            "method": "regex+llm",
            "_llm_reasoning": llm_data.get("reasoning"),
        }

    # 4. Fallback puro regex
    return {
        "service_type": st,
        "service_type_confidence": st_conf,
        "materials_detected": regex_materials,
        "ont_new_sn": regex_serials[0] if regex_serials else None,
        "ont_old_sn": regex_serials[1] if len(regex_serials) > 1 else None,
        "has_defect_signal": None,
        "warnings": [],
        "method": "regex",
    }


# ─── Comparador IA × formulário (para shadow report) ──────────────────────

FORM_FIELD_TO_ITEM = {
    "qtd_drop": ("drop", "m"),
    "conectores_fast": ("conector_fast", "unidade"),
    "esticadores": ("esticador", "unidade"),
    "cabo_rede": ("cabo_rede", "m"),
    "conectores_rede": ("conector_rede", "unidade"),
}


def compare_ia_vs_form(ia_result: Dict[str, Any],
                         completion_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compara extração IA com o que o técnico digitou no formulário."""
    form_items: Dict[str, float] = {}
    for fkey, (item, _) in FORM_FIELD_TO_ITEM.items():
        v = completion_data.get(fkey)
        if isinstance(v, (int, float)) and v > 0:
            form_items[item] = float(v)
    ia_items: Dict[str, float] = {}
    for m in ia_result.get("materials_detected") or []:
        ia_items[m["item"]] = ia_items.get(m["item"], 0) + float(m.get("qty") or 0)
    all_items = set(form_items) | set(ia_items)
    diffs = []
    perfect_match = 0
    only_form = 0
    only_ia = 0
    qty_mismatch = 0
    for item in all_items:
        f = form_items.get(item, 0)
        i = ia_items.get(item, 0)
        if f and not i:
            only_form += 1
            diffs.append({"item": item, "form": f, "ia": 0, "verdict": "only_form"})
        elif i and not f:
            only_ia += 1
            diffs.append({"item": item, "form": 0, "ia": i, "verdict": "only_ia"})
        elif f == i:
            perfect_match += 1
        else:
            qty_mismatch += 1
            diffs.append({"item": item, "form": f, "ia": i,
                           "verdict": "qty_mismatch"})
    return {
        "perfect_match": perfect_match,
        "only_form": only_form,
        "only_ia": only_ia,
        "qty_mismatch": qty_mismatch,
        "diffs": diffs,
    }
