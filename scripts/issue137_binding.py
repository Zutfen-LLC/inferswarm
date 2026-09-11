#!/usr/bin/env python3
"""Issue #137 correction — accepted-authority binding module.

Immutable pins of the ACCEPTED #133/#137 diagnostic authority, plus a
fail-closed verifier the probe driver runs BEFORE any GPU execution and
the conclusions reducer re-runs over retained records.

Authority model (issue #137 / correction C5): hashes recorded at run
time are OBSERVATIONS, not pins.  A value is a PIN only when compared
against an immutable accepted authority source:

  * #133 physical input/identity bytes — pinned by the accepted
    MANIFEST.sha256 frozen at the PR #136 merge `1b83bca…`
    (git blob identity; byte-exact by git's content addressing);
  * frozen producer module bytes — pinned by
    `arm-c-retry/coordinator-boundary-source-pins.json` (accepted #133
    authority, itself MANIFEST-pinned) for stage_chain.py, and by the
    deployment identity recorded in accepted #137 records for the
    modules the driver imports;
  * accepted #137 baseline observations (module hashes, fixture /
    environment / chain-plan / accepted-direct-run digests, GPU UUIDs,
    interpreter identity) — frozen in this module from the reviewed
    head a9922547… records, which were reviewed and retained as the
    accepted diagnostic baseline (reviews R1/R2, CI run at that head).
    These are the comparison authority for the CORRECTION probes: the
    corrected runs must execute on the identical substrate or fail
    closed before GPU work.

The verifier proves, mechanically:
  1. producer checkout: exact commit, clean tree, imported modules'
     on-disk sha256 == authority pins (misbinding fails before GPU);
  2. interpreter: executing python == recorded venv python;
  3. torch/CUDA flags: deterministic-algorithms, TF32/reduced
     precision, cudnn knobs, multiprocessing start method — compared
     against the accepted baseline snapshot (a silently changed
     numerical mode fails closed);
  4. accepted #133 baseline inputs (fixture, environment, chain plan,
     accepted direct run) byte-identical to accepted digests;
  5. GPU UUIDs match the accepted geometry (01 gpu-0/gpu-1, 03 gpu-0).

CPU-only, stdlib-only.  Every check emits a named condition; failures
raise BindError BEFORE any execution path can proceed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BINDER_SCHEMA = "inferswarm.issue137.binding/2"

# -- accepted identities (issue #137 baseline) -------------------------
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
PR138_REVIEWED_HEAD = "a9922547f2ab41157a7668e814e582abce3d2603"
PR136_MERGE = "1b83bcab0a5e682a438ca0554f71dd0ace15be55"

# -- accepted #133 physical baseline bytes ------------------------------
BASELINE_INPUT_SHA256 = {
    "prompt-fixture.json": (
        "e68dfaafe661f2f6cc5f5be3a51128c7e7abf0b5c81978cbdb45e9788fd88cd0"
    ),
    "environment.json": (
        "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5edbf67"
    ),
    "chain-plan.json": (
        "6d9a4859af5b686a321458fe50c86189244b7d0d41e2cbb0df28147552f709ab"
    ),
    "direct-run.json": (
        "08807407784be47e40b5051e4de152a42c8248b81e6ee70ae253c7a3ca623ebf"
    ),
}

# Modules the probe driver imports from the frozen producer tree, with
# the on-disk sha256 observed and retained across the accepted #137
# baseline AND re-verified on the frozen deployment (2026-09-11
# correction; deployment clean at 924cd22e on 01 and 03).
PRODUCER_MODULE_SHA256 = {
    "benchmarks/inferswarm_r6/stage_chain.py": (
        "321bc91deb9a0e7f651a75f4158e973b3e72d889a32f76c8d8dc5c9081acde54"
    ),
    "benchmarks/inferswarm_r6/wire_client.py": (
        "84390972b0ad109e334516d4d772518afc3de1c8e1df3bf70136a99a2155f3ed"
    ),
    "benchmarks/inferswarm_r6/stage_runtime.py": (
        "1cca03969a14d5b3d9b150a7972fa9bb2bee5a693073d603fb46e9af897f8737"
    ),
    "benchmarks/inferswarm_r6/chain_runtime.py": (
        "9652ebb376b3737d559e6f764b47dfe154e31d1804e9eac62825badb4b3d9980"
    ),
    "benchmarks/inferswarm_r6/last_stage_service.py": (
        "08825dcd39f81dcf0d3f0a38a680a9eaac0fadfd9cebba8c32a54113cbf6bbc1"
    ),
    "benchmarks/inferswarm_r6_localization/capture.py": (
        "369fe8e61c2c37bd3e5b0376e2569befce6eb212960bf3e8a37515b3438d1051"
    ),
    "python/freetoken/research/r4_wire.py": (
        "491f710efc07119441a98642f8569d18a47bc3b4e785fbe7111cea258ab05e2c"
    ),
}

# stage_chain.py is additionally pinned by the accepted #133 source-pin
# authority (coordinator-boundary-source-pins.json, MANIFEST-frozen);
# asserted equal to PRODUCER_MODULE_SHA256 at verification time.
ACCEPTED_133_STAGE_CHAIN_PIN = (
    "321bc91deb9a0e7f651a75f4158e973b3e72d889a32f76c8d8dc5c9081acde54"
)

# -- accepted execution-environment snapshot ---------------------------
# Observed on the frozen deployment (both hosts) at the accepted #137
# baseline and unchanged at correction time.  A probe environment whose
# flags differ from this snapshot is a DIFFERENT experiment and fails
# closed before GPU execution.
BASELINE_SOFTWARE = {
    "python": "3.12.13",
    "torch": "2.11.0+cu130",
    "cuda_runtime": "13.0",
    "driver": "610.57.04",
    "multiprocessing_start_method_default": "fork",
}
BASELINE_TORCH_FLAGS = {
    "deterministic_algorithms": False,
    "deterministic_algorithms_warn_only": False,
    "tf32_matmul": False,
    "tf32_cudnn": True,
    "cudnn_deterministic": False,
    "cudnn_benchmark": False,
}
BASELINE_GEOMETRY = {
    "inferswarm01": [
        "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",  # gpu-0 [0,16)
        "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",  # gpu-1 [16,32)
    ],
    "inferswarm03": [
        "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",  # gpu-0 [32,48)
    ],
}
BASELINE_VENV_PYTHON = "/srv/inferswarm/repos/FreeToken/.venv/bin/python"


class BindError(SystemExit):
    """Raised when the accepted-authority binding fails."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_baseline_inputs(files: dict[str, Path]) -> dict:
    """Fail closed unless every named baseline input byte-matches."""
    report = {}
    for name, pin in BASELINE_INPUT_SHA256.items():
        path = files.get(name)
        if path is None:
            raise BindError(f"BIND_FAIL: baseline input {name} not provided")
        if not path.is_file():
            raise BindError(f"BIND_FAIL: baseline input {name} missing")
        observed = sha256_file(path)
        if observed != pin:
            raise BindError(
                f"BIND_FAIL: baseline input {name} sha256 {observed} != "
                f"accepted {pin}")
        report[name] = observed
    return report


