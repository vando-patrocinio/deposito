"""IA Preventivas — sugere notas de serviço preventivas baseado em:

1. **Sinal crítico** (cache SmartOLT): clientes Online com Rx < -27 dBm ou
   `signal_text in {"Bad","Warning"}` que ainda NÃO têm bolha aberta.
2. **Ritmo dos técnicos** (últimos 30 dias): média de notas finalizadas/dia.
3. **Capacidade ociosa hoje**: pace_diário - notas_finalizadas_hoje.
4. **Match geográfico**: cliente é roteado pro técnico cujo `atlaz_filiais`
   tokens batem com a `zone_name`/`olt_name`.

Resultado: cria 1 notificação `ai_preventive_suggestion` consolidando o
ranking, e expõe endpoint `POST /accept/{candidate_id}` que cria a bolha
preventiva atribuída ao técnico recomendado.
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

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.ai_preventive")
router = APIRouter(prefix="/api/ai/preventive", tags=["ai_preventive"])

# Limiares (configuráveis via /settings)
DEFAULT_CRITICAL_RX = -27.0  # dBm — abaixo disso é crítico
DEFAULT_WARN_RX = -25.0       # entre warn e critical = "atenção", inclui se houver capacidade
DEFAULT_PACE_LOOKBACK_DAYS = 30
DEFAULT_MIN_CAPACITY = 1       # técnico precisa ter pelo menos 1 vaga ociosa
DEFAULT_MAX_PER_TECH = 2       # nunca sugere mais que 2 preventivas/dia/téc.


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AIPrevConfig(BaseModel):
    company_id: str = DEMO_COMPANY_ID
    enabled: bool = True
    critical_rx_dbm: float = DEFAULT_CRITICAL_RX
    warn_rx_dbm: float = DEFAULT_WARN_RX
    pace_lookback_days: int = Field(default=DEFAULT_PACE_LOOKBACK_DAYS, ge=7, le=90)
    min_capacity_to_suggest: int = Field(default=DEFAULT_MIN_CAPACITY, ge=1, le=10)
    max_suggestions_per_tech: int = Field(default=DEFAULT_MAX_PER_TECH, ge=1, le=10)
    scan_interval_hours: int = Field(default=4, ge=1, le=24)
    last_scan_at: Optional[str] = None


class AIPrevConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    critical_rx_dbm: Optional[float] = None
    warn_rx_dbm: Optional[float] = None
    pace_lookback_days: Optional[int] = Field(default=None, ge=7, le=90)
    min_capacity_to_suggest: Optional[int] = Field(default=None, ge=1, le=10)
    max_suggestions_per_tech: Optional[int] = Field(default=None, ge=1, le=10)
    scan_interval_hours: Optional[int] = Field(default=None, ge=1, le=24)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
async def _get_config(company_id: str) -> AIPrevConfig:
    raw = await db.ai_preventive_config.find_one({"company_id": company_id}, {"_id": 0})
    if not raw:
        cfg = AIPrevConfig(company_id=company_id)
        await db.ai_preventive_config.insert_one(cfg.model_dump())
        return cfg
    try:
        return AIPrevConfig(**raw)
    except Exception:
        cfg = AIPrevConfig(company_id=company_id)
        await db.ai_preventive_config.update_one(
            {"company_id": company_id}, {"$set": cfg.model_dump()}, upsert=True,
        )
        return cfg


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
async def compute_tech_pace(company_id: str, lookback_days: int) -> Dict[str, Dict[str, Any]]:
    """Para cada colaborador, calcula:
       - finalizadas_total: notas finalizadas no período
       - dias_ativos: nº de dias distintos com pelo menos 1 finalização
       - pace_per_day: finalizadas / max(1, dias_ativos)  (média em dias trabalhados)
       - pace_calendar: finalizadas / lookback_days  (média absoluta)
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    cur = db.tickets.find(
        {"company_id": company_id, "status": "finalizada",
         "closed_at": {"$gte": cutoff}},
        {"_id": 0, "assigned_collaborator_id": 1, "closed_at": 1},
    )
    by_tech: Dict[str, Dict[str, Any]] = {}
    async for t in cur:
        cid = t["assigned_collaborator_id"]
        d = (t["closed_at"] or "")[:10]
        bucket = by_tech.setdefault(cid, {"total": 0, "days": set()})
        bucket["total"] += 1
        bucket["days"].add(d)
    out: Dict[str, Dict[str, Any]] = {}
    for cid, b in by_tech.items():
        active_days = max(1, len(b["days"]))
        out[cid] = {
            "finalizadas_total": b["total"],
            "dias_ativos": active_days,
            "pace_per_active_day": round(b["total"] / active_days, 2),
            "pace_per_calendar_day": round(b["total"] / lookback_days, 2),
        }
    return out


