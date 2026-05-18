# Random Access Procedure

5G NR RA procedure reference for debugging from OCUDU gNB logs and Amarisoft UE logs. Covers 4-step CBRA, 2-step CBRA (MsgA/MsgB), and CFRA.

**Procedure variants:**

| Variant | Preamble | RAR | Msg3 | Contention resolution |
|---|---|---|---|---|
| 4-step CBRA | Random CB preamble (idx < `nof_cb_preambles_per_ssb`) | RAR on RA-RNTI | PUSCH on TC-RNTI | Msg4 (MAC CE + RRC Setup) |
| 2-step CBRA (MsgA) | Random CB preamble (idx ≥ `nof_cb_preambles_per_ssb`) | MsgB (`result=msgb`) or fallbackRAR | Part of MsgA PUSCH or fallback Msg3 | Via MsgB or fallback 4-step |
| CFRA | Dedicated preamble assigned in HO command | RAR with pre-assigned UL grant | PUSCH on TC-RNTI | None (no collision possible) |

---

## Step 0 — Read CONFIG

Before looking at PRACH logs, extract RA configuration from the CONFIG block:

```bash
python3 references/scripts/grep_multiline.py <logfile> '\[CONFIG.*Input configuration'
```

Key PRACH fields in the CONFIG dump:

| Field | What it tells you |
|---|---|
| `prach-ConfigurationIndex` | PRACH occasion periodicity and format |
| `nof_cb_preambles_per_ssb` | Threshold: preambles 0–(N−1) are 4-step CB; preambles N–63 are 2-step MsgA |
| `total_nof_ra_preambles` | Total preambles including CF ones; if > `nof_cb_preambles_per_ssb`, CFRA is in use |
| `two_step_rach` / `td_offset` | 2-step RACH enabled and MsgA timing offset |
| `cfra_enabled: true` | CFRA enabled (dedicated preambles will be assigned via RRC Reconfig) |
| `prach-RootSequenceIndex` | Root sequence; each cell must have a distinct root if multiple cells share a carrier |

**2-step vs 4-step preamble split:**
With `nof_cb_preambles_per_ssb: 60`, preambles 0–59 are 4-step CB, preambles 60–63 are 2-step MsgA.
With `nof_cb_preambles_per_ssb: 64` (default), all CB preambles are 4-step (no 2-step).

---

## Step 1 — PRACH detection (gNB PHY)

The PHY reports each detected preamble immediately after the PRACH occasion.

```
TIMESTAMP [PHY     ] [D|I] [sfn.slot] PRACH: rsi=N rssi=XdB detected_preambles=[{idx=N ta=X.Xus detection_metric=N.N power_dB=N.N}] t=Xus
```

Real examples:

```
# Run A — single 2-step preamble (idx=62 >= 60 → MsgA)
2026-05-11T13:03:13.360388 [PHY     ] [D] [   32.19] PRACH: rsi=1 rssi=-13.0dB detected_preambles=[{idx=62 ta=0.00us detection_metric=8.0 power_dB=-14.11}] t=259.6us

# Run B — CFRA dedicated preamble
2026-05-15T12:24:33.053778 [PHY     ] [I] [   32.19] PRACH: rsi=0 rssi=-42.1dB detected_preambles=[{idx=41 ta=0.26us detection_metric=17.0 power_dB=-42.63}] t=1409.2us

# Run C — multiple UEs in same PRACH occasion (contention)
2026-04-29T14:27:25.655464 [PHY     ] [I] [  432.19] PRACH: rsi=1 rssi=-8.2dB detected_preambles=[{idx=8 ta=0.00us detection_metric=1.8 power_dB=-13.28}, {idx=15 ta=0.00us detection_metric=1.8 power_dB=-13.23}, {idx=17 ta=0.00us detection_metric=2.9 power_dB=-12.08}] t=130.9us
```

Key fields:

| Field | Meaning |
|---|---|
| `rsi` | Root sequence index used to detect this occasion |
| `rssi` | Total received power including noise |
| `idx` | Detected preamble index — compare to CONFIG to classify (CB 4-step / CB 2-step / CF) |
| `ta` | Timing advance estimate (µs) — 0 for ZMQ; non-zero for real radio |
| `detection_metric` | Normalised peak metric; low values (< 2) are marginal detections |
| `power_dB` | Preamble power |
| `t=` | PHY processing time for the PRACH occasion |

**Grep:**
```bash
grep -c 'PRACH:.*detected' <logfile>             # count PRACH occasions
grep -m 20 'PRACH:.*detected' <logfile>           # first 20 detections
```

---

## Step 2 — SCHED PRACH event

After PHY detection, SCHED processes the preamble and assigns TC-RNTIs.

