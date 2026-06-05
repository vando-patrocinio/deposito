"""
tk103_parser.py — Parser do protocolo TK103 (e variantes TK303).

Frame típico:
  *HQ,<IMEI>,V1,<hhmmss>,<A|V>,<lat>,<N|S>,<lng>,<E|W>,<speed_kmh>,<heading>,<ddmmyy>,<status_hex>#

Exemplo real:
  *HQ,1234567890,V1,123456,A,2334.1234,S,04612.5678,W,015.0,180,010326,FFFFFBFF#

Campos:
  - IMEI       : 15 dígitos (alguns têm 10 — aceitamos)
  - V1         : tipo de mensagem (V1 = GPS position; pode ser XT/V4/etc)
  - hhmmss     : hora UTC
  - A | V      : fix válido (A) ou inválido (V)
  - lat ddmm.mmmm + N/S
  - lng dddmm.mmmm + E/W
  - speed em knots (depende do firmware) — para TK103 a maioria já manda km/h
  - heading 0-359
  - ddmmyy
  - status_hex : flags (ACC, GPS, alarme, etc) — bitmap

Saída: dict pronto pra POST em /api/fleet-tracking/ingest
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional


# Regex permissiva — alguns trackers enviam campos extras
TK103_RE = re.compile(
    r"^\*[A-Z]{2,3},"           # *HQ,
    r"(?P<imei>\d{10,16}),"
    r"(?P<msg>[A-Z0-9]+),"
    r"(?P<hms>\d{6}),"
    r"(?P<valid>[AV]),"
    r"(?P<lat>\d+\.\d+),"
    r"(?P<lat_dir>[NS]),"
    r"(?P<lng>\d+\.\d+),"
    r"(?P<lng_dir>[EW]),"
    r"(?P<speed>\d+\.?\d*),"
    r"(?P<heading>\d+\.?\d*),"
    r"(?P<dmy>\d{6}),"
    r"(?P<status>[0-9A-F]+)"
    r".*#$"
)


def _ddmm_to_decimal(value: str, direction: str) -> float:
    """Converte 'ddmm.mmmm' (NMEA) para decimal."""
    if not value:
        return 0.0
    # Para latitude: 2 dígitos de grau; para longitude: 3 dígitos
    # Heurística: ponto está depois dos 2 últimos dígitos antes do '.'
    dot = value.find(".")
    if dot < 3:
        return 0.0
    minutes_start = dot - 2
    degrees = float(value[:minutes_start])
    minutes = float(value[minutes_start:])
    dec = degrees + (minutes / 60.0)
    if direction in ("S", "W"):
        dec = -dec
    return dec


def parse_frame(raw: str) -> Optional[dict]:
    """Retorna dict pronto pra ingest, ou None se inválido."""
    raw = raw.strip()
    if not raw or not raw.endswith("#"):
        return None
    m = TK103_RE.match(raw)
    if not m:
        return None
    lat = _ddmm_to_decimal(m["lat"], m["lat_dir"])
    lng = _ddmm_to_decimal(m["lng"], m["lng_dir"])
    # Date/time UTC
    try:
        hms = m["hms"]
        dmy = m["dmy"]
        dt = datetime.strptime(dmy + hms, "%d%m%y%H%M%S").replace(
            tzinfo=timezone.utc)
        ts_iso = dt.isoformat()
    except ValueError:
        ts_iso = datetime.now(timezone.utc).isoformat()
    # Velocidade: alguns trackers mandam em knots; converter se necessário.
    # Heurística: se status contém 'KM' considera km/h; senão assume km/h por
    # padrão pra TK103 brasileiro (o firmware comum aqui já vem assim).
    speed_kmh = float(m["speed"])

    # ACC (ignition) está nos bits do status (depende do firmware).
    # Aproximação: bit 0 (LSB) = ACC. Se o status for múltiplo de 2, ACC=off.
    ignition = None
    try:
        status_int = int(m["status"], 16)
        ignition = bool(status_int & 0x01)
    except (ValueError, TypeError):
        pass

    return {
        "imei": m["imei"],
        "lat": lat,
        "lng": lng,
        "speed_kmh": speed_kmh,
        "heading": float(m["heading"]),
        "ignition": ignition,
        "fix_valid": m["valid"] == "A",
        "sats": 0,
        "timestamp": ts_iso,
        "raw": raw,
    }


# ─── Encoder de comandos remotos ────────────────────────────────────
def build_command(kind: str, password: str = "123456",
                   payload: Optional[dict] = None) -> Optional[str]:
    """Monta string a ser enviada via TCP/SMS ao tracker."""
    payload = payload or {}
    if kind == "block":
        return f"RELAY,1{password}#"
    if kind == "unblock":
        return f"RELAY,0{password}#"
    if kind == "locate_now":
        return "WHERE#"
    if kind == "audio_listen":
        phone = payload.get("phone", "")
        return f"MONITOR{phone}#"  # alguns firmwares
    if kind == "set_speed_limit":
        limit = int(payload.get("speed_kmh", 80))
        return f"SPEED{limit}{password}#"
    if kind == "reset":
        return f"RESET{password}#"
    return None
