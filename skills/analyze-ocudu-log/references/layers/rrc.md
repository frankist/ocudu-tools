# RRC layer

## What this layer reveals

Radio Resource Control manages UE connection setup, reconfiguration, and release, as well as mobility (handover, CHO, reestablishment) and system information broadcast (SIBs). RRC logs are the right place to look when a UE completes RACH but never reaches a connected state, when connections drop unexpectedly, or when handovers fail.

## Component tags

`RRC`

## Key log patterns

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
grep -E 'RRC.*Setup|RRC.*Complete|RRC.*Release|RRC.*Reconfig' <logfile>

# Handover and reestablishment
grep -E 'Handover|CHO winner|Reestablishment|RLF' <logfile>
```

## What to look for

- **UE stuck after RACH with no RRC Setup**: `F1AP` or `NGAP` may have rejected the UE context — cross-check F1AP and NGAP logs.
- **RLF with no preceding metric degradation**: Sudden loss — check PHY LDPC iterations and SNR in the slots before the RLF timestamp.
- **RLF followed immediately by Reestablishment**: Normal recovery path; look for whether Reestablishment Complete follows, or whether the UE is released instead.
- **Rapid RRC Setup + Release cycles**: Handover storm or CHO ping-pong — check `mobility` config and SCHED HARQ for the UE.
- **Missing Reconfiguration Complete after Handover Command**: UE did not respond — possible radio loss during HO execution.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
