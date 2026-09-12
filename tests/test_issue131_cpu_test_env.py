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


class DependencyAuthorityTests(unittest.TestCase):
    """The single repository-owned dependency definition."""

    def test_authority_exists_and_declares_expected_direct_packages(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        packages, references = doctor.parse_requirements(text)
        self.assertEqual(packages, {"jsonschema", "numpy", "pyyaml"})
        self.assertEqual(references, {doctor.REFERENCED_REQUIREMENTS[0]})

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

    def test_bootstrap_rejects_venvs_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "bootstrap_test_env.py"),
                 "--venv", str(Path(directory) / "escape-venv")],
                capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("inside the repository", result.stderr)

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
        bootstrap.create_venv = lambda venv_dir: venv_dir / "bin" / "python"
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


class EnvironmentPurityTests(unittest.TestCase):
    """The CPU test environment must not carry model runtimes."""

    def test_this_interpreters_environment_is_model_runtime_free(self):
        violations = bootstrap.forbidden_installed(Path(sys.executable))
        self.assertEqual(violations, [])

    def test_doctor_passes_in_a_canonical_environment(self):
        """The real repository state satisfies the doctor end to end."""
        findings = doctor.doctor()
        self.assertEqual(findings, [], [str(f) for f in findings])


if __name__ == "__main__":
    unittest.main()
