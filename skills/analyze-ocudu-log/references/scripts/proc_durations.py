#!/usr/bin/env python3
"""
Measure durations between 'Procedure started' and 'Procedure finished' log lines.
Works for any component layer and any procedure name.

Usage:
    python3 proc_durations.py <logfile> [--layer LAYER] [--proc PROC] [--top N]

Examples:
    python3 proc_durations.py gnb.log --layer DU-MNG --proc "UE Create" --top 10
    python3 proc_durations.py gnb.log --proc "F1 Setup"
    python3 proc_durations.py gnb.log --layer RRC
"""

import sys
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import parse_ts, iter_lines, TIMESTAMP_PAT

LINE_RE = re.compile(
    r'(?P<ts>' + TIMESTAMP_PAT + r')'
    r' \[(?P<component>[^\]]+)\] \[.\]'
    r'.*proc="(?P<proc>[^"]+)": Procedure (?P<state>started|finished)'
)
UE_RE = re.compile(r'\bue=(\d+)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logfile')
    ap.add_argument('--layer', default=None, help='Filter by component tag (e.g. DU-MNG, RRC, F1AP)')
    ap.add_argument('--proc', default=None, help='Filter by procedure name (e.g. "UE Create")')
    ap.add_argument('--top', type=int, default=10, metavar='N', help='Number of slowest entries to show (default: 10)')
    args = ap.parse_args()

    starts = {}
    durations = []

    for line in iter_lines(args.logfile):
        m = LINE_RE.search(line)
        if not m:
            continue
        comp = m.group('component').strip()
        proc = m.group('proc')
        if args.layer and args.layer not in comp:
            continue
        if args.proc and args.proc != proc:
            continue
        ue_m = UE_RE.search(line)
        ue = int(ue_m.group(1)) if ue_m else None
        key = (comp, proc, ue)
        ts = parse_ts(m.group('ts'))
        if m.group('state') == 'started':
            starts[key] = ts
        elif m.group('state') == 'finished' and key in starts:
            dt = (ts - starts.pop(key)).total_seconds() * 1000
            durations.append((dt, comp, proc, ue, ts.isoformat()))

    durations.sort(reverse=True)

    parts = []
    if args.layer:
        parts.append(f'[{args.layer}]')
    if args.proc:
        parts.append(f'proc="{args.proc}"')
    label = ' '.join(parts) if parts else 'all procedures'
    print(f"Total completed {label}: {len(durations)}")

    if not durations:
        sys.exit(0)

    print(f"\nTop {args.top} slowest (ms):")
    for dt, comp, proc, ue, ts in durations[:args.top]:
        ue_str = f' ue={ue}' if ue is not None else ''
        print(f'  [{comp}]{ue_str} proc="{proc}"  {dt:8.3f} ms  finished={ts}')

    print(f"\nFastest : {durations[-1][0]:.3f} ms")
    print(f"Median  : {durations[len(durations)//2][0]:.3f} ms")
    print(f"Mean    : {sum(d for d, *_ in durations) / len(durations):.3f} ms")


if __name__ == '__main__':
    main()
