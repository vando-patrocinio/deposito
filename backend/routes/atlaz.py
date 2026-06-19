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


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
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
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
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
    # NOVO (iter 25): fuso horário usado pelo Atlaz para `visit_date`. Sem tz na
    # string, o backend assume este fuso. Valores válidos: "UTC" (padrão) ou um
    # IANA TZ ("America/Sao_Paulo"). Mude se as horas das bolhas não baterem
    # com o painel Atlaz.
    atlaz_visit_date_tz: str = "America/Sao_Paulo"
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
    atlaz_visit_date_tz: Optional[str] = None
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


def _filial_tokens(s: str) -> set:
    """Tokeniza nome de filial/cidade: palavras com 3+ chars, sem acento, em UPPER.
    Ignora token genérico 'LIGO' (prefixo comum em filiais LIGO FIBRA)."""
    norm = _strip_accents(s).upper()
    for sep in "/-,()":
        norm = norm.replace(sep, " ")
    return {w for w in norm.split() if len(w) >= 3 and w != "LIGO"}


def _filter_by_filial(chamados: List[Dict[str, Any]], filiais: List[str]) -> List[Dict[str, Any]]:
    """Filtra chamados pela cidade do ponto via tokenização case/acento-insensitive.

    Match: pelo menos UM token (≥3 chars, ignorando 'LIGO') do nome da filial
    coincide com algum token do nome da cidade. Resolve casos como:
      filial='LIGO RIO' → token={'RIO'} bate com cidade='Rio de Janeiro' (token RIO).
      filial='LIGO MAGÉ' → token={'MAGE'} bate com cidade='Magé'.
      filial='LIGO CACHOEIRAS DE MACACÚ' → token={'CACHOEIRAS','MACACU'} bate com 'Cachoeiras de Macacu'.
    """
    if not filiais:
        return chamados
    filial_token_sets = [_filial_tokens(f) for f in filiais if f.strip()]
    filial_token_sets = [t for t in filial_token_sets if t]
    if not filial_token_sets:
        return chamados
    out = []
    for c in chamados:
        cidade = ((c.get("ponto") or {}).get("cidade") or "").strip()
        if not cidade:
            continue
        cidade_toks = _filial_tokens(cidade)
        if not cidade_toks:
            continue
        if any(ftoks & cidade_toks for ftoks in filial_token_sets):
            out.append(c)
    return out


async def _get_or_create_unassigned_inbox(company_id: str) -> str:
    """Retorna o ID da SALA (Lousa virtual) do tenant — destino unificado
    de bolhas Atlaz SEM tecnico mapeavel.

    REGRA (11/02/2026): Atlaz orfan -> SEMPRE cai na grade SALA. O placeholder
    `📥 Sem técnico (Atlaz)` (atlaz_inbox=True) foi descontinuado em favor da
    SALA virtual, que já é a coluna fixa de triagem da Lousa Admin.

    Migracao de tickets antigos: feita uma vez via script
    `scripts/migrate_atlaz_inbox_to_sala.py` (idempotente).
    """
    from services.isabella_actions import _ensure_sala
    return await _ensure_sala(company_id)


