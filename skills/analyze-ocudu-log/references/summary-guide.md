# OCUDU Run Summary — Detailed Steps

Produce the run summary efficiently. Do not read any log file in full. Work through all sources below in order — each step targets a different artifact type and contributes different information. Skip a step only when its artifact type is absent from the run.

---

## Step 1 — CI report files

If the artifacts came from a CI job, look for report files first:
```bash
ls <run_folder>   # look for *.html, *.xml files
```

The primary report is an HTML file (e.g. `report.html`, `log/report.html`). Open or `grep` it for pass/fail markers and failure messages:
```bash
grep -iE 'failed|passed|error|assertion' report.html | head -30
```

JUnit XML files (`out.xml`, `report.xml`) may also be present. If found, grep them for failure details:
```bash
grep -E '<failure|<error|<skipped' out.xml
```

These files often directly state whether the run passed or failed and the assertion or exception that caused the failure. If the failure reason is clear from the report file alone, note it in the summary and skip Step 7 (detailed errors and warnings scan).

If a **CI job raw log** is available (`/tmp/job_clean.log` from the SKILL.md CI flow), also grep for **Retina** per-component warning summaries — these are a high-value fast signal emitted at test end:
```bash
grep -E 'has [0-9]+ errors|has [0-9]+ warnings' /tmp/job_clean.log | head -20
```
Example: `[WARNING] GNB_1 has 9 errors and 23705 warnings. First error is: RealtimeSanitizer: unsafe-library-call`

---

## Step 2 — Config files (`*.yml`, `*.yaml`)

Read any YAML config files in the run folder before opening logs. They are small and reveal topology, radio, and test settings upfront.

**Topology:**
- Number of DUs: look for a top-level `du` section or multiple `du_N` entries
- Number of CUs: presence of `cu_cp` / `cu_up` sections (split CU) vs. a single `cu` section (combined)
- Cells per DU: `cell_cfg` list length or `nof_cells`

**UE simulator:**

| Config key / value | UE type |
|---|---|
| `test_mode.test_ue` present | Test mode UEs (simulated inside gNB) |
| `no_core: true` | No core — UEs simulated at RRC level |
| `ru_sdr.device_driver: zmq` | ZMQ-based external UE simulator |
| No simulator config, real AMF address | Real UE or Amarisoft |

**5G core:**
- AMF address/hostname in `amf.addr` or `ngap` section
- `no_core: true` means no core at all

**Radio and timing:**
- `ru_sdr.device_driver` — SDR type or `zmq`
- `ru_ofh` section — O-RAN FH RU
- `ru_dummy` — dummy RU (no actual radio)

**Carrier config:**
- `dl_arfcn`, `channel_bandwidth_mhz`, `scs` (subcarrier spacing), `duplex_mode` (TDD/FDD)
- `ntn` section or `ntn_level` key — NTN enabled

**Traffic:**
- Presence of `iperf` or `ping` keys, or check console output for iperf/ping invocations

---

## Step 3 — Console output (`.txt`, `.out`, `.stdout`)

Read console files as plain text. They are usually small.

**What to look for:**
```bash
# Test framework result
grep -iE 'PASSED|FAILED|ERROR|assert|exception|traceback|segfault|core dump' <console_file>

# Version / commit hash (if not in the log CONFIG block)
grep -iE 'version|commit|build' <console_file> | head -5

# iperf / ping traffic confirmation
grep -iE 'iperf|ping|bitrate|interval' <console_file> | head -10

# Sanitizer errors (RTSAN / ASAN / UBSAN) — written to stderr, appear in console output
grep -E '==.*==ERROR:.*Sanitizer' <console_file>
```

**Sanitizer errors** (`RealtimeSanitizer`, `AddressSanitizer`, `UndefinedBehaviorSanitizer`) are a distinct failure class: the process detected a runtime safety violation and printed a stack trace. They always appear as `==PID==ERROR: <SanitizerName>: <description>` lines followed by a stack trace. Flag any occurrence immediately — they are always actionable.

---

## Step 4 — Startup CONFIG block

The CONFIG block in the structured log lists all non-default settings. It often fills gaps left by config files (e.g. scheduler tweaks, log levels, PRACH config).

```bash
grep '\[CONFIG' <logfile> | head -80
```

Key fields to extract:
- Application type and version: first CONFIG lines
- `prach_config_index`, `tdd_ul_dl_cfg` — radio frame structure
- `scheduler` section — any non-default scheduler parameters
- `max_nof_ues` — maximum UE capacity configured
- `mobility.*` — handover trigger flags (see scenario table below)
- `xnap_enable`, `cu_cp.max_nof_dus` — multi-DU / inter-CU topology
- `ntn_level` — NTN mode

---

