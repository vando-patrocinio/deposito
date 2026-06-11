"""Coverage checker — verifica viabilidade técnica de instalação por endereço.

Cruza um texto livre de endereço (recebido do cliente no WhatsApp) com:
  1. `subscriber_addresses` — endereços de clientes ATIVOS (vizinhos)
  2. `ctos` — CTOs registradas (cobertura de fibra confirmada)

Retorna nível de viabilidade + evidências pra IA explicar pro cliente:
  - VIAVEL_DIRETO   → rua + bairro batem com clientes ativos OU com CTO
  - VIAVEL_PROVAVEL → bairro com ≥1 cliente ativo OU ≥1 CTO
  - SEM_REGISTROS   → bairro sem registros → exige visita técnica
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import re
import unicodedata
from typing import Any, Dict, List, Optional

from database import db


_STOPWORDS = {
    "rua", "r.", "av", "av.", "avenida", "tv", "travessa", "alameda",
    "estrada", "rodovia", "rod.", "praca", "praça", "largo", "viela",
    "rural", "via", "n", "no", "nº", "numero", "número", "casa", "ap",
    "apt", "apto", "apartamento", "bloco", "bl", "fundos", "qd", "lt",
    "complemento", "comp.", "ref", "referencia", "referência",
    "bairro", "cidade", "estado", "cep", "do", "da", "de", "dos", "das",
}


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> List[str]:
    return [t for t in _norm(s).split()
            if t and t not in _STOPWORDS and len(t) > 1]


def _extract_cep(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{5})-?(\d{3})\b", text or "")
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None


def _extract_number(text: str) -> Optional[str]:
    """Pega 1º número de 1-5 dígitos (após 'nº', 'numero', ou solto)."""
    m = re.search(r"(?:n[ºo°.]?\s*|numero\s*|n[ºo]?\s+)(\d{1,5})\b",
                  text or "", re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.search(r"\b(\d{1,5})\b", text or "")
    return m2.group(1) if m2 else None


def parse_address(text: str) -> Dict[str, Any]:
    """Extrai street, number, district, cep, full_norm de texto livre."""
    if not text:
        return {"raw": "", "tokens": [], "street": None, "number": None,
                "district": None, "cep": None, "full_norm": ""}
    raw = text.strip()
    # split por vírgula/traço/quebra de linha pra heurística por seção
    parts = [p.strip() for p in re.split(r"[,\n;]+", raw) if p.strip()]
    cep = _extract_cep(raw)
    number = _extract_number(raw)
    # heurísticas:
    street = parts[0] if parts else None
    # district: procura parte que começa com "bairro" ou é a última parte
    # textual (não-CEP, não-cidade conhecida, não-número-puro).
    district = None
    # 1ª tentativa: parte explícita "bairro X"
    for p in parts:
        m = re.match(r"^\s*bairro\s*[:\-]?\s*(.+)$", p, re.IGNORECASE)
        if m:
            district = m.group(1).strip()
            break
    # 2ª tentativa: última parte textual válida
    if not district:
        for p in reversed(parts):
            norm = _norm(p)
            if not norm:
                continue
            # pula CEP cru, números puros e cidades conhecidas
            if re.fullmatch(r"\d{5}-?\d{3}", p.strip()):
                continue
            if re.fullmatch(r"\d+", p.strip()):
                continue
            if re.search(r"^cep\b", norm):
                continue
            if "rio de janeiro" in norm or "sao paulo" in norm:
                continue
            district = p.strip()
            break
    return {
        "raw": raw,
        "street": street,
        "number": number,
        "district": district,
        "cep": cep,
        "full_norm": _norm(raw),
        "tokens": _tokens(raw),
    }


def _score_overlap(a_tokens: List[str], b_tokens: List[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    sa, sb = set(a_tokens), set(b_tokens)
    inter = len(sa & sb)
    return inter / max(1, min(len(sa), len(sb)))


def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "—"
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "—"
    if len(parts) == 1:
        return parts[0][:3] + "***"
    return f"{parts[0]} {parts[1][0]}."


async def _gather_neighbors(company_id: str, parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Retorna lista de assinantes ativos cujo endereço bate com o parsed."""
    if not parsed["tokens"]:
        return []
    district_norm = _norm(parsed["district"]) if parsed["district"] else ""
    found: List[Dict[str, Any]] = []
    # Busca por subscriber_addresses do mesmo company
    cursor = db.subscriber_addresses.find(
        {"company_id": company_id},
        {"_id": 0, "subscriber_id": 1, "street": 1, "number": 1,
         "district": 1, "city": 1, "zip_code": 1},
    ).limit(2000)
    async for a in cursor:
        a_norm_district = _norm(a.get("district") or "")
        same_district = (district_norm and a_norm_district and
                            (district_norm == a_norm_district
                             or district_norm in a_norm_district
                             or a_norm_district in district_norm))
        same_street_score = _score_overlap(_tokens(a.get("street") or ""),
                                              _tokens(parsed["street"] or ""))
        same_cep = (parsed["cep"] and (a.get("zip_code") or "")
                       .replace("-", "") == parsed["cep"])
        if same_district or same_street_score >= 0.5 or same_cep:
            found.append({
                "subscriber_id": a.get("subscriber_id"),
                "street": a.get("street"),
                "number": a.get("number"),
                "district": a.get("district"),
                "match_district": bool(same_district),
                "match_street_score": round(same_street_score, 2),
                "match_cep": bool(same_cep),
            })
    # Hidrata com subscriber name + status
    if not found:
        return []
    sub_ids = list({x["subscriber_id"] for x in found if x.get("subscriber_id")})
    subs = {}
    async for s in db.subscribers.find(
        {"id": {"$in": sub_ids}, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "plan_name": 1},
    ):
        subs[s["id"]] = s
    out = []
    for f in found:
        s = subs.get(f["subscriber_id"]) or {}
        if (s.get("status") or "").upper() != "ATIVO":
            continue
        out.append({
            **f,
            "name_masked": _mask_name(s.get("name")),
            "plan": s.get("plan_name"),
        })
    return out[:20]


