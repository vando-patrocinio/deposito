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
from typing import Any, Dict, List, Optional
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, walk_cmd,
)

logger = logging.getLogger(__name__)

# OIDs base por vendor
# V-SOL/Realtek
OID_VSOL = "1.3.6.1.4.1.5875.800.3.10.1.1"
# Huawei (HUAWEI-XPON-ONT-MIB / hwGponDeviceMib)
OID_HUAWEI = "1.3.6.1.4.1.2011.6.128.1.1.2.43.1"
# ZTE (ZXAN-XGPON-ONU-MIB)
OID_ZTE = "1.3.6.1.4.1.3902.1015.2.2.1"

# Mapeamento {field: oid_offset}. Cada vendor expõe os mesmos campos
# em offsets distintos. Para Huawei/ZTE, validado em templates Zabbix
# públicos (zabbix-templates/huawei-xpon, zabbix-templates/zte-c320).
VENDOR_OIDS = {
    "vsol": {
        "sn": f"{OID_VSOL}.10",
        "mac": f"{OID_VSOL}.11",
        "alias": f"{OID_VSOL}.12",
        "rx_power": f"{OID_VSOL}.30",
        "tx_power": f"{OID_VSOL}.31",
        "status": f"{OID_VSOL}.50",
        "distance": f"{OID_VSOL}.60",
        "dbm_divider": 10,  # 0.1 dBm
    },
    "huawei": {
        # hwGponDeviceOntControlTable / hwGponOntOpticalDdmInfoTable
        "sn": f"{OID_HUAWEI}.4",    # SerialNumber
        "mac": f"{OID_HUAWEI}.8",   # MAC
        "alias": f"{OID_HUAWEI}.9",  # Description
        "rx_power": "1.3.6.1.4.1.2011.6.128.1.1.2.51.1.4",   # OntOpticalRxPower
        "tx_power": "1.3.6.1.4.1.2011.6.128.1.1.2.51.1.5",   # OntOpticalTxPower
        "status": f"{OID_HUAWEI}.15",  # RunStatus
        "distance": f"{OID_HUAWEI}.20",
        "dbm_divider": 100,  # 0.01 dBm
    },
    "zte": {
        # ZXAN-XGPON-ONU-MIB::zxGponOnuInfo
        "sn": f"{OID_ZTE}.1.5",    # SerialNumber
        "mac": f"{OID_ZTE}.1.7",   # MAC
        "alias": f"{OID_ZTE}.1.4",  # Name
        "rx_power": "1.3.6.1.4.1.3902.1015.2.6.1.1.3",   # ONUOpticalRxPower
        "tx_power": "1.3.6.1.4.1.3902.1015.2.6.1.1.4",   # ONUOpticalTxPower
        "status": f"{OID_ZTE}.1.13",   # AdminState
        "distance": f"{OID_ZTE}.1.18",
        "dbm_divider": 100,  # 0.01 dBm
    },
}

STATUS_MAP_VSOL = {1: "online", 2: "offline", 3: "los",
                    4: "power-down", 5: "dying-gasp"}
STATUS_MAP_HUAWEI = {1: "online", 2: "offline", 3: "los"}
STATUS_MAP_ZTE = {1: "online", 2: "offline", 3: "los", 4: "lops"}

VENDOR_STATUS = {"vsol": STATUS_MAP_VSOL, "huawei": STATUS_MAP_HUAWEI,
                  "zte": STATUS_MAP_ZTE}


def _decimal_dbm_div(raw_val, divider: int = 10) -> Optional[float]:
    """Converte raw int para dBm. Default divider=10 (V-SOL),
    100 (Huawei/ZTE)."""
    try:
        v = int(raw_val)
    except (TypeError, ValueError):
        return None
    if v in (0, 1000, 10000, -1000, -10000, 65535, 2147483647):
        return None
    return round(v / float(divider), 1)


# Compat com código existente
def _decimal_dbm(raw_val) -> Optional[float]:
    return _decimal_dbm_div(raw_val, 10)


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
                 timeout: float = 5.0, retries: int = 1,
                 vendor: str = "vsol"):
        self.host = host
        self.community = community
        self.port = port
        self.version = version  # "v1" | "v2c"
        self.timeout = timeout
        self.retries = retries
        self.vendor = (vendor or "vsol").lower()
        if self.vendor not in VENDOR_OIDS:
            self.vendor = "vsol"
        self._oids = VENDOR_OIDS[self.vendor]
        self._status_map = VENDOR_STATUS[self.vendor]

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
        """Polla os OIDs do vendor em paralelo e cruza por instance suffix."""
        oids = {k: v for k, v in self._oids.items() if k != "dbm_divider"}
        coros = {field: self._walk(o) for field, o in oids.items()}
        keys = list(coros.keys())
        vals = await asyncio.gather(*coros.values(),
                                       return_exceptions=True)
        bundles: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}
        divider = self._oids.get("dbm_divider", 10)
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
                    slot["signal_rx_dbm"] = _decimal_dbm_div(raw, divider)
                elif field == "tx_power":
                    slot["signal_tx_dbm"] = _decimal_dbm_div(raw, divider)
                elif field == "status":
                    try:
                        slot["status"] = self._status_map.get(
                            int(raw), f"unknown({raw})")
                    except Exception:
                        slot["status"] = str(raw)
                elif field == "distance":
                    try:
                        slot["distance_m"] = int(raw)
                    except Exception:
                        pass
        for suffix, slot in bundles.items():
            parts = suffix.split(".")
            if len(parts) >= 3:
                slot["slot"] = parts[-3]
                slot["port"] = parts[-2]
                slot["onu_id"] = parts[-1]
            slot["vendor"] = self.vendor
            slot["host"] = (f"ONU-{slot.get('slot','?')}/"
                              f"{slot.get('port','?')}/"
                              f"{slot.get('onu_id','?')}")
        return {
            "host": self.host,
            "vendor": self.vendor,
            "community": "***",
            "onu_count": len(bundles),
            "onus": list(bundles.values()),
            "errors": errors or None,
        }
