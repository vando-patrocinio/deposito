"""Holerite IA — parsing de holerites brasileiros via Claude + fuzzy match.

Fluxo:
1. Extrai texto do PDF com pypdf (holerites CLT são tipicamente text-based).
2. Envia texto + prompt estruturado para Claude Sonnet 4.5 via motor_ia (OpenRouter).
3. Claude retorna JSON com lista de funcionários encontrados (nome, CPF, gross, net,
   deductions, period).
4. Match com `collaborators` da empresa via RapidFuzz token_set_ratio + Unidecode.
5. Retorna preview com cada item: matched_collaborator_id, score, status.

Best practices aplicadas (web search 2025):
- CLT/eSocial format awareness no prompt.
- BRL parsing ("R$ 1.234,56" → 1234.56).
- CPF validation (11 dígitos).
- Per-employee struct (1 holerite por funcionário, multi-page suportado).
- Fuzzy matching: token_set_ratio (handles "João Silva" vs "Silva, João" vs "Joao Silva")
- Threshold configurável (default 85).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import io
import json
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process
from unidecode import unidecode

from database import db
from services import motor_ia

logger = logging.getLogger("holerite_ai")


HOLERITE_PARSER_PROMPT = """\
Você é um parser especialista em holerites brasileiros (CLT/eSocial).

Recebe o TEXTO EXTRAÍDO de um PDF de folha de pagamento gerado pelo contador.
O arquivo pode conter MÚLTIPLOS funcionários (1 por página ou separados por
quebras claras).

EXTRAIA todos os funcionários no formato JSON ESTRITO:

{
  "competence": {
    "month": <int 1-12>,
    "year": <int 2000-2100>
  },
  "company": {
    "name": "<string>",
    "cnpj": "<string ou null>"
  },
  "employees": [
    {
      "full_name": "<nome completo conforme aparece no holerite>",
      "cpf": "<11 dígitos sem formatação, ou null se ausente>",
      "matricula": "<string ou null>",
      "position": "<cargo ou null>",
      "admission_date": "<YYYY-MM-DD ou null>",
      "gross": <float — soma de TODOS os proventos em BRL>,
      "net": <float — líquido a receber em BRL>,
      "deductions_total": <float — soma de descontos em BRL>,
      "earnings": [
        {"description": "<descrição>", "value": <float>, "reference": "<horas/dias ou null>"}
      ],
      "deductions": [
        {"description": "<descrição>", "value": <float>}
      ],
      "fgts_base": <float ou null>,
      "irrf_base": <float ou null>,
      "inss_base": <float ou null>
    }
  ]
}

REGRAS RÍGIDAS:
- BRL: "R$ 1.234,56" → 1234.56 · sempre float, NUNCA string.
- CPF: APENAS dígitos. Se inválido (≠ 11 dígitos), use null.
- Se o holerite contém só 1 funcionário, ainda assim use o array `employees`.
- Se houver QUALQUER incerteza sobre um campo, use null em vez de chutar.
- gross deve ser a soma das earnings (valida o cálculo).
- net = gross - deductions_total (valida o cálculo, ±0.05 tolerância).
- competence: período de referência do pagamento (NÃO data de emissão).
- Mantenha nomes EXATAMENTE como aparecem (acentos, maiúsculas etc).

