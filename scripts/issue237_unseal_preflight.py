#!/usr/bin/env python3
"""Holdout unseal PREFLIGHT for the future physical R8-I successor campaign.

Validates everything that must hold BEFORE the single-use holdout may be
decrypted — and hard-stops at the decision boundary WITHOUT decrypting.

Correction-pass contract: every precondition is enforced MECHANICALLY (no
file-existence-only checks). Exit-code 0 with
``"decision": "READY_FOR_MAINTAINER_UNSEAL_DECISION"`` requires ALL of:

1. complete valid calibration evidence — calibration corpus, stress pool,
   selected stress, calibration summary, observation manifest, committed
   core-threshold manifest, committed telemetry bands, all validating
   against the frozen schemas and the exact frozen identities;
2. freshly recomputed threshold artifacts BYTE-IDENTICAL to the committed
   frozen artifacts (the derivation replays over the complete retained
   observation bundle; any hand-edited value, forged digest, missing or
   extra case, wrong family, wrong stress selection, or NaN/Inf fails);
3. correct calibration-corpus and observation-manifest SHA bindings (the
   threshold artifacts' recorded input digests equal the live computed
   digests of those bytes);
4. telemetry artifact validation (bands re-derived and byte-identical);
5. threshold/contract artifacts TRACKED in Git, with the working-tree bytes
   equal to the committed blob bytes at HEAD (no dirty replacement bytes)
   — an untracked or locally-modified authority cannot clear the preflight;
6. active holdout commitment validation (ciphertext SHA derived from
   sealed/holdout.cms, supersession exclusion, CMS recipient bound to the
   retained recipient certificate, custody/commitment seed binding);
7. lifecycle SEALED_NOT_CONSUMED;
8. custody COMPLETE — at least REQUIRED_VERIFIED_CUSTODIANS independent
   custodians, each carrying a mechanically valid public verification
   receipt bound to the live active identities;
9. maintainer authorization record that is affirmative AND bound to the
   EXACT campaign HEAD, the ACTIVE holdout ciphertext, the committed
   frozen threshold-manifest identity, and the comparator/contract
   identities — tracked in Git with clean bytes.

The preflight still performs NO decrypt: the actual unseal is executed
only by the maintainer-authorized physical successor campaign.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
import issue237_schemas as schemas  # noqa: E402
import issue237_thresholds as thr  # noqa: E402
from issue237_freeze_tooling import (  # noqa: E402
    _certificate_pubkey_sha256,
    validate_holdout_commitment,
)
from issue237_seal_holdout import (  # noqa: E402
    custody_is_satisfied,
    custody_receipt_failures,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"

PREFLIGHT_SCHEMA = "inferswarm.issue237.unseal-preflight/2"
AUTHORIZATION_SCHEMA = "inferswarm.issue237.maintainer-unseal-authorization/1"


class PreflightError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        raise PreflightError(f"missing artifact: {path.name}") from None
    except json.JSONDecodeError as exc:
        raise PreflightError(f"malformed JSON in {path.name}: {exc}") from None
    if not isinstance(doc, dict):
        raise PreflightError(f"{path.name} must be a JSON object")
    return doc


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise PreflightError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _git_tracked_clean(rel_paths: list[str]) -> list[str]:
    """Every path must be tracked AND its worktree bytes must equal the
    committed HEAD blob bytes (reject untracked + dirty replacements)."""
    problems: list[str] = []
    for rel in rel_paths:
        # outside the repository entirely: untracked by definition
        if Path(rel).is_absolute() or rel.startswith(".."):
            problems.append(f"{rel} is not tracked in Git")
            continue
        # tracked?
        ls = _git(["ls-files", "--", rel]).splitlines()
        if not ls:
            problems.append(f"{rel} is not tracked in Git")
            continue
        # worktree bytes == HEAD blob bytes?
        blob = _git(["cat-file", "blob", f"HEAD:{rel}"])
        try:
            disk = (REPO / rel).read_text()
        except OSError:
            problems.append(f"{rel} unreadable on disk")
            continue
        if blob != disk:
            problems.append(f"{rel} worktree bytes differ from HEAD (dirty)")
    return problems


def _git_head() -> str:
    return _git(["rev-parse", "HEAD"]).strip()


def _blocked(checks: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema": PREFLIGHT_SCHEMA,
        "decision": "BLOCKED",
        "checks": checks,
        "reason": reason,
        "decrypt_performed": False,
    }


def validate_maintainer_authorization(
    authorization: dict[str, Any],
    *,
    campaign_head: str,
    active_ciphertext_sha256: str,
    frozen_threshold_sha256: str,
) -> list[str]:
    """Exact-head maintainer-authorization binding (fail-closed list)."""
    problems: list[str] = []
    if authorization.get("schema") != AUTHORIZATION_SCHEMA:
        problems.append("authorization schema drift")
    if authorization.get("authorized") is not True:
        problems.append("authorization is not affirmative")
    by = authorization.get("authorized_by")
    if not isinstance(by, str) or not by.strip():
        problems.append("authorization author identity missing")
    bound_head = authorization.get("campaign_head")
    if not isinstance(bound_head, str) or len(bound_head) != 40:
        problems.append("authorization campaign_head malformed")
    elif bound_head != campaign_head:
        problems.append(
            f"authorization bound to head {bound_head[:12]}, not this "
            f"campaign HEAD {campaign_head[:12]} (stale head)"
        )
    if authorization.get("holdout_ciphertext_sha256") != active_ciphertext_sha256:
        problems.append(
            "authorization not bound to the ACTIVE holdout ciphertext"
        )
    if (
        authorization.get("core_threshold_manifest_sha256")
        != frozen_threshold_sha256
    ):
        problems.append(
            "authorization not bound to the committed frozen threshold manifest"
        )
    if authorization.get("comparator_id") != m.COMPARATOR_ID:
        problems.append("authorization comparator identity drift")
    if authorization.get("contract_id") != m.CONTRACT_ID:
        problems.append("authorization contract identity drift")
    return problems


def preflight() -> dict[str, Any]:
    checks: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 1-4. complete valid calibration evidence + mechanical re-derivation
    # ------------------------------------------------------------------
    evidence_paths = {
        "calibration-corpus": DOCS / "manifests/calibration-corpus.json",
        "stress-pool": DOCS / "manifests/stress-pool.json",
        "selected-stress": DOCS / "manifests/selected-stress.json",
        "calibration-summary": DOCS / "manifests/calibration-summary.json",
        "observation-manifest": DOCS / "manifests/observation-manifest.json",
        "core-threshold-manifest": DOCS / "manifests/core-threshold-manifest.json",
        "telemetry-reference-bands": DOCS / "manifests/telemetry-reference-bands.json",
    }
    missing = [name for name, path in evidence_paths.items() if not path.exists()]
    if missing:
        return _blocked(
            {name: "MISSING" for name in missing},
            "complete calibration evidence does not exist yet (missing: "
            + ", ".join(sorted(missing))
            + ")",
        )
    for name, path in evidence_paths.items():
        checks[name] = "PRESENT"

    corpus = _load_json(evidence_paths["calibration-corpus"])
    stress_pool = _load_json(evidence_paths["stress-pool"])
    selected_stress = _load_json(evidence_paths["selected-stress"])
    summary = _load_json(evidence_paths["calibration-summary"])
    observation_manifest = _load_json(evidence_paths["observation-manifest"])

    try:
        schemas.validate_calibration_summary(summary)
    except schemas.SchemaError as exc:
        return _blocked(checks, f"calibration summary invalid: {exc}")
    try:
        verification = thr.verify_threshold_artifacts(
            committed_threshold_bytes=(
                evidence_paths["core-threshold-manifest"].read_bytes()
            ),
            committed_bands_bytes=(
                evidence_paths["telemetry-reference-bands"].read_bytes()
            ),
            calibration_summary=summary,
            calibration_corpus=corpus,
            stress_pool=stress_pool,
            selected_stress=selected_stress,
            observation_manifest=observation_manifest,
        )
    except thr.DerivationError as exc:
        return _blocked(checks, f"threshold derivation failed: {exc}")
    if not verification["threshold_byte_identical"]:
        return _blocked(
            checks,
            "committed core-threshold manifest is not byte-identical to the "
            "fresh mechanical derivation over the retained evidence",
        )
    if not verification["bands_byte_identical"]:
        return _blocked(
            checks,
            "committed telemetry bands are not byte-identical to the fresh "
            "mechanical derivation over the retained evidence",
        )
    checks["threshold_rederivation"] = "BYTE_IDENTICAL"
    checks["telemetry_rederivation"] = "BYTE_IDENTICAL"

    # explicit digest bindings against live computed bytes
    threshold_doc = json.loads(
        evidence_paths["core-threshold-manifest"].read_text()
    )
    live_corpus_sha = sha256_bytes(
        (evidence_paths["calibration-corpus"]).read_bytes()
    )
    live_manifest_sha = sha256_bytes(
        (evidence_paths["observation-manifest"]).read_bytes()
    )
    derived_from = threshold_doc.get("derived_from", {})
    if derived_from.get("calibration_corpus_sha256") != live_corpus_sha:
        return _blocked(
            checks,
            "threshold manifest corpus digest does not bind the live "
            "calibration-corpus bytes",
        )
    if derived_from.get("observation_manifest_sha256") != live_manifest_sha:
        return _blocked(
            checks,
            "threshold manifest observation-manifest digest does not bind "
            "the live observation-manifest bytes",
        )
    checks["digest_bindings"] = "BOUND"

    # ------------------------------------------------------------------
    # 5. git-tracked, HEAD-clean authority artifacts
    # ------------------------------------------------------------------
    manifests_dir = DOCS / "manifests"
    authority_paths = [
        evidence_paths["core-threshold-manifest"],
        evidence_paths["telemetry-reference-bands"],
        evidence_paths["calibration-corpus"],
        evidence_paths["stress-pool"],
        evidence_paths["selected-stress"],
        evidence_paths["calibration-summary"],
        evidence_paths["observation-manifest"],
        manifests_dir / "comparator-identity.json",
        manifests_dir / "layer1-integrity-contract.json",
    ]
    rel_authorities: list[str] = []
    for path in authority_paths:
        try:
            rel_authorities.append(str(path.relative_to(REPO)))
        except ValueError:
            # outside the repository: by definition untracked
            rel_authorities.append(str(path))
    git_problems = _git_tracked_clean(rel_authorities)
    if git_problems:
        return _blocked(
            checks,
            "authority artifacts not git-tracked/HEAD-clean: "
            + "; ".join(git_problems[:4]),
        )
    checks["git_tracked_head_clean"] = "OK"

    # ------------------------------------------------------------------
    # 6. active holdout commitment validation (no decrypt)
    # ------------------------------------------------------------------
    try:
        holdout_validation = validate_holdout_commitment()
    except Exception as exc:  # noqa: BLE001 - report, never crash past gate
        return _blocked(checks, f"holdout commitment validation failed: {exc}")
    checks["holdout_commitment"] = holdout_validation["status"]

    commitment = _load_json(DOCS / "manifests/sealed-holdout-commitment.json")
    active_ciphertext_sha = sha256_bytes(
        (DOCS / "sealed/holdout.cms").read_bytes()
    )

    # ------------------------------------------------------------------
    # 7. lifecycle SEALED_NOT_CONSUMED
    # ------------------------------------------------------------------
    if commitment.get("state") != m.HOLDOUT_STATE_LIFECYCLE:
        return _blocked(
            checks,
            f"holdout lifecycle must be {m.HOLDOUT_STATE_LIFECYCLE}, not "
            f"{commitment.get('state')!r}",
        )
    checks["lifecycle"] = m.HOLDOUT_STATE_LIFECYCLE

    # ------------------------------------------------------------------
    # 8. custody COMPLETE with independent receipt-verified custodians
    # ------------------------------------------------------------------
    custody = _load_json(DOCS / "manifests/holdout-custody-record.json")
    active_pubkey_sha = _certificate_pubkey_sha256(
        DOCS / "sealed/recipient-certificate.pem"
    )
    receipt_failures = custody_receipt_failures(
        custody,
        active_certificate_pubkey_sha256=active_pubkey_sha,
        active_seed_sha256=commitment["secret_seed_sha256"],
        active_ciphertext_sha256=active_ciphertext_sha,
    )
    if receipt_failures:
        return _blocked(
            checks,
            "custody receipts invalid: " + "; ".join(receipt_failures[:4]),
        )
    if not custody_is_satisfied(
        custody,
        active_ciphertext_sha256=active_ciphertext_sha,
        active_certificate_pubkey_sha256=active_pubkey_sha,
        active_seed_sha256=commitment["secret_seed_sha256"],
    ):
        return _blocked(
            checks,
            "custody incomplete: lifecycle must be SEALED_NOT_CONSUMED with "
            "custody_status COMPLETE and at least "
            f"{m.REQUIRED_VERIFIED_CUSTODIANS} independently receipt-verified "
            "custodians",
        )
    checks["custody"] = "SATISFIED"

    # ------------------------------------------------------------------
    # 9. exact-head maintainer authorization
    # ------------------------------------------------------------------
    auth_path = DOCS / "manifests/maintainer-unseal-authorization.json"
    if not auth_path.exists():
        return _blocked(checks, "maintainer unseal authorization record absent")
    try:
        authorization = _load_json(auth_path)
    except PreflightError as exc:
        return _blocked(checks, str(exc))
    frozen_threshold_sha = sha256_bytes(
        evidence_paths["core-threshold-manifest"].read_bytes()
    )
    auth_problems = validate_maintainer_authorization(
        authorization,
        campaign_head=_git_head(),
        active_ciphertext_sha256=active_ciphertext_sha,
        frozen_threshold_sha256=frozen_threshold_sha,
    )
    # authorization must itself be tracked + HEAD-clean
    auth_rel = str(auth_path.relative_to(REPO))
    git_problems = _git_tracked_clean([auth_rel])
    if git_problems:
        auth_problems.extend(git_problems)
    if auth_problems:
        return _blocked(
            checks,
            "maintainer authorization invalid: " + "; ".join(auth_problems[:4]),
        )
    checks["maintainer_authorization"] = "BOUND"

    return {
        "schema": PREFLIGHT_SCHEMA,
        "decision": "READY_FOR_MAINTAINER_UNSEAL_DECISION",
        "checks": checks,
        "campaign_head": _git_head(),
        "active_ciphertext_sha256": active_ciphertext_sha,
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
