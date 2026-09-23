#!/usr/bin/env python3
"""Issue #241 Phase 5: additive v2 methodology supersession builder.

Only after a valid prospective subject exists (a passing Phase 4
terminal), build the ADDITIVE v2 methodology/applicability area. Never
rewrite accepted #237 historical evidence (mechanically enforced: the
v1 area is outside the emitted changed-path allowlist and its bytes are
re-verified unchanged after emission).

Expected superseded fields (mechanically named, from the issue):
  - V340L/inferswarm02 candidate applicability for the FIRST practical
    workhorse comparator;
  - fixed R8-H-derived ngl=1 geometry;
  - independent-prefill comparator/1 physical observation semantics;
  - physical applicability identities downstream of those details.

Expected preserved fields (mechanically named):
  - statistical construction (M=3, H=24, alpha=0.05, N=1416);
  - calibration population;
  - holdout population;
  - acceptance-family definitions (comparator/2 re-audits the
    future-use-state question; family identity change is flagged for
    maintainer adjudication, never auto-applied);
  - decision-stability theorem structure;
  - exact model bytes;
  - historical exclusions;
  - sealed holdout bytes — applicability binding re-check: if the
    committed applicability key mechanically includes the superseded
    V340L identity or comparator/1 such that reuse is invalid, the
    builder STOPS (holdout_reuse_blocked) and requests exact-head
    maintainer review. It never reseals or replaces anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C

SCHEMA = "inferswarm.issue241.phase5-supersession/1"

SUPERSEDED = (
    "V340L/inferswarm02 candidate applicability for the FIRST practical "
    "workhorse comparator",
    "fixed R8-H-derived ngl=1 geometry (matched placement ladder replaces it)",
    "independent-prefill comparator/1 physical observation semantics "
    "(continuous canonical-reference-prefix comparator/2 replaces them)",
    "physical applicability identities downstream of those details "
    "(RX 580 same-host identities replace them)",
)
PRESERVED = (
    "statistical construction (M=3, H=24, alpha=0.05, N=1416)",
    "exact public calibration corpus",
    "holdout population",
    "acceptance-family definitions (comparator/2 re-audits future-use "
    "state; any family-identity change is maintainer-adjudicated)",
    "decision-stability theorem structure",
    "exact model bytes (three-member UD-IQ1_S set)",
    "historical exclusion inventory",
    "sealed holdout bytes (subject to the applicability-binding check)",
)

# The holdout's COMMITTED applicability key is the seal commitment
# (contract_id + ciphertext binding). The v1 subject-applicability and
# validation-report manifests DO carry the superseded markers, but they
# describe the v1 subject and remain frozen as accepted v1 history —
# they are scanned ADVISORILY (surface for maintainer adjudication),
# never treated as a re-seal trigger by this builder.
HOLDOUT_BINDING_REL = (
    "docs/qualification/qwen38-vulkan-v1/manifests/"
    "sealed-holdout-commitment.json")
ADVISORY_APPLICABILITY_RELS = (
    "docs/qualification/qwen38-vulkan-v1/manifests/subject-applicability.json",
    "docs/qualification/qwen38-vulkan-v1/manifests/validation-report.json",
)
SUPERSEDED_BINDING_MARKERS = (
    "00000000:06:00.0",       # V340L selected die BDF
    "inferswarm02",
    "comparator/1",
)


def check_holdout_reuse(root: Path | None = None) -> dict[str, Any]:
    """Read the PUBLIC commitment; stop if it mechanically binds the
    superseded subject such that reuse is invalid."""
    root = root or C.ROOT
    doc = json.loads((root / HOLDOUT_BINDING_REL).read_text())
    text = json.dumps(doc)
    hits = [m for m in SUPERSEDED_BINDING_MARKERS if m in text]
    advisory: dict[str, list[str]] = {}
    for rel in ADVISORY_APPLICABILITY_RELS:
        atext = (root / rel).read_text()
        advisory[rel] = [m for m in SUPERSEDED_BINDING_MARKERS if m in atext]
    return {
        "committed_binding": HOLDOUT_BINDING_REL,
        "contract_id": doc.get("contract_id"),
        "binding_markers_present": hits,
        "reuse_valid": not hits,
        "advisory_v1_area_markers": advisory,
        "advisory_note": (
            "v1-area applicability manifests legitimately describe the v1 "
            "V340L subject and stay frozen as accepted history; whether the "
            "existing seal may serve the v2 RX580 subject is a maintainer "
            "exact-head adjudication at Phase 5 acceptance"),
        "rule": ("if the committed applicability key includes the superseded "
                 "V340L identity or comparator/1, STOP before resealing/"
                 "replacing anything and request maintainer exact-head review"),
    }


def build_supersession(root: Path | None = None,
                       phase4_terminal: str | None = None) -> dict[str, Any]:
    """Emit the additive v2 supersession record (dormant until dispatch)."""
    root = root or C.ROOT
    if phase4_terminal not in C.DISPOSITIONS:
        raise ValueError("phase 4 terminal must name one frozen disposition")
    practical = phase4_terminal == C.DISPOSITION_PRACTICAL
    holdout = check_holdout_reuse(root)
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "phase4_terminal": phase4_terminal,
        "additive_area": C.AREA_REL,
        "accepted_predecessor": {
            "merge": C.ACCEPTED_MAIN,
            "terminal": C.R8I_TERMINAL,
            "area": C.R8I_AREA_REL,
            "preserved_byte_for_byte": True,
        },
        "superseded": list(SUPERSEDED),
        "preserved": list(PRESERVED),
        "holdout_reuse": holdout,
        "authority_emitted": False,
        "authority_note": (
            "PROSPECTIVE RECORD ONLY — this builder emits NO v2 "
            "supersession authority. A v2 supersession is emitted only "
            "after the measured Phase-4 disposition AND a subsequent "
            "maintainer GO on the exact corrected head (Issue #241 "
            "sequencing); until then this record carries no accepted "
            "authority of any kind."),
        "status": ("PROSPECTIVE — dormant until maintainer dispatch and a "
                   "passing practical terminal" if not practical else
                   "READY — pending maintainer acceptance"),
    }
    if not holdout["reuse_valid"]:
        record["status"] = (
            "HOLDOUT REUSE BLOCKED — superseded identity mechanically bound "
            "in the sealed-holdout commitment; maintainer exact-head review "
            "required before any v2 successor authority is emitted")
        record["supersession_blocked"] = True
    return record


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--phase4-terminal", required=True,
                    choices=list(C.DISPOSITIONS))
    args = ap.parse_args(argv)
    print(json.dumps(build_supersession(phase4_terminal=args.phase4_terminal),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
