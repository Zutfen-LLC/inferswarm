#!/usr/bin/env python3
"""Issue #228 — V2-E raw-receipt protocol: campaign identity + envelope.

Every correctness-bearing V2-E observation is a PRIMARY RAW RECEIPT whose
payload derives from retained command bytes (stdout/stderr/exit-code/
sysfs/journal/probe JSON), never from authored summaries. Architecture
follows the accepted #216 corrected-campaign pattern (schema /3 closure:
worktree == index == HEAD per source, pinned producer head) exactly.

Campaign question (issue #228): can the V340L's two independently
addressable Vega dies exchange data directly through their on-card
PM8533 PCIe-switch topology at materially different bandwidth/latency
from host-mediated traffic, and can that route be proven without relying
on the X12's shared Gen3 x1 upstream link?

Safety inheritance: the #216 terminal ``V2D_V340L_PLATFORM_STRESS_FAIL``
(retained fault: amdgpu ring-gfx timeout on die B during the accepted
#35 x1 transport seam, failed GPU reset ret=-62, wedged reset worker)
is a hard constraint. V2-E never runs that transport seam. Its bounded
probe changes the fault preconditions prospectively: (a) device-group
peer copies instead of per-die host-transport probing, (b) a frozen
conservative size ladder starting at 4 KiB with correctness verified
after EVERY timed operation, (c) per-arm health deltas (AER, amdgpu
journal, device presence) collected after every size boundary, (d)
immediate-stop conditions that retain the failure and halt escalation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_ID = "issue228-v2e-v340l-interdie-peer-link"
AREA_REL = "docs/investigations/vulkan-v2-e-v340l-peer-link"
NS = "vulkan-v2-e-v340l-peer-link"

RECEIPT_SCHEMA = "inferswarm.v2e.receipt/1"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"

# Every producer module whose bytes are part of the correctness-bearing
# closure. The closure file itself is excluded (binding, not a bound
# source).
CLOSURE_SOURCES = (
    "scripts/issue228_receipt.py",
    "scripts/issue228_freeze.py",
    "scripts/issue228_authority.py",
    "scripts/issue228_host.py",
    "scripts/issue228_capability.py",
    "scripts/issue228_probe.py",
    "scripts/issue228_ladder.py",
    "scripts/issue228_baselines.py",
    "scripts/issue228_reduce.py",
    "scripts/issue228_assemble.py",
    "scripts/issue228_manifest.py",
)

# Frozen transfer ladder (issue #228 Phase 3, prospectively frozen BEFORE
# any physical output; 1 GiB admitted only if every smaller arm is clean
# — the runner enforces the gate mechanically and the reducer refuses a
# 1 GiB row when any smaller size failed or is absent).
LADDER_SIZES = (4096, 65536, 1 << 20, 16 << 20, 64 << 20, 256 << 20)
EXTENDED_SIZE = 1 << 30  # conditional extension, gated on clean ladder
REPS_PER_SIZE = 5
WARMUPS_PER_SIZE = 1
LATENCY_BYTES = 4096
LATENCY_REPS = 200
BIDIR_REPS = 8

# Route-instrumentation set (sysfs paths sampled before/during/after
# every arm; retained raw). Byte counters: the kernel exposes no
# PM8533 per-port transaction counters on this host, so the route proof
# uses the bounded-alternative combination the issue authorizes
# (capability authority + same-card switch ancestry + measured x1
# ceiling + peer throughput + host-link observation + matched
# direct-vs-staged controls).
ROUTE_BDFS = {
    "root_port": "0000:00:1d.0",
    "switch_upstream": "0000:02:00.0",
    "switch_downstream_a": "0000:03:00.0",
    "switch_downstream_b": "0000:03:01.0",
    "die_a": "0000:06:00.0",
    "die_b": "0000:09:00.0",
    "control_nv": "0000:0a:00.0",
}

# Host-facing health BDFs whose AER counters are delta-tracked per arm.
HEALTH_BDFS = (
    "0000:06:00.0", "0000:09:00.0",      # the dies
    "0000:02:00.0", "0000:03:00.0", "0000:03:01.0",  # PM8533 ports
    "0000:00:1d.0", "0000:0a:00.0",      # root port + NV control
)


class ReceiptError(RuntimeError):
    """Receipt emission/validation failed; the campaign must stop."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def bind_raw(root: Path, rel_path: str) -> dict[str, Any]:
    """Bind a retained raw artifact by content: {rel_path, sha256, bytes}."""
    path = root / rel_path
    if not path.is_file():
        raise ReceiptError(f"raw artifact missing: {rel_path}")
    data = path.read_bytes()
    return {"rel_path": rel_path, "sha256": sha256_bytes(data),
            "byte_count": len(data)}