async def compute_today_workload(company_id: str) -> Dict[str, Dict[str, int]]:
    """Para cada colaborador: notas pendentes/abertas/finalizadas HOJE."""
    today = datetime.now(timezone.utc).date().isoformat()
    cur = db.tickets.find(
        {"company_id": company_id,
         "$or": [
             {"created_at": {"$gte": today}},
             {"status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
         ]},
        {"_id": 0, "assigned_collaborator_id": 1, "status": 1, "closed_at": 1, "created_at": 1},
    )
    out: Dict[str, Dict[str, int]] = {}
    async for t in cur:
        cid = t.get("assigned_collaborator_id")
        if not cid:
            continue
        bucket = out.setdefault(cid, {"pendente": 0, "aberta": 0, "finalizada_hoje": 0})
        if t["status"] == "finalizada" and (t.get("closed_at") or "").startswith(today):
            bucket["finalizada_hoje"] += 1
        elif t["status"] in ("pendente", "aberta", "aguardando_atendimento"):
            bucket[t["status"] if t["status"] in bucket else "aberta"] += 1
    return out


async def compute_capacity(company_id: str, cfg: AIPrevConfig) -> Dict[str, Dict[str, Any]]:
    """Capacidade ociosa hoje = pace_diário - (pendente + aberta + finalizada_hoje).

    Estratégia de pace:
      - Se técnico tem ≥5 dias ativos: usa pace_per_active_day (média em dias trabalhados).
      - Senão: usa max(1.0, pace_per_calendar_day) — assume meta mínima de 1/dia
        (técnicos novos/com pouco histórico não ficam zerados).
    """
    pace = await compute_tech_pace(company_id, cfg.pace_lookback_days)
    workload = await compute_today_workload(company_id)
    techs = await db.collaborators.find(
        {"company_id": company_id, "atlaz_inbox": {"$ne": True}, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "atlaz_filiais": 1},
    ).to_list(200)
    out: Dict[str, Dict[str, Any]] = {}
    for tech in techs:
        tid = tech["id"]
        p = pace.get(tid, {})
        w = workload.get(tid, {"pendente": 0, "aberta": 0, "finalizada_hoje": 0})
        dias_ativos = p.get("dias_ativos", 0)
        if dias_ativos >= 5:
            ritmo = p.get("pace_per_active_day", 0)
        else:
            ritmo = max(1.0, p.get("pace_per_calendar_day", 0))
        carga_hoje = w["pendente"] + w["aberta"] + w["finalizada_hoje"]
        capacity = max(0, int(round(ritmo - carga_hoje)))
        out[tid] = {
            "id": tid,
            "name": tech["name"],
            "pace_per_active_day": p.get("pace_per_active_day", 0),
            "pace_per_calendar_day": p.get("pace_per_calendar_day", 0),
            "ritmo_efetivo": round(ritmo, 1),
            "finalizadas_total_30d": p.get("finalizadas_total", 0),
            "dias_ativos_30d": dias_ativos,
            "carga_hoje": carga_hoje,
            "capacity_today": capacity,
            "atlaz_filiais": tech.get("atlaz_filiais") or [],
        }
    return out


# ---------------------------------------------------------------------------
# Candidatos: clientes com sinal crítico que ainda não têm bolha aberta
# ---------------------------------------------------------------------------
async def find_critical_clients(company_id: str, cfg: AIPrevConfig) -> List[dict]:
    """Lista clientes com sinal degradado, ordenados por urgência (rx mais negativo primeiro)."""
    # Pega ONUs Online com rx degradado
    cur = db.smartolt_onus.find(
        {"company_id": company_id, "status": "Online"},
        {"_id": 0, "unique_external_id": 1, "name": 1, "name_norm": 1,
         "signal_1310": 1, "signal_1490": 1, "signal_text": 1,
         "olt_name": 1, "zone_name": 1, "address": 1, "synced_at": 1},
    )
    candidates: List[dict] = []
    async for o in cur:
        rx = o.get("signal_1490") or o.get("signal_1310")
        try:
            rxf = float(rx) if rx is not None else None
        except (TypeError, ValueError):
            continue
        if rxf is None:
            continue
        text = (o.get("signal_text") or "").lower()
        is_critical = rxf <= cfg.critical_rx_dbm or "bad" in text
        is_warn = (cfg.critical_rx_dbm < rxf <= cfg.warn_rx_dbm) or "warning" in text
        if not (is_critical or is_warn):
            continue
        candidates.append({
            **o,
            "rx_dbm": rxf,
            "urgency": "critical" if is_critical else "warn",
            "score": -rxf,  # mais negativo = score maior
        })
    # Filtra clientes que JÁ têm bolha aberta/pendente (evita duplicar)
    if not candidates:
        return []
    open_tickets_cur = db.tickets.find(
        {"company_id": company_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "client_snapshot.pppoe_user": 1, "client_snapshot.name": 1},
    )
    busy_norms: set = set()
    async for t in open_tickets_cur:
        snap = t.get("client_snapshot") or {}
        for k in (snap.get("pppoe_user"), snap.get("name")):
            if not k:
                continue
            n = _norm(k)
            if n:
                busy_norms.add(n)
    free = [c for c in candidates if c["name_norm"] not in busy_norms]
    # Bolhas preventivas já criadas/sugeridas hoje pelo IA (evitar duplicar sugestão diária)
    today = datetime.now(timezone.utc).date().isoformat()
    suggested_today_cur = db.ai_preventive_suggestions.find(
        {"company_id": company_id,
         "created_at": {"$gte": today},
         "status": {"$in": ["pending", "accepted"]}},
        {"_id": 0, "external_id": 1},
    )
    suggested_ids = {s["external_id"] async for s in suggested_today_cur}
    free = [c for c in free if c["unique_external_id"] not in suggested_ids]
    free.sort(key=lambda c: c["score"], reverse=True)
    return free


def _norm(s: Any) -> str:
    """Normaliza igual ao smartolt._norm (dup mínimo pra evitar import cíclico)."""
    if not s:
        return ""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", str(s))
    out = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    return "".join(ch for ch in out if ch.isalnum())


# ---------------------------------------------------------------------------
# Match: cliente → técnico (usando atlaz_filiais)
# ---------------------------------------------------------------------------
def _match_tech_for_client(client: dict, capacity_map: Dict[str, dict]) -> Optional[str]:
    """Match por tokens da zona/OLT do cliente vs `atlaz_filiais` do técnico.

    Critérios:
      1. Filtra técnicos com `capacity_today >= min_capacity`.
      2. Match por substring/token: zone_name ou olt_name contém token de filial.
      3. Em caso de empate, escolhe o de MAIOR capacidade.
    """
    zone = (client.get("zone_name") or "").upper()
    olt = (client.get("olt_name") or "").upper()
    eligible = [t for t in capacity_map.values() if t["capacity_today"] >= 1]
    if not eligible:
        return None
    scored: List[tuple] = []
    for tech in eligible:
        tokens = set()
        for f in tech.get("atlaz_filiais") or []:
            for word in str(f).upper().replace("/", " ").replace("-", " ").split():
                if len(word) >= 3 and word != "LIGO":
                    tokens.add(word)
        m = sum(1 for tok in tokens if tok in zone or tok in olt)
        scored.append((m, tech["capacity_today"], tech["id"]))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0]
    # Sem nenhum match → escolhe maior capacidade (round-robin de fato)
    return best[2]


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
async def run_scan(company_id: str, force: bool = False) -> dict:
    cfg = await _get_config(company_id)
    if not cfg.enabled:
        return {"ok": False, "reason": "disabled"}
    capacity_map = await compute_capacity(company_id, cfg)
    clients = await find_critical_clients(company_id, cfg)

    suggestions: List[dict] = []
    per_tech_count: Dict[str, int] = {}
    # Em modo `force`, permite até `max_suggestions_per_tech` mesmo se capacity=0
    capacity_remaining = {
        tid: (max(t["capacity_today"], cfg.max_suggestions_per_tech) if force
              else t["capacity_today"])
        for tid, t in capacity_map.items()
    }

    for c in clients:
        tech_id = _match_tech_for_client(c, {
            tid: {**t, "capacity_today": capacity_remaining[tid]}
            for tid, t in capacity_map.items()
        })
        if not tech_id:
            continue
        if per_tech_count.get(tech_id, 0) >= cfg.max_suggestions_per_tech:
            continue
        if capacity_remaining.get(tech_id, 0) < 1:
            continue
        sid = f"prev-{uuid.uuid4().hex[:10]}"
        sugg = {
            "id": sid,
            "company_id": company_id,
            "external_id": c["unique_external_id"],
            "client_name": c["name"],
            "rx_dbm": c["rx_dbm"],
            "urgency": c["urgency"],
            "olt_name": c.get("olt_name"),
            "zone_name": c.get("zone_name"),
            "address": c.get("address"),
            "tech_id": tech_id,
            "tech_name": capacity_map[tech_id]["name"],
            "tech_capacity_at_suggest": capacity_remaining[tech_id],
            "tech_pace": capacity_map[tech_id]["ritmo_efetivo"],
            "status": "pending",
            "created_at": now_iso(),
            "ticket_id": None,
        }
        suggestions.append(sugg)
        per_tech_count[tech_id] = per_tech_count.get(tech_id, 0) + 1
        capacity_remaining[tech_id] -= 1

    if suggestions:
        await db.ai_preventive_suggestions.insert_many([dict(s) for s in suggestions])
        # Notificação consolidada pro gestor
        critical_count = sum(1 for s in suggestions if s["urgency"] == "critical")
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "type": "ai_preventive_suggestion",
            "title": f"🤖 IA sugere {len(suggestions)} preventiva(s) hoje",
            "message": (f"{critical_count} crítica(s) e {len(suggestions) - critical_count} de atenção. "
                        f"Capacidade ociosa detectada nos técnicos disponíveis. "
                        f"Veja em Lousa → 🤖 Preventivas IA."),
            "severity": "info" if critical_count == 0 else "warning",
            "created_at": now_iso(),
            "read_by": [],
            "audience_role": "gestor",
            "payload": {
                "suggestion_ids": [s["id"] for s in suggestions],
                "total": len(suggestions),
                "critical": critical_count,
            },
        })
    await db.ai_preventive_config.update_one(
        {"company_id": company_id},
        {"$set": {"last_scan_at": now_iso()}},
    )
    return {
        "ok": True,
        "scanned_clients": len(clients),
        "suggestions_created": len(suggestions),
        "suggestions": suggestions[:20],  # primeiros 20 pra preview
        "capacity_map": list(capacity_map.values()),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/settings")
async def get_settings(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return (await _get_config(cid)).model_dump()


@router.put("/settings")
async def put_settings(payload: AIPrevConfigUpdate,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    update = payload.model_dump(exclude_unset=True)
    new_cfg = AIPrevConfig(**{**cfg.model_dump(), **update})
    await db.ai_preventive_config.update_one(
        {"company_id": cid}, {"$set": new_cfg.model_dump()}, upsert=True,
    )
    return new_cfg.model_dump()


@router.post("/scan")
async def scan_now(force: bool = False,
                    user: dict = Depends(require_role("gestor"))):
    """Roda scan agora. `force=true` ignora capacity (útil em modo emergencial)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    started = time.time()
    result = await run_scan(cid, force=force)
    result["elapsed_seconds"] = round(time.time() - started, 2)
    return result


@router.get("/suggestions")
async def list_suggestions(status: Optional[str] = None,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    cur = db.ai_preventive_suggestions.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    return await cur.to_list(200)


@router.get("/capacity")
async def capacity_dashboard(user: dict = Depends(require_role("gestor"))):
    """Painel de capacidade: ritmo + carga + ociosidade por técnico."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    cap = await compute_capacity(cid, cfg)
    return {
        "config": cfg.model_dump(),
        "techs": list(cap.values()),
        "total_capacity_today": sum(t["capacity_today"] for t in cap.values()),
        "total_pace_per_day": round(sum(t["pace_per_active_day"] for t in cap.values()), 1),
    }


@router.post("/accept/{suggestion_id}")
async def accept_suggestion(suggestion_id: str,
                              user: dict = Depends(require_role("gestor"))):
    """Cria a bolha preventiva a partir da sugestão e marca como `accepted`."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await db.ai_preventive_suggestions.find_one(
        {"id": suggestion_id, "company_id": cid}, {"_id": 0},
    )
    if not s:
        raise HTTPException(404, "Sugestão não encontrada.")
    if s["status"] != "pending":
        raise HTTPException(400, f"Sugestão já {s['status']}.")
    onu = await db.smartolt_onus.find_one(
        {"company_id": cid, "unique_external_id": s["external_id"]}, {"_id": 0},
    )
    address = (onu or {}).get("address") or s.get("address") or ""
    relato = (f"🤖 Preventiva sugerida pela IA — sinal {s['rx_dbm']:.1f} dBm "
              f"({s['urgency']}). OLT: {s.get('olt_name', '?')} · zona {s.get('zone_name', '?')}.")
    tid = f"tkt-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": tid,
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": s["client_name"], "address": address, "neighborhood": "",
            "phone": "", "latitude": None, "longitude": None,
            "relato": relato, "pppoe_user": s["client_name"], "test_history": [],
        },
        "type": "preventiva", "priority": "normal", "scheduled_time": None,
        "position": 9999, "status": "pendente",
        "assigned_collaborator_id": s["tech_id"],
        "company_id": cid,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "created_at": now_iso(),
        "ai_preventive_id": suggestion_id,
        "ai_preventive_rx_dbm": s["rx_dbm"],
    }
    # SALA-routing — preventiva sistemica cai em SALA (11/02/2026).
    from services.sala_router import route_to_sala
    await route_to_sala(doc, reason="ai_preventive_accepted",
                          original_tech_suggested=s.get("tech_id"))
    await db.tickets.insert_one(doc)
    await db.ai_preventive_suggestions.update_one(
        {"id": suggestion_id}, {"$set": {"status": "accepted", "ticket_id": tid, "accepted_at": now_iso()}},
    )
    return {"ok": True, "ticket_id": tid}


@router.post("/reject/{suggestion_id}")
async def reject_suggestion(suggestion_id: str,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.ai_preventive_suggestions.update_one(
        {"id": suggestion_id, "company_id": cid, "status": "pending"},
        {"$set": {"status": "rejected", "rejected_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Sugestão pendente não encontrada.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Worker periódico
# ---------------------------------------------------------------------------
_WORKER_TASK: Optional[asyncio.Task] = None
_WORKER_RUN = True


async def _worker_loop() -> None:
    last_scan: Dict[str, float] = {}
    while _WORKER_RUN:
        try:
            cfgs = await db.ai_preventive_config.find({"enabled": True}, {"_id": 0}).to_list(50)
            now = time.time()
            for raw in cfgs:
                try:
                    cfg = AIPrevConfig(**raw)
                except Exception:
                    continue
                cid = cfg.company_id
                interval = cfg.scan_interval_hours * 3600
                if cid in last_scan and (now - last_scan[cid]) < interval:
                    continue
                last_scan[cid] = now
                try:
                    res = await run_scan(cid)
                    logger.info("[ai_preventive] scan %s — %s sugestões",
                                cid, res.get("suggestions_created"))
                except Exception as e:
                    logger.warning("[ai_preventive] scan falhou %s: %s", cid, e)
        except Exception as e:
            logger.warning("[ai_preventive] tick falhou: %s", e)
        await asyncio.sleep(300)  # 5 min entre ticks


async def start_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK and not _WORKER_TASK.done():
        return
    _WORKER_TASK = asyncio.create_task(_worker_loop())
    logger.info("[ai_preventive] worker started")


async def stop_worker() -> None:
    global _WORKER_RUN
    _WORKER_RUN = False
    if _WORKER_TASK:
        _WORKER_TASK.cancel()
