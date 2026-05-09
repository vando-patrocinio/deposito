"""Integração com Atlaz (sistema SaaS de gestão de provedores de internet/ISP).

Tudo é configurável via Settings — base URL, paths dos endpoints, mapeamento
de tipos, filiais. Isso permite que o cliente preencha sua doc real do Atlaz
sem precisar tocar no código.

Fluxos:
  • PULL periódico: busca OSs novas do Atlaz e cria bolhas na Lousa
  • PUSH na finalização: ao encerrar/cancelar/reagendar bolha vinda do Atlaz,
    envia baixa de volta para a API (best-effort, com retry simples)

DB:
  • atlaz_config (singleton por company_id) — config completa da integração
  • atlaz_sync_logs — auditoria de cada sincronização
  • tickets ganha campos atlaz_external_id, atlaz_filial, atlaz_synced_at,
    atlaz_pushed (status do push de baixa)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.atlaz")
router = APIRouter(prefix="/api/atlaz", tags=["atlaz"])


# -------------------------------------------------------------------------
# Models (config + payloads)
# -------------------------------------------------------------------------
DEFAULT_TYPE_MAP: Dict[str, str] = {
    "REPARO": "reparo",
    "INSTALACAO": "instalacao",
    "INSTALAÇÃO": "instalacao",
    "RETIRADA": "retirada",
    "PREVENTIVA": "preventiva",
    "VENDA": "venda",
    "PRIORIDADE": "prioridade",
}

DEFAULT_FIELD_MAP: Dict[str, str] = {
    "id": "id",
    "client_name": "cliente_nome",
    "address": "endereco",
    "neighborhood": "bairro",
    "phone": "telefone",
    "type": "tipo_servico",
    "scheduled_time": "data_agendamento",
    "relato": "observacoes",
    "filial": "filial",
}


class AtlazConfig(BaseModel):
    """Configuração da integração Atlaz por empresa."""
    enabled: bool = False
    base_url: str = "https://ligofibra.atlaz.com.br/api/v1"
    api_key: Optional[str] = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "  # prefixo aplicado antes da chave (ex: "Bearer ")
    # Path templates (compatíveis com .format(filial=..., id=..., status=...))
    list_path: str = "/ordens-servico"
    list_query_status: str = "aberta"  # status filtrado no GET ?status=
    close_path: str = "/ordens-servico/{id}/concluir"
    cancel_path: str = "/ordens-servico/{id}/cancelar"
    reschedule_path: str = "/ordens-servico/{id}/reagendar"
    # Mapeamento de filiais → colaborador padrão (opcional)
    # Ex.: {"FILIAL_CENTRO": "col-001", "FILIAL_NORTE": "col-002"}
    filial_to_collaborator: Dict[str, str] = Field(default_factory=dict)
    # Filiais a sincronizar (lista de nomes). Se vazio, busca todas.
    filiais: List[str] = Field(default_factory=list)
    # Mapeamento de tipos do Atlaz → tipos internos
    type_map: Dict[str, str] = Field(default_factory=lambda: DEFAULT_TYPE_MAP.copy())
    # Mapeamento de campos do JSON do Atlaz → campos internos
    field_map: Dict[str, str] = Field(default_factory=lambda: DEFAULT_FIELD_MAP.copy())
    # Sync periódico
    sync_interval_minutes: int = Field(default=10, ge=1, le=1440)
    auto_create_bubbles: bool = True
    auto_push_on_close: bool = True
    timeout_seconds: int = Field(default=15, ge=2, le=120)


class AtlazConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: Optional[str] = None
    api_key_prefix: Optional[str] = None
    list_path: Optional[str] = None
    list_query_status: Optional[str] = None
    close_path: Optional[str] = None
    cancel_path: Optional[str] = None
    reschedule_path: Optional[str] = None
    filial_to_collaborator: Optional[Dict[str, str]] = None
    filiais: Optional[List[str]] = None
    type_map: Optional[Dict[str, str]] = None
    field_map: Optional[Dict[str, str]] = None
    sync_interval_minutes: Optional[int] = None
    auto_create_bubbles: Optional[bool] = None
    auto_push_on_close: Optional[bool] = None
    timeout_seconds: Optional[int] = None


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
async def _get_config(company_id: str) -> AtlazConfig:
    """Lê config atual da empresa; cria default se não existir."""
    raw = await db.atlaz_config.find_one({"company_id": company_id}, {"_id": 0})
    if not raw:
        return AtlazConfig()
    raw.pop("company_id", None)
    return AtlazConfig(**raw)


async def _save_config(company_id: str, cfg: AtlazConfig) -> None:
    doc = cfg.model_dump()
    doc["company_id"] = company_id
    doc["updated_at"] = now_iso()
    await db.atlaz_config.update_one(
        {"company_id": company_id},
        {"$set": doc},
        upsert=True,
    )


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


def _public_config(cfg: AtlazConfig) -> Dict[str, Any]:
    """Versão para o frontend — chave mascarada."""
    d = cfg.model_dump()
    d["api_key"] = _mask_key(d.get("api_key"))
    d["api_key_set"] = bool(cfg.api_key)
    return d


def _build_url(base: str, path: str, **kwargs) -> str:
    base = (base or "").rstrip("/")
    formatted = path.format(**kwargs) if kwargs else path
    if not formatted.startswith("/"):
        formatted = "/" + formatted
    return base + formatted


def _http_headers(cfg: AtlazConfig) -> Dict[str, str]:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if cfg.api_key:
        header_name = cfg.api_key_header or "Authorization"
        prefix = cfg.api_key_prefix or ""
        h[header_name] = f"{prefix}{cfg.api_key}"
    return h


async def _log_sync(
    company_id: str, event: str, status: str,
    details: str = "", payload: Optional[Dict[str, Any]] = None,
) -> None:
    await db.atlaz_sync_logs.insert_one({
        "id": f"as-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "event": event,        # test|pull|push_close|push_cancel|push_reschedule
        "status": status,      # ok|error|partial
        "details": details[:600],
        "payload": payload,
        "at": now_iso(),
    })


def _normalize_type(raw_type: Any, type_map: Dict[str, str]) -> str:
    """Mapeia o tipo cru do Atlaz para um TicketType interno válido."""
    if raw_type is None:
        return "reparo"
    s = str(raw_type).strip().upper()
    return type_map.get(s) or type_map.get(s.replace(" ", "_")) or "reparo"


def _get_field(item: Dict[str, Any], internal: str, field_map: Dict[str, str]) -> Any:
    """Lê um campo do JSON do Atlaz pelo nome mapeado."""
    src = field_map.get(internal, internal)
    return item.get(src)


# -------------------------------------------------------------------------
# Pull (GET ordens) e mapeamento → ticket interno
# -------------------------------------------------------------------------
async def _fetch_orders(cfg: AtlazConfig, filial: Optional[str] = None) -> List[Dict[str, Any]]:
    url = _build_url(cfg.base_url, cfg.list_path)
    params: Dict[str, Any] = {}
    if cfg.list_query_status:
        params["status"] = cfg.list_query_status
    if filial:
        params["filial"] = filial

    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.get(url, headers=_http_headers(cfg), params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()

    # Aceita 3 shapes comuns: lista pura, {items:[]}, {data:[]}, {results:[]}
    if isinstance(data, list):
        return data
    for key in ("items", "data", "results", "ordens", "ordens_servico"):
        v = data.get(key) if isinstance(data, dict) else None
        if isinstance(v, list):
            return v
    raise RuntimeError(f"Resposta inesperada do Atlaz (não é lista): {str(data)[:200]}")


async def _import_one(
    item: Dict[str, Any], cfg: AtlazConfig, company_id: str, default_filial: Optional[str],
) -> str:
    """Importa 1 OS do Atlaz como bolha local. Retorna 'created'|'skipped'|'updated'."""
    fmap = cfg.field_map or DEFAULT_FIELD_MAP
    ext_id = _get_field(item, "id", fmap)
    if ext_id is None:
        raise ValueError("OS sem ID no Atlaz")
    ext_id = str(ext_id)

    # Dedupe por atlaz_external_id
    existing = await db.tickets.find_one(
        {"company_id": company_id, "atlaz_external_id": ext_id},
        {"_id": 0, "id": 1, "status": 1},
    )
    if existing:
        return "skipped"

    raw_type = _get_field(item, "type", fmap)
    ticket_type = _normalize_type(raw_type, cfg.type_map or DEFAULT_TYPE_MAP)
    filial = _get_field(item, "filial", fmap) or default_filial

    # Resolve colaborador: filial → collaborator default
    assigned = (cfg.filial_to_collaborator or {}).get(filial or "")
    if not assigned:
        # Pega 1° colaborador ativo da empresa como fallback
        any_coll = await db.collaborators.find_one(
            {"company_id": company_id, "active": {"$ne": False}},
            {"_id": 0, "id": 1},
        )
        assigned = any_coll["id"] if any_coll else None
    if not assigned:
        raise ValueError(f"Sem colaborador disponível para filial '{filial}'")

    doc = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": str(_get_field(item, "client_name", fmap) or "Cliente Atlaz"),
            "address": str(_get_field(item, "address", fmap) or ""),
            "neighborhood": str(_get_field(item, "neighborhood", fmap) or ""),
            "phone": str(_get_field(item, "phone", fmap) or ""),
            "latitude": None, "longitude": None,
            "relato": str(_get_field(item, "relato", fmap) or ""),
            "test_history": [],
        },
        "type": ticket_type,
        "priority": "normal",
        "scheduled_time": _get_field(item, "scheduled_time", fmap),
        "position": 0,
        "status": "pendente",
        "assigned_collaborator_id": assigned,
        "company_id": company_id,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "created_at": now_iso(),
        # Atlaz
        "atlaz_external_id": ext_id,
        "atlaz_filial": filial,
        "atlaz_synced_at": now_iso(),
    }
    await db.tickets.insert_one(doc)
    return "created"


async def run_sync(company_id: str, cfg: Optional[AtlazConfig] = None) -> Dict[str, Any]:
    """Executa pull para todas as filiais configuradas. Retorna sumário."""
    cfg = cfg or await _get_config(company_id)
    if not cfg.enabled:
        return {"ok": False, "reason": "disabled", "created": 0, "skipped": 0, "errors": []}
    if not cfg.api_key or not cfg.base_url:
        return {"ok": False, "reason": "missing_config", "created": 0, "skipped": 0, "errors": []}

    summary = {"created": 0, "skipped": 0, "errors": []}
    filiais = cfg.filiais or [None]  # None = sem filtro de filial

    for fil in filiais:
        try:
            items = await _fetch_orders(cfg, fil)
        except Exception as e:
            msg = f"filial={fil} fetch falhou: {e}"
            summary["errors"].append(msg)
            await _log_sync(company_id, "pull", "error", msg)
            continue

        for it in items:
            try:
                if cfg.auto_create_bubbles:
                    res = await _import_one(it, cfg, company_id, fil)
                    if res == "created":
                        summary["created"] += 1
                    else:
                        summary["skipped"] += 1
                else:
                    summary["skipped"] += 1
            except Exception as e:
                summary["errors"].append(f"item={it.get('id', '?')}: {e}")

    status = "ok" if not summary["errors"] else ("partial" if summary["created"] else "error")
    await _log_sync(
        company_id, "pull", status,
        f"created={summary['created']} skipped={summary['skipped']} errors={len(summary['errors'])}",
        summary,
    )
    return {"ok": True, **summary}


# -------------------------------------------------------------------------
# Push (dar baixa)
# -------------------------------------------------------------------------
async def push_close(ticket: Dict[str, Any], action: str, notes: Optional[str] = None,
                     new_scheduled_time: Optional[str] = None) -> Dict[str, Any]:
    """Envia baixa para o Atlaz. action ∈ {'encerrar','cancelar','reagendar'}.
    Best-effort — se falhar, registra log mas não levanta exceção (não bloqueia
    o fluxo do gestor na nossa app).
    """
    company_id = ticket.get("company_id") or DEMO_COMPANY_ID
    ext_id = ticket.get("atlaz_external_id")
    if not ext_id:
        return {"ok": False, "reason": "not_atlaz_ticket"}

    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.auto_push_on_close or not cfg.api_key:
        return {"ok": False, "reason": "disabled_or_missing"}

    if action == "encerrar":
        path_tpl = cfg.close_path
        body = {"status": "CONCLUIDA", "observacoes": notes or "", "data_conclusao": now_iso()}
    elif action == "cancelar":
        path_tpl = cfg.cancel_path
        body = {"status": "CANCELADA", "motivo": notes or ""}
    elif action == "reagendar":
        path_tpl = cfg.reschedule_path
        body = {
            "status": "REAGENDADA",
            "nova_data": new_scheduled_time,
            "motivo": notes or "",
        }
    else:
        return {"ok": False, "reason": "unknown_action"}

    url = _build_url(cfg.base_url, path_tpl, id=ext_id)
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            r = await client.post(url, headers=_http_headers(cfg), json=body)
        ok = r.status_code < 400
        push_status = "ok" if ok else f"http_{r.status_code}"
        await db.tickets.update_one(
            {"id": ticket["id"]},
            {"$set": {"atlaz_pushed": push_status, "atlaz_pushed_at": now_iso()}},
        )
        await _log_sync(
            company_id, f"push_{action}", "ok" if ok else "error",
            f"ext_id={ext_id} status={r.status_code} body={r.text[:200]}",
        )
        return {"ok": ok, "status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        await db.tickets.update_one(
            {"id": ticket["id"]},
            {"$set": {"atlaz_pushed": "error", "atlaz_pushed_at": now_iso()}},
        )
        await _log_sync(company_id, f"push_{action}", "error", f"ext_id={ext_id}: {e}")
        return {"ok": False, "error": str(e)[:200]}


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------
@router.get("/settings")
async def get_atlaz_settings(user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    return _public_config(cfg)


@router.put("/settings")
async def put_atlaz_settings(payload: AtlazConfigUpdate,
                             user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    current = await _get_config(company_id)
    update_dict = payload.model_dump(exclude_unset=True)
    # api_key vazio significa "não alterar"; só persiste se vier não-vazio
    if update_dict.get("api_key") == "":
        update_dict.pop("api_key", None)
    new_cfg = current.model_copy(update=update_dict)
    await _save_config(company_id, new_cfg)
    return _public_config(new_cfg)


@router.post("/test-connection")
async def test_connection(user: dict = Depends(require_role("gestor"))):
    """Faz um GET no list_path com filiais[0] (ou sem filtro) e devolve status."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    if not cfg.api_key:
        return {"ok": False, "reason": "missing_api_key"}
    if not cfg.base_url:
        return {"ok": False, "reason": "missing_base_url"}

    url = _build_url(cfg.base_url, cfg.list_path)
    params = {"status": cfg.list_query_status} if cfg.list_query_status else {}
    if cfg.filiais:
        params["filial"] = cfg.filiais[0]

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            r = await client.get(url, headers=_http_headers(cfg), params=params)
        body_preview = r.text[:300]
        ok = r.status_code < 400

        # Diagnóstico amigável
        diagnosis = None
        if r.status_code == 401:
            diagnosis = "Token rejeitado. Verifique: (a) a chave está correta; (b) header de auth está certo (default agora é 'Authorization' com prefixo 'Bearer ')."
        elif r.status_code == 403:
            diagnosis = "Token válido mas sem permissão para esta rota. Confirme com o suporte do Atlaz se a sua chave tem escopo para listar OSs."
        elif r.status_code == 404:
            try:
                j = r.json()
                if "could not be found" in (j.get("message") or ""):
                    diagnosis = (
                        f"Auth funcionou, mas a rota '{cfg.list_path}' NÃO existe na API. "
                        "Você precisa descobrir o path correto. Use F12 → Network no painel web do Atlaz "
                        "(em uma tela de OSs) e copie o path da chamada que aparece. Cole ele em 'Path para listar OSs'."
                    )
            except Exception:
                pass
            if not diagnosis:
                diagnosis = "Rota não encontrada (404). O auth pode estar OK — verifique o path em 'Path para listar OSs'."
        elif r.status_code == 405:
            diagnosis = "Método HTTP errado. A API espera POST em vez de GET para esta rota. Contate o suporte para confirmar."

        await _log_sync(
            company_id, "test", "ok" if ok else "error",
            f"GET {url} → {r.status_code} | {body_preview[:200]}",
        )
        # Tenta detectar quantos itens vieram (ajuda o gestor a saber se field_map está OK)
        sample_count = None
        sample_keys: List[str] = []
        try:
            data = r.json()
            if isinstance(data, list):
                sample_count = len(data)
                if data and isinstance(data[0], dict):
                    sample_keys = list(data[0].keys())[:20]
            elif isinstance(data, dict):
                for k in ("items", "data", "results", "ordens", "ordens_servico"):
                    if isinstance(data.get(k), list):
                        sample_count = len(data[k])
                        if data[k] and isinstance(data[k][0], dict):
                            sample_keys = list(data[k][0].keys())[:20]
                        break
        except Exception:
            pass
        return {
            "ok": ok,
            "status": r.status_code,
            "url": url,
            "params": params,
            "body_preview": body_preview,
            "sample_count": sample_count,
            "sample_keys": sample_keys,
            "diagnosis": diagnosis,
        }
    except Exception as e:
        await _log_sync(company_id, "test", "error", f"GET {url}: {e}")
        return {"ok": False, "error": str(e)[:300], "url": url}


