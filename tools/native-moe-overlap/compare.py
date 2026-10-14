#!/usr/bin/env python3
"""Compare native IS309_CAPTURE input/result records; no qualification claim.

Exact input/output equality is required for the same-work schedule comparison.
Always report finite checks, max absolute difference and RMS. No tolerances are
learned, widened, or borrowed from historical heterogeneous qualification.
"""
from __future__ import annotations

import argparse
from array import array
import json
import math
from pathlib import Path
import struct
import sys

HEADER = struct.Struct("<IIIIQ")


def records(path):
    path = Path(path)
    if path.stat().st_size > 64 << 20:
        raise ValueError("capture exceeds the bounded 64 MiB comparison budget")
    blob = path.read_bytes()
    pos = 0
    rows = []
    while pos < len(blob):
        if len(blob) - pos < HEADER.size:
            raise ValueError("truncated capture header")
        magic, layer, embd, tokens, step = HEADER.unpack_from(blob, pos)
        pos += HEADER.size
        count = embd * tokens
        if magic != 0x39303349 or not (0 < count <= 2**21) or step == 0:
            raise ValueError("invalid or over-budget capture record")
        if len(blob) - pos < count * 8:
            raise ValueError("truncated input/output capture")
        values = array("f")
        values.frombytes(blob[pos:pos + count * 8])
        if sys.byteorder != "little":
            values.byteswap()
        pos += count * 8
        rows.append(((layer, embd, tokens, step), values[:count], values[count:]))
    if not rows:
        raise ValueError("empty capture")
    return rows


def diagnostic(left, right):
    if len(left) != len(right):
        return {"pass": False, "finite": False, "max_abs": None, "rms": None}
    finite = all(math.isfinite(v) for v in (*left, *right))
    delta = [abs(a - b) for a, b in zip(left, right)]
    return {"pass": finite and left == right, "finite": finite,
            "max_abs": max(delta) if finite else None,
            "rms": math.sqrt(math.fsum(v*v for v in delta) / len(delta)) if finite else None}


def compare(serial, overlap):
    a, b = records(serial), records(overlap)
    report = {"schema": "native-moe-scheduling-comparison/1", "pass": len(a) == len(b),
              "serial_records": len(a), "overlap_records": len(b), "records": [],
              "scope": "same-work scheduling equality; not model qualification"}
    for index, (left, right) in enumerate(zip(a, b)):
        row = {"index": index, "shape_step_match": left[0] == right[0],
               "input": diagnostic(left[1], right[1]), "output": diagnostic(left[2], right[2])}
        report["pass"] &= row["shape_step_match"] and row["input"]["pass"] and row["output"]["pass"]
        report["records"].append(row)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", type=Path)
    parser.add_argument("overlap", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.serial, args.overlap)
    except (OSError, ValueError) as error:
        result = {"pass": False, "error": str(error)}
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    raise SystemExit(0 if result["pass"] else 1)
