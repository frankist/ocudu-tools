# OCUDU Log Analysis — Detailed Steps

## Report mode

Produce a concise summary of what occurred. Minimise token usage: do not read the full log. One combined grep pass covers everything needed.

### Step 1 — Single grep pass

Before grepping, check whether a parsing script exists for a relevant layer (e.g. `references/scripts/metrics.py`). If so, run it first — it will produce a compact summary that may cover steps 3–4 entirely:
```bash
python3 references/scripts/metrics.py <logfile>
```

Otherwise, fall back to the combined grep:
```bash
grep -E '\[CONFIG|\[METRICS|\[W\]|\[E\]' <logfile>
```

For large files, check size first (`wc -l`) and pipe through `grep -n` to get line numbers if you need to read surrounding context later.

### Step 2 — App and configuration summary

From `[CONFIG]` lines:
- Application type (GNB / DU / CU / CU-CP / CU-UP), commit hash, build type
- Run mode (see SKILL.md table)
- Key non-default settings: `prach`, `tdd_ul_dl_cfg`, `scheduler`, log levels

### Step 3 — Scenario detection

Follow the full procedure in SKILL.md § "Scenario detection". In brief:

1. `ls` the log's directory — read any companion files (configs, results, notes) before inspecting the log.
2. Extract scenario signals from the CONFIG block (mobility flags, cell count, `no_core`, NTN keys, etc.).
3. Grep for key procedure events (`CHO winner selected`, `XnAP`, rapid F1 context churn, etc.) to confirm.
4. If still ambiguous, ask the user one focused question.

**Output**: one sentence naming the scenario at the top of the report. This governs what counts as anomalous in the remaining steps.

### Step 4 — Metrics summary

From `[METRICS]` lines (load `layers/metrics.md` for field names):
- Number of UEs that connected (peak `ue_count` from MAC cell metrics)
- DL / UL throughput (aggregate and per-UE)
- DL / UL HARQ KOs (`dl_nok`, `ul_nok`) — report counts and rate
- PRACH detections (`preambles_detected` from Scheduler metrics)
- Any windows with zero throughput while UEs were attached

### Step 5 — Errors and warnings summary

From `[W]` and `[E]` lines:
- Suppress startup noise: `CPU* scaling governor` and `DRM KMS polling` warnings
- Count and categorise remaining warnings and errors by component and message type
- Flag RLF events explicitly (search for `RLF` or `radio link failure` in the filtered lines)
- Report first and last occurrence timestamps for recurring issues

---

## Analysis mode

Identify what failed and why. Start with a quick report pass to orient, then focus investigation on the failure events.

### Step 1 — Quick report pass

Run the report mode steps above to get an overview. This includes scenario detection (Report mode Step 3) — the identified scenario governs what counts as a real failure in the steps below.

### Step 2 — Locate failure events

For each identified failure, note its **timestamp and slot** precisely:
- Errors: already have timestamps from step 1
- Metric drops: find the first window where the KPI degrades
- RLF / PRACH failure: grep for the specific event string to get the exact slot

```bash
grep -n 'RLF\|radio link failure\|PRACH.*fail\|msg3.*nok\|Random Access' <logfile>
```

### Step 3 — Look backward from each failure

Using `grep -n` line numbers from step 2, read the log in the window **before** each failure event (typically 100–500 lines back, adjusted to cover a few seconds of wall-clock time). Look for:
- Preceding errors or warnings in any component
- Degrading metrics (rising KO rate, falling throughput) in prior METRICS windows
- Protocol events that should have occurred but are absent (e.g. missing RRC messages before an RLF)

Use `sed -n '<start>,<end>p' <logfile>` to read a specific line range without loading the whole file.

### Step 4 — Deep-dive by layer

Load the layer file(s) for each component implicated by steps 2–3. Files are in `references/layers/`.

Before grepping manually, check whether a parsing script exists for the layer:
```bash
python3 references/scripts/<layer>.py <logfile>
```
If the script exists, run it and use its output as the layer summary — skip the manual grep passes it already covers. Fall back to grep/sed only if no script is present.

| Component tag(s) | Layer file | When to load |
|---|---|---|
| `SCHED` | `layers/sched.md` | `msg3_nok > 0`, RACH issues, HARQ failures, allocation failures, zero throughput |
| `MAC` | `layers/mac.md` | Cell lifecycle issues, pipeline timing anomalies |
| `PHY`, `DU-LOW` | `layers/phy.md` | PHY latency spikes, high LDPC iterations |
| `RRC` | `layers/rrc.md` | UE stuck after RACH, connection drops, RLF |
| `F1AP` | `layers/f1ap.md` | CU–DU interface failures, UE context errors |
| `NGAP` | `layers/ngap.md` | Core network rejections, PDU session failures |
| `E1AP` | `layers/e1ap.md` | User-plane bearer failures, zero throughput with UE connected |

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