def receipt_id_ok(rid: str) -> bool:
    parts = rid.split("-")
    return len(parts) >= 3 and parts[0] == "v2e" and len(rid) <= 200


def emit_receipt(out_dir: Path, receipt: dict[str, Any]) -> Path:
    """Write one primary raw receipt; refuse duplicates and bad ids."""
    required = ("schema", "campaign_id", "receipt_id", "phase", "attempt_id",
                "utc", "raw_bindings", "payload")
    for key in required:
        if key not in receipt:
            raise ReceiptError(f"receipt missing required field: {key}")
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise ReceiptError(f"wrong schema: {receipt['schema']}")
    if receipt["campaign_id"] != CAMPAIGN_ID:
        raise ReceiptError(f"wrong campaign: {receipt['campaign_id']}")
    if not receipt_id_ok(receipt["receipt_id"]):
        raise ReceiptError(f"malformed receipt id: {receipt['receipt_id']}")
    if not receipt["raw_bindings"]:
        raise ReceiptError("receipt must bind at least one raw artifact")
    for binding in receipt["raw_bindings"]:
        if set(binding) != {"rel_path", "sha256", "byte_count"}:
            raise ReceiptError(f"bad raw binding shape: {binding}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{receipt['receipt_id']}.json"
    if out.exists():
        raise ReceiptError(f"duplicate receipt id: {receipt['receipt_id']}")
    body = dict(receipt)
    body.pop("receipt_digest", None)
    body["receipt_digest"] = sha256_bytes(canonical(body))
    out.write_bytes(json.dumps(body, indent=1, sort_keys=True).encode()
                    + b"\n")
    return out


def load_receipt(path: Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8",
                                        errors="strict"))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError(f"not a V2-E receipt: {path}")
    return receipt


def verify_receipt_digest(path: Path) -> dict[str, Any]:
    """Load one receipt and re-verify its digest + raw bindings."""
    receipt = load_receipt(path)
    body = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    expect = sha256_bytes(canonical(body))
    if receipt.get("receipt_digest") != expect:
        raise ReceiptError(f"receipt digest mismatch: {path.name}")
    ev_root = path.parent.parent  # receipts live in <ev>/receipts/
    for binding in receipt["raw_bindings"]:
        art = ev_root / binding["rel_path"]
        if not art.is_file():
            raise ReceiptError(
                f"bound raw artifact missing: {binding['rel_path']}")
        data = art.read_bytes()
        if len(data) != binding["byte_count"] \
                or sha256_bytes(data) != binding["sha256"]:
            raise ReceiptError(
                f"bound raw artifact diverges: {binding['rel_path']}")
    return receipt


# ---------------------------------------------------------------------------
# Producer-source closure (pre-execution freeze). Delegates to
# issue228_freeze (same corrected semantics as the accepted #216 /3).
# ---------------------------------------------------------------------------

def closure_document(repo: Path | None = None) -> dict[str, Any]:
    from issue228_freeze import closure_document as _closure
    return _closure(Path(repo) if repo is not None else ROOT)


def verify_closure(repo: Path | None = None,
                   committed: dict[str, Any] | None = None) -> dict[str, Any]:
    from issue228_freeze import verify_closure as _verify, FreezeError
    try:
        return _verify(Path(repo) if repo is not None else ROOT, committed)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc


def write_closure(repo: Path | None = None) -> Path:
    from issue228_freeze import write_closure as _write, FreezeError
    try:
        return _write(Path(repo) if repo is not None else ROOT)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc
