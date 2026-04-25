# ocudu-log-analyzer

A Claude Code skill for analysing log files and console output from [OCUDU](https://github.com/srsran/ocudu) — an open-source 5G CU/DU implementation.

## What it does

The skill automatically activates when you share an OCUDU log file or unit test console output. It analyses the log in layers, starting with the cheap aggregate metrics and drilling into specific protocol layers only when anomalies are found.

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

```
/plugin install ocudu-log-analyzer
```

Or browse via `/plugin > Discover`.

## Usage

The skill triggers automatically. Examples of what activates it:

- "Why is RACH failing?" (with a log file open)
- "Analyze `/tmp/gnb.log`"
- Pasting console output from a failed unit test that includes OCUDU log lines

## License

BSD 3-Clause — see [LICENSE](LICENSE).
