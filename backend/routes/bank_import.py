"""Importação de extrato bancário (Sicoob/OFX) com classificação IA.

Fluxo:
  1. Usuário envia arquivo OFX (ou CSV) via POST /upload.
  2. Backend parseia transações, dedup por hash (data+valor+desc).
  3. Para cada transação:
     a) Consulta `bank_import_memory` por padrão aprendido (cpf/cnpj +
        nomenclatura). Se match → usa sugestão da memória direto.
     b) Caso contrário → envia ao Claude Sonnet 4.5 (Emergent Universal Key)
        com lista de fornecedores e categorias da empresa pra classificar.
  4. Retorna `staging_id` + lista de linhas com sugestões editáveis.
  5. Usuário ajusta na UI, clica "Confirmar todos" → POST /confirm gera
     `fin_cash_movements` + atualiza memória pra próximas vezes.

Coleções:
  • bank_import_staging — preview com lista de transações
  • bank_import_memory  — padrões aprendidos por (cnpj/cpf, key)
  • bank_import_history — histórico de imports concluídos
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso
from database import db
from routes.financeiro import require_finance

logger = logging.getLogger("ponto.bank_import")
router = APIRouter(prefix="/api/financeiro/bank-import",
                       tags=["financeiro", "bank_import"])


# ---------------------------------------------------------------------------
# Helpers — normalização e detecção de CPF/CNPJ
# ---------------------------------------------------------------------------
CPF_RE = re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b")
CNPJ_RE = re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})\b")


def _strip_accent(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                       if unicodedata.category(c) != "Mn")


def _norm_text(s: str) -> str:
    """Normaliza descrição: lower, sem acento, sem números, sem pontuação."""
    if not s:
        return ""
    out = _strip_accent(s).lower()
    out = re.sub(r"[0-9]+", " ", out)
    out = re.sub(r"[^\w\s]", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    # Limita a 60 chars pra match de padrão
    return out[:60]


def _extract_doc(text: str) -> Optional[str]:
    """Retorna primeiro CPF/CNPJ encontrado, só dígitos, ou None."""
    if not text:
        return None
    m = CNPJ_RE.search(text)
    if m:
        return re.sub(r"\D", "", m.group(0))
    m = CPF_RE.search(text)
    if m:
        return re.sub(r"\D", "", m.group(0))
    return None


def _tx_hash(date: str, amount: float, desc: str) -> str:
    h = f"{date}|{amount:.2f}|{(desc or '')[:80]}"
    return hashlib.sha1(h.encode("utf-8")).hexdigest()[:16]


def _safe_date(dt: Any) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            return dt[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Parser OFX (Sicoob)
# ---------------------------------------------------------------------------
def _parse_ofx_bytes(data: bytes) -> List[Dict[str, Any]]:
    """Extrai transações de um arquivo OFX. Retorna lista de dicts."""
    from ofxparse import OfxParser
    f = io.BytesIO(data)
    try:
        ofx = OfxParser.parse(f)
    except Exception as e:
        raise HTTPException(400, f"OFX inválido: {e}")
    out: List[Dict[str, Any]] = []
    for account in (ofx.accounts or []):
        st = getattr(account, "statement", None)
        if not st:
            continue
        for tx in (getattr(st, "transactions", None) or []):
            amount = float(getattr(tx, "amount", 0) or 0)
            desc = (getattr(tx, "memo", None)
                       or getattr(tx, "payee", None)
                       or getattr(tx, "type", None) or "").strip()
            out.append({
                "date": _safe_date(getattr(tx, "date", None)),
                "amount": abs(amount),
                "type": "income" if amount > 0 else "expense",
                "description": desc[:300],
                "ofx_id": str(getattr(tx, "id", "") or "")[:64],
            })
    return out


def _parse_csv_bytes(data: bytes) -> List[Dict[str, Any]]:
    """Parser CSV genérico Sicoob — colunas Data, Histórico, Valor.

    Tenta detectar separador (`;` ou `,`) e formato de data BR/ISO.
    """
    import csv
    text = data.decode("utf-8", errors="ignore")
    # Detecta separador
    sep = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=sep)
    out: List[Dict[str, Any]] = []
    for row in reader:
        # Tenta mapear colunas comuns
        keys = {k.lower().strip(): k for k in row.keys() if k}
        date_k = next((keys[k] for k in keys if "data" in k), None)
        desc_k = next((keys[k] for k in keys if "histor" in k or "descr" in k
                          or "lanc" in k), None)
        val_k = next((keys[k] for k in keys if "valor" in k or "vlr" in k), None)
        if not date_k or not val_k:
            continue
        raw_val = (row.get(val_k) or "").strip().replace(".", "").replace(",", ".")
        try:
            v = float(raw_val)
        except ValueError:
            continue
        # Data BR: DD/MM/YYYY ou ISO
        d = (row.get(date_k) or "").strip()
        if "/" in d:
            try:
                dt = datetime.strptime(d[:10], "%d/%m/%Y")
                d = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        else:
            d = _safe_date(d)
        desc = (row.get(desc_k) if desc_k else "").strip()
        out.append({
            "date": d,
            "amount": abs(v),
            "type": "income" if v > 0 else "expense",
            "description": desc[:300],
            "ofx_id": "",
        })
    return out


# ---------------------------------------------------------------------------
# Classificação — memória + IA
# ---------------------------------------------------------------------------
async def _load_refs(cid: str) -> Dict[str, Any]:
    """Carrega fornecedores + categorias da empresa para sugerir."""
    suppliers = await db.fin_suppliers.find(
        {"company_id": cid, "active": True}, {"_id": 0}).to_list(2000)
    categories = await db.fin_categories.find(
        {"company_id": cid, "active": True}, {"_id": 0}).to_list(2000)
    return {"suppliers": suppliers, "categories": categories}


async def _lookup_memory(cid: str, doc: Optional[str],
                              key: str) -> Optional[Dict[str, Any]]:
    """Procura padrão aprendido. Prioridade: CPF/CNPJ exato → key normalizada."""
    if doc:
        m = await db.bank_import_memory.find_one(
            {"company_id": cid, "doc": doc}, {"_id": 0})
        if m:
            return m
    if key:
        m = await db.bank_import_memory.find_one(
            {"company_id": cid, "doc": None, "key": key}, {"_id": 0})
        if m:
            return m
    return None


async def _save_memory(cid: str, doc: Optional[str], key: str,
                              type_: str, supplier_id: Optional[str],
                              category_id: Optional[str]) -> None:
    """Salva/atualiza padrão aprendido. Incrementa hit_count."""
    flt = {"company_id": cid, "doc": doc, "key": key} if doc else \
          {"company_id": cid, "doc": None, "key": key}
    upd = {
        "$set": {
            "type": type_,
            "supplier_id": supplier_id,
            "category_id": category_id,
            "updated_at": now_iso(),
        },
        "$inc": {"hit_count": 1},
        "$setOnInsert": {
            "id": f"bim-{uuid.uuid4().hex[:10]}",
            "created_at": now_iso(),
            "company_id": cid, "doc": doc, "key": key,
        },
    }
    await db.bank_import_memory.update_one(flt, upd, upsert=True)


async def _ai_classify_batch(cid: str, txs: List[Dict[str, Any]],
                                 refs: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Classifica lote de transações via Claude Sonnet 4.5.

    Retorna dict {idx: {type, supplier_id, category_id, confidence, reason}}.
    """
    if not txs:
        return {}
    if not EMERGENT_LLM_KEY:
        return {}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        suppliers_str = "\n".join(
            f"- {s['id']}: {s['name']}"
            + (f" ({s.get('cnpj','')})" if s.get("cnpj") else "")
            for s in refs["suppliers"][:60]
        ) or "(sem fornecedores cadastrados)"
        categories_str = "\n".join(
            f"- {c['id']}: {c['name']} ({c.get('type', 'expense')})"
            for c in refs["categories"][:60]
        ) or "(sem categorias cadastradas)"
        # Lista de transações em JSON compacto
        tx_lines = []
        for i, t in enumerate(txs):
            tx_lines.append(
                f"{i}|{t['date']}|{t['type']}|R${t['amount']:.2f}|{t['description'][:140]}"
            )
        prompt = (
            "Você é um classificador financeiro de extrato bancário "
            "para um provedor de internet brasileiro. Para cada transação "
            "abaixo, decida:\n"
            "- type: 'income' (entrada) ou 'expense' (saída) - já vem "
            "pre-classificado pelo sinal do valor, MAS revise se faz "
            "sentido pela descrição (PIX REM = recebido, PIX ENV = enviado).\n"
            "- supplier_id: id do fornecedor mais provável (da lista) ou null.\n"
            "- category_id: id da categoria mais provável (da lista) ou null.\n"
            "- confidence: 0.0-1.0 (sua certeza).\n"
            "- reason: 1 frase curta em PT-BR explicando.\n\n"
            f"FORNECEDORES CADASTRADOS:\n{suppliers_str}\n\n"
            f"CATEGORIAS CADASTRADAS:\n{categories_str}\n\n"
            "TRANSAÇÕES (idx|data|tipo|valor|descrição):\n"
            + "\n".join(tx_lines)
            + "\n\nResponda APENAS em JSON válido neste formato:\n"
            "{\"items\": [{\"idx\": 0, \"type\": \"expense\", "
            "\"supplier_id\": \"sup-xxx\" ou null, "
            "\"category_id\": \"cat-xxx\" ou null, "
            "\"confidence\": 0.85, \"reason\": \"...\"}]}"
        )
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"bank-import-{cid}-{uuid.uuid4().hex[:6]}",
            system_message="Você responde APENAS em JSON válido.",
        ).with_model("anthropic", "claude-sonnet-4-5")
        resp = await chat.send_message(UserMessage(text=prompt))
        # Limpa markdown se houver
        text = (resp or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text,
                              flags=re.MULTILINE)
        data = json.loads(text)
        out: Dict[int, Dict[str, Any]] = {}
        for it in data.get("items", []):
            idx = it.get("idx")
            if isinstance(idx, int) and 0 <= idx < len(txs):
                out[idx] = {
                    "type": it.get("type") or txs[idx]["type"],
                    "supplier_id": it.get("supplier_id"),
                    "category_id": it.get("category_id"),
                    "confidence": float(it.get("confidence") or 0.5),
                    "reason": (it.get("reason") or "")[:200],
                }
        return out
    except Exception as e:
        logger.warning("[bank-import] IA classify falhou: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class StagingTxOut(BaseModel):
    idx: int
    date: str
    amount: float
    type: str
    description: str
    doc: Optional[str] = None  # CPF/CNPJ extraído
    key: str
    supplier_id: Optional[str] = None
    category_id: Optional[str] = None
    confidence: float = 0.0
    reason: Optional[str] = None
    source: str = "manual"  # 'memory' | 'ai' | 'manual'
    duplicate: bool = False  # já existe no caixa
    hash: str


class StagingResponse(BaseModel):
    staging_id: str
    file_name: str
    total: int
    new_count: int
    duplicate_count: int
    items: List[StagingTxOut]


class ConfirmItemIn(BaseModel):
    idx: int
    type: str = Field(..., pattern="^(income|expense)$")
    date: str
    amount: float = Field(..., gt=0)
    description: str
    cash_account_id: str
    supplier_id: Optional[str] = None
    category_id: Optional[str] = None
    skip: bool = False  # se True, ignora esta linha


class ConfirmIn(BaseModel):
    staging_id: str
    items: List[ConfirmItemIn]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=StagingResponse)
