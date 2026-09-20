#!/usr/bin/env python3
"""Issue #230 — V2-F raw-receipt protocol: campaign identity + envelope.

Every correctness-bearing V2-F observation is a PRIMARY RAW RECEIPT whose
payload derives from retained command bytes (stdout/stderr/exit-code/
sysfs/journal/probe JSON), never from authored summaries. Architecture
follows the accepted #228 corrected-campaign pattern (schema /1 closure:
worktree == index == HEAD per source, pinned producer head) exactly;
host helpers are adapted from the accepted #228 host module, which was
itself adapted from #216.

Campaign question (issue #230): can the accepted V340L subject perform a
truthful, correct cross-die transfer through an already-advertised Vulkan
external-memory mechanism (opaque_fd / dma_buf) — in both directions, at
what bandwidth/service time, over which physical route (local PM8533
switch fabric vs the shared host-facing Gen3 x1 upstream), and safely
under a deliberately bounded campaign?

Advertisement is not validated execution, and validated execution is not
route proof: those are SEPARATE state dimensions in every artifact this
campaign emits.

Safety inheritance: the #216 terminal ``V2D_V340L_PLATFORM_STRESS_FAIL``
(retained fault: amdgpu ring-gfx timeout on die B during the accepted
#35 x1 transport seam, failed GPU reset ret=-62, wedged reset worker)
is a hard constraint. V2-F never runs the #35 transport seam. Its
bounded external-memory probe changes the fault preconditions
prospectively (see issue230_safety): a single-process Vulkan
export/import seam with fence-synchronized bounded copies, starting at
ONE 4-KiB correctness probe, per-arm health windows, and immediate-stop
conditions that retain the earliest failure and halt escalation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_ID = "issue230-v2f-v340l-external-memory"
AREA_REL = "docs/investigations/vulkan-v2-f-v340l-external-memory"
NS = "vulkan-v2-f-v340l-external-memory"

RECEIPT_SCHEMA = "inferswarm.v2f.receipt/1"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"

# Every producer module whose bytes are part of the correctness-bearing
# closure. The closure file itself is excluded (binding, not a bound
# source).
CLOSURE_SOURCES = (
    "scripts/issue230_receipt.py",
    "scripts/issue230_freeze.py",
    "scripts/issue230_authority.py",
    "scripts/issue230_host.py",
    "scripts/issue230_preflight.py",
    "scripts/issue230_safety.py",
    "scripts/issue230_transfer.py",
    "scripts/issue230_runner.py",
    "scripts/issue230_reduce.py",
    "scripts/issue230_assemble.py",
    "scripts/issue230_manifest.py",
)

# ---------------------------------------------------------------------------
# Frozen transfer campaign parameters (issue #230 Phase 2/4 — frozen
# PROSPECTIVELY, before any retained physical transfer).
# ---------------------------------------------------------------------------

#: The two fd-carried external-memory handle types #228 classified
#: advertised-bidirectional for transfer-usage buffers on both dies.
#: Each is an INDEPENDENT arm; one handle type's result is never
#: promoted to the other.
MECHANISMS = ("opaque_fd", "dma_buf")

#: Handle-type identity strings as they appear in receipts (canonical
#: spellings; the C producer maps them to Vulkan enum bits).
DIRECTIONS = ("a_to_b", "b_to_a")

#: First physical execution is ONE 4-KiB correctness probe in ONE
#: direction (a_to_b) — never a benchmark ladder (issue Phase 2).
PROBE_SIZE = 4096

#: Frozen conservative size ladder (issue Phase 4). 1 GiB is NOT in the
#: ladder: it requires a separately frozen gate that this campaign does
#: not grant.
LADDER_SIZES = (4096, 65536, 1 << 20, 16 << 20, 64 << 20, 256 << 20)

#: Retained repetitions per (mechanism, direction, size) after a frozen
#: warmup (warmup rows are retained but never reduced as measurements).
REPS_PER_SIZE = 5
WARMUPS_PER_SIZE = 1

#: Matched controls use the same sizes so peer-vs-control comparisons
#: are byte-matched (issue Phase 5: "same size/repetition policy where
#: meaningful").
CONTROL_REPS = 5
CONTROL_WARMUPS = 1

# Route-instrumentation set (sysfs paths sampled before/during/after
# every arm; retained raw). The kernel exposes no PM8533 per-port
# transaction counters on this host (#228 established this), so the
# route proof uses the bounded-alternative combination the issue
# authorizes: same-card switch ancestry + MEASURED x1 ceiling (fresh
# H2D/D2H controls) + host-staged controls + peer throughput, under the
# frozen decision rule in ROUTE_RULE below. Nominal Gen3 arithmetic is
# never substituted for measured behavior.
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

# ---------------------------------------------------------------------------
# Frozen route decision rule (issue #230 Phase 6 — primary output).
#
# All quantities are MEDIANS over the full retained repetition
# population at the LARGEST ladder size (256 MiB), derived mechanically
# by issue230_reduce from retained raw bytes. Definitions:
#
#   x1_ceiling  = max(median fresh H2D GB/s, median fresh D2H GB/s)
#                 at 256 MiB (each crossing of the host-facing Gen3 x1
#                 link alone cannot exceed this; a transfer routed via
#                 the upstream/root path moves each peer byte across
#                 the x1 link (at least) twice — request+data loopback
#                 or D2H+H2D staging — so it is bounded near x1/2).
#   host_staged = median host-staged same-direction GB/s at 256 MiB
#                 (explicitly host-mediated A->host->B control).
#   peer        = median external-memory transfer GB/s at 256 MiB for
#                 the mechanism/direction being classified.
#
# Bands (frozen; never tuned after observation):
#   BYPASS       : peer > 1.25 * x1_ceiling
#                  (impossible for any x1-crossing traffic; with the
#                  retained same-card switch ancestry this proves the
#                  transfer stayed local to the PM8533 fanout fabric)
#   UPSTREAM     : peer <= 1.25 * x1_ceiling AND
#                  0.70 * host_staged <= peer <= 1.40 * host_staged
#                  (x1-consistent AND statistically equivalent to the
#                  host-mediated control)
#   UNRESOLVED   : anything else, OR missing/incomplete control
#                  populations (no route conclusion without the
#                  controls; control 21)
# ---------------------------------------------------------------------------
ROUTE_RULE = {
    "bypass_factor": 1.25,
    "upstream_hoststaged_low": 0.70,
    "upstream_hoststaged_high": 1.40,
    "basis": [
        "measured medians only, largest ladder size, full populations",
        "no nominal PCIe arithmetic substitutes a measurement",
        "a bypass claim requires the matched controls to exist",
    ],
}


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
    return (len(parts) >= 3 and parts[0] == "v2f"
            and len(rid) <= 200
            and all(p for p in parts))


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
        raise ReceiptError(f"not a V2-F receipt: {path}")
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
# issue230_freeze (same corrected semantics as the accepted #228 /1).
# ---------------------------------------------------------------------------

def closure_document(repo: Path | None = None) -> dict[str, Any]:
    from issue230_freeze import closure_document as _closure
    return _closure(Path(repo) if repo is not None else ROOT)


def verify_closure(repo: Path | None = None,
                   committed: dict[str, Any] | None = None) -> dict[str, Any]:
    from issue230_freeze import verify_closure as _verify, FreezeError
    try:
        return _verify(Path(repo) if repo is not None else ROOT, committed)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc


def write_closure(repo: Path | None = None) -> Path:
    from issue230_freeze import write_closure as _write, FreezeError
    try:
        return _write(Path(repo) if repo is not None else ROOT)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc
