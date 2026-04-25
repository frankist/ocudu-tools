# ocudu-tools

Claude Code skills for working with [OCUDU](https://github.com/srsran/ocudu) — an open-source 5G CU/DU implementation. Covers instrumentation, observability, and diagnostics across the OCUDU stack.

## Skills

### analyze-ocudu-log

Analyses log files and console output from any OCUDU application. Activates automatically when you share a log file or unit test output containing OCUDU log lines.

It analyses the log in layers, starting with the cheap aggregate metrics and drilling into specific protocol layers only when anomalies are found.

**Covered layers:**
- `METRICS` — scheduler, MAC, PHY and executor KPI windows
- `SCHED` — slot decisions, PRACH/RACH events, HARQ chains
- `MAC` — cell lifecycle, pipeline timing
- `PHY` — LDPC processing latencies
- `RRC`, `F1AP`, `NGAP`, `E1AP` — control and user-plane signalling (stubs, populated over time)

**Supported log sources:**
- Log files from any OCUDU application: `gnb`, `du`, `cu`, `cu_cp`, `cu_up`
- Console output from unit tests or runtime
- Pasted log snippets

## Installation

Add the marketplace, then install the plugin:

```
/plugin marketplace add frankist/ocudu-tools
/plugin install ocudu-tools
```

Or browse via `/plugin > Discover`.

## Usage

The skill triggers automatically. Examples of what activates it:

- "Why is RACH failing?" (with a log file open)
- "Analyze `/tmp/gnb.log`"
- Pasting console output from a failed unit test that includes OCUDU log lines

## License

BSD 3-Clause — see [LICENSE](LICENSE).
