"""Inputs: the MECM export (CSV), the Intune export (JSON) and the plan (JSON).

MECM columns (see scripts/mecm_devices.sql):
    name, resource_id, client, client_active, last_policy_request, os_build, win11_hw_ready, collections
Intune fields follow Microsoft Graph `managedDevice` (see scripts/Export-IntuneComanagement.ps1):
    deviceName, managementAgent, complianceState, lastSyncDateTime, osVersion, serialNumber,
    configurationManagerClientEnabledFeatures
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Co-management workloads: Graph feature flag -> name used in the Configuration Manager console
WORKLOADS = {
    "compliancePolicy": "Compliance policies",
    "deviceConfiguration": "Device configuration",
    "windowsUpdateForBusiness": "Windows Update policies",
    "endpointProtection": "Endpoint Protection",
    "resourceAccess": "Resource access policies",
    "officeApps": "Office Click-to-Run apps",
    "modernApps": "Client apps",
}
SLIDER = ("configmgr", "pilot", "intune")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _bool(v) -> bool | None:
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    return None


def parse_build(value) -> int:
    """'22631', '10.0.22631' or '10.0.22631.4317' -> 22631."""
    parts = [p for p in str(value or "").strip().split(".") if p]
    part = parts[2] if len(parts) >= 3 else (parts[0] if parts else "")
    return int(part) if part.isdigit() else 0


def key(name: str) -> str:
    """Match MECM and Intune records by device name, ignoring case and a DNS suffix."""
    return name.strip().split(".")[0].upper()


@dataclass
class MecmDevice:
    name: str
    resource_id: str
    client: bool
    client_active: bool
    last_policy: datetime | None
    os_build: int
    win11_hw_ready: bool | None
    collections: list[str] = field(default_factory=list)


@dataclass
class IntuneDevice:
    name: str
    agent: str
    compliance: str
    last_sync: datetime | None
    os_version: str
    serial: str
    features: dict[str, bool] = field(default_factory=dict)

    @property
    def comanaged(self) -> bool:
        return self.agent.startswith("configurationManagerClient") and "Mdm" in self.agent


def load_mecm(path: Path) -> dict[str, MecmDevice]:
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            build = parse_build(row.get("os_build", ""))
            dev = MecmDevice(
                name=row["name"].strip(),
                resource_id=row.get("resource_id", "").strip(),
                client=bool(_bool(row.get("client", "1"))),
                client_active=bool(_bool(row.get("client_active", "0"))),
                last_policy=parse_ts(row.get("last_policy_request")),
                os_build=build,
                win11_hw_ready=_bool(row.get("win11_hw_ready", "")),
                collections=[c.strip() for c in str(row.get("collections", "")).split(";") if c.strip()],
            )
            out[key(dev.name)] = dev
    return out


def load_intune(path: Path) -> dict[str, IntuneDevice]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("value", [])
    out = {}
    for d in data:
        if str(d.get("operatingSystem", "Windows")).lower() != "windows":
            continue
        feats = d.get("configurationManagerClientEnabledFeatures") or {}
        dev = IntuneDevice(
            name=str(d.get("deviceName", "")),
            agent=str(d.get("managementAgent") or "unknown"),
            compliance=str(d.get("complianceState") or "unknown"),
            last_sync=parse_ts(d.get("lastSyncDateTime")),
            os_version=str(d.get("osVersion") or ""),
            serial=str(d.get("serialNumber") or ""),
            features={k: bool(feats.get(k)) for k in WORKLOADS},
        )
        k = key(dev.name)
        # Keep the most recent record when a device was re-enrolled and left a stale duplicate
        if k not in out or (dev.last_sync or datetime.min.replace(tzinfo=timezone.utc)) > \
                (out[k].last_sync or datetime.min.replace(tzinfo=timezone.utc)):
            out[k] = dev
    return out


@dataclass
class Wave:
    name: str
    collection: str
    target: str          # date the wave should be finished (ISO)


@dataclass
class Gates:
    min_comanaged_pct: float = 95.0
    min_client_healthy_pct: float = 95.0
    min_pilot_compliant_pct: float = 90.0
    max_pilot_mismatch_pct: float = 2.0


@dataclass
class Plan:
    pilot_collection: str
    workloads: dict[str, str]          # feature key -> configmgr / pilot / intune
    waves: list[Wave]
    gates: Gates
    stale_days: int = 14
    win11_target_build: int = 22631


def load_plan(path: Path) -> Plan:
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    workloads = {}
    for k, v in p["workloads"].items():
        if k not in WORKLOADS:
            raise ValueError(f"unknown workload '{k}', expected one of {', '.join(WORKLOADS)}")
        if v not in SLIDER:
            raise ValueError(f"workload '{k}': slider must be one of {SLIDER}, got '{v}'")
        workloads[k] = v
    return Plan(
        pilot_collection=p["pilot_collection"],
        workloads=workloads,
        waves=[Wave(**w) for w in p.get("waves", [])],
        gates=Gates(**p.get("gates", {})),
        stale_days=int(p.get("stale_days", 14)),
        win11_target_build=int(p.get("win11_target_build", 22631)),
    )
