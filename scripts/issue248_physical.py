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

    Read-only sysfs/nvidia-smi/lspci observation (no GPU compute, no
    model reads) — the same seam the accepted campaign's Phase-3 used.
    Injected in tests via ``identity_observer``.
    """
    out: dict[str, Any] = {"arm": arm, "raw": {}}
    bdf = "00000000:03:00.0" if arm == "B" else "00000000:02:00.0"
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,name,pci.bus_id,driver_version",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=15)
    out["raw"]["nvidia-smi"] = smi.stdout
    for key, rel in (("vendor", "vendor"), ("device", "device"),
                     ("revision", "revision"),
                     ("current_link_width", "current_link_width"),
                     ("max_link_width", "max_link_width")):
        p = Path("/sys/bus/pci/devices") / bdf / rel
        if p.is_file():
            out["raw"][f"sysfs.{rel}"] = p.read_text().strip()
    return out


def _arm_identity_ok(arm: str, observation: dict[str, Any]) -> list[str]:
    """Fail-closed identity problems for one raw observation (arm B)."""
    problems: list[str] = []
    raw = observation.get("raw", {})
    smi = raw.get("nvidia-smi", "")
    if arm == "B":
        if "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55" not in smi:
            problems.append("reference GPU UUID absent from nvidia-smi")
        if "NVIDIA GeForce RTX 3060" not in smi:
            problems.append("reference GPU name absent")
        if "00000000:03:00.0" not in smi:
            problems.append("reference BDF absent (16-char form)")
        if raw.get("sysfs.vendor") != "0x10de":
            problems.append("reference vendor drift")
        if raw.get("sysfs.device") != "0x2504":
            problems.append("reference device drift")
    else:
        if raw.get("sysfs.vendor") != "0x1002":
            problems.append("candidate vendor drift")
        if raw.get("sysfs.device") != "0x67df":
            problems.append("candidate device drift")
        if raw.get("sysfs.current_link_width") != "Width 16":
            problems.append("candidate negotiated width drift (gen-2 x16)")
    return problems


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
    observer_mode: str = "comparator", binary: Path, model_member: Path,
    expected_head: str, authority: dict[str, Any],
    index: int,
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[str], dict[str, Any]] | None = None,
    revalidate_authority: Callable[[dict[str, Any]], dict[str, Any]]
    | None = None,
    request_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute ONE diagnostic unit under full gating; retain raw custody.

    ``execute`` is the injectable server-launch seam (tests supply a
    fake); production uses :func:`_real_execute`.
    """
    repo_root = Path(repo_root).resolve(strict=True)
    if kind not in UNIT_KINDS:
        raise PhysicalDiagnosticError(f"unknown unit kind: {kind}")
    if observer_mode not in OBSERVER_MODES:
        raise PhysicalDiagnosticError(f"unknown observer mode: {observer_mode}")
    if kind == "canonical" and binary_id != "canonical":
        raise PhysicalDiagnosticError("canonical kind requires canonical binary")
    if case == D.CASE_4096 and not str(authority.get(
            "preauthorized_case4096", "")) .startswith("case-4096:"):
        raise PhysicalDiagnosticError(
            "case-4096 requires explicit dispatch preauthorization")
    D.validate_namespace(namespace)
    tag = D.unit_tag(case, arm, _variant_for(kind, observer_mode, ngl, case),
                     index)
    fixtures = D.verify_fixtures(repo_root)
    binary_sha = D.verify_binary(Path(binary), binary_id)
    model_sha = D.file_sha256(Path(model_member))
    # GATE FIRST: authority must validate against the exact clean head
    # before any physical action, and again before launch.
    authority = D.validate_authority_payload(authority, expected_head)
    if revalidate_authority is not None:
        authority = D.validate_authority_payload(
            revalidate_authority(authority), expected_head)
    D._require_clean_head(repo_root, expected_head)
    unit_dir = D.prepare_unit_dir(evidence_root, namespace, tag)

    identity_pre = (identity_observer or _observe_arm_identity)(arm)
    problems_pre = _arm_identity_ok(arm, identity_pre)
    if problems_pre:
        _write_json(unit_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    request = dict(request_contract or D.REQUEST_CONTRACT)
    force = None
    out_prefix = unit_dir / "obs"
    env = D.launch_env(
        arm, icd=_icd_for(arm), selector=_selector_for(arm),
        observer=("comparator" if observer_mode.startswith("comparator")
                  else "r8e-only" if observer_mode == "r8e-only" else "off"),
        out_prefix=out_prefix, force=force,
        r8e_capture=(observer_mode == "comparator-dual"))
    if observer_mode == "comparator-off":
        env = {k: v for k, v in env.items()
               if not k.startswith("LLAMA_OBSERVE")}
    argv = D.server_argv(Path(binary), Path(model_member), ngl,
                         PORT_BY_ARM[arm])
    started = time.monotonic()

    runner = execute or _real_execute
    result = runner(argv=argv, env=env, arm=arm, request=request,
                    prompt=fixtures[case]["prompt_text"],
                    port=PORT_BY_ARM[arm], unit_dir=unit_dir)
    wall = time.monotonic() - started

    identity_post = (identity_observer or _observe_arm_identity)(arm)
    problems_post = _arm_identity_ok(arm, identity_post)
    _write_json(unit_dir / "identity-pre.json", identity_pre)
    _write_json(unit_dir / "identity-post.json", identity_post)

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
        "model_member_sha256": model_sha,
        "observer_mode": observer_mode,
        "request_contract": request,
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
        "authority": {"comment_id": authority["comment_id"],
                      "head_sha": authority["head_sha"],
                      "namespace": authority["namespace"],
                      "created_at": authority["created_at"]},
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


def _icd_for(arm: str) -> str:
    return ("/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json" if arm == "B"
            else "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json")


def _selector_for(arm: str) -> dict[str, str]:
    # Same arm-B/C device selection the accepted campaign used.
    return {"GGML_VK_VISIBLE_DEVICES": "0"}


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
    receipts + raw bytes; a missing unit fails its probe closed.
    """
    D.validate_namespace(namespace)
    base = D.namespace_dir(evidence_root, namespace)
    problems: list[str] = []
    probes: dict[str, Any] = {}
    for probe_name, spec in plan.get("probes", {}).items():
        unit_facts = []
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
            rows, _meta = D.collect_row_meta(unit_dir)
            facts["row_sha256"] = {
                d: D.row_digest(b) for d, b in rows.items()}
            r8e = D.r8e_captured_rows(unit_dir)
            if r8e:
                facts["r8e_row_sha256"] = {
                    str(p): D.row_digest(b) for p, b in r8e.items()}
            unit_facts.append(facts)
        if unit_facts and len(unit_facts) == len(spec.get("units", [])):
            digests = [f["deterministic_output_sha256"] for f in unit_facts]
            probes[probe_name] = {
                "units": unit_facts,
                "token_determinism": D.judge_repeat_determinism(digests),
                "row_determinism": _row_determinism(unit_facts),
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
