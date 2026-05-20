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

import csv
import io
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

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
]
CONSUMABLE_IDS = {c["id"] for c in CONSUMABLE_CATALOG}
CONSUMABLE_BY_ID: Dict[str, Dict[str, Any]] = {c["id"]: c for c in CONSUMABLE_CATALOG}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class OntBulkIn(BaseModel):
    model: str
    macs: List[str]


class OntEditIn(BaseModel):
    model: str


class OntTransferIn(BaseModel):
    mac: str
    technician_id: str  # = collaborator.id


class ConsumablePurchaseIn(BaseModel):
    consumable_id: str
    pack_qty: int


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
    used_items: List[UsedItem] = []
    tag: str = "instalacao"


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
        installed = sum(1 for h in history if h["type"] == "instalacao" and t["name"] in h["description"])
        withdrawals = sum(1 for h in history if h["type"] == "retirada" and t["name"] in h["description"])
        rows.append({
            "id": t["id"],
            "name": t["name"],
            "tech_onts": tech_onts,
            "installed_month": installed,
            "withdrawals": withdrawals,
            "stock": {c: stock_by_loc.get(t["id"], {}).get(c, 0) for c in CONSUMABLE_IDS},
        })

    expected = sum(1 for s in services if s["type"] == "retirada") + \
        sum(1 for h in history if h["tag"] in ("inadimplencia", "cancelamento"))
    effective = sum(1 for h in history if h["type"] == "retirada")
    rate = round((effective / expected) * 100) if expected else 0
    active_count = sum(1 for s in services if s["status"] == "ativo")

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


@router.post("/onts/bulk")
async def create_onts_bulk(payload: OntBulkIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    model = payload.model.strip()
    if not model:
        raise HTTPException(400, "Informe o modelo da ONT.")
    macs = [normalize_mac(m) for m in payload.macs if m.strip()]
    if not macs:
        raise HTTPException(400, "Informe pelo menos um MAC.")
    macs_unique = list(dict.fromkeys(macs))
    existing = await db.stok_onts.find(
        {"company_id": cid, "mac": {"$in": macs_unique}}, {"mac": 1, "_id": 0},
    ).to_list(5000)
    if existing:
        raise HTTPException(400, f"MAC já cadastrado: {existing[0]['mac']}")
    docs = [{
        "company_id": cid, "mac": mac, "model": model,
        "location_type": "empresa", "location_id": "empresa",
        "client_name": None, "status": "disponivel",
        "created_by": user.get("email", "?"), "created_at": now_iso(),
    } for mac in macs_unique]
    await db.stok_onts.insert_many([dict(d) for d in docs])
    await _add_history("entrada_ont", f"Entrada de {len(docs)} ONT(s) modelo {model} no estoque empresa",
                       user.get("name", "?"), "compra", cid)
    return {"inserted": len(docs), "macs": macs_unique}


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


@router.post("/onts/transfer-to-tech")
async def transfer_ont_to_tech(payload: OntTransferIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    mac_n = normalize_mac(payload.mac)
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "MAC não encontrado.")
    if ont["location_type"] != "empresa":
        raise HTTPException(400, "ONT precisa estar no estoque da empresa para ser transferida.")
    tech = await _get_collab(payload.technician_id, cid)
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {"location_type": "tecnico", "location_id": payload.technician_id, "status": "com_tecnico"}},
    )
    await _add_history("transferencia", f"ONT {mac_n} transferida da empresa para {tech['name']}",
                       user.get("name", "?"), "transferencia", cid)
    return {"ok": True}


