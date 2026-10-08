"""Canonical CPU test environment contract (Issue #131).

Focused controls for the single dependency authority
(``requirements-test.txt``), the bootstrap, and the doctor. Every
fail-closed path has a negative control, per the repository test
conventions: the environment contract must reject a removed dependency,
an ad-hoc CI install, a declared-but-unavailable package, an
incompatible version, a bootstrap that mutates tracked files, a
model-runtime package entering the CPU environment, and documentation
that names a different install command than the canonical bootstrap.
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap_test_env as bootstrap  # noqa: E402
import check_test_env as doctor  # noqa: E402


REQUIREMENTS = ROOT / "requirements-test.txt"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sandbox_repo(test: unittest.TestCase) -> tuple[Path, Path]:
    """A throwaway git repo mimicking the repository layout.

    Returns (sandbox, venv_target) with requirements-test.txt and
    .gitignore copied in; call patch_module_root so the bootstrap
    module's ROOT/VENV point at the sandbox.
    """
    sandbox = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
    for relative in ("requirements-test.txt", ".gitignore"):
        destination = sandbox / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    subprocess.run(["git", "init", "-q", str(sandbox)], check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "config", "user.email",
         "test@example.invalid"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "config", "user.name", "Test"],
        check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "add", ".gitignore"],
        check=True, capture_output=True)
    return sandbox, sandbox / ".venv"


def patch_module_root(test: unittest.TestCase, sandbox: Path) -> None:
    """Point the bootstrap module's ROOT/VENV at a sandbox repo."""
    original_root, original_venv = bootstrap.ROOT, bootstrap.VENV
    bootstrap.ROOT = sandbox
    bootstrap.VENV = sandbox / ".venv"
    test.addCleanup(setattr, bootstrap, "ROOT", original_root)
    test.addCleanup(setattr, bootstrap, "VENV", original_venv)


