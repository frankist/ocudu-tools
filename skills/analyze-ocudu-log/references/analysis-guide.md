# OCUDU Log Analysis — Detailed Steps

## Step 1 — Start from the Run summary

Identify the failure events from the Run summary, then proceed to Step 2.

---

## Progress reporting (Steps 2–4)

After each meaningful finding, report to the user and ask how to proceed:

```
**Found:** <one sentence — what the log shows, specific file/layer/timestamp>
**Next:** <planned action and why>
```

Then ask via `AskUserQuestion` with options:
- **Continue** — proceed as planned
- **Skip to diagnosis** — stop collecting evidence; go to Step 5 with what you have
- **Other** (open text) — redirect to a different area, add context, or ask a question

A finding is meaningful when it: locates a specific failure event, supports or refutes the current hypothesis, or identifies a lead to a different layer or component. Do not report after every individual grep — only when the result changes what you know or what you plan to do next.

**When to ask for clarification:** If evidence is ambiguous, do not speculate. First search the OCUDU source (if available) — the implementation often resolves ambiguous log patterns. If inconclusive, ask the user via `AskUserQuestion`. Typical triggers: multiple plausible root causes with no clear signal; an unfamiliar log pattern; missing context (what the test was supposed to do, what changed since the last passing run). If the answer is a generalisable log insight, save it to the relevant `references/layers/*.md` or `references/procedures/*.md` file.

---

## Step 2 — Locate failure events

For each failure, note its **timestamp and slot** precisely:
- Errors: timestamps already available from the summary
- Metric drops: find the first window where the KPI degrades
- RLF / PRACH failure: grep for the specific event string

```bash
grep -nE 'RLF|radio link failure|PRACH.*fail|msg3_nok=[^0]|Random Access' <logfile>
```

---

## Step 3 — Extract context around each failure

Extract a window before the failure (typically a few seconds back) and the full multiline entry at the failure point when continuation lines carry relevant detail.

---

## Step 4 — Deep-dive by layer or procedure

For failures centred on a specific NR procedure, load the procedure file and follow it — it covers all the relevant layers in one place. For other failures, load the individual layer file(s) implicated by steps 2–3.

Start with the single most-implicated layer. Cross-layer leads always count as meaningful findings — apply the progress reporting rule above before loading any additional layer.

**Procedure files** (`references/procedures/`):

| Failure type | Procedure file | Load when |
|---|---|---|
| PRACH not detected, UE stuck before RRC Setup, Msg3 failures, RAPID mismatch | `procedures/random-access.md` | Any RA or PRACH failure |

**Layer files** (`references/layers/`):

Read only the sections relevant to the observed symptom. Before grepping manually, check whether a parsing script in `references/scripts/` covers the layer:
```bash
cat <logfile> | python3 references/scripts/proc_durations.py --layer <LAYER> [--proc <proc>]
python3 references/scripts/grep_multiline.py <logfile> [grep-options] '<pattern>'
```
Fall back to grep/sed only when no relevant script exists.

| Component tag(s) | Layer file | When to load |
|---|---|---|
| `SCHED` | `layers/sched.md` | HARQ failures, allocation failures, zero throughput, slot decision timing |
| `MAC` | `layers/mac.md` | Cell lifecycle issues, pipeline timing anomalies |
| `DU-MNG` | `layers/du_mng.md` | UE lifecycle procedure latency, cycling scenarios, stuck cycling diagnosis |
| `PHY`, `DU-LOW` | `layers/phy.md` | PHY latency spikes, high LDPC iterations, DTX vs degradation |
| `RRC` | `layers/rrc.md` | Connection drops, RLF, handover, UE stuck after RACH completes |
| `F1AP` | `layers/f1ap.md` | CU–DU interface failures, UE context errors |
| `NGAP` | `layers/ngap.md` | Core network rejections, PDU session failures |
| `E1AP` | `layers/e1ap.md` | User-plane bearer failures, zero throughput with UE connected |
| `OFH` | `layers/ofh.md` | Any non-zero OFH sector/timing metrics anomaly, RACH failures in O-RAN FH deployments, missed UL symbols or PRACH occasions |
| `FAPI` | *(no layer file — search source)* | Timing or API failures between DU-high and DU-low |
| `RLC`, `PDCP`, `SDAP` | *(no layer files — search source)* | User-plane data path above MAC |

Apply the same grep output discipline (Step 2) to all layer-level greps.

---

## Step 5 — Diagnosis and recommendations

Short bulleted diagnosis:
- What is working and what failed
- Root cause in 5G/NR protocol terms
- Concrete next steps: config changes, debug logging to enable, what to look for in a pcap
- If only startup with no UE traffic, say so and note what to check next

---

## Step 6 — Persist new insights

Append new log structure insights to the **Accumulated knowledge** section of the relevant `references/layers/*.md` file. See SKILL.md § Memory for what qualifies — log structure observations only, not bug descriptions or run-specific values.
