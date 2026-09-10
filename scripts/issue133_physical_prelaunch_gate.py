#!/usr/bin/env python3
"""Issue #133 — canonical physical pre-execution entrypoint: the
external Git-rooted bootstrap (maintainer review 5167622668).

TRUST MODEL — the defect this module closes (review 5167622668): the
round-2 gate-tooling closure was verified by the very working-tree
modules it was supposed to distrust. ``issue133_arm_c_retry_campaign``
imported ``issue129_arm_c_retry_core`` at module-import time, so the
code that established "the gate tooling equals accepted history" was
itself already unverified working-tree Python. A modified working-tree
campaign/#129 module could alter or bypass ``verify_gate_tooling_closure``
before the closure check ran.

This bootstrap is STDLIB/GIT-ONLY. It NEVER imports any repository
Python module — not the Issue-133 campaign code, not the Issue-129
methodology core, not the direct driver, canonical-environment, or
frozen-pins code — before OR after the accepted materialization
exists. Authorization is decided exclusively by code whose bytes come
from the accepted Git object database:

1. resolve ``refs/remotes/origin/main`` — the external trust root
   (a missing remote ref fails closed);
2. identify the accepted AUTHORITY-BEARING commit from that history:
   the oldest commit in accepted history carrying the NEWEST accepted
   blob at the fixed authority-document path (later-main semantics:
   a later accepted authority document legitimately redefines
   authority after review — its own freeze binding must then hold —
   while a later accepted commit that leaves the authority bytes
   unchanged keeps the SAME authority-bearing anchor);
3. materialize that commit's COMPLETE tree into a fresh temporary
   directory via ``git archive`` (an isolated accepted tree; never a
   checkout over the working tree);
4. byte-verify the COMPLETE pre-execution closure — every gate-tooling
   file PLUS this bootstrap itself — against the accepted blobs
   BEFORE executing any gate code;
5. execute the pre-execution gate from the materialization only, in a
   subprocess whose PYTHONPATH/PYTHONHOME/PYTHONSTARTUP/PYTHONUSERBASE
   are scrubbed so the materialized modules cannot accidentally
   resolve same-named working-tree modules;
6. emit a verdict that proves the execution origin MECHANICALLY: the
   sha256 of every gate file actually executed, and the accepted blob
   sha256 it must equal, the accepted authority commit, the observed
   origin/main SHA, the source mode, the exact execution-freeze
   identity, the r5a static-plan schema/digest, the canonical
   environment identity, and the real-builder verdict.

Working-tree copies of gate files are NEVER executed as
authorization authority. Their drift versus the accepted bytes is
REPORTED as a secondary defense-in-depth integrity check only — it
does not establish trust and does not by itself authorize anything.

Adversarial property (proven by tests/test_issue133_prelaunch_bootstrap.py):
a working-tree ``issue133_arm_c_retry_campaign.py`` or
``issue129_arm_c_retry_core.py`` whose
``verify_gate_tooling_closure`` returns success unconditionally (or
which bypasses the gate entirely) can NEVER cause a PASS — the
substituted module is never imported; the accepted Git-materialized
gate alone evaluates authorization.

CPU-only. No GPU, no model execution, no tokenizer work, no
participant-state mutation, no h109-* consumption, no Arm D.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import NoReturn

#: fixed accepted-evidence path of the physical-campaign authority
AUTHORITY_REL_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/physical-campaign-authority.json")

#: the external trust root
ACCEPTED_REMOTE_REF = "refs/remotes/origin/main"

#: the gate entrypoint executed from the accepted materialization
GATE_ENTRY_REL_PATH = "scripts/issue133_arm_c_retry_campaign.py"

#: this bootstrap's own repository path (bound to the accepted commit
#: like every other closure member — a working-tree copy that drifted
#: from the accepted bytes fails closed before anything executes)
BOOTSTRAP_REL_PATH = "scripts/issue133_physical_prelaunch_gate.py"

#: the COMPLETE physical-prelaunch closure: the gate-tooling closure
#: (campaign + dry-run + canonical-environment + direct-driver +
#: #129 core + #117 frozen pins) PLUS the bootstrap itself. Kept in
#: lockstep with ``GATE_TOOLING_CLOSURE`` in
#: scripts/issue133_arm_c_retry_campaign.py (which asserts the same
#: membership at import time); this module cannot import that one, so
#: tests assert the two constants agree.
PHYSICAL_PRELAUNCH_CLOSURE = (
    BOOTSTRAP_REL_PATH,
    "scripts/issue133_arm_c_retry_campaign.py",
    "scripts/issue133_real_builder_dry_run.py",
    "scripts/issue133_canonical_environment.py",
    "scripts/issue133_arm_c_retry_direct.py",
    "scripts/issue129_arm_c_retry_core.py",
    "scripts/issue117_arm_c_frozen_pins.py",
)

#: subprocess environment keys removed before executing the accepted
#: gate: anything able to inject a module-search path or startup code
#: into the materialized interpreter (review requirement: audit
#: subprocess/environment/PYTHONPATH behavior)
_SCRUBBED_ENV_KEYS = frozenset({
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "PYTHONEXECUTABLE", "PYTHONWARNINGS",
})

_VERDICT_SCHEMA = "inferswarm.issue133.physical-prelaunch-bootstrap/1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str,
         check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=check)


def _fail(verdict: dict, message: str) -> NoReturn:
    verdict["pass"] = False
    verdict["failure"] = message
    print(json.dumps(verdict, indent=2, sort_keys=True))
    print(
        f"PHYSICAL_PRELAUNCH_GATE_REJECT: {message}",
        file=sys.stderr)
    raise SystemExit(1)


def _accepted_blob(repo: Path, commit: str,
                   relative: str) -> bytes | None:
    """Exact blob bytes at ``commit:relative`` (raw; None when the
    path does not exist at that commit)."""
    completed = _git(
        repo, "show", f"{commit}:{relative}", check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout


def resolve_accepted_authority_commit(repo: Path) -> dict:
    """Identify the accepted AUTHORITY-BEARING commit from accepted
    Git history alone (never from working-tree bytes).

    - ``refs/remotes/origin/main`` must exist (fail closed);
    - the fixed authority path must have accepted history;
    - the NEWEST accepted blob at that path is the currently
      accepted authority document;
    - the anchor is the NEWEST accepted commit carrying that blob —
      the commit that introduced the currently accepted authority
      bytes (the anchor the closure binds to and the tree that is
      materialized).
    """
    ref = _git(
        repo, "rev-parse", "--verify", "--quiet",
        ACCEPTED_REMOTE_REF, check=False)
    if ref.returncode != 0 or not ref.stdout.strip():
        raise RuntimeError(
            f"{ACCEPTED_REMOTE_REF} is missing; the Git object "
            "database cannot prove accepted ancestry — failing "
            "closed before any physical launch")
    observed_main = ref.stdout.decode().strip()
    log = _git(
        repo, "log", ACCEPTED_REMOTE_REF, "--format=%H", "--",
        AUTHORITY_REL_PATH, check=False)
    if log.returncode != 0:
        raise RuntimeError(
            "accepted-history authority lookup failed in the Git "
            "object database")
    commits = log.stdout.decode().split()
    if not commits:
        raise RuntimeError(
            "no accepted commit carries the physical-campaign "
            "authority document; the authority must be reviewed and "
            "merged into accepted InferSwarm history before any "
            "correctness-bearing physical attempt")
    # newest-first: resolve each commit's blob id cheaply
    newest_blob = None
    authority_commit = None
    for commit in commits:
        blob = _git(
            repo, "rev-parse", "--quiet",
            f"{commit}:{AUTHORITY_REL_PATH}", check=False)
        if blob.returncode != 0 or not blob.stdout.strip():
            # history older than the path's creation — stop scanning
            break
        blob_id = blob.stdout.decode().strip()
        if newest_blob is None:
            newest_blob = blob_id
        if blob_id == newest_blob and authority_commit is None:
            authority_commit = commit
        elif blob_id != newest_blob:
            # an OLDER accepted authority document — everything
            # older is superseded history; the oldest commit
            # carrying the NEWEST blob has already been recorded
            break
    if authority_commit is None:  # pragma: no cover — defensive
        raise RuntimeError(
            "failed to identify the accepted authority-bearing commit")
    return {
        "observed_origin_main_sha": observed_main,
        "authority_blob_sha1": newest_blob,
        "accepted_authority_commit": authority_commit,
    }


def materialize_accepted_tree(repo: Path, commit: str,
                              destination: Path) -> None:
    """Materialize the COMPLETE accepted tree at ``commit`` into a
    fresh empty directory via ``git archive`` (Git plumbing; never a
    checkout over any working tree)."""
    tarball = destination.parent / "accepted-tree.tar"
    archive = _git(
        repo, "archive", "--format=tar", f"--output={tarball}", commit,
        check=False)
    if archive.returncode != 0:
        raise RuntimeError(
            f"git archive failed for accepted commit {commit}: "
            + archive.stderr.decode(errors="replace").strip())
    try:
        with tarfile.open(tarball, mode="r:") as archive_file:
            for member in archive_file.getmembers():
                member_path = (destination / member.name).resolve()
                if not member_path.is_relative_to(destination.resolve()):
                    raise RuntimeError(
                        "git archive contains a path outside the accepted "
                        "materialization; failing closed")
            archive_file.extractall(destination, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise RuntimeError(
            f"accepted-tree materialization failed: {error}") from error
    finally:
        tarball.unlink(missing_ok=True)


def verify_closure_bytes(repo: Path, commit: str,
                         materialization: Path) -> dict:
    """Byte-bind the COMPLETE physical-prelaunch closure (bootstrap
    included) to the accepted commit — verified on the MATERIALIZED
    files BEFORE any gate code executes. Missing blob, missing file,
    symlink, or a single-byte mismatch fails closed."""
    provenance: dict[str, dict] = {}
    problems: list[str] = []
    for relative in PHYSICAL_PRELAUNCH_CLOSURE:
        accepted_bytes = _accepted_blob(repo, commit, relative)
        if accepted_bytes is None:
            problems.append(
                f"no blob at {relative} in accepted authority commit "
                f"{commit}; the accepted tree does not carry the "
                "complete physical-prelaunch closure — failing closed")
            continue
        local = materialization / relative
        if local.is_symlink() or not local.is_file():
            problems.append(
                f"{relative} is not a regular non-symlink file in the "
                "accepted materialization")
            continue
        accepted_sha = _sha256_bytes(accepted_bytes)
        executed_sha = _sha256_bytes(local.read_bytes())
        if executed_sha != accepted_sha:
            problems.append(
                f"materialized {relative} sha256 {executed_sha} != "
                f"accepted blob sha256 {accepted_sha}")
            continue
        provenance[relative] = {
            "executed_sha256": executed_sha,
            "accepted_blob_sha256": accepted_sha,
            "equal": True,
        }
    if problems:
        raise RuntimeError(
            "PHYSICAL-PRELAUNCH CLOSURE FAILED against accepted "
            f"authority commit {commit}: " + "; ".join(problems))
    return provenance


def execute_accepted_gate(materialization: Path,
                          repo: Path) -> dict:
    """Execute the pre-execution gate from the accepted
    materialization ONLY, in a scrubbed-environment subprocess.

    The original repository is passed solely as the Git-history
    target (``--git-repo``) — the physical/working tree there is
    never consulted for code."""
    entry = materialization / GATE_ENTRY_REL_PATH
    if not entry.is_file():
        raise RuntimeError(
            f"accepted materialization lacks the gate entrypoint at "
            f"{GATE_ENTRY_REL_PATH}")
    env = {
        key: value for key, value in os.environ.items()
        if key not in _SCRUBBED_ENV_KEYS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(entry),
         "--verify-pre-execution-gate", "--git-repo", str(repo.resolve())],
        cwd=str(materialization), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=3600)
    stdout = completed.stdout.decode(errors="replace")
    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            "the accepted Git-materialized pre-execution gate "
            f"REJECTED (exit {completed.returncode}): "
            + (stderr or stdout).strip()[-2000:])
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "the accepted gate produced no parseable verdict; "
            "failing closed") from error


def working_tree_drift_report(repo: Path, commit: str) -> dict:
    """SECONDARY defense-in-depth check (never the root of trust):
    compare working-tree closure copies with the accepted blobs and
    report every drift. The working tree is never executed; drift
    here is surfaced for the operator, and the authorization verdict
    is unaffected because it comes exclusively from the accepted
    materialization."""
    drift: dict[str, dict] = {}
    for relative in PHYSICAL_PRELAUNCH_CLOSURE:
        accepted_bytes = _accepted_blob(repo, commit, relative)
        if accepted_bytes is None:
            continue
        working = repo / relative
        if working.is_symlink() or not working.is_file():
            drift[relative] = {
                "working_tree_sha256": None,
                "accepted_blob_sha256": _sha256_bytes(accepted_bytes),
                "note": "missing or symlinked in the working tree",
            }
            continue
        working_sha = _sha256_bytes(working.read_bytes())
        accepted_sha = _sha256_bytes(accepted_bytes)
        if working_sha != accepted_sha:
            drift[relative] = {
                "working_tree_sha256": working_sha,
                "accepted_blob_sha256": accepted_sha,
            }
    return drift


def run_prelaunch_gate(repo: Path,
                       keep_materialization: bool = False) -> dict:
    """The canonical physical pre-execution entrypoint body."""
    verdict: dict = {
        "schema": _VERDICT_SCHEMA,
        "gate": "ACCEPTED_GIT_MATERIALIZATION_PRE_EXECUTION_GATE",
        "trust_root": f"{ACCEPTED_REMOTE_REF} (Git object database)",
        "source_mode": "accepted_git_materialization",
        "repository": str(repo.resolve()),
    }
    # ---- 1/2. accepted history resolution (Git plumbing only) -----
    try:
        resolution = resolve_accepted_authority_commit(repo)
    except RuntimeError as error:
        _fail(verdict, str(error))
    commit = resolution["accepted_authority_commit"]
    verdict.update({
        "accepted_authority_commit": commit,
        "origin_main_observed_sha":
            resolution["observed_origin_main_sha"],
        "authority_document_blob_sha1":
            resolution["authority_blob_sha1"],
    })

    # ---- 3. materialize the accepted tree (isolated; git archive) --
    materialization_parent = Path(
        tempfile.mkdtemp(prefix="issue133-accepted-tree-"))
    materialization = materialization_parent / "tree"
    materialization.mkdir()
    try:
        try:
            materialize_accepted_tree(repo, commit, materialization)
        except RuntimeError as error:
            _fail(verdict, str(error))
        verdict["materialization"] = {
            "method": "git archive (isolated temporary tree)",
            "commit": commit,
            "root": str(materialization),
        }

        # ---- 4. byte-bind the closure BEFORE executing anything ----
        try:
            provenance = verify_closure_bytes(
                repo, commit, materialization)
        except RuntimeError as error:
            _fail(verdict, str(error))
        verdict["gate_tooling_execution_provenance"] = provenance

        # the executing bootstrap's own provenance (the bootstrap is
        # the one closure member that runs from the invocation site;
        # report its identity against the accepted blob — a drifted
        # working-tree bootstrap is surfaced here and in the drift
        # report, never silently trusted)
        bootstrap_executed = _sha256_bytes(
            Path(__file__).resolve().read_bytes())
        bootstrap_accepted = provenance.get(
            BOOTSTRAP_REL_PATH, {}).get("accepted_blob_sha256")
        verdict["bootstrap_execution"] = {
            "executed_path": str(Path(__file__).resolve()),
            "executed_sha256": bootstrap_executed,
            "accepted_blob_sha256": bootstrap_accepted,
            "equal": bootstrap_executed == bootstrap_accepted,
        }

        # ---- 5. execute the gate from accepted bytes only ----------
        try:
            gate_verdict = execute_accepted_gate(
                materialization, repo)
        except RuntimeError as error:
            _fail(verdict, str(error))
        if gate_verdict.get("accepted_authority_commit") != commit:
            _fail(
                verdict,
                "the accepted-materialized gate resolved a DIFFERENT "
                f"authority commit ({gate_verdict.get('accepted_authority_commit')!r} "
                f"!= bootstrap resolution {commit!r}); failing closed")
        verdict["pre_execution_gate_verdict"] = gate_verdict

        # ---- requirement-6 identity fields, taken from the accepted
        # ---- gate verdict itself (never from working-tree code)
        binding = gate_verdict.get("execution_freeze_binding", {})
        dry = gate_verdict.get("real_builder_dry_run", {})
        verdict["execution_freeze_identity"] = binding.get(
            "authorized_execution_freeze_identity")
        verdict["campaign_id"] = binding.get("campaign_id")
        bound_fields = dry.get("freeze_bound_verdict_fields", {})
        verdict["r5a_static_plan_schema"] = bound_fields.get(
            "r5a_static_plan_schema")
        verdict["r5a_static_plan_digest"] = bound_fields.get(
            "r5a_static_plan_digest")
        verdict["arm_b_participant_plan_digest"] = bound_fields.get(
            "arm_b_participant_plan_digest")
        verdict["chain_plan_digest"] = bound_fields.get(
            "chain_plan_digest")
        verdict["environment_canonical_sha256"] = dry.get(
            "environment_canonical_sha256")
        verdict["real_builder_verdict"] = dry
        if not verdict["execution_freeze_identity"] or \
                not verdict["r5a_static_plan_digest"] or \
                not verdict["environment_canonical_sha256"]:
            _fail(
                verdict,
                "the accepted gate verdict lacks required identity "
                "fields (freeze identity / r5a digest / environment "
                "identity); failing closed")

        # ---- secondary working-tree drift report (defense in depth)
        verdict["working_tree_drift"] = working_tree_drift_report(
            repo, commit)
        verdict["working_tree_drift_note"] = (
            "secondary integrity check only: working-tree closure "
            "copies are never executed; authorization comes "
            "exclusively from the accepted Git materialization")

        verdict["pass"] = True
        return verdict
    finally:
        if not keep_materialization:
            import shutil
            shutil.rmtree(materialization_parent, ignore_errors=True)


def launch_accepted_bootstrap(repo: Path,
                              keep_materialization: bool = False) -> dict:
    """External, non-authorizing Git bootstrap.

    This loader does only Git-rooted authority-tree selection and byte-checks
    the accepted bootstrap before starting it.  It never evaluates authority,
    imports a gate module, or emits a passing authorization verdict.  The
    first Python code that performs authorization is this same script from the
    accepted materialization, under ``-I -S``.
    """
    loader_verdict = {
        "schema": _VERDICT_SCHEMA,
        "gate": "ACCEPTED_GIT_MATERIALIZATION_PRE_EXECUTION_GATE",
        "trust_root": f"{ACCEPTED_REMOTE_REF} (Git object database)",
        "source_mode": "accepted_git_materialization",
        "repository": str(repo.resolve()),
    }
    try:
        resolution = resolve_accepted_authority_commit(repo)
    except RuntimeError as error:
        _fail(loader_verdict, str(error))
    commit = resolution["accepted_authority_commit"]
    parent = Path(tempfile.mkdtemp(prefix="issue133-bootstrap-loader-"))
    materialization = parent / "tree"
    materialization.mkdir()
    try:
        materialize_accepted_tree(repo, commit, materialization)
        accepted_bootstrap = materialization / BOOTSTRAP_REL_PATH
        expected = _accepted_blob(repo, commit, BOOTSTRAP_REL_PATH)
        if expected is None or accepted_bootstrap.is_symlink() \
                or not accepted_bootstrap.is_file() \
                or _sha256_bytes(accepted_bootstrap.read_bytes()) != \
                _sha256_bytes(expected):
            _fail(loader_verdict,
                  "accepted bootstrap bytes could not be materialized and "
                  "verified before authorization")
        env = {key: value for key, value in os.environ.items()
               if key not in _SCRUBBED_ENV_KEYS}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(accepted_bootstrap),
             "--accepted-bootstrap", "--repo", str(repo.resolve())],
            cwd=str(materialization), env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=3600)
        if completed.returncode != 0:
            _fail(loader_verdict,
                  "the accepted Git-materialized authorization bootstrap "
                  f"REJECTED (exit {completed.returncode}): "
                  + (completed.stderr.decode(errors="replace").strip()
                     or completed.stdout.decode(errors="replace").strip())[-2000:])
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            _fail(loader_verdict,
                  "the accepted authorization bootstrap produced no "
                  "parseable verdict; failing closed")
            raise AssertionError("unreachable") from error
    finally:
        if not keep_materialization:
            shutil.rmtree(parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo", type=Path, default=None,
        help="the InferSwarm Git repository whose "
             f"{ACCEPTED_REMOTE_REF} / object database is the trust "
             "root (default: the repository containing this script)")
    parser.add_argument(
        "--accepted-bootstrap", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--keep-materialization", action="store_true",
        help="retain the accepted materialization tree for "
             "inspection (path recorded in the verdict)")
    args = parser.parse_args(argv)
    repo = args.repo
    if repo is None:
        repo = Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists() and not (
            repo / ".git").is_file():
        print(
            f"PHYSICAL_PRELAUNCH_GATE_REJECT: {repo} is not a Git "
            "repository; the Git object database is the trust root",
            file=sys.stderr)
        return 1
    if args.accepted_bootstrap:
        verdict = run_prelaunch_gate(repo, args.keep_materialization)
    else:
        verdict = launch_accepted_bootstrap(repo, args.keep_materialization)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
