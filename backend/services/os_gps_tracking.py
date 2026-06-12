"""GPS auto-detection de en_route e on_site para OSs (CTO P1).

Lógica:
  • Quando colaborador inicia movimento em direção a OS atribuída → en_route
  • Quando colaborador entra em raio 80m da OS → on_site (= in_progress)

Hook nas atualizações de Fleet `last_position` do colaborador.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Tuple

from database import db
from services.os_lifecycle import transition

logger = logging.getLogger("os_gps_tracking")

ON_SITE_RADIUS_M = 80   # raio de chegada
EN_ROUTE_RADIUS_M = 5000  # se está a até 5km, considera "indo pra lá"


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Distância em metros entre 2 coords."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _extract_coords(addr_or_loc: Optional[dict]) -> Optional[Tuple[float, float]]:
    if not addr_or_loc:
        return None
    if isinstance(addr_or_loc, dict):
        lat = addr_or_loc.get("lat") or addr_or_loc.get("latitude")
        lng = addr_or_loc.get("lng") or addr_or_loc.get("lon") \
              or addr_or_loc.get("longitude")
        if lat is not None and lng is not None:
            try:
                return float(lat), float(lng)
            except (ValueError, TypeError):
                return None
    return None


async def check_collaborator_progress(
    company_id: str, collaborator_id: str,
    lat: float, lng: float,
) -> dict:
    """Para cada OS ATRIBUÍDA/ACCEPTED do colaborador, verifica se a posição
    GPS aciona transição para en_route ou on_site (in_progress).

    Idempotente: se já está no estado, não faz nada.
    """
    summary = {"checked": 0, "en_route": 0, "on_site": 0, "skipped": 0}
    cursor = db.tickets.find(
        {"company_id": company_id,
         "assigned_collaborator_id": collaborator_id,
         "lifecycle_state": {"$in": ["assigned", "accepted", "en_route"]}},
        {"_id": 0, "id": 1, "lifecycle_state": 1, "location": 1,
         "client_location": 1, "geolocation": 1, "lat": 1, "lng": 1},
    )
    async for t in cursor:
        summary["checked"] += 1
        coords = (_extract_coords(t.get("location"))
                  or _extract_coords(t.get("client_location"))
                  or _extract_coords(t.get("geolocation"))
                  or _extract_coords({"lat": t.get("lat"), "lng": t.get("lng")}))
        if not coords:
            summary["skipped"] += 1
            continue
        dist = _haversine_m(lat, lng, coords[0], coords[1])
        current = t.get("lifecycle_state")

        # ON SITE: chegou no local (≤80m)
        if dist <= ON_SITE_RADIUS_M and current in ("assigned", "accepted", "en_route"):
            try:
                await transition(
                    db, t["id"],
                    to_state="in_progress",
                    notes=f"GPS auto: chegada detectada ({int(dist)}m)",
                    actor={"id": "system", "name": "GPS auto-detect",
                            "email": "system@smartprov"},
                    force=True,  # pula validações (assigned→in_progress não é direto)
                )
                summary["on_site"] += 1
            except Exception as e:
                logger.warning("[gps] on_site %s falhou: %s", t["id"], e)
            continue

        # EN ROUTE: dentro do raio mas ainda não chegou (e em assigned/accepted)
        if (dist <= EN_ROUTE_RADIUS_M and current in ("assigned", "accepted")):
            try:
                await transition(
                    db, t["id"],
                    to_state="en_route",
                    notes=f"GPS auto: técnico a {int(dist)}m do destino",
                    actor={"id": "system", "name": "GPS auto-detect",
                            "email": "system@smartprov"},
                    force=True,
                )
                summary["en_route"] += 1
            except Exception as e:
                logger.warning("[gps] en_route %s falhou: %s", t["id"], e)

    return summary
