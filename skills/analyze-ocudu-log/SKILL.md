---
name: analyze-ocudu-log
description: This skill should be used when the user explicitly asks to "analyze a log", "look at the logs", "check the log", "debug from logs", "what does the log say", "look at the pcap", "check the CI job", "investigate this test failure", "why did this CI test fail", "what happened in this run", "analyze the run artifacts", "what's wrong with this job", or shares a path to a .log file, .pcap file, console output file, a folder of run artifacts, or a GitLab CI job URL from an OCUDU application (gnb, du, cu, cu_cp, cu_up). It may also be auto-triggered for failed unit tests or runtime failures that include OCUDU-formatted log output — but only after cheaper methods have been exhausted: first try to diagnose from the test assertion message, stack trace, error summary, or surrounding non-log context. Load this skill only when those simpler signals are insufficient and the OCUDU artifacts themselves are needed to understand the failure.
version: 2.1.0
user-invocable: true
context: fork
agent: Explore
allowed-tools: Bash(ls:*), Bash(grep:*), Bash(cat:*)
---

# Analyze OCUDU Run Artifacts

Analyze artifacts produced by OCUDU applications (`gnb`, `du`, `cu`, `cu_cp`, `cu_up`), by 5G core and UE tools (e.g. amarisoft, Open5GS): structured log files, packet captures, and console output.

## Artifact source

Determine which case applies and follow the corresponding steps:

1. **GitLab CI job URL** — in case of a URL pointing to a test job is provided, load `references/gitlab-ci-job.md` and follow the steps there.

2. **Folder path provided** — the folder contains artifacts from a single run and provides more context than a single log file. Handle as follows:

   **Inventory first:**
   ```bash
   ls -lh <folder>
   ```
   Classify each file by extension:
   | Extension | Type | How to use |
   |---|---|---|
   | `*.log` | OCUDU structured log | Primary analysis source — apply all steps below |
   | `*.pcap`, `*.pcapng` | Packet capture | Binary — use `tshark` (see below); do not `cat` |
   | `*.txt`, `*.out`, `*.stdout` | Console/process output | Read as plain text; look for Python tracebacks, test-runner assertions, startup errors not in the structured log |
   | `*.yml`, `*.yaml` | OCUDU config | Read before touching logs — anchors scenario identification |

   **Reading order:** configs → console output → log files → pcaps (only if needed for protocol-level verification).

   **Multiple log files:** If more than one `.log` is present, check names for component hints (`gnb.log`, `du.log`, `cu_cp.log`, `cu_up.log`). Start with the file whose component is most implicated by the user's question or the detected failure. For a monolithic gNB log, that is always the single file. When in doubt, start with the highest-layer log that covers the failure.

   See **Artifact formats** below for per-type format details and tooling.

   **Cross-file timestamp correlation:** Log and pcap timestamps are both wall-clock (Unix epoch). To correlate, extract an event's timestamp from the log (`grep -n`), convert it to an epoch range, then filter the pcap:
   ```bash
   tshark -r <f> -t ad -Y 'frame.time_epoch >= X.X && frame.time_epoch <= Y.Y'
   ```

3. **File path provided** — check whether the file's directory contains other artifacts from the same run (e.g. other `.log`, `.pcap`, or `.yml` files). If so, ask the user whether to analyse the whole folder instead. If they confirm, apply case 2; otherwise use the file directly.
4. **Log content pasted inline** — analyse the pasted content directly; skip size/efficiency checks (the content is already in context).
5. **Neither** — ask the user to provide a path, paste relevant output, point to a run folder, or share a GitLab CI job URL.

For pasted console or unit test output, expect only a small subset of layers to be present (often just one or two components). Skip sections whose component tags are absent from the output entirely.

## Artifact formats (quick reference)

### Structured log (`.log`)

```
TIMESTAMP [COMPONENT  ] [LEVEL] [sfn.slot] message
```

- `COMPONENT`: 8-char space-padded tag — `GNB`, `SCHED`, `MAC`, `METRICS`, `PHY`, `DU-LOW`, `FAPI`, `DU`, `DU-MNG`, `RLC`, `PDCP`, `SDAP`, `CU-CP`, `CU-UP`, `RRC`, `NGAP`, `F1AP`, `E1AP`, `CONFIG`, `zmq:tx:N:N`, `zmq:rx:N:N`, `OFH`
- `LEVEL`: `[D]` debug · `[I]` info · `[W]` warning · `[E]` error
- `[sfn.slot]`: system frame · slot index — absent on startup/config lines
- Multi-line events: header line + `- key: value` sub-lines (no timestamp prefix)
- Startup CONFIG block: YAML dump of non-default settings after `Input configuration (only non-default values):`

### Packet capture (`.pcap`, `.pcapng`)

Binary format — never read directly. Protocols present: NGAP (N2), F1AP (F1-C), E1AP, XnAP, GTP-U (user plane), SCTP (transport). Timestamps are wall-clock.

Use `tshark` to extract protocol exchanges:
```bash
# List packets with timestamps and protocol
tshark -r <file.pcap> -t ad

# Filter to a specific protocol (e.g. NGAP, F1AP)
tshark -r <file.pcap> -Y 'ngap || f1ap' -t ad

# Decode a specific frame
tshark -r <file.pcap> -V -Y 'frame.number == N'
```

Use pcaps to verify or extend log analysis — e.g. confirm whether an NGAP message was actually sent when the log shows a send attempt, or identify retransmissions. Only pull pcap detail when the log analysis leaves a specific protocol question open.

