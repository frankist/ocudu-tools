# NGAP layer

## What this layer reveals

The NG Application Protocol is the gNB–AMF (5G core) interface. NGAP logs reveal AMF connectivity, UE registration and authentication outcomes, PDU session establishment, and paging. Useful when diagnosing failures that occur after RRC connection setup but before data bearers are established, or when the core network rejects a UE.

## Component tags

`NGAP`

## Key log patterns

### AMF connection

```
[NGAP    ] [I] NGAP Setup Request sent
[NGAP    ] [I] NGAP Setup Response received
[NGAP    ] [E] NGAP Setup Failure — cause=<reason>
[NGAP    ] [W] AMF connection dropped
```

### UE registration and context

```
[NGAP    ] [I] [sfn.slot] InitialUEMessage: ue_index=N
[NGAP    ] [I] [sfn.slot] InitialContextSetupRequest: ue_index=N
[NGAP    ] [I] [sfn.slot] InitialContextSetupResponse: ue_index=N
[NGAP    ] [W] [sfn.slot] InitialContextSetupFailure: ue_index=N cause=<reason>
[NGAP    ] [I] [sfn.slot] UEContextReleaseCommand: ue_index=N cause=<reason>
[NGAP    ] [I] [sfn.slot] UEContextReleaseComplete: ue_index=N
```

### PDU session

```
[NGAP    ] [I] [sfn.slot] PDU Session Resource Setup Request: ue_index=N
[NGAP    ] [I] [sfn.slot] PDU Session Resource Setup Response: ue_index=N
[NGAP    ] [W] [sfn.slot] PDU Session Resource Setup Failure: ue_index=N cause=<reason>
```

### Paging

```
[NGAP    ] [I] Paging: UE identity=<imsi/tmsi>
```

## Grep for key events

```bash
# AMF setup and connectivity
grep -E 'NGAP.*Setup|AMF.*connect|AMF.*drop' <logfile>

# UE registration and PDU session events
grep -E 'InitialUE|ContextSetup|PDU.*[Ss]ession|UEContext[Rr]elease|[Pp]aging' <logfile>
```

## What to look for

- **NGAP Setup Failure**: AMF rejects the gNB — check PLMN/TAC config matches AMF config.
- **AMF connection dropped mid-run**: All UE procedures will fail; check network connectivity to the AMF.
- **InitialContextSetupFailure**: AMF rejected the UE registration — cause field indicates whether it is an authentication failure, subscription issue, or config mismatch.
- **PDU Session Setup Failure**: Data path not established despite UE being registered — may indicate UPF config issue; check E1AP for the CU-UP side.
- **UEContextReleaseCommand with cause `user-inactivity`**: Normal idle release. With cause `radio-connection-with-ue-lost`: AMF-initiated release after RLF.
- **Paging without a subsequent InitialUEMessage**: UE did not respond to paging — may indicate UE out of coverage or RRC Inactive state issue.

## Accumulated knowledge

*Append entries here after analysis sessions: date, what was found, why it matters.*
