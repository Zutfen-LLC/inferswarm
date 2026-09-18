#!/usr/bin/env python3
"""Issue #216 — V2-D execution runner (shared correctness-bearing seam).

One frozen execution primitive used by baselines, concurrent pairs, soak
checkpoints, and fault/recovery sentinels:

  run_execution(...): argv built ONLY from authority runtime + fresh
  mapping selector; retains stdout/stderr/exit-code/observe-record bytes
  durably; derives the cross-check fields (correctness via the ACCEPTED
  V0-C comparator, accounting via the ACCEPTED V1-C reducer, offload
  from the runtime's own offload line, selected-BDF from the runtime's
  own selected-device line) — all re-derived later by the assembler
  from these same retained bytes; the payload's derived fields are
  cross-checks, never authority.

The #219 seam (corrected instrument build) supplies GPU-work overlap
observation whenever `observe_out` is given: the env-gated
GGML_VK_OBSERVE_INTERVAL=<file> activates the qualified instrument.
Overlap classification itself happens in the assembler (imported #219
reducer machinery), never in this runner.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue216_host as host

PROMPT = ("The quick brown fox jumps over the lazy dog. "
          "Explain what happens next in one sentence:")
N_TOKENS = 48


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def execution_argv(runtime_exe: str, model: str, selector: str,
                   n_tokens: int = N_TOKENS) -> list[str]:
    return [runtime_exe, "-m", model, "--temp", "0", "--seed", "42",
            "-n", str(n_tokens), "-ngl", "99", "--device", selector,
            "-lv", "4", "-p", PROMPT, "-st"]


def parse_selected_bdf(stderr_text: str) -> str | None:
    for line in stderr_text.splitlines():
        m = re.search(r"using device.*?([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}"
                      r"\.[0-9a-f])", line)
        if m:
            return m.group(1)
        m = re.search(r"using device.*?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9])",
                      line)
        if m:
            return m.group(1)
    return None


def parse_offload(stderr_text: str) -> list[int] | None:
    m = re.search(r"offloaded (\d+)/(\d+) layers", stderr_text)
    if not m:
        return None
    return [int(m.group(1)), int(m.group(2))]


def run_execution(*, argv: list[str], out_dir: Path, label: str,
                  env_extra: dict[str, str] | None = None,
                  expected_selector_bdf: str | None = None,
                  timeout: int = 1800) -> dict[str, Any]:
    """Run one frozen execution; retain raw bytes; derive cross-checks."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    start = time.monotonic_ns()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout,
                           env=env)
        rc, stdout, stderr = p.returncode, p.stdout, p.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc = 124
        stdout = exc.stdout or b""
        stderr = (exc.stderr or b"") + b"\nV2D_EXECUTION_TIMEOUT\n"
        timed_out = True
    end = time.monotonic_ns()
    host.durable_write(out_dir / f"{label}.stdout", stdout)
    host.durable_write(out_dir / f"{label}.stderr", stderr)
    host.durable_write(out_dir / f"{label}.exit-code",
                       f"{rc}\n".encode())
    stderr_text = stderr.decode("utf-8", "replace")
    return {
        "label": label,
        "argv": argv,
        "workload_interval_ns": [start, end],
        "timed_out": timed_out,
        "exit_code": rc,
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_rel": f"{label}.stdout",
        "stderr_rel": f"{label}.stderr",
        "exit_code_rel": f"{label}.exit-code",
        "selected_bdf": parse_selected_bdf(stderr_text),
        "offloaded_layers": parse_offload(stderr_text),
        "fallback_present": "fallback" in stderr_text.lower(),
    }


def correctness_semantics(argv: list[str]) -> str:
    """The frozen correctness contract, derived from the run's own argv.

    -n 8 (bounded sentinel): byte-exact PREFIX of the accepted reference
    (accepted V2-C sentinel semantics). -n 48 (full subject): byte-exact
    EQUALITY with the accepted reference (accepted V2-B/V2-D0 semantics).
    Any other -n value fails closed at derivation.
    """
    n = int(argv[argv.index("-n") + 1])
    if n == 8:
        return "byte-exact-prefix-of-reference"
    if n == 48:
        return "byte-exact-equality-with-reference"
    raise ValueError(f"unfrozen token count in argv: -n {n}")


def reduce_correctness(stdout: bytes, reference: bytes,
                      semantics: str) -> dict[str, Any]:
    """Apply the frozen comparator with the run's own semantics."""
    visible = extract_visible(stdout)
    if semantics == "byte-exact-prefix-of-reference":
        ok = bool(visible) and reference.startswith(visible)
    elif semantics == "byte-exact-equality-with-reference":
        ok = visible == reference
    else:
        raise ValueError(f"unknown semantics: {semantics}")
    return {"visible_response_sha256": sha256_bytes(visible),
            "byte_exact_visible_output": ok}


def extract_visible(transcript: bytes) -> bytes:
    import v0c_correctness
    return v0c_correctness.extract_visible_response(
        transcript, PROMPT.encode())


def derive_execution_facts(repo: Path, run: dict[str, Any],
                           out_dir: Path) -> dict[str, Any]:
    """Re-derive correctness/accounting from retained bytes with the
    ACCEPTED parsers (same functions the assembler re-runs; used here
    only as collector cross-checks)."""
    sys.path.insert(0, str(repo / "scripts"))
    import v1c_accounting
    stdout = (out_dir / run["stdout_rel"]).read_bytes()
    stderr_text = (out_dir / run["stderr_rel"]).read_text(
        encoding="utf-8", errors="replace")
    reference = (repo / "docs/investigations/vulkan-v1-a/"
                 "reference-visible-output.txt").read_bytes()
    semantics = correctness_semantics(run["argv"])
    correctness = reduce_correctness(stdout, reference, semantics)
    selector = run["argv"][run["argv"].index("--device") + 1]
    accounting = v1c_accounting.parse_accounting(
        stderr_text, selector=selector)
    run_out = dict(run)
    run_out["correctness_semantics"] = semantics
    run_out["correctness_crosscheck"] = {
        "visible_response_sha256": correctness["visible_response_sha256"],
        "byte_exact_visible_output": correctness["byte_exact_visible_output"],
    }
    run_out["accounting_crosscheck"] = accounting
    return run_out


def reduce_run(run: dict[str, Any]) -> dict[str, Any]:
    """Pure derivation of the correctness/offload/accounting verdict from
    the derived facts (assembler-side helper; same logic the assembler
    applies over receipts)."""
    acct = run.get("accounting_crosscheck") or {}
    acct_clean = all(acct.get(k) == 0 for k in (
        "unexplained_persistent_host_mirror_bytes",
        "source_fetches_after_ready", "unplanned_state_movements"))
    offload = run.get("offloaded_layers")
    full_offload = bool(offload and offload[0] == offload[1]
                        and offload[0] > 0)
    correct = (run.get("exit_code") == 0 and not run.get("timed_out")
               and (run.get("correctness_crosscheck") or {}).get(
                   "byte_exact_visible_output") is True
               and full_offload and not run.get("fallback_present"))
    return {
        "clean_exit": run.get("exit_code") == 0 and not run.get("timed_out"),
        "byte_exact": bool((run.get("correctness_crosscheck") or {}).get(
            "byte_exact_visible_output")),
        "full_offload": full_offload,
        "no_fallback": not run.get("fallback_present"),
        "accounting_tuple_zero": acct_clean,
        "correct": correct,
        "selected_bdf": run.get("selected_bdf"),
    }
