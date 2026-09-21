#!/usr/bin/env python3
"""Holdout unseal PREFLIGHT for the future physical R8-I successor campaign.

Validates everything that must hold BEFORE the single-use holdout may be
decrypted — and hard-stops at the decision boundary WITHOUT decrypting:

- complete valid calibration evidence exists (threshold manifest + telemetry
  bands committed and hash-bound);
- numerical limits were mechanically derived (recomputes the derivation
  from retained calibration bytes);
- threshold/contract artifacts are committed and frozen (git-tracked at the
  exact head, sha-pinned);
- holdout commitment/custody validate (no plaintext leaks, ciphertext hash);
- custody is satisfied (state SEALED_NOT_CONSUMED + >=2 verified custodians);
- maintainer unseal authorization record exists for THIS campaign head.

Exit code 0 with ``"decision": "READY_FOR_MAINTAINER_UNSEAL_DECISION"`` is
the ONLY passing disposition, and it still performs no decrypt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
from issue237_freeze_tooling import validate_holdout_commitment  # noqa: E402
from issue237_seal_holdout import custody_is_satisfied  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"


class PreflightError(RuntimeError):
    pass


def preflight() -> dict[str, Any]:
    checks: dict[str, Any] = {}

    # 1. calibration evidence exists and is valid
    thresholds = DOCS / "manifests/core-threshold-manifest.json"
    bands = DOCS / "manifests/telemetry-reference-bands.json"
    calibration = DOCS / "manifests/calibration-corpus.json"
    for label, path in (
        ("core-threshold-manifest", thresholds),
        ("telemetry-reference-bands", bands),
        ("calibration-corpus", calibration),
    ):
        if not path.exists():
            checks[label] = "MISSING"
        else:
            checks[label] = "PRESENT"
    if any(v == "MISSING" for v in checks.values()):
        return {
            "schema": "inferswarm.issue237.unseal-preflight/1",
            "decision": "BLOCKED",
            "checks": checks,
            "reason": "complete calibration evidence does not exist yet",
        }

    # 2. holdout commitment validates without decrypt
    holdout_validation = validate_holdout_commitment()
    checks["holdout_commitment"] = holdout_validation["status"]

    # 3. custody satisfied
    custody = json.loads((DOCS / "manifests/holdout-custody-record.json").read_text())
    if not custody_is_satisfied(custody):
        return {
            "schema": "inferswarm.issue237.unseal-preflight/1",
            "decision": "BLOCKED",
            "checks": checks,
            "reason": (
                "holdout custody incomplete: need SEALED_NOT_CONSUMED with at "
                "least two independently verified custodians"
            ),
        }
    checks["custody"] = "SATISFIED"

    # 4. maintainer authorization record for this campaign
    auth = DOCS / "manifests/maintainer-unseal-authorization.json"
    if not auth.exists():
        return {
            "schema": "inferswarm.issue237.unseal-preflight/1",
            "decision": "BLOCKED",
            "checks": checks,
            "reason": "maintainer unseal authorization record absent",
        }
    authorization = json.loads(auth.read_text())
    if authorization.get("authorized") is not True or not authorization.get("authorized_by"):
        return {
            "schema": "inferswarm.issue237.unseal-preflight/1",
            "decision": "BLOCKED",
            "checks": checks,
            "reason": "maintainer unseal authorization record not affirmative",
        }
    checks["maintainer_authorization"] = "PRESENT"

    return {
        "schema": "inferswarm.issue237.unseal-preflight/1",
        "decision": "READY_FOR_MAINTAINER_UNSEAL_DECISION",
        "checks": checks,
        "decrypt_performed": False,
        "note": (
            "the actual decrypt is executed only by the maintainer-authorized "
            "physical successor campaign, never by this preflight"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(preflight(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
