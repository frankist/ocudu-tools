# RRC layer

## What this layer reveals

Radio Resource Control manages UE connection setup, reconfiguration, and release, as well as mobility (handover, CHO, reestablishment) and system information broadcast (SIBs). RRC logs are the right place to look when a UE completes RACH but never reaches a connected state, when connections drop unexpectedly, or when handovers fail.

## Component tags

`RRC`

## Key log patterns

> **Note:** The exact log line formats below are illustrative. Verify against real logs and update this file when the actual format is observed.

### UE connection lifecycle

```
[RRC     ] [I] [sfn.slot] ue=N: RRC Setup
[RRC     ] [I] [sfn.slot] ue=N: RRC Setup Complete
[RRC     ] [I] [sfn.slot] ue=N: Security Mode Complete
[RRC     ] [I] [sfn.slot] ue=N: RRC Reconfiguration Complete
[RRC     ] [I] [sfn.slot] ue=N: UE Context Release
```

### Handover and mobility

```
[RRC     ] [I] [sfn.slot] ue=N: Handover Required — target pci=N
[RRC     ] [I] [sfn.slot] ue=N: Handover Command sent
[RRC     ] [I] [sfn.slot] ue=N: CHO winner selected — target pci=N
[RRC     ] [I] [sfn.slot] ue=N: RRC Reestablishment Request — cause=<reason>
[RRC     ] [I] [sfn.slot] ue=N: RRC Reestablishment Complete
```

### Radio Link Failure

```
[RRC     ] [W] [sfn.slot] ue=N: RLF detected — cause=<reason>
```

## Grep for key events

```bash
# UE connection and release events
grep -iE 'RRC.*Setup|RRC.*Complete|RRC.*Release|RRC.*Reconfig' <logfile>

# Handover and reestablishment
grep -iE 'Handover|CHO winner|Reestablishment|RLF' <logfile>
```

## What to look for

- **UE stuck after RACH with no RRC Setup**: `F1AP` or `NGAP` may have rejected the UE context — cross-check F1AP and NGAP logs.
- **RLF with no preceding metric degradation**: Sudden loss — check PHY LDPC iterations and SNR in the slots before the RLF timestamp.
- **RLF followed immediately by Reestablishment**: Normal recovery path; look for whether Reestablishment Complete follows, or whether the UE is released instead.
- **Rapid RRC Setup + Release cycles**: Handover storm or CHO ping-pong — check `mobility` config and SCHED HARQ for the UE.
- **Missing Reconfiguration Complete after Handover Command**: UE did not respond — possible radio loss during HO execution.

## Accumulated knowledge

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