## Step 5 — Run-mode detection

Use signals from config files (Step 2) and the CONFIG block (Step 4) to determine the run mode. It governs whether latency analysis is relevant and how to interpret timing figures.

| Signal | Mode |
|---|---|
| `ru_sdr.device_driver: uhd/bladerf/lime/soapy` | Real SDR — real-time |
| `ru_ofh` section present or `OFH` component tags in log | O-RAN FH RU — real-time |
| `ru_dummy` section or `device_driver: dummy` | Dummy RU — real-time timing, no actual radio |
| `ru_sdr.device_driver: zmq` or `zmq:tx`/`zmq:rx` component tags | ZMQ simulation — not real-time |
| No `ru_*` config present (unit test / console output only) | Unit test — not real-time |

In ZMQ simulation and unit test modes, latency analysis is not relevant — do not mention it. `ru_dummy` uses real-time timing, so latency metrics remain relevant there.

---

## Step 6 — METRICS lines

METRICS lines are sparse and give throughput and HARQ KO counts without reading the full log.

If `references/scripts/metrics.py` exists, run it — it scans all windows and computes peaks:
```bash
python3 references/scripts/metrics.py <logfile>
```

Otherwise, extract all scheduler cell metric lines (scanning all windows is required to find the peak — `tail` alone can miss an early peak):
```bash
grep '\[METRICS' <logfile> | grep 'Scheduler cell pci'
```
For recent state only, append `| tail -10`.

**Cell-level fields (from Scheduler cell metrics lines):**

| Field | Meaning |
|---|---|
| `total_dl_brate` / `total_ul_brate` | Aggregate DL/UL throughput (bps) |
| `nof_ues` | Active UEs at end of window |
| `nof_prach_preambles` | PRACH preamble detections |
| `msg3_ok` / `msg3_nok` | Msg3 completions / failures |

**Per-UE HARQ fields (from UE metrics lines):**

| Field | Meaning |
|---|---|
| `dl_nok` / `dl_ok` | Per-UE DL HARQ KO / OK counts |
| `ul_nok` / `ul_ok` | Per-UE UL HARQ KO / OK counts |

**KO rate formulas** (sum across all UE metrics lines):
```
DL KO rate = Σ(dl_nok) / Σ(dl_ok + dl_nok)
UL KO rate = Σ(ul_nok) / Σ(ul_ok + ul_nok)
```

Report peak `total_dl_brate` and `total_ul_brate` across all windows, and the overall KO rate across the whole run (sum all UE metrics lines).

---

## Step 7 — Errors and warnings

```bash
grep -cE '\[E\]|\[W\]' <logfile>              # count first
grep -E -m 20 '\[E\]|\[W\]' <logfile>         # first 20 occurrences
```

Suppress known startup noise: `CPU* scaling governor` and `DRM KMS polling` warnings. Count and categorise the rest by component tag.

---

## Scenario identification

Identify the test objective in one sentence. Check in order:

1. **User stated it** — take at face value.
2. **Config file name or folder path** — look for an embedded test name (e.g. `handover_zmq`, `ntn_attach`).
3. **CONFIG block signals:**

   | Config signal | Likely scenario |
   |---|---|
   | `mobility.trigger_cho_on_ue_setup: true` | CHO stress / ping-pong test |
   | `mobility.trigger_handover_from_measurements: true` | Measurement-triggered HO |
   | `xnap_enable: true` or XNAP component tags present | Inter-CU handover |
   | `cu_cp.max_nof_dus > 1` and multiple DU F1 connections | Inter-DU handover |
   | `no_core: true` | Standalone / no-core attach test |
   | Single cell, single UE, short run | Basic attach + data test |
   | `max_nof_ues` high or many concurrent RACHs | Load / scalability test |
   | `ntn_level` present or NTN config keys | NTN scenario |

4. **Procedure events in the log:**
   ```bash
   grep -E -m 10 'CHO winner|XnAP|F1 UE context|InitialUEMessage' <logfile>
   ```
   - `CHO winner selected` → CHO execution
   - `XnAP` PDUs → inter-CU in progress
   - Rapid `F1 UE context removed` / `F1 UE context created` cycles → handover loop
   - Single `InitialUEMessage` + `InitialContextSetupResponse` → basic attach

5. **If still ambiguous** — ask the user one focused question before continuing.

State at the top of the summary: **Scenario**: \<one sentence\>. This governs what counts as anomalous in any subsequent analysis.

---

## Accumulated knowledge

- 2026-04-29: Test mode cycling scenario is detected via `grep "TEST_MODE"` on the `[DU]` component tag. Key lifecycle transitions — "All UEs established", "Releasing", "Guard period elapsed", "Starting new creation cycle" — give a fast pass/fail signal without reading the full log.
