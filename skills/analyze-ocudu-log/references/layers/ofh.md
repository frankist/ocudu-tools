# OFH layer (Open FrontHaul / Split 7.2)

## What this layer reveals

The OFH layer manages the eCPRI/Ethernet fronthaul between the DU (Distributed Unit) and the Radio Unit (RU). Its metrics expose the Ethernet stats, timing health of the DL transmission and UL reception, CPU load of DL and UL processing chains, eCPRI sequence-ID anomalies. It is the primary diagnostic source for RU connectivity issues, timing misalignment between RU and DU, and dropped or missed UL data.

## Component tags

`OFH`

## Key log patterns

### OFH metrics

See `layers/metrics.md`. 

### Warnings and info messages

`Real-time timing worker woke up late, skipped '{}' symbols` — logged at `[I]` for delta > 1, `[W]` for delta ≥ 3, and `[W]` again with a slot-level summary for delta ≥ nof_symbols_per_slot. Directly feeds `nof_skipped_symbols` in the OFH timing metrics. A delta ≥ nof_symbols_per_slot means the timing thread was stalled for an entire slot — a much more severe event than a single skipped symbol.

`missed incoming User-Plane uplink messages for slot` — check `nof_dropped_msg` in `rcv_ul` metrics. Non-zero means messages were received but dropped inside the DU. When `nof_dropped_msg` is zero, the UL C-Plane message was likely not received by the RU — tune the C-Plane transmission timing window and check RX KPIs on the RU. Also reported as `nof_missed_uplink_symbols > 0` in sector metrics.

`missed incoming User-Plane PRACH messages for slot` — check `nof_dropped_msg` in `rcv_prach` metrics. Non-zero means PRACH U-Plane was received but dropped inside the DU. When zero, the PRACH C-Plane did not reach the RU. Verify `is_prach_cp_enabled: true` if the RU requires PRACH C-Plane, and confirm compression parameters match between DU and RU. Also reported as `nof_missed_prach_occasions > 0`.

`dropped received Open Fronthaul User-Plane packet as decoded eAxC value '{}' is not ...` — `[I]` level. eAxC ID mismatch between DU config and what the RU is sending. Check `ul_eaxc`/`prach_eaxc` configuration.

`dropped received Open Fronthaul User-Plane packet for eAxC value '{}' as sequence identifier field is from the past` — `[I]` level. Increments `nof_past_seqid_msg`. Indicates out-of-order or duplicate packets from the network or RU.

`potentially lost '{}' messages sent by the RU` — `[W]` level. Increments `nof_future_seqid_msg`. Sequence ID jumped forward — packets were dropped in the network between RU and DU.


## What to look for

- **`nof_skipped_symbols > 0`**: Critical — must stay at zero. The DU missed a symbol boundary, indicating severe CPU overload or OS scheduling jitter on the timing thread.
- **`rx_total = 0` on an active sector**: No Ethernet traffic received from the RU at all (`rx_bytes` will also be zero). Likely causes: wrong VLAN tag (`vlan_tag_cp`/`vlan_tag_up`), wrong eAxC ID, or the RU is not transmitting. A sector with no UEs is expected to have `rx_total=0` for UL data, but PRACH occasions should still be visible.
- **`nof_missed_uplink_symbols > 0`**: DU scheduled UL but the RU did not deliver the data. The most common cause is the C-Plane message arriving too early or too late at the RU and being dropped on the RU side. Tune the C-Plane transmission timing window.
- **`nof_missed_prach_occasions > 0`**: PRACH C-Plane sent but no UL U-Plane returned. Same root cause as above (C-Plane timing); will manifest as failed RACH in the `SCHED` layer.
- **`rx_late > 0`**: UL messages arriving after the DU's receive window. The fronthaul network has excess jitter or the RU's timing offset is misconfigured.
- **`nof_past_seqid_msg > 0`**: eCPRI packets arriving out of order or duplicated; dropped by the receiver. Check the Ethernet switch between DU and RU for reordering. Lower the OFH log level to `info` to see the accompanying per-packet drop message.
- **`nof_future_seqid_msg > 0`**: Sequence ID gaps — the network dropped packets between the RU and DU. Check for switch buffer overflows or misconfigured QoS/VLAN priorities.
- **`rcv_ul` or `rcv_prach: nof_dropped_msg > 0`**: The receive processing pipeline is discarding packets. Lower the OFH log level to `info` to see the specific drop reason (decode failure, filter mismatch, symbol out of range, etc.).
- **Any `tx_kpis` counter > 0**: Transmission deadlines are being missed. `nof_late_dl_rgs`/`nof_late_ul_req` point to the PHY being too slow delivering work to OFH; cross-check with `PHY metrics: dl_processing_max_latency`. `nof_late_cp_*`/`nof_late_up_dl` point to encoding/compression taking too long; check `tx_dl_up dl_up_max_latency` for spikes.
- **`dl_up_max_latency` spike in `tx_dl_up`**: DL IQ compression is intermittently slow — may indicate CPU contention on the OFH transmit thread.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