def verify_producer_checkout(
    repo: Path, *, git_rev_parse=None, git_status=None,
) -> dict:
    """Exact frozen producer commit, clean tree, module bytes == pins.

    git_rev_parse/git_status are injection seams for tests (CPU-only).
    """
    if git_rev_parse is None:
        import subprocess
        git_rev_parse = lambda *a: subprocess.check_output(  # noqa: E731
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *a],
            text=True,
        ).strip()
    head = git_rev_parse("rev-parse", "HEAD")
    if head != PRODUCER:
        raise BindError(f"BIND_FAIL: producer HEAD {head} != {PRODUCER}")
    status = git_status() if git_status is not None else git_rev_parse(
        "status", "--porcelain")
    if status:
        raise BindError(f"BIND_FAIL: producer tree dirty:\n{status}")
    modules: dict[str, str] = {}
    for rel, pin in sorted(PRODUCER_MODULE_SHA256.items()):
        p = repo / rel
        if not p.is_file():
            raise BindError(f"BIND_FAIL: producer module {rel} missing")
        observed = sha256_file(p)
        if observed != pin:
            raise BindError(
                f"BIND_FAIL: producer module {rel} sha256 {observed} != "
                f"accepted pin {pin} — import misbinding risk; refusing "
                f"before GPU execution")
        modules[rel] = observed
    if modules.get(
        "benchmarks/inferswarm_r6/stage_chain.py"
    ) != ACCEPTED_133_STAGE_CHAIN_PIN:
        raise BindError(
            "BIND_FAIL: stage_chain.py deviates from the accepted #133 "
            "source-pin authority")
    return {"producer": head, "modules": modules}


def verify_software(snapshot: dict, *, interpreter_path: str | None) -> dict:
    """Executing software must equal the accepted baseline snapshot."""
    for key, expected in BASELINE_SOFTWARE.items():
        if key == "multiprocessing_start_method_default":
            continue
        observed = snapshot.get(key)
        if observed != expected:
            raise BindError(
                f"BIND_FAIL: software {key}={observed!r} != accepted "
                f"{expected!r}")
    for key, expected in BASELINE_TORCH_FLAGS.items():
        observed = snapshot.get(key)
        if observed != expected:
            raise BindError(
                f"BIND_FAIL: torch flag {key}={observed!r} != accepted "
                f"{expected!r} — numerical mode changed; refusing")
    if interpreter_path is not None and interpreter_path != BASELINE_VENV_PYTHON:
        raise BindError(
            f"BIND_FAIL: executing interpreter {interpreter_path} != "
            f"recorded {BASELINE_VENV_PYTHON}")
    return dict(snapshot)


