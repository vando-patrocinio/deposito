"""Central de Compras — registro de compras de material com fluxo:

    COMPRA → ENTRADA NO ESTOQUE (Praça + responsável) → TÉCNICO → CLIENTE

Apenas:
- Administradores, gestores e super admin: veem TODAS as compras de TODAS
  as praças e podem confirmar entrada no estoque.
- Almoxarifes (collaborator com cargo=ALMOXARIFE + warehouse_praca_id):
  veem e lançam SOMENTE compras da própria praça.

Entrada do lançamento pode ser:
- Manual (form preenchido)
- Por upload de arquivo (PDF/XLS/DOC/JPG/PNG) → IA Claude extrai os dados.

Após confirmado, integra-se ao módulo `stok`:
- ONT: gera entrada em `stok_onts` (compatível com fluxo existente)
- Insumo: incrementa estoque do insumo na praça
- Outros: apenas registra (sem afetar `stok_*`)
"""
from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

import cargo as cargo_mod
from core import (
    DEMO_COMPANY_ID,
    get_current_user,
    is_super_admin,
    now_iso,
    require_role,
)
from database import db

logger = logging.getLogger("ponto.purchases")

router = APIRouter(prefix="/api/purchases", tags=["purchases"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
PURCHASE_TYPES = ("ont", "insumo", "equipamento", "outros")


class PurchaseItem(BaseModel):
    description: str
    quantity: float = 1
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    type: Optional[str] = None  # ont|insumo|equipamento|outros (por item)
    macs: Optional[List[str]] = None  # se tipo=ont, MACs


class PurchaseCreate(BaseModel):
    type: str = Field(..., description="ont|insumo|equipamento|outros")
    praca_id: str
    responsible_collaborator_id: str
    supplier_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None  # YYYY-MM-DD
    total_value: Optional[float] = None
    items: List[PurchaseItem] = []
    notes: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None


class PurchaseConfirmIn(BaseModel):
    purchase_id: str


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------
def _is_admin_like(user: dict) -> bool:
    return is_super_admin(user) or user.get("role") in (
        "administrador", "gestor", "auditor",
    )


async def _resolve_user_praca(user: dict) -> Optional[str]:
    """Se o user logado é colaborador almoxarife, retorna a praça vinculada."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if _is_admin_like(user):
        return None  # admin/gestor: sem restrição de praça
    coll = await db.collaborators.find_one(
        {"company_id": cid, "user_id": user.get("id")},
        {"_id": 0, "cargo": 1, "warehouse_praca_id": 1},
    )
    if not coll:
        return None
    if coll.get("cargo") != cargo_mod.ALMOXARIFE:
        return None
    return coll.get("warehouse_praca_id")


def _require_purchase_access(user: dict) -> None:
    """Lança 403 se o user não pode acessar a Central de Compras."""
    if _is_admin_like(user):
        return
    # Almoxarifes acessam (a verificação de praça é feita por query)
    if user.get("role") in ("financeiro",):
        return
    # Demais: bloqueia
    raise HTTPException(403, "Sem permissão para Central de Compras")


def _normalize_mac(s: str) -> str:
    s = re.sub(r"[^0-9A-Fa-f]", "", s or "").upper()
    return ":".join(s[i:i + 2] for i in range(0, len(s), 2)) if s else ""


# ---------------------------------------------------------------------------
# Routes — Listing
# ---------------------------------------------------------------------------
@router.get("")
async def list_purchases(
    user: dict = Depends(get_current_user),
    praca_id: Optional[str] = None,
    status: Optional[str] = None,
    type_: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    _require_purchase_access(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}

    # Almoxarife só vê própria praça
    user_praca = await _resolve_user_praca(user)
    if user_praca:
        q["praca_id"] = user_praca
    elif praca_id:
        q["praca_id"] = praca_id
    if status:
        q["status"] = status
    if type_:
        q["type"] = type_

    docs = await db.purchases.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(min(limit, 500)).to_list(500)

    # Enrich com nomes de praça/responsável
    if docs:
        praca_ids = {d.get("praca_id") for d in docs if d.get("praca_id")}
        coll_ids = {d.get("responsible_collaborator_id") for d in docs
                     if d.get("responsible_collaborator_id")}
        pracas = {p["id"]: p["name"] async for p in db.fin_filiais.find(
            {"id": {"$in": list(praca_ids)}}, {"_id": 0, "id": 1, "name": 1})}
        colls = {c["id"]: c["name"] async for c in db.collaborators.find(
            {"id": {"$in": list(coll_ids)}}, {"_id": 0, "id": 1, "name": 1})}
        for d in docs:
            d["praca_name"] = pracas.get(d.get("praca_id"), "—")
            d["responsible_name"] = colls.get(
                d.get("responsible_collaborator_id"), "—")
    return {
        "items": docs,
        "is_warehouse_keeper": user_praca is not None,
        "user_praca_id": user_praca,
    }


@router.get("/refs")
async def get_refs(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Retorna praças, responsáveis (almoxarifes), fornecedores existentes
    e tipos para autocomplete no form."""
    _require_purchase_access(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pracas = await db.fin_filiais.find(
        {"company_id": cid, "active": {"$ne": False}}, {"_id": 0}
    ).sort("name", 1).to_list(200)
    colls = await db.collaborators.find(
        {"company_id": cid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "cargo": 1,
          "warehouse_praca_id": 1},
    ).sort("name", 1).to_list(500)
    suppliers = await db.fin_suppliers.find(
        {"company_id": cid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "document": 1, "cnpj": 1},
    ).sort("name", 1).to_list(500)
    return {"pracas": pracas, "collaborators": colls,
             "suppliers": suppliers,
             "types": list(PURCHASE_TYPES)}


def _norm_supplier(name: str) -> str:
    """Normaliza nome de fornecedor para busca fuzzy."""
    import unicodedata
    s = (name or "").strip().upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                  if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(LTDA|ME|EPP|S/A|SA|EIRELI|MEI)\b", "", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    return s


async def _find_or_create_supplier(
    cid: str, name: str, user_email: str,
) -> Optional[str]:
    """Encontra fornecedor por nome normalizado; se não existir, cria.

    Retorna o `id` do fornecedor (ou None se nome vazio).
    """
    name = (name or "").strip()
    if not name:
        return None
    norm = _norm_supplier(name)
    if not norm:
        return None
    # Busca exata primeiro
    existing = await db.fin_suppliers.find_one(
        {"company_id": cid, "name": name}, {"_id": 0, "id": 1})
    if existing:
        return existing["id"]
    # Busca normalizada (compara em memória — fin_suppliers é pequena)
    async for s in db.fin_suppliers.find(
            {"company_id": cid}, {"_id": 0, "id": 1, "name": 1}):
        if _norm_supplier(s.get("name", "")) == norm:
            return s["id"]
    # Cria
    new_id = f"fsup-{uuid.uuid4().hex[:10]}"
    await db.fin_suppliers.insert_one({
        "id": new_id,
        "company_id": cid,
        "name": name[:200],
        "active": True,
        "created_at": now_iso(),
        "created_by": user_email,
        "auto_created_from": "central_compras",
    })
    logger.info("[purchases] fornecedor auto-criado: %s (%s) cid=%s",
                  name, new_id, cid)
    return new_id


# ---------------------------------------------------------------------------
# Routes — Manual create
# ---------------------------------------------------------------------------
@router.post("")
async def create_purchase(
    payload: PurchaseCreate,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_purchase_access(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if payload.type not in PURCHASE_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use: {PURCHASE_TYPES}")

    # Almoxarife: força praça dele
    user_praca = await _resolve_user_praca(user)
    if user_praca and payload.praca_id != user_praca:
        raise HTTPException(403, "Você só pode lançar compras da sua praça")

    pid = f"pur-{uuid.uuid4().hex[:10]}"
    # Resolve/cria fornecedor automaticamente (link com fin_suppliers)
    supplier_id = await _find_or_create_supplier(
        cid, payload.supplier_name or "", user.get("email") or "?",
    )
    doc = {
        "id": pid,
        "company_id": cid,
        "type": payload.type,
        "praca_id": payload.praca_id,
        "responsible_collaborator_id": payload.responsible_collaborator_id,
        "supplier_name": payload.supplier_name,
        "supplier_id": supplier_id,
        "invoice_number": payload.invoice_number,
        "invoice_date": payload.invoice_date,
        "total_value": payload.total_value,
        "items": [it.dict() for it in payload.items],
        "notes": payload.notes,
        "file_url": payload.file_url,
        "file_name": payload.file_name,
        "status": "pending",  # pending -> confirmed
        "created_at": now_iso(),
        "created_by": user.get("email"),
        "created_by_id": user.get("id"),
    }
    await db.purchases.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Routes — Upload + AI extraction
# ---------------------------------------------------------------------------
@router.post("/upload-extract")
async def upload_extract(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload de NF/recibo (PDF/imagem). IA Claude extrai os dados.

    Retorna um DRAFT (não persiste). Usuário revisa e confirma via POST /.
    """
    _require_purchase_access(user)
    raw = await file.read()
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Arquivo > 10 MB")
    fname = (file.filename or "compra").lower()
    is_pdf = fname.endswith(".pdf") or raw[:5] == b"%PDF-"
    is_img = any(fname.endswith(e) for e in
                  (".jpg", ".jpeg", ".png", ".webp"))
    is_doc = any(fname.endswith(e) for e in
                  (".doc", ".docx", ".xls", ".xlsx"))
    if not (is_pdf or is_img or is_doc):
        raise HTTPException(415, "Tipo não suportado. Envie PDF, "
                                   "imagem ou planilha.")

    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Extrair texto/imagem
    text_content = ""
    image_b64: Optional[str] = None
    try:
        if is_pdf:
            import pdfplumber
            import io
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages[:5]:  # primeiros 5
                    t = page.extract_text() or ""
                    text_content += t + "\n"
        elif is_doc:
            # docx/xlsx: leitura simples
            try:
                if fname.endswith((".xls", ".xlsx")):
                    from openpyxl import load_workbook
                    import io
                    wb = load_workbook(io.BytesIO(raw), data_only=True)
                    for ws in wb.worksheets[:3]:
                        for row in ws.iter_rows(values_only=True,
                                                  max_row=200):
                            text_content += " | ".join(
                                str(c) for c in row if c) + "\n"
                else:
                    from docx import Document
                    import io
                    d = Document(io.BytesIO(raw))
                    for p in d.paragraphs:
                        text_content += p.text + "\n"
            except Exception:
                pass
        elif is_img:
            image_b64 = base64.b64encode(raw).decode()
    except Exception as e:
        logger.warning("[purchases] extract falhou: %s", e)

    # Chama Claude Sonnet 4.5 para estruturar
    try:
        from emergentintegrations.llm.chat import (
            ImageContent, LlmChat, UserMessage,
        )
        from services.ai_keys import resolve_keys
        keys = await resolve_keys(cid)
        ai_key = (keys.get("anthropic") or keys.get("openai")
                       or keys.get("gemini"))
        if not ai_key:
            raise HTTPException(503, "IA não configurada — preencha manual")
        prompt = (
            "Extraia os dados desta nota fiscal / recibo / comprovante "
            "de compra de material para um provedor de internet "
            "brasileiro. Responda APENAS JSON válido (sem markdown):\n"
            "{\n"
            "  \"supplier_name\": \"...\",  // razão social/nome\n"
            "  \"invoice_number\": \"...\",\n"
            "  \"invoice_date\": \"YYYY-MM-DD\",\n"
            "  \"total_value\": 1234.56,\n"
            "  \"type\": \"ont\"|\"insumo\"|\"equipamento\"|\"ferramenta\"|\"outros\",\n"
            "  \"items\": [{\n"
            "      \"description\": \"...\",\n"
            "      \"quantity\": 1,\n"
            "      \"unit\": \"un|m|cx\",\n"
            "      \"unit_price\": 0.0,\n"
            "      \"type\": \"ont\"|\"insumo\"|\"equipamento\"|\"ferramenta\"|\"outros\",\n"
            "        // CLASSIFIQUE CADA ITEM: ferramenta = alicate, chave,\n"
            "        // OTDR, decapador, máquina de fusão, escada, etc.\n"
            "        // insumo = splitter, conector, cordão, drop, CTO sem\n"
            "        // splitter, adaptador. ont = modem/roteador/cliente.\n"
            "        // equipamento = OLT, switch, rack, nobreak.\n"
            "      \"macs\": [\"...\"]  // se ONT, MACs identificados\n"
            "  }],\n"
            "  \"confidence\": 0.0-1.0,\n"
            "  \"reason\": \"breve explicação PT-BR\"\n"
            "}\n\n"
        )
        if text_content:
            prompt += f"TEXTO EXTRAÍDO:\n{text_content[:8000]}"
        chat = LlmChat(
            api_key=ai_key,
            session_id=f"purchase-{cid}-{uuid.uuid4().hex[:6]}",
            system_message="Você responde APENAS em JSON válido.",
        ).with_model("anthropic", "claude-sonnet-4-5")
        msg_args: Dict[str, Any] = {"text": prompt}
        if image_b64:
            msg_args["file_contents"] = [ImageContent(image_base64=image_b64)]
        resp = await chat.send_message(UserMessage(**msg_args))
        text = (resp or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text,
                              flags=re.MULTILINE)
        draft = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("[purchases] IA JSON inválido: %s", e)
        draft = {"confidence": 0.0,
                  "reason": "IA não conseguiu estruturar — preencha manual."}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[purchases] upload-extract falhou: %s", e)
        draft = {"confidence": 0.0, "reason": f"erro: {e!s}"}

    return {
        "ok": True,
        "file_name": file.filename,
        "draft": draft,
        "raw_text_preview": text_content[:500] if text_content else None,
    }


# ---------------------------------------------------------------------------
# Routes — Confirm (integra com stok)
# ---------------------------------------------------------------------------
@router.post("/{purchase_id}/confirm")
async def confirm_purchase(
    purchase_id: str,
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    """Confirma a compra e gera entradas em stok_onts/stok_stock conforme tipo.

    Apenas gestor/administrador pode confirmar (regra de negócio do estoque).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await db.purchases.find_one({"id": purchase_id, "company_id": cid},
                                          {"_id": 0})
    if not p:
        raise HTTPException(404, "Compra não encontrada")
    if p.get("status") == "confirmed":
        raise HTTPException(400, "Compra já confirmada")

    items_imported = 0
    macs_imported: List[str] = []
    notes: List[str] = []

    if p["type"] == "ont":
        # Coleta MACs únicos de todos os items
        all_macs: List[str] = []
        for it in (p.get("items") or []):
            for m in (it.get("macs") or []):
                mn = _normalize_mac(m)
                if mn and mn not in all_macs:
                    all_macs.append(mn)
        if all_macs:
            # Filtra MACs já cadastrados
            existing = await db.stok_onts.find(
                {"company_id": cid, "mac": {"$in": all_macs}},
                {"_id": 0, "mac": 1},
            ).to_list(5000)
            existing_set = {e["mac"] for e in existing}
            new_macs = [m for m in all_macs if m not in existing_set]
            # Modelo: usa description do primeiro item ou "ONT"
            model = (p.get("items") or [{}])[0].get(
                "description") or "ONT"
            docs = [{
                "company_id": cid, "mac": m, "model": model[:120],
                "location_type": "empresa", "location_id": "empresa",
                "praca_id": p.get("praca_id"),
                "warehouse_responsible_id":
                    p.get("responsible_collaborator_id"),
                "purchase_id": purchase_id,
                "client_name": None, "status": "disponivel",
                "created_by": user.get("email", "?"),
                "created_at": now_iso(),
            } for m in new_macs]
            if docs:
                await db.stok_onts.insert_many([dict(d) for d in docs])
            items_imported = len(docs)
            macs_imported = new_macs
            if existing_set:
                notes.append(
                    f"{len(existing_set)} MAC(s) já cadastrados — ignorados")

    elif p["type"] == "insumo":
        # Incrementa o estoque por insumo na praça (collection stok_stock)
        for it in (p.get("items") or []):
            desc = (it.get("description") or "").strip()
            qty = float(it.get("quantity") or 0)
            if not desc or qty <= 0:
                continue
            # Tenta casar com catálogo de insumo
            key = re.sub(r"[^a-z]", "", desc.lower())[:30] or desc.lower()
            await db.stok_stock.update_one(
                {"company_id": cid, "praca_id": p.get("praca_id"),
                  "insumo_key": key},
                {"$inc": {"quantity": qty},
                  "$set": {"insumo_label": desc,
                            "updated_at": now_iso()},
                  "$setOnInsert": {"created_at": now_iso(),
                                      "company_id": cid,
                                      "praca_id": p.get("praca_id"),
                                      "insumo_key": key}},
                upsert=True,
            )
            items_imported += 1

    # else: equipamento/outros = só registra, não afeta stok

    await db.purchases.update_one(
        {"id": purchase_id, "company_id": cid},
        {"$set": {
            "status": "confirmed",
            "confirmed_at": now_iso(),
            "confirmed_by": user.get("email"),
            "items_imported": items_imported,
            "macs_imported": macs_imported,
            "import_notes": notes,
        }},
    )
    return {
        "ok": True,
        "purchase_id": purchase_id,
        "items_imported": items_imported,
        "macs_imported": len(macs_imported),
        "notes": notes,
    }


@router.delete("/{purchase_id}")
async def delete_purchase(
    purchase_id: str,
    user: dict = Depends(require_role("gestor")),
) -> Dict[str, Any]:
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await db.purchases.find_one({"id": purchase_id, "company_id": cid},
                                          {"_id": 0, "status": 1})
    if not p:
        raise HTTPException(404, "Compra não encontrada")
    if p.get("status") == "confirmed":
        raise HTTPException(400, "Compra já confirmada — não pode ser "
                                   "deletada. Faça lançamento reverso no "
                                   "estoque se necessário.")
    await db.purchases.delete_one({"id": purchase_id, "company_id": cid})
    return {"ok": True}
