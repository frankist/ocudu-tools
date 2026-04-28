# F1AP layer

## What this layer reveals

The F1 Application Protocol is the CU–DU interface. F1AP logs show cell setup, UE context establishment and release across the F1 split, and error responses from either side. Useful when diagnosing failures that occur after RACH succeeds but before the UE reaches RRC Connected, or when the DU and CU disagree on cell or UE state.

## Component tags

`F1AP`

## Key log patterns

> **Note:** The exact log line formats below are illustrative. Verify against real logs and update this file when the actual format is observed.

### Cell setup

```
[F1AP    ] [I] F1 Setup Request received
[F1AP    ] [I] F1 Setup Response sent
[F1AP    ] [W] F1 Setup Failure — cause=<reason>
```

### UE context lifecycle

```
[F1AP    ] [I] [sfn.slot] F1 UE context created: rnti=0xNNNN ue_index=N
[F1AP    ] [I] [sfn.slot] F1 UE context released: ue_index=N cause=<reason>
[F1AP    ] [I] [sfn.slot] UE context modification request: ue_index=N
[F1AP    ] [I] [sfn.slot] UE context modification response: ue_index=N
[F1AP    ] [W] [sfn.slot] UE context modification failure: ue_index=N cause=<reason>
```

### Error / release

```
[F1AP    ] [E] F1 interface error: <description>
[F1AP    ] [I] [sfn.slot] UE context release command: ue_index=N cause=<reason>
[F1AP    ] [I] [sfn.slot] UE context release complete: ue_index=N
```

## Grep for key events

```bash
# UE context events
grep -iE 'F1.*context|UE context' <logfile>

# F1 interface setup and errors
grep -iE 'F1 Setup|F1.*error|F1.*failure' <logfile>
```

## What to look for

- **F1 Setup Failure**: DU and CU configuration mismatch — check cell parameters on both sides.
- **UE context created but no RRC Setup follows**: CU-CP may have received the UE context but failed to initiate RRC — check RRC and NGAP logs for the same UE.
- **Rapid F1 UE context created / released cycles**: Handover execution — normal if handover is the scenario; abnormal if no handover was intended.
- **UE context modification failure**: Bearer modification or reconfiguration rejected — often paired with an E1AP or NGAP error for the same UE.
- **F1 interface error**: Connection between CU and DU dropped — all subsequent UE operations will fail until the F1 link is re-established.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
