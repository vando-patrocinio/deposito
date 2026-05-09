"""Integração com a API oficial Atlaz V2 (https://app.atlaz.com.br/api/v2).

Doc oficial: https://app.atlaz.com.br/docs/api

⚠ LIMITAÇÕES da API Atlaz V2:
  • Auth via querystring `?token=...` (não Bearer, não X-API-Key)
  • Apenas GET /listachamados e POST /criarchamado para chamados
  • NÃO HÁ endpoint para fechar/cancelar/reagendar — gestor faz isso
    manualmente no painel web do Atlaz após terminar na nossa Lousa
  • data_criacao_inicio é OBRIGATÓRIO em /listachamados

Fluxos suportados:
  • PULL periódico de bolhas: importa chamados abertos como bolhas na Lousa
  • PULL periódico de técnicos: cria/atualiza colaboradores a partir dos
    técnicos listados nos chamados (auto, intervalo > intervalo de bolhas)
  • Filtro por filial: usado nome da cidade (campo ponto.cidade)
  • Mapeamento técnico Atlaz → colaborador interno (por nome)
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.atlaz")
router = APIRouter(prefix="/api/atlaz", tags=["atlaz"])

# Import local (lazy) para evitar ciclo: events.py não depende de atlaz.py.
try:
    from routes.events import publish_event as _publish_event
except Exception:  # pragma: no cover
    _publish_event = None


async def _safe_publish(company_id: str, event: str, data: Dict[str, Any]) -> None:
    """Publica evento SSE — best-effort, não derruba sync se falhar."""
    if not _publish_event:
        return
    try:
        await _publish_event(company_id, event, data)
    except Exception as e:
        logger.warning("[atlaz] publish_event falhou: %s", e)


ATLAZ_BASE_URL = "https://app.atlaz.com.br/api/v2"

# Mapeamento dos TIPOS REAIS retornados pela API Atlaz LIGO FIBRA
DEFAULT_TYPE_MAP: Dict[str, str] = {
    "INSTALACAO": "instalacao",
    "INSTALAÇÃO": "instalacao",
    "RETIRADA DE EQUIPAMENTO": "retirada",
    "VISITA / VISTORIA": "reparo",
    "VISITA/VISTORIA": "reparo",
    "SUPORTE": "reparo",
    "CANCELAMENTO": "retirada",
    "OUTROS": "reparo",
    "REPARO": "reparo",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _normalize_type(raw_type: Any, type_map: Dict[str, str]) -> str:
    if not raw_type:
        return "reparo"
    s = _strip_accents(str(raw_type)).upper().strip()
    return type_map.get(s) or type_map.get(s.replace(" ", "_")) or "reparo"


# -------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------
class AtlazConfig(BaseModel):
    """Configuração da integração Atlaz por empresa."""
    enabled: bool = False
    api_key: Optional[str] = None
    # Domínio do painel web do tenant Atlaz (usado para gerar links "Abrir no Atlaz")
    # Ex.: "https://ligofibra.atlaz.com.br" (sem trailing slash)
    tenant_domain: str = ""
    # Filiais (cidades) a sincronizar. Vazio = todas.
    filiais: List[str] = Field(default_factory=list)
    filial_to_collaborator: Dict[str, str] = Field(default_factory=dict)
    technician_to_collaborator: Dict[str, str] = Field(default_factory=dict)
    type_map: Dict[str, str] = Field(default_factory=lambda: DEFAULT_TYPE_MAP.copy())
    lookback_days: int = Field(default=30, ge=1, le=365)
    sync_interval_minutes: int = Field(default=15, ge=1, le=1440)
    auto_create_bubbles: bool = True
    # NOVO (iter 20): auto-sincronização de técnicos do Atlaz para a aba Colaborador
    auto_sync_technicians: bool = True
    tech_sync_interval_minutes: int = Field(default=60, ge=5, le=1440)
    last_auto_sync_bubbles_at: Optional[str] = None
    last_auto_sync_technicians_at: Optional[str] = None
    # NOVO (iter 22): intervalo em SEGUNDOS — permite sync rápido (default 30s)
    # Quando setado, tem precedência sobre sync_interval_minutes.
    sync_interval_seconds: Optional[int] = Field(default=30, ge=10, le=86400)
    timeout_seconds: int = Field(default=20, ge=2, le=120)


class AtlazConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    tenant_domain: Optional[str] = None
    filiais: Optional[List[str]] = None
    filial_to_collaborator: Optional[Dict[str, str]] = None
    technician_to_collaborator: Optional[Dict[str, str]] = None
    type_map: Optional[Dict[str, str]] = None
    lookback_days: Optional[int] = Field(default=None, ge=1, le=365)
    sync_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    sync_interval_seconds: Optional[int] = Field(default=None, ge=10, le=86400)
    auto_create_bubbles: Optional[bool] = None
    auto_sync_technicians: Optional[bool] = None
    tech_sync_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    timeout_seconds: Optional[int] = Field(default=None, ge=2, le=120)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
async def _get_config(company_id: str) -> AtlazConfig:
    raw = await db.atlaz_config.find_one({"company_id": company_id}, {"_id": 0})
    if not raw:
        return AtlazConfig()
    raw.pop("company_id", None)
    raw.pop("updated_at", None)
    # filtra campos legados que não existem mais no modelo
    valid = set(AtlazConfig.model_fields.keys())
    raw = {k: v for k, v in raw.items() if k in valid}
    try:
        return AtlazConfig(**raw)
    except Exception as e:
        # Auto-cura: documento legado/corrompido no Mongo. Clamp valores fora
        # do range e tenta de novo. Loga o motivo para auditoria.
        logger.warning("[atlaz] config corrompida (%s) — sanitizando para defaults", e)
        defaults = AtlazConfig().model_dump()
        sanitized: Dict[str, Any] = {}
        for k, v in raw.items():
            try:
                AtlazConfig(**{**defaults, k: v})
                sanitized[k] = v
            except Exception:
                sanitized[k] = defaults.get(k)
        clean = AtlazConfig(**{**defaults, **sanitized})
        # Persiste a versão limpa para evitar 500 nos próximos GETs
        await _save_config(company_id, clean)
        return clean


async def _save_config(company_id: str, cfg: AtlazConfig) -> None:
    doc = cfg.model_dump()
    doc["company_id"] = company_id
    doc["updated_at"] = now_iso()
    await db.atlaz_config.update_one(
        {"company_id": company_id}, {"$set": doc}, upsert=True,
    )


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


def _public_config(cfg: AtlazConfig) -> Dict[str, Any]:
    d = cfg.model_dump()
    d["api_key"] = _mask_key(d.get("api_key"))
    d["api_key_set"] = bool(cfg.api_key)
    return d


async def _log_sync(
    company_id: str, event: str, status: str,
    details: str = "", payload: Optional[Dict[str, Any]] = None,
) -> None:
    await db.atlaz_sync_logs.insert_one({
        "id": f"as-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "event": event,
        "status": status,
        "details": details[:600],
        "payload": payload,
        "at": now_iso(),
    })


def _utc_iso_no_tz(dt: datetime) -> str:
    """Atlaz exige formato UTC sem timezone: YYYY-MM-DDTHH:mm:ss"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# -------------------------------------------------------------------------
