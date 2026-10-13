#!/usr/bin/env python3
"""Check an untimed MoE harness export against independent backend operands.

No backend calls, model downloads or hardware execution. Use the original
local GGUF shard; its identity remains the experiment's separately frozen
provenance. This proposed empirical contract does not confer qualification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from inferswarm.operator.source import _read_gguf_index
from operand_reference import CONTRACT, CPU_MODES, ABSOLUTE, RELATIVE, block, compare


class GGUFWeights:
    """Reuse the existing bounded GGUF index; read one expert at a time."""
    def __init__(self, path, layer, n_expert):
        self.stream = Path(path).open("rb")
        try:
            _, rows, _ = _read_gguf_index(self.stream, object_bytes=os.fstat(self.stream.fileno()).st_size)
            self.rows = {r.state_id: r for r in rows}
            self.prefix = f"blk.{layer}."
            self.n_expert = n_expert
        except Exception:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def __call__(self, kind, eid):
        if kind == "shared_gate":
            name, shape, typ = "ffn_gate_inp_shexp.weight", (2560,), 0
        else:
            name = f"ffn_{kind}_{'shexp' if eid is None else 'exps'}.weight"
            shape = (640, 2560) if kind == "down" else (2560, 640)
            if eid is not None:
                shape += (self.n_expert,)
            typ = 8
        r = self.rows.get(self.prefix + name)
        if r is None or r.shape != shape or r.ggml_type != typ:
            raise ValueError(f"missing/unsupported reference tensor: {name}")
        size = r.encoded_bytes if eid is None else r.encoded_bytes // self.n_expert
        if eid is not None and not 0 <= eid < self.n_expert:
            raise ValueError("reference expert outside GGUF bank")
        self.stream.seek(r.absolute_offset + (0 if eid is None else eid * size))
        raw = self.stream.read(size)
        if len(raw) != size:
            raise ValueError(f"truncated reference tensor: {name}")
        return raw


def check_case(case, gguf):
    case = Path(case)
    report = json.loads((case / "run.json").read_text())
    c = report["config"]
    T, E, split = c["tokens"], c["n_expert"], c["split"]
    if (T not in (1, 128) or c["n_embd"] != 2560 or c["n_ff"] != 640
            or c["n_used"] != 10 or E < 10 or not 0 <= split <= E
            or c["weights_mode"] != "GGUF"
            or c["native_pin"] != "llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"):
        raise ValueError("unsupported reference configuration")
    cpu, sec = c["reference_cpu_mode"], c["reference_secondary_mode"]
    expected_sec = cpu if c["secondary_kind"] == "cpu" else (
        "cuda-mmvq-q8_1" if T == 1 else "cuda-mmq-d4")
    if cpu not in CPU_MODES or sec != expected_sec or c["secondary_kind"] not in ("cpu", "cuda"):
        raise ValueError("unsupported/mismatched backend reference mode")
    reps = report["reps"]
    if len(reps) != c["reps"] or not reps or not report["resources_released"]:
        raise ValueError("incomplete native run")
    if not all(report["determinism_recheck"].get(k) is True for k in ("reference_bitwise", "serial_bitwise")):
        raise ValueError("native replay check failed")
    if report.get("negative_control", {}).get("comparator_rejected") is not True:
        raise ValueError("native negative control missing/failed")
    v = report["verdict"]
    if v["pass"] is not True and (v.get("reason") != "validation failed"
            or not any(r["checks"]["serial_vs_ref_pass"] is False for r in reps)):
        raise ValueError("native status/error check failed")
    result = {"contract": CONTRACT, "criterion": "block-scoped-empirical",
              "absolute": ABSOLUTE, "relative_plane_mass": RELATIVE,
              "cpu_mode": cpu, "secondary_mode": sec, "hardware_qualified": False,
              "legacy_native_verdict": v, "reps": []}
    loader = GGUFWeights(gguf, c["layer"], E)
    try:
        for i, rep in enumerate(reps):
            if rep["rep"] != i or not all(rep["checks"].get(k) is True for k in (
                    "routed_counts_ok", "overlap_vs_serial_bitwise", "overlap_vs_serial_pass")):
                raise ValueError("native schedule/routing check failed")
            def read(name, dtype, shape):
                raw = (case / f"rep-{i}-{name}").read_bytes()
                if len(raw) != int(np.prod(shape)) * np.dtype(dtype).itemsize:
                    raise ValueError(f"incomplete capture: {name}")
                return np.frombuffer(raw, dtype=dtype).reshape(shape)
            x = read("cur.f32", "<f4", (T, 2560))
            ids = read("ids.i32", "<i4", (T, 10))
            rw = read("weights.f32", "<f4", (T, 10))
            if (ids >= E).any():
                raise ValueError("captured expert outside bank")
            expected, masses = block(x, ids, rw, loader, split=split, n_ff=640,
                                     cpu_mode=cpu, secondary_mode=sec)
            checks = {k: compare(read(k + ".f32", "<f4", x.shape), expected[k], masses[k])
                      for k in expected}
            total = sum(expected.values())
            mass = sum(masses.values())
            serial = read("serial.f32", "<f4", x.shape)
            overlap = read("overlap.f32", "<f4", x.shape)
            if serial.tobytes() != overlap.tobytes():
                raise ValueError("exported schedule outputs are not bitwise equal")
            checks["serial"] = compare(serial, total, mass)
            checks["overlap"] = compare(overlap, total, mass)
            result["reps"].append({"rep": i, "checks": checks,
                "legacy_cpu_unsplit_diagnostic": rep["checks"].get("legacy_cpu_unsplit_diagnostic", {
                    "pass": rep["checks"]["serial_vs_ref_pass"],
                    "max_abs": rep["checks"]["serial_vs_ref_max_abs"],
                    "max_ratio": rep["checks"]["serial_vs_ref_max_ratio"]})})
    finally:
        loader.close()
    result["pass"] = all(v["pass"] for r in result["reps"] for v in r["checks"].values())
    result["status"] = "PROPOSED_EMPIRICAL_PASS" if result["pass"] else "FAIL"
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", type=Path)
    ap.add_argument("--gguf", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    try:
        result = check_case(args.case, args.gguf)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result = {"contract": CONTRACT, "pass": False, "status": "INVALID_OR_INCOMPLETE",
                  "hardware_qualified": False, "error": str(exc)}
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.json:
        args.json.write_text(text)
    print(text, end="")
    return 0 if result["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
