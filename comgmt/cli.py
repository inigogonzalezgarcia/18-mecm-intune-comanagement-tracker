"""Command line: `demo` builds everything from fictional data, `report` runs on your own exports."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import report, simulate
from .analysis import classify, gate_checks, overview
from .model import load_intune, load_mecm, load_plan, parse_ts


def run(mecm: Path, intune: Path, plan_path: Path, out: Path, now: datetime, title: str) -> dict:
    plan = load_plan(plan_path)
    devices = classify(load_mecm(mecm), load_intune(intune), plan, now)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(devices, plan, now, title), encoding="utf-8")
    report.write_exceptions(devices, out / "exceptions.csv")
    (out / "gates.md").write_text(report.gates_md(devices, plan, now), encoding="utf-8")
    o = overview(devices)
    o["gates"] = {g["workload"]: g["go"] for g in gate_checks(devices, plan)}
    return o


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="comgmt", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="generate a fictional estate and build the outputs")
    d.add_argument("--out", type=Path, default=Path("output"))
    d.add_argument("--data", type=Path, default=Path("sample_data"))
    r = sub.add_parser("report", help="build the outputs from your own exports")
    r.add_argument("mecm", type=Path, help="CSV from scripts/mecm_devices.sql")
    r.add_argument("intune", type=Path, help="JSON from scripts/Export-IntuneComanagement.ps1")
    r.add_argument("--plan", type=Path, required=True, help="plan.json (slider positions, waves, gates)")
    r.add_argument("--out", type=Path, default=Path("output"))
    r.add_argument("--now", help="ISO timestamp to evaluate at (default: current time)")
    r.add_argument("--title", default="Co-management and Windows 11 tracker")
    a = p.parse_args(argv)

    if a.cmd == "demo":
        paths = simulate.write_demo(a.data)
        o = run(paths["mecm"], paths["intune"], paths["plan"], a.out, simulate.DEMO_NOW,
                "Co-management and Windows 11 tracker (demo data)")
    else:
        now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
        o = run(a.mecm, a.intune, a.plan, a.out, now, a.title)
    gates = ", ".join(f"{k}: {'GO' if v else 'NO-GO'}" for k, v in o["gates"].items()) or "no workload on pilot"
    print(f"{o['mecm_scope']} devices in MECM · {o['comanaged_pct']}% co-managed · {o['win11_pct']}% on Windows 11 · "
          f"{o['with_issues']} with issues. Gates: {gates}. Outputs in {a.out}/")
    return 0
