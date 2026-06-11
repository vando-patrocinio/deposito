"""SmartOLT AI — Worker de monitoramento inteligente da rede.

Inspirado em padrões 2026 (Google Cloud Autonomous Networks, Extreme Agent One):
detecta "outage events" agrupando ONUs offline pelo eixo OLT+PON usando
clustering temporal simples — quando ≥N ONUs no mesmo PON ficam LOS dentro
de uma janela de tempo, dispara um evento de outage.

Threshold dinâmico (regra do gestor):
- ≥10 ONUs em LOS no mesmo PON  **OU**
- ≥50% da porta em LOS
o que vier primeiro.

Comunicação Agent-to-Agent (A2A pattern):
- SmartOLT AI grava outages em `network_outages` collection
- WhatsApp IA (atendimento) consulta antes de responder: se o phone do cliente
  pertence a um outage ativo, injeta contexto no system_prompt (RECEPTIVO)
- Para o modo ATIVO: cria *rascunhos* em `outage_drafts` que o atendente
  humano confirma com 1 clique antes de enviar (anti-spam).
- Para o CO-PILOTO INTERNO: insere mensagem `direction="internal"` em
  `aihub_wa_messages`, visível apenas para o atendente no chat (nunca
  enviada via Baileys).

Como o atendimento humano fica sabendo: ao abrir uma conversa marcada
com `outage_active=true`, o chat exibe nota amarela "IA — só você vê"
explicando a pane, e a aba SmartOLT AI lista os rascunhos prontos pra
aprovação em massa.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["wa.message.persisted"],
    "company_id_required": True,
}

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("smartolt_ai")

# Threshold dinâmico (regra do gestor — confirmada na sessão atual)
OUTAGE_MIN_LOS = 10        # mínimo absoluto de ONUs LOS
OUTAGE_MIN_PCT = 50.0      # OU 50% da porta — o que vier primeiro
OUTAGE_WINDOW_MIN = 15     # janela temporal (mesmo evento)
OUTAGE_RESOLVE_MIN = 5     # cooldown antes de marcar como resolvido
INTERVAL_SECONDS = 30      # worker roda a cada 30s

# Templates default (sobrescritos por aihub_settings.key=smartolt_outage_templates)
DEFAULT_TEMPLATES = {
    "proactive": (
        "Olá! Identificamos uma instabilidade na rede que está afetando "
        "sua região (OLT {olt} · porta {port}). Nossa equipe técnica já "
        "foi acionada e está trabalhando na normalização. Assim que voltar, "
        "te aviso por aqui. Sem necessidade de reiniciar o equipamento."
    ),
    "resolved": (
        "Boa notícia! ✅ A pane na sua região foi resolvida. Sua conexão "
        "deve estar normalizada agora. Qualquer dúvida é só chamar."
    ),
    "internal_assist": (
        "PANE ATIVA · OLT {olt} · Placa {board} · Porta {port}\n"
        "{los_count} de {total_count} ONUs em LOS ({severity_pct}%) — detectado há ~{duration_min}min.\n"
        "NÃO peça reset de modem. Equipe técnica já foi notificada."
    ),
    "internal_resolved": (
        "PANE RESOLVIDA · OLT {olt} · Placa {board} · Porta {port}\n"
        "Conexão normalizada há ~{since_resolved_min}min. Pode atender padrão."
    ),
}


async def _load_templates(company_id: str) -> Dict[str, str]:
    cfg = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": "smartolt_outage_templates"},
        {"_id": 0, "templates": 1},
    )
    saved = (cfg or {}).get("templates") or {}
    return {**DEFAULT_TEMPLATES, **{k: v for k, v in saved.items() if v}}


def _fmt(tpl: str, outage: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> str:
    ctx = {
        "olt": outage.get("olt_name", ""),
        "board": outage.get("board", ""),
        "port": outage.get("port", ""),
        "vlan": outage.get("vlan", ""),
        "los_count": outage.get("los_count", 0),
        "total_count": outage.get("total_count", 0),
        "severity_pct": outage.get("severity_pct", 0),
        "duration_min": 0,
        "since_resolved_min": 0,
    }
    if outage.get("first_detected_at"):
        try:
            fdt = datetime.fromisoformat(outage["first_detected_at"])
            ctx["duration_min"] = int((datetime.now(timezone.utc) - fdt).total_seconds() / 60)
        except Exception:
            pass
    if outage.get("resolved_at"):
        try:
            rdt = datetime.fromisoformat(outage["resolved_at"])
            ctx["since_resolved_min"] = int((datetime.now(timezone.utc) - rdt).total_seconds() / 60)
        except Exception:
            pass
    if extra:
        ctx.update(extra)
    try:
        return tpl.format(**ctx)
    except Exception:
        return tpl


async def _phones_with_existing_chat(company_id: str, phones: List[str]) -> Set[str]:
    """Retorna o subset de phones que já têm pelo menos 1 msg em aihub_wa_messages.
    Usado para decidir onde inserir notas internas (co-piloto)."""
    if not phones:
        return set()
    found: Set[str] = set()
    async for m in db.aihub_wa_messages.find(
        {"company_id": company_id, "phone": {"$in": phones}},
        {"_id": 0, "phone": 1},
    ):
        if m.get("phone"):
            found.add(m["phone"])
    return found


async def _create_outage_drafts(company_id: str, outage: Dict[str, Any],
                                  templates: Dict[str, str],
                                  kind: str = "outage_proactive") -> int:
    """Cria 1 rascunho por affected_phone. Anti-duplicado: se já existe
    rascunho do mesmo kind pro mesmo outage+phone, pula.
    """
    phones = outage.get("affected_phones") or []
    if not phones:
        return 0
    tpl_key = "proactive" if kind == "outage_proactive" else "resolved"
    text = _fmt(templates[tpl_key], outage)
    # Resolve subscriber names em batch (UX)
    subs_by_phone: Dict[str, Dict[str, Any]] = {}
    try:
        async for sub in db.subscribers.find(
            {"company_id": company_id,
             "phones.number": {"$in": phones}},
            {"_id": 0, "id": 1, "name": 1, "phones": 1, "external_code": 1},
        ):
            for p in (sub.get("phones") or []):
                ph = p.get("number") if isinstance(p, dict) else str(p)
                if ph:
                    digits = "".join(c for c in ph if c.isdigit())
                    subs_by_phone[digits] = {
                        "id": sub.get("id"),
                        "name": sub.get("name"),
                        "external_code": sub.get("external_code"),
                    }
    except Exception:
        pass
    created = 0
    for ph in phones:
        existing = await db.outage_drafts.find_one(
            {"company_id": company_id, "outage_id": outage["id"],
             "phone": ph, "kind": kind},
            {"_id": 0, "id": 1},
        )
        if existing:
            continue
        sub = subs_by_phone.get(ph) or {}
        await db.outage_drafts.insert_one({
            "id": f"draft-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "outage_id": outage["id"],
            "outage_key": outage.get("key"),
            "olt_name": outage.get("olt_name"),
            "board": outage.get("board"),
            "port": outage.get("port"),
            "kind": kind,
            "phone": ph,
            "subscriber_id": sub.get("id"),
            "subscriber_name": sub.get("name"),
            "subscriber_external_code": sub.get("external_code"),
            "text": text,
            "status": "pending",
            "created_at": now_iso(),
        })
        created += 1
    if created:
        logger.info("[smartolt-ai] %d rascunhos %s criados para outage %s",
                     created, kind, outage.get("key"))
    return created


async def _insert_internal_notes(company_id: str, outage: Dict[str, Any],
                                   templates: Dict[str, str],
                                   kind: str = "outage_active") -> int:
    """Insere mensagem direction='internal' (NUNCA enviada) em todos os chats
    dos affected_phones que JÁ TÊM histórico. Visível só para o atendente.
    Anti-duplicado: 1 nota por (outage_id, phone, kind).
    """
    phones = outage.get("affected_phones") or []
    if not phones:
        return 0
    chats = await _phones_with_existing_chat(company_id, phones)
    if not chats:
        return 0
    tpl_key = "internal_assist" if kind == "outage_active" else "internal_resolved"
    text = _fmt(templates[tpl_key], outage)
    inserted = 0
    for ph in chats:
        # Dedup: já tem nota interna desse outage+kind pra esse phone?
        existing = await db.aihub_wa_messages.find_one(
            {"company_id": company_id, "phone": ph,
             "direction": "internal",
             "outage_id": outage["id"],
             "internal_kind": kind},
            {"_id": 0, "id": 1},
        )
        if existing:
            continue
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "direction": "internal",            # NUNCA enviado via Baileys
            "internal_kind": kind,               # "outage_active" | "outage_resolved"
            "phone": ph,
            "text": text,
            "outage_id": outage["id"],
            "outage_key": outage.get("key"),
            "auto_reply": True,
            "created_at": now_iso(),
            # marcadores explícitos pro frontend não confundir
            "is_internal_note": True,
            "visible_to_client": False,
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=(existing or {}).get("company_id"),
                source="smartolt_ai",
                payload={},
            )
        except Exception:
            pass
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=company_id,
                source="smartolt_ai",
                payload={},
            )
        except Exception:
            pass
        inserted += 1
    if inserted:
        logger.info("[smartolt-ai] %d notas internas (%s) inseridas para outage %s",
                     inserted, kind, outage.get("key"))
    return inserted


async def _generate_ai_insight(company_id: str, outage_doc: Dict[str, Any],
                                  recent_history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Chama Claude (via Motor IA) pra analisar a pane e gerar insight.

    Retorna {priority, headline, recommendation, model} ou None se falhar.
    Falha silenciosa — detecção segue funcionando sem o insight.
    """
    try:
        from services.motor_ia import chat_completion
    except ImportError:
        return None

    # Constroi resumo factual da pane
    hr_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
    period = ("madrugada" if hr_brt < 6 else "manhã" if hr_brt < 12
              else "tarde" if hr_brt < 18 else "noite")
    hist_lines = []
    for h in recent_history[:5]:
        dur = h.get("duration_minutes") or "?"
        hist_lines.append(
            f"- {h.get('olt_name')} placa {h.get('board')} porta {h.get('port')} "
            f"· {h.get('los_count')}/{h.get('total_count')} LOS "
            f"({h.get('severity_pct')}%) · durou {dur}min"
        )
    history_str = ("\n".join(hist_lines)
                    if hist_lines else "Nenhuma pane recente nesta OLT.")

    user_msg = (
        f"PANE DETECTADA AGORA:\n"
        f"- OLT: {outage_doc.get('olt_name')}\n"
        f"- Placa {outage_doc.get('board')} · Porta {outage_doc.get('port')}"
        f"{' · VLAN ' + outage_doc.get('vlan') if outage_doc.get('vlan') else ''}\n"
        f"- {outage_doc.get('los_count')} de {outage_doc.get('total_count')} "
        f"ONUs em LOS ({outage_doc.get('severity_pct')}%)\n"
        f"- {len(outage_doc.get('affected_phones') or [])} clientes com telefone cadastrado\n"
        f"- Regra disparada: {outage_doc.get('trigger_rule')}\n"
        f"- Horário: {period} (hora local BRT ~{hr_brt}h)\n\n"
        f"HISTÓRICO DE PANES RECENTES (últimos 7 dias):\n{history_str}\n\n"
        "Gere análise no formato JSON exato:\n"
        "{\n"
        '  "priority": "critica" | "alta" | "media" | "baixa",\n'
        '  "headline": "1 frase, máx 90 chars",\n'
        '  "recommendation": "1 parágrafo, máx 280 chars, com ação concreta"\n'
        "}"
    )

    sys_msg = (
        "Você é um analista de operações de rede para provedor de internet (ISP). "
        "Analise panes detectadas pelo monitor automático e gere insight acionável "
        "em PT-BR. Considere: severidade, horário (impacto em residencial × comercial), "
        "recorrência na mesma OLT/porta (problema crônico vs pontual), e número de "
        "clientes afetados. Resposta APENAS o JSON pedido, sem markdown, sem texto extra."
    )

    try:
        result = await chat_completion(
            company_id,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            model="anthropic/claude-sonnet-4.5",   # força Claude pra esta análise
            temperature=0.3,
            max_tokens=300,
            json_mode=False,
            purpose="smartolt_insight",
            agent="smartolt_ai",
        )
        import json as _json
        raw = (result.get("content") or "").strip()
        # Remove markdown fences se LLM ignorar instrução
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        # Garante que pega só o objeto JSON (alguns modelos prefixam texto)
        if "{" in raw and "}" in raw:
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
        parsed = _json.loads(raw)
        priority = str(parsed.get("priority") or "media").lower()
        if priority not in ("critica", "alta", "media", "baixa"):
            priority = "media"
        return {
            "priority": priority,
            "headline": (parsed.get("headline") or "")[:120],
            "recommendation": (parsed.get("recommendation") or "")[:400],
            "model": result.get("model"),
            "generated_at": now_iso(),
        }
    except Exception as e:
        logger.info("[smartolt-ai] LLM insight falhou (silencioso): %s", e)
        return None


