# Playbook: moving co-management workloads and Windows 11 waves

How the tracker fits into a migration run in waves, with a change board (CAB) deciding each step.

## 1. Before the first wave

- Co-management enabled with **auto-enrolment** for a collection that starts small (the pilot).
- `plan.json` written and agreed: pilot collection, slider position per workload, one collection per wave with a target date, and the gates.
- Baseline report saved. It is the "before" picture for the CAB and shows the real size of the clean-up (devices without client, not enrolled, hardware not ready for Windows 11).

## 2. Every week during the migration

1. Export both sides (`scripts/mecm_devices.sql`, `scripts/Export-IntuneComanagement.ps1`) and run:
   ```bash
   python -m comgmt report mecm_devices.csv intune_devices.json --plan plan.json
   ```
2. Share `exceptions.csv` with the people who fix devices, ordered as it comes (no client first, then not enrolled, then the rest).
3. Look at the wave table: a wave close to its target date with a low "Done" share needs a decision now (more hands, move the date, or move devices to the next wave).
4. Hardware that blocks Windows 11 goes to the refresh plan, not to the wave.

## 3. Moving a workload slider

A workload goes **Configuration Manager → Pilot Intune → Intune**, one step at a time.

| Step | Evidence for the CAB |
|---|---|
| To **Pilot** | Intune policy for that workload built and tested on a lab device; pilot collection agreed with the users in it. |
| Pilot running | At least one full policy cycle; pilot users told who to call. |
| To **Intune** (everyone) | `gates.md` shows **GO** for that workload; no open incident caused by the pilot. |

**Rollback:** move the slider back. Devices pick up the change at the next policy cycle; force it with a machine policy retrieval if needed. Note it in the change record.

## 4. Gates used in the demo

| Gate | Default | Why |
|---|---|---|
| Co-managed devices | ≥ 95 % | A device that is not co-managed keeps the old authority whatever the slider says. |
| Healthy MECM clients | ≥ 95 % | Unhealthy clients do not receive the change and give false comfort. |
| Pilot devices compliant | ≥ 90 % | If the pilot is not compliant, moving everyone will not be either. |
| Pilot devices with wrong authority | ≤ 2 % | Shows the pilot actually took the change. |

Change the numbers in `plan.json` to match your own risk appetite. The point is to agree them **before** the CAB, not during it.

## 5. After the last wave

- Every workload on Intune, or a written reason to keep it in Configuration Manager.
- Exceptions list close to zero, with named owners for what is left.
- Decide what Configuration Manager is still used for (software distribution, task sequences, servers) and plan the rest.
