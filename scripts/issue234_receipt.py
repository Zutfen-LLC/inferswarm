#!/usr/bin/env python3
"""Issue #234 — R8-H raw-receipt protocol: campaign identity + envelope.

Qualify ONE independently addressed Radeon Pro V340L Vega10 die as a
truthful local Vulkan execution resource for the exact accepted
Qwen3.8-Flash-Next UD-IQ1_S subject under the pinned llama.cpp runtime
(b29c606e), before authorizing any Vulkan RPC, mixed AMD/NVIDIA,
multi-die, or ordinary InferSwarm serving experiment.

A prerequisite/fail terminal is a valid result. No runtime upgrade, no
representation change, no cross-die execution, no mixed-vendor
execution, no Vulkan RPC, no planner policy, no ordinary serving.

Every correctness-bearing R8-H observation is a PRIMARY RAW RECEIPT
whose payload derives from retained command bytes (stdout/stderr/exit
code/sysfs/journal/HTTP bodies), never from authored summaries.

Separate state dimensions (never conflated, in every artifact):
  RUNTIME_AUTHORITY    — pinned llama.cpp source/build/binary identity;
  SUBJECT_IDENTITY     — exact accepted UD-IQ1_S member bytes + fresh
                         census of the selected V340L die;
  PLACEMENT            — prospectively frozen nonzero single-die Vulkan
                         offload geometry (output-blind selection rule);
  EXECUTION_TRUTH      — proof of actual Vulkan die execution vs
                         silent CPU fallback (residency + backend
                         activity + process association);
  CORRECTNESS          — exact token/stop equality against the frozen
                         accepted R8-D true-greedy reference ladder;
  PLATFORM_HEALTH      — amdgpu/AER/PCIe/device-loss deltas around
                         model execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_ID = "issue234-r8h-vulkan-single-die-qualification"
AREA_REL = "docs/investigations/qwen38-flash-next-r8-h-vulkan"
NS = "qwen38-flash-next-r8-h-vulkan"

RECEIPT_SCHEMA = "inferswarm.r8h.receipt/1"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"

# Every producer module whose bytes are part of the correctness-bearing
# closure (the closure file itself is excluded — binding, not a bound
# source).
CLOSURE_SOURCES = (
    "scripts/issue234_receipt.py",
    "scripts/issue234_freeze.py",
    "scripts/issue234_authority.py",
    "scripts/issue234_host.py",
    "scripts/issue234_runtime.py",
    "scripts/issue234_placement.py",
    "scripts/issue234_ladder.py",
    "scripts/issue234_health.py",
    "scripts/issue234_reduce.py",
    "scripts/issue234_assemble.py",
    "scripts/issue234_manifest.py",
)

# -----------------------------------------------------------------------
# Frozen campaign authorities (issue #234 "Accepted predecessor
# authority" — consumed, never re-derived and never reopened here).
# -----------------------------------------------------------------------

#: Accepted R8 model/runtime authority (issue #234 binding).
R8A_MERGE = "938af774878f562314e920007846f9f2bb611ec2"      # #189/PR #190
R8D_MERGE = "f142a0d9"                                       # #195/PR #197 (short pin per issue; full sha asserted via evidence bytes)
R8F_MERGE = "affa26cc"                                       # #200/PR #206
R8G_MERGE = "267b983de1249cad9c516e5c5c3cf86ed4a5a252"       # #207/PR #208
START_MAIN = "8862adaaa78cfa6a091b10af461d7b6021e359f9"      # V2-G merge, issue-mandated start

#: V2-series hardware authority merges.
V2E_MERGE = "78a91de435ffc9e1678574a754bbdd49d67dbd7a"       # #228/PR #229
V2F_MERGE = "c21840e4a1e5b5c81c366dd23b18ff582f9670b1"       # #230/PR #231
V2G_MERGE = "8862adaaa78cfa6a091b10af461d7b6021e359f9"       # #232/PR #233

OFFICIAL_QWEN_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
UNSLOTH_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
REPRESENTATION = "UD-IQ1_S"
TOTAL_MODEL_BYTES = 72_546_461_344

#: Exact accepted UD-IQ1_S split-set member identity (R8-B
#: split-verification bytes, re-verified fresh at R8-H freeze).
MODEL_MEMBERS: tuple[dict[str, Any], ...] = (
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
        "bytes": 10_946_624,
        "sha256": "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
        "bytes": 49_990_818_368,
        "sha256": "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf",
        "sha256": "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
        "bytes": 22_544_696_352,
    },
)

LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"   # v0.4.1

#: Canonical true-greedy request contract (accepted R8-D; controls
#: 19/20/21 — legacy samplers=["greedy"] and top_k != 1 can never be
#: labeled true greedy).
REQUEST_CONTRACT: dict[str, Any] = {
    "samplers": ["top_k"],
    "top_k": 1,
    "temperature": 0.0,
    "seed": 0,
    "cache_prompt": False,
    "stream": False,
    "return_tokens": True,
    "n_predict": 8,
}

#: Accepted R8-D fixture ladder identity (frozen reference authority —
#: controls 17/18: never regenerated after candidate output; exact
#: retained prompt/token identities only).
R8D_FIXTURE_SHA256 = "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"
R8D_FIXTURE_REL = "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"
R8D_FROZEN_REFERENCE_REL = "docs/investigations/qwen38-flash-next-r8-d/evidence/reference/frozen-reference.json"

#: Bounded candidate ladder, prospectively frozen from the accepted
#: fixture set (issue Phase 3): case-256 -> case-1024 -> case-3072 ->
#: case-4096, escalating only on exact-token/exact-stop PASS + clean
#: platform health.
LADDER_CASES: tuple[str, ...] = ("case-256", "case-1024", "case-3072", "case-4096")
REPEATS_PER_CASE = 3

#: Prospectively frozen single-die placement selection rule
#: (output-blind; issue Phase 2 "smallest nonzero --n-gpu-layers value
#: that produces measured >0 model-buffer residency on the selected
#: die", established by load-only preflight with NO correctness output,
#: every attempted geometry retained).
PLACEMENT_RULE = "smallest-ngl-nonzero-residency"
NGL_CANDIDATE_LADDER: tuple[int, ...] = (1, 2, 4, 8, 16, 24, 32, 40, 48, 49)
CONTEXT_SETTINGS: dict[str, Any] = {
    "ctx-size": 8192,
    "batch": 512,
}

#: V340L single-die capacity contract: one die == one 8-GiB Memory
#: Resource (control 10: aggregate 16-GiB capacity may never be treated
#: as one resource). Prospectively frozen safety headroom: model
#: buffers on the die must leave >= 512 MiB below the die's reported
#: heap budget for runtime/KV/workspace allocations.
DIE_HEAP_BYTES = 8 * 1024**3
SAFETY_HEADROOM_BYTES = 512 * 1024**2

# -----------------------------------------------------------------------
# Receipt primitives (same envelope discipline as accepted #230/#232).
# -----------------------------------------------------------------------

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def emit_receipt(out_dir: Path, receipt: dict[str, Any]) -> Path:
    """Write one raw receipt with its self-digest envelope."""
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"receipt schema mismatch: {receipt.get('schema')!r}")
    if not receipt.get("campaign") == CAMPAIGN_ID:
        raise ValueError(f"receipt campaign mismatch: {receipt.get('campaign')!r}")
    name = receipt.get("name")
    if not isinstance(name, str) or not name or "/" in name:
        raise ValueError(f"bad receipt name: {name!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    body = dict(receipt)
    body["digest"] = "PENDING"
    body["digest"] = sha256_bytes(canonical(body))
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_receipt(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"{path}: schema mismatch")
    digest = doc.get("digest")
    body = dict(doc)
    body["digest"] = "PENDING"
    if sha256_bytes(canonical(body)) != digest:
        raise ValueError(f"{path}: receipt digest mismatch")
    return doc


def closure_document(repo: Path | None = None) -> dict[str, Any]:
    """Producer closure: exact bytes being executed for every source."""
    repo = (repo or ROOT).resolve()
    sources = {}
    for rel in CLOSURE_SOURCES:
        path = repo / rel
        if not path.is_file():
            raise FileNotFoundError(f"closure source missing: {rel}")
        sources[rel] = {
            "sha256": digest_file(path),
            "bytes": path.stat().st_size,
        }
    import subprocess
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True
                          ).stdout.strip()
    doc = {
        "schema": "inferswarm.r8h.producer-closure/1",
        "campaign": CAMPAIGN_ID,
        "producer_head": head,
        "sources": sources,
    }
    doc["closure_digest"] = "PENDING"
    doc["closure_digest"] = sha256_bytes(canonical(doc))
    return doc


def verify_closure(repo: Path | None = None,
                   expected_head: str | None = None) -> dict[str, Any]:
    """Fail closed unless every closure source byte-matches the worktree."""
    repo = (repo or ROOT).resolve()
    path = repo / AREA_REL / CLOSURE_NAME
    if not path.is_file():
        raise FileNotFoundError(f"closure missing: {path}")
    committed = json.loads(path.read_text(encoding="utf-8"))
    live = closure_document(repo)
    if committed.get("closure_digest") != live["closure_digest"]:
        # Distinguish producer drift from a damaged closure file.
        drift = [rel for rel in CLOSURE_SOURCES
                 if committed["sources"][rel]["sha256"] !=
                 live["sources"][rel]["sha256"]]
        raise RuntimeError(
            f"producer closure mismatch (drifted sources: {drift})")
    if expected_head is not None and committed["producer_head"] != expected_head:
        raise RuntimeError(
            f"closure head {committed['producer_head']} != expected {expected_head}")
    return committed


def write_closure(repo: Path | None = None) -> Path:
    repo = (repo or ROOT).resolve()
    out = repo / AREA_REL / CLOSURE_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = closure_document(repo)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    return out