### Console/process output (`.txt`, `.out`, `.stdout`)

Plain text capturing what was written to the terminal. May contain:
- Application startup banner (version, commit hash, build date)
- Python test framework output (`PASSED`, `FAILED`, `AssertionError`)
- Unhandled exceptions or segfault output not captured in the structured log
- **Sanitizer errors** (`RealtimeSanitizer`, `AddressSanitizer`, `UndefinedBehaviorSanitizer`): appear as `==PID==ERROR: <SanitizerName>: <description>` followed by a stack trace — always a distinct and actionable failure class

## Run summary

Always generate this before any deep analysis. The goal is a quick, factual overview — do not read any log file in full. Follow the detailed steps in `references/summary-guide.md`.

### What to report

- **Scenario**: one sentence identifying what the run was testing (see summary-guide.md § Scenario identification)
- **Setup**: topology (DUs, CUs, cells), UE simulator type, number of UEs, 5G core, RU/radio type, real-time vs simulated, traffic type (iperf/ping)
- **Basic config**: carrier bandwidth, SCS, duplex mode, NTN enabled/disabled, notable non-default settings
- **Errors and warnings**: count and first occurrences of `[E]`/`[W]` log lines; any assertions or exceptions in console output
- **Basic metrics**: peak DL/UL throughput; DL/UL HARQ KO rate

Present this summary to the user, then continue with **Analysis options**.

## Analysis options

After presenting the run summary, offer a numbered menu of analysis options tailored to what was found. If the user already stated their goal upfront (e.g. "analyse why this failed"), skip the full menu — but still state in one sentence what you understood the goal to be and which layer or procedure file you plan to start from, and ask for confirmation before proceeding.

**Always include:**
- If the run came from a failed CI job or unit test: **"Investigate why the job/test failed"**
- **"Other — describe what you'd like to investigate"** (always last)

**Add based on summary findings:**

| Finding in summary | Option to offer |
|---|---|
| HARQ KO rate > 5% | Investigate DL/UL HARQ failures |
| `[E]` or `[W]` log lines present | Investigate the errors/warnings found |
| RLF events detected | Investigate radio link failure |
| Handover scenario identified | Trace the handover procedure |
| Zero or low throughput with UEs attached | Investigate zero/low throughput |
| PRACH/random access events | Investigate random access failures — load `references/procedures/random-access.md` |
| OFH anomalies (`nof_skipped_symbols > 0`, `nof_missed_prach_occasions > 0`, `tx_kpis` non-zero) | Investigate OFH/fronthaul timing issues |

Wait for the user's reply before proceeding. Once they select an option (or confirm the stated-goal interpretation), before starting deep analysis state which layer or procedure file you will investigate first and why, and ask the user to confirm or redirect.

**Efficiency rules — apply throughout all analysis steps:**
- Never read a log file whole. Use targeted `grep` and `sed` line ranges.
- Before any grep that may return many lines: count first (`grep -c`), then cap output (`grep -m N`). Never pipe an unbounded grep result into context.
- Use `references/scripts/grep_multiline.py` to extract full multiline entries instead of reading surrounding line ranges when the entry structure matters.
- Run parsing scripts in `references/scripts/` before resorting to manual grep passes.

## Unknown artifact information

If a log line or protocol event's meaning is unclear and not covered by the layer reference files, look it up in the OCUDU source code. If this skill is currently installed inside a local OCUDU project, search the local project folder directly. Once understood, update the relevant `references/layers/*.md` file. If the source is inconclusive, ask the user.

## Memory

After each analysis, append new generalisable findings to the **Accumulated knowledge** section of the relevant reference file:
- `references/layers/*.md` — for layer-specific patterns (scheduling, PHY metrics, RRC events, etc.)
- `references/procedures/*.md` — for procedure-specific patterns that span multiple layers (RA, handover, etc.)

Save **log structure insights only**: newly seen log patterns, what a sequence of lines indicates, how to distinguish two superficially similar conditions, or what a field value means. Do **not** save bug descriptions, root causes, implementation details, fix summaries, or numerical observations from a specific run.

Parsing scripts are also part of accumulated knowledge. When parsing would otherwise require multiple grep passes or produce too many raw lines for efficient analysis, write a Python script and save it to `references/scripts/`. Scripts must:
- Import shared helpers from `references/scripts/utils.py` (timestamp parsing) rather than duplicating them
- Read log content from stdin, so they compose with pipes and work on both whole files and filtered subsets
- Print a compact human-readable summary to stdout
- Cover ≥3 structured fields or produce statistical summaries (rates, counts, extremes)
- Be **general when the log structure appears across multiple layers** — use CLI flags (e.g. `--layer`, `--proc`) to filter, so one script handles all variants. Hard-code a specific layer or procedure only when the structure is unique to that component.

Name scripts by analytical function (`proc_durations.py`), not by layer or procedure. When a script is created or updated, update the `## Parsing script` section in each relevant layer `.md` file to show the exact invocation with the appropriate flags for that layer's use case.

### Maintenance

When the user says "reorganize log knowledge", or whenever outdated or inconsistent information is found in the reference files during an analysis session:

1. Read relevant files under `references/`
2. Fix wrong or outdated information (log patterns, field names, grep commands)
3. Remove or merge redundant and duplicate entries across files
4. Reorganize content within a file if the structure has become unclear.
