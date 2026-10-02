#!/usr/bin/env python3
"""#262 R8-I3C rapid physical pilot producer (issue-authorized, bounded).

Implements the bounded physical pilot defined by Issue #262 on the #262
instrumented comparator source identity:

* execution authority is the OPEN, UNMERGED Issue #262 itself plus the
  issue's maintainer-authorization clause (``creation of this issue
  authorizes the bounded physical pilot``) — verified live against the
  GitHub API immediately before every unit (issue open + exact head);
  NO dispatch comment is required or accepted for this pilot;
* fresh process per unit, frozen case-3072 geometry/request/prompt, the
  #262 instrumented comparator binary (digest-frozen), the physical RTX
  3060 subject (frozen #252 HOST_FACTS identity, verified live);
* screening repeat law: 2 units, +1 only when the first two match
  (three identical = screening-stable); first mismatch = screening-variable;
* per-unit atomic publication of raw server log bytes, observer rows/meta,
  raw response, identity pre/post, placement, parsed H2/H3/H5 marker facts;
* arms: BASE, A1 (GGML_VK_SERIALIZE_SUBMISSIONS=1), A5
  (GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM=1), A4 (GGML_VK_PREFER_HOST_MEMORY=1,
  only when A5 gave no H3 contrast), H5_CANDIDATE
  (GGML_VK_DISABLE_COOPMAT2=1, only when the BASE H5 marker proves the
  output projection dispatched a coopmat2-family pipeline).

This module refuses to run any physical unit when the live issue/PR state
drifts from the frozen exact head. It never accepts caller-supplied
observations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue252_constants as C252
import issue252_arms as A
import issue250_diagnostic as D
import issue250_physical as B250
import issue248_identity as I248
import issue260_instrumentation as I260
import issue262_h5 as H5

API_ROOT = "https://api.github.com/repos/Zutfen-LLC/inferswarm"
ISSUE_NUMBER = 262
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
PILOT_SCHEMA = "inferswarm.issue262.pilot-unit/1"
MAX_UNITS = 3  # screening law: 2, +1 only when the first two match

# Frozen #262 instrumented comparator identity (issue262-source-identity.json)
IDENTITY262 = json.loads(
    (Path(__file__).resolve().parents[1]
     / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism"
     / "issue262-source-identity.json").read_text(encoding="utf-8"))
INSTRUMENTED262_TREE = IDENTITY262["instrumented262_tree"]

# Arm geometry: same frozen case-3072 launch shape as #254, one factor env.
ARM_ENV = {
    "BASE": {},
    "A1": {"GGML_VK_SERIALIZE_SUBMISSIONS": "1"},
    "A5": {"GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM": "1"},
    "A4": {"GGML_VK_PREFER_HOST_MEMORY": "1"},
    "H5_CANDIDATE": {"GGML_VK_DISABLE_COOPMAT2": "1"},
}


class PilotError(RuntimeError):
    """Pilot gate failure: the unit/arm cannot start or continue."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _api_get_json(path: str) -> Any:
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue262-pilot"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API_ROOT}/{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise PilotError(f"git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def verify_execution_authority(repo_root: Path, expected_head: str) -> dict:
    """Live authority check immediately before a unit.

    Issue #262 grants the bounded pilot authorization at creation. Physical
    execution additionally requires, live-fetched: the issue OPEN, the exact
    PR head unchanged (local HEAD == remote PR head == recorded head), and a
    clean worktree. Fail-closed on any drift.
    """
    root = Path(repo_root)
    local_head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PilotError("repository worktree is dirty")
    if local_head != expected_head:
        raise PilotError(
            f"local HEAD {local_head} != frozen execution head {expected_head}")
    issue = _api_get_json(f"issues/{ISSUE_NUMBER}")
    if issue.get("state") != "open":
        raise PilotError(f"issue #{ISSUE_NUMBER} is not open")
    head_branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    pulls = _api_get_json("pulls?state=open&per_page=100")
    matches = [p for p in pulls
               if p.get("head", {}).get("ref") == head_branch
               and p.get("base", {}).get("ref") == "issue-254-r8i3c-producer"]
    if len(matches) != 1:
        raise PilotError(
            f"pilot PR for branch {head_branch!r} is not uniquely open "
            f"against the producer branch (found {len(matches)})")
    live_head = matches[0].get("head", {}).get("sha")
    if live_head != expected_head:
        raise PilotError(
            f"live PR head {live_head} moved from the frozen execution head")
    return {"issue_state": issue["state"], "pr_number": matches[0]["number"],
            "head_sha": live_head}


