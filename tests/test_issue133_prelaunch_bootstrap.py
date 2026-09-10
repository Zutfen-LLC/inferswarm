"""Issue #133 — canonical Git-rooted launcher tests (review 5169777338).

The round-5 defect: the canonical command still executed
scripts/issue133_physical_prelaunch_gate.py from the MUTABLE INVOCATION
WORKING TREE first — an outer working-tree process that resolved the
authority commit, materialized accepted Git bytes, launched the
accepted bootstrap, parsed its output, and returned the final verdict,
so a modified invocation-stage bootstrap could fabricate a PASS. These
tests prove the corrected architecture:

- the CANONICAL physical prelaunch launch is the shell+Git recipe
  codified VERBATIM in METHODOLOGY-ARM-C-RETRY.md ("Canonical
  physical-prelaunch launch contract"): standard shell resolves
  refs/remotes/origin/main, selects the accepted authority-bearing
  commit with git log/rev-parse, extracts the bootstrap blob from THAT
  commit with git show into a fresh mktemp directory, re-hashes the
  extracted bytes against the selected Git blob (git hash-object), and
  only then executes `python3 -I -S <bootstrap> --accepted-bootstrap
  --repo <repository>`. Every test invocation runs that exact doc
  snippet through bash — no Python read from the working tree executes
  before the accepted bootstrap;

- ADVERSARIAL OUTER-BOOTSTRAP controls (the review's mandatory case):
  the working-tree scripts/issue133_physical_prelaunch_gate.py is
  replaced with hostile Python that never invokes Git, writes an
  execution marker, prints a structurally valid PASS verdict and exits
  0 (and a second variant that exits 0 immediately with no output).
  The CANONICAL launch must behave normally: the hostile file is never
  executed (no marker), the authorization bootstrap path is the
  Git-extracted accepted file, the verdict records the accepted
  authority commit and accepted bootstrap hash, every executed
  authorization byte equals accepted Git, and PASS occurs only because
  the accepted gate itself passes;

- WORKING-TREE INVOCATION FAILS CLOSED: the real bootstrap executed
  directly from a repository checkout rejects with launcher
  instructions — a checkout invocation can never produce an
  authoritative PASS;

- NEGATIVE GIT-ROOT controls: a missing refs/remotes/origin/main, an
  authority path with no accepted history, a missing accepted
  bootstrap blob, tampered extracted bytes, a symlinked extraction,
  a failing accepted gate, and a malformed accepted-gate verdict all
  reject; the real pre-merge repository rejects; later unrelated
  accepted main commits remain compatible.

CPU-only: no GPU, no model execution, no participant-state mutation,
no h109-* consumption, no Arm D.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/issue133_physical_prelaunch_gate.py"
METHODOLOGY = (
    ROOT / "docs/implementation"
    / "r6-successor-dense-full-integration-117"
    / "METHODOLOGY-ARM-C-RETRY.md")
AUTHORITY_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/physical-campaign-authority.json")
FREEZE_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/execution-freeze.json")

#: markers HOSTILE working-tree files leave behind if ever executed
_OUTER_MARKER = "HOSTILE_OUTER_BOOTSTRAP_WAS_EXECUTED"
_INNER_MARKER = "WORKING_TREE_GATE_WAS_EXECUTED"

_VERDICT_SCHEMA = "inferswarm.issue133.physical-prelaunch-bootstrap/2"


def canonical_launcher_snippet() -> str:
    """The EXACT shell recipe from the methodology doc's 'Canonical
    physical-prelaunch launch contract' section (executed verbatim,
    with only the documented REPO= parameterization point bound to the
    fixture repository)."""
    text = METHODOLOGY.read_text()
    heading = "## Canonical physical-prelaunch launch contract"
    start = text.index(heading)
    fence_start = text.index("```sh", start)
    fence_end = text.index("```", fence_start + len("```sh"))
    return text[fence_start + len("```sh"):fence_end].lstrip("\n")


def run_canonical_launch(repo: Path,
                         env: dict | None = None,
                         timeout: int = 900
                         ) -> subprocess.CompletedProcess:
    """Execute the doc's canonical launcher snippet through bash with
    REPO bound to ``repo`` (the snippet's only parameterization
    point)."""
    snippet = canonical_launcher_snippet()
    lines = snippet.split("\n")
    assert lines[0].startswith("REPO="), lines[0]
    lines[0] = f"REPO={repo}"
    script = "\n".join(lines)
    with tempfile.NamedTemporaryFile(
            "w", suffix=".sh", delete=False) as handle:
        handle.write(script)
        path = handle.name
    try:
        return subprocess.run(
            ["bash", path], capture_output=True, text=True,
            env=env or dict(os.environ), timeout=timeout)
    finally:
        os.unlink(path)


def _git(repo: Path, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env, check=True)


def _scratch_env(tmp: Path) -> dict:
    return dict(
        os.environ,
        GIT_AUTHOR_NAME="Issue 133 Launcher Control",
        GIT_AUTHOR_EMAIL="issue133-launcher@example.invalid",
        GIT_COMMITTER_NAME="Issue 133 Launcher Control",
        GIT_COMMITTER_EMAIL="issue133-launcher@example.invalid",
        HOME=os.environ.get("HOME", str(tmp)))


class _AcceptedFixture:
    """An accepted-history Git repository whose authority-bearing
    commit carries the COMPLETE corrected closure, the retained
    evidence, and a regenerated /7 execution freeze bound into the
    authority document.

    Ordering mirrors production: code committed first, then the real
    unmocked builder dry run executed and the freeze regenerated from
    the working fixture repository, then history amended so the
    authority-bearing commit carries the bound freeze bytes.
    """

    def __init__(self, tmp: str):
        import shutil
        self.tmp = Path(tmp)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        shutil.copytree(ROOT / "scripts", self.repo / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        area = ROOT / "docs/implementation"
        shutil.copytree(
            area / "r6-successor-dense-full-integration-117",
            self.repo / "docs/implementation"
            / "r6-successor-dense-full-integration-117",
            ignore=shutil.ignore_patterns("__pycache__"))
        self.env = _scratch_env(self.tmp)
        self.env.pop("PYTHONPATH", None)
        _git(self.repo, "init", "-q", "-b", "main", env=self.env)
        _git(self.repo, "add", ".", env=self.env)
        _git(self.repo, "commit", "-q", "-m", "accepted closure",
             env=self.env)
        # the real unmocked builder dry run + freeze regeneration from
        # the fixture repository bytes (production ordering)
        regenerate = subprocess.run(
            [sys.executable,
             str(self.repo / "scripts"
                 / "issue133_regenerate_corrected_freeze.py")],
            cwd=str(self.repo), capture_output=True, text=True,
            env=self.env)
        assert regenerate.returncode == 0, regenerate.stderr
        # fold the regenerated authority+freeze into the accepted
        # history: the authority-bearing commit must carry them
        _git(self.repo, "add", str(AUTHORITY_REL), env=self.env)
        _git(self.repo, "add", str(FREEZE_REL), env=self.env)
        _git(self.repo, "commit", "--amend", "--no-edit", "-q",
             env=self.env)
        self.accepted_head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=self.env,
            check=True).stdout.strip()
        _git(self.repo, "update-ref", "refs/remotes/origin/main",
             self.accepted_head, env=self.env)

    # -- working-tree substitutions ----------------------------------
    def substitute(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.write_text(text)

    def amend_accepted(self, message: str) -> None:
        """Fold current working-tree bytes into the accepted history
        (the authority-bearing commit) and re-point origin/main."""
        _git(self.repo, "add", "-A", env=self.env)
        _git(self.repo, "commit", "--amend", "--no-edit", "-q",
             "-m", message, env=self.env)
        self.accepted_head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=self.env,
            check=True).stdout.strip()
        _git(self.repo, "update-ref", "refs/remotes/origin/main",
             self.accepted_head, env=self.env)

    def launch(self) -> subprocess.CompletedProcess:
        return run_canonical_launch(self.repo, env=self.env)

    def verdict_of(self, result: subprocess.CompletedProcess) -> dict:
        payload = json.loads(result.stdout)
        assert payload["schema"] == _VERDICT_SCHEMA, payload["schema"]
        return payload


#: a HOSTILE invocation-stage (outer) bootstrap: never invokes Git,
#: writes an execution marker at the repository root, prints a
#: structurally valid PASS verdict, and exits 0
_HOSTILE_OUTER_BOOTSTRAP = f'''\
import json
import sys
from pathlib import Path

Path(__file__).resolve().parents[1].joinpath("{_OUTER_MARKER}").write_text(
    "hostile invocation-stage bootstrap executed as authority\\n")

print(json.dumps({{
    "schema": "inferswarm.issue133.physical-prelaunch-bootstrap/2",
    "gate": "ACCEPTED_GIT_MATERIALIZATION_PRE_EXECUTION_GATE",
    "trust_root": "refs/remotes/origin/main (Git object database)",
    "source_mode": "accepted_git_materialization",
    "accepted_authority_commit": "{"d" * 40}',
    "origin_main_observed_sha": "{"d" * 40}',
    "execution_freeze_identity": "{"f" * 64}',
    "campaign_id": "spoofed",
    "r5a_static_plan_digest": "sha256:{"f" * 64}",
    "environment_canonical_sha256": "{"f" * 64}",
    "bootstrap_execution": {{
        "executed_sha256": "{"f" * 64}',
        "accepted_blob_sha256": "{"f" * 64}',
        "equal": True}},
    "working_tree_drift": {{}},
    "pass": True}}, indent=2, sort_keys=True))
sys.exit(0)
'''

#: a hostile outer bootstrap that exits 0 immediately with no output
_SILENT_HOSTILE_OUTER_BOOTSTRAP = (
    "import sys\n"
    "from pathlib import Path\n"
    f"Path(__file__).resolve().parents[1].joinpath(\"{_OUTER_MARKER}\")"
    ".write_text('silent hostile outer bootstrap executed\\n')\n"
    "sys.exit(0)\n")


class CanonicalLauncherControls(unittest.TestCase):
    """The canonical physical prelaunch launch executes the doc's
    shell+Git recipe; no working-tree Python may execute before the
    accepted bootstrap."""

    def test_control_passing_gate_in_accepted_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            result = fixture.launch()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            self.assertEqual(
                verdict["source_mode"],
                "accepted_git_materialization")
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)
            self.assertEqual(
                verdict["origin_main_observed_sha"],
                fixture.accepted_head)
            # execution-origin provenance: EVERY executed closure file
            # hash equals its accepted blob hash
            provenance = verdict["gate_tooling_execution_provenance"]
            self.assertEqual(len(provenance), 7)
            for relative, entry in provenance.items():
                self.assertTrue(entry["equal"], relative)
                self.assertEqual(
                    entry["executed_sha256"],
                    entry["accepted_blob_sha256"], relative)
            self.assertIn(
                "scripts/issue133_physical_prelaunch_gate.py",
                provenance)
            # the authorization bootstrap executed the GIT-EXTRACTED
            # accepted file, never the invocation checkout's copy
            bootstrap_execution = verdict["bootstrap_execution"]
            self.assertTrue(bootstrap_execution["equal"])
            executed = Path(bootstrap_execution["executed_path"])
            self.assertNotEqual(executed.resolve(), BOOTSTRAP.resolve())
            self.assertNotEqual(
                executed.resolve(),
                (fixture.repo / "scripts"
                 / "issue133_physical_prelaunch_gate.py").resolve())
            self.assertEqual(executed.name, "bootstrap.py")
            # identity fields required by the review, taken from the
            # accepted gate verdict itself
            authority = json.loads(
                (fixture.repo / AUTHORITY_REL).read_text())
            self.assertEqual(
                verdict["execution_freeze_identity"],
                authority["campaigns"]
                ["armc-retry-afcdc4428f95d50c"]
                ["execution_freeze_identity"])
            self.assertEqual(
                verdict["campaign_id"],
                "armc-retry-afcdc4428f95d50c")
            self.assertEqual(
                verdict["r5a_static_plan_digest"],
                "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea15415"
                "a4d904bf666d020cdc625")
            self.assertEqual(
                verdict["arm_b_participant_plan_digest"],
                "sha256:8646e00ce53e3aac4c163ca35231fa82471815386"
                "d71266a0d0962eea565bdad")
            self.assertEqual(
                verdict["chain_plan_digest"],
                "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a"
                "20bcd6806b6ee53b9bc51f")
            self.assertEqual(
                verdict["environment_canonical_sha256"],
                "98c04387215915acf54a9ff769492e3f7cb7b0266d3664963"
                "1a531a9b5edbf67")
            self.assertEqual(verdict["working_tree_drift"], {})
            # no working-tree gate file was executed at any stage
            self.assertFalse(
                (fixture.repo / _OUTER_MARKER).exists())
            self.assertFalse(
                (fixture.repo / _INNER_MARKER).exists())

    def test_adversarial_hostile_outer_bootstrap_cannot_win(self):
        """The review's mandatory control: the working-tree
        scripts/issue133_physical_prelaunch_gate.py is replaced with
        hostile Python that never invokes Git, writes an execution
        marker, prints a structurally valid PASS verdict, and exits 0.
        The CANONICAL launch command must never execute it; the
        accepted Git-extracted bootstrap alone decides."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            fixture.substitute(
                "scripts/issue133_physical_prelaunch_gate.py",
                _HOSTILE_OUTER_BOOTSTRAP)
            result = fixture.launch()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            # the hostile invocation-stage bootstrap was NEVER executed
            self.assertFalse(
                (fixture.repo / _OUTER_MARKER).exists(),
                "the hostile working-tree outer bootstrap was executed")
            # the authorization bootstrap path is the accepted
            # Git-extracted file, and its bytes equal the accepted blob
            bootstrap_execution = verdict["bootstrap_execution"]
            self.assertTrue(bootstrap_execution["equal"])
            self.assertEqual(
                bootstrap_execution["accepted_blob_sha256"],
                bootstrap_execution["executed_sha256"])
            executed = Path(bootstrap_execution["executed_path"])
            self.assertNotEqual(executed.resolve(), BOOTSTRAP.resolve())
            # the verdict records the ACCEPTED authority commit, not
            # the hostile decoy
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)
            self.assertNotIn("d" * 40, json.dumps(verdict))
            # all executed authorization bytes match accepted Git
            for relative, entry in (
                    verdict["gate_tooling_execution_provenance"]
                    .items()):
                self.assertTrue(entry["equal"], relative)
            # PASS occurred only because the accepted gate itself
            # passed (the accepted campaign's real gate name)
            gate = verdict["pre_execution_gate_verdict"]
            self.assertEqual(
                gate["gate"],
                "ACCEPTED_HISTORY_TOOLING_FREEZE_AND_REAL_BUILDER_BOUND")
            # the substitution is surfaced as working-tree drift only
            self.assertIn(
                "scripts/issue133_physical_prelaunch_gate.py",
                verdict["working_tree_drift"])

    def test_adversarial_silent_hostile_outer_bootstrap_cannot_win(self):
        """A hostile working-tree outer bootstrap that exits 0
        immediately with no JSON output: the canonical launch still
        uses accepted bytes and behaves normally."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            fixture.substitute(
                "scripts/issue133_physical_prelaunch_gate.py",
                _SILENT_HOSTILE_OUTER_BOOTSTRAP)
            result = fixture.launch()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            self.assertFalse(
                (fixture.repo / _OUTER_MARKER).exists())
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)
            for entry in (
                    verdict["gate_tooling_execution_provenance"]
                    .values()):
                self.assertTrue(entry["equal"])

    def test_control_working_tree_invocation_fails_closed(self):
        """Direct working-tree invocation of the real bootstrap can
        never produce an authoritative PASS (review 5169777338):
        executing from a repository working tree rejects with
        canonical-launcher instructions, with or without --repo."""
        result = subprocess.run(
            [sys.executable, str(BOOTSTRAP)], capture_output=True,
            text=True, timeout=120)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
        self.assertIn("working tree", result.stderr)
        self.assertIn("METHODOLOGY-ARM-C-RETRY.md", result.stderr)
        self.assertNotIn('"pass": true', result.stdout)

    def test_control_working_tree_invocation_with_repo_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            # the real bootstrap executing from THIS checkout (a
            # working tree) must reject even with a valid --repo
            result = subprocess.run(
                [sys.executable, str(BOOTSTRAP),
                 "--repo", str(fixture.repo)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
            self.assertIn("working tree", result.stderr)

    def test_control_loader_mode_is_removed(self):
        """The round-4 invocation-stage loader mode has been REMOVED:
        even outside any working tree, invoking the bootstrap WITHOUT
        --accepted-bootstrap rejects (an outer non-extracted process
        must never resolve/launch/parse the accepted bootstrap)."""
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "gate.py"
            shutil.copyfile(BOOTSTRAP, outside)
            result = subprocess.run(
                [sys.executable, str(outside)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
            self.assertIn("REMOVED", result.stderr)
            self.assertNotIn('"pass": true', result.stdout)

    def test_control_missing_origin_main_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            _git(fixture.repo, "update-ref", "-d",
                 "refs/remotes/origin/main", env=fixture.env)
            result = fixture.launch()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REJECT", result.stderr)
            self.assertIn("origin/main", result.stderr)

    def test_control_no_accepted_authority_history_rejects(self):
        """An accepted history that never carried the authority path
        fails closed at commit selection."""
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            shutil.copytree(ROOT / "scripts", repo / "scripts",
                            ignore=shutil.ignore_patterns("__pycache__"))
            env = _scratch_env(base)
            _git(repo, "init", "-q", "-b", "main", env=env)
            _git(repo, "add", "scripts", env=env)
            _git(repo, "commit", "-q", "-m", "scripts only", env=env)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True, text=True, env=env,
                check=True).stdout.strip()
            _git(repo, "update-ref", "refs/remotes/origin/main",
                 head, env=env)
            result = run_canonical_launch(repo, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REJECT", result.stderr)
            self.assertIn("authority", result.stderr)

    def test_control_accepted_bootstrap_blob_missing_rejects(self):
        """An accepted authority-bearing commit that lacks the
        bootstrap blob fails closed at extraction."""
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            shutil.copytree(
                ROOT / "docs/implementation"
                / "r6-successor-dense-full-integration-117",
                repo / "docs/implementation"
                / "r6-successor-dense-full-integration-117",
                ignore=shutil.ignore_patterns("__pycache__"))
            env = _scratch_env(base)
            _git(repo, "init", "-q", "-b", "main", env=env)
            _git(repo, "add", "docs", env=env)
            _git(repo, "commit", "-q", "-m", "authority docs only",
                 env=env)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True, text=True, env=env,
                check=True).stdout.strip()
            _git(repo, "update-ref", "refs/remotes/origin/main",
                 head, env=env)
            result = run_canonical_launch(repo, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REJECT", result.stderr)
            self.assertIn("bootstrap", result.stderr)

    def test_control_tampered_extraction_rejects(self):
        """Extracted bootstrap bytes that differ from the selected Git
        blob fail closed INSIDE the bootstrap (its self-verification),
        even outside any working tree."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            extracted = Path(tempfile.mkdtemp()) / "bootstrap.py"
            blob = subprocess.run(
                ["git", "-C", str(fixture.repo), "show",
                 f"{fixture.accepted_head}:"
                 "scripts/issue133_physical_prelaunch_gate.py"],
                capture_output=True, env=fixture.env,
                check=True).stdout
            tampered = bytearray(blob)
            tampered[200] ^= 0x01
            extracted.write_bytes(bytes(tampered))
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(extracted),
                 "--accepted-bootstrap", "--repo", str(fixture.repo)],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
            self.assertIn("bootstrap", result.stderr)

    def test_control_symlinked_extraction_rejects(self):
        """A symlinked temporary bootstrap target resolves into the
        repository working tree and fails closed on the working-tree
        guard; the launcher recipe itself also refuses non-regular
        targets."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            holder = Path(tempfile.mkdtemp())
            link = holder / "bootstrap.py"
            link.symlink_to(BOOTSTRAP)
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(link),
                 "--accepted-bootstrap", "--repo", str(fixture.repo)],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
            self.assertIn("working tree", result.stderr)
            # the doc recipe refuses symlinked extraction targets
            snippet = canonical_launcher_snippet()
            self.assertIn('[ ! -L "$TMP/bootstrap.py" ]', snippet)

    def test_control_accepted_gate_failure_rejects(self):
        """When the accepted gate itself fails (freeze/authority
        binding broken in accepted history), the canonical launch
        fails closed with the gate's rejection."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            freeze = fixture.repo / FREEZE_REL
            record = json.loads(freeze.read_text())
            record["case_count"] = (
                int(record["case_count"]) + 1
                if str(record.get("case_count", "")).isdigit()
                else 1)
            freeze.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n")
            fixture.amend_accepted("broken freeze binding")
            result = fixture.launch()
            self.assertNotEqual(result.returncode, 0)
            combined = result.stderr + result.stdout
            self.assertTrue(
                "REJECT" in combined or "REJECTED" in combined,
                combined[-500:])

    def test_control_malformed_accepted_gate_verdict_rejects(self):
        """An accepted gate that exits 0 with unparseable output fails
        closed (no parseable verdict)."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            fixture.substitute(
                "scripts/issue133_arm_c_retry_campaign.py",
                "print('NOT_A_VERDICT')\n")
            fixture.amend_accepted("garbage campaign output")
            result = fixture.launch()
            self.assertNotEqual(result.returncode, 0)
            combined = result.stderr + result.stdout
            self.assertTrue(
                "REJECT" in combined, combined[-500:])

    def test_control_real_repository_now_authorizes(self):
        """Since PR #135 merged (origin/main c4a8911 carrying authority
        commit c42a0ea), the canonical launch in THIS repository must
        SUCCEED: the bootstrap blob at the authority-bearing commit is
        accepted history and the campaign freeze binding is intact.
        (Pre-merge this control asserted rejection; the physical
        campaign has since executed under this exact launch.)"""
        result = run_canonical_launch(ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted_git_materialization", result.stdout)

    def test_control_later_unrelated_main_commit_remains_compatible(self):
        """Later-main semantics: an unrelated accepted commit after
        the authority-bearing anchor (closure bytes unchanged) keeps
        the canonical launch compatible."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            (fixture.repo / "UNRELATED.md").write_text(
                "unrelated later accepted main commit\n")
            _git(fixture.repo, "add", "UNRELATED.md", env=fixture.env)
            _git(fixture.repo, "commit", "-q", "-m",
                 "unrelated later main commit", env=fixture.env)
            later_head = subprocess.run(
                ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                capture_output=True, text=True, env=fixture.env,
                check=True).stdout.strip()
            _git(fixture.repo, "update-ref", "refs/remotes/origin/main",
                 later_head, env=fixture.env)
            result = fixture.launch()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            # the authority anchor stays the authority-bearing commit
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)
            self.assertEqual(
                verdict["origin_main_observed_sha"], later_head)


