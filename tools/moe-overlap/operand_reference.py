"""Independent Q8_0 operand reference for this MoE block, not a native backend.

Adapted from t128r2 recon1.py's quantizers and the existing loader-fixture
reference. Corrects signed-byte decoding, scale indexing and block layout.
All packs below are reconstructed predictions, never captured device bytes.
"""
from __future__ import annotations

import numpy as np

CPU_MODES = ("cpu-scalar-q8_0", "cpu-avx-q8_0")
MODES = CPU_MODES + ("cuda-mmvq-q8_1", "cuda-mmq-d4")
CONTRACT = "moe-operand-reference/2"
# Fixed before held-out hardware validation. Empirical for this block only:
# 16 F32 eps of independently weighted plane mass, plus one F32 eps absolute.
# It covers accumulation/nonlinear implementation differences AFTER operand
# reconstruction, not quantization representation differences or a theorem.
ABSOLUTE = 2.0 ** -23
RELATIVE = 2.0 ** -19


def _finite(x):
    if not np.isfinite(x).all():
        raise ValueError("non-finite reference operand")


def quantize(x, mode):
    if mode not in MODES:
        raise ValueError(f"unsupported operand mode: {mode}")
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 1 or not x.size or x.size % 32:
        raise ValueError("activation must contain complete 32-element blocks")
    _finite(x)
    b = x.reshape(-1, 32)
    amax = np.abs(b).max(axis=1)
    d = amax / np.float32(127)
    inv = np.zeros_like(d)
    if mode == "cpu-scalar-q8_0":
        np.divide(np.float32(1), d, out=inv, where=d != 0)
    else:
        np.divide(np.float32(127), amax, out=inv, where=amax != 0)
    if mode == "cuda-mmvq-q8_1":
        v = np.zeros_like(b)
        np.divide(b, d[:, None], out=v, where=d[:, None] != 0)
    else:
        v = b * inv[:, None]
    _finite(v)
    q = np.rint(v) if mode == "cpu-avx-q8_0" else np.copysign(np.floor(np.abs(v.astype(np.float64)) + 0.5), v)
    if mode == "cuda-mmq-d4":
        scale = np.zeros_like(d)
        np.divide(np.float32(1), inv, out=scale, where=inv != 0)
    else:
        scale = d.astype(np.float16).astype(np.float32)
    _finite(scale)
    if (np.abs(q) > 127).any():
        raise ValueError("unrepresentable activation code")
    return q.astype(np.int32), scale


def decode_q8(raw, rows, cols):
    if cols % 32 or len(raw) != rows * (cols // 32) * 34:
        raise ValueError("Q8_0 extent does not match projection shape")
    b = np.frombuffer(raw, dtype=np.uint8).reshape(rows, cols // 32, 34)
    scales = b[:, :, :2].copy().view("<f2").reshape(rows, cols // 32).astype(np.float64)
    codes = b[:, :, 2:].copy().view(np.int8).astype(np.int32)
    _finite(scales)
    return codes, scales


def project(raw, x, rows, mode):
    q, scales = quantize(x, mode)
    wq, ws = decode_q8(raw, rows, len(x))
    # Exact integer dot per block (32*127*128 < 2**31), then F64 scale/sum.
    integer = np.einsum("rbk,bk->rb", wq, q, dtype=np.int64)
    y = (integer.astype(np.float64) * ws * scales.astype(np.float64)).sum(axis=1)
    return y.astype(np.float32)


def expert(x, up, gate, down, n_ff, mode):
    u = project(up, x, n_ff, mode)
    g = project(gate, x, n_ff, mode)
    # Source operation order, with explicit F32 graph-intermediate boundaries.
    with np.errstate(over="ignore"):
        hidden = (g / (np.float32(1) + np.exp(-g))) * u
    return project(down, hidden, len(x), mode)


def block(x, ids, weights, load, *, split, n_ff, cpu_mode, secondary_mode):
    """Expected per-backend partials/shared from original weights and routing.

    load(kind, expert_id) returns original Q8 bytes, or shared F32 gate bytes.
    No native outputs or backend API participate in computing expected values.
    """
    if cpu_mode not in CPU_MODES or secondary_mode not in MODES:
        raise ValueError("unsupported block operand mode")
    x = np.asarray(x, dtype=np.float32)
    ids = np.asarray(ids)
    weights = np.asarray(weights, dtype=np.float32)
    if x.ndim != 2 or ids.shape != (len(x), 10) or weights.shape != ids.shape:
        raise ValueError("block requires matching token/top-10 geometry")
    if ids.dtype.kind not in "iu" or (ids < 0).any() or (weights < 0).any():
        raise ValueError("invalid selected ids/weights")
    _finite(x); _finite(weights)
    if any(len(set(row.tolist())) != 10 for row in ids):
        raise ValueError("duplicate selected expert")
    outputs = {name: np.zeros_like(x, dtype=np.float64) for name in ("cpu", "sec", "shared")}
    masses = {name: np.zeros_like(x, dtype=np.float64) for name in outputs}
    for t, row in enumerate(ids):
        for slot, eid in enumerate(row):
            eid = int(eid)
            name, mode = ("cpu", cpu_mode) if eid < split else ("sec", secondary_mode)
            p = expert(x[t], *(load(k, eid) for k in ("up", "gate", "down")), n_ff, mode)
            weighted = (p * weights[t, slot]).astype(np.float64)
            outputs[name][t] += weighted
            masses[name][t] += np.abs(weighted)
        shared = expert(x[t], *(load(k, None) for k in ("up", "gate", "down")), n_ff, cpu_mode)
        gate = np.frombuffer(load("shared_gate", None), dtype="<f4")
        if gate.shape != x[t].shape:
            raise ValueError("shared gate extent mismatch")
        _finite(gate)
        logit = float(np.dot(gate.astype(np.float64), x[t].astype(np.float64)))
        e = np.exp(-abs(logit))
        sig = 1 / (1 + e) if logit >= 0 else e / (1 + e)
        outputs["shared"][t] = shared.astype(np.float64) * sig
        masses["shared"][t] = np.abs(outputs["shared"][t])
    return outputs, masses


def compare(got, expected, mass):
    got = np.asarray(got)
    if got.shape != expected.shape or mass.shape != expected.shape:
        raise ValueError("comparison shape mismatch")
    _finite(got); _finite(expected); _finite(mass)
    tolerance = ABSOLUTE + RELATIVE * mass
    error = np.abs(got.astype(np.float64) - expected)
    return {"pass": bool((error <= tolerance).all()),
            "max_abs": float(error.max()), "max_ratio": float((error / tolerance).max())}
