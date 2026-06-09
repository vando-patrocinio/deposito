"""vsol_snmp.py — Poller SNMP direto para OLTs V-SOL (Realtek-based).

V-SOL/Chima usa o chipset Realtek e expõe o GPON-ONU-MIB via OIDs sob
`1.3.6.1.4.1.5875.800.3.10` (enterprises.realtek.gpon.onu).

OIDs principais (validados nas séries V1600/V2700/V3000/V SOL XPON):
  - 1.3.6.1.4.1.5875.800.3.10.1.1.10  ONU SN (string hex)
  - 1.3.6.1.4.1.5875.800.3.10.1.1.11  ONU MAC
  - 1.3.6.1.4.1.5875.800.3.10.1.1.12  ONU description/alias
  - 1.3.6.1.4.1.5875.800.3.10.1.1.30  ONU RX power (0.1 dBm)
  - 1.3.6.1.4.1.5875.800.3.10.1.1.31  ONU TX power (0.1 dBm)
  - 1.3.6.1.4.1.5875.800.3.10.1.1.50  ONU run status (1=online, 2=offline,
                                       3=LOS, 4=power-down)
  - 1.3.6.1.4.1.5875.800.3.10.1.1.60  ONU distance (m)

Como o instance OID encoda PON+slot+port+onuId, parseamos a tail do OID
para descobrir hierarquia.

Uso:
    from services.vsol_snmp import VsolSnmpPoller
    poller = VsolSnmpPoller(host="10.0.0.1", community="public")
    res = await poller.discover_onus()
    # res = {"onu_count": N, "onus": [{"sn":..., "mac":..., "rx":..., "tx":..., "status":...}, ...]}
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, walk_cmd,
)

logger = logging.getLogger(__name__)

# OIDs base (V-SOL/Realtek)
OID_BASE = "1.3.6.1.4.1.5875.800.3.10.1.1"
OIDS = {
    "sn": f"{OID_BASE}.10",
    "mac": f"{OID_BASE}.11",
    "alias": f"{OID_BASE}.12",
    "rx_power": f"{OID_BASE}.30",
    "tx_power": f"{OID_BASE}.31",
    "status": f"{OID_BASE}.50",
    "distance": f"{OID_BASE}.60",
}

STATUS_MAP = {
    1: "online",
    2: "offline",
    3: "los",
    4: "power-down",
    5: "dying-gasp",
}


def _decimal_dbm(raw_val) -> Optional[float]:
    """V-SOL retorna potência em 0.1 dBm (signed int).
    Ex: -257 = -25.7 dBm; valor 0 ou 1000 = inválido/desligado."""
    try:
        v = int(raw_val)
    except (TypeError, ValueError):
        return None
    if v in (0, 1000, -1000, 65535):
        return None
    return round(v / 10.0, 1)


def _decode_mac(raw) -> Optional[str]:
    """MAC vem como OctetString (6 bytes) ou string. Normaliza p/ AA:BB:..."""
    if raw is None:
        return None
    try:
        if hasattr(raw, "asOctets"):
            b = raw.asOctets()
        else:
            b = bytes(raw)
        if len(b) >= 6:
            return ":".join(f"{x:02X}" for x in b[:6])
    except Exception:
        pass
    return str(raw)


def _decode_sn(raw) -> Optional[str]:
    """SN VSOL = 4 bytes ASCII (vendor) + 4 bytes hex (serial)."""
    if raw is None:
        return None
    try:
        if hasattr(raw, "asOctets"):
            b = raw.asOctets()
        else:
            b = bytes(raw)
        if len(b) >= 8:
            vendor = b[:4].decode("ascii", errors="replace")
            serial = b[4:8].hex().upper()
            return f"{vendor}{serial}"
    except Exception:
        pass
    return str(raw)


class VsolSnmpPoller:
    def __init__(self, host: str, community: str = "public",
                 port: int = 161, version: str = "v2c",
                 timeout: float = 5.0, retries: int = 1):
        self.host = host
        self.community = community
        self.port = port
        self.version = version  # "v1" | "v2c" (v3 fica para próxima)
        self.timeout = timeout
        self.retries = retries

    async def _walk(self, oid: str,
                     max_rows: int = 5000) -> List[tuple]:
        """SNMP walk genérico. Retorna lista [(instance_suffix, value), ...]"""
        engine = SnmpEngine()
        mp_model = 0 if self.version == "v1" else 1  # v2c=1
        community = CommunityData(self.community, mpModel=mp_model)
        transport = await UdpTransportTarget.create(
            (self.host, self.port), timeout=self.timeout,
            retries=self.retries)
        ctx = ContextData()
        results: List[tuple] = []
        base_oid = ObjectIdentity(oid)
        async for (errInd, errStatus, errIdx, varBinds) in walk_cmd(
                engine, community, transport, ctx,
                ObjectType(base_oid),
                lexicographicMode=False, maxRows=max_rows):
            if errInd:
                logger.warning("[vsol-snmp] %s walk %s: %s",
                                self.host, oid, errInd)
                break
            if errStatus:
                logger.warning("[vsol-snmp] %s walk %s status %s",
                                self.host, oid, errStatus)
                break
            for vb in varBinds:
                key = str(vb[0])
                if not key.startswith(oid):
                    return results
                suffix = key[len(oid) + 1:]  # tira "oid."
                results.append((suffix, vb[1]))
        engine.close_dispatcher()
        return results

    async def ping(self) -> Dict[str, Any]:
        """Conectividade básica via sysDescr."""
        try:
            r = await self._walk("1.3.6.1.2.1.1.1", max_rows=1)
            if r:
                return {"ok": True, "sys_descr": str(r[0][1])[:200]}
            return {"ok": False, "error": "sem resposta sysDescr"}
        except Exception as e:
            return {"ok": False, "error": repr(e)[:200]}

    async def discover_onus(self) -> Dict[str, Any]:
        """Polla os 7 OIDs em paralelo e cruza por instance suffix."""
        coros = {field: self._walk(o) for field, o in OIDS.items()}
        keys = list(coros.keys())
        vals = await asyncio.gather(*coros.values(),
                                       return_exceptions=True)
        bundles: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}
        for field, val in zip(keys, vals):
            if isinstance(val, Exception):
                errors[field] = repr(val)[:120]
                continue
            for suffix, raw in val:
                slot = bundles.setdefault(suffix, {"_oid_suffix": suffix})
                if field == "sn":
                    slot["sn"] = _decode_sn(raw)
                elif field == "mac":
                    slot["mac"] = _decode_mac(raw)
                elif field == "alias":
                    slot["alias"] = str(raw) if raw else None
                elif field == "rx_power":
                    slot["signal_rx_dbm"] = _decimal_dbm(raw)
                elif field == "tx_power":
                    slot["signal_tx_dbm"] = _decimal_dbm(raw)
                elif field == "status":
                    try:
                        slot["status"] = STATUS_MAP.get(
                            int(raw), f"unknown({raw})")
                    except Exception:
                        slot["status"] = str(raw)
                elif field == "distance":
                    try:
                        slot["distance_m"] = int(raw)
                    except Exception:
                        pass
        # Decodifica suffix -> pon/slot/port/onu (heurística V-SOL:
        # suffix tipicamente: slot.port.onuId)
        for suffix, slot in bundles.items():
            parts = suffix.split(".")
            if len(parts) >= 3:
                slot["slot"] = parts[-3]
                slot["port"] = parts[-2]
                slot["onu_id"] = parts[-1]
            slot["host"] = (f"ONU-{slot.get('slot','?')}/{slot.get('port','?')}/"
                              f"{slot.get('onu_id','?')}")
        return {
            "host": self.host,
            "community": "***",
            "onu_count": len(bundles),
            "onus": list(bundles.values()),
            "errors": errors or None,
        }
