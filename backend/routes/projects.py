"""projects.py — Acompanhamento de trabalho, execução e finalização.

Kanban-style boards inspirados em Trello/Linear/ClickUp + best practices
da indústria fiber/telecom (Splynx Field Service, Procore, Fieldwire).

Modelo de dados:
  - `projects`: documento por projeto/tarefa, com colunas Kanban.
  - `project_files`: arquivos anexos (PDF/DOC/imagem) — separado para não
    inflar o documento principal e simplificar download streaming.

Status (colunas do Kanban):
  - `backlog`     — a iniciar (default)
  - `em_andamento`— execução em campo
  - `em_revisao`  — entregue, aguardando validação
  - `finalizado`  — concluído

Endpoints:
  - GET    /api/projects                — lista + filtros
  - POST   /api/projects                — cria
  - GET    /api/projects/{id}           — detalhe + lista de files
  - PATCH  /api/projects/{id}           — atualiza qualquer campo (move col, edita)
  - DELETE /api/projects/{id}           — remove (com arquivos)
  - POST   /api/projects/{id}/files     — upload arquivo (PDF/DOC/IMG)
  - GET    /api/projects/{id}/files/{file_id}/download
  - DELETE /api/projects/{id}/files/{file_id}
  - GET    /api/projects/stats          — KPIs (contagens por status/prioridade)

Permissões:
  - Listagem/leitura: gestor, auditor, administrador, colaborador (próprio)
  - Criação/edição/exclusão: gestor, administrador, auditor + super_admin
  - Colaborador: leitura (próprio) + comentários (futuro)
"""
from __future__ import annotations

import base64
import io
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db

