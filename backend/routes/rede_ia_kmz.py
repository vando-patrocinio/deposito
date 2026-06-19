"""rede_ia_kmz.py — Exportação/Importação KMZ da topologia de rede.

Endpoints:
  - GET  /api/rede-ia/map/export-kmz?vlan=X
        Baixa CTOs + CEs + Cabos da empresa como arquivo KMZ
        (compatível com Google Earth, QGIS, Maps.me, MapInfo).
  - POST /api/rede-ia/map/import-kmz (multipart file)
        Recebe KMZ/KML, parseia Placemarks e cria CTOs/CEs/Cabos.
        Estratégia: cada Folder vira uma categoria. Reconhece também
        Placemarks individuais com base no estilo/ícone.

Conversão KML ↔ DB:
  CTO → <Placemark><Point> em folder "CTOs"
        ExtendedData: sigla, vlan, capacity, network_type
  CE  → <Placemark><Point> em folder "CEs"
  Cabo → <Placemark><LineString> em folder "Cabos"
        ExtendedData: type (drop/6fo/12fo/24fo/48fo/96fo), fo_count, length_m
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

import io
import logging
import uuid
import xml.etree.ElementTree as ET
import defusedxml.ElementTree as DET  # SECURITY: XML defuse — bloqueia XXE/billion-laughs
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.rede_ia_kmz")
router = APIRouter(prefix="/api/rede-ia/map", tags=["rede-ia-kmz"])

# Namespaces KML 2.2
KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
ET.register_namespace("", KML_NS)

# Mapa de cor para CTOs por health/status (formato KML AABBGGRR — alfa+BGR)
CTO_KML_COLORS = {
    "ok":       "ff14a014",  # verde
    "warning":  "ff04a8ca",  # amarelo/laranja
    "critical": "ff2626dc",  # vermelho
    "no_data":  "ff8b8b94",  # cinza
    "unknown":  "ff8b8b94",
}

# Cor por tipo de cabo
CABLE_KML_COLORS = {
    "drop":  "ffa3a394",  # cinza claro
    "6fo":   "ff15ccfa",  # amarelo (BGR=facc15)
    "12fo":  "ff2c93fb",  # laranja
    "24fo":  "ff4444ef",  # vermelho
    "48fo":  "ffc25c8b",  # roxo
    "96fo":  "ff170f0f",  # preto
}
CABLE_KML_WIDTHS = {
    "drop": 2, "6fo": 3, "12fo": 4, "24fo": 5, "48fo": 6, "96fo": 7,
}


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------
def _build_kml(ctos: List[dict], ces: List[dict],
               cables: List[dict], company_name: str) -> str:
    """Monta KML 2.2 válido (compatível Google Earth/Maps/QGIS)."""
    kml = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(kml, f"{{{KML_NS}}}Document")
    ET.SubElement(doc, f"{{{KML_NS}}}name").text = (
        f"SmartProv — Topologia {company_name}")
    ET.SubElement(doc, f"{{{KML_NS}}}description").text = (
        f"Exportado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}. "
        f"{len(ctos)} CTOs, {len(ces)} CEs, {len(cables)} cabos.")

    # Estilos CTO por health
    for health, color in CTO_KML_COLORS.items():
        style = ET.SubElement(doc, f"{{{KML_NS}}}Style",
                              id=f"cto_{health}")
        icon_style = ET.SubElement(style, f"{{{KML_NS}}}IconStyle")
        ET.SubElement(icon_style, f"{{{KML_NS}}}color").text = color
        ET.SubElement(icon_style, f"{{{KML_NS}}}scale").text = "1.1"
        icon = ET.SubElement(icon_style, f"{{{KML_NS}}}Icon")
        ET.SubElement(icon, f"{{{KML_NS}}}href").text = (
            "http://maps.google.com/mapfiles/kml/shapes/square.png")

    # Estilo CE (losango azul)
    ce_style = ET.SubElement(doc, f"{{{KML_NS}}}Style", id="ce_style")
    ce_icon = ET.SubElement(ce_style, f"{{{KML_NS}}}IconStyle")
    ET.SubElement(ce_icon, f"{{{KML_NS}}}color").text = "ffe14025"  # azul
    ET.SubElement(ce_icon, f"{{{KML_NS}}}scale").text = "1.0"
    ce_iconchild = ET.SubElement(ce_icon, f"{{{KML_NS}}}Icon")
    ET.SubElement(ce_iconchild, f"{{{KML_NS}}}href").text = (
        "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png")

    # Estilos por tipo de cabo
    for ctype, color in CABLE_KML_COLORS.items():
        style = ET.SubElement(doc, f"{{{KML_NS}}}Style",
                              id=f"cable_{ctype}")
        line = ET.SubElement(style, f"{{{KML_NS}}}LineStyle")
        ET.SubElement(line, f"{{{KML_NS}}}color").text = color
        ET.SubElement(line, f"{{{KML_NS}}}width").text = str(
            CABLE_KML_WIDTHS.get(ctype, 3))

    # Folder CTOs
    if ctos:
        folder = ET.SubElement(doc, f"{{{KML_NS}}}Folder")
        ET.SubElement(folder, f"{{{KML_NS}}}name").text = "CTOs"
        for c in ctos:
            lat = c.get("lat")
            lng = c.get("lng")
            if lat is None or lng is None:
                continue
            health_status = (c.get("health") or {}).get("status") or "unknown"
            pm = ET.SubElement(folder, f"{{{KML_NS}}}Placemark")
            ET.SubElement(pm, f"{{{KML_NS}}}name").text = (
                c.get("sigla") or c.get("name") or "CTO")
            ET.SubElement(pm, f"{{{KML_NS}}}description").text = (
                f"<![CDATA[<b>{c.get('name', '')}</b><br>"
                f"VLAN: {c.get('vlan') or '-'}<br>"
                f"Portas: {c.get('used_ports', 0)}/{c.get('capacity', 0)}<br>"
                f"Status: {health_status}<br>"
                f"Endereço: {c.get('address') or '-'}]]>")
            ET.SubElement(pm, f"{{{KML_NS}}}styleUrl").text = (
                f"#cto_{health_status}")
            # ExtendedData (round-trip de metadados)
            ext = ET.SubElement(pm, f"{{{KML_NS}}}ExtendedData")
            for k, v in {
                "smartprov_type": "cto",
                "smartprov_id": c.get("id"),
                "sigla": c.get("sigla"),
                "vlan": c.get("vlan"),
                "capacity": c.get("capacity"),
                "network_type": c.get("network_type"),
            }.items():
                if v is None:
                    continue
                d = ET.SubElement(ext, f"{{{KML_NS}}}Data", name=k)
                ET.SubElement(d, f"{{{KML_NS}}}value").text = str(v)
            point = ET.SubElement(pm, f"{{{KML_NS}}}Point")
            ET.SubElement(point, f"{{{KML_NS}}}coordinates").text = (
                f"{lng},{lat},0")

    # Folder CEs
    if ces:
        folder = ET.SubElement(doc, f"{{{KML_NS}}}Folder")
        ET.SubElement(folder, f"{{{KML_NS}}}name").text = "CEs"
        for c in ces:
            lat = c.get("lat")
            lng = c.get("lng")
            if lat is None or lng is None:
                continue
            pm = ET.SubElement(folder, f"{{{KML_NS}}}Placemark")
            ET.SubElement(pm, f"{{{KML_NS}}}name").text = (
                c.get("name") or c.get("sigla") or "CE")
            ET.SubElement(pm, f"{{{KML_NS}}}description").text = (
                f"<![CDATA[<b>CE {c.get('name') or ''}</b><br>"
                f"Endereço: {c.get('address') or '-'}]]>")
            ET.SubElement(pm, f"{{{KML_NS}}}styleUrl").text = "#ce_style"
            ext = ET.SubElement(pm, f"{{{KML_NS}}}ExtendedData")
            for k, v in {
                "smartprov_type": "ce",
                "smartprov_id": c.get("id"),
            }.items():
                if v is None:
                    continue
                d = ET.SubElement(ext, f"{{{KML_NS}}}Data", name=k)
                ET.SubElement(d, f"{{{KML_NS}}}value").text = str(v)
            point = ET.SubElement(pm, f"{{{KML_NS}}}Point")
            ET.SubElement(point, f"{{{KML_NS}}}coordinates").text = (
                f"{lng},{lat},0")

    # Folder Cabos
    if cables:
        folder = ET.SubElement(doc, f"{{{KML_NS}}}Folder")
        ET.SubElement(folder, f"{{{KML_NS}}}name").text = "Cabos"
        for cab in cables:
            segs = cab.get("segments") or []
            if len(segs) < 2:
                continue
            ctype = cab.get("type") or "drop"
            pm = ET.SubElement(folder, f"{{{KML_NS}}}Placemark")
            ET.SubElement(pm, f"{{{KML_NS}}}name").text = (
                f"Cabo {ctype.upper()}")
            ET.SubElement(pm, f"{{{KML_NS}}}description").text = (
                f"<![CDATA[<b>{ctype.upper()}</b> · "
                f"{cab.get('fo_count', 0)} FO<br>"
                f"Comprimento: {cab.get('length_m', 0):.0f}m]]>")
            ET.SubElement(pm, f"{{{KML_NS}}}styleUrl").text = (
                f"#cable_{ctype}")
            ext = ET.SubElement(pm, f"{{{KML_NS}}}ExtendedData")
            for k, v in {
                "smartprov_type": "cable",
                "smartprov_id": cab.get("id"),
                "cable_type": ctype,
                "fo_count": cab.get("fo_count"),
                "length_m": cab.get("length_m"),
                "from_type": cab.get("from_type"),
                "from_id": cab.get("from_id"),
                "to_type": cab.get("to_type"),
                "to_id": cab.get("to_id"),
            }.items():
                if v is None:
                    continue
                d = ET.SubElement(ext, f"{{{KML_NS}}}Data", name=k)
                ET.SubElement(d, f"{{{KML_NS}}}value").text = str(v)
            line = ET.SubElement(pm, f"{{{KML_NS}}}LineString")
            ET.SubElement(line, f"{{{KML_NS}}}tessellate").text = "1"
            coords_str = " ".join(
                f"{s['lng']},{s['lat']},0" for s in segs)
            ET.SubElement(line, f"{{{KML_NS}}}coordinates").text = coords_str

    return ET.tostring(kml, encoding="unicode", xml_declaration=True)


@router.get("/export-kmz")
async def export_kmz(
    vlan: Optional[int] = Query(default=None,
                                description="Se informado, exporta só elementos "
                                "dessa VLAN."),
    user: dict = Depends(get_current_user),
):
    """Baixa toda a topologia de rede como arquivo KMZ."""
    cid = _cid(user)

    # CTOs (somente approved e pending_validation)
    q_cto: Dict[str, Any] = {
        "company_id": cid,
        "status": {"$in": ["approved", "pending_validation"]},
    }
    if vlan is not None:
        q_cto["vlan"] = vlan
    ctos_raw = await db.ctos.find(q_cto, {"_id": 0}).to_list(2000)
    ctos: List[dict] = []
    for c in ctos_raw:
        gps = c.get("gps") or {}
        lat, lng = gps.get("lat"), gps.get("lng")
        if lat is None or lng is None:
            continue
        used = len([p for p in (c.get("ports") or [])
                    if p.get("status") == "used"])
        # Health rápida: critico se >85%, warning >70%, ok caso contrário
        cap = c.get("capacity") or 0
        pct = (used / cap * 100) if cap else 0
        if cap == 0:
            status = "no_data"
        elif pct > 85:
            status = "critical"
        elif pct > 70:
            status = "warning"
        else:
            status = "ok"
        ctos.append({
            "id": c.get("id"), "sigla": c.get("sigla"),
            "name": c.get("name"), "lat": lat, "lng": lng,
            "vlan": c.get("vlan"), "capacity": cap, "used_ports": used,
            "address": c.get("address"),
            "network_type": c.get("network_type"),
            "health": {"status": status},
        })

    # CEs
    ces = await db.network_ces.find({"company_id": cid},
                                     {"_id": 0}).to_list(500)

    # Cabos
    cables = await db.network_cables.find({"company_id": cid},
                                           {"_id": 0}).to_list(2000)

    # Empresa
    co = await db.companies.find_one({"id": cid}, {"_id": 0, "name": 1})
    co_name = (co or {}).get("name") or "SmartProv"

    # Monta KML
    kml_str = _build_kml(ctos, ces, cables, co_name)

    # Compacta em KMZ (ZIP com doc.kml)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w",
                          compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_str)
    buf.seek(0)

    fname_safe = (co_name or "smartprov").replace(" ", "_").lower()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"smartprov-topologia-{fname_safe}-{stamp}.kmz"

    return StreamingResponse(
        buf,
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# IMPORT
# ---------------------------------------------------------------------------
def _parse_coordinates(text: str) -> List[tuple[float, float]]:
    """Parseia o texto de <coordinates>. Cada token: 'lng,lat[,alt]'."""
    out: List[tuple[float, float]] = []
    if not text:
        return out
    for token in text.replace("\n", " ").replace("\t", " ").split():
        parts = token.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            lng = float(parts[0])
            lat = float(parts[1])
            out.append((lat, lng))
        except (ValueError, IndexError):
            continue
    return out


def _ext_data(pm: ET.Element) -> Dict[str, str]:
    """Extrai ExtendedData/Data name=value de um Placemark."""
    out: Dict[str, str] = {}
    for ed in pm.findall(".//kml:ExtendedData/kml:Data", NS):
        name = ed.attrib.get("name", "")
        val_el = ed.find("kml:value", NS)
        if name and val_el is not None and val_el.text is not None:
            out[name] = val_el.text.strip()
    return out


def _detect_folder_name(_pm: ET.Element) -> str:
    """Retorna o nome do Folder pai (ou string vazia)."""
    # ElementTree não tem getparent — folder_name é resolvido em
    # _import_placemark via varredura externa (vide import_kmz).
    return ""


def _classify_placemark(pm: ET.Element, folder_name: str) -> str:
    """Decide se um Placemark é cto/ce/cable usando ExtendedData,
    nome do folder pai e/ou geometria.

    Retorna: "cto" | "ce" | "cable" | "ignore"
    """
    ext = _ext_data(pm)
    if ext.get("smartprov_type") in ("cto", "ce", "cable"):
        return ext["smartprov_type"]
    fn = (folder_name or "").lower()
    has_point = pm.find(".//kml:Point", NS) is not None
    has_line = pm.find(".//kml:LineString", NS) is not None
    if "cto" in fn and has_point:
        return "cto"
    if "ce" in fn and has_point:
        return "ce"
    if ("cabo" in fn or "cable" in fn) and has_line:
        return "cable"
    # Fallback: ponto isolado → cto; linha → cabo drop
    if has_point:
        return "cto"
    if has_line:
        return "cable"
    return "ignore"


@router.post("/import-kmz")
async def import_kmz(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False,
                           description="Se true, retorna o que seria importado "
                           "sem persistir nada."),
    user: dict = Depends(get_current_user),
):
    """Importa CTOs, CEs e Cabos a partir de KMZ/KML.

    - Aceita .kmz (ZIP com doc.kml) ou .kml direto.
    - Para CTOs/CEs já existentes (mesmo `smartprov_id`), faz UPDATE de
      posição. Sem ID, cria novo.
    - Os Placemarks são classificados por (1) ExtendedData/smartprov_type,
      (2) nome do Folder pai, (3) tipo de geometria.
    """
    cid = _cid(user)
    role = (user.get("role") or "").lower()
    if (role not in ("gestor", "administrador") and not is_super_admin(user)):
        raise HTTPException(403, "Apenas gestor/administrador pode importar.")

    # Lê o arquivo
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")
    # Aceita .kmz (ZIP) ou .kml puro
    fname = (file.filename or "").lower()
    kml_bytes: Optional[bytes] = None
    if fname.endswith(".kmz") or raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                # Acha o primeiro .kml dentro (geralmente doc.kml)
                kml_name = next(
                    (n for n in zf.namelist() if n.lower().endswith(".kml")),
                    None,
                )
                if not kml_name:
                    raise HTTPException(400, "KMZ não contém .kml interno.")
                kml_bytes = zf.read(kml_name)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Arquivo KMZ inválido (ZIP corrompido).")
    else:
        kml_bytes = raw

    # Parseia XML (defusedxml — bloqueia XXE/entity expansion/DTD)
    try:
        root = DET.fromstring(kml_bytes)
    except ET.ParseError as e:
        raise HTTPException(400, safe_detail(400, e, "KML inválido:"))

    # Itera Folders e Placemarks
    summary = {
        "ctos_created": 0, "ctos_updated": 0,
        "ces_created": 0, "ces_updated": 0,
        "cables_created": 0, "cables_updated": 0,
        "ignored": 0,
        "errors": [],
    }

    # Pra cada Folder, processa seus Placemarks com folder_name
    folders = root.findall(".//kml:Folder", NS)
    seen_pms = set()
    for folder in folders:
        fname_el = folder.find("kml:name", NS)
        folder_name = fname_el.text if fname_el is not None else ""
        for pm in folder.findall("kml:Placemark", NS):
            seen_pms.add(id(pm))
            await _import_placemark(pm, folder_name, cid, user, summary,
                                     dry_run)
    # Placemarks soltos (fora de Folder)
    for pm in root.findall(".//kml:Placemark", NS):
        if id(pm) in seen_pms:
            continue
        await _import_placemark(pm, "", cid, user, summary, dry_run)

    return {
        "ok": True,
        "dry_run": dry_run,
        "filename": file.filename,
        **summary,
    }


async def _import_placemark(pm: ET.Element, folder_name: str,
                            company_id: str, user: dict,
                            summary: Dict[str, Any],
                            dry_run: bool) -> None:
    """Processa um único Placemark e atualiza `summary`."""
    try:
        kind = _classify_placemark(pm, folder_name)
        if kind == "ignore":
            summary["ignored"] += 1
            return
        ext = _ext_data(pm)
        name_el = pm.find("kml:name", NS)
        name = (name_el.text if name_el is not None else "") or ""
        if kind in ("cto", "ce"):
            pt_el = pm.find(".//kml:Point/kml:coordinates", NS)
            if pt_el is None or not pt_el.text:
                summary["ignored"] += 1
                return
            coords = _parse_coordinates(pt_el.text)
            if not coords:
                summary["ignored"] += 1
                return
            lat, lng = coords[0]
            existing_id = ext.get("smartprov_id")
            if kind == "cto":
                if existing_id and not dry_run:
                    r = await db.ctos.update_one(
                        {"company_id": company_id, "id": existing_id},
                        {"$set": {
                            "gps": {"lat": lat, "lng": lng},
                            "name": name or existing_id,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    if r.matched_count:
                        summary["ctos_updated"] += 1
                        return
                # criar nova
                new_id = f"cto-{uuid.uuid4().hex[:10]}"
                if not dry_run:
                    await db.ctos.insert_one({
                        "id": new_id,
                        "company_id": company_id,
                        "name": name or "CTO importada",
                        "sigla": ext.get("sigla") or name[:8],
                        "vlan": int(ext["vlan"]) if ext.get("vlan", "").isdigit() else None,
                        "capacity": int(ext["capacity"]) if ext.get(
                            "capacity", "").isdigit() else 16,
                        "gps": {"lat": lat, "lng": lng},
                        "status": "approved",
                        "network_type": ext.get("network_type") or "gpon",
                        "ports": [],
                        "imported_from_kmz": True,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    # iter183 — Sync Base de Portas (KMZ import)
                    try:
                        from routes.cto_ports_base import sync_cto_all_ports
                        await sync_cto_all_ports(company_id, new_id)
                    except Exception:
                        pass
                summary["ctos_created"] += 1
            else:  # ce
                if existing_id and not dry_run:
                    r = await db.network_ces.update_one(
                        {"company_id": company_id, "id": existing_id},
                        {"$set": {"lat": lat, "lng": lng,
                                   "name": name or existing_id}},
                    )
                    if r.matched_count:
                        summary["ces_updated"] += 1
                        return
                new_id = f"ce-{uuid.uuid4().hex[:10]}"
                if not dry_run:
                    await db.network_ces.insert_one({
                        "id": new_id,
                        "company_id": company_id,
                        "name": name or "CE importado",
                        "lat": lat, "lng": lng,
                        "imported_from_kmz": True,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                summary["ces_created"] += 1

        elif kind == "cable":
            ls_el = pm.find(".//kml:LineString/kml:coordinates", NS)
            if ls_el is None or not ls_el.text:
                summary["ignored"] += 1
                return
            coords = _parse_coordinates(ls_el.text)
            if len(coords) < 2:
                summary["ignored"] += 1
                return
            segments = [{"lat": lat, "lng": lng} for lat, lng in coords]
            ctype = ext.get("cable_type") or "drop"
            # Normaliza tipo
            if ctype not in CABLE_KML_COLORS:
                ctype = "drop"
            existing_id = ext.get("smartprov_id")
            if existing_id and not dry_run:
                r = await db.network_cables.update_one(
                    {"company_id": company_id, "id": existing_id},
                    {"$set": {"segments": segments,
                              "type": ctype,
                              "updated_at": datetime.now(timezone.utc).isoformat()}},
                )
                if r.matched_count:
                    summary["cables_updated"] += 1
                    return
            new_id = f"cab-{uuid.uuid4().hex[:10]}"
            if not dry_run:
                # Calcula length aproximado em metros (haversine)
                length_m = 0.0
                for i in range(len(coords) - 1):
                    length_m += _haversine_m(coords[i], coords[i + 1])
                await db.network_cables.insert_one({
                    "id": new_id,
                    "company_id": company_id,
                    "type": ctype,
                    "fo_count": int(ext["fo_count"]) if ext.get(
                        "fo_count", "").isdigit() else _default_fo(ctype),
                    "segments": segments,
                    "length_m": length_m,
                    "imported_from_kmz": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "created_by": user.get("email") or user.get("name"),
                })
            summary["cables_created"] += 1
    except Exception as e:
        logger.warning("[kmz import] placemark err: %s", e)
        summary["errors"].append(str(e)[:200])


def _default_fo(cable_type: str) -> int:
    return {"drop": 2, "6fo": 6, "12fo": 12,
            "24fo": 24, "48fo": 48, "96fo": 96}.get(cable_type, 2)


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distância em metros entre 2 coords (lat, lng)."""
    import math
    R = 6371000.0
    lat1, lng1 = a
    lat2, lng2 = b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))