class DependencyAuthorityTests(unittest.TestCase):
    """The single repository-owned dependency definition."""

    def test_authority_exists_and_declares_expected_direct_packages(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        packages, references = doctor.parse_requirements(text)
        self.assertEqual(packages, {"jsonschema", "numpy", "pyyaml", "requests"})
        self.assertEqual(references, {doctor.REFERENCED_REQUIREMENTS[0]})

    def test_issue255_http_client_is_bounded_in_canonical_authority(self):
        authority = REQUIREMENTS.read_text(encoding="utf-8")
        self.assertRegex(authority, r"(?m)^requests>=2\.\d+(?:\.\d+)?,<3$")

    def test_issue255_ci_has_no_separate_http_client_install(self):
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("requests==", workflow)
        self.assertNotIn("Install issue-255 operator test HTTP client", workflow)

    def test_authority_references_frozen_tokenizer_without_duplicating_pins(self):
        """The immutable #117 pins are consumed by reference, never copied."""
        referenced = (ROOT / doctor.REFERENCED_REQUIREMENTS[0]).read_text(
            encoding="utf-8")
        frozen_names = {
            doctor._normalize(line.split("==")[0].strip())
            for line in referenced.splitlines()
            if "==" in line and not line.strip().startswith("#")}
        self.assertTrue(frozen_names)
        authority = REQUIREMENTS.read_text(encoding="utf-8")
        for name in frozen_names:
            duplicated = re.search(
                rf"^\s*{re.escape(name)}\s*(==|>=|<|~=)", authority,
                re.MULTILINE)
            self.assertIsNone(
                duplicated,
                f"authority duplicates the frozen pin for {name}; the "
                "accepted #117 requirements must be installed by reference")

    def test_negative_control_removing_a_declared_dependency_fails_the_doctor(self):
        original = REQUIREMENTS.read_text(encoding="utf-8")
        mutated = re.sub(r"^jsonschema.*$", "", original, flags=re.MULTILINE)
        self.assertNotEqual(mutated, original)
        try:
            write(REQUIREMENTS, mutated)
            findings = doctor.doctor()
            self.assertTrue(
                any("drift" in str(finding) for finding in findings),
                [str(finding) for finding in findings])
        finally:
            write(REQUIREMENTS, original)

    def test_negative_control_authority_referencing_a_model_runtime_fails_bootstrap(self):
        original = REQUIREMENTS.read_text(encoding="utf-8")
        try:
            write(REQUIREMENTS, original + "\ntorch>=2\n")
            violations = bootstrap.forbidden_in_requirements(
                REQUIREMENTS.read_text(encoding="utf-8"))
            self.assertEqual(violations, ["torch"])
        finally:
            write(REQUIREMENTS, original)


class DoctorNegativeControls(unittest.TestCase):
    """Doctor mode fails closed on each prohibited environment state."""

    def test_negative_control_doctor_fails_when_declared_package_is_unavailable(self):
        """`jsonschema` masked out of the environment must fail the doctor."""
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            copies = ["requirements-test.txt", "CONTRIBUTING.md",
                      "tests/README.md", ".github/workflows/ci.yml",
                      "scripts/check_test_env.py",
                      "scripts/bootstrap_test_env.py"]
            for reference in doctor.REFERENCED_REQUIREMENTS:
                copies.append(reference)
            for relative in copies:
                destination = sandbox / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            write(sandbox / "mask_jsonschema.py",
                  "import importlib.metadata as m\n"
                  "real = m.distributions\n"
                  "def filtered():\n"
                  "    for d in real():\n"
                  "        n = (d.metadata.get('Name') or '').lower()\n"
                  "        if n not in ('jsonschema',):\n"
                  "            yield d\n"
                  "m.distributions = filtered\n"
                  "import runpy, sys\n"
                  "sys.argv = ['check_test_env.py']\n"
                  "sys.path.insert(0, 'scripts')\n"
                  "try:\n"
                  "    runpy.run_path('scripts/check_test_env.py',"
                  " run_name='__main__')\n"
                  "except SystemExit as e:\n"
                  "    sys.exit(e.code)\n")
            result = subprocess.run(
                [sys.executable, "mask_jsonschema.py"],
                cwd=sandbox, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0,
                                result.stdout + result.stderr)
            self.assertIn("jsonschema", result.stderr)

    def test_negative_control_doctor_fails_on_incompatible_declared_version(self):
        original = doctor.installed_versions

        def older_jsonschema():
            versions = original()
            versions["jsonschema"] = "4.17.0"
            return versions

        doctor.installed_versions = older_jsonschema
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("older than the declared floor" in str(f) for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_doctor_fails_when_model_runtime_is_installed(self):
        original = doctor.installed_versions

        def with_torch():
            versions = original()
            versions["torch"] = "2.9.0"
            return versions

        doctor.installed_versions = with_torch
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("model-runtime" in str(f) for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_doctor_fails_when_openssl_is_missing(self):
        original = doctor.check_executables
        doctor.check_executables = lambda: (_ for _ in ()).throw(
            doctor.DoctorError(
                "required external executable is not on PATH: openssl"))
        try:
            findings = doctor.doctor()
        finally:
            doctor.check_executables = original
        self.assertTrue(
            any("openssl" in str(f) for f in findings),
            [str(finding) for finding in findings])


class CIContractTests(unittest.TestCase):
    """CI consumes the canonical contract and installs nothing ad hoc."""

    def test_ci_bootstraps_from_the_canonical_contract(self):
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/bootstrap_test_env.py", workflow)
        self.assertIn("scripts/check_test_env.py", workflow)
        # No ad-hoc package-name installs survive anywhere in the workflow.
        for line in workflow.splitlines():
            if "pip install" in line:
                self.assertIn(
                    "requirements-test.txt", line,
                    f"CI pip install not from the canonical authority: {line}")

    def test_negative_control_ad_hoc_ci_install_is_rejected(self):
        original = CI_WORKFLOW.read_text(encoding="utf-8")
        try:
            write(CI_WORKFLOW, original + (
                "\n      - name: rogue\n"
                "        run: python3 -m pip install --user sympy\n"))
            findings = doctor.doctor()
            self.assertTrue(
                any("outside the canonical contract" in str(f)
                    for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(CI_WORKFLOW, original)

    def test_negative_control_ci_without_bootstrap_is_rejected(self):
        original = CI_WORKFLOW.read_text(encoding="utf-8")
        try:
            write(CI_WORKFLOW, original.replace(
                "python3 scripts/bootstrap_test_env.py", "true"))
            findings = doctor.doctor()
            self.assertTrue(
                any("bootstrap_test_env.py" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(CI_WORKFLOW, original)


class DocumentationContractTests(unittest.TestCase):
    """Docs name the canonical bootstrap, not package-specific installs."""

    def test_docs_name_the_canonical_commands(self):
        for relative in ("CONTRIBUTING.md", "tests/README.md",
                         "scripts/README.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("bootstrap_test_env.py", text,
                          f"{relative}: missing canonical bootstrap mention")
            self.assertIn("check_test_env.py", text,
                          f"{relative}: missing canonical doctor mention")

    def test_negative_control_package_specific_install_command_is_rejected(self):
        original = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        try:
            write(ROOT / "CONTRIBUTING.md", original.replace(
                "python3 scripts/bootstrap_test_env.py",
                "python3 -m pip install --user jsonschema numpy"))
            findings = doctor.doctor()
            self.assertTrue(
                any("CONTRIBUTING.md" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(ROOT / "CONTRIBUTING.md", original)

    def test_negative_control_docs_dropping_the_bootstrap_command_are_rejected(self):
        original = (ROOT / "tests" / "README.md").read_text(encoding="utf-8")
        try:
            write(ROOT / "tests" / "README.md",
                  original.replace("bootstrap_test_env.py", "setup.py"))
            findings = doctor.doctor()
            self.assertTrue(
                any("tests/README.md" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(ROOT / "tests" / "README.md", original)


class VenvTargetSafetyTests(unittest.TestCase):
    """The venv target is safe by construction, before any deletion.

    Negative controls prove a tracked directory, the repository root,
    an arbitrary --venv override, a symlink escape, and an existing
    ordinary (non-venv) directory are ALL rejected without modifying
    or deleting their sentinel contents.
    """

    def test_negative_control_tracked_directory_target_is_rejected(self):
        """A tracked repository directory must never be a venv target.

        Uses the real repository's tracked ``scripts/`` directory: the
        refusal must fire before any deletion and its sentinel file
        must survive byte-for-byte.
        """
        target = ROOT / "scripts"
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "scripts"],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertTrue(tracked)  # sanity: scripts/ is tracked
        sentinel = target / "bootstrap_test_env.py"
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.validate_venv_target(target)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)

    def test_negative_control_repository_root_is_rejected(self):
        sentinel = ROOT / "requirements-test.txt"
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.validate_venv_target(ROOT)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)

    def test_negative_control_arbitrary_venv_override_is_rejected(self):
        """There is no --venv surface left: any other target is refused,
        whether outside the repository or an untracked directory inside
        it. Sentinels survive both."""
        outside = Path(tempfile.mkdtemp()) / "escape-venv"
        outside.mkdir()
        sentinel_out = outside / "keep.txt"
        sentinel_out.write_text("sentinel", encoding="utf-8")
        inside = ROOT / "scratch-venv-under-test"
        inside.mkdir()
        sentinel_in = inside / "keep.txt"
        sentinel_in.write_text("sentinel", encoding="utf-8")
        try:
            for target in (outside, inside):
                with contextlib.redirect_stderr(io.StringIO()) as captured:
                    with self.assertRaises(SystemExit) as raised:
                        bootstrap.validate_venv_target(target)
                self.assertEqual(raised.exception.code, 1)
                self.assertIn("refusing venv target", captured.getvalue())
            self.assertEqual(
                sentinel_out.read_text(encoding="utf-8"), "sentinel")
            self.assertEqual(
                sentinel_in.read_text(encoding="utf-8"), "sentinel")
            # The CLI no longer exposes --venv at all.
            cli = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "bootstrap_test_env.py"),
                 "--venv", str(outside)],
                capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(cli.returncode, 0)
            self.assertIn("unrecognized arguments", cli.stderr)
            self.assertEqual(
                sentinel_out.read_text(encoding="utf-8"), "sentinel")
        finally:
            shutil.rmtree(outside)
            shutil.rmtree(inside)

    def test_negative_control_venv_shaped_ordinary_directory_is_refused(self):
        """The real create path must not rmtree `.venv/bin/keep.txt`.

        Generic names such as `bin` are not bootstrap ownership proof;
        the sentinel must survive byte-identically and create_venv must
        fail before any destructive operation.
        """
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        sentinel = target / "bin" / "keep.txt"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b"ordinary-user-content\n")
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.create_venv(target, "3.12")
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)
        self.assertTrue(target.is_dir())

    def test_negative_control_empty_existing_target_is_refused(self):
        """Even an empty no-config target is not inferred bootstrap-owned."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        target.mkdir()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertTrue(target.is_dir())

    def test_negative_control_existing_ordinary_directory_is_rejected(self):
        """An existing non-venv directory at the canonical target is
        refused, never rmtree'd — sentinel contents survive intact."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        target.mkdir()
        sentinel = target / "precious.txt"
        sentinel.write_text("do-not-delete", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"), "do-not-delete")
        self.assertTrue(target.is_dir())

    def test_negative_control_symlink_escape_is_rejected(self):
        """A symlinked venv directory could make deletion act outside
        the target; the target dir itself being a symlink is refused
        before anything else (internal bin/python symlinks are normal
        venv structure and harmless: rmtree never follows them)."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        real_home = sandbox / "real-home"
        real_home.mkdir()
        sentinel = real_home / "precious.txt"
        sentinel.write_text("do-not-delete", encoding="utf-8")
        target.symlink_to(real_home)
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertIn("symlink", captured.getvalue())
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"), "do-not-delete")
        self.assertTrue(target.is_symlink())

    def test_validate_target_accepts_the_canonical_gitignored_home(self):
        # The real .venv (or its absence) must pass validation.
        bootstrap.validate_venv_target(ROOT / ".venv")  # must not exit


class BootstrapContractTests(unittest.TestCase):
    """Bootstrap contracts: idempotent design, CPU-only, tree-safe."""

    def test_bootstrap_screens_model_runtime_requirements(self):
        self.assertEqual(
            bootstrap.forbidden_in_requirements("torch>=2\nsympy\n"),
            ["torch"])
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "# comment\n-r elsewhere.txt\njsonschema>=4.18,<5\n"),
            [])

    def test_bootstrap_cli_no_longer_exposes_a_venv_override(self):
        """The public --venv surface is removed: argparse rejects it."""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "bootstrap_test_env.py"),
                 "--venv", str(Path(directory) / "escape-venv")],
                capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_negative_control_bootstrap_mutation_of_tracked_files_is_detected(self):
        """The tree-digest guard fails closed on any tracked-file change.

        The install and venv creation are stubbed out so the guard is the
        only code under test.
        """
        real_digests = bootstrap.tracked_file_digests
        state = {"calls": 0}

        def mutating_digests():
            state["calls"] += 1
            digests = real_digests()
            if state["calls"] == 2:  # after the (stubbed) install
                digests["README.md"] = "0" * 64
            return digests

        bootstrap.tracked_file_digests = mutating_digests
        original_create, original_install, original_forbidden = (
            bootstrap.create_venv, bootstrap.install,
            bootstrap.forbidden_installed)
        bootstrap.create_venv = (
            lambda venv_dir, python_request="3.12": venv_dir / "bin" / "python")
        bootstrap.install = lambda python, *args: None
        bootstrap.forbidden_installed = lambda python: []
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.bootstrap(ROOT / ".venv")
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("modified tracked repository files",
                          captured.getvalue())
        finally:
            bootstrap.tracked_file_digests = real_digests
            bootstrap.create_venv = original_create
            bootstrap.install = original_install
            bootstrap.forbidden_installed = original_forbidden

    def test_forbidden_screen_covers_referenced_files(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("-r "):
                referenced = (ROOT / line[3:]).resolve()
                self.assertTrue(referenced.is_file(), referenced)
                self.assertEqual(
                    bootstrap.forbidden_in_requirements(
                        referenced.read_text(encoding="utf-8")),
                    [],
                    "frozen tokenizer requirements must stay CPU-only")


class ExistingVenvInterpreterTests(unittest.TestCase):
    """A pre-existing venv is reused only when its interpreter matches."""

    def _sandbox_venv(self) -> tuple[Path, Path]:
        """A sandbox git repo with a real venv inside it."""
        sandbox, venv = sandbox_repo(self)
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip",
             str(venv)], check=True, capture_output=True)
        return sandbox, venv

    def test_control_existing_matching_venv_is_reused(self):
        sandbox, venv = self._sandbox_venv()
        python = venv / "bin" / "python"
        # Same minor as the request: create_venv must reuse it (the
        # recorded version line and the real interpreter both match).
        request = f"{sys.version_info.major}.{sys.version_info.minor}"
        marker = venv / "sentinel-from-original-creation"
        marker.write_text("original", encoding="utf-8")
        patch_module_root(self, sandbox)
        result = bootstrap.create_venv(venv, request)
        self.assertEqual(result, python)
        self.assertEqual(
            marker.read_text(encoding="utf-8"), "original",
            "a matching existing venv must be reused, not recreated")

    def test_negative_control_stale_wrong_minor_venv_is_recreated(self):
        """A stale venv whose real interpreter has the wrong minor must
        be recreated with the requested interpreter, not installed
        into. Proven with a real mismatched venv when the host has both
        interpreters, else with a forged pyvenv.cfg (which must also be
        refused because its real interpreter is unverifiable/mismatched
        and pyvenv.cfg disagrees with reality)."""
        sandbox, venv = sandbox_repo(self)
        # Build a real venv on a minor that differs from the 3.12
        # request (the host launching interpreter's minor if it is not
        # 3.12, else a forged-config stale venv).
        launching_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        forged = launching_minor == "3.12"
        if not forged:
            subprocess.run(
                [sys.executable, "-m", "venv", "--without-pip",
                 str(venv)], check=True, capture_output=True)
        else:
            # Launching interpreter IS 3.12; forge a stale 3.13 venv
            # whose recorded version lies about the linked host
            # interpreter — the dual-channel check must reject it.
            venv.mkdir()
            (venv / "pyvenv.cfg").write_text(
                "home = /usr/bin\nversion = 3.13\n", encoding="utf-8")
            (venv / "bin").mkdir()
            (venv / "bin" / "python").symlink_to(sys.executable)
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c",
             "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)",
                         "the recreated venv must run 3.12")
        if forged:
            self.assertNotEqual(
                (venv / "pyvenv.cfg").read_text(encoding="utf-8"),
                "home = /usr/bin\nversion = 3.13\n",
                "the stale config must not survive recreation")

    def test_negative_control_unverifiable_venv_is_recreated(self):
        """pyvenv.cfg + a broken bin/python must not be trusted."""
        sandbox, venv = sandbox_repo(self)
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /usr/bin\nversion = 3.12\n", encoding="utf-8")
        (venv / "bin").mkdir()
        (venv / "bin" / "python").write_text("#!/bin/sh\nexit 9\n",
                                             encoding="utf-8")
        (venv / "bin" / "python").chmod(0o755)
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c",
             "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)")
    def test_negative_control_malformed_pyvenv_cfg_is_recreated(self):
        """A malformed recorded version is not accepted for reuse.

        `pyvenv.cfg` exists, so ownership is established and safe
        recreation is permitted; its malformed bytes must not survive.
        """
        sandbox, venv = self._sandbox_venv()
        config = venv / "pyvenv.cfg"
        config.write_text("home = /usr/bin\nversion = broken\n",
                          encoding="utf-8")
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)")
        self.assertEqual(bootstrap.venv_python_request(venv), "3.12")
        self.assertNotIn("version = broken",
                         config.read_text(encoding="utf-8"))


class MissingUvTests(unittest.TestCase):
    """No uv + wrong launching interpreter fails deterministically."""

    def test_negative_control_missing_uv_is_an_actionable_failure(self):
        sandbox, venv = sandbox_repo(self)
        original_which, original_launching = (
            shutil.which, bootstrap._launching_version)
        original_installed = bootstrap._installed_python_for
        patch_module_root(self, sandbox)
        shutil.which = lambda name: None
        bootstrap._launching_version = lambda: (3, 13)
        bootstrap._installed_python_for = lambda request: None
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.create_venv(venv, "3.12")
            self.assertEqual(raised.exception.code, 1)
            message = captured.getvalue()
            expected = (
                "bootstrap: cannot create the Python 3.12 virtual environment: "
                "the launching interpreter is 3.13, no installed python3.12 "
                "was found on PATH, and 'uv' is not installed. Install "
                "python3.12 with its venv module (for example: install a "
                "Python 3.12 package that provides `python3.12 -m venv`) or "
                "install uv <https://docs.astral.sh/uv/>, then re-run.\n")
            self.assertEqual(message, expected)
            self.assertNotIn("3..", message)
            self.assertNotIn("python3..", message)
            self.assertNotIn("Traceback", message)
        finally:
            shutil.which = original_which
            bootstrap._launching_version = original_launching
            bootstrap._installed_python_for = original_installed


class ModelRuntimeRejectionTests(unittest.TestCase):
    """The CPU/model-runtime rejection covers the declared invariant."""

    def test_nvidia_cuda_runtime_families_are_rejected_mechanically(self):
        """Common NVIDIA runtime wheels the round-1 exemplar list missed."""
        for name in (
                "nvidia-cublas-cu12", "nvidia-cuda-cuperso-cu12",
                "nvidia-cuda-nvrtc-cu12", "nvidia-cuda-runtime-cu12",
                "nvidia-cufft-cu12", "nvidia-curand-cu12",
                "nvidia-cusolver-cu12", "nvidia-cusparse-cu12",
                "nvidia-nccl-cu12", "nvidia-nvtx-cu12", "nvidia-nvjitlink-cu12",
                "nvidia-cudnn-cu12", "nvidia-cudnn-cu11",
                "nvidia_cuda_nvrtc_cu12", "NVIDIA-CUSOLVER-Cu12",
                "pytorch-triton", "cuda-python", "ptxas"):
            self.assertTrue(
                bootstrap.is_forbidden_package(name),
                f"{name} must be rejected as a model runtime")
            self.assertTrue(
                doctor.is_forbidden_package(name),
                f"{name} must be rejected by the doctor rule")

    def test_explicit_framework_names_stay_rejected(self):
        for name in ("torch", "torchvision", "torchaudio", "triton",
                     "vllm", "xformers", "flash-attn"):
            self.assertTrue(bootstrap.is_forbidden_package(name))
            self.assertTrue(doctor.is_forbidden_package(name))

    def test_legitimate_packages_are_not_rejected(self):
        for name in ("jsonschema", "numpy", "pyyaml", "transformers",
                     "tokenizers", "jinja2", "markupsafe", "sympy",
                     "typing-extensions", "attrs"):
            self.assertFalse(bootstrap.is_forbidden_package(name))
            self.assertFalse(doctor.is_forbidden_package(name))

    def test_forbidden_rules_are_one_shared_implementation(self):
        """Bootstrap and doctor must share one rule: the doctor imports
        the bootstrap's implementation, so a drift is impossible."""
        self.assertIs(doctor.is_forbidden_package,
                      bootstrap.is_forbidden_package)

    def test_negative_control_declared_nvidia_cuda_wheel_fails_bootstrap(self):
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "jsonschema>=4.18,<5\n"
                "nvidia-cuda-nvrtc-cu12==12.6.77\n"),
            ["nvidia-cuda-nvrtc-cu12"])
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "nvidia_nccl_cu12>=2.21\n"),
            ["nvidia-nccl-cu12"])

    def test_negative_control_installed_transitive_nvidia_wheel_fails(self):
        """An NVIDIA CUDA wheel found by post-install inspection must
        be reported — the transitive-contamination path. Install is
        stubbed so no real package enters any environment."""
        original = bootstrap.forbidden_installed
        original_install = bootstrap.install

        def contaminated(python: Path) -> list[str]:
            return ["nvidia-cusolver-cu12"]

        def stub_install(python: Path, *args: str) -> None:
            return None

        bootstrap.forbidden_installed = contaminated
        bootstrap.install = stub_install
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.bootstrap(ROOT / ".venv")
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("nvidia-cusolver-cu12", captured.getvalue())
            self.assertIn("entered the CPU environment", captured.getvalue())
        finally:
            bootstrap.forbidden_installed = original
            bootstrap.install = original_install

    def test_negative_control_installed_prohibited_runtime_fails_doctor(self):
        original = doctor.installed_versions

        def with_nvidia():
            versions = original()
            versions["nvidia-cuda-nvrtc-cu12"] = "12.6.77"
            return versions

        doctor.installed_versions = with_nvidia
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("model-runtime" in str(f) for f in findings),
            [str(finding) for finding in findings])