logger = logging.getLogger("ponto.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Status possíveis (colunas Kanban). A ordem aqui é a ordem de exibição.
PROJECT_STATUSES = ["backlog", "em_andamento", "em_revisao", "finalizado"]
PROJECT_PRIORITIES = ["baixa", "media", "alta", "critica"]

# Limite de upload por arquivo (10 MB). PDFs/DOCs de laudo fotográfico
# costumam ficar nessa faixa.
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats",
    "image/",
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class ProjectIn(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Optional[str] = "backlog"
    priority: Optional[str] = "media"
    tags: List[str] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ProjectPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    assignees: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ChecklistItemIn(BaseModel):
    text: str


class ChecklistItemPatch(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None


def _require_manager(user: dict):
    """Permissão de gerenciamento do módulo Acompanhamento/Kanban.

    Roles permitidas: gestor, administrador, auditor (perfil de
    fiscalização/gestão cross-tenant no SmartProv) + super_admin
    (flag DB ou via env `SUPER_ADMIN_EMAILS`).
    """
    if user.get("role") in ("gestor", "administrador", "auditor"):
        return
    if is_super_admin(user):
        return
    raise HTTPException(403, "Apenas gestor/administrador/auditor.")


# ---------------------------------------------------------------------------
# Activity feed — timeline auditável de cada projeto
# ---------------------------------------------------------------------------
async def _log_activity(project_id: str, company_id: str, atype: str,
                              actor: dict, message: str,
                              meta: Optional[dict] = None) -> None:
    """Grava 1 evento no feed `project_activity`. Best-effort: nunca quebra
    a operação principal se a coleção/insert falhar."""
    try:
        await db.project_activity.insert_one({
            "id": f"act-{uuid.uuid4().hex[:10]}",
            "project_id": project_id,
            "company_id": company_id,
            "type": atype,  # created|status_changed|edited|checklist_added|
                              # checklist_done|checklist_undone|checklist_removed|
                              # file_uploaded|file_removed|deleted
            "message": message,
            "meta": meta or {},
            "actor_email": (actor or {}).get("email"),
            "actor_name": (actor or {}).get("name"),
            "ts": now_iso(),
        })
    except Exception as e:
        logger.warning("[projects] log_activity fail: %s", e)


def _normalize_project(p: dict) -> dict:
    """Garante campos default e exclui _id antes de retornar."""
    p.pop("_id", None)
    p.setdefault("description", "")
    p.setdefault("priority", "media")
    p.setdefault("tags", [])
    p.setdefault("assignees", [])
    p.setdefault("files_count", 0)
    cl = p.get("checklist") or []
    p["checklist"] = cl
    done = sum(1 for it in cl if it.get("done"))
    p["checklist_progress"] = {
        "done": done, "total": len(cl),
        "pct": round(done / len(cl) * 100) if cl else 0,
    }
    return p


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_projects(
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Lista projetos da empresa do usuário, com filtros opcionais."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        if status not in PROJECT_STATUSES:
            raise HTTPException(400, f"Status inválido: {status}")
        q["status"] = status
    if priority:
        q["priority"] = priority
    if assignee:
        q["assignees"] = assignee
    docs = await db.projects.find(q, {"_id": 0}) \
        .sort([("status", 1), ("created_at", -1)]).to_list(2000)
    return {"items": [_normalize_project(d) for d in docs], "count": len(docs)}


@router.post("", status_code=201)
async def create_project(payload: ProjectIn,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    if not (payload.title or "").strip():
        raise HTTPException(400, "Título obrigatório.")
    status = payload.status or "backlog"
    if status not in PROJECT_STATUSES:
        raise HTTPException(400, f"Status inválido: {status}")
    priority = payload.priority or "media"
    if priority not in PROJECT_PRIORITIES:
        raise HTTPException(400, f"Prioridade inválida: {priority}")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "id": f"prj-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "title": payload.title.strip(),
        "description": (payload.description or "").strip(),
        "status": status,
        "priority": priority,
        "tags": payload.tags or [],
        "assignees": payload.assignees or [],
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "files_count": 0,
        "created_at": now_iso(),
        "created_by": user.get("email"),
        "created_by_name": user.get("name"),
        "updated_at": now_iso(),
    }
    await db.projects.insert_one(dict(doc))
    await _log_activity(
        doc["id"], cid, "created", user,
        f"Projeto criado: {doc['title']}",
        {"title": doc["title"], "status": doc["status"],
          "priority": doc["priority"]},
    )
    return _normalize_project(doc)


@router.get("/stats")
async def project_stats(user: dict = Depends(get_current_user)):
    """KPIs para o header do Kanban: contagens por status e por prioridade."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    by_status = {s: 0 for s in PROJECT_STATUSES}
    by_priority = {p: 0 for p in PROJECT_PRIORITIES}
    async for d in db.projects.find(
            {"company_id": cid},
            {"_id": 0, "status": 1, "priority": 1}):
        by_status[d.get("status", "backlog")] = \
            by_status.get(d.get("status", "backlog"), 0) + 1
        by_priority[d.get("priority", "media")] = \
            by_priority.get(d.get("priority", "media"), 0) + 1
    total = sum(by_status.values())
    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "completed_pct": (
            round(by_status["finalizado"] / total * 100, 1) if total else 0
        ),
    }


@router.get("/{project_id}")
async def get_project(project_id: str,
                          user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await db.projects.find_one(
        {"id": project_id, "company_id": cid}, {"_id": 0},
    )
    if not p:
        raise HTTPException(404, "Projeto não encontrado.")
    # Inclui meta dos arquivos (sem o blob)
    files = await db.project_files.find(
        {"project_id": project_id, "company_id": cid},
        {"_id": 0, "id": 1, "filename": 1, "mime": 1, "size": 1,
          "uploaded_at": 1, "uploaded_by_name": 1},
    ).sort("uploaded_at", -1).to_list(500)
    p["files"] = files
    p["files_count"] = len(files)
    return _normalize_project(p)


@router.patch("/{project_id}")
async def patch_project(project_id: str, payload: ProjectPatch,
                            user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update: Dict[str, Any] = {"updated_at": now_iso()}
    fields = payload.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in PROJECT_STATUSES:
        raise HTTPException(400, "Status inválido.")
    if "priority" in fields and fields["priority"] not in PROJECT_PRIORITIES:
        raise HTTPException(400, "Prioridade inválida.")
    update.update(fields)
    # Snapshot anterior para diff (status / priority)
    before = await db.projects.find_one(
        {"id": project_id, "company_id": cid},
        {"_id": 0, "status": 1, "priority": 1, "title": 1},
    ) or {}
    r = await db.projects.update_one(
        {"id": project_id, "company_id": cid}, {"$set": update})
    if not r.matched_count:
        raise HTTPException(404, "Projeto não encontrado.")
    # Activity log — diferencia mudança de status vs edição genérica
    if "status" in fields and fields["status"] != before.get("status"):
        await _log_activity(
            project_id, cid, "status_changed", user,
            f"Status alterado: {before.get('status', '?')} → {fields['status']}",
            {"from": before.get("status"), "to": fields["status"]},
        )
    else:
        edited = [k for k in fields if k != "status"]
        if edited:
            await _log_activity(
                project_id, cid, "edited", user,
                f"Campos editados: {', '.join(edited)}",
                {"fields": edited},
            )
    return await get_project(project_id, user)


@router.delete("/{project_id}", status_code=200)
async def delete_project(project_id: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.projects.delete_one(
        {"id": project_id, "company_id": cid})
    if not r.deleted_count:
        raise HTTPException(404, "Projeto não encontrado.")
    # Cleanup dos arquivos e activity feed
    fr = await db.project_files.delete_many(
        {"project_id": project_id, "company_id": cid})
    await db.project_activity.delete_many(
        {"project_id": project_id, "company_id": cid})
    return {"ok": True, "files_removed": fr.deleted_count}


# ---------------------------------------------------------------------------
# Checklist (subtarefas dentro do projeto)
# ---------------------------------------------------------------------------
@router.post("/{project_id}/checklist", status_code=201)
async def add_checklist_item(project_id: str, payload: ChecklistItemIn,
                                  user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "Texto obrigatório.")
    item = {
        "id": f"ck-{uuid.uuid4().hex[:8]}",
        "text": text,
        "done": False,
        "created_at": now_iso(),
        "created_by_name": user.get("name"),
    }
    r = await db.projects.update_one(
        {"id": project_id, "company_id": cid},
        {"$push": {"checklist": item}, "$set": {"updated_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Projeto não encontrado.")
    await _log_activity(
        project_id, cid, "checklist_added", user,
        f"Subtarefa adicionada: {text}",
        {"item_id": item["id"], "text": text},
    )
    return item


@router.patch("/{project_id}/checklist/{item_id}")
async def patch_checklist_item(project_id: str, item_id: str,
                                    payload: ChecklistItemPatch,
                                    user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update: Dict[str, Any] = {"updated_at": now_iso()}
    fields = payload.model_dump(exclude_unset=True)
    if "text" in fields:
        update["checklist.$.text"] = fields["text"]
    if "done" in fields:
        update["checklist.$.done"] = bool(fields["done"])
        if fields["done"]:
            update["checklist.$.done_at"] = now_iso()
            update["checklist.$.done_by_name"] = user.get("name")
        else:
            update["checklist.$.done_at"] = None
            update["checklist.$.done_by_name"] = None
    r = await db.projects.update_one(
        {"id": project_id, "company_id": cid, "checklist.id": item_id},
        {"$set": update},
    )
    if not r.matched_count:
        raise HTTPException(404, "Item não encontrado.")
    # Activity — concluir/desfazer + edição de texto
    if "done" in fields:
        # Busca o texto pra colocar na mensagem
        proj = await db.projects.find_one(
            {"id": project_id, "company_id": cid},
            {"_id": 0, "checklist": 1},
        ) or {}
        cl = next((it for it in (proj.get("checklist") or [])
                      if it.get("id") == item_id), {})
        txt = cl.get("text", "")
        if fields["done"]:
            await _log_activity(
                project_id, cid, "checklist_done", user,
                f"Subtarefa concluída: {txt}",
                {"item_id": item_id, "text": txt},
            )
        else:
            await _log_activity(
                project_id, cid, "checklist_undone", user,
                f"Subtarefa reaberta: {txt}",
                {"item_id": item_id, "text": txt},
            )
    return {"ok": True}


@router.delete("/{project_id}/checklist/{item_id}", status_code=200)
async def delete_checklist_item(project_id: str, item_id: str,
                                      user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Busca o texto antes do pull pra log
    proj = await db.projects.find_one(
        {"id": project_id, "company_id": cid}, {"_id": 0, "checklist": 1}) or {}
    cl = next((it for it in (proj.get("checklist") or [])
                  if it.get("id") == item_id), {})
    r = await db.projects.update_one(
        {"id": project_id, "company_id": cid},
        {"$pull": {"checklist": {"id": item_id}},
          "$set": {"updated_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Projeto não encontrado.")
    await _log_activity(
        project_id, cid, "checklist_removed", user,
        f"Subtarefa removida: {cl.get('text', '?')}",
        {"item_id": item_id, "text": cl.get("text")},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Arquivos (PDF / DOC / imagens)
# ---------------------------------------------------------------------------
@router.post("/{project_id}/files", status_code=201)
async def upload_file(project_id: str,
                          request: Request,
                          file: UploadFile = File(...),
                          user: dict = Depends(get_current_user)):
    """Upload de PDF / DOC / DOCX / imagem como anexo do projeto."""
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Pre-check via Content-Length: rejeita upload hostil ANTES de ler o
    # body para a RAM. Defesa em profundidade — o check pós-read continua
    # como segundo gate (clientes podem mentir no header).
    cl = request.headers.get("content-length")
    if cl:
        try:
            cl_int = int(cl)
            if cl_int > MAX_FILE_SIZE:
                raise HTTPException(
                    413,
                    f"Arquivo muito grande ({cl_int} bytes, "
                    f"máximo {MAX_FILE_SIZE}).",
                )
        except ValueError:
            pass  # header não numérico: deixa o read-time check pegar
    p = await db.projects.find_one(
        {"id": project_id, "company_id": cid}, {"_id": 0, "id": 1})
    if not p:
        raise HTTPException(404, "Projeto não encontrado.")
    mime = (file.content_type or "").lower()
    if not any(mime.startswith(m) for m in ALLOWED_MIME_PREFIXES):
        raise HTTPException(400,
            "Tipo de arquivo inválido. Envie PDF, DOC, DOCX ou imagem.")
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413,
            f"Arquivo muito grande ({len(data)} bytes, "
            f"máximo {MAX_FILE_SIZE}).")
    file_id = f"pfl-{uuid.uuid4().hex[:10]}"
    encoded = base64.b64encode(data).decode("ascii")
    doc = {
        "id": file_id,
        "project_id": project_id,
        "company_id": cid,
        "filename": file.filename or "arquivo",
        "mime": mime or "application/octet-stream",
        "size": len(data),
        "data_b64": encoded,
        "uploaded_at": now_iso(),
        "uploaded_by": user.get("email"),
        "uploaded_by_name": user.get("name"),
    }
    await db.project_files.insert_one(dict(doc))
    await db.projects.update_one(
        {"id": project_id, "company_id": cid},
        {"$inc": {"files_count": 1}, "$set": {"updated_at": now_iso()}},
    )
    await _log_activity(
        project_id, cid, "file_uploaded", user,
        f"Arquivo anexado: {doc['filename']}",
        {"file_id": file_id, "filename": doc["filename"],
          "size": len(data), "mime": doc["mime"]},
    )
    return {
        "id": file_id, "filename": doc["filename"],
        "mime": doc["mime"], "size": doc["size"],
        "uploaded_at": doc["uploaded_at"],
        "uploaded_by_name": doc["uploaded_by_name"],
    }


@router.get("/{project_id}/files/{file_id}/download")
async def download_file(project_id: str, file_id: str,
                              user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    f = await db.project_files.find_one(
        {"id": file_id, "project_id": project_id, "company_id": cid},
        {"_id": 0},
    )
    if not f:
        raise HTTPException(404, "Arquivo não encontrado.")
    raw = base64.b64decode(f.get("data_b64", ""))
    return StreamingResponse(
        io.BytesIO(raw),
        media_type=f.get("mime", "application/octet-stream"),
        headers={
            "Content-Disposition":
                f'attachment; filename="{f.get("filename", "arquivo")}"',
        },
    )


@router.delete("/{project_id}/files/{file_id}", status_code=200)
async def delete_file(project_id: str, file_id: str,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    f = await db.project_files.find_one(
        {"id": file_id, "project_id": project_id, "company_id": cid},
        {"_id": 0, "filename": 1},
    ) or {}
    r = await db.project_files.delete_one(
        {"id": file_id, "project_id": project_id, "company_id": cid})
    if not r.deleted_count:
        raise HTTPException(404, "Arquivo não encontrado.")
    await db.projects.update_one(
        {"id": project_id, "company_id": cid},
        {"$inc": {"files_count": -1}, "$set": {"updated_at": now_iso()}},
    )
    await _log_activity(
        project_id, cid, "file_removed", user,
        f"Arquivo removido: {f.get('filename', '?')}",
        {"file_id": file_id, "filename": f.get("filename")},
    )
    return {"ok": True}


@router.get("/{project_id}/activity")
async def get_activity(project_id: str, limit: int = 100,
                            user: dict = Depends(get_current_user)):
    """Timeline cronológica de eventos do projeto.

    Retorna eventos do mais recente ao mais antigo. Útil para
    auditoria (cliente questionar tempo gasto em cada etapa).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Verifica que o projeto existe pra evitar fishing
    p = await db.projects.find_one(
        {"id": project_id, "company_id": cid},
        {"_id": 0, "id": 1},
    )
    if not p:
        raise HTTPException(404, "Projeto não encontrado.")
    items = await db.project_activity.find(
        {"project_id": project_id, "company_id": cid},
        {"_id": 0},
    ).sort("ts", -1).limit(min(max(limit, 1), 500)).to_list(500)
    return {"items": items, "count": len(items)}
