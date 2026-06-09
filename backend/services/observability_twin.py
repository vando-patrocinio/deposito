"""
observability_twin.py — SMARTPROV OBSERVABILITY TWIN

Integra Zabbix e Grafana como fontes vivas do Sistema Nervoso:
  Fase 2: ZabbixConnector (problem.get, host.get, trigger.get, event.get)
  Fase 3: GrafanaConnector (dashboards, alerts, datasources, panels)
  Fase 4: observability_health_score (0-100, 5 níveis)
  Fase 5: correlate(...) → Zabbix + SmartOLT + Grafana + tickets + receita
  Fase 6: persist nodes/edges em knowledge_graph_nodes / _edges
  Fase 7: presidente_brief() + alvaro_recommendation()
  Fase 8: observability_summary() para o Command Center
  Fase 9: emit_decisions_from_correlations() → DecisionV5 → autonomous_engine
  Fase 10: testes mockáveis (clients aceitam http_client opcional)

Modo MOCK: se ZABBIX_URL/GRAFANA_URL vazios, usa fixtures internas para
permitir desenvolvimento sem credenciais. Status real exposto em
connector.is_real.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import db

logger = logging.getLogger("observability_twin")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# Severity Zabbix → mapping
ZBX_SEVERITY_NAMES = {
    "0": "not_classified", "1": "information", "2": "warning",
    "3": "average", "4": "high", "5": "disaster",
}
ZBX_CRITICAL_SEVERITIES = {"4", "5"}  # high + disaster


# ═══════════════════════════════════════════════════════════
# FASE 2 — ZABBIX CONNECTOR
# ═══════════════════════════════════════════════════════════
class ZabbixConnector:
    """JSON-RPC client. Prioriza API token. Fallback user/password.

    Se URL ausente: opera em modo MOCK (retorna fixtures consistentes).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.url = (os.environ.get("ZABBIX_URL") or "").rstrip("/")
        self.token = os.environ.get("ZABBIX_API_TOKEN") or ""
        self.user = os.environ.get("ZABBIX_USER") or ""
        self.password = os.environ.get("ZABBIX_PASSWORD") or ""
        self.verify_ssl = (
            os.environ.get("ZABBIX_VERIFY_SSL", "true").lower() != "false")
        self._http = http_client
        self._auth = None
        self._vault_loaded = False

    async def _load_from_vault(self) -> None:
        """Sobrepõe credenciais com valores do secrets_vault, se presentes.
        Chamado lazy em cada entry-point async. Permite UI dinâmica sem
        restart do backend."""
        if self._vault_loaded:
            return
        self._vault_loaded = True
        try:
            from services import secrets_vault as _v
            if not _v.is_available():
                return
            u = await _v.get_secret("integration:zabbix:url")
            tk = await _v.get_secret("integration:zabbix:api_token")
            usr = await _v.get_secret("integration:zabbix:user")
            pw = await _v.get_secret("integration:zabbix:password")
            if u:
                self.url = u.rstrip("/")
            if tk:
                self.token = tk
            if usr:
                self.user = usr
            if pw:
                self.password = pw
        except Exception as e:  # noqa: BLE001
            logger.debug("[zbx] vault load skip: %r", e)

    @property
    def is_real(self) -> bool:
        return bool(self.url) and (
            bool(self.token) or (bool(self.user) and bool(self.password)))

    async def is_real_async(self) -> bool:
        await self._load_from_vault()
        return self.is_real

    async def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        if not hasattr(self, "_own_client") or self._own_client is None:
            self._own_client = httpx.AsyncClient(
                verify=self.verify_ssl, timeout=15)
        return self._own_client

    async def _rpc(self, method: str,
                   params: Dict[str, Any]) -> Dict[str, Any]:
        await self._load_from_vault()
        if not self.is_real:
            return {"_mock": True, "method": method, "params": params}
        c = await self._client()
        endpoint = f"{self.url}/api_jsonrpc.php"
        headers = {"Content-Type": "application/json-rpc"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = {
            "jsonrpc": "2.0", "method": method, "params": params,
            "id": 1,
        }
        if not self.token and self._auth:
            body["auth"] = self._auth
        r = await c.post(endpoint, json=body, headers=headers)
        r.raise_for_status()
        out = r.json()
        if "error" in out:
            raise RuntimeError(f"Zabbix error: {out['error']}")
        return out.get("result", [])

    async def login(self) -> None:
        if self.token or not (self.user and self.password):
            return
        self._auth = await self._rpc("user.login",
                                     {"username": self.user,
                                      "password": self.password})

    async def get_problems(self) -> List[Dict[str, Any]]:
        await self._load_from_vault()
        if not self.is_real:
            return [
                {"eventid": "100001", "name": "MOCK: roteador CPU > 90%",
                 "severity": "4",
                 "clock": str(int(datetime.now(timezone.utc).timestamp()
                                  - 600)),
                 "objectid": "10501", "acknowledged": "0"},
            ]
        await self.login()
        return await self._rpc("problem.get", {
            "output": "extend", "recent": "true",
            "sortfield": "eventid", "sortorder": "DESC",
            "limit": 200,
        })

    async def get_hosts(
        self, hostids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        await self._load_from_vault()
        if not self.is_real:
            return [{"hostid": "10501", "host": "rt-borda-01",
                     "name": "Roteador Borda 01",
                     "status": "0",
                     "interfaces": [{"ip": "10.0.0.1"}]}]
        await self.login()
        params: Dict[str, Any] = {"output": "extend",
                                  "selectInterfaces": "extend"}
        if hostids:
            params["hostids"] = hostids
        return await self._rpc("host.get", params)

    async def get_triggers(
        self, triggerids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        if not self.is_real:
            return []
        await self.login()
        params: Dict[str, Any] = {"output": "extend"}
        if triggerids:
            params["triggerids"] = triggerids
        return await self._rpc("trigger.get", params)

    async def get_events(
        self, eventids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        if not self.is_real:
            return []
        await self.login()
        params: Dict[str, Any] = {"output": "extend"}
        if eventids:
            params["eventids"] = eventids
        return await self._rpc("event.get", params)

    async def close(self) -> None:
        if getattr(self, "_own_client", None) is not None:
            await self._own_client.aclose()
            self._own_client = None


def _classify_zbx_event(problem_name: str) -> str:
    p = (problem_name or "").lower()
    if "cpu" in p:
        return "ZABBIX_CPU_HIGH"
    if "memory" in p or "memória" in p:
        return "ZABBIX_MEMORY_HIGH"
    if "down" in p and ("host" in p or "ping" in p):
        return "ZABBIX_HOST_DOWN"
    if "service" in p or "serviço" in p:
        return "ZABBIX_SERVICE_DOWN"
    if "latency" in p or "latên" in p or "rtt" in p:
        return "ZABBIX_HIGH_LATENCY"
    if "loss" in p or "perda" in p:
        return "ZABBIX_PACKET_LOSS"
    if "link" in p:
        return "ZABBIX_LINK_DEGRADED"
    if "resolved" in p:
        return "ZABBIX_PROBLEM_RESOLVED"
    return "ZABBIX_PROBLEM_OPEN"


async def ingest_zabbix_problems(
    company_id: str,
    connector: Optional[ZabbixConnector] = None,
) -> Dict[str, Any]:
    """Lê problemas do Zabbix e gera eventos correlacionáveis em
    `motor_ia_events`. Dedup por (zabbix_eventid, company_id)."""
    if connector is None:
        connector = ZabbixConnector()
    problems = await connector.get_problems()
    # Cache de hosts em uma chamada
    host_ids = list({p.get("objectid") for p in problems if
                     p.get("objectid")})
    hosts_map: Dict[str, Dict[str, Any]] = {}
    if host_ids:
        try:
            hosts = await connector.get_hosts(host_ids)
            hosts_map = {h.get("hostid"): h for h in hosts}
        except Exception:
            hosts_map = {}

    inserted = 0
    skipped = 0
    events_emitted: List[str] = []
    for p in problems:
        zbx_eventid = p.get("eventid")
        if not zbx_eventid:
            continue
        existing = await db.motor_ia_events.find_one({
            "company_id": company_id, "source": "zabbix",
            "zabbix_eventid": zbx_eventid})
        if existing:
            skipped += 1
            continue
        host_id = p.get("objectid")
        host = hosts_map.get(host_id, {})
        started = datetime.fromtimestamp(
            int(p.get("clock") or 0), tz=timezone.utc).isoformat()
        duration = max(0, int(datetime.now(timezone.utc).timestamp())
                       - int(p.get("clock") or 0))
        event_type = _classify_zbx_event(p.get("name", ""))
        ev_id = _new("evt")
        doc = {
            "id": ev_id, "event_id": ev_id,
            "event_type": event_type,
            "source": "zabbix",
            "company_id": company_id,
            "zabbix_eventid": zbx_eventid,
            "host_id": host_id,
            "host_name": host.get("name") or host.get("host"),
            "severity": p.get("severity"),
            "severity_name":
                ZBX_SEVERITY_NAMES.get(p.get("severity"), "unknown"),
            "problem_name": p.get("name"),
            "started_at": started,
            "duration_seconds": duration,
            "tags": p.get("tags", []),
            "raw_payload": {"problem": p, "host": host},
            "consumed": False,
            "created_at": _now_iso(), "timestamp": _now_iso(),
        }
        await db.motor_ia_events.insert_one(doc)
        events_emitted.append(ev_id)
        inserted += 1
    return {"company_id": company_id,
            "is_real_connector": connector.is_real,
            "problems_received": len(problems),
            "inserted_events": inserted, "skipped_dedup": skipped,
            "event_ids": events_emitted[:50],
            "generated_at": _now_iso()}


# ═══════════════════════════════════════════════════════════
# FASE 3 — GRAFANA CONNECTOR
# ═══════════════════════════════════════════════════════════
class GrafanaConnector:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.url = (os.environ.get("GRAFANA_URL") or "").rstrip("/")
        self.token = (
            os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN") or "")
        # P0.4 — fallback Basic Auth (quando usuário não tem role Admin
        # para gerar Service Account). Token continua sendo o preferido.
        self.user = os.environ.get("GRAFANA_USER") or ""
        self.password = os.environ.get("GRAFANA_PASSWORD") or ""
        self.org_id = os.environ.get("GRAFANA_ORG_ID") or ""
        self.verify_ssl = (
            os.environ.get("GRAFANA_VERIFY_SSL", "true").lower()
            != "false")
        self._http = http_client
        self._vault_loaded = False

    async def _load_from_vault(self) -> None:
        """Sobrepõe credenciais com valores do secrets_vault, se presentes.
        Chamado lazy em cada entry-point async. Permite UI dinâmica sem
        restart do backend.

        Multi-perfil (P0.5): lê `integration:grafana:active_profile` e
        carrega `integration:grafana:profiles:{active}:*`. Cai pra chaves
        legadas `integration:grafana:*` se não houver active_profile."""
        if self._vault_loaded:
            return
        self._vault_loaded = True
        try:
            from services import secrets_vault as _v
            if not _v.is_available():
                return
            active = await _v.get_secret(
                "integration:grafana:active_profile")
            if active:
                prefix = f"integration:grafana:profiles:{active}"
                u = await _v.get_secret(f"{prefix}:url")
                tk = await _v.get_secret(f"{prefix}:token")
                usr = await _v.get_secret(f"{prefix}:user")
                pw = await _v.get_secret(f"{prefix}:password")
                org = await _v.get_secret(f"{prefix}:org_id")
            else:
                # Legado (pré-multi-perfil)
                u = await _v.get_secret("integration:grafana:url")
                tk = await _v.get_secret("integration:grafana:token")
                usr = await _v.get_secret("integration:grafana:user")
                pw = await _v.get_secret("integration:grafana:password")
                org = await _v.get_secret("integration:grafana:org_id")
            if u:
                self.url = u.rstrip("/")
            if tk:
                self.token = tk
            if usr:
                self.user = usr
            if pw:
                self.password = pw
            if org:
                self.org_id = org
        except Exception as e:  # noqa: BLE001
            logger.debug("[grafana] vault load skip: %r", e)

    @property
    def is_real(self) -> bool:
        return bool(self.url) and (
            bool(self.token) or (bool(self.user) and bool(self.password)))

    async def is_real_async(self) -> bool:
        await self._load_from_vault()
        return self.is_real

    @property
    def auth_mode(self) -> str:
        if self.token:
            return "token"
        if self.user and self.password:
            return "basic"
        return "none"

    async def _client(self) -> httpx.AsyncClient:
        await self._load_from_vault()
        if self._http is not None:
            return self._http
        if not hasattr(self, "_own_client") or self._own_client is None:
            kwargs = {"verify": self.verify_ssl, "timeout": 15}
            if not self.token and self.user and self.password:
                kwargs["auth"] = (self.user, self.password)
            self._own_client = httpx.AsyncClient(**kwargs)
        return self._own_client

    async def _get(self, path: str) -> Any:
        await self._load_from_vault()
        if not self.is_real:
            return None
        c = await self._client()
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.org_id:
            headers["X-Grafana-Org-Id"] = self.org_id
        r = await c.get(f"{self.url}{path}", headers=headers)
        # Capturar 401/403 silenciosamente: usuário com role insuficiente
        # (Viewer/Editor sem Admin, ou token sem escopo). Tracking via
        # self._permission_warnings para a UI exibir.
        if r.status_code in (401, 403):
            if not hasattr(self, "_permission_warnings"):
                self._permission_warnings = []
            self._permission_warnings.append({
                "path": path, "status": r.status_code})
            logger.warning(
                "[grafana] %s on %s — role insuficiente "
                "(precisa Admin OU Service Account Token com permissões)",
                r.status_code, path)
            return None
        r.raise_for_status()
        return r.json()

    async def get_dashboards(self) -> List[Dict[str, Any]]:
        await self._load_from_vault()
        if not self.is_real:
            return [{"id": 1, "uid": "mock-ops",
                     "title": "MOCK: Operations",
                     "folderTitle": "Network"}]
        return await self._get("/api/search?type=dash-db") or []

    async def get_folders(self) -> List[Dict[str, Any]]:
        """Tenta /api/folders (precisa Admin). Se 403, usa
        /api/search?type=dash-folder que respeita ACL por usuário."""
        await self._load_from_vault()
        if not self.is_real:
            return [{"id": 1, "title": "Network"}]
        # Primeiro tenta admin endpoint
        out = await self._get("/api/folders")
        if out is not None:
            return out
        # Fallback: busca via search (funciona para Viewer/Editor)
        search = await self._get("/api/search?type=dash-folder") or []
        return [{"id": f.get("id"), "uid": f.get("uid"),
                 "title": f.get("title")} for f in search]

    async def get_datasources(self) -> List[Dict[str, Any]]:
        await self._load_from_vault()
        if not self.is_real:
            return [{"id": 1, "name": "Prometheus",
                     "type": "prometheus", "isDefault": True}]
        return await self._get("/api/datasources") or []

    async def get_alerts(self) -> List[Dict[str, Any]]:
        """Tenta Alertmanager v2 (precisa Admin). Se 403, usa
        /api/ruler que aceita role Viewer com `alert.rules:read`."""
        await self._load_from_vault()
        if not self.is_real:
            return [{"uid": "mock-al-1",
                     "ruleName": "MOCK: Latency P95 > 300ms",
                     "state": "Alerting", "severity": "critical",
                     "annotations": {"summary": "Latência alta"}}]
        out = await self._get(
            "/api/alertmanager/grafana/api/v2/alerts")
        if out is not None:
            return out
        # Fallback: lista regras (não estado em tempo real, mas suficiente
        # para mapear quais alarmes existem)
        rules = await self._get(
            "/api/ruler/grafana/api/v1/rules") or {}
        flat: List[Dict[str, Any]] = []
        if isinstance(rules, dict):
            for ns_name, groups in rules.items():
                if not isinstance(groups, list):
                    continue
                for g in groups:
                    for r in (g.get("rules") or []):
                        flat.append({
                            "uid": r.get("grafana_alert", {}).get("uid"),
                            "ruleName": r.get("alert") or r.get("record"),
                            "state": (r.get("grafana_alert", {})
                                       .get("exec_err_state") or "Inactive"),
                            "severity": (r.get("labels") or {}).get(
                                "severity", "unknown"),
                            "annotations": r.get("annotations") or {},
                            "namespace": ns_name,
                            "group": g.get("name"),
                        })
        return flat

    async def get_user_permissions(self) -> Dict[str, Any]:
        """Lista permissões RBAC efetivas do usuário autenticado.
        Útil para diagnóstico ("por que 403?"). Sem fallback — se 401/403
        retorna None."""
        await self._load_from_vault()
        if not self.is_real:
            return {}
        return await self._get(
            "/api/access-control/user/actions") or {}

    async def get_dashboard_detail(self, uid: str) -> Optional[Dict[str, Any]]:
        """Detalhe completo do dashboard (panels, targets, variables)."""
        await self._load_from_vault()
        if not self.is_real:
            return None
        return await self._get(f"/api/dashboards/uid/{uid}")

    async def list_olt_dashboards(self) -> List[Dict[str, Any]]:
        """Lista dashboards de OLT (tag 'OLT' ou título contém OLT/PON/ONU).

        Para cada um, extrai panels relevantes e retorna metadados úteis para
        construir KPIs de ONT/ONU no frontend.
        """
        all_dashes = await self.get_dashboards()
        olts = []
        for d in all_dashes or []:
            tags = [t.lower() for t in (d.get("tags") or [])]
            title = (d.get("title") or "")
            tl = title.lower()
            is_olt = ("olt" in tags or "olt" in tl
                      or "onu" in tl or "pon" in tl)
            if not is_olt:
                continue
            uid = d.get("uid")
            # Detect vendor by tags/title
            vendor = "unknown"
            for v in ("huawei", "zte", "datacom", "fiberhome", "parks"):
                if v in tl or v in tags:
                    vendor = v.upper()
                    break
            olts.append({
                "uid": uid,
                "id": d.get("id"),
                "title": title,
                "tags": d.get("tags") or [],
                "vendor": vendor,
                "url_grafana":
                    f"{self.url}/d/{uid}/{d.get('uri','').split('/')[-1]}"
                    if uid else None,
                "url_embed_first_panel":
                    f"{self.url}/d-solo/{uid}?orgId={self.org_id or 1}"
                    if uid else None,
            })
        return olts



    async def get_annotations(self) -> List[Dict[str, Any]]:
        await self._load_from_vault()
        if not self.is_real:
            return []
        return await self._get("/api/annotations") or []

    async def close(self) -> None:
        if getattr(self, "_own_client", None) is not None:
            await self._own_client.aclose()
            self._own_client = None


async def snapshot_grafana(
    company_id: str,
    connector: Optional[GrafanaConnector] = None,
) -> Dict[str, Any]:
    """Cria snapshots em coleções dedicadas + emite eventos para alerts
    em estado Alerting/Firing."""
    if connector is None:
        connector = GrafanaConnector()
    dashboards = await connector.get_dashboards()
    folders = await connector.get_folders()
    datasources = await connector.get_datasources()
    alerts = await connector.get_alerts()
    now = _now_iso()
    # Upsert idempotente (limpa snapshots antigos do CO antes)
    for col, items in (
        ("grafana_dashboards", dashboards),
        ("grafana_folders", folders),
        ("grafana_datasources", datasources),
        ("grafana_alerts", alerts),
    ):
        await db[col].delete_many({"company_id": company_id})
        if items:
            await db[col].insert_many([{
                **i, "company_id": company_id,
                "snapshot_at": now} for i in items])

    inserted = 0
    for a in alerts:
        state = (a.get("state") or "").lower()
        if state not in ("alerting", "firing"):
            continue
        ev_id = _new("evt")
        await db.motor_ia_events.insert_one({
            "id": ev_id, "event_id": ev_id,
            "event_type": "GRAFANA_ALERT_FIRING",
            "source": "grafana",
            "company_id": company_id,
            "grafana_uid": a.get("uid"),
            "rule_name": a.get("ruleName") or a.get("labels", {}).get(
                "alertname"),
            "severity": a.get("severity") or a.get("labels", {}).get(
                "severity") or "unknown",
            "annotations": a.get("annotations", {}),
            "raw_payload": a,
            "consumed": False,
            "created_at": now, "timestamp": now,
        })
        inserted += 1
    return {"company_id": company_id,
            "is_real_connector": connector.is_real,
            "dashboards": len(dashboards), "alerts": len(alerts),
            "datasources": len(datasources),
            "firing_events_emitted": inserted,
            "generated_at": now}


# ═══════════════════════════════════════════════════════════
# FASE 4 — OBSERVABILITY HEALTH SCORE
# ═══════════════════════════════════════════════════════════
def _classify_health(score: float) -> str:
    if score >= 95:
        return "EXCELENTE"
    if score >= 90:
        return "SAUDAVEL"
    if score >= 80:
        return "ATENCAO"
    if score >= 70:
        return "CRITICO"
    return "INCIDENTE"


async def observability_health_score(
    company_id: str, window_hours: int = 24,
) -> Dict[str, Any]:
    """Score 0-100 composto. Penaliza alertas críticos abertos +
    hosts down + serviços fora + clientes impactados."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=window_hours)).isoformat()

    # Zabbix events não consumidos (CRITICOS = sev 4-5)
    zbx_open = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "zabbix",
        "consumed": False,
        "created_at": {"$gte": cutoff}})
    zbx_critical = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "zabbix",
        "consumed": False,
        "severity": {"$in": list(ZBX_CRITICAL_SEVERITIES)},
        "created_at": {"$gte": cutoff}})
    zbx_host_down = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "zabbix",
        "event_type": "ZABBIX_HOST_DOWN",
        "consumed": False,
        "created_at": {"$gte": cutoff}})

    # Grafana firing alerts
    graf_firing = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "grafana",
        "event_type": "GRAFANA_ALERT_FIRING",
        "consumed": False,
        "created_at": {"$gte": cutoff}})

    # Tickets criados via autonomous_engine no período
    tk = await db.tickets.count_documents({
        "company_id": company_id, "origin": "autonomous_engine",
        "opened_at": {"$gte": cutoff}})

    # ONUs em LOS/Offline
    onu_bad = await db.smartolt_onus.count_documents({
        "company_id": company_id,
        "status": {"$in": ["LOS", "Offline", "Power fail"]}})
    onu_total = max(await db.smartolt_onus.count_documents(
        {"company_id": company_id}), 1)
    onu_bad_pct = (onu_bad / onu_total) * 100

    # Componentes (cada um 0-100)
    inf_score = max(0, 100 - zbx_host_down * 10)
    links_score = max(0, 100 - (onu_bad_pct * 2))
    routers_score = max(0, 100 - zbx_critical * 8)
    servers_score = max(0, 100 - zbx_open * 4)
    services_score = max(0, 100 - graf_firing * 15)
    monitoring_score = 100 if (zbx_open + graf_firing) >= 0 else 0
    alerts_score = max(0, 100 - (zbx_critical + graf_firing) * 10)

    components = {
        "infrastructure": round(inf_score, 1),
        "links": round(links_score, 1),
        "routers": round(routers_score, 1),
        "servers": round(servers_score, 1),
        "services": round(services_score, 1),
        "monitoring": round(monitoring_score, 1),
        "alerts": round(alerts_score, 1),
    }
    score = round(sum(components.values()) / len(components), 1)
    return {
        "company_id": company_id,
        "window_hours": window_hours,
        "score": score, "classification": _classify_health(score),
        "components": components,
        "raw": {
            "zabbix_open_events": zbx_open,
            "zabbix_critical": zbx_critical,
            "zabbix_host_down": zbx_host_down,
            "grafana_firing": graf_firing,
            "auto_tickets": tk,
            "onu_bad_pct": round(onu_bad_pct, 2),
        },
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 5 — CORRELAÇÃO (Zabbix + SmartOLT + Grafana + Tickets)
# ═══════════════════════════════════════════════════════════
async def correlate(
    company_id: str, window_hours: int = 6,
) -> List[Dict[str, Any]]:
    """Correlaciona eventos da janela. Retorna incidentes com:
    related_zabbix, related_grafana, impacted_subscribers,
    revenue_at_risk_BRL, confidence."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=window_hours)).isoformat()

    zbx_events = await db.motor_ia_events.find({
        "company_id": company_id, "source": "zabbix",
        "created_at": {"$gte": cutoff}}).to_list(200)
    graf_events = await db.motor_ia_events.find({
        "company_id": company_id, "source": "grafana",
        "created_at": {"$gte": cutoff}}).to_list(200)

    incidents: List[Dict[str, Any]] = []
    for zev in zbx_events:
        host = (zev.get("host_name") or "").lower()
        # Buscar Grafana alerts no mesmo host/rule
        matched_graf = [g for g in graf_events
                        if host and (host in (g.get("rule_name", "")
                                              .lower()))]
        # ONUs degradadas no período (proxy de impact)
        onu_bad = await db.smartolt_onus.count_documents({
            "company_id": company_id,
            "status": {"$in": ["LOS", "Offline", "Power fail"]}})
        # Subscribers afetados: pertencem a alguma zona com ONU ruim
        bad_zones = await db.smartolt_onus.distinct(
            "zone_name", {"company_id": company_id,
                          "status": {"$in": ["LOS", "Offline",
                                             "Power fail"]}})
        impacted_subs = 0
        revenue_risk = 0.0
        if bad_zones:
            cursor = db.subscribers.find({
                "company_id": company_id,
                "smartolt_onu_zone": {"$in": bad_zones},
                "status": {"$ne": "inactive"}},
                {"plan_price": 1})
            async for s in cursor:
                impacted_subs += 1
                revenue_risk += float(s.get("plan_price") or 0)
        confidence = 0.7 + (0.05 * len(matched_graf)) + (
            0.10 if zev.get("severity") in ZBX_CRITICAL_SEVERITIES
            else 0)
        confidence = min(round(confidence, 2), 0.95)
        incidents.append({
            "incident_id": _new("inc"),
            "company_id": company_id,
            "trigger_event": zev.get("id"),
            "trigger_event_type": zev.get("event_type"),
            "host_name": zev.get("host_name"),
            "severity": zev.get("severity"),
            "related_zabbix_event_ids": [zev.get("id")],
            "related_grafana_event_ids":
                [g.get("id") for g in matched_graf],
            "impacted_subscribers": impacted_subs,
            "impacted_onus_in_region": onu_bad,
            "revenue_at_risk_BRL": round(revenue_risk, 2),
            "confidence": confidence,
            "created_at": _now_iso(),
        })
    incidents.sort(key=lambda x: -x["revenue_at_risk_BRL"])
    return incidents


# ═══════════════════════════════════════════════════════════
# FASE 6 — KNOWLEDGE GRAPH (nodes + edges)
# ═══════════════════════════════════════════════════════════
async def persist_knowledge_graph(
    company_id: str, incidents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Cria nós/relações em knowledge_graph_nodes/edges."""
    nodes_inserted = 0
    edges_inserted = 0
    for inc in incidents:
        # Node ZABBIX_HOST
        host_node_id = f"zbx-host::{inc['host_name'] or 'unknown'}"
        await db.knowledge_graph_nodes.update_one(
            {"id": host_node_id, "company_id": company_id},
            {"$set": {"id": host_node_id, "company_id": company_id,
                      "kind": "ZABBIX_HOST",
                      "label": inc.get("host_name"),
                      "updated_at": _now_iso()}},
            upsert=True)
        # Node ZABBIX_PROBLEM
        prob_node_id = f"zbx-problem::{inc['trigger_event']}"
        await db.knowledge_graph_nodes.update_one(
            {"id": prob_node_id, "company_id": company_id},
            {"$set": {"id": prob_node_id, "company_id": company_id,
                      "kind": "ZABBIX_PROBLEM",
                      "label": inc.get("trigger_event_type"),
                      "severity": inc.get("severity"),
                      "updated_at": _now_iso()}},
            upsert=True)
        nodes_inserted += 2
        # Edge HOST → PROBLEM
        edge_id = f"e::{host_node_id}::generates::{prob_node_id}"
        await db.knowledge_graph_edges.update_one(
            {"id": edge_id, "company_id": company_id},
            {"$set": {"id": edge_id, "company_id": company_id,
                      "src": host_node_id, "dst": prob_node_id,
                      "kind": "GENERATES_PROBLEM",
                      "updated_at": _now_iso()}},
            upsert=True)
        edges_inserted += 1
        # Edge PROBLEM → RECEITA_EM_RISCO
        if inc["revenue_at_risk_BRL"] > 0:
            rev_node_id = (
                f"revenue::{inc['incident_id']}")
            await db.knowledge_graph_nodes.update_one(
                {"id": rev_node_id, "company_id": company_id},
                {"$set": {
                    "id": rev_node_id, "company_id": company_id,
                    "kind": "RECEITA_EM_RISCO",
                    "amount_BRL": inc["revenue_at_risk_BRL"],
                    "updated_at": _now_iso()}},
                upsert=True)
            nodes_inserted += 1
            re_id = f"e::{prob_node_id}::causes::{rev_node_id}"
            await db.knowledge_graph_edges.update_one(
                {"id": re_id, "company_id": company_id},
                {"$set": {"id": re_id, "company_id": company_id,
                          "src": prob_node_id, "dst": rev_node_id,
                          "kind": "CAUSES_REVENUE_RISK",
                          "amount_BRL": inc["revenue_at_risk_BRL"],
                          "updated_at": _now_iso()}},
                upsert=True)
            edges_inserted += 1
    return {"company_id": company_id,
            "nodes_upserted": nodes_inserted,
            "edges_upserted": edges_inserted,
            "generated_at": _now_iso()}


# ═══════════════════════════════════════════════════════════
# FASE 7 — PRESIDENTE IA + ÁLVARO IA
# ═══════════════════════════════════════════════════════════
async def presidente_brief(
    company_id: str, window_hours: int = 24,
) -> Dict[str, Any]:
    """Briefing executivo. Responde:
       O que está falhando? Qual incidente tem maior impacto?
       Qual região? Qual serviço? Qual alerta priorizar?
       Qual receita em risco?"""
    health = await observability_health_score(company_id, window_hours)
    incidents = await correlate(company_id, window_hours=window_hours)
    total_revenue_at_risk = sum(i["revenue_at_risk_BRL"]
                                for i in incidents)
    top_incident = incidents[0] if incidents else None
    failing_components = [k for k, v in health["components"].items()
                          if v < 80]
    return {
        "company_id": company_id,
        "health_score": health["score"],
        "classification": health["classification"],
        "what_is_failing": failing_components,
        "top_incident": top_incident,
        "total_revenue_at_risk_BRL": round(total_revenue_at_risk, 2),
        "open_zabbix_events": health["raw"]["zabbix_open_events"],
        "firing_grafana_alerts": health["raw"]["grafana_firing"],
        "prioritize": ([f"Incidente {top_incident['host_name']} "
                        f"(severity={top_incident['severity']})"]
                       if top_incident else
                       ["Sem incidentes críticos no momento"]),
        "generated_at": _now_iso(),
    }


async def alvaro_recommendation(
    incident: Dict[str, Any]
) -> Dict[str, Any]:
    """Recomendações operacionais:
       open_os / acionar técnico / acionar NOC / escalar gestor."""
    sev = (incident.get("severity") or "")
    impacted = incident.get("impacted_subscribers", 0)
    rev = incident.get("revenue_at_risk_BRL", 0)
    actions: List[str] = []
    if sev in ZBX_CRITICAL_SEVERITIES:
        actions.append("open_noc_ticket")
    if impacted > 0:
        actions.append("open_technical_ticket")
    if impacted >= 20:
        actions.append("create_incident")
        actions.append("notify_presidente")
    if rev >= 1000:
        actions.append("pause_dunning_for_impacted_clients")
    if not actions:
        actions.append("notify_alvaro")
    return {
        "incident_id": incident.get("incident_id"),
        "recommended_actions": actions,
        "needs_field_tech": impacted > 0 and sev in
                            ZBX_CRITICAL_SEVERITIES,
        "needs_noc": sev in ZBX_CRITICAL_SEVERITIES,
        "needs_escalation": impacted >= 20 or rev >= 5000,
        "confidence": incident.get("confidence", 0.7),
    }


# ═══════════════════════════════════════════════════════════
# FASE 8 — OBSERVABILITY TWIN SUMMARY (cards do Command Center)
# ═══════════════════════════════════════════════════════════
async def observability_summary(
    company_id: str, window_hours: int = 24,
) -> Dict[str, Any]:
    """Resumo único para a UI com 10 cards no padrão V5.0
    PROBLEMA/CAUSA/IMPACTO/AÇÃO/CONFIANÇA/EVIDÊNCIA."""
    health = await observability_health_score(company_id, window_hours)
    incidents = await correlate(company_id, window_hours=window_hours)
    pres = await presidente_brief(company_id, window_hours)

    zbx_count = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "zabbix",
        "created_at": {"$gte": _cutoff(1)}})
    graf_count = await db.motor_ia_events.count_documents({
        "company_id": company_id, "source": "grafana",
        "created_at": {"$gte": _cutoff(1)}})
    host_down = health["raw"]["zabbix_host_down"]
    impacted_total = sum(i["impacted_subscribers"] for i in incidents)
    total_rev = pres["total_revenue_at_risk_BRL"]

    cards = [
        {"title": "Saúde da Infraestrutura",
         "problem": f"Score {health['score']} ({health['classification']})",
         "cause": ", ".join(pres["what_is_failing"])
                  or "Sem componentes em falha",
         "impact": f"R$ {total_rev:,.2f}/mês em receita exposta",
         "action": ("Acompanhar componentes vermelhos"
                    if pres["what_is_failing"]
                    else "Manter monitoramento ativo"),
         "confidence": 0.95,
         "evidence": [{"type": "components", "value": health["components"],
                       "source": "zabbix+grafana+smartolt"}]},
        {"title": "Alertas Críticos (Zabbix)",
         "problem": f"{health['raw']['zabbix_critical']} alertas críticos",
         "cause": "Severity high/disaster aberta",
         "impact": "Risco operacional iminente",
         "action": "Triagem NOC imediata",
         "confidence": 0.95,
         "evidence": [{"type": "zabbix_critical",
                       "value": health["raw"]["zabbix_critical"],
                       "source": "motor_ia_events"}]},
        {"title": "Hosts em Problema",
         "problem": f"{host_down} host(s) com problema HOST_DOWN",
         "cause": "Conectividade ICMP/SNMP perdida",
         "impact": "Visibilidade da rede comprometida",
         "action": "Visita ao DC + verificar uplink",
         "confidence": 0.90,
         "evidence": [{"type": "zabbix_host_down", "value": host_down,
                       "source": "motor_ia_events"}]},
        {"title": "Links Degradados",
         "problem": f"{health['raw']['onu_bad_pct']}% ONUs ruins",
         "cause": "LOS/Offline/Power Fail",
         "impact": "Clientes sem serviço regional",
         "action": "Despachar técnicos por CTO",
         "confidence": 0.85,
         "evidence": [{"type": "onu_bad_pct",
                       "value": health["raw"]["onu_bad_pct"],
                       "source": "smartolt_onus"}]},
        {"title": "Serviços Fora (Grafana)",
         "problem": f"{health['raw']['grafana_firing']} alerta(s) firing",
         "cause": "Threshold dashboard ultrapassado",
         "impact": "Degradação de SLO",
         "action": "Validar alerta + abrir incidente",
         "confidence": 0.90,
         "evidence": [{"type": "grafana_firing",
                       "value": health["raw"]["grafana_firing"],
                       "source": "motor_ia_events"}]},
        {"title": "Clientes Impactados",
         "problem": f"{impacted_total} cliente(s) afetado(s)",
         "cause": "Incidentes em CTOs com falha",
         "impact": (f"Risco de churn imediato em "
                    f"{impacted_total} clientes"),
         "action": "Pausar régua de cobrança + comunicação proativa",
         "confidence": 0.85,
         "evidence": [{"type": "impacted_subscribers",
                       "value": impacted_total,
                       "source": "subscribers+smartolt_onus"}]},
        {"title": "Receita em Risco",
         "problem": f"R$ {total_rev:,.2f}/mês",
         "cause": "Plan price dos subs em zona impactada",
         "impact": "Receita realizável bloqueada",
         "action": "Reduzir TTR (time-to-resolve) prioritário",
         "confidence": 0.88,
         "evidence": [{"type": "revenue_at_risk", "value": total_rev,
                       "source": "subscribers.plan_price"}]},
        {"title": "Incidentes Correlacionados",
         "problem": f"{len(incidents)} incidente(s) ativo(s)",
         "cause": "Zabbix + SmartOLT + Grafana convergem",
         "impact": ("Causa raiz unificada permite ação única"),
         "action": "Abrir 1 incidente master + tickets filhos",
         "confidence": 0.85,
         "evidence": [{"type": "incident_count", "value": len(incidents),
                       "source": "correlate()"}]},
        {"title": "Ações Recomendadas (Álvaro)",
         "problem": ("Necessidade de ação operacional"
                     if incidents else "Sistema estável"),
         "cause": "Decisão V5 a partir de incidentes correlacionados",
         "impact": "Reduzir MTTR + churn",
         "action": (f"{len(incidents)} incidente(s) requer(em) Álvaro"
                    if incidents else "Aguardar próximo ciclo"),
         "confidence": 0.85,
         "evidence": [{"type": "alvaro_recommendations",
                       "value": len(incidents), "source": "correlate"}]},
        {"title": "Evidências (raw)",
         "problem": (f"{zbx_count} eventos Zabbix + "
                     f"{graf_count} Grafana nas últimas 24h"),
         "cause": "Ingestão automática dos conectores",
         "impact": "Trilha completa para auditoria",
         "action": "Manter ciclo de ingestão a cada 5 min",
         "confidence": 0.99,
         "evidence": [{"type": "zbx_events_24h", "value": zbx_count,
                       "source": "motor_ia_events"},
                      {"type": "graf_events_24h", "value": graf_count,
                       "source": "motor_ia_events"}]},
    ]
    return {
        "company_id": company_id,
        "health": health, "incidents": incidents,
        "presidente_brief": pres, "cards": cards,
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 9 — DECISÕES AUTÔNOMAS A PARTIR DAS CORRELAÇÕES
# ═══════════════════════════════════════════════════════════
async def emit_decisions_from_correlations(
    company_id: str, window_hours: int = 6,
) -> Dict[str, Any]:
    """Para cada incidente correlacionado CRÍTICO com confiança > 0.8:
    chama autonomous_engine.run_cycle com event_type=OBSERVABILITY_INCIDENT.
    """
    from services import autonomous_engine as eng
    incidents = await correlate(company_id, window_hours=window_hours)
    cycles: List[str] = []
    for inc in incidents:
        sev = (inc.get("severity") or "")
        conf = inc.get("confidence", 0)
        if sev not in ZBX_CRITICAL_SEVERITIES or conf < 0.8:
            continue
        reco = await alvaro_recommendation(inc)
        cyc = await eng.run_cycle({
            "event_type": "OBSERVABILITY_INCIDENT",
            "company_id": company_id,
            "subscriber_id": None,
            "payload": {
                "incident_id": inc["incident_id"],
                "host_name": inc["host_name"],
                "severity": sev,
                "impacted_subscribers":
                    inc["impacted_subscribers"],
                "revenue_at_risk_BRL": inc["revenue_at_risk_BRL"],
                "recommended_actions": reco["recommended_actions"],
                "confidence": conf,
            },
        })
        cycles.append(cyc["cycle_id"])
        # Salvar incidente
        await db.observability_incidents.update_one(
            {"incident_id": inc["incident_id"],
             "company_id": company_id},
            {"$set": {**inc, "cycle_id": cyc["cycle_id"],
                      "recommendation": reco,
                      "updated_at": _now_iso()}},
            upsert=True)
    return {"company_id": company_id,
            "incidents_processed": len(incidents),
            "cycles_triggered": len(cycles),
            "cycle_ids": cycles[:50],
            "generated_at": _now_iso()}


# ═══════════════════════════════════════════════════════════
# FULL PIPELINE — utilitário 1 chamada
# ═══════════════════════════════════════════════════════════
async def run_full_pipeline(company_id: str) -> Dict[str, Any]:
    """Ciclo completo: ingest Zabbix → snapshot Grafana → correlate →
    knowledge_graph → autonomous decisions. Idempotente (dedup por
    zabbix_eventid)."""
    zbx_conn = ZabbixConnector()
    graf_conn = GrafanaConnector()
    try:
        zbx_out = await ingest_zabbix_problems(company_id, zbx_conn)
        graf_out = await snapshot_grafana(company_id, graf_conn)
        incidents = await correlate(company_id, window_hours=6)
        kg = await persist_knowledge_graph(company_id, incidents)
        dec = await emit_decisions_from_correlations(
            company_id, window_hours=6)
        return {
            "company_id": company_id,
            "zabbix": zbx_out, "grafana": graf_out,
            "incidents_correlated": len(incidents),
            "knowledge_graph": kg, "decisions": dec,
            "is_mock_mode": (not zbx_conn.is_real
                             and not graf_conn.is_real),
            "generated_at": _now_iso(),
        }
    finally:
        await zbx_conn.close()
        await graf_conn.close()
