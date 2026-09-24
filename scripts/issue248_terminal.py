"""Fail-closed offline terminal reduction for Issue #248 evidence.

All conclusions are reconstructed from retained unit, response, observer,
identity, and platform-health bytes. Caller-supplied terminal labels, health
summaries, and textual causal-intervention plans are not authorities.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

import issue248_diagnostic as D
import issue248_health as H
import issue248_identity as I

SCHEMA = "inferswarm.issue248.terminal/2"
UNIT_SCHEMA = "inferswarm.issue248.diagnostic-unit/1"
BLOCKED = "R8I3_REDUCER_BLOCKED_INCOMPLETE"
TERMINALS = (
    "R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED",
    "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED",
    "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED",
    "R8I3_REF_NONDETERMINISM_UNRESOLVED",
    "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED",
)
VARIANTS = ("obs-comparator", "obs-dual", "obs-r8e", "obs-off")
FROZEN_PROBE_NAMESPACE = {
    "repeat": "d248-ref-repeats",
    "placement": "d248-placement-rungs",
    "regime": "d248-regime-sweep",
    "observer": "d248-observer-ladder",
    "canonical": "d248-observer-ladder",
}
DECISIONS = 8
ROW_BYTES = 248320 * 4


def _blocked(namespace: str, problems: list[str], probes=None) -> dict[str, Any]:
    return {"schema": SCHEMA, "namespace": namespace, "terminal": None,
            "terminal_vocabulary": list(TERMINALS), "blocked": BLOCKED,
            "complete": False, "problems": problems, "probes": probes or {}}


def _safe_tag(tag: Any) -> bool:
    return (isinstance(tag, str) and re.fullmatch(
        r"case-(?:256|1024|3072|4096)-[BC]-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}", tag
    ) is not None)


def _tag_variant(tag: str, variant: str) -> str:
    match = re.fullmatch(r"(case-(?:256|1024|3072|4096)-[BC])-.+-([0-9]{3})", tag)
    if not match:
        raise ValueError(f"malformed observer unit tag: {tag}")
    return f"{match.group(1)}-{variant}-{match.group(2)}"


def _token_digest(tokens: list[int]) -> str:
    return hashlib.sha256(struct.pack("<8I", *tokens)).hexdigest()


def _expected_kind(tag: str) -> str:
    match = re.fullmatch(
        r"case-(256|1024|3072|4096)-B-(.+)-([0-9]{3})", tag)
    if match is None:
        return ""
    case, variant, _index = match.groups()
    if case == "4096":
        return "regime" if variant == "case4096" else ""
    if variant == "baseline":
        return "repeat" if case == "3072" else ""
    if re.fullmatch(r"ngl(?:1|2|4|6|8)", variant):
        return "rung" if case == "3072" else ""
    if variant == f"regime-{case}":
        return "regime"
    if variant == "canonical":
        return "canonical" if case == "3072" else ""
    if variant in VARIANTS:
        return "observer" if case == "3072" else ""
    return ""


def _unit_health(unit_dir: Path, receipt: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Verify actual platform receipt/artifacts and identity custody per unit."""
    problems: list[str] = []
    findings: list[str] = []
    # Use the same unit-receipt-bound verifier as the producer-facing reducer.
    # A free-standing health file (even with valid internal digests) is not
    # proof that this successful unit actually took custody of those bytes.
    import issue248_physical as P
    bound = P._platform_health(unit_dir.parent, [unit_dir.name])
    if bound is None:
        problems.append("platform health or unit receipt binding invalid")
    else:
        findings.extend(str(x.get("kind", "unknown"))
                        for x in bound["fatal_states"])
    try:
        pre = json.loads((unit_dir / "identity-pre.json").read_bytes())
        post = json.loads((unit_dir / "identity-post.json").read_bytes())
        if not isinstance(pre, dict) or not isinstance(post, dict):
            raise ValueError("identity observations must be objects")
        raw_problems = I.identity_problems("B", pre) + I.identity_problems("B", post)
        if raw_problems:
            problems.extend(f"identity drift in successful-unit receipt: {x}"
                            for x in raw_problems)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        problems.append(f"identity custody invalid: {exc}")
    return problems, findings


def _source(root: Path, spec: dict[str, Any], name: str
            ) -> tuple[Path, str]:
    expected = FROZEN_PROBE_NAMESPACE[name]
    if spec.get("namespace") != expected:
        raise ValueError(f"{name}: frozen namespace must be {expected}")
    base = root / expected
    if base.is_symlink() or not base.is_dir():
        raise ValueError(f"{name}: frozen evidence namespace missing or symlink")
    return base, expected


def _execution_contract(unit_dir: Path, receipt: dict[str, Any],
                        expected_ngl: int, kind: str) -> None:
    """Rebind the retained runtime realization to its frozen probe."""
    import issue248_physical as P
    mode = receipt.get("observer_mode")
    binary_id = ("canonical" if kind == "canonical" else
                 "r8e-obs" if mode == "r8e-only" else "comparator")
    if (receipt.get("binary_id") != binary_id
            or receipt.get("binary_sha256") != D.SERVER_BINARIES[binary_id]):
        raise ValueError("frozen executing binary identity mismatch")
    if receipt.get("model_members_sha256") != D.MODEL_MEMBER_SHA256:
        raise ValueError("complete frozen model member identity mismatch")
    model_dir = receipt.get("model_dir")
    member = receipt.get("model_launch_member")
    if (not isinstance(model_dir, str) or not isinstance(member, str)
            or member != str(Path(model_dir) / D.MODEL_MEMBER_1)):
        raise ValueError("frozen model launch member mismatch")
    contract = receipt.get("request_contract")
    if (not isinstance(contract, dict) or contract != D.REQUEST_CONTRACT
            or D.canonical_request_digest(contract) !=
            receipt.get("request_contract_sha256")):
        raise ValueError("frozen request contract mismatch")
    argv = receipt.get("server_argv")
    if (not isinstance(argv, list) or not argv or
            not isinstance(argv[0], str) or not argv[0]):
        raise ValueError("server argv missing")
    if argv != D.server_argv(Path(argv[0]), Path(member), expected_ngl,
                             P.PORT_BY_ARM["B"]):
        raise ValueError("server argv differs from frozen placement/geometry")
    if mode not in P.OBSERVER_MODES:
        raise ValueError("unknown observer mode")
    identity = I.frozen_identity("B")
    selector = identity["selector"]
    if not isinstance(selector, dict):
        raise ValueError("frozen selector malformed")
    env = D.launch_env(
        "B", icd=identity["icd"],
        selector={str(key): str(value)
                  for key, value in selector.items()},
        observer=("comparator" if mode.startswith("comparator")
                  else "r8e-only"), out_prefix=unit_dir / "obs", force=None,
        r8e_capture=(mode == "comparator-dual"))
    if mode == "comparator-off":
        env = {key: value for key, value in env.items()
               if not key.startswith("LLAMA_OBSERVE")}
    visible = {key: value for key, value in env.items()
               if key.startswith(("LLAMA_", "VK_", "CUDA_"))}
    if receipt.get("server_env") != visible:
        raise ValueError("observer/runtime env differs from frozen probe")
    actual = receipt.get("process_attribution")
    if (not isinstance(actual, dict) or type(actual.get("server_pid")) is not int
            or actual["server_pid"] <= 0
            or actual.get("server_exe_sha256") != D.SERVER_BINARIES[binary_id]
            or actual.get("server_argv") != argv
            or actual.get("server_env") != env):
        raise ValueError("executed process attribution differs from probe contract")


def _plan_has_case4096(plan: dict[str, Any]) -> bool:
    """True when any planned probe population contains case-4096 units."""
    probes = plan.get("probes", {}) if isinstance(plan, dict) else {}
    for spec in probes.values():
        if isinstance(spec, dict):
            units = spec.get("units")
            if isinstance(units, list) and any(
                    isinstance(tag, str) and tag.startswith("case-4096")
                    for tag in units):
                return True
    return False


def _live_case4096_permission(authority: Any,
                              namespace: str) -> tuple[dict[str, Any] | None,
                                                       list[str]]:
    """Re-derive the case-4096 authorization from a LIVE authority payload.

    The payload's precomputed ``case4096`` block is ignored exactly like
    every other caller-supplied summary: the authorization line is parsed
    from the fetched comment body bytes, must be exactly one nonempty
    ``case-4096:<reason>`` line, and the comment must carry exactly one
    ``diagnostic-namespace=`` line scoping it to this reduction. Without
    this live binding a fabricated, internally consistent receipt could
    make unauthorized case-4096 evidence terminal-bearing (the reducer
    cannot trust retained authorization claims about GitHub state).
    """
    if not isinstance(authority, dict):
        return None, ["case-4096 live authority payload is not an object"]
    comment_id = authority.get("comment_id")
    head_sha = authority.get("head_sha")
    body = authority.get("body")
    if (type(comment_id) is not int or not isinstance(head_sha, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
            or not isinstance(body, str)):
        return None, ["case-4096 live authority identity malformed"]
    lines = [ln.strip() for ln in body.splitlines()]
    scope = [ln.split("=", 1)[1] for ln in lines
             if ln.startswith("diagnostic-namespace=")]
    if scope != [namespace]:
        return None, [
            "case-4096 live authority is not bound to this diagnostic namespace"]
    c4096 = [ln for ln in lines if ln.startswith("case-4096:")]
    if len(c4096) != 1:
        return None, [
            "case-4096 live authority lacks exactly one authorization line"]
    reason = c4096[0][len("case-4096:"):].strip()
    if not reason:
        return None, ["case-4096 live authorization line has an empty reason"]
    return {"comment_id": comment_id, "line": c4096[0], "reason": reason,
            "head_sha": head_sha}, []


def _population(root: Path, units: Any, name: str, namespace: str,
                *, require_rows: bool = True,
                case4096_permission: dict[str, Any] | None = None
                ) -> tuple[dict[str, Any], list[str]]:
    facts: list[dict[str, Any]] = []
    problems: list[str] = []
    if (not isinstance(units, list) or not units or
            any(not _safe_tag(u) for u in units) or len(set(units)) != len(units)):
        return {}, [f"{name}: invalid, empty, or duplicate unit plan"]
    for tag in units:
        unit_dir = root / tag
        try:
            if unit_dir.is_symlink() or not unit_dir.is_dir():
                raise ValueError("unit directory missing or symlink")
            receipt = json.loads((unit_dir / "unit.json").read_bytes())
            raw = (unit_dir / "response.json.raw").read_bytes()
            response = json.loads(raw)
            if not isinstance(receipt, dict) or receipt.get("schema") != UNIT_SCHEMA:
                raise ValueError("unit receipt schema mismatch")
            if (receipt.get("tag") != tag or receipt.get("namespace") != namespace
                    or receipt.get("kind") != _expected_kind(tag)):
                raise ValueError("receipt kind/tag/namespace binding mismatch")
            case_match = re.match(r"case-(?:256|1024|3072|4096)", tag)
            if (receipt.get("arm") != "B" or not case_match
                    or receipt.get("case_id") != case_match.group(0)):
                raise ValueError("receipt case/arm binding mismatch")
            if receipt["case_id"] == "case-4096":
                # The retained receipt's authority block is only a claim
                # about GitHub state; the reducer must re-derive the
                # authorization from the LIVE dispatch comment body (the
                # payload's precomputed case4096 block is ignored) and
                # bind it to this exact comment/head/namespace.
                authority = receipt.get("authority")
                permission = authority.get("case4096") if isinstance(authority, dict) else None
                line = permission.get("line") if isinstance(permission, dict) else None
                reason = permission.get("reason") if isinstance(permission, dict) else None
                if (case4096_permission is None
                        or not isinstance(authority, dict) or not isinstance(permission, dict)
                        or type(authority.get("comment_id")) is not int
                        or permission.get("comment_id") != authority.get("comment_id")
                        or authority.get("comment_id") != case4096_permission["comment_id"]
                        or authority.get("head_sha") != case4096_permission["head_sha"]
                        or not isinstance(line, str) or not line.startswith("case-4096:")
                        or not isinstance(reason, str) or not reason.strip()
                        or line != case4096_permission["line"]
                        or reason.strip() != case4096_permission["reason"]):
                    raise ValueError(
                        "case-4096 unit is not bound to a live dispatch "
                        "comment's authorization line for this head")
            rung_match = re.search(r"-ngl(\d+)-", tag)
            expected_ngl = int(rung_match.group(1)) if rung_match else 8
            if receipt.get("ngl") != expected_ngl:
                raise ValueError("receipt ngl does not match frozen tag")
            mode = next((v for v in VARIANTS if f"-{v}-" in tag), None)
            expected_mode = {"obs-comparator": "comparator",
                             "obs-dual": "comparator-dual",
                             "obs-r8e": "r8e-only",
                             "obs-off": "comparator-off"}.get(mode)
            if expected_mode and receipt.get("observer_mode") != expected_mode:
                raise ValueError("observer mode does not match frozen variant")
            _execution_contract(unit_dir, receipt, expected_ngl,
                                _expected_kind(tag))
            tokens = (response.get("tokens", response.get("tokens_predicted"))
                      if isinstance(response, dict) else None)
            if (not isinstance(response, dict)
                    or not isinstance(tokens, list) or len(tokens) != DECISIONS
                    or any(type(t) is not int or t < 0 or t >= 2**32 for t in tokens)
                    or tokens != receipt.get("tokens")):
                raise ValueError("raw and receipt must bind exactly eight integer tokens")
            token_sha = _token_digest(tokens)
            if receipt.get("deterministic_output_sha256") != token_sha:
                raise ValueError("receipt token digest mismatch")
            raw_sha = hashlib.sha256(raw).hexdigest()
            if receipt.get("response_raw_sha256") != raw_sha:
                raise ValueError("raw response digest binding mismatch")
            rows: list[bytes] = []
            row_sha: list[str] = []
            has_rows = (unit_dir / "obs.meta.json").is_file()
            if require_rows and not has_rows:
                raise ValueError("observer rows required for this probe")
            if has_rows:
                meta_raw = (unit_dir / "obs.meta.json").read_bytes()
                if receipt.get("observer_meta_sha256") != hashlib.sha256(meta_raw).hexdigest():
                    raise ValueError("observer metadata digest binding mismatch")
                lines = [line for line in meta_raw.decode("utf-8").splitlines()
                         if line.strip()]
                if len(lines) != DECISIONS:
                    raise ValueError("observer metadata must cover all eight decisions")
                for i, line in enumerate(lines):
                    meta = json.loads(line)
                    if not isinstance(meta, dict) or meta.get("pos") != i:
                        raise ValueError("observer metadata position order mismatch")
                    row = (unit_dir / f"obs.row{i}.f32").read_bytes()
                    if len(row) != ROW_BYTES:
                        raise ValueError("observer row has wrong retained vocabulary width")
                    rows.append(row)
                    row_sha.append(hashlib.sha256(row).hexdigest())
                if receipt.get("observer_rows") != row_sha:
                    raise ValueError("observer row digest binding mismatch")
            elif not ("canonical" in tag or "obs-off" in tag or "obs-r8e" in tag):
                raise ValueError("only canonical/off/r8e-only units may be rowless")
            elif any(unit_dir.glob("obs.row*.f32")):
                raise ValueError("rowless unit contains unbound observer rows")
            r8e: dict[int, bytes] = {}
            for path in unit_dir.glob("*.r8e.pos*.f32"):
                match = re.search(r"\.pos(\d+)\.f32$", path.name)
                if match:
                    pos = int(match.group(1))
                    if pos in r8e:
                        raise ValueError("duplicate r8e position")
                    r8e[pos] = path.read_bytes()
            if mode in ("obs-dual", "obs-r8e"):
                if set(r8e) != {0} or len(r8e[0]) != ROW_BYTES:
                    raise ValueError("R8-E must retain the full position-zero row")
                if receipt.get("r8e_row0_sha256") != hashlib.sha256(r8e[0]).hexdigest():
                    raise ValueError("R8-E row digest binding mismatch")
            elif r8e:
                raise ValueError("unexpected R8-E capture")
            if mode == "obs-dual" and r8e[0] != rows[0]:
                raise ValueError("dual capture rows disagree at position zero")
            hp, fatal = _unit_health(unit_dir, receipt)
            problems.extend(f"{name}/{tag}: {x}" for x in hp)
            facts.append({"tag": tag, "token_sha256": token_sha,
                          "row_sha256": row_sha, "rows": rows, "r8e": r8e,
                          "receipt": receipt, "fatal_findings": fatal})
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError,
                struct.error) as exc:
            problems.append(f"{name}: malformed retained unit {tag}: {exc}")
    return {"units": facts}, problems


def _det(pop: dict[str, Any], key: str) -> bool | None:
    units = pop.get("units", [])
    if not units:
        return None
    values = [tuple(u[key]) if key == "row_sha256" else u[key] for u in units]
    return all(value == values[0] for value in values[1:])


def _validate_phase2_counts(plan: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    probes = plan.get("probes", {})
    repeat = probes.get("repeat")
    repeat_units = repeat.get("units") if isinstance(repeat, dict) else None
    if not isinstance(repeat_units, list) or len(repeat_units) < 5:
        problems.append("repeat probe requires at least five units")
    expected_placement = {
        f"case-3072-B-ngl{rung}-{index:03d}"
        for rung in (1, 2, 4, 6, 8) for index in (1, 2)}
    expected_regime = {
        f"case-{case}-B-regime-{case}-{index:03d}"
        for case in (256, 1024, 3072) for index in (1, 2)}
    optional_4096 = {f"case-4096-B-case4096-{index:03d}"
                     for index in (1, 2)}
    for name, expected in (("placement", expected_placement),
                           ("regime", expected_regime)):
        spec = probes.get(name)
        units = spec.get("units") if isinstance(spec, dict) else None
        if not isinstance(units, list):
            problems.append(f"Phase 2 missing required {name} plan")
            continue
        declared = set(units) if all(isinstance(tag, str) for tag in units) else set()
        if name == "regime" and declared & optional_4096:
            expected = expected | optional_4096
        if len(units) != len(expected) or declared != expected:
            problems.append(f"{name} requires exactly two frozen repeats per level")
    return problems


def _phase2(plan: dict[str, Any], root: Path,
            case4096_permission: dict[str, Any] | None = None
            ) -> tuple[dict[str, Any], list[str]]:
    reduced: dict[str, Any] = {}
    problems = _validate_phase2_counts(plan)
    probes = plan.get("probes", {})
    for name in ("placement", "regime"):
        spec = probes.get(name)
        if not isinstance(spec, dict):
            continue
        try:
            base, probe_namespace = _source(root, spec, name)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        pop, errors = _population(base, spec.get("units"), name, probe_namespace,
                                  case4096_permission=(case4096_permission
                                                       if name == "regime"
                                                       else None))
        reduced[name] = pop
        problems.extend(errors)
        groups: dict[str, list[dict[str, Any]]] = {}
        for unit in pop.get("units", []):
            tag = unit["tag"]
            match = (re.search(r"-ngl(\d+)-", tag) if name == "placement"
                     else re.match(r"case-(\d+)", tag))
            if match is None:
                problems.append(f"{name}: cannot derive contrast level from {tag}")
                continue
            key = match.group(1)
            groups.setdefault(key, []).append(unit)
        expected = ({"1", "2", "4", "6", "8"} if name == "placement"
                    else {"256", "1024", "3072"})
        contrasts = {}
        for key in sorted(expected):
            samples = groups.get(key, [])
            if len(samples) >= 2:
                contrasts[key] = {
                    "token_deterministic": len({u["token_sha256"] for u in samples}) == 1,
                    "row_deterministic": len({tuple(u["row_sha256"]) for u in samples}) == 1,
                }
        reduced[name]["contrasts"] = contrasts
    return reduced, problems


def _observer_cause(reduced: dict[str, Any]) -> bool:
    """No observer-localized claim without a matched row-level control.

    The frozen comparator-off units retain tokens but no rows. The R8-E-only
    units use a different binary and retain only position zero. Thus even
    same-binary comparator-on/off token equality and faithful dual capture
    cannot identify the comparator as the smallest causal factor. The
    approved producer must first gain a reviewed same-binary, single-factor
    row-level contrast; no caller-provided assertion can replace it.
    """
    return False



def _later_probe_variation(reduced: dict[str, Any]) -> bool:
    """Detect contradictory within-condition repeats outside Phase 1."""
    for name in ("placement", "regime"):
        for contrast in reduced.get(name, {}).get("contrasts", {}).values():
            if not contrast["token_deterministic"] or not contrast["row_deterministic"]:
                return True
    for variant in VARIANTS:
        pop = reduced[f"observer:{variant}"]
        if _det(pop, "token_sha256") is False:
            return True
        if variant == "obs-r8e":
            if len({hashlib.sha256(u["r8e"][0]).hexdigest()
                    for u in pop["units"]}) > 1:
                return True
        elif variant != "obs-off" and _det(pop, "row_sha256") is False:
            return True
    return _det(reduced["canonical"], "token_sha256") is False


def derive_terminal(evidence_root: Path, namespace: str, plan: dict[str, Any],
                    *, health_verifier=None,
                    case4096_authority: Any = None) -> dict[str, Any]:
    """Derive a terminal from retained bytes; health_verifier is never trusted.

    Vulkan localization is intentionally unreachable: the frozen producer has
    no validated one-factor Vulkan runtime control. A runtime-initialization
    contrast by itself does not establish Vulkan causality.

    When the plan contains case-4096 units, ``case4096_authority`` must be a
    LIVE dispatch authority payload (fetched by the caller through
    ``D.fetch_dispatch_authority`` at reduction time); its precomputed
    ``case4096`` block is ignored and the authorization is re-parsed from
    the comment body. A retained receipt's own authority block can never
    authorize case-4096 evidence.
    """
    if (not isinstance(namespace, str)
            or not re.fullmatch(r"d248-[a-z0-9][a-z0-9-]*", namespace)
            or "--" in namespace):
        return _blocked(str(namespace), ["invalid diagnostic namespace"])
    if not isinstance(plan, dict) or not isinstance(plan.get("probes"), dict):
        return _blocked(namespace, ["missing frozen plan"])
    probes = plan["probes"]
    required = tuple(FROZEN_PROBE_NAMESPACE)
    missing = [f"missing required Phase-1/2/3 probe: {name}" for name in required
               if not isinstance(probes.get(name), dict)]
    if missing:
        return _blocked(namespace, missing)
    observer_units = probes["observer"].get("units")
    if not isinstance(observer_units, list) or len(observer_units) < 2:
        return _blocked(namespace, ["observer plan requires at least two matched units"])
    root = Path(evidence_root)
    if root.is_symlink() or not root.is_dir():
        return _blocked(namespace, ["evidence root missing or symlink"])
    try:
        sources = {name: _source(root, probes[name], name)
                   for name in required}
        specs: dict[str, Any] = {"repeat": probes["repeat"].get("units"),
                                 "canonical": probes["canonical"].get("units")}
        for variant in VARIANTS:
            specs[f"observer:{variant}"] = [_tag_variant(t, variant) for t in observer_units]
    except (ValueError, TypeError) as exc:
        return _blocked(namespace, [str(exc)])
    reduced: dict[str, Any] = {}
    problems: list[str] = []
    try:
        expected_by_family = {name: set(probes[name]["units"])
                              for name in ("repeat", "placement", "regime", "canonical")}
        expected_by_family["observer"] = {
            _tag_variant(tag, variant)
            for tag in observer_units for variant in VARIANTS}
    except (KeyError, TypeError, ValueError) as exc:
        return _blocked(namespace, [f"malformed frozen unit population: {exc}"])
    for family, (base, _probe_namespace) in sources.items():
        # Canonical and observer share a directory. Quarantined failed
        # attempts remain historical, but no current unit may be silently
        # omitted from the plan to cherry-pick a favorable population.
        expected = set(expected_by_family[family])
        if family in ("observer", "canonical"):
            expected |= expected_by_family["observer"] | expected_by_family["canonical"]
        for candidate in base.iterdir():
            if candidate.name.startswith("case-") and not candidate.name.endswith(
                    "-quarantined") and (candidate.is_dir() or candidate.is_symlink()):
                if candidate.is_symlink() or candidate.name not in expected:
                    problems.append(f"{family}: unplanned or symlinked current unit {candidate.name}")
    for name, units in specs.items():
        family = name.split(":")[0]
        base, probe_namespace = sources[family]
        rowless_allowed = name == "canonical" or name in (
            "observer:obs-off", "observer:obs-r8e")
        pop, errors = _population(base, units, name,
                                  probe_namespace, require_rows=not rowless_allowed)
        reduced[name] = pop
        problems.extend(errors)
    # case-4096 authorization is derived ONLY from the live dispatch
    # comment body supplied at reduction time; a retained receipt's own
    # authority block is a claim, not authority.
    permission, permission_problems = _live_case4096_permission(
        case4096_authority, namespace)
    problems.extend(permission_problems if _plan_has_case4096(plan) else [])
    phase2, phase2_errors = _phase2(plan, root, case4096_permission=permission)
    reduced.update(phase2)
    problems.extend(phase2_errors)
    if problems:
        return _blocked(namespace, problems, reduced)
    repeat = reduced["repeat"]
    token_det = _det(repeat, "token_sha256")
    row_det = _det(repeat, "row_sha256")
    all_units = [unit for pop in reduced.values() for unit in pop.get("units", [])]
    fatal = [item for unit in all_units for item in unit["fatal_findings"]]
    if fatal:
        return {"schema": SCHEMA, "namespace": namespace,
                "terminal": "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED",
                "terminal_vocabulary": list(TERMINALS), "blocked": None,
                "complete": True, "problems": [], "probes": reduced,
                "basis": {"fatal_findings": fatal,
                          "health_source": "verified retained platform-health custody"}}
    observer_localized = _observer_cause(reduced)
    if observer_localized:
        terminal = "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED"
    elif token_det is True and row_det is True and not _later_probe_variation(reduced):
        return {"schema": SCHEMA, "namespace": namespace,
                "terminal": "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED",
                "terminal_vocabulary": list(TERMINALS), "blocked": None,
                "complete": True, "problems": [], "probes": reduced,
                "basis": {"accepted_241_mismatch": "preserved; not reinterpreted",
                          "repeat_tokens_and_rows_deterministic": True}}
    elif (token_det is False or row_det is False
          or _later_probe_variation(reduced)):
        terminal = "R8I3_REF_NONDETERMINISM_UNRESOLVED"
    else:
        return _blocked(namespace, ["repeat determinism is incomplete/ambiguous"], reduced)
    placement = {key: not facts["row_deterministic"]
                 for key, facts in reduced["placement"]["contrasts"].items()}
    regime = {key: not facts["row_deterministic"]
              for key, facts in reduced["regime"]["contrasts"].items()}
    dual = reduced["observer:obs-dual"]["units"]
    independent = reduced["observer:obs-r8e"]["units"]
    observer_independent_varies = len({
        hashlib.sha256(unit["r8e"][0]).hexdigest()
        for unit in independent}) > 1
    return {"schema": SCHEMA, "namespace": namespace, "terminal": terminal,
            "terminal_vocabulary": list(TERMINALS), "blocked": None,
            "complete": True, "problems": [], "probes": reduced,
            "basis": {
                "phase2_complete": True,
                "placement_row_variation_by_ngl": placement,
                "regime_row_variation_by_case": regime,
                "dual_capture_position0_agrees": all(
                    unit["r8e"][0] == unit["rows"][0] for unit in dual),
                "observer_independent_r8e_position0_varies":
                    observer_independent_varies,
                "platform_health_complete_clean": not fatal,
                "causal_limit": (
                    "row variation may be upstream of capture, but the "
                    "frozen probes do not distinguish Vulkan, placement, "
                    "regime, process lifecycle, or observer perturbation")}}
