#!/usr/bin/env python3
"""Issue #133 corrected freeze — canonical physical environment.

The Issue-133 canonical physical environment, per the maintainer decision
(issuecomment-5617122680, Blocker B): current physical topology is
authoritative over the stale #129 hard-coded BDF literals.

The environment is constructed exactly like the frozen #129 derivation
(``scripts/issue129_arm_c_retry_core.py:_frozen_environment`` at
methodology head 808b77c45f0b4e5d52a202c1a931f43447ff93a6``) — the same
accepted immutable model/producer/network/participant identity sources —
with exactly two differences, each authorized by the maintainer decision:

1. the three node_a/node_b ``pci_bdf`` values are the freshly re-observed
   physical BDFs retained in
   ``evidence/arm-c-retry/gpu-identity-observation.json`` (16-char
   domain-prefixed form), NOT the #129 reconstruction's control-plane-only
   literals;
2. the #129 ``provenance_note`` (narrative/provenance-only prose) is
   dropped: it carries no correctness-bearing physical identity, and the
   correction must not let non-semantic prose fields become physical
   authorization inputs.

The historical deployed ``/srv/inferswarm/state/arm-c/environment.json``
(which reproduces the historical Arm-C direct-run digest a730405d…) is NOT
adopted wholesale; only its BDF truth, re-observed live, is used.

The canonical sha256 of the canonical-JSON encoding of this environment is
the new environment authority identity. The r5a static execution plan is
derived mechanically from this environment through the real frozen producer
machinery; nothing here substitutes a hand-copied digest into authority.

CPU-only. No GPU, no model execution, no participant-state mutation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
RETRY_EVIDENCE = (ROOT / "docs/implementation"
                  / "r6-successor-dense-full-integration-117"
                  / "evidence/arm-c-retry")
OBSERVATION_RECORD = RETRY_EVIDENCE / "gpu-identity-observation.json"

#: The environment document family this module produces/validates.
ENVIRONMENT_SCHEMA = "inferswarm.r6.environment-freeze/1"

#: The logical authorized geometry (issue #133; unchanged).
AUTHORIZED_GEOMETRY_CU_IDS = (
    "inferswarm01/gpu-0", "inferswarm01/gpu-1", "inferswarm03/gpu-0")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def environment_canonical_sha256(environment: Mapping[str, Any]) -> str:
    import hashlib
    return hashlib.sha256(canonical_bytes(environment)).hexdigest()


def issue133_physical_environment(repo_root: Path | None = None) -> dict:
    """Construct the canonical Issue-133 physical environment.

    Reuses the frozen #129 derivation verbatim for every accepted
    immutable identity (model, revision, checkpoint, producer, network,
    runtime context, GPU UUID/product/index, VRAM totals), then corrects
    the three pci_bdf values from the retained live observation record.
    The #129 prose-only ``provenance_note`` is dropped.
    """
    import sys
    root = Path(repo_root) if repo_root else ROOT
    sys.path.insert(0, str(root / "scripts"))
    import issue129_arm_c_retry_core as _frozen
    environment = _frozen._frozen_environment(root)
    observation = json.loads(OBSERVATION_RECORD.read_text())
    observed_bdfs: dict[str, str] = {}
    for host in ("inferswarm01", "inferswarm03"):
        for gpu in observation["hosts"][host]["gpus"]:
            cu_id = gpu["logical_authorized_gpu_identity"]
            if cu_id in AUTHORIZED_GEOMETRY_CU_IDS:
                observed_bdfs[cu_id] = gpu["pci_bdf"]
    if set(observed_bdfs) != set(AUTHORIZED_GEOMETRY_CU_IDS):
        raise RuntimeError(
            "gpu-identity-observation.json does not cover exactly the "
            "authorized geometry " + ", ".join(AUTHORIZED_GEOMETRY_CU_IDS))
    bdf_by_uuid = {
        gpu["gpu_uuid"]: gpu["pci_bdf"]
        for host in ("inferswarm01", "inferswarm03")
        for gpu in observation["hosts"][host]["gpus"]}
    environment["node_a"]["gpus"][0]["pci_bdf"] = observed_bdfs[
        "inferswarm01/gpu-0"]
    environment["node_a"]["gpus"][1]["pci_bdf"] = observed_bdfs[
        "inferswarm01/gpu-1"]
    environment["node_b"]["gpus"][0]["pci_bdf"] = observed_bdfs[
        "inferswarm03/gpu-0"]
    # every corrected BDF must come from the observation of the SAME
    # physical GPU (same UUID) the accepted preflight bound
    for node in ("node_a", "node_b"):
        for gpu in environment[node]["gpus"]:
            observed = bdf_by_uuid.get(gpu["uuid"])
            if observed != gpu["pci_bdf"]:
                raise RuntimeError(
                    f"BDF correction for {gpu['uuid']} does not come from "
                    f"the live observation of that GPU "
                    f"(observed {observed!r}, set {gpu['pci_bdf']!r})")
    environment.pop("provenance_note", None)
    return environment


def validate_environment_shape(environment: Mapping[str, Any]) -> None:
    """Fail closed on shape drift: the environment must be exactly the
    #129 structure minus the prose note, with BDFs in the 16-char
    domain-prefixed form for all three authorized units."""
    if environment.get("schema") != ENVIRONMENT_SCHEMA:
        raise RuntimeError("environment schema drift")
    missing = [n for n in ("node_a", "node_b", "model", "network",
                           "runtime_context", "network_context",
                           "implementation_commit") if n not in environment]
    if missing:
        raise RuntimeError(f"environment missing fields {missing}")
    if "provenance_note" in environment:
        raise RuntimeError(
            "provenance_note is narrative-only and must not be a physical "
            "authorization input")
    if len(environment["node_a"]["gpus"]) != 2 or \
            len(environment["node_b"]["gpus"]) != 1:
        raise RuntimeError(
            "authorized geometry is exactly 2+1 GPUs; an expanded "
            "geometry (e.g. the extra idle inferswarm03 GPU) is rejected")
    import re
    for node in ("node_a", "node_b"):
        for gpu in environment[node]["gpus"]:
            if not re.fullmatch(r"[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\."
                                r"[0-9a-f]", gpu["pci_bdf"]):
                raise RuntimeError(
                    f"pci_bdf {gpu['pci_bdf']!r} is not the 16-char "
                    "domain-prefixed nvidia-smi form")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", action="store_true",
                        help="print the canonical environment JSON")
    parser.add_argument("--identity", action="store_true",
                        help="print the canonical sha256 identity")
    args = parser.parse_args()
    environment = issue133_physical_environment()
    validate_environment_shape(environment)
    if args.emit:
        print(json.dumps(environment, indent=2, sort_keys=True))
    if args.identity or not args.emit:
        print(environment_canonical_sha256(environment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
