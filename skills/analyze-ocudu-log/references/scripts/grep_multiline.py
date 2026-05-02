#!/usr/bin/env python3
"""
Search a log file for a pattern and print the full multiline entry for each match.

Runs 'grep -b' internally and, for each byte offset returned, seeks to the
enclosing log entry (from its timestamp line to the next) and prints it.
Entries with multiple grep matches are printed only once.

A log entry starts on a line beginning with a timestamp and extends until the
next timestamp-prefixed line (exclusive).

Usage:
    python3 grep_multiline.py <logfile> [grep-args...]

Examples:
    python3 grep_multiline.py gnb.log 'Input configuration'
    python3 grep_multiline.py gnb.log -i 'ue create'
    python3 grep_multiline.py gnb.log -E 'Procedure (started|finished)'
"""

import sys
import re
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import TIMESTAMP_PAT

ENTRY_START_RE = re.compile(r'^' + TIMESTAMP_PAT)
GREP_B_RE = re.compile(r'^(\d+):')


def find_entry_start(f, offset):
    """Seek backward from offset to the nearest timestamp line; return its byte offset."""
    pos = offset
    while pos > 0:
        f.seek(pos - 1)
        if f.read(1) == b'\n':
            break
        pos -= 1

    while True:
        f.seek(pos)
        if ENTRY_START_RE.match(f.readline().decode(errors='replace')):
            return pos
        if pos == 0:
            return 0
        pos -= 1
        while pos > 0:
            f.seek(pos - 1)
            if f.read(1) == b'\n':
                break
            pos -= 1


def find_entry_end(f, entry_start):
    """Return the byte offset of the next entry's timestamp line (or EOF)."""
    f.seek(entry_start)
    f.readline()
    while True:
        pos = f.tell()
        line = f.readline()
        if not line or ENTRY_START_RE.match(line.decode(errors='replace')):
            return pos


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <logfile> [grep-args...]", file=sys.stderr)
        sys.exit(1)

    logfile = sys.argv[1]
    grep_args = sys.argv[2:]

    proc = subprocess.Popen(
        ['grep', '-b'] + grep_args + [logfile],
        stdout=subprocess.PIPE, text=True,
    )

    seen = set()
    with open(logfile, 'rb') as f:
        for grep_line in proc.stdout:
            m = GREP_B_RE.match(grep_line)
            if not m:
                continue
            offset = int(m.group(1))

            entry_start = find_entry_start(f, offset)
            if entry_start in seen:
                continue
            seen.add(entry_start)

            entry_end = find_entry_end(f, entry_start)
            f.seek(entry_start)
            content = f.read(entry_end - entry_start).decode(errors='replace')

            print(f"# entry at offset {entry_start}")
            print(content, end='' if content.endswith('\n') else '\n')

    proc.wait()


if __name__ == '__main__':
    main()