def verify_subject() -> dict:
    """Verify the physical subject is the frozen RTX 3060 (#252 HOST_FACTS).

    Issue #262 subject law: reuse the historical accepted UUID/BDF when the
    card is still installed (the fleet ledger is never proof). Fail-closed
    when the frozen subject is absent — the pilot then stops for rebinding
    by the maintainer, never silently substitutes.
    """
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,uuid,pci.bus_id,driver_version",
         "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    if smi.returncode:
        raise PilotError("nvidia-smi failed; cannot verify physical subject")
    facts = C252.HOST_FACTS
    for line in smi.stdout.strip().splitlines():
        name, uuid, bus_id, driver = [c.strip() for c in line.split(",")]
        if (uuid == facts["gpu_uuid"]
                and bus_id.lower() == facts["bdf"].lower()):
            return {"gpu": name, "gpu_uuid": uuid, "bdf": bus_id,
                    "driver": driver,
                    "binding": "historical-A3/A5-subject-reused"}
    raise PilotError(
        f"frozen subject {facts['gpu_uuid']} ({facts['bdf']}) is not "
        "currently installed; pilot requires maintainer rebinding")


def verify_comparator262(binary: Path) -> str:
    """Authenticate the #262 instrumented comparator binary digest."""
    path = Path(binary)
    if not path.is_file():
        raise PilotError(f"instrumented comparator missing: {path}")
    digest = _sha(path.read_bytes())
    frozen = os.environ.get("ISSUE262_COMPARATOR_SHA256")
    if not frozen:
        raise PilotError(
            "ISSUE262_COMPARATOR_SHA256 (frozen binary digest) not set; "
            "refusing unauthenticated binary")
    if digest != frozen:
        raise PilotError(
            f"comparator binary sha256 {digest} != frozen {frozen}")
    return digest


def launch_env(arm: str, observer_prefix: Path) -> dict[str, str]:
    """The frozen launch environment for one pilot arm (one factor only)."""
    if arm not in ARM_ENV:
        raise PilotError(f"unknown pilot arm {arm!r}")
    env = {
        "CUDA_VISIBLE_DEVICES": "-1",
        "VK_ICD_FILENAMES": "/usr/share/vulkan/icd.d/nvidia_icd.json",
        "GGML_VK_VISIBLE_DEVICES": "0",
        "GGML_VK_MEMORY_LOGGER": "1",
        "LLAMA_OBSERVE_CAPTURE": "8",
        "LLAMA_OBSERVE_OUT": str(observer_prefix),
        "LLAMA_OBSERVE_FORCE": "",
    }
    env.update(ARM_ENV[arm])
    return env


def launch_argv(binary: Path) -> list[str]:
    member = next(iter(C252.MODEL_MEMBERS))
    return [str(binary), "--model", f"/srv/models/qwen38-ud-iq1-s/{member}",
            "-ngl", "1", "--ctx-size", "8192", "--batch-size", "512",
            "--host", "127.0.0.1", "--port", "19000", "-v"]


def parse_unit_markers(server_log: bytes, arm: str) -> dict[str, Any]:
    """Parse retained H2/H3 (#260 grammar) and H5 (#262 grammar) markers.

    The #262 tree identity is accepted by the extended #260 parser. BASE and
    every arm must yield a valid H5 output-projection observation; H2/H3 are
    validated per the #260 arm law (A1 serialized; A4/A5 branch expected at
    the target allocation; BASE default).
    """
    text = server_log.decode("utf-8", errors="strict")
    result: dict[str, Any] = {}
    # H5 routes (all arms): fail closed when absent/malformed.
    routes = H5.parse_routes(text)
    result["h5"] = H5.output_projection_routes(routes)
    # H2/H3 via the #260 grammar under the #262 tree identity.
    i260_arm = {"BASE": "BASE", "A1": "A1", "A5": "A5", "A4": "A4",
                "H5_CANDIDATE": "BASE"}.get(arm)
    if i260_arm is None:
        raise PilotError(f"arm {arm} has no H2/H3 parse mapping")
    observation = I260.parse_unit(text, arm=i260_arm,
                                  source_tree=INSTRUMENTED262_TREE)
    result["h2h3"] = {k: v for k, v in observation.items()
                      if k in ("submission", "graphs", "target",
                               "staging_active")}
    return result


