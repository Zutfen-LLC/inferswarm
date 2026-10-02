#!/usr/bin/env python3
"""#252 retrospective retained-byte reducer; prospective Phase-0 code ONLY.

The input is a filesystem tree, not caller-provided verdicts. This does not
execute, dispatch, or certify any physical experiment. Any live-use campaign
must add a separately reviewed producer and independently authenticated live
per-unit dispatch/placement/health custody before treating a synthetic result
as physical authority. No caller boolean selects a terminal.

Retained dispatch authority is RETRIEVAL-BOUND (issue252_capture): the
reducer admits an arm's authority only from a retained, digest-bound capture
whose immutable comment is independently re-fetched by exact ID and compared
byte-for-byte. A locally fabricated, merely self-consistent authority object
can never satisfy admission. Live PR/issue state is authenticated against the
RETAINED execution-time snapshot only — terminal derivation never depends on
mutable current GitHub state.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue252_constants as C
import issue252_arms as A
import issue252_physical as P
import issue252_phase0 as P0
import issue252_capture as CAP
import issue252_mechanism as M
import issue250_diagnostic as D
import issue258_theorem as TH

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


def _authority(root: Path, rel: str) -> dict[str, Any]:
    """Admit retained dispatch authority ONLY through capture verification.

    ``rel`` holds {"repo_root": ..., "dispatch_capture": {...}}. The capture
    is authenticated by CAP.verify_capture (schema /2, merged Phase-0
    campaign) or, additively, by the #254 live-producer capture verifier
    (schema /3): structural law PLUS independent re-fetch of the immutable
    comment by exact ID with byte equality — through the PRODUCTION GitHub
    HTTPS seam only; this function has no fetch parameter, so no caller can
    supply an authority fetcher. The legacy path — trusting a
    self-consistent dispatch dict — is gone.
    """
    doc = _json(root, rel)
    repo = doc.get("repo_root")
    capture = doc.get("dispatch_capture")
    if not isinstance(repo, str) or not isinstance(capture, dict):
        raise ValueError("retained parent/dispatch capture absent")
    accepted = P0.verify_terminalization(Path(repo))
    if (not isinstance(accepted, dict) or accepted.get("terminal") != C.PREDECESSOR_TERMINAL
            or accepted.get("execution_head") != C.ACCEPTED_EXECUTION_HEAD):
        raise ValueError("retained parent terminalization unauthenticated")
    if capture.get("schema") == "inferswarm.issue254.dispatch-capture/3":
        # Additive #254 live-producer capture: re-fetched by exact ID
        # through the production seam by its own verifier.
        import issue254_producer as PR254
        verified = PR254.verify_live_capture(capture)
    else:
        verified = CAP.verify_capture(capture, repo_pr_number=C.CAMPAIGN_PR)
    if (verified.get("parent_terminalization_head", C.ACCEPTED_TERMINALIZATION_HEAD) != (
            C.ACCEPTED_TERMINALIZATION_HEAD)):
        raise ValueError("retained capture parent terminalization mismatch")
    return verified


def _repo_root_of(root: Path, rel: str) -> Path:
    """Repo root retained in an authority document (verified path)."""
    repo = _json(root, rel).get("repo_root")
    if not isinstance(repo, str) or not repo:
        raise ValueError("authority document repo_root missing")
    return Path(repo)


def _unit(root: Path, directory: Path, auth: dict[str, Any], idx: int,
          fix: dict[str, Any] | None = None,
          repo_root: Path | None = None) -> tuple[str, ...]:
    rec = _json(directory, "unit.json")
    P.validate_unit_receipt(rec)
    if (rec.get("authority") != auth or rec.get("unit_index") != idx
            or rec.get("namespace") != A.ARMS[rec["arm"]]["namespace"]
            or rec.get("fix_commit") != (fix["commit"] if fix else None)):
        raise ValueError("unit authority/index/fix mismatch")
    head = fix["dispatch_capture"]["head_sha"] if fix else auth["head_sha"]
    if rec["head_sha"] != head:
        raise ValueError("unit head not authenticated")
    # #254 producer custody: a unit retained under a live-producer capture
    # (schema /3) is physical evidence ONLY with a valid producer
    # attestation that re-binds to every retained byte. A hand-built,
    # internally consistent unit tree without producer execution is
    # refused as physical authority right here (adversarial matrix #17).
    if auth.get("schema") == "inferswarm.issue254.dispatch-capture/3":
        import issue254_producer as PR254
        try:
            # Round-3 prompt binding (#254): the attested execution-payload
            # digest must equal the digest independently derived from the
            # accepted fixture authority at the authority document's own
            # retained repo_root (no second configuration source).
            PR254.verify_unit_producer_binding(
                directory, rec, head, repo_root=repo_root)
        except PR254.ProducerError as exc:
            raise ValueError(
                f"unit lacks producer-authenticated physical custody: "
                f"{exc}") from exc
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
                fix: dict[str, Any] | None = None,
                repo_root: Path | None = None) -> str:
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
        rows[name] = _unit(root, base / name, auth, planned.index(name) + 1,
                           fix, repo_root)
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


def _vulkan_participation_active(root: Path, namespace: str) -> bool:
    """Fixed-run proof that intended Vulkan participation remains active.

    Every retained fixed unit's server log must carry the backend's device
    enumeration line (the same seam the mechanism contracts use), proving the
    corrected run still executed on the Vulkan path rather than silently
    falling back to a non-Vulkan backend.
    """
    base = root / namespace
    if base.is_symlink() or not base.is_dir():
        return False
    for unit in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
        log = (unit / "server.log")
        if log.is_symlink() or not log.is_file():
            return False
        try:
            text = log.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return False
        # The exact device-enumeration line (same full-line law as the
        # mechanism contracts) — arbitrary text containing the two markers
        # is not evidence of Vulkan participation — and exactly ONE per
        # unit: the frozen one-device launch emits a single enumeration
        # line, so multiple lines are doctored/unrelated-context copies.
        enum_lines = [line for line in text.splitlines()
                      if M.ENUM_LINE.match(line)]
        if len(enum_lines) != 1:
            return False
    return True


def _fix(root: Path, original: dict[str, Any]) -> dict[str, Any] | None:
    path = root / "fix.json"
    if not path.is_file() or path.is_symlink():
        return None
    fix = _json(root, "fix.json")
    commit, repo = fix.get("commit"), fix.get("repo_root")
    capture = fix.get("dispatch_capture")
    if (not isinstance(commit, str) or not P.SHA.fullmatch(commit)
            or not isinstance(repo, str) or not isinstance(capture, dict)):
        raise ValueError("fix commit not bound to retained dispatch authority")
    # Retained raw capture bytes are separately pinned by SHA-256 custody.
    if fix.get("authority_sha256") != _sha(_read(root, "fix-dispatch.json")):
        raise ValueError("fix retained capture custody digest mismatch")
    if _json(root, "fix-dispatch.json") != capture:
        raise ValueError("fix retained capture bytes differ from fix.json")
    # Prospective fix dispatch authority is held to the SAME retrieval-bound
    # custody contract as the original arm dispatch: retained capture plus
    # independent re-fetch of the immutable comment by exact ID.
    verified = CAP.verify_capture(capture, repo_pr_number=C.CAMPAIGN_PR)
    if (verified["arm"] != original["arm"]
            or verified["namespace"] != original["namespace"]
            or verified["head_sha"] != commit):
        raise ValueError("fix dispatch capture arm/namespace/head mismatch")
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
    return {"commit": commit, "dispatch_capture": verified, "repo_root": repo}


def derive_terminal(evidence_root: Path, arms_result: dict[str, Any]) -> str:
    """Return exactly a frozen terminal or BLOCKED; ignore verdict summaries.

    ``arms_result`` is not authority: any nonempty caller verdict/selection
    mapping is refused, so it cannot hide a retained arm or select a winner.
    Authority re-fetch happens ONLY through the production GitHub HTTPS seam
    (issue252_physical.fetch_dispatch_comment); this public API has NO
    fetch parameter and NO test flag — a caller-supplied fetcher is
    structurally unrepresentable, not merely rejected at runtime (round-4
    adversarial review: a reducer-invocation controller must not be able to
    enable an offline authority mode with one boolean). Terminal derivation
    depends only on retained bytes plus immutable comment re-fetches —
    never on mutable current PR/issue state.
    """
    try:
        root = Path(evidence_root)
        if arms_result != {} or root.is_symlink() or not root.is_dir():
            raise ValueError("caller result or evidence root invalid")
        if A.validate_arms():
            raise ValueError("frozen arms invalid")
        auth = _authority(root, "authority.json")
        # Round-3 prompt binding (#254): the repo root retained in the
        # authority document is the single configuration source the /3
        # reducer path uses to re-derive the expected case-3072 payload
        # digest (accepted request contract + frozen fixture prompt).
        repo_root = _repo_root_of(root, "authority.json")
        namespaces = {spec["namespace"] for spec in A.ARMS.values()}
        present = {p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()}
        expected_dirs = namespaces | ({"fixed"} if (root / "fix.json").is_file() else set())
        if present - expected_dirs or not (present & namespaces):
            raise ValueError("unplanned namespace / no retained arms")
        original_present = present & namespaces
        if auth["namespace"] not in original_present:
            raise ValueError("retained arm lacks dispatch")
        # One dispatch authorizes only its named arm: every ADDITIONAL
        # retained namespace is consumed only through its own
        # independently retained, re-verified arm-specific dispatch
        # authority (authority-<arm>.json below). The old requirement
        # that a multi-arm tree contain the COMPLETE named arm set is
        # withdrawn (AMENDMENT-006 #258): partial multi-arm trees are
        # legal evidence; terminal semantics handle coverage.
        states = {}
        for arm, spec in A.ARMS.items():
            ns = spec["namespace"]
            if ns not in present:
                continue
            if ns == auth["namespace"]:
                arm_auth = auth
                arm_repo_root = repo_root
            else:
                arm_auth = _authority(root, f"authority-{arm}.json")
                if (arm_auth.get("arm") != arm or arm_auth.get("namespace") != ns
                        or arm_auth.get("head_sha") != auth["head_sha"]):
                    raise ValueError("arm-specific dispatch absent/mismatched")
                arm_repo_root = _repo_root_of(root, f"authority-{arm}.json")
            states[arm] = _population(root, ns, arm_auth, repo_root=arm_repo_root)
        # Custody/mechanism-law gate (AMENDMENT-006): every retained arm
        # that HAS a frozen retained-observation law must satisfy it,
        # regardless of terminal capability — a stream violating its
        # arm's law (forged markers, one-factor violation, dead-control
        # proof) is inadmissible evidence and blocks the whole reduction.
        # Terminal capability governs only localization eligibility and
        # non-localization coverage counting, never custody admission.
        # Correction round 3 (#258 review): the gate consults the
        # RETAINED_OBSERVATION_LAWS registry — the custody/observation
        # law set (A2/A3/A5) — NOT the localization-capability registry
        # (A2/A3). Keying custody to capability membership silently
        # dropped A5 validation when #258 correctly removed A5 from the
        # capable set: malformed retained A5 evidence reduced to
        # UNRESOLVED without its frozen observation law (_mechanism_a5)
        # ever being consulted. The two laws are mechanically
        # independent: A5 remains nonterminal with zero localization
        # authority while its retained-observation law is still
        # production-enforced.
        for arm in states:
            if arm in M.RETAINED_OBSERVATION_LAWS:
                M.retained_observation_status(root, arm, A.ARMS[arm]["namespace"])
        # AMENDMENT-006 (#258): terminal capability is explicit per arm
        # (issue258_theorem.TERMINAL_CAPABLE), never inferred from arm
        # existence or evidence presence. Nonterminal/dead arms can never
        # localize and are never required for terminal completion; a
        # physically executed nonterminal arm gains no authority.
        corrected = [arm for arm, state in states.items()
                     if state == "deterministic" and TH.terminal_capable(arm)]
        if len(corrected) > 1:
            raise ValueError("ambiguous multi-factor localization")
        if not corrected:
            if (root / "fix.json").exists():
                raise ValueError("unexplained fix artifact without localized arm")
            # Honest non-localization-family terminal. LOCALIZED requires a
            # capable arm above; the non-localization family now splits:
            # NON_LOCALIZED only when every frozen hypothesis class with a
            # discriminator arm is covered by a terminal-capable arm AND
            # every capable arm produced an admissible variable population;
            # UNRESOLVED otherwise (coverage absent/incomplete, no capable
            # arm admitted, or only nonterminal arms executed). The old
            # complete-named-arm-set condition is withdrawn (AMENDMENT-006).
            if states and TH.hypothesis_coverage()["covered"]:
                required = TH.required_arms()
                if all(states.get(arm) == "variable" for arm in required):
                    return C.NON_LOCALIZED_TERMINAL
            if states:
                return C.UNRESOLVED_TERMINAL
            raise ValueError("no retained arms")
        arm = corrected[0]
        # Five identical rows establish deterministic behavior under the arm;
        # the bounded mechanism/discriminator claimed by the arm needs its own
        # prospective retained observations (issue252_mechanism), kept
        # strictly separate from the determinism contrast.
        status = M.mechanism_status(root, arm, A.ARMS[arm]["namespace"])
        if not status["capable"]:
            # Non-terminal-capable arm (A1/A4/A5 at this pin): deterministic
            # contrast alone cannot localize a bounded mechanism. Honest
            # UNRESOLVED under AMENDMENT-006 (#258) — never a localized
            # terminal through an incapable arm.
            if (root / "fix.json").exists():
                raise ValueError("unexplained fix artifact without localized arm")
            return C.UNRESOLVED_TERMINAL
        fix = _fix(root, auth)
        if fix is None:
            return C.NOT_VALIDATED_TERMINAL
        fixed_ns = "fixed/" + A.ARMS[arm]["namespace"]
        if _population(root, fixed_ns, fix["dispatch_capture"], fix) != "deterministic":
            return C.NOT_VALIDATED_TERMINAL
        if not _vulkan_participation_active(root, fixed_ns):
            return C.NOT_VALIDATED_TERMINAL
        return C.ACCEPTED_TERMINAL
    except (OSError, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, P0.ReconciliationError, D.DiagnosticError,
            CAP.CaptureInvalid, M.MechanismInvalid):
        return BLOCKED
