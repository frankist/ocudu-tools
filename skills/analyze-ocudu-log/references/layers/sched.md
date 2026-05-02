# SCHED layer

## What this layer reveals

The scheduler (`SCHED`) is the heart of the DU. At debug level it logs every slot decision and every event processed, making it the primary source for diagnosing radio access failures: RACH outcomes, HARQ retransmission chains, resource allocation conflicts, and per-UE scheduling behaviour.

## Component tags

`SCHED`

## Key log patterns

### Slot decisions

Emitted every scheduled slot. The header summarises what was allocated; sub-lines list individual grants.

```
[SCHED   ] [D] [sfn.slot] Slot decisions pci=N t=Xus (N PDSCHs, N PUSCHs, N PUCCHs, N attempted PDCCHs, N attempted UCIs):
- DL PDCCH: rnti=0xNNNN type=<rnti-type> cs_id=N ss_id=N format=<fmt> cce=N al=N
- DL PDSCH: rnti=0xNNNN rb=[start..end) symb=[start..end) tbs=N mcs=N rv=N nof_layers=N
- RAR PDSCH: ra-rnti=0xNNNN rb=[start..end) symb=[start..end) tbs=N mcs=N rv=N grants (N): tc-rnti=0xNNNN: rapid=N ta=N time_res=N result=fallbackRAR|msgb
- UL PDCCH: rnti=0xNNNN type=<rnti-type> cs_id=N ss_id=N format=<fmt> cce=N al=N dci: h_id=N ndi=N rv=N mcs=N tpc=N
- UE PUSCH: ue=N rnti=0xNNNN h_id=N rb=[start..end) symb=[start..end) tbs=N rv=N nrtx=N nof_layers=N [k2=N|msg3_delay=N]
- UE PUCCH: rnti=0xNNNN ...
```

Key fields:
- `t=Xus`: time spent producing this slot's decisions — high values indicate scheduler overload
- `nrtx=0`: initial transmission; `nrtx>0`: retransmission
- `rv`: redundancy version (0/2/3/1 in standard sequence)
- `result=fallbackRAR`: gNB responded with 4-step RAR to a 2-step MsgA preamble
- `result=msgb`: gNB sent MsgB (2-step RAR) — 2-step procedure succeeded
- `msg3_delay=N`: this PUSCH grant is the Msg3 (N slots after the RAR)

### Processed slot events

Aggregates PHY-layer events received in this slot (PRACH detections, HARQ feedback, etc.).

```
[SCHED   ] [D] [sfn.slot] Processed slot events pci=N:
- PRACH: slot=sfn.slot preamble=N msgb-rnti=0xNNNN temp_crnti=0xNNNN ta_cmd=N
- HARQ feedback: rnti=0xNNNN h_id=N ack=<ack|nack>
```

PRACH sub-line fields:
- `preamble`: index of the detected preamble
- `msgb-rnti`: non-zero → preamble classified as 2-step (MsgA); the gNB will decide whether to send MsgB or fallbackRAR
- `temp_crnti`: TC-RNTI assigned to this attempt
- `ta_cmd`: timing advance

### HARQ discard

```
[SCHED   ] [I] [sfn.slot] rnti=0xNNNN h_id=N: Discarding UL HARQ process TB with tbs=N. Cause: <reason>
[SCHED   ] [I] [sfn.slot] rnti=0xNNNN h_id=N: Discarding DL HARQ process TB with tbs=N. Cause: <reason>
```

Common causes:
- `Maximum number of reTxs N exceeded`: HARQ chain exhausted — indicates persistent decode failure
- `HARQ process timeout`: MAC reset or UE context release during an active HARQ process

### Msg3 allocation failure

```
[SCHED   ] [D] [sfn.slot] pci=N tc-rnti=0xNNNN: Failed to allocate PUSCH Msg3 reTx grant in slot sfn.slot. Retrying it in a later slot. Cause: <reason>
```

Common causes:
- `Not enough available RBs`: the target UL slot is fully occupied — likely by pre-reserved resources or concurrent allocations

### Cell lifecycle

```
[SCHED   ] [I] [sfn.slot] cell=N: Cell scheduling was activated.
[SCHED   ] [I] [sfn.slot] cell=N: Cell scheduling was deactivated.
```

## What to look for

- **All RARs are `fallbackRAR`**: The gNB is not sending MsgB for any 2-step preamble. Either MsgA PUSCH decode is failing consistently, or there is a configuration mismatch.
- **`msg3_nok > 0` in METRICS + Msg3 allocation failures**: A resource reservation is blocking the Msg3 reTx UL slot — cross-check what else is allocated in that slot.
- **`nrtx` reaching max on every HARQ chain**: Persistent UL decode failures — check PHY layer (LDPC iterations, SNR).
- **Slot decision `t=` growing over time**: Scheduler taking longer per slot — may indicate O(n) scaling with UE count.
- **Cluster of HARQ discards in a short slot range**: Sudden channel degradation or UE context release storm.

## Two-step RACH classification

With `nof_cb_preambles_per_ssb: N` configured, preambles 0–(N−1) are 4-step CB preambles; preambles ≥ N are 2-step (MsgA) preambles. A PRACH event with a non-zero `msgb-rnti` confirms the preamble was classified as 2-step.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