async def upload_extract(file: UploadFile = File(...),
                              user: dict = Depends(require_finance())):
    """Recebe arquivo OFX/CSV do Sicoob, parseia, classifica e devolve staging."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio")
    if len(raw) > 5_000_000:
        raise HTTPException(413, "Arquivo > 5 MB")
    fname = (file.filename or "extrato").lower()
    if fname.endswith(".ofx") or b"<OFX>" in raw[:200].upper():
        txs = _parse_ofx_bytes(raw)
    elif fname.endswith(".csv"):
        txs = _parse_csv_bytes(raw)
    else:
        raise HTTPException(415, "Suporte só para OFX e CSV por enquanto")
    if not txs:
        raise HTTPException(400, "Nenhuma transação encontrada no arquivo")

    # Carrega refs (fornecedores + categorias)
    refs = await _load_refs(cid)

    # Hashes pra detectar duplicatas
    hashes = [_tx_hash(t["date"], t["amount"], t["description"]) for t in txs]
    existing = await db.fin_cash_movements.find(
        {"company_id": cid, "import_hash": {"$in": hashes}},
        {"_id": 0, "import_hash": 1}).to_list(len(hashes))
    existing_set = {e["import_hash"] for e in existing}

    # Memória + IA: primeiro tenta memória, depois manda lote pra IA
    items: List[Dict[str, Any]] = []
    to_ai: List[int] = []  # indices que precisam IA
    for i, t in enumerate(txs):
        doc = _extract_doc(t["description"])
        key = _norm_text(t["description"])
        h = hashes[i]
        is_dup = h in existing_set
        base = {
            "idx": i, "date": t["date"], "amount": t["amount"],
            "type": t["type"], "description": t["description"],
            "doc": doc, "key": key, "hash": h, "duplicate": is_dup,
            "supplier_id": None, "category_id": None,
            "confidence": 0.0, "reason": None, "source": "manual",
        }
        if is_dup:
            items.append(base); continue
        mem = await _lookup_memory(cid, doc, key)
        if mem:
            base["type"] = mem.get("type") or t["type"]
            base["supplier_id"] = mem.get("supplier_id")
            base["category_id"] = mem.get("category_id")
            base["confidence"] = 0.95
            base["reason"] = (
                f"Padrão aprendido ({mem.get('hit_count', 1)} vez(es))")
            base["source"] = "memory"
            items.append(base); continue
        to_ai.append(i)
        items.append(base)

    # Lote pra IA (somente não-duplicadas sem memória)
    if to_ai:
        ai_txs = [txs[i] for i in to_ai]
        ai_results = await _ai_classify_batch(cid, ai_txs, refs)
        for local_idx, orig_idx in enumerate(to_ai):
            r = ai_results.get(local_idx)
            if not r:
                continue
            items[orig_idx]["type"] = r["type"]
            items[orig_idx]["supplier_id"] = r["supplier_id"]
            items[orig_idx]["category_id"] = r["category_id"]
            items[orig_idx]["confidence"] = r["confidence"]
            items[orig_idx]["reason"] = r["reason"]
            items[orig_idx]["source"] = "ai"

    staging_id = f"bsi-{uuid.uuid4().hex[:10]}"
    new_count = sum(1 for x in items if not x["duplicate"])
    dup_count = sum(1 for x in items if x["duplicate"])
    await db.bank_import_staging.insert_one({
        "id": staging_id, "company_id": cid, "file_name": file.filename,
        "created_at": now_iso(), "created_by": user.get("id"),
        "total": len(items), "new_count": new_count,
        "duplicate_count": dup_count, "items": items,
        "status": "preview",
    })
    return {
        "staging_id": staging_id, "file_name": file.filename or "extrato",
        "total": len(items), "new_count": new_count,
        "duplicate_count": dup_count, "items": items,
    }


@router.get("/staging/{staging_id}")
async def get_staging(staging_id: str,
                            user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await db.bank_import_staging.find_one(
        {"id": staging_id, "company_id": cid}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Staging não encontrado")
    return s


@router.post("/confirm")
async def confirm_import(payload: ConfirmIn,
                              user: dict = Depends(require_finance())):
    """Confirma o batch: gera fin_cash_movements + atualiza memória."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await db.bank_import_staging.find_one(
        {"id": payload.staging_id, "company_id": cid}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Staging não encontrado")
    if s.get("status") == "confirmed":
        raise HTTPException(409, "Importação já confirmada")
    # Mapeia idx→tx original (precisamos do hash + doc + key)
    orig_by_idx = {it["idx"]: it for it in (s.get("items") or [])}
    created = 0
    skipped = 0
    for it in payload.items:
        if it.skip:
            skipped += 1
            continue
        orig = orig_by_idx.get(it.idx)
        if not orig:
            continue
        if orig.get("duplicate"):
            skipped += 1
            continue
        cash_acc = await db.fin_cash_accounts.find_one(
            {"id": it.cash_account_id, "company_id": cid}, {"_id": 0})
        if not cash_acc:
            raise HTTPException(400,
                f"Conta caixa inválida (linha {it.idx + 1})")
        doc = {
            "id": f"mov-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "type": it.type, "date": it.date, "amount": it.amount,
            "description": it.description[:300],
            "category_id": it.category_id, "supplier_id": it.supplier_id,
            "cash_account_id": it.cash_account_id,
            "reference_type": "bank_import",
            "reference_id": payload.staging_id,
            "source": "bank_import_sicoob",
            "import_hash": orig.get("hash"),
            "created_at": now_iso(),
        }
        await db.fin_cash_movements.insert_one(doc)
        # Atualiza saldo
        delta = it.amount if it.type == "income" else -it.amount
        await db.fin_cash_accounts.update_one(
            {"id": it.cash_account_id, "company_id": cid},
            {"$inc": {"current_balance": delta},
             "$set": {"updated_at": now_iso()}},
        )
        # Aprende o padrão
        await _save_memory(cid, orig.get("doc"), orig.get("key"),
                                 it.type, it.supplier_id, it.category_id)
        created += 1

    await db.bank_import_staging.update_one(
        {"id": payload.staging_id, "company_id": cid},
        {"$set": {"status": "confirmed", "confirmed_at": now_iso(),
                   "confirmed_by": user.get("id"),
                   "created_count": created, "skipped_count": skipped}},
    )
    await db.bank_import_history.insert_one({
        "id": f"bih-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "staging_id": payload.staging_id,
        "file_name": s.get("file_name"), "created_at": now_iso(),
        "created_by": user.get("id"), "created_count": created,
        "skipped_count": skipped, "total": s.get("total"),
    })
    return {"ok": True, "created": created, "skipped": skipped}


@router.get("/history")
async def list_history(limit: int = 30,
                              user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.bank_import_history.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(min(limit, 100)).to_list(limit)
    return {"items": items}


@router.get("/memory")
async def list_memory(limit: int = 200,
                            user: dict = Depends(require_finance())):
    """Lista padrões aprendidos (CPF/CNPJ → fornecedor/categoria)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.bank_import_memory.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("hit_count", -1).limit(min(limit, 500)).to_list(limit)
    return {"items": items, "total": len(items)}


@router.delete("/memory/{mem_id}")
async def delete_memory(mem_id: str,
                              user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.bank_import_memory.delete_one(
        {"id": mem_id, "company_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Padrão não encontrado")
    return {"ok": True}