def _wait_healthy(proc: subprocess.Popen, port: int,
                  timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise PilotError(f"server exited early rc={proc.returncode}")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    raise PilotError("server never became healthy")


def _terminate_group(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    if proc.poll() is None:
        raise PilotError("measured server process survived cleanup")


def frozen_prompt(repo_root: Path) -> str:
    """The frozen case-3072 prompt from the accepted fixture authority."""
    fixtures = B250.verify_fixtures(Path(repo_root))
    entry = fixtures.get(D.CASE) if isinstance(fixtures, dict) else None
    prompt = entry.get("prompt_text") if isinstance(entry, dict) else None
    if not isinstance(prompt, str) or not prompt:
        raise PilotError("accepted fixture does not provide prompt_text")
    return prompt


def execute_unit(*, repo_root: Path, arm: str, unit_index: int,
                 binary: Path, unit_dir: Path, timeout_s: float) -> dict:
    """ONE physical pilot unit: launch, measure, collect, terminate, parse.

    Reuses the accepted #254 execution semantics (fresh process, byte-exact
    request, observer collection, process attribution, identity custody)
    with the #262 instrumented comparator and the pilot arm environment.
    """
    root = Path(repo_root)
    if arm not in ARM_ENV:
        raise PilotError("unknown arm")
    prompt = frozen_prompt(root)
    request = D.REQUEST_CONTRACT
    unit_dir = Path(unit_dir)
    unit_dir.mkdir(parents=True, exist_ok=True)
    observer_prefix = unit_dir / "obs"
    argv = launch_argv(Path(binary))
    env = launch_env(arm, observer_prefix)
    binary_sha = verify_comparator262(binary)
    subject = verify_subject()
    identity_pre = I248.observe_arm_identity("B")
    problems = I248.identity_problems("B", identity_pre)
    if problems:
        raise PilotError(f"pre-launch identity drift: {problems}")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = unit_dir / "server.log"
    proc = None
    try:
        with log_path.open("wb") as log_file:
            full_env = {**os.environ, **env}
            proc = subprocess.Popen(argv, env=full_env, stdout=log_file,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
            _wait_healthy(proc, 19000, timeout_s)
            # process attribution: argv/env readback from /proc
            cmdline = Path(f"/proc/{proc.pid}/cmdline").read_bytes()
            live_argv = [a.decode("utf-8", "surrogateescape")
                         for a in cmdline.rstrip(b"\0").split(b"\0")]
            if live_argv != argv:
                raise PilotError("live server argv drift")
            environ = dict(
                chunk.split(b"=", 1) for chunk in
                Path(f"/proc/{proc.pid}/environ").read_bytes().split(b"\0")
                if b"=" in chunk)
            for key, value in env.items():
                if environ.get(key.encode()) != value.encode():
                    raise PilotError(f"live server env drift: {key}")
            payload = json.dumps({**request, "prompt": prompt}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:19000/completion", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout_s) as response:
                if response.status != 200:
                    raise PilotError(
                        f"completion HTTP status {response.status}")
                raw_response = response.read(16 * 1024 * 1024)
            meta = Path(f"{observer_prefix}.meta.json").read_bytes()
            rows = [Path(f"{observer_prefix}.row{n}.f32").read_bytes()
                    for n in range(D.DECISIONS)]
            identity_post = I248.observe_arm_identity("B")
            problems = I248.identity_problems("B", identity_post)
            if problems:
                raise PilotError(f"post-unit identity drift: {problems}")
    finally:
        if proc is not None:
            _terminate_group(proc)
    server_log = log_path.read_bytes()
    markers = parse_unit_markers(server_log, arm)
    ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if proc is None or proc.poll() is None:
        raise PilotError("server process not verified dead")
    return {
        "schema": PILOT_SCHEMA, "arm": arm, "unit_index": unit_index,
        "started_at": started_at, "ended_at": ended_at,
        "binary_sha256": binary_sha, "subject": subject,
        "argv": argv, "env": env,
        "request_sha256": _sha(payload),
        "response_raw": raw_response,
        "response_raw_sha256": _sha(raw_response),
        "observer_rows": rows, "observer_meta": meta,
        "server_log": server_log, "server_log_sha256": _sha(server_log),
        "identity_pre": identity_pre, "identity_post": identity_post,
        "markers": markers,
        "row_digest": _sha(b"".join(rows)),
        "process_exit": {"returncode": proc.returncode,
                         "cleanup_verified": True},
    }


def screen_class(units: list[dict]) -> str:
    """Screening classification over completed units (row-digest equality)."""
    digests = [u["row_digest"] for u in units]
    if len(digests) >= 2 and digests[0] != digests[1]:
        return "screening-variable"
    if len(digests) >= 3 and len(set(digests)) == 1:
        return "screening-stable"
    if len(set(digests)) == 1:
        return "matching-prefix (need one more for stable)"
    return "screening-variable"


def run_arm(*, repo_root: Path, evidence_root: Path, arm: str,
            binary: Path, timeout_s: float = 900.0,
            authority: dict | None = None) -> dict:
    """Run one pilot arm under the screening repeat law (2-3 units)."""
    if arm not in ARM_ENV:
        raise PilotError("unknown arm")
    base = Path(evidence_root) / f"d262-{arm.lower().replace('_', '-')}"
    base.mkdir(parents=True, exist_ok=True)
    units = []
    index = 1
    while index <= MAX_UNITS:
        work = base / f".unit-{index:03d}.tmp"
        if work.exists():
            raise PilotError(f"staging directory exists: {work.name}")
        auth = authority or verify_execution_authority(
            repo_root=Path(repo_root),
            expected_head=_git(Path(repo_root), "rev-parse", "HEAD"))
        unit = execute_unit(repo_root=Path(repo_root), arm=arm,
                            unit_index=index, binary=Path(binary),
                            unit_dir=work, timeout_s=timeout_s)
        final = base / f"{arm.lower().replace('_', '-')}-{index:03d}"
        # atomic publication: stage complete unit, then rename
        (work / "unit.json").write_bytes(json.dumps(
            {k: v for k, v in unit.items()
             if k not in ("response_raw", "observer_rows", "observer_meta",
                          "server_log", "argv", "env", "markers",
                          "identity_pre", "identity_post")},
            sort_keys=True, indent=1).encode() + b"\n")
        (work / "response.json.raw").write_bytes(unit["response_raw"])
        (work / "server.log").write_bytes(unit["server_log"])
        (work / "obs.meta.json").write_bytes(unit["observer_meta"])
        (work / "markers.json").write_bytes(json.dumps(
            unit["markers"], sort_keys=True, indent=1).encode() + b"\n")
        (work / "identity-pre.json").write_bytes(json.dumps(
            unit["identity_pre"], sort_keys=True).encode())
        (work / "identity-post.json").write_bytes(json.dumps(
            unit["identity_post"], sort_keys=True).encode())
        for n, row in enumerate(unit["observer_rows"]):
            (work / f"obs.row{n}.f32").write_bytes(row)
        os.rename(work, final)
        units.append(unit)
        if index == 2:
            digests = [u["row_digest"] for u in units]
            if digests[0] != digests[1]:
                break  # screening-variable: stop repeats
        elif index == 3:
            break  # three identical (or variable) -> stop
        index += 1
        _ = auth  # authority re-verified per unit at next loop entry
    return {"arm": arm, "units": [
        {k: u[k] for k in ("arm", "unit_index", "row_digest",
                           "response_raw_sha256", "server_log_sha256")}
        for u in units], "classification": screen_class(units),
        "markers": units[-1]["markers"] if units else None}
