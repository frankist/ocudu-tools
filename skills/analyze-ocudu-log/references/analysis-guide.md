# OCUDU Log Analysis — Detailed Steps

## Report mode

The **Run summary** (from SKILL.md § Run summary and `summary-guide.md`) already covers the report. Report mode adds deeper detail on top of it when the user asks for a fuller picture.

### Step 1 — Deeper metrics

From `[METRICS]` lines (load `layers/metrics.md` for field names):
- Per-UE DL/UL throughput breakdown
- PRACH detections (`nof_prach_preambles` from Scheduler cell metrics)
- Any windows with zero throughput while UEs were attached
- For O-RAN FH runs (`OFH` component tags present): OFH timing and sector metrics — check `nof_skipped_symbols`, `nof_missed_prach_occasions`, `nof_missed_uplink_symbols`, and the `tx_kpis` counters

If `references/scripts/metrics.py` exists, run it — it produces a compact summary covering all metric fields:
```bash
python3 references/scripts/metrics.py <logfile>
```

### Step 2 — Detailed errors and warnings

From `[W]` and `[E]` lines:
- Suppress startup noise: `CPU* scaling governor` and `DRM KMS polling` warnings
- Count and categorise remaining warnings and errors by component tag
- Flag RLF events explicitly: `grep -nE 'RLF|radio link failure' <logfile>`
- Report first and last occurrence timestamps for recurring issues

---

## Analysis mode

Identify what failed and why. Start with a quick report pass to orient, then focus investigation on the failure events.

### Step 1 — Start from the Run summary

The Run summary already provides the overview: scenario, setup, errors/warnings, and basic metrics. Use it as the starting point — do not repeat those steps. Identify the failure events from what the summary found, then proceed to Step 2.

### Step 2 — Locate failure events

For each identified failure, note its **timestamp and slot** precisely:
- Errors: already have timestamps from step 1
- Metric drops: find the first window where the KPI degrades
- RLF / PRACH failure: grep for the specific event string to get the exact slot

```bash
grep -nE 'RLF|radio link failure|PRACH.*fail|msg3_nok=[^0]|Random Access' <logfile>
```

### Step 3 — Look backward from each failure

Using `grep -n` line numbers from step 2, read the log in the window **before** each failure event (typically 100–500 lines back, adjusted to cover a few seconds of wall-clock time). Look for:
- Preceding errors or warnings in any component
- Degrading metrics (rising KO rate, falling throughput) in prior METRICS windows
- Protocol events that should have occurred but are absent (e.g. missing RRC messages before an RLF)

Use `sed -n '<start>,<end>p' <logfile>` to read a specific line range without loading the whole file.

### Step 4 — Deep-dive by layer

Load the layer file(s) for each component implicated by steps 2–3. Files are in `references/layers/`.

Before grepping manually, check whether a parsing script exists for the layer (`references/scripts/<layer>.py`). If it does, run it:
```bash
python3 references/scripts/<layer>.py <logfile>
```
Use its output as the layer summary — skip the manual grep passes it already covers. Fall back to grep/sed only if no script is present.

| Component tag(s) | Layer file | When to load |
|---|---|---|
| `SCHED` | `layers/sched.md` | `msg3_nok > 0`, RACH issues, HARQ failures, allocation failures, zero throughput |
| `MAC` | `layers/mac.md` | Cell lifecycle issues, pipeline timing anomalies |
| `PHY`, `DU-LOW` | `layers/phy.md` | PHY latency spikes, high LDPC iterations |
| `RRC` | `layers/rrc.md` | UE stuck after RACH, connection drops, RLF |
| `F1AP` | `layers/f1ap.md` | CU–DU interface failures, UE context errors |
| `NGAP` | `layers/ngap.md` | Core network rejections, PDU session failures |
| `E1AP` | `layers/e1ap.md` | User-plane bearer failures, zero throughput with UE connected |
| `OFH` | `layers/ofh.md` | Any non-zero OFH sector/timing metrics anomaly, RACH failures in O-RAN FH deployments, missed UL symbols or PRACH occasions |
| `FAPI` | *(no layer file — search source)* | Timing or API failures between DU-high and DU-low |
| `RLC`, `PDCP`, `SDAP` | *(no layer files — search source)* | User-plane data path above MAC: segmentation errors, ciphering failures, QoS flow mapping |

Use a single combined `grep -E` pass per layer. For very large logs, use `grep -n` to get line numbers first, then `sed` to read only the relevant ranges.

### Step 5 — Diagnosis and recommendations

Short bulleted diagnosis:
- What is working and what failed
- Root cause in 5G/NR protocol terms
- Concrete next steps: config changes, debug logging to enable, what to look for in a pcap
- If only startup with no UE traffic, say so and note what to check next

### Step 6 — Persist new insights

Append new generalisable findings to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file.

Format: `- YYYY-MM-DD: <what was found and why it matters>`

Worth saving: new log patterns or fields, root causes that took non-trivial reasoning, protocol facts deduced during analysis.
Not worth saving: per-run values (RNTIs, slot numbers, bitrates from a single run).
