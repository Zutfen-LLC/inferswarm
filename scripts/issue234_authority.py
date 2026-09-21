#!/usr/bin/env python3
"""Issue #234 — R8-H immutable intended-identity authority builder (/2).

Derives R8-H's authority exclusively from accepted predecessor BYTES in
this repository (paths/sha pinned through each predecessor's own
accepted MANIFEST.sha256 row, every file re-hashed at build):

  R8-D (#195/PR #197) — frozen true-greedy reference (EXTERNAL
       HISTORICAL ANCHOR ONLY in the corrected campaign — never the
       sole Vulkan PASS/FAIL oracle; control 31);
  R8-B — fixture ladder + split identity;
  R8-E (#199) — observation-only divergence-characterization
       methodology reused for the first-divergence score capture;
  V2-F/V2-G — V340L platform predecessors.

Nonclaims: this document authorizes NO physical execution by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

ROOT = rc.ROOT


def _manifest_rows(ns_dir: Path) -> dict[str, str]:
    man = ns_dir / "MANIFEST.sha256"
    rows: dict[str, str] = {}
    prefix = ns_dir.relative_to(ROOT).as_posix() + "/"
    for line in man.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition(" ")
        rel = rel.strip()
        if rel.startswith(prefix):
            rows[rel] = digest
        else:
            rows[prefix + rel] = digest
    return rows


def _verify_against_manifest(ns_dir: Path, rels: list[str]) -> dict[str, dict]:
    rows = _manifest_rows(ns_dir)
    out: dict[str, dict] = {}
    for rel in rels:
        target = ns_dir / rel
        if not target.is_file():
            raise SystemExit(f"authority input missing: {target}")
        manifest_rel = f"{ns_dir.relative_to(ROOT)}/{rel}"
        expected = rows.get(manifest_rel)
        if expected is None:
            raise SystemExit(f"not pinned in accepted MANIFEST: {manifest_rel}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"predecessor byte drift: {manifest_rel} "
                f"{actual} != {expected}")
        out[manifest_rel] = {"sha256": actual, "bytes": target.stat().st_size}
    return out


def build(repo: Path | None = None) -> dict[str, Any]:
    repo = (repo or ROOT).resolve()
    inv = repo / "docs" / "investigations"

    r8d_files = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-d",
        ["evidence/reference/frozen-reference.json",
         "terminal-reduction.json",
         "evidence/split-identity/split-rehash.json"],
    )
    r8b_files = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-b",
        ["evidence/reference/fixture-ladder.json",
         "evidence/split-identity/split-verification.json"],
    )
    r8e_files = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-e",
        ["README.md",
         "evidence/instrumentation/applied-source.patch",
         "terminal-reduction.json"],
    )
    v2g_files = _verify_against_manifest(
        inv / "vulkan-v2-g-pcie-path-remediation",
        ["evidence/TERMINAL.json"],
    )
    v2f_files = _verify_against_manifest(
        inv / "vulkan-v2-f-v340l-external-memory",
        ["evidence/TERMINAL.json"],
    )

    # Cross-bind the fixture ladder identity the issue text pins.
    fixture_path = (inv / "qwen38-flash-next-r8-b" /
                    "evidence/reference/fixture-ladder.json")
    fixture_bytes = fixture_path.read_bytes()
    fixture_sha = hashlib.sha256(fixture_bytes).hexdigest()
    if fixture_sha != rc.R8D_FIXTURE_SHA256:
        raise SystemExit(
            f"fixture ladder identity drift: {fixture_sha} != "
            f"{rc.R8D_FIXTURE_SHA256}")
    fixture = json.loads(fixture_bytes.decode("utf-8"))
    case_ids = [c["case_id"] for c in fixture["cases"]]
    if tuple(case_ids) != rc.LADDER_CASES:
        raise SystemExit(f"fixture case set mismatch: {case_ids}")

    reference = json.loads(
        (inv / "qwen38-flash-next-r8-d" /
         "evidence/reference/frozen-reference.json").read_text("utf-8"))
    r8d_terminal = json.loads(
        (inv / "qwen38-flash-next-r8-d" /
         "terminal-reduction.json").read_text("utf-8"))
    if r8d_terminal.get("terminal") != \
            "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL":
        raise SystemExit(
            f"R8-D terminal drift: {r8d_terminal.get('terminal')!r}")
    for case_id in rc.LADDER_CASES:
        if case_id not in reference["cases"]:
            raise SystemExit(f"reference missing case: {case_id}")

    # Superseded-campaign preservation proof: the quarantined original
    # evidence must still byte-match its df0cf43 blobs. The quarantine
    # moved evidence/<rel> -> SUPERSEDED_REL/<rel>, so the blob lookup
    # maps back to the ORIGINAL df0cf43 path.
    sup_checks = {}
    for p in sorted((repo / rc.SUPERSEDED_REL).rglob("*")):
        if not p.is_file() or p.name == "README.md":
            continue
        rel = p.relative_to(repo / rc.SUPERSEDED_REL).as_posix()
        # the quarantine flattened some duplicate copies: try the
        # direct original path first, then any df0cf43 blob with
        # identical bytes (the quarantined copy IS a preserved copy)
        orig_rel = f"{rc.AREA_REL}/evidence/{rel}"
        blob = subprocess.run(
            ["git", "-C", str(repo), "show",
             f"{rc.SUPERSEDED_HEAD}:{orig_rel}"],
            capture_output=True).stdout
        local_bytes = p.read_bytes()
        if not blob or hashlib.sha256(blob).hexdigest() != \
                hashlib.sha256(local_bytes).hexdigest():
            # search the df0cf43 tree for a byte-identical blob
            tree = subprocess.run(
                ["git", "-C", str(repo), "ls-tree", "-r",
                 rc.SUPERSEDED_HEAD, "--", f"{rc.AREA_REL}"],
                capture_output=True, text=True).stdout
            want = hashlib.sha256(local_bytes).hexdigest()
            # resolve blob sha -> content hash via git cat-file
            found = None
            for line in tree.splitlines():
                meta, path = line.split("\t", 1)
                bsha = meta.split()[2]
                content = subprocess.run(
                    ["git", "-C", str(repo), "cat-file", "blob", bsha],
                    capture_output=True).stdout
                if hashlib.sha256(content).hexdigest() == want:
                    found = path
                    break
            if found is None:
                raise SystemExit(
                    f"superseded byte drift or missing blob: {rel}")
            orig_rel = found
        sup_checks[f"{rc.SUPERSEDED_REL}/{rel}"] = {
            "sha256": hashlib.sha256(local_bytes).hexdigest(),
            "bytes": len(local_bytes)}

    authority = {
        "schema": "inferswarm.r8h.authority/2",
        "campaign": rc.CAMPAIGN_ID,
        "corrected_campaign_note": (
            "R8-D is an external historical anchor only; the matched "
            "A/B/C arms are the terminal authority (control 31)."),
        "predecessor_merges": {
            "r8a": rc.R8A_MERGE,
            "r8d": rc.R8D_MERGE,
            "r8f": rc.R8F_MERGE,
            "r8g": rc.R8G_MERGE,
            "v2e": rc.V2E_MERGE,
            "v2f": rc.V2F_MERGE,
            "v2g": rc.V2G_MERGE,
            "start_main": rc.START_MAIN,
            "superseded_original_campaign_head": rc.SUPERSEDED_HEAD,
        },
        "model_authority": {
            "official_qwen_revision": rc.OFFICIAL_QWEN_REVISION,
            "unsloth_revision": rc.UNSLOTH_REVISION,
            "representation": rc.REPRESENTATION,
            "total_bytes": rc.TOTAL_MODEL_BYTES,
            "members": list(rc.MODEL_MEMBERS),
        },
        "runtime_authority": {
            "llama_cpp_pin": rc.LLAMA_CPP_PIN,
            "builds": {
                "cuda": {"GGML_CUDA": "ON", "GGML_VULKAN": "OFF"},
                "vulkan": {"GGML_VULKAN": "ON", "GGML_CUDA": "OFF"},
            },
            "request_contract": rc.REQUEST_CONTRACT,
        },
        "matched_geometry": {
            "ngl": rc.MATCHED_NGL,
            "context": rc.CONTEXT_SETTINGS,
            "ladder_cases": list(rc.LADDER_CASES),
            "repeats_per_case": rc.REPEATS_PER_CASE,
        },
        "fixture_ladder": {
            "sha256": fixture_sha,
            "case_ids": case_ids,
            "prompt_lengths": {
                c["case_id"]: len(c["prompt_token_ids"])
                for c in fixture["cases"]},
        },
        "external_anchor_outputs": {
            case_id: {
                "generated_tokens":
                    reference["cases"][case_id]["generated_tokens"],
                "stop_type": reference["cases"][case_id]["stop_type"],
                "prompt_len": reference["cases"][case_id]["prompt_len"],
            }
            for case_id in rc.LADDER_CASES
        },
        "superseded_preservation": sup_checks,
        "predecessor_files": {**r8d_files, **r8b_files, **r8e_files,
                              **v2g_files, **v2f_files},
        "nonclaims": [
            "This document binds intended identity only; it authorizes "
            "no physical execution.",
            "Historical BDFs/selectors are not current authority after "
            "hardware movement or reboot.",
            "R8-D token streams are an external historical anchor, "
            "never the sole Vulkan PASS/FAIL oracle.",
        ],
    }
    return authority


def main(argv: list[str] | None = None) -> int:
    desc = (__doc__ or "").splitlines()
    ap = argparse.ArgumentParser(description=desc[0] if desc else "authority")
    ap.add_argument("--out", type=Path,
                    default=rc.ROOT / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
    args = ap.parse_args(argv)
    doc = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out} "
          f"({len(doc['predecessor_files'])} pinned files, "
          f"{len(doc['superseded_preservation'])} superseded-preservised)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