NÃO INCLUA NENHUM TEXTO FORA DO JSON. NEM ```json. NEM EXPLICAÇÕES.
SOMENTE O JSON VÁLIDO.
"""


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------
def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extrai texto de um PDF usando pypdf. Mantém quebras de página."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("pypdf não instalado") from e

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text: List[str] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as e:
            logger.warning("[holerite-ai] page %d extract falhou: %s", i, e)
            txt = ""
        pages_text.append(f"--- PÁGINA {i+1} ---\n{txt}")
    return "\n\n".join(pages_text)


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------
def _normalize(name: str) -> str:
    """Lowercase + remove acentos + colapsa espaços."""
    if not name:
        return ""
    n = unidecode(name).lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def match_employee(
    full_name: str,
    cpf: Optional[str],
    candidates: List[Dict[str, Any]],
    threshold: int = 85,
) -> Tuple[Optional[Dict[str, Any]], float, str]:
    """Encontra o melhor match num conjunto de candidatos.

    Retorna (collaborator_dict ou None, score 0-100, status).
    Status: 'cpf_exact' | 'name_high' | 'name_medium' | 'no_match'.
    """
    if not candidates:
        return None, 0.0, "no_match"

    # 1) Tentativa CPF exato (mais confiável)
    if cpf:
        cpf_norm = re.sub(r"\D", "", cpf)
        if len(cpf_norm) == 11:
            for c in candidates:
                c_cpf = re.sub(r"\D", "", c.get("cpf") or "")
                if c_cpf == cpf_norm:
                    return c, 100.0, "cpf_exact"

    # 2) Token-set ratio (lida com ordem diferente e nomes incompletos)
    target = _normalize(full_name)
    choices = {c["id"]: _normalize(c.get("name") or "") for c in candidates}
    # process.extractOne retorna (str, score, key)
    best = process.extractOne(
        target, choices, scorer=fuzz.token_set_ratio, score_cutoff=threshold,
    )
    if best:
        _, score, cid = best
        match = next(c for c in candidates if c["id"] == cid)
        status = "name_high" if score >= 92 else "name_medium"
        return match, float(score), status
    return None, 0.0, "no_match"


# ---------------------------------------------------------------------------
# Claude parsing
# ---------------------------------------------------------------------------
async def parse_pdf_with_ai(
    company_id: str,
    pdf_bytes: bytes,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Roda o pipeline completo: extract → Claude → JSON normalizado."""
    text = extract_pdf_text(pdf_bytes)
    if not text.strip():
        raise RuntimeError(
            "PDF não contém texto extraível (provavelmente é uma imagem "
            "escaneada). Use OCR antes de subir."
        )

    # Limita tamanho do texto para o LLM (≈ 60k chars ≈ 15k tokens)
    if len(text) > 80_000:
        text = text[:80_000] + "\n\n[... texto truncado por excesso de tamanho ...]"

    res = await motor_ia.chat_completion(
        company_id=company_id,
        messages=[
            {"role": "system", "content": HOLERITE_PARSER_PROMPT},
            {"role": "user",
             "content": f"TEXTO DO PDF:\n\n{text}\n\nRetorne SOMENTE o JSON."},
        ],
        model=model or "anthropic/claude-sonnet-4.5",
        temperature=0.0,
        max_tokens=8000,
        json_mode=True,
        purpose="general",
        agent="holerite_ai",
    )
    content = (res.get("content") or "").strip()
    # remove eventuais ```json wrappers
    if content.startswith("```"):
        content = content.strip("`").lstrip("json").strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("[holerite-ai] Claude JSON inválido: %s · raw=%r",
                      e, content[:500])
        raise RuntimeError(
            f"Claude retornou JSON inválido: {e}. Tente novamente ou "
            "verifique se o PDF está legível."
        )

    # Garante estrutura mínima
    if "employees" not in data or not isinstance(data["employees"], list):
        raise RuntimeError(
            "Claude não identificou nenhum funcionário no holerite."
        )
    return data


# ---------------------------------------------------------------------------
# Match all employees with collaborators
# ---------------------------------------------------------------------------
async def match_all(
    company_id: str,
    parsed: Dict[str, Any],
    threshold: int = 85,
) -> Dict[str, Any]:
    """Para cada employee do parsed JSON, busca colaborador no banco.

    Retorna dict com lista de matches enriquecida + stats.
    """
    candidates = await db.collaborators.find(
        {"company_id": company_id, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "cpf": 1, "phone": 1,
         "position": 1, "email": 1},
    ).to_list(2000)

    employees = parsed.get("employees", []) or []
    matched = []
    matched_count = 0
    total_gross = 0.0
    total_net = 0.0

    for emp in employees:
        col, score, status = match_employee(
            emp.get("full_name", ""), emp.get("cpf"),
            candidates, threshold,
        )
        total_gross += float(emp.get("gross") or 0)
        total_net += float(emp.get("net") or 0)
        item = {
            "parsed": emp,
            "match": col,
            "match_score": score,
            "match_status": status,
        }
        if col:
            matched_count += 1
        matched.append(item)

    return {
        "competence": parsed.get("competence", {}),
        "company": parsed.get("company", {}),
        "matches": matched,
        "stats": {
            "parsed_count": len(employees),
            "matched_count": matched_count,
            "unmatched_count": len(employees) - matched_count,
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "candidate_pool_size": len(candidates),
        },
    }
