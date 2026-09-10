#!/usr/bin/env python3
"""Issue #133 — the ACCEPTED authorization bootstrap (review 5169777338).

TRUST MODEL — the defect this revision closes (review 5169777338 on head
424922d7d6c5a3c98e5c8fd59f8a51c817c7fa1f): the round-4 canonical command
still executed this file from the MUTABLE INVOCATION WORKING TREE first.
That outer process resolved ``origin/main``, selected the accepted
authority-bearing commit, materialized accepted Git bytes, launched the
accepted bootstrap, parsed its output, and returned the final verdict —
so a modified invocation-stage bootstrap could bypass every inner
protection and simply fabricate a passing verdict. The invocation-stage
bootstrap was part of the effective authorization root even though it
described itself as "non-authorizing".

The corrected architecture (this file, round 5):

- The CANONICAL physical prelaunch launch is SHELL + GIT ONLY before
  Python. The exact operator recipe is codified in
  ``METHODOLOGY-ARM-C-RETRY.md`` ("Canonical physical-prelaunch launch
  contract") and is executed VERBATIM by
  ``tests/test_issue133_prelaunch_bootstrap.py``: standard shell resolves
  ``refs/remotes/origin/main`` (fail closed when missing), selects the
  newest accepted commit carrying the current physical-campaign
  authority document with ``git log -1``/``git rev-parse`` (fail closed
  when the authority path has no accepted history), extracts
  ``scripts/issue133_physical_prelaunch_gate.py`` from THAT commit with
  ``git show`` into a fresh ``mktemp -d`` directory (fail closed when
  the blob is missing, when the target is not a regular non-symlink
  file, or when the extracted bytes' sha256 differs from the selected
  Git blob), and only then executes::

      python3 -I -S <extracted-bootstrap> --accepted-bootstrap --repo <repository>

- NO Python file read from the mutable working tree executes before the
  accepted bootstrap. This module — the bytes Git itself returned — is
  the FIRST Python executed for the physical prelaunch decision.

- WORKING-TREE INVOCATION FAILS CLOSED. When this file detects that it
  is executing from inside a Git working tree (``git rev-parse --show-
  toplevel`` around the executing file succeeds and contains it), or
  when it is invoked without the ``--accepted-bootstrap`` flag, it
  rejects with instructions to use the canonical Git-rooted launcher
  and exits nonzero. Direct ``python scripts/issue133_physical_
  prelaunch_gate.py`` from a checkout can NEVER produce an
  authoritative PASS.

- The accepted bootstrap verifies its OWN bytes equal the accepted Git
  blob at the resolved authority commit before evaluating anything
  else (an extracted-but-tampered or replaced/symlinked copy fails
  closed), then materializes that commit's COMPLETE tree via
  ``git archive``, byte-binds the COMPLETE pre-execution closure —
  every gate-tooling file PLUS this bootstrap — against the accepted
  blobs, and executes the pre-execution gate from the materialization
  only, in a subprocess whose PYTHONPATH/PYTHONHOME/PYTHONSTARTUP/
  PYTHONUSERBASE/PYTHONEXECUTABLE/PYTHONWARNINGS are scrubbed.

- The emitted verdict proves the execution origin MECHANICALLY: the
  observed ``origin/main`` SHA, the accepted authority-bearing commit,
  ``source_mode = accepted_git_materialization``, the accepted bootstrap
  Git blob identity AND the actually-executed bootstrap sha256 (required
  equal), the sha256 of every gate file actually executed with the
  accepted blob sha256 it must equal, the exact execution-freeze
  identity, the campaign ID, the r5a static-plan schema/digest, the
  Arm-B participant-plan and chain-plan digests, the canonical
  environment identity, and the real-builder verdict.

Adversarial property (proven by tests/test_issue133_prelaunch_bootstrap.py):
a working-tree ``scripts/issue133_physical_prelaunch_gate.py`` replaced
with hostile Python — one that never invokes Git, prints a structurally
valid PASS verdict, writes an execution marker, and exits 0 (or exits 0
immediately with no output) — can NEVER affect the canonical launch:
the launcher extracts the bootstrap bytes from the Git object database
and the hostile file is never executed.

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
#: like every other closure member — the executed bootstrap's bytes
#: must equal this path's accepted blob before anything evaluates)
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
#: into the materialized interpreter
_SCRUBBED_ENV_KEYS = frozenset({
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "PYTHONEXECUTABLE", "PYTHONWARNINGS",
})

_VERDICT_SCHEMA = "inferswarm.issue133.physical-prelaunch-bootstrap/2"

_CANONICAL_LAUNCHER_INSTRUCTIONS = (
    "Working-tree invocation of the physical prelaunch bootstrap is "
    "NON-AUTHORIZING (maintainer review 5169777338): the first Python "
    "executed for the physical prelaunch decision must come directly "
    "from accepted Git history, not from the mutable working tree. Use "
    "the canonical Git-rooted launcher codified in "
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "METHODOLOGY-ARM-C-RETRY.md ('Canonical physical-prelaunch launch "
    "contract'): resolve the accepted authority-bearing commit from "
    "refs/remotes/origin/main with git log/rev-parse, extract "
    f"{BOOTSTRAP_REL_PATH} from THAT commit with git show into a fresh "
    "mktemp directory, verify the extracted bytes equal the selected "
    "Git blob, then execute `python3 -I -S <extracted-bootstrap> "
    "--accepted-bootstrap --repo <repository>`.")


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


def executing_working_tree_root() -> Path | None:
    """The toplevel of the Git working tree this file is executing
    from, or None when the executing file is not inside any working
    tree (a ``git show`` extraction or a ``git archive``
    materialization in a fresh temporary directory — the only
    authorization-capable execution origins)."""
    here = Path(__file__).resolve()
    probe = subprocess.run(
        ["git", "-C", str(here.parent), "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if probe.returncode != 0:
        return None
    top = Path(probe.stdout.decode(errors="replace").strip())
    if not top.is_absolute():
        return None
    try:
        here.relative_to(top)
    except ValueError:
        return None
    return top


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
    """The accepted-bootstrap authorization body. ONLY reachable when
    this file's own bytes have been extracted/materialized from the
    accepted Git object database by the canonical launcher (the
    working-tree invocation guard in ``main`` rejects everything
    else); step 0 below re-proves that mechanically."""
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

    # ---- 0. the EXECUTING bootstrap's bytes must equal the accepted
    # ----    blob (an extracted-but-tampered, replaced, or symlinked
    # ----    copy fails closed BEFORE any authorization runs) ------
    executing_bytes = Path(__file__).resolve().read_bytes()
    executing_sha = _sha256_bytes(executing_bytes)
    accepted_bootstrap_bytes = _accepted_blob(
        repo, commit, BOOTSTRAP_REL_PATH)
    if accepted_bootstrap_bytes is None:
        _fail(
            verdict,
            f"no accepted blob at {BOOTSTRAP_REL_PATH} in authority "
            f"commit {commit}; the executing bootstrap cannot prove "
            "its bytes are accepted history — failing closed")
    accepted_bootstrap_sha = _sha256_bytes(accepted_bootstrap_bytes)
    verdict["bootstrap_execution"] = {
        "executed_path": str(Path(__file__).resolve()),
        "executed_sha256": executing_sha,
        "accepted_blob_sha256": accepted_bootstrap_sha,
        "equal": executing_sha == accepted_bootstrap_sha,
        "requirement": (
            "accepted bootstrap bytes == executed bootstrap bytes "
            "(review 5169777338)"),
    }
    if executing_sha != accepted_bootstrap_sha:
        _fail(
            verdict,
            f"the EXECUTING bootstrap bytes (sha256 {executing_sha}) "
            f"are not the accepted blob at {BOOTSTRAP_REL_PATH} in "
            f"authority commit {commit} (sha256 "
            f"{accepted_bootstrap_sha}); only Git-materialized "
            "accepted bytes may evaluate authorization — failing "
            "closed")

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

        # ---- identity fields, taken from the accepted gate verdict
        # ---- itself (never from working-tree code)
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

    # ---- working-tree invocation FAILS CLOSED (review 5169777338) --
    working_tree = executing_working_tree_root()
    if working_tree is not None:
        print(
            "PHYSICAL_PRELAUNCH_GATE_REJECT: this bootstrap is "
            f"executing from the mutable repository working tree at "
            f"{working_tree}; working-tree invocation is "
            "NON-AUTHORIZING. " + _CANONICAL_LAUNCHER_INSTRUCTIONS,
            file=sys.stderr)
        return 1
    if not args.accepted_bootstrap:
        print(
            "PHYSICAL_PRELAUNCH_GATE_REJECT: the invocation-stage "
            "loader mode has been REMOVED (maintainer review "
            "5169777338) — an outer working-tree process that "
            "resolves, materializes, launches, and parses the "
            "accepted bootstrap could fabricate the final verdict. "
            "The authorization-capable mode (--accepted-bootstrap) "
            "is intended ONLY for the Git-materialized bootstrap "
            "extracted by the canonical launcher. "
            + _CANONICAL_LAUNCHER_INSTRUCTIONS,
            file=sys.stderr)
        return 1

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
    verdict = run_prelaunch_gate(repo, args.keep_materialization)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