# API Atlaz: lista chamados
# -------------------------------------------------------------------------
async def _fetch_chamados(cfg: AtlazConfig) -> List[Dict[str, Any]]:
    """Chama GET /listachamados com janela = now - lookback_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    params = {
        "token": cfg.api_key,
        "status": "abertos",
        "data_criacao_inicio": _utc_iso_no_tz(cutoff),
    }
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.get(f"{ATLAZ_BASE_URL}/listachamados", params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if data.get("success") != "true":
        raise RuntimeError(f"Atlaz erro: {data.get('msg') or data}")
    return data.get("chamados") or []


def _filter_by_filial(chamados: List[Dict[str, Any]], filiais: List[str]) -> List[Dict[str, Any]]:
    """Filtra chamados pela cidade do ponto, comparando case/acento-insensitive."""
    if not filiais:
        return chamados
    norm_filiais = {_strip_accents(f).upper().strip() for f in filiais}
    out = []
    for c in chamados:
        cidade = ((c.get("ponto") or {}).get("cidade") or "").strip()
        if _strip_accents(cidade).upper() in norm_filiais:
            out.append(c)
    return out


async def _resolve_collaborator(
    chamado: Dict[str, Any], cfg: AtlazConfig, company_id: str,
) -> Optional[str]:
    """Decide qual colaborador local recebe o chamado.

    Ordem de prioridade:
      1. mapeamento explícito por nome do técnico (technician_to_collaborator)
      2. mapeamento por filial/cidade (filial_to_collaborator)
      3. primeiro colaborador ativo da empresa (fallback)
    """
    tec_name = ((chamado.get("tecnico") or {}).get("nome") or "").strip()
    if tec_name:
        key = _strip_accents(tec_name).lower().strip()
        for k, v in (cfg.technician_to_collaborator or {}).items():
            if _strip_accents(k).lower().strip() == key:
                return v

    cidade = ((chamado.get("ponto") or {}).get("cidade") or "").strip()
    if cidade:
        for k, v in (cfg.filial_to_collaborator or {}).items():
            if _strip_accents(k).lower().strip() == _strip_accents(cidade).lower().strip():
                return v

    any_coll = await db.collaborators.find_one(
        {"company_id": company_id, "active": {"$ne": False}}, {"_id": 0, "id": 1},
    )
    return any_coll["id"] if any_coll else None


async def _import_one(
    chamado: Dict[str, Any], cfg: AtlazConfig, company_id: str,
) -> str:
    """Importa 1 chamado como bolha local."""
    ext_id = str(chamado.get("id"))
    if not ext_id:
        raise ValueError("Chamado sem ID")

    existing = await db.tickets.find_one(
        {"company_id": company_id, "atlaz_external_id": ext_id},
        {"_id": 0, "id": 1, "status": 1},
    )
    if existing:
        return "skipped"

    assigned = await _resolve_collaborator(chamado, cfg, company_id)
    if not assigned:
        raise ValueError("Sem colaborador disponível na empresa")

    ticket_type = _normalize_type(chamado.get("tipo"), cfg.type_map or DEFAULT_TYPE_MAP)
    assinante = chamado.get("assinante") or {}
    ponto = chamado.get("ponto") or {}

    addr_parts = [
        ponto.get("logradouro") or "",
        ponto.get("numero") or "",
    ]
    address = ", ".join(p for p in addr_parts if p).strip(", ")
    if ponto.get("complemento"):
        address = f"{address} ({ponto['complemento']})" if address else ponto["complemento"]

    # GPS pode vir como "lat, lng"
    lat = lng = None
    if ponto.get("gps"):
        try:
            parts = [p.strip() for p in str(ponto["gps"]).split(",", 1)]
            lat, lng = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            pass

    doc = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": str(assinante.get("nome") or "Cliente"),
            "address": address,
            "neighborhood": str(ponto.get("bairro") or ""),
            "phone": str(assinante.get("telefone") or ""),
            "latitude": lat,
            "longitude": lng,
            "relato": str(chamado.get("detalhes") or ""),
            "test_history": [],
        },
        "type": ticket_type,
        "priority": "normal",
        "scheduled_time": chamado.get("visit_date"),
        "position": 0,
        "status": "pendente",
        "assigned_collaborator_id": assigned,
        "company_id": company_id,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "created_at": now_iso(),
        # Atlaz-specific
        "atlaz_external_id": ext_id,
        "atlaz_protocolo": str(chamado.get("protocolo") or ""),
        "atlaz_assunto": str(chamado.get("assunto") or ""),
        "atlaz_filial": str(ponto.get("cidade") or ""),
        "atlaz_tecnico_nome": ((chamado.get("tecnico") or {}).get("nome") or ""),
        "atlaz_id_assinante": assinante.get("id_assinante"),
        "atlaz_id_ponto": ponto.get("id_ponto"),
        "atlaz_synced_at": now_iso(),
    }
    await db.tickets.insert_one(doc)
    return "created"


async def run_sync(company_id: str, cfg: Optional[AtlazConfig] = None) -> Dict[str, Any]:
    cfg = cfg or await _get_config(company_id)
    if not cfg.enabled:
        return {"ok": False, "reason": "disabled", "created": 0, "skipped": 0, "errors": []}
    if not cfg.api_key:
        return {"ok": False, "reason": "missing_api_key", "created": 0, "skipped": 0, "errors": []}

    summary: Dict[str, Any] = {"created": 0, "skipped": 0, "errors": []}
    try:
        chamados = await _fetch_chamados(cfg)
    except Exception as e:
        summary["errors"].append(f"fetch falhou: {e}")
        await _log_sync(company_id, "pull", "error", str(e)[:400])
        return {"ok": True, **summary}

    chamados = _filter_by_filial(chamados, cfg.filiais)
    summary["fetched"] = len(chamados)

    created_ids: List[str] = []
    for c in chamados:
        try:
            if cfg.auto_create_bubbles:
                res = await _import_one(c, cfg, company_id)
                if res == "created":
                    summary["created"] += 1
                    created_ids.append(str(c.get("id")))
                else:
                    summary["skipped"] += 1
            else:
                summary["skipped"] += 1
        except Exception as e:
            summary["errors"].append(f"id={c.get('id')}: {e}")

    status = "ok" if not summary["errors"] else ("partial" if summary["created"] else "error")
    await _log_sync(
        company_id, "pull", status,
        f"fetched={summary.get('fetched',0)} created={summary['created']} skipped={summary['skipped']} errors={len(summary['errors'])}",
    )
    # Publica evento SSE se bolhas novas foram criadas — UI faz refresh em tempo real
    if summary["created"] > 0:
        await _safe_publish(company_id, "atlaz_bubbles_synced", {
            "created": summary["created"],
            "skipped": summary["skipped"],
            "fetched": summary.get("fetched", 0),
            "ticket_external_ids": created_ids,
            "at": now_iso(),
        })
    return {"ok": True, **summary}


async def _run_tech_sync_internal(company_id: str, cfg: AtlazConfig) -> Dict[str, Any]:
    """Lógica interna de sync de técnicos — reusada pelo endpoint manual e pelo worker.

    Retorna o mesmo shape do endpoint /sync-technicians.
    """
    if not cfg.api_key:
        return {"ok": False, "reason": "missing_api_key"}

    try:
        chamados = await _fetch_chamados(cfg)
    except Exception as e:
        await _log_sync(company_id, "sync_tec", "error", str(e)[:300])
        return {"ok": False, "error": str(e)[:200]}

    # Extrai técnicos únicos (chave = email; fallback nome)
    seen: Dict[str, Dict[str, Any]] = {}
    for c in chamados:
        tec = c.get("tecnico") or {}
        nome = (tec.get("nome") or "").strip()
        email = (tec.get("email") or "").strip().lower()
        if not nome:
            continue
        key = email or nome.lower()
        if key not in seen:
            seen[key] = {"nome": nome, "email": email}

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    new_mapping = dict(cfg.technician_to_collaborator or {})

    for tec in seen.values():
        nome = tec["nome"]
        email = tec["email"]
        existing = None
        if email:
            existing = await db.collaborators.find_one(
                {"company_id": company_id, "email": email}, {"_id": 0, "id": 1, "name": 1},
            )
        if not existing:
            existing = await db.collaborators.find_one(
                {"company_id": company_id, "name": nome}, {"_id": 0, "id": 1, "name": 1},
            )

        if existing:
            new_mapping[nome] = existing["id"]
            skipped.append({"nome": nome, "email": email, "matched_collaborator_id": existing["id"]})
            continue

        cid = f"col-{uuid.uuid4().hex[:8]}"
        now = now_iso()
        coll_doc = {
            "id": cid,
            "name": nome,
            "cpf": f"ATLAZ-{cid[-8:]}",
            "email": email or f"{cid}@atlaz.local",
            "phone": "",
            "role": "Técnico (Atlaz)",
            "company": "Atlaz Sync",
            "schedule": {
                "weekdays": [1, 2, 3, 4, 5],
                "start": "08:00", "end": "18:00",
                "lunch_start": "12:00", "lunch_end": "13:00",
            },
            "overtime_policy": {"enabled": False, "max_minutes_per_day": 120},
            "city": None, "state": None, "praca_id": None,
            "is_test_mode": False,
            "company_id": company_id,
            "avatar_data_url": None,
            "reference_face": None,
            "atlaz_synced": True,
            "atlaz_synced_at": now,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await db.collaborators.insert_one(coll_doc)
            created.append({"id": cid, "nome": nome, "email": email})
            new_mapping[nome] = cid
        except Exception as e:
            skipped.append({"nome": nome, "email": email, "error": str(e)[:100]})

    # Persiste mapeamento atualizado
    new_cfg = cfg.model_copy(update={"technician_to_collaborator": new_mapping})
    await _save_config(company_id, new_cfg)

    await _log_sync(
        company_id, "sync_tec", "ok" if not any("error" in s for s in skipped) else "partial",
        f"created={len(created)} skipped={len(skipped)}",
    )
    # SSE: publica evento se algum técnico novo foi criado, para a aba Colaborador refrescar
    if created:
        await _safe_publish(company_id, "atlaz_technicians_synced", {
            "created_count": len(created),
            "items_created": created,
            "at": now_iso(),
        })
    return {
        "ok": True,
        "total_atlaz_technicians": len(seen),
        "created": len(created),
        "matched_existing": sum(1 for s in skipped if "matched_collaborator_id" in s),
        "errors": [s for s in skipped if "error" in s],
        "items_created": created,
    }


# Stub mantido para compatibilidade com hooks de admin-close em lousa.py.
# A API Atlaz V2 NÃO permite fechar/cancelar/reagendar via REST.
async def push_close(*_args, **_kwargs) -> Dict[str, Any]:
    return {"ok": False, "reason": "atlaz_api_v2_not_supported"}


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
    if update_dict.get("api_key") == "":
        update_dict.pop("api_key", None)
    # Reconstrói o modelo (em vez de model_copy) para FORÇAR re-validação dos
    # constraints do AtlazConfig — defesa em profundidade contra valores fora do range.
    new_cfg = AtlazConfig(**{**current.model_dump(), **update_dict})
    await _save_config(company_id, new_cfg)
    return _public_config(new_cfg)


@router.post("/test-connection")
async def test_connection(user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    if not cfg.api_key:
        return {"ok": False, "reason": "missing_api_key"}

    try:
        chamados = await _fetch_chamados(cfg)
        cidades: Dict[str, int] = {}
        tipos: Dict[str, int] = {}
        tecnicos: Dict[str, int] = {}
        for c in chamados:
            cid = ((c.get("ponto") or {}).get("cidade") or "—").strip() or "—"
            cidades[cid] = cidades.get(cid, 0) + 1
            tp = (c.get("tipo") or "—")
            tipos[tp] = tipos.get(tp, 0) + 1
            tn = ((c.get("tecnico") or {}).get("nome") or "").strip()
            if tn:
                tecnicos[tn] = tecnicos.get(tn, 0) + 1
        await _log_sync(
            company_id, "test", "ok",
            f"chamados={len(chamados)} cidades={len(cidades)} tecnicos={len(tecnicos)}",
        )
        return {
            "ok": True,
            "total_chamados": len(chamados),
            "lookback_days": cfg.lookback_days,
            "cidades": dict(sorted(cidades.items(), key=lambda x: -x[1])),
            "tipos": dict(sorted(tipos.items(), key=lambda x: -x[1])),
            "tecnicos_atlaz": dict(sorted(tecnicos.items(), key=lambda x: -x[1])),
            "exemplo": chamados[0] if chamados else None,
        }
    except Exception as e:
        await _log_sync(company_id, "test", "error", str(e)[:400])
        return {"ok": False, "error": str(e)[:300]}


@router.post("/sync-now")
async def sync_now(user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await run_sync(company_id)


@router.post("/sync-technicians")
async def sync_technicians(user: dict = Depends(require_role("gestor"))):
    """Cria/atualiza colaboradores locais a partir dos técnicos do Atlaz.

    Lê todos os chamados do lookback, extrai técnicos únicos (nome+email),
    e cria um Colaborador interno para cada um que ainda não existe (match
    por email). Também atualiza o mapeamento technician_to_collaborator
    automaticamente para que o pull seguinte já atribua corretamente.

    Internamente chama _run_tech_sync_internal — mesma lógica usada pelo
    worker periódico (auto_sync_technicians).
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    return await _run_tech_sync_internal(company_id, cfg)