**Debug-level format** (sub-lines under "Processed slot events"):
```
[SCHED   ] [D] [sfn.slot] Processed slot events pci=N:
- PRACH: slot=sfn.slot preamble=N msgb-rnti=0xNNNN temp_crnti=0xNNNN ta_cmd=N
```

- `msgb-rnti` **non-zero** → preamble classified as 2-step MsgA (idx ≥ `nof_cb_preambles_per_ssb`)
- `msgb-rnti=0x0` → 4-step CB or CF preamble

**Info-level format** (inline, one line):
```
[SCHED   ] [I] [sfn.slot] Processed slot events pci=N: prach(ra-rnti=0xNNNN preamble=N tc-rnti=0xNNNN)
```

Real examples:
```
# Run A — 2-step preamble, debug level
- PRACH: slot=32.19 preamble=62 msgb-rnti=0x470b temp_crnti=0x4601 ta_cmd=0

# Run C — 4-step CB preambles, info level, multiple in same slot
2026-04-29T14:27:25.655547 [SCHED   ] [I] [  433.6] Processed slot events pci=1: prach(ra-rnti=0x10b preamble=8 tc-rnti=0x4604), prach(ra-rnti=0x10b preamble=15 tc-rnti=0x4605), prach(ra-rnti=0x10b preamble=17 tc-rnti=0x4606)
```

**Grep:**
```bash
grep -m 20 'Processed slot events.*prach\|PRACH: slot=' <logfile>
```

Note: preambles sharing the same `ra-rnti` were transmitted in the same PRACH time-frequency resource. Each gets a distinct `tc-rnti`.

---

## Step 3 — RAR scheduling (gNB SCHED → DL)

The gNB schedules the RAR in the next DL occasion. It appears as a sub-line in "Slot decisions":

**4-step CBRA RAR:**
```
- RAR PDSCH: ra-rnti=0xNNNN rb=[start..end) symb=[start..end) tbs=N mcs=N rv=N grants (N): tc-rnti=0xNNNN: rapid=N ta=N time_res=N
```
No `result=` field for normal 4-step RAR.

**2-step fallbackRAR** (gNB forced 4-step response to MsgA preamble):
```
- RAR PDSCH: ra-rnti=0x470b rb=[0..3) symb=[1..14) tbs=10 mcs=0 rv=0 grants (1): tc-rnti=0x4601: rapid=62 ta=0 time_res=4 result=fallbackRAR
```

**2-step MsgB success:**
```
- RAR PDSCH: ... result=msgb
```

**CFRA:** The gNB still sends an RAR for CFRA (pre-configured grant). The dedicated preamble is pre-assigned in the HO command, so contention resolution is skipped. The SCHED may allocate Msg3 directly in the same "Slot decisions" slot when the PRACH and Msg3 grant slot coincide.

A single RAR PDSCH can carry grants for multiple UEs (all preambles detected in the same PRACH occasion on the same ra-rnti):
```
grants (3): tc-rnti=0x4604: rapid=8 ..., tc-rnti=0x4605: rapid=15 ..., tc-rnti=0x4606: rapid=17 ...
```

**Grep:**
```bash
grep -m 20 'RAR PDSCH' <logfile>
```

---

## Step 4 — UE-side: PRACH and RAR reception (Amarisoft ue.log)

### UE PHY — PRACH transmission

```
HH:MM:SS.mmm [PHY] UL UEID 00    -   sfn.slot PRACH: sequence_index=N prb=S:N symb=0:12 [two_steps=1] epre=N.N [p=N]
```

- `sequence_index` = preamble index transmitted — should match `idx` in gNB PHY PRACH line
- `two_steps=1` — UE classified this as 2-step MsgA preamble
- `p=N` — transmit power in dBm (present in some runs)

Real examples:
```
# Run A — 2-step preamble
13:03:13.357 [PHY] UL 0001 00    -   32.19 PRACH: sequence_index=62 prb=11:12 symb=0:12 two_steps=1 epre=0.0

# Run B — CFRA dedicated preamble (no two_steps flag)
12:24:33.047 [PHY] UL 0001 00    -   32.19 PRACH: sequence_index=41 prb=11:12 symb=0:12 epre=-29.0 p=-16
```

### UE MAC — RAR reception

Two sequential lines appear when the UE receives and accepts the RAR:

```
HH:MM:SS.mmm [MAC] DL    - 00 RAR: rapid=N
HH:MM:SS.mmm [MAC] -  UEID 00 ta=N ul_grant=0xHHHHHH tc_rnti=0xNNNN
```