async def _gather_ctos(company_id: str, parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not parsed["tokens"]:
        return []
    district_norm = _norm(parsed["district"]) if parsed["district"] else ""
    found: List[Dict[str, Any]] = []
    cursor = db.ctos.find(
        {"company_id": company_id, "status": {"$ne": "inactive"}},
        {"_id": 0, "id": 1, "name": 1, "address": 1, "ports": 1,
         "capacity": 1},
    ).limit(500)
    async for c in cursor:
        addr = c.get("address") or {}
        a_norm_district = _norm(addr.get("bairro") or "")
        same_district = (district_norm and a_norm_district and
                            (district_norm == a_norm_district
                             or district_norm in a_norm_district
                             or a_norm_district in district_norm))
        same_street_score = _score_overlap(_tokens(addr.get("rua") or ""),
                                              _tokens(parsed["street"] or ""))
        if same_district or same_street_score >= 0.5:
            free_ports = max(0, int(c.get("capacity") or 16) -
                                len(c.get("ports") or []))
            found.append({
                "cto_id": c.get("id"),
                "cto_name": c.get("name"),
                "rua": addr.get("rua"),
                "numero": addr.get("numero"),
                "bairro": addr.get("bairro"),
                "free_ports": free_ports,
                "match_district": bool(same_district),
                "match_street_score": round(same_street_score, 2),
            })
    return found[:8]


async def check_coverage(company_id: str, address_text: str) -> Dict[str, Any]:
    """Retorna avaliação de viabilidade pronta pra ser injetada no prompt."""
    parsed = parse_address(address_text or "")
    if not parsed["tokens"]:
        return {
            "viable": "UNKNOWN",
            "reason": "Texto não parece um endereço válido — peça pra o "
                       "cliente repetir bairro + rua.",
            "parsed": parsed,
            "neighbors": [], "ctos": [],
        }
    neighbors = await _gather_neighbors(company_id, parsed)
    ctos = await _gather_ctos(company_id, parsed)
    direct_street_match = any(n["match_street_score"] >= 0.6
                                  for n in neighbors)
    cto_street_match = any(c["match_street_score"] >= 0.6 for c in ctos)
    district_evidence = (
        sum(1 for n in neighbors if n["match_district"])
        + sum(1 for c in ctos if c["match_district"])
    )

    if direct_street_match or cto_street_match:
        viable = "VIAVEL_DIRETO"
        reason = ("Já temos cliente ativo (ou CTO) na MESMA RUA — "
                     "viabilidade técnica confirmada.")
    elif district_evidence >= 1:
        viable = "VIAVEL_PROVAVEL"
        reason = (f"Temos {district_evidence} ponto(s) de cobertura no "
                     f"bairro — provavelmente viável; visita técnica "
                     f"confirma.")
    else:
        viable = "SEM_REGISTROS"
        reason = ("Não temos cobertura registrada nesse bairro/rua — "
                     "precisamos passar com viabilidade técnica.")

    return {
        "viable": viable,
        "reason": reason,
        "parsed": parsed,
        "neighbors": neighbors,
        "ctos": ctos,
    }


def format_for_prompt(check: Dict[str, Any]) -> str:
    p = check.get("parsed") or {}
    neighbors = check.get("neighbors") or []
    ctos = check.get("ctos") or []
    lines = ["=== VIABILIDADE TÉCNICA (cliente forneceu endereço) ==="]
    lines.append(f"Endereço informado: {p.get('raw') or '?'}")
    if p.get("district"):
        lines.append(f"Bairro detectado: {p['district']}")
    if p.get("street"):
        lines.append(f"Rua detectada: {p['street']}")
    if p.get("number"):
        lines.append(f"Número detectado: {p['number']}")
    if p.get("cep"):
        lines.append(f"CEP detectado: {p['cep']}")
    lines.append(f"Status: {check.get('viable')}")
    lines.append(f"Análise: {check.get('reason')}")
    if neighbors:
        lines.append("Vizinhos ativos próximos (mascarado):")
        for n in neighbors[:3]:
            lines.append(
                f"  · {n.get('name_masked')} — {n.get('street') or '?'} "
                f"{n.get('number') or ''} ({n.get('district') or '?'})"
            )
        if len(neighbors) > 3:
            lines.append(f"  · …e mais {len(neighbors) - 3} cliente(s) ativos no entorno.")
    if ctos:
        lines.append("CTOs registradas no entorno:")
        for c in ctos[:3]:
            lines.append(
                f"  · {c.get('cto_name')} — {c.get('rua') or '?'} "
                f"{c.get('numero') or ''} ({c.get('bairro') or '?'}) — "
                f"{c.get('free_ports')} portas livres"
            )
    lines.append("")
    lines.append("REGRA: explique a viabilidade ao cliente em linguagem "
                  "natural, sem soltar nomes de outros clientes.")
    lines.append(
        "  · VIAVEL_DIRETO   → 'temos cobertura aí, vamos agendar?'\n"
        "  · VIAVEL_PROVAVEL → 'temos cobertura no seu bairro — vou "
        "agendar uma visita técnica pra confirmar'\n"
        "  · SEM_REGISTROS   → 'ainda não atendemos sua rua/bairro mas "
        "vou passar pra equipe técnica avaliar (pode levar 1-2 dias)'"
    )
    return "\n".join(lines)


_ADDRESS_HINTS_RE = re.compile(
    r"\b(rua|av(\.|enida)?|travessa|alameda|estrada|cep|bairro|"
    r"\d{5}-?\d{3}|moro\s+(em|na|no)|fica\s+(em|na|no)|endereço|endereco)\b",
    re.IGNORECASE,
)


def looks_like_address(text: str) -> bool:
    if not text or len(text.strip()) < 8:
        return False
    return bool(_ADDRESS_HINTS_RE.search(text))
