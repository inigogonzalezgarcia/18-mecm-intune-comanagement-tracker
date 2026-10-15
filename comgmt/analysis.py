"""Join both sides, classify every device, check workload authority and evaluate the go/no-go gates."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import WORKLOADS, IntuneDevice, MecmDevice, Plan, key

# Join states
COMANAGED = "Co-managed"
MECM_ONLY = "MECM only (not enrolled)"
ENROLLED_NOT_COMGMT = "Enrolled, not co-managed"
INTUNE_ONLY = "Intune only"
NO_CLIENT = "In MECM, no client"

FIX = {
    "not_enrolled": "Check Entra hybrid join and the auto-enrolment setting in the co-management properties; "
                    "look at CoManagementHandler.log on the device.",
    "not_comanaged": "Enrolled in Intune but not through co-management: check that the device is in the "
                     "co-management collection and the MECM client is healthy.",
    "no_client": "Install or repair the Configuration Manager client (ccmsetup), then wait for the first policy cycle.",
    "client_inactive": "MECM client inactive or no policy request in the stale window: run client health checks or reinstall.",
    "intune_stale": "No Intune sync in the stale window: trigger a sync and check the MDM enrolment certificate.",
    "authority": "Workload authority differs from the plan: check collection membership, then force a machine policy "
                 "retrieval and an Intune sync.",
    "noncompliant": "Non-compliant in Intune: open the device in Intune to see which setting fails.",
    "win11_blocked": "Hardware not ready for Windows 11: plan a replacement or exclude from the wave.",
}


@dataclass
class DeviceState:
    name: str
    mecm: MecmDevice | None
    intune: IntuneDevice | None
    state: str
    wave: str = ""
    in_pilot: bool = False
    issues: list[tuple[str, str]] = field(default_factory=list)       # (code, text)
    authority: dict[str, tuple[str, str]] = field(default_factory=dict)  # workload -> (expected, actual)

    @property
    def win11(self) -> bool:
        if self.mecm and self.mecm.os_build:
            return self.mecm.os_build >= 22000
        if self.intune and self.intune.os_version:
            parts = self.intune.os_version.split(".")
            return len(parts) > 2 and parts[2].isdigit() and int(parts[2]) >= 22000
        return False

    @property
    def client_healthy(self) -> bool:
        return not any(c in {"no_client", "client_inactive"} for c, _ in self.issues)

    @property
    def mismatches(self) -> list[str]:
        return [w for w, (exp, act) in self.authority.items() if exp != act]


def expected_authority(plan: Plan, in_pilot: bool, workload: str) -> str:
    slider = plan.workloads.get(workload, "configmgr")
    if slider == "intune" or (slider == "pilot" and in_pilot):
        return "Intune"
    return "ConfigMgr"


def classify(mecm: dict[str, MecmDevice], intune: dict[str, IntuneDevice], plan: Plan, now: datetime) -> list[DeviceState]:
    stale = timedelta(days=plan.stale_days)
    wave_by_collection = {w.collection: w.name for w in plan.waves}
    out = []
    for k in sorted(set(mecm) | set(intune)):
        m, i = mecm.get(k), intune.get(k)
        if m and not m.client:
            state = NO_CLIENT
        elif m and i:
            state = COMANAGED if i.comanaged else ENROLLED_NOT_COMGMT
        elif m:
            state = MECM_ONLY
        else:
            state = INTUNE_ONLY
        d = DeviceState((m or i).name, m, i, state)
        if m:
            d.in_pilot = plan.pilot_collection in m.collections
            d.wave = next((wave_by_collection[c] for c in m.collections if c in wave_by_collection), "")

        if state == NO_CLIENT:
            d.issues.append(("no_client", "No Configuration Manager client"))
        elif m and (not m.client_active or not m.last_policy or now - m.last_policy > stale):
            d.issues.append(("client_inactive", "MECM client inactive or no recent policy request"))
        if state == MECM_ONLY:
            d.issues.append(("not_enrolled", "Not enrolled in Intune"))
        if state == ENROLLED_NOT_COMGMT:
            d.issues.append(("not_comanaged", f"Enrolled in Intune but management agent is {i.agent}"))
        if i and (not i.last_sync or now - i.last_sync > stale):
            d.issues.append(("intune_stale", "No recent Intune sync"))
        if i and i.compliance in {"noncompliant", "error", "conflict"}:
            d.issues.append(("noncompliant", f"Intune compliance: {i.compliance}"))
        if m and not d.win11 and m.win11_hw_ready is False:
            d.issues.append(("win11_blocked", "Hardware not ready for Windows 11"))

        if state == COMANAGED:
            for w in WORKLOADS:
                exp = expected_authority(plan, d.in_pilot, w)
                act = "Intune" if i.features.get(w) else "ConfigMgr"
                d.authority[w] = (exp, act)
            wrong = d.mismatches
            if wrong:
                d.issues.append(("authority", "Workload authority not as planned: " +
                                 ", ".join(WORKLOADS[w] for w in wrong)))
        out.append(d)
    return out


def pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def overview(devices: list[DeviceState]) -> dict:
    windows = [d for d in devices if d.mecm]          # the MECM estate is the scope of the migration
    states = Counter(d.state for d in devices)
    return {
        "devices": len(devices),
        "mecm_scope": len(windows),
        "states": dict(states),
        "comanaged_pct": pct(sum(1 for d in windows if d.state == COMANAGED), len(windows)),
        "client_healthy_pct": pct(sum(1 for d in windows if d.client_healthy), len(windows)),
        "win11_pct": pct(sum(1 for d in windows if d.win11), len(windows)),
        "win11_blocked": sum(1 for d in windows if any(c == "win11_blocked" for c, _ in d.issues)),
        "with_issues": sum(1 for d in devices if d.issues),
    }


def wave_progress(devices: list[DeviceState], plan: Plan, now: datetime) -> list[dict]:
    rows = []
    for w in plan.waves:
        members = [d for d in devices if d.wave == w.name]
        n = len(members)
        done = sum(1 for d in members if d.win11 and d.state == COMANAGED and not d.issues)
        target = datetime.fromisoformat(w.target).date()
        rows.append({
            "wave": w.name, "collection": w.collection, "target": w.target, "devices": n,
            "comanaged_pct": pct(sum(1 for d in members if d.state == COMANAGED), n),
            "win11_pct": pct(sum(1 for d in members if d.win11), n),
            "done_pct": pct(done, n),
            "blocked": sum(1 for d in members if any(c == "win11_blocked" for c, _ in d.issues)),
            "days_left": (target - now.date()).days,
        })
    return rows


def gate_checks(devices: list[DeviceState], plan: Plan) -> list[dict]:
    """For every workload still on 'pilot', can the slider move to Intune for everyone?"""
    g = plan.gates
    scope = [d for d in devices if d.mecm]
    pilot = [d for d in scope if d.in_pilot and d.state == COMANAGED]
    common = [
        ("Co-managed devices", pct(sum(1 for d in scope if d.state == COMANAGED), len(scope)), g.min_comanaged_pct, ">="),
        ("Healthy MECM clients", pct(sum(1 for d in scope if d.client_healthy), len(scope)), g.min_client_healthy_pct, ">="),
        ("Pilot devices compliant", pct(sum(1 for d in pilot if d.intune.compliance == "compliant"), len(pilot)),
         g.min_pilot_compliant_pct, ">="),
    ]
    out = []
    for w, slider in plan.workloads.items():
        if slider != "pilot":
            continue
        wrong = pct(sum(1 for d in pilot if w in d.mismatches), len(pilot))
        checks = common + [(f"Pilot devices with wrong authority for {WORKLOADS[w]}", wrong, g.max_pilot_mismatch_pct, "<=")]
        results = [{"check": c, "value": v, "limit": lim, "op": op, "ok": v >= lim if op == ">=" else v <= lim}
                   for c, v, lim, op in checks]
        out.append({"workload": w, "name": WORKLOADS[w], "pilot_devices": len(pilot),
                    "go": all(r["ok"] for r in results) and len(pilot) > 0, "checks": results})
    return out


def find(devices: list[DeviceState], name: str) -> DeviceState | None:
    return next((d for d in devices if key(d.name) == key(name)), None)
