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

## Test mode patterns

The `[DU-F1  ]` tag (not `[F1AP]`) is used for F1AP UE context events at the DU side:

```
[DU-F1   ] [I] ue=N c-rnti=0xNNNN du_ue=N: F1 UE context removed.
```

### Test mode cycling — release injection

```
[DU      ] [I] TEST_MODE: Injecting UE Context Release Command for rnti=0xNNNN
[DU      ] [W] TEST_MODE: Cannot release rnti=0xNNNN: gnb_du_ue_f1ap_id not found
[DU      ] [W] TEST_MODE: Cannot release rnti=0xNNNN: gnb_cu_ue_f1ap_id not found
```

`gnb_du_ue_f1ap_id not found` means the UE took the rrcReject path (`!du_to_cu_rrc_container_present` in `InitialULRRCMessageTransfer`) — it was never assigned an ID and was deleted early. `gnb_cu_ue_f1ap_id not found` means the UE connected but was already deleted from F1AP before the release attempt.

### Test mode cycling — lifecycle transitions

```
[DU      ] [I] TEST_MODE: All N UE(s) on cell=N established. Running for N slots.
[DU      ] [I] TEST_MODE: Attach/detach duration elapsed on cell=N. Releasing N UE(s).
[DU      ] [I] TEST_MODE: All UE(s) released on cell=N. Entering guard period.
[DU      ] [I] TEST_MODE: Guard period elapsed on cell=N. Starting new creation cycle.
[DU      ] [I] TEST_MODE: No releasable UEs on cell=N. Entering guard period.
```

If "Guard period elapsed" never appears after "Releasing", the cycle is stuck — check for "Cannot release" warnings and whether `nof_ues_pending_remove` can reach zero.

## Accumulated knowledge

### rrcReject UEs in cycling mode

UEs with `!du_to_cu_rrc_container_present` in `InitialULRRCMessageTransfer` are deleted during the `creating` state and never get a `gnb_du_ue_f1ap_id`. At cycle-end these appear as `"Cannot release: gnb_du_ue_f1ap_id not found"` log lines.

### False-alarm "no more UEs to create" error

`[DU] [E] TEST_MODE cell=0: There are no more UEs to create but only N/M have established` is a benign false alarm if it is immediately followed (within a few log lines) by `[DU] [I] TEST_MODE cell=0: All M UE(s) established`. Without that follow-up "established" message the cycle is genuinely stuck.
