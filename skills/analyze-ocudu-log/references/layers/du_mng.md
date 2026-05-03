# DU-MNG layer

## What this layer reveals

The DU manager orchestrates UE lifecycle procedures (create, reconfigure, delete) and cell configuration. Its logs show the start and finish of each async procedure with wall-clock timestamps, making it the primary source for procedure latency analysis.

## Component tags

`DU-MNG`

## Key log patterns

### UE lifecycle procedures

```
[DU-MNG  ] [I] ue=N rnti=0xNNNN proc="UE Create": Procedure started....
[DU-MNG  ] [I] ue=N rnti=0xNNNN proc="UE Create": Procedure finished successfully.
[DU-MNG  ] [I] ue=N proc="UE Delete": Procedure started....
[DU-MNG  ] [I] ue=N proc="UE Delete": Procedure finished successfully.
[DU-MNG  ] [I] ue=N proc="UE Reconfig": Procedure started....
```

### DU stop

```
[DU-MNG  ] [I] proc="DU UE Manager stop": Procedure finished successfully.
[DU-MNG  ] [I] proc="DU Stop": Procedure finished successfully.
```

## Parsing script

`references/scripts/proc_durations.py` — measures durations between `Procedure started` and `Procedure finished` lines for any layer/procedure combination, reports top-N slowest with finish timestamps, plus fastest/median/mean.

```bash
# UE Create latency across all cycles
cat <logfile> | python3 references/scripts/proc_durations.py --layer DU-MNG --proc "UE Create" --top 10

# All DU-MNG procedures (UE Create, UE Delete, UE Reconfig, DU Stop, …)
cat <logfile> | python3 references/scripts/proc_durations.py --layer DU-MNG
```

Use when: investigating UE setup latency outliers, comparing cycle-to-cycle creation performance, or identifying whether slowdowns are systematic or intermittent.

## What to look for

- **UE Create duration >> 5 ms**: Healthy range is ~0.5–2 ms. Outliers of 20–40 ms suggest executor queue backlog (e.g. ctrl_exec saturated by many concurrent UE setups or cycling activity).
- **UE Delete procedures before the cycling timer fires**: UEs deleted during `creating` state never get a `gnb_du_ue_f1ap_id` (rrcReject path — see `f1ap.md`). At cycle-end these appear as `"Cannot release: gnb_du_ue_f1ap_id not found"` warnings.
- **Many rapid UE Deletes clustered at a single timestamp**: Usually the controller injecting release commands for all UEs at once (cycling mode).

## Accumulated knowledge

### Stuck cycling: detection via "Cannot release" warnings

`grep "Cannot release.*gnb_du_ue_f1ap_id not found"` during a cycling run identifies UEs deleted during the `creating` state (rrcReject path — these UEs never got a `gnb_du_ue_f1ap_id`). If this count is non-zero and the log contains no subsequent "Guard period elapsed" or "Starting new creation cycle", the release phase is stuck.
