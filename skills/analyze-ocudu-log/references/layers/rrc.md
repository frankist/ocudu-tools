# RRC layer

## What this layer reveals

Radio Resource Control manages UE connection setup, reconfiguration, and release, as well as mobility (handover, CHO, reestablishment) and system information broadcast (SIBs). RRC logs are the right place to look when a UE completes RACH but never reaches a connected state, when connections drop unexpectedly, or when handovers fail.

## Component tags

`RRC`

## Key log patterns

### UE connection lifecycle

```
[RRC     ] [I] ue=N c-rnti=0xNNNN: CCCH UL rrcSetupRequest
[RRC     ] [I] ue=N c-rnti=0xNNNN: CCCH DL rrcSetup
[RRC     ] [I] ue=N c-rnti=0xNNNN: DCCH UL rrcSetupComplete
[RRC     ] [I] ue=N c-rnti=0xNNNN: DCCH DL rrcReconfiguration
[RRC     ] [I] ue=N c-rnti=0xNNNN: DCCH UL rrcReconfigurationComplete
```

### Handover and mobility

CU-CP trigger (source UE):
```
[CU-CP   ] [I] ue=N: Trigger intra-CU (intra-DU) handover on du=0
[RRC     ] [I] ue=N c-rnti=0xSRC: DCCH DL rrcReconfiguration           ← HO command (reconfigWithSync)
[RRC     ] [I] ue=M c-rnti=0xTGT: DCCH UL rrcReconfigurationComplete   ← HO complete on target (M = target UE)
[CU-CP   ] [W] ue=M: "Intra CU Handover Target Routine" failed          ← HO timeout (target never arrived)
```

Source cell RLF after HO command sent (DU-local ue ID):
```
[MAC     ] [I] ue=DU_ID: RLF detected. Cause: 100 consecutive HARQ-ACK KOs
```

### Re-establishment

```
[RRC     ] [I] ue=P c-rnti=0xNEW: CCCH UL rrcReestablishmentRequest
[RRC     ] [I] ue=P c-rnti=0xNEW: "RRC Reestablishment Procedure" for old c-rnti=0xSRC, pci=N started...
[RRC     ] [I] ue=P c-rnti=0xNEW: DCCH DL rrcReestablishment
[RRC     ] [I] ue=P c-rnti=0xNEW: DCCH UL rrcReestablishmentComplete
[RRC     ] [I] ue=P c-rnti=0xNEW: "RRC Reestablishment Procedure" for old_ue=N finished successfully
```

## Grep for key events

```bash
# UE connection and release events
grep -E 'rrcSetup|rrcSetupComplete|rrcReconfiguration' <logfile>

# Handover and reestablishment
grep -E 'Trigger intra-CU.*handover|Handover Target Routine|rrcReestablishment' <logfile>

# RLF (note: comes from MAC/DU-MNG, not RRC)
grep -E 'RLF detected|radio link failure' <logfile>
```

## What to look for

- **UE stuck after RACH with no RRC Setup**: `F1AP` or `NGAP` may have rejected the UE context — cross-check F1AP and NGAP logs.
- **RLF with no preceding metric degradation**: Sudden loss — check PHY LDPC iterations and SNR in the slots before the RLF timestamp.
- **RLF followed immediately by Reestablishment**: Normal recovery path; look for whether Reestablishment Complete follows, or whether the UE is released instead.
- **Rapid RRC Setup + Release cycles**: Handover storm or CHO ping-pong — check `mobility` config and SCHED HARQ for the UE.
- **Missing Reconfiguration Complete after Handover Command**: UE did not respond — possible radio loss during HO execution.

## Accumulated knowledge

### Direct RLF re-establishment — CU UE index stays the same (2026-05-22)

When RLF is triggered on the UE's current serving cell (no preceding HO command), OCUDU reuses the existing CU UE context for re-establishment. The CU `ue=` index does **not** change; only the C-RNTI changes.

```
# Before RLF: ue=10 c-rnti=0x460a (active on cell)
[RRC     ] [I] ue=10 c-rnti=0x460b: CCCH UL rrcReestablishmentRequest
[RRC     ] [I] ue=10 c-rnti=0x460b: DCCH DL rrcReestablishment
[RRC     ] [I] ue=10 c-rnti=0x460b: DCCH UL rrcReestablishmentComplete
```

The new C-RNTI (0x460b) comes from the TC-RNTI assigned during the re-establishment PRACH/RAR. The old C-RNTI (0x460a) is in the `rrcReestablishmentRequest` payload (not in the log line itself).

Contrast with **post-HO re-establishment** (T304 expiry): there, a new CU UE context P is created and the log shows `"RRC Reestablishment Procedure" for old_ue=N` where P ≠ N.

During a mass re-establishment event, all UEs trigger PRACH at the same slot with **different** randomly chosen sequence indices — a burst of contention-based preambles:
```
01:43:22.475 [PHY] UL 0001 00  -  110.19 PRACH: sequence_index=62 ...
01:43:22.475 [PHY] UL 0002 00  -  110.19 PRACH: sequence_index=63 ...
01:43:22.475 [PHY] UL 0003 00  -  110.19 PRACH: sequence_index=13 ...
```

### HARQ max retransmissions as RLF trigger (2026-05-22)

RLF can be triggered upstream by SCHED exhausting HARQ retries:
```
[SCHED   ] [I] [SLOT] rnti=0xNNNN h_id=N: Discarding DL HARQ process TB with tbs=NNN. Cause: Maximum number of reTxs 4 exceeded
```

This causes T310 to expire on the UE → the UE initiates re-establishment. On the gNB side, the chain is: SCHED log (above) → `[DU-MNG] RLF detected with cause "MAC max KOs reached"` → `[RRC] rrcReestablishmentRequest`.

Search:
```bash
grep "Maximum number of reTxs.*exceeded" <gnb.log>
```

### "MAC max KOs reached" RLF — investigation path (2026-05-14)

Log pattern (comes from `DU-MNG`, not `RRC`):
```
[DU-MNG] [W] ue=N rnti=0xXXXX: RLF detected with cause "MAC max KOs reached". Timer of 4000 msec to release UE started...
```

This means the gNB exhausted the DL or UL HARQ retry budget. Despite the "MAC" label, the root cause is
almost always at PHY — start there, not at RRC or MAC:

1. Grep `gnb.log` for `PUSCH: rnti=0xXXXX` of `PDSCH: rnti=xXXXX` covering the ~2 s before the RLF timestamp.
2. Check SINR on the KO entries:
   - `sinr=infdB` → **DTX** → follow the DTX path in `layers/phy.md`.
   - SINR < −10 dB → **degradation** → check RF/link conditions and LDPC iteration counts.
3. Use `references/scripts/ue_rlf_trace.py` to automate this triage (see script usage).

