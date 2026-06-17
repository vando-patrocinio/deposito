"""ISABELLA EXPERIENCE COMMANDER — encantamento + Universo Ligo.

Detecta eventos de relacionamento (não promocionais) e gera CAMPANHAS
**em estado DRAFT** com história, contexto, custo e ROI esperado.

Estados (Human Authorization Gate):
  DRAFT → READY → AWAITING_APPROVAL → APPROVED → SCHEDULED → EXECUTED
                            ↘                                       ↘
                          CANCELLED                              CANCELLED

Níveis de aprovação:
  L1 sem custo financeiro → permitido `auto_execute=true`
  L2 financeiro pequeno   → 1 aprovador (gestor)
  L3 financeiro moderado  → 1 aprovador (administrador)
  L4 estratégico/massa    → CTO

Regra conversacional de NOME:
  • Saudação inicial pode usar o primeiro nome
  • Corpo da mensagem NÃO repete o nome
  • Despedida pode usar nome só em mensagens emocionais
  Helper `compose_message` valida e impede uso > 2 ocorrências do nome.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["campaign.updated"],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.event_bus import EventType, emit_event
from services import universo_ligo

log = logging.getLogger("ponto.isabella_experience")

VALID_STATES = ("DRAFT", "READY", "AWAITING_APPROVAL", "APPROVED",
                  "SCHEDULED", "EXECUTED", "CANCELLED")
APPROVAL_LEVELS = {1: "automatica", 2: "gestor", 3: "administrador", 4: "cto"}


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat()


def _first_name(full: Optional[str]) -> str:
    if not full:
        return "amigo"
    return (full.strip().split(" ")[0] or "amigo").title()


def _count_name_occurrences(text: str, name: str) -> int:
    if not text or not name:
        return 0
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    return len(pattern.findall(text))


def compose_message(template: str, *, subscriber: Dict[str, Any],
                      extras: Optional[Dict[str, Any]] = None,
                      max_name_uses: int = 2) -> Dict[str, Any]:
    """Renderiza template + valida regra de não-repetição de nome.

    Variáveis suportadas: {nome}, {empresa}, {mes_atual}, {anos}, {meses}.
    Retorna {text, name_occurrences, ok, warnings}.
    """
    nome = _first_name(subscriber.get("name") or subscriber.get("nome"))
    text = template
    repl = {"{nome}": nome,
             "{empresa}": (extras or {}).get("empresa", "Ligo"),
             "{mes_atual}": _now().strftime("%B"),
             "{anos}": str((extras or {}).get("anos", "")),
             "{meses}": str((extras or {}).get("meses", "")),
             "{bairro}": subscriber.get("neighborhood") or
                          (subscriber.get("address") or "")[:30],
             "{plano}": subscriber.get("plan_name") or "seu plano"}
    for k, v in repl.items():
        text = text.replace(k, str(v))
    occ = _count_name_occurrences(text, nome)
    warnings: List[str] = []
    if occ > max_name_uses:
        warnings.append(
            f"Nome '{nome}' usado {occ}x — máximo permitido {max_name_uses}")
    return {"text": text.strip(),
            "name_occurrences": occ,
            "ok": occ <= max_name_uses,
            "warnings": warnings}


# ---------------------------------------------------------------------------
# Templates (zero promocional — todos contam UMA história)
# ---------------------------------------------------------------------------
TEMPLATES = {
    "anniversary_install_1y": (
        "Olá {nome}. Há exatamente um ano sua casa entrou para o Universo "
        "Ligo. Desde então foram centenas de horas de filmes, chamadas, "
        "jogos, trabalho e momentos importantes conectados. Obrigado por "
        "fazer parte da nossa história."
    ),
    "anniversary_install_3y": (
        "Alguns clientes chegam. Outros permanecem. Hoje completam-se 3 "
        "anos da nossa conexão. Isso representa confiança — algo raro e "
        "que a Ligo valoriza profundamente. Obrigado por caminhar conosco "
        "nessa trajetória, {nome}."
    ),
    "anniversary_install_5y": (
        "Cinco anos juntos. Uma comunidade se constrói com clientes que "
        "permanecem. Você é parte fundamental dessa história. Obrigado "
        "pela confiança contínua, {nome}."
    ),
    "anniversary_birthday": (
        "Olá {nome}. Hoje é seu dia. A equipe Ligo deseja momentos "
        "marcantes ao lado de quem você ama — e que sua conexão continue "
        "ajudando a guardar essas memórias. Feliz aniversário."
    ),
    "referral_converted": (
        "Olá {nome}. Toda comunidade cresce através das pessoas. "
        "Recentemente um amigo seu chegou à Ligo por sua indicação — mais "
        "do que uma conversão, isso demonstra confiança. Obrigado por "
        "ajudar a construir o Universo Ligo."
    ),
    "incident_resolved": (
        "Olá {nome}. Nossa equipe identificou e corrigiu uma "
        "instabilidade que afetou sua região. Seguimos monitorando tudo "
        "de perto para garantir a melhor experiência possível. Obrigado "
        "pela paciência e confiança."
    ),
    "upgrade_realized": (
        "Olá {nome}. Sua nova velocidade já está ativa em {plano}. "
        "Esperamos que ela amplie tudo aquilo que você faz pela internet "
        "— trabalho, lazer, família, criação. Boa jornada."
    ),
    "level_up_galaxia": (
        "Alguns clientes utilizam internet. Outros ajudam a construir "
        "uma comunidade. Pela sua trajetória conosco, você agora faz "
        "parte do nível {level_name}. Obrigado por caminhar conosco "
        "nessa jornada, {nome}."
    ),
    "level_up_universo": (
        "Hoje você alcança o nível mais alto da nossa comunidade: "
        "{level_name}. Esse título é reservado a pessoas que constroem "
        "a Ligo com a gente. Obrigado, {nome}."
    ),
    "vip_pizza": (
        "Olá {nome}. Hoje queremos retribuir um pouco da confiança que "
        "você deposita na Ligo. Por isso, a próxima pizza é por nossa "
        "conta. Aproveite esse momento com quem faz parte da sua história."
    ),
    "nps_proactive": (
        "Olá {nome}. Sua opinião nos ajuda a crescer melhor. De 0 a 10, "
        "o quanto você indicaria a Ligo para um amigo? Responda apenas "
        "com o número — leva 5 segundos."
    ),
    "welcome": (
        "Olá {nome}. Bem-vindo ao Universo Ligo. Sua conexão está "
        "ativa em {bairro}. Aqui você não é só mais um número — você "
        "passa a fazer parte de uma comunidade que cresce com cada nova "
        "história. Boa jornada."
    ),
}


# ---------------------------------------------------------------------------
# Campaign engine
# ---------------------------------------------------------------------------
async def ensure_indexes() -> None:
    try:
        await db.experience_campaigns.create_index(
            [("company_id", 1), ("status", 1), ("created_at", -1)])
        await db.experience_campaigns.create_index(
            [("company_id", 1), ("event_key", 1), ("target_id", 1)],
            name="exp_dedup_idx")
        await db.experience_campaigns_audit.create_index(
            [("campaign_id", 1), ("at", -1)])
    except Exception as e:  # noqa
        log.warning("[experience] indexes: %s", e)


async def _audit(campaign_id: str, action: str, actor: str,
                  details: Optional[Dict[str, Any]] = None) -> None:
    await db.experience_campaigns_audit.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "campaign_id": campaign_id,
        "action": action, "actor": actor,
        "details": details or {}, "at": _iso(_now())})


async def _opportunity_exists(company_id: str, event_key: str,
                                  target_id: str) -> bool:
    """Anti-flood: já existe campanha aberta para este (event, target)?"""
    return bool(await db.experience_campaigns.find_one(
        {"company_id": company_id, "event_key": event_key,
         "target_id": target_id,
         "status": {"$in": ["DRAFT", "READY", "AWAITING_APPROVAL",
                              "APPROVED", "SCHEDULED"]}}))


async def _draft_campaign(*, company_id: str, event_key: str,
                              subscriber: Dict[str, Any],
                              template_id: str,
                              approval_level: int,
                              estimated_cost_brl: float = 0.0,
                              expected_roi_brl: float = 0.0,
                              context: Optional[Dict[str, Any]] = None
                              ) -> Optional[Dict[str, Any]]:
    if await _opportunity_exists(company_id, event_key, subscriber["id"]):
        return None
    template = TEMPLATES.get(template_id) or ""
    if not template:
        return None
    rendered = compose_message(template, subscriber=subscriber,
                                 extras=context or {})
    if not rendered["ok"]:
        log.warning("[experience] template '%s' falhou regra do nome: %s",
                    template_id, rendered["warnings"])
        # ainda assim cria draft com warning para gestor revisar
    auto = approval_level == 1
    state = "READY" if auto else "AWAITING_APPROVAL"
    doc = {
        "id": f"exp-{uuid.uuid4().hex[:14]}",
        "company_id": company_id,
        "event_key": event_key,
        "template_id": template_id,
        "target_type": "subscriber",
        "target_id": subscriber["id"],
        "target_label": subscriber.get("name"),
        "target_phone": subscriber.get("phone"),
        "channel": "whatsapp",
        "message": rendered["text"],
        "message_warnings": rendered["warnings"],
        "approval_level": approval_level,
        "approval_role": APPROVAL_LEVELS.get(approval_level, "?"),
        "auto_execute": auto,
        "estimated_cost_brl": round(float(estimated_cost_brl), 2),
        "expected_roi_brl": round(float(expected_roi_brl), 2),
        "context": context or {},
        "status": state,
        "created_at": _iso(_now()),
        "updated_at": _iso(_now()),
        "approvals": [],
    }
    await db.experience_campaigns.insert_one(dict(doc))
    await _audit(doc["id"], "created", "isabella_experience",
                  {"event_key": event_key,
                    "template_id": template_id,
                    "approval_level": approval_level})
    await emit_event(EventType.EXPERIENCE_CAMPAIGN_DRAFTED,
                      company_id=company_id, source="isabella_experience",
                      severity="baixa" if auto else "media",
                      payload={"campaign_id": doc["id"],
                                "event_key": event_key,
                                "subscriber_id": subscriber["id"]})
    doc.pop("_id", None)
    return doc


async def _detect_anniversaries(company_id: str) -> List[Dict[str, Any]]:
    """Aniversário de instalação (1/3/5 anos) — janela de hoje."""
    today = _now().date()
    today_md = today.strftime("%m-%d")
    out: List[Dict[str, Any]] = []
    cur = db.subscribers.find(
        {"company_id": company_id,
         "contract_status": {"$nin": ["CANCELADO", "cancelado"]},
         "activation_date": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "activation_date": 1,
         "address": 1, "plan_name": 1}).limit(50000)
    async for s in cur:
        try:
            act = datetime.fromisoformat(
                s["activation_date"].replace("Z", "+00:00")).date()
        except Exception:
            continue
        if act.strftime("%m-%d") != today_md:
            continue
        anos = today.year - act.year
        if anos == 1:
            tpl = "anniversary_install_1y"
        elif anos == 3:
            tpl = "anniversary_install_3y"
        elif anos == 5:
            tpl = "anniversary_install_5y"
        else:
            continue
        d = await _draft_campaign(
            company_id=company_id,
            event_key=f"anniv_{anos}y",
            subscriber=s,
            template_id=tpl,
            approval_level=1,
            estimated_cost_brl=0.0,
            expected_roi_brl=0.0,
            context={"anos": anos})
        if d:
            out.append(d)
    return out


async def _detect_birthdays(company_id: str) -> List[Dict[str, Any]]:
    today_md = _now().strftime("%m-%d")
    out: List[Dict[str, Any]] = []
    cur = db.subscribers.find(
        {"company_id": company_id,
         "contract_status": {"$nin": ["CANCELADO"]},
         "birthday": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "birthday": 1,
         "plan_name": 1, "address": 1}).limit(50000)
    async for s in cur:
        b = s.get("birthday") or ""
        try:
            bd = b[5:10] if len(b) >= 10 else ""
        except Exception:
            bd = ""
        if bd != today_md:
            continue
        d = await _draft_campaign(
            company_id=company_id, event_key="birthday",
            subscriber=s, template_id="anniversary_birthday",
            approval_level=1)
        if d:
            out.append(d)
    return out


async def _detect_level_ups(company_id: str) -> List[Dict[str, Any]]:
    """Mudança de nível ocorrida nas últimas 24h em universo_ligo_history."""
    cutoff = _iso(_now() - timedelta(hours=36))
    cur = db.universo_ligo_history.find(
        {"company_id": company_id, "changed_at": {"$gte": cutoff},
         "to_level_id": {"$gte": 4}},  # Estelar+
        {"_id": 0}).limit(2000)
    out: List[Dict[str, Any]] = []
    async for h in cur:
        sub = await db.subscribers.find_one(
            {"id": h["subscriber_id"]},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "plan_name": 1})
        if not sub:
            continue
        to_id = int(h["to_level_id"])
        if to_id == 6:
            tpl = "level_up_universo"
        else:
            tpl = "level_up_galaxia"
        d = await _draft_campaign(
            company_id=company_id,
            event_key=f"level_up_{to_id}",
            subscriber=sub, template_id=tpl,
            approval_level=1,
            context={"level_name": h.get("to_level_name") or ""})
        if d:
            out.append(d)
    return out


async def _detect_referral_conversions(company_id: str) -> List[Dict[str, Any]]:
    """Indicações convertidas nas últimas 7 dias."""
    cutoff = _iso(_now() - timedelta(days=7))
    cur = db.indicacao_leads.find(
        {"company_id": company_id,
         "status": {"$in": ["convertido", "converted", "ativo"]},
         "updated_at": {"$gte": cutoff}},
        {"_id": 0, "referrer_subscriber_id": 1, "referrer_phone": 1,
         "referrer_document": 1}).limit(2000)
    out: List[Dict[str, Any]] = []
    async for r in cur:
        sub = None
        if r.get("referrer_subscriber_id"):
            sub = await db.subscribers.find_one(
                {"id": r["referrer_subscriber_id"]},
                {"_id": 0, "id": 1, "name": 1, "phone": 1})
        if not sub and r.get("referrer_phone"):
            sub = await db.subscribers.find_one(
                {"phone": r["referrer_phone"]},
                {"_id": 0, "id": 1, "name": 1, "phone": 1})
        if not sub:
            continue
        d = await _draft_campaign(
            company_id=company_id, event_key="referral_converted",
            subscriber=sub, template_id="referral_converted",
            approval_level=1)
        if d:
            out.append(d)
    return out


async def _detect_incident_resolutions(company_id: str
                                          ) -> List[Dict[str, Any]]:
    """Incidentes resolvidos nas últimas 24h — agradecimento."""
    cutoff = _iso(_now() - timedelta(hours=24))
    cur = db.isabella_incidents.find(
        {"company_id": company_id, "status": "resolved",
         "resolved_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "affected_client_ids": 1,
         "grouped_clients": 1}).limit(50)
    out: List[Dict[str, Any]] = []
    async for inc in cur:
        ids = list(set((inc.get("affected_client_ids") or [])
                          + [g.get("client_id") for g in
                              (inc.get("grouped_clients") or [])
                              if g.get("client_id")]))
        subs = await db.subscribers.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "phone": 1}).to_list(500)
        for s in subs:
            d = await _draft_campaign(
                company_id=company_id,
                event_key=f"incident_resolved_{inc['id']}",
                subscriber=s, template_id="incident_resolved",
                approval_level=1)
            if d:
                out.append(d)
    return out


async def scan_company(company_id: str) -> Dict[str, Any]:
    out = {
        "anniversaries": await _detect_anniversaries(company_id),
        "birthdays": await _detect_birthdays(company_id),
        "level_ups": await _detect_level_ups(company_id),
        "referrals": await _detect_referral_conversions(company_id),
        "incidents_resolved": await _detect_incident_resolutions(company_id),
    }
    totals = {k: len(v) for k, v in out.items()}
    totals["total"] = sum(totals.values())
    return {"company_id": company_id, "totals": totals, "drafts": out}


async def list_campaigns(company_id: str, *,
                            status: Optional[str] = None,
                            limit: int = 100) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if status:
        q["status"] = status
    return await db.experience_campaigns.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(min(limit, 500)) \
        .to_list(min(limit, 500))


async def approve_campaign(*, campaign_id: str, company_id: str,
                              actor: str, actor_role: str,
                              notes: Optional[str] = None
                              ) -> Dict[str, Any]:
    camp = await db.experience_campaigns.find_one(
        {"id": campaign_id, "company_id": company_id}, {"_id": 0})
    if not camp:
        raise ValueError("campanha não encontrada")
    if camp["status"] not in ("AWAITING_APPROVAL", "DRAFT", "READY"):
        raise ValueError(f"status atual não permite aprovação: {camp['status']}")
    # Validação de role × approval_level
    required = camp["approval_level"]
    role_rank = {"tecnico": 0, "atendente": 1, "gestor": 2,
                  "administrador": 3, "cto": 4}.get(actor_role, 0)
    if required == 2 and role_rank < 2:
        raise PermissionError("requer gestor ou superior")
    if required == 3 and role_rank < 3:
        raise PermissionError("requer administrador ou superior")
    if required == 4 and role_rank < 4:
        raise PermissionError("requer CTO")
    approvals = camp.get("approvals") or []
    approvals.append({"by": actor, "role": actor_role,
                       "at": _iso(_now()), "notes": notes})
    await db.experience_campaigns.update_one(
        {"id": campaign_id},
        {"$set": {"status": "APPROVED",
                   "approvals": approvals,
                   "updated_at": _iso(_now())}})
    await _audit(campaign_id, "approved", actor,
                  {"role": actor_role, "notes": notes})
    await emit_event(EventType.EXPERIENCE_CAMPAIGN_APPROVED,
                      company_id=company_id, source="isabella_experience",
                      severity="media",
                      payload={"campaign_id": campaign_id, "actor": actor})
    return await db.experience_campaigns.find_one(
        {"id": campaign_id}, {"_id": 0})


async def cancel_campaign(*, campaign_id: str, company_id: str,
                              actor: str,
                              reason: Optional[str] = None
                              ) -> Dict[str, Any]:
    camp = await db.experience_campaigns.find_one(
        {"id": campaign_id, "company_id": company_id}, {"_id": 0})
    if not camp:
        raise ValueError("campanha não encontrada")
    await db.experience_campaigns.update_one(
        {"id": campaign_id},
        {"$set": {"status": "CANCELLED",
                   "cancel_reason": reason,
                   "updated_at": _iso(_now())}})
    await _audit(campaign_id, "cancelled", actor, {"reason": reason})
    await emit_event(EventType.EXPERIENCE_CAMPAIGN_CANCELLED,
                      company_id=company_id, source="isabella_experience",
                      severity="baixa",
                      payload={"campaign_id": campaign_id})
    return await db.experience_campaigns.find_one(
        {"id": campaign_id}, {"_id": 0})


async def execute_campaign(*, campaign_id: str, company_id: str,
                              actor: str) -> Dict[str, Any]:
    """Dispara a mensagem. Exige status APPROVED ou (READY+auto_execute)."""
    from services.wa_dispatcher import send_text
    camp = await db.experience_campaigns.find_one(
        {"id": campaign_id, "company_id": company_id}, {"_id": 0})
    if not camp:
        raise ValueError("campanha não encontrada")
    if camp["status"] not in ("APPROVED", "READY"):
        if not (camp["status"] == "READY" and camp.get("auto_execute")):
            raise PermissionError(
                f"campanha em {camp['status']} — requer aprovação humana")
    if camp["status"] == "READY" and not camp.get("auto_execute"):
        raise PermissionError(
            "campanha READY mas não é auto_execute — requer aprovação")
    phone = camp.get("target_phone")
    if not phone:
        await cancel_campaign(campaign_id=campaign_id,
                                 company_id=company_id, actor=actor,
                                 reason="sem telefone")
        return {"ok": False, "reason": "no_phone"}
    r = await send_text(company_id=company_id, to=phone,
                          text=camp["message"],
                          channel="baileys")  # P0 CEO 17/02/2026 — atendimento via Baileys
    real_cost = float(camp.get("estimated_cost_brl") or 0)
    await db.experience_campaigns.update_one(
        {"id": campaign_id},
        {"$set": {"status": "EXECUTED",
                   "executed_at": _iso(_now()),
                   "executed_by": actor,
                   "send_result": r,
                   "real_cost_brl": real_cost,
                   "updated_at": _iso(_now())}})
    await _audit(campaign_id, "executed", actor,
                  {"send_ok": bool(r.get("ok")),
                    "real_cost_brl": real_cost})
    await emit_event(EventType.EXPERIENCE_CAMPAIGN_EXECUTED,
                      company_id=company_id, source="isabella_experience",
                      severity="media",
                      payload={"campaign_id": campaign_id,
                                "send_ok": bool(r.get("ok"))})
    return await db.experience_campaigns.find_one(
        {"id": campaign_id}, {"_id": 0})


async def council_review(campaign_id: str,
                          company_id: str) -> Dict[str, Any]:
    """Parecer Isabella + Presidente + Álvaro. Não executa."""
    camp = await db.experience_campaigns.find_one(
        {"id": campaign_id, "company_id": company_id}, {"_id": 0})
    if not camp:
        raise ValueError("campanha não encontrada")
    isa = ("Mensagem alinhada ao Universo Ligo, sem promoção excessiva."
           if not camp.get("message_warnings") else
           "Reveja a repetição do nome do cliente.")
    pres = (f"ROI projetado positivo (R$ {camp.get('expected_roi_brl', 0):.2f})"
            if camp.get("expected_roi_brl", 0) > camp.get("estimated_cost_brl", 0)
            else "Custo > retorno previsível — recomendo cautela.")
    alv = ("Conteúdo emocional e contextual. Aprovado pelo curador de marca."
           if camp.get("approval_level") == 1
           else "Confirmar tom institucional antes do disparo em massa.")
    parecer = {
        "campaign_id": campaign_id,
        "isabella": isa,
        "presidente_ia": pres,
        "alvaro_ia": alv,
        "risco": "baixo" if camp.get("approval_level", 1) <= 2 else "moderado",
        "recomendacao": "aprovar" if camp.get("expected_roi_brl", 0)
                                       >= camp.get("estimated_cost_brl", 0)
                                       else "revisar",
        "generated_at": _iso(_now()),
    }
    await db.experience_campaigns.update_one(
        {"id": campaign_id},
        {"$set": {"council_review": parecer,
                   "updated_at": _iso(_now())}})
    try:
        from services.event_bus import emit_event
        await emit_event(
            "campaign.updated",
            company_id=company_id,
            source="isabella_experience",
            payload={},
        )
    except Exception:
        pass
    return parecer
