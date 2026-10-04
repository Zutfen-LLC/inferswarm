#!/usr/bin/env python3
"""Issue #273 Phase 2 — source-level mutation testing.

Mutates the CORRECTED production surfaces (issue273_admission.py,
issue273_reducer.py, issue270_physical.py) one mutation at a time and
verifies the focused test module catches each (exit non-zero). Any
SURVIVED mutation is a coverage hole to fix before merge.

Run from the worktree root: python3 scripts/issue273_mutation_check.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "scripts/issue273_admission.py": [
        # (name, old, new) — each must be caught by the test suite
        ("arm-icd-swap-ref",
         '"reference": C.NVIDIA_ICD',
         '"reference": C.RADV_ICD'),
        ("placement-flatten-ref-8to7",
         '"reference": REFERENCE_PLACEMENT_NGL',
         '"reference": 7'),
        ("placement-flatten-cand-7to8",
         '"candidate": CANDIDATE_PLACEMENT_NGL',
         '"candidate": 8'),
        ("identity-drop-process-attribution",
         '"ngl", "subject_identity", "process_attribution",',
         '"ngl", "subject_identity",'),
        ("identity-drop-icd",
         '"arm", "host", "bdf", "icd", "selector",',
         '"arm", "host", "bdf", "selector",'),
        ("env-icd-check-removed",
         'if env.get("VK_ICD_FILENAMES") != want_icd:',
         'if False:'),
        ("cuda-fence-removed",
         'if receipt.get("cuda_visible_devices") != "-1":',
         'if False:'),
        ("argv-ngl-check-removed",
         'if "-ngl" in argv_s:',
         'if False:'),
        ("proc-host-check-removed",
         'if proc_host is not None and proc_host != expected_host(arm):',
         'if False:'),
        ("row-aliasing-check-removed",
         'if ref_rows[d].get("sha256") == cand_rows[d].get("sha256"):',
         'if False:'),
        ("same-source-check-removed",
         'if ref_src is not None and ref_src == cand_src:',
         'if False:'),
        ("distinct-pid-check-removed",
         'if ref_pa.get(field) == cand_pa.get(field):',
         'if False:'),
        ("det-gate-removed",
         'if reference_deterministic is not True:',
         'if False:'),
        ("staged-source-schema-removed",
         'or binding.get("schema") != STAGED_SOURCE_SCHEMA:',
         'or False:'),
    ],
    "scripts/issue273_reducer.py": [
        ("ref-nondet-terminal-degraded",
         'return _blocked(\n                TERMINAL_REFERENCE_NONDETERMINISTIC_273,',
         'return _blocked(\n                TERMINAL_RUNTIME_BLOCKED_273,'),
        ("ref-det-check-disabled",
         'if ref_det is not True:',
         'if False:'),
        ("legacy-namespace-allowed",
         '"c270-",                          # the invalidated #270 namespace',
         ''),
        ("pass-on-problems",
         '    if problems:\n        return _blocked(TERMINAL_RUNTIME_BLOCKED_273, problems)',
         '    if problems and False:\n        return _blocked(TERMINAL_RUNTIME_BLOCKED_273, problems)'),
    ],
    "scripts/issue270_physical.py": [
        ("vram-total-capture-removed",
         'die_raw["mem_info_vram_total"] = sysfs_reader(\n            bdf, "mem_info_vram_total")',
         'pass'),
    ],
}


def run_tests(python: str) -> bool:
    proc = subprocess.run(
        [python, "-m", "unittest", "tests.test_issue273_admission"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    return proc.returncode == 0


def main() -> int:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    baseline = run_tests(python)
    if not baseline:
        print("BASELINE FAILS — fix tests before mutation run")
        return 2
    print("baseline: PASS")
    survived, killed, broken = [], [], []
    for rel, mutations in MODULES.items():
        path = ROOT / rel
        original = path.read_text()
        backup = Path(tempfile.mkstemp(suffix=".bak")[1])
        backup.write_text(original)
        try:
            for name, old, new in mutations:
                src = backup.read_text()
                if src.count(old) == 0:
                    broken.append((rel, name, "anchor not found"))
                    continue
                if new and src.count(new.split("\n")[0]) and \
                        src.replace(old, new) == src:
                    broken.append((rel, name, "no-op mutation"))
                    continue
                path.write_text(src.replace(old, new, 1))
                ok = run_tests(python)
                status = "KILLED" if not ok else "SURVIVED"
                print(f"{status:8s} {rel} :: {name}")
                (killed if not ok else survived).append((rel, name))
            path.write_text(original)
        finally:
            path.write_text(original)
            backup.unlink(missing_ok=True)
    print(f"\nkilled={len(killed)} survived={len(survived)} "
          f"broken={len(broken)}")
    for item in broken:
        print("BROKEN:", item)
    if survived:
        print("SURVIVED MUTATIONS (coverage holes):")
        for item in survived:
            print(" ", item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
