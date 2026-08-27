#!/usr/bin/env python3
"""Validate the frozen InferSwarm Phase-0 workload manifest without model/GPU access.

This is a repository-integrity check, not the runtime token-shape check. The FreeToken
Phase-0 harness remains authoritative for tokenizer-observed W1-W4 prompt shapes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/benchmarks/workloads/phase0-v1/manifest.json"
EXPECTED_CLASSES = {"W1": 512, "W2": 512, "W3": 256, "W4": 128}
EXPECTED_SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20}


def main() -> int:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []

    if doc.get("schema") != "inferswarm.phase0.workload-manifest/1":
        errors.append(f"unexpected schema: {doc.get('schema')!r}")
    if doc.get("canonical") is not True:
        errors.append("manifest must declare canonical=true")

    workloads = doc.get("workloads")
    if not isinstance(workloads, list):
        errors.append("workloads must be a list")
        workloads = []

    seen: set[str] = set()
    for entry in workloads:
        class_id = entry.get("class_id")
        if class_id not in EXPECTED_CLASSES:
            errors.append(f"unknown class_id: {class_id!r}")
            continue
        if class_id in seen:
            errors.append(f"duplicate class_id: {class_id}")
            continue
        seen.add(class_id)

        rel = entry.get("fixture_path")
        if not isinstance(rel, str):
            errors.append(f"{class_id}: fixture_path missing")
            continue
        path = (MANIFEST.parent / rel).resolve()
        if not path.is_file():
            errors.append(f"{class_id}: fixture missing: {rel}")
            continue

        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        declared = entry.get("content_sha256")
        print(f"{class_id} sha256 {actual}  {rel}")
        if declared != actual:
            errors.append(f"{class_id}: content_sha256 mismatch: manifest={declared} actual={actual}")

        if entry.get("output_tokens") != EXPECTED_CLASSES[class_id]:
            errors.append(
                f"{class_id}: output_tokens={entry.get('output_tokens')!r}; "
                f"expected {EXPECTED_CLASSES[class_id]}"
            )
        if entry.get("ignore_eos") is not True:
            errors.append(f"{class_id}: ignore_eos must be true")
        if entry.get("sampling") != EXPECTED_SAMPLING:
            errors.append(
                f"{class_id}: sampling={entry.get('sampling')!r}; expected {EXPECTED_SAMPLING!r}"
            )
        if entry.get("seed", None) is not None:
            errors.append(f"{class_id}: seed must be null because FreeToken exposes no seed")

    missing = sorted(set(EXPECTED_CLASSES) - seen)
    if missing:
        errors.append(f"missing required classes: {missing}")

    if errors:
        print("\nERRORS:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Frozen Phase-0 workload manifest integrity OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
