#!/usr/bin/env python3
"""Issue #216 — V2-D raw-receipt protocol: campaign identity + envelope.

Every correctness-bearing V2-D observation is a PRIMARY RAW RECEIPT whose
payload is derived from retained command bytes (stdout/stderr/exit-code/
sysfs/journal), never from authored summaries. This module is the single
source of campaign identity, receipt envelope schema, and the committed
producer-source closure used by every producer and by the assembler.

Design corrections over the rejected PR #218 architecture (audit record in
docs/investigations/vulkan-v2-d-v340l-concurrent/AUDIT-REJECTIONS.md):

1. Receipts bind RAW SOURCE BYTES: every observation carries, for each
   retained raw stream, {rel_path, sha256, byte_count} and the receipt
   digest covers those bytes. The assembler re-derives every verdict by
   re-reading the raw bytes through the accepted parsers; the receipt's
   own derived fields are cross-checks that must agree, never authority.
2. Intended identity (from accepted V2-B/V2-C authority bytes) and the
   fresh execution-time mapping are SEPARATE artifacts; concurrency
   receipts bind BOTH, and the assembler rejects any pair where the
   fresh mapping does not corroborate the intended identity.
3. The producer-source closure is a committed file; every producer
   refuses to emit when any closure source has drifted from the
   committed sha256 (checked against the Git worktree bytes).
4. Overlap authority is the accepted #219 seam (imported reducer
   machinery), never process/wrapper lifetime.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys_path_setup = None

CAMPAIGN_ID = "issue216-v2d-v340l-concurrent-dual-die-v2"
AREA_REL = "docs/investigations/vulkan-v2-d-v340l-concurrent"
NS = "vulkan-v2-d-v340l-concurrent"

RECEIPT_SCHEMA = "inferswarm.v2d.receipt/2"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"

# Every producer module whose bytes are part of the correctness-bearing
# closure. The closure file itself is excluded (it is the binding, not a
# bound source). The assembler verifies the closure against the committed
# closure record BEFORE reducing any phase, and each producer verifies it
# before emitting.
CLOSURE_SOURCES = (
    "scripts/issue216_receipt.py",
    "scripts/issue216_freeze.py",
    "scripts/issue216_physical_authority.py",
    "scripts/issue216_host.py",
    "scripts/issue216_execution.py",
    "scripts/issue216_preflight.py",
    "scripts/issue216_concurrent.py",
    "scripts/issue216_transport.py",
    "scripts/issue216_soak.py",
    "scripts/issue216_fault.py",
    "scripts/issue216_reset.py",
    "scripts/issue216_assemble.py",
    "scripts/issue216_manifest.py",
)

# Frozen runtime identities (byte-identical to the accepted V2-B/V2-C
# authority runtime block; the authority builder verifies equality).
FROZEN_RUNTIME = {
    "executable": "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli",
    "executable_sha256": "5a8f5edec3cafce77e371b082f4dd52f07d38a72704a652063f6255a018c36ec",
    "model": "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    "model_sha256": "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94",
    # model_bytes was stale (2001162224). The accepted V2-B/V2-C frozen
    # runtime authority — and the physical model file on inferswarm02 —
    # carry 1929903264; the authority builder verifies equality against
    # the accepted predecessor bytes, so this field must describe the
    # SAME predecessor-frozen model (verified 2026-09-18 against
    # PHYSICAL-AUTHORITY.json runtime.model_bytes and the on-host file
    # size). Predecessor authority bytes are unchanged.
    "model_bytes": 1929903264,
    "reference_path": "docs/investigations/vulkan-v1-a/reference-visible-output.txt",
    "reference_sha256": "9013db8fb38982f9085754e69fa3feb2f74c7372360da686fe90a3444f26182d",
    # V2-D concurrency authority instrument: the CORRECTED #219 seam build.
    "observe_runtime_executable": "/home/zutfen/is219-v2d0-src/build-v2d0-observe-v216/bin/llama-cli",
    "observe_runtime_instrumented_ggml_vulkan_sha256":
        "6469472015ade1f01075101af982076ff7ddbbcc0c8404017f8f3a6e4489bfc4",
    "observe_runtime_source_commit": "8ea290247c87ced2ab245b056ffe96dbcf90d36c",
    "observe_env_gate": "GGML_VK_OBSERVE_INTERVAL",
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
    """Bind a retained raw artifact by content: {rel_path, sha256, bytes}.

    rel_path is relative to the campaign evidence root so receipts stay
    valid when the evidence tree is committed at the repo root.
    """
    path = root / rel_path
    if not path.is_file():
        raise ReceiptError(f"raw artifact missing: {rel_path}")
    data = path.read_bytes()
    return {"rel_path": rel_path, "sha256": sha256_bytes(data),
            "byte_count": len(data)}


def receipt_id_ok(rid: str) -> bool:
    parts = rid.split("-")
    return len(parts) >= 3 and parts[0] == "v2d" and len(rid) <= 200


def emit_receipt(out_dir: Path, receipt: dict[str, Any]) -> Path:
    """Write one primary raw receipt; refuse duplicates and bad ids.

    The receipt MUST carry: schema, campaign_id, receipt_id, phase,
    attempt_id, utc, raw_bindings (list of bind_raw rows), and payload
    (the derived observation, cross-checked later by the assembler).
    The receipt digest covers canonical(receipt minus digest field).
    """
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
    receipt = json.loads(path.read_text(encoding="text/plain",
                                        errors="strict"))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError(f"not a V2-D receipt: {path}")
    return receipt


# ---------------------------------------------------------------------------
# Producer-source closure (pre-execution freeze).
#
# CORRECTED (schema /3): the closure now proves EXECUTED-BYTE identity.
# The old /2 closure hashed `git show :<path>` (the Git index) while
# Python executed working-tree bytes, so unstaged producer drift was
# invisible. All closure logic lives in issue216_freeze (fail-closed:
# worktree == index == HEAD for every source; pinned producer head;
# no missing/untracked/substituted sources). This module re-exports the
# freeze API so existing `rc.verify_closure` / `rc.closure_document`
# callers get the corrected semantics.
# ---------------------------------------------------------------------------

def closure_document(repo: Path = ROOT) -> dict[str, Any]:
    """Corrected closure: worktree==index==HEAD per source, pinned head."""
    from issue216_freeze import closure_document as _closure
    return _closure(repo)


def verify_closure(repo: Path = ROOT,
                   committed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify the committed closure record against the live frozen tree.

    Returns the verified closure; raises ReceiptError on any drift
    (staged, unstaged, missing/substituted source, moved HEAD, or a
    retired schema /2 record).
    """
    from issue216_freeze import verify_closure as _verify, FreezeError
    try:
        return _verify(repo, committed)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc


def write_closure(repo: Path = ROOT) -> Path:
    from issue216_freeze import write_closure as _write, FreezeError
    try:
        return _write(repo)
    except FreezeError as exc:
        raise ReceiptError(str(exc)) from exc
