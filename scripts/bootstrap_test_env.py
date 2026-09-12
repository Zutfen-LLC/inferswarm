#!/usr/bin/env python3
"""Bootstrap the canonical CPU test environment (Issue #131).

Creates or refreshes the repository-local ``.venv`` and installs the
canonical CPU test dependency set declared in ``requirements-test.txt``
(the single dependency authority, which itself installs the immutable
Issue #117 frozen tokenizer requirements by reference).

Contract:

- **Idempotent** — safe to run repeatedly; an existing healthy ``.venv``
  with the canonical interpreter is reused and re-installed with the
  same requirement set.
- **Python 3.12** — the canonical suite interpreter. An existing venv is
  reused only after its real interpreter's major/minor matches the
  request; a mismatched venv is recreated (only after target safety is
  proven, never before).
- **CPU-only** — refuses to install any model runtime (torch/triton/
  vLLM/xformers/flash-attn and every NVIDIA/CUDA runtime distribution,
  matched by normalized family rule); the requirement graph is screened
  before installation and the environment is re-screened after
  installation so transitive contamination fails closed.
- **Safe by construction, not by after-digest** — the venv target is
  restricted to exactly ``<repo>/.venv`` (a gitignored, dedicated
  environment directory, checked before any deletion); there is no
  ``--venv`` override, so a tracked/ordinary directory can never be
  rmtree'd. The tracked-file before/after digest remains as a reporting
  guard, never as the primary protection.
- **Non-mutating to the working tree** — writes only inside ``.venv/``
  (gitignored) and ``/tmp``.
- **Offline of model runtimes only** — installs from PyPI; it never
  contacts a GPU node or downloads model weights.

Usage::

    python3 scripts/bootstrap_test_env.py            # bootstrap .venv (Python 3.12)
    python3 scripts/bootstrap_test_env.py --python 3.12

The canonical suite interpreter is Python 3.12: the accepted Issue
#129 real-tokenizer proof pins its frozen software identity to 3.12,
so the bootstrap requests a 3.12 interpreter (using the launching
interpreter, an installed ``python3.12``, or a ``uv``-managed 3.12 when
the system python differs) and the doctor rejects any other minor
version.

Afterwards run the doctor and the suite::

    .venv/bin/python scripts/check_test_env.py
    .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-test.txt"
VENV = ROOT / ".venv"

# Model-runtime packages prohibited from the CPU test environment
# (Issue #131: heavy GPU/model dependencies must not enter the ordinary
# CPU bootstrap). Explicit framework/runtime names cover the frameworks
# themselves; every NVIDIA/CUDA runtime distribution family (nvidia-*,
# *-cu11/*-cu12/... wheels, cuda-python, ptxas, ...) is additionally
# rejected by the normalized prefix/family rule below, so the common
# runtime wheels (nvidia-cuda-nvrtc-cu12, nvidia-nccl-cu12,
# nvidia-cufft-cu12, nvidia-cusolver-cu12, ...) cannot slip through an
# incomplete exemplar list.
EXPLICIT_FORBIDDEN_PACKAGES = frozenset({
    "torch", "torchvision", "torchaudio", "triton", "cuda-python",
    "xformers", "vllm", "flash-attn",
})

# The freeze takes a module-level import of the doctor so negative
# controls can assert the contract constants without a subprocess.
sys.path.insert(0, str(ROOT / "scripts"))


def _normalize_name(name: str) -> str:
    """PEP 503 distribution-name normalization."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def is_forbidden_package(name: str) -> bool:
    """True when a distribution name is a prohibited model runtime.

    Mechanical family rule, not an exemplar list:

    - explicit framework/runtime names (torch, triton, vllm, ...); or
    - any ``nvidia-*`` distribution (the NVIDIA runtime wheel family);
    - any distribution carrying a CUDA runtime tag (``*-cu11``,
      ``*-cu12``, ``*-cu13``, ``*-cuda*``, ``cuda-*``, ``*-*-cuNN``);
    - the CUDA toolchain front-ends (ptxas, cuobjdump, nvjitlink...).
    """
    normalized = _normalize_name(name)
    if normalized in EXPLICIT_FORBIDDEN_PACKAGES:
        return True
    if normalized.startswith(("nvidia-", "pytorch-triton")):
        return True
    if re.search(r"(?:^|-)cu(?:1[0-9]|[2-9])(?:$|-)", normalized):
        return True
    if re.search(r"(?:^|-)cuda(?:-|$)", normalized):
        return True
    if normalized in {"ptxas", "cuobjdump", "nvcc", "nvidia"}:
        return True
    return False


