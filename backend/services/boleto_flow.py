"""Fluxo automatizado de envio de boleto/2ª via via WhatsApp.

Quando o cliente menciona boleto/fatura/pagamento, este serviço:
  1. Detecta a intenção (regex/keywords + fuzzy);
  2. Localiza o assinante via telefone (e fallback CPF se cliente enviar);
  3. Busca TODAS as faturas em aberto em `db.subscriber_invoices` (já sincronizado
     via Atlaz V2 — campo `boleto_url` populado);
  4. Monta resposta formatada (link + PIX copia-e-cola + linha digitável + valor +
     vencimento + status);
  5. Retorna o texto pronto pra Isabella enviar.

Princípios:
  - Não responde se o cliente NÃO pediu boleto (apenas detecta intenção).
  - Se cliente não tem cadastro pelo telefone, pede CPF educadamente.
  - Se faturas em aberto = 0, parabeniza ("você está em dia!").
  - Se faturas em aberto ≥ 1, lista TODAS com formatação clara.
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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


# Palavras-chave que indicam pedido de boleto.
# Combinação de gírias + termos formais + comandos diretos.
_KEYWORDS = [
    r"\b2[aª°]\s*via\b",
    r"\bsegunda\s*via\b",
    r"\bboleto\b", r"\bboletos\b",
    r"\bfatura\b", r"\bfaturas\b",
    r"\bconta\b(?!\s*corrente)",  # "conta" mas não "conta corrente"
    r"\bcobran[cç]a\b",
    r"\bpag(ar|amento)\b",
    r"\bpix\b",
    r"\bcódigo\s*de\s*barras\b",
    r"\blinha\s*digit[áa]vel\b",
    r"\bvencimento\b", r"\bvencendo\b", r"\bvencer\b", r"\bvenceu\b",
    r"\bdebito\b", r"\bd[ée]bito\b",
    r"\batras(o|ado|ada)\b",
    r"\bquit(ar|ação)\b",
    r"\bnegoci(ar|ação)\b",
]

# Termos negativos — não disparam o fluxo
_BLOCK_TERMS = [
    r"\binternet\b", r"\bvelocidade\b", r"\bplano\b",
    r"\bcancelar\b.*\bcontrato\b",
]

_INTENT_RE = re.compile("|".join(_KEYWORDS), re.IGNORECASE)
_BLOCK_RE = re.compile("|".join(_BLOCK_TERMS), re.IGNORECASE) if _BLOCK_TERMS else None

# Detecta CPF (com ou sem máscara)
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")


def detect_boleto_intent(text: str) -> bool:
    """True se o cliente está pedindo boleto/2ª via/pagamento."""
    if not text:
        return False
    t = text.strip().lower()
    # Atalho: cliente digitou só BOLETO ou número de menu (1, 2)
    if t in {"boleto", "boletos", "1", "fatura", "2", "pagamento"}:
        return True
    if _BLOCK_RE and _BLOCK_RE.search(text) and not _INTENT_RE.search(text):
        return False
    return bool(_INTENT_RE.search(text))


def extract_cpf(text: str) -> Optional[str]:
    """Retorna CPF (só dígitos) se encontrado no texto, senão None."""
    if not text:
        return None
    m = _CPF_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return digits if len(digits) == 11 else None


def _format_brl(value: Any) -> str:
    try:
        v = float(value)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "—"


def _format_linha_digitavel(barcode: Optional[str]) -> Optional[str]:
    """Formata os 47 dígitos da linha digitável do boleto bancário.

    Padrão FEBRABAN: `XXXXX.XXXXX XXXXX.XXXXXX XXXXX.XXXXXX X XXXXXXXXXXXXXX`
    (campos 1, 2, 3, DV, fator+valor). Tolerante a entrada com 47 ou 48
    dígitos.
    """
    if not barcode:
        return None
    digits = re.sub(r"\D", "", str(barcode))
    if len(digits) < 47:
        return None
    d = digits[:47]
    try:
        return (f"{d[0:5]}.{d[5:10]} {d[10:15]}.{d[15:21]} "
                f"{d[21:26]}.{d[26:32]} {d[32]} {d[33:47]}")
    except Exception:
        return d


def _status_emoji_and_label(due_iso: Optional[str]) -> tuple:
    """Retorna (emoji, label_curto) baseado no delta de dias.

    🟢 no prazo (>7d), 🟡 vence em breve (0-7d), 🔴 vencida.
    """
    if not due_iso:
        return ("⚪", "")
    try:
        dt = datetime.fromisoformat(str(due_iso).replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).date()
        delta = (dt.date() - today).days
        if delta < 0:
            return ("🔴", f"venceu há {abs(delta)} dia{'s' if abs(delta) != 1 else ''}")
        if delta == 0:
            return ("🟡", "vence HOJE")
        if delta <= 7:
            return ("🟡", f"vence em {delta} dia{'s' if delta != 1 else ''}")
        return ("🟢", "no prazo")
    except Exception:
        return ("⚪", "")


def _format_due(due_iso: Optional[str]) -> str:
    if not due_iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(due_iso).replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).date()
        d = dt.date()
        delta = (d - today).days
        date_br = d.strftime("%d/%m/%Y")
        if delta < 0:
            return f"{date_br} (venceu há {abs(delta)} dia{'s' if abs(delta) != 1 else ''})"
        if delta == 0:
            return f"{date_br} (vence HOJE)"
        if delta <= 7:
            return f"{date_br} (vence em {delta} dia{'s' if delta != 1 else ''})"
        return date_br
    except Exception:
        return str(due_iso)[:10]


async def _find_subscriber_by_phone(cid: str, phone: str) -> Optional[Dict[str, Any]]:
    """Procura assinante pelo telefone.

    Schema multi-coleção:
      1. `subscriber_phones` (preferência — tem `subscriber_id` direto e `normalized_number`)
      2. `atlaz_clients_cache` (fallback — tem `phone` mas só `external_id`)

    Retorna doc do `subscribers` ou um doc sintético com `external_code` setado
    para que `_list_open_invoices` consiga buscar as faturas.
    """
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return None

    # Variações: com/sem DDI 55, com/sem 9 no celular brasileiro
    variants = {digits}
    if digits.startswith("55") and len(digits) >= 12:
        variants.add(digits[2:])  # remove 55
    if len(digits) == 11 and digits[2] == "9":
        variants.add(digits[:2] + digits[3:])  # remove 9
    if len(digits) == 10:
        variants.add(digits[:2] + "9" + digits[2:])  # adiciona 9
    if not digits.startswith("55") and len(digits) >= 10:
        variants.add("55" + digits)  # adiciona DDI

    variants_list = list(variants)

    # 1. Tenta subscriber_phones (rede principal — vínculo direto)
    sp = await db.subscriber_phones.find_one(
        {
            "company_id": cid,
            "$or": [
                {"normalized_number": {"$in": variants_list}},
                {"raw_number": {"$in": variants_list}},
                {"phone": {"$in": variants_list}},
            ],
        },
        {"_id": 0},
    )
    if sp and sp.get("subscriber_id"):
        sub = await db.subscribers.find_one(
            {"id": sp["subscriber_id"]}, {"_id": 0}
        )
        if sub:
            # Completa o external_code se faltar — busca em atlaz_clients_cache
            # pelo document (CPF) ou pelo telefone.
            if not sub.get("external_code"):
                doc = sub.get("document") or sub.get("cpf")
                acc = None
                if doc:
                    acc = await db.atlaz_clients_cache.find_one(
                        {"company_id": cid, "document": doc}, {"_id": 0}
                    )
                if not acc:
                    acc = await db.atlaz_clients_cache.find_one(
                        {"company_id": cid, "phone": {"$in": variants_list}},
                        {"_id": 0},
                    )
                if acc and acc.get("external_id"):
                    sub["external_code"] = str(acc["external_id"])
            return sub

    # 2. Fallback: atlaz_clients_cache (tem só external_id, mas serve pra buscar faturas)
    acc = await db.atlaz_clients_cache.find_one(
        {"company_id": cid, "phone": {"$in": variants_list}}, {"_id": 0},
    )
    if acc and acc.get("external_id"):
        ext = str(acc["external_id"])
        # Tenta achar subscriber pelo external_code
        sub = await db.subscribers.find_one(
            {"company_id": cid, "external_code": ext}, {"_id": 0}
        )
        if sub:
            return sub
        # Doc sintético — boleto_flow funciona com external_code mesmo sem subscriber salvo
        return {
            "id": None,
            "external_code": ext,
            "name": acc.get("name"),
            "email": acc.get("email"),
            "document": acc.get("document"),
            "_from_cache": True,
        }
    return None


async def _find_subscriber_by_cpf(cid: str, cpf: str) -> Optional[Dict[str, Any]]:
    digits = re.sub(r"\D", "", cpf or "")
    if len(digits) != 11:
        return None
    masked = f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

    # 1. Tenta subscribers (campo document/cpf)
    sub = await db.subscribers.find_one(
        {"company_id": cid,
         "$or": [
             {"document": {"$in": [digits, masked]}},
             {"cpf": {"$in": [digits, masked]}},
         ]},
        {"_id": 0},
    )
    if sub:
        return sub
    # 2. Fallback Atlaz
    acc = await db.atlaz_clients_cache.find_one(
        {"company_id": cid, "document": {"$in": [digits, masked]}}, {"_id": 0},
    )
    if acc and acc.get("external_id"):
        ext = str(acc["external_id"])
        sub = await db.subscribers.find_one(
            {"company_id": cid, "external_code": ext}, {"_id": 0}
        )
        if sub:
            return sub
        return {
            "id": None, "external_code": ext,
            "name": acc.get("name"), "email": acc.get("email"),
            "document": acc.get("document"), "_from_cache": True,
        }
    return None


async def _audit_subscriber_financial_status(
    cid: str, subscriber: Dict[str, Any]
) -> Dict[str, Any]:
    """REGRA DURA CEO (17/02/2026): "conferir, analisar, conferir novamente".

    Antes de afirmar qualquer coisa sobre status financeiro do cliente,
    produz um bloco de evidência auditável com 3 verificações:

      1. CONFERIR: subscriber identificado + last_sync atual?
      2. ANALISAR: invoices paid vs open vs sem dados?
      3. CONFERIR NOVAMENTE: cross-check pelos diferentes formatos de
         external_id (com prefixo ATLAZ-, sem prefixo, int) — todos
         retornam o mesmo resultado?

    Retorna `evidence_block` que é persistido em `isabella_financial_audit`
    e usado pra montar a mensagem com prova ao cliente.
    """
    ext = subscriber.get("external_code") or subscriber.get("id_assinante")
    ext_str = str(ext).strip() if ext else None
    ext_num = None
    if ext_str and "-" in ext_str:
        tail = ext_str.rsplit("-", 1)[-1]
        if tail.isdigit():
            ext_num = tail
    elif ext_str and ext_str.isdigit():
        ext_num = ext_str

    out: Dict[str, Any] = {
        "subscriber_id": subscriber.get("id"),
        "subscriber_external_id": ext_num or ext_str,
        "subscriber_name": subscriber.get("name"),
        "company_id": cid,
        "checks": [],
        "warnings": [],
        "audit_passed": False,
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }

    # CHECK 1 — Identificação
    if not ext_str and not subscriber.get("id"):
        out["warnings"].append("subscriber_unidentified")
        out["checks"].append({"check": "identification", "ok": False})
        return out
    out["checks"].append({"check": "identification", "ok": True,
                            "ext": ext_str, "ext_num": ext_num})

    # CHECK 2 — Conferência primária + análise
    queries = []
    if ext_num:
        queries.append({"subscriber_external_id": ext_num})
    if ext_str and ext_str != ext_num:
        queries.append({"subscriber_external_id": ext_str})
    if subscriber.get("id"):
        queries.append({"subscriber_id": subscriber["id"]})

    paid_total = 0
    open_total = 0
    last_paid_date: Optional[str] = None
    next_due_date: Optional[str] = None
    last_sync_at: Optional[str] = None
    examined_ids: List[str] = []

    for q in queries:
        q_full = {"company_id": cid, **q}
        async for d in db.subscriber_invoices.find(q_full, {
            "_id": 0, "external_id": 1, "status": 1, "due_date": 1,
            "amount": 1, "paid_date": 1, "synced_at": 1,
        }).sort("due_date", -1):
            eid = d.get("external_id")
            if eid in examined_ids:
                continue
            examined_ids.append(eid)
            st = (d.get("status") or "").lower()
            if st == "paid" or d.get("paid_date"):
                paid_total += 1
                if d.get("paid_date") and (
                    not last_paid_date or str(d["paid_date"]) > last_paid_date
                ):
                    last_paid_date = str(d.get("paid_date"))
            elif st in ("open", "overdue", "pending"):
                open_total += 1
                if d.get("due_date") and (
                    not next_due_date or str(d["due_date"]) < next_due_date
                ):
                    next_due_date = str(d.get("due_date"))
            if d.get("synced_at") and (
                not last_sync_at or str(d["synced_at"]) > last_sync_at
            ):
                last_sync_at = str(d.get("synced_at"))

    # Se cliente tem status=paid no histórico mas nenhum upcoming,
    # calcula próxima data de vencimento estimada pelo due_day.
    if not next_due_date and paid_total > 0:
        try:
            today = datetime.now(timezone.utc).date()
            due_day = int(subscriber.get("due_day") or 0)
            if due_day and 1 <= due_day <= 28:
                from calendar import monthrange
                month = today.month + (1 if today.day >= due_day else 0)
                year = today.year + (1 if month > 12 else 0)
                month = ((month - 1) % 12) + 1
                day = min(due_day, monthrange(year, month)[1])
                next_due_date = f"{year:04d}-{month:02d}-{day:02d}"
        except Exception:
            pass

    out["paid_count"] = paid_total
    out["open_count"] = open_total
    out["last_paid_date"] = last_paid_date
    out["next_due_date"] = next_due_date
    out["last_sync_at"] = last_sync_at
    out["checks"].append({"check": "primary_count", "ok": True,
                            "paid": paid_total, "open": open_total})

    # CHECK 3 — Conferência cross (sync staleness)
    sync_stale_h: Optional[float] = None
    if last_sync_at:
        try:
            ts = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            sync_stale_h = round(
                (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 1)
        except Exception:
            pass
    out["sync_stale_h"] = sync_stale_h
    SYNC_FRESH_MAX_H = 24.0
    if sync_stale_h is None and paid_total + open_total == 0:
        out["warnings"].append("no_invoices_no_sync_data")
    elif sync_stale_h is not None and sync_stale_h > SYNC_FRESH_MAX_H:
        out["warnings"].append(
            f"sync_stale:{sync_stale_h:.1f}h>{SYNC_FRESH_MAX_H}h")
    out["checks"].append({"check": "sync_freshness", "ok":
                            sync_stale_h is not None
                            and sync_stale_h <= SYNC_FRESH_MAX_H,
                            "stale_h": sync_stale_h})

    # Audit pass: cliente identificado + sync fresco + dados coerentes
    out["audit_passed"] = (
        bool(ext_num or ext_str)
        and (sync_stale_h is None or sync_stale_h <= SYNC_FRESH_MAX_H)
        and (paid_total > 0 or open_total > 0)
    )

    # P0 CEO 17/02/2026 — Persiste claim factual padrão institucional
    # em `isabella_factual_claims`. Mantém também o doc legado
    # `isabella_financial_audit` durante migração para retrocompat.
    try:
        from services import isabella_factual_claims as _fc
        evidence = {
            "subscriber_external_id": out["subscriber_external_id"],
            "subscriber_name": out["subscriber_name"],
            "paid_count": paid_total,
            "open_count": open_total,
            "last_paid_date": last_paid_date,
            "next_due_date": next_due_date,
            "last_sync_at": last_sync_at,
        }
        claim_doc = await _fc.claim(
            domain=_fc.ClaimDomain.FINANCIAL,
            entity_type="subscriber",
            entity_id=subscriber.get("id"),
            company_id=cid,
            checks=out["checks"],
            warnings=out["warnings"],
            evidence=evidence,
        )
        out["evidence_id"] = claim_doc.get("id")
        # Sobrescreve o audit_passed com o do claim (mesma lógica
        # estrita: checks_ok + zero_warnings)
        out["audit_passed"] = claim_doc.get("audit_passed", out["audit_passed"])
    except Exception:
        pass

    # Legado (retrocompat — remover após Sprint 5)
    try:
        await db.isabella_financial_audit.insert_one({**out})
    except Exception:
        pass

    return out


async def _list_open_invoices(cid: str,
                                subscriber: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lista faturas em aberto cruzando por `subscriber_external_id`."""
    # Junção: subscriber.external_code <-> subscriber_invoices.subscriber_external_id
    ext_id = subscriber.get("external_code") or subscriber.get("id_assinante")
    if not ext_id:
        return []
    ext_id_str = str(ext_id).strip()
    # Remove prefixos comuns: "ATLAZ-1234" → "1234"
    if "-" in ext_id_str:
        tail = ext_id_str.rsplit("-", 1)[-1]
        if tail.isdigit():
            ext_id_str = tail
    # Tenta tanto string quanto sem prefixo
    OPEN_STATUSES = ["open", "pending", "overdue", "aberto", "pendente",
                       "atrasado", "vencido", "em_aberto", "PENDENTE",
                       "ABERTO", "ATRASADO", None]
    q = {
        "company_id": cid,
        "subscriber_external_id": ext_id_str,
        "$or": [
            {"status": {"$in": OPEN_STATUSES}},
            {"paid": {"$ne": True}},
        ],
    }
    docs = await db.subscriber_invoices.find(q, {"_id": 0}) \
        .sort("due_date", 1).to_list(50)
    result = []
    for d in docs:
        paid = d.get("paid") or (d.get("status") or "").lower() in (
            "paid", "pago", "quitado", "settled", "cancelled", "cancelado"
        )
        # Se tem paid_date preenchido, considera pago
        if d.get("paid_date"):
            paid = True
        if not paid:
            result.append(d)
    return result


