"""Shared helpers for OCUDU log parsing scripts."""

import re
from datetime import datetime

TIMESTAMP_PAT = r'\d{4}-\d{2}-\d{2}T[\d:.]+'
TIMESTAMP_RE = re.compile(TIMESTAMP_PAT)


def parse_ts(s):
    return datetime.fromisoformat(s)


def iter_lines(path):
    with open(path) as f:
        yield from f
