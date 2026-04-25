---
name: analyze-ocudu-log
description: This skill should be used when the user explicitly asks to "analyze a log", "look at the logs", "check the gnb log", "debug from logs", "what does the log say", or shares a path to a .log file from an OCUDU application (gnb, du, cu, cu_cp, cu_up). It may also be auto-triggered for failed unit tests or runtime failures that include OCUDU-formatted log output — but only after cheaper methods have been exhausted: first try to diagnose from the test assertion message, stack trace, error summary, or surrounding non-log context. Load this skill only when those simpler signals are insufficient and the OCUDU log lines themselves are needed to understand the failure.
version: 1.0.0
---

# Analyze OCUDU Log

Analyze log files produced by OCUDU applications (`gnb`, `du`, `cu`, `cu_cp`, `cu_up`).

## Log source

Three cases, in order of priority:

1. **File path provided** — use it directly.
2. **Log content pasted inline** — analyse the pasted content directly; skip size/efficiency checks (the content is already in context).
3. **Neither** — ask the user to provide a path or paste the relevant log output.

For pasted console or unit test output, expect only a small subset of layers to be present (often just one or two components). Skip sections whose component tags are absent from the output entirely.

## Log format (quick reference)

```
TIMESTAMP [COMPONENT  ] [LEVEL] [sfn.slot] message
```

- `COMPONENT`: 8-char space-padded tag — `GNB`, `SCHED`, `MAC`, `METRICS`, `DU`, `DU-MNG`, `CU-CP`, `CU-UP`, `RRC`, `NGAP`, `F1AP`, `E1AP`, `CONFIG`, `zmq:tx:N:N`, `zmq:rx:N:N`, `OFH`
- `LEVEL`: `[D]` debug · `[I]` info · `[W]` warning · `[E]` error
- `[sfn.slot]`: system frame · slot index — absent on startup/config lines
- Multi-line events: header line + `- key: value` sub-lines (no timestamp prefix)
- Startup CONFIG block: YAML dump of non-default settings after `Input configuration (only non-default values):`

## Efficiency rules

Logs can exceed 1 GB — never read the file whole.

- Use `wc -l` first to gauge size; use `grep -c` to count matches before fetching lines
- Always grep METRICS lines first — they are sparse and drive whether deeper sections are needed
- Combine RACH/HARQ patterns into a single `grep -E` pass over the file

## Run-mode detection

Determine this from the CONFIG block before interpreting any latency figures:

| Signal | Mode |
|---|---|
| `ru_sdr.device_driver: zmq` or `zmq:tx`/`zmq:rx` component tags | Simulated (ZMQ) — not real-time |
| `ru_sdr.device_driver: uhd/bladerf/lime/soapy` | Real SDR hardware — real-time |
| `ru_ofh` section or `OFH` tags | O-RAN FH hardware — real-time |
| No `ru_sdr` / `ru_ofh`, or console/unit test output | No radio — latency irrelevant |

In simulated and no-radio modes, skip commentary on wall-clock latency spikes, `slot_ind_msg_time_diff`, and PHY processing latency.

## Analysis order

Follow the detailed steps in `references/analysis-guide.md`. The top-level order is:

1. Overview (build info, time span, components, log levels, cell active range)
2. Active configuration and run-mode
3. Errors and warnings
4. **Metrics analysis** — always first; use findings to decide what deeper investigation is needed
5. Deep-dive analysis — load only the relevant layer file(s) from `references/layers/` based on which components show anomalies
6. Diagnosis and recommendations
7. Persist new insights to the relevant layer file

## Memory

After each analysis, append new generalisable findings to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file. Save root causes, newly seen log patterns, metric keys, or protocol facts — not per-run values (RNTIs, slot numbers, bitrates).