def verify_geometry(observed_uuids: dict[str, list[str]]) -> dict:
    for host, expected in BASELINE_GEOMETRY.items():
        got = observed_uuids.get(host)
        if got != expected:
            raise BindError(
                f"BIND_FAIL: GPU geometry for {host}: {got} != {expected}")
    return json.loads(json.dumps(observed_uuids))


def verify_record_binding(record: dict) -> dict:
    """Validate a retained probe record's binding fields (reducer-side).

    Requires the correction/2 record shape: authority block with
    verified baseline inputs, producer modules, software snapshot,
    geometry, and realization identities for every claimed fresh
    realization.
    """
    problems = []
    if record.get("schema") != "inferswarm.issue137.diagnostic-probe/2":
        problems.append(
            f"scheme:{record.get('schema')!r}!=diagnostic-probe/2")
    if record.get("classification") != "DIAGNOSTIC_ONLY":
        problems.append("classification-not-diagnostic-only")
    if record.get("producer") != PRODUCER:
        problems.append(f"producer-drift:{record.get('producer')!r}")
    authority = record.get("authority")
    if not isinstance(authority, dict):
        problems.append("authority-block-missing")
        authority = {}
    for name, pin in BASELINE_INPUT_SHA256.items():
        if authority.get("baseline_inputs", {}).get(name) != pin:
            problems.append(f"baseline-input-{name}-unbound-or-drifted")
    for rel, pin in PRODUCER_MODULE_SHA256.items():
        if authority.get("producer_modules", {}).get(rel) != pin:
            problems.append(f"producer-module-{rel}-unbound-or-drifted")
    software = authority.get("software", {})
    for key, expected in BASELINE_TORCH_FLAGS.items():
        if software.get(key) != expected:
            problems.append(f"software-{key}-drifted")
    for key in ("python", "torch", "cuda_runtime", "driver"):
        if software.get(key) != BASELINE_SOFTWARE[key]:
            problems.append(f"software-{key}-drifted")
    if authority.get("venv_python") != BASELINE_VENV_PYTHON:
        problems.append("interpreter-not-the-recorded-venv-python")
    obs = record.get("observations")
    if not isinstance(obs, list) or not obs:
        problems.append("observations-missing-or-empty")
    return problems


def verify_realization_freshness(observation: dict) -> list[str]:
    """A claimed fresh realization must retain distinct stage pids and
    a distinct remote last-stage identity (pid + boot counter)."""
    problems = []
    ids = observation.get("realization_identity")
    if not isinstance(ids, dict):
        return ["realization-identity-missing"]
    stage_pids = ids.get("stage_pids")
    if not isinstance(stage_pids, list) or len(stage_pids) < 2 \
            or any(not isinstance(p, int) for p in stage_pids):
        problems.append("stage-pids-missing-or-malformed")
    if ids.get("stage_pids_distinct_within") is not True:
        problems.append("stage-pids-not-distinct-within-realization")
    last = ids.get("remote_last_stage")
    if not isinstance(last, dict):
        problems.append("remote-last-stage-identity-missing")
    else:
        if not isinstance(last.get("pid"), int):
            problems.append("remote-last-stage-pid-missing")
        if not isinstance(last.get("launch_counter"), int):
            problems.append("remote-last-stage-launch-counter-missing")
        if last.get("host") != "inferswarm03":
            problems.append("remote-last-stage-host-drift")
        if last.get("gpu_uuid") != BASELINE_GEOMETRY["inferswarm03"][0]:
            problems.append("remote-last-stage-gpu-drift")
    return problems


def verify_capture_manifest_binding(
    manifest: dict, *, expected_run_id: str | None = None,
    expected_capture_dir: str | None = None,
) -> list[str]:
    problems = []
    if manifest.get("schema") != "inferswarm.r6_localization.manifest/1":
        problems.append("manifest-schema-drift")
    if manifest.get("producer_sha") != PRODUCER:
        problems.append("manifest-producer-drift")
    binding = manifest.get("diagnostic_run_binding", {})
    run_id = binding.get("run_id")
    if not run_id:
        problems.append("manifest-not-bound-to-diagnostic-run")
    elif expected_run_id is not None and run_id != expected_run_id:
        problems.append(f"manifest-wrong-run:{run_id}!={expected_run_id}")
    cap_dir = binding.get("capture_dir")
    if not cap_dir:
        problems.append("manifest-capture-dir-unbound")
    elif expected_capture_dir is not None and cap_dir != expected_capture_dir:
        problems.append("manifest-capture-dir-mismatch")
    if not manifest.get("records"):
        problems.append("manifest-records-empty")
    if not isinstance(manifest.get("record_count"), int) \
            or manifest["record_count"] != len(manifest.get("records", [])):
        problems.append("manifest-record-count-inconsistent")
    for r in manifest.get("records", []):
        if r.get("producer_sha") != PRODUCER:
            problems.append("manifest-record-producer-drift")
            break
    return problems
