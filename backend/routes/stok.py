"""Sistema de Estoque de Fibra Óptica — integrado ao painel principal.

Adaptado do projeto stok-main:
- Coleções isoladas com prefixo `stok_*` (não colide com lousa/clock/atlaz).
- Técnicos NÃO são uma coleção própria: usamos `collaborators` existente.
  Qualquer colaborador serve como "estoque destino" — o gestor decide.
- Auth via `require_role("administrador"|"gestor")` do core (sem JWT próprio).
- Insumos baixam SOMENTE no fechamento da OS (regra de negócio do stok).
- ONT instalada/troca exige OS ativa + MAC no estoque do técnico.
- Retirada exige OS ativa + MAC vinculado ao cliente.
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

import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services import client_equipment_history as ceh
from services import ont_duplicate_detector as ont_dup

logger = logging.getLogger("ponto.stok")

router = APIRouter(prefix="/api/stok", tags=["stok"])


# ---------------------------------------------------------------------------
# Catálogo de insumos (estático)
# ---------------------------------------------------------------------------
CONSUMABLE_CATALOG = [
    {"id": "drop", "name": "Drop", "unit": "m", "pack_label": "Bobina", "pack_qty": 1000},
    {"id": "cabo_rede", "name": "Cabo de rede", "unit": "m", "pack_label": "Caixa", "pack_qty": 305},
    {"id": "conector_fast", "name": "Conector fast", "unit": "un", "pack_label": "Unidade", "pack_qty": 1},
    {"id": "conector_fibra", "name": "Conector de fibra", "unit": "un", "pack_label": "Unidade", "pack_qty": 1},
    {"id": "esticador", "name": "Esticador", "unit": "un", "pack_label": "Unidade", "pack_qty": 1},
    {"id": "conector_rede", "name": "Conector de rede", "unit": "un", "pack_label": "Unidade", "pack_qty": 1},
    # Insumos de REDE (técnicos de rede / lançamentos de backbone)
    {"id": "fibra_06fo", "name": "Fibra 06FO", "unit": "m", "pack_label": "Bobina", "pack_qty": 2000, "category": "rede"},
    {"id": "fibra_12fo", "name": "Fibra 12FO", "unit": "m", "pack_label": "Bobina", "pack_qty": 2000, "category": "rede"},
    {"id": "fibra_24fo", "name": "Fibra 24FO", "unit": "m", "pack_label": "Bobina", "pack_qty": 2000, "category": "rede"},
    # iter211f — fibras de alta capacidade (backbone)
    {"id": "fibra_48fo", "name": "Fibra 48FO", "unit": "m", "pack_label": "Bobina", "pack_qty": 2000, "category": "rede"},
    {"id": "fibra_96fo", "name": "Fibra 96FO", "unit": "m", "pack_label": "Bobina", "pack_qty": 2000, "category": "rede"},
]
CONSUMABLE_IDS = {c["id"] for c in CONSUMABLE_CATALOG}
CONSUMABLE_BY_ID: Dict[str, Dict[str, Any]] = {c["id"]: c for c in CONSUMABLE_CATALOG}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class OntBulkItem(BaseModel):
    """iter211h — SN agora é OBRIGATÓRIO (chave primária). MAC opcional
    (preenchido pelo SmartOLT depois de aprovisionar)."""
    sn: str
    mac: Optional[str] = None


class OntBulkIn(BaseModel):
    model: str
    # iter211h — backward-compat: ainda aceita `macs: List[str]` (legado),
    # mas o caminho recomendado é `items: [{sn, mac?}]`.
    macs: Optional[List[str]] = None
    items: Optional[List[OntBulkItem]] = None
    # iter215bc — destino opcional. Quando informado, a ONT é cadastrada
    # JÁ no estoque do técnico (location_type=tecnico), economizando o
    # passo de transferência. Default = estoque da empresa.
    technician_id: Optional[str] = None


class OntEditIn(BaseModel):
    model: str


class OntTransferIn(BaseModel):
    mac: str
    technician_id: str  # = collaborator.id
    # Onda 2 (16/02/2026) — `reason` obrigatório no handler.
    reason: Optional[Dict[str, Any]] = None  # {"code": ..., "details": ...}


class OntBulkTransferReasonIn(BaseModel):
    macs: List[str]
    technician_id: str
    reason: Optional[Dict[str, Any]] = None


class ConsumablePurchaseIn(BaseModel):
    consumable_id: str
    pack_qty: int
    # iter215bd — destino opcional. Quando informado, o insumo é
    # registrado direto no estoque do técnico. Default = empresa.
    technician_id: Optional[str] = None


class ConsumableTransferIn(BaseModel):
    consumable_id: str
    quantity: int
    technician_id: str


class ServiceIn(BaseModel):
    type: str
    client_id: str
    client_name: str
    technician_id: str
    reason: Optional[str] = None
    ticket_id: Optional[str] = None  # vínculo opcional com bolha da Lousa (parte b)


class UsedItem(BaseModel):
    consumable_id: str
    quantity: int


class ServiceCloseIn(BaseModel):
    ont_mac: Optional[str] = None
    ont_sn: Optional[str] = None  # iter174 — alternativa ao MAC para retirada
    used_items: List[UsedItem] = []
    tag: str = "instalacao"
    # Troca de porta da CTO (cliente já vinculado a uma porta)
    port_swap: bool = False
    new_port_number: Optional[int] = None
    # Caso instalação sem porta prévia → técnico informa porta a ocupar
    cto_id: Optional[str] = None
    cto_port_number: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_mac(mac: str) -> str:
    return mac.strip().upper()


async def _add_history(htype: str, description: str, user: str, tag: str, company_id: str) -> None:
    await db.stok_history.insert_one({
        "id": str(uuid.uuid4()),
        "company_id": company_id,
        "date": now_iso(),
        "type": htype,
        "description": description,
        "user": user,
        "tag": tag,
    })


async def _get_collab(cid: str, company_id: str) -> dict:
    coll = await db.collaborators.find_one(
        {"id": cid, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador (técnico) não encontrado.")
    return coll


# ---------------------------------------------------------------------------
# Catálogo + dashboard
# ---------------------------------------------------------------------------
@router.get("/catalog")
async def catalog(user: dict = Depends(require_role("gestor"))):
    return {"consumables": CONSUMABLE_CATALOG}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_role("gestor"))):
    """iter171 — Envelopado em try/except para nunca dar 500 silencioso.
    Em caso de erro, retorna estrutura vazia + campo `error_logged=True`."""
    try:
        return await _dashboard_impl(user)
    except Exception as e:
        logger.exception("[stok-dashboard] falhou: %s", e)
        return {
            "company_onts": 0, "total_onts": 0,
            "active_services_count": 0, "technicians_count": 0,
            "tech_rows": [], "empresa_stock": {c: 0 for c in CONSUMABLE_IDS},
            "expected_withdrawals": 0, "effective_withdrawals": 0,
            "withdrawal_rate": 0,
            "error_logged": True, "error_detail": str(e)[:200],
        }


async def _dashboard_impl(user: dict):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    company_onts = await db.stok_onts.count_documents({"company_id": cid, "location_type": "empresa"})
    total_onts = await db.stok_onts.count_documents({"company_id": cid})

    techs = await db.collaborators.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1, "atlaz_inbox": 1},
    ).to_list(500)
    techs = [t for t in techs if not t.get("atlaz_inbox")]

    stocks = await db.stok_stock.find({"company_id": cid}, {"_id": 0}).to_list(500)
    stock_by_loc = {s["location"]: s for s in stocks}
    services = await db.stok_services.find({"company_id": cid}, {"_id": 0}).to_list(2000)
    history = await db.stok_history.find({"company_id": cid}, {"_id": 0}).to_list(5000)

    rows = []
    for t in techs:
        tech_onts = await db.stok_onts.count_documents(
            {"company_id": cid, "location_type": "tecnico", "location_id": t["id"]},
        )
        # iter171 — guards defensivos: history pode ter description/tag/type
        # ausentes ou None em dados reais de produção
        tname = t.get("name") or ""
        installed = sum(1 for h in history
                          if h.get("type") == "instalacao"
                          and tname in (h.get("description") or ""))
        withdrawals = sum(1 for h in history
                             if h.get("type") == "retirada"
                             and tname in (h.get("description") or ""))
        rows.append({
            "id": t["id"],
            "name": t["name"],
            "tech_onts": tech_onts,
            "installed_month": installed,
            "withdrawals": withdrawals,
            "stock": {c: stock_by_loc.get(t["id"], {}).get(c, 0) for c in CONSUMABLE_IDS},
        })

    expected = sum(1 for s in services if s.get("type") == "retirada") + \
        sum(1 for h in history
              if h.get("tag") in ("inadimplencia", "cancelamento"))
    effective = sum(1 for h in history if h.get("type") == "retirada")
    rate = round((effective / expected) * 100) if expected else 0
    active_count = sum(1 for s in services if s.get("status") == "ativo")

    return {
        "company_onts": company_onts,
        "total_onts": total_onts,
        "active_services_count": active_count,
        "technicians_count": len(techs),
        "tech_rows": rows,
        "empresa_stock": {c: stock_by_loc.get("empresa", {}).get(c, 0) for c in CONSUMABLE_IDS},
        "expected_withdrawals": expected,
        "effective_withdrawals": effective,
        "withdrawal_rate": rate,
    }


@router.get("/technicians")
async def list_technicians(user: dict = Depends(require_role("gestor"))):
    """Retorna colaboradores aptos a ter estoque (exclui o inbox Atlaz)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    coll = await db.collaborators.find(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "role": 1},
    ).to_list(500)
    return coll