- `rapid=N` — RAPID carried in the RAR grant; UE accepts only if `rapid` matches its transmitted `sequence_index`
- `ta=N` — Timing Advance command (units ≈ 0.52 µs; 0 in ZMQ simulation)
- `ul_grant` — encoded UL resource grant for Msg3
- `tc_rnti` — TC-RNTI assigned by the gNB; should match `temp_crnti` in SCHED PRACH event

Real examples:
```
# Run A — 2-step fallbackRAR accepted
13:03:13.377 [MAC] -  0001 00 ta=0 ul_grant=0x23c40e tc_rnti=0x4601

# Run B — CFRA RAR accepted
12:24:33.063 [MAC] DL    - 00 RAR: rapid=41
12:24:33.063 [MAC] -  0001 00 ta=1 ul_grant=0x22a00e tc_rnti=0x4601
```

**RAPID mismatch (failure pattern):** If `RAR: rapid=N` appears but no `ta=X ul_grant=...` line follows for that UE, the UE rejected the RAR — the RAPID does not match the preamble it transmitted. The gNB assigned a TC-RNTI to the wrong preamble; it will schedule Msg3 on that TC-RNTI and decode empty PRBs (`crc=KO sinr=infdB` on the PHY side).

**Grep:**
```bash
grep -m 20 -E 'PRACH:|RAR:|ul_grant|tc_rnti' <ue.log>
```

---

## Step 5 — Msg3 (gNB SCHED + PHY)

### SCHED — Msg3 allocation

Msg3 appears in SCHED "Slot decisions" as a PUSCH with `msg3_delay=N`:

```
- UE PUSCH: ue=8192 [tc-rnti|rnti]=0xNNNN h_id=0 rb=[start..end) symb=[start..end) tbs=N rv=0 nrtx=0 nof_layers=1 msg3_delay=N
```

- `ue=8192` (sentinel 0x2000) — UE not yet fully established
- `msg3_delay=N` — slots from RAR to Msg3 PUSCH grant
- Typical `msg3_delay`: 7 slots (4-step CBRA), 14 slots (2-step fallbackRAR in this setup)

Real example:
```
# Run A — 2-step fallback Msg3
- UE PUSCH: ue=8192 tc-rnti=0x4601 h_id=0 rb=[26..29) symb=[0..14) tbs=11 rv=0 nrtx=0 nof_layers=1 msg3_delay=14
```

### PHY — Msg3 PUSCH result

```
TIMESTAMP [PHY     ] [D|I] [sfn.slot] PUSCH: rnti=0xNNNN h_id=0 prb=[start, end) symb=[0, 14) mod=QPSK rv=0 tbs=N crc=OK|KO iter=N.N sinr=N.NdB t=Xus ...
```

Real example (Msg3 OK):
```
2026-05-11T13:03:13.384370 [PHY     ] [D] [   34.19] PUSCH: rnti=0x4601 h_id=0 prb=[26, 29) symb=[0, 14) mod=QPSK rv=0 tbs=11 crc=OK iter=1.0 sinr=40.3dB t=115.9us uci_t=0.0us ret_t=0.0us
```

Msg3 KO with `sinr=infdB` → DTX: UE did not transmit (see `layers/phy.md` § DTX vs channel degradation).

### Allocation failure

If Msg3 PUSCH cannot be allocated (UL slot fully occupied):
```
[SCHED   ] [D] [sfn.slot] pci=N tc-rnti=0xNNNN: Failed to allocate PUSCH Msg3 reTx grant in slot sfn.slot. Retrying it in a later slot. Cause: <reason>
```

**Grep:**
```bash
grep -m 20 'msg3_delay\|Failed to allocate PUSCH Msg3' <logfile>
grep 'PUSCH.*0xNNNN' <logfile>   # substitute tc-rnti from RAR PDSCH
```

---

## Step 6 — Contention resolution → RRC Setup

After Msg3 is decoded successfully, the gNB promotes the UE from TC-RNTI to C-RNTI via Msg4 (contention resolution MAC CE + RRC Setup).

### gNB RRC

```
TIMESTAMP [RRC     ] [I] ue=N c-rnti=0xNNNN: CCCH UL rrcSetupRequest
TIMESTAMP [RRC     ] [I] ue=N c-rnti=0xNNNN: CCCH DL rrcSetup
TIMESTAMP [RRC     ] [I] ue=N c-rnti=0xNNNN: DCCH UL rrcSetupComplete
```

### gNB NGAP (triggers after rrcSetupComplete)

```
TIMESTAMP [NGAP    ] [I] Tx PDU ue=N ran_ue=N: InitialUEMessage
```

### Amarisoft UE RRC

```
HH:MM:SS.mmm [RRC] UL UEID 00 CCCH-NR: RRC setup request
HH:MM:SS.mmm [RRC] DL UEID 00 CCCH-NR: RRC setup
HH:MM:SS.mmm [RRC] UL UEID 00 DCCH-NR: RRC setup complete
```

