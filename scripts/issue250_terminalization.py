#!/usr/bin/env python3
"""Additive, authority-bound terminalization of accepted Issue #250 Arm A.

This wrapper preserves issue250_terminal's frozen receipt/provenance validation.
It only translates its exact adjudicated Arm-A stop after authenticating the
retained historical dispatch and both captured maintainer adjudications.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
AUTHORITY_DIR = HERE / "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization"
ORIGINAL_HEAD = "5d015b5bc437bb82d5e966d0da8b90ff44b079a1"
EXPECTED_HEAD = ORIGINAL_HEAD
DISPATCH_ID = 5902614446
DISPATCH_SHA256 = "9b98c73090aec7fcdb72f6933f26c8b6834eef7e11ba3235e6b19d6baf47725a"
AUTHORITY_SHA256 = "c2f79e975b0931af30d2dad22f0e4326e27c1afdf8a11d62a5f0ffe4a7cc5ad2"
PR_ADJUDICATION_ID = 5904093750
PR_ADJUDICATION_SHA256 = "9b5968d27ad81f394945a46b6695dfa8719d985a0807cd41b80f08c6fb45b385"
ISSUE_ADJUDICATION_ID = 5904094070
ISSUE_ADJUDICATION_SHA256 = "8c913e76fae5910152c8eb09a1fc414c0f4a91aa25ba70d67a7bded1559b0e4e"
PREFLIGHT_SHA256 = "1c0504ee9bbebe8f657733cd0fdc7600337b921a69593dcc2de907c25cbb193a"
SOURCE_HEAD = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
SOURCE_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
COMPARATOR_SHA256 = "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad"
DISPATCH_DIGEST = "70843356c497c3537eade2cec7767e56601954cc5fa083a3dce73d37aca5697b"
TERMINAL = "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
FACTOR = "zero↔nonzero Vulkan participation"
STOP = "ARM_A_STOPS_LADDER"

sys.path.insert(0, str(HERE / "scripts"))
import issue250_terminal as frozen  # noqa: E402


def _load(name: str, sha: str, ident: int) -> tuple[bytes, dict[str, Any]]:
    path = AUTHORITY_DIR / name
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError(f"authority byte digest mismatch: {name}")
    obj = json.loads(raw)
    if obj.get("id") != ident or obj.get("author_association") != "MEMBER" or obj.get("user", {}).get("login") != "ezutfen":
        raise ValueError(f"authority semantic identity mismatch: {name}")
    return raw, obj


def captured_dispatch() -> dict[str, Any]:
    raw = (AUTHORITY_DIR / "dispatch-comment.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != DISPATCH_SHA256:
        raise ValueError("historical dispatch capture byte digest mismatch")
    comment = json.loads(raw)
    auth_raw = (AUTHORITY_DIR / "dispatch-authority.json").read_bytes()
    if hashlib.sha256(auth_raw).hexdigest() != AUTHORITY_SHA256:
        raise ValueError("dispatch authority byte digest mismatch")
    auth = json.loads(auth_raw)
    body = "R8I3B PHYSICAL DISPATCH #250\nhead=" + EXPECTED_HEAD + "\ndiagnostic-namespace=d250-arm-a\narm=A-vulkan-necessity"
    if (comment.get("id") != DISPATCH_ID or comment.get("user", {}).get("login") != "ezutfen"
            or comment.get("author_association") != "MEMBER" or comment.get("body") != body
            or auth.get("comment_id") != DISPATCH_ID or auth.get("head_sha") != EXPECTED_HEAD
            or auth.get("namespace") != "d250-arm-a" or auth.get("arm") != "A-vulkan-necessity"
            or auth.get("body") != body or auth.get("issue_open") is not True or auth.get("open_pr") is not True
            or frozen.D.authority_digest(auth) != DISPATCH_DIGEST):
        raise ValueError("historical dispatch semantic binding mismatch")
    return frozen.D.validate_authority_payload(auth, EXPECTED_HEAD)


def verify_source_build(evidence_root: Path) -> dict[str, Any]:
    path = Path(evidence_root) / "preflight-complete.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PREFLIGHT_SHA256:
        raise ValueError("retained source/build preflight digest mismatch")
    doc = json.loads(raw)
    source = doc.get("source_build")
    if (not isinstance(source, dict) or source.get("status") != "PASS"
            or source.get("mode") != "NONPHYSICAL"
            or source.get("physical_units_attempted") != 0
            or source.get("source_head") != SOURCE_HEAD
            or source.get("source_tree") != SOURCE_TREE
            or source.get("binary_sha256") != COMPARATOR_SHA256
            or doc.get("head") != ORIGINAL_HEAD):
        raise ValueError("retained source/build preflight semantic mismatch")
    libs = source.get("observer_libraries")
    if not isinstance(libs, dict) or len(libs) != 8 or any(
            not isinstance(v, dict) or not re.fullmatch(r"[0-9a-f]{64}", v.get("sha256", ""))
            for v in libs.values()):
        raise ValueError("retained observer-library custody malformed")
    return source


def validate_adjudications() -> None:
    _, pr = _load("adjudication-pr-251.json", PR_ADJUDICATION_SHA256, PR_ADJUDICATION_ID)
    _, issue = _load("adjudication-issue-250.json", ISSUE_ADJUDICATION_SHA256, ISSUE_ADJUDICATION_ID)
    for item, issue_no in ((pr, 251), (issue, 250)):
        if item.get("issue_url") != f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{issue_no}":
            raise ValueError("adjudication repository/issue mismatch")
        body = item.get("body", "")
        for required in (ORIGINAL_HEAD, "ACCEPTED. STOP THE PHYSICAL LADDER.", "zero and nonzero Vulkan participation", "not** Vulkan", "No Arm B/C/C1/C2/D", TERMINAL):
            if required not in body:
                raise ValueError(f"adjudication lacks required ruling: {required}")
    if pr["body"] != issue["body"]:
        raise ValueError("PR and issue adjudications disagree")


def derive(evidence_root: Path, *, contrast_root: Path, repo_root: Path,
           authority_fetcher: Any = None, github_api: str = "https://api.github.com") -> dict[str, Any]:
    """Revalidate accepted Arm-A retained bytes, then derive the authorized terminal."""
    try:
        validate_adjudications()
        source_build = verify_source_build(Path(evidence_root))
        dispatch = captured_dispatch()
        def fetch(root, head, namespace, github_api=None):
            if namespace != "d250-arm-a" or head != EXPECTED_HEAD:
                raise ValueError("unexpected namespace/head authority request")
            if authority_fetcher is not None:
                supplied = authority_fetcher(root, head, namespace, github_api)
                if supplied != dispatch:
                    raise ValueError("injected authority differs from captured dispatch")
            return dispatch
        result = frozen.derive_terminal(
            evidence_root=Path(evidence_root), expected_head=EXPECTED_HEAD,
            repo_root=Path(repo_root), authority_fetcher=fetch,
            contrast_root=Path(contrast_root), github_api=github_api)
        if result.get("terminal") is not None:
            return {"status": "BLOCKED", "terminal": None,
                    "problems": ["frozen reducer reached a terminal outside adjudicated Arm-A stop"],
                    "frozen_result": result}
        problems = result.get("problems", [])
        arms = result.get("arms", {})
        arm = arms.get("A-vulkan-necessity") or {}
        cpu = arm.get("cpu_only_devnone") or {}
        units = arm.get("units", [])
        vectors = [u.get("row_sha256") for u in units]
        if (problems != [frozen.ARM_A_STOPS_LADDER] or arm.get("reachability_source") != "arm-a-bridge"
                or cpu.get("population") != "complete_deterministic"
                or cpu.get("deterministic") is not True
                or cpu.get("nondeterministic") is not False
                or cpu.get("invalid") is not None
                or cpu.get("n") != 5 or len(units) != 5
                or any(not isinstance(v, list) or len(v) != 8 for v in vectors)
                or any(v != vectors[0] for v in vectors[1:])
                or arm.get("contrast", {}).get("row_deterministic") is not False):
            return {"status": "BLOCKED", "terminal": None,
                    "problems": ["retained evidence did not derive the exact authorized deterministic-A/variable-contrast stop"],
                    "frozen_result": result}
        return {"status": "TERMINAL", "terminal": TERMINAL,
                "localized_factor": FACTOR, "source_build": source_build,
                "interpretation": (
                    "Vulkan participation is a necessary boundary for the observed "
                    "fresh-process case-3072 nondeterminism under the frozen accepted "
                    "runtime/model/request conditions because the zero-Vulkan control "
                    "is deterministic while the accepted nonzero-Vulkan condition is "
                    "variable. Necessary runtime/execution boundary only; "
                    "not a Vulkan, driver, device, kernel, vendor, or mechanism "
                    "root-cause claim. Implementation fix below this boundary "
                    "remains unlocalized."),
                "predecessor_disposition": STOP,
                "implementation_fix_localized": False,
                "later_arms_required": False,
                "further_physical_work_authorized": False,
                "later_arms_authorized": False, "frozen_result": result,
                "authority": {"dispatch_comment_id": DISPATCH_ID,
                              "pr_adjudication_id": PR_ADJUDICATION_ID,
                              "issue_adjudication_id": ISSUE_ADJUDICATION_ID}}
    except Exception as exc:
        return {"status": "BLOCKED", "terminal": None,
                "problems": [f"terminalization authority/evidence rejected: {type(exc).__name__}: {exc}"]}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--contrast-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=HERE)
    args = parser.parse_args()
    out = derive(args.evidence_root, contrast_root=args.contrast_root, repo_root=args.repo_root)
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out.get("terminal") == TERMINAL else 2

if __name__ == "__main__":
    raise SystemExit(main())
