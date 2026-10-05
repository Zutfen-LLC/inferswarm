#!/usr/bin/env python3
"""Issue #273 Phase 2 — source-level mutation testing."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "scripts/issue273_admission.py": [
        ("arm-icd-swap-ref", '"reference": C.NVIDIA_ICD', '"reference": C.RADV_ICD'),
        ("placement-flatten-ref-8to7", '"reference": REFERENCE_PLACEMENT_NGL', '"reference": 7'),
        ("placement-flatten-cand-7to8", '"candidate": CANDIDATE_PLACEMENT_NGL', '"candidate": 8'),
        ("identity-drop-process-attribution", '"ngl", "subject_identity", "process_attribution",', '"ngl", "subject_identity",'),
        ("identity-drop-icd", '"arm", "host", "bdf", "icd", "selector",', '"arm", "host", "bdf", "selector",'),
        ("env-icd-check-removed", 'if env.get("VK_ICD_FILENAMES") != want_icd:', 'if False:'),
        ("cuda-fence-removed", 'if receipt.get("cuda_visible_devices") != "-1":', 'if False:'),
        ("argv-ngl-check-removed", 'if "-ngl" in argv_s:', 'if False:'),
        ("proc-host-check-removed", 'elif proc_host != expected_host(arm):', 'elif False:'),
        ("proc-host-mandatory-removed", 'if proc_host is None:', 'if False:'),
        ("row-aliasing-check-removed", 'if ref_rows[d].get("sha256") == cand_rows[d].get("sha256"):', 'if False:'),
        ("same-source-check-removed", 'if ref_src is not None and ref_src == cand_src:', 'if False:'),
        ("distinct-pid-check-removed", 'if ref_pa.get(field) == cand_pa.get(field):', 'if False:'),
        ("det-gate-removed", 'if reference_deterministic is not True:', 'if False:'),
        ("staged-source-schema-removed", 'or binding.get("schema") != STAGED_SOURCE_SCHEMA:', 'or False:'),
    ],
    "scripts/issue273_reducer.py": [
        ("legacy-namespace-allowed", '"c270-",                          # the invalidated #270 namespace', ''),
        ("in-memory-terminal-pass-enabled",
         '        TERMINAL_RUNTIME_BLOCKED_273,\n        ["retained-byte-to-terminal producer verification is required; "',
         '        TERMINAL_PASS_273,\n        ["retained-byte-to-terminal producer verification is required; "'),
    ],
    "scripts/issue273_evidence.py": [
        ("capture-seal-byte-pin-removed", 'require(fields.get("manifest_sha256") == sha(manifest),', 'require(True,',
         "test_bytes_cannot_be_reauthorized_with_self_picked_manifest"),
        ("independent-authority-removed", 'require(parse(files["authority.json"]) == authority,', 'require(True,',
         "test_authenticated_mutations_rejected_at_semantic_boundaries"),
        ("source-repeat-binding-removed", 'require(not binding_problems, "; ".join(binding_problems))', 'require(True, "; ".join(binding_problems))',
         "test_authenticated_source_binding_claims_do_not_override_bytes"),
        ("observed-used-device-removed", 'require(obs.get("used_device_uuids") == [device["vulkan_uuid"]],', 'require(True,',
         "test_authenticated_mutations_rejected_at_semantic_boundaries"),
        ("observer-inertness-removed", 'require(inert["inert"],', 'require(True,',
         "test_authenticated_mutations_rejected_at_semantic_boundaries"),
        ("platform-health-removed", 'if not valid:\n        raise InfrastructureError', 'if False:\n        raise InfrastructureError',
         "test_authenticated_mutations_rejected_at_semantic_boundaries"),
        ("source-stage-provenance-reuse-allowed", 'require(value not in seen.setdefault(label, set()),', 'require(True,',
         "test_coherent_source_stage_observation_session_reuse_is_rejected"),
        ("canonical-prefix-witness-removed", 'require(meta.get("prefix_tokens") == fx["prompt_token_ids"] + (staged["sampled_winners"][:d] if arm == "reference" else staged["forced_tokens"][:d]),', 'require(True,',
         "test_coherent_source_stage_prefix_forgery_is_rejected"),
        ("finite-fp32-law-removed", 'require(len(raw) == C.ROW_BYTES and not K.validate_rows_finite(raw),', 'require(len(raw) == C.ROW_BYTES,',
         "test_forged_digest_claims_and_authenticated_nonfinite_rows_are_rejected"),
        ("reference-before-candidate-stop-removed", 'if not verdict["deterministic"]:\n                return _result(R.TERMINAL_REFERENCE_NONDETERMINISTIC_273,', 'if False:\n                return _result(R.TERMINAL_REFERENCE_NONDETERMINISTIC_273,',
         "test_reference_mismatch_stops_before_candidate_parse"),
        ("producer-reference-stop-removed", 'if arm == "reference" and any(not v["deterministic"] for v in ref_det.values()):', 'if False:',
         "test_producer_stops_before_parsing_candidate_on_reference_mismatch"),
    ],
    "scripts/issue270_physical.py": [
        ("vram-total-capture-removed", 'die_raw["mem_info_vram_total"] = sysfs_reader(\n            bdf, "mem_info_vram_total")', 'pass'),
    ],
}


def run_tests(python: str, target: str | None = None) -> bool:
    modules = [target] if target else ["tests.test_issue273_admission", "tests.test_issue273_evidence"]
    proc = subprocess.run([python, "-m", "unittest", *modules],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    return proc.returncode == 0


def main() -> int:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    if not run_tests(python):
        print("BASELINE FAILS — fix tests before mutation run")
        return 2
    print("baseline: PASS")
    survived, killed, broken = [], [], []
    for rel, mutations in MODULES.items():
        path = ROOT / rel
        original = path.read_text()
        backup_fd, backup_name = tempfile.mkstemp(suffix=".bak")
        os.close(backup_fd)
        backup = Path(backup_name)
        backup.write_text(original)
        try:
            for mutation in mutations:
                name, old, new = mutation[:3]
                target = ("tests.test_issue273_evidence.SerializedEvidenceTests." + mutation[3]
                          if len(mutation) == 4 else "tests.test_issue273_admission")
                src = backup.read_text()
                if src.count(old) != 1:
                    broken.append((rel, name, "anchor missing/ambiguous"))
                    continue
                mutated = src.replace(old, new, 1)
                try:
                    compile(mutated, rel, "exec")
                except SyntaxError as exc:
                    broken.append((rel, name, str(exc)))
                    continue
                path.write_text(mutated)
                for cache in path.parent.joinpath("__pycache__").glob(path.stem + ".*.pyc"):
                    cache.unlink()
                ok = run_tests(python, target)
                status = "KILLED" if not ok else "SURVIVED"
                print(f"{status:8s} {rel} :: {name}")
                (killed if not ok else survived).append((rel, name))
            path.write_text(original)
        finally:
            path.write_text(original)
            backup.unlink(missing_ok=True)
    print(f"\nkilled={len(killed)} survived={len(survived)} broken={len(broken)}")
    for item in broken:
        print("BROKEN:", item)
    if survived:
        print("SURVIVED MUTATIONS (coverage holes):")
        for item in survived:
            print(" ", item)
        return 1
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
