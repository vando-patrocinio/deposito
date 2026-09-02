"""Módulo Holerite Digital — RH com LGPD e segurança reforçada.

Recursos:
- Upload de PDF (admin/RH) com nome físico aleatório fora de pasta pública
- Token criptograficamente seguro (apenas hash salvo no banco)
- Link público `/holerite/{token}` exige re-autenticação do colaborador
- Audit logs completos (upload, envio WhatsApp, clique, view, download, revogação)
- Integração com canal WhatsApp Meta Cloud já configurado
- Princípios LGPD: minimização, finalidade, retenção, controle de acesso

Coleções MongoDB:
- payroll_documents: metadados do holerite
- payroll_access_tokens: tokens hashados + expiração
- payroll_access_logs: auditoria completa

Endpoints:
- POST   /api/holerites/upload                  (admin) sobe 1 PDF
- GET    /api/holerites                          (admin) lista
- DELETE /api/holerites/{doc_id}                 (admin) revoga (soft)
- POST   /api/holerites/{doc_id}/notify          (admin) envia WA
- GET    /api/holerites/me                       (collab) lista próprios
- POST   /api/holerites/token/{token}/validate   (público) valida token (sem expor doc)
- POST   /api/holerites/token/{token}/access     (collab autenticado) cria sessão
- GET    /api/holerites/{doc_id}/file            (collab/admin) stream PDF
- GET    /api/holerites/audit/{doc_id}           (admin) logs do doc
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                       UploadFile)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.holerite")
router = APIRouter(prefix="/api/holerites", tags=["holerite"])

# Diretório isolado, fora de pasta pública. Variável de env opcional.
STORAGE_DIR = Path(os.environ.get("HOLERITE_STORAGE_DIR")
                       or "/app/data/holerites")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_TOKEN_TTL_HOURS = 72


def _default_pay_date(year: int, month: int) -> str:
    """Data padrão de pagamento = 5º dia útil do mês seguinte à competência.

    Para simplificar, usamos 5º dia corrido (formato ISO YYYY-MM-DD).
    Pode ser alterada manualmente pelo admin no upload.
    """
    next_m = month + 1
    next_y = year
    if next_m > 12:
        next_m = 1
        next_y += 1
    return f"{next_y:04d}-{next_m:02d}-05"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _has_pdf_signature(pdf_bytes: bytes) -> bool:
    """Detecta se um PDF tem assinatura digital embarcada.

    Verifica a presença de:
    - /AcroForm com /SigFlags
    - /ByteRange (presente em PDFs assinados pelo gov.br)
    - /Sig ou /Sig.V (campos de assinatura)
    """
    sample = pdf_bytes[:50_000] + pdf_bytes[-50_000:] if len(pdf_bytes) > 100_000 else pdf_bytes
    markers = [b"/ByteRange", b"/Sig", b"/SigFlags", b"adbe.pkcs7"]
    return any(m in sample for m in markers)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class HoleriteOut(BaseModel):
    id: str
    employee_id: Optional[str] = None
    employee_name: str
    employee_phone: Optional[str] = None
    competence_month: int
    competence_year: int
    gross: float = 0.0
    net: float = 0.0
    status: str = "available"  # available | revoked
    file_size_kb: int = 0
    created_at: str
    created_by: Optional[str] = None
    notified_at: Optional[str] = None
    viewed_at: Optional[str] = None


class NotifyIn(BaseModel):
    ttl_hours: int = Field(DEFAULT_TOKEN_TTL_HOURS, ge=1, le=720)
    custom_message: Optional[str] = Field(None, max_length=400)


class AccessIn(BaseModel):
    """Payload do colaborador autenticado abrindo o link."""
    password: str = Field(..., min_length=4, max_length=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_ip(req: Request) -> str:
    return (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip() \
        or (req.client.host if req.client else "?")


async def _audit(doc_id: str, company_id: str, action: str,
                    actor_id: Optional[str], actor_type: str,
                    req: Optional[Request] = None, result: str = "ok",
                    extra: Optional[dict] = None) -> None:
    """Insere log de auditoria. NUNCA falha o request por erro de log."""
    try:
        await db.payroll_access_logs.insert_one({
            "id": f"log-{uuid.uuid4().hex[:14]}",
            "doc_id": doc_id,
            "company_id": company_id,
            "action": action,
            "actor_id": actor_id,
            "actor_type": actor_type,  # admin | rh | collaborator | system
            "ip": _client_ip(req) if req else None,
            "user_agent": (req.headers.get("User-Agent") if req else None),
            "result": result,
            "extra": extra or {},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning("[audit] falha: %s", e)


def _doc_to_out(d: dict) -> dict:
    """Sanitiza documento Mongo pra resposta JSON segura (sem _id, sem file_path)."""
    return {
        "id": d.get("id"),
        "employee_id": d.get("employee_id"),
        "employee_name": d.get("employee_name") or "—",
        "employee_phone": d.get("employee_phone"),
        "competence_month": int(d.get("competence_month", 0)),
        "competence_year": int(d.get("competence_year", 0)),
        "gross": float(d.get("gross", 0)),
        "net": float(d.get("net", 0)),
        "deductions_total": float(d.get("deductions_total", 0)),
        "earnings_breakdown": d.get("earnings_breakdown") or [],
        "deductions_breakdown": d.get("deductions_breakdown") or [],
        "matricula": d.get("matricula"),
        "position": d.get("position"),
        "cpf": d.get("cpf"),
        "source": d.get("source") or "manual",
        "ai_match_score": d.get("ai_match_score"),
        "ai_match_status": d.get("ai_match_status"),
        "anomalies": d.get("anomalies") or [],
        "anomalies_count": int(d.get("anomalies_count") or 0),
        "anomalies_critical": int(d.get("anomalies_critical") or 0),
        "pending_review_reason": d.get("pending_review_reason"),
        "approved_at": d.get("approved_at"),
        "approved_by_name": d.get("approved_by_name"),
        "approval_note": d.get("approval_note"),
        # Assinatura digital
        "signed_at": d.get("signed_at"),
        "signed_method": d.get("signed_method"),
        "signed_by_name": d.get("signed_by_name"),
        "signature_valid": bool(d.get("signature_valid")),
        "signature_hash": d.get("signature_hash"),
        "signed_file_size_kb": int(
            (d.get("signed_file_size_bytes", 0) or 0) / 1024,
        ),
        # Data de pagamento (release date pro colaborador)
        "pay_date": d.get("pay_date"),
        "status": d.get("status", "available"),
        "file_size_kb": int((d.get("file_size_bytes", 0) or 0) / 1024),
        "created_at": d.get("created_at"),
        "created_by": d.get("created_by"),
        "notified_at": d.get("notified_at"),
        "viewed_at": d.get("viewed_at"),
    }


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_holerite(
    request: Request,
    file: UploadFile = File(...),
    employee_id: Optional[str] = Form(None),
    employee_name: str = Form(...),
    employee_phone: Optional[str] = Form(None),
    competence_month: int = Form(...),
    competence_year: int = Form(...),
    gross: float = Form(0.0),
    net: float = Form(0.0),
    user: dict = Depends(require_role("gestor")),
):
    """Sobe 1 holerite. Apenas RH/gestor/admin. Valida PDF."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Lê e valida arquivo
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "Arquivo maior que 10MB.")
    if len(data) < 100:
        raise HTTPException(400, "Arquivo vazio ou corrompido.")
    # Validação de tipo PDF pela assinatura mágica (%PDF-)
    if not data[:5].startswith(b"%PDF-"):
        raise HTTPException(400, "Arquivo não é PDF válido (assinatura inválida).")

    if competence_month < 1 or competence_month > 12:
        raise HTTPException(400, "competence_month deve ser 1-12.")
    if competence_year < 2000 or competence_year > 2100:
        raise HTTPException(400, "competence_year inválido.")

    # Nome físico aleatório, fora de pasta pública.
    file_uuid = uuid.uuid4().hex
    physical_name = f"{file_uuid}.pdf"
    from services.objstore import put_object
    storage_ref = await put_object(
        f"smartprov/holerites/{cid}/{physical_name}", data, "application/pdf")

    doc_id = f"hol-{uuid.uuid4().hex[:14]}"
    doc = {
        "id": doc_id,
        "company_id": cid,
        "employee_id": employee_id,
        "employee_name": employee_name.strip(),
        "employee_phone": (employee_phone or "").strip() or None,
        "competence_month": competence_month,
        "competence_year": competence_year,
        "pay_date": _default_pay_date(competence_year, competence_month),
        "gross": float(gross or 0),
        "net": float(net or 0),
        "file_uuid": file_uuid,
        "file_path": storage_ref,
        "file_size_bytes": len(data),
        "file_hash": _sha256_bytes(data),
        "status": "available",
        "created_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.payroll_documents.insert_one(doc)
    await _audit(doc_id, cid, "upload", user.get("id"), "rh", request,
                    extra={"size_bytes": len(data),
                              "competence": f"{competence_month:02d}/{competence_year}"})
    return _doc_to_out(doc)


@router.get("")
async def list_holerites(
    year: Optional[int] = None,
    month: Optional[int] = None,
    employee_id: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(require_role("gestor")),
):
    """Lista holerites da empresa (filtros opcionais)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    filt: dict = {"company_id": cid}
    if year:
        filt["competence_year"] = int(year)
    if month:
        filt["competence_month"] = int(month)
    if employee_id:
        filt["employee_id"] = employee_id
    if q:
        filt["employee_name"] = {"$regex": q, "$options": "i"}
    docs = await db.payroll_documents.find(filt, {"_id": 0,
                                                       "file_path": 0,
                                                       "file_uuid": 0}) \
        .sort("created_at", -1).limit(500).to_list(500)
    return {"items": [_doc_to_out(d) for d in docs], "count": len(docs)}


@router.delete("/{doc_id}")
async def revoke_holerite(doc_id: str, request: Request,
                              user: dict = Depends(require_role("gestor"))):
    """Soft delete (marca revoked). Tokens ativos viram inválidos."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": cid},
        {"$set": {"status": "revoked", "revoked_at": now_iso(),
                     "revoked_by": user.get("id")}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Holerite não encontrado.")
    # Invalida tokens ativos
    await db.payroll_access_tokens.update_many(
        {"doc_id": doc_id, "revoked_at": None},
        {"$set": {"revoked_at": now_iso()}},
    )
    await _audit(doc_id, cid, "revoke", user.get("id"), "rh", request)
    return {"ok": True}


@router.delete("/{doc_id}/permanent")
async def permanent_delete_holerite(
    doc_id: str, request: Request,
    user: dict = Depends(require_role("gestor")),
):
    """HARD DELETE — remove o documento, arquivo PDF e arquivo assinado do disco.

    Use para erros de lançamento que precisam ser totalmente eliminados.
    Audit log fica gravado para compliance LGPD.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": cid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")

    # Auditoria ANTES de apagar (deixa rastro de quem apagou e quando)
    await _audit(
        doc_id, cid, "permanent_delete", user.get("id"), "rh", request,
        extra={
            "employee_id": doc.get("employee_id"),
            "employee_name": doc.get("employee_name"),
            "competence": (
                f"{doc.get('competence_month'):02d}/{doc.get('competence_year')}"
            ),
            "gross": doc.get("gross"),
            "net": doc.get("net"),
            "had_signature": bool(doc.get("signed_at")),
        },
    )

    # Apaga arquivos físicos
    for key in ("file_path", "signed_file_path"):
        fp = doc.get(key)
        if fp:
            try:
                p = Path(fp)
                if p.exists():
                    p.unlink()
            except Exception as e:
                logger.warning("[holerite] falha ao apagar %s: %s", fp, e)

    # Apaga doc + tokens
    await db.payroll_documents.delete_one({"id": doc_id, "company_id": cid})
    await db.payroll_access_tokens.delete_many({"doc_id": doc_id})

    return {"ok": True, "deleted": doc_id}


@router.post("/{doc_id}/notify")
async def notify_holerite(doc_id: str, payload: NotifyIn, request: Request,
                              user: dict = Depends(require_role("gestor"))):
    """Gera token + envia link via WhatsApp Meta Cloud."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.payroll_documents.find_one({"id": doc_id, "company_id": cid},
                                                  {"_id": 0})
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")
    if doc.get("status") == "revoked":
        raise HTTPException(400, "Holerite revogado.")
    if doc.get("status") == "pending_review":
        raise HTTPException(
            423,  # Locked
            f"Holerite aguardando revisão do RH. {doc.get('pending_review_reason', '')}"
        )
    phone = doc.get("employee_phone")
    if not phone:
        raise HTTPException(400, "Colaborador sem telefone WhatsApp cadastrado.")

    # Gera token aleatório (32 bytes urlsafe → ~43 chars). Salva apenas hash.
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires = datetime.now(timezone.utc) + timedelta(hours=payload.ttl_hours)

    await db.payroll_access_tokens.insert_one({
        "id": f"tok-{uuid.uuid4().hex[:14]}",
        "doc_id": doc_id,
        "company_id": cid,
        "employee_id": doc.get("employee_id"),
        "token_hash": token_hash,
        "expires_at": expires.isoformat(),
        "used_at": None,
        "revoked_at": None,
        "created_at": now_iso(),
        "created_by": user.get("id"),
    })

    # Monta link público
    public_base = (os.environ.get("PUBLIC_BASE_URL")
                      or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
    secure_link = f"{public_base}/holerite/{raw_token}"

    competence = f"{int(doc['competence_month']):02d}/{int(doc['competence_year'])}"
    first_name = (doc.get("employee_name") or "").split()[0] or "colaborador"
    if payload.custom_message:
        text = payload.custom_message.replace("{{nome}}", first_name) \
            .replace("{{competencia}}", competence) \
            .replace("{{link_seguro}}", secure_link)
    else:
        text = (
            f"Olá, {first_name}. Seu holerite referente à competência "
            f"{competence} está disponível para consulta. "
            f"Acesse com segurança pelo link: {secure_link} . "
            f"Por segurança, será necessário informar sua senha de acesso "
            f"ao SmartProv."
        )

    # Envia via Meta Cloud (canal já configurado)
    creds = await db.whatsapp_meta_creds.find_one({"company_id": cid},
                                                      {"_id": 0})
    wa_send_ok = False
    wa_err = None
    if creds and creds.get("enabled_whatsapp_cloud") \
            and creds.get("wa_access_token") and creds.get("wa_phone_number_id"):
        try:
            url = f"https://graph.facebook.com/v25.0/{creds['wa_phone_number_id']}/messages"
            wa_to = phone.lstrip("+")
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {creds['wa_access_token']}"},
                    json={"messaging_product": "whatsapp", "to": wa_to,
                            "type": "text", "text": {"body": text}},
                )
                if r.status_code < 400:
                    wa_send_ok = True
                else:
                    try:
                        wa_err = (r.json().get("error") or {}).get("message")
                    except Exception:
                        wa_err = r.text[:200]
        except Exception as e:
            wa_err = str(e)
    else:
        wa_err = "Canal Meta Cloud não configurado/habilitado."

    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": cid},
        {"$set": {"notified_at": now_iso(),
                     "last_notification_status": "sent" if wa_send_ok else "failed"}},
    )
    await db.payroll_whatsapp_notifications.insert_one({
        "id": f"not-{uuid.uuid4().hex[:14]}",
        "doc_id": doc_id,
        "company_id": cid,
        "phone": phone,
        "sent_ok": wa_send_ok,
        "error": wa_err,
        "ttl_hours": payload.ttl_hours,
        "created_at": now_iso(),
        "created_by": user.get("id"),
    })
    await _audit(doc_id, cid, "notify_whatsapp", user.get("id"), "rh", request,
                    result="ok" if wa_send_ok else "fail",
                    extra={"phone": phone, "error": wa_err})

    return {
        "ok": wa_send_ok,
        "secure_link": secure_link,
        "ttl_hours": payload.ttl_hours,
        "phone": phone,
        "error": wa_err,
    }