class OntBulkTransferIn(BaseModel):
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
async def transfer_onts_bulk(payload: OntBulkTransferIn,
                               user: dict = Depends(require_role("gestor"))):
    """Transfere várias ONTs de uma vez (UX simple recomendada).

    Aceita lista de MACs e o técnico destino. Retorna detalhes do que
    foi/não foi transferido (ex: MAC não encontrado, MAC já com técnico).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    macs_norm = list(dict.fromkeys(normalize_mac(m) for m in payload.macs if m))
    if not macs_norm:
        raise HTTPException(400, "Informe pelo menos um MAC.")
    tech = await _get_collab(payload.technician_id, cid)
    docs = await db.stok_onts.find(
        {"company_id": cid, "mac": {"$in": macs_norm}},
        {"_id": 0, "mac": 1, "location_type": 1, "location_id": 1},
    ).to_list(2000)
    by_mac = {d["mac"]: d for d in docs}
    transferred: List[str] = []
    skipped: List[Dict[str, str]] = []
    for m in macs_norm:
        d = by_mac.get(m)
        if not d:
            skipped.append({"mac": m, "reason": "não encontrado"})
            continue
        if d["location_type"] != "empresa":
            skipped.append({"mac": m, "reason":
                              f"está em {d['location_type']}"})
            continue
        transferred.append(m)
    if transferred:
        await db.stok_onts.update_many(
            {"company_id": cid, "mac": {"$in": transferred}},
            {"$set": {"location_type": "tecnico",
                       "location_id": payload.technician_id,
                       "status": "com_tecnico"}},
        )
        await _add_history(
            "transferencia",
            f"BULK: {len(transferred)} ONT(s) transferidas para {tech['name']}",
            user.get("name", "?"), "transferencia", cid,
        )
    return {
        "ok": True,
        "transferred_count": len(transferred),
        "transferred": transferred,
        "skipped": skipped,
    }


@router.post("/onts/{mac}/return-to-company")
async def return_ont_to_company(mac: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    mac_n = normalize_mac(mac)
    ont = await db.stok_onts.find_one({"company_id": cid, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "MAC não encontrado.")
    if ont["location_type"] != "tecnico":
        raise HTTPException(400, "ONT precisa estar com técnico para retornar à empresa.")
    tech = await db.collaborators.find_one({"id": ont["location_id"]}, {"_id": 0, "name": 1})
    await db.stok_onts.update_one(
        {"company_id": cid, "mac": mac_n},
        {"$set": {"location_type": "empresa", "location_id": "empresa",
                  "status": "retornada_empresa", "client_name": None}},
    )
    await _add_history("devolucao", f"ONT {mac_n} devolvida por {(tech or {}).get('name', 'técnico')} ao estoque da empresa",
                       user.get("name", "?"), "retorno_empresa", cid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Stock (insumos)
# ---------------------------------------------------------------------------
@router.get("/stock")
async def get_stock(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.stok_stock.find({"company_id": cid}, {"_id": 0}).to_list(500)
    return {d["location"]: {c: d.get(c, 0) for c in CONSUMABLE_IDS} for d in docs}


@router.post("/consumables/purchase")
async def purchase_consumable(payload: ConsumablePurchaseIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    item = CONSUMABLE_BY_ID.get(payload.consumable_id)
    if not item:
        raise HTTPException(400, "Insumo inválido.")
    if payload.pack_qty <= 0:
        raise HTTPException(400, "Quantidade inválida.")
    total = payload.pack_qty * item["pack_qty"]
    await db.stok_stock.update_one(
        {"company_id": cid, "location": "empresa"},
        {"$inc": {item["id"]: total}, "$setOnInsert": {"company_id": cid, "location": "empresa"}},
        upsert=True,
    )
    await _add_history("entrada_insumo",
                       f"Entrada de {payload.pack_qty} {item['pack_label']}(s) de {item['name']}: {total} {item['unit']}",
                       user.get("name", "?"), "compra", cid)
    return {"ok": True, "added": total}


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
        {"_id": 0, "mac": 1, "model": 1, "status": 1},
    ).to_list(200)
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
                                 used_items: List[UsedItem]) -> None:
    tech_stock = await db.stok_stock.find_one(
        {"company_id": company_id, "location": technician_id}, {"_id": 0},
    ) or {}
    for ui in used_items:
        if ui.quantity > 0 and tech_stock.get(ui.consumable_id, 0) < ui.quantity:
            item = CONSUMABLE_BY_ID[ui.consumable_id]
            raise HTTPException(400, f"{tech_name} não tem saldo suficiente de {item['name']}.")


async def _move_ont_for_install(company_id: str, service: dict, mac_input: Optional[str]) -> str:
    if not mac_input:
        raise HTTPException(400, "Para instalação/troca, informe o MAC da ONT.")
    mac_n = normalize_mac(mac_input)
    ont = await db.stok_onts.find_one({"company_id": company_id, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "MAC da ONT não existe.")
    if ont["location_type"] != "tecnico" or ont["location_id"] != service["technician_id"]:
        raise HTTPException(400, "A ONT precisa estar no estoque do técnico responsável.")
    await db.stok_onts.update_one(
        {"company_id": company_id, "mac": mac_n},
        {"$set": {"location_type": "cliente", "location_id": service["client_id"],
                  "client_name": service["client_name"], "status": "instalada"}},
    )
    return f"ONT {mac_n} instalada no {service['client_name']}"


async def _move_ont_for_withdraw(company_id: str, service: dict, tech_name: str,
                                  mac_input: Optional[str]) -> str:
    if not mac_input:
        raise HTTPException(400, "Para retirada, informe o MAC da ONT retirada.")
    mac_n = normalize_mac(mac_input)
    ont = await db.stok_onts.find_one({"company_id": company_id, "mac": mac_n}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "MAC da ONT não existe.")
    if ont["location_type"] != "cliente" or ont["location_id"] != service["client_id"]:
        raise HTTPException(400, "A ONT precisa estar vinculada a este cliente.")
    await db.stok_onts.update_one(
        {"company_id": company_id, "mac": mac_n},
        {"$set": {"location_type": "tecnico", "location_id": service["technician_id"],
                  "client_name": None, "status": "retirada_com_tecnico"}},
    )
    return f"ONT {mac_n} retirada do {service['client_name']} e entrou no estoque de {tech_name}"


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
                         user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    service = await db.stok_services.find_one(
        {"id": service_id, "company_id": cid,
         "status": {"$in": ["ativo", "erro_estoque"]}}, {"_id": 0},
    )
    if not service:
        raise HTTPException(404, "Serviço ativo não encontrado. Sem serviço ativo não existe baixa de estoque.")
    tech = await _get_collab(service["technician_id"], cid)

    _validate_used_items(payload.used_items)
    await _check_tech_has_stock(cid, service["technician_id"], tech["name"], payload.used_items)

    parts: List[str] = []
    if service["type"] in ("instalacao", "troca"):
        parts.append(await _move_ont_for_install(cid, service, payload.ont_mac))
    elif service["type"] == "retirada":
        parts.append(await _move_ont_for_withdraw(cid, service, tech["name"], payload.ont_mac))

    stock_desc = await _decrement_tech_stock(cid, service["technician_id"], payload.used_items)
    if stock_desc:
        parts.append(stock_desc)

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
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso


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
) -> dict:
    """Quando técnico finaliza bolha, auto-fecha a OS associada e baixa estoque.

    Mapeia `completion_data` (Lousa) para `used_items` (Estoque).
    Tratamento de erro: se saldo insuficiente OU MAC inválido, marca OS como
    `status="erro_estoque"` com notas pro gestor, mas **não derruba o finalize
    da Lousa** (best-effort).
    Retorna `{ok, service_id?, reason?, used_items?}` para logging.
    """
    if not ticket_id or not company_id:
        return {"ok": False, "reason": "missing_ids"}
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

    err_reason: Optional[str] = None
    parts: List[str] = []
    smartolt_validation: Optional[dict] = None

    # SmartOLT: cross-check do MAC contra cache (rastreabilidade)
    if ont_mac:
        try:
            sm_doc = await db.smartolt_onus.find_one(
                {"company_id": company_id,
                 "$or": [{"unique_external_id": ont_mac}, {"sn": ont_mac}]},
                {"_id": 0, "unique_external_id": 1, "sn": 1, "name": 1,
                 "olt_name": 1, "status": 1, "signal_1490": 1},
            )
            if sm_doc:
                smartolt_validation = sm_doc
        except Exception as e:
            logger.warning("[stok] smartolt cross-check falhou: %s", e)

    # Validações em try-block: qualquer erro vira "erro_estoque" sem derrubar
    try:
        _validate_used_items(used_items)
        await _check_tech_has_stock(company_id, technician_id, technician_name, used_items)
        if service["type"] in ("instalacao", "troca"):
            if not ont_mac:
                raise HTTPException(400, "MAC da ONT é obrigatório para instalação/troca.")
            parts.append(await _move_ont_for_install(company_id, service, ont_mac))
        elif service["type"] == "retirada":
            if not ont_mac:
                raise HTTPException(400, "MAC da ONT retirada é obrigatório.")
            parts.append(await _move_ont_for_withdraw(company_id, service, technician_name, ont_mac))
        stock_desc = await _decrement_tech_stock(company_id, technician_id, used_items)
        if stock_desc:
            parts.append(stock_desc)
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
                        identify_manufacturer_max: int = 100,
                        user: dict = Depends(require_role("gestor"))):
    """Lista todas as ONUs em uso pelos clientes (cache do SmartOLT).

    Para cada ONU retorna: cliente, número de série, MAC, fabricante (detectado
    via prefixo IEEE/CCM, com fallback Gemini Flash). O `identify_manufacturer_max`
    limita quantas detecções por LLM são feitas por chamada (cache permanente
    em `manufacturer_cache` cobre repetições).
    """
    from manufacturers import identify_manufacturer
    cid = user.get("company_id") or DEMO_COMPANY_ID

    q = {"company_id": cid}
    if only_authorized:
        q["authorization_date"] = {"$nin": [None, "", "0000-00-00"]}
    cur = db.smartolt_onus.find(q, {"_id": 0}).limit(min(max(limit, 1), 10000))

    items: list[dict] = []
    sn_list: list[str] = []
    async for o in cur:
        sn = (o.get("sn") or "").strip().upper()
        mac = (o.get("mac") or o.get("ont_mac") or "").strip()
        items.append({
            "client_name": o.get("name") or "(cliente sem nome)",
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
        })
        if sn:
            sn_list.append(sn)

    # Otimização: identifica por PREFIXO único (não por SN) — cache cobre
    # tudo de graça. Limit aplica apenas a chamadas LLM novas.
    detected = await _detect_by_prefix(
        sn_list, identify_manufacturer, llm_max=identify_manufacturer_max)

    # Aplica nos itens
    for it in items:
        if it.get("sn") and it["sn"] in detected:
            it["manufacturer"] = detected[it["sn"]]

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


async def _detect_many_manufacturers(sns: list[str], identify_fn) -> dict:
    """Detecta fabricantes em paralelo, cache-friendly. Limita concorrência
    para não sobrecarregar Gemini."""
    import asyncio
    sem = asyncio.Semaphore(6)

    async def one(sn: str):
        async with sem:
            try:
                return sn, await identify_fn(sn)
            except Exception as e:
                logger.warning("[clientes] detect %s falhou: %s", sn[:8], e)
                return sn, None

    results = await asyncio.gather(*[one(s) for s in sns], return_exceptions=False)
    return {s: m for s, m in results if m}


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
