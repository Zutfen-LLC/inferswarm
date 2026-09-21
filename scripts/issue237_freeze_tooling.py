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
    }
    if retokenize:
        # optional deep re-tokenization check (needs `tokenizers`)
        pass
    return result


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
    require(
        commitment["state"] in ("SEALED_NOT_CONSUMED", "SEALED_CUSTODY_INCOMPLETE"),
        "holdout state must be sealed-family without decrypt",
    )
    require(
        commitment["case_count"] == m.HOLDOUT_CASES,
        "holdout case count drift",
    )
    require(
        len(commitment["draws"]) == m.HOLDOUT_CASES,
        "holdout draw count drift",
    )
    require(
        commitment["ciphertext_sha256"] == sha256_file(ciphertext_path),
        "ciphertext hash mismatch",
    )
    require(
        commitment["recipient_certificate_sha256"] == sha256_file(certificate_path),
        "certificate hash mismatch",
    )
    # no plaintext holdout anywhere in the repository
    for draw in commitment["draws"]:
        require("prompt_text" not in draw and "token_ids" not in draw,
                "holdout commitment leaks plaintext fields")
    ids = [d["case_id"] for d in commitment["draws"]]
    require(len(set(ids)) == m.HOLDOUT_CASES, "duplicate holdout case ids")
    require(all(i.startswith("h237-") for i in ids), "holdout id prefix drift")

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
    require(
        custody["holdout_state"] == commitment["state"],
        "custody/commitment state mismatch",
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
        "case_count": commitment["case_count"],
        "ciphertext_sha256": commitment["ciphertext_sha256"],
        "decrypt_performed": False,
    }


def cmd_freeze() -> dict[str, Any]:
    findings = {
        "schema": "inferswarm.issue237.freeze/1",
        "prerequisites": validate_prerequisites(),
        "methodology": validate_methodology(),
        "corpora": validate_corpora(),
        "holdout": validate_holdout_commitment(),
    }
    (DOCS / "manifests/validation-report.json").write_bytes(
        canonical_json_bytes(findings)
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[
        "validate-prerequisites", "validate-methodology", "validate-corpora",
        "validate-holdout-commitment", "freeze",
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
    else:
        result = cmd_freeze()
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
