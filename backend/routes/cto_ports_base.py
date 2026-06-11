"""cto_ports_base — iter182. Base de Portas das CTOs.

Modelo denormalizado: cada documento representa UMA porta de UMA CTO,
com status (livre/ocupada/defeituosa), cliente vinculado (se houver),
MAC, SN, sinal e timestamps de ocupação/liberação. É uma "view"
materializada das `ctos.ports[]` — facilita consultas por cliente,
por MAC, por CTO ou por status sem precisar fazer $unwind.

Origem (source of truth): `ctos.ports[]`. Esta collection é sincronizada
via hooks `sync_port_from_cto` que devem ser chamados após qualquer
alteração nas portas (occupy/free/migrate/manual edit).

Endpoints (router prefix /api/cto-ports):
  GET    /              listar com filtros (cto_id, status, subscriber_id, q)
  GET    /stats         contagens por status na empresa
  GET    /by-cto/{id}   todas as portas de uma CTO
  GET    /by-subscriber/{id}   porta atual do assinante (None se livre)
  POST   /sync          re-sincronizar TODA a base a partir de ctos.ports
                       (admin only — idempotente; usa para migração)
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["cto.updated"],
    "company_id_required": True,
}

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import now_iso, require_role
from database import db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cto-ports", tags=["cto-ports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


def _port_doc_id(cto_id: str, port_number: int) -> str:
    """ID estável p/ a porta. Permite upsert atômico."""
    return f"{cto_id}-p{int(port_number)}"


def _normalize_status(status: Optional[str]) -> str:
    """Normaliza status: livre / ocupada / defeituosa."""
    if not status:
        return "free"
    s = status.lower().strip()
    if s in ("used", "occupied", "ocupada"):
        return "occupied"
    if s in ("defective", "defect", "defeito", "defeituosa"):
        return "defective"
    return "free"


async def sync_port_from_cto(company_id: str, cto_id: str,
                                 port_number: int) -> Optional[Dict[str, Any]]:
    """Re-sincroniza UMA porta da collection denormalizada a partir do
    documento real em ctos.ports. Idempotente — pode ser chamado várias
    vezes em sequência.

    iter182 — Saneamento automático: se a porta está marcada como
    `occupied` mas o subscriber referenciado NÃO existe mais (ou
    subscriber_id é null/vazio), libera a porta automaticamente em
    ctos.ports[] ANTES de sincronizar — não deixa porta ocupada órfã.
    """
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "vlan": 1, "ports": 1,
         "olt_name": 1, "neighborhood": 1, "lat": 1, "lng": 1,
         "technician_name": 1, "technician_id": 1,
         "created_by_user_id": 1, "created_at": 1},
    )
    if not cto:
        return None
    p = next((x for x in (cto.get("ports") or [])
              if int(x.get("number") or 0) == int(port_number)), None)
    if not p:
        return None
    status = _normalize_status(p.get("status"))
    subscriber_id = (p.get("client_subscriber_id") or "").strip() or None

    # ----- SANEAMENTO: porta ocupada sem cliente válido -> libera -----
    invalid = False
    if status == "occupied":
        if not subscriber_id:
            invalid = True
            reason = "auto_heal_no_subscriber_id"
        else:
            sub_exists = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": company_id},
                {"_id": 0, "id": 1},
            )
            if not sub_exists:
                invalid = True
                reason = "auto_heal_subscriber_deleted"
    if invalid:
        await db.ctos.update_one(
            {"id": cto_id, "company_id": company_id,
             "ports.number": int(port_number)},
            {"$set": {
                "ports.$.status": "free",
                "ports.$.client_subscriber_id": None,
                "ports.$.client_pppoe": None,
                "ports.$.client_name": None,
                "ports.$.client_phone": None,
                "ports.$.released_at": now_iso(),
                "ports.$.release_reason": reason,
                "updated_at": now_iso(),
            }},
        )
        logger.warning(
            "[cto-ports] auto-healed orphan port cid=%s cto=%s p=%s"
            " reason=%s old_sub=%s",
            company_id, cto_id, port_number, reason, subscriber_id)
        cto = await db.ctos.find_one(
            {"id": cto_id, "company_id": company_id},
            {"_id": 0, "id": 1, "name": 1, "vlan": 1, "ports": 1,
             "olt_name": 1, "neighborhood": 1, "lat": 1, "lng": 1,
             "technician_name": 1, "technician_id": 1,
             "created_by_user_id": 1, "created_at": 1},
        )
        p = next((x for x in (cto.get("ports") or [])
                  if int(x.get("number") or 0) == int(port_number)), None)
        status = _normalize_status(p.get("status"))
        subscriber_id = None
    # ----- fim do saneamento -----

    doc_id = _port_doc_id(cto_id, port_number)
    mac = None
    sn = None
    signal_dbm = None
    pppoe_user = p.get("client_pppoe") or None
    if subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": subscriber_id, "company_id": company_id},
            {"_id": 0, "ont_mac": 1, "ont_sn": 1, "last_signal_dbm": 1,
             "pppoe_user": 1, "name": 1},
        ) or {}
        mac = (sub.get("ont_mac") or "").upper() or None
        sn = (sub.get("ont_sn") or "").upper() or None
        signal_dbm = sub.get("last_signal_dbm")
        pppoe_user = pppoe_user or sub.get("pppoe_user")
    doc = {
        "id": doc_id,
        "company_id": company_id,
        "cto_id": cto_id,
        "cto_name": cto.get("name"),
        "olt_name": cto.get("olt_name"),
        "neighborhood": cto.get("neighborhood"),
        "lat": cto.get("lat"),
        "lng": cto.get("lng"),
        "vlan": cto.get("vlan"),
        # iter182 — Técnico que cadastrou a CTO (rastreabilidade)
        "cto_technician_name": cto.get("technician_name"),
        "cto_technician_id": cto.get("technician_id"),
        "cto_created_at": cto.get("created_at"),
        "port_number": int(port_number),
        "status": status,
        "subscriber_id": subscriber_id,
        "subscriber_name": p.get("client_name") or None,
        "pppoe_user": pppoe_user,
        "mac": mac,
        "sn": sn,
        "signal_dbm": signal_dbm,
        "occupied_at": p.get("linked_at"),
        "freed_at": p.get("released_at"),
        "linked_by_email": p.get("linked_by_user_email"),
        "release_reason": p.get("release_reason"),
        "last_updated_at": now_iso(),
    }
    await db.cto_ports.update_one(
        {"id": doc_id}, {"$set": doc}, upsert=True,
    )
    return doc


async def sync_cto_all_ports(company_id: str, cto_id: str) -> int:
    """Sincroniza TODAS as portas de uma CTO. Retorna nº de portas."""
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": company_id},
        {"_id": 0, "ports": 1},
    )
    if not cto:
        return 0
    n = 0
    for p in (cto.get("ports") or []):
        num = p.get("number")
        if num is None:
            continue
        await sync_port_from_cto(company_id, cto_id, int(num))
        n += 1
    return n


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_ports(
    cto_id: Optional[str] = None,
    status: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    q: Optional[str] = Query(None, description="Busca: MAC/SN/PPPoE/Nome"),
    limit: int = 100,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "auditor",
                                          "tecnico", "supervisor")),
):
    """Lista portas com filtros. Default: todas da empresa."""
    cid = _user_company(user)
    filt: Dict[str, Any] = {"company_id": cid}
    if cto_id:
        filt["cto_id"] = cto_id
    if status:
        filt["status"] = _normalize_status(status)
    if subscriber_id:
        filt["subscriber_id"] = subscriber_id
    if q:
        qs = q.strip().upper()
        filt["$or"] = [
            {"mac": {"$regex": qs, "$options": "i"}},
            {"sn": {"$regex": qs, "$options": "i"}},
            {"pppoe_user": {"$regex": qs, "$options": "i"}},
            {"subscriber_name": {"$regex": qs, "$options": "i"}},
            {"cto_name": {"$regex": qs, "$options": "i"}},
        ]
    items: List[Dict[str, Any]] = []
    cursor = db.cto_ports.find(filt, {"_id": 0}).limit(min(limit, 500))
    async for it in cursor:
        items.append(it)
    return {"items": items, "count": len(items)}


@router.get("/stats")
async def stats(
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "auditor")),
):
    """Contagens agregadas. Útil para dashboard."""
    cid = _user_company(user)
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    out = {"free": 0, "occupied": 0, "defective": 0, "total": 0}
    async for r in db.cto_ports.aggregate(pipe):
        out[r["_id"]] = r["count"]
        out["total"] += r["count"]
    out["occupancy_rate"] = (round((out["occupied"] / out["total"]) * 100, 1)
                              if out["total"] else 0)
    return out


@router.get("/by-cto/{cto_id}")
async def by_cto(
    cto_id: str,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "auditor",
                                          "tecnico", "supervisor")),
):
    cid = _user_company(user)
    items = []
    cursor = db.cto_ports.find(
        {"company_id": cid, "cto_id": cto_id},
        {"_id": 0}).sort("port_number", 1)
    async for it in cursor:
        items.append(it)
    if not items:
        # Auto-sync se a CTO existe mas a base ainda não foi populada
        synced = await sync_cto_all_ports(cid, cto_id)
        if synced:
            cursor = db.cto_ports.find(
                {"company_id": cid, "cto_id": cto_id},
                {"_id": 0}).sort("port_number", 1)
            async for it in cursor:
                items.append(it)
    return {"cto_id": cto_id, "items": items}


@router.get("/by-subscriber/{subscriber_id}")
async def by_subscriber(
    subscriber_id: str,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "auditor",
                                          "tecnico", "supervisor")),
):
    """Porta atual do assinante (ocupada). Retorna 404 se não tem porta."""
    cid = _user_company(user)
    doc = await db.cto_ports.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id,
         "status": "occupied"},
        {"_id": 0},
    )
    if not doc:
        return {"subscriber_id": subscriber_id, "port": None}
    return {"subscriber_id": subscriber_id, "port": doc}


class SyncBody(BaseModel):
    cto_id: Optional[str] = None  # se informado, sync só dessa CTO


class BackfillBody(BaseModel):
    dry_run: bool = True
    overwrite_occupied: bool = False  # se True, força mesmo se porta ocupada


@router.post("/backfill-from-subscribers")
async def backfill_from_subscribers(
    body: Optional[BackfillBody] = None,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede")),
):
    """iter182 — Sync inteligente: varre subscribers ATIVOS com
    `cto_port` (legado) e popula a Base de Portas se a porta estiver
    livre. Idempotente, retorna preview em dry_run=True.

    Heurística:
    - Filtra subs ATIVO/BLOQUEADO/SUSPENSO/INADIMPLENTE com `cto_port`
      e `cto_id` (ou `cto_name`) populado
    - Para cada um, localiza a CTO real em `ctos`
    - Confere se a porta indicada está livre (ou força com
      overwrite_occupied=True)
    - Vincula via _occupy_cto_port-like (escreve em ctos.ports[]
      + sync pra cto_ports)
    """
    cid = _user_company(user)
    body = body or BackfillBody()
    summary = {
        "scanned": 0,
        "linked": 0,
        "skipped_no_cto": 0,
        "skipped_no_port": 0,
        "skipped_port_occupied": 0,
        "skipped_port_not_found": 0,
        "samples": [],
    }
    cursor = db.subscribers.find(
        {"company_id": cid,
         "status": {"$in": ["ATIVO", "BLOQUEADO", "SUSPENSO",
                              "INADIMPLENTE"]},
         "cto_port": {"$nin": [None, "", 0]}},
        {"_id": 0, "id": 1, "name": 1, "cto_port": 1, "cto_id": 1,
         "cto_name": 1, "pppoe_user": 1, "phone": 1},
    )
    async for sub in cursor:
        summary["scanned"] += 1
        cto_port = sub.get("cto_port")
        try:
            cto_port = int(cto_port)
        except (TypeError, ValueError):
            summary["skipped_no_port"] += 1
            continue
        # Localiza a CTO por id ou name
        cto = None
        if sub.get("cto_id"):
            cto = await db.ctos.find_one(
                {"id": sub["cto_id"], "company_id": cid},
                {"_id": 0, "id": 1, "name": 1, "ports": 1},
            )
        if not cto and sub.get("cto_name"):
            cto = await db.ctos.find_one(
                {"name": sub["cto_name"], "company_id": cid},
                {"_id": 0, "id": 1, "name": 1, "ports": 1},
            )
        if not cto:
            summary["skipped_no_cto"] += 1
            continue
        # Localiza a porta
        target = next((p for p in (cto.get("ports") or [])
                        if int(p.get("number") or 0) == cto_port), None)
        if not target:
            summary["skipped_port_not_found"] += 1
            continue
        # Já tem cliente diferente?
        cur_sid = (target.get("client_subscriber_id") or "").strip()
        if cur_sid and cur_sid != sub["id"]:
            if not body.overwrite_occupied:
                summary["skipped_port_occupied"] += 1
                continue
        if cur_sid == sub["id"]:
            # já vinculado — só re-sync
            if not body.dry_run:
                await sync_port_from_cto(cid, cto["id"], cto_port)
            continue
        if body.dry_run:
            summary["linked"] += 1
            if len(summary["samples"]) < 20:
                summary["samples"].append({
                    "subscriber_name": sub.get("name"),
                    "pppoe_user": sub.get("pppoe_user"),
                    "cto_name": cto.get("name"),
                    "port_number": cto_port,
                })
            continue
        # Faz o link real (cuidadoso — segue mesmo padrão do _occupy)
        await db.ctos.update_one(
            {"id": cto["id"], "company_id": cid,
             "ports.number": cto_port},
            {"$set": {
                "ports.$.status": "occupied",
                "ports.$.client_subscriber_id": sub["id"],
                "ports.$.client_pppoe": sub.get("pppoe_user"),
                "ports.$.client_name": sub.get("name"),
                "ports.$.client_phone": sub.get("phone"),
                "ports.$.linked_at": now_iso(),
                "ports.$.linked_by_user_email": user.get("email"),
                "ports.$.linked_via": "backfill_subscribers",
                "updated_at": now_iso(),
            }},
        )
        await sync_port_from_cto(cid, cto["id"], cto_port)
        summary["linked"] += 1
        if len(summary["samples"]) < 20:
            summary["samples"].append({
                "subscriber_name": sub.get("name"),
                "pppoe_user": sub.get("pppoe_user"),
                "cto_name": cto.get("name"),
                "port_number": cto_port,
            })
    logger.info(
        "[cto-ports] backfill cid=%s dry=%s linked=%s scanned=%s",
        cid, body.dry_run, summary["linked"], summary["scanned"])
    return {"ok": True, "dry_run": body.dry_run, **summary}


@router.post("/sync")
async def sync_all(
    body: Optional[SyncBody] = None,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede")),
):
    """Re-sincroniza toda a base (ou uma CTO específica) a partir do
    source-of-truth `ctos.ports[]`. Idempotente."""
    cid = _user_company(user)
    body = body or SyncBody()
    if body.cto_id:
        n = await sync_cto_all_ports(cid, body.cto_id)
        return {"ok": True, "cto_id": body.cto_id, "ports_synced": n}
    # Sync TUDO
    total_ctos = 0
    total_ports = 0
    cursor = db.ctos.find({"company_id": cid}, {"_id": 0, "id": 1})
    async for c in cursor:
        n = await sync_cto_all_ports(cid, c["id"])
        if n > 0:
            total_ctos += 1
            total_ports += n
    logger.info("[cto-ports] sync_all cid=%s ctos=%s ports=%s",
                  cid, total_ctos, total_ports)
    return {"ok": True, "ctos_synced": total_ctos,
              "ports_synced": total_ports}


# ---------------------------------------------------------------------------
# DESTRUCTIVE ACTIONS — release port, delete CTO
# ---------------------------------------------------------------------------

class ReleasePortBody(BaseModel):
    reason: Optional[str] = "manual_admin"


@router.post("/{cto_id}/port/{port_number}/release")
async def release_port(
    cto_id: str, port_number: int,
    body: Optional[ReleasePortBody] = None,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede")),
):
    """Libera (desvincula) o cliente de uma porta específica."""
    cid = _user_company(user)
    body = body or ReleasePortBody()
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": cid},
        {"_id": 0, "ports": 1, "name": 1},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    target = next((p for p in (cto.get("ports") or [])
                    if int(p.get("number") or 0) == int(port_number)), None)
    if not target:
        raise HTTPException(404, f"Porta {port_number} não existe")
    client_id = target.get("client_subscriber_id")
    client_name = target.get("client_name")
    await db.ctos.update_one(
        {"id": cto_id, "company_id": cid, "ports.number": port_number},
        {"$set": {
            "ports.$.status": "free",
            "ports.$.client_subscriber_id": None,
            "ports.$.client_pppoe": None,
            "ports.$.client_name": None,
            "ports.$.client_phone": None,
            "ports.$.released_at": now_iso(),
            "ports.$.released_by_email": user.get("email"),
            "ports.$.release_reason": body.reason or "manual_admin",
            "updated_at": now_iso(),
        }},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "cto.updated",
            company_id=cid,
            source="cto_ports_base",
            payload={},
        )
    except Exception:
        pass
    await sync_port_from_cto(cid, cto_id, port_number)
    logger.info(
        "[cto-ports] port released cid=%s cto=%s p=%s by=%s reason=%s",
        cid, cto_id, port_number, user.get("email"), body.reason)
    return {
        "ok": True, "cto_id": cto_id, "port_number": port_number,
        "previous_client_id": client_id,
        "previous_client_name": client_name,
    }


@router.post("/cto/{cto_id}/release-all")
async def release_all_ports(
    cto_id: str,
    body: Optional[ReleasePortBody] = None,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """iter182 — Libera TODAS as portas ocupadas de uma CTO de uma vez.

    Útil pra migração de provedor / desativação de CTO inteira. Operação
    atômica em loop, retorna lista de portas liberadas.
    Restrita a administrador/gestor (mais que release single).
    """
    cid = _user_company(user)
    body = body or ReleasePortBody()
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": cid},
        {"_id": 0, "ports": 1, "name": 1},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    occupied = [p for p in (cto.get("ports") or [])
                if (p.get("client_subscriber_id") or "").strip()]
    released = []
    for p in occupied:
        n = int(p.get("number") or 0)
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid, "ports.number": n},
            {"$set": {
                "ports.$.status": "free",
                "ports.$.client_subscriber_id": None,
                "ports.$.client_pppoe": None,
                "ports.$.client_name": None,
                "ports.$.client_phone": None,
                "ports.$.released_at": now_iso(),
                "ports.$.released_by_email": user.get("email"),
                "ports.$.release_reason": body.reason or "bulk_release",
                "updated_at": now_iso(),
            }},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "cto.updated",
                company_id=cid,
                source="cto_ports_base",
                payload={},
            )
        except Exception:
            pass
        await sync_port_from_cto(cid, cto_id, n)
        released.append({
            "port_number": n,
            "previous_client_id": p.get("client_subscriber_id"),
            "previous_client_name": p.get("client_name"),
        })
    logger.warning(
        "[cto-ports] BULK release cid=%s cto=%s ports=%s by=%s reason=%s",
        cid, cto_id, len(released), user.get("email"), body.reason)
    return {
        "ok": True, "cto_id": cto_id, "cto_name": cto.get("name"),
        "released_count": len(released), "released": released,
    }


@router.delete("/cto/{cto_id}")
async def delete_cto(
    cto_id: str,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Apaga uma CTO inteira (e em cascata, suas portas da base
    denormalizada). Restrita a administrador/gestor por destrutividade.

    Bloqueia se a CTO tiver portas OCUPADAS (libere antes via
    /port/N/release).
    """
    cid = _user_company(user)
    cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": cid},
        {"_id": 0, "name": 1, "ports": 1},
    )
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    occupied = [int(p.get("number") or 0)
                for p in (cto.get("ports") or [])
                if (p.get("client_subscriber_id") or "").strip()]
    if occupied:
        raise HTTPException(
            409,
            f"CTO {cto.get('name') or cto_id} tem {len(occupied)} porta(s)"
            f" ocupada(s) ({', '.join(map(str, occupied[:5]))}"
            f"{'...' if len(occupied) > 5 else ''}). Libere antes.",
        )
    # 1) Apaga CTO
    await db.ctos.delete_one({"id": cto_id, "company_id": cid})
    # 2) Apaga portas denormalizadas
    delp = await db.cto_ports.delete_many(
        {"cto_id": cto_id, "company_id": cid})
    logger.info(
        "[cto-ports] CTO deleted cid=%s cto=%s name=%s ports=%s by=%s",
        cid, cto_id, cto.get("name"), delp.deleted_count, user.get("email"))
    return {
        "ok": True, "cto_id": cto_id, "cto_name": cto.get("name"),
        "ports_deleted": delp.deleted_count,
    }


@router.on_event("startup")
async def _ensure_indexes():
    """Cria índices necessários no startup."""
    try:
        await db.cto_ports.create_index("id", unique=True)
        await db.cto_ports.create_index([("company_id", 1), ("status", 1)])
        await db.cto_ports.create_index([("company_id", 1), ("cto_id", 1),
                                            ("port_number", 1)])
        await db.cto_ports.create_index([("company_id", 1),
                                            ("subscriber_id", 1)])
        await db.cto_ports.create_index([("company_id", 1), ("mac", 1)])
        logger.info("[cto-ports] indexes ensured")
    except Exception as e:
        logger.warning("[cto-ports] index error: %s", e)
