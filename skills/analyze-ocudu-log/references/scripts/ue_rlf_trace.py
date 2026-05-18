#!/usr/bin/env python3
"""
ue_rlf_trace.py — Triage a UE RLF by locating the first PUSCH failure, classifying it as
DTX vs channel degradation, and (optionally) correlating Amarisoft ue.log PDCCH anomalies.

Usage:
    python3 ue_rlf_trace.py --gnb <gnb.log> --rnti <0xXXXX> [--ue <ue.log>] [--window <seconds>]
"""

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# e.g. "2026-05-14T22:41:38.489179"
GNB_TS_PAT = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)")
# e.g. "22:41:38.474"
UE_TS_PAT = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d+)")

# gnb.log PUSCH line:
#   2026-05-14T22:41:38.489 [PHY] [I] [72.17] PUSCH: rnti=0x4603 ... crc=KO ... sinr=infdB
GNB_PUSCH_PAT = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)"
    r".*\[(?P<sfn>\d+\.\d+)\]"
    r"\s+PUSCH:\s+rnti=(?P<rnti>0x[0-9a-fA-F]+)"
    r".*?\bcrc=(?P<crc>OK|KO)"
    r"(?:.*?\bsinr=(?P<sinr>\S+))?"
    r"(?:.*?\biter=(?P<iter>\S+))?"
)

# ue.log PDCCH line (Amarisoft format):
#   22:41:38.474 [PHY] DL 0003 00 4603    72.6 PDCCH: ss_id=1 cce_index=0 al=4 dci=1_0
UE_PDCCH_PAT = re.compile(
    r"(?P<ts>\d{2}:\d{2}:\d{2}\.\d+)"
    r"\s+\[PHY\]\s+DL\s+\S+\s+\S+\s+(?P<rnti>[0-9a-fA-F]+)"
    r"\s+(?P<sfn>\d+\.\d+)\s+PDCCH:\s+(?P<rest>.*)"
)


def parse_gnb_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def parse_ue_ts(s: str, ref_date: str) -> datetime:
    return datetime.fromisoformat(f"{ref_date}T{s}")


def classify_kos(ko_entries: list[dict]) -> str:
    if not ko_entries:
        return "unknown"
    first = ko_entries[0]
    sinr = first.get("sinr", "")
    if sinr == "infdB":
        return "DTX"
    try:
        val = float(sinr.replace("dB", ""))
        if val < -5:
            return "degradation"
    except (ValueError, AttributeError):
        pass
    return "unknown"


def scan_gnb(path: Path, rnti_hex: str) -> tuple[list[dict], list[dict]]:
    rnti_norm = rnti_hex.lower()
    ok_entries: list[dict] = []
    ko_entries: list[dict] = []
    with path.open(errors="replace") as f:
        for line in f:
            m = GNB_PUSCH_PAT.search(line)
            if not m:
                continue
            if m.group("rnti").lower() != rnti_norm:
                continue
            entry = {
                "ts": m.group("ts"),
                "sfn": m.group("sfn"),
                "crc": m.group("crc"),
                "sinr": m.group("sinr") or "",
                "iter": m.group("iter") or "",
                "line": line.rstrip(),
            }
            if entry["crc"] == "OK":
                ok_entries.append(entry)
                if len(ok_entries) > 20:
                    ok_entries.pop(0)
            else:
                ko_entries.append(entry)
    return ok_entries, ko_entries


