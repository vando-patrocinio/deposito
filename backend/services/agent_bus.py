"""AGENT BUS — barramento interno entre os agentes IA.

Conecta as IAs como uma organização: o que um detecta o outro recebe.

Fluxos canônicos (handlers registrados):
  Isabella detecta churn          → Camila recebe oportunidade.
  Camila detecta campanha         → Isabella executa relacionamento.
  Rede IA detecta incidente       → Isabella abre comunicação.
  Álvaro detecta padrão           → Presidente recebe insight.
  Avaliador detecta falha         → Presidente cria ação corretiva.

Não é um pub/sub generalista (não criamos um framework). É um
roteador de eventos de NEGÓCIO específicos com handlers explícitos
que persistem o resultado em coleções existentes (motor_ia_events,
motor_ia_insights, opportunities/sales_opportunities, etc.).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": True,
    "event_types": [
        "AGENT_BUS_ROUTED",
        "AGENT_BUS_HANDLER_FAILED",
    ],
    "company_id_required": True,
    "notes": "Barramento entre agentes IA.",
}

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from database import db
from services import presidente_ia as svc

log = logging.getLogger("ponto.agent_bus")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────── Routing Table ───────────────────
# event_type → [(handler_callable, target_agent_id)]
Handler = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


async def _isabella_churn_to_camila(company_id: str,
                                         data: Dict[str, Any]
                                         ) -> Dict[str, Any]:
    """Cria oportunidade comercial em motor_ia_insights atribuída
    a Camila quando Isabella detecta risco de churn."""
    insight = {
        "id": f"insight-bus-{int(datetime.now().timestamp()*1000)}",
        "company_id": company_id,
        "kind": "OPORTUNIDADE_RETENCAO_CAMILA",
        "owner_agent": "camila",
        "originator_agent": "isabella",
        "status": "open",
        "severity": "warn",
        "subscriber_id": data.get("subscriber_id"),
        "data": data,
        "created_at": _now_iso(),
    }
    await db.motor_ia_insights.insert_one(insight)
    return {"to": "camila", "via": "motor_ia_insights",
              "insight_id": insight["id"]}


async def _camila_campanha_to_isabella(company_id: str,
                                            data: Dict[str, Any]
                                            ) -> Dict[str, Any]:
    """Quando Camila dispara campanha, Isabella recebe instrução
    para executar relacionamento — registra no event store."""
    await svc.record_event(
        company_id, "ISABELLA_CAMPANHA_DELEGADA",
        source="agent_bus", severity="info", data=data)
    return {"to": "isabella", "via": "motor_ia_events"}


async def _rede_incidente_to_isabella(company_id: str,
                                           data: Dict[str, Any]
                                           ) -> Dict[str, Any]:
    """Rede IA detecta incidente → Isabella abre comunicação."""
    insight = {
        "id": f"insight-bus-{int(datetime.now().timestamp()*1000)}",
        "company_id": company_id,
        "kind": "COMUNICACAO_INCIDENTE_ISABELLA",
        "owner_agent": "isabella",
        "originator_agent": "rede",
        "status": "open",
        "severity": "alert",
        "data": data,
        "created_at": _now_iso(),
    }
    await db.motor_ia_insights.insert_one(insight)
    return {"to": "isabella", "via": "motor_ia_insights",
              "insight_id": insight["id"]}


async def _alvaro_pattern_to_presidente(company_id: str,
                                              data: Dict[str, Any]
                                              ) -> Dict[str, Any]:
    """Álvaro detecta padrão → Presidente recebe insight."""
    insight = {
        "id": f"insight-bus-{int(datetime.now().timestamp()*1000)}",
        "company_id": company_id,
        "kind": "INSIGHT_ESTRATEGICO_PRESIDENTE",
        "owner_agent": "presidente",
        "originator_agent": "alvaro",
        "status": "open",
        "severity": data.get("severity") or "info",
        "data": data,
        "created_at": _now_iso(),
    }
    await db.motor_ia_insights.insert_one(insight)
    return {"to": "presidente", "via": "motor_ia_insights",
              "insight_id": insight["id"]}


async def _avaliador_falha_to_presidente(company_id: str,
                                                data: Dict[str, Any]
                                                ) -> Dict[str, Any]:
    """Avaliador detecta falha → Presidente cria ação corretiva."""
    action = {
        "id": f"act-bus-{int(datetime.now().timestamp()*1000)}",
        "company_id": company_id,
        "categoria": "ACAO_CORRETIVA_QUALIDADE",
        "source": "agent_bus",
        "originator_agent": "avaliador",
        "owner_agent": "presidente",
        "status": "pending",
        "severity": "alert",
        "descricao": data.get("descricao") or "Ação corretiva sugerida",
        "data": data,
        "created_at": _now_iso(),
    }
    await db.motor_ia_actions.insert_one(action)
    return {"to": "presidente", "via": "motor_ia_actions",
              "action_id": action["id"]}


ROUTING_TABLE: Dict[str, List[Handler]] = {
    "ISABELLA_CHURN_DETECTED": [_isabella_churn_to_camila],
    "CAMILA_CAMPANHA_DISPARADA": [_camila_campanha_to_isabella],
    "REDE_INCIDENTE_DETECTADO": [_rede_incidente_to_isabella],
    "ALVARO_PADRAO_DETECTADO": [_alvaro_pattern_to_presidente],
    "AVALIADOR_FALHA_DETECTADA": [_avaliador_falha_to_presidente],
}


async def route(event_type: str, company_id: str,
                  data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Roteia um evento de negócio pelos handlers registrados.
    Sempre exige company_id (Orphan Event Watcher exige)."""
    if not company_id:
        raise ValueError("company_id obrigatório no agent_bus.route")

    handlers = ROUTING_TABLE.get(event_type, [])
    if not handlers:
        return {"routed": False, "reason": "no handler",
                  "event_type": event_type}

    results = []
    for h in handlers:
        try:
            r = await h(company_id, data or {})
            results.append({"handler": h.__name__, **r})
        except Exception as e:
            log.exception("[agent_bus] handler %s falhou: %s",
                            h.__name__, e)
            await svc.record_event(
                company_id, "AGENT_BUS_HANDLER_FAILED",
                source="agent_bus", severity="alert",
                data={"event_type": event_type,
                        "handler": h.__name__, "error": str(e)})
            results.append({"handler": h.__name__,
                              "error": str(e)})

    await svc.record_event(
        company_id, "AGENT_BUS_ROUTED",
        source="agent_bus", severity="info",
        data={"event_type": event_type,
                "fanout": len(handlers),
                "results": results})

    return {"routed": True, "event_type": event_type,
              "fanout": len(handlers), "results": results}


def list_routes() -> Dict[str, List[str]]:
    """Para o dashboard do Presidente: o que conecta com o quê."""
    return {et: [h.__name__ for h in hs]
            for et, hs in ROUTING_TABLE.items()}