# ---------------------------------------------------------------------------
# Collaborator endpoints
# ---------------------------------------------------------------------------
@router.get("/me")
async def list_my_holerites(user: dict = Depends(require_role("colaborador"))):
    """Colaborador autenticado lista os próprios holerites."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    eid = user.get("id")
    docs = await db.payroll_documents.find(
        {"company_id": cid, "employee_id": eid, "status": "available"},
        {"_id": 0, "file_path": 0, "file_uuid": 0},
    ).sort("created_at", -1).limit(120).to_list(120)
    return {"items": [_doc_to_out(d) for d in docs], "count": len(docs)}


# ---------------------------------------------------------------------------
# Public-token endpoints (sem autenticação prévia)
# ---------------------------------------------------------------------------
@router.get("/token/{token}/info")
async def token_info(token: str, request: Request):
    """Devolve info mínima do token (sem expor dados sensíveis).

    Usado pela página de acesso pra mostrar 'Holerite de mai/2026 disponível.
    Faça login pra visualizar.' sem revelar dados pessoais.
    """
    th = _hash_token(token)
    tok = await db.payroll_access_tokens.find_one({"token_hash": th},
                                                       {"_id": 0})
    if not tok:
        raise HTTPException(404, "Link inválido ou expirado.")
    if tok.get("revoked_at"):
        raise HTTPException(403, "Link revogado.")
    expires = tok.get("expires_at")
    if expires and expires < now_iso():
        raise HTTPException(403, "Link expirado.")
    doc = await db.payroll_documents.find_one(
        {"id": tok["doc_id"], "company_id": tok["company_id"]},
        {"_id": 0, "competence_month": 1, "competence_year": 1,
         "status": 1, "employee_name": 1},
    )
    if not doc or doc.get("status") != "available":
        raise HTTPException(404, "Holerite indisponível.")
    await _audit(tok["doc_id"], tok["company_id"], "link_click", None,
                    "anonymous", request,
                    extra={"token_id_suffix": (tok.get("id") or "")[-6:]})
    # Não revela nome completo — só o primeiro nome
    first_name = (doc.get("employee_name") or "—").split()[0]
    return {
        "ok": True,
        "first_name": first_name,
        "competence": f"{int(doc['competence_month']):02d}/{int(doc['competence_year'])}",
        "expires_at": expires,
    }


@router.post("/token/{token}/access")
async def token_access(token: str, payload: AccessIn, request: Request):
    """Colaborador autentica para acessar.

    Confere a senha do cadastro do colaborador (hash bcrypt em `users` ou
    `collaborators`). Em caso de sucesso, marca token como usado e devolve
    um session_token curto pra carregar o PDF.
    """
    th = _hash_token(token)
    tok = await db.payroll_access_tokens.find_one({"token_hash": th},
                                                       {"_id": 0})
    if not tok:
        raise HTTPException(404, "Link inválido.")
    if tok.get("revoked_at"):
        raise HTTPException(403, "Link revogado.")
    if (tok.get("expires_at") or "") < now_iso():
        raise HTTPException(403, "Link expirado.")

    cid = tok["company_id"]
    doc_id = tok["doc_id"]
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": cid}, {"_id": 0}
    )
    if not doc or doc.get("status") != "available":
        raise HTTPException(404, "Holerite indisponível.")

    # Tenta validar senha em `users` (admin/gestor/rh) ou `collaborators`.
    # IMPORTANTE: usamos bcrypt já presente no projeto.
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    eid = doc.get("employee_id")
    employee_phone = (doc.get("employee_phone") or "").strip()
    ok = False
    actor_id = None
    if eid:
        u = await db.users.find_one({"id": eid, "company_id": cid},
                                       {"_id": 0, "password_hash": 1, "id": 1})
        if u and u.get("password_hash"):
            try:
                if pwd_ctx.verify(payload.password, u["password_hash"]):
                    ok = True
                    actor_id = u["id"]
            except Exception:
                pass
        if not ok:
            c = await db.collaborators.find_one({"id": eid, "company_id": cid},
                                                    {"_id": 0, "password_hash": 1, "id": 1})
            if c and c.get("password_hash"):
                try:
                    if pwd_ctx.verify(payload.password, c["password_hash"]):
                        ok = True
                        actor_id = c["id"]
                except Exception:
                    pass

    if not ok:
        await _audit(doc_id, cid, "auth_attempt", actor_id, "anonymous",
                        request, result="fail")
        # 1 segundo de delay anti-bruteforce
        import asyncio
        await asyncio.sleep(0.8)
        raise HTTPException(401, "Senha inválida.")

    # Gera session_token curto, único para este doc_id (válido 30min).
    session_token = secrets.token_urlsafe(24)
    await db.payroll_view_sessions.insert_one({
        "id": f"sess-{uuid.uuid4().hex[:14]}",
        "session_hash": _hash_token(session_token),
        "doc_id": doc_id,
        "company_id": cid,
        "employee_id": actor_id,
        "expires_at": (datetime.now(timezone.utc)
                          + timedelta(minutes=30)).isoformat(),
        "created_at": now_iso(),
        "ip": _client_ip(request),
    })
    await db.payroll_access_tokens.update_one(
        {"token_hash": th},
        {"$set": {"used_at": now_iso()}},
    )
    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": cid, "viewed_at": {"$exists": False}},
        {"$set": {"viewed_at": now_iso()}},
    )
    await _audit(doc_id, cid, "auth_success", actor_id, "collaborator", request,
                    extra={"phone_suffix": employee_phone[-4:] if employee_phone else None})
    return {"ok": True, "session_token": session_token, "doc_id": doc_id}


@router.get("/session/{session_token}/file")
async def stream_holerite(session_token: str, request: Request):
    """Stream do PDF — só com session_token válido (curta duração).

    Não expõe URL pública direta. Validação dupla: sessão ativa + doc disponível.
    """
    sh = _hash_token(session_token)
    sess = await db.payroll_view_sessions.find_one({"session_hash": sh},
                                                        {"_id": 0})
    if not sess:
        raise HTTPException(404, "Sessão inválida.")
    if (sess.get("expires_at") or "") < now_iso():
        raise HTTPException(403, "Sessão expirada.")
    doc = await db.payroll_documents.find_one(
        {"id": sess["doc_id"], "company_id": sess["company_id"]},
        {"_id": 0},
    )
    if not doc or doc.get("status") != "available":
        raise HTTPException(404, "Holerite indisponível.")
    fp = doc.get("file_path")
    from services.objstore import read_ref
    pdf = await read_ref(fp or "")
    if pdf is None:
        raise HTTPException(404, "Arquivo físico não encontrado.")
    await _audit(doc["id"], doc["company_id"], "view_pdf",
                    sess.get("employee_id"), "collaborator", request)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                'inline; filename="holerite-'
                f"{doc['competence_year']}-{doc['competence_month']:02d}.pdf\""
            ),
            # Evita cache do PDF em proxies/cdn
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@router.get("/audit/{doc_id}")
async def list_audit(doc_id: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.payroll_access_logs.find(
        {"doc_id": doc_id, "company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(200).to_list(200)
    return {"items": docs, "count": len(docs)}


# ---------------------------------------------------------------------------
# Holerite IA — Upload + parse + match
# ---------------------------------------------------------------------------
@router.post("/ai-parse")
async def ai_parse_holerite(
    request: Request,
    file: UploadFile = File(...),
    threshold: int = Form(85),
    user: dict = Depends(require_role("gestor")),
):
    """Recebe PDF do contador, extrai funcionários via Holerite IA (Claude)
    e faz match com colaboradores da empresa.

    NÃO persiste nada — apenas devolve preview pra confirmação.
    """
    from services import holerite_ai as ha

    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "Arquivo maior que 10MB.")
    if not data[:5].startswith(b"%PDF-"):
        raise HTTPException(400, "Arquivo não é PDF válido.")
    if not 50 <= int(threshold) <= 100:
        raise HTTPException(400, "threshold deve estar entre 50 e 100.")

    try:
        parsed = await ha.parse_pdf_with_ai(cid, data)
    except RuntimeError as e:
        raise HTTPException(422, safe_detail(422, e))
    except Exception as e:
        logger.exception("[holerite-ai] erro parsing: %s", e)
        raise HTTPException(500, safe_detail(500, e, "Falha ao processar com IA:"))

    preview = await ha.match_all(cid, parsed, threshold=int(threshold))

    # Guarda o resultado temporário pra import posterior (TTL implícito via cleanup)
    parse_id = f"hai-{uuid.uuid4().hex[:14]}"
    await db.holerite_ai_drafts.insert_one({
        "id": parse_id,
        "company_id": cid,
        "preview": preview,
        "raw_pdf_size": len(data),
        "created_at": now_iso(),
        "created_by": user.get("id"),
    })

    # Salva o PDF cru temporariamente (mesma pasta, prefixo "drafts/")
    from services.objstore import put_object
    draft_ref = await put_object(
        f"smartprov/holerites/{cid}/drafts/{parse_id}.pdf",
        data, "application/pdf")
    await db.payroll_ai_drafts.update_one(
        {"parse_id": parse_id},
        {"$set": {"parse_id": parse_id, "company_id": cid,
                   "storage_ref": draft_ref, "created_at": now_iso()}},
        upsert=True,
    )

    await _audit(parse_id, cid, "ai_parse", user.get("id"), "rh", request,
                    extra={
                        "parsed": preview["stats"]["parsed_count"],
                        "matched": preview["stats"]["matched_count"],
                        "size_bytes": len(data),
                    })

    return {
        "ok": True,
        "parse_id": parse_id,
        **preview,
    }


class AiImportItem(BaseModel):
    """1 item do import (corresponde a 1 funcionário identificado)."""
    parsed_index: int            # índice dentro de preview.matches
    employee_id: Optional[str] = None  # confirmado/alterado pelo gestor
    skip: bool = False           # se True, ignora este funcionário


class AiImportIn(BaseModel):
    parse_id: str
    competence_month: int = Field(..., ge=1, le=12)
    competence_year: int = Field(..., ge=2000, le=2100)
    items: List[AiImportItem]


@router.post("/ai-import")
async def ai_import_holerite(
    payload: AiImportIn, request: Request,
    user: dict = Depends(require_role("gestor")),
):
    """Confirma o import: cria 1 payroll_document por funcionário matched.

    O PDF original é compartilhado por todos (mesmo arquivo do contador).
    Cada doc filtra o nome do funcionário para exibição.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    draft = await db.holerite_ai_drafts.find_one(
        {"id": payload.parse_id, "company_id": cid}, {"_id": 0},
    )
    if not draft:
        raise HTTPException(404, "Draft de parsing não encontrado.")

    preview = draft["preview"]
    matches = preview.get("matches", [])

    # Localiza arquivo cru
    draft_path = STORAGE_DIR / cid / "drafts" / f"{payload.parse_id}.pdf"
    draft_rec = await db.payroll_ai_drafts.find_one(
        {"parse_id": payload.parse_id, "company_id": cid}, {"_id": 0})
    from services.objstore import read_ref
    pdf_bytes = await read_ref((draft_rec or {}).get("storage_ref") or "",
                                draft_path)
    if pdf_bytes is None:
        raise HTTPException(404, "Arquivo do draft expirou ou foi removido.")

    imported: List[Dict[str, Any]] = []
    skipped = 0
    for it in payload.items:
        if it.skip:
            skipped += 1
            continue
        if it.parsed_index < 0 or it.parsed_index >= len(matches):
            continue
        match_item = matches[it.parsed_index]
        parsed_emp = match_item.get("parsed", {})
        eid = it.employee_id or (
            match_item.get("match", {}) or {}
        ).get("id")
        if not eid:
            continue  # sem match e sem manual → pula

        # Pega dados do colaborador (telefone para WhatsApp)
        col = await db.collaborators.find_one(
            {"id": eid, "company_id": cid},
            {"_id": 0, "name": 1, "phone": 1},
        )
        employee_name = (
            col.get("name") if col else parsed_emp.get("full_name")
        ) or "—"
        employee_phone = (col or {}).get("phone")

        # Cada funcionário ganha uma cópia do mesmo PDF (caminho único)
        file_uuid = uuid.uuid4().hex
        physical_name = f"{file_uuid}.pdf"
        from services.objstore import put_object
        storage_ref = await put_object(
            f"smartprov/holerites/{cid}/{physical_name}",
            pdf_bytes, "application/pdf")

        doc_id = f"hol-{uuid.uuid4().hex[:14]}"
        doc = {
            "id": doc_id,
            "company_id": cid,
            "employee_id": eid,
            "employee_name": employee_name.strip(),
            "employee_phone": (employee_phone or "").strip() or None,
            "competence_month": payload.competence_month,
            "competence_year": payload.competence_year,
            "pay_date": _default_pay_date(
                payload.competence_year, payload.competence_month
            ),
            "gross": float(parsed_emp.get("gross") or 0),
            "net": float(parsed_emp.get("net") or 0),
            "deductions_total": float(parsed_emp.get("deductions_total") or 0),
            "earnings_breakdown": parsed_emp.get("earnings", []),
            "deductions_breakdown": parsed_emp.get("deductions", []),
            "fgts_base": parsed_emp.get("fgts_base"),
            "irrf_base": parsed_emp.get("irrf_base"),
            "inss_base": parsed_emp.get("inss_base"),
            "matricula": parsed_emp.get("matricula"),
            "position": parsed_emp.get("position"),
            "cpf": parsed_emp.get("cpf"),
            "source": "ai_import",
            "ai_parse_id": payload.parse_id,
            "ai_match_score": match_item.get("match_score"),
            "ai_match_status": match_item.get("match_status"),
            "file_uuid": file_uuid,
            "file_path": storage_ref,
            "file_size_bytes": len(pdf_bytes),
            "status": "available",
            "created_at": now_iso(),
            "created_by": user.get("id"),
        }
        await db.payroll_documents.insert_one(doc)
        await _audit(doc_id, cid, "ai_import", user.get("id"), "rh", request,
                        extra={
                            "employee_id": eid,
                            "match_score": match_item.get("match_score"),
                            "competence": (
                                f"{payload.competence_month:02d}/"
                                f"{payload.competence_year}"
                            ),
                            "parse_id": payload.parse_id,
                        })
        # Detecta anomalias comparando com mês anterior (auto-lock se crítica)
        try:
            from services import holerite_anomaly as ha_anom
            anomalies = await ha_anom.analyze_doc(doc_id, cid)
            doc["anomalies"] = anomalies
            doc["anomalies_count"] = len(anomalies)
            doc["anomalies_critical"] = sum(
                1 for a in anomalies if a.get("severity") == "critical"
            )
            if doc["anomalies_critical"] > 0:
                doc["status"] = "pending_review"
                doc["pending_review_reason"] = (
                    f"{doc['anomalies_critical']} anomalia(s) crítica(s) "
                    "detectada(s) — aprovação do RH necessária."
                )
        except Exception as e:
            logger.warning("[holerite-ai] anomaly detect falhou %s: %s",
                              doc_id, e)
        out = _doc_to_out(doc)
        out["anomalies"] = doc.get("anomalies") or []
        out["anomalies_count"] = doc.get("anomalies_count", 0)
        out["anomalies_critical"] = doc.get("anomalies_critical", 0)
        imported.append(out)

    # Marca draft como consumido (mas mantém pra auditoria)
    await db.holerite_ai_drafts.update_one(
        {"id": payload.parse_id},
        {"$set": {"imported_at": now_iso(),
                    "imported_count": len(imported),
                    "skipped_count": skipped}},
    )

    return {
        "ok": True,
        "imported": len(imported),
        "skipped": skipped,
        "items": imported,
    }


