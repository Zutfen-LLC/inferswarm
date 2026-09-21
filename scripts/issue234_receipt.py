#!/usr/bin/env python3
"""Issue #234 — R8-H raw-receipt protocol, corrected campaign (schema /2).

CORRECTED CAMPAIGN (maintainer amendment 2026-09-20): matched
backend/device parity, three arms on the exact same Qwen subject and
matched minimal placement:

  Arm A — one frozen RTX 3060 12 GB / CUDA-only build / local;
  Arm B — the EXACT SAME physical RTX 3060 / Vulkan-only build / local;
  Arm C — one independently addressed V340L Vega10 die / the same
          Vulkan-only binary bytes as Arm B / local.

No RPC. No mixed simultaneous AMD/NVIDIA model execution. No cross-die
V340L memory. No llama.cpp revision change. No alternate quantization.
The historical R8-D output is an EXTERNAL ANCHOR ONLY and never the
sole Vulkan PASS/FAIL oracle (control 31).

The original single-arm campaign (df0cf43) and its terminal
R8H_QWEN38_VULKAN_CORRECTNESS_FAIL are RETIRED; its physical bytes are
preserved under evidence/superseded-20260920-original-comparator/.

Producer-closure doctrine (corrected):
  * closure pins an exact committed producer SHA (the "producer pin");
  * source hashes are calculated from GIT BLOBS AT THAT PIN;
  * the pin must be an ANCESTOR of the final PR HEAD;
  * PHYSICAL producers must be byte-identical from pin to final HEAD
    (docs/evidence/tests/reduction-only commits may follow freely, and
    any amendment re-pins through a new closure);
  * verification recomputes blob identity at HEAD, worktree
    cleanliness, and deployed-hash equality, and fails closed on any
    physical-producer modification after execution — including when a
    reduction-only amendment tries to conceal it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_ID = "issue234-r8h-matched-backend-device-parity"
AREA_REL = "docs/investigations/qwen38-flash-next-r8-h-vulkan"
NS = "qwen38-flash-next-r8-h-vulkan"
SUPERSEDED_REL = f"{AREA_REL}/evidence/superseded-20260920-original-comparator"

RECEIPT_SCHEMA = "inferswarm.r8h.receipt/2"
CLOSURE_NAME = "PRODUCER-CLOSURE.json"
FREEZE_REL = f"{AREA_REL}/evidence/freeze/campaign-freeze.json"

# ---- producer classification (corrected closure doctrine) --------------
# PHYSICAL_PRODUCERS: execution receipt/helpers materially affecting
# physical evidence. Must be byte-identical from producer pin to final
# PR HEAD and must hash-match the bytes deployed on execution hosts.
PHYSICAL_PRODUCERS: tuple[str, ...] = (
    "scripts/issue234_host.py",
    "scripts/issue234_runtime.py",
    "scripts/issue234_placement.py",
    "scripts/issue234_ladder.py",
    "scripts/issue234_health.py",
)
# REDUCTION/AUTHORITY PRODUCERS: may be amended after the pin by
# reduction-only commits, but never to conceal physical-producer drift;
# any amendment re-pins through a new closure commit.
REDUCTION_PRODUCERS: tuple[str, ...] = (
    "scripts/issue234_receipt.py",
    "scripts/issue234_freeze.py",
    "scripts/issue234_authority.py",
    "scripts/issue234_reduce.py",
    "scripts/issue234_assemble.py",
    "scripts/issue234_manifest.py",
    # Round-2 closure pin: the characterization assembler is
    # terminal-bearing reduction authority (its output feeds the
    # control-33 gate) and must be closure-bound like every other
    # reduction producer.
    "scripts/issue234_characterize.py",
)
CLOSURE_SOURCES: tuple[str, ...] = PHYSICAL_PRODUCERS + REDUCTION_PRODUCERS

#: Observation-only score-characterization producer identity (R8-E
#: hook, Issue #199 methodology, same llama.cpp pin). The hook is INERT
#: unless LLAMA_OBSERVE_LOGITS is set; it reads the logits row the
#: sampler just consumed and writes no llama/ggml state. Round-2
#: closure-pinned: the reducer validates the prospective observation
#: pin document against these constants before accepting any
#: characterization derived from observation bytes.
OBSERVATION_HOOK_DIFF_SHA256 = (
    "058674419daa1189b25b80e99278001e437827a97c9a2d68ed7e24f03df0d659")
OBSERVATION_HOOK_ADDED_LINES = 85
OBSERVATION_FOCUS_ENV = "328,561,271,34227,12188,248068"
OBSERVATION_BINARIES: dict[str, dict[str, str]] = {
    "A": {"host": "inferswarm01", "backend": "cuda",
          "sha256": "2242e96363c651184c1565969abe4eaf619c1c534e965fdb053db4119f16be2f"},
    "B": {"host": "inferswarm01", "backend": "vulkan",
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0"},
    "C": {"host": "inferswarm02", "backend": "vulkan",
          # byte-identical to B (01-built, deployed to 02)
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0"},
}
#: case-256 fixture prompt identity (equals the accepted R8-E capture
#: binding prompt_sha256 for the same fixture row).
PROMPT_CASE256_SHA256 = (
    "647c266d9e9b7769679d875a1d06fb7c47cf6f4b3acd9fb5d0364f2baa7a94b5")

# -----------------------------------------------------------------------
# Frozen campaign authorities (issue #234 binding — consumed, never
# reopened here).
# -----------------------------------------------------------------------
R8A_MERGE = "938af774878f562314e920007846f9f2bb611ec2"      # #189/PR #190
R8D_MERGE = "f142a0d9"                                       # #195/PR #197
R8E_CAMPAIGN_NS = "qwen38-flash-next-r8-e"                   # #199 observation methodology
R8F_MERGE = "affa26cc"                                       # #200/PR #206
R8G_MERGE = "267b983de1249cad9c516e5c5c3cf86ed4a5a252"       # #207/PR #208
START_MAIN = "8862adaaa78cfa6a091b10af461d7b6021e359f9"      # V2-G merge, issue-mandated start
SUPERSEDED_HEAD = "df0cf4348e993628344919424a0515c6b485c3b7"  # original comparator campaign

V2E_MERGE = "78a91de435ffc9e1678574a754bbdd49d67dbd7a"       # #228/PR #229
V2F_MERGE = "c21840e4a1e5b5c81c366dd23b18ff582f9670b1"       # #230/PR #231
V2G_MERGE = "8862adaaa78cfa6a091b10af461d7b6021e359f9"       # #232/PR #233

OFFICIAL_QWEN_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
UNSLOTH_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
REPRESENTATION = "UD-IQ1_S"
TOTAL_MODEL_BYTES = 72_546_461_344

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
        "bytes": 22_544_696_352,
        "sha256": "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
    },
)

LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"   # v0.4.1

#: Canonical true-greedy request contract (accepted R8-D; controls
#: 19/20). Legacy samplers=["greedy"] and top_k != 1 can never be
#: labeled true greedy.
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

R8D_FIXTURE_SHA256 = "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"
R8D_FIXTURE_REL = "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"
R8D_FROZEN_REFERENCE_REL = "docs/investigations/qwen38-flash-next-r8-d/evidence/reference/frozen-reference.json"

#: Matched ladder (prospective freeze): case-256 first; a rung may be
#: executed only after every arm completed the previous rung and the
#: reducer adjudicated equality (control 35).
LADDER_CASES: tuple[str, ...] = ("case-256", "case-1024", "case-3072", "case-4096")
REPEATS_PER_CASE = 3
REQUIRED_REPEAT_IDS: tuple[int, ...] = (1, 2, 3)

#: Matched minimal placement geometry, frozen prospectively for ALL
#: THREE arms: --n-gpu-layers 1 (smallest nonzero offload; legality
#: re-proven per arm by issue234_placement.py load-only preflight
#: before any tokens are emitted).
MATCHED_NGL = 1
CONTEXT_SETTINGS: dict[str, Any] = {
    "ctx-size": 8192,
    "batch-size": 512,   # CLI flag at pin b29c606e is --batch-size
}

#: Excluded-device noise bounds. Vulkan instance creation initializes
#: drivers on sibling devices; model-tensor residency at IQ1_S is
#: MiB-scale at minimum (measured ~1.0-1.2 GB at ngl=1). nvidia-smi
#: reports whole MiB, so a 1 MiB delta is counter granularity, not
#: residency. Mechanical rule: an excluded device is "active" only at
#: model scale — >= 8 MiB (one-ninth of the smallest observed arm
#: residency, still two orders below any partial-layer footprint).
#:   * Arm C excluded V340L die: < 8 MiB vram delta;
#:   * Arm A/B sibling 3060: < 8 MiB memory-used delta AND no compute
#:     process bound to it (control 36: unmatched residency geometry
#:     may not be presented as a matched comparison).
EXCLUDED_DEVICE_MAX_BYTES = 8 * 1024 * 1024

ARMS: dict[str, dict[str, str]] = {
    "A": {"backend": "cuda", "host": "inferswarm01",
          "description": "frozen RTX 3060 / CUDA-only build"},
    "B": {"backend": "vulkan", "host": "inferswarm01",
          "description": "the SAME physical RTX 3060 / Vulkan-only build"},
    "C": {"backend": "vulkan", "host": "inferswarm02",
          "description": "one V340L Vega10 die / same Vulkan binary bytes"},
}

# -----------------------------------------------------------------------
# Receipt primitives.
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
    if receipt.get("campaign") != CAMPAIGN_ID:
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


# -----------------------------------------------------------------------
# Campaign freeze record (identity authority for the matched arms;
# written from the fresh census BEFORE canonical output and committed
# with the producer closure).
# -----------------------------------------------------------------------

class FreezeError(RuntimeError):
    pass


def load_freeze(repo: Path | None = None) -> dict[str, Any]:
    repo = (repo or ROOT).resolve()
    path = repo / FREEZE_REL
    if not path.is_file():
        raise FreezeError(f"campaign freeze record missing: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("campaign") != CAMPAIGN_ID:
        raise FreezeError("freeze campaign mismatch")
    if doc.get("schema") != "inferswarm.r8h.freeze/2":
        raise FreezeError(f"freeze schema mismatch: {doc.get('schema')!r}")
    return doc


def verify_freeze_binding(doc: dict[str, Any]) -> None:
    """Structural checks that do not depend on host state."""
    if doc.get("llama_cpp_pin") != LLAMA_CPP_PIN:
        raise FreezeError("freeze runtime pin drift")
    if doc.get("request_contract") != REQUEST_CONTRACT:
        raise FreezeError("freeze request contract drift")
    if doc.get("fixture_sha256") != R8D_FIXTURE_SHA256:
        raise FreezeError("freeze fixture identity drift")
    if doc.get("ngl") != MATCHED_NGL:
        raise FreezeError("freeze ngl drift")
    if doc.get("context") != CONTEXT_SETTINGS:
        raise FreezeError("freeze context/batch drift")
    members = doc.get("model_members", [])
    if len(members) != len(MODEL_MEMBERS):
        raise FreezeError("freeze model member set drift")
    for want, got in zip(MODEL_MEMBERS, members):
        if (got.get("member") != want["member"]
                or got.get("sha256") != want["sha256"]
                or got.get("bytes") != want["bytes"]):
            raise FreezeError(f"freeze model member drift: {want['member']}")
    g3060 = doc.get("rtx3060", {})
    for key in ("host", "uuid", "bdf", "cuda_identity", "vulkan_identity"):
        if not g3060.get(key):
            raise FreezeError(f"freeze rtx3060 missing {key}")
    a, b = doc.get("arms", {}).get("A", {}), doc.get("arms", {}).get("B", {})
    if not a or not b:
        raise FreezeError("freeze missing arm A/B definitions")
    if a.get("gpu", {}) != b.get("gpu", {}):
        raise FreezeError("freeze arms A/B do not pin the identical GPU")
    for arm in ("A", "B", "C"):
        d = doc.get("arms", {}).get(arm)
        if not d or d.get("ngl") != MATCHED_NGL \
                or d.get("context") != CONTEXT_SETTINGS \
                or d.get("request") != REQUEST_CONTRACT \
                or d.get("fixture_sha256") != R8D_FIXTURE_SHA256:
            raise FreezeError(f"freeze arm {arm} geometry mismatch")
        if d.get("model_sha256") != [m["sha256"] for m in MODEL_MEMBERS]:
            raise FreezeError(f"freeze arm {arm} model bytes mismatch")
    c = doc["arms"]["C"]
    if not c.get("gpu", {}).get("bdf") or not c.get("gpu", {}).get("deviceUUID"):
        raise FreezeError("freeze arm C die identity incomplete")
    if not c.get("excluded_die", {}).get("bdf"):
        raise FreezeError("freeze arm C excluded-die identity incomplete")


# -----------------------------------------------------------------------
# Producer closure (corrected doctrine).
# -----------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr[-500:]}")
    return proc.stdout


def blob_sha(repo: Path, revision: str, rel: str) -> str:
    """Blob hash of `rel` at `revision` (git hash-object semantics)."""
    out = _git(repo, "rev-parse", f"{revision}:{rel}")
    return out.strip()


def blob_bytes(repo: Path, revision: str, rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{revision}:{rel}"],
        capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cat-file failed for {revision}:{rel}")
    return proc.stdout


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor",
         ancestor, descendant],
        capture_output=True, text=True)
    return proc.returncode == 0


def closure_document(repo: Path | None = None,
                     producer_head: str | None = None) -> dict[str, Any]:
    """Closure over GIT BLOBS at the producer pin.

    Source hashes are calculated from the blobs AT THE PIN (never from
    mutable worktree bytes). If `producer_head` is omitted, HEAD is
    pinned — used when creating the closure at the producer commit.
    """
    repo = (repo or ROOT).resolve()
    head = producer_head or _git(repo, "rev-parse", "HEAD").strip()
    sources: dict[str, dict[str, Any]] = {}
    for rel in CLOSURE_SOURCES:
        try:
            blob = blob_sha(repo, head, rel)
            raw = blob_bytes(repo, head, rel)
        except RuntimeError:
            raise FileNotFoundError(f"closure source missing at {head}: {rel}")
        sources[rel] = {
            "git_blob": blob,
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
            "class": ("physical" if rel in PHYSICAL_PRODUCERS
                      else "reduction"),
        }
    n_phys = sum(1 for v in sources.values() if v["class"] == "physical")
    n_red = sum(1 for v in sources.values() if v["class"] == "reduction")
    if n_phys != len(PHYSICAL_PRODUCERS) or n_red != len(REDUCTION_PRODUCERS):
        raise ClosureError("closure classification count mismatch")
    doc = {
        "schema": "inferswarm.r8h.producer-closure/2",
        "campaign": CAMPAIGN_ID,
        "producer_head": head,
        "sources": sources,
    }
    doc["closure_digest"] = "PENDING"
    doc["closure_digest"] = sha256_bytes(canonical(doc))
    return doc


class ClosureError(RuntimeError):
    pass


def verify_closure(repo: Path | None = None) -> dict[str, Any]:
    """Fail closed unless the corrected closure contract holds at HEAD.

    1. the committed closure pins an exact producer SHA;
    2. the pin is an ANCESTOR of current HEAD;
    3. every closure source is BYTE-IDENTICAL from pin to HEAD (blob
       equality) — physical AND reduction sources alike (a drifted
       reduction producer must re-pin through a new closure, never
       silently continue);
    4. worktree bytes of every closure source match the pin blob (no
       dirty or substituted producer);
    5. deployed physical-producer hashes (evidence tree) match the
       pin's blobs — checked by the assembler against runtime receipts.
    """
    repo = (repo or ROOT).resolve()
    path = repo / AREA_REL / CLOSURE_NAME
    if not path.is_file():
        raise ClosureError(f"closure missing: {path}")
    committed = json.loads(path.read_text(encoding="utf-8"))
    if committed.get("schema") != "inferswarm.r8h.producer-closure/2":
        raise ClosureError(
            f"closure schema {committed.get('schema')!r} is not the "
            "corrected /2 doctrine")
    pin = committed.get("producer_head")
    if not pin:
        raise ClosureError("closure pins no producer head")
    head = _git(repo, "rev-parse", "HEAD").strip()
    if not is_ancestor(repo, pin, head):
        raise ClosureError(
            f"producer pin {pin} is NOT an ancestor of HEAD {head}")
    problems = []
    for rel, meta in committed.get("sources", {}).items():
        pin_blob = meta.get("git_blob")
        head_blob = blob_sha(repo, head, rel)
        if pin_blob is None or head_blob != pin_blob:
            problems.append(f"blob drift pin->HEAD: {rel}")
            continue
        wt = repo / rel
        if not wt.is_file():
            problems.append(f"missing from worktree: {rel}")
            continue
        if digest_file(wt) != meta.get("sha256"):
            problems.append(f"worktree bytes != pin blob: {rel}")
    if problems:
        raise ClosureError(
            "producer closure violated: " + "; ".join(problems))
    return committed


def write_closure(repo: Path | None = None) -> Path:
    repo = (repo or ROOT).resolve()
    out = repo / AREA_REL / CLOSURE_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = closure_document(repo)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    return out