Real example (Run A):
```
2026-05-11T13:03:13.386989 [RRC     ] [I] ue=0 c-rnti=0x4601: CCCH UL rrcSetupRequest
2026-05-11T13:03:13.387132 [RRC     ] [I] ue=0 c-rnti=0x4601: CCCH DL rrcSetup
2026-05-11T13:03:13.409979 [RRC     ] [I] ue=0 c-rnti=0x4601: DCCH UL rrcSetupComplete
2026-05-11T13:03:13.410018 [NGAP    ] [I] Tx PDU ue=0 ran_ue=0: InitialUEMessage
```

---

## Step 7 — METRICS sanity check

```bash
grep -m 10 'nof_prach_preambles\|msg3_ok\|msg3_nok' <logfile>
```

Fields from `[METRICS ] Scheduler cell pci=N metrics:` lines:

| Field | Healthy | Suspicious |
|---|---|---|
| `nof_prach_preambles` | > 0 during attach | = 0 for entire run (UE never reached gNB) |
| `msg3_ok` | = `nof_prach_preambles` in steady state | much less than preambles (Msg3 decoding failures) |
| `msg3_nok` | = 0 in steady state | > 0 (retry budget exceeded for some Msg3s) |

High `msg3_nok` with `nof_prach_preambles > 0` indicates either contention collisions (multiple UEs chose the same preamble) or Msg3 allocation failures (UL slot resource conflicts).

---

## CFRA differences

CFRA assigns dedicated preambles in the RRC Reconfiguration (handover command). The UE transmits the assigned preamble — no contention is possible.

Log differences vs CBRA:

- **CONFIG**: `cfra_enabled: true`, `total_nof_ra_preambles > nof_cb_preambles_per_ssb`
- **PHY PRACH**: `idx` is a fixed, predictable value across multiple HO attempts (same preamble each time)
- **UE PRACH**: no `two_steps=1` flag; `sequence_index` matches the assigned value
- **SCHED**: same RAR/Msg3 sequence as 4-step CBRA but contention resolution MAC CE is not strictly required (gNB may still include it)
- **METRICS**: `nof_prach_preambles=1` and `msg3_ok=1` for each HO attempt; reliable preamble-to-Msg3 ratio

---

## Common failure patterns

### 1. PRACH not detected by gNB

**Signal:** `nof_prach_preambles=0` in METRICS; no PHY PRACH lines near expected attach time.

**Causes:** UE transmitting on wrong PRACH occasion (carrier/SCS mismatch), RF path issues (real radio only), ZMQ port/address misconfiguration.

### 2. RAPID mismatch (preamble index classification)

**Signal:** UE log shows `RAR: rapid=N` but no `ta=X ul_grant=... tc_rnti=...` follow-up. gNB assigns Msg3 on a TC-RNTI the UE doesn't recognise. gNB PHY: `PUSCH: rnti=0xNNNN crc=KO sinr=infdB iter=max` (DTX).

**Root cause:** The preamble index the UE transmitted (UE PRACH `sequence_index`) does not match the preamble index the gNB reported in the RAR PDSCH (`rapid=`). Either the gNB detected the wrong preamble, or `nof_cb_preambles_per_ssb` is misconfigured differently on each side.

**Verification:** Compare UE `sequence_index` ↔ gNB SCHED `preamble=` ↔ RAR PDSCH `rapid=`. All three must match.

### 3. Msg3 DTX (UE silent at scheduled Msg3 slot)

**Signal:** `PUSCH: rnti=0xNNNN crc=KO sinr=infdB` at the Msg3 slot; repeated retransmissions; eventual `msg3_nok` increment.

**Cause:** Usually a RAPID mismatch (UE used a different TC-RNTI); or UE failed to decode the RAR. See `layers/phy.md` § DTX vs channel degradation.

### 4. Contention collision (4-step CBRA, multiple UEs)

**Signal:** Multiple UEs transmit the same preamble (`nof_prach_preambles=N` but `msg3_ok < N` and `msg3_nok > 0`); UE logs show `RAR: rapid=X` without subsequent `ul_grant` (all UEs got the RAR but only one wins contention resolution).

**Investigation:** Check gNB SCHED processed slot events for preamble index collisions across simultaneous PRACH occasions.

### 5. Msg3 allocation failure (UL slot congestion)

**Signal:** `Failed to allocate PUSCH Msg3 reTx grant` in SCHED; `msg3_nok > 0` in METRICS.

**Cause:** The target UL slot is fully occupied. Common in dense multi-UE scenarios or when semi-persistent UL allocations block the Msg3 timing window.

