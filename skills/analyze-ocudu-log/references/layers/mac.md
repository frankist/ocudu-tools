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

*Append entries here after analysis sessions: date, what was found, why it matters. For RA-specific patterns (PRACH, RAR, Msg3), see `procedures/random-access.md`.*