class OldDefectRegressionTests(unittest.TestCase):
    """Prove the NEW controls catch the OLD round-1 defects.

    Each control re-implements the round-1 behavior inline and shows
    the old code accepted/missed what the corrected code rejects.
    """

    def test_old_round1_denylist_missed_common_nvidia_wheels(self):
        """The round-1 exemplar frozenset did not contain the common
        NVIDIA runtime wheels; the generalized rule rejects them."""
        round1_denylist = frozenset({
            "torch", "torchvision", "torchaudio", "triton", "cuda-python",
            "nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12",
            "nvidia-cudnn-cu12", "xformers", "vllm", "flash-attn"})
        for missed in ("nvidia-cuda-nvrtc-cu12", "nvidia-nccl-cu12",
                       "nvidia-cufft-cu12", "nvidia-cusolver-cu12"):
            self.assertNotIn(missed, round1_denylist)  # the old gap
            self.assertTrue(bootstrap.is_forbidden_package(missed))
            self.assertTrue(doctor.is_forbidden_package(missed))

    def test_old_round1_reuse_check_could_not_detect_stale_venv(self):
        """Round-1 create_venv reused any venv with pyvenv.cfg +
        bin/python; show that check alone cannot distinguish a 3.12
        from a 3.13 venv — which is why the corrected code inspects
        the real interpreter."""
        sandbox, venv = sandbox_repo(self)
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /usr/bin\nversion = 3.13\n", encoding="utf-8")
        (venv / "bin").mkdir()
        (venv / "bin" / "python").symlink_to(sys.executable)

        def round1_reuse_check() -> bool:
            return ((venv / "pyvenv.cfg").is_file()
                    and (venv / "bin" / "python").exists())

        self.assertTrue(round1_reuse_check(),
                        "the old check accepted a stale 3.13 venv")
        # The old check could not see the real interpreter at all; the
        # corrected code requires BOTH channels to agree with the
        # request. Here the channels disagree with each other (cfg
        # says 3.13, real interpreter is the host's), so a request can
        # never be satisfied by both — exactly the stale shape.
        real = bootstrap.venv_interpreter_version(venv / "bin" / "python")
        recorded = bootstrap.venv_python_request(venv)
        self.assertIsNotNone(real)
        self.assertIsNotNone(recorded)
        self.assertTrue(
            real != (3, 12) or recorded != "3.12",
            "the forged venv must fail the corrected dual-channel check")

    def test_old_round1_venv_override_could_target_tracked_dirs(self):
        """Round-1 main() accepted any repo descendant as --venv; show
        that containment check alone accepted scripts/ — which is why
        the override is removed entirely."""
        venv_dir = (ROOT / "scripts" / ".venv").resolve()
        round1_containment_ok = ROOT in venv_dir.parents
        self.assertTrue(
            round1_containment_ok,
            "the old containment check accepted scripts/ as a venv target")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(venv_dir)


class FrozenPinValidationTests(unittest.TestCase):
    """Referenced frozen pins are enforced, parsed dynamically."""

    def test_frozen_pins_are_parsed_from_the_immutable_file(self):
        frozen_path = ROOT / doctor.REFERENCED_REQUIREMENTS[0]
        pins = doctor.parse_frozen_pins(
            frozen_path.read_text(encoding="utf-8"))
        self.assertEqual(pins, {
            "transformers": "==5.17.0",
            "tokenizers": "==0.23.2",
            "jinja2": "==3.1.6",
            "markupsafe": "==3.0.3"})
        # The doctor module itself must not duplicate the pins.
        doctor_source = (ROOT / "scripts" / "check_test_env.py").read_text(
            encoding="utf-8")
        for version in ("5.17.0", "0.23.2", "3.1.6", "3.0.3"):
            self.assertNotIn(
                version, doctor_source,
                f"the doctor duplicates frozen pin {version}; the "
                "immutable file is the only authority")

    def test_negative_control_wrong_frozen_version_fails_the_doctor(self):
        """At least one frozen package at a wrong installed version
        must fail the doctor with the exact mismatch named."""
        original = doctor.installed_versions

        def wrong_transformers():
            versions = original()
            versions["transformers"] = "5.16.0"  # pin is 5.17.0
            return versions

        doctor.installed_versions = wrong_transformers
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("frozen dependency version mismatch" in str(f)
                and "transformers" in str(f)
                for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_wrong_jinja2_pin_fails_the_doctor(self):
        original = doctor.installed_versions

        def wrong_jinja2():
            versions = original()
            versions["jinja2"] = "3.1.5"  # pin is 3.1.6
            return versions

        doctor.installed_versions = wrong_jinja2
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("frozen dependency version mismatch" in str(f)
                and "jinja2" in str(f)
                for f in findings),
            [str(finding) for finding in findings])


class EnvironmentPurityTests(unittest.TestCase):
    """The CPU test environment must not carry model runtimes."""

    def test_this_interpreters_environment_is_model_runtime_free(self):
        violations = bootstrap.forbidden_installed(Path(sys.executable))
        self.assertEqual(violations, [])

    def test_doctor_passes_in_a_canonical_environment(self):
        """The real repository state satisfies the doctor end to end."""
        findings = doctor.doctor()
        self.assertEqual(findings, [], [str(f) for f in findings])


# ---------------------------------------------------------------------------
# Issue #292 — dependency-cache trust contract.
#
# Hosted validation does NOT cache dependencies today (see
# docs/investigations/issue292-ci-dependency-cache.md: the measurable saving
# is ~3 s of a ~22 s bootstrap and ~0.3% of the Final CPU Validation critical
# path).  These controls make any FUTURE enablement prove, offline and
# mechanically, that the cache is only an untrusted download hint: keyed on
# the complete requirement closure, never holding the venv or validation
# outputs, and never able to bypass the canonical bootstrap and doctor.
# ---------------------------------------------------------------------------

FINAL_WORKFLOW = ROOT / ".github" / "workflows" / "final-cpu-validation.yml"
NESTED_FROZEN_REQUIREMENTS = (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/"
    "arm-c-retry/frozen-tokenizer/requirements.txt")

# Fail-closed cache contract (Issue #292, correction round 1).  Cache paths
# are an explicit ALLOWLIST of pip download-cache locations -- never a
# denylist of markers, which glob/absolute/dynamic paths trivially evade.
ALLOWED_PIP_CACHE_PATHS = ("~/.cache/pip", "/home/runner/.cache/pip")

# The only shell lines a canonical bootstrap/doctor step may contain.  A step
# counts as executing the canonical command ONLY when every non-blank,
# non-comment line is one of these exact lines, so nothing can make the
# command conditional, ignored, inert or reordered inside the step.
CANONICAL_BOOTSTRAP_LINES = frozenset({
    "python3 scripts/bootstrap_test_env.py",
    "python3 scripts/bootstrap_test_env.py --python 3.12"})
CANONICAL_DOCTOR_LINES = frozenset({
    ".venv/bin/python scripts/check_test_env.py"})
CANONICAL_PATH_EXPORT_LINE = 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"'

# Step keys that can skip, soften, redirect or re-interpret a command.
STEP_ESCAPE_KEYS = ("if", "shell", "working-directory", "env")

# A step whose script mentions any of these uses the bootstrapped venv or
# runs tests, so its job is "environment-bearing".
ENVIRONMENT_USE_MARKERS = (
    ".venv/bin/", "-m unittest", "run_full_cpu_suite.py", "pytest")

# Environment that could redirect where packages come from, which resolver
# constraints/config apply, or which interpreter a canonical command runs.
#
# pip reads EVERY option from PIP_<OPTION> (PIP_CONFIG_FILE, PIP_CONSTRAINT,
# PIP_REQUIREMENT, PIP_TARGET, ...) and uv, the bootstrap's documented fallback
# installer, from UV_<OPTION>, so those families are an ALLOWLIST (prefix
# rejected, one reviewed exception), not a list of names.  The remaining names
# are an explicit denylist, compared case-insensitively.
ALLOWED_PIP_FAMILY_ENV = frozenset({"PIP_DISABLE_PIP_VERSION_CHECK"})
FORBIDDEN_ENV_PREFIXES = ("PIP_", "UV_")
RISKY_ENV = frozenset({
    "PIP_CACHE_DIR", "PIP_FIND_LINKS", "PIP_NO_INDEX", "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL", "PIP_REQUIRE_VIRTUALENV", "PATH", "PYTHONPATH",
    "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV",
    "BASH_ENV", "ENV", "HOME", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "LD_PRELOAD", "LD_LIBRARY_PATH"})


def forbidden_env_names(env: object) -> list[str]:
    """Names in an ``env`` mapping that a validation job must not set."""
    if env and not isinstance(env, dict):
        # e.g. ``env: ${{ fromJSON(inputs.env) }}``: keys unknowable here.
        return ["<dynamic env mapping>"]
    bad = []
    for name in sorted((env or {})):
        upper = str(name).upper()
        if upper in ALLOWED_PIP_FAMILY_ENV:
            continue
        if upper.startswith(FORBIDDEN_ENV_PREFIXES) or upper in RISKY_ENV:
            bad.append(str(name))
    return bad

# The only actions/setup-python inputs a validation job may pass.
SETUP_PYTHON_REVIEWED_INPUTS = frozenset({
    "python-version", "cache", "cache-dependency-path"})

GLOB_CHARS = set("*?[]{}")


class RequirementsAuthorityError(ValueError):
    """A requirements file contains something the closure cannot account for.

    The closure must be complete or absent: an unhandled directive would
    silently drop resolver authority from the cache key, so it fails closed."""


_REQ_SPEC_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"                # name
    r"(?:\s*\[[A-Za-z0-9._,\s-]*\])?"                           # extras
    r"(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+"      # version
    r"(?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+)*)?"
    r"(?:\s*;[^#]*)?")                                             # marker
_REQ_INCLUDE_RE = re.compile(
    r"(?:(?:--requirement|--constraint)(?:\s+|=)|-[rc]\s*)(?P<path>\S.*)")


def _requirement_logical_lines(text: str) -> list[str]:
    """pip's line joining (a trailing backslash continues, except on comment
    lines) followed by comment stripping (``#`` at line start or after
    whitespace), returning stripped non-empty logical lines."""
    joined: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        if not line.endswith("\\") or re.match(r"\s*#", line):
            buffer.append(line)
            joined.append("".join(buffer))
            buffer = []
        else:
            buffer.append(line[:-1])
    if buffer:
        joined.append("".join(buffer))
    stripped = (re.sub(r"(^|\s+)#.*$", "", line).strip() for line in joined)
    return [line for line in stripped if line]


