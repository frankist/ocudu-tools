# UE Identifier Reference

Multiple UE identity spaces coexist in OCUDU gNB logs and Amarisoft UE logs. Each belongs to a specific protocol layer or internal subsystem and has a different scope and lifetime. This document describes each identifier type, where it is instantiated, how it appears in logs, how identifiers map across layers, and how they change across key RRC procedures.

Load this file when cross-referencing UE IDs across log layers or when a UE's identity is unclear after a procedure (handover, re-establishment, release).

---

## Quick-reference table

| Identifier | Field in logs | Assigned by | Layer/unit | Scope |
|---|---|---|---|---|
| CU UE index | `ue=N` (CU logs) | CU-CP UE Manager | CU-CP internal | Per CU UE context lifetime |
| RAN UE NGAP ID | `ran_ue=N` | CU-CP (= CU UE index in OCUDU) | NGAP (CU-CP ↔ AMF) | Stable until NGAP release |
| AMF UE NGAP ID | `amf_ue=N` | AMF | NGAP (CU-CP ↔ AMF) | Assigned by AMF in first DL NAS; stable until deregistration |
| gNB-CU-UE-F1AP-ID | `cu_ue=N` | CU-CP (= CU UE index in OCUDU) | F1AP (CU-CP ↔ DU) | Per F1AP UE context lifetime |
| gNB-DU-UE-F1AP-ID | `du_ue=N` | DU (= cu_ue in OCUDU) | F1AP (CU-CP ↔ DU) | Per F1AP UE context lifetime |
| DU-local UE index | `ue=N` (DU logs) | DU MAC/DU-MNG | DU internal | Per DU UE context; small integer, recycled |
| E1AP CU-CP UE ID | `cu_cp_ue=N` | CU-CP | E1AP (CU-CP ↔ CU-UP) | From bearer setup; stable across intra-CU HO |
| E1AP CU-UP UE ID | `cu_up_ue=N` | CU-UP (= cu_cp_ue in OCUDU) | E1AP (CU-CP ↔ CU-UP) | From bearer setup; stable across intra-CU HO |
| C-RNTI | `c-rnti=0xNNNN` or `rnti=0xNNNN` | DU scheduler | MAC/PHY/RRC | Per cell; changes on HO and re-establishment |
| TC-RNTI | `tc-rnti=0xNNNN` | DU scheduler (RAR) | MAC/PHY (RACH) | Temporary; promoted to C-RNTI or discarded |
| RA-RNTI | `ra-rnti=0xNNNN` | Derived from PRACH resource | MAC/PHY (RACH) | Per PRACH time-frequency occasion; shared by UEs in same occasion |
| Amarisoft UEID | `UEID` (hex, e.g. `0001`) | UE simulator | Amarisoft internal | Fixed for the test run; one per simulated UE |
| Amarisoft cell index | `CC` (e.g. `00`, `01`) | UE simulator | Amarisoft internal | Changes when UE switches cells (HO) |

---

## gNB-side identifiers

### CU UE index — `ue=N` in CU logs

Assigned by the CU-CP UE Manager when a UE context is created. This is the master CU-internal reference.

**Appears in:** `[CU-CP]`, `[CU-UEMNG]`, `[RRC]`, `[NGAP]`, `[CU-CP-F1]`, `[CU-CP-E1]`, `[PDCP]`

**Allocation:** monotonically increasing per gNB run; never reused within the same run.

**Log examples:**
```
[CU-UEMNG] [I] ue=0 du_index=0: Created new CU-CP UE
[CU-CP   ] [I] ue=0 c-rnti=0x4601: UE created
[RRC     ] [I] ue=0 c-rnti=0x4601: DCCH UL rrcSetupComplete
[NGAP    ] [I] Tx PDU ue=0 ran_ue=0: InitialUEMessage
```

**Key behaviour:** In intra-CU handover, the source UE keeps its `ue=N` ID while a new target UE `ue=M` is created for the target cell. Once the UE completes HO, the source context (ue=N) is released; the UE is now known as ue=M.

---

### RAN UE NGAP ID — `ran_ue=N`

The gNB-allocated UE identifier used in the NGAP interface toward the AMF. In OCUDU it is always equal to the CU UE index (`ran_ue=N == ue=N`).

**Appears in:** `[NGAP]`

**Log examples:**
```
[NGAP    ] [I] Tx PDU ue=0 ran_ue=0: InitialUEMessage
[NGAP    ] [I] Rx PDU ue=0 ran_ue=0 amf_ue=100: DownlinkNASTransport
[NGAP    ] [I] Tx PDU ue=0 ran_ue=0 amf_ue=100: UplinkNASTransport
```

