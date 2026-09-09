"""Parser for the retained RAW source-server access log (Issue #117 Arm B).

Input: evidence/arm-b/raw/source-server-access.log — the byte-exact copy of
/tmp/armb-source-server.log on inferswarm01 (the Source host), retrieved
read-only 2026-09-08 during the PR #127 correction. This parser re-derives
the request accounting from the raw lines themselves; nothing here is
hard-coded.
"""
from __future__ import annotations

import hashlib
import re

#: pin of the raw log as retained (both host copy and repo copy must match)
RAW_LOG_SHA256 = (
    "8b09e9575a51fdcf39b2a360d228140b7d314ac1b657f85d459a701e73c342e2")
RAW_LOG_BYTES = 21872
RAW_LOG_LINES = 429
COORDINATOR_IP = "10.0.0.206"
PARTICIPANT03_IP = "10.0.0.219"
SOURCE_HOST_IP = "10.0.0.141"

_LINE = re.compile(
    r'^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+"(?P<method>GET)\s+(?P<path>\S+)\s+'
    r'HTTP/[\d.]+"\s+(?P<status>\d{3})')


def parse(raw_text: str) -> dict:
    """Return the mechanically derived request accounting."""
    lines = raw_text.splitlines()
    banner = lines[0] if lines else ""
    gets = 0
    histogram: dict[str, int] = {}
    coordinator_gets = 0
    non_get = 0
    malformed = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        m = _LINE.match(line)
        if m is None:
            malformed += 1
            continue
        gets += 1
        ip = m.group("ip")
        histogram[ip] = histogram.get(ip, 0) + 1
        if ip == COORDINATOR_IP:
            coordinator_gets += 1
    return {
        "banner": banner,
        "get_requests": gets,
        "client_ip_histogram": histogram,
        "coordinator_get_requests": coordinator_gets,
        "non_get_lines": non_get,
        "malformed_lines": malformed,
        "line_count": len(lines),
    }


def parse_file(path) -> dict:
    data = open(path, "rb").read()
    if hashlib.sha256(data).hexdigest() != RAW_LOG_SHA256:
        raise ValueError(
            f"raw source-server log sha256 drift: {path} is not the "
            f"retained raw log (expected {RAW_LOG_SHA256[:16]}…)")
    if len(data) != RAW_LOG_BYTES:
        raise ValueError(f"raw source-server log size drift: {len(data)} "
                         f"(expected {RAW_LOG_BYTES})")
    return parse(data.decode())