def _inv_pick(inv: Dict[str, Any], *keys: str) -> Any:
    """Pega 1º valor não-vazio entre N chaves. Procura no nível raiz
    (schema normalizado por `_norm_invoice` no `atlaz_financeiro.py`)
    E em `raw.*` (fallback p/ docs antigos). Aceita 0 como vazio."""
    raw = inv.get("raw") if isinstance(inv.get("raw"), dict) else {}
    for k in keys:
        v = inv.get(k)
        if v not in (None, "", 0, 0.0):
            return v
        v = raw.get(k) if raw else None
        if v not in (None, "", 0, 0.0):
            return v
    return None


def format_invoices_message(subscriber: Dict[str, Any],
                              invoices: List[Dict[str, Any]],
                              audit: Optional[Dict[str, Any]] = None
                              ) -> str:
    """Mensagem WhatsApp formatada (best practices ISP/BR · CTO 17/02/2026).

    Inclui no texto:
      - Status visual (🟢/🟡/🔴) por urgência de vencimento.
      - Valor original + valor com juros (quando vencida e Atlaz retorna).
      - Descrição da cobrança (mensalidade, multa, avulso etc).
      - Link clicável do boleto online.
      - Linha digitável formatada (padrão FEBRABAN) para internet banking.
      - PIX copia-e-cola **quando disponível** no payload Atlaz.
      - Orientação proativa de negociação para vencidas >15 dias.
      - Disclaimer pós-pagamento (até 1 dia útil pra compensar).

    O PDF anexo branded continua sendo enviado em paralelo via
    `_deliver_boleto_with_pdf` no caller (whatsapp_baileys.py).

    REGRA CEO 17/02/2026: quando `invoices=[]` (cliente "em dia"),
    exige `audit.audit_passed=True` + exibe evidência (última fatura paga +
    próximo vencimento). Sem prova auditável, NÃO afirma "em dia".
    """
    name = (subscriber.get("name") or "").split()[0] or "cliente"
    if not invoices:
        # REGRA DURA CEO: só afirma "em dia" se auditoria passou
        a = audit or {}
        if not a.get("audit_passed"):
            return (
                f"Oi, {name}. 💙\n\n"
                f"Vou conferir aqui no nosso sistema o status do seu "
                f"cadastro com calma. Só um instante — qualquer "
                f"divergência, eu te aviso imediatamente."
            )
        last_paid = a.get("last_paid_date") or ""
        next_due = a.get("next_due_date") or ""
        paid_count = a.get("paid_count") or 0

        def _fmt_dt(s: str) -> str:
            try:
                return datetime.fromisoformat(
                    str(s).replace("Z", "+00:00").replace(" ", "T")
                ).strftime("%d/%m/%Y")
            except Exception:
                return str(s)[:10]
        evid: List[str] = []
        if last_paid:
            evid.append(f"✅ Última fatura paga em *{_fmt_dt(last_paid)}*")
        elif paid_count > 0:
            evid.append(f"✅ {paid_count} fatura(s) já quitada(s) no histórico")
        if next_due:
            evid.append(f"📅 Próxima fatura vence em *{_fmt_dt(next_due)}*")
        evid_block = "\n".join(evid) if evid else (
            "✅ Nenhuma fatura em aberto no cadastro")
        return (
            f"Oba, {name}! 🎉\n\n"
            f"Verifiquei aqui no sistema e *você está em dia* com a Ligo:\n\n"
            f"{evid_block}\n\n"
            f"Se algo não bate com seu controle pessoal, me avisa que "
            f"eu confiro de novo — pode ser cobrança de outro serviço."
        )

    qty = len(invoices)
    qty_label = "fatura" if qty == 1 else "faturas"
    total_original = sum(float(i.get("amount") or 0) for i in invoices)
    total_atualizado = 0.0
    has_overdue = False
    max_days_overdue = 0
    for inv in invoices:
        try:
            v_juros = float(_inv_pick(
                inv, "amount_with_interest", "valor_com_juros") or 0) \
                or float(inv.get("amount") or 0)
        except (TypeError, ValueError):
            v_juros = float(inv.get("amount") or 0)
        total_atualizado += v_juros
        due = inv.get("due_date")
        if due:
            try:
                d = datetime.fromisoformat(
                    str(due).replace("Z", "+00:00")).date()
                delta = (d - datetime.now(timezone.utc).date()).days
                if delta < 0:
                    has_overdue = True
                    max_days_overdue = max(max_days_overdue, abs(delta))
            except Exception:
                pass

    parts: List[str] = []
    parts.append("*Sua 2ª via — Ligo Fibra* 💚")
    parts.append("")
    parts.append(f"Olá, {name}! Encontrei *{qty} {qty_label}* em aberto "
                 f"no seu cadastro:")
    parts.append("")

    for idx, inv in enumerate(invoices, 1):
        desc = (_inv_pick(inv, "description", "descricao")
                or "Cobrança")
        desc = str(desc).strip().rstrip("*").strip()  # sanitiza asterisco residual
        valor_original = _format_brl(inv.get("amount"))
        emoji, label = _status_emoji_and_label(inv.get("due_date"))
        venc_date = ""
        if inv.get("due_date"):
            try:
                d = datetime.fromisoformat(
                    str(inv["due_date"]).replace("Z", "+00:00"))
                venc_date = d.strftime("%d/%m/%Y")
            except Exception:
                venc_date = str(inv["due_date"])[:10]
        header = (f"📄 *Fatura {idx}/{qty} — {desc}*" if qty > 1
                  else f"📄 *{desc}*")
        parts.append(header)
        parts.append(f"💵 Valor original: *{valor_original}*")
        if venc_date:
            label_full = f" ({label})" if label else ""
            parts.append(f"📅 Vencimento: {venc_date} {emoji}{label_full}")

        # Valor atualizado (juros + multa) — Atlaz V2 retorna `amount_with_interest`
        # (normalizado em `atlaz_financeiro._norm_invoice`).
        v_atualizado = _inv_pick(inv, "amount_with_interest",
                                   "valor_com_juros")
        try:
            v_atualizado_f = float(v_atualizado or 0)
            v_original_f = float(inv.get("amount") or 0)
        except (TypeError, ValueError):
            v_atualizado_f = 0.0
            v_original_f = 0.0
        if (v_atualizado_f > 0 and v_original_f > 0
                and abs(v_atualizado_f - v_original_f) > 0.01):
            multa = _inv_pick(inv, "fine_value", "multa") or 0
            juros = _inv_pick(inv, "interest_value", "juros") or 0
            extra = []
            try:
                if float(multa) > 0:
                    extra.append(f"multa R$ {float(multa):.2f}")
            except (TypeError, ValueError):
                pass
            try:
                if float(juros) > 0:
                    extra.append(f"juros R$ {float(juros):.2f}")
            except (TypeError, ValueError):
                pass
            suffix = f" ({' + '.join(extra)})" if extra else ""
            parts.append(f"💰 *Valor atualizado: "
                         f"{_format_brl(v_atualizado_f)}*{suffix}")

        link = _inv_pick(inv, "boleto_url", "link")
        if link:
            parts.append("🔗 Boleto online:")
            parts.append(str(link))
        ld = _format_linha_digitavel(
            _inv_pick(inv, "barcode", "linha_digitavel"))
        if ld:
            parts.append("🧾 Linha digitável:")
            parts.append(f"`{ld}`")
        # PIX copia-e-cola — Atlaz V2 retorna `pix_brcode` (normalizado
        # em `atlaz_financeiro._norm_invoice` com `retornar_pix=1`).
        pix_code = _inv_pick(inv, "pix_brcode", "pix_copia_cola",
                              "pix_emv", "pix")
        if pix_code and len(str(pix_code)) > 30:
            parts.append("⚡ *PIX copia-e-cola:*")
            parts.append(f"`{pix_code}`")
        # QR Code do PIX (link de imagem) — quando Atlaz expõe
        pix_qr = _inv_pick(inv, "pix_qrcode_link", "pix_qrcode")
        if pix_qr and not pix_code:
            # Só anuncia o QR se NÃO temos o copia-e-cola
            parts.append(f"📱 QR Code PIX: {pix_qr}")
        parts.append("")

    if qty > 1:
        parts.append(f"💵 *Total original: {_format_brl(total_original)}*")
        if abs(total_atualizado - total_original) > 0.01:
            parts.append(f"💰 *Total atualizado: "
                         f"{_format_brl(total_atualizado)}*")
        parts.append("")

    parts.append("📎 Também estou enviando o(s) PDF(s) logo abaixo, prontos "
                 "pra pagar pelo app do banco. ")

    # Orientação proativa de negociação
    if has_overdue and max_days_overdue >= 15:
        parts.append("")
        parts.append(f"⚠️ Há fatura vencida há {max_days_overdue} dias. Se "
                     f"quiser *negociar ou parcelar*, é só me dizer "
                     f"\"quero negociar\" que eu te encaminho pro time "
                     f"financeiro. 💙")
    elif has_overdue:
        parts.append("")
        parts.append("ℹ️ Após o pagamento, a compensação leva até "
                     "*1 dia útil* pra cair no nosso sistema.")

    parts.append("")
    parts.append("Qualquer dúvida é só me chamar! 💙")
    return "\n".join(parts)