---

### AMF UE NGAP ID — `amf_ue=N`

The AMF-allocated UE identifier, received in the first `DownlinkNASTransport` response to `InitialUEMessage`. Absent from `Tx` lines until the AMF has assigned it.

**Appears in:** `[NGAP]` (Rx direction initially; both Tx and Rx once assigned)

**Log example:**
```
[NGAP    ] [I] Rx PDU ue=0 ran_ue=0 amf_ue=100: DownlinkNASTransport
```

---

### gNB-CU-UE-F1AP-ID — `cu_ue=N`

The CU-side F1AP UE identifier sent to the DU in F1AP UE context procedures. In OCUDU it equals the CU UE index.

**Appears in:** `[CU-CP-F1]` (Tx and Rx), `[DU-F1]` (Rx from CU perspective / visible in DU lines)

**Log examples:**
```
[CU-CP-F1] [I] Tx PDU du=0 ue=0 cu_ue=0: UEContextSetupRequest
[CU-CP-F1] [I] Rx PDU du=0 ue=0 cu_ue=0 du_ue=0: UEContextSetupResponse
[DU-F1   ] [I] Rx PDU du=0 cu_ue=0: UEContextSetupRequest
```

---

### gNB-DU-UE-F1AP-ID — `du_ue=N`

The DU-side F1AP UE identifier, echoed back to the CU in UEContextSetupResponse and present in all subsequent F1AP messages. In OCUDU it equals `cu_ue` (both sides use the CU-assigned value).

**Appears in:** `[DU-F1]` (Tx), `[CU-CP-F1]` (Rx), both after UEContextSetupResponse

**Log examples:**
```
[DU-F1   ] [I] ue=0 c-rnti=0x4601 du_ue=0: F1 UE context created successfully.
[DU-F1   ] [I] Tx PDU du=0 ue=0 cu_ue=0 du_ue=0: InitialULRRCMessageTransfer
[CU-CP-F1] [I] Rx PDU du=0 ue=71 cu_ue=71 du_ue=71: UEContextSetupResponse
```

---

### DU-local UE index — `ue=N` in DU logs

The DU-internal UE identifier used by MAC, DU-MNG, and the DU side of DU-F1. **This is a different namespace from the CU `ue=N`.**

**Appears in:** `[MAC]` (as `ue=N crnti=0xNNNN`), `[DU-MNG]` (as `ue=N rnti=0xNNNN`), `[DU-F1]` (as `ue=N` alongside `du_ue=M`)

**Allocation:** small integers, starting from 0; reused (recycled) once a UE is released. With 10 concurrent UEs, the DU-local index cycles through 0–9 (or similar) regardless of how many total UEs have been served.

**Log examples:**
```
[DU-MNG  ] [I] ue=0 rnti=0x4601 proc="UE Create": Procedure started....
[MAC     ] [I] [34.4] ue=0 crnti=0x4601 proc="MAC UE Creation": finished successfully
[DU-F1   ] [I] ue=10 c-rnti=0x0 du_ue=70: F1 UE context created successfully.
[MAC     ] [I] ue=0: RLF detected. Cause: 100 consecutive HARQ-ACK KOs
```

**To map DU-local ue=N to a CU ue=M:** find the `[DU-F1] ue=N ... du_ue=M` creation line (du_ue=M equals the CU ue=M in OCUDU), or match the RNTI via `[CU-CP] ue=M c-rnti=0xNNNN: UE created`.

---

### E1AP CU-CP UE ID — `cu_cp_ue=N`
### E1AP CU-UP UE ID — `cu_up_ue=N`

Identifiers for the E1AP interface between CU-CP and CU-UP. In OCUDU `cu_cp_ue=N == cu_up_ue=N`. Assigned at `BearerContextSetupRequest` (initial PDU session establishment).

**Appears in:** `[CU-CP-E1]`

**Allocation:** assigned sequentially at initial bearer setup; stable across intra-CU handover (the bearer is modified, not recreated). After many HOs, the CU UE index (ue=N) increases while `cu_cp_ue` stays at the value from the original bearer setup.

**Log examples:**
```
[CU-CP-E1] [I] Rx PDU ue=0 cu_cp_ue=0 cu_up_ue=0: BearerContextSetupResponse
[CU-CP-E1] [I] Tx PDU ue=69 cu_cp_ue=9 cu_up_ue=9: BearerContextModificationRequest
```

The second line shows ue=69 (after 6 HO rounds for the 10th UE) still using `cu_cp_ue=9` from the original bearer.

---

### C-RNTI — `c-rnti=0xNNNN` or `rnti=0xNNNN`

