"""ONT Label Scanner — Claude Sonnet 4.6 vision lê MAC/SN da etiqueta.

Fluxo:
- Técnico tira foto da etiqueta da ONT (no momento de finalizar uma OS de
  retirada).
- Frontend envia o base64 da imagem para `/api/stok/retirada/scan-ont`
- Backend chama Claude Sonnet 4.6 (via Emergent LLM key) com a imagem +
  prompt forte de OCR pedindo SOMENTE o MAC e o SN (sem texto adicional).
- Resposta JSON: `{mac, sn, raw, confidence}`
- O frontend confirma com o técnico e envia esses dados ao finalizar a OS.
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import binascii
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, get_current_user, now_iso
from database import db

logger = logging.getLogger("ponto.ont_scan")
router = APIRouter(prefix="/api/stok/retirada", tags=["ont-scan"])


class ScanIn(BaseModel):
    image_base64: str = Field(..., min_length=100,
                                 description="Imagem PNG/JPEG em base64 (sem prefixo data:)")
    hint: Optional[str] = None  # ex: "ONT modelo Huawei HG6145"


_PROMPT = """Você é um leitor especialista de etiquetas de ONTs/ONUs (equipamentos de fibra óptica).

Recebeu uma foto da etiqueta. Extraia APENAS estes 2 campos:

1. MAC — endereço físico, 12 caracteres hex, normalmente impresso como
   "MAC: XX:XX:XX:XX:XX:XX" ou "XX-XX-XX-XX-XX-XX" ou contínuo "XXXXXXXXXXXX"
2. SN  — serial number, normalmente "S/N", "SN", "Serial No.", começando
   com letras do fabricante (ex: HWTC, ZTEG, FHTT, NOKxxxx) seguidas
   por hex/alfanuméricos

