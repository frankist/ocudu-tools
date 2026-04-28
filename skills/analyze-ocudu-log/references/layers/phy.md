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

*Append entries here after analysis sessions: date, what was found, why it matters.*