def _requirement_include_target(current: Path, repo: Path, raw: str) -> Path:
    path = raw.strip()
    if ("${" in path or "://" in path or path.startswith(("/", "~"))
            or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", path)):
        raise RequirementsAuthorityError(
            f"{current.name}: include {path!r} is not a local repo-relative path")
    target = (current.parent / path).resolve()
    try:
        target.relative_to(repo.resolve())
    except ValueError:
        raise RequirementsAuthorityError(
            f"{current.name}: include {path!r} escapes the repository") from None
    if not target.is_file():
        raise RequirementsAuthorityError(
            f"{current.name}: included file {path!r} does not exist")
    return target


def requirement_closure(root_file: Path, repo: Path) -> set[str]:
    """Repo-relative POSIX paths of a requirements file and every local file
    pip would read as resolver authority through it: ``-r``/``--requirement``
    and ``-c``/``--constraint`` includes (all spellings, nested and
    recursive; a nested path is relative to the including file, as in pip).
    Cycle-safe.

    FAILS CLOSED (``RequirementsAuthorityError``) on anything else that could
    change resolution without being a plain registry requirement: other
    option lines (``--find-links``, ``--index-url``, ``-e``, hashes, ...),
    direct URL/path/``@`` requirements, ``${VAR}`` expansion, and includes
    that are non-local, outside the repository or missing."""
    closure: set[str] = set()
    pending = [root_file.resolve()]
    while pending:
        current = pending.pop()
        relative = current.relative_to(repo.resolve()).as_posix()
        if relative in closure:
            continue
        closure.add(relative)
        for line in _requirement_logical_lines(
                current.read_text(encoding="utf-8")):
            if "${" in line:
                raise RequirementsAuthorityError(
                    f"{relative}: environment expansion in {line!r}")
            if line.startswith("-"):
                include = _REQ_INCLUDE_RE.fullmatch(line)
                if not include:
                    raise RequirementsAuthorityError(
                        f"{relative}: unhandled requirements directive "
                        f"{line!r}")
                pending.append(_requirement_include_target(
                    current, repo, include.group("path")))
            elif re.search(r"\s-{1,2}[A-Za-z]", line) \
                    or not _REQ_SPEC_RE.fullmatch(line):
                raise RequirementsAuthorityError(
                    f"{relative}: not a plain registry requirement: {line!r}")
    return closure


def _script_lines(run: object) -> list[str]:
    """Non-blank, non-comment lines of a run script (exact text, stripped)."""
    return [line.strip() for line in str(run).splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _truthy(value: object) -> bool:
    """Fail-closed truthiness for ``continue-on-error``: anything that is
    not a literal false (including expressions) counts as possibly true."""
    return not (value is False or str(value).strip().lower() == "false")


def step_roles(step: dict) -> set[str]:
    """Roles a step PROVABLY plays: ``bootstrap`` / ``doctor``.

    Structural, not textual: the step must be a plain ``run`` step with no
    escape-hatch key, and every command line must be exactly a canonical
    line (plus the PATH export for bootstrap).  Conditionals, lists,
    ``|| true``, ``set +e``, echo/printf/heredoc/comment embeddings,
    continuations and folded scalars all make the script non-canonical, so
    the step plays no role (fail closed)."""
    if "run" not in step or "uses" in step:
        return set()
    if any(key in step for key in STEP_ESCAPE_KEYS):
        return set()
    if "continue-on-error" in step and _truthy(step["continue-on-error"]):
        return set()
    lines = _script_lines(step["run"])
    if not lines:
        return set()
    if all(l in CANONICAL_BOOTSTRAP_LINES | {CANONICAL_PATH_EXPORT_LINE}
           for l in lines) and any(l in CANONICAL_BOOTSTRAP_LINES for l in lines):
        return {"bootstrap"}
    if all(l in CANONICAL_DOCTOR_LINES for l in lines):
        return {"doctor"}
    return set()


def environment_job_findings(job_name: str, job: dict) -> list[str]:
    """An environment-bearing job (runs the venv or tests, or declares a
    bootstrap/doctor) must run canonical bootstrap, then canonical doctor,
    then anything that uses the environment -- on every cache state."""
    steps = job.get("steps") or []
    roles = [step_roles(s) for s in steps]
    uses_env = [
        i for i, step in enumerate(steps)
        if not roles[i] and any(
            marker in line for line in _script_lines(step.get("run", ""))
            for marker in ENVIRONMENT_USE_MARKERS)]
    declared = any(
        line in CANONICAL_BOOTSTRAP_LINES | CANONICAL_DOCTOR_LINES
        for step in steps for line in _script_lines(step.get("run", "")))
    if not uses_env and not any(roles) and not declared:
        return []  # not environment-bearing
    bootstrap = [i for i, r in enumerate(roles) if "bootstrap" in r]
    doctor = [i for i, r in enumerate(roles) if "doctor" in r]
    findings = []
    if not bootstrap:
        findings.append(
            f"{job_name}: no unconditional canonical bootstrap step "
            "(scripts/bootstrap_test_env.py)")
    if not doctor:
        findings.append(
            f"{job_name}: no unconditional canonical doctor step "
            "(scripts/check_test_env.py)")
    if bootstrap and doctor and bootstrap[0] > doctor[0]:
        findings.append(f"{job_name}: doctor runs before bootstrap")
    first = [i for i in (bootstrap[:1] + doctor[:1])]
    if uses_env and (len(first) < 2 or uses_env[0] < max(first)):
        findings.append(
            f"{job_name}: environment is used before the canonical "
            "bootstrap and doctor have both run")
    return findings


def _literal_repo_path_findings(where: str, entry: str) -> list[str]:
    # '!' negates a pattern in hashFiles/cache-dependency-path, which could
    # cancel a closure file that is otherwise listed literally.
    if "${{" in entry or entry.startswith(("/", "~", "$", "!")) or ".." in entry \
            .split("/") or GLOB_CHARS & set(entry):
        return [f"{where}: {entry!r} is not a literal repo-relative path"]
    return []


_EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_PYTHON_REF_RE = re.compile(
    r"steps\.([A-Za-z0-9_-]+)\.outputs\.python-version")
_HASH_ARGS_RE = re.compile(r"\s*'[^']*'(?:\s*,\s*'[^']*')*\s*")


def parse_cache_key(key: str) -> tuple[list[tuple], list[str]]:
    """Split a cache key into literal text and REAL ``${{ }}`` expressions.

    Only four reviewed expression shapes are understood, each matched as the
    WHOLE expression (never as a substring, so words inside static text,
    string literals, ``format()`` or operator-combined expressions confer
    nothing): ``runner.os``, ``runner.arch``,
    ``steps.<id>.outputs.python-version`` and ``hashFiles('<literal>', ...)``.
    Anything else -- including an unbalanced ``${{`` / ``}}`` in the text --
    is reported as a problem.  Returns ``(segments, problems)`` where a
    segment is ``("text", s)``, ``("os",)``, ``("arch",)``,
    ``("python", step_id)`` or ``("hash", [literal, ...])``."""
    segments: list[tuple] = []
    problems: list[str] = []
    position = 0
    for match in _EXPR_RE.finditer(key):
        text = key[position:match.start()]
        if "${{" in text or "}}" in text:
            problems.append("unbalanced expression delimiter in key text")
        segments.append(("text", text))
        expression = match.group(1).strip()
        python_ref = _PYTHON_REF_RE.fullmatch(expression)
        hash_call = re.fullmatch(r"hashFiles\((.*)\)", expression, re.DOTALL)
        if expression == "runner.os":
            segments.append(("os",))
        elif expression == "runner.arch":
            segments.append(("arch",))
        elif python_ref:
            segments.append(("python", python_ref.group(1)))
        elif hash_call and _HASH_ARGS_RE.fullmatch(hash_call.group(1)):
            segments.append(("hash", re.findall(r"'([^']*)'", hash_call.group(1))))
        else:
            problems.append(f"unsupported key expression {expression!r}")
        position = match.end()
    tail = key[position:]
    if "${{" in tail or "}}" in tail:
        problems.append("unbalanced expression delimiter in key text")
    segments.append(("text", tail))
    return segments, problems


def _cache_key_findings(where: str, key: str, closure: set[str],
                        steps: list[dict], index: int) -> list[str]:
    """The key must be built from REAL evaluated expressions that invalidate
    on runner OS, architecture, exact Python version (from a setup-python
    step that runs BEFORE this cache step) and every closure file."""
    segments, problems = parse_cache_key(key)
    findings = [f"{where}: {problem}" for problem in problems]
    kinds = [segment[0] for segment in segments]
    for kind, label in (("os", "runner OS"), ("arch", "runner architecture")):
        if kind not in kinds:
            findings.append(
                f"{where}: cache key has no evaluated ${{{{ runner.{kind} }}}} "
                f"expression for the {label}")
    references = [segment[1] for segment in segments if segment[0] == "python"]
    if not references:
        findings.append(
            f"{where}: cache key has no evaluated "
            "steps.<id>.outputs.python-version expression")
    for step_id in references:
        # The referenced step must ALWAYS run and must not soft-fail: a
        # skipped step yields an empty output and a static key.
        earlier = [s for s in steps[:index]
                   if s.get("id") == step_id and str(
                       s.get("uses", "")).startswith("actions/setup-python@")
                   and "if" not in s
                   and not ("continue-on-error" in s
                            and _truthy(s["continue-on-error"]))]
        if not earlier:
            findings.append(
                f"{where}: python-version reference {step_id!r} is not an "
                "unconditional actions/setup-python step that runs before "
                "this cache step")
    hashed: set[str] = set()
    for segment in segments:
        if segment[0] == "hash":
            for entry in segment[1]:
                hashed.add(entry)
                findings += _literal_repo_path_findings(
                    where + " hashFiles", entry)
    missing = sorted(closure - hashed)
    if missing:
        findings.append(
            f"{where}: cache key hashFiles omits the requirement closure: "
            + ", ".join(missing))
    return findings


def cache_policy_findings(workflow: dict, closure: set[str]) -> list[str]:
    """Fail-closed findings for a parsed workflow's dependency-cache use.

    * ``setup-python`` caching must be ``pip`` with ``cache-dependency-path``
      enumerating every closure file as a literal repo-relative path.
    * ``actions/cache`` may store ONLY an allowlisted pip download-cache
      directory (never the checkout, workspace, venv, tests, outputs, globs
      or dynamic expressions), keyed on OS, architecture, Python version and
      the whole closure, with no ``restore-keys``, no cross-OS archive and
      no ``fail-on-cache-miss`` (a miss must be an ordinary cold run).
    * No other action may enable caching; pip source-redirecting env vars
      are forbidden.
    * Every environment-bearing job runs canonical bootstrap then doctor,
      unconditionally, before using the environment -- cache or not."""
    findings: list[str] = []

    def env_findings(where: str, env: object) -> None:
        for name in forbidden_env_names(env):
            findings.append(
                f"{where}: env {name} is not a reviewed environment input "
                "(it can redirect pip sources, config, constraints or cache)")

    def defaults_findings(where: str, defaults: object) -> None:
        run_defaults = (defaults or {}).get("run") or {}
        for name in ("shell", "working-directory"):
            if name in run_defaults:
                findings.append(
                    f"{where}: defaults.run.{name} re-interprets every "
                    "canonical command")

    env_findings("workflow", workflow.get("env"))
    defaults_findings("workflow", workflow.get("defaults"))
    for job_name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        env_findings(job_name, job.get("env"))
        defaults_findings(job_name, job.get("defaults"))
        for step in steps:
            roles = step_roles(step)
            for line in _script_lines(step.get("run", "")):
                if "GITHUB_ENV" in line or "::set-env" in line:
                    findings.append(
                        f"{job_name}: step writes GITHUB_ENV, which can "
                        "redirect later canonical commands")
                if "GITHUB_PATH" in line or "::add-path" in line:
                    # Only the reviewed canonical .venv export, inside the
                    # provably canonical bootstrap step, may touch PATH.
                    if not (line == CANONICAL_PATH_EXPORT_LINE
                            and "bootstrap" in roles):
                        findings.append(
                            f"{job_name}: step writes GITHUB_PATH outside "
                            "the canonical bootstrap export, which can "
                            "redirect later canonical commands")
        for index, step in enumerate(steps):
            env_findings(job_name, step.get("env"))
            uses = str(step.get("uses", ""))
            options = step.get("with") or {}
            if uses.startswith("actions/setup-python@"):
                for name in options:
                    # Allowlist: newer setup-python releases take pip inputs
                    # (pip-install, pip-version, ...) that would bypass the
                    # canonical bootstrap's resolver inputs.
                    if name not in SETUP_PYTHON_REVIEWED_INPUTS:
                        findings.append(
                            f"{job_name}: unreviewed setup-python input "
                            f"{name!r}")
                if options.get("cache"):
                    if options["cache"] != "pip":
                        findings.append(
                            f"{job_name}: setup-python cache must be 'pip', "
                            f"got {options['cache']!r}")
                    listed = [line.strip() for line in str(options.get(
                        "cache-dependency-path", "")).splitlines()
                        if line.strip()]
                    for entry in listed:
                        findings += _literal_repo_path_findings(
                            f"{job_name}: cache-dependency-path", entry)
                    missing = sorted(closure - set(listed))
                    if missing:
                        findings.append(
                            f"{job_name}: cache-dependency-path does not "
                            "list the full requirement closure: "
                            + ", ".join(missing))
            elif uses.startswith("actions/cache"):
                lines = [l.strip() for l in
                         str(options.get("path", "")).splitlines()
                         if l.strip()]
                if not lines:
                    findings.append(f"{job_name}: actions/cache has no path")
                for line in lines:
                    if line not in ALLOWED_PIP_CACHE_PATHS:
                        findings.append(
                            f"{job_name}: actions/cache path {line!r} is not "
                            "an allowed pip download-cache location "
                            "(environment/validation state must never be "
                            "cached)")
                findings += _cache_key_findings(
                    f"{job_name}: actions/cache", str(options.get("key", "")),
                    closure, steps, index)
                if str(options.get("restore-keys", "")).strip():
                    findings.append(
                        f"{job_name}: restore-keys permit stale partial "
                        "restores")
                for name in ("enableCrossOsArchive", "fail-on-cache-miss"):
                    if name in options and _truthy(options[name]):
                        findings.append(
                            f"{job_name}: actions/cache {name} must not be "
                            "enabled")
            else:
                for name in options:
                    if "cache" in str(name).lower():
                        findings.append(
                            f"{job_name}: {uses or 'step'} enables caching "
                            f"({name!r}) outside the cache contract")
        findings += environment_job_findings(job_name, job)
    return findings


class DependencyCacheContractTests(unittest.TestCase):
    """Issue #292 — a dependency cache is an untrusted performance hint."""

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)
        cls.workflows = {
            path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in (CI_WORKFLOW, FINAL_WORKFLOW)}

    def test_closure_is_root_plus_nested_frozen_requirements(self):
        self.assertEqual(
            self.closure, {"requirements-test.txt", NESTED_FROZEN_REQUIREMENTS})

    def test_real_workflows_satisfy_the_cache_policy(self):
        for name, workflow in self.workflows.items():
            self.assertEqual(
                cache_policy_findings(workflow, self.closure), [], name)

    def test_real_workflows_keep_bootstrap_and_doctor_unconditional(self):
        # Pin the environment-bearing job set so the structural detector
        # cannot silently go vacuous (a renamed marker would drop jobs).
        expected = {
            "ci.yml": {n for n in self.workflows["ci.yml"]["jobs"]
                       if n not in {"plan", "ci-gate"}},
            "final-cpu-validation.yml": {"final-cpu-validation"}}
        for name, workflow in self.workflows.items():
            bearing = {
                job_name for job_name, job in workflow["jobs"].items()
                if any("bootstrap" in step_roles(s) for s in job["steps"])}
            self.assertEqual(bearing, expected[name], name)
            self.assertEqual(len(bearing), 17 if name == "ci.yml" else 1)
            for job_name in bearing:
                self.assertEqual(environment_job_findings(
                    job_name, workflow["jobs"][job_name]), [], job_name)

    def test_mutated_real_workflows_are_rejected(self):
        import yaml
        boot = "python3 scripts/bootstrap_test_env.py"
        doctor = ".venv/bin/python scripts/check_test_env.py"
        for path in (CI_WORKFLOW, FINAL_WORKFLOW):
            original = path.read_text(encoding="utf-8")
            mutations = {
                "bootstrap || true": original.replace(
                    f"          {boot}\n", f"          {boot} || true\n", 1),
                "doctor || true": original.replace(
                    f"run: {doctor}\n", f"run: {doctor} || true\n", 1),
                "doctor removed": original.replace(
                    f"run: {doctor}\n", 'run: echo "doctor skipped"\n', 1),
                "bootstrap skipped by step if": original.replace(
                    "      - name: Bootstrap canonical CPU test environment"
                    " (Issue #131)\n",
                    "      - name: Bootstrap canonical CPU test environment"
                    " (Issue #131)\n        if: github.event_name == 'push'\n",
                    1)}
            for label, mutated in mutations.items():
                with self.subTest(path.name, mutation=label):
                    self.assertNotEqual(mutated, original, "mutation no-op")
                    self.assertTrue(cache_policy_findings(
                        yaml.safe_load(mutated), self.closure))

    def _workflow_with(self, **setup_python_with):
        return {"jobs": {"j": {"steps": [
            {"uses": "actions/setup-python@x",
             "with": {"python-version": "3.12", **setup_python_with}},
            {"run": "python3 scripts/bootstrap_test_env.py"},
            {"run": ".venv/bin/python scripts/check_test_env.py"}]}}}

    def test_negative_control_default_dependency_path_is_rejected(self):
        # setup-python's default glob (**/requirements.txt) would miss the
        # root requirements-test.txt: stale-cache reuse on a root change.
        findings = cache_policy_findings(
            self._workflow_with(cache="pip"), self.closure)
        self.assertTrue(any("full requirement closure" in f for f in findings),
                        findings)

    def test_negative_control_root_only_dependency_path_is_rejected(self):
        findings = cache_policy_findings(self._workflow_with(
            cache="pip", **{"cache-dependency-path": "requirements-test.txt"}),
            self.closure)
        self.assertTrue(any(NESTED_FROZEN_REQUIREMENTS in f for f in findings),
                        findings)

    def test_full_closure_dependency_path_is_accepted(self):
        listed = "\n".join(sorted(self.closure))
        self.assertEqual(cache_policy_findings(self._workflow_with(
            cache="pip", **{"cache-dependency-path": listed}), self.closure), [])

    def test_negative_control_unlisted_transitive_requirements_file(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            write(repo / "root.txt", "pkg-a\n-r sub/mid.txt\n")
            write(repo / "sub" / "mid.txt", "pkg-b\n-r ../deep/leaf.txt\n")
            write(repo / "deep" / "leaf.txt", "pkg-c==1\n")
            closure = requirement_closure(repo / "root.txt", repo)
            self.assertEqual(
                closure, {"root.txt", "sub/mid.txt", "deep/leaf.txt"})
            findings = cache_policy_findings(self._workflow_with(
                cache="pip", **{"cache-dependency-path": "root.txt\nsub/mid.txt"}),
                closure)
            self.assertTrue(any("deep/leaf.txt" in f for f in findings), findings)

    def test_negative_control_caching_the_venv_or_outputs_is_rejected(self):
        for path in (".venv", "~/work/inferswarm/.venv", "tests/__pycache__",
                     "/tmp/final-validation-receipt.json", "."):
            workflow = {"jobs": {"j": {"steps": [
                {"uses": "actions/cache@x", "with": {"path": path, "key": "k"}},
                {"run": "python3 scripts/bootstrap_test_env.py"},
                {"run": ".venv/bin/python scripts/check_test_env.py"}]}}}
            self.assertTrue(
                any("environment/validation state" in f
                    for f in cache_policy_findings(workflow, self.closure)),
                path)

    def test_negative_control_conditional_bootstrap_or_doctor_is_rejected(self):
        workflow = self._workflow_with(
            cache="pip",
            **{"cache-dependency-path": "\n".join(sorted(self.closure))})
        workflow["jobs"]["j"]["steps"][1]["if"] = (
            "steps.setup.outputs.cache-hit != 'true'")
        findings = cache_policy_findings(workflow, self.closure)
        self.assertTrue(any("conditional" in f for f in findings), findings)
        workflow["jobs"]["j"]["steps"][1].pop("if")
        workflow["jobs"]["j"]["steps"].pop()  # drop the doctor step
        findings = cache_policy_findings(workflow, self.closure)
        self.assertTrue(any("check_test_env.py" in f for f in findings), findings)


# ---------------------------------------------------------------------------
# Issue #292 correction round 1 — the cache contract must fail CLOSED.
#
# PR #294 review found the first validator fail-open: cache paths were
# screened by substring markers (so the checkout root, ${{ github.workspace }}
# and globs passed), and bootstrap/doctor were "present" if their text merely
# appeared in a run script (so conditional, ``|| true``, echoed, commented or
# heredoc-embedded commands counted, and an environment-bearing job with no
# bootstrap at all was ignored unless it also used a cache).  These controls
# demonstrate each bypass; they are RED against the first validator.
# ---------------------------------------------------------------------------

BOOTSTRAP_CMD = "python3 scripts/bootstrap_test_env.py"
DOCTOR_CMD = ".venv/bin/python scripts/check_test_env.py"
PIP_CACHE_PATH = "~/.cache/pip"


def _step(run: str, **extra) -> dict:
    return {"run": run, **extra}


def _setup_python(closure: set[str], **extra) -> dict:
    return {"uses": "actions/setup-python@x", "id": "py", "with": {
        "python-version": "3.12", "cache": "pip",
        "cache-dependency-path": "\n".join(sorted(closure)), **extra}}


def _actions_cache(path: str, key: str | None = None, **extra) -> dict:
    options = {"path": path, "key": key if key is not None else "k", **extra}
    return {"uses": "actions/cache@x", "with": options}


def _job_workflow(steps: list[dict]) -> dict:
    return {"jobs": {"j": {"steps": steps}}}


def _canonical_steps() -> list[dict]:
    return [_step(BOOTSTRAP_CMD), _step(DOCTOR_CMD)]


class CacheContractBypassTests(unittest.TestCase):
    """Issue #292 correction: each bypass below must be REJECTED."""

    @classmethod
    def setUpClass(cls):
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)

    def findings(self, steps: list[dict]) -> list[str]:
        return cache_policy_findings(_job_workflow(steps), self.closure)

    def assertRejected(self, steps, label):
        with self.subTest(label):
            self.assertTrue(self.findings(steps), f"bypass accepted: {label}")

    # -- 1. absolute checkout-root / workspace cache paths ------------------
    def test_red_checkout_root_and_workspace_cache_paths_are_rejected(self):
        for path in ("/home/runner/work/inferswarm/inferswarm",
                     "/home/runner/work/inferswarm/inferswarm/scripts",
                     "~/work/inferswarm/inferswarm",
                     "${{ github.workspace }}",
                     "${{ github.workspace }}/",
                     "$GITHUB_WORKSPACE",
                     "${{ runner.temp }}"):
            self.assertRejected(
                [_actions_cache(path), *_canonical_steps()], path)

    # -- 2. broad / glob / traversal paths ----------------------------------
    def test_red_broad_and_glob_cache_paths_are_rejected(self):
        for path in ("**", "*", "**/*", ".v*nv", "./.[v]env", "te*ts",
                     "/t[m]p/*", "{.venv,x}", "~/.cache/pip/../../work",
                     "~/.cache/pip\n.", "~/.cache/pip\n!x", "final-validation-*.json"):
            self.assertRejected(
                [_actions_cache(path), *_canonical_steps()], path)

    # -- 3. shell-level conditional execution --------------------------------
    def test_red_shell_conditional_bootstrap_is_rejected(self):
        variants = {
            "if/then": 'if [ "$HIT" != "true" ]; then\n  ' + BOOTSTRAP_CMD + '\nfi',
            "and-list": '[ "$HIT" != "true" ] && ' + BOOTSTRAP_CMD,
            "or-list": '[ "$HIT" = "true" ] || ' + BOOTSTRAP_CMD,
            "|| true": BOOTSTRAP_CMD + " || true",
            "; true": BOOTSTRAP_CMD + "; true",
            "set +e": "set +e\n" + BOOTSTRAP_CMD,
            "negated": "! " + BOOTSTRAP_CMD,
            "backgrounded": BOOTSTRAP_CMD + " &",
            "continuation": BOOTSTRAP_CMD + " \\\n  || true",
            "folded": BOOTSTRAP_CMD + " echo done",
        }
        for label, script in variants.items():
            self.assertRejected(
                [_step(script), _step(DOCTOR_CMD)], f"bootstrap {label}")

    def test_red_shell_conditional_doctor_is_rejected(self):
        variants = {
            "if/then": 'if [ -z "$HIT" ]; then\n  ' + DOCTOR_CMD + '\nfi',
            "and-list": 'test -d .venv && ' + DOCTOR_CMD,
            "|| true": DOCTOR_CMD + " || true",
            "set +e": "set +e\n" + DOCTOR_CMD,
        }
        for label, script in variants.items():
            self.assertRejected(
                [_step(BOOTSTRAP_CMD), _step(script)], f"doctor {label}")

    def test_red_step_level_escape_hatches_are_rejected(self):
        for extra in ({"continue-on-error": True},
                      {"continue-on-error": "${{ steps.s.outputs.x }}"},
                      {"if": "steps.s.outputs.cache-hit != 'true'"},
                      {"shell": "python"},
                      {"working-directory": "/tmp"},
                      {"env": {"PATH": "/tmp/evil"}}):
            self.assertRejected(
                [_step(BOOTSTRAP_CMD, **extra), _step(DOCTOR_CMD)],
                f"bootstrap step {extra}")
            self.assertRejected(
                [_step(BOOTSTRAP_CMD), _step(DOCTOR_CMD, **extra)],
                f"doctor step {extra}")

    # -- 4. inert commands mistaken for execution ----------------------------
    def test_red_inert_bootstrap_and_doctor_are_not_counted(self):
        inert = {
            "echo": 'echo "%s"',
            "single-quoted echo": "echo '%s'",
            "comment": "# %s\ntrue",
            "heredoc body": "cat <<'EOF'\n%s\nEOF",
            "colon": ": %s",
            "printf": 'printf "%%s\\n" "%s"',
            "trailing comment": "true # %s",
        }
        for label, template in inert.items():
            self.assertRejected(
                [_step(template % BOOTSTRAP_CMD), _step(DOCTOR_CMD)],
                f"inert bootstrap: {label}")
            self.assertRejected(
                [_step(BOOTSTRAP_CMD), _step(template % DOCTOR_CMD)],
                f"inert doctor: {label}")

    # -- 5. required environment-bearing job missing bootstrap/doctor --------
    def test_red_environment_job_without_bootstrap_or_doctor_is_rejected(self):
        suite = _step("python3 -m unittest tests.test_issue74_methodology -v")
        runner = _step(".venv/bin/python scripts/run_full_cpu_suite.py --json")
        cases = {
            "no bootstrap, no doctor (no cache)": [suite],
            "no bootstrap (doctor only)": [_step(DOCTOR_CMD), suite],
            "no doctor (bootstrap only)": [_step(BOOTSTRAP_CMD), suite],
            "venv suite without either": [runner],
            "tests before bootstrap": [suite, *_canonical_steps()],
            "doctor before bootstrap": [
                _step(DOCTOR_CMD), _step(BOOTSTRAP_CMD), suite],
            "tests between bootstrap and doctor": [
                _step(BOOTSTRAP_CMD), suite, _step(DOCTOR_CMD)],
            "cache but no bootstrap/doctor": [
                _setup_python(self.closure), suite],
        }
        for label, steps in cases.items():
            self.assertRejected(steps, label)

    # -- acceptance: legitimate shapes keep passing (GREEN before and after) -
    def test_legitimate_no_cache_environment_job_is_accepted(self):
        steps = [
            {"uses": "actions/setup-python@x",
             "with": {"python-version": "3.12"}},
            _step(BOOTSTRAP_CMD + '\necho "$PWD/.venv/bin" >> "$GITHUB_PATH"'),
            _step(DOCTOR_CMD),
            _step("python3 -m unittest tests.test_issue74_methodology -v")]
        self.assertEqual(self.findings(steps), [])

    def test_legitimate_non_environment_job_is_accepted(self):
        self.assertEqual(self.findings([
            _step("python3 scripts/plan_ci.py --mode pr"),
            _step("echo planned")]), [])

    def test_valid_narrow_setup_python_pip_cache_is_accepted(self):
        steps = [_setup_python(self.closure), *_canonical_steps(),
                 _step("python3 -m unittest tests.test_x")]
        self.assertEqual(self.findings(steps), [])

    def test_valid_narrow_actions_cache_is_accepted(self):
        key = ("pip-${{ runner.os }}-${{ runner.arch }}-"
               "py${{ steps.py.outputs.python-version }}-"
               "${{ hashFiles('requirements-test.txt', '%s') }}"
               % NESTED_FROZEN_REQUIREMENTS)
        steps = [{"uses": "actions/setup-python@x", "id": "py",
                  "with": {"python-version": "3.12"}},
                 _actions_cache(PIP_CACHE_PATH, key),
                 *_canonical_steps(),
                 _step("python3 -m unittest tests.test_x")]
        self.assertEqual(self.findings(steps), [])


def simulate_cache_key(key: str, repo: Path, os_name: str, arch: str,
                       python_version: str) -> str:
    """Deterministically evaluate a cache key offline, like Actions would.

    Only real ``${{ }}`` expressions of the reviewed shapes evaluate; static
    text stays static.  An expression it cannot evaluate raises, so an
    unevaluable key can never masquerade as an invalidating one.  Like
    ``hashFiles``, files that do not exist contribute nothing (an empty hash
    when none match)."""
    import hashlib

    segments, problems = parse_cache_key(key)
    if problems:
        raise ValueError("; ".join(problems))
    parts = []
    for segment in segments:
        if segment[0] == "text":
            parts.append(segment[1])
        elif segment[0] == "os":
            parts.append(os_name)
        elif segment[0] == "arch":
            parts.append(arch)
        elif segment[0] == "python":
            parts.append(python_version)
        else:
            digest, matched = hashlib.sha256(), False
            for name in segment[1]:
                path = repo / name
                if path.is_file():
                    matched = True
                    digest.update(name.encode() + b"\0" + path.read_bytes())
            parts.append(digest.hexdigest() if matched else "")
    return "".join(parts)


VALID_CACHE_KEY = (
    "pip-${{ runner.os }}-${{ runner.arch }}-"
    "py${{ steps.py.outputs.python-version }}-"
    "${{ hashFiles('requirements-test.txt', '%s') }}" % NESTED_FROZEN_REQUIREMENTS)


class CacheKeyAndMissContractTests(unittest.TestCase):
    """Issue #292 correction: key invalidation and cache-miss behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)

    def workflow(self, *cache_steps) -> dict:
        return _job_workflow([
            {"uses": "actions/setup-python@x", "id": "py",
             "with": {"python-version": "3.12"}},
            *cache_steps, *_canonical_steps(),
            _step("python3 -m unittest tests.test_x")])

    def findings(self, **options) -> list[str]:
        step = _actions_cache(PIP_CACHE_PATH, VALID_CACHE_KEY, **options)
        return cache_policy_findings(self.workflow(step), self.closure)

    def test_valid_key_is_accepted(self):
        self.assertEqual(self.findings(), [])

    def test_negative_controls_weak_keys_are_rejected(self):
        h = "${{ hashFiles('requirements-test.txt', '%s') }}" % (
            NESTED_FROZEN_REQUIREMENTS)
        weak = {
            "static key": "pip-cache-v1",
            "no runner os": "pip-${{ runner.arch }}-py${{ steps.py.outputs.python-version }}-" + h,
            "no runner arch": "pip-${{ runner.os }}-py${{ steps.py.outputs.python-version }}-" + h,
            "no python version": "pip-${{ runner.os }}-${{ runner.arch }}-" + h,
            "python version from unknown step": (
                "pip-${{ runner.os }}-${{ runner.arch }}-"
                "${{ steps.other.outputs.python-version }}-" + h),
            "root file not hashed": (
                "pip-${{ runner.os }}-${{ runner.arch }}-"
                "py${{ steps.py.outputs.python-version }}-"
                "${{ hashFiles('%s') }}" % NESTED_FROZEN_REQUIREMENTS),
            "nested file not hashed": (
                "pip-${{ runner.os }}-${{ runner.arch }}-"
                "py${{ steps.py.outputs.python-version }}-"
                "${{ hashFiles('requirements-test.txt') }}"),
            "glob hashFiles": (
                "pip-${{ runner.os }}-${{ runner.arch }}-"
                "py${{ steps.py.outputs.python-version }}-"
                "${{ hashFiles('**/requirements*.txt') }}"),
        }
        for label, key in weak.items():
            with self.subTest(label):
                step = _actions_cache(PIP_CACHE_PATH, key)
                self.assertTrue(cache_policy_findings(
                    self.workflow(step), self.closure))

    def test_negative_controls_unsafe_restore_options_are_rejected(self):
        for options in ({"restore-keys": "pip-"},
                        {"enableCrossOsArchive": True},
                        {"fail-on-cache-miss": True},
                        {"fail-on-cache-miss": "${{ inputs.strict }}"}):
            with self.subTest(**{k: str(v) for k, v in options.items()}):
                self.assertTrue(self.findings(**options))

    def test_negative_controls_other_caching_surfaces_are_rejected(self):
        closure = self.closure
        listed = "\n".join(sorted(closure))
        cases = {
            "setup-python poetry cache": [_setup_python(closure, cache="poetry")],
            "setup-python glob dependency path": [{
                "uses": "actions/setup-python@x", "with": {
                    "cache": "pip", "cache-dependency-path": "**/requirements*.txt"}}],
            "setup-python absolute dependency path": [{
                "uses": "actions/setup-python@x", "with": {
                    "cache": "pip",
                    "cache-dependency-path": listed + "\n/etc/passwd"}}],
            "setup-python dynamic dependency path": [{
                "uses": "actions/setup-python@x", "with": {
                    "cache": "pip",
                    "cache-dependency-path": listed + "\n${{ github.workspace }}/x"}}],
            "setup-uv enable-cache": [{
                "uses": "astral-sh/setup-uv@x", "with": {"enable-cache": True}}],
        }
        for label, steps in cases.items():
            with self.subTest(label):
                self.assertTrue(cache_policy_findings(
                    _job_workflow([*steps, *_canonical_steps(),
                                   _step("python3 -m unittest tests.test_x")]),
                    closure))

    def test_negative_controls_pip_source_redirection_env_is_rejected(self):
        for scope in ("workflow", "job", "step"):
            for name in sorted(RISKY_ENV):
                workflow = self.workflow()
                if scope == "workflow":
                    workflow["env"] = {name: "/x"}
                elif scope == "job":
                    workflow["jobs"]["j"]["env"] = {name: "/x"}
                else:
                    workflow["jobs"]["j"]["steps"][0]["env"] = {name: "/x"}
                with self.subTest(scope=scope, var=name):
                    self.assertTrue(
                        cache_policy_findings(workflow, self.closure))

    def test_negative_controls_command_reinterpretation_is_rejected(self):
        for scope in ("workflow", "job"):
            for defaults in ({"run": {"shell": "python"}},
                             {"run": {"working-directory": "/tmp"}}):
                workflow = self.workflow()
                if scope == "workflow":
                    workflow["defaults"] = defaults
                else:
                    workflow["jobs"]["j"]["defaults"] = defaults
                with self.subTest(scope=scope, defaults=str(defaults)):
                    self.assertTrue(
                        cache_policy_findings(workflow, self.closure))

    def test_negative_control_github_env_writes_are_rejected(self):
        for script in ('echo "PIP_CACHE_DIR=/x" >> "$GITHUB_ENV"',
                       'echo "PATH=/evil:$PATH" >> $GITHUB_ENV'):
            workflow = self.workflow()
            workflow["jobs"]["j"]["steps"].insert(1, _step(script))
            with self.subTest(script):
                self.assertTrue(cache_policy_findings(workflow, self.closure))

    def test_key_invalidates_on_every_authority_input(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            write(repo / "requirements-test.txt", "numpy>=1.26,<3\n")
            write(repo / NESTED_FROZEN_REQUIREMENTS, "transformers==5.17.0\n")

            def key(**override):
                args = dict(os_name="Linux", arch="X64", python_version="3.12.15")
                args.update(override)
                return simulate_cache_key(VALID_CACHE_KEY, repo, **args)

            base = key()
            self.assertEqual(base, key(), "deterministic")
            self.assertNotEqual(base, key(os_name="macOS"))
            self.assertNotEqual(base, key(arch="ARM64"))
            self.assertNotEqual(base, key(python_version="3.13.0"))
            self.assertNotEqual(base, key(python_version="3.12.16"))
            write(repo / "requirements-test.txt", "numpy>=1.26,<4\n")
            changed_root = key()
            self.assertNotEqual(base, changed_root)
            write(repo / NESTED_FROZEN_REQUIREMENTS, "transformers==5.18.0\n")
            self.assertNotEqual(changed_root, key())

    def test_cache_miss_does_not_change_the_canonical_install_command(self):
        """A cold/miss/poisoned-directory run installs exactly as before:
        the bootstrap never reads cache environment or adds cache flags."""
        import os
        from unittest import mock

        commands: list[list[str]] = []

        def fake_run(command, *args, **kwargs):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0)

        outcomes = []
        for cache_dir in (None, "/nonexistent/poisoned-pip-cache"):
            commands.clear()
            environment = dict(os.environ)
            environment.pop("PIP_CACHE_DIR", None)
            if cache_dir:
                environment["PIP_CACHE_DIR"] = cache_dir
            with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(bootstrap.subprocess, "run", fake_run):
                bootstrap.install(Path("/venv/bin/python"), "-r",
                                  str(bootstrap.REQUIREMENTS))
            outcomes.append([c for c in commands if "install" in c])
        self.assertEqual(outcomes[0], outcomes[1])
        (install_command,) = outcomes[0]
        self.assertEqual(install_command, [
            "/venv/bin/python", "-m", "pip", "install",
            "--disable-pip-version-check", "-r", str(bootstrap.REQUIREMENTS)])
        source = (ROOT / "scripts" / "bootstrap_test_env.py").read_text(
            encoding="utf-8")
        for forbidden in ("PIP_", "--find-links", "--no-index", "--no-deps",
                          "os.environ", "--cache-dir"):
            self.assertNotIn(forbidden, source, forbidden)


# ---------------------------------------------------------------------------
# Issue #292 correction round 2 (maintainer re-review of cd6fd13).
#
# B1: the first key validator looked for ``runner.os``/``hashFiles(...)`` as
#     arbitrary SUBSTRINGS, so a fully static key that merely spells those
#     words passed although GitHub evaluates nothing and the key never
#     changes.  Keys must be built from real, evaluated ``${{ }}`` expressions
#     that reference an earlier setup-python step.
# B2: only GITHUB_ENV was screened; an arbitrary GITHUB_PATH write before the
#     canonical bootstrap redirects every later canonical ``python3``.
# ---------------------------------------------------------------------------

_B1_NESTED = NESTED_FROZEN_REQUIREMENTS
_B1_HASH = "${{ hashFiles('requirements-test.txt', '%s') }}" % _B1_NESTED
_B1_PY_STEP = {"uses": "actions/setup-python@x", "id": "py",
               "with": {"python-version": "3.12"}}


class CacheKeyExpressionBypassTests(unittest.TestCase):
    """B1 -- the key must be real evaluated expressions, not look-alikes."""

    @classmethod
    def setUpClass(cls):
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)

    def workflow(self, key: str, *, before=(), after=()) -> dict:
        return _job_workflow([
            *before, _actions_cache(PIP_CACHE_PATH, key), *after,
            *_canonical_steps(), _step("python3 -m unittest tests.test_x")])

    def findings(self, key: str, **kw) -> list[str]:
        kw.setdefault("before", (_B1_PY_STEP,))
        return cache_policy_findings(self.workflow(key, **kw), self.closure)

    def crafted_keys(self) -> dict[str, str]:
        os_, arch = "${{ runner.os }}", "${{ runner.arch }}"
        py = "${{ steps.py.outputs.python-version }}"
        return {
            # the exact maintainer reproduction: needles as static text
            "fully static look-alike": (
                "runner.os-runner.arch-steps.py.outputs.python-version-"
                "hashFiles('requirements-test.txt', '%s')" % _B1_NESTED),
            "static text, no expressions at all": "pip-linux-x64-py312",
            "os is text, rest real": f"runner.os-{arch}-py{py}-{_B1_HASH}",
            "arch is text, rest real": f"{os_}-runner.arch-py{py}-{_B1_HASH}",
            "python is text, rest real": (
                f"{os_}-{arch}-steps.py.outputs.python-version-{_B1_HASH}"),
            "hash is text, rest real": (
                f"{os_}-{arch}-py{py}-hashFiles('requirements-test.txt', "
                f"'{_B1_NESTED}')"),
            "needle only inside a string literal": (
                "${{ 'runner.os' }}-${{ 'runner.arch' }}-"
                "${{ 'steps.py.outputs.python-version' }}-"
                "${{ 'hashFiles(requirements-test.txt)' }}"),
            "needle hidden in format()": (
                "${{ format('{0}', 'runner.os runner.arch "
                "steps.py.outputs.python-version') }}-" + _B1_HASH),
            "operator-combined expression": (
                f"${{{{ runner.os && runner.arch }}}}-py{py}-{_B1_HASH}"),
            "unbalanced expression": (
                f"${{{{ runner.os -{arch}-py{py}-{_B1_HASH}"),
            "hash of a different (constant) file set": (
                f"{os_}-{arch}-py{py}-${{{{ hashFiles('README.md') }}}}"),
            "hash expression with nested file omitted": (
                f"{os_}-{arch}-py{py}-${{{{ hashFiles("
                f"'requirements-test.txt') }}}}"),
        }

    # -- the key must be rejected, and must never be accepted-yet-static ----
    def test_red_look_alike_and_static_keys_are_rejected(self):
        for label, key in self.crafted_keys().items():
            with self.subTest(label):
                self.assertTrue(self.findings(key), f"accepted: {label}")

    def test_red_any_accepted_key_changes_on_every_authority_input(self):
        """Contract: a key the validator ACCEPTS must evaluate differently
        for OS, architecture, Python version, root and nested requirements."""
        candidates = dict(self.crafted_keys())
        candidates["valid"] = VALID_CACHE_KEY
        for label, key in candidates.items():
            if self.findings(key):
                continue  # rejected: fine
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as raw:
                    repo = Path(raw)
                    write(repo / "requirements-test.txt", "numpy>=1.26,<3\n")
                    write(repo / _B1_NESTED, "transformers==5.17.0\n")
                    base_args = dict(os_name="Linux", arch="X64",
                                     python_version="3.12.15")

                    def evaluate(**override):
                        return simulate_cache_key(
                            key, repo, **{**base_args, **override})

                    base = evaluate()
                    for name, override in (
                            ("OS", {"os_name": "macOS"}),
                            ("architecture", {"arch": "ARM64"}),
                            ("Python version", {"python_version": "3.13.0"})):
                        self.assertNotEqual(
                            base, evaluate(**override),
                            f"accepted key does not change with {name}")
                    write(repo / "requirements-test.txt", "numpy>=1.26,<4\n")
                    changed = evaluate()
                    self.assertNotEqual(
                        base, changed,
                        "accepted key does not change with root requirements")
                    write(repo / _B1_NESTED, "transformers==5.18.0\n")
                    self.assertNotEqual(
                        changed, evaluate(),
                        "accepted key does not change with nested requirements")

    # -- references must be to a PRECEDING setup-python step ----------------
    def test_red_python_reference_must_be_an_earlier_setup_python_step(self):
        real = VALID_CACHE_KEY
        cases = {
            "setup-python only after the cache step": dict(
                before=(), after=(_B1_PY_STEP,)),
            "id belongs to a non-setup-python step": dict(before=(
                {"id": "py", "run": "echo hi"},)),
            "no step with that id": dict(before=()),
            "id on a different action": dict(before=(
                {"uses": "actions/checkout@x", "id": "py"},)),
        }
        for label, kw in cases.items():
            with self.subTest(label):
                self.assertTrue(self.findings(real, **kw), f"accepted: {label}")

    def test_valid_key_after_an_earlier_setup_python_is_accepted(self):
        self.assertEqual(self.findings(VALID_CACHE_KEY), [])

    def test_red_negated_hashfiles_entry_cannot_cancel_a_closure_file(self):
        # GitHub excludes '!'-patterns: listing the root file literally AND
        # negating it would leave the key blind to root requirement changes.
        key = ("${{ runner.os }}-${{ runner.arch }}-"
               "py${{ steps.py.outputs.python-version }}-"
               "${{ hashFiles('requirements-test.txt', "
               "'!requirements-test.txt', '%s') }}" % _B1_NESTED)
        self.assertTrue(self.findings(key))
        self.assertTrue(cache_policy_findings(_job_workflow([
            {"uses": "actions/setup-python@x", "with": {
                "cache": "pip", "cache-dependency-path":
                    "requirements-test.txt\n!requirements-test.txt\n"
                    + _B1_NESTED}},
            *_canonical_steps(), _step("python3 -m unittest tests.test_x")]),
            self.closure))

    def test_red_conditional_or_soft_failing_python_step_is_rejected(self):
        # A skipped setup-python step yields an EMPTY python-version output,
        # silently making that part of the key static.
        for label, extra in {
            "if": {"if": "github.event_name == 'push'"},
            "continue-on-error": {"continue-on-error": True},
            "dynamic continue-on-error": {
                "continue-on-error": "${{ inputs.soft }}"},
        }.items():
            with self.subTest(label):
                self.assertTrue(self.findings(
                    VALID_CACHE_KEY, before=({**_B1_PY_STEP, **extra},)),
                    f"accepted: {label}")


class GithubPathWriteBypassTests(unittest.TestCase):
    """B2 -- only the reviewed canonical export may write GITHUB_PATH."""

    @classmethod
    def setUpClass(cls):
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)

    def findings(self, steps) -> list[str]:
        return cache_policy_findings(_job_workflow(steps), self.closure)

    def tail(self):
        return [_step("python3 -m unittest tests.test_x")]

    def test_red_arbitrary_github_path_write_before_bootstrap_is_rejected(self):
        for label, script in {
            "attacker dir": 'echo /tmp/attacker/bin >> "$GITHUB_PATH"',
            "unquoted var": "echo /tmp/attacker/bin >> $GITHUB_PATH",
            "braced var": 'echo /tmp/attacker/bin >> "${GITHUB_PATH}"',
            "tee": 'echo /tmp/attacker/bin | tee -a "$GITHUB_PATH"',
            "printf": 'printf "%s\\n" /tmp/attacker/bin >> "$GITHUB_PATH"',
            "canonical text outside bootstrap step":
                'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"',
            "repo-relative bin": 'echo "$PWD/bin" >> "$GITHUB_PATH"',
        }.items():
            with self.subTest(label):
                self.assertTrue(self.findings(
                    [_step(script), *_canonical_steps(), *self.tail()]),
                    f"accepted: {label}")

    def test_red_github_path_write_in_any_other_position_is_rejected(self):
        evil = 'echo /tmp/attacker/bin >> "$GITHUB_PATH"'
        for label, steps in {
            "between bootstrap and doctor": [
                _step(BOOTSTRAP_CMD), _step(evil), _step(DOCTOR_CMD),
                *self.tail()],
            "after doctor": [*_canonical_steps(), _step(evil), *self.tail()],
            "in the test step": [*_canonical_steps(), _step(
                evil + "\npython3 -m unittest tests.test_x")],
            "mixed into the bootstrap step": [
                _step(BOOTSTRAP_CMD + "\n" + evil), _step(DOCTOR_CMD),
                *self.tail()],
        }.items():
            with self.subTest(label):
                self.assertTrue(self.findings(steps), f"accepted: {label}")

    def test_canonical_export_inside_the_exact_bootstrap_step_is_accepted(self):
        self.assertEqual(self.findings([
            _step(BOOTSTRAP_CMD + '\necho "$PWD/.venv/bin" >> "$GITHUB_PATH"'),
            _step(DOCTOR_CMD), *self.tail()]), [])

    def test_red_real_workflows_reject_an_injected_github_path_write(self):
        import yaml
        evil = ('      - name: evil\n        run: |\n'
                '          echo /tmp/attacker/bin >> "$GITHUB_PATH"\n')
        anchor = ("      - name: Bootstrap canonical CPU test environment "
                  "(Issue #131)\n")
        for path in (CI_WORKFLOW, FINAL_WORKFLOW):
            original = path.read_text(encoding="utf-8")
            mutated = original.replace(anchor, evil + anchor, 1)
            with self.subTest(path.name):
                self.assertNotEqual(mutated, original, "mutation no-op")
                self.assertEqual(cache_policy_findings(
                    yaml.safe_load(original), self.closure), [])
                self.assertTrue(cache_policy_findings(
                    yaml.safe_load(mutated), self.closure))


# ---------------------------------------------------------------------------
# Issue #292 correction round 3 (maintainer re-review of 69b3013).
#
# B1: the forbidden-environment list was a short denylist, so pip inputs it
#     did not name (PIP_CONFIG_FILE, PIP_CONSTRAINT, PIP_REQUIREMENT, ...)
#     could change the index, config or resolver constraints while the
#     requirements-derived cache key stayed unchanged.  pip reads EVERY option
#     from PIP_<OPTION>, so the contract must be an allowlist.
# B2: requirement_closure followed only ``-r file``; ``-c``/``--constraint``
#     (resolver authority), no-space forms (``-rfile``), continuations and
#     other material directives were silently omitted, yielding an incomplete
#     closure and therefore an incomplete cache key.
# ---------------------------------------------------------------------------

class PipEnvironmentAllowlistTests(unittest.TestCase):
    """B1 -- only reviewed environment may reach a validation job."""

    @classmethod
    def setUpClass(cls):
        cls.closure = requirement_closure(REQUIREMENTS, ROOT)

    def workflow_with_env(self, scope: str, name: str, value="/tmp/x") -> dict:
        steps = [_B1_PY_STEP,
                 _actions_cache(PIP_CACHE_PATH, VALID_CACHE_KEY),
                 *_canonical_steps(),
                 _step("python3 -m unittest tests.test_x")]
        workflow = _job_workflow(steps)
        if scope == "workflow":
            workflow["env"] = {name: value}
        elif scope == "job":
            workflow["jobs"]["j"]["env"] = {name: value}
        else:  # a non-canonical step, so the step-role rule cannot mask it
            steps[-1]["env"] = {name: value}
        return workflow

    MATERIAL = (
        # the maintainer's reproductions and their relatives
        "PIP_CONFIG_FILE", "PIP_CONSTRAINT", "PIP_REQUIREMENT",
        # every other PIP_<OPTION> is honoured by pip
        "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_NO_DEPS", "PIP_PRE",
        "PIP_ONLY_BINARY", "PIP_NO_BINARY", "PIP_PROXY", "PIP_TRUSTED_HOST",
        "PIP_CERT", "PIP_CLIENT_CERT", "PIP_NO_CACHE_DIR", "PIP_ISOLATED",
        "PIP_REQUIRE_HASHES", "PIP_USE_FEATURE", "pip_config_file",
        # uv is the bootstrap's documented fallback installer
        "UV_INDEX_URL", "UV_EXTRA_INDEX_URL", "UV_CONSTRAINT", "UV_PYTHON",
        "UV_CACHE_DIR", "UV_NO_INDEX",
        # network / trust / config-location inputs that redirect resolution
        "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy",
        "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE",
        "SSL_CERT_DIR", "HOME", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS",
        "PYTHONUSERBASE", "LD_PRELOAD", "LD_LIBRARY_PATH")

    def test_red_material_pip_and_resolver_env_is_rejected_at_every_level(self):
        for scope in ("workflow", "job", "step"):
            for name in self.MATERIAL:
                for value in ("/tmp/x", "${{ inputs.x }}"):
                    with self.subTest(scope=scope, var=name, value=value):
                        self.assertTrue(
                            cache_policy_findings(
                                self.workflow_with_env(scope, name, value),
                                self.closure),
                            "accepted")

    def test_red_dynamic_whole_mapping_env_is_rejected(self):
        # ``env: ${{ fromJSON(...) }}`` is a string, not a mapping: its keys
        # are unknowable statically, so it could carry PIP_CONFIG_FILE.
        for scope in ("workflow", "job", "step"):
            for value in ("${{ fromJSON(inputs.env) }}",
                          "${{ needs.plan.outputs.env }}"):
                workflow = self.workflow_with_env(scope, "X", None)
                holder = (workflow if scope == "workflow" else
                          workflow["jobs"]["j"] if scope == "job" else
                          workflow["jobs"]["j"]["steps"][-1])
                holder["env"] = value
                with self.subTest(scope=scope, value=value):
                    self.assertTrue(cache_policy_findings(
                        workflow, self.closure), "accepted")

    def test_red_unreviewed_setup_python_inputs_are_rejected(self):
        # Newer setup-python releases can install packages or pin pip
        # themselves, bypassing the canonical bootstrap's resolver inputs.
        for name, value in (("pip-install", "requests"),
                            ("pip-version", "99.0"),
                            ("python-version-file", "/tmp/evil"),
                            ("token", "x"), ("architecture", "x86"),
                            ("update-environment", False)):
            workflow = self.workflow_with_env("job", "CI", "1")
            workflow["jobs"]["j"]["steps"][0] = {
                **_B1_PY_STEP, "with": {**_B1_PY_STEP["with"], name: value}}
            with self.subTest(name):
                self.assertTrue(cache_policy_findings(
                    workflow, self.closure), "accepted")

    def test_reviewed_setup_python_inputs_remain_accepted(self):
        workflow = self.workflow_with_env("job", "CI", "1")
        workflow["jobs"]["j"]["steps"][0] = {**_B1_PY_STEP, "with": {
            "python-version": "3.12", "cache": "pip",
            "cache-dependency-path": "\n".join(sorted(self.closure))}}
        self.assertEqual(cache_policy_findings(workflow, self.closure), [])

    def test_reviewed_env_remains_accepted(self):
        for scope in ("workflow", "job", "step"):
            with self.subTest(scope):
                self.assertEqual(cache_policy_findings(
                    self.workflow_with_env(
                        scope, "PIP_DISABLE_PIP_VERSION_CHECK", "1"),
                    self.closure), [])

    def test_unrelated_env_remains_accepted(self):
        for name in ("GITHUB_TOKEN_UNUSED", "CI", "MY_FLAG", "TZ"):
            with self.subTest(name):
                self.assertEqual(cache_policy_findings(
                    self.workflow_with_env("job", name, "1"),
                    self.closure), [])

    def test_real_workflows_reject_injected_pip_resolver_env(self):
        import copy
        import yaml
        for path in (CI_WORKFLOW, FINAL_WORKFLOW):
            real = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(
                cache_policy_findings(real, self.closure), [], path.name)
            for name in ("PIP_CONFIG_FILE", "PIP_CONSTRAINT"):
                for level in ("workflow", "every job", "every step"):
                    mutated = copy.deepcopy(real)
                    if level == "workflow":
                        mutated.setdefault("env", {})[name] = "/tmp/x"
                    for job in mutated["jobs"].values():
                        if level == "every job":
                            job.setdefault("env", {})[name] = "/tmp/x"
                        elif level == "every step":
                            for step in job["steps"]:
                                step.setdefault("env", {})[name] = "/tmp/x"
                    with self.subTest(path.name, var=name, level=level):
                        self.assertTrue(
                            cache_policy_findings(mutated, self.closure))

    def test_real_workflows_still_pass_the_env_allowlist(self):
        import yaml
        for path in (CI_WORKFLOW, FINAL_WORKFLOW):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(
                cache_policy_findings(workflow, self.closure), [], path.name)


class RequirementClosureAuthorityTests(unittest.TestCase):
    """B2 -- the closure must contain every local resolver-authority file or
    fail closed; never return an incomplete closure."""

    def closure_of(self, files: dict[str, str]) -> set[str]:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            for name, body in files.items():
                write(repo / name, body)
            return requirement_closure(repo / "root.txt", repo)

    def test_red_constraint_references_are_in_the_closure(self):
        for label, root in {
            "-c file": "pkg-a\n-c constraints.txt\n",
            "-c no space": "pkg-a\n-cconstraints.txt\n",
            "--constraint file": "pkg-a\n--constraint constraints.txt\n",
            "--constraint=file": "pkg-a\n--constraint=constraints.txt\n",
            "-c with comment": "pkg-a\n-c constraints.txt  # pin\n",
            "-c via continuation": "pkg-a\n-c \\\nconstraints.txt\n",
        }.items():
            with self.subTest(label):
                self.assertEqual(
                    self.closure_of({"root.txt": root,
                                     "constraints.txt": "pkg-a==1\n"}),
                    {"root.txt", "constraints.txt"})

    def test_red_requirement_no_space_and_continuation_forms_are_followed(self):
        for label, root in {
            "-rfile": "pkg-a\n-rnested.txt\n",
            "--requirement=file": "pkg-a\n--requirement=nested.txt\n",
            "--requirement file": "pkg-a\n--requirement nested.txt\n",
            "-r via continuation": "pkg-a\n-r \\\nnested.txt\n",
        }.items():
            with self.subTest(label):
                self.assertEqual(
                    self.closure_of({"root.txt": root, "nested.txt": "pkg-b\n"}),
                    {"root.txt", "nested.txt"})

    def test_red_nested_and_recursive_constraints_are_followed(self):
        self.assertEqual(self.closure_of({
            "root.txt": "pkg-a\n-r sub/mid.txt\n",
            "sub/mid.txt": "pkg-b\n-c ../constraints/pins.txt\n",
            "constraints/pins.txt": "pkg-b==2\n-c more.txt\n",
            "constraints/more.txt": "pkg-c==3\n"}),
            {"root.txt", "sub/mid.txt", "constraints/pins.txt",
             "constraints/more.txt"})

    def test_red_unhandled_material_directives_fail_closed(self):
        directives = {
            "--find-links": "--find-links /tmp/wheels", "-f": "-f /tmp/wheels",
            "--index-url": "--index-url https://evil.example/simple",
            "-i": "-i https://evil.example/simple",
            "--extra-index-url": "--extra-index-url https://evil.example/s",
            "--no-index": "--no-index", "--trusted-host": "--trusted-host x",
            "--pre": "--pre", "--only-binary": "--only-binary :all:",
            "--no-binary": "--no-binary :all:",
            "--prefer-binary": "--prefer-binary",
            "--require-hashes": "--require-hashes",
            "-e editable": "-e .", "--editable": "--editable ./pkg",
            "--use-feature": "--use-feature=fast-deps",
            "--config-settings": "--config-settings x=y",
            "unknown option": "--frobnicate",
        }
        for label, line in directives.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.closure_of({"root.txt": f"pkg-a\n{line}\n"})

    def test_red_non_registry_or_dynamic_requirement_lines_fail_closed(self):
        for label, line in {
            "local path": "./local-pkg",
            "parent path": "../other",
            "absolute path": "/opt/pkg",
            "direct file reference": "pkg @ file:///tmp/pkg.whl",
            "direct url reference": "pkg @ https://evil.example/pkg.whl",
            "bare url": "https://evil.example/pkg.whl",
            "per-requirement hash option": "pkg==1 --hash=sha256:ab",
            "env expansion": "pkg==${PKG_VERSION}",
            "option after marker": "pkg==1 ; python_version>'3' --hash=sha256:a",
        }.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.closure_of({"root.txt": f"pkg-a\n{line}\n"})

    def test_red_non_local_or_escaping_include_paths_fail_closed(self):
        for label, line in {
            "url include": "-r https://evil.example/req.txt",
            "file scheme": "-r file:///tmp/req.txt",
            "absolute include": "-r /etc/hosts",
            "home include": "-r ~/req.txt",
            "escapes repository": "-r ../outside.txt",
            "constraint url": "-c https://evil.example/c.txt",
            "constraint absolute": "-c /etc/hosts",
            "env expansion in path": "-c ${CONSTRAINTS}",
        }.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.closure_of({"root.txt": f"pkg-a\n{line}\n"})

    def test_missing_included_file_fails_closed(self):
        with self.assertRaises((ValueError, OSError)):
            self.closure_of({"root.txt": "pkg-a\n-c missing.txt\n"})

    def test_plain_specifiers_comments_and_blank_lines_are_accepted(self):
        self.assertEqual(self.closure_of({"root.txt": (
            "# comment\n\njsonschema>=4.18,<5\nnumpy>=1.26,<3  # why\n"
            "pkg[extra,more]==1.0.0 ; python_version >= '3.10'\n"
            "Jinja2==3.1.6\nMarkupSafe==3.0.3\n   \npkg-b\n")}),
            {"root.txt"})

    def test_real_authority_closure_is_unchanged(self):
        self.assertEqual(requirement_closure(REQUIREMENTS, ROOT),
                         {"requirements-test.txt", NESTED_FROZEN_REQUIREMENTS})

    # -- behavioural: a constraint change must change an accepted key -------
    def test_red_constraint_change_invalidates_an_accepted_key(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            write(repo / "root.txt", "pkg-a\n-c constraints.txt\n")
            write(repo / "constraints.txt", "pkg-a==1\n")
            closure = requirement_closure(repo / "root.txt", repo)
            self.assertIn("constraints.txt", closure)
            key = ("pip-${{ runner.os }}-${{ runner.arch }}-"
                   "py${{ steps.py.outputs.python-version }}-"
                   "${{ hashFiles('root.txt', 'constraints.txt') }}")
            workflow = _job_workflow([
                _B1_PY_STEP, _actions_cache(PIP_CACHE_PATH, key),
                *_canonical_steps(), _step("python3 -m unittest tests.test_x")])
            self.assertEqual(cache_policy_findings(workflow, closure), [])
            args = dict(os_name="Linux", arch="X64", python_version="3.12.15")
            before = simulate_cache_key(key, repo, **args)
            write(repo / "constraints.txt", "pkg-a==2\n")
            self.assertNotEqual(before, simulate_cache_key(key, repo, **args))

    def test_red_key_that_omits_a_constraint_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            write(repo / "root.txt", "pkg-a\n-c constraints.txt\n")
            write(repo / "constraints.txt", "pkg-a==1\n")
            closure = requirement_closure(repo / "root.txt", repo)
            key = ("pip-${{ runner.os }}-${{ runner.arch }}-"
                   "py${{ steps.py.outputs.python-version }}-"
                   "${{ hashFiles('root.txt') }}")
            workflow = _job_workflow([
                _B1_PY_STEP, _actions_cache(PIP_CACHE_PATH, key),
                *_canonical_steps(), _step("python3 -m unittest tests.test_x")])
            findings = cache_policy_findings(workflow, closure)
            self.assertTrue(any("constraints.txt" in f for f in findings),
                            findings)


if __name__ == "__main__":
    unittest.main()
