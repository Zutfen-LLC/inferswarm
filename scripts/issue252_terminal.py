#!/usr/bin/env python3
"""#252 retrospective retained-byte reducer; prospective Phase-0 code ONLY.

The input is a filesystem tree, not caller-provided verdicts. This does not
execute, dispatch, or certify any physical experiment. Any live-use campaign
must add a separately reviewed producer and independently authenticated live
per-unit dispatch/placement/health custody before treating a synthetic result
as physical authority. No caller boolean selects a terminal.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import issue252_constants as C
import issue252_arms as A
import issue252_physical as P
import issue252_phase0 as P0
import issue250_diagnostic as D

BLOCKED = "R8I3C_REDUCER_BLOCKED_INCOMPLETE"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read(root: Path, rel: str) -> bytes:
    path = root / rel
    if (path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(root.resolve()) is False):
        raise ValueError(f"missing/unsafe retained artifact: {rel}")
    return path.read_bytes()


def _json(root: Path, rel: str) -> dict[str, Any]:
    val = json.loads(_read(root, rel))
    if not isinstance(val, dict):
        raise ValueError(f"retained JSON object missing: {rel}")
    return val


def _authority(root: Path) -> dict[str, Any]:
    doc = _json(root, "authority.json")
    repo = doc.get("repo_root")
    auth = doc.get("dispatch")
    if not isinstance(repo, str) or not isinstance(auth, dict):
        raise ValueError("retained parent/dispatch authority absent")
    accepted = P0.verify_terminalization(Path(repo))
    if (not isinstance(accepted, dict) or accepted.get("terminal") != C.PREDECESSOR_TERMINAL
            or accepted.get("execution_head") != C.ACCEPTED_EXECUTION_HEAD
            or auth.get("parent_terminalization_head") != C.ACCEPTED_TERMINALIZATION_HEAD
            or auth.get("issue_number") != C.ISSUE
            or auth.get("author_association") not in ("OWNER", "MEMBER")
            or not isinstance(auth.get("head_sha"), str) or not P.SHA.fullmatch(auth["head_sha"])
            or auth.get("arm") not in A.ARMS
            or auth.get("namespace") != A.ARMS[auth["arm"]]["namespace"]
            or auth.get("body") != f"{C.DISPATCH_PHRASE_FORMAT}\nhead={auth['head_sha']}\narm={auth['arm']}"
            or auth.get("body_sha256") != _sha(auth["body"].encode())):
        raise ValueError("retained dispatch/parent identity mismatch")
    return auth


def _unit(root: Path, directory: Path, auth: dict[str, Any], idx: int,
          fix: dict[str, Any] | None = None) -> tuple[str, ...]:
    rec = _json(directory, "unit.json")
    P.validate_unit_receipt(rec)
    if (rec.get("authority") != auth or rec.get("unit_index") != idx
            or rec.get("namespace") != A.ARMS[rec["arm"]]["namespace"]
            or rec.get("fix_commit") != (fix["commit"] if fix else None)):
        raise ValueError("unit authority/index/fix mismatch")
    if fix and rec["head_sha"] != fix["dispatch"]["head_sha"]:
        raise ValueError("fix receipt head not authenticated")
    if not fix and rec["head_sha"] != auth["head_sha"]:
        raise ValueError("unit head not authenticated")
    raw = _read(directory, "response.json.raw")
    if _sha(raw) != rec["response_raw_sha256"] or len(raw) != rec["response_raw_bytes"]:
        raise ValueError("raw response bytes mismatch")
    response = json.loads(raw)
    if (not isinstance(response, dict) or not isinstance(response.get("tokens"), list)
            or len(response["tokens"]) != D.DECISIONS
            or any(type(t) is not int for t in response["tokens"])):
        raise ValueError("raw response tokens missing")
    meta = _read(directory, "obs.meta.json")
    if _sha(meta) != rec["observer_meta_sha256"]:
        raise ValueError("observer metadata bytes mismatch")
    metas = [json.loads(line) for line in meta.splitlines() if line.strip()]
    if len(metas) != D.DECISIONS or any(m.get("pos") != i for i, m in enumerate(metas)):
        raise ValueError("observer metadata positions incomplete")
    if _sha(_read(directory, "server.log")) != rec["server_log_sha256"]:
        raise ValueError("server log bytes mismatch")
    for phase in ("pre", "post"):
        if _json(directory, f"identity-{phase}.json") != rec[f"identity_{phase}"]:
            raise ValueError(f"identity {phase} bytes differ from receipt")
    if _json(directory, "placement.json") != rec["placement"]:
        raise ValueError("placement observation differs from receipt")
    digests = []
    for n in range(D.DECISIONS):
        row = _read(directory, f"obs.row{n}.f32")
        if len(row) != D.ROW_BYTES or _sha(row) != rec["observer_rows"][n]:
            raise ValueError("full observer row bytes mismatch")
        digests.append(_sha(row))
    return tuple(digests)


def _population(root: Path, namespace: str, auth: dict[str, Any],
                fix: dict[str, Any] | None = None) -> str:
    base = root / namespace
    if base.is_symlink() or not base.is_dir():
        raise ValueError("required arm namespace absent or symlink")
    arm = auth["arm"]
    planned = [f"case-3072-B-{arm.lower()}-{i:03d}" for i in range(1, 6)]
    entries = list(base.iterdir())
    if any(e.is_symlink() or not e.is_dir() or e.name not in planned for e in entries):
        raise ValueError("unplanned/quarantined or unsafe unit (no cherry-picking)")
    retained = [e.name for e in entries]
    if len(set(retained)) != len(retained):
        raise ValueError("duplicate units")
    rows = {}
    for name in retained:
        rows[name] = _unit(root, base / name, auth, planned.index(name) + 1, fix)
    # Same frozen prefix law as #250: 001..N; stop exactly at first
    # mismatch; 3 matching is a screen, never deterministic.
    facts = D.prefix_population_facts(planned, retained, rows,
            deterministic_required=A.REPEAT_LAW["deterministic_requires"])
    if facts["population"] in ("invalid", "incomplete"):
        raise ValueError("retained prefix incomplete/invalid: " + str(facts.get("invalid") or facts.get("stop_reason")))
    if facts["population"] == "complete_deterministic":
        return "deterministic"
    if facts["population"] == "complete_nondeterministic_prefix":
        return "variable"
    raise ValueError("unknown prefix-law verdict")


def _mechanism(root: Path, arm: str) -> bool:
    """A1 only: retained raw queue-order transition, not a label/boolean.

    These prospective trace bytes require a future observer producer; current
    accepted server logs alone cannot prove this causal boundary. Mere five
    matching rows or an unverified narrative must NOT localize.
    """
    path = root / "mechanism-trace.json"
    if not path.is_file() or path.is_symlink() or arm != "A1":
        return False
    trace = _json(root, "mechanism-trace.json")
    before, after = trace.get("before"), trace.get("after")
    if (trace.get("schema") != "inferswarm.issue252.queue-order-observation/1"
            or not isinstance(before, list) or not isinstance(after, list)
            or len(before) < 2 or len(after) < 2):
        return False
    # Event bytes are parseable only under an independently supplied Vulkan
    # trace seam; synthetic fixtures exercise logic, not physical validity.
    def numbers(events: list[Any]) -> list[int]:
        if any(not isinstance(x, dict) or x.get("event") != "vkQueueSubmit" or
               type(x.get("sequence")) is not int for x in events):
            raise ValueError("malformed Vulkan queue trace")
        return [x["sequence"] for x in events]
    b, a = numbers(before), numbers(after)
    return sorted(b) == sorted(a) and b != sorted(b) and a == sorted(a)


def _fix(root: Path, original: dict[str, Any]) -> dict[str, Any] | None:
    path = root / "fix.json"
    if not path.is_file() or path.is_symlink():
        return None
    fix = _json(root, "fix.json")
    commit, repo, auth = fix.get("commit"), fix.get("repo_root"), fix.get("dispatch")
    if (not isinstance(commit, str) or not P.SHA.fullmatch(commit)
            or not isinstance(repo, str) or not isinstance(auth, dict)
            or auth.get("arm") != original["arm"] or auth.get("namespace") != original["namespace"]
            or auth.get("head_sha") != commit or auth.get("parent_terminalization_head") != C.ACCEPTED_TERMINALIZATION_HEAD
            or auth.get("author_association") not in ("OWNER", "MEMBER")
            or auth.get("body") != f"{C.DISPATCH_PHRASE_FORMAT}\nhead={commit}\narm={auth.get('arm')}"
            or auth.get("body_sha256") != _sha(auth["body"].encode())
            or fix.get("authority_sha256") != _sha(_read(root, "fix-dispatch.json"))
            or _json(root, "fix-dispatch.json") != auth):
        raise ValueError("fix commit not bound to retained dispatch authority")
    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
        if result.returncode:
            raise ValueError("fix commit git object unavailable")
        return result.stdout.strip()
    if git("rev-parse", "HEAD") != commit or git("status", "--porcelain"):
        raise ValueError("fix source tree not clean/current at dispatched commit")
    paths = git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
    if not paths or not any(p.startswith("ggml/src/ggml-vulkan/") and p.endswith(('.cpp', '.glsl')) for p in paths):
        raise ValueError("fix commit contains no Vulkan implementation change")
    diff = git("show", "--format=", "--unified=0", commit, "--", "ggml/src/ggml-vulkan/")
    additions = [line[1:].strip() for line in diff.splitlines()
                 if line.startswith("+") and not line.startswith("+++")]
    if not any(line and not line.startswith(("//", "/*", "*", "#"))
               for line in additions):
        raise ValueError("fix commit contains no Vulkan executable-code addition")
    return fix


def derive_terminal(evidence_root: Path, arms_result: dict[str, Any]) -> str:
    """Return exactly a frozen terminal or BLOCKED; ignore verdict summaries.

    ``arms_result`` is not authority: any nonempty caller verdict/selection
    mapping is refused, so it cannot hide a retained arm or select a winner.
    """
    try:
        root = Path(evidence_root)
        if arms_result != {} or root.is_symlink() or not root.is_dir():
            raise ValueError("caller result or evidence root invalid")
        if A.validate_arms():
            raise ValueError("frozen arms invalid")
        auth = _authority(root)
        namespaces = {spec["namespace"] for spec in A.ARMS.values()}
        present = {p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()}
        expected_dirs = namespaces | ({"fixed"} if (root / "fix.json").is_file() else set())
        if present - expected_dirs or not (present & namespaces):
            raise ValueError("unplanned namespace / no retained arms")
        original_present = present & namespaces
        if auth["namespace"] not in original_present:
            raise ValueError("retained arm lacks dispatch")
        # One dispatch authorizes only its named arm: no extra namespace may
        # be consumed using the authority of another arm.
        if original_present != {auth["namespace"]} and original_present != namespaces:
            raise ValueError("mixed arms require independently retained authorities")
        states = {}
        for arm, spec in A.ARMS.items():
            ns = spec["namespace"]
            if ns not in present:
                continue
            arm_auth = auth if ns == auth["namespace"] else _json(root, f"authority-{arm}.json")
            if arm_auth.get("arm") != arm or arm_auth.get("namespace") != ns or arm_auth.get("head_sha") != auth["head_sha"]:
                raise ValueError("arm-specific dispatch absent/mismatched")
            states[arm] = _population(root, ns, arm_auth)
        corrected = [arm for arm, state in states.items() if state == "deterministic"]
        if len(corrected) > 1:
            raise ValueError("ambiguous multi-factor localization")
        if not corrected:
            if (root / "fix.json").exists():
                raise ValueError("unexplained fix artifact without localized arm")
            if set(states) == set(A.ARMS):
                return C.UNRESOLVED_TERMINAL
            raise ValueError("non-localization needs complete frozen arm set")
        arm = corrected[0]
        if not _mechanism(root, arm):
            raise ValueError("five matching rows alone do not localize a mechanism")
        fix = _fix(root, auth)
        if fix is None:
            return C.NOT_VALIDATED_TERMINAL
        fixed_auth = fix["dispatch"]
        if _population(root, "fixed/" + A.ARMS[arm]["namespace"], fixed_auth, fix) != "deterministic":
            return C.NOT_VALIDATED_TERMINAL
        return C.ACCEPTED_TERMINAL
    except (OSError, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, P0.ReconciliationError, D.DiagnosticError):
        return BLOCKED
