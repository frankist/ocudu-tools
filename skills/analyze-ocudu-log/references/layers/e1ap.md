# E1AP layer

## What this layer reveals

The E1 Application Protocol is the CU-CP–CU-UP interface. E1AP logs show bearer setup and release for the user-plane split. Useful when diagnosing data-plane failures where control-plane setup appears to succeed (UE is RRC Connected, NGAP InitialContextSetup succeeded) but no user data flows.

## Component tags

`E1AP`

## Key log patterns

> **Note:** The exact log line formats below are illustrative. Verify against real logs and update this file when the actual format is observed.

### CU-UP registration

```
[E1AP    ] [I] E1 Setup Request received
[E1AP    ] [I] E1 Setup Response sent
[E1AP    ] [W] E1 Setup Failure — cause=<reason>
```

### Bearer context lifecycle

```
[E1AP    ] [I] [sfn.slot] Bearer context setup request: ue_index=N
[E1AP    ] [I] [sfn.slot] Bearer context setup response: ue_index=N
[E1AP    ] [W] [sfn.slot] Bearer context setup failure: ue_index=N cause=<reason>
[E1AP    ] [I] [sfn.slot] Bearer context modification request: ue_index=N
[E1AP    ] [I] [sfn.slot] Bearer context modification response: ue_index=N
[E1AP    ] [I] [sfn.slot] Bearer context release command: ue_index=N cause=<reason>
[E1AP    ] [I] [sfn.slot] Bearer context release complete: ue_index=N
```

## Grep for key events

```bash
# Bearer context events
grep -iE 'Bearer context|bearer.*setup|bearer.*release' <logfile>

# E1AP interface setup and errors
grep -iE 'E1.*setup|E1.*error|E1.*failure' <logfile>
```

## What to look for

- **Bearer context setup failure**: CU-UP could not establish the user-plane bearer — check GTP-U endpoint config and CU-UP logs. This directly causes zero throughput despite a connected UE.
- **Zero DL/UL throughput with `nof_ues > 0`**: If RRC and NGAP show successful setup, look for a missing or failed bearer context here. A bearer that was never set up (or was released early) produces this symptom.
- **Bearer context modification failure during handover**: Handover requires bearer modification to update the UL GTP tunnel endpoint; failure here leaves the UE connected but with a broken data path.
- **E1 Setup Failure**: CU-UP not accepted by CU-CP — configuration mismatch; check PLMN or capacity parameters.
- **E1 interface error / CU-UP disconnected**: All user-plane bearers for all UEs are lost; throughput drops to zero immediately.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