async def handle_boleto_flow(cid: str, phone: str, text: str,
                                subscriber_id: Optional[str] = None) -> Optional[str]:
    """Processa intenção de boleto e retorna texto pronto pra enviar.

    Retorna `None` quando:
      - Não há intenção de boleto na msg
      - Cliente está aguardando informar CPF (próxima msg)

    Quando retorna string, é o texto FINAL que deve ser enviado ao WhatsApp.
    """
    # 1. Verifica se o cliente já estava aguardando CPF na conversa anterior
    state = await db.boleto_flow_state.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0}
    )
    awaiting_cpf = bool(state and state.get("awaiting_cpf"))

    cpf_detected = extract_cpf(text) if awaiting_cpf else None
    has_intent = detect_boleto_intent(text)

    if not has_intent and not awaiting_cpf:
        return None  # Nada a fazer

    subscriber = None

    # 2. Tenta achar pelo telefone primeiro
    if subscriber_id:
        subscriber = await db.subscribers.find_one(
            {"company_id": cid, "id": subscriber_id}, {"_id": 0}
        )
    if not subscriber:
        subscriber = await _find_subscriber_by_phone(cid, phone)

    # 3. Se cliente respondeu com CPF e estamos esperando, busca por CPF
    if not subscriber and cpf_detected:
        subscriber = await _find_subscriber_by_cpf(cid, cpf_detected)

    # 4. Cliente ainda não localizado
    if not subscriber:
        if awaiting_cpf and not cpf_detected:
            # já pedimos antes e ele mandou algo que não é CPF
            return (
                "Hmm, não consegui identificar seu CPF nessa mensagem 🤔\n\n"
                "Pode me enviar apenas os 11 dígitos do CPF, por favor?\n"
                "_Exemplo:_ `12345678900`\n\n"
                "Se preferir, vou transferir você para um atendente humano. 💙"
            )
        # primeira vez sem encontrar pelo telefone → pede CPF
        await db.boleto_flow_state.update_one(
            {"company_id": cid, "phone": phone},
            {"$set": {
                "awaiting_cpf": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return (
            "Oi! 👋 Pra eu localizar seu cadastro e te enviar o boleto, "
            "pode me informar seu *CPF*, por favor?\n\n"
            "_Pode mandar só os 11 dígitos (sem pontos ou traços)._"
        )

    # 5. Cliente localizado — limpa estado e busca faturas
    await db.boleto_flow_state.delete_one({"company_id": cid, "phone": phone})

    invoices = await _list_open_invoices(cid, subscriber)
    audit = await _audit_subscriber_financial_status(cid, subscriber)
    return format_invoices_message(subscriber, invoices, audit=audit)


async def handle_boleto_flow_full(cid: str, phone: str, text: str,
                                    subscriber_id: Optional[str] = None
                                    ) -> Optional[Dict[str, Any]]:
    """Versão "full" — retorna dict com texto + invoices + subscriber pra
    que o caller possa enviar tanto o texto quanto os PDFs anexos.

    Retorna `None` se não há intenção de boleto OU se precisamos pedir CPF
    (nesse caso, o texto de pedido de CPF vai em `{"text": "...", "is_request": True}`).
    """
    state = await db.boleto_flow_state.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0}
    )
    awaiting_cpf = bool(state and state.get("awaiting_cpf"))
    cpf_detected = extract_cpf(text) if awaiting_cpf else None
    has_intent = detect_boleto_intent(text)

    if not has_intent and not awaiting_cpf:
        return None

    subscriber = None
    if subscriber_id:
        subscriber = await db.subscribers.find_one(
            {"company_id": cid, "id": subscriber_id}, {"_id": 0}
        )
    if not subscriber:
        subscriber = await _find_subscriber_by_phone(cid, phone)
    if not subscriber and cpf_detected:
        subscriber = await _find_subscriber_by_cpf(cid, cpf_detected)

    if not subscriber:
        if awaiting_cpf and not cpf_detected:
            return {"text": (
                "Hmm, não consegui identificar seu CPF nessa mensagem 🤔\n\n"
                "Pode me enviar apenas os 11 dígitos do CPF, por favor?\n"
                "_Exemplo:_ `12345678900`\n\n"
                "Se preferir, vou transferir você para um atendente humano. 💙"
            ), "invoices": [], "subscriber": None, "is_request": True}
        await db.boleto_flow_state.update_one(
            {"company_id": cid, "phone": phone},
            {"$set": {
                "awaiting_cpf": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return {"text": (
            "Oi! 👋 Pra eu localizar seu cadastro e te enviar o boleto, "
            "pode me informar seu *CPF*, por favor?\n\n"
            "_Pode mandar só os 11 dígitos (sem pontos ou traços)._"
        ), "invoices": [], "subscriber": None, "is_request": True}

    await db.boleto_flow_state.delete_one({"company_id": cid, "phone": phone})
    invoices = await _list_open_invoices(cid, subscriber)
    audit = await _audit_subscriber_financial_status(cid, subscriber)
    return {
        "text": format_invoices_message(subscriber, invoices, audit=audit),
        "invoices": invoices,
        "subscriber": subscriber,
        "audit": audit,
        "is_request": False,
    }
