import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from comgmt import cli
from comgmt.analysis import (COMANAGED, ENROLLED_NOT_COMGMT, INTUNE_ONLY, MECM_ONLY, NO_CLIENT, classify,
                             expected_authority, gate_checks, wave_progress)
from comgmt.model import WORKLOADS, Gates, IntuneDevice, MecmDevice, Plan, Wave, key, load_intune, load_plan

NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
PLAN = Plan("Pilot", {"compliancePolicy": "intune", "deviceConfiguration": "pilot", "officeApps": "configmgr"},
            [Wave("W1", "Wave1", "2026-10-30")], Gates())


def mecm(name="PC1", collections=("Wave1",), active=True, client=True, build=22631, hw=None, policy_days=1):
    return MecmDevice(name, "1", client, active, NOW - timedelta(days=policy_days), build, hw, list(collections))


def intune(name="PC1", agent="configurationManagerClientMdm", feats=None, compliance="compliant", sync_days=1):
    return IntuneDevice(name, agent, compliance, NOW - timedelta(days=sync_days), "10.0.22631.1", "S",
                        feats if feats is not None else {w: False for w in WORKLOADS})


def planned(in_pilot):
    return {w: expected_authority(PLAN, in_pilot, w) == "Intune" for w in WORKLOADS}


def one(m=None, i=None, plan=PLAN):
    ms = {key(m.name): m} if m else {}
    iss = {key(i.name): i} if i else {}
    return classify(ms, iss, plan, NOW)[0]


class Join(unittest.TestCase):
    def test_states(self):
        self.assertEqual(one(mecm(), intune(feats=planned(False))).state, COMANAGED)
        self.assertEqual(one(mecm()).state, MECM_ONLY)
        self.assertEqual(one(mecm(), intune(agent="mdm")).state, ENROLLED_NOT_COMGMT)
        self.assertEqual(one(None, intune(agent="mdm")).state, INTUNE_ONLY)
        self.assertEqual(one(mecm(client=False)).state, NO_CLIENT)

    def test_name_match_ignores_case_and_dns_suffix(self):
        d = one(mecm("pc1.corp.contoso.example"), intune("PC1", feats=planned(False)))
        self.assertEqual(d.state, COMANAGED)

    def test_comanaged_with_eas_agent(self):
        self.assertEqual(one(mecm(), intune(agent="configurationManagerClientMdmEas", feats=planned(False))).state,
                         COMANAGED)


class Authority(unittest.TestCase):
    def test_slider_logic(self):
        self.assertEqual(expected_authority(PLAN, False, "compliancePolicy"), "Intune")
        self.assertEqual(expected_authority(PLAN, True, "deviceConfiguration"), "Intune")
        self.assertEqual(expected_authority(PLAN, False, "deviceConfiguration"), "ConfigMgr")
        self.assertEqual(expected_authority(PLAN, True, "officeApps"), "ConfigMgr")
        self.assertEqual(expected_authority(PLAN, True, "endpointProtection"), "ConfigMgr")  # not in plan

    def test_mismatch_is_reported(self):
        feats = planned(True)
        feats["deviceConfiguration"] = False
        d = one(mecm(collections=("Wave1", "Pilot")), intune(feats=feats))
        self.assertEqual(d.mismatches, ["deviceConfiguration"])
        self.assertIn("authority", [c for c, _ in d.issues])

    def test_planned_state_has_no_issue(self):
        d = one(mecm(collections=("Pilot",)), intune(feats=planned(True)))
        self.assertEqual(d.issues, [])


class Health(unittest.TestCase):
    def test_inactive_and_stale(self):
        codes = [c for c, _ in one(mecm(active=False), intune(feats=planned(False))).issues]
        self.assertIn("client_inactive", codes)
        codes = [c for c, _ in one(mecm(policy_days=30), intune(feats=planned(False), sync_days=30)).issues]
        self.assertEqual(set(codes), {"client_inactive", "intune_stale"})

    def test_win11_blocked_only_when_on_win10_and_not_ready(self):
        self.assertIn("win11_blocked", [c for c, _ in one(mecm(build=19045, hw=False), intune(feats=planned(False))).issues])
        self.assertEqual(one(mecm(build=19045, hw=None), intune(feats=planned(False))).issues, [])
        self.assertTrue(one(mecm(build=26100), intune(feats=planned(False))).win11)


class Gates_(unittest.TestCase):
    def fleet(self, n_ok, n_bad):
        ms, iss = {}, {}
        for k in range(n_ok + n_bad):
            name = f"PC{k}"
            ms[key(name)] = mecm(name, collections=("Wave1", "Pilot"))
            if k < n_ok:
                iss[key(name)] = intune(name, feats=planned(True))
        return classify(ms, iss, PLAN, NOW)

    def test_go_when_all_checks_pass(self):
        g = gate_checks(self.fleet(100, 0), PLAN)
        self.assertEqual([x["workload"] for x in g], ["deviceConfiguration"])
        self.assertTrue(g[0]["go"])

    def test_no_go_when_too_few_comanaged(self):
        g = gate_checks(self.fleet(90, 10), PLAN)[0]
        self.assertFalse(g["go"])
        self.assertFalse(g["checks"][0]["ok"])

    def test_wave_progress(self):
        rows = wave_progress(self.fleet(3, 1), PLAN, NOW)
        self.assertEqual(rows[0]["devices"], 4)
        self.assertEqual(rows[0]["comanaged_pct"], 75.0)
        self.assertEqual(rows[0]["days_left"], 11)


class Files(unittest.TestCase):
    def test_intune_loader_keeps_newest_duplicate_and_skips_non_windows(self):
        rows = [{"deviceName": "PC1", "operatingSystem": "Windows", "managementAgent": "mdm",
                 "lastSyncDateTime": "2026-01-01T00:00:00Z"},
                {"deviceName": "pc1", "operatingSystem": "Windows", "managementAgent": "configurationManagerClientMdm",
                 "lastSyncDateTime": "2026-10-18T00:00:00Z"},
                {"deviceName": "Phone", "operatingSystem": "iOS"}]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "i.json"
            p.write_text(json.dumps({"value": rows}), encoding="utf-8")
            loaded = load_intune(p)
        self.assertEqual(list(loaded), ["PC1"])
        self.assertTrue(loaded["PC1"].comanaged)

    def test_plan_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps({"pilot_collection": "P", "workloads": {"compliancePolicy": "half"}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_plan(p)

    def test_demo_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cli.main(["demo", "--out", str(tmp / "out"), "--data", str(tmp / "data")])
            html = (tmp / "out" / "report.html").read_text(encoding="utf-8")
            self.assertIn("Go/no-go", html)
            gates = (tmp / "out" / "gates.md").read_text(encoding="utf-8")
            self.assertIn("Device configuration: NO-GO", gates)
            with open(tmp / "out" / "exceptions.csv", encoding="utf-8") as f:
                codes = {r["issue_code"] for r in csv.DictReader(f)}
            self.assertTrue({"no_client", "not_enrolled", "authority", "win11_blocked"} <= codes)


if __name__ == "__main__":
    unittest.main()
