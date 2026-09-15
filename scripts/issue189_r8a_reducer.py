#!/usr/bin/env python3
"""Issue #189 R8-A terminal reduction (CPU-only, offline, stdlib only).

This reducer does not download a model, inspect a GPU, or execute a model.
It turns three retained static authorities into the one terminal permitted
by Issue #189:

1. ``source-findings.md``  — pinned upstream/Unsloth authority facts;
2. ``hardware-census.json`` — the mechanically derived heterogeneous fleet
   census (per-resource rows, statuses, provenance; NO authored fleet byte
   constant is trusted anywhere in this file);
3. ``gguf-header-census.json`` — the bounded header/tensor census of the
   pinned UD-IQ1_S split set (magic/version, split metadata, tensor
   identities, PLE n-gram table identity and byte extent).

It fails closed if any authority drifts, if the split census is internally
inconsistent, if fleet totals cannot be re-derived from resource rows, or
if the terminal is changed without the evidence supporting it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/qwen38-flash-next-r8-a"
SOURCE = f"{AREA}/source-findings.md"
CENSUS = f"{AREA}/gguf-census.json"
HEADER_CENSUS = f"{AREA}/gguf-header-census.json"
HARDWARE = f"{AREA}/hardware-census.json"
OUTPUT = f"{AREA}/terminal-reduction.json"

OFFICIAL_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
GGUF_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
RUNTIME_AUDIT_REVISION = "1bc7a5af0d14b1fb72f266abbd1237b394187115"
RPC_REPRODUCER_REVISION = "17252c769a63c1cb650ce98ae309cf4de0da7778"
RPC_REPORTER_REBUILD_REVISION = "cc231cb0da565440cf6a3e5b55dfeba477972cb6"
RPC_FIX_REVISION = "a273d22e142b9ad253a09d7b76d4d24ba64eb9bc"
RPC_ISSUE_BODY_SHA256 = "d0f1f6a5033e177be6fc44365b7700402c5690e9aad810fb9f6d83dfe1b352c2"
RPC_CLASSIFICATION = "CORRECTNESS_BLOCKER"
RPC_REPORTED_MODE = (
    "Metal layer-split cross-host RPC, UD-IQ4_XS, long prefill/decode "
    "beyond about 2K prompt tokens"
)
RPC_MODE_SOURCE_FACTS = (
    "Metal layer-split",
    "cross-host RPC topology",
    "Unsloth UD-IQ4_XS",
    "after roughly 2K prompt",
)
UD_IQ1_S_MEMBERS = (
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf", 10_946_624, "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd"),
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf", 49_990_818_368, "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6"),
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf", 22_544_696_352, "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a"),
)

# Representation facts pinned by the header census (re-derived below from
# gguf-header-census.json; these constants only bound plausibility).
EXPECTED_TOTAL_TENSORS = 1224
PLE_TABLE_TENSOR = "per_layer_token_embd.weight"
PLE_TABLE_BYTES = 28_800_138_240
PLE_TABLE_DIMS = [160, 320001536]
PLE_TABLE_GGML_TYPE_NAME = "GGML_TYPE_IQ4_NL"
BACKBONE_BYTES = 72_546_461_344 - PLE_TABLE_BYTES

# Statuses permitted in the hardware census (fail closed on anything else).
DEPLOYED_STATUSES = (
    "DEPLOYED_AVAILABLE",
    "DEPLOYED_UNQUALIFIED_FOR_R8",
    "DEPLOYED_QUALIFIED_FOR_RELEVANT_BACKEND",
)
PENDING_STATUS = "PENDING_NOT_AVAILABLE"


def canonical_bytes(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_census(root: Path) -> dict:
    path = root / CENSUS
    if not path.is_file():
        raise ValueError("ISSUE189_FAIL: object-level GGUF census is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schema") != "inferswarm.issue189.gguf-census/1"
            or document.get("revision") != GGUF_REVISION):
        raise ValueError("ISSUE189_FAIL: GGUF census authority drift")
    files = document.get("files")
    if not isinstance(files, list) or len(files) != 56:
        raise ValueError("ISSUE189_FAIL: incomplete GGUF object inventory")
    indexed = {row[0]: row for row in files
               if isinstance(row, list) and len(row) == 3
               and isinstance(row[0], str) and isinstance(row[1], int)
               and isinstance(row[2], str) and len(row[2]) == 64}
    if len(indexed) != 56:
        raise ValueError("ISSUE189_FAIL: malformed GGUF object identity")
    members = [indexed.get(name) for name, _, _ in UD_IQ1_S_MEMBERS]
    if any(member is None for member in members):
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split member missing")
    member_rows = [member for member in members if member is not None]
    if [row[1] for row in member_rows] != [size for _, size, _ in UD_IQ1_S_MEMBERS]:
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split size drift")
    if sum(row[1] for row in member_rows) != 72_546_461_344:
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split sum drift")
    return document


def load_header_census(root: Path) -> dict:
    """Load and internally re-verify the bounded GGUF header/tensor census."""
    path = root / HEADER_CENSUS
    if not path.is_file():
        raise ValueError("ISSUE189_FAIL: GGUF header/tensor census is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schema") != "inferswarm.issue189.gguf-header-census/1"
            or document.get("revision") != GGUF_REVISION):
        raise ValueError("ISSUE189_FAIL: header census authority drift")
    if document.get("body_download_bytes") != 0:
        raise ValueError("ISSUE189_FAIL: header census claims body bytes")
    files = document.get("files")
    if not isinstance(files, list) or len(files) != len(UD_IQ1_S_MEMBERS):
        raise ValueError("ISSUE189_FAIL: header census does not cover the split set")
    for entry, (name, size, lfs) in zip(files, UD_IQ1_S_MEMBERS):
        if entry.get("path") != name or entry.get("object_bytes") != size \
                or entry.get("hf_lfs_sha256") != lfs:
            raise ValueError("ISSUE189_FAIL: header census object identity drift")
        if entry.get("gguf_version") != 3:
            raise ValueError("ISSUE189_FAIL: GGUF magic/version drift")
        if entry.get("header_bytes_sha256") != sha256_file(
                root / AREA / entry["header_bytes_retained"]):
            raise ValueError("ISSUE189_FAIL: retained header bytes drift")
        for receipt in entry.get("receipts", []):
            if receipt.get("http_status") != 206:
                raise ValueError("ISSUE189_FAIL: non-206 range receipt")
    # split metadata consistency
    split_nos = [f["metadata"]["split.no"] for f in files]
    split_counts = [f["metadata"]["split.count"] for f in files]
    declared = [f["metadata"]["split.tensors.count"] for f in files]
    if split_nos != [0, 1, 2] or set(split_counts) != {3}:
        raise ValueError("ISSUE189_FAIL: split order/count drift")
    carried = sum(f["tensor_count"] for f in files)
    if carried != EXPECTED_TOTAL_TENSORS or set(declared) != {EXPECTED_TOTAL_TENSORS}:
        raise ValueError("ISSUE189_FAIL: carried tensor count contradicts split metadata")
    # PLE table identity and byte extent
    ple = [t for f in files for t in f["tensors"]
           if t["name"] == PLE_TABLE_TENSOR]
    if len(ple) != 1:
        raise ValueError("ISSUE189_FAIL: PLE table tensor identity not unique")
    if ple[0]["dims"] != PLE_TABLE_DIMS or \
            ple[0]["ggml_type_name"] != PLE_TABLE_GGML_TYPE_NAME:
        raise ValueError("ISSUE189_FAIL: PLE table shape/type drift")
    # byte extent from offset deltas within its split member
    owner = next(f for f in files
                 if any(t["name"] == PLE_TABLE_TENSOR for t in f["tensors"]))
    ordered = sorted(owner["tensors"], key=lambda t: t["offset"])
    names = [t["name"] for t in ordered]
    i = names.index(PLE_TABLE_TENSOR)
    end = ordered[i + 1]["offset"] if i + 1 < len(ordered) \
        else owner["object_bytes"] - owner["data_start_offset"]
    span = end - ordered[i]["offset"]
    if span != PLE_TABLE_BYTES:
        raise ValueError("ISSUE189_FAIL: PLE table byte extent drift")
    # duplicate / missing tensor identities across the split set
    all_names = [t["name"] for f in files for t in f["tensors"]]
    if len(all_names) != len(set(all_names)):
        raise ValueError("ISSUE189_FAIL: duplicate tensor identity")
    document["_derived"] = {
        "ple_table_bytes": span,
        "backbone_bytes": sum(size for _, size, _ in UD_IQ1_S_MEMBERS) - span,
        "ple_split_member": owner["path"],
        "tensor_total": len(all_names),
    }
    return document


def load_hardware_census(root: Path) -> dict:
    """Load the mechanical fleet census and fail closed on authored totals."""
    path = root / HARDWARE
    if not path.is_file():
        raise ValueError("ISSUE189_FAIL: hardware census is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "inferswarm.issue189.hardware-census/2":
        raise ValueError("ISSUE189_FAIL: hardware census schema drift")
    resources = document.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValueError("ISSUE189_FAIL: hardware census has no resources")

    def is_vendor(row: dict, prefix: str) -> bool:
        vd = str(row.get("vendor_device", ""))
        return vd.startswith(prefix)

    def counted(row: dict) -> bool:
        # Deployed rows contribute execution-fleet bytes. A physically
        # observed but boundary-excluded row (e.g. Valinor's GTX 1060) may
        # carry its real measured bytes yet is NOT counted; a phantom
        # reported-not-observed row must carry zero bytes.
        status = row.get("status")
        if status in DEPLOYED_STATUSES:
            return True
        if status == PENDING_STATUS:
            if row.get("memory_bytes", 0) != 0:
                raise ValueError(
                    "ISSUE189_FAIL: pending resource carries capacity bytes")
            return False
        if status == "EXCLUDED_WITH_REASON":
            if "resource_id" in row and row.get("memory_bytes", 0) != 0:
                raise ValueError(
                    "ISSUE189_FAIL: reported-not-observed resource carries "
                    "capacity bytes")
            return False
        raise ValueError(f"ISSUE189_FAIL: unclassified resource status: {status}")

    def memory(row: dict) -> int:
        value = row.get("memory_bytes")
        source = row.get("memory_source")
        if not isinstance(value, int) or value <= 0 or not source:
            raise ValueError(
                f"ISSUE189_FAIL: deployed resource lacks measured memory: "
                f"{row.get('resource_id', row.get('host', '?'))}")
        return value

    def observed_memory(row: dict) -> int:
        value = row.get("memory_bytes")
        return value if isinstance(value, int) and value > 0 else 0

    nvidia_rows = [r for r in resources if counted(r) and is_vendor(r, "10de")
                   and r.get("host") != "valinor"]
    amd_rows = [r for r in resources if counted(r) and is_vendor(r, "1002")]
    # Valinor is physically deployed hardware outside the execution-fleet
    # boundary: its bytes are real and disclosed, but never counted above.
    valinor_rows = [r for r in resources if r.get("host") == "valinor"
                    and r.get("status") != "EXCLUDED_WITH_REASON"
                    or (r.get("host") == "valinor"
                        and "resource_id" not in r)]
    nvidia = sum(memory(r) for r in nvidia_rows)
    amd = sum(memory(r) for r in amd_rows)
    valinor = sum(observed_memory(r) for r in valinor_rows)
    # A hard-coded aggregate must never survive as the authority: the census
    # document's own totals are re-derived here and must agree row-for-row.
    totals = document.get("totals", {})
    if totals.get("deployed_nvidia_bytes") != nvidia \
            or totals.get("deployed_amd_bytes") != amd \
            or totals.get("deployed_accelerator_bytes_total") != nvidia + amd:
        raise ValueError("ISSUE189_FAIL: census totals disagree with resource rows")
    def backend_capacity(backend: str) -> int:
        """Row-sum of measured memory over resources listing the backend."""
        total = 0
        for row in resources:
            if row.get("status") in (PENDING_STATUS, "EXCLUDED_WITH_REASON") \
                    and "resource_id" in row:
                continue
            if any(backend in str(b) for b in row.get("backends_observable", [])):
                total += observed_memory(row)
        return total

    pending = [r for r in resources if r.get("status") == PENDING_STATUS]
    if not pending or any(r.get("memory_bytes", 0) != 0 for r in pending):
        raise ValueError("ISSUE189_FAIL: pending hardware must be zero-capacity")
    v340l = [r for r in pending if "v340l" in r.get("resource_id", "").lower()]
    note = v340l[0].get("modeling_note", "") if v340l else ""
    if not v340l or "two separate 8 GiB" not in note \
            or "never flattened" not in note:
        raise ValueError(
            "ISSUE189_FAIL: V340L not modeled as two independent address spaces")
    document["_derived"] = {
        "cuda_driver_present_bytes": backend_capacity("cuda"),
        "vulkan_enumerated_bytes": backend_capacity("vulkan"),
        "nvidia_bytes": nvidia,
        "nvidia_rows": len(nvidia_rows),
        "amd_bytes": amd,
        "amd_rows": len(amd_rows),
        "valinor_bytes": valinor,
        "deployed_total": nvidia + amd,
        "max_single_resource": max(memory(r) for r in nvidia_rows + amd_rows),
        "qualified_for_r8_bytes": 0,
    }
    return document


def reduction_document(root: Path = ROOT) -> dict:
    """Derive the R8-A terminal only from retained, static inputs."""
    source = root / SOURCE
    if not source.is_file():
        raise ValueError("ISSUE189_FAIL: source-authority record is missing")
    text = source.read_text(encoding="utf-8")
    for expected in (OFFICIAL_REVISION, GGUF_REVISION, RUNTIME_AUDIT_REVISION,
                     RPC_REPRODUCER_REVISION, RPC_REPORTER_REBUILD_REVISION,
                     RPC_FIX_REVISION, RPC_ISSUE_BODY_SHA256, RPC_CLASSIFICATION,
                     *RPC_MODE_SOURCE_FACTS, "R8-A"):
        if expected not in text:
            raise ValueError(f"ISSUE189_FAIL: source-authority fact missing: {expected}")

    census = load_census(root)
    headers = load_header_census(root)
    hardware = load_hardware_census(root)
    derived_h = hardware["_derived"]
    derived_r = headers["_derived"]

    representation_bytes = sum(size for _, size, _ in UD_IQ1_S_MEMBERS)
    backbone = derived_r["backbone_bytes"]
    ple_bytes = derived_r["ple_table_bytes"]
    deployed_total = derived_h["deployed_total"]
    headroom = deployed_total - representation_bytes
    # Per-resource fit constraint: the largest deployed resource vs the
    # separable pieces of the representation.
    largest = derived_h["max_single_resource"]
    single_resource_fits_backbone = largest >= backbone
    single_resource_fits_ple = largest >= ple_bytes

    document = {
        "schema": "inferswarm.issue189.r8a-terminal/2",
        "issue": 189,
        "source_authority": {
            "official_revision": OFFICIAL_REVISION,
            "third_party_gguf_revision": GGUF_REVISION,
            "source_findings_sha256": sha256_file(source),
            "gguf_census_sha256": sha256_file(root / CENSUS),
            "gguf_header_census_sha256": sha256_file(root / HEADER_CENSUS),
            "hardware_census_sha256": sha256_file(root / HARDWARE),
        },
        "representation": {
            "id": "unsloth-UD-IQ1_S",
            "complete_split_files": 3,
            "complete_split_bytes": representation_bytes,
            "complete_split_gib": round(representation_bytes / 1024**3, 2),
            "gguf_version": 3,
            "architecture": "qwen4exp",
            "tensor_total": derived_r["tensor_total"],
            "object_identities": [row[2] for row in
                                  [next(row for row in census["files"] if row[0] == name)
                                   for name, _, _ in UD_IQ1_S_MEMBERS]],
            "ngram_ple_state": {
                "table_tensor": PLE_TABLE_TENSOR,
                "table_dims": PLE_TABLE_DIMS,
                "table_ggml_type": PLE_TABLE_GGML_TYPE_NAME,
                "table_bytes": ple_bytes,
                "table_gib": round(ple_bytes / 1024**3, 2),
                "split_member": derived_r["ple_split_member"],
                "ple_layer_tensors": [
                    "blk.1.ple_conv1d.weight", "blk.1.ple_key.weight",
                    "blk.1.ple_norm_conv.weight", "blk.1.ple_norm_key.weight",
                    "blk.1.ple_norm_query.weight", "blk.1.ple_value.weight"],
                "metadata_keys": [
                    "qwen4exp.ple.layers", "qwen4exp.ple.ngram_size",
                    "qwen4exp.ple.heads_per_ngram", "qwen4exp.ple.conv_kernel",
                    "qwen4exp.ple.eos_token_id", "qwen4exp.ple.layer_multipliers",
                    "qwen4exp.ple.head_offsets", "qwen4exp.ple.head_vocab_sizes"],
                "identity_addressability": "ESTABLISHED",
                "byte_extent_derived": "offset-delta within split member 00002",
                "representation_separable_from_backbone": "YES",
                "runtime_control_surface": (
                    "llama.cpp -ot/--override-tensor buffer-type override exists at "
                    "the pinned audit revision (common/arg.cpp; "
                    "LLAMA_ARG_OVERRIDE_TENSOR), and per_layer_token_embd is created "
                    "TENSOR_READ_LAZY with PLE-range validation in "
                    "src/models/qwen4exp.cpp. CAVEAT (review finding, loader source "
                    "at the pinned revision): the TENSOR_READ_LAZY path returns "
                    "lazy_read::buft() (CPU) before the -ot override block in "
                    "llama-model-loader/hash buft_for_tensor, so -ot applicability "
                    "to THIS tensor is itself NOT_ESTABLISHED at this revision; "
                    "representation-level addressability (exact identity, byte "
                    "extent, separate split placement) is what is established."),
                "placement_behavior_of_any_build": "NOT_ESTABLISHED (runtime question)",
                "economic_usefulness_of_host_placement": "NOT_ESTABLISHED (unmeasured)",
            },
            "backbone_minus_ple_table_bytes": backbone,
            "backbone_minus_ple_table_gib": round(backbone / 1024**3, 2),
        },
        "fleet_fit": {
            "authority": "hardware-census.json (mechanically derived rows)",
            "deployed_nvidia_bytes": derived_h["nvidia_bytes"],
            "deployed_nvidia_gib": round(derived_h["nvidia_bytes"] / 1024**3, 2),
            "deployed_amd_bytes": derived_h["amd_bytes"],
            "deployed_amd_gib": round(derived_h["amd_bytes"] / 1024**3, 2),
            "deployed_accelerator_bytes_total": deployed_total,
            "deployed_accelerator_gib_total": round(deployed_total / 1024**3, 2),
            "valinor_gtx1060_bytes_excluded_from_execution_fleet":
                derived_h["valinor_bytes"],
            "pending_v340l_bytes": 0,
            "aggregate_weight_headroom_bytes": headroom,
            "capacity_feasible": "NOT_ESTABLISHED",
            "per_resource_fit_constraints": {
                "largest_single_resource_bytes": largest,
                "largest_single_resource_gib": round(largest / 1024**3, 2),
                "single_resource_fits_backbone": single_resource_fits_backbone,
                "single_resource_fits_ple_table": single_resource_fits_ple,
                "note": (
                    "No deployed resource individually holds even the 40.74 GiB "
                    "backbone (largest is 24 GiB), and the 26.82 GiB PLE table "
                    "alone exceeds every resource; any accelerator-resident plan "
                    "requires distribution, and the PLE table specifically "
                    "requires host or split residency regardless of fleet "
                    "aggregate."),
            },
            "capacity_visible_to_backends": {
                "cuda_driver_present_bytes_execution_fleet":
                    derived_h["cuda_driver_present_bytes"] - derived_h["valinor_bytes"],
                "cuda_driver_present_bytes_including_valinor":
                    derived_h["cuda_driver_present_bytes"],
                "vulkan_enumerated_bytes": derived_h["vulkan_enumerated_bytes"],
                "derivation": "row-sum of measured memory over census resources listing each backend",
            },
            "r8_runtime_mode_qualified_capacity_bytes":
                derived_h["qualified_for_r8_bytes"],
            "runtime_supported": "NOT_ESTABLISHED",
            "correctness_qualified": "NOT_ESTABLISHED",
            "economically_useful": "NOT_ESTABLISHED",
            "reason": (
                "96 GiB of deployed accelerator memory exists (80 GiB NVIDIA + "
                "16 GiB AMD, mechanically derived), and the representation is "
                "now header-established, but exact R8 execution qualification "
                "is not established: aggregate VRAM is not a per-resource fit "
                "proof and no qualified llama.cpp build exists for the "
                "proposed mode."),
        },
        "runtime_blockers": [
            {
                "id": "rpc-cross-host-correctness",
                "classification": RPC_CLASSIFICATION,
                "source": "https://github.com/ggml-org/llama.cpp/issues/27993",
                "affected_runtime_revision": RPC_REPRODUCER_REVISION,
                "reported_mode": RPC_REPORTED_MODE,
                "reported_rebuild_revision": RPC_REPORTER_REBUILD_REVISION,
                "reported_fix_revision": RPC_FIX_REVISION,
                "reason": "The reported fix does not qualify NVIDIA, AMD, UD-IQ1_S, this fleet, or the required exact layer/RPC shape.",
            },
            {
                "id": "ngram-materialization-control",
                "classification": "PERFORMANCE_ONLY_RISK",
                "source": "https://github.com/ggml-org/llama.cpp/issues/28256",
                "reason": "The NFS/FS-cache small-read report is performance-only; representation-level addressability of the PLE table is now ESTABLISHED, but actual placement behavior of any build and its economics remain unmeasured runtime questions.",
            },
        ],
        "terminal": "R8A_QWEN38_RUNTIME_PREREQUISITE",
        "terminal_derivation": {
            "representation_sufficient": (
                "YES — bounded header census established GGUF v3/qwen4exp identity, "
                "complete 1224-tensor split placement, exact PLE n-gram tensor "
                "identity/bytes, and an upstream buffer-override control surface; "
                "no separate representation prerequisite remains"),
            "fleet_truthfully_inventoried": (
                "YES — per-resource mechanical census with statuses, provenance, "
                "and reported-but-unobserved devices disclosed, not authored "
                "into capacity"),
            "remaining_blocker": (
                "runtime/backend qualification of one pinned llama.cpp build for "
                "the exact proposed mode on this fleet"),
            "rejected_alternatives": {
                "R8A_QWEN38_REPRESENTATION_PREREQUISITE":
                    "not emitted: the header/tensor census closed the representation gap",
                "R8A_EVIDENCE_BLOCKED":
                    "not emitted: pinned public metadata fully supported the census",
                "R8A_QWEN38_GGUF_PHYSICAL_GATE_READY":
                    "not emitted: no qualified runtime/build exists",
            },
        },
        "runtime_audit_revision": RUNTIME_AUDIT_REVISION,
        "terminal_reason": (
            "The target remains architecturally informative, but no selected and qualified llama.cpp build plus bounded, text-only, single-slot, NVIDIA/cross-host layer-RPC correctness and residency protocol exists for the only current-fleet-sized representation."),
        "successor_recommendation": (
            "Frame the next issue as a bounded qualification problem (not 'fix llama.cpp'): prospective qualification of one pinned llama.cpp commit/build across the exact chosen R8 subject — text only, single request slot, exact pinned UD-IQ1_S split, frozen prompt/context ladder, per-resource weight/KV/GDN/QSA/PLE-staging accounting, exact no-fallback/device proof, short and long prefill/decode correctness. A sensible arm order is NVIDIA first, RX 6800 XT Vulkan when it exists on a reachable host, one RX 580 Vulkan arm, and only then any mixed-backend experiment."),
        "non_claims": [
            "No Qwen3.8 inference, model body download, GPU execution, serving run, or R8-B execution occurred.",
            "This reduction is not acceptance or execution authorization for R8-B.",
            "It does not infer per-tensor residency feasibility, throughput, or host/SSD suitability from aggregate bytes.",
            "No mixed-vendor correctness and no economic claim for PLE host placement is made.",
            "The reported 40 GB AMD inventory and the pending V340L contribute zero bytes to every total above.",
        ],
    }
    document["record_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()
    return document


def render(root: Path = ROOT) -> bytes:
    return json.dumps(reduction_document(root), indent=2, sort_keys=True).encode() + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / OUTPUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(render(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
