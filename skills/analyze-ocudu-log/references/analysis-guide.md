# OCUDU Log Analysis — Detailed Steps

## Step 1 — Start from the Run summary

The Run summary (SKILL.md § Run summary and `summary-guide.md`) already provides the overview: scenario, setup, errors/warnings, and basic metrics. Do not repeat those steps. Identify the failure events from what the summary found, then proceed to Step 2.

---

## Step 2 — Locate failure events

For each failure, note its **timestamp and slot** precisely:
- Errors: timestamps already available from the summary
- Metric drops: find the first window where the KPI degrades
- RLF / PRACH failure: grep for the specific event string

```bash
grep -nE 'RLF|radio link failure|PRACH.*fail|msg3_nok=[^0]|Random Access' <logfile>
```

**Grep output discipline** — apply this to every grep in this workflow:
```bash
grep -cE '<pattern>' <logfile>          # count first
grep -m 30 -nE '<pattern>' <logfile>    # then cap output if count is large
```
Never pipe an unbounded grep result into context. Count first; sample with `-m N` if the count is large.

---

## Step 3 — Extract context around each failure

**Window before the failure** (typically a few seconds of wall-clock time back): use the line number from `grep -n` to read a `sed` range:
```bash
sed -n '<start>,<end>p' <logfile>
```

**Full multiline log entry** at a specific point — use `grep_multiline.py` when an entry's continuation lines (key-value sub-lines) carry the relevant detail:
```bash
python3 references/scripts/grep_multiline.py <logfile> '<pattern>'
```
This avoids partial reads that miss structured sub-lines.

---

## Step 4 — Deep-dive by layer or procedure

For failures centred on a specific NR procedure, load the procedure file and follow it — it covers all the relevant layers in one place. For other failures, load the individual layer file(s) implicated by steps 2–3.

**Procedure files** (`references/procedures/`):

| Failure type | Procedure file | Load when |
|---|---|---|
| PRACH not detected, UE stuck before RRC Setup, Msg3 failures, RAPID mismatch | `procedures/random-access.md` | Any RA or PRACH failure |

**Layer files** (`references/layers/`):

Read only the sections relevant to the observed symptom. Before grepping manually, check whether a parsing script in `references/scripts/` covers the layer:
```bash
cat <logfile> | python3 references/scripts/proc_durations.py --layer <LAYER> [--proc <proc>]
python3 references/scripts/grep_multiline.py <logfile> [grep-options] '<pattern>'
```
Fall back to grep/sed only when no relevant script exists.

| Component tag(s) | Layer file | When to load |
|---|---|---|
| `SCHED` | `layers/sched.md` | HARQ failures, allocation failures, zero throughput, slot decision timing |
| `MAC` | `layers/mac.md` | Cell lifecycle issues, pipeline timing anomalies |
| `DU-MNG` | `layers/du_mng.md` | UE lifecycle procedure latency, cycling scenarios, stuck cycling diagnosis |
| `PHY`, `DU-LOW` | `layers/phy.md` | PHY latency spikes, high LDPC iterations, DTX vs degradation |
| `RRC` | `layers/rrc.md` | Connection drops, RLF, handover, UE stuck after RACH completes |
| `F1AP` | `layers/f1ap.md` | CU–DU interface failures, UE context errors |
| `NGAP` | `layers/ngap.md` | Core network rejections, PDU session failures |
| `E1AP` | `layers/e1ap.md` | User-plane bearer failures, zero throughput with UE connected |
| `OFH` | `layers/ofh.md` | Any non-zero OFH sector/timing metrics anomaly, RACH failures in O-RAN FH deployments, missed UL symbols or PRACH occasions |
| `FAPI` | *(no layer file — search source)* | Timing or API failures between DU-high and DU-low |
| `RLC`, `PDCP`, `SDAP` | *(no layer files — search source)* | User-plane data path above MAC |

Apply the same grep output discipline (Step 2) to all layer-level greps.

#### When gnb.log shows a DTX pattern

If PHY PUSCH KOs show `sinr=infdB` (UE transmitted nothing), cross-reference the Amarisoft
`ue.log` to find what the UE decoded at the silence boundary:

```bash
# 1. Find the silence boundary — first KO slot and last OK slot — from gnb.log
grep "PUSCH: rnti=0xXXXX" gnb.log | grep -E 'crc=(OK|KO)' | tail -20

# 2. Grep ue.log for PDCCH entries around the failure window (adjust timestamps)
grep "PDCCH" ue.log | grep -E "HH:MM:3[789]\."

# 3. Automate both steps with the dedicated script:
python3 references/scripts/ue_rlf_trace.py --gnb gnb.log --rnti 0xXXXX [--ue ue.log]
```

Look for: `PDCCH: ss_id=1 cce_index=0 al=4 dci=1_0` entries in `ue.log` at a slot where
`gnb.log` sent `ss_id=2` for that UE. See `references/layers/rrc.md` § Amarisoft ZMQ spurious DCI
for the full interpretation and confirmation checklist.

---

## Step 5 — Diagnosis and recommendations

Short bulleted diagnosis:
- What is working and what failed
- Root cause in 5G/NR protocol terms
- Concrete next steps: config changes, debug logging to enable, what to look for in a pcap
- If only startup with no UE traffic, say so and note what to check next

---

## Step 6 — Persist new insights

Append new log structure insights to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file. See SKILL.md § Memory for what qualifies — log structure observations only, not bug descriptions or run-specific values.