async def detect_outages(company_id: str = DEMO_COMPANY_ID) -> Dict[str, Any]:
    """Varre `smartolt_onus` agrupando por OLT+placa+porta+vlan e detecta
    grupos com ≥OUTAGE_MIN_LOS ONUs LOS **OU** ≥OUTAGE_MIN_PCT%.

    Para cada outage novo:
    - Insere doc em network_outages
    - Cria rascunhos em outage_drafts (modo ATIVO)
    - Insere notas internas em chats existentes (CO-PILOTO)

    Para cada outage resolvido:
    - Marca como resolved
    - Cria rascunhos de "voltou ao normal"
    - Insere notas internas de "pane resolvida"
    """
    templates = await _load_templates(company_id)

    cursor = db.smartolt_onus.find(
        {"company_id": company_id},
        {"_id": 0, "unique_external_id": 1, "olt_name": 1, "board": 1,
         "port": 1, "vlan": 1, "status": 1, "name": 1, "pppoe_user": 1},
    )
    groups: Dict[str, Dict[str, Any]] = {}
    async for o in cursor:
        olt = (o.get("olt_name") or "").strip()
        board = str(o.get("board") or "").strip()
        port = str(o.get("port") or "").strip()
        vlan = str(o.get("vlan") or "").strip()
        if not olt or not board or not port:
            continue
        key = f"{olt}|B{board}|P{port}|V{vlan}"
        g = groups.setdefault(key, {
            "key": key, "olt_name": olt, "board": board, "port": port,
            "vlan": vlan, "los_count": 0, "online_count": 0, "total_count": 0,
            "los_onts": [],
        })
        g["total_count"] += 1
        status_lc = str(o.get("status") or "").lower()
        if "los" in status_lc or "offline" in status_lc or "dying" in status_lc:
            g["los_count"] += 1
            g["los_onts"].append({
                "external_id": o.get("unique_external_id"),
                "pppoe_user": o.get("pppoe_user"),
                "name": o.get("name"),
            })
        else:
            g["online_count"] += 1

    detected = 0
    resolved = 0
    drafts_created = 0
    notes_inserted = 0
    now = now_iso()
    for key, g in groups.items():
        severity_pct = round(g["los_count"] / g["total_count"] * 100, 1) \
            if g["total_count"] else 0
        # ── REGRA DINÂMICA: 10 ONUs OU 50% da porta ─────────────────────────
        is_outage = (g["los_count"] >= OUTAGE_MIN_LOS) or (severity_pct >= OUTAGE_MIN_PCT)

        if is_outage:
            pppoes = [x["pppoe_user"] for x in g["los_onts"] if x.get("pppoe_user")]
            affected_phones: List[str] = []
            if pppoes:
                async for sub in db.subscribers.find(
                    {"company_id": company_id, "pppoe_user": {"$in": pppoes}},
                    {"_id": 0, "phones": 1, "name": 1},
                ):
                    for p in (sub.get("phones") or []):
                        ph = p.get("number") if isinstance(p, dict) else str(p)
                        if ph:
                            ph = "".join(c for c in ph if c.isdigit())
                            if ph and ph not in affected_phones:
                                affected_phones.append(ph)
            existing = await db.network_outages.find_one(
                {"company_id": company_id, "key": key, "status": "active"},
                {"_id": 0, "id": 1, "first_detected_at": 1},
            )
            if existing:
                await db.network_outages.update_one(
                    {"company_id": company_id, "key": key, "status": "active"},
                    {"$set": {
                        "los_count": g["los_count"],
                        "online_count": g["online_count"],
                        "total_count": g["total_count"],
                        "severity_pct": severity_pct,
                        "los_onts_sample": g["los_onts"][:10],
                        "affected_phones": affected_phones,
                        "last_seen_at": now,
                    }},
                )
                # Re-emite drafts/notes para novos phones que apareceram tarde
                full = await db.network_outages.find_one(
                    {"company_id": company_id, "key": key, "status": "active"},
                    {"_id": 0},
                )
                if full:
                    drafts_created += await _create_outage_drafts(
                        company_id, full, templates, "outage_proactive")
                    notes_inserted += await _insert_internal_notes(
                        company_id, full, templates, "outage_active")
            else:
                detected += 1
                outage_id = f"out-{uuid.uuid4().hex[:10]}"
                outage_doc = {
                    "id": outage_id,
                    "company_id": company_id,
                    "key": key,
                    "status": "active",
                    "olt_name": g["olt_name"],
                    "board": g["board"],
                    "port": g["port"],
                    "vlan": g["vlan"],
                    "los_count": g["los_count"],
                    "online_count": g["online_count"],
                    "total_count": g["total_count"],
                    "severity_pct": severity_pct,
                    "los_onts_sample": g["los_onts"][:10],
                    "affected_phones": affected_phones,
                    "first_detected_at": now,
                    "last_seen_at": now,
                    "trigger_rule": (
                        f"los>={OUTAGE_MIN_LOS}" if g["los_count"] >= OUTAGE_MIN_LOS
                        else f"pct>={OUTAGE_MIN_PCT}"
                    ),
                }
                # Análise IA (Claude) — histórico recente da mesma OLT
                cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                history = await db.network_outages.find(
                    {"company_id": company_id, "olt_name": g["olt_name"],
                     "first_detected_at": {"$gte": cutoff_7d},
                     "key": {"$ne": key}},
                    {"_id": 0, "olt_name": 1, "board": 1, "port": 1,
                     "los_count": 1, "total_count": 1, "severity_pct": 1,
                     "duration_minutes": 1, "first_detected_at": 1},
                ).sort("first_detected_at", -1).limit(5).to_list(5)
                insight = await _generate_ai_insight(company_id, outage_doc, history)
                if insight:
                    outage_doc["ai_insight"] = insight
                await db.network_outages.insert_one(outage_doc)
                logger.warning(
                    "[smartolt-ai] OUTAGE detectado: %s — %d/%d LOS (%.1f%%) — %d clientes afetados — regra=%s%s",
                    key, g["los_count"], g["total_count"], severity_pct,
                    len(affected_phones), outage_doc["trigger_rule"],
                    f" · IA={insight['priority']}" if insight else "",
                )
                # PROATIVO: avisa gestor por WhatsApp e aguarda decisão
                try:
                    from services.proactive_alerts import notify_outage
                    await notify_outage(company_id, outage_doc)
                except Exception as e:
                    logger.warning("[smartolt-ai] proactive notify falhou: %s", e)
                # ATIVO: rascunhos prontos pra aprovação
                drafts_created += await _create_outage_drafts(
                    company_id, outage_doc, templates, "outage_proactive")
                # CO-PILOTO: nota interna nos chats existentes
                notes_inserted += await _insert_internal_notes(
                    company_id, outage_doc, templates, "outage_active")
        else:
            existing = await db.network_outages.find_one(
                {"company_id": company_id, "key": key, "status": "active"},
                {"_id": 0},
            )
            if existing:
                resolved += 1
                duration_min = None
                try:
                    fdt = datetime.fromisoformat(existing["first_detected_at"])
                    duration_min = int((datetime.now(timezone.utc) - fdt).total_seconds() / 60)
                except Exception:
                    pass
                await db.network_outages.update_one(
                    {"company_id": company_id, "key": key, "status": "active"},
                    {"$set": {
                        "status": "resolved",
                        "resolved_at": now,
                        "duration_minutes": duration_min,
                    }},
                )
                full_resolved = {**existing, "status": "resolved",
                                  "resolved_at": now, "duration_minutes": duration_min}
                logger.info("[smartolt-ai] OUTAGE resolvido: %s (durou %s min)",
                              key, duration_min)
                # Rascunhos de normalização
                drafts_created += await _create_outage_drafts(
                    company_id, full_resolved, templates, "outage_resolved")
                # Nota interna de pane resolvida
                notes_inserted += await _insert_internal_notes(
                    company_id, full_resolved, templates, "outage_resolved")
    return {"detected": detected, "resolved": resolved,
            "groups_evaluated": len(groups),
            "drafts_created": drafts_created,
            "internal_notes_inserted": notes_inserted,
            "thresholds": {"min_los": OUTAGE_MIN_LOS, "min_pct": OUTAGE_MIN_PCT},
            "interval_seconds": INTERVAL_SECONDS}