async def _resolve_collaborator(
    chamado: Dict[str, Any], cfg: AtlazConfig, company_id: str,
) -> Optional[str]:
    """Decide qual colaborador local recebe o chamado.

    Ordem de prioridade:
      1. Mapeamento EXPLÍCITO por nome do técnico (technician_to_collaborator).
         Match case/acento-insensitive.
      2. Mapeamento por filial/cidade (filial_to_collaborator) com matching
         por TOKEN — chave 'LIGO RIO' bate com cidade 'Rio de Janeiro'.
      3. Match automático por nome do técnico Atlaz contra colaboradores
         já cadastrados (db.collaborators) — case/acento-insensitive.

    Se NENHUM dos 3 funcionar, retorna None (chamado fica sem técnico e o
    sync usa skip 'unassigned' em vez de jogar para o primeiro colaborador
    aleatório — que causava 32 bolhas atribuídas erradas).
    """
    tec_name = ((chamado.get("tecnico") or {}).get("nome") or "").strip()
    if tec_name:
        key = _strip_accents(tec_name).lower().strip()
        # 1) Mapping explícito
        for k, v in (cfg.technician_to_collaborator or {}).items():
            if _strip_accents(k).lower().strip() == key:
                return v
        # 3) Match automático em db.collaborators por nome (insensitive)
        async for coll in db.collaborators.find(
            {"company_id": company_id, "active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1},
        ):
            if _strip_accents(coll.get("name", "")).lower().strip() == key:
                return coll["id"]

    # 2) Mapping por filial via tokenização — 'LIGO RIO' bate com 'Rio de Janeiro'
    cidade = ((chamado.get("ponto") or {}).get("cidade") or "").strip()
    if cidade and cfg.filial_to_collaborator:
        cidade_toks = _filial_tokens(cidade)
        if cidade_toks:
            for k, v in cfg.filial_to_collaborator.items():
                ftoks = _filial_tokens(k)
                if ftoks and ftoks & cidade_toks:
                    return v

    # SEM fallback automático — devolve None para que o caller pule o chamado
    # com motivo claro, em vez de errar a atribuição.
    return None


async def _next_available_slot(
    company_id: str,
    technician_id: Optional[str],
    target_iso: str,
    *,
    exclude_ticket_id: Optional[str] = None,
) -> str:
    """CTO 12/06/2026 — Regra de negócio do gestor (substitui iter211aa):

      • cutoff_hour (default 17): Atlaz `visit_date` >= cutoff → empurra
        pro PRÓXIMO DIA ÚTIL no PRIMEIRO SLOT LIVRE da grade.
      • Dia útil = SEG a SÁB (DOMINGO pula, weekday==6).
      • Atlaz visit_date < cutoff → encaixa no MESMO dia, no slot da grade
        (≥ grid_start), avançando slot-a-slot até achar vaga.
      • Esgotou o dia inteiro lotado → empurra pro próximo dia útil no
        primeiro slot livre.
      • Tickets sem `technician_id` (inbox) não competem por slot — retorna
        o ISO original.

    Retorna o ISO UTC do slot escolhido.
    """
    if not target_iso or not technician_id:
        return target_iso
    try:
        target_dt = datetime.fromisoformat(target_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return target_iso
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)

    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    max_per_slot = int(settings.get("lousa_grid_max_per_slot", 2))
    grid_start = int(settings.get("lousa_grid_start_hour", 9))
    grid_end = int(settings.get("lousa_grid_end_hour", 18))
    slot_minutes = int(settings.get("lousa_grid_slot_minutes", 60)) or 60
    cutoff_hour = int(settings.get("lousa_atlaz_cutoff_hour", 17))

    try:
        from zoneinfo import ZoneInfo
        tz_br = ZoneInfo("America/Sao_Paulo")
    except Exception:
        tz_br = timezone(timedelta(hours=-3))

    async def _count_at(dt_local: datetime, *, ignore_id: Optional[str] = None) -> int:
        day_str = dt_local.strftime("%Y-%m-%d")
        slot_str = dt_local.strftime("%H:%M")
        q = {
            "company_id": company_id,
            "assigned_collaborator_id": technician_id,
            "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        }
        if ignore_id or exclude_ticket_id:
            q["id"] = {"$ne": ignore_id or exclude_ticket_id}
        candidates = await db.tickets.find(
            q, {"_id": 0, "id": 1, "scheduled_time": 1, "opened_at": 1,
                  "atlaz_created_at": 1, "created_at": 1},
        ).to_list(500)
        n = 0
        for t in candidates:
            raw = (t.get("scheduled_time") or t.get("opened_at")
                   or t.get("atlaz_created_at") or t.get("created_at"))
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local = dt.astimezone(tz_br)
                if local.strftime("%Y-%m-%d") != day_str:
                    continue
                minutes = (local.hour * 60 + local.minute) // slot_minutes * slot_minutes
                hh, mm = minutes // 60, minutes % 60
                if f"{hh:02d}:{mm:02d}" == slot_str:
                    n += 1
            except (ValueError, TypeError):
                continue
        return n

    def _is_business_day(dt: datetime) -> bool:
        """SEG-SÁB úteis (0..5), DOM (6) não é útil."""
        return dt.weekday() < 6

    async def _find_first_free_slot_on_day(day_local: datetime) -> Optional[datetime]:
        """Procura o 1º slot livre na grade do dia (≥ grid_start, < grid_end)."""
        slots_per_day = max(1, ((grid_end - grid_start) * 60) // slot_minutes)
        cur = day_local.replace(hour=grid_start, minute=0, second=0, microsecond=0)
        for _ in range(slots_per_day):
            if cur.hour >= grid_end:
                return None
            if await _count_at(cur) < max_per_slot:
                return cur
            cur = cur + timedelta(minutes=slot_minutes)
        return None

    local_target = target_dt.astimezone(tz_br)
    target_hour = local_target.hour

    # ROTA A: visit_date >= cutoff_hour → empurra pro próximo dia útil
    # ROTA B: visit_date <  cutoff_hour → mesmo dia, slot livre da grade
    push_next_day = target_hour >= cutoff_hour

    if not push_next_day:
        # Normaliza horário pedido pro slot da grade do MESMO dia
        normalized_hour = max(grid_start, target_hour)
        if normalized_hour < grid_end:
            minutes = (normalized_hour * 60 + local_target.minute) // slot_minutes * slot_minutes
            cur = local_target.replace(hour=minutes // 60, minute=minutes % 60,
                                          second=0, microsecond=0)
            # Avança slot a slot dentro do mesmo dia
            while cur.hour < grid_end:
                if await _count_at(cur) < max_per_slot:
                    logger.info(
                        "[atlaz] slot encaixado MESMO DIA target=%s → %s",
                        target_iso, cur.isoformat(),
                    )
                    return cur.astimezone(timezone.utc).isoformat()
                cur = cur + timedelta(minutes=slot_minutes)
        # Dia inteiro cheio → cai pra rota A

    # Rota A: próximo dia útil, primeiro slot livre da grade
    next_day = local_target + timedelta(days=1)
    for _ in range(14):  # janela de 14 dias é mais que suficiente
        if _is_business_day(next_day):
            free_slot = await _find_first_free_slot_on_day(next_day)
            if free_slot is not None:
                logger.info(
                    "[atlaz] slot encaixado DIA+N target=%s (cutoff=%dh) → %s",
                    target_iso, cutoff_hour, free_slot.isoformat(),
                )
                return free_slot.astimezone(timezone.utc).isoformat()
        next_day = next_day + timedelta(days=1)

    # Fallback extremo (improvável): mantém o ISO original
    logger.warning(
        "[atlaz] _next_available_slot: nenhum slot livre em 14 dias úteis "
        "para target=%s tech=%s — mantendo ISO original.",
        target_iso, technician_id,
    )
    return target_iso



def _resolve_schedule(chamado: Dict[str, Any], visit_tz: str = "America/Sao_Paulo") -> tuple:
    """A partir do chamado Atlaz, decide priority/position/scheduled_time da bolha.

    iter211z — Ordem de fallback (do mais específico para o mais genérico):
      1. `visit_date` / `data_visita` (agendamento explícito do técnico) → HORARIO
      2. `data_marcada` / `data_agendamento` (agendamento alternativo) → HORARIO
      3. `data_criacao` / `data_abertura` / `criado_em` (data de abertura
         do chamado no Atlaz) → NORMAL, mas com a data preservada no
         `scheduled_time` para que `_ticket_day_iso` enxergue a data correta.

    Sem nenhum desses, retorna ("normal", 0, None) — o ticket vai cair em
    `created_at` local (dia da importação) como último recurso.

    Retorna (priority, position, scheduled_time_iso_or_raw).
    """
    # Resolve tz alvo (uma vez)
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(visit_tz) if visit_tz != "UTC" else timezone.utc
    except Exception:
        tzinfo = timezone.utc

    def _try_parse(raw):
        if not raw:
            return None
        raw_str = str(raw).strip()
        if not raw_str:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z",
                    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                    "%Y-%m-%d", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(raw_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tzinfo)
                # Quando só veio data sem hora, ancora em 09:00 local
                # (horário comercial padrão de visita técnica).
                if fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                    dt = dt.replace(hour=9, minute=0, second=0)
                return dt
            except ValueError:
                continue
        return None

    # 1) Agendamento explícito → HORARIO (ordena na coluna por hora)
    dt = _try_parse(chamado.get("visit_date") or chamado.get("data_visita")
                    or chamado.get("data_marcada")
                    or chamado.get("data_agendamento"))
    if dt:
        return "horario", int(dt.timestamp()), dt.astimezone(timezone.utc).isoformat()

    # 2) Sem agendamento — usa data de criação do chamado no Atlaz como
    # `scheduled_time` (NORMAL), pra que a bolha caia no dia ORIGINAL
    # do Atlaz, não no dia da importação local.
    dt = _try_parse(chamado.get("data_criacao") or chamado.get("data_abertura")
                    or chamado.get("criado_em") or chamado.get("created_at")
                    or chamado.get("data"))
    if dt:
        return "normal", 0, dt.astimezone(timezone.utc).isoformat()

    return "normal", 0, None


async def _import_one(
    chamado: Dict[str, Any], cfg: AtlazConfig, company_id: str,
) -> str:
    """Importa 1 chamado como bolha local. Retorna:
      - 'skipped'      → já existia (dedupe por atlaz_external_id)
      - 'unassigned'   → atribuído ao inbox Atlaz (sem técnico mapeável)
      - 'created'      → bolha criada com sucesso
    """
    ext_id = str(chamado.get("id"))
    if not ext_id:
        raise ValueError("Chamado sem ID")

    existing = await db.tickets.find_one(
        {"company_id": company_id, "atlaz_external_id": ext_id},
        {"_id": 0, "id": 1, "status": 1, "client_snapshot": 1},
    )
    if existing:
        # Backfill: se a bolha existente está sem pppoe_user, atualiza com o ponto.username atual
        ponto_now = chamado.get("ponto") or {}
        new_pppoe = str(ponto_now.get("username") or "").strip()
        cur_pppoe = (existing.get("client_snapshot") or {}).get("pppoe_user") or ""
        if new_pppoe and not cur_pppoe:
            await db.tickets.update_one(
                {"id": existing["id"]},
                {"$set": {"client_snapshot.pppoe_user": new_pppoe,
                          "atlaz_synced_at": now_iso()}},
            )
        return "skipped"

    assigned = await _resolve_collaborator(chamado, cfg, company_id)
    is_unassigned = False
    if not assigned:
        assigned = await _get_or_create_unassigned_inbox(company_id)
        is_unassigned = True

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

    # Horário agendado do Atlaz (`visit_date`) → bolha entra como prioridade
    # "horario" e a `position` recebe o epoch da visita. Assim, dentro da coluna
    # do técnico, as bolhas com agendamento ficam automaticamente ordenadas pelo
    # horário REAL do reparo (13h antes de 14h antes de 16h), sem precisar
    # arrastar manualmente.
    sched_priority, sched_position, sched_iso = _resolve_schedule(
        chamado, cfg.atlaz_visit_date_tz or "America/Sao_Paulo",
    )
    # iter211aa — Distribui bolhas dentro dos horários disponíveis. Se 2 OS
    # vierem do Atlaz no MESMO slot do mesmo técnico, a segunda é empurrada
    # pro próximo horário livre. Mantém `atlaz_visit_date` original
    # (auditoria) — apenas `scheduled_time` é deslocado.
    original_sched_iso = sched_iso
    if sched_priority == "horario" and sched_iso and assigned:
        adjusted = await _next_available_slot(
            company_id, assigned, sched_iso,
        )
        if adjusted != sched_iso:
            sched_iso = adjusted
            try:
                _dt = datetime.fromisoformat(sched_iso.replace("Z", "+00:00"))
                sched_position = int(_dt.timestamp())
            except (ValueError, TypeError):
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
            "pppoe_user": str(
                ponto.get("username")            # Atlaz V2: PPPoE fica em chamado.ponto.username
                or assinante.get("login")
                or assinante.get("usuario")
                or assinante.get("usuario_pppoe")
                or chamado.get("login")
                or ""
            ).strip(),
        },
        "type": ticket_type,
        "priority": sched_priority,
        "scheduled_time": sched_iso,
        "position": sched_position,
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
        "atlaz_visit_date": chamado.get("visit_date"),  # raw — usado em reassign-existing
        # iter211aa — Quando o slot foi deslocado por estar cheio, guarda
        # o ISO original do Atlaz para auditoria.
        "atlaz_slot_original": (original_sched_iso
                                 if original_sched_iso != sched_iso else None),
        # iter211z — Data ORIGINAL do chamado no Atlaz (não o created_at local).
        # Usado pelo `_ticket_day_iso` (lousa.py) como fallback quando não há
        # `scheduled_time`, garantindo que a bolha caia no dia que veio do Atlaz
        # e não no dia da importação local.
        "atlaz_created_at": (
            chamado.get("data_criacao") or chamado.get("data_abertura")
            or chamado.get("criado_em") or chamado.get("created_at")
            or chamado.get("data")
        ),
        "atlaz_synced_at": now_iso(),
        "atlaz_unassigned": is_unassigned,
    }
    await db.tickets.insert_one(doc)
    return "unassigned" if is_unassigned else "created"


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
    summary["unassigned"] = 0

    created_ids: List[str] = []
    for c in chamados:
        try:
            if cfg.auto_create_bubbles:
                res = await _import_one(c, cfg, company_id)
                if res == "created":
                    summary["created"] += 1
                    created_ids.append(str(c.get("id")))
                elif res == "unassigned":
                    summary["created"] += 1
                    summary["unassigned"] += 1
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
        f"fetched={summary.get('fetched',0)} created={summary['created']} (unassigned={summary['unassigned']}) skipped={summary['skipped']} errors={len(summary['errors'])}",
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


# iter211z — Backfill da data ORIGINAL Atlaz nos tickets já importados.
# Roda uma nova sincronização SÓ pra ler o campo `data_criacao` (ou similar)
# do Atlaz e salvar como `atlaz_created_at` + reposicionar `scheduled_time`
# quando o ticket ainda não tinha. Sem efeito destrutivo: nunca sobrescreve
# scheduled_time existente.
@router.post("/backfill-dates")
async def atlaz_backfill_dates(
    user: dict = Depends(require_role("gestor")),
    dry_run: bool = False,
):
    """Reprocessa tickets Atlaz sem `atlaz_created_at` ou sem `scheduled_time`,
    puxando a data original do chamado direto da API do Atlaz e preenchendo
    os campos. Útil pra corrigir bolhas que caíram em "hoje" depois de uma
    importação onde o Atlaz não retornou `visit_date`.

    Query:
      dry_run=true → apenas conta o que seria atualizado, sem alterar nada.

    Retorna:
      {scanned, would_update, updated, samples: [...]}
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    if not cfg or not cfg.enabled or not cfg.api_key:
        raise HTTPException(400, "Atlaz não configurado para esta empresa.")

    # Busca todos os tickets Atlaz que precisam de correção: ou sem
    # atlaz_created_at, ou com scheduled_time None (caíram no created_at local).
    cursor = db.tickets.find(
        {"company_id": company_id,
         "atlaz_external_id": {"$exists": True, "$ne": None},
         "$or": [{"atlaz_created_at": {"$exists": False}},
                  {"atlaz_created_at": None},
                  {"scheduled_time": None}]},
        {"_id": 0, "id": 1, "atlaz_external_id": 1,
         "scheduled_time": 1, "atlaz_visit_date": 1},
    )
    pending = await cursor.to_list(5000)

    scanned = len(pending)
    updated = 0
    samples: List[Dict[str, Any]] = []

    if scanned == 0:
        return {"scanned": 0, "would_update": 0, "updated": 0, "samples": []}

    # Não há endpoint Atlaz de "buscar 1 chamado por ID" garantido na v2.
    # Estratégia: roda uma `listar_chamados` recente e casa por
    # `atlaz_external_id`. Pra ambientes onde isso não é suficiente,
    # o gestor pode pedir um sync completo pelo endpoint normal.
    try:
        chamados = await _fetch_chamados(cfg)
    except Exception as e:
        raise HTTPException(502, safe_detail(502, e, "Falha ao consultar Atlaz:"))
    by_ext = {str(c.get("id")): c for c in chamados if c.get("id") is not None}

    pending_by_ext = {str(t["atlaz_external_id"]): t for t in pending}
    matched = [ext for ext in pending_by_ext if ext in by_ext]

    for ext_id in matched:
        chamado = by_ext[ext_id]
        ticket = pending_by_ext[ext_id]
        # Decide o novo scheduled_time/priority com _resolve_schedule
        priority, position, sched_iso = _resolve_schedule(
            chamado, cfg.atlaz_visit_date_tz or "America/Sao_Paulo",
        )
        atlaz_created = (
            chamado.get("data_criacao") or chamado.get("data_abertura")
            or chamado.get("criado_em") or chamado.get("created_at")
            or chamado.get("data")
        )
        update_set: Dict[str, Any] = {}
        # Nunca sobrescreve scheduled_time já preenchido (preserva
        # reagendamentos manuais feitos pelo gestor).
        if not ticket.get("scheduled_time") and sched_iso:
            update_set["scheduled_time"] = sched_iso
            update_set["position"] = position
            update_set["priority"] = priority
        if atlaz_created:
            update_set["atlaz_created_at"] = atlaz_created
        if chamado.get("visit_date") and not ticket.get("atlaz_visit_date"):
            update_set["atlaz_visit_date"] = chamado["visit_date"]
        if not update_set:
            continue
        if len(samples) < 6:
            samples.append({
                "id": ticket["id"],
                "atlaz_external_id": ext_id,
                "set": update_set,
            })
        if not dry_run:
            await db.tickets.update_one({"id": ticket["id"]},
                                          {"$set": update_set})
            updated += 1

    return {
        "scanned": scanned,
        "matched_in_atlaz_recent": len(matched),
        "would_update": len(samples) if dry_run else updated,
        "updated": updated,
        "samples": samples,
        "dry_run": dry_run,
    }


# iter211aa — Redistribui bolhas Atlaz já importadas que tenham horários
# duplicados (mesmo técnico + mesmo slot). Útil pra arrumar o backlog
# existente depois do deploy do iter211aa.
@router.post("/redistribute-slots")
async def atlaz_redistribute_slots(
    user: dict = Depends(require_role("gestor")),
    dry_run: bool = False,
):
    """Varre todas as bolhas Atlaz ativas (pendente/aberta/aguardando) com
    `priority='horario'`, agrupa por (técnico, dia, slot), e desloca as
    excedentes (após o `max_per_slot`) para o próximo slot livre. Preserva
    `atlaz_visit_date` para auditoria.

    Query:
      dry_run=true → conta o que seria atualizado, sem alterar nada.

    Retorna:
      {scanned, conflicts_found, would_move, moved, samples}
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID

    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    max_per_slot = int(settings.get("lousa_grid_max_per_slot", 2))
    slot_minutes = int(settings.get("lousa_grid_slot_minutes", 60)) or 60

    try:
        from zoneinfo import ZoneInfo
        tz_br = ZoneInfo("America/Sao_Paulo")
    except Exception:
        tz_br = timezone(timedelta(hours=-3))

    cursor = db.tickets.find(
        {"company_id": company_id,
         "atlaz_external_id": {"$exists": True, "$ne": None},
         "priority": "horario",
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
         "assigned_collaborator_id": {"$ne": None},
         "scheduled_time": {"$ne": None}},
        {"_id": 0, "id": 1, "assigned_collaborator_id": 1,
         "scheduled_time": 1, "atlaz_external_id": 1,
         "client_snapshot.name": 1},
    )
    tickets = await cursor.to_list(5000)

    # Agrupa por (technician_id, dia_local, slot_local)
    groups: Dict[tuple, List[dict]] = {}
    for t in tickets:
        try:
            dt = datetime.fromisoformat(t["scheduled_time"].replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz_br)
        minutes = (local.hour * 60 + local.minute) // slot_minutes * slot_minutes
        slot_key = (
            t["assigned_collaborator_id"],
            local.strftime("%Y-%m-%d"),
            f"{minutes // 60:02d}:{minutes % 60:02d}",
        )
        groups.setdefault(slot_key, []).append({
            **t,
            "_dt_utc": dt.astimezone(timezone.utc),
        })

    conflicts: List[tuple] = [k for k, v in groups.items() if len(v) > max_per_slot]
    moved = 0
    samples: List[Dict[str, Any]] = []

    for key in conflicts:
        members = sorted(groups[key],
                          key=lambda x: x["_dt_utc"])  # mais antigo fica no slot
        # Os primeiros `max_per_slot` permanecem; os demais são deslocados.
        for excess in members[max_per_slot:]:
            new_iso = await _next_available_slot(
                company_id, excess["assigned_collaborator_id"],
                excess["scheduled_time"],
                exclude_ticket_id=excess["id"],
            )
            if new_iso == excess["scheduled_time"]:
                continue  # já é o melhor possível
            try:
                _dt = datetime.fromisoformat(new_iso.replace("Z", "+00:00"))
                new_pos = int(_dt.timestamp())
            except (ValueError, TypeError):
                new_pos = 0
            if len(samples) < 8:
                samples.append({
                    "id": excess["id"],
                    "atlaz_external_id": excess.get("atlaz_external_id"),
                    "client": (excess.get("client_snapshot") or {}).get("name"),
                    "from": excess["scheduled_time"],
                    "to": new_iso,
                })
            if not dry_run:
                await db.tickets.update_one(
                    {"id": excess["id"]},
                    {"$set": {
                        "scheduled_time": new_iso,
                        "position": new_pos,
                        "atlaz_slot_original": (
                            excess.get("atlaz_slot_original")
                            or excess["scheduled_time"]
                        ),
                    }},
                )
                moved += 1

    return {
        "scanned": len(tickets),
        "conflicts_found": len(conflicts),
        "would_move": len(samples) if dry_run else moved,
        "moved": moved,
        "samples": samples,
        "dry_run": dry_run,
    }


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


# ---------------------------------------------------------------------------
# SYNC DE ASSINANTES (Atlaz /listaclientes → db.subscribers)
# ---------------------------------------------------------------------------
async def _fetch_assinantes_page(cfg: AtlazConfig, page: int) -> Dict[str, Any]:
    """Busca uma página de /listaclientes (Atlaz V2). Retorna {assinantes, total_de_paginas}."""
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as cli:
        r = await cli.get(
            f"{ATLAZ_BASE_URL}/listaclientes",
            params={"token": cfg.api_key, "pagina": page},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if data.get("success") != "true":
        raise RuntimeError(f"Atlaz erro: {data.get('msg') or data}")
    return data


def _digits(s: Any) -> str:
    return "".join(c for c in str(s or "") if c.isdigit())


def _slug(s: Optional[str]) -> str:
    """Normaliza string para matching: minúsculas, sem acento, sem espaços extra."""
    if not s:
        return ""
    n = unicodedata.normalize("NFD", str(s))
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return n.lower().strip().replace("  ", " ")


async def _build_branch_index(company_id: str) -> List[Dict[str, str]]:
    """Carrega filiais de `fin_filiais` + `pracas` e retorna lista normalizada.

    Cada item: {id, name, slug, keywords[]} pra match contra cidade/bairro.
    """
    items: List[Dict[str, str]] = []
    for coll in ("fin_filiais", "pracas"):
        async for f in db[coll].find({"company_id": company_id, "active": {"$ne": False}},
                                       {"_id": 0, "id": 1, "name": 1}):
            name = (f.get("name") or "").strip()
            if not name:
                continue
            slug = _slug(name)
            # Remove prefixo "ligo" pra match contra cidade
            keyword = slug
            for prefix in ("ligo ", "filial "):
                if keyword.startswith(prefix):
                    keyword = keyword[len(prefix):]
            items.append({"id": f.get("id"), "name": name,
                           "slug": slug, "keyword": keyword})
    return items


def _derive_branch(branches: List[Dict[str, str]], city: Optional[str],
                    district: Optional[str], document: Optional[str],
                    custom_rules: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Deriva nome da filial a partir do endereço + tipo de documento.

    Heurística (em ordem de precedência):
    0. REGRAS CUSTOMIZADAS (do gestor): match por district/city → branch específico
    1. Cidade bate diretamente com keyword da filial (ex: "Guaratinguetá" ↔ "guaratingueta")
    2. Bairro bate (ex: "Penha" → "LIGO PENHA")
    3. CNPJ (14 dígitos) → "LIGO EMPRESAS" se existir
    4. Cidade RJ default → "LIGO RIO" se existir
    """
    if not branches:
        return None
    city_slug = _slug(city)
    dist_slug = _slug(district)
    # 0) regras customizadas do gestor (precedência máxima)
    if custom_rules:
        for rule in custom_rules:
            mt = (rule.get("match_type") or "").lower()
            val = _slug(rule.get("value"))
            branch_name = rule.get("branch")
            if not val or not branch_name:
                continue
            target = dist_slug if mt == "district" else (city_slug if mt == "city" else "")
            if not target:
                continue
            # match exato OU substring (cobre "Bocaina" vs "BOCAINAS")
            if target == val or val in target or target in val:
                return branch_name
    # 1) match exato por cidade
    for b in branches:
        kw = b["keyword"]
        if not kw:
            continue
        if kw in city_slug or city_slug in kw and kw:
            return b["name"]
    # 2) match por bairro
    if dist_slug:
        for b in branches:
            kw = b["keyword"]
            if not kw or kw in ("empresas", "rio"):
                continue
            if kw in dist_slug:
                return b["name"]
    # 3) CNPJ → empresas
    if document and len(_digits(document)) == 14:
        for b in branches:
            if "empresas" in b["keyword"]:
                return b["name"]
    # 4) fallback RJ
    if "rio" in city_slug or "rj" == _slug(city or "").strip():
        for b in branches:
            if b["keyword"] == "rio":
                return b["name"]
    return None


@router.get("/customers/preview")
async def preview_customers(user: dict = Depends(require_role("gestor"))):
    """Mostra um sample da 1ª página + total — sem persistir nada.
    Útil pro gestor inspecionar o que vai vir antes de sincronizar.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.api_key:
        raise HTTPException(400, "Atlaz não configurado/desabilitado.")
    try:
        page1 = await _fetch_assinantes_page(cfg, 1)
    except Exception as e:
        raise HTTPException(502, safe_detail(502, e, "Falha ao consultar Atlaz:"))
    items = []
    for entry in (page1.get("assinantes") or {}).values():
        a = entry.get("assinante") or {}
        items.append({
            "id_assinante": a.get("id_assinante"),
            "nome": a.get("nome"),
            "cpf_cnpj": a.get("cpf_cnpj"),
            "email": a.get("email"),
            "telefone": a.get("telefone"),
            "dia_de_vencimento": a.get("dia_de_vencimento"),
        })
    total_pages = int(page1.get("total_de_paginas") or 0)
    per_page = len(items)
    return {
        "sample": items[:10],
        "per_page": per_page,
        "total_pages": total_pages,
        "estimated_total": total_pages * per_page,
    }


@router.post("/customers/sync")
async def sync_customers(user: dict = Depends(require_role("gestor"))):
    """Sincroniza assinantes Atlaz → `db.subscribers` (upsert por CPF/CNPJ).
    De-dup também por id_assinante via `external_code = "ATLAZ-<id>"`.

    Salva o telefone em `subscriber_phones` (formato normalizado, só dígitos).
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.api_key:
        raise HTTPException(400, "Atlaz não configurado/desabilitado.")

    stats = {
        "pages_fetched": 0,
        "items_seen": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_doc": 0,
        "errors": 0,
        "phones_attached": 0,
        "addresses_filled": 0,
        "access_points_synced": 0,
        "branch_derived": 0,
        "branch_not_found": 0,
        "snapshot_deactivated": 0,    # iter215 — clientes que sumiram do Atlaz
        "snapshot_reactivated": 0,    # iter215 — voltaram após snapshot diff
        "plans_referenced": set(),
    }
    # iter215 — Snapshot Diff: coleta TODOS atlaz_ids vistos nesse sync.
    # No final, marca como INATIVO os que sumiram da listagem do Atlaz.
    seen_atlaz_ids: set[str] = set()
    started = datetime.now(timezone.utc)
    # Carrega filiais 1x (não muda durante o sync)
    branches = await _build_branch_index(company_id)
    # Carrega regras customizadas de derivação (district/city → branch)
    cfg_doc = await db.atlaz_config.find_one(
        {"company_id": company_id}, {"_id": 0, "branch_rules": 1},
    )
    custom_branch_rules = (cfg_doc or {}).get("branch_rules") or []
    logger.info(
        "[atlaz] sync_customers branches=%s custom_rules=%d",
        [b["name"] for b in branches], len(custom_branch_rules),
    )
    try:
        # Página 1 — descobre total de páginas
        page1 = await _fetch_assinantes_page(cfg, 1)
        total_pages = int(page1.get("total_de_paginas") or 1)
        stats["total_pages"] = total_pages
        pages_data = [page1]
        # Demais páginas (limit em 100 pra não estourar)
        for p in range(2, min(total_pages, 100) + 1):
            try:
                pages_data.append(await _fetch_assinantes_page(cfg, p))
            except Exception as e:
                logger.warning("[atlaz] sync_customers page %d falhou: %s", p, e)
                stats["errors"] += 1

        for pg_data in pages_data:
            stats["pages_fetched"] += 1
            for entry in (pg_data.get("assinantes") or {}).values():
                a = entry.get("assinante") or {}
                pontos = entry.get("pontos_de_acesso") or []
                stats["items_seen"] += 1
                doc_cpf = _digits(a.get("cpf_cnpj"))
                ext_id = a.get("id_assinante")
                if not doc_cpf and not ext_id:
                    stats["skipped_no_doc"] += 1
                    continue

                ext_code = f"ATLAZ-{ext_id}" if ext_id else None
                phone_raw = _digits(a.get("telefone"))

                # ===== ENDEREÇO + PPPoE + Status do 1º ponto ATIVO =====
                primary_point: Optional[Dict[str, Any]] = None
                addresses: List[Dict[str, Any]] = []
                pppoe_user: Optional[str] = None
                derived_status: str = "ATIVO"
                primary_plan_atlaz_id: Optional[str] = None
                primary_plan_name: Optional[str] = None
                for pt in pontos:
                    if not isinstance(pt, dict):
                        continue
                    # Endereço
                    if any(pt.get(k) for k in ("logradouro", "bairro", "cidade",
                                                 "cep", "numero", "estado")):
                        lat_lng = (pt.get("gps") or "").split(",")
                        try:
                            lat = float(lat_lng[0].strip()) if len(lat_lng) >= 1 and lat_lng[0].strip() else None
                            lng = float(lat_lng[1].strip()) if len(lat_lng) >= 2 and lat_lng[1].strip() else None
                        except (ValueError, IndexError):
                            lat, lng = None, None
                        addr = {
                            "id": f"addr-{uuid.uuid4().hex[:10]}",
                            "label": pt.get("plano") or "Atlaz",
                            "street": (pt.get("logradouro") or "").strip()[:200] or None,
                            "number": (str(pt.get("numero") or "").strip())[:30] or None,
                            "complement": (pt.get("complemento") or "").strip()[:120] or None,
                            "district": (pt.get("bairro") or "").strip()[:120] or None,
                            "city": (pt.get("cidade") or "").strip()[:120] or None,
                            "state": (pt.get("estado") or "").strip()[:4] or None,
                            "zip_code": _digits(pt.get("cep"))[:9] or None,
                            "lat": lat, "lng": lng,
                            "source": "atlaz",
                            "atlaz_id_ponto": pt.get("id_ponto"),
                            "is_primary": primary_point is None,
                        }
                        addresses.append(addr)
                    # 1º ponto ativo vira primário
                    if primary_point is None and str(pt.get("status") or "").lower() in (
                            "ativo", "active", "1", "true"):
                        primary_point = pt
                        pppoe_user = (pt.get("username") or "").strip()[:80] or None
                        primary_plan_atlaz_id = pt.get("id_plano")
                        primary_plan_name = pt.get("plano")
                # Status mapping: pelo menos 1 ponto ativo → ATIVO; nenhum ativo → INATIVO
                if pontos:
                    statuses = [str(p.get("status") or "").lower() for p in pontos if isinstance(p, dict)]
                    if any(s in ("ativo", "active") for s in statuses):
                        derived_status = "ATIVO"
                    elif any(s in ("bloqueado", "suspenso", "suspended", "blocked") for s in statuses):
                        derived_status = "INADIMPLENTE"
                    elif any(s in ("inativo", "inactive", "cancelado") for s in statuses):
                        derived_status = "INATIVO"

                # Deriva FILIAL a partir do primeiro endereço + tipo de doc
                derived_branch: Optional[str] = None
                if addresses:
                    a0 = addresses[0]
                    derived_branch = _derive_branch(
                        branches, a0.get("city"), a0.get("district"), doc_cpf,
                        custom_rules=custom_branch_rules,
                    )
                if derived_branch:
                    stats["branch_derived"] += 1
                else:
                    stats["branch_not_found"] += 1

                payload = {
                    "company_id": company_id,
                    "name": (a.get("nome") or "").strip()[:160] or "—",
                    "document": doc_cpf or None,
                    "email": (a.get("email") or "").strip()[:200] or None,
                    "external_code": ext_code,
                    "due_day": (int(a.get("dia_de_vencimento"))
                                 if str(a.get("dia_de_vencimento") or "").isdigit() else None),
                    "status": derived_status,
                    "pppoe_user": pppoe_user,
                    "branch": derived_branch,
                    "metadata": {
                        "atlaz_id_assinante": ext_id,
                        "atlaz_plan_id": primary_plan_atlaz_id,
                        "atlaz_plan_name": primary_plan_name,
                        "atlaz_access_points_count": len(pontos),
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if primary_plan_atlaz_id:
                    stats["plans_referenced"].add(str(primary_plan_atlaz_id))

                # Match: 1) document; 2) external_code (ATLAZ-id)
                match = None
                if doc_cpf:
                    match = await db.subscribers.find_one(
                        {"company_id": company_id, "document": doc_cpf},
                        {"_id": 0, "id": 1, "addresses": 1},
                    )
                if not match and ext_code:
                    match = await db.subscribers.find_one(
                        {"company_id": company_id, "external_code": ext_code},
                        {"_id": 0, "id": 1, "addresses": 1},
                    )

                # Merge de endereços: sempre substitui pelos do Atlaz (fonte de verdade)
                if addresses:
                    payload["addresses"] = addresses
                    stats["addresses_filled"] += 1

                if match:
                    sid = match["id"]
                    # iter215 — Snapshot reactivation: se estava INATIVO e
                    # voltou na listagem, reativa.
                    if match.get("status") == "INATIVO" and \
                       match.get("deactivation_reason") == "atlaz_snapshot_diff":
                        payload.pop("status", None)  # mantém status do payload (ATIVO/etc)
                        payload["deactivation_date"] = None
                        payload["deactivation_reason"] = None
                        stats["snapshot_reactivated"] += 1
                    await db.subscribers.update_one(
                        {"id": sid}, {"$set": payload}
                    )
                    stats["updated"] += 1
                else:
                    sid = f"sub-{uuid.uuid4().hex[:12]}"
                    payload.update({
                        "id": sid,
                        "created_at": payload["updated_at"],
                    })
                    await db.subscribers.insert_one(payload)
                    payload.pop("_id", None)
                    stats["inserted"] += 1
                if ext_id:
                    seen_atlaz_ids.add(str(ext_id))

                # ===== PERSISTIR endereços ALSO em coleção dedicada =====
                # A listagem (`/subscribers`) lê dessa coleção, não do array
                # embedded. Limpa endereços antigos do Atlaz e re-insere
                # (fonte de verdade é o Atlaz).
                if addresses:
                    await db.subscriber_addresses.delete_many(
                        {"company_id": company_id, "subscriber_id": sid,
                         "source": "atlaz"},
                    )
                    addr_docs = []
                    for i, a_obj in enumerate(addresses):
                        addr_docs.append({
                            **a_obj,
                            "company_id": company_id,
                            "subscriber_id": sid,
                            "is_primary": i == 0,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                    if addr_docs:
                        try:
                            await db.subscriber_addresses.insert_many(addr_docs, ordered=False)
                        except Exception as e:
                            logger.warning("[atlaz] addresses insert falhou: %s", e)

                # ===== PERSISTIR pontos_de_acesso em coleção dedicada =====
                # 1 doc por ponto. Upsert via (company_id, atlaz_id_ponto).
                if pontos:
                    from pymongo import UpdateOne
                    ap_ops = []
                    for pt in pontos:
                        if not isinstance(pt, dict):
                            continue
                        id_ponto = pt.get("id_ponto")
                        if not id_ponto:
                            continue
                        ap_doc = {
                            "company_id": company_id,
                            "subscriber_id": sid,
                            "subscriber_external_id": str(ext_id) if ext_id else None,
                            "atlaz_id_ponto": str(id_ponto),
                            "atlaz_id_plano": str(pt.get("id_plano")) if pt.get("id_plano") else None,
                            "plan_name": pt.get("plano"),
                            "pppoe_user": pt.get("username"),
                            "status": pt.get("status"),
                            "address": {
                                "street": pt.get("logradouro"),
                                "number": pt.get("numero"),
                                "complement": pt.get("complemento"),
                                "district": pt.get("bairro"),
                                "city": pt.get("cidade"),
                                "state": pt.get("estado"),
                                "zip_code": _digits(pt.get("cep")) or None,
                                "gps": pt.get("gps"),
                            },
                            "isento": pt.get("isento"),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        ap_ops.append(UpdateOne(
                            {"company_id": company_id, "atlaz_id_ponto": str(id_ponto)},
                            {"$set": ap_doc,
                             "$setOnInsert": {
                                 "id": f"ap-{uuid.uuid4().hex[:10]}",
                                 "created_at": ap_doc["updated_at"],
                             }},
                            upsert=True,
                        ))
                    if ap_ops:
                        try:
                            await db.subscriber_access_points.bulk_write(ap_ops, ordered=False)
                            stats["access_points_synced"] += len(ap_ops)
                        except Exception as e:
                            logger.warning("[atlaz] access_points bulk falhou: %s", e)

                # Telefone (normaliza + dedupe na coleção subscriber_phones)
                if phone_raw and len(phone_raw) >= 10:
                    existing = await db.subscriber_phones.find_one(
                        {"company_id": company_id, "phone": phone_raw},
                        {"_id": 0, "subscriber_id": 1},
                    )
                    if not existing:
                        await db.subscriber_phones.insert_one({
                            "id": f"sph-{uuid.uuid4().hex[:10]}",
                            "company_id": company_id,
                            "subscriber_id": sid,
                            "phone": phone_raw,
                            "normalized_number": phone_raw,
                            "raw_number": phone_raw,
                            "label": "atlaz",
                            "is_primary": True,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                        stats["phones_attached"] += 1

    except Exception as e:
        logger.exception("[atlaz] sync_customers falhou: %s", e)
        stats["errors"] += 1
        stats["fatal_error"] = str(e)

    # iter215 — Snapshot Diff: marca como INATIVO subscribers que existem
    # no DB com `external_code=ATLAZ-*` mas NÃO apareceram nessa sync.
    # Só executa se sync foi bem-sucedido (>= 5 itens vistos pra evitar
    # disparar mass-deactivation em sync vazio/quebrado).
    if stats["items_seen"] >= 5 and not stats.get("fatal_error"):
        seen_codes = {f"ATLAZ-{aid}" for aid in seen_atlaz_ids}
        now_iso = datetime.now(timezone.utc).isoformat()
        # Query: do tenant, vieram do Atlaz, ainda não-inativos, mas
        # NÃO apareceram nesse sync. Bulk update.
        result = await db.subscribers.update_many(
            {
                "company_id": company_id,
                "external_code": {
                    "$regex": "^ATLAZ-",
                    "$nin": list(seen_codes),
                },
                "status": {"$nin": ["INATIVO", "CANCELADO"]},
            },
            {"$set": {
                "status": "INATIVO",
                "deactivation_date": now_iso,
                "deactivation_reason": "atlaz_snapshot_diff",
                "cancellation_reason": "Removido do Atlaz",
                "updated_at": now_iso,
            }},
        )
        stats["snapshot_deactivated"] = result.modified_count

    stats["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    # Converte set -> list para serialização BSON/JSON
    if isinstance(stats.get("plans_referenced"), set):
        stats["plans_referenced"] = sorted(stats["plans_referenced"])
    # Persiste o último sync de assinantes (para mostrar no painel)
    await db.atlaz_config.update_one(
        {"company_id": company_id},
        {"$set": {"last_customer_sync_at": stats["finished_at"],
                   "last_customer_sync_stats": stats}},
        upsert=True,
    )
    return stats


@router.get("/customers/stats")
async def customers_stats(user: dict = Depends(require_role("gestor"))):
    """KPIs rápidos: total no Atlaz, total local, último sync, etc."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg_doc = await db.atlaz_config.find_one(
        {"company_id": company_id},
        {"_id": 0, "last_customer_sync_at": 1, "last_customer_sync_stats": 1, "enabled": 1},
    ) or {}
    local_total = await db.subscribers.count_documents({"company_id": company_id})
    local_from_atlaz = await db.subscribers.count_documents(
        {"company_id": company_id, "external_code": {"$regex": "^ATLAZ-"}}
    )
    return {
        "configured": bool(cfg_doc.get("enabled")),
        "local_total": local_total,
        "local_from_atlaz": local_from_atlaz,
        "last_sync_at": cfg_doc.get("last_customer_sync_at"),
        "last_sync_stats": cfg_doc.get("last_customer_sync_stats"),
    }


# ===========================================================================
# Branch rules — Regras de derivação de filial por bairro/cidade
# ===========================================================================
class BranchRule(BaseModel):
    match_type: str = Field(..., description="'district' (bairro) ou 'city' (cidade)")
    value: str = Field(..., min_length=1, max_length=120,
                       description="Texto a casar (case/acento-insensitive)")
    branch: str = Field(..., min_length=1, max_length=120,
                        description="Nome da filial (ex: LIGO CPX)")


class BranchRulesIn(BaseModel):
    rules: List[BranchRule]


@router.get("/branch-rules")
async def get_branch_rules(user: dict = Depends(require_role("gestor"))):
    """Retorna regras customizadas de derivação de filial."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.atlaz_config.find_one(
        {"company_id": company_id},
        {"_id": 0, "branch_rules": 1, "filiais": 1},
    ) or {}
    return {
        "rules": cfg.get("branch_rules") or [],
        "available_branches": cfg.get("filiais") or [],
    }


@router.put("/branch-rules")
async def put_branch_rules(payload: BranchRulesIn,
                            user: dict = Depends(require_role("gestor"))):
    """Substitui o conjunto inteiro de regras. Validação leve."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    rules = [r.model_dump() for r in payload.rules]
    for r in rules:
        if r["match_type"] not in ("district", "city"):
            raise HTTPException(400, f"match_type inválido: {r['match_type']}")
    await db.atlaz_config.update_one(
        {"company_id": company_id},
        {"$set": {"branch_rules": rules,
                  "branch_rules_updated_at": datetime.now(timezone.utc).isoformat(),
                  "branch_rules_updated_by": user.get("email")}},
        upsert=True,
    )
    return {"ok": True, "rules_count": len(rules)}


@router.post("/branch-rules/apply-now")
async def apply_branch_rules_now(user: dict = Depends(require_role("gestor"))):
    """Reaplica regras de filial em TODOS os subscribers SEM re-sincronizar Atlaz.

    Recarrega regras + branches do banco, percorre subscribers com endereço
    cadastrado e atualiza `subscriber.branch` conforme regras atuais.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    branches = await _build_branch_index(company_id)
    cfg = await db.atlaz_config.find_one(
        {"company_id": company_id}, {"_id": 0, "branch_rules": 1},
    ) or {}
    custom_rules = cfg.get("branch_rules") or []
    from pymongo import UpdateOne
    ops = []
    changed = 0
    unchanged = 0
    no_address = 0
    async for sub in db.subscribers.find(
        {"company_id": company_id}, {"_id": 0, "id": 1, "branch": 1,
                                      "addresses": 1, "document": 1},
    ):
        addrs = sub.get("addresses") or []
        if not addrs:
            no_address += 1
            continue
        a0 = addrs[0] or {}
        new_branch = _derive_branch(
            branches, a0.get("city"), a0.get("district"), sub.get("document"),
            custom_rules=custom_rules,
        )
        if new_branch != sub.get("branch"):
            ops.append(UpdateOne(
                {"company_id": company_id, "id": sub["id"]},
                {"$set": {"branch": new_branch,
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
            ))
            changed += 1
        else:
            unchanged += 1
    if ops:
        for i in range(0, len(ops), 1000):
            await db.subscribers.bulk_write(ops[i:i + 1000], ordered=False)
    return {"changed": changed, "unchanged": unchanged,
            "no_address": no_address, "rules_count": len(custom_rules)}


async def _customers_sync_internal(company_id: str) -> Dict[str, Any]:
    """Versão interna do sync de assinantes — usada pelo cron noturno.
    Replica a lógica do endpoint POST /customers/sync sem depender de auth.
    """
    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.api_key:
        return {"skipped": "atlaz_disabled"}

    stats = {
        "pages_fetched": 0,
        "items_seen": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_doc": 0,
        "errors": 0,
        "phones_attached": 0,
    }
    started = datetime.now(timezone.utc)
    try:
        page1 = await _fetch_assinantes_page(cfg, 1)
        total_pages = int(page1.get("total_de_paginas") or 1)
        stats["total_pages"] = total_pages
        pages_data = [page1]
        for p in range(2, min(total_pages, 100) + 1):
            try:
                pages_data.append(await _fetch_assinantes_page(cfg, p))
            except Exception as e:
                logger.warning("[atlaz] cron sync page %d falhou: %s", p, e)
                stats["errors"] += 1

        for pg_data in pages_data:
            stats["pages_fetched"] += 1
            for entry in (pg_data.get("assinantes") or {}).values():
                a = entry.get("assinante") or {}
                stats["items_seen"] += 1
                doc_cpf = _digits(a.get("cpf_cnpj"))
                ext_id = a.get("id_assinante")
                if not doc_cpf and not ext_id:
                    stats["skipped_no_doc"] += 1
                    continue
                ext_code = f"ATLAZ-{ext_id}" if ext_id else None
                phone_raw = _digits(a.get("telefone"))
                payload = {
                    "company_id": company_id,
                    "name": (a.get("nome") or "").strip()[:160] or "—",
                    "document": doc_cpf or None,
                    "email": (a.get("email") or "").strip()[:200] or None,
                    "external_code": ext_code,
                    "due_day": (int(a.get("dia_de_vencimento"))
                                 if str(a.get("dia_de_vencimento") or "").isdigit() else None),
                    "status": "ATIVO",
                    "metadata": {"atlaz_id_assinante": ext_id},
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                match = None
                if doc_cpf:
                    match = await db.subscribers.find_one(
                        {"company_id": company_id, "document": doc_cpf},
                        {"_id": 0, "id": 1},
                    )
                if not match and ext_code:
                    match = await db.subscribers.find_one(
                        {"company_id": company_id, "external_code": ext_code},
                        {"_id": 0, "id": 1},
                    )
                if match:
                    sid = match["id"]
                    await db.subscribers.update_one({"id": sid}, {"$set": payload})
                    stats["updated"] += 1
                else:
                    sid = f"sub-{uuid.uuid4().hex[:12]}"
                    payload.update({"id": sid, "created_at": payload["updated_at"]})
                    await db.subscribers.insert_one(payload)
                    payload.pop("_id", None)
                    stats["inserted"] += 1
                if phone_raw and len(phone_raw) >= 10:
                    existing = await db.subscriber_phones.find_one(
                        {"company_id": company_id, "phone": phone_raw},
                        {"_id": 0, "subscriber_id": 1},
                    )
                    if not existing:
                        await db.subscriber_phones.insert_one({
                            "id": f"sph-{uuid.uuid4().hex[:10]}",
                            "company_id": company_id,
                            "subscriber_id": sid,
                            "phone": phone_raw,
                            "label": "atlaz",
                            "is_primary": True,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                        stats["phones_attached"] += 1
    except Exception as e:
        logger.exception("[atlaz] cron sync falhou: %s", e)
        stats["errors"] += 1
        stats["fatal_error"] = str(e)

    stats["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    stats["triggered_by"] = "cron_nightly_22h"
    await db.atlaz_config.update_one(
        {"company_id": company_id},
        {"$set": {"last_customer_sync_at": stats["finished_at"],
                   "last_customer_sync_stats": stats}},
        upsert=True,
    )
    return stats


async def nightly_customers_sync_job() -> None:
    """Cron job: roda às 22h00 (America/Sao_Paulo) para TODAS as empresas
    com Atlaz habilitado. Falha silenciosa por tenant — não derruba o
    scheduler.
    """
    logger.info("[atlaz] nightly_customers_sync_job INICIANDO")
    cursor = db.atlaz_config.find({"enabled": True}, {"_id": 0, "company_id": 1})
    total_companies = 0
    async for cfg_doc in cursor:
        cid = cfg_doc.get("company_id") or DEMO_COMPANY_ID
        total_companies += 1
        try:
            stats = await _customers_sync_internal(cid)
            logger.info("[atlaz] nightly sync cid=%s -> %s", cid, stats)
        except Exception as e:
            logger.exception("[atlaz] nightly sync FALHOU cid=%s: %s", cid, e)
    logger.info("[atlaz] nightly_customers_sync_job FIM (%d empresas)", total_companies)


@router.post("/reassign-existing")
async def reassign_existing_tickets(user: dict = Depends(require_role("gestor"))):
    """Re-resolve o colaborador de TODAS as bolhas Atlaz pendentes da empresa
    aplicando a lógica atual de mapping (technician_to_collaborator + filial).

    Usado quando o gestor altera o mapping ou quando bolhas chegaram com
    fallback errado em versões antigas. Não toca em bolhas já abertas/finalizadas.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(company_id)

    cursor = db.tickets.find(
        {"company_id": company_id,
         "atlaz_external_id": {"$ne": None},
         "status": "pendente"},
        {"_id": 0},
    )

    inbox_id: Optional[str] = None  # lazy-init, só cria placeholder se precisar

    moved = 0
    unchanged = 0
    moved_to_inbox = 0
    rescheduled = 0  # bolhas que tiveram priority/position reaplicados pelo visit_date
    items: List[Dict[str, Any]] = []
    async for t in cursor:
        # Reconstrói "shape Atlaz" mínimo para passar pelo _resolve_collaborator
        # `data_visita` é o nome do campo que persistimos no _import_one
        atlaz_visit_date = t.get("atlaz_visit_date") or t.get("scheduled_time")
        chamado = {
            "tecnico": {"nome": t.get("atlaz_tecnico_nome") or ""},
            "ponto": {"cidade": t.get("atlaz_filial") or ""},
            "visit_date": atlaz_visit_date,
        }
        new_cid = await _resolve_collaborator(chamado, cfg, company_id)
        old_cid = t.get("assigned_collaborator_id")

        # Schedule: re-aplica priority/position pelo visit_date
        sched_priority, sched_position, sched_iso = _resolve_schedule(
            chamado, cfg.atlaz_visit_date_tz or "America/Sao_Paulo",
        )
        sched_change: Dict[str, Any] = {}
        if (
            sched_priority != t.get("priority")
            or sched_position != t.get("position", 0)
            or (sched_iso and sched_iso != t.get("scheduled_time"))
        ):
            sched_change = {
                "priority": sched_priority,
                "position": sched_position,
            }
            if sched_iso:
                sched_change["scheduled_time"] = sched_iso

        if not new_cid:
            # Sem técnico mapeável → manda pro inbox Atlaz
            if inbox_id is None:
                inbox_id = await _get_or_create_unassigned_inbox(company_id)
            if old_cid != inbox_id:
                update = {
                    "assigned_collaborator_id": inbox_id,
                    "atlaz_unassigned": True,
                    "atlaz_reassigned_at": now_iso(),
                    **sched_change,
                }
                await db.tickets.update_one({"id": t["id"]}, {"$set": update})
                moved_to_inbox += 1
                if sched_change:
                    rescheduled += 1
                items.append({
                    "id": t["id"], "ext": t.get("atlaz_external_id"),
                    "from": old_cid, "to": inbox_id,
                    "reason": "no_technician_match",
                    "tecnico_atlaz": t.get("atlaz_tecnico_nome"),
                    "client": (t.get("client_snapshot") or {}).get("name"),
                })
            else:
                # já no inbox; mas pode ter precisar reagendar
                if sched_change:
                    await db.tickets.update_one({"id": t["id"]}, {"$set": sched_change})
                    rescheduled += 1
                else:
                    unchanged += 1
        elif new_cid != old_cid:
            update = {
                "assigned_collaborator_id": new_cid,
                "atlaz_unassigned": False,
                "atlaz_reassigned_at": now_iso(),
                **sched_change,
            }
            await db.tickets.update_one({"id": t["id"]}, {"$set": update})
            moved += 1
            if sched_change:
                rescheduled += 1
            items.append({
                "id": t["id"], "ext": t.get("atlaz_external_id"),
                "from": old_cid, "to": new_cid,
                "reason": "remapped",
                "tecnico_atlaz": t.get("atlaz_tecnico_nome"),
                "client": (t.get("client_snapshot") or {}).get("name"),
            })
        else:
            # Mesmo técnico — pode precisar só reagendar
            if sched_change:
                await db.tickets.update_one({"id": t["id"]}, {"$set": sched_change})
                rescheduled += 1
            else:
                unchanged += 1

    await _log_sync(
        company_id, "reassign", "ok",
        f"moved={moved} to_inbox={moved_to_inbox} rescheduled={rescheduled} unchanged={unchanged}",
    )
    return {
        "ok": True,
        "moved": moved,
        "moved_to_inbox": moved_to_inbox,
        "rescheduled": rescheduled,
        "unchanged": unchanged,
        "inbox_collaborator_id": inbox_id,
        "items": items[:50],
    }


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
