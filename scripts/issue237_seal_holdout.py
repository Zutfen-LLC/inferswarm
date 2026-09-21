#!/usr/bin/env python3
"""Create the R8-I sealed holdout: CMS-seal + public commitment + custody.

Runs ONCE on the sealing host. Reads the plaintext holdout from outside the
repository, seals it to a fresh RSA-3072 recipient certificate with OpenSSL
CMS, and emits ONLY public artifacts:

- sealed/holdout.cms            (ciphertext; single-use)
- sealed/recipient-certificate.pem
- manifests/sealed-holdout-commitment.json (public identity of every draw:
  case_id/content_class/length_regime/token_count + prompt/token hashes —
  no plaintext)
- manifests/holdout-custody-record.json   (custody; no private material)

The private key and the secret seed NEVER enter the repository. No decrypt
is performed (structural CMS checks only). Fresh secret seed comes from
CSPRNG; the fresh RSA keypair is generated here and the private key written
only to an operator-nominated path OUTSIDE the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"

SEALED_NOT_CONSUMED = "SEALED_NOT_CONSUMED"
SEALED_CUSTODY_INCOMPLETE = "SEALED_CUSTODY_INCOMPLETE"


class SealError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], *, what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SealError(f"{what} failed: {proc.stderr.strip()[:300]}")
    return proc


def generate_keypair(key_dir: Path) -> tuple[Path, Path]:
    key_dir.mkdir(parents=True, exist_ok=True)
    private = key_dir / "r8i-holdout-recipient.key"
    certificate = key_dir / "r8i-holdout-recipient.crt"
    if private.exists() or certificate.exists():
        raise SealError("refusing to overwrite an existing holdout keypair")
    run(
        ["openssl", "req", "-x509", "-newkey", "rsa:3072", "-keyout", str(private),
         "-out", str(certificate), "-days", "3650", "-nodes",
         "-subj", "/CN=inferswarm-r8i-qwen38-vulkan-holdout"],
        what="recipient keypair generation",
    )
    return private, certificate


def seal(plaintext: Path, certificate: Path, out_cms: Path) -> None:
    run(
        ["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc",
         "-in", str(plaintext), "-out", str(out_cms), str(certificate)],
        what="CMS encryption of the holdout",
    )
    # structural check only — NO decrypt
    run(
        ["openssl", "cms", "-cmsout", "-print", "-in", str(out_cms)],
        what="CMS structure validation",
    )


def build_commitment(holdout: dict[str, Any], ciphertext: Path,
                     certificate: Path, secret_seed_sha: str,
                     state: str, generator_sha: str) -> dict[str, Any]:
    if holdout.get("schema") != m.HOLDOUT_PLAINTEXT_SCHEMA:
        raise SealError("holdout plaintext schema mismatch")
    cases = holdout.get("cases", [])
    if len(cases) != m.HOLDOUT_CASES:
        raise SealError(f"holdout must contain exactly {m.HOLDOUT_CASES} cases")
    valid_classes = set(m.CONTENT_CLASSES)
    valid_regimes = {tuple(r) for r in m.LENGTH_REGIMES}
    draws = []
    seen: set[str] = set()
    for row in cases:
        case_id = row["case_id"]
        if case_id in seen or not case_id.startswith("h237-"):
            raise SealError("duplicate or malformed holdout case id")
        if (row["content_class"] not in valid_classes
                or tuple(row["length_regime"]) not in valid_regimes):
            raise SealError("holdout case outside the frozen mixture population")
        seen.add(case_id)
        draws.append(
            {
                "case_id": case_id,
                "draw_index": row["draw_index"],
                "content_class": row["content_class"],
                "length_regime": row["length_regime"],
                "token_count": row["token_count"],
                "prompt_sha256": row["prompt_sha256"],
                "token_ids_sha256": row["token_ids_sha256"],
                "case_sha256": row["case_sha256"],
                "historical_rejection_attempt": row["historical_rejection_attempt"],
            }
        )
    if len(seen) != m.HOLDOUT_CASES:
        raise SealError("holdout identities are not all distinct")
    return {
        "schema": m.HOLDOUT_COMMITMENT_SCHEMA,
        "contract_id": m.CONTRACT_ID,
        "state": state,
        "case_count": m.HOLDOUT_CASES,
        "cipher": "CMS AES-256-CBC to RSA-3072 recipient",
        "ciphertext_sha256": sha256_file(ciphertext),
        "recipient_certificate_sha256": sha256_file(certificate),
        "secret_seed_sha256": secret_seed_sha,
        "draws": draws,
        "generator": "scripts/issue237_generate_corpora.py",
        "generator_sha256": generator_sha,
        "unseal_rule": (
            "single-use; the future physical campaign may open it only after "
            "(1) complete valid calibration evidence, (2) mechanically "
            "derived numerical limits, (3) committed frozen threshold/"
            "contract artifacts, (4) maintainer unseal authorization. No "
            "decrypt occurs in issue #237."
        ),
        "plaintext_retention": "sealing host only; never committed",
    }


def build_custody(state: str, custodians: list[dict[str, Any]],
                  secret_seed_sha: str) -> dict[str, Any]:
    return {
        "schema": m.HOLDOUT_CUSTODY_SCHEMA,
        "contract_id": m.CONTRACT_ID,
        "holdout_state": state,
        "unseal_authorized": False,
        "private_key_in_git": False,
        "secret_seed_in_git": False,
        "custodians": custodians,
        "secret_seed_sha256": secret_seed_sha,
        "note": (
            "Fail-closed custody: unless at least two independently verified "
            "custodian copies of the recipient private key + secret seed "
            "exist, the state stays SEALED_CUSTODY_INCOMPLETE and no unseal "
            "preflight may proceed."
        ),
    }


def custody_is_satisfied(record: dict[str, Any]) -> bool:
    if record.get("holdout_state") != SEALED_NOT_CONSUMED:
        return False
    custodians = record.get("custodians", [])
    verified = [c for c in custodians if c.get("verified")]
    return len(verified) >= 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plaintext-holdout", required=True, type=Path,
                        help="plaintext holdout JSON OUTSIDE the repository")
    parser.add_argument("--secret-seed-file", required=True, type=Path,
                        help="secret seed file OUTSIDE the repository")
    parser.add_argument("--private-key-dir", required=True, type=Path,
                        help="directory OUTSIDE the repo for the new keypair")
    parser.add_argument("--custodian-label", default="local-sealing-host")
    args = parser.parse_args(argv)

    for label, path in (
        ("plaintext holdout", args.plaintext_holdout),
        ("secret seed", args.secret_seed_file),
        ("private key dir", args.private_key_dir),
    ):
        try:
            path.resolve().relative_to(REPO)
        except ValueError:
            continue
        raise SealError(f"{label} path must be OUTSIDE the repository")

    holdout = json.loads(args.plaintext_holdout.read_text())
    secret_seed = args.secret_seed_file.read_text(encoding="utf-8").strip()
    if sha256_bytes(secret_seed.encode()) != holdout.get("secret_seed_sha256"):
        raise SealError("secret seed does not match the holdout record")

    generator = REPO / "scripts/issue237_generate_corpora.py"
    private, certificate = generate_keypair(args.private_key_dir)
    out_cms = DOCS / "sealed/holdout.cms"
    out_cert = DOCS / "sealed/recipient-certificate.pem"
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "sealed").mkdir(exist_ok=True)
    seal(args.plaintext_holdout, certificate, out_cms)
    out_cert.write_bytes(certificate.read_bytes())

    commitment = build_commitment(
        holdout, out_cms, out_cert,
        sha256_bytes(secret_seed.encode()),
        SEALED_CUSTODY_INCOMPLETE,
        sha256_file(generator),
    )
    (DOCS / "manifests").mkdir(exist_ok=True)
    (DOCS / "manifests/sealed-holdout-commitment.json").write_bytes(
        canonical_json_bytes(commitment)
    )
    custody = build_custody(
        SEALED_CUSTODY_INCOMPLETE,
        [
            {
                "label": args.custodian_label,
                "holds": ["recipient private key", "secret seed"],
                "verified": False,
            }
        ],
        sha256_bytes(secret_seed.encode()),
    )
    (DOCS / "manifests/holdout-custody-record.json").write_bytes(
        canonical_json_bytes(custody)
    )
    print(
        json.dumps(
            {
                "sealed": True,
                "ciphertext_sha256": commitment["ciphertext_sha256"],
                "state": commitment["state"],
                "case_count": commitment["case_count"],
                "decrypt_performed": False,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