@router.get("/sync-logs")
async def sync_logs(limit: int = 30, user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.atlaz_sync_logs.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("at", -1).limit(min(limit, 200))
    items = await cur.to_list(min(limit, 200))
    return {"items": items, "count": len(items)}


# -------------------------------------------------------------------------
# Worker periódico
# -------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None
_worker_stop = asyncio.Event()


async def _worker_loop():
    logger.info("[atlaz] worker started")
    last_run_bubbles: Dict[str, datetime] = {}
    last_run_tech: Dict[str, datetime] = {}
    while not _worker_stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            cursor = db.atlaz_config.find({"enabled": True}, {"_id": 0})
            async for cfg_doc in cursor:
                cid = cfg_doc.get("company_id")
                if not cid:
                    continue
                valid = set(AtlazConfig.model_fields.keys())
                try:
                    cfg = AtlazConfig(**{k: v for k, v in cfg_doc.items() if k in valid})
                except Exception as e:
                    logger.exception("[atlaz] config inválida para %s: %s", cid, e)
                    continue

                # 1) Bubble pull — precedência: sync_interval_seconds > sync_interval_minutes
                if cfg.sync_interval_seconds and cfg.sync_interval_seconds > 0:
                    interval_b_sec = max(10, int(cfg.sync_interval_seconds))
                else:
                    interval_b_sec = max(60, int(cfg.sync_interval_minutes or 15) * 60)
                last_b = last_run_bubbles.get(cid)
                if not last_b or (now - last_b).total_seconds() >= interval_b_sec:
                    try:
                        await run_sync(cid, cfg)
                        await db.atlaz_config.update_one(
                            {"company_id": cid},
                            {"$set": {"last_auto_sync_bubbles_at": now_iso()}},
                        )
                    except Exception as e:
                        logger.exception("[atlaz] bubble sync falhou para %s: %s", cid, e)
                    last_run_bubbles[cid] = now

                # 2) Technician auto-sync (intervalo em min, default 60min)
                if cfg.auto_sync_technicians:
                    interval_t = max(5, int(cfg.tech_sync_interval_minutes or 60))
                    last_t = last_run_tech.get(cid)
                    if not last_t or (now - last_t).total_seconds() >= interval_t * 60:
                        try:
                            res = await _run_tech_sync_internal(cid, cfg)
                            if res.get("ok"):
                                await db.atlaz_config.update_one(
                                    {"company_id": cid},
                                    {"$set": {"last_auto_sync_technicians_at": now_iso()}},
                                )
                        except Exception as e:
                            logger.exception("[atlaz] tech sync falhou para %s: %s", cid, e)
                        last_run_tech[cid] = now
        except Exception as e:
            logger.exception("[atlaz] worker tick falhou: %s", e)
        # Tick curto (5s) — permite intervalos em segundos. O check >= interval_b_sec por empresa
        # garante que o pull respeita o intervalo configurado, sem hammering na API Atlaz.
        try:
            await asyncio.wait_for(_worker_stop.wait(), timeout=5)
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
