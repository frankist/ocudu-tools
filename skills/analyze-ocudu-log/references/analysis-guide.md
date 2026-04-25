# OCUDU Log Analysis — Detailed Steps

## 1. Overview

- Build info: `grep 'Built in'` → application (GNB / DU / CU / CU-CP / CU-UP), commit hash, branch, build type
- Wall-clock time span: first and last timestamp in the file
- Components present and line counts: `grep -oP '\[\w[\w:.-]*\s*\]' | sort | uniq -c` — filter out bare `[D]`/`[I]`/`[W]`/`[E]` tokens
- Log level per component: grep for `*_level` keys in the CONFIG YAML block
- Cell active range: grep for `Cell scheduling was activated` / `Cell scheduling was deactivated`; report slot range

## 2. Active configuration and run-mode

Extract the YAML block after `Input configuration (only non-default values):`. Report fields relevant to diagnosis (`prach`, `tdd_ul_dl_cfg`, `scheduler`, `two_step`, `all_level`/`*_level`).

State the detected run mode (see SKILL.md table). This determines whether latency figures in §4 are meaningful.

## 3. Errors and warnings

- `grep '\[E\]'` — list every unique error with component and first occurrence timestamp/slot
- `grep '\[W\]'` — suppress the two repetitive startup lines (`CPU* scaling governor`, `DRM KMS polling`); list the rest
- State explicitly if none found

## 4. Metrics analysis

Load `references/layers/metrics.md` for full KPI line formats and interpretation guidance.

Run this before §5. Use findings to decide which layers warrant deeper investigation.

Grep for all METRICS lines in a single pass:
```
grep '\[METRICS \]'
```

Report each metrics type present (Scheduler, MAC cell, PHY, Executor, UE). After reporting all windows, list which KPIs are abnormal and which layer files to load in §5.

## 5. Deep-dive analysis

Load the layer file(s) for each component that showed anomalies in §3 or §4. Layer files are in `references/layers/`:

| Component tag(s) | Layer file | When to load |
|---|---|---|
| `SCHED` | `layers/sched.md` | `msg3_nok > 0`, RACH issues, HARQ failures, allocation failures, zero throughput |
| `MAC` | `layers/mac.md` | Cell lifecycle issues, pipeline timing anomalies |
| `PHY`, `DU-LOW` | `layers/phy.md` | PHY latency spikes, high LDPC iterations |
| `RRC` | `layers/rrc.md` | UE stuck after RACH, connection drops |
| `F1AP` | `layers/f1ap.md` | CU–DU interface failures, UE context errors |
| `NGAP` | `layers/ngap.md` | Core network rejections, PDU session failures |
| `E1AP` | `layers/e1ap.md` | User-plane bearer failures, zero throughput with UE connected |

Use a single combined `grep -E` pass per layer where possible. For very large logs, use `grep -n` to get line numbers first, then read only the relevant ranges.

## 6. Diagnosis and recommendations

Short bulleted diagnosis:
- What is working and what is failing
- Root cause of each problem in 5G/NR protocol terms
- Concrete next steps: config changes, debug logging to enable, what to look for in a pcap
- If only startup with no UE traffic, say so and note what to check next

## 7. Persist new insights

Append new generalisable findings to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file — not to the general analysis guide.

Format: `- YYYY-MM-DD: <what was found and why it matters>`

Worth saving: new log patterns or fields, root causes that took non-trivial reasoning, protocol facts deduced during analysis.

Not worth saving: per-run values (RNTIs, slot numbers, bitrates from a single run).
