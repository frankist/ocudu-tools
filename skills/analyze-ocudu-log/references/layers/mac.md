# MAC layer

## What this layer reveals

The MAC layer sits between the scheduler and the lower PHY. Its log entries cover cell lifecycle events, timing of the slot processing pipeline (from slot indication receipt to TTI request delivery), and the metric report triggers that cause METRICS lines to be emitted. MAC logs are most useful for diagnosing pipeline timing issues and confirming cell activation state.

## Component tags

`MAC`

## Key log patterns

### Cell lifecycle

```
[MAC     ] [I] [sfn.slot] cell=N: Cell was activated
[MAC     ] [I] [sfn.slot] cell=N: Cell was stopped.
```

### Metric report trigger

```
[MAC     ] [D] [sfn.slot] Metric report of N cells completed for slots=[sfn.slot, sfn.slot)
```

Emitted just before the corresponding `[METRICS ]` lines. The slot range identifies the window covered by the following metrics.

## What to look for

- **Cell activated but no scheduler metrics follow**: DU-high may have stalled before reaching steady state.
- **Large gap between metric report trigger slot and the wall-clock timestamp**: Indicates the MAC thread is running behind real time.

## Accumulated knowledge

### Amarisoft UE RACH log patterns (2026-05-18)

Amarisoft UE MAC logs use a distinct format. Key patterns for diagnosing Random Access failures:

- `[MAC] DL ... RAR: rapid=N` — UE received an RAR carrying RAPID=N.
- `[MAC] ... ta=X ul_grant=0xHHH tc_rnti=0xYYYY` — UE accepted the RAR and will send Msg3.
- If `RAR: rapid=N` appears but the `ta=X ul_grant=...` line is **absent**, the UE rejected the RAR: the RAPID in the RAR did not match the preamble the UE transmitted. This means the gNB decoded or reported a different preamble index than what the UE sent — the gNB will then schedule Msg3 on the wrong RNTI and decode empty PRBs (`crc=KO sinr=infdB iter=max` on the gNB side).
