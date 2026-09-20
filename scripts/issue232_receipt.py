#!/usr/bin/env python3
"""Issue #232 — V2-G raw-receipt protocol: campaign identity + envelope.

Every correctness-bearing V2-G observation is a PRIMARY RAW RECEIPT whose
payload derives from retained command bytes (stdout/stderr/exit-code/
sysfs/journal), never from authored summaries. Architecture follows the
accepted #230 corrected-campaign pattern (schema /1 closure: worktree ==
index == HEAD per source, pinned producer head) exactly.

Campaign question (issue #232): the V2-F fault boot carried a CHRONIC
Correctable Physical-Layer RxErr flood sourced at the PM8533 upstream
port 0000:02:00.0 on the width-downgraded Gen3 x1 link — a condition
that predates V2-F and whose causal relationship to the #216/#230
amdgpu ring/reset fault is UNKNOWN. V2-G remediates the physical PCIe
path first (one intervention at a time), proves a clean link under a
PROSPECTIVELY frozen gate, and only then authorizes one narrowly
bounded replay of the previously faulting B->A external-memory seam.

Separate state dimensions (never conflated, in every artifact):
  PCIE_PATH_HEALTH      — the chronic RxErr condition and its
                          remediation;
  V340L_DRIVER_HEALTH   — enumeration/identity/driver usability of both
                          dies (no GPU transfer workload before the
                          clean-link gate);
  EXTERNAL_MEMORY_CORRECTNESS — replay arm results (only after the
                          gate passes and replay is authorized);
  AMDGPU_RING_STABILITY — amdgpu timeout/reset/device-loss classes;
  PHYSICAL_ROUTE        — which physical path carries the traffic.

Correctable AER is never treated as harmless merely because it is
correctable, and the disappearance of AER alone never proves the V340L
fault is solved (the replay answers that as its own dimension).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_ID = "issue232-v2g-pcie-path-remediation"
AREA_REL = "docs/investigations/vulkan-v2-g-pcie-path-remediation"
NS = "vulkan-v2-g-pcie-path-remediation"

RECEIPT_SCHEMA = "inferswarm.v2g.receipt/1"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"

# Every producer module whose bytes are part of the correctness-bearing
# closure. The closure file itself is excluded (binding, not a bound
# source).
CLOSURE_SOURCES = (
    "scripts/issue232_receipt.py",
    "scripts/issue232_freeze.py",
    "scripts/issue232_authority.py",
    "scripts/issue232_host.py",
    "scripts/issue232_baseline.py",
    "scripts/issue232_gate.py",
    "scripts/issue232_qualify.py",
    "scripts/issue232_replay.py",
    "scripts/issue232_reduce.py",
    "scripts/issue232_assemble.py",
    "scripts/issue232_manifest.py",
)

# ---------------------------------------------------------------------------
# Frozen campaign parameters (issue #232 — frozen PROSPECTIVELY, before
# any retained remediation observation; never tuned after observation).
# ---------------------------------------------------------------------------

#: Predecessor physical topology (frozen from the accepted V2-F
#: evidence #230). These bind the PATH, not the post-power-cycle BDFs:
#: after any physical intervention the current-boot chain is RE-DERIVED
#: from fresh lspci bytes and bound by switch identity + bus chaining
#: (never assumed equal to these literals — issue control 1).
HISTORICAL_BDFS = {
    "root_port": "0000:00:1d.0",
    "switch_upstream": "0000:02:00.0",
    "switch_downstream_a": "0000:03:00.0",
    "switch_downstream_b": "0000:03:01.0",
    "die_a": "0000:06:00.0",
    "die_b": "0000:09:00.0",
    "control_nv": "0000:0a:00.0",
}

#: The switch vendor:device id that identifies the PM8533 upstream port
#: in fresh lspci -nn output REGARDLESS of slot/BDF (the stable
#: identity seam for post-intervention re-binding; the tree chain is
#: then derived from that row's bus, not from historical literals).
PM8533_ID = "11f8:8533"
VEGA_ID = "1002:6864"

#: Accepted fault-boot condition this campaign remediates against
#: (V2-F supplementary whole-boot AER record, retained bytes): the
#: chronic Correctable Physical-Layer RxErr flood sourced at the PM8533
#: upstream port, ~477 events/min averaged across the whole fault boot,
#: 250,507 parsed events from the upstream port alone.
FAULT_BOOT_BASELINE = {
    "source": ("issue230-v2f-v340l-external-memory supplementary "
               "SUPPLEMENTARY-FAULT-BOOT-AER.json"),
    "boot_id": "9121c110-4eaf-446b-84f4-f1a90c792801",
    "severity_counts": {"Correctable": 250851,
                        "Uncorrectable": 0, "DPC": 0},
    "upstream_port_events": 250507,
    "rate_per_minute": {
        "pre_campaign_avg": 477,
        "campaign_window": 477,
        "post_campaign": 232,
    },
}

#: Clean-link gate criterion (issue #232 Phase 3): PREFER ZERO RxErr on
#: the candidate upstream path over the fixed confirmation interval.
#: Any nonzero threshold would have to be frozen BEFORE observing the
#: confirmation result with an orders-of-magnitude justification; this
#: campaign freezes ZERO (issue control 10: no post-hoc threshold).
CLEAN_LINK_RXERR_MAX = 0

#: Fixed confirmation interval (minutes) for every clean-link gate
#: evaluation: one full interval of sysfs AER counters + journal event
#: census on the candidate path, GPUs idle (no workload before the
#: gate).
GATE_INTERVAL_MINUTES = 15

#: The clean result must repeat across at least one COLD power cycle
#: (issue Phase 3; warm reboot never substitutes — control 8).
GATE_REQUIRED_COLD_CONFIRMATIONS = 1

#: Replay ladder (issue Phase 5): the smallest scientifically useful
#: sequence approaching the previous boundary; the first replay NEVER
#: jumps to the historical fault scale (control 15), and 64 MiB is ONE
#: exact-correct rep (no warmup/repetition ladder until the single
#: 64-MiB result is known).
REPLAY_LADDER = (
    {"size_bytes": 4096, "reps": 1, "warmups": 0},
    {"size_bytes": 1 << 20, "reps": 1, "warmups": 0},
    {"size_bytes": 16 << 20, "reps": 1, "warmups": 0},
    {"size_bytes": 64 << 20, "reps": 1, "warmups": 0},
)
#: Seed family for replay arms (deterministic; frozen).
REPLAY_SEED_BASE = 0x23200000

#: The accepted V2-F producer the replay must be byte-identical to
#: (issue Phase 5: replay producer identity). The replay driver invokes
#: THAT closure's transfer binary source, unmodified: any change
#: requires a separately reviewed freeze. The closure digest is NEVER
#: hand-copied here — the authority builder re-derives it from the
#: retained PRODUCER-CLOSURE.json bytes and asserts it self-validates
#: (a hand-copied digest always drifts).
REPLAY_PRODUCER_PIN = {
    "campaign": "issue230-v2f-v340l-external-memory",
    "producer_head": "30cf699688aa3d718fb475f5390317ebb4ba7385",
    "closure_rel": ("docs/investigations/vulkan-v2-f-v340l-external-memory/"
                    "PRODUCER-CLOSURE.json"),
    "transfer_source": "scripts/issue230_transfer.py",
    "transfer_source_sha256": None,  # bound at authority build
    "closure_digest": None,  # bound at authority build (from file bytes)
}

#: Mechanism/direction of the replay seam (frozen): the previously
#: faulting B->A opaque_fd external-memory arm.
REPLAY_MECHANISM = "opaque_fd"
REPLAY_DIRECTION = "b_to_a"

#: Immediate-stop conditions during replay (issue Phase 5), identical
#: in class to the V2-F safety machine plus the RxErr-recurrence
#: condition this campaign adds.
REPLAY_STOP_CONDITIONS = (
    "correctness_mismatch",
    "ring_timeout_or_hang",
    "gpu_reset_or_reset_failure",
    "device_disappearance",
    "d_state_wedge",
    "uncorrectable_aer_or_dpc",
    "material_rxerr_flood_recurrence",
    "unexpected_topology_or_width_change",
    "nonzero_producer_exit",
)

#: Terminal vocabulary (issue Phase 6). Exactly one primary terminal is
#: derivable deterministically from retained evidence.
TERMINALS = (
    "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS",
    "V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED",
    "V2G_PCIE_PATH_REMEDIATED_DIFFERENT_FAILURE",
    "V2G_PCIE_PATH_REMEDIATION_FAILED",
    "V2G_PCIE_PATH_CLEAN_NO_REPLAY",
    "V2G_EVIDENCE_BLOCKED",
)

#: Nonclaims carried by every terminal (issue acceptance criteria).
NONCLAIMS = (
    "no causal claim between the historical chronic RxErr condition and "
    "the #216/#230 amdgpu ring/reset faults without discriminating "
    "evidence",
    "no soak/sustained-load stability claimed",
    "no model inference correctness or utility claimed",
    "no production V340L support or route claimed",
    "correctable-AER disappearance alone is not proof the V340L fault "
    "is solved",
    "no claim that the remediated arrangement is the only clean one",
    "advertisement is never conflated with validated execution",
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
    return (len(parts) >= 3 and parts[0] == "v2g"
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
        raise ReceiptError(f"not a V2-G receipt: {path}")
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
# issue232_freeze (same corrected semantics as the accepted #230 /1).
# ---------------------------------------------------------------------------

def closure_document(repo: Path | None = None) -> dict[str, Any]:
    from issue232_freeze import closure_document as _closure
    return _closure(Path(repo) if repo is not None else ROOT)


def verify_closure(repo: Path | None = None,
                   committed: dict[str, Any] | None = None) -> dict[str, Any]:
    from issue232_freeze import verify_closure as _verify, FreezeError
    try:
        return _verify(Path(repo) if repo is not None else ROOT, committed)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc


def write_closure(repo: Path | None = None) -> Path:
    from issue232_freeze import write_closure as _write, FreezeError
    try:
        return _write(Path(repo) if repo is not None else ROOT)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc
