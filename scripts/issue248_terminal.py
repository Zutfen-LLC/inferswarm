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
                        expected_ngl: int, kind: str, *,
                        root_attestation_digest: str | None = None,
                        root_attestation_members: dict | None = None,
                        ) -> None:
    """Rebind the retained runtime realization to its frozen probe.

    The campaign model attestation context (opening digest + per-member
    attested stats) is required — see derive_terminal, which loads and
    validates the retained opening/closing attestation receipts before
    any population is admitted.
    """
    import issue248_physical as P
    if (root_attestation_digest is None
            or root_attestation_members is None):
        raise ValueError("campaign model attestation context missing")
    mode = receipt.get("observer_mode")
    binary_id = ("canonical" if kind == "canonical" else
                 "r8e-obs" if mode == "r8e-only" else "comparator")
    if (receipt.get("binary_id") != binary_id
            or receipt.get("binary_sha256") != D.SERVER_BINARIES[binary_id]):
        raise ValueError("frozen executing binary identity mismatch")
    # Campaign-level model attestation (2026-09-25): every unit binds
    # the campaign opening attestation digest and carries the stat
    # witness observed immediately before its launch; the per-unit
    # full member hash map (old contract) is no longer a unit field.
    attestation_digest = receipt.get("model_attestation_sha256")
    if (not isinstance(attestation_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", attestation_digest)):
        raise ValueError("unit is not bound to a campaign model attestation")
    if attestation_digest != root_attestation_digest:
        raise ValueError(
            "unit model attestation digest differs from the campaign "
            "opening attestation")
    witness = receipt.get("model_stat_witness")
    if not isinstance(witness, dict) or sorted(witness) != sorted(
            D.MODEL_MEMBERS):
        raise ValueError("unit model stat witness population malformed")
    for member, fields in witness.items():
        if (not isinstance(fields, dict)
                or sorted(fields) != sorted(D.WITNESS_STAT_KEYS)
                or any(type(fields[k]) is not int for k in
                       D.WITNESS_STAT_KEYS)):
            raise ValueError(f"unit model stat witness malformed: {member}")
        attested = root_attestation_members[member]
        if any(fields[k] != attested[k] for k in D.WITNESS_STAT_KEYS):
            raise ValueError(
                f"unit stat witness differs from the attestation: {member}")
    model_dir = receipt.get("model_dir")
    member = receipt.get("model_launch_member")
    if (not isinstance(model_dir, str) or not isinstance(member, str)
            or model_dir != D.MODEL_DIR
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


def _live_namespace_authorities(repo_root: Path, expected_head: str,
                                authority_fetcher: Any = None
                                ) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Live-fetch the dispatch authority for EVERY frozen probe namespace.

    Round-4 correction (maintainer NO-GO comment 5825967767): the
    reduction must never accept a ready-made authority payload or map
    as production authority — a synthetic ``dispatch_map()`` plus
    matching fabricated unit receipts is internally self-consistent
    and would pass the structural validator without any of it ever
    having come from GitHub. Instead the reducer derives the unique
    diagnostic namespaces consumed by the frozen plan and invokes the
    SAME canonical live-fetch seam physical execution gates on
    (``D.require_live_dispatch`` -> ``D.fetch_dispatch_authority`` ->
    ``D.validate_authority_payload``): there is deliberately NO second,
    reduced authority implementation anywhere in the reduction.

    Production callers pass ``authority_fetcher=None``, which resolves
    to the REAL live GitHub fetcher (clean exact-head worktree, live
    PR OPEN/unmerged/base-main/head equality, Issue OPEN, OWNER/MEMBER
    top-level comment with the exact phrase/head/namespace stripped
    lines). Tests inject a fetch FUNCTION whose contract mirrors the
    real fetcher's output; a prevalidated payload map is never an
    input, and any fetch loss fails closed below.
    """
    authorities: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    seen: set[str] = set()
    # Deterministic fetch order: the unique namespaces of the frozen
    # probe plan (repeat, placement, regime, observer-ladder — the
    # canonical probe shares the observer namespace and is fetched once).
    for probe_namespace in FROZEN_PROBE_NAMESPACE.values():
        if probe_namespace in seen:
            continue
        seen.add(probe_namespace)
        try:
            validated = D.require_live_dispatch(
                repo_root, expected_head, probe_namespace,
                revalidate_authority=authority_fetcher)
        except D.DiagnosticError as exc:
            problems.append(
                "live dispatch authority for namespace "
                f"{probe_namespace} rejected: {exc}")
            continue
        except Exception as exc:  # network/OS/git loss must fail closed
            problems.append(
                "live dispatch fetch for namespace "
                f"{probe_namespace} failed: {exc!r}")
            continue
        if validated.get("namespace") != probe_namespace:
            problems.append(
                "live dispatch authority scope "
                f"{validated.get('namespace')!r} does not match the "
                f"required namespace {probe_namespace!r}")
            continue
        if validated.get("head_sha") != expected_head:
            problems.append(
                "live dispatch authority for namespace "
                f"{probe_namespace} binds head "
                f"{validated.get('head_sha')!r} != expected reviewed "
                f"head {expected_head!r}")
            continue
        authorities[probe_namespace] = validated
    return authorities, problems


def _case4096_permission(validated: dict[str, Any]) -> dict[str, Any] | None:
    """The case-4096 permission bound to a FULLY validated dispatch."""
    permission = validated.get("case4096")
    if not isinstance(permission, dict):
        return None
    return {"comment_id": validated["comment_id"],
            "head_sha": validated["head_sha"],
            "namespace": validated["namespace"],
            "line": permission.get("line"),
            "reason": permission.get("reason")}


def _population(root: Path, units: Any, name: str, namespace: str,
                *, require_rows: bool = True,
                case4096_permission: dict[str, Any] | None = None,
                expected_authority: dict[str, Any] | None = None,
                attestation: dict[str, Any] | None = None,
                ) -> tuple[dict[str, Any], list[str]]:
    facts: list[dict[str, Any]] = []
    problems: list[str] = []
    if (not isinstance(units, list) or not units or
            any(not _safe_tag(u) for u in units) or len(set(units)) != len(units)):
        return {}, [f"{name}: invalid, empty, or duplicate unit plan"]
    if attestation is None:
        # Campaign-level model attestation is a terminal precondition
        # (maintainer correction 2026-09-25): without a validated
        # opening attestation NO unit population is admissible.
        return {}, [f"{name}: campaign model attestation missing/invalid"]
    if expected_authority is None:
        # Round-3 blocker 2: without a validated live dispatch authority
        # for this probe namespace, NO unit population is admissible —
        # fully valid numerical/runtime/health bytes cannot overcome
        # absent dispatch provenance.
        return {}, [f"{name}: no validated live dispatch authority for "
                    f"namespace {namespace}"]
    expected_block = D.unit_authority_block(expected_authority)
    if expected_block.get("namespace") != namespace:
        # A unit copied from a different probe namespace carries that
        # namespace's authority; it can never satisfy this one.
        return {}, [f"{name}: dispatch authority namespace "
                    f"{expected_block.get('namespace')!r} != probe "
                    f"namespace {namespace!r}"]
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
            # Round-3 blocker 2: EVERY terminal-bearing unit must carry a
            # dispatch-authority block that exactly equals the canonical
            # block re-derived from the LIVE validated dispatch payload
            # for this probe namespace. The block binds comment ID, exact
            # PR head SHA, diagnostic namespace, created-at, author
            # association, PR/issue binding and the canonical digest of
            # the authorizing comment body — so a fabricated receipt
            # (no authority), a wrong comment/head/namespace, or a valid
            # unit transplanted from another probe namespace all fail.
            authority = receipt.get("authority")
            if not isinstance(authority, dict):
                raise ValueError(
                    "unit receipt carries no dispatch authority block")
            if authority.get("namespace") != namespace:
                raise ValueError(
                    "unit authority namespace does not equal the probe "
                    "namespace containing the unit")
            for key, value in expected_block.items():
                if key == "case4096":
                    continue
                if authority.get(key) != value:
                    raise ValueError(
                        f"unit dispatch authority binding mismatch: {key}")
            if receipt["case_id"] == "case-4096":
                # The retained receipt's authority block is only a claim
                # about GitHub state; the reducer must re-derive the
                # authorization from the LIVE dispatch comment body (the
                # payload's precomputed case4096 block is ignored) and
                # bind it to this exact comment/head/namespace/line.
                permission = authority.get("case4096")
                line = permission.get("line") if isinstance(permission, dict) else None
                reason = permission.get("reason") if isinstance(permission, dict) else None
                if (case4096_permission is None
                        or not isinstance(permission, dict)
                        or type(authority.get("comment_id")) is not int
                        or permission.get("comment_id") != authority.get("comment_id")
                        or authority.get("comment_id") != case4096_permission["comment_id"]
                        or authority.get("head_sha") != case4096_permission["head_sha"]
                        or not isinstance(line, str) or not line.startswith("case-4096:")
                        or not isinstance(reason, str) or not reason.strip()
                        or line != case4096_permission["line"]
                        or reason.strip() != case4096_permission["reason"]
                        or authority.get("dispatch_sha256")
                        != expected_block["dispatch_sha256"]):
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
                                _expected_kind(tag),
                                root_attestation_digest=attestation[
                                    "attestation_sha256"],
                                root_attestation_members={
                                    m["name"]: m
                                    for m in attestation["members"]})
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
            for path in unit_dir.glob("*.pos*.f32"):
                if ".r8e" not in path.name:
                    continue
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
            case4096_permission: dict[str, Any] | None = None,
            authorities: dict[str, dict[str, Any]] | None = None,
            attestation: dict[str, Any] | None = None,
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
                                                       else None),
                                  expected_authority=(authorities or {}
                                                      ).get(probe_namespace),
                                  attestation=attestation)
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
                    expected_head: str, repo_root: Path | None = None,
                    *, health_verifier=None,
                    authority_fetcher: Any = None) -> dict[str, Any]:
    """Derive a terminal from retained bytes; health_verifier is never trusted.

    Vulkan localization is intentionally unreachable: the frozen producer has
    no validated one-factor Vulkan runtime control. A runtime-initialization
    contrast by itself does not establish Vulkan causality.

    Round-4 correction (maintainer NO-GO comment 5825967767): this
    reducer performs its OWN live authority resolution for every
    unique frozen diagnostic namespace the reduction consumes
    (``d248-ref-repeats``, ``d248-placement-rungs``,
    ``d248-regime-sweep``, ``d248-observer-ladder`` — the canonical
    probe shares the observer namespace). A caller-supplied authority
    payload or map is NO LONGER an input of any kind: the required
    namespaces are derived mechanically from the frozen plan and each
    is fetched through the canonical live seam
    ``D.require_live_dispatch`` (production default
    ``D.fetch_dispatch_authority``; clean exact-head worktree, live
    PR OPEN/unmerged/base-main/head equality, Issue OPEN, OWNER/MEMBER
    top-level PR conversation comment carrying the exact dispatch
    phrase / ``head=<sha>`` / single ``diagnostic-namespace=`` stripped
    lines). Every terminal-bearing unit receipt's authority block must
    equal the canonical block re-derived from its namespace's LIVE
    payload, all namespace authorities must bind the same exact-head
    generation, and case-4096 permission derives ONLY from the
    live-fetched regime-namespace comment body. Missing authority
    blocks, wrong comment ID / head / namespace / digest, a deleted or
    edited or stale comment, a closed PR/issue, a moved PR head, an
    unavailable fetch, or any payload failing full validation make the
    reduction ``R8I3_REDUCER_BLOCKED_INCOMPLETE`` — valid
    numerical/runtime/health evidence never overcomes invalid dispatch
    provenance.

    ``authority_fetcher`` is a TEST-ONLY injection seam: a callable
    with the real fetcher's ``((repo_root, expected_head, namespace,
    github_api) -> validated payload)`` contract. Production callers
    pass nothing, which resolves to the REAL live GitHub fetcher —
    omission never falls back to trusting caller-supplied authority.
    """
    if (not isinstance(namespace, str)
            or not re.fullmatch(r"d248-[a-z0-9][a-z0-9-]*", namespace)
            or "--" in namespace):
        return _blocked(str(namespace), ["invalid diagnostic namespace"])
    if (not isinstance(expected_head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_head)):
        return _blocked(str(namespace),
                        ["expected reviewed head is not a 40-hex sha"])
    if repo_root is None:
        repo_root = Path.cwd()
    repo_root = Path(repo_root)
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
    # The reducer LIVE-FETCHES every unique frozen probe namespace FIRST
    # (round-4 correction): no probe population below can be
    # terminal-bearing until its namespace's dispatch authority was
    # fetched through the canonical live seam at reduction time. Any
    # fetch/validation loss fails closed.
    authorities, authority_problems = _live_namespace_authorities(
        repo_root, expected_head, authority_fetcher)
    problems.extend(authority_problems)
    # Campaign-level model attestation (maintainer correction
    # 2026-09-25): the retained OPENING cryptographic attestation and
    # the retained CLOSING full re-hash are both terminal preconditions.
    # Every unit must be bound to the opening digest with a matching
    # per-unit stat witness; the closing receipt must re-verify the
    # complete three-member set byte-identically against the opening.
    attestation: dict[str, Any] | None = None
    try:
        opening_path = root / D.MODEL_ATTESTATION_OPEN_NAME
        if opening_path.is_symlink() or not opening_path.is_file():
            raise ValueError("opening attestation missing or symlink")
        opening = json.loads(opening_path.read_bytes())
        D.validate_model_attestation(opening, expected_head)
        closing_path = root / D.MODEL_ATTESTATION_CLOSE_NAME
        if closing_path.is_symlink() or not closing_path.is_file():
            raise ValueError("closing attestation missing or symlink")
        closing = json.loads(closing_path.read_bytes())
        D.validate_closing_attestation(closing, opening)
        attestation = opening
    except (OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError, D.DiagnosticError) as exc:
        problems.append(f"campaign model attestation invalid: {exc}")
    # One exact-head generation: every live namespace authority must
    # bind the SAME exact expected head (each fetch already required
    # head == expected_head, so surviving payloads agree by
    # construction; the cross-binding is asserted, not assumed).
    heads = {v["head_sha"] for v in authorities.values()}
    if len(heads) > 1 or (authorities and heads != {expected_head}):
        problems.append(
            "live dispatch authorities do not bind one exact-head "
            f"generation (heads={sorted(heads)}, expected={expected_head})")
    permission = None
    regime_authority = authorities.get(FROZEN_PROBE_NAMESPACE["regime"])
    if regime_authority is not None:
        permission = _case4096_permission(regime_authority)
    if _plan_has_case4096(plan) and permission is None:
        problems.append(
            "case-4096 units planned but the live regime-namespace "
            "dispatch fetched for this reduction carries no valid "
            "case-4096 authorization line")
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
                                  probe_namespace, require_rows=not rowless_allowed,
                                  expected_authority=authorities.get(probe_namespace),
                                  attestation=attestation)
        reduced[name] = pop
        problems.extend(errors)
    phase2, phase2_errors = _phase2(plan, root, case4096_permission=permission,
                                    authorities=authorities,
                                    attestation=attestation)
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