# ---------------------------------------------------------------------------
# Anomalias (Holerite IA Watchdog)
# ---------------------------------------------------------------------------
@router.get("/anomalies")
async def list_anomalies(
    user: dict = Depends(require_role("gestor")),
    severity: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """Lista holerites que têm anomalias detectadas."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    filt: dict = {"company_id": cid, "anomalies_count": {"$gt": 0}}
    if severity == "critical":
        filt["anomalies_critical"] = {"$gt": 0}
    if year:
        filt["competence_year"] = int(year)
    if month:
        filt["competence_month"] = int(month)
    docs = await db.payroll_documents.find(
        filt, {"_id": 0, "file_path": 0, "file_uuid": 0},
    ).sort([("anomalies_critical", -1), ("competence_year", -1),
              ("competence_month", -1)]).limit(500).to_list(500)
    return {
        "items": [_doc_to_out(d) for d in docs],
        "count": len(docs),
        "critical_count": sum(
            1 for d in docs if int(d.get("anomalies_critical") or 0) > 0
        ),
    }


@router.post("/{doc_id}/reanalyze")
async def reanalyze_anomalies(doc_id: str,
                                  user: dict = Depends(require_role("gestor"))):
    """Re-roda a detecção de anomalias para um doc específico."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from services import holerite_anomaly as ha_anom
    anomalies = await ha_anom.analyze_doc(doc_id, cid)
    return {
        "ok": True,
        "doc_id": doc_id,
        "anomalies": anomalies,
        "count": len(anomalies),
        "critical": sum(1 for a in anomalies if a.get("severity") == "critical"),
    }


class ApprovalIn(BaseModel):
    """Aprovação manual de holerite em pending_review."""
    reviewer_note: Optional[str] = Field(None, max_length=500)


@router.post("/{doc_id}/approve")
async def approve_holerite(
    doc_id: str, payload: ApprovalIn, request: Request,
    user: dict = Depends(require_role("gestor")),
):
    """Libera um holerite que estava em pending_review.

    Marca status='available' + registra reviewer + timestamp + nota.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": cid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")
    if doc.get("status") == "revoked":
        raise HTTPException(400, "Holerite revogado — não pode ser aprovado.")
    if doc.get("status") == "available":
        return {"ok": True, "message": "Holerite já estava liberado.",
                  "status": "available"}

    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": cid},
        {"$set": {
            "status": "available",
            "approved_at": now_iso(),
            "approved_by": user.get("id"),
            "approved_by_name": user.get("name") or user.get("email"),
            "approval_note": (payload.reviewer_note or "").strip() or None,
            "pending_review_reason": None,
        }},
    )
    await _audit(doc_id, cid, "approve", user.get("id"), "rh", request,
                    extra={"note": payload.reviewer_note})
    return {"ok": True, "status": "available", "doc_id": doc_id}


@router.post("/{doc_id}/reject")
async def reject_holerite(
    doc_id: str, payload: ApprovalIn, request: Request,
    user: dict = Depends(require_role("gestor")),
):
    """Rejeita um holerite em pending_review (revoga).

    Usado quando o RH confirma o erro do contador e pede correção.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": cid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")

    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": cid},
        {"$set": {
            "status": "revoked",
            "rejected_at": now_iso(),
            "rejected_by": user.get("id"),
            "rejected_by_name": user.get("name") or user.get("email"),
            "rejection_note": (payload.reviewer_note or "").strip() or None,
        }},
    )
    await _audit(doc_id, cid, "reject", user.get("id"), "rh", request,
                    extra={"note": payload.reviewer_note})
    return {"ok": True, "status": "revoked", "doc_id": doc_id}