Cell Radio Network Temporary Identifier. Identifies a UE within a cell. Assigned by the DU scheduler at the conclusion of RACH (promoted from TC-RNTI).

**Appears in:** `[RRC]`, `[SCHED]`, `[PHY]`, `[MAC]`, `[DU-F1]`

**Format variants:**
- `c-rnti=0xNNNN` — used in `[RRC]`, `[CU-CP]`, `[DU-F1]`
- `rnti=0xNNNN` — used in `[SCHED]`, `[PHY]`, `[DU-MNG]`
- `crnti=0xNNNN` — used in `[MAC]` (no dash)

In SCHED `Slot decisions` lines the RNTI appears without a prefix:
```
[SCHED   ] [I] [sfn.slot] Slot decisions pci=N t=Xus (...): DL: ue=N c-rnti=0xNNNN ...
```

**Lifetime:** assigned per-cell. Changes on handover (new C-RNTI on target cell, carried as `newUE-Identity` in the HO command) and on re-establishment (new C-RNTI from RACH).

---

### TC-RNTI and RA-RNTI

**TC-RNTI (Temporary C-RNTI):** assigned by SCHED in the RAR and used for Msg3 PUSCH. Promoted to the permanent C-RNTI after successful contention resolution (Msg4) or rrcSetupComplete/rrcReconfigurationComplete.

- Appears as `tc-rnti=0xNNNN` in SCHED PRACH slot events
- Appears as `rnti=0xNNNN` in SCHED Msg3 allocation (`UE PUSCH: ue=8192`) and PHY PUSCH decode lines during RACH

Sentinel `ue=8192` (0x2000) in SCHED identifies a not-yet-established UE (TC-RNTI phase):
```
[SCHED   ] [I] [sfn.slot] UL: ue=8192 rnti=0xNNNN h_id=0 ... msg3_delay=7
```

**RA-RNTI:** derived from the PRACH time-frequency occasion. Used to address the RAR PDSCH. Multiple UEs transmitting in the same PRACH occasion share the same RA-RNTI.

```
[SCHED   ] [I] [sfn.slot] Processed slot events pci=N: prach(ra-rnti=0xNNNN preamble=K tc-rnti=0xMMMM)
[SCHED   ] [I] [sfn.slot] - RAR PDSCH: ra-rnti=0xNNNN ... grants (N): tc-rnti=0xMMMM: rapid=K ...
```

---

## Amarisoft UE simulator identifiers

### UEID — `0001` … `000a`

A 4-digit hex identifier assigned by the UE simulator at startup, one per simulated UE. Appears in every UE log line as the second field.

**Format:** `[LAYER] DIR UEID CC [RNTI] [sfn.slot] ...`

Example:
```
01:27:08.961 [MAC] -  0009 00 ta=1 ul_grant=0x24400e tc_rnti=0x460b
01:27:08.962 [PHY] UL 0009 00 460b  538.14 PUSCH: ...
```

**Mapping to gNB:** match the RNTI in the UE log (`tc_rnti` or the inline RNTI field) to `[CU-CP] ue=M c-rnti=0xNNNN: UE created` in the gNB log.

**Stability:** fixed for the entire test run; does not change across HO, re-establishment, or reconfiguration.

---

### Cell index — `CC`

A single-digit decimal index indicating which configured cell the UE is currently on.

- `00` = cell index 0 (first cell in Amarisoft config, pci determined by SIB1)
- `01` = cell index 1 (second cell)

Appears as `-` before the UE has attached to a cell (e.g., during PRACH before RAR, the cell index is present but RNTI shows `-`):
```
01:27:08.954 [PHY] UL 0009 00    -  537.19 PRACH: sequence_index=47 ...
```

**On handover:** switches from source CC to target CC when the UE transmits the CFRA preamble on the target cell. This is the UE-side signal that the cell switch has occurred.

---

## Identity mapping across layers

To correlate a UE across all log layers, start from any known ID and follow these links:

```
Amarisoft UEID ──► RNTI (from UE log PHY/MAC lines)
                         │
                         ▼
         [CU-CP] ue=M c-rnti=0xNNNN: UE created   ──► CU ue=M
                         │                                  │
                         ▼                                  ▼
         [DU-F1] ue=DU_LOCAL c-rnti=0xNNNN du_ue=M       ran_ue=M  (NGAP)
                                │                          cu_cp_ue=K (E1AP, from original attach)
                                ▼
         [MAC]   ue=DU_LOCAL crnti=0xNNNN    (RLF, proc events)
```