async def get_outage_for_phone(company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Verifica se um telefone pertence a um outage ativo.

    Usado pela IA de atendimento (whatsapp_baileys) para injetar contexto:
    se cliente está em região com pane, IA já avisa proativamente (RECEPTIVO).
    """
    if not phone:
        return None
    ph = "".join(c for c in phone if c.isdigit())
    if not ph:
        return None
    outage = await db.network_outages.find_one(
        {"company_id": company_id, "status": "active",
         "affected_phones": ph},
        {"_id": 0},
    )
    return outage


async def list_active_outages(company_id: str = DEMO_COMPANY_ID) -> List[Dict[str, Any]]:
    items = await db.network_outages.find(
        {"company_id": company_id, "status": "active"},
        {"_id": 0},
    ).sort("first_detected_at", -1).to_list(50)
    return items


async def list_recent_resolved(company_id: str = DEMO_COMPANY_ID,
                                  hours: int = 24) -> List[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    items = await db.network_outages.find(
        {"company_id": company_id, "status": "resolved",
         "resolved_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("resolved_at", -1).to_list(50)
    return items


# ---------------------------------------------------------------------------
# Worker periódico
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None


async def _worker_loop():
    while True:
        try:
            await detect_outages(DEMO_COMPANY_ID)
        except Exception as e:
            logger.exception("[smartolt-ai] worker err: %s", e)
        await asyncio.sleep(INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[smartolt-ai] worker iniciado (intervalo=%ds)", INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
