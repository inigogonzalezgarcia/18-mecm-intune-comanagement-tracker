"""Fictional estate for the demo: 260 Windows devices of a made-up company (contoso.example)
in the middle of a Windows 11 migration with co-management. No real tenant or site data.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import expected_authority
from .model import WORKLOADS, Gates, Plan, Wave

DEMO_NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)

PLAN = {
    "pilot_collection": "CM - Co-management Pilot",
    "workloads": {
        "compliancePolicy": "intune",
        "resourceAccess": "intune",
        "deviceConfiguration": "pilot",
        "windowsUpdateForBusiness": "pilot",
        "modernApps": "pilot",
        "endpointProtection": "configmgr",
        "officeApps": "configmgr",
    },
    "waves": [
        {"name": "Wave 0 · IT pilot", "collection": "W11 - Wave 0 Pilot", "target": "2026-10-02"},
        {"name": "Wave 1 · Finance and Operations", "collection": "W11 - Wave 1", "target": "2026-10-30"},
        {"name": "Wave 2 · Rest of the office", "collection": "W11 - Wave 2", "target": "2026-11-27"},
    ],
    "gates": {"min_comanaged_pct": 95.0, "min_client_healthy_pct": 95.0,
              "min_pilot_compliant_pct": 90.0, "max_pilot_mismatch_pct": 2.0},
    "stale_days": 14,
    "win11_target_build": 22631,
}

# (wave index, devices, share already on Windows 11)
WAVES = [(0, 25, 1.0), (1, 95, 0.62), (2, 140, 0.12)]


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def write_demo(folder: Path, now: datetime = DEMO_NOW, seed: int = 18) -> dict[str, Path]:
    rng = random.Random(seed)
    folder.mkdir(parents=True, exist_ok=True)
    plan = Plan(PLAN["pilot_collection"], PLAN["workloads"], [Wave(**w) for w in PLAN["waves"]], Gates(**PLAN["gates"]))
    mecm_rows, intune = [], []
    n = 0
    for wave, count, w11_share in WAVES:
        for j in range(count):
            n += 1
            name = f"CTS-{'LT' if rng.random() < 0.8 else 'DT'}-{n:04d}"
            collections = ["All Windows Workstations", "CM - Co-management", PLAN["waves"][wave]["collection"]]
            in_pilot = wave == 0 or (wave == 1 and j < 10)
            if in_pilot:
                collections.append(PLAN["pilot_collection"])
            win11 = rng.random() < w11_share
            build = rng.choice([22631, 22631, 26100]) if win11 else 19045
            hw_ready = True if win11 else rng.random() > 0.09

            client, active = True, True
            last_policy = now - timedelta(hours=rng.randint(1, 30))
            enrolled, agent = True, "configurationManagerClientMdm"
            compliance = "compliant" if rng.random() > 0.04 else "noncompliant"
            last_sync = now - timedelta(hours=rng.randint(1, 40))
            mismatch = None

            roll = rng.random()
            if wave > 0 and roll < 0.05:
                enrolled = False                                   # auto-enrolment did not happen
            elif roll < 0.065:
                agent = "mdm"                                      # enrolled by the user, outside co-management
            elif roll < 0.095:
                active, last_policy = False, now - timedelta(days=rng.randint(20, 60))
            elif roll < 0.12:
                last_sync = now - timedelta(days=rng.randint(16, 45))
            if n in (3, 141, 222):
                client = False
            if in_pilot and n == 7:
                mismatch = "deviceConfiguration"                   # pilot device that has not picked up the change

            mecm_rows.append({
                "name": name, "resource_id": str(16777000 + n), "client": int(client), "client_active": int(active and client),
                "last_policy_request": _iso(last_policy) if client else "", "os_build": build,
                "win11_hw_ready": "" if win11 else int(hw_ready), "collections": ";".join(collections),
            })
            if enrolled and client:
                feats = {w: expected_authority(plan, in_pilot, w) == "Intune" for w in WORKLOADS}
                if agent != "configurationManagerClientMdm":
                    feats = {w: False for w in WORKLOADS}
                if mismatch:
                    feats[mismatch] = not feats[mismatch]
                intune.append({
                    "id": f"00000000-0000-4000-9000-{n:012d}", "deviceName": name, "operatingSystem": "Windows",
                    "osVersion": f"10.0.{build}.{rng.randint(4000, 4400) if build != 19045 else 5011}",
                    "managementAgent": agent, "complianceState": compliance, "lastSyncDateTime": _iso(last_sync),
                    "serialNumber": f"DEMO{n:06d}", "configurationManagerClientEnabledFeatures": feats,
                })

    # New laptops provisioned with Autopilot, cloud-only: they never get an MECM client
    for k in range(1, 5):
        intune.append({"id": f"00000000-0000-4000-9100-{k:012d}", "deviceName": f"CTS-AP-{k:04d}", "operatingSystem": "Windows",
                       "osVersion": "10.0.26100.4202", "managementAgent": "mdm", "complianceState": "compliant",
                       "lastSyncDateTime": _iso(now - timedelta(hours=k)), "serialNumber": f"DEMOAP{k:04d}",
                       "configurationManagerClientEnabledFeatures": None})
    # A stale duplicate left behind by a re-enrolment: the loader keeps the newest record
    dup = dict(intune[30])
    dup.update(id="00000000-0000-4000-9200-000000000001", lastSyncDateTime=_iso(now - timedelta(days=90)),
               complianceState="noncompliant")
    intune.append(dup)
    # A phone, to show that non-Windows records are ignored
    intune.append({"id": "00000000-0000-4000-9300-000000000001", "deviceName": "iPhone de demo", "operatingSystem": "iOS",
                   "managementAgent": "mdm", "complianceState": "compliant", "lastSyncDateTime": _iso(now)})

    paths = {"mecm": folder / "mecm_devices.csv", "intune": folder / "intune_devices.json", "plan": folder / "plan.json"}
    with open(paths["mecm"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(mecm_rows[0]))
        w.writeheader()
        w.writerows(mecm_rows)
    paths["intune"].write_text(json.dumps({"value": intune}, indent=1), encoding="utf-8")
    paths["plan"].write_text(json.dumps(PLAN, indent=2, ensure_ascii=False), encoding="utf-8")
    return paths
