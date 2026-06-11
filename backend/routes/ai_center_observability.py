"""ai_center_observability.py — Endpoints REST Observability Twin."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from database import db
from core import require_role
from services import observability_twin as twin

router = APIRouter(prefix="/api/ai-center/observability",
                   tags=["observability-twin"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente.")
    return cid


@router.get("/health")
async def get_health(window_hours: int = Query(24, ge=1, le=720),
                     user=Depends(require_role("administrador",
                                               "auditor", "gestor"))):
    return await twin.observability_health_score(
        _co(user), window_hours=window_hours)


@router.get("/summary")
async def get_summary(window_hours: int = Query(24, ge=1, le=720),
                      user=Depends(require_role("administrador",
                                                "auditor", "gestor"))):
    return await twin.observability_summary(_co(user),
                                            window_hours=window_hours)


@router.get("/presidente-brief")
async def get_pres(window_hours: int = Query(24, ge=1, le=720),
                   user=Depends(require_role("administrador",
                                             "auditor", "gestor"))):
    return await twin.presidente_brief(_co(user),
                                       window_hours=window_hours)


@router.get("/incidents")
async def get_incidents(window_hours: int = Query(6, ge=1, le=72),
                        user=Depends(require_role("administrador",
                                                  "auditor", "gestor"))):
    items = await twin.correlate(_co(user), window_hours=window_hours)
    return {"items": items, "count": len(items)}


@router.post("/zabbix/ingest")
async def zabbix_ingest(user=Depends(require_role("administrador"))):
    """Pull manual do Zabbix (a cron faz a cada 5 min)."""
    conn = twin.ZabbixConnector()
    try:
        return await twin.ingest_zabbix_problems(_co(user), conn)
    finally:
        await conn.close()


@router.post("/grafana/snapshot")
async def grafana_snap(user=Depends(require_role("administrador"))):
    conn = twin.GrafanaConnector()
    try:
        return await twin.snapshot_grafana(_co(user), conn)
    finally:
        await conn.close()


@router.post("/run")
async def run_pipeline(user=Depends(require_role("administrador"))):
    """Dispara pipeline completo: Zabbix + Grafana + Correlate +
    Knowledge Graph + Decisões autônomas."""
    return await twin.run_full_pipeline(_co(user))


@router.get("/grafana/olts")
async def grafana_olts(user=Depends(require_role("administrador",
                                                  "auditor", "gestor"))):
    """Lista OLTs monitorados pelo Grafana + KPIs agregados.

    Identifica dashboards com tag 'OLT' (huawei/zte/datacom) ou que
    contenham OLT/PON/ONU no título. Para cada um conta panels relevantes
    a ONT/ONU (timeseries de sinal, status de PON, etc) e retorna
    dados estruturados para a sub-aba "ONT/ONU · Grafana".
    """
    conn = twin.GrafanaConnector()
    try:
        olts = await conn.list_olt_dashboards()
        kpis_items: List[Dict[str, Any]] = []
        total_panels = 0
        total_pon_panels = 0
        total_onu_panels = 0
        total_alert_panels = 0
        vendors: Dict[str, int] = {}
        for o in olts:
            detail = await conn.get_dashboard_detail(o["uid"])
            panel_count = 0
            pon_panels = 0
            onu_panels = 0
            alert_panels = 0
            if detail:
                stack = list(detail.get("dashboard", {}).get("panels", []))
                while stack:
                    p = stack.pop()
                    panel_count += 1
                    title = (p.get("title") or "").lower()
                    if "onu" in title or "ont" in title:
                        onu_panels += 1
                    if "pon" in title:
                        pon_panels += 1
                    if ("alerta" in title or "alert" in title
                            or "incidente" in title):
                        alert_panels += 1
                    if p.get("panels"):
                        stack.extend(p["panels"])
            o["panels"] = panel_count
            o["pon_panels"] = pon_panels
            o["onu_panels"] = onu_panels
            o["alert_panels"] = alert_panels
            kpis_items.append(o)
            total_panels += panel_count
            total_pon_panels += pon_panels
            total_onu_panels += onu_panels
            total_alert_panels += alert_panels
            vendors[o["vendor"]] = vendors.get(o["vendor"], 0) + 1

        return {
            "kpis": {
                "olts_monitored": len(olts),
                "total_panels": total_panels,
                "pon_panels": total_pon_panels,
                "onu_panels": total_onu_panels,
                "alert_panels": total_alert_panels,
                "vendors": vendors,
            },
            "items": kpis_items,
            "grafana_url": conn.url,
        }
    finally:
        await conn.close()



@router.get("/grafana/olts/all")
async def grafana_olts_all(user=Depends(require_role(
        "administrador", "auditor", "gestor"))):
    """Agrega OLTs de TODOS os perfis Grafana habilitados (multi-ativo).

    Permite ver simultaneamente OLTs cadastradas em N Grafanas
    (ex: cliente A + cliente B + matriz)."""
    import asyncio as _asyncio
    connectors = await twin.list_enabled_grafana_connectors()
    if not connectors:
        return {"profiles": 0, "kpis": {}, "items": []}

    async def _one(c):
        try:
            olts = await c.list_olt_dashboards()
            kpis_items = []
            for o in olts:
                d = await c.get_dashboard_detail(o["uid"])
                pc = po = pn = pa = 0
                if d:
                    stack = list(d.get("dashboard", {}).get(
                        "panels", []))
                    while stack:
                        p = stack.pop()
                        pc += 1
                        t = (p.get("title") or "").lower()
                        if "onu" in t or "ont" in t:
                            pn += 1
                        if "pon" in t:
                            po += 1
                        if "alerta" in t or "alert" in t:
                            pa += 1
                        if p.get("panels"):
                            stack.extend(p["panels"])
                o["panels"] = pc
                o["pon_panels"] = po
                o["onu_panels"] = pn
                o["alert_panels"] = pa
                o["_profile"] = c.profile or "default"
                kpis_items.append(o)
            return {
                "profile": c.profile or "default",
                "url": c.url,
                "olts": kpis_items,
            }
        finally:
            try:
                await c.close()
            except Exception:
                pass

    per_profile = await _asyncio.gather(*[_one(c) for c in connectors],
                                           return_exceptions=True)
    profiles_out = [p for p in per_profile if isinstance(p, dict)]

    # Agrega KPIs cross-profile
    agg = {"olts_monitored": 0, "total_panels": 0,
            "pon_panels": 0, "onu_panels": 0, "alert_panels": 0,
            "vendors": {}}
    all_items = []
    for p in profiles_out:
        for o in p["olts"]:
            agg["olts_monitored"] += 1
            agg["total_panels"] += o.get("panels", 0)
            agg["pon_panels"] += o.get("pon_panels", 0)
            agg["onu_panels"] += o.get("onu_panels", 0)
            agg["alert_panels"] += o.get("alert_panels", 0)
            v = o.get("vendor") or "UNKNOWN"
            agg["vendors"][v] = agg["vendors"].get(v, 0) + 1
            all_items.append(o)
    return {
        "profiles": len(profiles_out),
        "kpis": agg,
        "items": all_items,
        "per_profile": [{"profile": p["profile"], "url": p["url"],
                          "olt_count": len(p["olts"])}
                         for p in profiles_out],
    }


@router.post("/grafana/discover-onus")
async def grafana_discover_onus(
    user=Depends(require_role("administrador", "auditor", "gestor"))
):
    """Discovery REAL de ONT/ONU.

    Estratégia híbrida:
    1) Tenta Grafana proxy (data source Zabbix) — funciona se o data
       source aceitar passar credenciais (raramente acontece).
    2) Fallback automático: tenta `ZabbixConnector` direto (se Zabbix
       estiver cadastrado em Credenciais → Zabbix).
    """
    import asyncio as _asyncio
    connectors = await twin.list_enabled_grafana_connectors()

    async def _one_graf(c):
        try:
            res = await c.discover_onus()
            for o in (res.get("onus") or []):
                o["_profile"] = c.profile or "default"
                o["_grafana_url"] = c.url
                o["_source"] = "grafana_proxy"
            return res
        except Exception as e:
            return {"_error": repr(e)[:200],
                    "profile": c.profile or "default"}
        finally:
            try:
                await c.close()
            except Exception:
                pass

    results = await _asyncio.gather(*[_one_graf(c) for c in connectors],
                                       return_exceptions=True)
    all_onus: List[Dict[str, Any]] = []
    total_items = 0
    profiles_summary: List[Dict[str, Any]] = []
    any_proxy_unauth = False
    for i, r in enumerate(results):
        prof = connectors[i].profile or "default"
        if isinstance(r, dict) and "_error" not in r:
            all_onus.extend(r.get("onus") or [])
            total_items += r.get("items_returned", 0)
            if r.get("proxy_unauthorized"):
                any_proxy_unauth = True
            profiles_summary.append({
                "profile": prof, "source": "grafana_proxy",
                "datasources": r.get("datasources", 0),
                "onus_found": r.get("onu_count", 0),
                "items": r.get("items_returned", 0),
                "note": r.get("note"),
                "proxy_unauthorized": r.get("proxy_unauthorized", False),
                "hint": r.get("hint"),
            })
        else:
            profiles_summary.append({
                "profile": prof, "source": "grafana_proxy",
                "error": (r.get("_error")
                          if isinstance(r, dict) else repr(r)[:200]),
            })

    # Fallback: Zabbix direto, se cadastrado
    zbx = twin.ZabbixConnector()
    zbx_configured = False
    try:
        await zbx._load_from_vault()
        zbx_configured = zbx.is_real
        if zbx.is_real:
            zbx_result = await zbx.discover_onus()
            for o in (zbx_result.get("onus") or []):
                o["_source"] = "zabbix_direct"
                all_onus.append(o)
            profiles_summary.append({
                "profile": "_zabbix_direct",
                "source": "zabbix_direct",
                "onus_found": zbx_result.get("onu_count", 0),
                "items": zbx_result.get("items_returned", 0),
            })
        else:
            profiles_summary.append({
                "profile": "_zabbix_direct",
                "source": "zabbix_direct",
                "configured": False,
                "hint": ("Cadastre Zabbix em Credenciais → Zabbix "
                          "(URL + API Token) para discovery completo."),
            })
    finally:
        try:
            await zbx.close()
        except Exception:
            pass

    # Discovery via OLT SNMP direto (fonte mais confiável)
    try:
        from routes.olt_registry import (_list_profile_names, _k,
                                            _load_poller)
        olt_names = await _list_profile_names()
        from services import secrets_vault as _v
        enabled_olts = []
        for n in olt_names:
            en = await _v.get_secret(_k(n, "enabled"), scope="global")
            if en != "false":
                enabled_olts.append(n)
        import asyncio as _aio

        async def _one_olt(n):
            try:
                p = await _load_poller(n)
                r = await p.discover_onus()
                for o in (r.get("onus") or []):
                    o["_source"] = "olt_snmp"
                    o["_olt"] = n
                    o["_host"] = p.host
                return {"profile": n, "host": p.host,
                        "onu_count": r.get("onu_count", 0),
                        "onus": r.get("onus", []),
                        "errors": r.get("errors")}
            except Exception as e:
                return {"profile": n, "error": repr(e)[:200]}

        olt_results = await _aio.gather(*[_one_olt(n) for n in enabled_olts],
                                            return_exceptions=True)
        for rr in olt_results:
            if isinstance(rr, dict) and "error" not in rr:
                all_onus.extend(rr.get("onus") or [])
                profiles_summary.append({
                    "profile": rr["profile"],
                    "source": "olt_snmp",
                    "host": rr.get("host"),
                    "onus_found": rr.get("onu_count", 0),
                    "errors": rr.get("errors"),
                })
            elif isinstance(rr, dict):
                profiles_summary.append({
                    "profile": rr["profile"],
                    "source": "olt_snmp",
                    "error": rr.get("error"),
                })
    except Exception as e:
        profiles_summary.append({
            "profile": "_olt_snmp", "source": "olt_snmp",
            "error": repr(e)[:200],
        })

    return {
        "profiles": len(connectors),
        "total_items": total_items,
        "onu_count": len(all_onus),
        "onus": all_onus,
        "per_profile": profiles_summary,
        "fallback_required": any_proxy_unauth and not zbx_configured,
        "guidance": (
            "Grafana proxy não autentica no Zabbix automaticamente. "
            "Para discovery completo de ONUs (SN, MAC, sinal), "
            "cadastre as credenciais Zabbix em 'Credenciais Integração "
            "→ aba Zabbix' OU cadastre OLTs SNMP direto em 'aba OLT (SNMP)'."
            if any_proxy_unauth and not zbx_configured else None
        ),
    }


@router.get("/grafana/diagnose")
async def grafana_diagnose(user=Depends(require_role("administrador",
                                                     "auditor", "gestor"))):
    """Diagnóstico do Grafana: lista permissões RBAC do usuário
    configurado. Útil para entender 403s."""
    conn = twin.GrafanaConnector()
    try:
        actions = await conn.get_user_permissions()
        # Categoriza
        cats: Dict[str, List[str]] = {}
        for a in actions or {}:
            cat = a.split(":")[0] if ":" in a else "other"
            cats.setdefault(cat, []).append(a)
        return {
            "is_real": conn.is_real,
            "url": conn.url or None,
            "auth_mode": conn.auth_mode,
            "permissions_count": len(actions or {}),
            "categories": {k: sorted(v) for k, v in cats.items()},
            "raw_actions": sorted((actions or {}).keys()),
        }
    finally:
        await conn.close()


@router.get("/connectors/status")
async def conn_status(user=Depends(require_role("administrador",
                                                "auditor", "gestor"))):
    """Status REAL — faz ping em /api/org (Grafana) e ping em api_jsonrpc
    (Zabbix). Reporta permissões insuficientes detectadas."""
    import httpx
    zbx = twin.ZabbixConnector()
    graf = twin.GrafanaConnector()
    try:
        # Carrega vault antes (vault tem prioridade sobre .env)
        await zbx._load_from_vault()
        await graf._load_from_vault()
        from services import secrets_vault as _v
        vault_ok = _v.is_available()
        zbx_in_vault = vault_ok and bool(
            await _v.get_secret("integration:zabbix:url"))
        graf_in_vault = vault_ok and bool(
            await _v.get_secret("integration:grafana:url"))

        # ── Connectivity probe: Grafana ──
        graf_probe = {"connected": False, "status": None,
                       "permission_warnings": [], "org_name": None,
                       "endpoints_403": [],
                       "capabilities": {},
                       "fully_operational": False}
        if graf.is_real:
            try:
                hdrs = {"Accept": "application/json"}
                auth = None
                if graf.token:
                    hdrs["Authorization"] = f"Bearer {graf.token}"
                elif graf.user and graf.password:
                    auth = (graf.user, graf.password)
                if graf.org_id:
                    hdrs["X-Grafana-Org-Id"] = graf.org_id
                async with httpx.AsyncClient(timeout=10) as cli:
                    # /api/org só requer login
                    r = await cli.get(f"{graf.url}/api/org",
                                       headers=hdrs, auth=auth)
                    graf_probe["status"] = r.status_code
                    if r.status_code == 200:
                        graf_probe["connected"] = True
                        try:
                            graf_probe["org_name"] = r.json().get("name")
                        except Exception:
                            pass
                    # Testa CAPABILITIES reais (endpoints que usamos no
                    # snapshot, considerando fallbacks).
                    caps_probes = [
                        # nome lógico, endpoint, fallback?, weight
                        ("dashboards", "/api/search?type=dash-db", None, 1),
                        ("folders", "/api/folders",
                         "/api/search?type=dash-folder", 1),
                        ("datasources", "/api/datasources", None, 1),
                        ("alerts",
                         "/api/alertmanager/grafana/api/v2/alerts",
                         "/api/ruler/grafana/api/v1/rules", 1),
                        ("annotations", "/api/annotations", None, 0),
                    ]
                    fail_critical = []
                    for name, ep, fb, weight in caps_probes:
                        rr = await cli.get(f"{graf.url}{ep}",
                                            headers=hdrs, auth=auth)
                        if rr.status_code == 200:
                            graf_probe["capabilities"][name] = {
                                "ok": True, "via": "primary"}
                        elif fb:
                            # Tenta fallback que aceita Viewer
                            rfb = await cli.get(f"{graf.url}{fb}",
                                                  headers=hdrs, auth=auth)
                            if rfb.status_code == 200:
                                graf_probe["capabilities"][name] = {
                                    "ok": True, "via": "fallback",
                                    "fallback_endpoint": fb}
                            else:
                                graf_probe["capabilities"][name] = {
                                    "ok": False, "status": rfb.status_code,
                                    "tried": [ep, fb]}
                                if weight > 0:
                                    fail_critical.append(name)
                                graf_probe["endpoints_403"].append(ep)
                        else:
                            graf_probe["capabilities"][name] = {
                                "ok": False, "status": rr.status_code,
                                "tried": [ep]}
                            if weight > 0:
                                fail_critical.append(name)
                            if rr.status_code in (401, 403):
                                graf_probe["endpoints_403"].append(ep)
                    graf_probe["fully_operational"] = (
                        len(fail_critical) == 0)
                    if fail_critical:
                        graf_probe["permission_warnings"].append(
                            f"Sem acesso a: {', '.join(fail_critical)}. "
                            f"Use Service Account Token com role Admin "
                            f"para acesso pleno.")
            except Exception as e:
                graf_probe["status"] = "error"
                graf_probe["error"] = repr(e)[:200]

        # ── Connectivity probe: Zabbix ──
        zbx_probe = {"connected": False, "status": None}
        if zbx.is_real:
            try:
                async with httpx.AsyncClient(timeout=10) as cli:
                    body = {"jsonrpc": "2.0", "method": "apiinfo.version",
                            "params": {}, "id": 1}
                    if zbx.token:
                        rr = await cli.post(
                            f"{zbx.url}/api_jsonrpc.php", json=body,
                            headers={"Authorization": f"Bearer {zbx.token}"})
                    else:
                        rr = await cli.post(
                            f"{zbx.url}/api_jsonrpc.php", json=body)
                    zbx_probe["status"] = rr.status_code
                    if rr.status_code == 200:
                        zbx_probe["connected"] = True
                        try:
                            zbx_probe["api_version"] = rr.json().get("result")
                        except Exception:
                            pass
            except Exception as e:
                zbx_probe["status"] = "error"
                zbx_probe["error"] = repr(e)[:200]

        return {
            "zabbix": {"is_real": zbx.is_real, "url": zbx.url or None,
                       "auth": ("token" if zbx.token else
                                "user_password" if zbx.user else "none"),
                       "source": "vault" if zbx_in_vault else (
                           "env" if zbx.is_real else "none"),
                       "probe": zbx_probe},
            "grafana": {"is_real": graf.is_real,
                         "url": graf.url or None,
                         "auth": ("token" if graf.token else
                                  "basic" if graf.user else "none"),
                         "source": "vault" if graf_in_vault else (
                             "env" if graf.is_real else "none"),
                         "probe": graf_probe},
            "mock_mode": (not zbx.is_real and not graf.is_real),
            "vault_available": vault_ok,
        }
    finally:
        await zbx.close()
        await graf.close()


@router.get("/knowledge-graph")
async def kg(limit: int = Query(200, ge=1, le=2000),
             user=Depends(require_role("administrador",
                                       "auditor", "gestor"))):
    cid = _co(user)
    nodes = []
    async for n in db.knowledge_graph_nodes.find(
            {"company_id": cid}).limit(limit):
        n.pop("_id", None)
        nodes.append(n)
    edges = []
    async for e in db.knowledge_graph_edges.find(
            {"company_id": cid}).limit(limit):
        e.pop("_id", None)
        edges.append(e)
    return {"nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges)}
