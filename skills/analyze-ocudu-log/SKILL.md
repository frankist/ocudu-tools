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

## Run-mode detection

Determine this from the CONFIG block before interpreting any latency figures:

| Signal | Mode |
|---|---|
| `ru_sdr.device_driver: uhd/bladerf/lime/soapy` | Real SDR — real-time |
| `ru_ofh` section or `OFH` component tags | O-RAN FH RU — real-time |
| `ru_dummy` section or `device_driver: dummy` | Dummy RU — real-time timing, no actual radio |
| `ru_sdr.device_driver: zmq` or `zmq:tx`/`zmq:rx` component tags | ZMQ simulation — not real-time |
| Console/unit test output (no `ru_*` config present) | Unit test — not real-time |

In simulated and no-radio modes, latency analysis is not relevant, so do not mention them.

## Mode

Determine the mode from the user's request before starting:

| Request type | Mode |
|---|---|
| "report", "summary", "what happened", "give me an overview" | **Report** — summarise what occurred |
| "what went wrong", "why did X fail", "analyze", "debug" | **Analysis** — root-cause investigation |
| Ambiguous | Ask the user |

Follow the steps for the selected mode in `references/analysis-guide.md`.

## Unknown log information

If a log line's meaning is unclear and not covered by the layer reference files, look it up in the OCUDU source code. If this skill is currently installed inside a local OCUDU project, search the local project folder directly. Once understood, update the relevant `references/layers/*.md` file. If the source is inconclusive, ask the user.

## Memory

After each analysis, append new generalisable findings to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file. Save root causes, newly seen log patterns, metric keys, or protocol facts — not per-run values (RNTIs, slot numbers, bitrates).

Parsing scripts are also part of accumulated knowledge. When a layer requires complex multi-field parsing that would otherwise need multiple grep passes or produce too many raw lines for efficient analysis, write a Python script and save it to `references/scripts/<layer>.py`. Scripts must:
- Accept a log file path as `sys.argv[1]`
- Print a compact human-readable summary to stdout
- Cover ≥3 structured fields or produce statistical summaries (rates, counts, extremes)

When a script is created or updated, add a `## Parsing script` section to the corresponding layer `.md` file describing what it outputs and when to use it.