def scan_ue_pdcch(path: Path, rnti_hex: str, center_ts: datetime, window_s: float) -> list[dict]:
    rnti_digits = rnti_hex.lstrip("0x").lower().lstrip("0")
    ref_date = center_ts.date().isoformat()
    lo = center_ts - timedelta(seconds=window_s)
    hi = center_ts + timedelta(seconds=window_s)
    results: list[dict] = []
    with path.open(errors="replace") as f:
        for line in f:
            m = UE_PDCCH_PAT.search(line)
            if not m:
                continue
            if m.group("rnti").lower().lstrip("0") != rnti_digits:
                continue
            try:
                ts = parse_ue_ts(m.group("ts"), ref_date)
            except ValueError:
                continue
            if not (lo <= ts <= hi):
                continue
            rest = m.group("rest")
            ss_m = re.search(r"ss_id=(\d+)", rest)
            ss_id = int(ss_m.group(1)) if ss_m else -1
            results.append({
                "ts": m.group("ts"),
                "sfn": m.group("sfn"),
                "ss_id": ss_id,
                "rest": rest.rstrip(),
                "line": line.rstrip(),
            })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage UE RLF from gNB (and optionally UE) logs")
    parser.add_argument("--gnb", required=True, type=Path, help="Path to gnb.log")
    parser.add_argument("--rnti", required=True, help="UE RNTI in hex, e.g. 0x4603")
    parser.add_argument("--ue", type=Path, default=None, help="Path to Amarisoft ue.log (optional)")
    parser.add_argument("--window", type=float, default=2.0, help="Seconds either side of silence onset to search ue.log (default: 2)")
    args = parser.parse_args()

    if not args.gnb.exists():
        print(f"ERROR: gnb.log not found: {args.gnb}", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== PUSCH failure summary for rnti={args.rnti} ===")
    print(f"Scanning {args.gnb} ...", end=" ", flush=True)
    ok_entries, ko_entries = scan_gnb(args.gnb, args.rnti)
    print("done.")

    if not ko_entries:
        print("No PUSCH KOs found for this RNTI.")
        return

    first_ko = ko_entries[0]
    last_ok = ok_entries[-1] if ok_entries else None

    print(f"\nFirst KO:  [{first_ko['sfn']}]  {first_ko['ts']}  sinr={first_ko['sinr'] or '?'}  iter={first_ko['iter'] or '?'}")
    if last_ok:
        print(f"Last OK:   [{last_ok['sfn']}]  {last_ok['ts']}")
    else:
        print("Last OK:   (none found in log)")

    if ok_entries:
        recent = ok_entries[-min(5, len(ok_entries)):]
        print(f"\nLast {len(recent)} OK slots: " + "  ".join(f"[{e['sfn']}]" for e in reversed(recent)))

    mode = classify_kos(ko_entries)
    if mode == "DTX":
        print(f"\nClassification: DTX — sinr=infdB means the UE transmitted nothing (not a channel issue).")
    elif mode == "degradation":
        sinrs = [e["sinr"] for e in ko_entries[:5] if e.get("sinr")]
        print(f"\nClassification: Degradation — SINR trend: {' → '.join(sinrs)}")
    else:
        print(f"\nClassification: Unknown (sinr={first_ko.get('sinr', '?')})")

    if mode == "DTX":
        print(f"\nNext step: cross-reference ue.log for PDCCH anomalies near {first_ko['ts']}")
        print("  Look for: PDCCH ss_id=1 entries when gnb.log shows ss_id=2 for this UE")
        print("  See references/layers/rrc.md § Amarisoft ZMQ spurious DCI")

    if args.ue:
        if not args.ue.exists():
            print(f"\nWARNING: ue.log not found: {args.ue}", file=sys.stderr)
            return

        try:
            center = parse_gnb_ts(first_ko["ts"])
        except ValueError:
            print(f"\nERROR: could not parse first-KO timestamp: {first_ko['ts']}", file=sys.stderr)
            return

        lo_s = (center - timedelta(seconds=args.window)).strftime("%H:%M:%S")
        hi_s = (center + timedelta(seconds=args.window)).strftime("%H:%M:%S")
        print(f"\n=== ue.log PDCCH entries for rnti={args.rnti} in window [{lo_s} – {hi_s}] ===")
        print(f"Scanning {args.ue} ...", end=" ", flush=True)
        pdcch_entries = scan_ue_pdcch(args.ue, args.rnti, center, args.window)
        print("done.")

        if not pdcch_entries:
            print("  (no PDCCH entries found for this RNTI in the window)")
        else:
            for e in pdcch_entries:
                flag = ""
                if e["ss_id"] == 1:
                    flag = "  *** SPURIOUS? ss_id=1 in common search space — UE should use ss_id=2 for dedicated grants ***"
                print(f"  {e['ts']}  [{e['sfn']}]  PDCCH: {e['rest']}{flag}")


if __name__ == "__main__":
    main()