@router.post("/sync-now")
async def sync_now(user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await run_sync(company_id)


@router.get("/sync-logs")
async def sync_logs(limit: int = 30, user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.atlaz_sync_logs.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("at", -1).limit(min(limit, 200))
    items = await cur.to_list(min(limit, 200))
    return {"items": items, "count": len(items)}


# -------------------------------------------------------------------------
# Worker periódico — startado pelo server.py no startup
# -------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None
_worker_stop = asyncio.Event()


async def _worker_loop():
    """Verifica a cada minuto quais empresas precisam sincronizar (por
    sync_interval_minutes) e dispara run_sync. Nunca derruba se uma falhar.
    """
    logger.info("[atlaz] worker started")
    last_run: Dict[str, datetime] = {}
    while not _worker_stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            cursor = db.atlaz_config.find({"enabled": True}, {"_id": 0})
            async for cfg_doc in cursor:
                cid = cfg_doc.get("company_id")
                if not cid:
                    continue
                interval = int(cfg_doc.get("sync_interval_minutes") or 10)
                last = last_run.get(cid)
                if last and (now - last).total_seconds() < interval * 60:
                    continue
                try:
                    cfg = AtlazConfig(**{k: v for k, v in cfg_doc.items() if k != "company_id" and k != "updated_at"})
                    await run_sync(cid, cfg)
                except Exception as e:
                    logger.exception("[atlaz] sync falhou para %s: %s", cid, e)
                last_run[cid] = now
        except Exception as e:
            logger.exception("[atlaz] worker tick falhou: %s", e)
        try:
            await asyncio.wait_for(_worker_stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("[atlaz] worker stopped")


def start_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_stop.clear()
    _worker_task = asyncio.create_task(_worker_loop())


def stop_worker() -> None:
    _worker_stop.set()
