# METRICS layer

## What this layer reveals

The `METRICS` component emits periodic aggregated KPI reports covering all lower layers. METRICS lines are sparse but information-dense: a handful summarise cell health across a time window and quickly identify which layers need deeper investigation.

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

### OFH metrics

```
[METRICS ] OFH timing metrics: nof_skipped_symbols=X skipped_symbols_max_burst=X symbol_notification_max_latency=X.XXus symbol_notification_avg_latency=X.XXus

[METRICS ] OFH sector#X metrics: pci=N received messages stats: rx_total=X rx_early=X rx_on_time=X rx_late=X earliest_msg_us=-X.XX latest_msg_us=X.XX, nof_missed_uplink_symbols=X nof_missed_prach_occasions=X ether_rx: cpu_usage=X.X% max_latency=X.XXus avg_latency=X.XXus throughput=X.XMbps rx_bytes=X; ether_tx: cpu_usage=X.X% max_latency=X.XXus avg_latency=X.XXus throughput=XMbps tx_bytes=X; ecpri: nof_past_seqid_msg=X nof_future_seqid_msg=X; rcv_prach: nof_dropped_msg=X cpu_usage=X.X% max_latency=Xus avg_latency=Xus; rcv_ul: nof_dropped_msg=0 cpu_usage=X% max_latency=X.XXus avg_latency=X.XXus; tx_dl_up: cpu_usage=XX.X% dl_up_max_latency=X.XXus dl_up_avg_latency=X.XXus; tx_dl_cp: cpu_usage=X% dl_cp_max_latency=X.XXus dl_cp_avg_latency=X.XXus; tx_ul_cp: cpu_usage=X.X% ul_cp_max_latency=X.XXus ul_cp_avg_latency=X.XXus; message_tx: cpu_usage=X.X% max_latency=X.XXus avg_latency=X.XXus; tx_kpis: nof_late_dl_rgs=X nof_late_ul_req=X nof_late_cp_dl=X nof_late_up_dl=X nof_late_cp_ul=X
```

OFH operation poses real-time requirements on the system.

#### OFH timing metrics field reference:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `nof_skipped_symbols` | Number of symbols the OFH Realtime worker skipped while polling the system time | Should stay zero, otherwise the system has real-time issues |
| `skipped_symbols_max_burst` | Maximum number of skipped consecutive symbols | Should stay zero. Otherwise the values > 3 indicate the system requires RT tuning |
| `symbol_notification_max_latency` | Worst-case latency of notifying the new symbol start to DU-low | The value should be significantly less than OFDM symbol duration |


#### OFH sector metrics
Sector metrics are formatted as `received messages stats: key=value; ether_rx: key=value; ether_tx: key=value; ecpri: key=value; rcv_prach: key=value; rcv_ul: key=value; tx_dl_up: key=value; tx_dl_cp: key=value; tx_ul_cp: key=value; message_tx: key=value; tx_kpis: key=value`

##### Field reference for `received messages stats` set:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `rx_total` | Total number of UL messages received from the RU | Must not be zero once UL C-Plane messages were sent to the RU |
| `rx_early` | Number of UL messages arrived before the start of reception window | Not a concern on its own, `ta4_min` parameter may need to be reduced |
| `rx_on_time` | Number of UL messages arrived within the reception window | Ideally `rx_total == rx_on_time` |
| `rx_late` | Number of UL messages arrived after the reception window closed | Should stay zero, late packets are dropped |
| `earliest_msg_us` | Earliest UL message arrival offset relative to OTA — negative means the packet arrived early | Should be a positive value within the reception window (`ta4_min` to `ta4_max`) |
| `latest_msg_us` | Latest UL message arrival offset relative to OTA | Should be within the reception window (`ta4_min` to `ta4_max`) |
| `nof_missed_uplink_symbols` | Number of expected but not received UL messages | Must be 0. Non-zero value means the DU sent an UL C-Plane type 1 (UL scheduling) message to the RU, but received no UL U-Plane data in response |
| `nof_missed_prach_occasions` | Number of expected but not received UL PRACH messages | Must be 0. Non-zero value means the DU sent a C-Plane type 3 (PRACH) message to the RU, but received no UL PRACH U-Plane data in response |


##### Field reference for `ether_rx` and `ether_tx` sets:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `rx_bytes` | Total number of bytes received over the Ethernet link | Must not be zero all the time when the DU sends UL C-Plane messages to the RU (i.e. the `tx_ul_cp` metrics are non-zero) |
| `tx_bytes` | Total number of bytes transmitted over the Ethernet link | Must be greater than zero, otherwise the link is down |
| `max_latency`| Maximum latency of receiving or transmitting a burst of Ethernet packets | Expected to be in the order of microseconds |

##### Field reference for `ecpri` set (eCPRI sequence ID stats):

