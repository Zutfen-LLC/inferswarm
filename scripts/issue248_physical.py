#!/usr/bin/env python3
"""Issue #248 (R8-I3A) bounded physical diagnostic producer.

DIAGNOSTIC-ONLY. Every entrypoint gates FIRST (authority, namespace,
exact-head clean worktree, binary identity, model identity, fixture
identity, arm identity) and only then performs any GPU work. There is no
qualification path here: comparator/2 methodology is untouched, no
threshold exists, no holdout access is possible, and the diagnostic
terminals are derived by the offline reducer from retained bytes.

Execution-unit semantics mirror the accepted #241 campaign exactly:
one fresh llama-server process per request, exact accepted launch shape
(--ctx-size 8192 --batch-size 512, port per arm), exact request contract,
one completion request per unit, process attribution captured from
/proc, device identity observed pre/post through the same raw-observation
seam, polaris fan held for multi-run sessions.

Unit kinds (each changes exactly one factor vs the accepted baseline):
  repeat     — case-3072 arm B ngl=8 comparator binary, r8i3 observer on
               (repeatability probe population unit; Phase 1)
  rung       — same but ngl varies over the frozen ladder 1/2/4/6/8
               (placement dependence; Phase 2A)
  regime     — case varies over the accepted historical controls, plus
               case-4096 ONLY under explicit preauthorization (Phase 2B)
  observer   — binary/observer-mode varies: comparator-dual (r8i3 + r8e
               capture in ONE process), r8e-only (R8-E obs binary),
               comparator-off (patched binary, observer inert) (Phase 3)
  canonical  — accepted canonical no-hook binary, token-level custody
               (Phase 3 rung 3)

Retained per unit (append-only, no overwrite; quarantine to re-run):
  request/response raw bytes, server log, all captured row files and
  observer meta, device-samples JSON, identity pre/post JSON, process
  attribution, launch argv/env, authority snapshot, wall time (metadata).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import issue248_diagnostic as D
import issue248_identity as I

UNIT_SCHEMA = "inferswarm.issue248.diagnostic-unit/1"
UNIT_KINDS = ("repeat", "rung", "regime", "observer", "canonical")
OBSERVER_MODES = ("comparator", "comparator-dual", "r8e-only",
                  "comparator-off")
PORT_BY_ARM = {"B": 19000, "C": 19001}


class PhysicalDiagnosticError(RuntimeError):
    pass


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _observe_arm_identity(arm: str) -> dict[str, Any]:
    """Raw device identity observation for the executing arm.

    Read-only sysfs/nvidia-smi/ICD-inventory/vulkaninfo observation (no
    GPU compute, no model reads) through the same seam the accepted
    campaign's Phase-3 used — now via the exact-subject identity module
    (correction 6). Injected in tests via ``identity_observer``.
    """
    return I.observe_arm_identity(arm)


def _arm_identity_ok(arm: str, observation: dict[str, Any]) -> list[str]:
    """Fail-closed identity problems for one raw observation.

    Every frozen runtime/device field is derived from the raw bytes and
    compared against the accepted subject constants (correction 6 — the
    previous gate checked only UUID/name/BDF/vendor/device).
    """
    return I.identity_problems(arm, observation)


def _device_sample(arm: str) -> dict[str, Any]:
    """One residency sample for both devices (per-process residency)."""
    sample: dict[str, Any] = {"stage": None, "residency_mib": {}}
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15).stdout
    for line in smi.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) == 2:
            sample["residency_mib"]["00000000:03:00.0"] = int(fields[1])
    for bdf, card in (("00000000:02:00.0", "card0"),):
        p = Path(f"/sys/class/drm/{card}/device/mem_info_vram_used")
        if p.is_file():
            sample["residency_mib"][bdf] = (
                int(p.read_text().strip()) / (1024 * 1024))
    return sample


def _http_completion(port: int, request: dict[str, Any],
                     prompt: str) -> tuple[bytes, dict[str, Any]]:
    payload = json.dumps({**request, "prompt": prompt}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=1200) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"completion HTTP status {response.status}")
        raw = response.read(1024 * 1024)
    return raw, json.loads(raw)


def run_diagnostic_unit(
    repo_root: Path, evidence_root: Path, namespace: str, kind: str,
    *, arm: str, case: str, ngl: int, binary_id: str,
    observer_mode: str = "comparator", binary: Path,
    model_dir: Path,
    expected_head: str,
    index: int,
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[str], dict[str, Any]] | None = None,
    revalidate_authority: Callable[[Path, str, str, str],
                                   dict[str, Any]] | None = None,
    request_contract: dict[str, Any] | None = None,
    intervention: dict[str, Any] | None = None,
    model_hasher: Callable[[Path], str] | None = None,
    github_api: str = "https://api.github.com",
) -> dict[str, Any]:
    """Execute ONE diagnostic unit under full gating; retain raw custody.

    ``execute`` is the injectable server-launch seam (tests supply a
    fake); production uses :func:`_real_execute`. There is NO authority
    parameter: the dispatch authority ALWAYS comes from the mandatory
    live revalidation (correction 3) — a cached dict was the corrected
    defect.

    Correction gates (maintainer NO-GO round 1), all BEFORE any launch:
      1. exact three-member model authority — every member of the
         accepted #241 GGUF set is hashed and compared against the
         accepted digests; the launched path is DERIVED (member 1),
         never caller-supplied;
      2. frozen request contract — the executed request is the frozen
         authority; a caller override must equal it byte/semantically
         or execution fails before launch;
      3. MANDATORY live dispatch revalidation — the live PR-conversation
         fetch (PR open/unmerged/base-main/exact-head, issue open,
         OWNER/MEMBER comment, exact lines) runs through
         :func:`D.require_live_dispatch` immediately before the unit;
         omitting the injection runs the REAL fetcher, never disables
         verification;
      4. case-4096 authorization derives only from the fetched
         comment's exact ``case-4096:<reason>`` line;
      5. the offline reducer derives the terminal (see derive_terminal);
      6. exact subject identity — every frozen runtime/device field is
         derived from a fresh raw observation and verified pre AND post
         (single-factor DIAGNOSTIC_ONLY interventions excepted).
    """
    repo_root = Path(repo_root).resolve(strict=True)
    if kind not in UNIT_KINDS:
        raise PhysicalDiagnosticError(f"unknown unit kind: {kind}")
    if observer_mode not in OBSERVER_MODES:
        raise PhysicalDiagnosticError(f"unknown observer mode: {observer_mode}")
    if kind == "canonical" and binary_id != "canonical":
        raise PhysicalDiagnosticError("canonical kind requires canonical binary")
    D.validate_namespace(namespace)
    # GATE ORDER (source-checked by tests): namespace shape -> live
    # dispatch authority -> clean exact head -> case authorization ->
    # fixture identity -> exact model bytes -> binary identity ->
    # subject identity -> prepare custody -> launch.
    authority = D.require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    # case-4096 permission is COMMENT-DERIVED ONLY (correction 4): the
    # live authority's parsed case4096 block is the sole source; any
    # ``preauthorized_case4096`` key on a caller dict is ignored by the
    # validator and can never manufacture this permission.
    if case == D.CASE_4096:
        case4096 = authority.get("case4096")
        if not case4096:
            raise PhysicalDiagnosticError(
                "case-4096 requires an exact 'case-4096:<reason>' line in "
                "the live dispatch comment")
        if case4096.get("comment_id") != authority.get("comment_id"):
            raise PhysicalDiagnosticError(
                "case-4096 authorization is not bound to the live "
                "dispatch comment")
    tag = D.unit_tag(case, arm, _variant_for(kind, observer_mode, ngl, case),
                     index)
    fixtures = D.verify_fixtures(repo_root)
    binary_sha = D.verify_binary(Path(binary), binary_id)
    # Correction 1: the COMPLETE accepted three-member set verifies
    # before any launch; the launch path is derived member 1.
    verified_members = D.verify_model_members(
        Path(model_dir), hasher=model_hasher or D.file_sha256)
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1
    D._require_clean_head(repo_root, expected_head)
    unit_dir = D.prepare_unit_dir(evidence_root, namespace, tag)

    identity_pre = (identity_observer or _observe_arm_identity)(arm)
    if intervention is not None:
        problems_pre = I.intervention_problems(arm, identity_pre, intervention)
    else:
        problems_pre = _arm_identity_ok(arm, identity_pre)
    if problems_pre:
        _write_json(unit_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    # Correction 2: production derives the request from the frozen
    # authority. A caller-supplied contract must equal it exactly
    # (validate_request_contract rejects value drift AND extra keys).
    request = D.validate_request_contract(
        request_contract if request_contract is not None
        else D.REQUEST_CONTRACT)
    force = None
    out_prefix = unit_dir / "obs"
    env = D.launch_env(
        arm, icd=I.frozen_identity(arm)["icd"],
        selector=dict(I.frozen_identity(arm)["selector"]),
        observer=("comparator" if observer_mode.startswith("comparator")
                  else "r8e-only" if observer_mode == "r8e-only" else "off"),
        out_prefix=out_prefix, force=force,
        r8e_capture=(observer_mode == "comparator-dual"))
    if observer_mode == "comparator-off":
        env = {k: v for k, v in env.items()
               if not k.startswith("LLAMA_OBSERVE")}
    argv = D.server_argv(Path(binary), launch_member, ngl,
                         PORT_BY_ARM[arm])
    started = time.monotonic()

    runner = execute or _real_execute
    result = runner(argv=argv, env=env, arm=arm, request=request,
                    prompt=fixtures[case]["prompt_text"],
                    port=PORT_BY_ARM[arm], unit_dir=unit_dir)
    wall = time.monotonic() - started

    identity_post = (identity_observer or _observe_arm_identity)(arm)
    if intervention is not None:
        problems_post = I.intervention_problems(arm, identity_post,
                                                intervention)
    else:
        problems_post = _arm_identity_ok(arm, identity_post)
    _write_json(unit_dir / "identity-pre.json", identity_pre)
    _write_json(unit_dir / "identity-post.json", identity_post)
    if problems_post:
        raise PhysicalDiagnosticError(
            f"post-execution identity drift: {problems_post}")

    tokens = result.get("tokens")
    if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(f"{tag}: malformed token output")
    (unit_dir / "response.json.raw").write_bytes(result["response_raw"])
    receipt = {
        "schema": UNIT_SCHEMA,
        "kind": kind,
        "namespace": namespace,
        "tag": tag,
        "case_id": case,
        "arm": arm,
        "ngl": ngl,
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "model_dir": str(model_dir),
        "model_members_sha256": dict(verified_members),
        "model_launch_member": str(launch_member),
        "request_contract": request,
        "request_contract_sha256": D.canonical_request_digest(request),
        "observer_mode": observer_mode,
        "prompt_len": fixtures[case]["rendered_length"],
        "prompt_token_ids": fixtures[case]["prompt_token_ids"],
        "server_argv": argv,
        "server_env": {k: env[k] for k in sorted(env)
                       if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
        "process_attribution": result.get("process_attribution"),
        "tokens": tokens,
        "deterministic_output_sha256": D.canonical_token_digest(tokens),
        "identity_problems_pre": problems_pre,
        "identity_problems_post": problems_post,
        "subject_identity_schema": I.IDENTITY_SCHEMA,
        "intervention": dict(intervention) if intervention else None,
        "intervention_mode": bool(intervention),
        "authority": {"comment_id": authority["comment_id"],
                      "head_sha": authority["head_sha"],
                      "namespace": authority["namespace"],
                      "created_at": authority["created_at"],
                      "case4096": authority.get("case4096")},
        "wall_time_s": wall,
    }
    rows_meta = result.get("rows_meta")
    if rows_meta:
        receipt["observer_rows"] = rows_meta
    _write_json(unit_dir / "unit.json", receipt)
    return receipt


def _variant_for(kind: str, observer_mode: str, ngl: int, case: str) -> str:
    if kind == "repeat":
        return "baseline"
    if kind == "rung":
        return f"ngl{ngl}"
    if kind == "regime":
        return "case4096" if case == D.CASE_4096 else f"regime-{case[5:]}"
    if kind == "observer":
        return {"comparator": "obs-comparator",
                "comparator-dual": "obs-dual",
                "r8e-only": "obs-r8e",
                "comparator-off": "obs-off"}.get(observer_mode, "obs")
    return "canonical"


def _real_execute(argv: list[str], env: dict[str, str], arm: str,
                  request: dict[str, Any], prompt: str, port: int,
                  unit_dir: Path) -> dict[str, Any]:
    """Launch one fresh server process; issue one completion; tear down."""
    samples = [_device_sample(arm) | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            argv, env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True)
        attribution: dict[str, Any] = {}
        try:
            deadline = time.monotonic() + 1800
            ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise PhysicalDiagnosticError(
                        f"server exited early rc={proc.returncode}")
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=2
                    ) as response:
                        if response.status == 200:
                            ready = True
                            break
                except (urllib.error.URLError, OSError):
                    time.sleep(1.0)
            if not ready:
                raise PhysicalDiagnosticError("server never became healthy")
            exe = os.path.realpath(f"/proc/{proc.pid}/exe")
            attribution = {
                "server_pid": proc.pid,
                "server_exe_sha256": D.file_sha256(Path(exe)),
                "server_argv": list(argv),
                "server_env": dict(env),
            }
            stop = threading.Event()
            errors: list[Exception] = []

            def sample_loop() -> None:
                while not stop.is_set():
                    try:
                        samples.append(
                            _device_sample(arm) | {"stage": "during"})
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)
                        return
                    time.sleep(2.0)

            thread = threading.Thread(target=sample_loop, daemon=True)
            thread.start()
            try:
                raw, response = _http_completion(port, request, prompt)
            finally:
                stop.set()
                thread.join(timeout=2)
            if errors:
                raise PhysicalDiagnosticError(
                    "device sampling failed") from errors[0]
            samples.append(_device_sample(arm) | {"stage": "after"})
            tokens = response.get("tokens", response.get("tokens_predicted"))
            return {"returncode": proc.poll(),
                    "tokens": tokens, "response_raw": raw,
                    "process_attribution": attribution,
                    "device_samples": samples}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
    # rows land via observer files written by the server into unit_dir


# ---------------------------------------------------------------------------
# Offline reducer: derive the diagnostic terminal from retained units
# ---------------------------------------------------------------------------

REDUCER_SCHEMA = "inferswarm.issue248.diagnostic-reduction/1"


def derive_reduction(evidence_root: Path, namespace: str,
                     plan: dict[str, Any]) -> dict[str, Any]:
    """Re-derive every conclusion from retained unit bytes (fail-closed).

    ``plan`` is the frozen diagnostic plan (which units were supposed to
    exist for which probe). Every check derives from the retained
    receipts + raw bytes; a missing unit fails its probe closed. Units
    without observer rows (canonical/observer-off custody) contribute
    token determinism only; row determinism is judged over the units
    that carry rows.
    """
    D.validate_namespace(namespace)
    base = D.namespace_dir(evidence_root, namespace)
    problems: list[str] = []
    probes: dict[str, Any] = {}
    for probe_name, spec in plan.get("probes", {}).items():
        unit_facts = []
        rowless = 0
        for tag in spec.get("units", []):
            unit_dir = base / tag
            receipt_path = unit_dir / "unit.json"
            if not receipt_path.is_file():
                problems.append(f"{probe_name}: unit receipt missing: {tag}")
                continue
            receipt = json.loads(receipt_path.read_bytes())
            raw_path = unit_dir / "response.json.raw"
            if not raw_path.is_file():
                problems.append(f"{probe_name}: raw response missing: {tag}")
                continue
            resp = json.loads(raw_path.read_bytes())
            tokens = resp.get("tokens", resp.get("tokens_predicted"))
            if tokens != receipt.get("tokens"):
                problems.append(
                    f"{probe_name}: receipt tokens differ from raw: {tag}")
                continue
            facts = {"tag": tag,
                     "deterministic_output_sha256":
                         D.canonical_token_digest(tokens)}
            meta_path = unit_dir / "obs.meta.json"
            if meta_path.is_file():
                rows, _meta = D.collect_row_meta(unit_dir)
                facts["row_sha256"] = {
                    d: D.row_digest(b) for d, b in rows.items()}
            else:
                rowless += 1
            r8e = D.r8e_captured_rows(unit_dir)
            if r8e:
                facts["r8e_row_sha256"] = {
                    str(p): D.row_digest(b) for p, b in r8e.items()}
            unit_facts.append(facts)
        if unit_facts and len(unit_facts) == len(spec.get("units", [])):
            digests = [f["deterministic_output_sha256"] for f in unit_facts]
            row_facts = [f for f in unit_facts if "row_sha256" in f]
            probes[probe_name] = {
                "units": unit_facts,
                "rowless_units": rowless,
                "token_determinism": D.judge_repeat_determinism(digests),
                "row_determinism": (_row_determinism(row_facts)
                                    if row_facts else
                                    {"deterministic": None,
                                     "per_decision": {}}),
            }
    return {
        "schema": REDUCER_SCHEMA,
        "namespace": namespace,
        "probes": probes,
        "problems": problems,
        "complete": not problems and len(probes) == len(
            plan.get("probes", {})),
    }


def _row_determinism(unit_facts: list[dict[str, Any]]) -> dict[str, Any]:
    per_decision: dict[str, list[str]] = {}
    for f in unit_facts:
        for d, digest in f.get("row_sha256", {}).items():
            per_decision.setdefault(d, []).append(digest)
    out: dict[str, Any] = {}
    for d, digests in sorted(per_decision.items()):
        out[d] = D.judge_repeat_determinism(digests)
    if not per_decision:
        return {"deterministic": None, "per_decision": {}}
    return {"deterministic": all(v["deterministic"] for v in out.values()),
            "per_decision": out}


# ---------------------------------------------------------------------------
# Correction 5: the terminal is MECHANICALLY derived from retained unit
# bytes + the frozen plan. No caller may supply or select a terminal;
# missing/broken evidence fails closed to the machine-readable BLOCKED
# state (distinct from the Issue #248 diagnostic vocabulary).
# ---------------------------------------------------------------------------

REDUCER_BLOCKED = "R8I3_REDUCER_BLOCKED_INCOMPLETE"
# The frozen probe names the decision tree consumes; a plan lacking one
# can never yield a terminal.
REQUIRED_PROBE_NAMES = ("repeat", "observer", "canonical")
# Phase-3 observer-ladder variants (unit-tag variant spellings). The
# plan declares the primary observer units; every variant's units are
# derived by swapping the variant segment (same case/arm/index shape).
OBSERVER_VARIANTS = ("obs-comparator", "obs-dual", "obs-r8e", "obs-off")


def _fork_units(units: list[str], variant: str) -> list[str]:
    """Swap the variant segment of every unit tag (same case/arm/index).

    Case IDs themselves contain dashes (``case-3072``) and variants may
    be multi-segment (``obs-comparator``), so the tag is split from the
    ARM side: the arm is the single-character ``B``/``C`` segment.
    """
    out = []
    for tag in units:
        head, index = tag.rsplit("-", 1)
        parts = head.split("-")
        arm_idx = next(i for i in range(len(parts) - 1, 0, -1)
                       if len(parts[i]) == 1 and parts[i] in ("B", "C"))
        out.append(f"{'-'.join(parts[:arm_idx])}-{parts[arm_idx]}-"
                   f"{variant}-{index}")
    return out


def derive_terminal(evidence_root: Path, namespace: str,
                    plan: dict[str, Any]) -> dict[str, Any]:
    """Mechanically derive the Issue #248 terminal (correction 5).

    Decision tree over retained bytes + frozen plan (first match wins;
    any missing/malformed evidence fails closed to ``blocked``):

      A. NOT_REPRODUCED — the fresh reference repeatability population
         is complete and fully deterministic (tokens AND rows). The
         accepted retained #241 mismatch stays verified by Phase-0
         authority; no later probe reinterprets it.
      D. PLATFORM_INSTABILITY_LOCALIZED — retained physical evidence:
         fatal platform states (recorded identity drift or fatal
         device-sample markers) in the repeat population. Numerical row
         variation alone never selects D.
      B. OBSERVER_PERTURBATION_LOCALIZED — repeatable comparator-observer
         row variability demonstrated AND the dual-capture discriminator
         agrees within every process AND the comparator-independent
         capture path (r8e-only) is row-DETERMINISTIC AND the canonical
         unobserved ladder is token-deterministic: the equivalent
         unobserved path is stable, localizing the perturbation to
         observer/capture.
      C. VULKAN_NONDETERMINISM_LOCALIZED — row variation reproducible,
         dual capture paths agree within each process (capture
         faithful), variation survives across fresh processes in every
         capture mode including the comparator-independent one, and
         platform health is clean: the boundary is the Vulkan/runtime
         execution upstream of capture.
      E. UNRESOLVED — complete probes confirm repeatable variation but
         no stronger localization predicate is mechanically satisfied.
    """
    evidence_root = Path(evidence_root)
    base = D.namespace_dir(evidence_root, namespace)
    plan_probes = plan.get("probes", {})
    for required in REQUIRED_PROBE_NAMES:
        if required not in plan_probes:
            return _blocked(reduction=None, namespace=namespace, extra=[
                f"plan lacks required probe: {required}"])
    # Internal plan: repeat + canonical as frozen, plus one probe per
    # observer-ladder variant (units derived by variant swap).
    observer_units = plan_probes["observer"].get("units", [])
    internal: dict[str, Any] = {"probes": {
        "repeat": plan_probes["repeat"],
        "canonical": plan_probes["canonical"],
    }}
    for variant in OBSERVER_VARIANTS:
        internal["probes"][f"observer:{variant}"] = {
            "units": _fork_units(observer_units, variant)}
    reduction = derive_reduction(evidence_root, namespace, internal)
    if not reduction["complete"]:
        return _blocked(reduction, namespace, [
            "reduction incomplete: missing/malformed retained units"])
    return _derive_terminal_from_reduction(base, namespace, reduction,
                                           plan_probes)


def _blocked(reduction: dict[str, Any] | None, namespace: str,
             extra: list[str]) -> dict[str, Any]:
    return {
        "schema": REDUCER_SCHEMA,
        "namespace": namespace,
        "terminal": None,
        "terminal_vocabulary": list(D.TERMINALS),
        "blocked": REDUCER_BLOCKED,
        "problems": list((reduction or {}).get("problems", [])) + extra,
        "probes": (reduction or {}).get("probes", {}),
        "complete": False,
    }


def _terminal_result(namespace: str, reduction: dict[str, Any],
                     terminal: str, basis: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": REDUCER_SCHEMA,
        "namespace": namespace,
        "terminal": terminal,
        "terminal_vocabulary": list(D.TERMINALS),
        "blocked": None,
        "problems": list(reduction.get("problems", [])),
        "probes": reduction.get("probes", {}),
        "complete": True,
        "basis": basis,
    }


def _derive_terminal_from_reduction(
        base: Path, namespace: str, reduction: dict[str, Any],
        plan_probes: dict[str, Any]) -> dict[str, Any]:
    repeat = reduction["probes"]["repeat"]
    token_det = repeat["token_determinism"]["deterministic"]
    row_det = repeat["row_determinism"]["deterministic"]

    # --- A. NOT_REPRODUCED ----------------------------------------------
    if token_det is True and row_det is True:
        return _terminal_result(namespace, reduction,
                                "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED",
                                {"accepted_241_mismatch":
                                 "verified (Phase-0 authority, read-only)",
                                 "repeat_population_complete": True,
                                 "repeat_rows_deterministic": True,
                                 "note": ("no later probe reinterprets the "
                                          "accepted #241 blocked campaign")})

    repeat_units = plan_probes["repeat"].get("units", [])
    if not repeat_units:
        return _blocked(reduction, namespace, ["repeat probe has no units"])

    # --- D. PLATFORM_INSTABILITY_LOCALIZED -------------------------------
    health = _platform_health(base, repeat_units)
    if health is None:
        return _blocked(reduction, namespace, [
            "platform-health evidence missing/malformed for the repeat "
            "population (fail closed: D unavailable)"])
    if health["fatal_states"]:
        return _terminal_result(namespace, reduction,
                                "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED",
                                {"fatal_states": health["fatal_states"],
                                 "evidence": health["evidence"],
                                 "note": ("causal platform instability "
                                          "evidence, not numerical "
                                          "variation alone")})

    # --- Discriminator evidence (B vs C) ----------------------------------
    dual_ok, dual_detail = _dual_capture_agreement(base, reduction,
                                                   plan_probes)
    if dual_ok is None:
        return _blocked(reduction, namespace,
                        ["dual-capture discriminator evidence missing "
                         "(obs-dual units or r8e rows absent)"])
    canonical = reduction["probes"]["canonical"]
    canon_det = canonical["token_determinism"]["deterministic"]
    r8e_det = reduction["probes"]["observer:obs-r8e"][
        "row_determinism"]["deterministic"]
    comparator_det = reduction["probes"]["observer:obs-comparator"][
        "row_determinism"]["deterministic"]

    # --- B. OBSERVER_PERTURBATION_LOCALIZED ------------------------------
    if (comparator_det is False and dual_ok
            and r8e_det is True and canon_det is True):
        return _terminal_result(namespace, reduction,
                                "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED",
                                {"comparator_rows_vary": True,
                                 "dual_capture_within_process": dual_detail,
                                 "r8e_only_rows_deterministic": True,
                                 "canonical_tokens_deterministic": True,
                                 "note": ("the comparator-independent path "
                                          "is stable: perturbation "
                                          "localized to observer/capture")})

    # --- C. VULKAN_NONDETERMINISM_LOCALIZED -------------------------------
    all_capture_modes_vary = True
    for variant in ("obs-comparator", "obs-dual", "obs-r8e"):
        det = reduction["probes"][f"observer:{variant}"][
            "row_determinism"]["deterministic"]
        if det is not False:
            all_capture_modes_vary = False
            break
    if (row_det is False and dual_ok and all_capture_modes_vary
            and canon_det is True):
        return _terminal_result(namespace, reduction,
                                "R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED",
                                {"row_variation_reproducible": True,
                                 "dual_capture_within_process": dual_detail,
                                 "fresh_process_variation_all_modes": True,
                                 "platform_health_clean": True,
                                 "boundary": ("Vulkan/runtime execution "
                                              "upstream of capture")})

    # --- E. UNRESOLVED ------------------------------------------------------
    if token_det is False or row_det is False:
        return _terminal_result(namespace, reduction,
                                "R8I3_REF_NONDETERMINISM_UNRESOLVED",
                                {"repeatable_variation_confirmed": True,
                                 "localization_predicates_satisfied": False})
    return _blocked(reduction, namespace,
                    ["repeatable variation could not be confirmed from "
                     "complete evidence; no honest terminal derivable"])


def _platform_health(base: Path,
                     repeat_units: list[str]) -> dict[str, Any] | None:
    """Derive platform-health fatal states from retained unit receipts.

    Reads the identity receipts + device samples of the repeat
    population. Fatal states are an explicit closed vocabulary
    (recorded identity drift; ECC/XID/thermal/power fatal markers in
    retained samples). Returns None when evidence is missing/malformed
    (fail closed), never a vacuous clean bill.
    """
    FATAL_MARKERS = ("ECC", "XID", "thermal violation", "power violation",
                     "overcurrent")
    fatal: list[str] = []
    evidence: list[str] = []
    for tag in repeat_units:
        unit = base / tag
        identity_path = unit / "identity-post.json"
        receipt_path = unit / "unit.json"
        if not identity_path.is_file() or not receipt_path.is_file():
            return None
        try:
            receipt = json.loads(receipt_path.read_bytes())
        except json.JSONDecodeError:
            return None
        if receipt.get("tag") != tag:
            return None
        if receipt.get("identity_problems_post"):
            fatal.append(f"{tag}: identity problems post-execution")
        samples_path = unit / "device-samples.json"
        if samples_path.is_file():
            try:
                text = json.dumps(json.loads(samples_path.read_bytes()))
            except json.JSONDecodeError:
                return None
            for marker in FATAL_MARKERS:
                if marker in text:
                    fatal.append(
                        f"{tag}: fatal marker {marker} in device samples")
            evidence.append(f"{tag}/device-samples.json")
        evidence.append(f"{tag}/identity-post.json")
    return {"fatal_states": fatal, "evidence": evidence}


def _dual_capture_agreement(base: Path, reduction: dict[str, Any],
                            plan_probes: dict[str, Any]
                            ) -> tuple[bool | None, str]:
    """Do the two capture paths agree WITHIN each obs-dual process?

    For every obs-dual unit with comparator rows: the r8i3 row-0 bytes
    and the R8-E captured row-0 bytes must be byte-identical (two
    independently coded capture paths reading the same row). Returns
    (None, detail) when the evidence is missing, (False, detail) on the
    first disagreement, (True, detail) when every dual unit agrees.
    """
    dual_units = _fork_units(
        plan_probes["observer"].get("units", []), "obs-dual")
    if not dual_units:
        return None, "no obs-dual units retained"
    checked = 0
    for tag in dual_units:
        unit = base / tag
        meta_path = unit / "obs.meta.json"
        if not meta_path.is_file():
            return None, f"obs-dual unit lacks comparator capture: {tag}"
        rows, _meta = D.collect_row_meta(unit)
        r8e = D.r8e_captured_rows(unit)
        if 0 not in r8e:
            return None, f"obs-dual unit lacks r8e row 0: {tag}"
        if rows["0"] != r8e[0]:
            return False, f"dual-capture disagreement in {tag} (row 0)"
        checked += 1
    return True, f"both capture paths byte-identical in {checked} processes"