**CU ue=M → DU-local ue:**
```bash
grep "ue=DU_LOCAL.*du_ue=M\|c-rnti=0xNNNN.*du_ue=M" <gnb.log>
```

**RNTI → CU ue=M:**
```bash
grep "ue=M c-rnti=0xNNNN: UE created" <gnb.log>
```

**Amarisoft UEID → RNTI:**
```bash
grep "UEID CC" <ue.log> | grep -v '    -  ' | head -5   # RNTI appears in 3rd field after CC
```

**Target UE (HO) → Source UE:**
```bash
# Find source trigger immediately before target creation
grep -B1 "ue=M du_index.*Created new CU-CP UE" <gnb.log>
# Returns: [CU-CP] ue=N: Trigger intra-CU (intra-DU) handover on du=0
```

**Bulk extraction from pcap:**

`references/scripts/map_ue_ids.py` extracts all UE ID mappings from a pcap and prints one line per mapping update:

```bash
python3 references/scripts/map_ue_ids.py f1ap.pcap   # du_ue ↔ cu_ue ↔ c_rnti
python3 references/scripts/map_ue_ids.py ngap.pcap   # ran_ue ↔ amf_ue
python3 references/scripts/map_ue_ids.py e1ap.pcap   # cu_cp_ue ↔ cu_up_ue
```

The protocol is auto-detected from the filename. Output format:
```
<frame>, <message>, <id>=<val>, ...
```

Example (F1AP, 10 UEs connecting then handing over):
```
3, InitialULRRCMessageTransfer, du_ue=0, c_rnti=0x4601
4, DLRRCMessageTransfer, du_ue=0, cu_ue=0, c_rnti=0x4601
...
204, UEContextSetupRequest, cu_ue=10
207, UEContextSetupResponse, du_ue=10, cu_ue=10, c_rnti=0x460b
```

For inter-DU HO, run on both DU pcaps separately: the source DU shows `UEContextRelease` at the end; the target DU shows `UEContextSetup` when UEs arrive.

---

## Stability across key procedures

| Identifier | RRC Reconfig (non-HO) | Intra-CU intra-DU HO | Intra-CU inter-DU HO | Re-establishment | Full release + re-attach |
|---|---|---|---|---|---|
| CU ue=N | stable | **changes** (new M for target; N released) | **changes** (new M on target DU; N released) | **stable** (direct RLF); **changes** to P if post-HO T304 expiry | resets (new from 0) |
| ran_ue | stable | changes (follows CU ue) | changes (follows CU ue) | stable (direct RLF); new P | resets |
| amf_ue | stable | stable (intra-CU HO invisible to AMF) | **stable** (inter-DU still intra-CU; AMF unaware) | stable (recovery preserves NAS) | resets |
| cu_ue (F1AP) | stable | **changes** (new request for target) | **changes** (new request to target DU) | new | resets |
| du_ue (F1AP) | stable | **changes** | **changes** | new | resets |
| DU-local ue | stable | **changes** (recycled index on target) | **changes** on both DUs independently | new (recycled) | resets (recycled) |
| cu_cp_ue / cu_up_ue (E1AP) | stable | **stable** (bearer modified, not recreated) | **stable** (same CU-UP; bearer modified) | stable | resets |
| C-RNTI | stable | **changes** (newUE-Identity in HO cmd) | **changes** (new RACH on target cell) | **changes** (new RACH) | resets |
| Amarisoft UEID | stable | **stable** | **stable** | **stable** | stable (fixed at test start) |
| Amarisoft CC | stable | **changes** (source → target cell) | **changes** | may change | resets |

**Key observations:**

- The Amarisoft UEID is the most stable identifier — it is the only one that stays constant across HO, re-establishment, and even brief releases within a test run. Use it as the anchor when correlating the UE log to a specific gNB UE context.
- `cu_cp_ue` / `cu_up_ue` are the second most stable — they survive both intra-DU and inter-DU intra-CU HO. A large gap between `ue=N` and `cu_cp_ue=K` (e.g., `ue=69 cu_cp_ue=9`) indicates the logical UE has been through multiple HO cycles.
- The DU-local `ue=N` (MAC/DU-MNG) recycles small integers and can mislead: `ue=0: RLF detected` after 100 HOs refers to whatever UE currently holds DU-local slot 0, not the original CU ue=0. In inter-DU HO, source and target DUs recycle their local indices independently.
- **Re-establishment CU ue= depends on the trigger**: for direct RLF (no preceding HO command), OCUDU reuses the existing UE context — ue= stays the same, only C-RNTI changes. For post-HO T304 expiry, a new context P is created and the log shows `"RRC Reestablishment Procedure" for old_ue=N`.