Devolva SOMENTE um JSON válido, sem markdown, sem ```, sem explicação:

{"mac":"AA:BB:CC:DD:EE:FF","sn":"HWTC12345678","confidence":0.92}

Regras:
- Se NÃO conseguir ler com clareza, devolva o campo como string vazia ""
- MAC deve sempre ter 12 hex chars; formate com ":" maiúsculo
- SN preserve exatamente como na etiqueta (com letras maiúsculas)
- confidence: 0.0 a 1.0 (sua certeza geral)
- NUNCA invente. Se borrado/ilegível, retorne "" e confidence baixa.
"""


def _normalize_mac(raw: str) -> str:
    """Normaliza MAC para AA:BB:CC:DD:EE:FF."""
    if not raw:
        return ""
    s = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if len(s) != 12:
        return ""
    return ":".join(s[i:i+2].upper() for i in range(0, 12, 2))


def _clean_sn(raw: str) -> str:
    """Mantém apenas alfanuméricos, maiúsculas."""
    if not raw:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()[:32]


def _parse_json_loose(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.M)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


async def _do_scan_ont(payload: ScanIn) -> Dict[str, Any]:
    """Lógica compartilhada de OCR via Claude Sonnet 4.6 vision."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada")

    # Valida base64
    try:
        b64 = payload.image_base64
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, safe_detail(400, e, "Imagem base64 inválida:"))

    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
        import uuid as _uuid

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"ont-scan-{_uuid.uuid4().hex[:10]}",
            system_message=_PROMPT,
        ).with_model("anthropic", "claude-sonnet-4-6")

        msg_text = "Leia o MAC e o SN desta etiqueta de ONT."
        if payload.hint:
            msg_text += f" (Dica: {payload.hint[:80]})"

        msg = UserMessage(
            text=msg_text,
            file_contents=[ImageContent(image_base64=b64)],
        )
        raw_resp = await chat.send_message(msg)
        parsed = _parse_json_loose(raw_resp)
    except Exception as e:
        logger.exception("[ont-scan] LLM error: %s", e)
        raise HTTPException(502, safe_detail(502, e, "Falha na leitura IA:"))

    mac = _normalize_mac(parsed.get("mac") or "")
    sn = _clean_sn(parsed.get("sn") or "")
    confidence = parsed.get("confidence")
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = 0.0

    ok = bool(mac or sn)
    return {
        "ok": ok,
        "mac": mac,
        "sn": sn,
        "confidence": confidence,
        "raw": raw_resp[:500] if isinstance(raw_resp, str) else None,
    }


@router.post("/scan-ont")
async def scan_ont_label(payload: ScanIn,
                            user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """OCR da etiqueta da ONT via Claude Sonnet 4.6 vision (autenticado)."""
    return await _do_scan_ont(payload)


@router.post("/public/scan-ont")
async def public_scan_ont_label(payload: ScanIn) -> Dict[str, Any]:
    """OCR da etiqueta da ONT via Claude Sonnet 4.6 — versão pública.

    Usado pelo app do colaborador (PWA) que autentica via session_token
    Google (`pp_collab_token`) e não tem JWT (`ponto_token`). Mesma lógica
    de OCR, sem dependência de auth — segue o padrão de
    `/api/lousa/public/ocr-sn` (que já existe para o mesmo público).
    Não grava nada no DB; é puramente leitura de imagem.
    """
    return await _do_scan_ont(payload)


# ---------------------------------------------------------------------------
# Batch commit — várias ONTs lidas pela IA em lote
# ---------------------------------------------------------------------------
class BatchItem(BaseModel):
    mac: str = ""
    sn: str = ""
    confidence: Optional[float] = 0
    image_base64: Optional[str] = None  # foto-prova (opcional)
    model: Optional[str] = "Desconhecido"


class BatchIn(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=50)
    technician_id: Optional[str] = None  # default = self
    reason: Optional[str] = "Retirada em massa via Scan IA"


@router.post("/scan-batch-commit")
async def scan_batch_commit(payload: BatchIn,
                                user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Recebe N ONTs já lidas pela IA e adiciona TODAS ao estoque do técnico.

    Cria/atualiza docs em `stok_onts` com:
      - location_type='tecnico'
      - location_id=technician_id (ou self)
      - status='retirada_com_tecnico'
      - source='ai_scan_batch'
      - scan_confidence=float

    Idempotente por MAC: se o MAC já existe, faz move (preservando histórico).
    Se MAC vazio mas SN preenchido, usa SN como chave única.

    Onda 2.9 — para cada ONT já cadastrada, a movimentação para o estoque
    do técnico passa OBRIGATORIAMENTE por `transfer_engine.execute_transfer`
    (chokepoint canônico). ONTs novas (genesis) ainda entram via
    `insert_one` direto — coberto pelo hook R1.4 (valuation genesis).
    """
    from services.transfer_engine import (
        execute_transfer, TransferEngineError,
    )

    cid = user.get("company_id") or DEMO_COMPANY_ID
    tech_id = payload.technician_id or user.get("collaborator_id") or user.get("id")
    if not tech_id:
        raise HTTPException(400, "technician_id não informado e usuário não tem collaborator_id")

    created, moved, skipped = [], [], []
    for it in payload.items:
        mac = (it.mac or "").strip().upper()
        sn = (it.sn or "").strip().upper()
        if not mac and not sn:
            skipped.append({"reason": "sem MAC nem SN"})
            continue

        # Procura por MAC primeiro, depois por SN
        existing = None
        if mac:
            existing = await db.stok_onts.find_one(
                {"company_id": cid, "mac": mac}, {"_id": 0})
        if not existing and sn:
            existing = await db.stok_onts.find_one(
                {"company_id": cid, "scan_sn": sn}, {"_id": 0})

        if existing:
            prev_loc = existing.get("location_type")
            prev_id = existing.get("location_id")

            # Determina origin canônico. Bypass se já está com este técnico
            # (no-op idempotente).
            if prev_loc == "tecnico" and prev_id == tech_id:
                skipped.append({"mac": existing.get("mac"),
                                 "reason": "já está com este técnico (no-op)"})
                continue

            # Determina origin_type compatível com o grafo de transferências.
            if prev_loc in ("empresa", "cliente"):
                origin_type = prev_loc
                # Reason canônico do scan IA — quando vem do cliente é
                # "Retirada OS" (scan da etiqueta no local) / quando vem
                # da empresa é "Saída pra campo".
                reason_code = ("Retirada OS" if origin_type == "cliente"
                                else "Saída pra campo")
            elif prev_loc == "tecnico":
                # Transferência intra-técnico não está no grafo. Skip
                # com warning — gestor deve usar return-to-company antes.
                skipped.append({
                    "mac": existing.get("mac"),
                    "reason": (f"transição não permitida tecnico→tecnico "
                                f"(prev={prev_id}). Use return-to-company "
                                f"antes de re-atribuir."),
                })
                continue
            elif prev_loc == "defeito":
                skipped.append({
                    "mac": existing.get("mac"),
                    "reason": "ONT em defeito não pode ir direto pro técnico",
                })
                continue
            else:
                skipped.append({
                    "mac": existing.get("mac"),
                    "reason": f"location_type desconhecido: {prev_loc!r}",
                })
                continue

            try:
                tr = await execute_transfer(
                    company_id=cid,
                    origin_type=origin_type,
                    origin_id=prev_id,
                    destination_type="tecnico",
                    destination_id=tech_id,
                    actor={"id": user.get("id"),
                            "email": user.get("email"),
                            "name": user.get("name") or user.get("email"),
                            "role": user.get("role"),
                            "origin": "ai_scan_batch",
                            "physical_attendance": True},
                    reason={
                        "code": reason_code,
                        "details": (
                            (payload.reason or "Retirada via Scan IA")[:200]
                            + f" · OCR conf={float(it.confidence or 0):.2f}"
                        ),
                    },
                    mac=existing.get("mac"),
                    sn=sn or existing.get("scan_sn"),
                    manual=(origin_type == "empresa"),
                    extra_set_fields={
                        "status": "retirada_com_tecnico",
                        "source": "ai_scan_batch",
                        "scan_confidence": float(it.confidence or 0),
                        "scan_sn": sn or existing.get("scan_sn") or sn,
                        "batch_reason": (payload.reason or "")[:120],
                        "batch_committed_at": now_iso(),
                        "batch_committed_by": user.get("email"),
                    },
                )
                # Empilha history humano (audit auxiliar)
                await db.stok_onts.update_one(
                    {"company_id": cid, "mac": existing.get("mac")},
                    {"$push": {"history": {
                        "at": now_iso(),
                        "action": "batch_retirada",
                        "by": user.get("email"),
                        "transfer_audit_id": tr["movement_id"],
                    }}},
                )
                moved.append({
                    "mac": existing.get("mac"),
                    "sn": existing.get("scan_sn") or sn,
                    "transfer_audit_id": tr["movement_id"],
                    "transfer_audit_hash": tr["audit_hash"],
                    "from": {"type": prev_loc, "id": prev_id},
                })
            except TransferEngineError as e:
                skipped.append({
                    "mac": existing.get("mac"),
                    "reason": f"transfer_blocked: {e}",
                })
                logger.warning("[scan-batch-commit] transfer_engine bloqueou "
                                "%s: %s", existing.get("mac"), e)
        else:
            # Genesis — ONT nova, sem trilha anterior. Mantém insert direto
            # (será coberto por R1.4 valuation_genesis hook).
            new_doc = {
                "company_id": cid,
                "mac": mac or f"AUTOSN_{sn[:12]}",
                "model": (it.model or "Desconhecido")[:120],
                "praca_id": None,
                "warehouse_responsible_id": None,
                "purchase_id": None,
                "created_by": "ai_scan_batch",
                "created_at": now_iso(),
                "location_type": "tecnico",
                "location_id": tech_id,
                "client_name": None,
                "status": "retirada_com_tecnico",
                "source": "ai_scan_batch",
                "scan_confidence": float(it.confidence or 0),
                "scan_sn": sn,
                "batch_reason": (payload.reason or "")[:120],
                "batch_committed_at": now_iso(),
                "batch_committed_by": user.get("email"),
                "genesis_via": "ai_scan_batch",
            }
            # R1.4 — Hook valuation no genesis via scan_batch
            from services.inventory_valuation import (
                apply_valuation_to_genesis_doc,
            )
            await apply_valuation_to_genesis_doc(
                new_doc, genesis_source="scan_batch_commit")
            await db.stok_onts.insert_one(new_doc)
            created.append({"mac": new_doc["mac"], "sn": sn})

    # Log permanente do lote
    # iter172 — guarda também `onts` (MAC+SN+operação) para auditoria detalhada
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    onts_log = (
        [{"mac": x.get("mac"), "sn": x.get("sn"), "op": "created"} for x in created]
        + [{"mac": x.get("mac"), "sn": x.get("sn"), "op": "moved",
            "transfer_audit_id": x.get("transfer_audit_id")} for x in moved]
    )
    await db.stok_batch_log.insert_one({
        "id": batch_id,
        "company_id": cid,
        "at": now_iso(),
        "by_email": user.get("email"),
        "by_name": user.get("name"),
        "technician_id": tech_id,
        "reason": (payload.reason or "")[:120],
        "items_count": len(payload.items),
        "created": len(created),
        "moved": len(moved),
        "skipped": len(skipped),
        "onts": onts_log,
    })

    return {
        "ok": True,
        "technician_id": tech_id,
        "created": created,
        "moved": moved,
        "skipped": skipped,
        "total": len(created) + len(moved),
        "batch_id": batch_id,
    }


# ---------------------------------------------------------------------------
# Histórico de lotes (admin) — listagem + PDF
# ---------------------------------------------------------------------------
@router.get("/batch-history")
async def batch_history(technician_id: Optional[str] = None,
                           since: Optional[str] = None,
                           until: Optional[str] = None,
                           limit: int = 100,
                           only_pending: bool = False,
                           user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Lista lotes de retirada com filtros (technician_id, since, until).

    iter173 — `only_pending=true` filtra para lotes que ainda têm pelo menos
    1 ONT no estoque do técnico (não devolvida e não instalada). Inclui em
    cada lote o campo `pending_with_tech` (contagem).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if technician_id:
        q["technician_id"] = technician_id
    date_q: Dict[str, Any] = {}
    if since:
        date_q["$gte"] = since
    if until:
        date_q["$lte"] = until
    if date_q:
        q["at"] = date_q

    items = await db.stok_batch_log.find(q, {"_id": 0}) \
        .sort("at", -1).limit(int(min(max(limit, 1), 500))).to_list(limit)

    # Enriquece com nome do técnico (best-effort)
    tech_ids = list({i.get("technician_id") for i in items if i.get("technician_id")})
    techs: Dict[str, str] = {}
    if tech_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": tech_ids}}, {"_id": 0, "id": 1, "name": 1}):
            techs[c["id"]] = c.get("name")
    for it in items:
        it["technician_name"] = techs.get(it.get("technician_id"))

    # iter173 — pre-calcula `pending_with_tech` por lote (MACs ainda no técnico)
    # Coleta todos os MACs únicos de todos os lotes em 1 query
    all_macs: List[str] = []
    for it in items:
        for o in (it.get("onts") or []):
            mac = o.get("mac")
            if mac:
                all_macs.append(mac)
    macs_with_tech: set[str] = set()
    if all_macs:
        async for d in db.stok_onts.find(
            {"company_id": cid, "mac": {"$in": list(set(all_macs))},
             "location_type": "tecnico",
             "status": {"$nin": ["defeito_devolver_empresa"]}},
            {"_id": 0, "mac": 1},
        ):
            macs_with_tech.add(d["mac"])
    for it in items:
        it["pending_with_tech"] = sum(
            1 for o in (it.get("onts") or [])
            if o.get("mac") in macs_with_tech
        )

    # Filtro `only_pending`
    if only_pending:
        items = [it for it in items if it.get("pending_with_tech", 0) > 0]

    # Totais agregados
    total_onts = sum((i.get("created") or 0) + (i.get("moved") or 0) for i in items)
    total_pending = sum(i.get("pending_with_tech") or 0 for i in items)
    return {
        "items": items,
        "total_batches": len(items),
        "total_onts": total_onts,
        "total_pending_with_tech": total_pending,
    }


# ---------------------------------------------------------------------------
# iter172 — Detalhes de um lote: ONTs catalogadas + status atual + PPPoE
# ---------------------------------------------------------------------------
@router.get("/batch-history/{batch_id}/items")
async def batch_items(batch_id: str,
                          user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Retorna a lista detalhada de ONTs catalogadas em um lote.

    Para cada ONT inclui:
      - `status_current`: "em_estoque" | "instalada" | "defeito" | "removida_smartolt"
      - `current_location_id`: técnico (estoque) ou client_id (instalada)
      - `current_client_name`: nome do cliente (se instalada)
      - `pppoe_user`: PPPoE do cliente atual (se instalada)
      - `installed_by`: nome do técnico que instalou (se instalada)
      - `installed_at`: timestamp da instalação (se instalada)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    batch = await db.stok_batch_log.find_one(
        {"company_id": cid, "id": batch_id}, {"_id": 0})
    if not batch:
        raise HTTPException(404, "Lote não encontrado")

    onts_log: List[Dict[str, Any]] = batch.get("onts") or []
    if not onts_log:
        return {"batch_id": batch_id, "items": [], "total": 0,
                  "note": "Este lote é antigo e não tem detalhamento por ONT."}

    macs = [o.get("mac") for o in onts_log if o.get("mac")]

    # Mapa MAC -> stok_onts atual
    onts_by_mac: Dict[str, Dict[str, Any]] = {}
    if macs:
        async for d in db.stok_onts.find(
            {"company_id": cid, "mac": {"$in": macs}}, {"_id": 0},
        ):
            onts_by_mac[d["mac"]] = d

    # Coleta client_ids para buscar PPPoE em lote
    client_ids = {d.get("location_id") for d in onts_by_mac.values()
                    if d.get("location_type") == "cliente" and d.get("location_id")}
    pppoe_by_client: Dict[str, str] = {}
    name_by_client: Dict[str, str] = {}
    if client_ids:
        async for sub in db.subscribers.find(
            {"company_id": cid, "id": {"$in": list(client_ids)}},
            {"_id": 0, "id": 1, "pppoe_user": 1, "name": 1, "username": 1},
        ):
            pppoe_by_client[sub["id"]] = sub.get("pppoe_user") or sub.get("username")
            name_by_client[sub["id"]] = sub.get("name")

    items_out: List[Dict[str, Any]] = []
    for o in onts_log:
        mac = o.get("mac")
        ont = onts_by_mac.get(mac) if mac else None
        if not ont:
            items_out.append({
                "mac": mac, "sn": o.get("sn"),
                "operation": o.get("op"),
                "status_current": "removida_smartolt",
                "current_location_id": None,
                "current_client_name": None,
                "pppoe_user": None,
                "installed_by": None,
                "installed_at": None,
            })
            continue
        loc_type = ont.get("location_type")
        status = ont.get("status")
        if loc_type == "cliente":
            cur_client_id = ont.get("location_id")
            status_cur = "instalada"
            pppoe = pppoe_by_client.get(cur_client_id)
            client_name = (name_by_client.get(cur_client_id)
                              or ont.get("client_name"))
        elif loc_type == "tecnico":
            status_cur = "defeito" if status == "defeito_devolver_empresa" \
                           else "em_estoque"
            pppoe = None
            client_name = None
        elif loc_type == "empresa":
            status_cur = "em_estoque"
            pppoe = None
            client_name = None
        else:
            status_cur = "desconhecido"
            pppoe = None
            client_name = None
        items_out.append({
            "mac": mac,
            "sn": o.get("sn") or ont.get("scan_sn"),
            "operation": o.get("op"),
            "status_current": status_cur,
            "current_location_id": ont.get("location_id"),
            "current_client_name": client_name,
            "pppoe_user": pppoe,
            "installed_by": ont.get("installed_by_name") or ont.get("installed_by_email"),
            "installed_at": ont.get("installed_at"),
        })

    # Sumário
    summary = {
        "instaladas": sum(1 for i in items_out if i["status_current"] == "instalada"),
        "em_estoque": sum(1 for i in items_out if i["status_current"] == "em_estoque"),
        "defeito": sum(1 for i in items_out if i["status_current"] == "defeito"),
        "removida_smartolt": sum(1 for i in items_out
                                       if i["status_current"] == "removida_smartolt"),
    }

    return {
        "batch_id": batch_id,
        "technician_id": batch.get("technician_id"),
        "at": batch.get("at"),
        "by_name": batch.get("by_name"),
        "reason": batch.get("reason"),
        "items": items_out,
        "total": len(items_out),
        "summary": summary,
    }


@router.get("/batch-history/pdf")
async def batch_history_pdf(technician_id: Optional[str] = None,
                                since: Optional[str] = None,
                                until: Optional[str] = None,
                                user: dict = Depends(get_current_user)):
    """Exporta o histórico filtrado em PDF para auditoria."""
    from fastapi.responses import StreamingResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from datetime import datetime as _dt
    import io as _io

    hist = await batch_history(technician_id=technician_id, since=since,
                                  until=until, limit=500, user=user)

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=15*mm, rightMargin=15*mm,
                              topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    period_txt = ""
    if since or until:
        period_txt = f" · Período: {since or '—'} a {until or '—'}"
    tech_txt = ""
    if technician_id:
        # Pega o nome do primeiro item se houver
        first_with_name = next((i for i in hist["items"]
                                  if i.get("technician_name")), None)
        tech_txt = (f" · Técnico: {first_with_name['technician_name']}"
                    if first_with_name and first_with_name.get("technician_name")
                    else f" · Técnico: {technician_id}")
    story = [
        Paragraph("<b>📋 Histórico de Retiradas em Lote (Scan IA)</b>", styles["Title"]),
        Paragraph(
            f"Gerado em <b>{_dt.now().strftime('%d/%m/%Y %H:%M')}</b>{period_txt}{tech_txt}",
            styles["BodyText"],
        ),
        Paragraph(
            f"Total: <b>{hist['total_batches']}</b> lote(s) · "
            f"<b>{hist['total_onts']}</b> ONTs catalogadas",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Data", "Técnico", "Operador", "Criadas", "Movidas", "Motivo"]]
    for it in hist["items"]:
        at = (it.get("at") or "")[:16].replace("T", " ")
        rows.append([
            at,
            (it.get("technician_name") or it.get("technician_id") or "—")[:24],
            (it.get("by_name") or it.get("by_email") or "—")[:20],
            str(it.get("created") or 0),
            str(it.get("moved") or 0),
            (it.get("reason") or "—")[:34],
        ])
    if len(rows) == 1:
        rows.append(["—", "—", "—", "0", "0", "Sem lotes no período"])
    t = Table(rows, colWidths=[28*mm, 38*mm, 32*mm, 16*mm, 16*mm, 50*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d9488")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
            [colors.white, colors.HexColor("#f8fafc")]),
        ("ALIGN", (3,0), (4,-1), "CENTER"),
    ]))
    story.append(t)
    doc.build(story)
    buf.seek(0)
    fname = f"retiradas_lote_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

