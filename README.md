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

## Contributing

### Branch model

| Branch | Purpose |
|---|---|
| `main` | Stable, shared skills — the version installed by users |
| `<name>` | Personal branch — local improvements, lessons learned, experimental notes |

### Proposing a skill update

1. Branch off `main`: `git checkout -b <your-name>`
2. Make your changes — add knowledge to layer files, refine instructions, fix gaps
3. Run `/ocudu-tools:synthesize-skill-update` to clean up your branch before submitting
4. Open a PR against `main`

### Review process

PRs are reviewed with the `synthesize-skill-update` skill, which extracts the generalisable knowledge from your branch, discards personal or overly specific notes, and merges the result cleanly into `main`. You will receive a summary of what was kept and what was left out.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
