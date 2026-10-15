"""Outputs: report.html, exceptions.csv and gates.md (go/no-go note for the change board)."""
from __future__ import annotations

import csv
import html
from collections import Counter
from datetime import datetime
from pathlib import Path

from .analysis import (COMANAGED, ENROLLED_NOT_COMGMT, FIX, INTUNE_ONLY, MECM_ONLY, NO_CLIENT, DeviceState,
                       gate_checks, overview, wave_progress)
from .model import WORKLOADS, Plan

e = html.escape
ORDER = ["no_client", "not_enrolled", "not_comanaged", "client_inactive", "authority", "intune_stale",
         "noncompliant", "win11_blocked"]


def write_exceptions(devices: list[DeviceState], path: Path) -> int:
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["device", "state", "wave", "pilot", "os_build", "issue_code", "issue", "next_step"])
        for d in sorted(devices, key=lambda d: (min((ORDER.index(c) for c, _ in d.issues), default=99), d.name)):
            for code, text in d.issues:
                w.writerow([d.name, d.state, d.wave, "yes" if d.in_pilot else "no",
                            d.mecm.os_build if d.mecm else "", code, text, FIX.get(code, "")])
                rows += 1
    return rows


def gates_md(devices: list[DeviceState], plan: Plan, now: datetime) -> str:
    lines = [f"# Co-management workloads · go/no-go · {now:%Y-%m-%d}", "",
             "Workloads currently on **Pilot**, and whether the slider can move to **Intune** for all devices.", ""]
    gates = gate_checks(devices, plan)
    if not gates:
        lines.append("No workload is on Pilot.")
    for g in gates:
        lines += [f"## {g['name']}: {'GO' if g['go'] else 'NO-GO'}", "",
                  f"Pilot devices (co-managed): {g['pilot_devices']}", "",
                  "| Check | Value | Limit | Result |", "|---|---|---|---|"]
        for c in g["checks"]:
            lines.append(f"| {c['check']} | {c['value']} % | {c['op']} {c['limit']} % | {'pass' if c['ok'] else 'FAIL'} |")
        lines.append("")
    o = overview(devices)
    lines += ["## Blocking devices", "",
              f"- Not enrolled in Intune: {o['states'].get(MECM_ONLY, 0)}",
              f"- Enrolled outside co-management: {o['states'].get(ENROLLED_NOT_COMGMT, 0)}",
              f"- No MECM client: {o['states'].get(NO_CLIENT, 0)}",
              f"- MECM client unhealthy: {sum(1 for d in devices if any(c == 'client_inactive' for c, _ in d.issues))}",
              "", "Full list with next steps: `exceptions.csv`.", "",
              "Rollback for any workload: move the slider back to Configuration Manager (or Pilot). "
              "Devices pick up the change at their next policy cycle.", ""]
    return "\n".join(lines)


CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--cm:#7a5af8;--in:#0b6bcb}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;--bad:#f2685c;--cm:#a48afb;--in:#5aa9f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:28px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;min-width:120px}.bar i{display:block;height:100%;background:var(--ok)}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.go{color:var(--ok)}.nogo{color:var(--bad)}.cm{color:var(--cm)}.in{color:var(--in)}.pilot{color:var(--warn)}
.gates{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}.gate{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.gate h3{margin:0 0 8px;font-size:16px;display:flex;justify-content:space-between;gap:8px}.gate ul{margin:0;padding-left:18px}.gate li.fail{color:var(--bad)}
footer{margin-top:40px;font-size:13px}
"""


def render_html(devices: list[DeviceState], plan: Plan, now: datetime, title: str) -> str:
    o = overview(devices)
    tiles = (f"<div class='tile'><span class='muted'>Devices in MECM</span><b>{o['mecm_scope']}</b></div>"
             f"<div class='tile'><span class='muted'>Co-managed</span><b>{o['comanaged_pct']}%</b></div>"
             f"<div class='tile'><span class='muted'>Healthy MECM client</span><b>{o['client_healthy_pct']}%</b></div>"
             f"<div class='tile'><span class='muted'>On Windows 11</span><b>{o['win11_pct']}%</b></div>"
             f"<div class='tile'><span class='muted'>Hardware blocks W11</span><b>{o['win11_blocked']}</b></div>")

    state_rows = "".join(f"<tr><td>{e(s)}</td><td class='num'>{o['states'].get(s, 0)}</td></tr>"
                         for s in (COMANAGED, MECM_ONLY, ENROLLED_NOT_COMGMT, NO_CLIENT, INTUNE_ONLY))

    wave_rows = "".join(
        f"<tr><td><b>{e(w['wave'])}</b><br><span class='muted'>{e(w['collection'])}</span></td><td class='num'>{w['devices']}</td>"
        f"<td>{w['win11_pct']}%<div class='bar'><i style='width:{w['win11_pct']}%'></i></div></td>"
        f"<td>{w['comanaged_pct']}%</td><td>{w['done_pct']}%</td><td class='num'>{w['blocked']}</td>"
        f"<td>{e(w['target'])}<br><span class='muted'>{'overdue by ' + str(-w['days_left']) + ' d' if w['days_left'] < 0 else str(w['days_left']) + ' d left'}</span></td></tr>"
        for w in wave_progress(devices, plan, now))

    co = [d for d in devices if d.state == COMANAGED]
    wl_rows = []
    for w, label in WORKLOADS.items():
        slider = plan.workloads.get(w, "configmgr")
        intune = sum(1 for d in co if d.authority[w][1] == "Intune")
        wrong = sum(1 for d in co if w in d.mismatches)
        cls = {"configmgr": "cm", "pilot": "pilot", "intune": "in"}[slider]
        wl_rows.append(f"<tr><td>{e(label)}</td><td><span class='pill {cls}'>{ {'configmgr': 'Configuration Manager', 'pilot': 'Pilot Intune', 'intune': 'Intune'}[slider]}</span></td>"
                       f"<td class='num'>{intune}</td><td class='num'>{len(co) - intune}</td>"
                       f"<td class='num'>{wrong if wrong else '—'}</td></tr>")

    gate_cards = []
    for g in gate_checks(devices, plan):
        items = "".join(f"<li class='{'' if c['ok'] else 'fail'}'>{e(c['check'])}: {c['value']}% "
                        f"<span class='muted'>(limit {c['op']} {c['limit']}%)</span></li>" for c in g["checks"])
        gate_cards.append(f"<div class='gate'><h3>{e(g['name'])}<span class='pill {'go' if g['go'] else 'nogo'}'>"
                          f"{'GO' if g['go'] else 'NO-GO'}</span></h3><ul>{items}</ul></div>")
    gates_html = f"<div class='gates'>{''.join(gate_cards)}</div>" if gate_cards else "<p>No workload is on Pilot.</p>"

    issues = Counter(c for d in devices for c, _ in d.issues)
    issue_rows = "".join(f"<tr><td><code>{c}</code></td><td class='num'>{issues[c]}</td><td>{e(FIX[c])}</td></tr>"
                         for c in ORDER if issues.get(c))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><main>
<h1>{e(title)}</h1><p class="muted">Generated {now:%Y-%m-%d %H:%M} UTC · MECM and Intune joined by device name</p>
<div class="tiles">{tiles}</div>
<h2>Go/no-go for the next slider move</h2><p class="muted">Workloads on Pilot, checked against the gates in plan.json.</p>
{gates_html}
<h2>Windows 11 waves</h2><p class="muted">"Done" = Windows 11, co-managed and no open issue.</p>
<div class="wrap"><table><thead><tr><th>Wave</th><th class="num">Devices</th><th>Windows 11</th><th>Co-managed</th><th>Done</th><th class="num">HW blocked</th><th>Target</th></tr></thead><tbody>{wave_rows}</tbody></table></div>
<h2>Workloads</h2><p class="muted">Slider position in the plan and actual authority reported by co-managed devices.</p>
<div class="wrap"><table><thead><tr><th>Workload</th><th>Slider</th><th class="num">Intune</th><th class="num">ConfigMgr</th><th class="num">Not as planned</th></tr></thead><tbody>{''.join(wl_rows)}</tbody></table></div>
<h2>Device states</h2><div class="wrap"><table><thead><tr><th>State</th><th class="num">Devices</th></tr></thead><tbody>{state_rows}</tbody></table></div>
<h2>Exceptions</h2><p class="muted">{o['with_issues']} devices with at least one issue. Full list in exceptions.csv.</p>
<div class="wrap"><table><thead><tr><th>Issue</th><th class="num">Devices</th><th>Next step</th></tr></thead><tbody>{issue_rows}</tbody></table></div>
<footer class="muted">MECM + Intune co-management tracker · github.com/inigogonzalezgarcia/18-mecm-intune-comanagement-tracker</footer>
</main></body></html>
"""