| Field | Meaning | Anomaly signal |
|---|---|---|
| `nof_past_seqid_msg` | Packets whose eCPRI sequence ID is from the past (`nof_skipped_seq_id < 0`) | Must be zero, otherwise such UL messages are dropped |
| `nof_future_seqid_msg` | Packets whose eCPRI Sequence ID jumped forward (`nof_skipped_seq_id > 0`) | Non-zero value implies packets were lost in the network or the RU didn't send them |

Dropped packets number may correlate with the `nof_missed_uplink_symbols` and `nof_missed_prach_occasions`.

##### Field reference for `rcv_prach` and `rcv_ul` sets:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `max_latency` | Maximum latency of U-Plane message decoding (including decompression) | Expected to be lower than OFDM symbol duration |
| `nof_dropped_msg` | Number of UL messages dropped during decoding | Must be zero, otherwise some UL messages were dropped (see the conditions below) |

Drop conditions for `rcv_ul`:
- U-Plane decode failure (malformed packet);
- Invalid or reserved filter index, or a PRACH filter index arriving on the UL flow;
- Missing context for writing resulting IQ symbols;
- Context parameters were not set for the decoded eAxC;
- Symbol index outside the range indicated in the C-Plane message (= in the context);
- PRB ranges inconsistent with the C-Plane context;
- Failed write to the resource grid.

Drop conditions for `rcv_prach` (`nof_dropped_msg` increments on):
- U-Plane decode failure (malformed packet);
- Filter index is not a valid PRACH type, or does not match the C-Plane context;
- Symbol index outside the range indicated in the C-Plane message (= context);
- PRB ranges inconsistent with the C-Plane context;
- Failed write to the PRACH buffer.

##### Transmission data-plane sets `tx_dl_up`, `tx_dl_cp` and `tx_ul_cp`:

Flag the spikes in `cpu_usage` > 80% and spikes in `dl_up_max_latency`, `dl_cp_max_latency` and `ul_cp_max_latency`.

##### Message transmitter `message_tx` set:

Flag the spikes in the `cpu_usage` and `max_latency`. Since transmitter works in the same thread as Ethernet receiver, high `max_latency` may also cause the Ethernet receiver to miss incoming packets (they will be dropped by the NIC).

##### Field reference for transmitted messages stats `tx_kpis`:

| Field | Meaning | Anomaly signal |
|---|---|---|
| `nof_late_dl_rgs` | PHY handed a DL resource grid to OFH too close to (or after) the transmission window deadline (defined by OFH proc. latency and `t1a_max_cp_dl`/`t1a_max_up`) | Must be zero, otherwise data for the entire DL slot are dropped |
| `nof_late_ul_req` | PHY handed an UL scheduling request to OFH too close to (or after) the transmission window deadline for UL C-Plane (defined by `t1a_max_cp_ul`) | Must be zero, otherwise request is dropped -> no UL data will be sent by the RU -> retransmission will be scheduled by the higher layers |
| `nof_late_cp_dl` | DL C-Plane message encoded/compressed too late to be sent inside the configured DL CP Tx window | Must be zero |
| `nof_late_up_dl` | DL U-Plane message encoded/compressed too late to be sent inside the configured DL UP Tx window | Must be zero |
| `nof_late_cp_ul` | UL C-Plane message encoded/compressed too late to be sent inside the configured UL CP Tx window | Must be zero |


### Executor metrics

```
[METRICS ] Executor metrics "NAME": nof_executes=N nof_defers=N enqueue_avg=Xusec enqueue_max=Xusec task_avg=Xusec task_max=Xusec cpu_load=X.X% nof_vol_ctxt_switch=N nof_invol_ctxt_switch=N
```

Flag executors with `task_max` > 10 ms or `cpu_load` > 80% — these indicate that a thread is saturated or experiencing OS contention. Relevant only in real-time runs.

### UE metrics (when present)

```
[METRICS ] UE metrics rnti=0xNNNN pci=N dl_brate=X.Xbps ul_brate=X.Xbps dl_nok=N dl_ok=N ul_nok=N ul_ok=N
```

Per-UE throughput and HARQ stats. Useful for identifying which specific UE is degraded when aggregate metrics look healthy.

| Field | Meaning |
|---|---|
| `dl_brate` / `ul_brate` | Per-UE DL/UL throughput (bps) |
| `dl_nok` / `dl_ok` | DL HARQ KO / OK counts for this UE |
| `ul_nok` / `ul_ok` | UL HARQ KO / OK counts for this UE |

HARQ KO rate per UE: `dl_nok / (dl_ok + dl_nok)`. Sum across all UE lines for the aggregate run KO rate.

## What to look for

- **Zero bitrate with `nof_ues > 0`**: UEs connected but no data flowing — check RLC/PDCP or bearer setup.
- **`msg3_nok > 0`**: Investigate SCHED layer for RACH failure details.
- **`late_dl_harqs` or `late_ul_harqs > 0`**: Timing stress — relevant only in real-time runs; investigate MAC and PHY layers.
- **Metrics windows with no scheduler report**: Cell may have restarted or not been active.
- **`slot_ind_msg_time_diff` avg >> slot duration**: MAC falling behind real time — investigate executor CPU load.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