def tracked_file_digests() -> dict[str, str]:
    """Digest every tracked path (staged content or HEAD blob)."""
    digests: dict[str, str] = {}
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, check=True).stdout
    for relative in listing.split(b"\0"):
        if not relative:
            continue
        path = ROOT / relative.decode()
        if path.is_file() and not path.is_symlink():
            digests[relative.decode()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return digests


def forbidden_in_requirements(text: str) -> list[str]:
    """Return forbidden package names referenced by a requirements text."""
    found: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None:
            continue
        name = _normalize_name(match.group(1))
        if is_forbidden_package(name):
            found.append(name)
    return found


def forbidden_installed(python: Path) -> list[str]:
    """Return forbidden packages present in the environment."""
    probe = (
        "import importlib.metadata as m\n"
        "seen = set()\n"
        "for d in m.distributions():\n"
        "    n = (d.metadata.get('Name') or '').strip()\n"
        "    if n:\n"
        "        seen.add(n)\n"
        "for n in sorted(seen):\n"
        "    print(n)\n"
    )
    result = subprocess.run([str(python), "-c", probe],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("environment enumeration failed: "
                           + result.stderr.strip())
    return [name for name in (_normalize_name(line)
                              for line in result.stdout.splitlines()
                              if line.strip())
            if is_forbidden_package(name)]


def _fail(message: str) -> NoReturn:
    print(f"bootstrap: {message}", file=sys.stderr)
    raise SystemExit(1)


def venv_interpreter_version(python: Path) -> tuple[int, int] | None:
    """Major/minor of the venv's real interpreter, or None if unknowable."""
    probe = (
        "import sys\n"
        "print(sys.version_info.major, sys.version_info.minor)\n"
    )
    result = subprocess.run([str(python), "-c", probe],
                            capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        major, minor = result.stdout.split()
        return int(major), int(minor)
    except ValueError:
        return None


def venv_python_request(venv_dir: Path) -> str | None:
    """Parse the major/minor recorded by a standard or uv pyvenv.cfg.

    CPython's stdlib writes ``version = X.Y.Z``; uv writes
    ``version_info = X.Y.Z``. Both are bootstrap-owned venv metadata,
    but missing/malformed values are not acceptable reuse evidence.
    """
    config = venv_dir / "pyvenv.cfg"
    if not config.is_file():
        return None
    match = re.search(
        r"^(?:version|version_info)\s*=\s*(\d+\.\d+)(?:\.\d+)?\s*$",
        config.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def validate_venv_target(venv_dir: Path) -> None:
    """Mechanically prove ``venv_dir`` is a dedicated venv location.

    This runs BEFORE any creation or deletion. The only accepted target
    is the repository-local ``.venv`` — a dedicated, gitignored,
    untracked environment directory. Because the accepted target is a
    constant, the check has no arbitrary-path surface: a tracked
    repository directory, the repository root, or any other path can
    never reach ``shutil.rmtree``. The remaining checks prove the
    constant target itself is safe on this machine (untracked,
    gitignored, not a symlink escape, and — when it already exists —
    genuinely a venv home or absent).
    """
    try:
        resolved = venv_dir.resolve(strict=False)
    except OSError as error:
        _fail(f"cannot resolve the venv target: {error}")
    if venv_dir.is_symlink() or (
            venv_dir.exists() and not venv_dir.is_dir()):
        _fail(f"refusing venv target {venv_dir}: it is a symlink or a "
              "non-directory; resolve it manually if this is unexpected")
    if resolved != VENV:
        _fail(
            f"refusing venv target {venv_dir}: the bootstrap manages "
            f"exactly the repository-local {VENV} (gitignored, dedicated); "
            "arbitrary --venv targets are not supported")
    # Untracked and gitignored — a tracked or staged target is a defect.
    try:
        listing = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", "--", str(venv_dir)],
            capture_output=True, check=True).stdout
        # A trailing slash makes directory patterns (".venv/") match
        # even when the target does not exist yet (clean CI checkout).
        ignored = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "--quiet",
             str(venv_dir) + "/"]).returncode == 0
    except subprocess.CalledProcessError as error:
        _fail(f"cannot inspect git state for the venv target "
              f"(is {ROOT} a git repository?): {error}")
    if listing.strip(b"\0"):
        _fail(f"refusing venv target {venv_dir}: it contains tracked "
              "repository content")
    if not ignored:
        _fail(f"refusing venv target {venv_dir}: it is not gitignored; "
              "add it to .gitignore before bootstrapping")
    if venv_dir.exists() and not (venv_dir / "pyvenv.cfg").is_file():
        # Never infer bootstrap ownership from directory shape.  Names
        # such as bin/lib/include/share are ordinary user-directory
        # names too; `.venv/bin/keep.txt` must not become rmtree input.
        # Automatic partial-creation recovery would require an explicit
        # bootstrap-owned marker created BEFORE creation; none exists, so
        # fail closed and require human inspection/cleanup instead.
        _fail(
            f"refusing venv target {venv_dir}: it already exists without "
            "a bootstrap-owned pyvenv.cfg; refusing to recursively delete "
            "a possibly ordinary directory. Inspect it and remove it "
            "manually only if it is a disposable failed venv")


def _request_tuple(python_request: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)", python_request.strip())
    if match is None:
        _fail(f"invalid --python request {python_request!r}: expected "
              "'<major>.<minor>' (e.g. 3.12)")
    return int(match.group(1)), int(match.group(2))


def _installed_python_for(request: tuple[int, int]) -> str | None:
    """An installed pythonX.Y executable for the request, or None."""
    name = f"python{request[0]}.{request[1]}"
    found = shutil.which(name)
    return found


def _launching_version() -> tuple[int, int]:
    """Major/minor of the interpreter running this script."""
    return (sys.version_info.major, sys.version_info.minor)


def create_venv(venv_dir: Path, python_request: str = "3.12") -> Path:
    """Create or reuse the venv, verifying the existing interpreter.

    Reuse requires an existing ``pyvenv.cfg`` plus a working
    ``bin/python`` whose REAL major/minor matches ``python_request``.
    A mismatched (e.g. stale 3.13) venv is recreated — but only after
    ``validate_venv_target`` has already proven the target is a
    dedicated, untracked, gitignored venv home, never before.

    Interpreter resolution order for creation: the launching
    interpreter if it matches, then an installed ``pythonX.Y``, then a
    ``uv``-managed interpreter. A missing ``uv`` is a deterministic,
    actionable failure, never an uncaught exception.
    """
    request = _request_tuple(python_request)
    validate_venv_target(venv_dir)

    python = venv_dir / "bin" / "python"
    if (venv_dir / "pyvenv.cfg").is_file() and python.exists():
        existing = venv_interpreter_version(python)
        recorded = venv_python_request(venv_dir)
        if existing is not None and existing == request and (
                recorded == python_request):
            return python  # verified healthy venv: reuse
        # Stale or unverifiable interpreter: recreate (target already
        # proven safe above). Report what was found.
        shutil.rmtree(venv_dir, ignore_errors=True)
        if venv_dir.exists():
            _fail(f"cannot remove the stale virtual environment at "
                  f"{venv_dir}; remove it manually and re-run")
    elif venv_dir.exists():
        # A partial venv from a failed creation attempt is not reusable.
        shutil.rmtree(venv_dir, ignore_errors=True)

    launching = _launching_version()
    base = None
    if launching == request:
        base = sys.executable
    else:
        base = _installed_python_for(request)
    if base is not None:
        if subprocess.run([base, "-m", "venv", str(venv_dir)],
                          capture_output=True).returncode == 0:
            return venv_dir / "bin" / "python"
        # stdlib venv may fail (Debian ships venv without ensurepip).
        shutil.rmtree(venv_dir, ignore_errors=True)
    if shutil.which("uv") is None:
        requested = f"{request[0]}.{request[1]}"
        executable = f"python{request[0]}.{request[1]}"
        _fail(
            f"cannot create the Python {requested} virtual environment: "
            f"the launching interpreter is {launching[0]}.{launching[1]}, "
            f"no installed {executable} was found on PATH, and 'uv' is "
            f"not installed. Install {executable} with its venv module "
            f"(for example: install a Python {requested} package that "
            f"provides `{executable} -m venv`) or install uv "
            "<https://docs.astral.sh/uv/>, then re-run.")
    uv = subprocess.run(["uv", "venv", "--python", python_request,
                         str(venv_dir)], capture_output=True)
    if uv.returncode != 0:
        _fail(f"cannot create the Python {python_request} virtual "
              "environment: stdlib venv and uv both failed; install "
              f"python{python_request}-venv or uv")
    return venv_dir / "bin" / "python"


def pip_available(python: Path) -> bool:
    return subprocess.run([str(python), "-m", "pip", "--version"],
                          capture_output=True).returncode == 0


def install(python: Path, *args: str) -> None:
    """Install with stdlib pip, falling back to ``uv pip``."""
    if pip_available(python):
        command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", *args]
        completed = subprocess.run(command)
    elif shutil.which("uv") is not None:
        completed = subprocess.run(
            ["uv", "pip", "install", "--python", str(python), *args])
    else:
        _fail("dependency installation failed: neither pip nor uv is "
              "available in the environment")
    if completed.returncode != 0:
        _fail("dependency installation failed (exit "
              f"{completed.returncode})")


def bootstrap(venv_dir: Path = VENV, python_request: str = "3.12") -> Path:
    """Create/refresh the environment; returns the venv interpreter."""
    if not REQUIREMENTS.is_file():
        _fail(f"missing dependency authority: {REQUIREMENTS}")

    requirements_text = REQUIREMENTS.read_text(encoding="utf-8")
    violations = forbidden_in_requirements(requirements_text)
    if violations:
        _fail("dependency authority declares model-runtime packages ("
              + ", ".join(violations) + ") — refusing to bootstrap")

    # Referenced frozen requirement files inherit the same screen.
    for raw_line in requirements_text.splitlines():
        line = raw_line.strip()
        if line.startswith("-r "):
            referenced = (ROOT / line[3:].strip()).resolve()
            if not referenced.is_file():
                _fail(f"referenced requirements file is missing: {referenced}")
            violations = forbidden_in_requirements(
                referenced.read_text(encoding="utf-8"))
            if violations:
                _fail("referenced requirements declare model-runtime "
                      "packages (" + ", ".join(violations) + ") — "
                      "refusing to bootstrap")

    # Target safety is proven BEFORE any destructive operation; the
    # tracked-file digest below is a reporting guard on top of that
    # structural protection, never the primary one.
    validate_venv_target(venv_dir)
    before = tracked_file_digests()
    python = create_venv(venv_dir, python_request)
    install(python, "-r", str(REQUIREMENTS))
    present = forbidden_installed(python)
    if present:
        _fail("model-runtime packages entered the CPU environment ("
              + ", ".join(present) + ") — this is a dependency-authority "
              "bug; the environment is not qualified for the CPU suite")
    after = tracked_file_digests()
    if before != after:
        changed = sorted(set(before) ^ set(after)
                         | {p for p in set(before) & set(after)
                            if before[p] != after[p]})
        _fail("bootstrap modified tracked repository files: "
              + ", ".join(changed))
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--python", default="3.12", dest="python_request",
        help="canonical suite interpreter request (default: 3.12; the "
             "Issue #129 frozen tokenizer identity pins it)")
    args = parser.parse_args(argv)
    python = bootstrap(VENV, args.python_request)
    print("CPU test environment ready:", python)
    print("Next: run the doctor and the suite:")
    print(f"  {python} scripts/check_test_env.py")
    print(f"  {python} -m unittest discover -s tests -p 'test_*.py'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