# ---------------------------------------------------------------------------
# ONTs
# ---------------------------------------------------------------------------
@router.get("/onts")
async def list_onts(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_onts.find({"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return docs


@router.get("/onts/traceability/{ident}")
async def ont_traceability(ident: str,
                              user: dict = Depends(require_role("gestor"))):
    """iter201 — Rastreabilidade ponta a ponta da ONT a partir de SN/MAC.

    Pedido do usuário 10/02/2026: "ao informar o SN, identifique qual é a
    nota fiscal de que ela veio".

    Devolve:
      - ont: dados atuais (location, status, modelo, SN, MAC)
      - purchase: nota fiscal de origem (fornecedor, NF, data, valor, file)
      - history: eventos do client_equipment_history (instalações, retiradas)
      - withdrawn_from: cliente anterior se houver
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    raw = (ident or "").strip().upper()
    if not raw:
        raise HTTPException(400, "Informe SN ou MAC")
    # Busca SN primeiro (prevalente desde iter197), depois MAC, depois MAC placeholder
    ont = await db.stok_onts.find_one(
        {"company_id": cid, "scan_sn": raw}, {"_id": 0})
    if not ont:
        mac_n = normalize_mac(raw) or raw
        ont = await db.stok_onts.find_one(
            {"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        ont = await db.stok_onts.find_one(
            {"company_id": cid, "mac": f"SN-{raw}"}, {"_id": 0})
    if not ont:
        raise HTTPException(404, f"ONT não encontrada (busca por SN/MAC: {raw})")

    # Resolve compra de origem (NF)
    purchase = None
    if ont.get("purchase_id"):
        purchase = await db.purchases.find_one(
            {"id": ont["purchase_id"], "company_id": cid},
            {"_id": 0, "id": 1, "supplier_name": 1, "invoice_number": 1,
             "invoice_date": 1, "total_value": 1, "file_name": 1,
             "praca_id": 1, "responsible_collaborator_id": 1,
             "created_at": 1, "confirmed_at": 1, "type": 1, "notes": 1},
        )
        if purchase and purchase.get("praca_id"):
            praca = await db.pracas.find_one(
                {"id": purchase["praca_id"]}, {"_id": 0, "name": 1})
            purchase["praca_name"] = (praca or {}).get("name")
        if purchase and purchase.get("responsible_collaborator_id"):
            resp = await db.collaborators.find_one(
                {"id": purchase["responsible_collaborator_id"]},
                {"_id": 0, "name": 1})
            purchase["responsible_name"] = (resp or {}).get("name")

    # Histórico do equipamento (instalações/retiradas)
    history = await db.client_equipment_history.find(
        {"company_id": cid,
         "$or": [{"ont_mac": ont.get("mac")},
                 {"ont_sn": ont.get("scan_sn") or raw}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(100)

    # Localização atual (resolve nome quando location_id é tecnico/cliente)
    location_name = None
    if ont.get("location_type") == "tecnico" and ont.get("location_id"):
        tech = await db.collaborators.find_one(
            {"id": ont["location_id"]}, {"_id": 0, "name": 1})
        location_name = (tech or {}).get("name")
    elif ont.get("location_type") == "cliente" and ont.get("location_id"):
        sub = await db.subscribers.find_one(
            {"id": ont["location_id"]}, {"_id": 0, "name": 1})
        location_name = (sub or {}).get("name") or ont.get("client_name")

    return {
        "ont": {
            "sn": ont.get("scan_sn"),
            "mac": ont.get("mac"),
            "model": ont.get("model"),
            "status": ont.get("status"),
            "source": ont.get("source"),
            "location_type": ont.get("location_type"),
            "location_id": ont.get("location_id"),
            "location_name": location_name,
            "created_at": ont.get("created_at"),
            "installed_at": ont.get("installed_at"),
            "installed_by_name": ont.get("installed_by_name"),
            "withdrawn_from_client_name": ont.get("withdrawn_from_client_name"),
            "withdrawn_by_name": ont.get("withdrawn_by_name"),
            "withdrawn_at": ont.get("withdrawn_at"),
        },
        "purchase": purchase,
        "history": history,
        "found_by": "sn" if ont.get("scan_sn") == raw else "mac",
    }


@router.get("/onts/traceability/{ident}/pdf")
async def ont_traceability_pdf(ident: str,
                                  user: dict = Depends(require_role("gestor"))):
    """iter201b — PDF do relatório de rastreabilidade da ONT.

    Reaproveita a mesma resolução do endpoint /traceability/{ident} e gera
    um PDF A4 com Cabeçalho (SN/MAC) + Onde está + NF de origem + Histórico.
    Útil para auditorias fiscais e disputas com fornecedor.
    """
    # Reaproveita a função acima (resolve tudo de novo internamente)
    data = await ont_traceability(ident, user=user)  # type: ignore
    return _build_traceability_pdf(data, ident)


def _build_traceability_pdf(data: Dict[str, Any], ident: str):
    """Constrói PDF A4 com layout limpo: header preto + 3 seções."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors as rl_colors
    from fastapi.responses import Response

    ont = data.get("ont") or {}
    purchase = data.get("purchase") or None
    history = data.get("history") or []

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 20 * mm

    # === Header preto ===
    c.setFillColor(rl_colors.HexColor("#0f172a"))
    c.rect(0, height - 32 * mm, width, 32 * mm, fill=1, stroke=0)
    c.setFillColor(rl_colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, height - 12 * mm, "RELATÓRIO DE RASTREABILIDADE — ONT")
    c.setFont("Courier-Bold", 18)
    sn = ont.get("sn") or ident
    c.drawString(15 * mm, height - 22 * mm, f"SN: {sn}")
    if ont.get("mac") and not str(ont.get("mac")).startswith(("SN-", "AUTOSN_", "MANUAL-")):
        c.setFont("Courier", 9)
        c.drawString(15 * mm, height - 28 * mm, f"MAC: {ont.get('mac')}")
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 15 * mm, height - 12 * mm,
                      datetime.now(timezone.utc).strftime("Gerado em %d/%m/%Y %H:%M UTC"))
    y = height - 42 * mm

    def section(title: str):
        nonlocal y
        c.setFillColor(rl_colors.HexColor("#475569"))
        c.setFont("Helvetica-Bold", 10)
        c.drawString(15 * mm, y, title.upper())
        c.setStrokeColor(rl_colors.HexColor("#cbd5e1"))
        c.line(15 * mm, y - 1 * mm, width - 15 * mm, y - 1 * mm)
        y -= 8 * mm

    def line(label: str, value: str, indent: float = 15.0):
        nonlocal y
        c.setFillColor(rl_colors.HexColor("#64748b"))
        c.setFont("Helvetica", 8)
        c.drawString(indent * mm, y, label.upper())
        c.setFillColor(rl_colors.HexColor("#0f172a"))
        c.setFont("Helvetica-Bold", 10)
        c.drawString((indent + 38) * mm, y, str(value or "—")[:80])
        y -= 6 * mm

    def page_break_if_needed(min_space: float = 30):
        nonlocal y
        if y < min_space * mm:
            c.showPage()
            y = height - 20 * mm

    # === 1) Onde está agora ===
    section("📍 Onde está agora")
    status_map = {
        "disponivel": "Disponível",
        "instalada": "Instalada (cliente)",
        "retirada_com_tecnico": "Com o técnico (após retirada)",
        "defeito_devolver_empresa": "Defeito — devolver",
        "pendente_aprovacao_gestor": "Pendente aprovação",
    }
    line("Status", status_map.get(ont.get("status"), ont.get("status")))
    line("Modelo", ont.get("model"))
    loc_label = (
        "📦 Estoque da empresa" if ont.get("location_type") == "empresa"
        else f"👷 {ont.get('location_name') or 'Técnico'}" if ont.get("location_type") == "tecnico"
        else f"👤 {ont.get('location_name') or 'Cliente'}" if ont.get("location_type") == "cliente"
        else (ont.get("location_type") or "—")
    )
    line("Localização", loc_label)
    line("Cadastrada em",
         _pretty_dt(ont.get("created_at")))
    y -= 3 * mm

    # === 2) Nota fiscal de origem ===
    page_break_if_needed()
    section("📄 Nota fiscal de origem")
    if purchase:
        c.setFillColor(rl_colors.HexColor("#eff6ff"))
        c.setStrokeColor(rl_colors.HexColor("#93c5fd"))
        c.rect(15 * mm, y - 48 * mm, width - 30 * mm, 50 * mm,
                fill=1, stroke=1)
        y -= 2 * mm
        line("Fornecedor", purchase.get("supplier_name"), indent=18.0)
        line("Nº NF", purchase.get("invoice_number"), indent=18.0)
        line("Data NF", purchase.get("invoice_date"), indent=18.0)
        val = purchase.get("total_value")
        line("Valor total",
             f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
             if val is not None else "—",
             indent=18.0)
        line("Praça", purchase.get("praca_name"), indent=18.0)
        line("Responsável recebedor", purchase.get("responsible_name"), indent=18.0)
        if purchase.get("file_name"):
            line("Arquivo", "📎 " + purchase["file_name"], indent=18.0)
        line("Confirmada em",
             _pretty_dt(purchase.get("confirmed_at")), indent=18.0)
        y -= 2 * mm
    else:
        c.setFillColor(rl_colors.HexColor("#fef3c7"))
        c.setStrokeColor(rl_colors.HexColor("#fcd34d"))
        c.rect(15 * mm, y - 12 * mm, width - 30 * mm, 12 * mm,
                fill=1, stroke=1)
        c.setFillColor(rl_colors.HexColor("#92400e"))
        c.setFont("Helvetica", 9)
        c.drawString(18 * mm, y - 6 * mm,
                     "⚠️ Esta ONT não foi vinculada a nenhuma nota fiscal "
                     "(cadastro manual em massa ou migração).")
        y -= 16 * mm

    # === 3) Histórico ===
    page_break_if_needed(50)
    section(f"🕒 Histórico ({len(history)} evento(s))")
    if not history:
        c.setFillColor(rl_colors.HexColor("#94a3b8"))
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(15 * mm, y, "Nenhum evento registrado ainda.")
        y -= 8 * mm
    else:
        action_labels = {
            "install": "🔧 Instalação",
            "withdraw": "📦 Retirada",
            "swap": "🔄 Troca",
            "port_link": "🔌 Porta CTO vinculada",
            "port_unlink": "❌ Porta CTO desvinculada",
        }
        for ev in history[:30]:  # limita p/ não estourar página
            page_break_if_needed(25)
            c.setFillColor(rl_colors.HexColor("#0f172a"))
            c.setFont("Helvetica-Bold", 10)
            c.drawString(18 * mm, y,
                         action_labels.get(ev.get("action"), ev.get("action", "?")))
            c.setFillColor(rl_colors.HexColor("#64748b"))
            c.setFont("Helvetica", 8)
            c.drawRightString(width - 15 * mm, y,
                              _pretty_dt(ev.get("created_at")))
            y -= 5 * mm
            ctx_parts = []
            if ev.get("client_name"):
                ctx_parts.append(f"Cliente: {ev['client_name']}")
            if ev.get("cto_name"):
                p = f"CTO: {ev['cto_name']}"
                if ev.get("cto_port_number"):
                    p += f" (porta {ev['cto_port_number']})"
                ctx_parts.append(p)
            if ev.get("actor_name"):
                ctx_parts.append(f"Por: {ev['actor_name']}")
            if ctx_parts:
                c.setFillColor(rl_colors.HexColor("#475569"))
                c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, " · ".join(ctx_parts)[:110])
                y -= 5 * mm
            if ev.get("notes"):
                c.setFillColor(rl_colors.HexColor("#475569"))
                c.setFont("Helvetica-Oblique", 8)
                c.drawString(20 * mm, y, f"“{ev['notes'][:110]}”")
                y -= 5 * mm
            y -= 2 * mm

    # === Footer ===
    c.setFillColor(rl_colors.HexColor("#94a3b8"))
    c.setFont("Helvetica", 7)
    c.drawString(15 * mm, 10 * mm,
                 "Relatório gerado automaticamente pelo SmartProv · "
                 "documento válido para auditoria fiscal e disputas com fornecedor.")

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()

    fname = f"rastreabilidade_{(sn or ident).replace(':', '').replace('/', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _pretty_dt(iso) -> str:
    """Formata ISO datetime em PT-BR."""
    if not iso:
        return "—"
    try:
        from datetime import datetime as _dt
        if isinstance(iso, str):
            iso2 = iso.replace("Z", "+00:00")
            dt = _dt.fromisoformat(iso2)
        else:
            dt = iso
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(iso)


@router.post("/onts/bulk")
async def create_onts_bulk(payload: OntBulkIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    model = payload.model.strip()
    if not model:
        raise HTTPException(400, "Informe o modelo da ONT.")
    # iter211h — base agora é SN (obrigatório). Aceita 2 formatos:
    #   1) items: [{sn, mac?}]   ← preferido
    #   2) macs: [str]           ← legado (cada str é um SN, MAC vazio)
    items = []
    if payload.items:
        items = [{"sn": (it.sn or "").strip().upper(),
                   "mac": (it.mac or "").strip().upper() or None}
                  for it in payload.items if (it.sn or "").strip()]
    elif payload.macs:
        # Compat: trata cada string como SN (era assim que o frontend velho
        # mandava). Se a string for um MAC válido, mantém como MAC também.
        for raw in payload.macs:
            raw = (raw or "").strip().upper()
            if not raw:
                continue
            macn = normalize_mac(raw)
            items.append({"sn": raw, "mac": macn if macn else None})

    if not items:
        raise HTTPException(400,
            "Informe pelo menos um SN (base obrigatória). "
            "Use o campo 'items' [{sn, mac?}] ou 'macs' (legado).")

    # Deduplicação por SN
    seen_sn, dedup = set(), []
    for it in items:
        if it["sn"] in seen_sn:
            continue
        seen_sn.add(it["sn"])
        dedup.append(it)

    sns = [it["sn"] for it in dedup]
    existing = await db.stok_onts.find(
        {"company_id": cid, "scan_sn": {"$in": sns}},
        {"scan_sn": 1, "_id": 0},
    ).to_list(5000)
    if existing:
        raise HTTPException(400, f"SN já cadastrado: {existing[0]['scan_sn']}")

    docs = []
    # iter215bc — destino opcional: técnico direto OU estoque empresa
    tech_target = None
    if payload.technician_id:
        tech_target = await db.collaborators.find_one(
            {"id": payload.technician_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not tech_target:
            raise HTTPException(404,
                "Técnico de destino não encontrado.")

    for it in dedup:
        # Quando não tem MAC ainda, usa placeholder `SN-{sn}` pra manter a
        # constraint de unicidade (legado) sem bloquear o cadastro.
        mac_final = it["mac"] or f"SN-{it['sn']}"
        if tech_target:
            location_type = "tecnico"
            location_id = tech_target["id"]
            status = "com_tecnico"
        else:
            location_type = "empresa"
            location_id = "empresa"
            status = "disponivel"
        docs.append({
            "company_id": cid,
            "scan_sn": it["sn"],
            "mac": mac_final,
            "model": model,
            "location_type": location_type, "location_id": location_id,
            "client_name": None, "status": status,
            "created_by": user.get("email", "?"), "created_at": now_iso(),
        })
    await db.stok_onts.insert_many([dict(d) for d in docs])
    if tech_target:
        await _add_history(
            "entrada_ont",
            f"Entrada de {len(docs)} ONT(s) modelo {model} "
            f"DIRETO no estoque de {tech_target['name']}",
            user.get("name", "?"), "compra", cid)
    else:
        await _add_history(
            "entrada_ont",
            f"Entrada de {len(docs)} ONT(s) modelo {model} "
            f"no estoque empresa",
            user.get("name", "?"), "compra", cid)
    return {
        "inserted": len(docs),
        "sns": sns,
        "macs": [d["mac"] for d in docs],
        "destination": ("tecnico:" + tech_target["id"]) if tech_target
            else "empresa",
        "destination_name": tech_target["name"] if tech_target
            else "Estoque da empresa",
    }


@router.patch("/onts/{mac}")
async def edit_ont(mac: str, payload: OntEditIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    mac_n = normalize_mac(mac)
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada.")
    if ont["location_type"] != "empresa":
        raise HTTPException(400, "Só pode editar ONT quando estiver no estoque da empresa.")
    if user.get("role") != "administrador" and ont.get("created_by") != user.get("email"):
        raise HTTPException(403, "Só o funcionário que cadastrou ou administrador pode editar.")
    await db.stok_onts.update_one({"company_id": cid, "mac": mac_n}, {"$set": {"model": payload.model.strip()}})
    await _add_history("edicao_ont", f"Modelo do MAC {mac_n} alterado para {payload.model}",
                       user.get("name", "?"), "correcao", cid)
    return {"ok": True}


class OntSetSnIn(BaseModel):
    """iter211m — Define ou corrige o SN de uma ONT legada."""
    scan_sn: str


@router.post("/onts/{mac_or_sn}/set-sn")
async def set_ont_sn(mac_or_sn: str, payload: OntSetSnIn,
                       user: dict = Depends(require_role("gestor"))):
    """Define o SN de uma ONT que está sem SN (legada).
    Pode ser identificada pelo MAC ou pelo SN atual (caso queira corrigir).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    new_sn = (payload.scan_sn or "").strip().upper()
    if not new_sn:
        raise HTTPException(400, "Informe o novo SN.")
    # Busca por MAC normalizado OU por scan_sn exato (case-insensitive)
    mac_n = normalize_mac(mac_or_sn)
    ont = None
    if mac_n:
        ont = await db.stok_onts.find_one(
            {"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        ont = await db.stok_onts.find_one(
            {"company_id": cid,
              "scan_sn": (mac_or_sn or "").strip().upper()},
            {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada.")
    # Confere unicidade
    dup = await db.stok_onts.find_one(
        {"company_id": cid, "scan_sn": new_sn, "mac": {"$ne": ont.get("mac")}},
        {"_id": 0})
    if dup:
        raise HTTPException(400, f"SN '{new_sn}' já está usado por outra ONT.")
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": ont["mac"]},
        {"$set": {"scan_sn": new_sn,
                    "sn_updated_at": now_iso(),
                    "sn_updated_by": user.get("email")}},
    )
    await _add_history("set_sn",
                        f"SN definido para ONT (MAC {ont.get('mac')}): {new_sn}",
                        user.get("name", "?"), "correcao", cid)
    return {"ok": True, "scan_sn": new_sn,
             "previous_sn": ont.get("scan_sn")}


@router.post("/onts/migrate-fill-sn")
async def migrate_fill_sn(user: dict = Depends(require_role("administrador"))):
    """iter211m — Para ONTs sem SN, popular `scan_sn` a partir do MAC
    (apenas como placeholder identificador único). Útil para migração
    de bases antigas. Idempotente.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cursor = db.stok_onts.find(
        {"company_id": cid,
          "$or": [{"scan_sn": {"$exists": False}},
                    {"scan_sn": None},
                    {"scan_sn": ""}]},
        {"_id": 0, "mac": 1},
    )
    updated = 0
    async for d in cursor:
        mac = d.get("mac") or ""
        # Gera SN com prefixo SN-{ultimos 6 chars do MAC sem :}
        clean = mac.replace(":", "").replace("-", "").upper()
        if not clean:
            continue
        placeholder = f"AUTOSN_{clean[-8:]}" if len(clean) >= 8 else f"AUTOSN_{clean}"
        # Evita conflito com outro placeholder
        dup = await db.stok_onts.find_one(
            {"company_id": cid, "scan_sn": placeholder,
              "mac": {"$ne": mac}}, {"_id": 0})
        if dup:
            # Adiciona random suffix se colidiu
            import uuid
            placeholder = f"{placeholder}_{uuid.uuid4().hex[:4].upper()}"
        await db.stok_onts.update_one(
            {"company_id": cid, "mac": mac},
            {"$set": {"scan_sn": placeholder,
                        "sn_auto_generated": True,
                        "sn_updated_at": now_iso()}},
        )
        updated += 1
    if updated:
        await _add_history(
            "migrate_sn",
            f"Migração: {updated} ONT(s) tiveram SN placeholder gerado (AUTOSN_*).",
            user.get("name", "?"), "migracao", cid)
    return {"updated": updated,
             "message": (f"{updated} ONT(s) receberam SN placeholder. "
                          "Substitua pelo SN real escaneando a etiqueta.")}


@router.post("/onts/transfer-to-tech")
async def transfer_ont_to_tech(payload: OntTransferIn, user: dict = Depends(require_role("gestor"))):
    """Onda 2.2 (CTO 16/02/2026): refatorado para passar por `transfer_engine`.

    Comportamento legado preservado: validações de pré-condição + history.
    Mudanças:
    - `reason` é OBRIGATÓRIO no payload (decisão CEO C).
    - Update em stok_onts agora acontece DENTRO de execute_transfer (chokepoint único).
    - Trilha em inventory_movements gravada automaticamente.

    Rollback: idempotente por audit_hash. Revert manual = `transfer_engine.execute_transfer`
    direção contrária (tecnico→empresa) com reason="Outro" + details apontando o audit_id.
    """
    from services.transfer_engine import execute_transfer, TransferEngineError
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not getattr(payload, "reason", None):
        raise HTTPException(400, {
            "error": "transfer_reason_required",
            "message": "Onda 2: transfer-to-tech exige payload.reason "
                       "({code, details?}). Vide TRANSFER_REASONS.",
        })
    mac_n = normalize_mac(payload.mac)
    tech = await _get_collab(payload.technician_id, cid)
    try:
        result = await execute_transfer(
            company_id=cid,
            origin_type="empresa", origin_id=None,
            destination_type="tecnico", destination_id=payload.technician_id,
            actor={"id": user.get("id"), "email": user.get("email"),
                    "name": user.get("name"), "role": user.get("role"),
                    "origin": "gestor_ui"},
            reason=(payload.reason.model_dump()
                     if hasattr(payload.reason, "model_dump")
                     else dict(payload.reason)),
            mac=mac_n,
        )
    except TransferEngineError as e:
        raise HTTPException(400, {"error": "transfer_blocked", "message": str(e)})
    await _add_history("transferencia",
                        f"ONT {mac_n} transferida da empresa para {tech['name']}",
                        user.get("name", "?"), "transferencia", cid)
    return {"ok": True, **result}


class OntBulkTransferIn(BaseModel):
    """Legado mantido pra compat — não usado mais pelo handler bulk."""
    macs: List[str]
    technician_id: str


@router.get("/praca-summary")
async def praca_summary(user: dict = Depends(require_role("gestor"))):
    """Saldo de ONTs e insumos por praça (agregação).

    Útil para o painel Movimento mostrar quanto cada filial tem em estoque.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # 1) Praças ativas
    pracas = await db.fin_filiais.find(
        {"company_id": cid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "default_collaborator_id": 1},
    ).sort("name", 1).to_list(200)
    # 2) ONTs disponíveis na empresa por praça
    ont_rows: list = []
    async for r in db.stok_onts.aggregate([
        {"$match": {"company_id": cid, "location_type": "empresa",
                     "status": {"$in": ["disponivel", None]}}},
        {"$group": {"_id": "$praca_id", "count": {"$sum": 1}}},
    ]):
        ont_rows.append({"praca_id": r["_id"], "count": r["count"]})
    ont_by_praca = {x["praca_id"]: x["count"] for x in ont_rows}
    # 3) Insumos (stok_stock) por praça — lê o formato real (campos por
    #    consumable_id) em docs que têm praca_id OU location "praca:<id>".
    consum_by_praca: dict = {}
    async for r in db.stok_stock.find(
        {"company_id": cid,
         "$or": [
            {"praca_id": {"$exists": True, "$ne": None}},
            {"location": {"$regex": "^praca:"}},
         ]},
        {"_id": 0},
    ):
        praca_id = r.get("praca_id")
        if not praca_id and isinstance(r.get("location"), str) \
                and r["location"].startswith("praca:"):
            praca_id = r["location"].split("praca:", 1)[1]
        if not praca_id:
            continue
        for cons in CONSUMABLE_CATALOG:
            qty = int(r.get(cons["id"], 0) or 0)
            if qty <= 0:
                continue
            consum_by_praca.setdefault(praca_id, []).append({
                "key": cons["id"], "label": cons["name"], "qty": qty,
            })
    # 4) Almoxarife / responsável por praça (collaborator com cargo=almoxarife
    #    e warehouse_praca_id = praça)
    keepers: dict = {}
    async for c in db.collaborators.find(
            {"company_id": cid, "cargo": "almoxarife",
              "active": {"$ne": False}},
            {"_id": 0, "id": 1, "name": 1, "warehouse_praca_id": 1}):
        if c.get("warehouse_praca_id"):
            keepers.setdefault(c["warehouse_praca_id"], []).append({
                "id": c["id"], "name": c["name"],
            })
    # 5) Monta resposta
    items = []
    for p in pracas:
        items.append({
            "praca_id": p["id"],
            "praca_name": p["name"],
            "ont_count": ont_by_praca.get(p["id"], 0),
            "ont_no_praca": ont_by_praca.get(None, 0)
                if p == pracas[0] else 0,  # legado sem praca_id
            "keepers": keepers.get(p["id"], []),
            "default_collaborator_id": p.get("default_collaborator_id"),
            "consumables": consum_by_praca.get(p["id"], []),
        })
    # Total de ONTs sem praça (compat com estoque legado)
    orphan_onts = ont_by_praca.get(None, 0)
    return {
        "items": items,
        "orphan_onts": orphan_onts,
    }


@router.post("/onts/transfer-to-tech/bulk")
async def transfer_onts_bulk(payload: OntBulkTransferReasonIn,
                               user: dict = Depends(require_role("gestor"))):
    """Onda 2.2: bulk via `transfer_engine`. `reason` obrigatório uma vez para o lote.

    Cada MAC vira 1 movimento individual em inventory_movements (idempotente
    por audit_hash, performed_at único). MACs falhos retornam em `skipped`.
    """
    from services.transfer_engine import execute_transfer, TransferEngineError
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not payload.reason or not (payload.reason.get("code") or "").strip():
        raise HTTPException(400, {
            "error": "transfer_reason_required",
            "message": "Bulk transfer exige reason ({code,details?}).",
        })
    macs_norm = list(dict.fromkeys(normalize_mac(m) for m in payload.macs if m))
    if not macs_norm:
        raise HTTPException(400, "Informe pelo menos um MAC.")
    tech = await _get_collab(payload.technician_id, cid)
    transferred: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for m in macs_norm:
        try:
            result = await execute_transfer(
                company_id=cid,
                origin_type="empresa", origin_id=None,
                destination_type="tecnico", destination_id=payload.technician_id,
                actor={"id": user.get("id"), "email": user.get("email"),
                        "name": user.get("name"), "role": user.get("role"),
                        "origin": "gestor_ui_bulk"},
                reason=payload.reason,
                mac=m,
            )
            transferred.append({"mac": m, "movement_id": result["movement_id"],
                                "audit_hash": result["audit_hash"]})
        except TransferEngineError as e:
            skipped.append({"mac": m, "reason": str(e)[:200]})
    if transferred:
        await _add_history(
            "transferencia",
            f"BULK Onda2: {len(transferred)} ONT(s) → {tech['name']}",
            user.get("name", "?"), "transferencia", cid,
        )
    return {
        "ok": True,
        "transferred_count": len(transferred),
        "transferred": transferred,
        "skipped": skipped,
    }


@router.post("/onts/{mac}/return-to-company")
async def return_ont_to_company(mac: str, payload: Optional[Dict[str, Any]] = None,
                                  user: dict = Depends(require_role("gestor"))):
    """Onda 2.3: refatorado para passar por `transfer_engine`. `reason` OBRIGATÓRIO.

    Rollback: idempotente por audit_hash. Reverter = transfer-to-tech com mesma ONT.
    """
    from services.transfer_engine import execute_transfer, TransferEngineError
    cid = user.get("company_id") or DEMO_COMPANY_ID
    reason = (payload or {}).get("reason")
    if not reason or not (reason.get("code") if isinstance(reason, dict) else "").strip():
        raise HTTPException(400, {
            "error": "transfer_reason_required",
            "message": "Onda 2: return-to-company exige reason ({code,details?}).",
        })
    mac_n = normalize_mac(mac)
    try:
        result = await execute_transfer(
            company_id=cid,
            origin_type="tecnico", origin_id=None,  # location_id atual da ONT
            destination_type="empresa", destination_id=None,
            actor={"id": user.get("id"), "email": user.get("email"),
                    "name": user.get("name"), "role": user.get("role"),
                    "origin": "gestor_ui"},
            reason=dict(reason),
            mac=mac_n,
            manual=True,  # tecnico→empresa não tem fluxo via OS direto
        )
    except TransferEngineError as e:
        raise HTTPException(400, {"error": "transfer_blocked", "message": str(e)})
    await _add_history("devolucao",
                        f"ONT {mac_n} devolvida ao estoque da empresa",
                        user.get("name", "?"), "retorno_empresa", cid)
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Reconciliação ONT × SmartOLT live (12/06/2026 — pedido do gestor)
# Botão "Validar ONTs" na Lousa: cruza todas as ONTs em estoque
# (empresa/técnico) contra a OLT em tempo real. Se uma ONT estiver de fato
# instalada em cliente, faz a baixa do técnico/empresa e transfere pro cliente.
# ---------------------------------------------------------------------------
@router.post("/onts/reconcile-with-olt")
async def reconcile_onts_with_olt(user: dict = Depends(require_role("gestor"))):
    """Varre todas as ONTs do estoque (location_type=empresa|tecnico) e cruza
    com SmartOLT live. Para cada ONT cujo SN/MAC aparecer ativa em algum
    assinante na OLT, faz o fluxo de saída do colaborador/empresa e marca
    como instalada no cliente real. Idempotente por SN.
    """
    from routes.smartolt import _do_sync, _get_config  # imports tardios pra evitar cycle

    cid = user.get("company_id") or DEMO_COMPANY_ID
    actor_email = user.get("email") or user.get("name") or "gestor"
    actor_name = user.get("name") or actor_email

    # Passo 1: força sync LIVE da SmartOLT (atualiza smartolt_onus)
    sync_summary: Dict[str, Any] = {"skipped": True}
    try:
        cfg = await _get_config(cid)
        if cfg.enabled and cfg.subdomain and cfg.api_key:
            sync_summary = await _do_sync(cid, cfg)
            sync_summary["skipped"] = False
    except HTTPException as e:
        # SmartOLT desconfigurada/rate-limit: segue com cache atual
        sync_summary = {"skipped": True, "reason": str(e.detail)}
    except Exception as e:  # noqa: BLE001
        logger.warning("[reconcile] sync live falhou: %s — usando cache", e)
        sync_summary = {"skipped": True, "reason": f"sync_error: {e}"}

    # Passo 2: lê estoque atual (empresa + técnico)
    stock_onts = await db.stok_onts.find(
        {"company_id": cid,
         "location_type": {"$in": ["empresa", "tecnico"]}},
        {"_id": 0},
    ).to_list(5000)

    # Passo 3: monta índices da SmartOLT (sn → onu, mac → onu)
    olt_cursor = db.smartolt_onus.find(
        {"company_id": cid},
        {"_id": 0, "sn": 1, "mac": 1, "name": 1, "pppoe_user": 1,
         "status": 1, "olt_name": 1, "unique_external_id": 1},
    )
    olt_docs = await olt_cursor.to_list(50000)
    by_sn: Dict[str, Dict[str, Any]] = {}
    by_mac: Dict[str, Dict[str, Any]] = {}
    for o in olt_docs:
        sn = (o.get("sn") or "").strip().upper()
        mac = normalize_mac(o.get("mac") or "") if o.get("mac") else ""
        if sn:
            by_sn.setdefault(sn, o)
        if mac:
            by_mac.setdefault(mac, o)

    # Passo 4: pra cada ONT em estoque, procura match na OLT
    reconciled: List[Dict[str, Any]] = []
    no_change: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for ont in stock_onts:
        ont_sn = (ont.get("scan_sn") or "").strip().upper()
        ont_mac = (ont.get("mac") or "").strip().upper()
        olt_hit = (by_sn.get(ont_sn) if ont_sn else None) \
                  or (by_mac.get(ont_mac) if ont_mac else None)
        if not olt_hit:
            no_change.append({"mac": ont_mac, "sn": ont_sn,
                              "reason": "não encontrada na OLT"})
            continue

        # Acha o assinante via pppoe_user da ONU
        pppoe = (olt_hit.get("pppoe_user") or "").strip()
        sub = None
        if pppoe:
            sub = await db.subscribers.find_one(
                {"company_id": cid, "pppoe_user": pppoe},
                {"_id": 0, "id": 1, "name": 1},
            )
        if not sub and olt_hit.get("name"):
            # Fallback: nome da ONU vs nome do assinante
            olt_name = (olt_hit.get("name") or "").strip()
            if len(olt_name) >= 5:
                sub = await db.subscribers.find_one(
                    {"company_id": cid,
                     "name": {"$regex": __import__("re").escape(olt_name[:25]),
                              "$options": "i"}},
                    {"_id": 0, "id": 1, "name": 1},
                )

        if not sub:
            no_change.append({"mac": ont_mac, "sn": ont_sn,
                              "olt_name": olt_hit.get("name"),
                              "reason": "ONU achada na OLT mas sem assinante vinculado"})
            continue

        client_id = sub["id"]
        client_name = sub["name"]

        # Captura origem pro audit
        prev_loc_type = ont.get("location_type")
        prev_loc_id = ont.get("location_id")
        prev_tech_name = None
        if prev_loc_type == "tecnico" and prev_loc_id:
            tech = await db.collaborators.find_one(
                {"id": prev_loc_id}, {"_id": 0, "name": 1})
            prev_tech_name = (tech or {}).get("name")

        # Passo 4a: se estava com técnico → registra evento de saída (withdraw)
        try:
            if prev_loc_type == "tecnico":
                await ceh.log_event(
                    company_id=cid,
                    client_id=client_id,
                    client_name=client_name,
                    action="withdraw",
                    ont_mac=ont_mac,
                    ont_sn=ont_sn or None,
                    actor_id=user.get("id"),
                    actor_name=actor_name,
                    actor_email=actor_email,
                    notes=(f"reconcile-with-olt: saída automática do técnico "
                           f"{prev_tech_name or prev_loc_id} (ONT estava "
                           f"instalada no cliente conforme OLT)"),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[reconcile] withdraw ceh falhou %s: %s", ont_mac, e)

        # Passo 4b: registra install no cliente real
        try:
            await ceh.log_event(
                company_id=cid,
                client_id=client_id,
                client_name=client_name,
                action="install",
                ont_mac=ont_mac,
                ont_sn=ont_sn or None,
                actor_id=user.get("id"),
                actor_name=actor_name,
                actor_email=actor_email,
                notes=(f"reconcile-with-olt: ONT estava em estoque "
                       f"({prev_loc_type}/{prev_tech_name or prev_loc_id}) "
                       f"mas a OLT mostra instalada — vínculo corrigido"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[reconcile] install ceh falhou %s: %s", ont_mac, e)

        # Passo 4c: atualiza stok_onts para cliente
        try:
            await db.stok_onts.update_one(
                {"company_id": cid, "mac": ont["mac"]},
                {"$set": {
                    "location_type": "cliente",
                    "location_id": client_id,
                    "client_name": client_name,
                    "status": "instalada",
                    "installed_at": now_iso(),
                    "installed_by_id": user.get("id"),
                    "installed_by_name": actor_name,
                    "installed_by_email": actor_email,
                    "installed_via_ticket": None,
                    "installed_via_service": None,
                    "reconciled_at": now_iso(),
                    "reconciled_from_location_type": prev_loc_type,
                    "reconciled_from_location_id": prev_loc_id,
                    "reconciled_from_tech_name": prev_tech_name,
                    "reconciled_source": "smartolt_live",
                    "reconciled_by_email": actor_email,
                }},
            )
            await _add_history(
                "reconcile",
                (f"ONT {ont_mac or ont_sn} reconciliada: estava em "
                 f"{prev_loc_type}/{prev_tech_name or prev_loc_id}, "
                 f"mas a OLT mostrou instalada no cliente "
                 f"'{client_name}'. Vínculo corrigido automaticamente."),
                actor_name, "reconcile_with_olt", cid,
            )
            reconciled.append({
                "mac": ont_mac, "sn": ont_sn,
                "from": {"type": prev_loc_type,
                          "id": prev_loc_id,
                          "tech_name": prev_tech_name},
                "to": {"client_id": client_id,
                        "client_name": client_name},
                "olt_status": olt_hit.get("status"),
                "olt_name": olt_hit.get("olt_name"),
            })
        except Exception as e:  # noqa: BLE001
            errors.append({"mac": ont_mac, "sn": ont_sn, "error": str(e)})
            logger.exception("[reconcile] update stok_onts falhou %s", ont_mac)

    return {
        "checked": len(stock_onts),
        "reconciled_count": len(reconciled),
        "no_change_count": len(no_change),
        "errors_count": len(errors),
        "smartolt_sync": sync_summary,
        "reconciled": reconciled,
        "no_change": no_change[:50],   # limita payload
        "errors": errors,
        "ran_at": now_iso(),
        "ran_by": actor_email,
    }


# ---------------------------------------------------------------------------
# Stock (insumos)
# ---------------------------------------------------------------------------
@router.get("/stock")
async def get_stock(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_stock.find({"company_id": cid}, {"_id": 0}).to_list(500)
    # iter171 — guard defensivo: docs sem `location` (legacy/corrompido) eram
    # KeyError → 500. Agora ignora silenciosamente.
    return {d["location"]: {c: d.get(c, 0) for c in CONSUMABLE_IDS}
              for d in docs if d.get("location")}


@router.post("/consumables/purchase")
async def purchase_consumable(payload: ConsumablePurchaseIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    item = CONSUMABLE_BY_ID.get(payload.consumable_id)
    if not item:
        raise HTTPException(400, "Insumo inválido.")
    if payload.pack_qty <= 0:
        raise HTTPException(400, "Quantidade inválida.")
    total = payload.pack_qty * item["pack_qty"]

    # iter215bd — destino opcional: técnico OU empresa
    tech_target = None
    if payload.technician_id:
        tech_target = await db.collaborators.find_one(
            {"id": payload.technician_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not tech_target:
            raise HTTPException(404, "Técnico de destino não encontrado.")

    location = tech_target["id"] if tech_target else "empresa"
    dest_label = (f"estoque de {tech_target['name']}" if tech_target
                   else "estoque da empresa")

    await db.stok_stock.update_one(
        {"company_id": cid, "location": location},
        {"$inc": {item["id"]: total},
         "$setOnInsert": {"company_id": cid, "location": location}},
        upsert=True,
    )
    await _add_history("entrada_insumo",
                       f"Entrada de {payload.pack_qty} {item['pack_label']}(s) "
                       f"de {item['name']}: {total} {item['unit']} no {dest_label}",
                       user.get("name", "?"), "compra", cid)
    return {
        "ok": True, "added": total,
        "destination": ("tecnico:" + tech_target["id"]) if tech_target
            else "empresa",
        "destination_name": tech_target["name"] if tech_target
            else "Estoque da empresa",
    }


@router.post("/consumables/transfer")
async def transfer_consumable(payload: ConsumableTransferIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    item = CONSUMABLE_BY_ID.get(payload.consumable_id)
    if not item:
        raise HTTPException(400, "Insumo inválido.")
    if payload.quantity <= 0:
        raise HTTPException(400, "Quantidade inválida.")
    empresa = await db.stok_stock.find_one({"company_id": cid, "location": "empresa"}, {"_id": 0})
    if not empresa or empresa.get(item["id"], 0) < payload.quantity:
        raise HTTPException(400, "Estoque da empresa insuficiente.")
    tech = await _get_collab(payload.technician_id, cid)
    await db.stok_stock.update_one(
        {"company_id": cid, "location": "empresa"}, {"$inc": {item["id"]: -payload.quantity}},
    )
    await db.stok_stock.update_one(
        {"company_id": cid, "location": payload.technician_id},
        {"$inc": {item["id"]: payload.quantity},
         "$setOnInsert": {"company_id": cid, "location": payload.technician_id}},
        upsert=True,
    )
    await _add_history("transferencia_insumo",
                       f"{payload.quantity} {item['unit']} de {item['name']} transferidos da empresa para {tech['name']}",
                       user.get("name", "?"), "transferencia", cid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Endpoint PÚBLICO (mobile) — saldo do técnico
# ---------------------------------------------------------------------------
@router.get("/public/collaborator/{collaborator_id}/stock")
async def public_get_collaborator_stock(collaborator_id: str):
    """Saldo de insumos + ONTs em poder do técnico, pra exibir na finalização da nota.

    Resposta:
    {
      "consumables": [{id, name, unit, qty}],
      "onts": [{mac, model, status}]
    }
    """
    coll = await db.collaborators.find_one(
        {"id": collaborator_id}, {"_id": 0, "company_id": 1, "name": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    cid = coll.get("company_id") or DEMO_COMPANY_ID
    stock_doc = await db.stok_stock.find_one(
        {"company_id": cid, "location": collaborator_id}, {"_id": 0},
    ) or {}
    consumables = [{
        "id": c["id"], "name": c["name"], "unit": c["unit"],
        "qty": int(stock_doc.get(c["id"], 0)),
    } for c in CONSUMABLE_CATALOG]
    onts = await db.stok_onts.find(
        {"company_id": cid, "location_type": "tecnico", "location_id": collaborator_id},
        {"_id": 0, "mac": 1, "model": 1, "status": 1, "scan_sn": 1},
    ).to_list(200)
    # iter197 — SN é o identificador prevalente: expõe `sn` no nível raiz
    for o in onts:
        o["sn"] = o.get("scan_sn") or None
    return {
        "collaborator_id": collaborator_id,
        "collaborator_name": coll.get("name"),
        "consumables": consumables, "onts": onts,
    }



# ---------------------------------------------------------------------------
# Services (OS)
# ---------------------------------------------------------------------------
@router.get("/services")
async def list_services(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_services.find({"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return docs


@router.post("/services")
async def create_service(payload: ServiceIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if payload.type not in {"instalacao", "reparo", "troca", "retirada", "ponto_adicional"}:
        raise HTTPException(400, "Tipo de serviço inválido.")
    tech = await _get_collab(payload.technician_id, cid)
    sid = f"OS-{uuid.uuid4().hex[:6].upper()}"
    doc = {
        "id": sid, "company_id": cid, "type": payload.type,
        "client_id": payload.client_id.strip(), "client_name": payload.client_name.strip(),
        "technician_id": payload.technician_id, "status": "ativo",
        "reason": payload.reason, "ticket_id": payload.ticket_id,
        "created_at": now_iso(),
    }
    await db.stok_services.insert_one(dict(doc))
    await _add_history("servico",
                       f"Serviço {sid} ({payload.type}) aberto para {doc['client_name']} - Técnico {tech['name']}",
                       user.get("name", "?"), payload.type, cid)
    return doc


def _validate_used_items(used_items: List[UsedItem]) -> None:
    for ui in used_items:
        if ui.consumable_id not in CONSUMABLE_IDS:
            raise HTTPException(400, f"Insumo inválido: {ui.consumable_id}")
        if ui.quantity < 0:
            raise HTTPException(400, "Quantidade não pode ser negativa.")


async def _check_tech_has_stock(company_id: str, technician_id: str, tech_name: str,
                                 used_items: List[UsedItem]) -> List[Dict[str, Any]]:
    """iter168 — Detecta itens que ficarão NEGATIVOS após o consumo.

    NÃO bloqueia mais a baixa: retorna a lista de "quebras" (itens cujo
    saldo do técnico não cobre o consumo) para auditoria + notificação.
    Permitir saldo negativo dá visibilidade à QUEBRA (material usado fora
    de controle, perdido ou roubado).
    """
    tech_stock = await db.stok_stock.find_one(
        {"company_id": company_id, "location": technician_id}, {"_id": 0},
    ) or {}
    shortages: List[Dict[str, Any]] = []
    for ui in used_items:
        if ui.quantity <= 0:
            continue
        cur = tech_stock.get(ui.consumable_id, 0) or 0
        if cur < ui.quantity:
            item = CONSUMABLE_BY_ID[ui.consumable_id]
            shortages.append({
                "consumable_id": ui.consumable_id,
                "name": item["name"],
                "unit": item["unit"],
                "current": cur,
                "needed": ui.quantity,
                "deficit": ui.quantity - cur,
                "tech_id": technician_id,
                "tech_name": tech_name,
            })
    return shortages


async def _notify_negative_stock(company_id: str, shortages: List[Dict[str, Any]],
                                    service_id: Optional[str] = None,
                                    ticket_id: Optional[str] = None) -> None:
    """iter168 — Cria notificação para o gestor quando há QUEBRA (saldo negativo)."""
    if not shortages:
        return
    try:
        tech_name = shortages[0].get("tech_name") or "técnico"
        details = "; ".join(
            f"{s['name']}: faltou {s['deficit']} {s['unit']}"
            for s in shortages
        )
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "type": "stok_negative_balance",
            "title": f"📉 Saldo negativo — {tech_name}",
            "message": (
                f"{tech_name} consumiu material além do saldo. Quebra detectada: "
                f"{details}. Verifique se houve uso fora de OS, perda ou se "
                f"é necessário registrar uma compra."
            ),
            "severity": "warning",
            "created_at": now_iso(),
            "read_by": [],
            "audience_role": "gestor",
            "ticket_id": ticket_id,
            "service_id": service_id,
        })
    except Exception as e:
        logger.warning("[stok] notify negative stock falhou: %s", e)


async def _move_ont_for_install(company_id: str, service: dict, mac_input: Optional[str],
                                  installer_name: Optional[str] = None,
                                  installer_email: Optional[str] = None) -> str:
    """Move ONT do estoque do técnico para o cliente. Compara MAC com SmartOLT:
    se bater → status='instalada', transferência OK; se não bater → cria
    `pending_transfer` aguardando aprovação do gestor; ONT NÃO é movida.

    `installer_name`/`installer_email` (iter163) — gravados em `stok_onts`
    e no histórico do equipamento por cliente (`client_equipment_history`).

    iter197 — SN prevalente: se `service.ont_sn` está preenchido, busca a ONT
    primeiro por SN (`scan_sn`), depois cai para MAC. Aceita instalação
    quando só o SN foi informado (MAC fica vazio até o SmartOLT propagar).
    """
    sn_input = (service.get("ont_sn") or "").strip().upper() or None
    if not mac_input and not sn_input:
        raise HTTPException(400, "Para instalação/troca, informe o SN da ONT (obrigatório).")
    # iter197 — busca por SN PRIMEIRO; se achou e ainda não temos MAC, herda do doc
    # iter211h — busca tolerante: normaliza SN (sem hífens/espaços/dois-pontos)
    # e cai pra busca parcial quando exact match falha. Isso resolve casos
    # em que o OCR detecta SN com caracteres a mais/menos.
    ont = None
    sn_norm = None
    if sn_input:
        sn_norm = sn_input.replace("-", "").replace(":", "").replace(" ", "")
        # 1) Match exato (case já está upper)
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "scan_sn": sn_input}, {"_id": 0})
        # 2) Match normalizado (compara sem separadores)
        if not ont and sn_norm != sn_input:
            ont = await db.stok_onts.find_one(
                {"company_id": company_id, "scan_sn": sn_norm}, {"_id": 0})
        # 3) Match por sufixo (últimos 8+ chars) — útil quando OCR comeu prefixo
        if not ont and len(sn_norm) >= 8:
            tail = sn_norm[-8:]
            ont = await db.stok_onts.find_one(
                {"company_id": company_id,
                  "scan_sn": {"$regex": f"{tail}$", "$options": "i"}},
                {"_id": 0})
    mac_n = normalize_mac(mac_input) if mac_input else None
    if not ont and mac_n:
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "mac": mac_n}, {"_id": 0})
    if not ont:
        ident = sn_input or mac_n
        raise HTTPException(
            404,
            f"ONT com SN '{ident}' não encontrada no estoque. "
            "Cadastre a ONT em Estoque › Equipamentos antes de finalizar. "
            "A base é obrigatória pelo SN."
        )
    # Garante mac_n preenchido para os updates subsequentes
    if not mac_n:
        mac_n = ont.get("mac")
    if ont["location_type"] != "tecnico" or ont["location_id"] != service["technician_id"]:
        # iter215bc — mensagem detalhada com diagnóstico para correção rápida
        # do bug "ONT cadastrada mas não aparece no estoque do técnico".
        if ont["location_type"] == "empresa":
            raise HTTPException(400,
                "A ONT está no estoque da EMPRESA (não no técnico). "
                "Vá em Estoque › Equipamentos e use '↗ Transferir' para "
                "enviar a ONT ao técnico antes de fechar a OS.")
        elif ont["location_type"] == "tecnico":
            other_tech = await db.collaborators.find_one(
                {"id": ont["location_id"]}, {"_id": 0, "name": 1})
            raise HTTPException(400,
                f"A ONT está no estoque de OUTRO técnico "
                f"({other_tech['name'] if other_tech else ont['location_id']}). "
                f"Ela precisa estar no estoque do técnico responsável "
                f"pela OS para ser usada.")
        elif ont["location_type"] == "cliente":
            raise HTTPException(400,
                f"A ONT já está instalada no cliente "
                f"'{ont.get('client_name') or ont.get('location_id')}'. "
                f"Faça uma retirada primeiro.")
        else:
            raise HTTPException(400,
                f"A ONT está em local inesperado "
                f"({ont['location_type']}). Verifique em Estoque › "
                f"Equipamentos › Rastreabilidade.")

    # Consulta SmartOLT (cache local) pelo MAC ATIVO do cliente
    sm_doc = await db.smartolt_onus.find_one(
        {"company_id": company_id, "client_id": service["client_id"]},
        {"_id": 0, "unique_external_id": 1, "sn": 1, "name": 1, "status": 1},
    )
    smart_mac_raw = (sm_doc or {}).get("unique_external_id") or (sm_doc or {}).get("sn")
    smart_mac_n = normalize_mac(smart_mac_raw) if smart_mac_raw else None

    # Caso 1: SmartOLT tem MAC e bate → instala normalmente
    if smart_mac_n and smart_mac_n == mac_n:
        await db.stok_onts.update_one(
            {"company_id": company_id, "mac": mac_n},
            {"$set": {"location_type": "cliente",
                       "location_id": service["client_id"],
                       "client_name": service["client_name"],
                       "status": "instalada",
                       "installed_at": now_iso(),
                       "installed_by_id": service.get("technician_id"),
                       "installed_by_name": installer_name,
                       "installed_by_email": installer_email,
                       "installed_via_ticket": service.get("ticket_id"),
                       "installed_via_service": service.get("id")}},
        )
        # iter163 — registra evento de instalação por cliente
        await ceh.log_event(
            company_id=company_id,
            client_id=service["client_id"],
            client_name=service.get("client_name"),
            action="install",
            ont_mac=mac_n,
            ont_sn=ont.get("scan_sn"),
            actor_id=service.get("technician_id"),
            actor_name=installer_name,
            actor_email=installer_email,
            ticket_id=service.get("ticket_id"),
            service_id=service.get("id"),
            notes=f"ONT instalada · SmartOLT MAC bate ({smart_mac_n})",
        )
        # iter164 — detecta ONT duplicada (mesmo MAC/SN em outro cliente recente)
        await ont_dup.detect_and_log(
            company_id=company_id,
            client_id=service["client_id"],
            client_name=service.get("client_name"),
            ont_mac=mac_n,
            ont_sn=ont.get("scan_sn"),
            actor_name=installer_name,
            actor_email=installer_email,
            ticket_id=service.get("ticket_id"),
            service_id=service.get("id"),
        )
        return (f"✅ Transferência com sucesso · ONT {mac_n} instalada no "
                f"{service['client_name']} (SmartOLT: {smart_mac_n} bate)")

    # Caso 2: SmartOLT NÃO encontrado → permite install mas marca pendente
    # Caso 3: SmartOLT tem MAC diferente → também pendente
    # iter166 — Se toggle `mac_validation_required` está LIGADO, bloqueia
    # ao invés de criar pending (admin exige validação estrita).
    toggles_doc = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": "os_validation_toggles"},
        {"_id": 0, "value": 1},
    )
    mac_strict = bool(((toggles_doc or {}).get("value") or {})
                        .get("mac_validation_required"))
    if mac_strict:
        if not smart_mac_n:
            raise HTTPException(
                400,
                f"Validação estrita de MAC habilitada: SmartOLT sem registro "
                f"para o cliente {service['client_name']}. Sincronize o "
                f"SmartOLT ou desabilite a validação estrita no painel.",
            )
        raise HTTPException(
            400,
            f"Validação estrita de MAC habilitada: MAC do estoque ({mac_n}) "
            f"difere do MAC ativo do cliente no SmartOLT ({smart_mac_n}). "
            f"Verifique o equipamento ou desabilite a validação estrita "
            f"no painel.",
        )

    pending_doc = {
        "id": f"pt-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "service_id": service.get("id"),
        "kind": "install_mac_mismatch",
        "technician_id": service["technician_id"],
        "client_id": service["client_id"],
        "client_name": service.get("client_name"),
        "stock_mac": mac_n,
        "stock_sn": ont.get("scan_sn"),
        "smartolt_mac": smart_mac_n,
        "smartolt_sn": (sm_doc or {}).get("sn"),
        "smartolt_status": (sm_doc or {}).get("status"),
        "reason": ("SmartOLT sem registro pro cliente"
                    if not smart_mac_n
                    else "MAC do estoque difere do MAC ativo no SmartOLT"),
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.stok_pending_transfers.insert_one(pending_doc)
    # ONT continua com o técnico mas marcamos com flag de pendência
    await db.stok_onts.update_one(
        {"company_id": company_id, "mac": mac_n},
        {"$set": {"pending_install_to_client": service["client_id"],
                   "pending_install_service_id": service.get("id"),
                   "pending_transfer_id": pending_doc["id"],
                   "status": "pendente_aprovacao_gestor"}},
    )
    if not smart_mac_n:
        return (f"⚠️ Transferência pendente · ONT {mac_n} aguardando aprovação "
                f"do gestor (SmartOLT sem registro pro cliente {service['client_name']})")
    return (f"⚠️ Transferência pendente · SN estoque: {mac_n} · "
            f"SN SmartOLT: {smart_mac_n} · aguardando aprovação do gestor")


async def _move_ont_for_withdraw(company_id: str, service: dict, tech_name: str,
                                  mac_input: Optional[str],
                                  withdrawer_email: Optional[str] = None) -> str:
    """iter174 — Aceita MAC OU SN para identificar a ONT retirada. Antes
    exigia o MAC; agora qualquer um dos 2 valida (OCR lê o que conseguir
    no equipamento).
    """
    sn_input = (service.get("ont_sn") or "").strip().upper() or None
    if not mac_input and not sn_input:
        raise HTTPException(400, "Para retirada, informe o SN da ONT retirada (base obrigatória).")
    mac_n = normalize_mac(mac_input) if mac_input else None
    # Equipamento marcado como defeituoso (iter153) — fica bloqueado para
    # reinstalar em outro cliente; volta direto pro estoque "empresa" como
    # `defeito_devolver_empresa`.
    is_defective = bool(service.get("is_defective"))
    defective_reason = (service.get("defective_reason") or "").strip()[:300] or None
    ont_status = "defeito_devolver_empresa" if is_defective else "retirada_com_tecnico"
    # iter163 — quem retirou (email + nome do técnico)
    actor_email = withdrawer_email or service.get("closed_by_email")
    # Quando defeituoso, o destino lógico permanece "tecnico" (precisa
    # devolver fisicamente), mas o status bloqueia a seleção como ONT
    # disponível em novas instalações (filtros de estoque excluem este).
    extra_fields: Dict[str, Any] = {}
    if is_defective:
        extra_fields["is_defective"] = True
        extra_fields["defective_marked_at"] = now_iso()
        extra_fields["defective_marked_by"] = actor_email
        if defective_reason:
            extra_fields["defective_reason"] = defective_reason
    # iter211h — busca por SN PRIMEIRO (base obrigatória), MAC só como fallback
    ont = None
    if sn_input:
        # 1) Match exato
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "scan_sn": sn_input}, {"_id": 0})
        # 2) Match normalizado (sem separadores)
        sn_norm = sn_input.replace("-", "").replace(":", "").replace(" ", "")
        if not ont and sn_norm != sn_input:
            ont = await db.stok_onts.find_one(
                {"company_id": company_id, "scan_sn": sn_norm}, {"_id": 0})
        # 3) Match por sufixo (últimos 8+ chars) — tolerante a OCR ruim
        if not ont and len(sn_norm) >= 8:
            tail = sn_norm[-8:]
            ont = await db.stok_onts.find_one(
                {"company_id": company_id,
                  "scan_sn": {"$regex": f"{tail}$", "$options": "i"}},
                {"_id": 0})
        if ont and not mac_n:
            mac_n = ont.get("mac")
    if not ont and mac_n:
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "mac": mac_n}, {"_id": 0})
    # Identificador a exibir nas mensagens (preferência: SN, fallback MAC)
    ident = sn_input or mac_n
    if not ont:
        # ONT não cadastrada — cria registro novo já no estoque do técnico
        # com origem `ai_scan_retirada` (técnico fotografou e IA leu).
        # iter174 — se não tem MAC mas tem SN, gera um placeholder único
        ont_mac_final = mac_n or f"SN-{sn_input}"
        await db.stok_onts.insert_one({
            "company_id": company_id,
            "mac": ont_mac_final,
            "model": (service.get("ont_model") or "Desconhecido")[:120],
            "location_type": "tecnico",
            "location_id": service["technician_id"],
            "praca_id": service.get("praca_id"),
            "warehouse_responsible_id": None,
            "purchase_id": None,
            "client_name": None,
            "status": ont_status,
            "created_by": "ai_scan_retirada",
            "created_at": now_iso(),
            "source": "ai_scan_retirada",
            "scan_sn": sn_input,
            **extra_fields,
        })
        suffix = " — marcada como DEFEITUOSA (devolver à empresa)" if is_defective else ""
        return (f"ONT {ident} (não cadastrada) registrada via scan IA "
                f"e entrou no estoque de {tech_name}{suffix}")
    # A partir daqui temos `ont` carregada. Garante `mac_n` setado.
    if not mac_n:
        mac_n = ont.get("mac")
    if ont["location_type"] != "cliente" or ont["location_id"] != service["client_id"]:
        # Caso inconsistente: força a baixa pro técnico mesmo assim
        # (a foto + IA é prova auditável); marca o desvio em notes
        await db.stok_onts.update_one(
            {"company_id": company_id, "mac": mac_n},
            {"$set": {"location_type": "tecnico",
                       "location_id": service["technician_id"],
                       "client_name": None,
                       "status": ont_status,
                       "withdraw_inconsistency": True,
                       "withdraw_inconsistency_note":
                           f"prev_loc={ont.get('location_type')}/{ont.get('location_id')}",
                       "source": "retirada",
                       "withdrawn_from_client_id": service["client_id"],
                       "withdrawn_from_client_name": service.get("client_name"),
                       "withdrawn_by_email": actor_email,
                       "withdrawn_by_name": tech_name,
                       "withdrawn_via_ticket": service.get("ticket_id"),
                       "withdrawn_via_service": service.get("id"),
                       "withdrawn_at": now_iso(),
                       **extra_fields}},
        )
        await ceh.log_event(
            company_id=company_id,
            client_id=service["client_id"],
            client_name=service.get("client_name"),
            action="withdraw",
            ont_mac=mac_n,
            ont_sn=ont.get("scan_sn"),
            actor_id=service.get("technician_id"),
            actor_name=tech_name,
            actor_email=actor_email,
            ticket_id=service.get("ticket_id"),
            service_id=service.get("id"),
            notes=f"vínculo prévio divergente: {ont.get('location_type')}/{ont.get('location_id')}",
        )
        suffix = " (DEFEITUOSA)" if is_defective else ""
        return (f"ONT {mac_n} retirada via scan IA e entrou no estoque "
                f"de {tech_name}{suffix} (atenção: vínculo prévio divergente)")
    await db.stok_onts.update_one(
        {"company_id": company_id, "mac": mac_n},
        {"$set": {"location_type": "tecnico", "location_id": service["technician_id"],
                  "client_name": None, "status": ont_status,
                  "source": "retirada",
                  "withdrawn_from_client_id": service["client_id"],
                  "withdrawn_from_client_name": service.get("client_name"),
                  "withdrawn_by_email": actor_email,
                  "withdrawn_by_name": tech_name,
                  "withdrawn_via_ticket": service.get("ticket_id"),
                  "withdrawn_via_service": service.get("id"),
                  "withdrawn_at": now_iso(),
                  **extra_fields}},
    )
    # iter163 — registra evento de retirada por cliente
    await ceh.log_event(
        company_id=company_id,
        client_id=service["client_id"],
        client_name=service.get("client_name"),
        action="withdraw",
        ont_mac=mac_n,
        ont_sn=ont.get("scan_sn"),
        actor_id=service.get("technician_id"),
        actor_name=tech_name,
        actor_email=actor_email,
        ticket_id=service.get("ticket_id"),
        service_id=service.get("id"),
        notes=("DEFEITUOSA — " + (defective_reason or "sem motivo informado")) if is_defective else None,
    )
    if is_defective:
        return (f"ONT {mac_n} retirada do {service['client_name']} marcada como "
                f"DEFEITUOSA — devolução obrigatória à empresa, não disponível "
                f"para nova instalação")
    return f"ONT {mac_n} retirada do {service['client_name']} e entrou no estoque de {tech_name}"


async def _find_client_cto_port(company_id: str, client_id: str
                                  ) -> Optional[Dict[str, Any]]:
    """Localiza a porta da CTO em que o cliente está atualmente vinculado.
    Retorna {cto_id, cto_name, port_number, port_dict} ou None.
    """
    if not client_id:
        return None
    cto = await db.ctos.find_one(
        {"company_id": company_id,
         "ports.client_subscriber_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "ports": 1},
    )
    if not cto:
        return None
    for p in (cto.get("ports") or []):
        if p.get("client_subscriber_id") == client_id:
            return {
                "cto_id": cto["id"],
                "cto_name": cto.get("name"),
                "port_number": p.get("number"),
                "port_dict": p,
            }
    return None


async def _free_cto_port(company_id: str, cto_id: str, port_number: int,
                           user_email: Optional[str], reason: str,
                           *, client_id: Optional[str] = None,
                           client_name: Optional[str] = None,
                           actor_name: Optional[str] = None,
                           ticket_id: Optional[str] = None,
                           service_id: Optional[str] = None) -> None:
    """Libera uma porta (status=free + limpa campos do cliente).

    iter163 — registra `port_release` no histórico do cliente se `client_id`
    for fornecido.
    """
    # Captura nome da CTO p/ histórico (best-effort)
    cto_name = None
    if client_id:
        cto_doc = await db.ctos.find_one(
            {"id": cto_id, "company_id": company_id}, {"_id": 0, "name": 1})
        cto_name = (cto_doc or {}).get("name")
    await db.ctos.update_one(
        {"id": cto_id, "company_id": company_id, "ports.number": port_number},
        {"$set": {
            "ports.$.status": "free",
            "ports.$.client_subscriber_id": None,
            "ports.$.client_pppoe": None,
            "ports.$.client_name": None,
            "ports.$.client_phone": None,
            "ports.$.released_at": now_iso(),
            "ports.$.released_by_email": user_email,
            "ports.$.release_reason": reason,
            "updated_at": now_iso(),
        }},
    )
    if client_id:
        await ceh.log_event(
            company_id=company_id, client_id=client_id,
            client_name=client_name, action="port_release",
            cto_id=cto_id, cto_name=cto_name,
            cto_port_number=port_number,
            actor_name=actor_name, actor_email=user_email,
            ticket_id=ticket_id, service_id=service_id,
            notes=f"motivo: {reason}",
        )
    # iter182 — sync para a base denormalizada `cto_ports`
    try:
        from routes.cto_ports_base import sync_port_from_cto
        await sync_port_from_cto(company_id, cto_id, port_number)
    except Exception as e:
        logger.warning("[stok] sync_port_from_cto(free) falhou: %s", e)


async def _occupy_cto_port(company_id: str, cto_id: str, port_number: int,
                              client_id: str, client_name: Optional[str],
                              client_pppoe: Optional[str],
                              user_email: Optional[str],
                              *, actor_name: Optional[str] = None,
                              ticket_id: Optional[str] = None,
                              service_id: Optional[str] = None,
                              is_swap: bool = False,
                              prev_cto_id: Optional[str] = None,
                              prev_port_number: Optional[int] = None) -> bool:
    """Ocupa uma porta livre. Retorna False se a porta não existe ou
    já está ocupada por outro cliente.

    iter163 — registra `port_link` (instalação) ou `port_swap` (troca) no
    histórico do cliente.
    iter182 — REJEITA chamadas sem client_id válido (regra: porta
    ocupada SEMPRE tem cliente cadastrado).
    """
    if not client_id or not str(client_id).strip():
        logger.warning(
            "[stok] _occupy_cto_port REJEITADO: client_id vazio "
            "(cto=%s p=%s)", cto_id, port_number)
        return False
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": company_id}, {"_id": 0, "ports": 1, "name": 1})
    if not cto:
        return False
    target = next((p for p in (cto.get("ports") or [])
                    if p.get("number") == port_number), None)
    if not target:
        return False
    if target.get("status") == "used" and \
       target.get("client_subscriber_id") != client_id:
        return False
    await db.ctos.update_one(
        {"id": cto_id, "company_id": company_id, "ports.number": port_number},
        {"$set": {
            "ports.$.status": "used",
            "ports.$.client_subscriber_id": client_id,
            "ports.$.client_name": client_name,
            "ports.$.client_pppoe": client_pppoe,
            "ports.$.linked_by_user_email": user_email,
            "ports.$.linked_at": now_iso(),
            "updated_at": now_iso(),
        }},
    )
    await ceh.log_event(
        company_id=company_id, client_id=client_id,
        client_name=client_name,
        action="port_swap" if is_swap else "port_link",
        cto_id=cto_id, cto_name=cto.get("name"),
        cto_port_number=port_number,
        prev_cto_id=prev_cto_id, prev_cto_port_number=prev_port_number,
        actor_name=actor_name, actor_email=user_email,
        ticket_id=ticket_id, service_id=service_id,
    )
    # iter182 — sync para a base denormalizada `cto_ports`
    try:
        from routes.cto_ports_base import sync_port_from_cto
        await sync_port_from_cto(company_id, cto_id, port_number)
    except Exception as e:
        logger.warning("[stok] sync_port_from_cto(occupy) falhou: %s", e)
    return True


async def _handle_cto_port_on_close(company_id: str, service: dict,
                                       payload: "ServiceCloseIn",
                                       user_email: Optional[str],
                                       actor_name: Optional[str] = None
                                       ) -> Optional[str]:
    """Atualiza a porta da CTO ao fechar a OS:

    - retirada: libera porta atual do cliente (auto).
    - instalacao/manutencao/troca:
        * cliente já tem porta + port_swap=true → libera atual + ocupa nova
          (mesma CTO).
        * cliente já tem porta + port_swap=false → mantém.
        * cliente SEM porta + cto_id/cto_port_number informados → ocupa.
    """
    stype = service.get("type")
    client_id = service.get("client_id")
    current = await _find_client_cto_port(company_id, client_id)
    ticket_id = service.get("ticket_id")
    service_id = service.get("id")
    client_name = service.get("client_name")

    if stype == "retirada":
        if current:
            await _free_cto_port(company_id, current["cto_id"],
                                   current["port_number"], user_email,
                                   "retirada",
                                   client_id=client_id, client_name=client_name,
                                   actor_name=actor_name, ticket_id=ticket_id,
                                   service_id=service_id)
            return (f"Porta {current['port_number']} ({current['cto_name']}) "
                    f"liberada — cliente retirado")
        return None

    if stype in ("instalacao", "reparo", "troca", "troca_endereco",
                   "ponto_adicional"):
        if current and payload.port_swap:
            new_port = payload.new_port_number
            if not new_port:
                raise HTTPException(400, "Para troca de porta informe new_port_number")
            if new_port == current["port_number"]:
                raise HTTPException(400, "A nova porta é igual à porta atual")
            ok = await _occupy_cto_port(
                company_id, current["cto_id"], new_port, client_id,
                client_name,
                (current["port_dict"] or {}).get("client_pppoe"),
                user_email,
                actor_name=actor_name, ticket_id=ticket_id,
                service_id=service_id, is_swap=True,
                prev_cto_id=current["cto_id"],
                prev_port_number=current["port_number"],
            )
            if not ok:
                raise HTTPException(409, f"Porta {new_port} indisponível ou ocupada")
            await _free_cto_port(company_id, current["cto_id"],
                                   current["port_number"], user_email,
                                   "port_swap",
                                   client_id=None)  # já logado como port_swap
            return (f"Porta trocada {current['port_number']} → {new_port} "
                    f"({current['cto_name']})")
        if not current and payload.cto_id and payload.cto_port_number:
            ok = await _occupy_cto_port(
                company_id, payload.cto_id, payload.cto_port_number,
                client_id, client_name, None, user_email,
                actor_name=actor_name, ticket_id=ticket_id,
                service_id=service_id,
            )
            if not ok:
                raise HTTPException(409,
                    f"Porta {payload.cto_port_number} indisponível")
            return f"Cliente vinculado à porta {payload.cto_port_number}"
    return None


async def _decrement_tech_stock(company_id: str, technician_id: str,
                                  used_items: List[UsedItem]) -> Optional[str]:
    inc: Dict[str, int] = {}
    for ui in used_items:
        if ui.quantity > 0:
            inc[ui.consumable_id] = inc.get(ui.consumable_id, 0) - ui.quantity
    if not inc:
        return None
    await db.stok_stock.update_one(
        {"company_id": company_id, "location": technician_id},
        {"$inc": inc, "$setOnInsert": {"company_id": company_id, "location": technician_id}},
        upsert=True,
    )
    return "Materiais baixados: " + "; ".join(
        f"{CONSUMABLE_BY_ID[cid]['name']}: {abs(q)} {CONSUMABLE_BY_ID[cid]['unit']}"
        for cid, q in inc.items()
    )


@router.post("/services/{service_id}/close")
async def close_service(service_id: str, payload: ServiceCloseIn,
                         request: Request,
                         user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # ─── Onda 0c — Observabilidade obrigatória (ROTA LEGADA) ─────────────
    # Esta rota direta de fechamento de service é candidata a sunset.
    # Logamos QUEM, QUANDO e DE ONDE chama para mapear callers em 7 dias.
    # Nenhuma alteração funcional. Janela de observação definida pelo CEO.
    try:
        import os as _os
        if _os.environ.get("STOK_CLOSE_LEGACY_DEPRECATED", "true").lower() in (
                "1", "true", "yes", "on"):
            headers = request.headers if request else {}
            referer = headers.get("referer") or headers.get("referrer")
            ua = headers.get("user-agent")
            xff = headers.get("x-forwarded-for")
            origin = headers.get("origin")
            logger.warning(
                "[stok][LEGACY][close_service] service=%s company=%s "
                "gestor=%s/%s referer=%s ua=%s",
                service_id, cid, user.get("id"), user.get("email"),
                referer, (ua or "")[:120],
            )
            await db.stok_close_legacy_observability.insert_one({
                "id": f"sclo-{service_id}-{int(datetime.now(timezone.utc).timestamp()*1000)}",
                "service_id": service_id,
                "company_id": cid,
                "gestor_id": user.get("id"),
                "gestor_email": user.get("email"),
                "gestor_name": user.get("name"),
                "referer": referer,
                "origin": origin,
                "user_agent": (ua or "")[:255],
                "x_forwarded_for": xff,
                "payload_keys": sorted(list(
                    payload.model_dump().keys()))[:50],
                "ont_mac": payload.ont_mac,
                "ont_sn": payload.ont_sn,
                "called_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as _obs_err:  # pragma: no cover — observabilidade nunca quebra
        logger.warning("[stok] close_service legacy observability falhou: %s",
                       _obs_err)
    # ──────────────────────────────────────────────────────────────────────

    service = await db.stok_services.find_one(
        {"id": service_id, "company_id": cid,
         "status": {"$in": ["ativo", "erro_estoque"]}}, {"_id": 0},
    )
    if not service:
        raise HTTPException(404, "Serviço ativo não encontrado. Sem serviço ativo não existe baixa de estoque.")
    tech = await _get_collab(service["technician_id"], cid)

    _validate_used_items(payload.used_items)
    shortages = await _check_tech_has_stock(
        cid, service["technician_id"], tech["name"], payload.used_items)

    parts: List[str] = []
    if service["type"] in ("instalacao", "troca"):
        parts.append(await _move_ont_for_install(
            cid, service, payload.ont_mac,
            installer_name=tech["name"], installer_email=user.get("email")))
    elif service["type"] == "retirada":
        # iter174 — propaga SN p/ _move_ont_for_withdraw via service
        if payload.ont_sn and not service.get("ont_sn"):
            service["ont_sn"] = payload.ont_sn.strip().upper() or None
        parts.append(await _move_ont_for_withdraw(
            cid, service, tech["name"], payload.ont_mac,
            withdrawer_email=user.get("email")))

    stock_desc = await _decrement_tech_stock(cid, service["technician_id"], payload.used_items)
    if stock_desc:
        parts.append(stock_desc)
    # iter168 — Notifica gestor se houver quebra (saldo negativo)
    if shortages:
        await _notify_negative_stock(cid, shortages, service_id=service_id)
        parts.append("⚠️ QUEBRA: " + ", ".join(
            f"{s['name']} -{s['deficit']} {s['unit']}" for s in shortages))

    # Atualiza vínculo de porta na CTO (troca/retirada/instalação)
    try:
        port_desc = await _handle_cto_port_on_close(
            cid, service, payload, user.get("email"), actor_name=tech["name"])
        if port_desc:
            parts.append(port_desc)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[stok] handle_cto_port_on_close falhou: %s", e)

    await db.stok_services.update_one(
        {"id": service_id, "company_id": cid},
        {"$set": {"status": "fechado", "closed_at": now_iso()}},
    )

    htype = "retirada" if service["type"] == "retirada" else "instalacao"
    await _add_history(
        htype,
        f"{service_id} - {' | '.join(parts) if parts else 'Serviço fechado'} - Técnico {tech['name']}",
        tech["name"], payload.tag, cid,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@router.get("/history")
async def list_history(
    user: dict = Depends(require_role("gestor")),
    tag: Optional[str] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 500,
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    query: Dict[str, Any] = {"company_id": cid}
    if tag:
        query["tag"] = tag
    if type:
        query["type"] = type
    if q:
        query["description"] = {"$regex": q, "$options": "i"}
    docs = await db.stok_history.find(query, {"_id": 0}).sort("date", -1).to_list(limit)
    return docs


def _fmt_dt_br(iso: Optional[str]) -> str:
    # iter183 — usa helper global; antes mantinha UTC sem conversão.
    from core import fmt_br_dt
    return fmt_br_dt(iso, "%d/%m/%Y %H:%M") if iso else "—"


async def _filter_history(user: dict, tag: Optional[str], type_: Optional[str],
                           q: Optional[str], limit: int) -> List[dict]:
    cid = user.get("company_id") or DEMO_COMPANY_ID
    query: Dict[str, Any] = {"company_id": cid}
    if tag:
        query["tag"] = tag
    if type_:
        query["type"] = type_
    if q:
        query["description"] = {"$regex": q, "$options": "i"}
    return await db.stok_history.find(query, {"_id": 0}).sort("date", -1).to_list(limit)


@router.get("/history/export")
async def export_history(
    format: str = "csv",
    tag: Optional[str] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 5000,
    user: dict = Depends(require_role("gestor")),
):
    """Exporta histórico em CSV ou PDF respeitando os mesmos filtros do GET /history."""
    fmt = (format or "csv").lower()
    if fmt not in {"csv", "pdf"}:
        raise HTTPException(400, "format deve ser 'csv' ou 'pdf'.")
    docs = await _filter_history(user, tag, type, q, limit)

    ts = now_iso().replace(":", "-").split(".")[0]

    if fmt == "csv":
        buf = io.StringIO()
        # BOM para Excel reconhecer UTF-8 com acentos
        buf.write("\ufeff")
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Data", "Tipo", "Tag", "Usuário", "Descrição"])
        for h in docs:
            writer.writerow([
                _fmt_dt_br(h.get("date")), h.get("type", ""), h.get("tag", ""),
                h.get("user", ""), (h.get("description") or "").replace("\n", " "),
            ])
        data = buf.getvalue().encode("utf-8")
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="estoque_historico_{ts}.csv"'},
        )

    # ---------- PDF ----------
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError as e:
        raise HTTPException(500, f"reportlab indisponível: {e}")

    pdf_buf = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Histórico do Estoque",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleX", parent=styles["Heading1"], fontSize=16, spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"], fontSize=8, textColor=colors.grey,
    )
    body_style = ParagraphStyle(
        "BodyX", parent=styles["Normal"], fontSize=8, leading=10,
    )

    elements: List[Any] = []
    elements.append(Paragraph("Histórico do Estoque · Fibra Óptica", title_style))
    filters_txt = " · ".join(filter(None, [
        f"tipo: {type}" if type else None,
        f"tag: {tag}" if tag else None,
        f"busca: {q}" if q else None,
        f"registros: {len(docs)}",
        f"gerado em {_fmt_dt_br(now_iso())}",
    ]))
    elements.append(Paragraph(filters_txt, meta_style))
    elements.append(Spacer(1, 6))

    headers = ["Data", "Tipo", "Tag", "Usuário", "Descrição"]
    rows: List[List[Any]] = [headers]
    for h in docs:
        rows.append([
            Paragraph(_fmt_dt_br(h.get("date")), body_style),
            Paragraph(str(h.get("type", "")), body_style),
            Paragraph(str(h.get("tag", "")), body_style),
            Paragraph(str(h.get("user", "")), body_style),
            Paragraph(str(h.get("description", "")), body_style),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Sem registros para os filtros selecionados.", body_style), "", "", "", ""])

    page_w = landscape(A4)[0] - 24 * mm  # margens
    col_widths = [page_w * w for w in (0.13, 0.13, 0.13, 0.16, 0.45)]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    pdf_buf.seek(0)
    return StreamingResponse(
        iter([pdf_buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="estoque_historico_{ts}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Bridge Lousa ↔ Estoque (parte b da integração)
# ---------------------------------------------------------------------------
async def auto_open_service_for_ticket(ticket: dict) -> Optional[str]:
    """Chamado pelo lousa.py quando uma bolha é ABERTA pelo técnico.

    Cria uma OS de estoque (`stok_services`) automaticamente se ainda não
    houver uma vinculada. Retorna o ID da OS ou None.

    Mapeamento ticket.type → service.type:
      instalacao → instalacao | retirada → retirada |
      troca_endereco → troca | outros → reparo
    """
    if not ticket.get("id") or not ticket.get("assigned_collaborator_id"):
        return None
    company_id = ticket.get("company_id") or DEMO_COMPANY_ID

    existing = await db.stok_services.find_one(
        {"ticket_id": ticket["id"], "company_id": company_id, "status": "ativo"}, {"_id": 0, "id": 1},
    )
    if existing:
        return existing["id"]

    type_map = {
        "instalacao": "instalacao", "retirada": "retirada",
        "troca_endereco": "troca", "troca_titularidade": "troca",
    }
    svc_type = type_map.get(ticket.get("type"), "reparo")
    snap = ticket.get("client_snapshot") or {}
    sid = f"OS-{uuid.uuid4().hex[:6].upper()}"
    await db.stok_services.insert_one({
        "id": sid, "company_id": company_id, "type": svc_type,
        "client_id": ticket.get("client_id") or ticket["id"],
        "client_name": snap.get("name", "Cliente"),
        "technician_id": ticket["assigned_collaborator_id"],
        "status": "ativo", "reason": None,
        "ticket_id": ticket["id"], "created_at": now_iso(),
        "auto_opened": True,
    })
    return sid


async def mark_service_ticket_finalized(ticket_id: str, company_id: str) -> None:
    """Lousa avisou que o ticket foi FINALIZADO pelo técnico.

    A OS associada continua `ativo` (gestor precisa informar MAC + insumos
    via aba Estoque), mas marca `ticket_finalized=true` para destaque na UI.
    """
    await db.stok_services.update_one(
        {"ticket_id": ticket_id, "company_id": company_id, "status": "ativo"},
        {"$set": {"ticket_finalized": True, "ticket_finalized_at": now_iso()}},
    )


async def cancel_service_for_ticket(ticket_id: str, company_id: str, reason: str = "") -> None:
    """Lousa cancelou/reagendou o ticket — cancela a OS sem baixa de estoque."""
    await db.stok_services.update_one(
        {"ticket_id": ticket_id, "company_id": company_id, "status": "ativo"},
        {"$set": {"status": "cancelado", "closed_at": now_iso(),
                  "cancel_reason": reason or "Cancelado via Lousa"}},
    )


# Mapping completion_data fields → consumable IDs (Lousa → Estoque)
_COMPLETION_FIELD_TO_CONSUMABLE = {
    "qtd_drop": "drop",
    "esticadores": "esticador",
    "conectores_fast": "conector_fast",
    "cabo_rede": "cabo_rede",
    "conectores_rede": "conector_rede",
    # Backbone / lançamento de rede
    "fibra_06fo": "fibra_06fo",
    "fibra_12fo": "fibra_12fo",
    "fibra_24fo": "fibra_24fo",
    # `conector_fibra` não tem campo na Lousa hoje; gestor adiciona manualmente se precisar
}


async def auto_close_service_from_ticket(
    ticket_id: str, company_id: str, completion_data: dict,
    technician_id: str, technician_name: str,
    *, caller: Optional[str] = None,
) -> dict:
    """Quando técnico finaliza bolha, auto-fecha a OS associada e baixa estoque.

    Mapeia `completion_data` (Lousa) para `used_items` (Estoque).
    Tratamento de erro: se saldo insuficiente OU MAC inválido, marca OS como
    `status="erro_estoque"` com notas pro gestor, mas **não derruba o finalize
    da Lousa** (best-effort).
    Retorna `{ok, service_id?, reason?, used_items?}` para logging.

    Onda 0b (CTO 16/02/2026) — LEGADO em sunset observado.
    Flag env `AUTO_CLOSE_LEGACY_DEPRECATED` ativa log estruturado em
    `auto_close_legacy_observability` para mapear callers em produção.
    Nada é desligado nesta fase. Após 7 dias com tráfego zero → remoção.
    """
    if not ticket_id or not company_id:
        return {"ok": False, "reason": "missing_ids"}

    # ─── Onda 0b — Observabilidade obrigatória do legado ──────────────────
    try:
        import os as _os
        if _os.environ.get("AUTO_CLOSE_LEGACY_DEPRECATED", "true").lower() in (
                "1", "true", "yes", "on"):
            logger.warning(
                "[stok][LEGACY][auto_close_service_from_ticket] caller=%s "
                "ticket=%s company=%s tech=%s/%s cd_keys=%s",
                caller or "unknown", ticket_id, company_id,
                technician_id, technician_name,
                sorted(list((completion_data or {}).keys()))[:20],
            )
            await db.auto_close_legacy_observability.insert_one({
                "id": f"acl-{ticket_id}-{int(datetime.now(timezone.utc).timestamp()*1000)}",
                "ticket_id": ticket_id,
                "company_id": company_id,
                "caller": caller or "unknown",
                "technician_id": technician_id,
                "technician_name": technician_name,
                "completion_data_keys": sorted(
                    list((completion_data or {}).keys()))[:50],
                "has_ont": bool((completion_data or {}).get("ont")),
                "has_ont_sn": bool((completion_data or {}).get("ont_sn")),
                "called_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as _obs_err:  # pragma: no cover — observabilidade nunca quebra
        logger.warning("[stok] auto_close legacy observability falhou: %s",
                       _obs_err)
    # ──────────────────────────────────────────────────────────────────────

    service = await db.stok_services.find_one(
        {"ticket_id": ticket_id, "company_id": company_id, "status": "ativo"},
        {"_id": 0},
    )
    if not service:
        return {"ok": False, "reason": "no_active_service_for_ticket"}
    sid = service["id"]

    # Monta used_items a partir do completion_data
    used_items: List[UsedItem] = []
    for field, cons_id in _COMPLETION_FIELD_TO_CONSUMABLE.items():
        try:
            qty = int(round(float(completion_data.get(field) or 0)))
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            used_items.append(UsedItem(consumable_id=cons_id, quantity=qty))

    ont_mac = (completion_data.get("ont") or "").strip() or None
    # iter174 — também aceita SN como alternativa ao MAC
    ont_sn = (completion_data.get("ont_sn") or "").strip().upper() or None
    # iter153 — flag de defeito propagada do completion_data para o service
    service["is_defective"] = bool(completion_data.get("is_defective"))
    service["defective_reason"] = (completion_data.get("defective_reason") or "") or None
    # iter174 — propaga SN no service para que _move_ont_for_withdraw use
    if ont_sn and not service.get("ont_sn"):
        service["ont_sn"] = ont_sn

    err_reason: Optional[str] = None
    parts: List[str] = []
    smartolt_validation: Optional[dict] = None

    # SmartOLT: cross-check do MAC/SN contra cache (rastreabilidade)
    cross_check_value = ont_mac or ont_sn
    if cross_check_value:
        try:
            sm_doc = await db.smartolt_onus.find_one(
                {"company_id": company_id,
                 "$or": [{"unique_external_id": cross_check_value},
                            {"sn": cross_check_value}]},
                {"_id": 0, "unique_external_id": 1, "sn": 1, "name": 1,
                 "olt_name": 1, "status": 1, "signal_1490": 1},
            )
            if sm_doc:
                smartolt_validation = sm_doc
        except Exception as e:
            logger.warning("[stok] smartolt cross-check falhou: %s", e)

    # Validações em try-block: qualquer erro vira "erro_estoque" sem derrubar
    shortages: List[Dict[str, Any]] = []
    # CTO 2026-02 — Gate anti-dupla-movimentação. Se a OS já passou pelo
    # `os_inventory_guardrail`, o ONT já foi movido. Aqui só processamos
    # consumíveis (cabos/conectores), evitando dupla baixa.
    skip_ont_movement = False
    try:
        tk = await db.tickets.find_one(
            {"id": ticket_id, "company_id": company_id},
            {"_id": 0, "os_inventory_guardrail": 1})
        if tk and tk.get("os_inventory_guardrail", {}).get("movements"):
            skip_ont_movement = True
            parts.append(
                "ONT já movimentada pelo guardrail global — pulo aqui.")
    except Exception as e:  # pragma: no cover
        logger.warning("[stok] gate guardrail lookup falhou: %s", e)
    try:
        _validate_used_items(used_items)
        shortages = await _check_tech_has_stock(
            company_id, technician_id, technician_name, used_items)
        if service["type"] in ("instalacao", "troca") and not skip_ont_movement:
            # iter197 — SN prevalente: Instalação/Troca aceita SN OU MAC.
            # Quando só SN é informado, `_move_ont_for_install` busca por SN
            # e herda o MAC da ONT existente no estoque do técnico.
            if not ont_mac and not ont_sn:
                raise HTTPException(400, "Para instalação/troca, informe o SN (preferido) ou o MAC da ONT.")
            # garante que ticket_id e ont_sn propagam p/ histórico e lookup
            service["ticket_id"] = service.get("ticket_id") or ticket_id
            if ont_sn and not service.get("ont_sn"):
                service["ont_sn"] = ont_sn
            parts.append(await _move_ont_for_install(
                company_id, service, ont_mac,
                installer_name=technician_name,
                installer_email=completion_data.get("closed_by_email")))
        elif service["type"] == "retirada" and not skip_ont_movement:
            # iter174 — Retirada aceita MAC OU SN (qualquer um dos dois valida)
            if not ont_mac and not ont_sn:
                raise HTTPException(400, "Para retirada, informe o MAC OU o SN da ONT retirada.")
            service["ticket_id"] = service.get("ticket_id") or ticket_id
            parts.append(await _move_ont_for_withdraw(
                company_id, service, technician_name, ont_mac,
                withdrawer_email=completion_data.get("closed_by_email")))
        stock_desc = await _decrement_tech_stock(company_id, technician_id, used_items)
        if stock_desc:
            parts.append(stock_desc)
        # iter168 — Notifica gestor se saldo do técnico ficou negativo
        if shortages:
            await _notify_negative_stock(
                company_id, shortages, service_id=sid, ticket_id=ticket_id)
            parts.append("⚠️ QUEBRA: " + ", ".join(
                f"{s['name']} -{s['deficit']} {s['unit']}" for s in shortages))
    except HTTPException as e:
        err_reason = e.detail if isinstance(e.detail, str) else str(e.detail)
    except Exception as e:
        err_reason = f"erro inesperado: {e}"

    if err_reason:
        await db.stok_services.update_one(
            {"id": sid, "company_id": company_id},
            {"$set": {
                "status": "erro_estoque",
                "ticket_finalized": True,
                "ticket_finalized_at": now_iso(),
                "error_reason": err_reason,
                "auto_close_attempted_at": now_iso(),
            }},
        )
        await _add_history(
            "erro_baixa",
            f"{sid} — Auto-baixa FALHOU: {err_reason}. Técnico {technician_name}. Gestor precisa fechar manualmente.",
            technician_name, "auto_finalize_lousa", company_id,
        )
        # Notifica gestores
        try:
            await db.notifications.insert_one({
                "id": f"notif-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "type": "stok_auto_close_failed",
                "title": f"⚠️ OS {sid} sem baixa automática",
                "message": f"{technician_name} finalizou a bolha mas estoque não foi baixado: {err_reason}. Resolva manualmente em Estoque → Serviços.",
                "severity": "warning",
                "created_at": now_iso(),
                "read_by": [],
                "audience_role": "gestor",
                "ticket_id": ticket_id,
            })
        except Exception:
            pass
        return {"ok": False, "service_id": sid, "reason": err_reason,
                "needs_manual_close": True}

    # Sucesso: fecha OS
    await db.stok_services.update_one(
        {"id": sid, "company_id": company_id},
        {"$set": {
            "status": "fechado",
            "closed_at": now_iso(),
            "ticket_finalized": True,
            "ticket_finalized_at": now_iso(),
            "auto_closed": True,
            "auto_closed_used_items": [ui.model_dump() for ui in used_items],
            "auto_closed_ont_mac": ont_mac,
            "smartolt_validation": smartolt_validation,
        }},
    )
    htype = "retirada" if service["type"] == "retirada" else "instalacao"
    sm_suffix = ""
    if smartolt_validation:
        sm_suffix = (f" [SmartOLT: {smartolt_validation.get('name')} · "
                     f"{smartolt_validation.get('olt_name')} · "
                     f"{smartolt_validation.get('status')}]")
    await _add_history(
        htype,
        f"{sid} (auto-baixa Lousa) - {' | '.join(parts) if parts else 'Sem materiais'} - Técnico {technician_name}{sm_suffix}",
        technician_name, "auto_finalize_lousa", company_id,
    )
    return {"ok": True, "service_id": sid,
            "used_items": [ui.model_dump() for ui in used_items],
            "ont_mac": ont_mac}



# ---------------------------------------------------------------------------
# Aba "Clientes" — pega ONUs ativas do SmartOLT com cliente + SN + fabricante (IA)
# ---------------------------------------------------------------------------
@router.get("/clientes")
async def stok_clientes(only_authorized: bool = True, limit: int = 5000,
                        identify_manufacturer_max: int = 0,
                        user: dict = Depends(require_role("gestor"))):
    """Lista todas as ONUs em uso pelos clientes (cache do SmartOLT).

    Para cada ONU retorna: cliente, número de série, MAC, fabricante (detectado
    via prefixo IEEE/CCM, com fallback Gemini Flash). O `identify_manufacturer_max`
    limita quantas detecções por LLM são feitas por chamada (cache permanente
    em `manufacturer_cache` cobre repetições).

    IMPORTANTE: por padrão (`identify_manufacturer_max=0`) NÃO faz chamada LLM
    nova — usa só KNOWN_PREFIXES + cache em DB. Garante resposta rápida (<2s).
    Para identificar prefixos novos via IA, use o endpoint
    POST /stok/clientes/identify-all (botão "Identificar todos").

    iter163 — enriquece cada cliente com:
      - `installed_by` (nome do técnico que instalou)
      - `installed_at` (data da instalação)
      - `withdrawn_by` / `withdrawn_at` (última retirada, se houver)
      - `cto_id` / `cto_name` / `cto_port_number` (porta atual)
      - `port_changes` (qtde de mudanças de porta no histórico)
    """
    import asyncio as _asyncio
    from manufacturers import identify_manufacturer
    cid = user.get("company_id") or DEMO_COMPANY_ID

    q = {"company_id": cid}
    if only_authorized:
        q["authorization_date"] = {"$nin": [None, "", "0000-00-00"]}
    cur = db.smartolt_onus.find(q, {"_id": 0}).limit(min(max(limit, 1), 10000))

    items: list[dict] = []
    sn_list: list[str] = []
    client_names: list[str] = []
    async for o in cur:
        sn = (o.get("sn") or "").strip().upper()
        mac = (o.get("mac") or o.get("ont_mac") or "").strip()
        client_name = o.get("name") or "(cliente sem nome)"
        items.append({
            "client_name": client_name,
            "sn": sn or None,
            "mac": mac or None,
            "model": o.get("onu_type_name") or None,
            "manufacturer": None,
            "olt_name": o.get("olt_name"),
            "board": o.get("board"),
            "port": o.get("port"),
            "signal_text": o.get("signal_text") or o.get("signal_1490"),
            "authorization_date": o.get("authorization_date"),
            "smartolt_external_id": o.get("unique_external_id"),
            "status": o.get("status") or "online",
            # iter163 — campos enriquecidos preenchidos abaixo
            "installed_by": None,
            "installed_at": None,
            "withdrawn_by": None,
            "withdrawn_at": None,
            "cto_id": None,
            "cto_name": None,
            "cto_port_number": None,
            "port_changes": 0,
            "client_id": None,
        })
        if sn:
            sn_list.append(sn)
        if client_name and client_name != "(cliente sem nome)":
            client_names.append(client_name)

    # Otimização: identifica por PREFIXO único (não por SN) — cache cobre
    # tudo de graça. Limit aplica apenas a chamadas LLM novas.
    # Timeout duro de 8s para não travar a UI mesmo se Gemini estiver lento.
    detected: dict = {}
    try:
        detected = await _asyncio.wait_for(
            _detect_by_prefix(
                sn_list, identify_manufacturer,
                llm_max=identify_manufacturer_max),
            timeout=8.0,
        )
    except _asyncio.TimeoutError:
        logger.warning("[clientes] _detect_by_prefix timeout 8s — retornando "
                          "sem identificação LLM (usa botão 'Identificar todos' "
                          "para forçar)")
    except Exception as e:
        logger.warning("[clientes] _detect_by_prefix erro: %s", e)

    # Aplica nos itens
    for it in items:
        if it.get("sn") and it["sn"] in detected:
            it["manufacturer"] = detected[it["sn"]]

    # ------------------------------------------------------------------
    # iter163 — Enriquecimento de instalador/retirada/porta CTO
    # ------------------------------------------------------------------
    # 1) stok_onts: instalado/retirado por (match por client_name)
    onts_by_name: dict = {}
    if client_names:
        try:
            async for ont in db.stok_onts.find(
                {"company_id": cid,
                 "client_name": {"$in": client_names}},
                {"_id": 0, "client_name": 1, "installed_by_name": 1,
                 "installed_by_email": 1, "installed_at": 1,
                 "installed_via_ticket": 1, "withdrawn_by_name": 1,
                 "withdrawn_by_email": 1, "withdrawn_at": 1,
                 "location_id": 1, "status": 1, "mac": 1},
            ):
                onts_by_name.setdefault(ont["client_name"], []).append(ont)
        except Exception as e:
            logger.warning("[clientes] stok_onts enrich falhou: %s", e)

    # 2) CTOs: porta atual (match por client_name dentro de ports[])
    cto_by_name: dict = {}
    if client_names:
        try:
            async for cto in db.ctos.find(
                {"company_id": cid,
                 "ports.client_name": {"$in": client_names}},
                {"_id": 0, "id": 1, "name": 1, "ports": 1},
            ):
                for p in (cto.get("ports") or []):
                    cn = p.get("client_name")
                    if cn and cn in client_names and p.get("status") == "used":
                        cto_by_name[cn] = {
                            "cto_id": cto["id"],
                            "cto_name": cto.get("name"),
                            "cto_port_number": p.get("number"),
                            "client_subscriber_id": p.get("client_subscriber_id"),
                        }
        except Exception as e:
            logger.warning("[clientes] ctos enrich falhou: %s", e)

    # 3) Contagem de mudanças de porta (port_swap) por client_id
    port_swaps_by_client: dict = {}
    client_ids_from_ctos = [v.get("client_subscriber_id") for v in cto_by_name.values()
                              if v.get("client_subscriber_id")]
    if client_ids_from_ctos:
        try:
            pipeline = [
                {"$match": {"company_id": cid,
                              "client_id": {"$in": client_ids_from_ctos},
                              "action": "port_swap"}},
                {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
            ]
            async for r in db.client_equipment_history.aggregate(pipeline):
                port_swaps_by_client[r["_id"]] = r["n"]
        except Exception as e:
            logger.warning("[clientes] port_swaps enrich falhou: %s", e)

    # Aplica enriquecimentos
    for it in items:
        cn = it["client_name"]
        # Pega o ONT mais recente do cliente (status instalada > retirada)
        onts = onts_by_name.get(cn) or []
        installed = next((o for o in onts if o.get("status") == "instalada"), None)
        if installed:
            it["installed_by"] = installed.get("installed_by_name") \
                or installed.get("installed_by_email")
            it["installed_at"] = installed.get("installed_at")
        # Última retirada (com `withdrawn_at`)
        withdrawn = sorted(
            [o for o in onts if o.get("withdrawn_at")],
            key=lambda x: x.get("withdrawn_at") or "", reverse=True)
        if withdrawn:
            it["withdrawn_by"] = withdrawn[0].get("withdrawn_by_name") \
                or withdrawn[0].get("withdrawn_by_email")
            it["withdrawn_at"] = withdrawn[0].get("withdrawn_at")
        # Porta CTO
        cto = cto_by_name.get(cn)
        if cto:
            it["cto_id"] = cto["cto_id"]
            it["cto_name"] = cto["cto_name"]
            it["cto_port_number"] = cto["cto_port_number"]
            it["client_id"] = cto.get("client_subscriber_id")
            if cto.get("client_subscriber_id"):
                it["port_changes"] = port_swaps_by_client.get(
                    cto["client_subscriber_id"], 0)

    # Estatísticas
    by_manufacturer: dict = {}
    for it in items:
        m = it.get("manufacturer") or "Desconhecido"
        by_manufacturer[m] = by_manufacturer.get(m, 0) + 1

    return {
        "total": len(items),
        "items": items,
        "by_manufacturer": dict(sorted(by_manufacturer.items(),
                                       key=lambda x: -x[1])),
        "identified": sum(1 for i in items if i.get("manufacturer")),
    }


# ---------------------------------------------------------------------------
# iter163 — Histórico de Equipamento por Cliente
# ---------------------------------------------------------------------------
@router.get("/clientes/{client_id}/history")
async def stok_cliente_history(client_id: str, limit: int = 100,
                                  user: dict = Depends(require_role("gestor"))):
    """Linha do tempo de eventos do equipamento de um cliente:
    instalações, retiradas, vínculos de porta CTO, trocas e liberações.

    `client_id` é o ID do assinante (subscriber). Quando o cliente é
    consultado a partir da aba SmartOLT, o frontend pode usar o
    `client_id` resolvido via porta da CTO.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not client_id:
        raise HTTPException(400, "client_id é obrigatório")
    events = await ceh.list_events(cid, client_id, limit=limit)
    summary = await ceh.get_current_summary(cid, [client_id])
    return {
        "client_id": client_id,
        "total": len(events),
        "events": events,
        "summary": summary.get(client_id, {}),
    }


# ---------------------------------------------------------------------------
# iter163 — Histórico por nome de cliente (quando subscriber_id não conhecido)
# ---------------------------------------------------------------------------
@router.get("/clientes/by-name/{client_name}/history")
async def stok_cliente_history_by_name(
    client_name: str, limit: int = 100,
    user: dict = Depends(require_role("gestor")),
):
    """Linha do tempo via nome do cliente — útil quando a aba SmartOLT só
    tem o nome (sem subscriber_id resolvido).

    Estratégia:
      1. Tenta resolver subscriber_id via porta da CTO atual.
      2. Caso não tenha porta, faz join via ticket history (tickets do
         cliente que viraram OS) — pega o último `client_id` conhecido.
      3. Se não achar nada, devolve eventos vazios.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not client_name or not client_name.strip():
        raise HTTPException(400, "client_name é obrigatório")
    cn = client_name.strip()

    # 1) Tenta achar client_id via CTO
    cto = await db.ctos.find_one(
        {"company_id": cid, "ports.client_name": cn},
        {"_id": 0, "ports": 1})
    client_id: Optional[str] = None
    if cto:
        for p in (cto.get("ports") or []):
            if p.get("client_name") == cn and p.get("client_subscriber_id"):
                client_id = p["client_subscriber_id"]
                break

    # 2) Fallback: subscribers por nome (best-effort)
    if not client_id:
        sub = await db.subscribers.find_one(
            {"company_id": cid, "name": cn},
            {"_id": 0, "id": 1}) or await db.subscribers.find_one(
            {"company_id": cid,
             "name": {"$regex": f"^{cn[:25]}", "$options": "i"}},
            {"_id": 0, "id": 1})
        if sub:
            client_id = sub.get("id")

    if not client_id:
        return {
            "client_id": None,
            "client_name": cn,
            "total": 0,
            "events": [],
            "summary": {},
            "reason": "client_id não pôde ser resolvido a partir do nome",
        }
    events = await ceh.list_events(cid, client_id, limit=limit)
    summary = await ceh.get_current_summary(cid, [client_id])
    return {
        "client_id": client_id,
        "client_name": cn,
        "total": len(events),
        "events": events,
        "summary": summary.get(client_id, {}),
    }


# ---------------------------------------------------------------------------
# iter170 — Retirada MANUAL (sem OS) — direto na aba SmartOLT
# ---------------------------------------------------------------------------
class ManualWithdrawIn(BaseModel):
    technician_id: str
    client_name: Optional[str] = None
    client_id: Optional[str] = None
    ont_mac: Optional[str] = None
    ont_sn: Optional[str] = None
    notes: Optional[str] = None
    is_defective: bool = False
    defective_reason: Optional[str] = None


@router.post("/clientes/manual-withdraw")
async def manual_withdraw(payload: ManualWithdrawIn,
                            user: dict = Depends(require_role("gestor"))):
    """Registra a retirada de um equipamento direto da aba SmartOLT, SEM
    OS aberta. Útil para regularizar casos em que o equipamento foi
    fisicamente retirado mas não houve fluxo formal.

    Efeitos:
      - Cria/atualiza `stok_onts` com `location_type=tecnico`,
        `location_id=technician_id`, `status=retirada_com_tecnico`
        (ou `defeito_devolver_empresa` se `is_defective=true`).
      - Libera a porta da CTO se houver vínculo.
      - Loga evento `withdraw` em `client_equipment_history` com o
        nome do GESTOR como `actor_name` + notes "RETIRADA MANUAL".
      - Cria notification de auditoria.

    Requer:
      - `technician_id` (obrigatório)
      - `client_name` OU `client_id` (pelo menos um)
      - `ont_mac` OU `ont_sn` (pelo menos um — para identificar o equipamento)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    gestor_name = (user.get("name") or user.get("email") or "Gestor").strip()
    gestor_email = (user.get("email") or "").strip() or None

    # ─── Onda 2.4 — reason obrigatório ANTES de qualquer side effect ──────
    from services.transfer_engine import execute_transfer, TransferEngineError
    if not payload.reason or not (payload.reason.get("code") or "").strip():
        raise HTTPException(400, {
            "error": "transfer_reason_required",
            "message": "manual-withdraw exige payload.reason ({code,details?}).",
        })

    if not payload.technician_id:
        raise HTTPException(400, "technician_id é obrigatório")
    if not (payload.client_name or payload.client_id):
        raise HTTPException(400, "Informe client_name ou client_id")
    if not (payload.ont_mac or payload.ont_sn):
        raise HTTPException(400, "Informe ont_mac ou ont_sn")

    # Resolve técnico
    tech = await db.collaborators.find_one(
        {"id": payload.technician_id}, {"_id": 0, "name": 1, "id": 1})
    if not tech:
        raise HTTPException(404, "Técnico não encontrado")
    tech_name = tech.get("name") or payload.technician_id

    # Resolve client_id se só veio o nome (best-effort via porta CTO ou subscribers)
    client_id = payload.client_id
    client_name = payload.client_name
    if not client_id and client_name:
        cto = await db.ctos.find_one(
            {"company_id": cid, "ports.client_name": client_name},
            {"_id": 0, "ports": 1})
        if cto:
            for p in (cto.get("ports") or []):
                if p.get("client_name") == client_name and p.get("client_subscriber_id"):
                    client_id = p["client_subscriber_id"]
                    break
        if not client_id:
            sub = await db.subscribers.find_one(
                {"company_id": cid, "name": client_name},
                {"_id": 0, "id": 1})
            if sub:
                client_id = sub.get("id")

    # Normaliza MAC
    mac_n = normalize_mac(payload.ont_mac) if payload.ont_mac else None
    sn_clean = (payload.ont_sn or "").strip().upper() or None

    # Status final
    is_defective = bool(payload.is_defective)
    defective_reason = (payload.defective_reason or "").strip()[:300] or None
    ont_status = "defeito_devolver_empresa" if is_defective else "retirada_com_tecnico"

    # Procura ONT existente por MAC (preferencial) ou SN
    ont = None
    if mac_n:
        ont = await db.stok_onts.find_one(
            {"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont and sn_clean:
        ont = await db.stok_onts.find_one(
            {"company_id": cid, "scan_sn": sn_clean}, {"_id": 0})

    notes_full = (
        f"RETIRADA MANUAL pelo gestor {gestor_name} · "
        f"{(payload.notes or '').strip()}"
    ).strip(" ·")

    extra_fields: Dict[str, Any] = {}
    if is_defective:
        extra_fields["is_defective"] = True
        extra_fields["defective_marked_at"] = now_iso()
        extra_fields["defective_marked_by"] = gestor_email
        if defective_reason:
            extra_fields["defective_reason"] = defective_reason

    if ont:
        # ─── Onda 2.4 — Grava trilha canônica ANTES do update ─────────────
        # Transição: cliente → tecnico (manual, sem OS).
        transfer_audit_id = None
        transfer_audit_hash = None
        try:
            tr = await execute_transfer(
                company_id=cid,
                origin_type="cliente", origin_id=client_id,
                destination_type="tecnico", destination_id=payload.technician_id,
                actor={"id": user.get("id"), "email": gestor_email,
                        "name": gestor_name, "role": user.get("role"),
                        "origin": "gestor_ui_manual_withdraw",
                        "client_name": client_name},
                reason=payload.reason,
                mac=ont["mac"],
                extra_set_fields={
                    "source": "retirada_manual",
                    "withdrawn_from_client_id": client_id,
                    "withdrawn_from_client_name": client_name,
                    "withdrawn_by_email": gestor_email,
                    "withdrawn_by_name": tech_name,
                    "withdrawn_manual_by": gestor_name,
                    "withdrawn_at": now_iso(),
                    "withdraw_notes": notes_full,
                    "status": ont_status,
                    **extra_fields,
                },
            )
            transfer_audit_id = tr["movement_id"]
            transfer_audit_hash = tr["audit_hash"]
        except TransferEngineError as e:
            raise HTTPException(400, {
                "error": "transfer_blocked", "message": str(e)})
        ont_id_msg = ont["mac"]
    else:
        # Cria ONT do zero — útil quando o equipamento não estava no estoque
        new_mac = mac_n or f"MANUAL-{uuid.uuid4().hex[:10].upper()}"
        await db.stok_onts.insert_one({
            "id": f"ont-{uuid.uuid4().hex[:12]}",
            "company_id": cid,
            "mac": new_mac,
            "scan_sn": sn_clean,
            "location_type": "tecnico",
            "location_id": payload.technician_id,
            "client_name": None,
            "status": ont_status,
            "source": "retirada_manual",
            "withdrawn_from_client_id": client_id,
            "withdrawn_from_client_name": client_name,
            "withdrawn_by_email": gestor_email,
            "withdrawn_by_name": tech_name,
            "withdrawn_manual_by": gestor_name,
            "withdrawn_at": now_iso(),
            "withdraw_notes": notes_full,
            "created_at": now_iso(),
            **extra_fields,
        })
        ont_id_msg = new_mac

    # Libera porta CTO vinculada
    port_msg = None
    if client_id:
        current = await _find_client_cto_port(cid, client_id)
        if current:
            await _free_cto_port(
                cid, current["cto_id"], current["port_number"], gestor_email,
                "retirada_manual", client_id=client_id, client_name=client_name,
                actor_name=gestor_name)
            port_msg = (f"Porta {current['port_number']} de {current['cto_name']} "
                          f"liberada")

    # Histórico
    if client_id:
        await ceh.log_event(
            company_id=cid, client_id=client_id, client_name=client_name,
            action="withdraw", ont_mac=mac_n, ont_sn=sn_clean,
            actor_name=gestor_name, actor_email=gestor_email,
            notes=notes_full
                  + (f" · {defective_reason}" if defective_reason else ""),
        )

    # Notificação
    try:
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "type": "manual_withdraw",
            "title": "📦 Retirada manual registrada",
            "message": (
                f"{gestor_name} registrou retirada manual do equipamento "
                f"{ont_id_msg} de '{client_name or client_id}' para o estoque "
                f"do técnico {tech_name}"
                + (" (DEFEITUOSO)" if is_defective else "") + "."
            ),
            "severity": "info",
            "created_at": now_iso(),
            "read_by": [],
            "audience_role": "gestor",
        })
    except Exception as e:
        logger.warning("[manual-withdraw] notification falhou: %s", e)

    return {
        "ok": True,
        "ont_id": ont_id_msg,
        "technician_id": payload.technician_id,
        "technician_name": tech_name,
        "client_id": client_id,
        "client_name": client_name,
        "status": ont_status,
        "performed_by": gestor_name,
        "port_msg": port_msg,
    }


# ---------------------------------------------------------------------------
# iter164 — Alertas de ONT Duplicada
# ---------------------------------------------------------------------------
class ResolveDuplicateAlertIn(BaseModel):
    resolution: str  # ok_legitimo | retirada_nao_registrada | clonagem | erro_cadastro | outro
    notes: Optional[str] = None


@router.get("/ont-duplicate-alerts")
async def list_ont_duplicate_alerts(status: str = "open", limit: int = 100,
                                       user: dict = Depends(require_role("gestor"))):
    """Lista alertas de ONT duplicada (mesmo MAC/SN em clientes diferentes).

    `status`: `open` (default), `resolved`, ou `all`.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await ont_dup.list_alerts(cid, status=status, limit=limit)
    return {
        "items": items,
        "total": len(items),
        "open_count": sum(1 for i in items if i.get("status") == "open"),
        "critical_count": sum(1 for i in items
                                if i.get("status") == "open"
                                and i.get("severity") == "critical"),
    }


@router.post("/ont-duplicate-alerts/{alert_id}/resolve")
async def resolve_ont_duplicate_alert(alert_id: str,
                                          payload: ResolveDuplicateAlertIn,
                                          user: dict = Depends(require_role("gestor"))):
    """Gestor marca o alerta como resolvido com o motivo (auditoria).

    `resolution` ∈ {ok_legitimo, retirada_nao_registrada, clonagem,
    erro_cadastro, outro}.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    valid = {"ok_legitimo", "retirada_nao_registrada", "clonagem",
             "erro_cadastro", "outro"}
    if payload.resolution not in valid:
        raise HTTPException(400,
            f"resolution inválido. Use: {', '.join(sorted(valid))}")
    ok = await ont_dup.resolve_alert(
        cid, alert_id, payload.resolution,
        notes=payload.notes,
        resolved_by=(user.get("email") or "").strip() or None,
    )
    if not ok:
        raise HTTPException(404, "Alerta não encontrado ou já resolvido")
    return {"ok": True, "alert_id": alert_id, "resolution": payload.resolution}


# ---------------------------------------------------------------------------
# iter168 — Reprocessar OSs em `erro_estoque` (permitindo saldo negativo)
# ---------------------------------------------------------------------------
@router.post("/services/reprocess-erro-estoque")
async def reprocess_erro_estoque(
    limit: int = 100,
    user: dict = Depends(require_role("gestor")),
):
    """Reaplica `auto_close_service_from_ticket` em OSs que ficaram travadas
    em `erro_estoque` por falta de saldo. Agora que o sistema aceita saldo
    negativo (iter168), essas OSs podem ser finalizadas e o consumo
    registrado (saldo do técnico vai para negativo, criando a QUEBRA
    visível).

    Retorna `{processed, succeeded, still_failed, details[]}`.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    services = await db.stok_services.find(
        {"company_id": cid, "status": "erro_estoque"}, {"_id": 0},
    ).limit(min(max(limit, 1), 500)).to_list(min(max(limit, 1), 500))

    succeeded = 0
    failed = 0
    details: List[Dict[str, Any]] = []
    for svc in services:
        sid = svc.get("id")
        tid = svc.get("ticket_id")
        if not tid:
            failed += 1
            details.append({"service_id": sid, "ok": False,
                              "reason": "sem ticket_id"})
            continue
        ticket = await db.tickets.find_one(
            {"id": tid, "company_id": cid}, {"_id": 0})
        if not ticket:
            failed += 1
            details.append({"service_id": sid, "ok": False,
                              "reason": "ticket não encontrado"})
            continue
        cd = ticket.get("completion_data") or {}
        if not cd:
            failed += 1
            details.append({"service_id": sid, "ok": False,
                              "reason": "ticket sem completion_data"})
            continue
        # Reabre temporariamente para auto_close re-processar
        await db.stok_services.update_one(
            {"id": sid, "company_id": cid},
            {"$set": {"status": "ativo"}, "$unset": {"error_reason": ""}},
        )
        tech = await db.collaborators.find_one(
            {"id": svc.get("technician_id")}, {"_id": 0, "name": 1}) or {}
        result = await auto_close_service_from_ticket(
            ticket_id=tid,
            company_id=cid,
            completion_data=cd,
            technician_id=svc.get("technician_id"),
            technician_name=tech.get("name") or "Técnico",
            caller="stok.retry_erro_estoque",
        )
        if result.get("ok"):
            succeeded += 1
            details.append({"service_id": sid, "ok": True,
                              "used_items": result.get("used_items")})
        else:
            failed += 1
            details.append({"service_id": sid, "ok": False,
                              "reason": result.get("reason")})

    return {
        "processed": len(services),
        "succeeded": succeeded,
        "still_failed": failed,
        "details": details[:50],
    }


# ---------------------------------------------------------------------------
# iter165 — Dashboard de Saúde do Estoque
# ---------------------------------------------------------------------------
@router.get("/health-dashboard")
async def stok_health_dashboard(
    user: dict = Depends(require_role("gestor")),
):
    """Consolida em paralelo os principais sinais de saúde operacional do estoque:

      • Defeituosas (pendentes de devolução + em análise)
      • ONTs duplicadas (abertas + críticas)
      • Auditoria SN (mismatches últimos 7d)
      • Retiradas com inconsistência (vínculo prévio divergente)

    Retorna também um `health_score` composto (0-100):
      - 100 = sem alertas
      - Cada categoria penaliza proporcionalmente
    """
    import asyncio as _asyncio
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    since_7d = (now - timedelta(days=7)).isoformat()

    async def _count_defective():
        try:
            pending = await db.stok_onts.count_documents(
                {"company_id": cid, "status": "defeito_devolver_empresa"})
            in_analysis = await db.stok_onts.count_documents(
                {"company_id": cid, "status": "defeito_em_analise"})
            return {"pending_return": pending, "in_analysis": in_analysis,
                    "total": pending + in_analysis}
        except Exception as e:
            logger.warning("[health] defective falhou: %s", e)
            return {"pending_return": 0, "in_analysis": 0, "total": 0}

    async def _count_duplicates():
        try:
            opn = await db.ont_duplicate_alerts.count_documents(
                {"company_id": cid, "status": "open"})
            crit = await db.ont_duplicate_alerts.count_documents(
                {"company_id": cid, "status": "open", "severity": "critical"})
            resolved_7d = await db.ont_duplicate_alerts.count_documents(
                {"company_id": cid, "status": "resolved",
                 "resolved_at": {"$gte": since_7d}})
            return {"open": opn, "critical": crit,
                    "resolved_7d": resolved_7d}
        except Exception as e:
            logger.warning("[health] duplicates falhou: %s", e)
            return {"open": 0, "critical": 0, "resolved_7d": 0}

    async def _sn_audit_7d():
        try:
            total = await db.withdraw_sn_audit.count_documents(
                {"company_id": cid, "created_at": {"$gte": since_7d}})
            mism = await db.withdraw_sn_audit.count_documents(
                {"company_id": cid, "created_at": {"$gte": since_7d},
                 "match_status": {"$ne": "match"}})
            # Top 5 técnicos com mais divergências em 7d
            pipeline = [
                {"$match": {"company_id": cid,
                             "created_at": {"$gte": since_7d},
                             "match_status": {"$ne": "match"}}},
                {"$group": {"_id": "$technician_id", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}, {"$limit": 5},
            ]
            tops_raw = []
            async for r in db.withdraw_sn_audit.aggregate(pipeline):
                tops_raw.append({"technician_id": r["_id"], "count": r["n"]})
            # Resolve nomes
            tids = [t["technician_id"] for t in tops_raw if t.get("technician_id")]
            names: Dict[str, str] = {}
            if tids:
                async for c in db.collaborators.find(
                    {"id": {"$in": tids}}, {"_id": 0, "id": 1, "name": 1},
                ):
                    names[c["id"]] = c.get("name") or c["id"]
            for t in tops_raw:
                t["name"] = names.get(t.get("technician_id")) or t.get("technician_id") or "—"
            return {"total_7d": total, "mismatches_7d": mism,
                    "top_techs": tops_raw,
                    "mismatch_rate_pct": round(100.0 * mism / total, 1) if total else 0.0}
        except Exception as e:
            logger.warning("[health] sn_audit falhou: %s", e)
            return {"total_7d": 0, "mismatches_7d": 0,
                    "top_techs": [], "mismatch_rate_pct": 0.0}

    async def _withdraw_inconsistency():
        try:
            count = await db.stok_onts.count_documents(
                {"company_id": cid, "withdraw_inconsistency": True})
            recent = await db.stok_onts.find(
                {"company_id": cid, "withdraw_inconsistency": True},
                {"_id": 0, "mac": 1, "scan_sn": 1, "withdrawn_at": 1,
                 "withdrawn_from_client_name": 1,
                 "withdraw_inconsistency_note": 1,
                 "withdrawn_by_name": 1},
            ).sort("withdrawn_at", -1).limit(5).to_list(5)
            return {"count": count, "recent": recent}
        except Exception as e:
            logger.warning("[health] withdraw_inconsistency falhou: %s", e)
            return {"count": 0, "recent": []}

    async def _erro_estoque_count():
        try:
            return await db.stok_services.count_documents(
                {"company_id": cid, "status": "erro_estoque"})
        except Exception:
            return 0

    async def _negative_stock_techs():
        """Técnicos com qualquer consumível negativo."""
        try:
            techs = []
            async for s in db.stok_stock.find(
                {"company_id": cid, "location": {"$ne": "empresa"}},
                {"_id": 0},
            ):
                neg = {k: v for k, v in s.items()
                       if isinstance(v, (int, float)) and v < 0}
                if neg:
                    techs.append({
                        "location": s.get("location"),
                        "items": neg,
                    })
            # Resolve nomes
            tids = [t["location"] for t in techs if t.get("location")]
            names: Dict[str, str] = {}
            if tids:
                async for c in db.collaborators.find(
                    {"id": {"$in": tids}}, {"_id": 0, "id": 1, "name": 1},
                ):
                    names[c["id"]] = c.get("name") or c["id"]
            for t in techs:
                t["tech_name"] = names.get(t.get("location")) or t.get("location")
            return {"count": len(techs), "techs": techs[:10]}
        except Exception as e:
            logger.warning("[health] negative_stock falhou: %s", e)
            return {"count": 0, "techs": []}

    # Executa em paralelo
    (defective, duplicates, sn_audit, withdraw_inc,
     erro_estoque_n, negative_stock) = await _asyncio.gather(
        _count_defective(),
        _count_duplicates(),
        _sn_audit_7d(),
        _withdraw_inconsistency(),
        _erro_estoque_count(),
        _negative_stock_techs(),
    )

    # ---- Health Score (0-100) ----
    # Penalidades:
    #   - Defeituosas pendentes: -2 por unidade (cap -20)
    #   - Duplicadas abertas:    -8 por unidade (cap -40)
    #   - Duplicadas críticas:   -5 extra por unidade (cap -15)
    #   - SN mismatch rate > 10%: -1 por % acima (cap -20)
    #   - Withdraw inconsistency: -3 por unidade (cap -15)
    #   - OSs em erro_estoque:   -2 por unidade (cap -20) — iter168
    #   - Técnicos com saldo negativo: -4 por técnico (cap -20) — iter168
    penalty = 0
    penalty += min(defective["pending_return"] * 2, 20)
    penalty += min(duplicates["open"] * 8, 40)
    penalty += min(duplicates["critical"] * 5, 15)
    if sn_audit["mismatch_rate_pct"] > 10:
        penalty += min(int(sn_audit["mismatch_rate_pct"] - 10), 20)
    penalty += min(withdraw_inc["count"] * 3, 15)
    penalty += min(erro_estoque_n * 2, 20)
    penalty += min(negative_stock["count"] * 4, 20)
    score = max(0, 100 - penalty)
    if score >= 85:
        status = "excelente"
    elif score >= 60:
        status = "atencao"
    else:
        status = "critico"

    # ---- Lista acionável (prioridade DESC) ----
    actions: List[Dict[str, Any]] = []
    if erro_estoque_n > 0:
        actions.append({
            "severity": "critical",
            "label": (f"{erro_estoque_n} OS(s) travada(s) em erro_estoque · "
                       "use 'Reprocessar' para baixar com saldo negativo"),
            "deeplink_tab": "servicos",
            "action_id": "reprocess_erro_estoque",
        })
    if negative_stock["count"] > 0:
        actions.append({
            "severity": "warning",
            "label": (f"{negative_stock['count']} técnico(s) com saldo negativo "
                       "(quebra — verificar compras ou uso fora de OS)"),
            "deeplink_tab": "insumos",
        })
    if duplicates["critical"] > 0:
        actions.append({
            "severity": "critical",
            "label": f"{duplicates['critical']} alerta(s) CRÍTICO(s) de ONT duplicada",
            "deeplink_tab": "duplicados",
        })
    if duplicates["open"] - duplicates["critical"] > 0:
        actions.append({
            "severity": "warning",
            "label": f"{duplicates['open'] - duplicates['critical']} alerta(s) de ONT duplicada (warning)",
            "deeplink_tab": "duplicados",
        })
    if defective["pending_return"] > 0:
        actions.append({
            "severity": "warning",
            "label": f"{defective['pending_return']} ONT(s) defeituosa(s) aguardando devolução",
            "deeplink_tab": "defeitos",
        })
    if sn_audit["mismatches_7d"] > 0:
        actions.append({
            "severity": "warning" if sn_audit["mismatch_rate_pct"] < 20 else "critical",
            "label": (f"{sn_audit['mismatches_7d']} divergência(s) de SN nos últimos 7d "
                       f"({sn_audit['mismatch_rate_pct']}% das auditorias)"),
            "deeplink_tab": "audit-sn",
        })
    if withdraw_inc["count"] > 0:
        actions.append({
            "severity": "info",
            "label": f"{withdraw_inc['count']} retirada(s) com vínculo prévio divergente",
            "deeplink_tab": "audit-sn",
        })
    if not actions:
        actions.append({
            "severity": "ok",
            "label": "Tudo em ordem — nenhuma ação pendente",
            "deeplink_tab": None,
        })

    return {
        "score": score,
        "status": status,
        "defective": defective,
        "duplicates": duplicates,
        "sn_audit": sn_audit,
        "withdraw_inconsistency": withdraw_inc,
        "erro_estoque_count": erro_estoque_n,
        "negative_stock": negative_stock,
        "actions": actions,
        "generated_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# iter176 — Estatísticas de qualidade do OCR
# ---------------------------------------------------------------------------
@router.get("/ocr-quality-stats")
async def ocr_quality_stats(
    days: int = 30,
    user: dict = Depends(require_role("gestor")),
):
    """Agrega correções manuais do OCR nos últimos `days` dias:
      - total de leituras corrigidas (mac/sn)
      - top 5 modelos de ONT com mais correções (etiquetas problemáticas)
      - top 5 colaboradores que mais corrigem (potencial bias ou treino)
    Útil para identificar etiquetas ruins e melhorar o prompt da IA.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()

    q = {"company_id": cid, "created_at": {"$gte": since}}
    total = await db.stok_ocr_corrections.count_documents(q)
    changed_mac = await db.stok_ocr_corrections.count_documents({**q, "changed_mac": True})
    changed_sn = await db.stok_ocr_corrections.count_documents({**q, "changed_sn": True})

    # Top modelos com mais correções
    top_models: List[Dict[str, Any]] = []
    pipeline = [
        {"$match": {**q, "ont_model": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$ont_model", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 5},
    ]
    async for r in db.stok_ocr_corrections.aggregate(pipeline):
        top_models.append({"model": r["_id"], "corrections": r["n"]})

    # Top colaboradores
    top_collabs_raw: List[Dict[str, Any]] = []
    pipeline2 = [
        {"$match": {**q, "collaborator_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$collaborator_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 5},
    ]
    async for r in db.stok_ocr_corrections.aggregate(pipeline2):
        top_collabs_raw.append({"id": r["_id"], "corrections": r["n"]})
    coll_ids = [c["id"] for c in top_collabs_raw]
    names: Dict[str, str] = {}
    if coll_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": coll_ids}}, {"_id": 0, "id": 1, "name": 1}):
            names[c["id"]] = c.get("name") or c["id"]
    top_collabs = [{"name": names.get(c["id"]) or c["id"],
                       "corrections": c["corrections"]} for c in top_collabs_raw]

    return {
        "days": days,
        "total_corrections": total,
        "changed_mac": changed_mac,
        "changed_sn": changed_sn,
        "top_models": top_models,
        "top_collaborators": top_collabs,
    }


async def _detect_by_prefix(sns: list[str], identify_fn,
                             llm_max: int = 200) -> dict:
    """Identifica fabricantes em escala — agrupa por prefixo (4 chars). Para
    cada prefixo resolve UMA vez (cache + KNOWN_PREFIXES + LLM se necessário),
    aplica a todos os SNs do mesmo prefixo. `llm_max` limita só chamadas LLM
    novas (não afeta cache hits)."""
    from manufacturers import KNOWN_PREFIXES, _ascii_prefix, _hex_prefix

    # 1) Agrupa SNs por prefixo
    prefix_to_sns: dict = {}
    for sn in sns:
        p = _ascii_prefix(sn) or _hex_prefix(sn)
        if not p:
            continue
        prefix_to_sns.setdefault(p, []).append(sn)
    unique_prefixes = list(prefix_to_sns.keys())

    # 2) Resolve cada prefixo único (cache faz isso ser barato)
    prefix_to_manuf: dict = {}
    # 2a) Hardcoded primeiro (zero custo)
    pending: list[str] = []
    for p in unique_prefixes:
        # KNOWN_PREFIXES pode ter ascii (4) ou hex (8) prefix
        if p in KNOWN_PREFIXES:
            prefix_to_manuf[p] = KNOWN_PREFIXES[p]
        else:
            pending.append(p)

    # 2b) Cache em DB (1 query batch para todos os pendentes)
    if pending:
        cached_cur = db.manufacturer_cache.find(
            {"prefix": {"$in": pending}}, {"_id": 0, "prefix": 1, "manufacturer": 1})
        async for c in cached_cur:
            prefix_to_manuf[c["prefix"]] = c.get("manufacturer")

    # 2c) LLM só para os ainda pendentes (limitado por llm_max)
    still_pending = [p for p in pending if p not in prefix_to_manuf]
    if still_pending and llm_max > 0:
        import asyncio
        sem = asyncio.Semaphore(4)
        to_resolve = still_pending[:llm_max]

        async def one(prefix: str):
            sample_sn = prefix_to_sns[prefix][0]
            async with sem:
                try:
                    return prefix, await identify_fn(sample_sn)
                except Exception as e:
                    logger.warning("[clientes] LLM %s falhou: %s", prefix, e)
                    return prefix, None

        results = await asyncio.gather(*[one(p) for p in to_resolve],
                                        return_exceptions=False)
        for prefix, m in results:
            prefix_to_manuf[prefix] = m

    # 3) Mapeia de volta para SNs
    sn_to_manuf: dict = {}
    for prefix, manuf in prefix_to_manuf.items():
        if not manuf:
            continue
        for sn in prefix_to_sns.get(prefix, []):
            sn_to_manuf[sn] = manuf
    return sn_to_manuf


# ---------------------------------------------------------------------------
# Forçar descoberta de fabricantes (LLM em todos os prefixos desconhecidos)
# ---------------------------------------------------------------------------
@router.post("/clientes/identify-all")
async def clientes_identify_all(force: bool = False,
                                use_similarity: bool = True,
                                user: dict = Depends(require_role("gestor"))):
    """Roda a IA em TODOS os prefixos de SN ainda sem fabricante identificado.

    Modo padrão (`use_similarity=True`): chama Gemini em batch de 30 prefixos com
    contexto rico (catálogo de prefixos já conhecidos como exemplos) — muito
    mais eficiente que 1 chamada por prefixo.

    Modo legacy (`use_similarity=False`): 1 chamada LLM por prefixo, sem
    contexto adicional.
    """
    from manufacturers import (KNOWN_PREFIXES, _ascii_prefix, _hex_prefix,
                                  identify_by_similarity_batch,
                                  identify_manufacturer)
    cid = user.get("company_id") or DEMO_COMPANY_ID

    cur = db.smartolt_onus.find({"company_id": cid}, {"_id": 0, "sn": 1})
    prefixes_to_resolve: dict = {}  # prefix -> sample SN
    async for o in cur:
        sn = (o.get("sn") or "").strip().upper()
        if not sn or len(sn) < 4:
            continue
        # Conta como já resolvido se hardcoded
        is_known = False
        for cand in (_ascii_prefix(sn), _hex_prefix(sn)):
            if cand in KNOWN_PREFIXES:
                is_known = True
                break
        if is_known:
            continue
        p = _ascii_prefix(sn) or _hex_prefix(sn)
        if p and p not in prefixes_to_resolve:
            prefixes_to_resolve[p] = sn

    # Filtra os que já estão no cache (a menos que force=true)
    if not force and prefixes_to_resolve:
        cached_cur = db.manufacturer_cache.find(
            {"prefix": {"$in": list(prefixes_to_resolve.keys())}},
            {"_id": 0, "prefix": 1})
        cached = {c["prefix"] async for c in cached_cur}
        for p in cached:
            prefixes_to_resolve.pop(p, None)

    sample_sns = list(prefixes_to_resolve.values())
    new_found = 0

    if use_similarity:
        # Batch LLM com contexto — recomendado
        result = await identify_by_similarity_batch(sample_sns, max_per_batch=30)
        new_found = sum(1 for v in result.values() if v)
        method = "similarity-batch"
    else:
        # Legacy: 1 chamada LLM por prefixo
        import asyncio
        sem = asyncio.Semaphore(4)

        async def _resolve(sn: str):
            async with sem:
                try:
                    return await identify_manufacturer(sn)
                except Exception as e:
                    logger.warning("[identify-all] %s falhou: %s", sn[:8], e)
                    return None

        results = await asyncio.gather(*[_resolve(s) for s in sample_sns])
        new_found = sum(1 for r in results if r)
        method = "one-by-one"

    await _add_history(
        "identify_all",
        f"Descoberta forçada de fabricantes ({method}): {new_found} novos prefixos identificados de {len(sample_sns)} testados",
        user.get("name", "?"), "identify_all", cid)
    return {"prefixes_tested": len(sample_sns),
            "new_manufacturers_found": new_found,
            "total_prefixes_unknown_before": len(sample_sns),
            "method": method}


# ---------------------------------------------------------------------------
# RESET DESTRUTIVO — zera estoque e movimentações (somente Auditor)
# ---------------------------------------------------------------------------
class ReasonIn(BaseModel):
    """ONDA 1 — Motivo obrigatório para qualquer operação destrutiva.

    `code` deve estar em services.destructive_audit.DESTRUCTIVE_REASONS.
    Quando `code == "Outro"`, `details` é obrigatório com ≥ 20 chars.
    """
    code: str
    details: Optional[str] = None


class StokResetIn(BaseModel):
    """Confirmação obrigatória para o reset.

    O usuário precisa digitar EXATAMENTE "ZERAR ESTOQUE" no campo `confirm`.
    Sem isso a requisição é rejeitada. Garantia adicional contra mau uso.

    ONDA 1 (16/02/2026 — CTO): `reason` agora é OBRIGATÓRIO. Sem reason válido
    o endpoint retorna HTTP 400 ANTES de qualquer leitura ao banco.
    """
    confirm: str
    reset_history: bool = True
    reset_onts: bool = True
    reset_insumos: bool = True
    reason: Optional[ReasonIn] = None  # validação real no handler


@router.post("/admin/reset", status_code=200)
async def stok_admin_reset(payload: StokResetIn,
                              user: dict = Depends(require_role("auditor"))):
    """Zera estoque (ONTs + insumos) e/ou histórico de lançamentos.

    Restrições:
    - Somente role=auditor pode chamar (RBAC do `require_role`).
    - Exige `confirm == "ZERAR ESTOQUE"`.
    - Exige `reason` (code ∈ DESTRUCTIVE_REASONS; se "Outro", details ≥ 20 chars).
    - Apaga apenas dentro da `company_id` do auditor (escopo de tenant).

    Onda 1 — Auditoria patrimonial obrigatória:
    - ANTES do delete: dump COMPLETO dos docs em `destructive_actions_audit`
      via `record_destructive_action(...)` com `audit_hash` SHA-256.
    - APÓS o delete: contagens reais anexadas via `attach_after_snapshot(...)`.
    - `stok_admin_log` legado é MANTIDO em paralelo (compat retroativa).

    ROLLBACK: irreversível por delete_many. Recuperação só via re-insert do
    `before_snapshot.docs` (collection `destructive_actions_audit`) — auditor
    pode pedir restore manual via script.
    """
    if (payload.confirm or "").strip().upper() != "ZERAR ESTOQUE":
        raise HTTPException(400,
            "Confirmação inválida. Digite exatamente 'ZERAR ESTOQUE'.")

    # ─── Onda 1 — validação de reason ANTES de qualquer leitura ───────────
    from services.destructive_audit import (
        record_destructive_action, attach_after_snapshot,
        DestructiveAuditError,
    )
    reason_payload = (payload.reason.model_dump()
                      if payload.reason else None)
    if not reason_payload:
        raise HTTPException(400, {
            "error": "destructive_reason_required",
            "message": "Operação destrutiva exige `reason.code` "
                       "(e `details` ≥ 20 chars se code='Outro').",
        })

    cid = user.get("company_id") or DEMO_COMPANY_ID
    q = {"company_id": cid}

    # ─── Onda 1 — dump COMPLETO antes do delete (decisão CEO 2a) ──────────
    before_docs_onts: List[Dict[str, Any]] = []
    before_docs_consumables: List[Dict[str, Any]] = []
    before_docs_history: List[Dict[str, Any]] = []
    if payload.reset_onts:
        before_docs_onts = await db.stok_onts.find(q, {"_id": 0}).to_list(None)
    if payload.reset_insumos:
        before_docs_consumables = await db.stok_consumables.find(
            q, {"_id": 0}).to_list(None)
    if payload.reset_history:
        before_docs_history = await db.stok_history.find(
            q, {"_id": 0}).to_list(None)

    before = {
        "onts": len(before_docs_onts),
        "insumos": len(before_docs_consumables),
        "history": len(before_docs_history),
    }

    # Persiste auditoria ANTES do delete (chokepoint patrimonial)
    try:
        audit_doc = await record_destructive_action(
            company_id=cid,
            action_type="stok_reset_full",
            reason=reason_payload,
            executed_by={
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role"),
            },
            before_snapshot={
                "docs": (before_docs_onts + before_docs_consumables
                         + before_docs_history),
                "counts": before,
                "by_collection": {
                    "stok_onts": len(before_docs_onts),
                    "stok_consumables": len(before_docs_consumables),
                    "stok_history": len(before_docs_history),
                },
            },
            scope={
                "reset_onts": payload.reset_onts,
                "reset_insumos": payload.reset_insumos,
                "reset_history": payload.reset_history,
            },
        )
    except DestructiveAuditError as e:
        raise HTTPException(400, {
            "error": "destructive_audit_validation",
            "message": str(e),
        })

    # ─── Execução do delete (comportamento legado preservado) ─────────────
    deleted = {"onts": 0, "insumos": 0, "history": 0}
    if payload.reset_onts:
        r = await db.stok_onts.delete_many(q)
        deleted["onts"] = r.deleted_count
    if payload.reset_insumos:
        r = await db.stok_consumables.delete_many(q)
        deleted["insumos"] = r.deleted_count
    if payload.reset_history:
        r = await db.stok_history.delete_many(q)
        deleted["history"] = r.deleted_count

    # ─── Onda 1 — after_snapshot pós-execução ─────────────────────────────
    after_counts = {
        "onts": await db.stok_onts.count_documents(q),
        "insumos": await db.stok_consumables.count_documents(q),
        "history": await db.stok_history.count_documents(q),
    }
    try:
        await attach_after_snapshot(audit_doc["audit_id"], {
            "counts": after_counts,
            "delta": {k: before[k] - after_counts[k] for k in before},
        })
    except Exception as _e:
        logger.warning("[stok_reset] attach_after_snapshot falhou: %s", _e)

    # Log legado (mantido para compat com painel `/admin/reset/log`)
    log_entry = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "action": "stok_reset",
        "performed_by_email": user.get("email"),
        "performed_by_name": user.get("name"),
        "performed_by_role": user.get("role"),
        "timestamp": now_iso(),
        "before": before,
        "deleted": deleted,
        "scope": {
            "reset_onts": payload.reset_onts,
            "reset_insumos": payload.reset_insumos,
            "reset_history": payload.reset_history,
        },
        # Onda 1 — cross-reference para a auditoria canônica
        "destructive_audit_id": audit_doc["audit_id"],
        "destructive_audit_hash": audit_doc["audit_hash"],
    }
    try:
        await db.stok_admin_log.insert_one(log_entry)
    except Exception as e:
        logger.warning("[stok_reset] falha ao gravar log: %s", e)

    logger.warning(
        "[stok_reset] AUDITOR %s zerou estoque cid=%s · onts=%d insumos=%d hist=%d · audit=%s",
        user.get("email"), cid,
        deleted["onts"], deleted["insumos"], deleted["history"],
        audit_doc["audit_id"],
    )
    return {
        "ok": True, "before": before, "deleted": deleted,
        "after": after_counts,
        "log_id": log_entry["id"],
        "audit_id": audit_doc["audit_id"],
        "audit_hash": audit_doc["audit_hash"],
    }


@router.get("/admin/reset/log")
async def stok_admin_reset_log(user: dict = Depends(require_role("auditor"))):
    """Lista histórico de resets executados pelo auditor."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.stok_admin_log.find(
        {"company_id": cid, "action": {"$in": ["stok_reset", "stok_reset_granular"]}},
        {"_id": 0},
    ).sort("timestamp", -1).limit(50).to_list(50)
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# RESET GRANULAR — auditor zera por item, colaborador ou praça
# ---------------------------------------------------------------------------
class StokGranularResetIn(BaseModel):
    """Reset com escopo limitado.

    - `scope='item'` zera UM insumo específico em TODAS as locations
      (consumable_id em `target_id`).
    - `scope='collaborator'` zera ONTs com `location_id=<target_id>` (deleta
      do `stok_onts`, devolvendo para "empresa" se preferir) E o doc
      `stok_stock` com `location='tech:<target_id>'`.
    - `scope='praca'` zera ONTs com `location_id=<target_id>` (location_type=praca)
      E `stok_stock` com `location='praca:<target_id>'`.

    `reset_onts` e `reset_consumables` controlam quais entidades são
    afetadas dentro do escopo. Confirmação obrigatória.
    """
    confirm: str
    scope: str  # "item" | "collaborator" | "praca"
    target_id: str
    reset_onts: bool = True
    reset_consumables: bool = True
    reason: Optional[ReasonIn] = None  # Onda 1 — obrigatório no handler


@router.post("/admin/reset-granular", status_code=200)
async def stok_admin_reset_granular(payload: StokGranularResetIn,
                                       user: dict = Depends(require_role("auditor"))):
    """Reset por escopo (item, colaborador, praça).

    Onda 1 (16/02/2026): `reason` obrigatório + auditoria patrimonial via
    `destructive_audit.record_destructive_action`. Snapshot completo dos docs
    afetados ANTES do delete; contagens reais ANEXADAS após execução.

    ROLLBACK: irreversível por delete_many. Recuperação só via re-insert do
    `before_snapshot.docs` (em `destructive_actions_audit`).
    """
    if (payload.confirm or "").strip().upper() != "ZERAR ESTOQUE":
        raise HTTPException(400,
            "Confirmação inválida. Digite exatamente 'ZERAR ESTOQUE'.")
    scope = (payload.scope or "").strip().lower()
    if scope not in ("item", "collaborator", "praca"):
        raise HTTPException(400, "Escopo inválido. Use item|collaborator|praca.")
    if not (payload.target_id or "").strip():
        raise HTTPException(400, "target_id obrigatório.")

    # ─── Onda 1 — reason obrigatório ANTES de qualquer leitura ────────────
    from services.destructive_audit import (
        record_destructive_action, attach_after_snapshot,
        DestructiveAuditError,
    )
    reason_payload = (payload.reason.model_dump()
                      if payload.reason else None)
    if not reason_payload:
        raise HTTPException(400, {
            "error": "destructive_reason_required",
            "message": "Operação destrutiva exige `reason.code` "
                       "(e `details` ≥ 20 chars se code='Outro').",
        })

    cid = user.get("company_id") or DEMO_COMPANY_ID
    target = payload.target_id.strip()
    deleted = {"onts": 0, "consumables_rows": 0, "consumable_units": 0}
    before: Dict[str, Any] = {}
    target_label = target
    # ─── Onda 1 — dump completo dos docs antes do delete ──────────────────
    before_docs_onts: List[Dict[str, Any]] = []
    before_docs_stock: List[Dict[str, Any]] = []

    if scope == "item":
        # Validação do consumable_id
        if target not in CONSUMABLE_IDS:
            raise HTTPException(400, f"Insumo desconhecido: {target}")
        target_label = CONSUMABLE_BY_ID[target]["name"]
        # Soma total antes
        cur = db.stok_stock.find({"company_id": cid, target: {"$gt": 0}},
                                       {"_id": 0})
        before_docs_stock = await cur.to_list(2000)
        total_before = sum(r.get(target, 0) for r in before_docs_stock)
        before = {"total_units": total_before,
                  "rows_affected": len(before_docs_stock)}

    elif scope == "collaborator":
        coll = await db.collaborators.find_one(
            {"id": target, "company_id": cid}, {"_id": 0, "name": 1},
        )
        if not coll:
            raise HTTPException(404, "Colaborador não encontrado.")
        target_label = coll.get("name", target)
        if payload.reset_onts:
            before_docs_onts = await db.stok_onts.find(
                {"company_id": cid, "location_type": "tecnico",
                  "location_id": target}, {"_id": 0}).to_list(None)
            before["onts"] = len(before_docs_onts)
        if payload.reset_consumables:
            loc_key = f"tech:{target}"
            doc = await db.stok_stock.find_one(
                {"company_id": cid, "location": loc_key}, {"_id": 0},
            )
            if doc:
                before_docs_stock = [doc]
                before["consumables_units"] = sum(
                    v for k, v in doc.items() if k in CONSUMABLE_IDS
                    and isinstance(v, (int, float)))

    elif scope == "praca":
        praca = await db.pracas.find_one(
            {"id": target, "company_id": cid}, {"_id": 0, "name": 1},
        )
        if not praca:
            praca = await db.fin_filiais.find_one(
                {"id": target, "company_id": cid}, {"_id": 0, "name": 1},
            )
        if not praca:
            raise HTTPException(404, "Praça não encontrada.")
        target_label = praca.get("name", target)
        if payload.reset_onts:
            before_docs_onts = await db.stok_onts.find(
                {"company_id": cid, "location_type": "praca",
                  "location_id": target}, {"_id": 0}).to_list(None)
            before["onts_praca"] = len(before_docs_onts)
        if payload.reset_consumables:
            loc_key = f"praca:{target}"
            doc = await db.stok_stock.find_one(
                {"company_id": cid, "location": loc_key}, {"_id": 0},
            )
            extras = await db.stok_stock.find(
                {"company_id": cid, "praca_id": target}, {"_id": 0}
            ).to_list(2000)
            before_docs_stock = ([doc] if doc else []) + extras
            if doc:
                before["consumables_units"] = sum(
                    v for k, v in doc.items() if k in CONSUMABLE_IDS
                    and isinstance(v, (int, float)))

    # ─── Onda 1 — registra auditoria ANTES do delete ──────────────────────
    try:
        audit_doc = await record_destructive_action(
            company_id=cid,
            action_type="stok_reset_granular",
            reason=reason_payload,
            executed_by={
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role"),
            },
            before_snapshot={
                "docs": before_docs_onts + before_docs_stock,
                "counts": before,
                "by_collection": {
                    "stok_onts": len(before_docs_onts),
                    "stok_stock": len(before_docs_stock),
                },
            },
            scope={
                "scope": scope,
                "target_id": target,
                "target_label": target_label,
                "reset_onts": payload.reset_onts,
                "reset_consumables": payload.reset_consumables,
            },
        )
    except DestructiveAuditError as e:
        raise HTTPException(400, {
            "error": "destructive_audit_validation",
            "message": str(e),
        })

    # ─── Execução do delete (comportamento legado preservado) ─────────────
    if scope == "item":
        r = await db.stok_stock.update_many(
            {"company_id": cid}, {"$set": {target: 0}},
        )
        deleted["consumables_rows"] = r.modified_count
        deleted["consumable_units"] = before.get("total_units", 0)

    elif scope == "collaborator":
        if payload.reset_onts:
            r = await db.stok_onts.delete_many(
                {"company_id": cid, "location_type": "tecnico",
                  "location_id": target},
            )
            deleted["onts"] = r.deleted_count
        if payload.reset_consumables:
            loc_key = f"tech:{target}"
            r = await db.stok_stock.delete_one(
                {"company_id": cid, "location": loc_key})
            deleted["consumables_rows"] = r.deleted_count

    elif scope == "praca":
        if payload.reset_onts:
            r = await db.stok_onts.delete_many(
                {"company_id": cid, "location_type": "praca",
                  "location_id": target},
            )
            deleted["onts"] = r.deleted_count
        if payload.reset_consumables:
            loc_key = f"praca:{target}"
            r = await db.stok_stock.delete_one(
                {"company_id": cid, "location": loc_key})
            r2 = await db.stok_stock.update_many(
                {"company_id": cid, "praca_id": target},
                {"$set": {**{cid_: 0 for cid_ in CONSUMABLE_IDS}}},
            )
            deleted["consumables_rows"] = (
                (r.deleted_count or 0) + (r2.modified_count or 0))

    # ─── Onda 1 — after_snapshot pós-execução ─────────────────────────────
    after_counts: Dict[str, Any] = {}
    if scope == "item":
        after_counts = {"total_units": 0,
                         "rows_affected": deleted.get("consumables_rows", 0)}
    elif scope == "collaborator":
        after_counts["onts"] = await db.stok_onts.count_documents(
            {"company_id": cid, "location_type": "tecnico",
             "location_id": target})
        if payload.reset_consumables:
            after_counts["consumables_doc_exists"] = bool(
                await db.stok_stock.find_one(
                    {"company_id": cid, "location": f"tech:{target}"}))
    elif scope == "praca":
        after_counts["onts_praca"] = await db.stok_onts.count_documents(
            {"company_id": cid, "location_type": "praca",
             "location_id": target})
    try:
        await attach_after_snapshot(audit_doc["audit_id"], {
            "counts": after_counts,
            "deleted": deleted,
        })
    except Exception as _e:
        logger.warning("[stok_reset_granular] attach_after_snapshot falhou: %s", _e)

    # Auditoria legada + histórico (compat)
    log_entry = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "action": "stok_reset_granular",
        "performed_by_email": user.get("email"),
        "performed_by_name": user.get("name"),
        "performed_by_role": user.get("role"),
        "timestamp": now_iso(),
        "scope": scope,
        "target_id": target,
        "target_label": target_label,
        "reset_onts": payload.reset_onts,
        "reset_consumables": payload.reset_consumables,
        "before": before,
        "deleted": deleted,
        # Onda 1 — cross-reference para a auditoria canônica
        "destructive_audit_id": audit_doc["audit_id"],
        "destructive_audit_hash": audit_doc["audit_hash"],
    }
    try:
        await db.stok_admin_log.insert_one(log_entry)
    except Exception as e:
        logger.warning("[stok_reset_granular] log fail: %s", e)
    await _add_history(
        "admin_reset_granular",
        f"Auditor zerou {scope}={target_label}: "
        f"ONTs={deleted.get('onts', 0)}, "
        f"insumos_rows={deleted.get('consumables_rows', 0)}, "
        f"insumos_unidades={deleted.get('consumable_units', 0)}",
        user.get("name", "?"), "auditoria", cid,
    )
    logger.warning(
        "[stok_reset_granular] auditor=%s scope=%s target=%s deleted=%s audit=%s",
        user.get("email"), scope, target, deleted, audit_doc["audit_id"],
    )
    return {"ok": True, "scope": scope, "target_id": target,
             "target_label": target_label, "before": before,
             "deleted": deleted, "after": after_counts,
             "log_id": log_entry["id"],
             "audit_id": audit_doc["audit_id"],
             "audit_hash": audit_doc["audit_hash"]}


# ---------------------------------------------------------------------------
# RELATÓRIO DE QUEBRA DE ESTOQUE — perdas e divergências
# ---------------------------------------------------------------------------
@router.get("/admin/shrinkage-report")
async def stok_shrinkage_report(user: dict = Depends(require_role("auditor"))):
    """Relatório de quebra (shrinkage) de estoque.

    Para cada **insumo**: compara
      `entries`  (soma de eventos `entrada_insumo`) +
      `transfer` (movimentações internas, somam zero em rede mas servem
                  de auditoria) —
      `services` (consumo via fechamento de OS, derivado de `servico`)
      vs `current_balance` (soma de `stok_stock[item]` em todas as locations).

    Se `entries - services - current_balance > 0`, classifica como
    **QUEBRA** (item desaparecido / não rastreado).

    Para **ONTs**: total de eventos `entrada_ont` − ONTs registradas
    atualmente em `stok_onts` − ONTs instaladas em clientes
    (status='com_cliente') = delta. Delta>0 → quebra.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # ---- INSUMOS ----
    consumables_report: List[Dict[str, Any]] = []
    # Saldo atual por item
    stock_rows = await db.stok_stock.find(
        {"company_id": cid}, {"_id": 0},
    ).to_list(2000)
    current_balance = {cid_: 0 for cid_ in CONSUMABLE_IDS}
    for r in stock_rows:
        for k in CONSUMABLE_IDS:
            v = r.get(k)
            if isinstance(v, (int, float)) and v > 0:
                current_balance[k] = current_balance.get(k, 0) + v

    # Entradas e saídas via histórico (heurística baseada na descrição)
    hist = await db.stok_history.find(
        {"company_id": cid,
          "type": {"$in": ["entrada_insumo", "servico", "transferencia_insumo"]}},
        {"_id": 0, "type": 1, "description": 1},
    ).to_list(50000)
    entries = {cid_: 0 for cid_ in CONSUMABLE_IDS}
    consumed = {cid_: 0 for cid_ in CONSUMABLE_IDS}
    # Extrai quantidades das descrições — formato já padronizado:
    #   "Entrada de N {pack_label}(s) de {name}: {total} {unit}"
    import re
    for h in hist:
        desc = h.get("description") or ""
        t = h.get("type")
        for item_id, item in CONSUMABLE_BY_ID.items():
            if item["name"] not in desc:
                continue
            # Tenta extrair total
            m = re.search(r":\s*(\d+(?:\.\d+)?)\s*" + re.escape(item["unit"]),
                              desc)
            if not m:
                m = re.search(r"(\d+(?:\.\d+)?)\s*" + re.escape(item["unit"]),
                                  desc)
            qty = float(m.group(1)) if m else 0
            if qty <= 0:
                continue
            if t == "entrada_insumo":
                entries[item_id] += qty
            elif t == "servico":
                consumed[item_id] += qty
            break  # match único por linha
    # Monta o relatório
    total_entries = total_consumed = total_balance = total_shrinkage = 0
    for item_id, item in CONSUMABLE_BY_ID.items():
        e = entries.get(item_id, 0)
        c = consumed.get(item_id, 0)
        b = current_balance.get(item_id, 0)
        # Quebra = entradas − consumidos − saldo. Se positivo, sumiu.
        shrink = max(e - c - b, 0)
        total_entries += e
        total_consumed += c
        total_balance += b
        total_shrinkage += shrink
        consumables_report.append({
            "item_id": item_id, "name": item["name"], "unit": item["unit"],
            "entries": e, "consumed": c, "current_balance": b,
            "shrinkage": shrink,
            "shrinkage_pct": round((shrink / e) * 100, 2) if e > 0 else 0,
        })

    # ---- ONTs ----
    total_ont_entries = await db.stok_history.count_documents(
        {"company_id": cid, "type": "entrada_ont"},
    )
    # Entradas reais (cada doc pode ter trazido N ONTs). Como a descrição é
    # "Entrada de N ONT(s) modelo X" — soma N:
    entry_docs = await db.stok_history.find(
        {"company_id": cid, "type": "entrada_ont"},
        {"_id": 0, "description": 1},
    ).to_list(10000)
    ont_in = 0
    for d in entry_docs:
        m = re.search(r"Entrada de (\d+) ONT", d.get("description") or "")
        if m:
            ont_in += int(m.group(1))
    onts_now = await db.stok_onts.count_documents({"company_id": cid})
    onts_with_clients = await db.stok_onts.count_documents(
        {"company_id": cid, "status": "com_cliente"})
    # Quebra = entradas − total atual no banco (independente da status,
    # pois já estão em algum lugar dentro do sistema).
    ont_shrinkage = max(ont_in - onts_now, 0)

    return {
        "company_id": cid,
        "generated_at": now_iso(),
        "consumables": consumables_report,
        "consumables_totals": {
            "entries": total_entries,
            "consumed": total_consumed,
            "current_balance": total_balance,
            "shrinkage": total_shrinkage,
        },
        "onts": {
            "entries_events": total_ont_entries,
            "total_in": ont_in,
            "current_count": onts_now,
            "with_clients": onts_with_clients,
            "shrinkage": ont_shrinkage,
        },
    }


# ---------------------------------------------------------------------------
# Zerar QUEBRA — auditor compensa shrinkage com lançamentos de ajuste
# ---------------------------------------------------------------------------
class StokClearShrinkageIn(BaseModel):
    """Confirmação para zerar a quebra. Mesmo padrão de segurança do reset."""
    confirm: str
    include_onts: bool = True
    include_consumables: bool = True
    reason: Optional[str] = "Ajuste auditor"


@router.post("/admin/clear-shrinkage", status_code=200)
async def stok_clear_shrinkage(payload: StokClearShrinkageIn,
                                  user: dict = Depends(require_role("auditor"))):
    """Zera a QUEBRA de estoque (shrinkage) registrando lançamentos
    compensatórios em `stok_history`. Preserva o histórico original.

    Estratégia:
    - Calcula a quebra atual chamando a mesma lógica do shrinkage-report.
    - Para cada insumo com quebra > 0, insere 1 doc com type=`servico` e
      descrição no formato que a fórmula entende como consumo, anulando
      a diferença (consumed += shrink).
    - Para ONTs com quebra > 0, insere 1 doc com type=`saida_ont_ajuste`
      e ajusta os contadores internos via descrição.
    - Toda operação é logada em `stok_admin_log`.
    """
    if (payload.confirm or "").strip().upper() != "ZERAR QUEBRA":
        raise HTTPException(400,
            "Confirmação inválida. Digite exatamente 'ZERAR QUEBRA'.")

    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Reaproveita a função de relatório (chamando o handler internamente
    # com user fake do mesmo company_id e role auditor).
    report = await stok_shrinkage_report(user=user)

    adjustments: List[Dict[str, Any]] = []
    total_compensated_units = 0
    reason = (payload.reason or "Ajuste auditor")[:80]
    now = now_iso()

    if payload.include_consumables:
        for c in report.get("consumables", []):
            shrink = float(c.get("shrinkage") or 0)
            if shrink <= 0:
                continue
            name = c["name"]
            unit = c["unit"]
            # Formato que o regex do report reconhece como consumo via
            # 'servico': "...{name}...: {qty} {unit}"
            qty_str = f"{int(shrink)}" if shrink.is_integer() else f"{shrink:.2f}"
            desc = (f"Ajuste de quebra (auditor {user.get('email') or '—'}) "
                    f"— {reason}: {name}: {qty_str} {unit}")
            doc = {
                "id": str(uuid.uuid4()),
                "company_id": cid,
                "type": "servico",  # entra na coluna `consumed` do report
                "description": desc,
                "performed_by_email": user.get("email"),
                "performed_by_name": user.get("name"),
                "performed_by_role": user.get("role"),
                "created_at": now,
                "is_shrinkage_adjustment": True,
                "adjustment_target": c.get("item_id"),
                "adjustment_qty": shrink,
                "adjustment_unit": unit,
            }
            await db.stok_history.insert_one(doc)
            adjustments.append({
                "item_id": c.get("item_id"), "name": name,
                "qty": shrink, "unit": unit,
            })
            total_compensated_units += shrink

    ont_shrink_compensated = 0
    if payload.include_onts:
        ont_shrink = int(report.get("onts", {}).get("shrinkage") or 0)
        if ont_shrink > 0:
            # Insere doc que compensa quebra de ONTs.
            # A fórmula do report usa: ont_in (de entrada_ont) − onts_now.
            # Para zerar, inserimos um doc do tipo `entrada_ont` negativo
            # (formato "Entrada de -N ONT" NÃO funciona com regex \d+).
            # Solução: inserir docs `entrada_ont` com Quantity=0 NÃO ajuda.
            # Em vez disso, vamos remover (idempotentemente) docs de
            # entrada_ont mais antigos até zerar — preservando os mais
            # recentes que correspondem ao estoque ATUAL.
            # Mas o usuário quer "zerar" — usaremos a abordagem auditoria:
            # apagar entradas_ont antigas (>= ont_shrink) e logar.
            remaining = ont_shrink
            cursor = db.stok_history.find({
                "company_id": cid, "type": "entrada_ont",
                "is_shrinkage_adjustment": {"$ne": True},
            }, {"_id": 0, "id": 1, "description": 1}).sort("created_at", 1)
            import re as _re
            async for d in cursor:
                if remaining <= 0:
                    break
                m = _re.search(r"Entrada de (\d+) ONT", d.get("description") or "")
                if not m:
                    continue
                qty = int(m.group(1))
                if qty <= remaining:
                    await db.stok_history.delete_one({"id": d["id"]})
                    remaining -= qty
                else:
                    # Reduz o N para qty − remaining (mantém o registro)
                    new_qty = qty - remaining
                    new_desc = _re.sub(
                        r"Entrada de \d+ ONT",
                        f"Entrada de {new_qty} ONT", d.get("description"),
                    )
                    await db.stok_history.update_one(
                        {"id": d["id"]},
                        {"$set": {"description": new_desc,
                                   "shrinkage_adjusted_at": now,
                                   "shrinkage_adjusted_by": user.get("email")}},
                    )
                    remaining = 0
            ont_shrink_compensated = ont_shrink - remaining
            # Marca log explícito
            await db.stok_history.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": cid,
                "type": "ajuste_quebra_ont",
                "description": (f"Ajuste auditor: {ont_shrink_compensated} ONT(s) "
                                f"perdidas baixadas — {reason}"),
                "performed_by_email": user.get("email"),
                "performed_by_role": user.get("role"),
                "created_at": now,
                "is_shrinkage_adjustment": True,
                "adjustment_qty": ont_shrink_compensated,
            })

    # Log permanente
    log_entry = {
        "id": str(uuid.uuid4()),
        "company_id": cid,
        "action": "stok_clear_shrinkage",
        "performed_by_email": user.get("email"),
        "performed_by_name": user.get("name"),
        "performed_by_role": user.get("role"),
        "timestamp": now,
        "reason": reason,
        "consumables_adjustments": adjustments,
        "consumables_total_units": total_compensated_units,
        "onts_compensated": ont_shrink_compensated,
        "report_snapshot": {
            "consumables_totals": report.get("consumables_totals"),
            "onts": report.get("onts"),
        },
    }
    try:
        await db.stok_admin_log.insert_one(log_entry)
    except Exception as e:
        logger.warning("[stok_clear_shrinkage] log fail: %s", e)

    logger.warning(
        "[stok_clear_shrinkage] AUDITOR %s zerou quebra cid=%s · "
        "itens=%d unidades=%.1f onts=%d",
        user.get("email"), cid, len(adjustments),
        total_compensated_units, ont_shrink_compensated,
    )
    return {
        "ok": True,
        "consumables_adjustments": adjustments,
        "consumables_total_units": total_compensated_units,
        "onts_compensated": ont_shrink_compensated,
        "log_id": log_entry["id"],
    }


# ===========================================================================
# iter215am — Painel de Revisão IA de ONTs retiradas por foto
# ---------------------------------------------------------------------------
# Lista equipamentos retirados via OS de retirada/troca sem SN no SmartOLT
# (entrada criada no `lousa.public_finalize_ticket`). Gestor revisa a foto
# + análise da IA e decide: aprovar pra reaproveitar com o técnico, devolver
# ao estoque da empresa, ou descartar como defeito.
# ===========================================================================
class AiReviewApproveIn(BaseModel):
    decision: str  # "approve_reuse" | "return_to_company" | "scrap_defect"
    note: Optional[str] = None
    final_sn: Optional[str] = None
    final_mac: Optional[str] = None
    final_model: Optional[str] = None


@router.get("/ai-review/pending")
async def list_ai_review_pending(
    user: dict = Depends(require_role("gestor")),
):
    """Lista entradas pendentes (ou já analisadas pela IA mas ainda sem
    decisão do gestor)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_onts.find(
        {"company_id": cid, "via_photo_ai": True,
         "status": {"$in": ["pending_ai_review",
                              "pending_human_review",
                              "bloqueado_defeito"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    techs = {}
    for d in docs:
        tid = d.get("location_id")
        if tid and tid not in techs:
            t = await db.collaborators.find_one(
                {"id": tid}, {"_id": 0, "name": 1})
            techs[tid] = (t or {}).get("name") or tid
        d["technician_name"] = techs.get(tid)
    return {"items": docs, "count": len(docs)}


@router.post("/ai-review/{ont_id}/decision")
async def decide_ai_review(
    ont_id: str,
    payload: AiReviewApproveIn,
    user: dict = Depends(require_role("gestor")),
):
    """Aplica a decisão do gestor a uma entrada pendente."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.stok_onts.find_one(
        {"id": ont_id, "company_id": cid, "via_photo_ai": True},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Entrada não encontrada")
    decision = (payload.decision or "").strip()
    if decision not in ("approve_reuse", "return_to_company",
                          "scrap_defect"):
        raise HTTPException(400, "decision inválido")

    update_set: Dict[str, Any] = {
        "ai_review_decision": decision,
        "ai_review_decided_at": now_iso(),
        "ai_review_decided_by_email": user.get("email"),
        "ai_review_decided_by_name": user.get("name") or user.get("email"),
        "via_photo_ai_resolved": True,
    }
    if payload.note:
        update_set["ai_review_note"] = payload.note[:500]
    # Permite o gestor ajustar SN/MAC/modelo manualmente
    if payload.final_sn:
        update_set["sn"] = payload.final_sn.strip().upper()
    if payload.final_mac:
        update_set["mac"] = payload.final_mac.strip().upper()
    if payload.final_model:
        update_set["model"] = payload.final_model.strip()

    if decision == "approve_reuse":
        # Reaproveitar: fica com o técnico como "retirada_com_tecnico"
        update_set["status"] = "retirada_com_tecnico"
        update_set["is_defective"] = False
        update_set["defective_reason"] = None
    elif decision == "return_to_company":
        # Devolver à empresa: status `retornada_empresa`
        update_set["status"] = "retornada_empresa"
        update_set["location_type"] = "empresa"
        update_set["location_id"] = "empresa"
        update_set["location"] = "empresa"
    elif decision == "scrap_defect":
        # Descarte definitivo (sucateada). Continua no técnico até
        # devolução física, mas indisponível pra reinstalar.
        update_set["status"] = "sucateada"
        update_set["is_defective"] = True
        if payload.note and not doc.get("defective_reason"):
            update_set["defective_reason"] = payload.note[:300]

    await db.stok_onts.update_one(
        {"id": ont_id, "company_id": cid},
        {"$set": update_set},
    )
    # Histórico
    try:
        await db.stok_history.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": cid,
            "date": now_iso(),
            "type": "ai_review_decision",
            "description": (
                f"ONT {ont_id} — gestor decidiu {decision}"
                + (f" (nota: {payload.note[:120]})" if payload.note else "")
                + f". Novo status: {update_set['status']}."
            ),
            "user": user.get("email"),
            "tag": "stok_ai_review",
            "ticket_id": doc.get("ticket_id"),
        })
    except Exception as e:
        logger.warning("[stok] history ai-review falhou: %s", e)
    return {"ok": True, "id": ont_id,
            "status": update_set["status"],
            "decision": decision}