# ---------------------------------------------------------------------------
# Endpoints PÚBLICOS (app do colaborador — autenticação por collab_id)
# ---------------------------------------------------------------------------
async def _company_for_collab(cid: str) -> str:
    """Retorna company_id do colaborador ou DEMO_COMPANY_ID."""
    col = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "company_id": 1},
    )
    if not col:
        raise HTTPException(404, "Colaborador não encontrado.")
    return col.get("company_id") or DEMO_COMPANY_ID


@router.get("/public/by-collaborator/{cid}")
async def collab_list_holerites(cid: str):
    """Lista holerites do colaborador (acesso via link único do app).

    REGRA: Mostra apenas holerites cuja `pay_date <= hoje` (já foram pagos)
    e `status="available"` (não pending_review nem revoked).
    Não exige JWT — autenticação é o próprio collab_id.
    """
    company_id = await _company_for_collab(cid)
    today_iso = datetime.now(timezone.utc).date().isoformat()
    docs = await db.payroll_documents.find(
        {
            "company_id": company_id, "employee_id": cid,
            "status": "available",
            "$or": [
                {"pay_date": {"$lte": today_iso}},
                {"pay_date": {"$exists": False}},  # docs antigos sem pay_date
                {"pay_date": None},
            ],
        },
        {"_id": 0, "file_path": 0, "file_uuid": 0, "signed_file_path": 0,
         "anomalies": 0, "earnings_breakdown": 0, "deductions_breakdown": 0},
    ).sort("created_at", -1).to_list(500)
    col = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "name": 1, "role": 1},
    )
    return {
        "collaborator": col or {},
        "items": [_doc_to_out(d) for d in docs],
        "count": len(docs),
    }


