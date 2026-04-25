# METRICS layer

## What this layer reveals

The `METRICS` component emits periodic aggregated KPI reports covering all lower layers. It is the cheapest and most information-dense starting point: a handful of lines summarise the health of the entire cell across a time window without requiring a full log scan. Always read METRICS first to determine whether deeper layer investigation is needed.

## Component tags

`METRICS`

## Key log patterns

### Scheduler cell metrics

```
[METRICS ] Scheduler cell pci=N metrics: total_dl_brate=X.Xbps total_ul_brate=X.Xbps nof_prbs=N nof_dl_slots=N nof_ul_slots=N nof_prach_preambles=N error_indications=N pdsch_rbs_per_slot=X pusch_rbs_per_slot=X pdschs_per_slot=X puschs_per_slot=X failed_pdcch=N failed_uci=N nof_ues=N mean_latency=Xusec max_latency=Xusec max_latency_slot=sfn.slot latency_hist=[...] msg3_ok=N msg3_nok=N late_dl_harqs=N late_ul_harqs=N pucch_tot_rb_usage_avg=X pusch_rbs_per_tdd_slot_idx=[...] pdsch_rbs_per_tdd_slot_idx=[...] avg_prach_delay=N
```

Field reference:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `total_dl_brate` / `total_ul_brate` | Aggregate DL/UL throughput | Zero with UEs present → data-path problem |
| `nof_prach_preambles` | PRACH preambles detected in this window | Non-zero → UEs attempting to connect |
| `msg3_ok` / `msg3_nok` | Msg3 completions / failures | `msg3_nok > 0` → RACH problem; investigate `sched.md` |
| `late_dl_harqs` / `late_ul_harqs` | HARQ processes that missed their deadline | Non-zero → timing stress; relevant only in real-time runs |
| `failed_pdcch` | PDCCH allocation failures | Non-zero → DL control channel congestion |
| `failed_uci` | UCI decode failures | Non-zero → uplink control loss |
| `nof_ues` | Active UEs at end of window | Zero throughout → no UE connected |
| `mean_latency` / `max_latency` | Scheduler slot processing time | Real-time: max > 500 µs is concerning |
| `latency_hist` | Histogram of slot processing times (10 buckets, 100 µs wide) | High counts in buckets 2+ signal latency spikes |
| `error_indications` | Error indication count from lower layers | Any non-zero is significant |
| `avg_prach_delay` | Average slots from PRACH detection to scheduling | Baseline ~7 slots; high values indicate congestion |

### MAC cell metrics

```
[METRICS ] MAC cell pci=N metrics: slots=[sfn.slot, sfn.slot) nof_slots=N slot_duration=Xusec nof_voluntary_context_switches=N nof_involuntary_context_switches=N wall_clock_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] sched_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] dl_tti_req_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] tx_data_req_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] ul_tti_req_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] slot_ind_dequeue_latency=[avg=Xusec max=Xusec max_slot=sfn.slot] slot_ind_msg_time_diff=[avg=Xusec max=Xusec max_slot=sfn.slot]
```

Field reference:

| Field | Meaning | Anomaly signal (real-time only) |
|---|---|---|
| `wall_clock_latency` | Total slot processing wall time | max > 1 ms indicates overload |
| `sched_latency` | Time spent in the scheduler | max > 500 µs indicates scheduler bottleneck |
| `slot_ind_msg_time_diff` | Age of slot indication when dequeued | avg >> `slot_duration` means MAC is falling behind real time |
| `nof_involuntary_context_switches` | OS preemptions during slot processing | High counts indicate CPU contention |

### PHY metrics

```
[METRICS ] PHY metrics: dl_processing_max_latency=X.Xus dl_processing_max_slot=sfn.slot ul_processing_max_latency=X.Xus ul_processing_max_slot=sfn.slot ldpc_encoder_avg_latency=X.Xus ldpc_encoder_max_latency=X.Xus ldpc_decoder_avg_latency=X.Xus ldpc_decoder_max_latency=X.Xus ldpc_decoder_avg_nof_iter=X.X
```

Field reference:

| Field | Meaning | Anomaly signal (real-time only) |
|---|---|---|
| `dl_processing_max_latency` | Peak DL chain processing time | Should be well under 1 slot duration |
| `ul_processing_max_latency` | Peak UL chain processing time | Should be well under 1 slot duration |
| `ldpc_decoder_avg_nof_iter` | Average LDPC decoder iterations | High values (>10) indicate poor channel conditions |
| `ldpc_decoder_max_latency` | Peak LDPC decode time | Extreme values indicate CPU stress |

### Executor metrics

```
[METRICS ] Executor metrics "NAME": nof_executes=N nof_defers=N enqueue_avg=Xusec enqueue_max=Xusec task_avg=Xusec task_max=Xusec cpu_load=X.X% nof_vol_ctxt_switch=N nof_invol_ctxt_switch=N
```

Flag executors with `task_max` > 10 ms or `cpu_load` > 80% — these indicate that a thread is saturated or experiencing OS contention. Relevant only in real-time runs.

### UE metrics (when present)

```
[METRICS ] UE metrics rnti=0xNNNN ...
```

Per-UE throughput and HARQ stats. Useful for identifying which specific UE is degraded when aggregate metrics look healthy.

## What to look for

- **Zero bitrate with `nof_ues > 0`**: UEs connected but no data flowing — check RLC/PDCP or bearer setup.
- **`msg3_nok > 0`**: Investigate SCHED layer for RACH failure details.
- **`late_dl_harqs` or `late_ul_harqs > 0`**: Timing stress — relevant only in real-time runs; investigate MAC and PHY layers.
- **Metrics windows with no scheduler report**: Cell may have restarted or not been active.
- **`slot_ind_msg_time_diff` avg >> slot duration**: MAC falling behind real time — investigate executor CPU load.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
