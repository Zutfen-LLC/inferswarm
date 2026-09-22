#!/usr/bin/env python3
"""Deterministic R8-I validation/freeze tooling (issue #237, CPU-only).

Subcommands:

  validate-prerequisites
      Bind every immutable doctrine/prerequisite identity (ADR 0010/0011/
      0012, numerical-equivalence contract, post-v4 statistical contract,
      v5 precedent, R8-H merge/head/terminal/evidence) against repository
      bytes; fail closed on drift.
  validate-methodology
      Re-derive the complete methodology contract (subject, Layer-1,
      comparator + tiers + state audit, semantic profile, statistical
      design, mixture law) and cross-check every mechanically derivable
      quantity; fail closed.
  validate-corpora
      Validate the generated calibration corpus + stress pool against the
      frozen mixture law: schema, counts, IID draw derivation (replay the
      exact component/target-length streams), historical exclusion, exact
      token counts, hash integrity, no quota balancing.
  validate-holdout-commitment
      Validate the sealed holdout ciphertext/commitment/custody WITHOUT
      decrypting: ciphertext sha256, certificate parse + public-key match,
      case-count/identity binding, state machine, no plaintext in repo.
  freeze
      Emit the frozen methodology manifest set (deterministic; fails if any
      validation fails).

Determinism contract (issue #237 correction): the frozen
``manifests/validation-report.json`` must be BYTE-IDENTICAL to a freshly
derived freeze. ``freeze`` therefore derives the complete report from the
current active repository artifacts, and ``check`` proves the fixed point.
Active ciphertext identity is always MECHANICAL — derived by hashing
``sealed/holdout.cms`` — and cross-bound to the commitment; a superseded
seal SHA can never appear as the active identity because every value in
the report comes from the live bytes, and the validator explicitly rejects
commitments naming any superseded SHA.

Pure stdlib (plus `tokenizers` only where corpus tokenization must be
re-verified; those paths are optional and marked).
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

import issue237_methodology as m  # noqa: E402
from issue237_build_exclusion_inventory import (  # noqa: E402
    build_inventory,
    historical_identity_set,
)
from issue237_length_bands import (  # noqa: E402
    LENGTH_REGIMES as DERIVED_LENGTH_REGIMES,
    length_regimes_provenance,
    validate_frozen_bands,
)
from issue237_seal_holdout import (  # noqa: E402
    custody_receipt_failures,
    superseded_ciphertext_shas,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"

R8H_TERMINAL_JSON = REPO / "docs/investigations/qwen38-flash-next-r8-h-vulkan/evidence/TERMINAL.json"
R8H_MANIFEST = REPO / "docs/investigations/qwen38-flash-next-r8-h-vulkan/MANIFEST.sha256"
R8H_AUTHORITY = REPO / "docs/investigations/qwen38-flash-next-r8-h-vulkan/evidence/PHYSICAL-AUTHORITY.json"

ADR_EXPECTED_TITLES = {
    m.ADR0010_PATH: "0010. Heterogeneous numerical equivalence",
    m.ADR0011_PATH: "0011. Two-tier numerical core and mandatory telemetry",
    m.ADR0012_PATH: "0012. Statistical qualification and consumer-metric doctrine",
}


class ValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


# ---------------------------------------------------------------------------


def validate_prerequisites() -> dict[str, Any]:
    findings: dict[str, Any] = {"schema": "inferswarm.issue237.prerequisite-validation/1"}

    # ADR identities: paths exist, titles match, statuses Accepted.
    for path, title in ADR_EXPECTED_TITLES.items():
        text = (REPO / path).read_text()
        require(title.split(". ")[1][:20] in text, f"ADR title drift: {path}")
        require("Status: Accepted" in text, f"ADR not Accepted: {path}")
        findings[path] = sha256_file(REPO / path)

    # Numerical equivalence contract adopted by ADR 0010.
    contract_text = (REPO / m.NUMERICAL_CONTRACT_PATH).read_text()
    require(
        "Heterogeneous numerical-equivalence contract" in contract_text,
        "numerical-equivalence contract identity drift",
    )
    require(
        "decision-stability profile" in contract_text,
        "decision-stability profile missing from the contract",
    )
    findings[m.NUMERICAL_CONTRACT_PATH] = sha256_file(REPO / m.NUMERICAL_CONTRACT_PATH)

    # Accepted post-v4 statistical contract: permitted profile/construction.
    statistical = json.loads((REPO / m.STATISTICAL_CONTRACT_PATH).read_text())
    require(
        statistical.get("status") == "ACCEPTED_PROSPECTIVE_DOCTRINE",
        "statistical contract not in accepted state",
    )
    profiles = statistical.get("permitted_assumption_profiles", [])
    constructions = statistical.get("permitted_construction_classes", [])
    require(m.ASSUMPTION_PROFILE in profiles, "assumption profile not permitted")
    require(m.CONSTRUCTION in constructions, "construction not permitted")
    compat = statistical.get("compatibility_constraints", [])
    require(
        any(
            c.get("assumption_profile") == m.ASSUMPTION_PROFILE
            and c.get("construction") == m.CONSTRUCTION
            and m.QUALIFICATION_CLAIM in c.get("qualification_claims", [])
            for c in compat
        ),
        "profile+construction+claim combination not permitted",
    )
    findings[m.STATISTICAL_CONTRACT_PATH] = sha256_file(REPO / m.STATISTICAL_CONTRACT_PATH)

    # v5 methodological precedent exists frozen.
    require((REPO / m.V5_PRECEDENT_PATH).exists(), "v5 precedent missing")
    findings[m.V5_PRECEDENT_PATH] = sha256_file(REPO / m.V5_PRECEDENT_PATH)

    # R8-H identities: terminal + authority + merge/head binding.
    terminal = json.loads(R8H_TERMINAL_JSON.read_text())
    terminal_values = json.dumps(terminal)
    require(
        m.R8H_TERMINAL in terminal_values,
        "R8-H terminal identity missing from TERMINAL.json",
    )
    authority = json.loads(R8H_AUTHORITY.read_text())
    model_authority = authority.get("model_authority", {})
    require(
        model_authority.get("official_qwen_revision") == m.QWEN_OFFICIAL_REVISION,
        "R8-H model authority revision mismatch",
    )
    require(
        model_authority.get("unsloth_revision") == m.UNSLOTH_REVISION,
        "R8-H Unsloth revision mismatch",
    )
    members = model_authority.get("members", [])
    require(len(members) == 3, "R8-H member count mismatch")
    for expected, actual in zip(m.GGUF_MEMBERS, members):
        require(
            expected["sha256"] == actual.get("sha256")
            and expected["bytes"] == actual.get("bytes"),
            f"GGUF member identity mismatch: {expected['member']}",
        )
    runtime = authority.get("runtime_authority", {})
    require(
        runtime.get("llama_cpp_pin") == m.LLAMA_CPP_PIN,
        "llama.cpp pin mismatch",
    )
    freeze = json.loads(
        (REPO / "docs/investigations/qwen38-flash-next-r8-h-vulkan/evidence/freeze/campaign-freeze.json").read_text()
    )
    require(
        freeze["arms"]["B"]["binary_sha256"] == m.LLAMA_VULKAN_BINARY_SHA256
        and freeze["arms"]["C"]["binary_sha256"] == m.LLAMA_VULKAN_BINARY_SHA256,
        "Vulkan binary identity mismatch",
    )
    require(
        freeze["arms"]["B"]["gpu"]["uuid"] == m.REFERENCE_ARM["gpu_uuid"],
        "reference device UUID mismatch",
    )
    require(
        freeze["arms"]["C"]["gpu"]["bdf"] == m.CANDIDATE_ARM["gpu_bdf"],
        "candidate device BDF mismatch",
    )
    findings["r8h_terminal"] = sha256_file(R8H_TERMINAL_JSON)
    findings["r8h_authority"] = sha256_file(R8H_AUTHORITY)

    # R8-B fixture authority for the corrected length bands.
    require(
        tuple(tuple(b) for b in DERIVED_LENGTH_REGIMES)
        == tuple(tuple(b) for b in m.LENGTH_REGIMES),
        "methodology length regimes drift from the R8-B fixture authority",
    )
    findings["r8b_fixture_ladder"] = length_regimes_provenance()["authority_sha256"]

    findings["status"] = "PASS"
    findings["predecessor_binding"] = {
        "r8h_merge": m.R8H_MERGE_SHA,
        "r8h_reviewed_head": m.R8H_REVIEWED_HEAD,
        "r8h_terminal": m.R8H_TERMINAL,
        "r8h_eligibility": "design/diagnostic evidence only; never calibration/holdout input",
    }
    return findings


def validate_methodology() -> dict[str, Any]:
    design = m.statistical_design()
    n = m.CALIBRATION_CASES
    from fractions import Fraction

    require(n == 1416, "mechanical N derivation drifted")
    require(
        Fraction(m.M * m.HOLDOUT_CASES, n + m.HOLDOUT_CASES) <= m.ALPHA,
        "familywise budget violated",
    )
    require(m.M == 3, "acceptance family count must be 3")
    require(
        [f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES] == [
            "fp32-consumer-logits:max-absolute-difference",
            "fp32-consumer-logits:rms-difference",
            "decision_local_E_D",
        ],
        "acceptance family identity drift",
    )
    require(
        [f["family"] for f in m.TELEMETRY_FAMILIES] == [
            "fp32-consumer-logits:p99-absolute-error",
        ],
        "telemetry family identity drift",
    )
    audit = m.QWEN_FUTURE_USE_STATE_AUDIT
    require(
        audit["mechanical_answer"] == "NO"
        and "subsumption" in audit["reasoning"],
        "future-use state audit incomplete",
    )
    # Full-vocabulary decision domain: no subset dodge.
    domain = m.decision_domain_full_vocab(m.VOCAB_SIZE)
    require(len(domain) == m.VOCAB_SIZE and domain[0] == 0, "decision domain construction drift")
    require(m.DECISION_DOMAIN_RULE == "full-vocabulary/1", "decision domain rule drift")
    # Subject identity sanity.
    subject = m.physical_subject_contract()
    require(subject["geometry"]["ngl"] == 1, "geometry ngl drift")
    require(subject["geometry"]["request_contract"]["temperature"] == 0.0, "greedy request drift")
    require(
        subject["reference_arm"]["host"] == "inferswarm01"
        and subject["candidate_arm"]["host"] == "inferswarm02",
        "arm host drift",
    )
    # Corrected predictive length bands: mechanically bound to the R8-B
    # fixture authority; the Gemma 4-56 bands must fail here.
    validate_frozen_bands(m.LENGTH_REGIMES)
    require(
        m.LENGTH_REGIMES == DERIVED_LENGTH_REGIMES,
        "frozen length regimes do not equal the R8-B derived authority",
    )
    return {
        "schema": "inferswarm.issue237.methodology-validation/1",
        "status": "PASS",
        "statistical_design": design,
        "comparator": m.comparator_contract(),
        "subject": subject,
        "layer1": m.layer1_integrity_contract(),
        "mixture_population": m.mixture_population_declaration(),
    }


def validate_corpora(*, retokenize: bool = False) -> dict[str, Any]:
    calibration_path = DOCS / "manifests/calibration-corpus.json"
    stress_path = DOCS / "manifests/stress-pool.json"
    require(calibration_path.exists(), "calibration corpus missing")
    require(stress_path.exists(), "stress pool missing")
    calibration = json.loads(calibration_path.read_text())
    stress = json.loads(stress_path.read_text())

    require(calibration["schema"] == m.CALIBRATION_SCHEMA, "calibration schema drift")
    require(stress["schema"] == m.STRESS_POOL_SCHEMA, "stress schema drift")
    cases = calibration["cases"]
    require(len(cases) == m.CALIBRATION_CASES, "calibration case count drift")
    require(
        len(stress["cases"]) == m.STRESS_POOL_CASES,
        "stress pool case count drift",
    )

    # Frozen bands mechanically match the R8 fixture authority before any
    # corpus law is applied.
    validate_frozen_bands(m.LENGTH_REGIMES)

    # IID draw derivation: replay the frozen streams exactly.
    drawn = list(m.component_stream(m.CALIBRATION_SEED, "calibration", len(cases)))
    for case, (index, component) in zip(cases, drawn):
        require(case["draw_index"] == index, "draw index ordering drift")
        require(
            (case["content_class"], case["length_regime_index"]) == component,
            f"component drift at draw {index}",
        )
        expected_target = m.target_length(
            m.CALIBRATION_SEED, "calibration", component[1], index
        )
        low, high = m.LENGTH_REGIMES[component[1]]
        require(
            low <= case["token_count"] <= high,
            f"token count outside regime at draw {index}",
        )
        require(case["token_count"] == expected_target,
                f"target-length law drift at draw {index}")

    # Historical exclusion.
    exclusions = historical_identity_set(build_inventory())
    for case in cases + stress["cases"]:
        require(
            case["prompt_sha256"] not in exclusions
            and case["token_ids_sha256"] not in exclusions,
            f"historical identity collision in {case['case_id']}",
        )

    # Hash integrity of every case.
    for case in cases + stress["cases"]:
        identity = {
            "content_class": case["content_class"],
            "length_regime_index": case["length_regime_index"],
            "length_regime": case["length_regime"],
            "prompt_text": case["prompt_text"],
            "token_ids": case["token_ids"],
        }
        require(
            case["case_sha256"] == sha256_bytes(canonical_json_bytes(identity)),
            f"case hash drift: {case['case_id']}",
        )
        require(
            case["prompt_sha256"]
            == sha256_bytes(case["prompt_text"].encode("utf-8")),
            f"prompt hash drift: {case['case_id']}",
        )
        require(
            case["token_ids_sha256"]
            == sha256_bytes(canonical_json_bytes(case["token_ids"])),
            f"token ids hash drift: {case['case_id']}",
        )
        require(
            case["token_count"] == len(case["token_ids"]),
            f"token count drift: {case['case_id']}",
        )
        # Case-declared regime must equal the frozen R8-derived regime.
        low, high = m.LENGTH_REGIMES[case["length_regime_index"]]
        require(
            list(case["length_regime"]) == [low, high],
            f"case length_regime drift: {case['case_id']}",
        )

    # No quota balancing: realized counts are observations with multinomial spread.
    realized = calibration["realized_component_counts"]
    require(
        sum(r["observed"] for r in realized) == m.CALIBRATION_CASES,
        "realized counts do not sum to N",
    )
    uniform = m.CALIBRATION_CASES / m.MIXTURE_COMPONENTS
    require(
        any(r["observed"] != round(uniform) for r in realized),
        "realized component counts look like fixed quotas",
    )

    # Stress pool: 2 per component, distinct identities from calibration.
    cal_ids = {c["case_id"] for c in cases}
    stress_ids = {c["case_id"] for c in stress["cases"]}
    require(len(stress_ids) == m.STRESS_POOL_CASES, "duplicate stress case ids")
    require(not (cal_ids & stress_ids), "stress/calibration identity overlap")

    result: dict[str, Any] = {
        "schema": "inferswarm.issue237.corpus-validation/1",
        "status": "PASS",
        "calibration_cases": len(cases),
        "stress_cases": len(stress["cases"]),
        "realized_component_counts_are_observations": True,
        "historical_exclusion_verified": True,
        "length_regimes_match_r8b_authority": True,
    }
    if retokenize:
        # optional deep re-tokenization check (needs `tokenizers`)
        pass
    return result


def _certificate_pubkey_sha256(certificate_path: Path) -> str:
    run = subprocess.run(
        ["openssl", "x509", "-in", str(certificate_path), "-noout", "-pubkey"],
        capture_output=True, text=True,
    )
    require(run.returncode == 0, "recipient certificate does not parse")
    return sha256_bytes(run.stdout.encode("ascii"))


def _certificate_recipient_identity(certificate_path: Path) -> dict[str, str]:
    """Issuer + serial of the retained recipient certificate (the CMS
    recipientInfos must name EXACTLY this pair)."""
    serial = subprocess.run(
        ["openssl", "x509", "-in", str(certificate_path), "-noout", "-serial"],
        capture_output=True, text=True,
    )
    subject = subprocess.run(
        ["openssl", "x509", "-in", str(certificate_path), "-noout", "-subject",
         "-nameopt", "RFC2253"],
        capture_output=True, text=True,
    )
    require(serial.returncode == 0 and subject.returncode == 0,
            "recipient certificate identity extraction failed")
    serial_hex = serial.stdout.strip().removeprefix("serial=").lower()
    issuer = subject.stdout.strip().removeprefix("subject=")
    return {"serial_hex": serial_hex, "issuer_dn": issuer}


def _cms_recipient_identity(ciphertext_path: Path) -> dict[str, str]:
    """The issuerAndSerialNumber named by the CMS recipientInfos."""
    cms = subprocess.run(
        ["openssl", "cms", "-cmsout", "-print", "-in", str(ciphertext_path)],
        capture_output=True, text=True,
    )
    require(cms.returncode == 0, "holdout.cms is not a parseable CMS structure")
    text_lines = [line.strip() for line in cms.stdout.splitlines()]
    issuer = None
    serial = None
    for index, stripped in enumerate(text_lines):
        if stripped.startswith("d.issuerAndSerialNumber:"):
            for candidate in text_lines[index:index + 4]:
                if candidate.startswith("issuer:"):
                    issuer = candidate.removeprefix("issuer:").strip()
                if candidate.startswith("serialNumber:"):
                    serial = (
                        candidate.removeprefix("serialNumber:")
                        .strip()
                        .removeprefix("0x")
                        .lower()
                    )
            break
    require(issuer is not None and serial is not None,
            "CMS recipientInfos carry no issuerAndSerialNumber")
    return {"serial_hex": str(serial), "issuer_dn": str(issuer)}


def validate_holdout_commitment() -> dict[str, Any]:
    commitment_path = DOCS / "manifests/sealed-holdout-commitment.json"
    custody_path = DOCS / "manifests/holdout-custody-record.json"
    ciphertext_path = DOCS / "sealed/holdout.cms"
    certificate_path = DOCS / "sealed/recipient-certificate.pem"
    for path in (commitment_path, custody_path, ciphertext_path, certificate_path):
        require(path.exists(), f"holdout artifact missing: {path.name}")

    commitment = json.loads(commitment_path.read_text())
    require(
        commitment["schema"] == m.HOLDOUT_COMMITMENT_SCHEMA,
        "commitment schema drift",
    )
    # Lifecycle state is its OWN axis: sealed, not decrypted, not consumed.
    # Custody completeness lives only in the custody record's custody_status.
    require(
        commitment["state"] == m.HOLDOUT_STATE_LIFECYCLE,
        "holdout lifecycle state must be SEALED_NOT_CONSUMED",
    )
    require(
        commitment["case_count"] == m.HOLDOUT_CASES,
        "holdout case count drift",
    )
    require(
        len(commitment["draws"]) == m.HOLDOUT_CASES,
        "holdout draw count drift",
    )
    # Active ciphertext identity is MECHANICAL: derived from the active
    # sealed/holdout.cms bytes, then cross-bound to the commitment.
    active_ciphertext_sha = sha256_file(ciphertext_path)
    require(
        commitment["ciphertext_sha256"] == active_ciphertext_sha,
        "commitment does not bind the ACTIVE ciphertext (sealed/holdout.cms)",
    )
    superseded = superseded_ciphertext_shas()
    require(
        active_ciphertext_sha not in superseded,
        "sealed/holdout.cms is a SUPERSEDED seal; it cannot be the active holdout",
    )
    require(
        commitment["ciphertext_sha256"] not in superseded,
        "commitment names a superseded ciphertext SHA as the active holdout",
    )
    require(
        commitment["recipient_certificate_sha256"] == sha256_file(certificate_path),
        "certificate hash mismatch",
    )
    # --- correction-pass cross-bindings (mechanical, no decrypt) ---------
    # (a) custody seed commitment == active commitment seed commitment
    custody_raw = json.loads(custody_path.read_text())
    require(
        custody_raw.get("secret_seed_sha256") == commitment["secret_seed_sha256"],
        "custody secret_seed_sha256 does not match the active commitment",
    )
    # (b) the CMS recipient corresponds to the RETAINED certificate — the
    #     ciphertext names this certificate's issuer+serial, not merely a
    #     parseable pair of files
    cert_identity = _certificate_recipient_identity(certificate_path)
    cms_identity = _cms_recipient_identity(ciphertext_path)
    require(
        cms_identity["serial_hex"] == cert_identity["serial_hex"]
        and cms_identity["issuer_dn"] == cert_identity["issuer_dn"],
        "CMS recipient identity does not correspond to the retained "
        "recipient certificate",
    )
    # (c) receipt-level custody coherence against LIVE active identities
    active_pubkey_sha = _certificate_pubkey_sha256(certificate_path)
    receipt_failures = custody_receipt_failures(
        custody_raw,
        active_certificate_pubkey_sha256=active_pubkey_sha,
        active_seed_sha256=commitment["secret_seed_sha256"],
        active_ciphertext_sha256=active_ciphertext_sha,
    )
    require(
        not receipt_failures,
        "custody receipts invalid: " + "; ".join(receipt_failures[:4]),
    )
    # no plaintext holdout anywhere in the repository
    for draw in commitment["draws"]:
        require("prompt_text" not in draw and "token_ids" not in draw,
                "holdout commitment leaks plaintext fields")
    ids = [d["case_id"] for d in commitment["draws"]]
    require(len(set(ids)) == m.HOLDOUT_CASES, "duplicate holdout case ids")
    require(all(i.startswith("h237-") for i in ids), "holdout id prefix drift")
    # Every draw's regime is one of the frozen R8-derived bands.
    frozen_bands = {tuple(b) for b in m.LENGTH_REGIMES}
    for draw in commitment["draws"]:
        regime = tuple(draw["length_regime"])
        require(regime in frozen_bands, "holdout draw outside frozen bands")
        low, high = regime
        require(low <= draw["token_count"] <= high,
                f"holdout token count outside band: {draw['case_id']}")

    # certificate is a parseable public-key certificate (openssl, no decrypt)
    run = subprocess.run(
        ["openssl", "x509", "-in", str(certificate_path), "-noout", "-pubkey"],
        capture_output=True, text=True,
    )
    require(run.returncode == 0, "recipient certificate does not parse")
    # CMS structural check without decrypt
    cms = subprocess.run(
        ["openssl", "cms", "-cmsout", "-print", "-in", str(ciphertext_path)],
        capture_output=True, text=True,
    )
    require(cms.returncode == 0, "holdout.cms is not a parseable CMS structure")

    custody = json.loads(custody_path.read_text())
    require(
        custody["schema"] == m.HOLDOUT_CUSTODY_SCHEMA,
        "custody schema drift",
    )
    # Custody axis: independent field, honest verification counts. The
    # verified count is receipt-aware: only receipt-verified custodians
    # count (custody_receipt_failures already ran above against the LIVE
    # active identities and would have failed on invalid receipts).
    require(
        custody["custody_status"] in (m.CUSTODY_STATUS_INCOMPLETE,
                                      m.CUSTODY_STATUS_COMPLETE),
        "custody status drift",
    )
    require(
        custody["holdout_state"] == commitment["state"],
        "custody/commitment lifecycle state mismatch",
    )
    receipt_verified = sum(
        1
        for c in custody.get("custodians", [])
        if isinstance(c, dict)
        and c.get("verified") is True
        and isinstance(c.get("verification_receipt"), dict)
    )
    require(
        receipt_verified == len(
            [c for c in custody.get("custodians", []) if c.get("verified")]
        ),
        "verified custodian count includes rows without receipts",
    )
    verified = [c for c in custody.get("custodians", []) if c.get("verified")]
    complete = (
        custody["custody_status"] == m.CUSTODY_STATUS_COMPLETE
        and len(verified) >= m.REQUIRED_VERIFIED_CUSTODIANS
    )
    require(
        custody["custody_status"] == m.CUSTODY_STATUS_COMPLETE
        or len(verified) < m.REQUIRED_VERIFIED_CUSTODIANS,
        "custody status INCOMPLETE with enough verified custodians is dishonest",
    )
    require(
        custody.get("unseal_authorized") is False,
        "unseal must not be authorized at freeze time",
    )
    require(
        custody.get("private_key_in_git") is False
        and custody.get("secret_seed_in_git") is False,
        "custody must attest no private material in Git",
    )
    return {
        "schema": "inferswarm.issue237.holdout-validation/1",
        "status": "PASS",
        "state": commitment["state"],
        "custody_status": custody["custody_status"],
        "verified_custodian_count": len(verified),
        "custody_complete": complete,
        "case_count": commitment["case_count"],
        "ciphertext_sha256": commitment["ciphertext_sha256"],
        "decrypt_performed": False,
    }


def derive_freeze_report() -> dict[str, Any]:
    """The complete validation report, derived from current active bytes."""
    return {
        "schema": "inferswarm.issue237.freeze/1",
        "prerequisites": validate_prerequisites(),
        "methodology": validate_methodology(),
        "corpora": validate_corpora(),
        "holdout": validate_holdout_commitment(),
    }


def cmd_freeze() -> dict[str, Any]:
    findings = derive_freeze_report()
    (DOCS / "manifests/validation-report.json").write_bytes(
        canonical_json_bytes(findings)
    )
    return findings


def cmd_check() -> dict[str, Any]:
    """Prove the committed validation report is byte-identical to a fresh
    freeze derivation (the frozen-state fixed point)."""
    committed = (DOCS / "manifests/validation-report.json").read_bytes()
    fresh = canonical_json_bytes(derive_freeze_report())
    ok = committed == fresh
    return {
        "schema": "inferswarm.issue237.freeze-fixed-point/1",
        "status": "PASS" if ok else "FAIL",
        "committed_sha256": sha256_bytes(committed),
        "fresh_sha256": sha256_bytes(fresh),
        "byte_identical": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[
        "validate-prerequisites", "validate-methodology", "validate-corpora",
        "validate-holdout-commitment", "freeze", "check",
    ])
    args = parser.parse_args(argv)
    if args.command == "validate-prerequisites":
        result = validate_prerequisites()
    elif args.command == "validate-methodology":
        result = validate_methodology()
    elif args.command == "validate-corpora":
        result = validate_corpora()
    elif args.command == "validate-holdout-commitment":
        result = validate_holdout_commitment()
    elif args.command == "check":
        result = cmd_check()
    else:
        result = cmd_freeze()
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