@router.get("/public/{cid}/{doc_id}/file")
async def collab_get_file_public(cid: str, doc_id: str, request: Request):
    """Stream do PDF do holerite para o colaborador (sem JWT).

    Marca viewed_at + registra audit log. O acesso é restrito a docs do
    próprio collab_id.
    """
    company_id = await _company_for_collab(cid)
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": company_id, "employee_id": cid,
         "status": "available"},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")
    from services.objstore import read_ref
    pdf = await read_ref(doc.get("file_path") or "")
    if pdf is None:
        raise HTTPException(404, "Arquivo do holerite indisponível.")
    if not doc.get("viewed_at"):
        await db.payroll_documents.update_one(
            {"id": doc_id, "company_id": company_id},
            {"$set": {"viewed_at": now_iso()}},
        )
    await _audit(doc_id, company_id, "view_collab_public",
                    cid, "collaborator", request)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                f'inline; filename="holerite-{doc["competence_year"]}-'
                f'{doc["competence_month"]:02d}.pdf"'
            ),
        },
    )


@router.post("/public/{cid}/{doc_id}/sign-upload")
async def collab_upload_signed(
    cid: str, doc_id: str, request: Request,
    file: UploadFile = File(...),
):
    """Recebe PDF assinado pelo colaborador via gov.br.

    Fluxo:
    1. Colaborador baixou o original.
    2. Acessou https://assinador.iti.br/ e assinou com conta gov.br.
    3. Faz upload aqui do PDF assinado.

    Referências legais (FEB/2026):
    - Lei 14.063/2020 — assinatura "avançada" gov.br vale para relação
      empregado-empregador.
    - STJ reconhece validade para holerites.
    """
    company_id = await _company_for_collab(cid)
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": company_id, "employee_id": cid,
         "status": "available"},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")

    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "Arquivo maior que 10MB.")
    if not data[:5].startswith(b"%PDF-"):
        raise HTTPException(400, "Arquivo não é PDF válido.")

    sig_detected = _has_pdf_signature(data)
    hash_signed = _sha256_bytes(data)

    fname = f"{doc_id}_signed_{uuid.uuid4().hex[:8]}.pdf"
    from services.objstore import put_object
    signed_ref = await put_object(
        f"smartprov/holerites/{company_id}/signed/{fname}",
        data, "application/pdf")

    col = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "name": 1},
    )
    update = {
        "signed_at": now_iso(),
        "signed_method": "govbr_manual_upload",
        "signed_by": cid,
        "signed_by_name": (col or {}).get("name") or "—",
        "signed_file_path": signed_ref,
        "signed_file_size_bytes": len(data),
        "signature_hash": hash_signed,
        "signature_valid": bool(sig_detected),
    }
    await db.payroll_documents.update_one(
        {"id": doc_id, "company_id": company_id},
        {"$set": update},
    )
    await _audit(
        doc_id, company_id, "sign_upload", cid, "collaborator", request,
        extra={
            "size_bytes": len(data),
            "signature_detected": sig_detected,
            "hash": hash_signed[:16] + "...",
        },
    )
    return {
        "ok": True,
        "doc_id": doc_id,
        "signature_valid": bool(sig_detected),
        "signature_hash": hash_signed,
        "signed_at": update["signed_at"],
        "warning": (
            None if sig_detected else
            "PDF não contém marcadores de assinatura digital detectáveis. "
            "Foi salvo, mas verifique se foi mesmo assinado via gov.br."
        ),
    }


@router.get("/public/{cid}/{doc_id}/signed-file")
async def collab_get_signed_file(cid: str, doc_id: str, request: Request):
    """Stream do PDF ASSINADO pelo colaborador."""
    company_id = await _company_for_collab(cid)
    doc = await db.payroll_documents.find_one(
        {"id": doc_id, "company_id": company_id, "employee_id": cid},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Holerite não encontrado.")
    from services.objstore import read_ref
    pdf = await read_ref(doc.get("signed_file_path") or "")
    if pdf is None:
        raise HTTPException(404, "Holerite ainda não foi assinado.")
    await _audit(
        doc_id, company_id, "view_signed", cid, "collaborator", request,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                f'inline; filename="holerite-assinado-'
                f'{doc["competence_year"]}-'
                f'{doc["competence_month"]:02d}.pdf"'
            ),
        },
    )

