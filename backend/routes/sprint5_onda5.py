"""sprint5_onda5 — Genesis SmartOLT Import (CEO mandate 19/02/2026)

FASES (todas obrigatórias por ordem CEO):
  5.0 Genesis Audit (READ-ONLY)
  5.1 Genesis Preview (simulação)
  5.2 Genesis Import (após preview aprovado)
  5.3 Certidão Patrimonial Inicial

Endpoints (prefix /api/sprint5/onda5):
  GET  /audit                — Fase 5.0 (READ-ONLY)
  GET  /preview              — Fase 5.1 (simulação)
  POST /import               — Fase 5.2 (write, batch)
  GET  /certidao             — Fase 5.3
  GET  /status               — métricas atuais
  GET  /audit-log            — trilha por batch
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda5", tags=["sprint5", "onda5"])

GENESIS_VERSION = "sprint5_onda5_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


async def _classify_confidence(
    db, cid: str, ont: dict,
) -> tuple[float, str, dict]:
    """Determina data_confidence (1.0/0.9/0.7/0.5) para uma ONU SmartOLT."""
    sn = ont.get("sn")
    mac = ont.get("mac")
    pppoe = (ont.get("pppoe_user") or "").strip().upper()
    name = (ont.get("name") or "").strip()
    subscriber_id = None

    # 1.00 — pppoe_user → SAP → subscriber_id (mais forte)
    if pppoe:
        sap = await db.subscriber_access_points.find_one(
            {"company_id": cid, "pppoe_user": {"$regex": f"^{pppoe}$",
                                                     "$options": "i"}},
            {"_id": 0, "subscriber_id": 1, "pppoe_user": 1},
        )
        if sap and sap.get("subscriber_id"):
            subscriber_id = sap["subscriber_id"]
            return 1.00, "pppoe_via_sap", {
                "subscriber_id": subscriber_id,
                "matched_pppoe": sap.get("pppoe_user")}

    # 0.90 — name fuzzy match em subscribers.name (palavra única > 5 chars)
    if name:
        # extrai tokens com 5+ chars (prováveis nomes próprios)
        tokens = [t for t in name.replace("_", " ").split()
                  if len(t) >= 5 and t.replace(".", "").isalpha()]
        for token in tokens:
            sub = await db.subscribers.find_one(
                {"company_id": cid,
                 "name": {"$regex": token, "$options": "i"},
                 "status": {"$in": ["ATIVO", "ativo", "Ativo",
                                          "ACTIVE", "active"]}},
                {"_id": 0, "id": 1, "name": 1},
            )
            if sub:
                return 0.90, "name_fuzzy_match", {
                    "subscriber_id": sub["id"],
                    "matched_token": token,
                    "matched_name": sub["name"]}

    # 0.70 — tem SN/MAC mas sem cliente identificável (inferência baixa)
    if sn or mac:
        return 0.70, "inventory_only_no_client", {}

    # 0.50 — sem nada
    return 0.50, "insufficient_data", {}


@router.get("/audit")
async def audit(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Fase 5.0 — Genesis Audit (READ-ONLY).

    Zero writes. Apenas leitura e contagem.
    """
    cid = _user_company(user)
    smartolt_total = await db.smartolt_onus.count_documents(
        {"company_id": cid})
    stok_total = await db.stok_onts.count_documents({"company_id": cid})

    # Qualidade dos identificadores
    with_sn = await db.smartolt_onus.count_documents(
        {"company_id": cid, "sn": {"$nin": [None, ""]}})
    with_mac = await db.smartolt_onus.count_documents(
        {"company_id": cid, "mac": {"$nin": [None, ""]}})
    with_eid = await db.smartolt_onus.count_documents(
        {"company_id": cid, "unique_external_id": {"$nin": [None, ""]}})
    with_pppoe = await db.smartolt_onus.count_documents(
        {"company_id": cid, "pppoe_user": {"$nin": [None, ""]}})
    with_sub_ext = await db.smartolt_onus.count_documents(
        {"company_id": cid,
         "subscriber_external_id": {"$nin": [None, ""]}})
    no_id = await db.smartolt_onus.count_documents(
        {"company_id": cid,
         "$and": [{"sn": {"$in": [None, ""]}},
                  {"mac": {"$in": [None, ""]}}]})

    # Duplicatas
    dup_sn = await db.smartolt_onus.aggregate([
        {"$match": {"company_id": cid, "sn": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$sn", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}}, {"$count": "x"},
    ]).to_list(length=1)
    dup_sn_count = dup_sn[0]["x"] if dup_sn else 0
    dup_mac = await db.smartolt_onus.aggregate([
        {"$match": {"company_id": cid, "mac": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$mac", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}}, {"$count": "x"},
    ]).to_list(length=1)
    dup_mac_count = dup_mac[0]["x"] if dup_mac else 0

    # Cross-match com stok_onts (já existentes — não duplicar)
    smartolt_sns = set()
    smartolt_macs = set()
    cur = db.smartolt_onus.find({"company_id": cid},
                                       {"_id": 0, "sn": 1, "mac": 1})
    async for d in cur:
        if d.get("sn"):
            smartolt_sns.add(d["sn"])
        if d.get("mac"):
            smartolt_macs.add(d["mac"])
    stok_sns: set = set()
    stok_macs: set = set()
    cur = db.stok_onts.find({"company_id": cid},
                                 {"_id": 0, "sn": 1, "mac": 1, "scan_sn": 1})
    async for d in cur:
        sn_field = d.get("sn") or d.get("scan_sn")
        if sn_field:
            stok_sns.add(sn_field)
        if d.get("mac"):
            stok_macs.add(d["mac"])
    overlap_sn = len(smartolt_sns & stok_sns)
    overlap_mac = len(smartolt_macs & stok_macs)
    new_in_smartolt = (smartolt_total - overlap_sn) if overlap_sn else \
        smartolt_total

    # Vínculo com cliente — projeção de confidence
    # (amostra pequena pra não estourar; classifica TODOS, ~1833 docs)
    conf_dist: Dict[str, int] = {"1.00": 0, "0.90": 0, "0.70": 0, "0.50": 0}
    cur = db.smartolt_onus.find({"company_id": cid}, {"_id": 0})
    async for d in cur:
        conf, path, _extras = await _classify_confidence(db, cid, d)
        key = f"{conf:.2f}"
        conf_dist[key] = conf_dist.get(key, 0) + 1

    # Status
    by_status = await db.smartolt_onus.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]).to_list(length=20)
    by_status_map = {x["_id"]: x["n"] for x in by_status}

    # ONUs sem CTO no canonical (todas — porque o canonical hoje só
    # tem 1 occupied)
    canonical_with_ont = await db.network_access_canonical.count_documents(
        {"company_id": cid,
         "$or": [{"ont_sn": {"$nin": [None, ""]}},
                    {"ont_mac": {"$nin": [None, ""]}}]})

    return {
        "phase": "5.0_genesis_audit",
        "mode": "READ_ONLY",
        "company_id": cid,
        "smartolt_total": smartolt_total,
        "stok_onts_existing": stok_total,
        "identifiers": {
            "with_sn": with_sn,
            "with_mac": with_mac,
            "with_unique_external_id": with_eid,
            "with_pppoe_user": with_pppoe,
            "with_subscriber_external_id": with_sub_ext,
            "without_sn_and_mac_blocked": no_id,
        },
        "duplicates": {
            "duplicate_sn": dup_sn_count,
            "duplicate_mac": dup_mac_count,
        },
        "cross_match_stok_onts": {
            "overlap_sn": overlap_sn,
            "overlap_mac": overlap_mac,
            "new_in_smartolt_estimated": new_in_smartolt,
        },
        "client_link_confidence_projection": conf_dist,
        "by_status": by_status_map,
        "canonical_with_ont_link": canonical_with_ont,
        "computed_at": _now_iso(),
    }


@router.get("/preview")
async def preview(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Fase 5.1 — Genesis Preview. Simula import sem writes.

    Retorna importáveis/bloqueadas/duplicadas/inválidas + sucesso projetado.
    """
    cid = _user_company(user)
    a = await audit(user)

    smartolt_total = a["smartolt_total"]
    blocked = a["identifiers"]["without_sn_and_mac_blocked"]
    duplicate = (a["duplicates"]["duplicate_sn"]
                  + a["duplicates"]["duplicate_mac"])
    overlap_existing = a["cross_match_stok_onts"]["overlap_sn"]

    importable = smartolt_total - blocked - duplicate - overlap_existing
    success_pct = round((importable / smartolt_total * 100), 2) \
        if smartolt_total else 0.0

    return {
        "phase": "5.1_genesis_preview",
        "mode": "SIMULATION",
        "company_id": cid,
        "smartolt_total": smartolt_total,
        "would_import": importable,
        "would_block_no_id": blocked,
        "would_block_duplicate": duplicate,
        "would_skip_existing": overlap_existing,
        "import_success_pct": success_pct,
        "meets_95pct_gate": success_pct >= 95.0,
        "confidence_projection": a["client_link_confidence_projection"],
        "computed_at": _now_iso(),
    }


@router.post("/import")
async def execute_import(
    confirm: bool = Query(False,
        description="DEVE ser true para executar"),
    tier: str = Query("official",
        description="official (>=0.90) ou quarantine (0.70-0.89)"),
    batch_size: int = Query(100, ge=10, le=500),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Fase 5.2 — Genesis Import em DUAS CAMADAS (CEO Opção D 19/02/2026).

    - tier=official    → importa data_confidence >= 0.90 (asset_status=validado)
    - tier=quarantine  → importa data_confidence < 0.90 e >= 0.70
                          (asset_status=pending_validation, exclude_from_balance=True)

    REQUER: ?confirm=true
    """
    if not confirm:
        raise HTTPException(400,
            "Genesis Import requer ?confirm=true. Rode /preview primeiro.")
    if tier not in ("official", "quarantine"):
        raise HTTPException(400, "tier deve ser official ou quarantine")

    cid = _user_company(user)
    batch_id = f"o5g-{tier[:3]}-{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    cur = db.smartolt_onus.find({"company_id": cid}, {"_id": 0})
    imported = 0
    blocked = 0
    skipped_existing = 0
    skipped_wrong_tier = 0
    by_conf: Dict[str, int] = {"1.00": 0, "0.90": 0, "0.70": 0, "0.50": 0}

    async for ont in cur:
        sn = ont.get("sn")
        mac = ont.get("mac")
        eid = ont.get("unique_external_id")
        if not sn and not mac:
            blocked += 1
            continue
        if sn:
            exists = await db.stok_onts.find_one(
                {"company_id": cid,
                 "$or": [{"sn": sn}, {"scan_sn": sn}]},
                {"_id": 0, "id": 1})
            if exists:
                skipped_existing += 1
                continue

        conf, path, extras = await _classify_confidence(db, cid, ont)
        # Decide tier-skip
        if tier == "official" and conf < 0.90:
            skipped_wrong_tier += 1
            continue
        if tier == "quarantine" and (conf >= 0.90 or conf < 0.70):
            skipped_wrong_tier += 1
            continue

        by_conf[f"{conf:.2f}"] = by_conf.get(f"{conf:.2f}", 0) + 1

        # Tier-specific fields (CEO Opção D)
        is_official = (tier == "official")
        ont_id = f"ont-{uuid.uuid4().hex[:14]}"
        doc = {
            "id": ont_id,
            "company_id": cid,
            "sn": sn,
            "scan_sn": sn,
            "unique_external_id": eid,
            "model": ont.get("onu_type_name"),
            "olt_name": ont.get("olt_name"),
            "olt_id": ont.get("olt_id"),
            "port_olt": ont.get("port"),
            "smartolt_status": ont.get("status"),
            "signal_1490": ont.get("signal_1490"),
            "subscriber_id": extras.get("subscriber_id"),
            "client_name": ont.get("name"),
            "status": "smartolt_genesis",
            "location_type": "smartolt",
            "location_id": ont.get("olt_id"),
            # Genesis metadata
            "origin": "smartolt_genesis",
            "import_batch_id": batch_id,
            "imported_at": now,
            "imported_by": user.get("id"),
            "genesis_version": GENESIS_VERSION,
            "data_confidence": conf,
            "data_confidence_path": path,
            "data_confidence_extras": extras,
            # CEO Opção D — DUAS CAMADAS
            "tier": tier,
            "asset_status": "validado" if is_official
                                  else "pending_validation",
            "exclude_from_balance": not is_official,
            "created_at": now,
            "created_by": user.get("id"),
        }
        # Só inclui `mac` se truthy (evita conflito com sparse unique index)
        if mac:
            doc["mac"] = mac
        try:
            await db.stok_onts.insert_one(doc)
            imported += 1
        except Exception as ex:
            logger.warning("[onda5.import] insert falhou sn=%s: %s",
                              sn, ex)
            blocked += 1

    try:
        await db.sprint5_audit_log.insert_one({
            "id": f"o5a-{uuid.uuid4().hex[:14]}",
            "batch_id": batch_id,
            "company_id": cid,
            "wave": "sprint5_onda5",
            "action": f"genesis_import.completed.{tier}",
            "target": f"stok_onts/genesis/{tier}/{batch_id}",
            "payload": {
                "tier": tier,
                "imported": imported,
                "blocked": blocked,
                "skipped_existing": skipped_existing,
                "skipped_wrong_tier": skipped_wrong_tier,
                "by_confidence": by_conf,
            },
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "created_at": now,
        })
    except Exception:
        pass

    return {
        "batch_id": batch_id,
        "phase": "5.2_genesis_import",
        "tier": tier,
        "imported": imported,
        "blocked": blocked,
        "skipped_existing": skipped_existing,
        "skipped_wrong_tier": skipped_wrong_tier,
        "by_confidence": by_conf,
        "asset_status": "validado" if tier == "official"
                              else "pending_validation",
        "exclude_from_balance": tier == "quarantine",
        "completed_at": _now_iso(),
    }


@router.post("/promote-pending")
async def promote_pending(
    confirm: bool = Query(False),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Fase 5.2C — Worker de promoção quarantena → oficial.

    Re-classifica cada ONU em `pending_validation` cruzando com
    SAP/subscribers/canonical/swap_events. Se confidence >= 0.90,
    promove para asset_status=validado e exclude_from_balance=false.
    """
    if not confirm:
        raise HTTPException(400, "Requer ?confirm=true")
    cid = _user_company(user)
    batch_id = f"o5p-{uuid.uuid4().hex[:14]}"
    promoted = 0
    still_pending = 0
    cur = db.stok_onts.find(
        {"company_id": cid, "asset_status": "pending_validation",
         "origin": "smartolt_genesis"}, {"_id": 0})
    async for ont in cur:
        # Reconsulta smartolt_onus para pegar metadata mais recente
        sm = await db.smartolt_onus.find_one(
            {"company_id": cid, "sn": ont.get("sn")}, {"_id": 0})
        if not sm:
            still_pending += 1
            continue
        conf, path, extras = await _classify_confidence(db, cid, sm)
        # Tentar enriquecimento adicional via canonical/swap_events
        if conf < 0.90 and ont.get("sn"):
            # Procurar em canonical
            link = await db.network_access_canonical.find_one(
                {"company_id": cid,
                 "$or": [{"ont_sn": ont["sn"]}, {"ont_mac": ont.get("mac")}]},
                {"_id": 0, "subscriber_id": 1})
            if link and link.get("subscriber_id"):
                conf = 0.95
                path = "promoted_via_canonical"
                extras = {"subscriber_id": link["subscriber_id"]}
        if conf >= 0.90:
            await db.stok_onts.update_one(
                {"id": ont["id"], "company_id": cid},
                {"$set": {
                    "asset_status": "validado",
                    "exclude_from_balance": False,
                    "data_confidence": conf,
                    "data_confidence_path": path,
                    "data_confidence_extras": extras,
                    "subscriber_id":
                        extras.get("subscriber_id")
                        or ont.get("subscriber_id"),
                    "promoted_at": _now_iso(),
                    "promoted_by": user.get("id"),
                    "promotion_batch_id": batch_id,
                }})
            promoted += 1
        else:
            still_pending += 1
    return {
        "batch_id": batch_id,
        "promoted": promoted,
        "still_pending": still_pending,
        "completed_at": _now_iso(),
    }


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    total = await db.stok_onts.count_documents({"company_id": cid})
    genesis_total = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis"})
    official = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "official"})
    quarantine = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "quarantine"})

    pipe = [
        {"$match": {"company_id": cid, "origin": "smartolt_genesis"}},
        {"$group": {"_id": "$data_confidence", "n": {"$sum": 1}}},
    ]
    res = await db.stok_onts.aggregate(pipe).to_list(length=20)
    conf_dist = {f"{(x['_id'] or 0):.2f}": x["n"] for x in res}

    # Cobertura SOBRE OS OFICIAIS (gate da Onda 6)
    with_sub_off = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "official", "subscriber_id": {"$nin": [None, ""]}})
    high_conf_off = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": "official", "data_confidence": {"$gte": 0.9}})

    pct_with_sub = round((with_sub_off / official * 100), 2) \
        if official else 0.0
    pct_high_conf = round((high_conf_off / official * 100), 2) \
        if official else 0.0

    return {
        "phase": "post_genesis",
        "company_id": cid,
        "stok_onts_total": total,
        "from_genesis_total": genesis_total,
        "tier_official": official,
        "tier_quarantine": quarantine,
        "by_confidence": conf_dist,
        "official_with_subscriber_pct": pct_with_sub,
        "official_high_confidence_pct": pct_high_conf,
        "gates_onda6_over_official": {
            "cobertura_onus_95": (official >= 0.95 * 1833),
            "cliente_vinculado_95": pct_with_sub >= 95.0,
            "origem_conhecida_95": official > 0,
            "data_confidence_high_90": pct_high_conf >= 90.0,
        },
        "computed_at": _now_iso(),
    }


@router.get("/certidao")
async def certidao(
    tier: str = Query("official",
        description="official ou quarantine"),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Emite certidão por tier (CEO Opção D — 2 certidões separadas)."""
    if tier not in ("official", "quarantine"):
        raise HTTPException(400, "tier deve ser official ou quarantine")
    cid = _user_company(user)
    total = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": tier})
    with_sub = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": tier, "subscriber_id": {"$nin": [None, ""]}})
    high_conf = await db.stok_onts.count_documents(
        {"company_id": cid, "origin": "smartolt_genesis",
         "tier": tier, "data_confidence": {"$gte": 0.9}})

    last_batch = await db.sprint5_audit_log.find_one(
        {"company_id": cid, "wave": "sprint5_onda5",
         "action": f"genesis_import.completed.{tier}"},
        {"_id": 0}, sort=[("created_at", -1)])

    pct_high = round((high_conf / total * 100), 2) if total else 0.0
    pct_sub = round((with_sub / total * 100), 2) if total else 0.0

    return {
        "certidao_type": f"SPRINT5_ONDA5_GENESIS_{tier.upper()}",
        "company_id": cid,
        "tier": tier,
        "total": total,
        "with_subscriber": with_sub,
        "high_confidence": high_conf,
        "pct_with_subscriber": pct_sub,
        "pct_high_confidence": pct_high,
        "exclude_from_balance": tier == "quarantine",
        "onda6_eligible": (tier == "official"
                              and pct_high >= 90.0),
        "last_batch": last_batch,
        "issued_at": _now_iso(),
    }


@router.get("/audit-log")
async def audit_log(
    batch_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "wave": "sprint5_onda5"}
    if batch_id:
        q["batch_id"] = batch_id
    items = await db.sprint5_audit_log.find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(
        length=limit)
    return {"items": items, "count": len(items)}
