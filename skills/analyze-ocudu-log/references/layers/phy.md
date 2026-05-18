# PHY / DU-low layer

## What this layer reveals

The physical layer (DU-low) handles LDPC encoding/decoding, FFT, channel estimation, and the overall DL/UL processing pipeline. Its log entries are most useful for diagnosing CPU-bound processing latency and poor channel conditions (via LDPC iteration counts). Most PHY information is surfaced through the `[METRICS ] PHY metrics:` line rather than per-slot debug entries.

## Component tags

`PHY`, `DU-LOW`, `FAPI` (lower-layer API between DU-high and DU-low)

## Key log patterns

### Processing pipeline latency (via METRICS)

See `layers/metrics.md` — the `PHY metrics:` line contains the key fields:
- `dl_processing_max_latency` / `ul_processing_max_latency`
- `ldpc_encoder_avg_latency` / `ldpc_encoder_max_latency`
- `ldpc_decoder_avg_latency` / `ldpc_decoder_max_latency` / `ldpc_decoder_avg_nof_iter`

## What to look for

- **`ldpc_decoder_avg_nof_iter` > 10**: Decoder is working hard — indicates poor SNR or large TBS at the cell edge.
- **`dl_processing_max_latency` or `ul_processing_max_latency` approaching slot duration**: Risk of missed deadlines in real-time runs.
- **PHY latency spikes co-located with MAC `slot_ind_msg_time_diff` spikes**: Confirms the bottleneck is in the lower PHY chain rather than the scheduler.

## Accumulated knowledge

### DTX vs channel degradation (2026-05-14)

`sinr=infdB iter=6.0 ack=2` on a PUSCH entry = **DTX**: the UE transmitted nothing at that slot.
The gNB ran the LDPC decoder on pure noise, hit the maximum iteration count, and declared KO. This
is NOT a channel quality issue — do not look at RF conditions when you see this pattern.

**Distinguishing DTX from degradation**:

| Symptom | DTX (UE silence) | Degradation (bad channel) |
|---|---|---|
| SINR | `infdB` on all KO entries | Declining dB values (e.g. −10 → −25 → −38) |
| Onset | Sudden — all h_ids fail simultaneously at one slot boundary | Gradual — failures spread across retransmissions |
| `iter` count | Maxed out (e.g. 6.0) | Climbing from nominal toward max |

**When DTX is confirmed**:
1. Note the timestamp of the first KO slot (e.g. `[72.17]`).
2. Note the timestamp of the last `crc=OK` PUSCH (grep backwards from the KO window).
3. Take both timestamps to the Amarisoft `ue.log` — grep for PDCCH entries in the ~500 ms window
   around the silence onset. See `layers/rrc.md` § Amarisoft ZMQ spurious DCI for what to look for.
