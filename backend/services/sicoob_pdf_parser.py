"""
Parser de extrato PDF do Sicoob (Cooperativa de Crédito).

O PDF do Sicoob tem layout fixo mas com quebras de linha problemáticas:
quando o valor estoura a coluna, o valor ou o indicador C/D pula para outra
linha. Esse parser implementa um state-machine que reconhece 3 padrões:

  Padrão A (comum):
    DD/MM     CRÉD.LIQ.COBRANÇA          212,53C
              DOC.: 3580248

  Padrão B (valor presente, indicador na linha seguinte):
    DD/MM     PIX EMIT.OUTRA IF          10.000,00
              Pagamento Pix               D
              ***.820.297-**
              DOC.: Pix

  Padrão C (valor órfão na linha anterior, indicador na linha do DD/MM):
              1.296,86
    DD/MM     CRÉD.LIQ.COBRANÇA          C
              DOC.: 3456650

Linhas a IGNORAR (não são transações):
  - SALDO DO DIA, SALDO ANTERIOR, SALDO BLOQ.ANTERIOR
  - Tudo a partir de "RESUMO" (rodapé com totais).

Saída: lista de dicts compatíveis com `_build_staging` em
`backend/routes/bank_import.py` — campos: date (YYYY-MM-DD), amount (float
positivo), type ("income"|"expense"), description (str<=300), ofx_id (str).
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sicoob_pdf")

# ── Regex helpers ──────────────────────────────────────────────────────────
# Linha que começa uma transação: DD/MM no início (ignora espaços iniciais)
RX_TX_START = re.compile(r"^\s*(\d{2})/(\d{2})\s+(.+)$")
# Valor BR: 1.234,56 ou 12,34 (mín 1 dígito antes da vírgula)
RX_VALUE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\b")
# Indicador C ou D solitário ou ao final de um valor
RX_INDICATOR = re.compile(r"(?:^|\s)([CD])(?:\s|$)")
# Período do cabeçalho — usado pra inferir o ano das datas DD/MM
RX_PERIOD = re.compile(
    r"PER[ÍI]ODO:\s*(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})",
    re.IGNORECASE,
)
# Linhas que NÃO são transações — saldos / resumos
RX_SKIP = re.compile(
    r"^\s*\d{2}/\d{2}\s+SALDO\s+(DO\s+DIA|ANTERIOR|BLOQ\.?ANTERIOR)",
    re.IGNORECASE,
)
RX_DOC_LINE = re.compile(r"^\s*DOC\.:", re.IGNORECASE)


def _br_to_float(s: str) -> Optional[float]:
    """Converte '1.234,56' -> 1234.56. Retorna None se inválido."""
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _extract_text_from_pdf(data: bytes) -> str:
    """Extrai texto cru do PDF preservando quebras de linha.

    Usa pdfplumber (melhor pra layouts tabulares). Se PDF for puramente
    escaneado (sem camada de texto), retorna string vazia — o caller decide
    como tratar (geralmente: erro pedindo OFX).
    """
    import pdfplumber
    chunks: List[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                chunks.append(t)
    return "\n".join(chunks)


def _detect_year(text: str) -> int:
    """Tenta achar o ano via PERÍODO do cabeçalho; senão usa ano corrente."""
    m = RX_PERIOD.search(text)
    if m:
        # Usa o ano do início do período (mês passado normalmente está dentro
        # do mesmo ano do final)
        try:
            return int(m.group(3))
        except ValueError:
            pass
    return datetime.now().year


def _strip_footer(text: str) -> str:
    """Remove tudo a partir da seção RESUMO (rodapé com totais)."""
    idx = text.find("\nRESUMO")
    if idx < 0:
        idx = text.find("RESUMO\n")
    return text[:idx] if idx > 0 else text


# ── State machine ─────────────────────────────────────────────────────────
class _TxState:
    """Estado parcial de uma transação enquanto montamos a partir de várias
    linhas (description, value, indicator podem vir separados)."""

    __slots__ = ("date", "desc_parts", "value", "indicator",
                  "extra_lines", "doc_ref")

    def __init__(self, date: str):
        self.date: str = date            # YYYY-MM-DD
        self.desc_parts: List[str] = []  # principal: header da linha DD/MM
        self.value: Optional[float] = None
        self.indicator: Optional[str] = None   # "C" ou "D"
        self.extra_lines: List[str] = []  # linhas de continuação (DOC, nome…)
        self.doc_ref: str = ""           # DOC.: <id>

    def to_dict(self) -> Optional[Dict[str, Any]]:
        if not self.value or not self.indicator:
            return None
        desc = " · ".join(p.strip() for p in self.desc_parts if p.strip())
        # Adiciona contexto útil (DOC ref + 1ª linha de continuação que não
        # seja DOC.:, SALDO, ou apenas C/D solto) — ajuda a IA classificadora.
        ctx: List[str] = []
        if self.doc_ref:
            ctx.append(f"DOC#{self.doc_ref}")
        for ln in self.extra_lines:
            ln = ln.strip()
            if not ln or ln.upper().startswith("DOC.:"):
                continue
            # ignora linhas que são só o indicador C/D ou só um valor solto
            if re.fullmatch(r"[CD]", ln) or RX_VALUE.fullmatch(ln):
                continue
            if "SALDO" in ln.upper():
                continue
            ctx.append(ln)
            if len(ctx) >= 3:
                break
        if ctx:
            desc = f"{desc} · {' · '.join(ctx)}"
        return {
            "date": self.date,
            "amount": abs(self.value),
            "type": "income" if self.indicator == "C" else "expense",
            "description": desc[:300],
            "ofx_id": self.doc_ref[:64],
        }


def _split_value_indicator(token: str) -> Tuple[Optional[float], Optional[str]]:
    """Tenta extrair valor e indicador (C/D) de um único token/linha.

    Ex.: "212,53C" -> (212.53, "C")
         "10.000,00" -> (10000.0, None)
         "C" -> (None, "C")
         "Pagamento Pix    D" -> (None, "D")  (procura C/D isolado no final)
    """
    # Valor com indicador colado: "212,53C"
    m = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*([CD])\b", token)
    if m:
        return _br_to_float(m.group(1)), m.group(2)
    # Só valor
    vm = RX_VALUE.search(token)
    val = _br_to_float(vm.group(1)) if vm else None
    # Só indicador isolado — pega o ÚLTIMO C/D solitário na string
    # (várias linhas têm "...D\n" sem nada antes)
    im = list(re.finditer(r"(?:^|\s)([CD])(?:\s|$)", token))
    ind = im[-1].group(1) if im else None
    return val, ind


def parse_sicoob_pdf(data: bytes) -> List[Dict[str, Any]]:
    """Parser principal: bytes PDF Sicoob -> lista de transações dict."""
    text = _extract_text_from_pdf(data)
    if not text or len(text) < 80:
        raise ValueError(
            "PDF sem camada de texto (provavelmente escaneado). "
            "Exporte o OFX/CSV pelo Internet Banking Sicoob ou envie um "
            "PDF gerado diretamente pelo app.",
        )
    year = _detect_year(text)
    body = _strip_footer(text)

    transactions: List[Dict[str, Any]] = []
    cur: Optional[_TxState] = None
    pending_value: Optional[float] = None   # padrão C: valor órfão na linha
                                              # ANTERIOR à do DD/MM

    def flush(tx: Optional[_TxState]) -> None:
        if not tx:
            return
        d = tx.to_dict()
        if d:
            transactions.append(d)
        else:
            logger.debug("sicoob: ignorando tx incompleta date=%s desc=%s "
                          "value=%s ind=%s", tx.date, tx.desc_parts,
                          tx.value, tx.indicator)

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m_start = RX_TX_START.match(line)
        if m_start:
            # Linha SALDO DO DIA / SALDO ANTERIOR: fecha tx atual e ignora
            if RX_SKIP.match(line):
                flush(cur)
                cur = None
                pending_value = None
                continue
            # Nova transação — fecha a anterior
            flush(cur)
            dd, mm, rest = m_start.group(1), m_start.group(2), m_start.group(3)
            try:
                date_iso = datetime(year, int(mm), int(dd)).strftime("%Y-%m-%d")
            except ValueError:
                cur = None
                pending_value = None
                continue
            cur = _TxState(date_iso)
            # Tenta extrair desc + valor + indicador da MESMA linha
            val, ind = _split_value_indicator(rest)
            # Desc = "rest" antes do valor e indicador
            desc_clean = rest
            # Remove o valor da descrição
            if val is not None:
                desc_clean = re.sub(r"\d{1,3}(?:\.\d{3})*,\d{2}\s*[CD]?",
                                     "", desc_clean, count=1)
            else:
                # Remove indicador solto C/D no final
                desc_clean = re.sub(r"\s+[CD]\s*$", "", desc_clean)
            cur.desc_parts.append(desc_clean.strip())
            # Aplica valor pendente da linha anterior (padrão C)
            if val is None and pending_value is not None:
                cur.value = pending_value
                pending_value = None
            else:
                cur.value = val
                pending_value = None
            cur.indicator = ind
            continue

        # ── Linha de continuação (sem DD/MM no início) ────────────────────
        # Verifica se a linha é APENAS um valor (orphan value entre txs)
        line_stripped = line.strip()
        is_pure_value = bool(RX_VALUE.fullmatch(line_stripped))

        if cur is None:
            # Pode ser um valor órfão antes do próximo DD/MM (padrão C)
            if is_pure_value:
                pending_value = _br_to_float(line_stripped)
            continue

        # DOC.: <id>
        if RX_DOC_LINE.match(line):
            doc = line.split(":", 1)[1].strip() if ":" in line else ""
            cur.doc_ref = doc[:64]
            cur.extra_lines.append(line.strip())
            continue

        # Linha puramente de valor (sem indicador, sem outro texto):
        # - Se cur ainda não tem value → é o value de cur (caso raro)
        # - Se cur já tem value → é orphan para a PRÓXIMA tx → flush cur,
        #   guarda em pending_value e zera cur
        if is_pure_value:
            v = _br_to_float(line_stripped)
            if cur.value is None:
                cur.value = v
            else:
                flush(cur)
                cur = None
                pending_value = v
            continue

        # Linha pode trazer o indicador C/D faltante (padrão B)
        if cur.indicator is None:
            ind_m = RX_INDICATOR.search(line)
            if ind_m:
                cur.indicator = ind_m.group(1)
        # Ou trazer o valor faltante (raro mas possível)
        if cur.value is None:
            v = RX_VALUE.search(line)
            if v:
                cur.value = _br_to_float(v.group(1))

        cur.extra_lines.append(line.strip())

    flush(cur)
    return transactions