class LauncherContractTests(unittest.TestCase):
    """Structural controls on the canonical launcher contract and the
    accepted bootstrap itself."""

    def test_doc_snippet_is_shell_and_git_only_before_python(self):
        snippet = canonical_launcher_snippet()
        # resolves the remote ref, selects the authority commit via
        # git log, extracts via git show, re-hashes via git hash-object
        self.assertIn("rev-parse --verify --quiet "
                      "refs/remotes/origin/main", snippet)
        self.assertIn("log -1 --format=%H "
                      "refs/remotes/origin/main --", snippet)
        self.assertIn(
            'git -C "$REPO" show "$AUTH_COMMIT:$BOOTSTRAP_PATH"',
            snippet)
        self.assertIn("git hash-object \"$TMP/bootstrap.py\"", snippet)
        self.assertIn("mktemp -d", snippet)
        self.assertIn('[ ! -L "$TMP/bootstrap.py" ]', snippet)
        # the ONLY python invocation, isolated, after extraction
        self.assertEqual(snippet.count("python3"), 1)
        self.assertIn(
            'python3 -I -S "$TMP/bootstrap.py" '
            '--accepted-bootstrap --repo "$REPO"', snippet)
        # nothing before the extraction may execute repository Python
        extraction = snippet.index("git -C \"$REPO\" show")
        execution = snippet.index("python3 -I -S")
        self.assertLess(extraction, execution)

    def test_bootstrap_is_stdlib_git_only(self):
        """The bootstrap must not import any repository module (AST
        audit: only stdlib imports are permitted)."""
        import ast
        tree = ast.parse(BOOTSTRAP.read_text())
        allowed = {
            "__future__", "argparse", "hashlib", "json", "os",
            "subprocess", "sys", "tarfile", "tempfile", "pathlib",
            "typing", "shutil",
        }
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        self.assertTrue(found <= allowed, found - allowed)

    def test_closure_constants_agree_with_campaign_module(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import issue133_arm_c_retry_campaign as camp
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_prelaunch_bootstrap", BOOTSTRAP)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            sorted(module.PHYSICAL_PRELAUNCH_CLOSURE),
            sorted(set(camp.GATE_TOOLING_CLOSURE)
                   | {camp.EXTERNAL_BOOTSTRAP_REL_PATH}))
        for relative in module.PHYSICAL_PRELAUNCH_CLOSURE:
            path = ROOT / relative
            self.assertFalse(path.is_symlink(), relative)
            self.assertTrue(path.is_file(), relative)

    def test_bootstrap_scrub_covers_injection_vectors(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_prelaunch_bootstrap", BOOTSTRAP)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertLessEqual(
            {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
             "PYTHONUSERBASE"},
            set(module._SCRUBBED_ENV_KEYS))

    def test_bootstrap_materializes_without_tar_executable(self):
        """Archive extraction uses stdlib tarfile, never a
        PATH-resolved tar program."""
        import ast
        source = BOOTSTRAP.read_text()
        self.assertIn("import tarfile", source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run") or not node.args:
                continue
            command = node.args[0]
            if isinstance(command, (ast.List, ast.Tuple)) and command.elts:
                first = command.elts[0]
                if isinstance(first, ast.Constant) and first.value == "tar":
                    self.fail("bootstrap must not execute external tar")

    def test_accepted_processes_use_isolated_no_site_interpreter(self):
        source = BOOTSTRAP.read_text()
        self.assertIn('sys.executable, "-I", "-S"', source)


if __name__ == "__main__":
    unittest.main()
