# Handover Procedure

Reference for debugging handover in OCUDU gNB and Amarisoft UE logs. Covers intra-CU intra-DU (main body), intra-CU inter-DU, and inter-CU handover types; CFRA and contention-based RACH modes. Jump to the relevant section using the overview table below.

For the PRACH/RAR/Msg3 mechanics that run on the target cell during handover, see **`procedures/random-access.md` § CFRA differences**.

---

## Handover type overview

Quickly identify the HO type from the first distinctive log line, then go to the relevant section.

| What you see | Handover type | Section |
|---|---|---|
| `[CU-CP] ue=N: Trigger intra-CU (intra-DU) handover on du=0` | Intra-CU intra-DU (same DU, different RUs) | Steps 0–4 below |
| `[CU-CP] ue=N: Trigger intra-CU (inter-DU) handover from source_du=X to target_du=Y` | Intra-CU inter-DU (different DUs, same CU) | [§ Inter-DU HO](#inter-du-ho-intra-cu) |
| `HandoverRequired` / `PathSwitchRequest` in NGAP pcap or gNB log | Inter-CU (different gNBs) | [§ Inter-CU HO](#inter-cu-ho) |

For any intra-CU HO: the NGAP pcap should contain **only** `InitialContextSetup`, NAS transport, and `UEContextRelease`. Presence of `HandoverRequired` or `PathSwitchRequest` confirms inter-CU.

---

## Handover overview

In intra-CU intra-DU CFRA handover:

1. CU-CP detects measurement event → triggers HO
2. Target UE context created on target cell
3. HO command (`rrcReconfiguration` with `reconfigWithSync`) sent to source UE, carrying a dedicated PRACH preamble index (`ra-PreambleIndex`)
4. Source UE detaches from source cell and transmits the dedicated preamble on the target cell
5. gNB target cell schedules RAR; UE completes RACH (no contention resolution needed)
6. UE sends `rrcReconfigurationComplete` via Msg3 PUSCH → HO complete
7. Source UE context released

If the UE does not complete the HO within T304, it falls back to re-establishment.

---

## Step 0 — Check CONFIG for HO parameters

```bash
python3 references/scripts/grep_multiline.py <logfile> '\[CONFIG.*Input configuration'
```

Key HO fields:

| Field | Meaning |
|---|---|
| `trigger_handover_from_measurements: true` | A3-triggered HO enabled; CU-CP initiates HO on measurement reports |
| `cfra_enabled: true` | CFRA mode: dedicated preambles assigned in HO command |
| `cho_timeout_ms: N` | CHO timer (ms); overall HO timeout before the target routine is abandoned |
| `force_reestablishment_fallback: false` | After T304, UE falls back to re-establishment (not RRC re-setup) |

---

## Step 1 — Count HO attempts and failures

```bash
grep -c 'Trigger intra-CU.*handover' <gnb.log>
grep -c '"Intra CU Handover Target Routine" failed' <gnb.log>
grep -c '"RRC Reestablishment Procedure".*old_ue' <gnb.log>
```

One `"Intra CU Handover Target Routine" failed` corresponds to one UE that did not complete the HO within the CU-CP timeout. It is typically followed by an `"RRC Reestablishment Procedure"` recovery.

---

## Step 2 — gNB: Trace a successful CFRA HO

### CU-CP side

```
[CU-CP   ] [I] ue=N: Trigger intra-CU (intra-DU) handover on du=0     ← source UE
[CU-UEMNG] [I] ue=M du_index=0: Created new CU-CP UE                  ← target context (M typically N+1)
[CU-CP-F1] [I] Tx PDU du=0 ue=M cu_ue=M: UEContextSetupRequest
[DU-F1   ] [I] ue=DU_ID c-rnti=0x0 du_ue=M: F1 UE context created successfully.
[CU-CP   ] [I] ue=M c-rnti=0xTGT: UE created                          ← target RNTI assigned
[RRC     ] [I] ue=N c-rnti=0xSRC: DCCH DL rrcReconfiguration           ← HO command to source
```

### DU/PHY side (target cell PRACH → rrcReconfigurationComplete)

After the HO command is sent, the UE transmits the dedicated preamble on the target cell. The PRACH→RAR→Msg3 sequence on the target cell follows the same flow as CFRA in `procedures/random-access.md`. The Msg3 carries the `rrcReconfigurationComplete`.

On success:
```
[PHY     ] [I] [sfn.slot] PRACH: rsi=0 rssi=XdB detected_preambles=[{idx=K ta=X.Xus ...}]
[SCHED   ] [I] [sfn.slot] Processed slot events pci=P: prach(ra-rnti=0xNNNN preamble=K tc-rnti=0xTGT)
...
[RRC     ] [I] ue=M c-rnti=0xTGT: DCCH UL rrcReconfigurationComplete
```

After HO completes, the source RNTI appears in METRICS `events` as `ue_rem`:
```
events=[..., {rnti=0xTGT type=ue_create}, {rnti=0xTGT type=ue_reconf}, ..., {rnti=0xSRC type=ue_rem}, ...]
```

---

## Step 3 — gNB: Diagnose a failed CFRA HO

### Failure indicator

```
[CU-CP   ] [W] ue=M: "Intra CU Handover Target Routine" failed
[RRC     ] [I] ue=M c-rnti=0xTGT: DCCH DL rrcRelease
```

`ue=M` is the **target** UE ID. To find the source UE and its Amarisoft UEID:

```bash
# Find source UE (ue=N) from the trigger immediately before target context creation
grep -B3 "ue=M du_index.*Created new CU-CP" <gnb.log>
# Find source RNTI
grep "ue=N c-rnti=.*: UE created" <gnb.log>
# Source RNTI → Amarisoft UEID: cross-reference in UE log
grep "RNTI_HEX" <ue.log> | head -5
```

### Pre-failure RLF on the source cell

After the HO command is sent, the source UE detaches. The gNB keeps sending DL to the old RNTI until the source context is released. The resulting HARQ KOs produce:

```
[MAC     ] [I] ue=DU_ID: RLF detected. Cause: 100 consecutive HARQ-ACK KOs
```

This uses the **DU-local** `ue=DU_ID` (not the CU `ue=N`).

### Missing PRACH detection

This is the confirmed failure mode for the inter-RU CFRA HO issue: the UE transmitted the dedicated preamble but the gNB PHY did not detect it.

Check whether preamble `idx=K` (assigned in the HO command) appears in the gNB PHY PRACH lines during the T304 window (~0–2 s after the HO command timestamp):

```bash
grep 'PRACH:.*detected_preambles' <gnb.log>
```

Then verify in the UE log that the UE did attempt the PRACH. If `sequence_index=K` appears in the UE log but `idx=K` is absent from the gNB PHY log: the preamble was **transmitted but not detected**. This is the gNB-side miss pattern.

Example from a real failure (preamble 45 sent by UE 000a, undetected by gNB):
```
# UE log — preamble transmitted on target cell (CC 00)
01:27:54.623 [PHY] UL 000a 00    -  166.19 PRACH: sequence_index=45 prb=37:12 symb=0:12 epre=-29.9 p=-25

# gNB log — no corresponding PHY PRACH detection for idx=45 in this time window
```

### Re-establishment recovery sequence

After T304 expires, the UE re-establishes using a CB preamble:

```
[RRC     ] [I] ue=P c-rnti=0xNEW: CCCH UL rrcReestablishmentRequest
[RRC     ] [I] ue=P c-rnti=0xNEW: "RRC Reestablishment Procedure" for old c-rnti=0xSRC, pci=PCIx started...
[RRC     ] [I] ue=P c-rnti=0xNEW: DCCH DL rrcReestablishment
[RRC     ] [I] ue=P c-rnti=0xNEW: DCCH UL rrcReestablishmentComplete
[RRC     ] [I] ue=P c-rnti=0xNEW: "RRC Reestablishment Procedure" for old_ue=N finished successfully
```

`old c-rnti=0xSRC, pci=PCIx` identifies the source cell and RNTI. `old_ue=N` cross-references the original CU source UE ID.

---

## Step 4 — UE (Amarisoft): Trace CFRA HO

### HO command: dedicated preamble assignment

```bash
grep -n 'ra-PreambleIndex\|rach-ConfigDedicated\|t304\|newUE-Identity' <ue.log> | head -20
```

In the decoded RRC:

```
message c1: rrcReconfiguration: {
  ...
  reconfigWithSync {
    ...
    newUE-Identity N,           ← new C-RNTI on target cell (decimal)
    t304 ms2000,                ← HO timeout
    rach-ConfigDedicated uplink: {
      cfra {
        resources ssb: {
          ssb-ResourceList {
            { ssb 0, ra-PreambleIndex K }
          },
          ra-ssb-OccasionMaskIndex 0
        },
        totalNumberOfRA-Preambles 4
      }
    },
```

`ra-PreambleIndex K` is the dedicated preamble the UE will transmit. This value must match `idx=K` in the gNB PHY PRACH detection.

### CFRA PRACH transmission

```
HH:MM:SS.mmm [PHY] UL UEID CC    -   sfn.slot PRACH: sequence_index=K prb=37:12 symb=0:12 epre=X p=X
```

- `CC` is the target cell index (switches from source CC to target CC after the HO command)
- No `two_steps=1` flag (CFRA is 4-step; the flag only appears for 2-step MsgA)
- `sequence_index=K` must match `ra-PreambleIndex K`

Real example (UE 0009 doing CFRA with dedicated preamble 47):
```
01:27:08.954 [PHY] UL 0009 00    -  537.19 PRACH: sequence_index=47 prb=37:12 symb=0:12 epre=-28.9 p=-24
```

### RAR reception (CFRA)

```
HH:MM:SS.mmm [MAC] DL    - CC RAR: rapid=K
HH:MM:SS.mmm [MAC] -  UEID CC ta=N ul_grant=0xNNNNNN tc_rnti=0xNNNN
```

For CFRA the RAR contains a single entry (`rapid=K` alone). If no `ta=... ul_grant=...` follows for that UE, the RAR was rejected — RAPID mismatch; see `procedures/random-access.md` § Common failure patterns #2.

Real example:
```
01:27:08.961 [MAC] DL    - 00 RAR: rapid=47
01:27:08.961 [MAC] -  0009 00 ta=1 ul_grant=0x24400e tc_rnti=0x460b
```

### Msg3 PUSCH

```
HH:MM:SS.mmm [PHY] UL UEID CC TCRNTI sfn.slot PUSCH: harq=0 prb=P:W symb=0:14 CW0: tb_len=N mod=2 rv_idx=0 cr=X retx=0 p=X
```

The Msg3 PUSCH carries `rrcReconfigurationComplete` via SRB1 (MAC/RLC/PDCP transparent to the PHY line).

Real example:
```
01:27:08.962 [PHY] UL 0009 00 460b  538.14 PUSCH: harq=0 prb=34:3 symb=0:14 CW0: tb_len=11 mod=2 rv_idx=0 cr=0.12 retx=0 p=12
```

```bash
grep -n 'PRACH: sequence_index\|RAR: rapid\|ul_grant\|tc_rnti' <ue.log> | head -30
```

### Re-establishment after T304 timeout

If CFRA fails, the UE re-establishes using a random CB preamble (`sequence_index=J` where `J ≠ K`):

```
HH:MM:SS.mmm [PHY] UL UEID CC    -   sfn.slot PRACH: sequence_index=J ...
HH:MM:SS.mmm [RRC] UL UEID CC CCCH-NR: RRC reestablishment request
HH:MM:SS.mmm [RRC] DL UEID CC CCCH-NR: RRC reestablishment
HH:MM:SS.mmm [RRC] UL UEID CC DCCH-NR: RRC reestablishment complete
```

---

## METRICS signal for HO waves

```bash
grep 'nof_prach_preambles\|msg3_ok\|msg3_nok\|events=' <gnb.log>
```

In each 1-second METRICS window for the target cell (target cell is the one where `nof_prach_preambles > 0` during an HO wave):

| Condition | Signal |
|---|---|
| Clean HO wave | `nof_prach_preambles=N`, `msg3_ok=N`, `msg3_nok=0`; `events` has `ue_create` + `ue_reconf` for each arriving UE |
| HO failure(s) | `msg3_ok < nof_prach_preambles` or `msg3_nok > 0`; `events` has `ue_rem` for a target RNTI without a prior `ue_reconf` for the same RNTI |
| UE never reached target | `nof_prach_preambles=0` in the window; no `ue_create` for expected target RNTIs |

---

## Common failure patterns

### 1. CFRA preamble transmitted by UE but not detected by gNB

**Signal:** `"Intra CU Handover Target Routine" failed` + source cell `RLF detected. Cause: 100 consecutive HARQ-ACK KOs` (UE left source) + UE log shows `PRACH: sequence_index=K` on the target cell CC + **no matching `idx=K` in gNB PHY PRACH detections** during that window.

This is the confirmed failure mode for the inter-RU CFRA HO test (issue #419): the UE successfully receives the HO command, switches to the target cell, and transmits the dedicated preamble — but the gNB PHY does not detect it.

**Cause:** Possible causes include PHY detection threshold miss during a mass HO wave (multiple preambles in the same PRACH occasion reducing per-preamble SNR), ZMQ scheduling jitter dropping the PRACH IQ samples, or a bug in preamble detection under load.

**Diagnosis:** Find `ra-PreambleIndex K` in the UE log HO command → confirm `sequence_index=K` appears in the UE PHY log on the target cell CC → grep gNB PHY for `idx=K` in the same ~10 ms window → absence of `idx=K` confirms gNB-side miss.

### 2. Multiple simultaneous HO failures

**Signal:** Several `"Intra CU Handover Target Routine" failed` warnings within 300 ms, followed by a cluster of `rrcReestablishmentRequest` on the target cell.

**Cause:** Scheduling congestion on the target cell during a mass HO wave; the target UL slots are fully occupied, blocking Msg3 allocation. Check:
```bash
grep 'Failed to allocate PUSCH Msg3' <gnb.log>
```

**Diagnosis:** Count simultaneous HO triggers in the 500 ms before the failure and compare with `nof_ues` (target cell METRICS) to estimate the PRACH congestion.

### 3. CFRA RAR received but rrcReconfigurationComplete missing

**Signal:** PHY PRACH detection for `idx=K` present; RAR PDSCH scheduled; `msg3_delay=7` allocated; but `rrcReconfigurationComplete` never appears for the target UE; `"Intra CU Handover Target Routine" failed` after timeout.

**Cause:** Msg3 PUSCH CRC failure (`crc=KO`) due to poor channel conditions during the cell transition. Check:
```bash
grep "PUSCH: rnti=0xTGT" <gnb.log>
```

---

## Using pcaps for HO analysis

If a `f1ap.pcap` is available alongside the log, tshark can extract the dedicated PRACH preamble assignment directly from the F1AP `UEContextModification` message — useful when the gNB log is not verbose enough to show the assigned preamble.

### F1AP procedure survey

```bash
# Count F1AP procedures by type
tshark -r f1ap.pcap -T fields -e f1ap.procedureCode | sort | uniq -c | sort -rn
```

F1AP procedure codes relevant to handover:

| Code | Procedure |
|---|---|
| 5 | UEContextSetup — creates target UE context |
| 6 | UEContextRelease — releases source UE context |
| 7 | UEContextModification — carries HO command RRCContainer |

### Extracting the HO command (dedicated preamble)

`UEContextModification` (code 7) carries the full `rrcReconfiguration` in its RRCContainer, decoded by tshark as ASN.1:

```bash
# Show all UEContextModification exchanges with full decode
tshark -r f1ap.pcap -V -Y 'f1ap.procedureCode == 7' 2>/dev/null | grep -A5 'ra-PreambleIndex\|newUE-Identity\|t304'
```

Key fields in the decoded output:

```
nr-RRCReconfiguration
  criticalExtensions: rrcReconfiguration (0)
    rrcReconfiguration
      reconfigWithSync
        newUE-Identity: 17931         ← target C-RNTI (decimal)
        t304: ms2000                  ← HO timeout
        rach-ConfigDedicated
          cfra
            resources: ssb (0)
              ssb-ResourceList: 1 item
                Item 0
                  ssb: 0
                  ra-PreambleIndex: 47    ← dedicated preamble (must appear in gNB PHY log as idx=47)
```

Cross-check: `ra-PreambleIndex` here must match `sequence_index=K` in the UE PHY log and `idx=K` in the gNB PHY PRACH detection line.

### Confirming intra-CU HO has no NGAP involvement

For intra-CU handover, NGAP carries **no HO-related messages** — only `InitialContextSetup`, NAS transport (`UplinkNASTransport` / `DownlinkNASTransport`), and `UEContextRelease`. If you see `HandoverRequired` or `PathSwitchRequest` in the NGAP pcap, the HO is inter-CU (or inter-AMF), which changes the analysis significantly.

```bash
tshark -r ngap.pcap -T fields -e ngap.procedureCode | sort | uniq -c | sort -rn
```

---

## Non-CFRA (contention-based) intra-DU HO

When `cfra_enabled` is absent or false, the same intra-DU HO trigger fires but the UE uses a randomly chosen preamble instead of a dedicated one.

**Key differences from CFRA in the logs:**

- No `rach-ConfigDedicated` in the HO command (`ra-PreambleIndex` absent from the F1AP UEContextModification RRCContainer)
- UE log: multiple UEs transmit **different** `sequence_index` values in the **same slot** (contention pattern). Compare: CFRA shows a single UE with a single assigned index per PRACH occasion.

```
# Contention-based: diverse indices at same slot
01:45:13.342 [PHY] UL 000a 00  -  542.19 PRACH: sequence_index=46 ...
01:45:13.342 [PHY] UL 0008 00  -  542.19 PRACH: sequence_index=54 ...
01:45:13.342 [PHY] UL 0007 00  -  542.19 PRACH: sequence_index=3  ...
```

- `msg3_nok > 0` in METRICS is more likely under load (PRACH collision → Msg3 CRC failure) — not necessarily a bug

**Diagnosis when contention-based HO fails:** check `"Failed to allocate PUSCH Msg3"` (scheduling congestion) and `msg3_nok` in METRICS for the target cell.

---

## Inter-DU HO (intra-CU)

Triggered when the target cell is on a **different DU** from the source cell, managed by the same CU.

### Identifying inter-DU HO

The trigger log line explicitly names both DU indices:

```
[CU-CP   ] [I] ue=N: Trigger intra-CU (inter-DU) handover from source_du=X to target_du=Y
[CU-UEMNG] [I] ue=M du_index=Y: Created new CU-CP UE
```

Compare intra-DU, where `source_du == target_du` and the line says `(intra-DU)`:
```
[CU-CP   ] [I] ue=N: Trigger intra-CU (intra-DU) handover on du=0
```

### F1AP flow

UEContextSetupRequest goes to the **target DU** (`du=Y`):
```
[CU-CP-F1] [I] Tx PDU du=Y ue=M cu_ue=M: UEContextSetupRequest
[DU-F1   ] [I] ue=LOCAL c-rnti=0x0 du_ue=M: F1 UE context created successfully.
[DU-F1   ] [I] Tx PDU du=Y ue=LOCAL cu_ue=M du_ue=M: UEContextSetupResponse
```

Then UEContextReleaseCommand goes to the **source DU** (`du=X`):
```
[CU-CP-F1] [I] Tx PDU du=X ue=N cu_ue=N du_ue=N: UEContextReleaseCommand
[DU-F1   ] [I] ue=LOCAL c-rnti=0xSRC du_ue=N cu_ue=N: F1 UE context removed.
[DU-F1   ] [I] Tx PDU du=X cu_ue=N du_ue=N: UEContextReleaseComplete
```

For intra-DU HO both messages go to `du=0`; for inter-DU they go to different DU indices. CU UE index changes (N → M), NGAP `amf_ue` stays stable (AMF unaware of intra-CU HO), `cu_cp_ue`/`cu_up_ue` stay stable (same CU-UP, bearer modified not recreated). See `references/ue-ids.md` for the full stability table.

### Logs to check

- **CU log** (`cu.log` or gnb.log): HO trigger, F1AP exchanges with both DUs
- **Target DU log**: PRACH detection, Msg3, RRC ReconfigComplete (look for `du=Y` messages)
- **Source DU log**: UEContextRelease and UE cleanup (look for `du=X` messages)
- F1AP pcap on each DU shows `UEContextSetup` (code 5) on target and `UEContextRelease` (code 6) on source

---

## Inter-CU HO

Triggered when the target cell is on a **different gNB** (different CU). NGAP is involved.

### Identifying inter-CU HO

NGAP pcap contains handover-related messages absent in intra-CU HO:

```bash
tshark -r ngap.pcap -T fields -e ngap.procedureCode | sort | uniq -c | sort -rn
```

Relevant codes: 14 = HandoverPreparation (source sends `HandoverRequired`), 15 = HandoverResourceAllocation (target sends `HandoverRequestAcknowledge`), 13 = HandoverNotification, 32 = PathSwitchRequest.

In gnb.log:
```bash
grep "HandoverRequired\|HandoverRequest\|PathSwitchRequest" <gnb.log>
```

### F1-U bearer failure — DL data silently drops after HO

After inter-CU HO, DL traffic can drop silently if the F1-U (F1 user-plane gateway) on the source or target fails to associate the CU-UP tunnel with the updated DU-side bearer. Component tag: `[CU-F1-U]`.

**Failure pattern** (logged at [I] level — easy to miss):
```
[CU-F1-U ] [I] ue=N DRB1 ul-teid=0xNNNNNN: Cannot handle F1-U GW DL message. F1-U DU GW bearer does not exist.
[CU-F1-U ] [I] No associated DU F1-U bearer when disconnecting CU F1-U bearer. UL GTP Tunnel={Addr=127.0.X.X TEID=0xNNNNNN}
```

The UE receives no DL traffic, exhausts CSI feedback slots, and eventually hits:
```
[MAC     ] [I] ue=DU_ID: RLF detected. Cause: 100 consecutive undecoded CSIs
[DU-MNG  ] [W] ue=DU_ID rnti=0xNNNN: RLF detected with cause "MAC max KOs reached". Timer of 4000 msec to release UE started...
```

Note: "100 consecutive undecoded CSIs" is a distinct RLF cause from the usual HARQ KO cause. It indicates the gNB scheduled CSI reports that were never received — typical when the DL path is silently broken post-HO.

```bash
grep "Cannot handle F1-U GW DL message\|No associated DU F1-U bearer" <gnb.log>
grep "consecutive undecoded CSIs" <gnb.log>
```

### PUCCH CSI allocation skip after inter-CU HO

```
[SCHED   ] [W] [SLOT] PUCCH CSI allocation skipped (rnti=0xNNNN slot=SFN.SLOT). Cause: CSI resource not available
```

If persistent (not just the first few slots after HO), the RRC reconfiguration carrying CSI config was not applied correctly on the target DU.

```bash
grep "PUCCH CSI allocation skipped" <gnb.log>
```
