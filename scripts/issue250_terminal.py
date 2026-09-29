#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — fail-closed retained-byte terminal reduction.

Correction pass 2 (maintainer NO-GO comment 5840630050, blocker 4):
the previous ``derive_terminal(reduction)`` trusted a caller-constructed
dictionary of booleans. That is not retained-byte authority. This
module derives the Issue #250 terminal DIRECTLY from the retained
evidence tree: every conclusion is reconstructed from retained unit
receipts, raw responses, observer rows/metadata, server logs,
identity pre/post observations, platform-health receipts, campaign
model attestations, and the live dispatch-authority binding.

Caller-supplied ``deterministic=true``, localized factors, terminal
labels, or condition summaries are not authorities of any kind — the
function takes none of them.

Sequential terminal law (Issue #250 §A–§D; frozen):

  A. Arm A (namespace d250-arm-a) — required always.
     * CPU-only (-dev none) deterministic WITH a valid deterministic
       repeat count (>=5 identical) AND the accepted nonzero-Vulkan
       contrast (#248 retained ngl=1) nondeterministic
       => R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED,
          factor = backend-participation boundary.
     * CPU-only deterministic AND the contrast ALSO deterministic in a
       way that destroys the planned comparison (retained #248 bytes
       no longer vary / were consumed invalid)
       => R8I3B_REDUCER_BLOCKED_INCOMPLETE or honest UNRESOLVED per
          the frozen rule below — never localization.
     * CPU-only varies => Arm B becomes REQUIRED (no terminal yet).
  B. Arm B (d250-arm-b) — required only when A's CPU-only varies.
     * fresh-process CPU-only varies AND same-process CPU-only
       deterministic => LOCALIZED, factor = fresh-process/runtime-
       initialization boundary.
     * both vary => Arm C becomes required.
     * missing B evidence when required => REDUCER_BLOCKED.
  C. AMENDED (correction pass 6, AMENDMENT-003) — the automatic
     discriminator is now the BOUNDED C1 reduced-parallelism probe
     (namespace d250-arm-c1, `-t 4 -tb 4`) after the d250-arm-c
     default-threading reproduction pair:
     * C1 deterministic OR variable: neither alone proves the
       issue-required default-vs-serial boundary. Without dedicated
       C2 authority and completed-C1 gate record, BLOCKED, never
       LOCALIZED or a silent fall-through to D.
     * With a closed C2 gate after EITHER completed C1 verdict:
       serial deterministic => LOCALIZED (default-vs-serial boundary);
       serial variable => Arm D becomes required.
     * missing C evidence when required => REDUCER_BLOCKED.
  D. Arm D (d250-arm-d) — required only when A-C do not localize
     UNDER THE AMENDED REACHABILITY (i.e. Arm C's bounded methodology
     genuinely completed, including a closed C2 gate when C1
     varied). Preserves every accepted pass-3/4/5 correction:
     attributed tokenizer authority, actual token counts,
     indexer_top_k_boundary sides, screening pair + 5-repeat
     confirmation, no retrospective ladder selection.
     * LOCALIZED only if retained source/runtime evidence
       mechanically identifies the corresponding execution transition
       and a FROZEN predicate binds it to the observed
       deterministic->variable boundary (see TRANSITION_PREDICATES).
     * Otherwise => R8I3B_REFERENCE_RUNTIME_UNRESOLVED.

UNRESOLVED may be emitted only after every reachable arm is complete
UNDER THE AMENDED REACHABILITY. Unreachable later-arm evidence can
never override an earlier localization (later namespaces are simply
not consumed once a terminal is derived at an earlier arm).

CORRECTION PASS 6 (AMENDMENT-003) additional reduction preconditions:

  * EVIDENCE GENERATION: only ONE canonical generation
    (gen-2-pass6) is accepted. The retained v1 failed units
    (gen-1-v1-timeout-defect — zero-row, timeout-killed) are
    historical defect evidence: a generation mismatch, mixed
    generations, or v1 markers in consumed namespaces fail closed.
  * TIMEOUT POLICY BINDING: every consumed unit receipt must carry a
    timeout_policy block that recomputes exactly from the frozen
    per-unit budget law (issue250_timeout.verify_timeout_budget_block).
    Receipts without it (e.g. v1-era receipts) cannot be consumed
    for a canonical terminal — they are the defect record, not
    canonical evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

import issue250_diagnostic as D
import issue250_physical as P
import issue250_timeout as TB
import issue248_health as H
import issue248_identity as I

SCHEMA = TERMINAL_SCHEMA = "inferswarm.issue250.terminal/1"
LOCALIZED = "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
UNRESOLVED = "R8I3B_REFERENCE_RUNTIME_UNRESOLVED"
BLOCKED = D.REDUCER_BLOCKED

TERMINALS = (LOCALIZED, UNRESOLVED)


def derive_v0_state(evidence_root: Path, contrast_root: Path,
                    repo_root: Path, expected_head: str, *,
                    authority_fetcher: Any = None,
                    github_api: str = "https://api.github.com") -> dict[str, Any]:
    """Read-only V0 evidence reduction; no caller-supplied row or validity facts.

    Both the accepted #248 corpus and AMD observations must pass custody,
    identity, placement and live dispatch checks before comparing full rows.
    """
    invalid = {"state": D.V0_STATE_INVALID, "valid": False,
               "terminal": None, "a_eligible": False}
    try:
        history = verify_v0_historical_rows(Path(contrast_root),
                                            Path(__file__).resolve().parents[1])
        authority = P.require_live_dispatch(
            Path(repo_root), expected_head, D.V0_NAMESPACE,
            revalidate_authority=authority_fetcher, github_api=github_api)
        root = Path(evidence_root) / D.V0_NAMESPACE
        if root.is_symlink() or not root.is_dir():
            raise ValueError("V0 namespace missing or symlink")
        tags = [p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()]
        if (len(tags) not in (2, 3)
                or set(tags) != set(D.V0_UNIT_TAGS[:len(tags)])):
            raise ValueError("V0 requires a contiguous two/three-unit prefix")
        # Reuse the producer's exact selector/BDF, source-law, residency,
        # environment and process-custody validator before reducing rows.
        P._v0_retained_rows(Path(evidence_root), len(tags), expected_head,
                            authority)
        # INDEPENDENT one-factor enforcement (not producer behavior):
        # authenticate the retained screen freeze directly and require
        # every retained receipt to carry the same frozen Vulkan index
        # and selected BDF. A synthetically mixed-die population fails
        # closed here even if each receipt were individually valid, and
        # can never reach reduce_v0_screen / AMD_VARIABLE / A-eligibility.
        freeze, _ = P._v0_load_freeze_with_preflight(
            Path(evidence_root), expected_head, authority)
        amd_rows = []
        pids = set()
        for tag in D.V0_UNIT_TAGS[:len(tags)]:
            unit = root / tag
            if unit.is_symlink():
                raise ValueError("V0 unit symlink")
            receipt_path, row_path = unit / "unit.json", unit / "obs.row0.f32"
            if receipt_path.is_symlink() or row_path.is_symlink():
                raise ValueError("V0 retained file symlink")
            rec = json.loads(receipt_path.read_bytes())
            device = rec.get("amd_device", {})
            if (device.get("index")
                    != freeze["v0_screen_vulkan_index"]
                    or rec.get("selected_bdf")
                    != freeze["v0_screen_selected_bdf"]
                    or rec.get("excluded_bdf")
                    != freeze["v0_screen_excluded_bdf"]):
                raise ValueError(
                    "V0 mixed-die retained population cannot be reduced")
            row = row_path.read_bytes()
            if len(row) != D.ROW_BYTES:
                raise ValueError("V0 full row width mismatch")
            digest = hashlib.sha256(row).hexdigest()
            if (rec.get("schema") != D.V0_SCHEMA or rec.get("tag") != tag
                    or rec.get("namespace") != D.V0_NAMESPACE
                    or rec.get("arm") != D.V0_ARM
                    or rec.get("head_sha") != expected_head
                    or rec.get("evidence_generation") != P.EVIDENCE_GENERATION
                    or rec.get("authority_sha256") != D.authority_digest(authority)
                    or rec.get("placement_verified") is not True
                    or not isinstance(rec.get("amd_device"), dict)
                    or rec["amd_device"].get("vendor_id") != "0x1002"
                    or type(rec["amd_device"].get("index")) is not int
                    or rec.get("decision0_row_sha256") != digest
                    or rec.get("row_bytes") != D.ROW_BYTES
                    or rec.get("case_id") != D.CONTRAST_CASE
                    or rec.get("ngl") != 1
                    or rec.get("backend") != "Vulkan"
                    or rec.get("embedding_placement") != "CPU"
                    or rec.get("output_projection_placement") != "Vulkan"
                    or rec.get("model_dir") != D.MODEL_DIR
                    or rec.get("model_launch_member") !=
                       str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
                    or rec.get("model_member_sha256") !=
                       D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1]
                    or rec.get("prompt_sha256") != history["prompt_sha256"]
                    or rec.get("prompt_token_ids") != history["prompt_token_ids"]
                    or rec.get("prompt_len") != history["prompt_len"]
                    or rec.get("prompt_text_sha256") != history["prompt_text_sha256"]
                    or rec.get("request_contract") != D.REQUEST_CONTRACT
                    or rec.get("request_contract_sha256") !=
                       D.canonical_request_digest(D.REQUEST_CONTRACT)
                    or rec.get("fresh_process") is not True):
                raise ValueError(f"V0 receipt workload/custody mismatch: {tag}")
            pid = rec.get("server_pid")
            argv = rec.get("server_argv")
            device = rec.get("amd_device", {})
            if (not isinstance(argv, list)
                    or argv != P.v0_server_argv(
                        Path(argv[0]), Path(rec["model_launch_member"]), P.PORT)
                    or rec.get("binary_sha256") != P.V0_COMPARATOR_SHA
                    or type(pid) is not int or pid <= 0 or pid in pids):
                raise ValueError("V0 process/AMD placement attribution unproven")
            pids.add(pid)
            amd_rows.append(row)
        result = D.reduce_v0_screen(amd_rows, history["row_sha256"])
        result["historical_provenance"] = {
            k: v for k, v in history.items() if k != "prompt_token_ids"}
        result["v0_authority_sha256"] = D.authority_digest(authority)
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError,
            __import__("subprocess").CalledProcessError, json.JSONDecodeError,
            D.DiagnosticError, P.PhysicalDiagnosticError) as exc:
        return dict(invalid, reason=str(exc))


def verify_v0_historical_rows(contrast_root: Path, repo_root: Path
                              ) -> dict[str, Any]:
    """Authenticate the exact accepted #248 ngl=1 rows against committed
    adjudication and the original external retained manifest and bytes."""
    import subprocess
    base = ("docs/investigations/"
            "qwen38-flash-next-r8-i3a-ref-nondeterminism/")
    def committed(rel: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{D.ACCEPTED_248_RESULT_HEAD}:{base}{rel}"],
            cwd=repo_root, check=True, capture_output=True).stdout
    report = committed("FINAL-REPORT.md")
    manifest = committed("MANIFEST.sha256").decode()
    reduction_raw = committed("evidence/physical/terminal-reduction.json")
    for rel, raw in (("FINAL-REPORT.md", report),
                     ("evidence/physical/terminal-reduction.json", reduction_raw)):
        name = base + rel
        expected = [ln.split()[0] for ln in manifest.splitlines()
                    if ln.split()[1:] == [name]]
        if len(expected) != 1 or hashlib.sha256(raw).hexdigest() != expected[0]:
            raise ValueError(f"committed #248 manifest binding mismatch: {rel}")
    if (D.ACCEPTED_248_TERMINAL.encode() not in report
            or D.ACCEPTED_248_MANIFEST_SELF_DIGEST.encode() not in report):
        raise ValueError("committed #248 final report provenance mismatch")
    reduction = json.loads(reduction_raw)
    if (reduction.get("terminal") != D.ACCEPTED_248_TERMINAL
            or reduction.get("complete") is not True
            or reduction.get("problems") != []
            or reduction.get("probes", {}).get("placement", {}).get(
                "contrasts", {}).get("1", {}).get("row_deterministic") is not False):
        raise ValueError("committed #248 terminal/placement mismatch")
    entries = {u["receipt"]["tag"]: u["receipt"] for u in reduction[
        "probes"]["placement"]["units"] if u.get("receipt", {}).get(
            "tag") in D.CONTRAST_UNITS}
    if set(entries) != set(D.CONTRAST_UNITS):
        raise ValueError("committed #248 placement pair missing")
    rows = _verify_contrast_manifest(contrast_root / "SHA256SUMS")["rows"]
    digests = []
    prompts = []
    for tag in D.CONTRAST_UNITS:
        rel = f"{D.CONTRAST_NAMESPACE}/{tag}/"
        path = contrast_root / rel
        if path.is_symlink() or not path.is_dir():
            raise ValueError("historical #248 unit missing or symlink")
        receipt_path, row_path = path / "unit.json", path / "obs.row0.f32"
        if receipt_path.is_symlink() or row_path.is_symlink():
            raise ValueError("historical #248 file symlink")
        receipt_raw, row = receipt_path.read_bytes(), row_path.read_bytes()
        _require_manifest_row(rows, rel + "unit.json", receipt_raw)
        _require_manifest_row(rows, rel + "obs.row0.f32", row)
        receipt = json.loads(receipt_raw)
        digest = hashlib.sha256(row).hexdigest()
        auth = receipt.get("authority", {})
        argv = receipt.get("server_argv", [])
        env = receipt.get("server_env", {})
        if (len(row) != D.ROW_BYTES or digest != receipt.get("observer_rows", [None])[0]
                or digest != D.V0_NVIDIA_ROW0_SHA256[D.CONTRAST_UNITS.index(tag)]
                or receipt != entries[tag]
                or receipt.get("namespace") != D.CONTRAST_NAMESPACE
                or receipt.get("ngl") != 1
                or receipt.get("case_id") != D.CONTRAST_CASE
                or receipt.get("binary_sha256") != D.SERVER_BINARIES["comparator"]
                or receipt.get("model_dir") != D.MODEL_DIR
                or receipt.get("model_launch_member") != str(
                    Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
                or receipt.get("request_contract") != D.REQUEST_CONTRACT
                or receipt.get("request_contract_sha256") !=
                   D.canonical_request_digest(D.REQUEST_CONTRACT)
                or auth.get("head_sha") != CONTRAST_AUTHORITY_HEAD
                or auth.get("namespace") != D.CONTRAST_NAMESPACE
                or auth.get("issue_number") != 248
                or auth.get("pr_number") != 249
                or argv[argv.index("-ngl") + 1] != "1"
                or argv[argv.index("--model") + 1] != receipt["model_launch_member"]
                or env.get("VK_ICD_FILENAMES") !=
                   "/usr/share/vulkan/icd.d/nvidia_icd.json"
                or receipt.get("prompt_len") != 3077
                or len(receipt.get("prompt_token_ids", [])) != 3077):
            raise ValueError(f"historical #248 placement/workload drift: {tag}")
        digests.append(digest)
        prompts.append(receipt["prompt_token_ids"])
    if digests[0] == digests[1] or prompts[0] != prompts[1]:
        raise ValueError("historical #248 rows/prompt contradict adjudication")
    fixture_raw = (repo_root / D.FIXTURE_LADDER_REL).read_bytes()
    if hashlib.sha256(fixture_raw).hexdigest() != D.FIXTURE_LADDER_SHA256:
        raise ValueError("accepted fixture ladder drift")
    case = next(c for c in json.loads(fixture_raw)["cases"]
                if c["case_id"] == D.CONTRAST_CASE)
    if case["prompt_token_ids"] != prompts[0]:
        raise ValueError("historical prompt tokens differ from accepted fixture")
    return {"row_sha256": tuple(digests), "prompt_len": 3077,
            "prompt_token_ids": prompts[0],
            "prompt_text_sha256": D.sha256_bytes(case["prompt_text"].encode()),
            "prompt_sha256": D.sha256_bytes(json.dumps(
                prompts[0], separators=(",", ":")).encode()),
            "manifest_self_digest": D.ACCEPTED_248_MANIFEST_SELF_DIGEST,
            "result_head": D.ACCEPTED_248_RESULT_HEAD}


def derive_v0n_state(evidence_root: Path, contrast_root: Path,
                     repo_root: Path, expected_head: str, *,
                     authority_fetcher: Any = None,
                     github_api: str = "https://api.github.com"
                     ) -> dict[str, Any]:
    """Read-only V0n current-window NVIDIA reduction; no caller facts.

    Custody chain before any comparison (mirrors derive_v0_state):
      1. the retained #248 NVIDIA Vulkan ngl=1 rows are authenticated
         (verify_v0_historical_rows: manifest, committed adjudication,
         external bytes, per-receipt nvidia ICD env + -ngl 1 + CUDA off
         + comparator SHA) — this is ALSO the proof that the retained
         comparison rows are NVIDIA Vulkan ngl=1 evidence, not CUDA;
      2. the V0n live dispatch authority is revalidated live;
      3. the producer's exact retained-row custody validator
         (_v0n_retained_rows) re-checks every retained NVIDIA unit;
      4. every receipt's nvidia_device identity must equal the frozen
         NVIDIA contract fields (single RTX 3060: vendor 0x10de,
         device 0x2504, NVIDIA-proprietary driver) and its env must
         carry the NVIDIA ICD with CUDA_VISIBLE_DEVICES=-1;
         _v0n_retained_rows additionally enforces the V0n screen
         freeze (NO-GO 5874443020): one authenticated freeze digest,
         one accepted #248 Arm-B physical subject (UUID/BDF/PCI/
         driver/ICD/Vulkan/runtime identity equal across every unit,
         pre-launch and post-execution observations bound) — any
         violation fails to CURRENT_NVIDIA_INVALID_BLOCKED before any
         numerical comparison;
      5. only then does the pure reducer compare FULL 993280-byte rows
         against the AMD current-window row digest and BOTH retained
         #248 NVIDIA rows.

    No Issue #250 terminal and no A-eligibility can be emitted here:
    the result always carries terminal=None and a_eligible=False.
    """
    invalid = {"state": D.V0N_STATE_INVALID, "valid": False,
               "terminal": None, "a_eligible": False}
    try:
        history = verify_v0_historical_rows(Path(contrast_root),
                                            Path(__file__).resolve().parents[1])
        authority = P.require_live_dispatch(
            Path(repo_root), expected_head, D.V0N_NAMESPACE,
            revalidate_authority=authority_fetcher, github_api=github_api)
        root = Path(evidence_root) / D.V0N_NAMESPACE
        if root.is_symlink() or not root.is_dir():
            raise ValueError("V0n namespace missing or symlink")
        tags = [p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()]
        if (len(tags) not in (2, 3)
                or set(tags) != set(D.V0N_UNIT_TAGS[:len(tags)])):
            raise ValueError("V0n requires a contiguous two/three-unit prefix")
        P._v0n_retained_rows(Path(evidence_root), len(tags), expected_head,
                             authority)
        nvidia_rows = []
        pids = set()
        for tag in D.V0N_UNIT_TAGS[:len(tags)]:
            unit = root / tag
            if unit.is_symlink():
                raise ValueError("V0n unit symlink")
            receipt_path, row_path = unit / "unit.json", unit / "obs.row0.f32"
            if receipt_path.is_symlink() or row_path.is_symlink():
                raise ValueError("V0n retained file symlink")
            rec = json.loads(receipt_path.read_bytes())
            device = rec.get("nvidia_device", {})
            env = rec.get("server_env", {})
            if (device.get("vendor_id") != P.V0N_GPU_VENDOR_ID
                    or device.get("device_id") != P.V0N_GPU_DEVICE_ID
                    or device.get("driver_id") != P.V0N_DRIVER_ID
                    or device.get("index") != 0
                    or rec.get("selected_gpu") not in (None,)
                    or env.get("VK_ICD_FILENAMES") != P.V0N_NVIDIA_ICD
                    or env.get("CUDA_VISIBLE_DEVICES") != "-1"
                    or env.get("GGML_VK_VISIBLE_DEVICES") != "0"):
                raise ValueError(
                    f"V0n device/backend identity mismatch: {tag}")
            row = row_path.read_bytes()
            if len(row) != D.ROW_BYTES:
                raise ValueError("V0n full row width mismatch")
            pid = rec.get("server_pid")
            if (type(pid) is not int or pid <= 0 or pid in pids):
                raise ValueError("V0n fresh-process PID custody mismatch")
            pids.add(pid)
            nvidia_rows.append(row)
        result = D.reduce_v0n_screen(
            nvidia_rows, D.V0N_AMD_CURRENT_ROW0_SHA256, history["row_sha256"])
        result["historical_provenance"] = {
            k: v for k, v in history.items() if k != "prompt_token_ids"}
        result["amd_current_row0_sha256"] = D.V0N_AMD_CURRENT_ROW0_SHA256
        result["v0n_authority_sha256"] = D.authority_digest(authority)
        result["terminal"] = None
        result["a_eligible"] = False
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError,
            __import__("subprocess").CalledProcessError, json.JSONDecodeError,
            D.DiagnosticError, P.PhysicalDiagnosticError) as exc:
        return dict(invalid, reason=str(exc))

# Sequential arm ladder (namespace, arm) in reachability order.
# AMENDMENT-003: Arm C is split — d250-arm-c (default reproduction
# pair) feeds d250-arm-c1 (the bounded reduced-parallelism probe).
# The gated serial namespace d250-arm-c2 is NOT part of the automatic
# ladder; it is consumed only through the explicit gate below.
ARM_LADDER = (
    ("d250-arm-a", "A-vulkan-necessity"),
    ("d250-arm-b", "B-process-init"),
    ("d250-arm-c", "C-cpu-threads"),
    ("d250-arm-c1", "C1-reduced-parallelism"),
    ("d250-arm-d", "D-context-transition"),
)

# Historical C1 factor retained for audit only: never terminal-bearing.
LOCALIZED_FACTORS = {
    "A-vulkan-necessity": "backend-participation boundary "
                          "(zero vs nonzero Vulkan participation)",
    "B-process-init": "fresh-process/runtime-initialization boundary",
    "C-cpu-threads": "CPU parallel execution/order boundary",
    "C1-reduced-parallelism": (
        "CPU thread-regime / parallelism boundary (default 14-thread "
        "regime varies while the frozen reduced -t 4 -tb 4 regime is "
        "deterministic; single-thread execution was NOT tested)"),
    "C2-serial": (
        "CPU thread-regime / parallelism boundary (default 14-thread "
        "regime varies while the serial -t 1 -tb 1 regime is "
        "deterministic; maintainer-gated C2 serial population)"),
    "D-context-transition": "long-context execution-path transition "
                            "(bound by frozen transition predicate)",
}

# AMENDMENT-004: either completed C1 verdict without C2 remains blocked.
ARM_C1_VARIED_C2_UNGATED = (
    "arm C1 bounded probe completed; neither deterministic nor variable "
    "C1 establishes the issue-required default-vs-serial boundary. "
    "Serial C2 remains unexecuted (dedicated d250-arm-c2 exact-head "
    "maintainer gate required; cost-gated separately) — review required "
    "arm executes")

# METHODOLOGY-AMENDMENT-008: after an Arm-A result (whatever the
# verdict), the ladder STOPS — no later arm is auto-reachable. B and
# everything after it require a NEW maintainer decision; a fresh
# Arm-A variable population satisfies the historical ladder law
# (_require_sequential_reachability), but a post-A continuation needs
# an explicit future amendment before any B dispatch. Recorded here as
# the frozen reason surfaced by derive_terminal when B is refused.
ARM_A_STOPS_LADDER = (
    "Arm-A completed under METHODOLOGY-AMENDMENT-008; the ladder stops "
    "for maintainer review — no B/C/C1/C2/D arm is auto-reachable from "
    "an Arm-A result without a new maintainer decision")

# Frozen Arm-D transition predicates (correction pass 4, NO-GO
# 5851078451, blocker 3; supersedes the pass-3 set). A length
# transition alone never establishes causality: LOCALIZED at D
# requires retained evidence matching one of these mechanical
# predicates — a concrete execution transition identified from
# retained source/runtime evidence, bound to the observed
# deterministic->variable length boundary, measured in the correct
# runtime units. Each predicate names the retained evidence it
# consumes; none is derivable from the nominal length alone.
#
# REMOVED (correction pass 4, blocker 3): ``midstream_ubatch_split``.
# The retained ``prompt processing, n_tokens = ...`` lines are
# ~3-second WALL-CLOCK samples of ONE cumulative counter (pinned
# server-context.cpp print_timings_pp gate: t_prompt_total >= 3000
# ms, sampled inside the batch-fill loop) — they are NOT ubatch
# boundary events. A sub-512 sampled delta followed by later
# progress cannot mechanically distinguish an actual scheduler/
# ubatch split from ordinary throughput variation, timing/sampling
# alignment, or pauses between samples; the same observable was
# already declared unsound for ubatch inference when
# ``ubatch_geometry_split`` was retired, and requiring the short
# delta to be midstream does not convert a wall-clock artifact into
# an execution-boundary event. No other retained source/runtime
# signal identifies actual ubatch boundaries under the frozen launch
# shape and log level, so ubatch geometry is NOT localizable in
# Issue #250. Adding instrumentation for it would be a tooling/head
# change requiring fresh prospective review and exact-head dispatch.
TRANSITION_PREDICATES = {
    "indexer_top_k_boundary": {
        "requires": "model-architecture fact "
                    "qwen4exp.attention.indexer.top_k = 2048 with "
                    "compress ratio r = 4: the source-proven QSA "
                    "selection-width law width = min(n_kv, 2048 + 4 "
                    "- 1) = min(n_kv, 2051) crosses between the last "
                    "deterministic and first variable length "
                    "MEASURED IN ACTUAL PROMPT TOKEN COUNTS "
                    "(retained tokenizer-authority receipts, not "
                    "nominal ladder labels)",
        "binds": "every deterministic length's actual token count "
                 "<= 2051 (all-cells side: the selection still "
                 "covers the full population) AND every variable "
                 "length's actual token count >= 2052 (selective "
                 "side: the capped width is smaller than the "
                 "population); equality at 2051 is NOT selective",
    },
}


def _blocked(problems: list[str], reduction: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    return {"schema": SCHEMA, "terminal": None, "terminal_vocabulary":
            list(D.TERMINALS), "blocked": BLOCKED, "complete": False,
            "problems": problems, "arms": (reduction or {}).get("arms", {}),
            "contrast": (reduction or {}).get("contrast"),
            "v0": (reduction or {}).get("v0"),
            "arm_c_gate_status": (reduction or {}).get("arm_c_gate_status")}


def _ok(terminal: str, reduction: dict[str, Any], basis: dict[str, Any]
        ) -> dict[str, Any]:
    return {"schema": SCHEMA, "terminal": terminal,
            "terminal_vocabulary": list(D.TERMINALS), "blocked": None,
            "complete": True, "problems": [], "arms": reduction["arms"],
            "contrast": reduction.get("contrast"), "v0": reduction.get("v0"),
            "basis": basis,
            "arm_c_gate_status": reduction.get("arm_c_gate_status")}


# ---------------------------------------------------------------------------
# Arm-D transition predicate evaluation (frozen, mechanical).
#
# CORRECTION PASS 4 (NO-GO 5851078451, blocker 3): the pass-3
# ``midstream_ubatch_split`` predicate is REMOVED from terminal-bearing
# authority. Pinned-source facts that make it unsound:
#   * server-context.cpp print_timings_pp emits ``prompt processing,
#     n_tokens = N`` lines on a WALL-CLOCK sampling gate
#     (t_prompt_total >= 3000 ms; sampled in the batch-fill loop), so
#     the cumulative counts are TIME-sampled checkpoints of ONE
#     ubatch stream, not per-ubatch boundaries; a sub-512 sampled
#     delta followed by continuing progress cannot distinguish a real
#     scheduler/ubatch split from throughput variation, sampling
#     alignment, or pauses between samples;
#   * hybrid-memory checkpoint resegmentation evidence
#     (``main/do_checkpoint``) is logged at DBG level only
#     (server-context.cpp:3904 SLT_DBG) and is ABSENT from the frozen
#     non-verbose launch shape, so no retained log line identifies an
#     actual ubatch boundary;
#   * therefore ubatch geometry is NOT localizable in Issue #250, and
#     NO instrumentation may be added to preserve the predicate (that
#     would require a prospectively reviewed tooling/head change and
#     a fresh exact-head dispatch).
# The frozen predicate set is reduced to the single retained-byte-
# observable, source-proven transition:
#   * ``indexer_top_k_boundary`` — a TOKEN-COUNT mechanism: the
#     boundary between the last deterministic and first variable
#     length, measured in ACTUAL prompt token counts (tokenizer
#     authority), equals the qwen4exp indexer top_k crossing
#     (top_k=2048; model arch fact from phase0 MODEL_ARCH_FACTS).
# The retained ``prompt processing`` progress lines remain DIAGNOSTIC
# METADATA ONLY (``_ladder_split_shapes`` keeps parsing them into
# ``prompt_progress_counts`` for the reduction record; they can never
# select LOCALIZED).
# A length threshold alone still fires nothing.
# ---------------------------------------------------------------------------

UBATCH_N_BATCH = 512  # frozen accepted launch shape --batch-size 512


def _progress_run_steps(counts: list[int]) -> list[int]:
    """Ordered cumulative->step deltas (mechanical, no semantics).

    Diagnostic metadata only (correction pass 4, blocker 3): these
    deltas derive from ~3-second wall-clock samples of one cumulative
    counter and carry NO ubatch-boundary semantics.
    """
    if len(counts) < 2:
        return []
    return [b - a for a, b in zip(counts, counts[1:])]


def _midstream_split_signature(counts: list[int]) -> bool:
    """RETIRED (correction pass 4, NO-GO 5851078451, blocker 3).

    This function always returns False and exists ONLY so any stale
    caller fails closed instead of inheriting the retired causal
    semantics: the retained cumulative prompt-progress counts are
    ~3-second WALL-CLOCK samples of one counter, so a sub-512 sampled
    delta followed by later progress cannot mechanically identify a
    scheduler/ubatch boundary (throughput variation, sampling
    alignment, and pauses between samples produce the same shape).
    Wall-clock-sampled progress counts can never select a LOCALIZED
    terminal.
    """
    return False


def _evaluate_transition_predicates(
        ladder_facts: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """Evaluate the frozen Arm-D predicates from retained ladder facts.

    ``ladder_facts`` maps nominal length -> {"row_deterministic":
    bool, "prompt_progress_counts": [...], "actual_token_count": int,
    "pair_identical": bool, "deterministic_confirmed": bool}
    (all derived from retained bytes + the tokenizer authority).
    A predicate FIRES only on the mechanical shape it names, and only
    on a VALID boundary (monotone deterministic->variable, the
    deterministic side confirmed at the frozen count). Returns the
    fired predicate description or None.
    """
    lengths = sorted(ladder_facts)
    if not lengths:
        return None
    det = [n for n in lengths if ladder_facts[n]["row_deterministic"]]
    var = [n for n in lengths if not ladder_facts[n]["row_deterministic"]
           and ladder_facts[n]["unit_count"] >= 2]
    if not det or not var:
        return None
    if max(det) >= min(var):
        return None  # interleaved — no monotone boundary exists
    boundary = (max(det), min(var))

    # indexer_top_k_boundary: measured in ACTUAL token counts against
    # the SOURCE-PROVEN selection-width law (correction pass 4,
    # blocker 3 audit; equality corrected in pass 5, NO-GO
    # 5852014883): the pinned tree's build_qsa_top_k computes
    # width = min(n_kv, indexer_top_k + r - 1) with r = 4, i.e.
    # width = min(n_kv, 2051). At every population THROUGH 2051
    # cells the width equals n_kv, so every KV cell is selected
    # (dense / all-cells side, n_kv <= 2051 — 2051 itself is NOT
    # selective); from 2052 cells on the capped width is smaller
    # than the population and the top-k selection actively masks
    # the QSA attention (selective side, n_kv >= 2052). Ordinary
    # timing/batching cannot mimic the signal: the width is a
    # function of the token COUNT alone (single-sequence frozen
    # launch shape => n_kv equals the actual prompt token count),
    # not of wall-clock scheduling.
    all_cells_max = D.INDEXER_ALL_CELLS_MAX
    selective_min = D.INDEXER_SELECTIVE_MIN
    det_tokens = [ladder_facts[n]["actual_token_count"] for n in det]
    var_tokens = [ladder_facts[n]["actual_token_count"] for n in var]
    if (all(t <= all_cells_max for t in det_tokens)
            and all(t >= selective_min for t in var_tokens)
            and max(det_tokens) <= all_cells_max
            and min(var_tokens) >= selective_min):
        return {
            "predicate": "indexer_top_k_boundary",
            "boundary": boundary,
            "boundary_actual_tokens": (max(det_tokens), min(var_tokens)),
            "all_cells_max": all_cells_max,
            "selective_min": selective_min,
            "mechanism": TRANSITION_PREDICATES["indexer_top_k_boundary"],
        }
    # No surviving source-proven predicate fires: ubatch geometry is
    # not localizable from retained evidence under the frozen launch
    # shape (midstream_ubatch_split retired, correction pass 4,
    # blocker 3) — the caller reports UNRESOLVED, never a LOCALIZED
    # claim from wall-clock-sampled progress counts.
    return None


def _ladder_split_shapes(text: str) -> list[int]:
    """Parse cumulative prompt-progress counts from a retained server
    log slice. The pinned server emits cumulative
    ``prompt processing, n_tokens = <n>`` lines (~3-second wall-clock
    samples). CORRECTION PASS 4 (NO-GO 5851078451, blocker 3): these
    counts are DIAGNOSTIC METADATA ONLY for the reduction record —
    they are not ubatch boundary events and can never select a
    LOCALIZED terminal.
    """
    counts: list[int] = []
    for match in re.finditer(
            r"prompt processing, n_tokens = (\d+)", text):
        n = int(match.group(1))
        if n not in counts:
            counts.append(n)
    return counts


# ---------------------------------------------------------------------------
# Per-unit retained-byte verification (fail-closed)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Retained-population verification under the FROZEN PREFIX POPULATION
# LAW (correction pass 3, NO-GO 5847890177 blocker 2)
# ---------------------------------------------------------------------------

UNIT_SAFE_TAG = re.compile(
    r"case-\d+-B-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}"
    r"(?:-confirm)?")


def _verify_unit_receipt(unit_dir: Path, namespace: str, arm: str,
                         tag: str, expected_head: str,
                         expected_authority: dict[str, Any],
                         attestation: dict[str, Any],
                         expected_request_kind: str,
                         ) -> dict[str, Any]:
    """Independently verify ONE retained unit from its bytes.

    Checks (each from retained bytes, fail-closed): unit receipt
    schema/tag/namespace/arm binding; dispatch-authority block equality
    with the live-validated payload; exact branch/head; binary SHA;
    model-member attestation binding + stat witness; request contract;
    process argv/env; raw response digest; token digest; complete row
    bytes and row SHA-256; observer metadata; identity pre/post raw
    observations; platform-health receipt.
    """
    if unit_dir.is_symlink() or not unit_dir.is_dir():
        raise ValueError(f"unit directory missing or symlink: {tag}")
    receipt = json.loads((unit_dir / "unit.json").read_bytes())
    if not isinstance(receipt, dict) or receipt.get("schema") != (
            P.UNIT_SCHEMA):
        raise ValueError("unit receipt schema mismatch")
    if (receipt.get("tag") != tag or receipt.get("namespace") != namespace
            or receipt.get("arm_id") != arm or receipt.get("arm") != P.ARM):
        raise ValueError("receipt tag/namespace/arm binding mismatch")
    # planned-unit geometry consistency (frozen plan membership)
    plan = D.probe_list_for(arm)
    spec = next((u for u in plan if u["tag"] == tag), None)
    if spec is None:
        raise ValueError(f"unit {tag} is not in the frozen arm plan")
    if receipt.get("unit", {}).get("argv_delta") != list(
            spec.get("argv_delta", ())):
        raise ValueError("receipt argv delta differs from frozen plan")
    # dispatch authority binding (exact block equality with live payload)
    authority = receipt.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("unit receipt carries no dispatch authority block")
    expected_block = P.unit_authority_block(expected_authority)
    for key, value in expected_block.items():
        if authority.get(key) != value:
            raise ValueError(
                f"unit dispatch authority binding mismatch: {key}")
    if authority.get("head_sha") != expected_head:
        raise ValueError("unit authority head mismatch")
    # AMENDMENT-003: the canonical evidence generation must be exact
    # (no v1 defect-record units, no mixed generations).
    if receipt.get("evidence_generation") != P.EVIDENCE_GENERATION:
        raise ValueError(
            f"unit evidence generation "
            f"{receipt.get('evidence_generation')!r} != canonical "
            f"{P.EVIDENCE_GENERATION!r} (v1 defect-record units are "
            "never canonical reduction inputs)")
    # AMENDMENT-003: the receipt's timeout policy must recompute
    # EXACTLY from the frozen per-unit budget law (mutation / absent
    # policy / wrong budget all fail closed).
    try:
        TB.verify_timeout_budget_block(
            receipt.get("timeout_policy"), spec)
    except Exception as exc:
        raise ValueError(
            f"timeout policy binding invalid: {exc}") from None
    # AMENDMENT-008 r2: Arm-A receipts MUST carry reachability
    # provenance from the frozen vocabulary (persisted by the
    # authenticated launch gate); later-arm receipts must NOT.
    if arm == "A-vulkan-necessity":
        if receipt.get("reachability_source") not in (
                "historical-v0-amd-variable", "arm-a-bridge"):
            raise ValueError(
                "Arm-A unit receipt carries no authenticated "
                "reachability provenance")
    elif receipt.get("reachability_source") is not None:
        raise ValueError(
            f"{arm} receipt must not carry Arm-A reachability "
            "provenance")
    # binary authority
    if (receipt.get("binary_sha256")
            != D.SERVER_BINARIES.get(receipt.get("binary_id"))):
        raise ValueError("unit binary identity mismatch")
    # model authority
    if receipt.get("model_attestation_sha256") != attestation[
            "attestation_sha256"]:
        raise ValueError(
            "unit model attestation digest differs from campaign opening")
    witness = receipt.get("model_stat_witness")
    if not isinstance(witness, dict) or sorted(witness) != sorted(
            D.MODEL_MEMBERS):
        raise ValueError("unit model stat witness population malformed")
    attested = {m["name"]: m for m in attestation["members"]}
    for member, fields in witness.items():
        if (not isinstance(fields, dict)
                or sorted(fields) != sorted(P.WITNESS_STAT_KEYS)
                or any(type(fields[k]) is not int for k in
                       P.WITNESS_STAT_KEYS)):
            raise ValueError(f"unit stat witness malformed: {member}")
        if any(fields[k] != attested[member][k]
               for k in P.WITNESS_STAT_KEYS):
            raise ValueError(
                f"unit stat witness differs from attestation: {member}")
    if (receipt.get("model_dir") != D.MODEL_DIR
            or receipt.get("model_launch_member")
            != str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)):
        raise ValueError("unit model launch member mismatch")
    # request contract
    if expected_request_kind == "arm-b":
        expected_contract = D.ARM_B_CONTRACT
    else:
        expected_contract = D.REQUEST_CONTRACT
    contract = receipt.get("request_contract")
    if (not isinstance(contract, dict) or contract != expected_contract
            or D.canonical_request_digest(contract)
            != receipt.get("request_contract_sha256")):
        raise ValueError("unit request contract mismatch")
    # argv/env (exact frozen geometry, one declared factor)
    argv = receipt.get("server_argv")
    if not isinstance(argv, list) or not argv or not argv[0]:
        raise ValueError("server argv missing")
    if argv != P.server_argv(
            Path(argv[0]),
            Path(receipt["model_launch_member"]), spec,
            c2_verification=(arm == D.ARM_C2_NAME)):
        raise ValueError("server argv differs from frozen geometry")
    env = receipt.get("server_env")
    if not isinstance(env, dict):
        raise ValueError("server env missing")
    expected_env_visible = {
        k: v for k, v in P.launch_env(Path("x") / "obs").items()
        if k.startswith(("LLAMA_", "VK_", "CUDA_"))}
    # LLAMA_OBSERVE_OUT differs per unit dir; compare the rest
    for key in expected_env_visible:
        if key == "LLAMA_OBSERVE_OUT":
            continue
        if env.get(key) != expected_env_visible[key]:
            raise ValueError(
                f"server env differs from frozen probe: {key}")
    # process attribution
    actual = receipt.get("process_attribution")
    if (not isinstance(actual, dict)
            or type(actual.get("server_pid")) is not int
            or actual["server_pid"] <= 0
            or actual.get("server_exe_sha256") != receipt["binary_sha256"]
            or actual.get("server_argv") != argv):
        raise ValueError("process attribution mismatch")
    # Arm-D ladder token authority (correction pass 3, blocker 4A):
    # the receipt must bind the retained tokenizer-authority entry and
    # the runtime prompt-eval count must EQUAL the actual token count.
    if spec.get("ladder_length"):
        token_authority = receipt.get("ladder_token_authority")
        try:
            entry = P.validate_ladder_token_authority(token_authority)
        except Exception as exc:
            raise ValueError(
                f"ladder token authority malformed: {exc}")
        if entry["nominal_length"] != spec["ladder_length"]:
            raise ValueError(
                "ladder token authority nominal length differs from "
                "the unit plan")
        log_text = (unit_dir / "server.log").read_text(
            errors="replace")
        eval_counts = [int(m.group(1)) for m in re.finditer(
            r"prompt eval time\s*=\s*[0-9.]+ ms\s*/\s*(\d+)\s*tokens",
            log_text)]
        actual_count = entry["actual_token_count"]
        if (not eval_counts
                or eval_counts[-1] != actual_count
                or any(n != actual_count for n in eval_counts)):
            raise ValueError(
                f"runtime prompt-eval counts {eval_counts} disagree "
                f"with the retained tokenizer authority "
                f"({actual_count} tokens) — BLOCKED")
    # raw response + token digests
    raw = (unit_dir / "response.json.raw").read_bytes()
    if receipt.get("response_raw_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("raw response digest binding mismatch")
    response = json.loads(raw)
    tokens = (response.get("tokens", response.get("tokens_predicted"))
              if isinstance(response, dict) else None)
    if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
            or any(type(t) is not int for t in tokens)
            or tokens != receipt.get("tokens")):
        raise ValueError("raw and receipt tokens disagree")
    token_sha = hashlib.sha256(
        D.CANONICAL_PACK.pack(*tokens)).hexdigest()
    if receipt.get("deterministic_output_sha256") != token_sha:
        raise ValueError("receipt token digest mismatch")
    # complete row bytes + digests
    meta_raw = (unit_dir / "obs.meta.json").read_bytes()
    if receipt.get("observer_meta_sha256") != hashlib.sha256(
            meta_raw).hexdigest():
        raise ValueError("observer metadata digest binding mismatch")
    lines = [ln for ln in meta_raw.decode("utf-8").splitlines()
             if ln.strip()]
    if len(lines) != D.DECISIONS:
        raise ValueError("observer metadata must cover all decisions")
    row_sha: list[str] = []
    for i, ln in enumerate(lines):
        meta = json.loads(ln)
        if not isinstance(meta, dict) or meta.get("pos") != i:
            raise ValueError("observer metadata position order mismatch")
        row = (unit_dir / f"obs.row{i}.f32").read_bytes()
        if len(row) != D.ROW_BYTES:
            raise ValueError("observer row wrong vocabulary width")
        row_sha.append(hashlib.sha256(row).hexdigest())
    if receipt.get("observer_rows") != row_sha:
        raise ValueError("observer row digest binding mismatch")
    # identity pre/post (raw observations, re-derived). Same-process
    # request units share the lifecycle identity observations.
    identity_dir = unit_dir
    if receipt.get("kind") == "same-process-request":
        sp_dir = receipt.get("same_process", {}).get("lifecycle_dir")
        if not isinstance(sp_dir, str) or "/" in sp_dir:
            raise ValueError("lifecycle dir binding malformed")
        identity_dir = unit_dir.parent / sp_dir
    pre = json.loads((identity_dir / "identity-pre.json").read_bytes())
    post = json.loads((identity_dir / "identity-post.json").read_bytes())
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise ValueError("identity observations malformed")
    raw_problems = (I.identity_problems(P.ARM, pre)
                    + I.identity_problems(P.ARM, post))
    if raw_problems:
        raise ValueError(f"identity drift: {raw_problems[0]}")
    # platform-health custody
    binding = receipt.get("platform_health_receipt")
    health_receipt = receipt.get("platform_health")
    health_dir = unit_dir
    if isinstance(binding, dict) and ".." in Path(
            binding.get("path", "")).parts:
        # same-process receipts bind the shared lifecycle receipt
        # (../<lifecycle>/platform-health-receipt.json)
        parts = [p for p in Path(binding["path"]).parts if p != ".."]
        if len(parts) != 2:
            raise ValueError("platform-health receipt binding malformed")
        health_dir = unit_dir.parent / parts[0]
        binding_path = health_dir / parts[1]
    else:
        binding_path = unit_dir / (
            binding.get("path") if isinstance(binding, dict)
            else "platform-health-receipt.json")
    raw_health = binding_path.read_bytes()
    if (not isinstance(binding, dict)
            or type(binding.get("bytes")) is not int
            or binding["bytes"] != len(raw_health)
            or binding.get("sha256") != hashlib.sha256(raw_health).hexdigest()
            or binding.get("window") != health_receipt.get("window")):
        raise ValueError("platform-health receipt binding mismatch")
    checked = H.verify_platform_health(
        health_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(P.ARM)["bdf"],
        expected_arm=P.ARM)
    if not checked["valid"]:
        raise ValueError("platform-health custody invalid")
    return {"tag": tag, "token_sha256": token_sha, "row_sha256": row_sha,
            "receipt": receipt, "rows_meta_lines": lines,
            "reachability_source": receipt.get("reachability_source"),
            "fatal_findings": checked["fatal_findings"]}


def _verify_namespace_population(
        root: Path, namespace: str, arm: str, expected_head: str,
        authority: dict[str, Any], attestation: dict[str, Any],
        tags: list[str], request_kind_for_tag: Callable[[str], str],
        extra_expected: set[str] | None = None,
        allow_inflight_tail: bool = False,
        ) -> tuple[dict[str, Any], list[str]]:
    """Verify one condition's retained population under the FROZEN
    PREFIX POPULATION LAW (correction pass 3, blocker 2).

    OLD DEFECT: required every planned tag to exist, defeating the
    frozen early-stop law — a correctly stopped early-mismatch
    condition was classified incomplete. CORRECTED: the population is
    judged by ``D.prefix_population_facts`` from the RETAINED bytes:
    a contiguous retained prefix containing the first verified
    row-digest mismatch (execution stopped there) is a COMPLETE
    NONDETERMINISTIC population; the unexecuted planned tail is not
    missing evidence. A deterministic claim still requires the full
    predeclared population, all identical. Gaps, cherry-picking,
    quarantined-result substitution, or execution past the declared
    stop point fail closed. Quarantined siblings and unplanned
    current units remain problems.
    """
    base = D.namespace_dir(root, namespace)
    problems: list[str] = []
    facts: list[dict[str, Any]] = []
    if base.is_symlink() or not base.is_dir():
        return {}, [f"{arm}: namespace {namespace} missing"]
    current: set[str] = set()
    for candidate in sorted(base.iterdir()):
        name = candidate.name
        if name.endswith("-quarantined") or name.endswith("lifecycle"):
            continue
        if candidate.is_dir() and not candidate.is_symlink() and (
                UNIT_SAFE_TAG.fullmatch(name)):
            current.add(name)
    expected_all = set(tags) | (extra_expected or set())
    unplanned = current - expected_all
    if unplanned:
        problems.append(
            f"{arm}: unplanned current units present: {sorted(unplanned)}")
    retained: list[str] = []
    for tag in tags:
        if tag not in current:
            continue  # prefix law: the unexecuted tail is not missing
        try:
            facts.append(_verify_unit_receipt(
                base / tag, namespace, arm, tag, expected_head,
                authority, attestation, request_kind_for_tag(tag)))
            retained.append(tag)
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            problems.append(f"{arm}: malformed retained unit {tag}: {exc}")
    if problems:
        return {"units": facts, "retained_tags": retained}, problems
    by_tag = {f["tag"]: f for f in facts}
    digests = {t: tuple(by_tag[t]["row_sha256"]) for t in retained}
    prefix = D.prefix_population_facts(
        tags, retained, digests,
        allow_inflight_tail=allow_inflight_tail)
    out: dict[str, Any] = {"units": facts, "retained_tags": retained,
                           "prefix_law": prefix}
    if prefix["population"] == "invalid":
        problems.append(
            f"{arm}: invalid retained population: {prefix['invalid']}")
    elif prefix["population"] == "incomplete":
        # not a failure by itself: deterministic-claim sufficiency is
        # judged by the sequential law; carry the facts upward.
        out["population_incomplete"] = True
    return out, problems


# ---------------------------------------------------------------------------
# Accepted #248 contrast verification (read-only historical authority)
# ---------------------------------------------------------------------------

def _verify_contrast_manifest(manifest_path: Path) -> dict[str, Any]:
    """Verify the accepted #248 SHA256SUMS manifest self-digest."""
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != D.ACCEPTED_248_MANIFEST_SELF_DIGEST:
        raise ValueError(
            f"accepted #248 manifest self-digest drift: {digest}")
    rows: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError("malformed manifest row")
        rows[parts[1].strip()] = parts[0].strip()
    return {"rows": rows, "self_digest": digest}


# The accepted #248 retained units bind the exact head of the #248
# DISPATCH generation (the reviewed tooling head the campaign ran
# under), not the later result-adjudication head; both are frozen
# accepted authority constants.
CONTRAST_AUTHORITY_HEAD = "3f36ef1a518065bdc848cb66f6f26d94b34319f4"


def verify_historical_contrast(contrast_root: Path) -> dict[str, Any]:
    """Consume the accepted #248 retained ngl=1 result as the Arm-A
    nonzero-Vulkan contrast (READ-ONLY; never fresh #250 execution).

    Verifies: manifest self-digest; every consumed file's digest
    against a manifest row; unit receipts bind the accepted #248
    result head + placement namespace; ngl/case exact; row
    nondeterminism DERIVED from the retained row bytes themselves.
    """
    contrast_root = Path(contrast_root)
    manifest = _verify_contrast_manifest(contrast_root / "SHA256SUMS")
    rows = manifest["rows"]
    units = []
    for tag in D.CONTRAST_UNITS:
        unit_dir = contrast_root / D.CONTRAST_NAMESPACE / tag
        if unit_dir.is_symlink() or not unit_dir.is_dir():
            raise ValueError(f"contrast unit missing: {tag}")
        receipt_raw = (unit_dir / "unit.json").read_bytes()
        _require_manifest_row(rows, f"{D.CONTRAST_NAMESPACE}/{tag}/unit.json",
                              receipt_raw)
        receipt = json.loads(receipt_raw)
        if (receipt.get("namespace") != D.CONTRAST_NAMESPACE
                or receipt.get("case_id") != D.CONTRAST_CASE
                or receipt.get("ngl") != D.CONTRAST_NGL):
            raise ValueError(f"contrast unit binding mismatch: {tag}")
        authority = receipt.get("authority", {})
        if (authority.get("head_sha") != CONTRAST_AUTHORITY_HEAD
                or authority.get("namespace") != D.CONTRAST_NAMESPACE
                or authority.get("pr_number") != 249
                or authority.get("issue_number") != 248):
            raise ValueError(
                f"contrast unit not bound to the accepted #248 dispatch "
                f"head/PR/issue: {tag}")
        row_sha = []
        for i in range(D.DECISIONS):
            rel = f"{D.CONTRAST_NAMESPACE}/{tag}/obs.row{i}.f32"
            row = (contrast_root / rel).read_bytes()
            _require_manifest_row(rows, rel, row)
            if len(row) != D.ROW_BYTES:
                raise ValueError(f"contrast row width mismatch: {rel}")
            row_sha.append(hashlib.sha256(row).hexdigest())
        if receipt.get("observer_rows") != row_sha:
            raise ValueError(f"contrast receipt row digests mismatch: {tag}")
        units.append({"tag": tag, "row_sha256": row_sha,
                      "token_sha256": receipt["deterministic_output_sha256"]})
    if len(units) < D.CONTRAST_MIN_UNITS:
        raise ValueError("contrast population incomplete")
    row_digests = [tuple(u["row_sha256"]) for u in units]
    row_deterministic = len(set(row_digests)) == 1
    if row_deterministic != D.CONTRAST_EXPECTED_ROW_DETERMINISTIC:
        raise ValueError(
            "retained #248 contrast rows contradict the accepted "
            "nondeterminism — the planned Arm-A comparison is destroyed")
    return {
        "provenance": D.CONTRAST_PROVENANCE,
        "namespace": D.CONTRAST_NAMESPACE,
        "units": units,
        "manifest_self_digest": manifest["self_digest"],
        "row_deterministic": row_deterministic,
        "note": "accepted #248 retained evidence consumed read-only; "
                "never represented as fresh #250 execution",
    }


def _require_manifest_row(rows: dict[str, str], rel: str, raw: bytes
                          ) -> None:
    expected = rows.get(rel)
    if expected is None:
        raise ValueError(f"consumed contrast file absent from manifest: {rel}")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"contrast file digest mismatch: {rel}")


# ---------------------------------------------------------------------------
# Same-process lifecycle verification (Arm B condition 2)
# ---------------------------------------------------------------------------

def _verify_same_process_units(
        root: Path, namespace: str, arm: str, expected_head: str,
        authority: dict[str, Any], attestation: dict[str, Any],
        expected_prompt_tokens: int = 3077,
        ) -> tuple[dict[str, Any], list[str]]:
    """Verify the Arm-B same-process population from retained bytes.

    Requires: one shared lifecycle record binding ONE PID to all five
    requests; per-request TASK-BOUND reset proofs (selection-by-id ->
    fresh-task launch -> full-prompt eval, re-derived from the retained
    log slices against the consumed task-id set — correction pass 3,
    blocker 3); per-request authority blocks (blocker 1) that each
    equal the live-validated authority generation; request-history
    invariance (same frozen Arm-B contract, same shared PID).

    PREFIX LAW (blocker 2): an authority/process/error-truncated
    lifecycle is an INCOMPLETE population, never a valid
    nondeterministic early-stop — the reducer distinguishes
    mismatch-triggered stops (valid) from truncation (fail-closed).
    """
    base = D.namespace_dir(root, namespace)
    problems: list[str] = []
    plan = D.probe_list_for(arm)
    same_specs = [u for u in plan if u.get("same_process")]
    tags = [u["tag"] for u in same_specs]
    lifecycle_dir = base / (tags[0].rsplit("-", 1)[0] + "-lifecycle")
    if lifecycle_dir.is_symlink() or not lifecycle_dir.is_dir():
        return {}, [f"{arm}: same-process lifecycle record missing"]
    lifecycle_raw = (lifecycle_dir / "lifecycle.json").read_bytes()
    lifecycle = json.loads(lifecycle_raw)
    if lifecycle.get("schema") != P.LIFECYCLE_SCHEMA:
        return {}, [f"{arm}: lifecycle schema mismatch"]
    shared_pid = lifecycle.get("shared_server_pid")
    if type(shared_pid) is not int or shared_pid <= 0:
        return {}, [f"{arm}: lifecycle binds no shared PID"]
    # Lifecycle completion cause (correction pass 4, NO-GO 5851078451,
    # blocker 1). A TRUNCATED lifecycle (authority/process/error loss
    # mid-sequence) is NEVER terminal-complete — even when its
    # retained prefix happens to contain a row mismatch: the truncated
    # retained prefix stays valid historical evidence (units are still
    # verified below when present), but authority/process/error
    # truncation is not equivalent to the prospectively authorized
    # mismatch-stop law, so the truncation CAUSE dominates any
    # accidental mismatch inside the prefix and the population is
    # reported incomplete (BLOCKED). A MISMATCH STOP is the frozen
    # early-stop law firing: authority current, the current request
    # completed, the mismatch mechanically derived from the retained
    # rows, and the stop occurred because the discriminator was
    # answered — the retained prefix IS a complete nondeterministic
    # population.
    stop_kind = lifecycle.get("stop_kind", "completed_all")
    if stop_kind not in ("completed_all", "truncated", "mismatch_stop"):
        return {}, [f"{arm}: lifecycle stop kind malformed: "
                    f"{stop_kind!r}"]
    planned = lifecycle.get("planned_request_count", len(tags))
    if stop_kind == "truncated":
        # Truncated-lifecycle schema (correction pass 4, blocker 1):
        # the accounting fields are mechanically validated against the
        # retained request units — successful gate observations must
        # equal the retained request count, and the failed gate index
        # (when present) must not correspond to any retained request.
        successful = lifecycle.get("successful_gate_count")
        if type(successful) is not int or successful != lifecycle.get(
                "request_count"):
            return {}, [f"{arm}: truncated lifecycle gate accounting "
                        f"malformed (successful gates {successful!r} "
                        f"!= retained {lifecycle.get('request_count')!r})"]
        failed_index = lifecycle.get("failed_gate_index")
        if failed_index is not None and (type(failed_index) is not int
                                         or failed_index < 0
                                         or failed_index >= planned):
            return {}, [f"{arm}: truncated lifecycle failed gate index "
                        f"malformed: {failed_index!r}"]
        return {}, [f"{arm}: same-process lifecycle TRUNCATED "
                    f"(retained {lifecycle.get('request_count')}/"
                    f"{planned} requests; successful gates="
                    f"{successful}; failed gate index="
                    f"{failed_index!r}; reason="
                    f"{lifecycle.get('stop_reason')!r}) — an "
                    "authority/process/error-loss partial prefix is "
                    "never terminal-complete even if it contains a "
                    "row mismatch (truncation cause dominates)"]
    if stop_kind == "mismatch_stop" and lifecycle.get(
            "request_count", 0) < D.PREFIX_LAW_MIN_MISMATCH_UNITS:
        return {}, [f"{arm}: mismatch-stop lifecycle retained fewer "
                    "than two requests"]
    if lifecycle.get("request_count") != len(tags):
        # mismatch_stop retains a prefix < planned; completed_all must
        # cover every planned request
        if stop_kind != "mismatch_stop":
            return {}, [f"{arm}: lifecycle request count != planned "
                        f"{len(tags)}"]
    authority_block = lifecycle.get("authority")
    expected_block = P.unit_authority_block(authority)
    for key, value in expected_block.items():
        if not isinstance(authority_block, dict) or (
                authority_block.get(key) != value):
            return {}, [f"{arm}: lifecycle authority binding mismatch "
                        f"({key})"]
    # per-request authority observations (correction pass 3, blocker 1)
    per_request_authorities = lifecycle.get("per_request_authorities")
    if (not isinstance(per_request_authorities, list)
            or len(per_request_authorities)
            != lifecycle.get("request_count")
            or any(not isinstance(a, dict) for a in
                   per_request_authorities)):
        return {}, [f"{arm}: lifecycle lacks one bound authority "
                    "observation per retained request"]
    for index, block in enumerate(per_request_authorities):
        for key, value in expected_block.items():
            if block.get(key) != value:
                return {}, [f"{arm}: request {index} authority "
                            f"observation mismatch ({key})"]
    units = []
    consumed_task_ids: set[int] = set()
    retained_count = lifecycle.get("request_count", len(same_specs))
    for spec in same_specs:
        tag = spec["tag"]
        index = same_specs.index(spec)
        # PREFIX LAW (blocker 2): a mismatch-stop lifecycle retains
        # only the executed prefix; the unexecuted planned tail is not
        # malformed — it is not missing evidence either.
        if (stop_kind == "mismatch_stop" and index >= retained_count):
            continue
        try:
            fact = _verify_unit_receipt(
                base / tag, namespace, arm, tag, expected_head,
                authority, attestation, "arm-b")
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            problems.append(f"{arm}: malformed same-process unit {tag}: "
                            f"{exc}")
            continue
        receipt = fact["receipt"]
        sp = receipt.get("same_process")
        if (not isinstance(sp, dict)
                or sp.get("shared_server_pid") != shared_pid
                or type(sp.get("request_index")) is not int
                or not isinstance(sp.get("reset_proof"), dict)):
            problems.append(
                f"{arm}: unit {tag} not bound to the shared lifecycle "
                "PID/requests")
            continue
        index = sp["request_index"]
        # Re-derive the TASK-BOUND reset proof from the retained log
        # slice bytes against the consumed task-id set (blocker 3):
        # delayed prior-task evidence must fail this request.
        log_raw = (base / tag / "server.log").read_bytes()
        rederived = P._parse_slot_log(
            log_raw.decode("utf-8", errors="replace"),
            index, expected_prompt_tokens,
            consumed_task_ids=frozenset(consumed_task_ids))
        if not rederived["proven"]:
            problems.append(
                f"{arm}: unit {tag} retained log slice does not prove "
                f"task-bound reset semantics: {rederived['problems']}")
            continue
        # the receipt's own proof must agree with the re-derivation
        if sp["reset_proof"].get("task_id") != rederived["task_id"]:
            problems.append(
                f"{arm}: unit {tag} reset-proof task binding disagrees "
                "with the retained log bytes")
            continue
        consumed_task_ids.add(rederived["task_id"])
        # per-request authority block equality (blocker 1)
        if receipt.get("authority") != per_request_authorities[index]:
            problems.append(
                f"{arm}: unit {tag} authority block differs from the "
                "lifecycle's per-request observation")
            continue
        units.append(fact)
    if problems:
        return {"units": units, "shared_pid": shared_pid}, problems
    indexes = sorted(u["receipt"]["same_process"]["request_index"]
                     for u in units)
    expected_indexes = (list(range(lifecycle.get("request_count")))
                        if stop_kind == "mismatch_stop"
                        else list(range(len(tags))))
    if indexes != expected_indexes:
        problems.append(
            f"{arm}: lifecycle request indexes are not a complete "
            f"sequence: {indexes}")
        return {"units": units, "shared_pid": shared_pid}, problems
    # MISMATCH STOP (blocker 2): re-derive the nondeterminism
    # MECHANICALLY from the retained row digests — never trust the
    # producer's stop claim. The retained prefix must actually contain
    # the first row-digest mismatch.
    if stop_kind == "mismatch_stop":
        row_tuples = [tuple(u["row_sha256"]) for u in units]
        if len(set(row_tuples)) == 1:
            problems.append(
                f"{arm}: lifecycle claims a mismatch stop but the "
                "retained rows are all identical — the claim is not "
                "supported by retained bytes")
    prefix = D.prefix_population_facts(
        [u["tag"] for u in same_specs],
        [u["receipt"]["tag"] for u in units],
        {u["receipt"]["tag"]: tuple(u["row_sha256"])
         for u in units},
        deterministic_required=len(tags))
    return {"units": units, "shared_pid": shared_pid,
            "lifecycle": lifecycle, "prefix_law": prefix}, problems


# ---------------------------------------------------------------------------
# Condition determinism derivation
# ---------------------------------------------------------------------------

def _walk_condition(pop: dict[str, Any]) -> dict[str, Any]:
    """Convert one verified population's prefix-law facts into the
    sequential-walk decision (correction pass 3, blocker 2).

    OLD DEFECT: the walk required the full planned population, so a
    correctly stopped early-mismatch condition was BLOCKED. CORRECTED:
    a ``complete_nondeterministic_prefix`` (contiguous retained prefix
    containing the first verified mismatch, execution stopped there)
    is a VALID nondeterministic verdict — the walk proceeds to the
    next arm. Only genuinely incomplete/invalid populations block.
    """
    prefix = pop.get("prefix_law") or {}
    return {
        "deterministic": bool(prefix.get("deterministic")),
        "nondeterministic": bool(prefix.get("nondeterministic")),
        "n": prefix.get("n", 0),
        "population": prefix.get("population"),
        "invalid": prefix.get("invalid"),
        "stop_reason": prefix.get("stop_reason"),
    }


def _condition_determinism(units: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a condition's determinism from unit row/token digests."""
    if not units:
        return {"deterministic": None, "n": 0}
    row_digests = [tuple(u["row_sha256"]) for u in units]
    token_digests = [u["token_sha256"] for u in units]
    rows_identical = len(set(row_digests)) == 1
    row_judgement = D.judge_repeat_determinism(
        [hashlib.sha256(json.dumps(list(rd)).encode()).hexdigest()
         for rd in row_digests])
    token_judgement = D.judge_repeat_determinism(token_digests)
    return {
        "deterministic": row_judgement["deterministic_claim_valid"],
        "rows_strictly_identical": rows_identical,
        "row_deterministic_claim_valid":
            row_judgement["deterministic_claim_valid"],
        "token_deterministic_claim_valid":
            token_judgement["deterministic_claim_valid"],
        "n": len(units),
        "row_unique_tuples": len(set(row_digests)),
        "token_unique": len(set(token_digests)),
    }


def _arm_a_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any], contrast_root: Path,
                 ) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    pop, pop_problems = _verify_namespace_population(
        root, "d250-arm-a", "A-vulkan-necessity", expected_head,
        authority, attestation,
        [u["tag"] for u in D.probe_list_for("A-vulkan-necessity")],
        lambda tag: "accepted")
    problems.extend(pop_problems)
    # AMENDMENT-008 r2: the population's reachability provenance is the
    # per-unit receipt provenance; a population mixing paths (or with
    # none, already rejected per-unit) fails closed here.
    sources = {u.get("reachability_source")
               for u in pop.get("units", [])}
    if len(sources) == 1 and sources <= {
            "historical-v0-amd-variable", "arm-a-bridge"}:
        pop["reachability_source"] = sources.pop()
    elif pop.get("units"):
        problems.append(
            "Arm-A population mixes or lacks reachability provenance: "
            f"{sorted(map(str, sources))}")
    try:
        contrast = verify_historical_contrast(contrast_root)
    except (OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError) as exc:
        return pop, problems + [f"contrast verification failed: {exc}"]
    return {**pop, "contrast": contrast}, problems


def _arm_b_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any],
                 ) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    fresh_tags = [u["tag"] for u in D.probe_list_for("B-process-init")
                  if not u.get("same_process")]
    same_tags = [u["tag"] for u in D.probe_list_for("B-process-init")
                 if u.get("same_process")]
    pop, pop_problems = _verify_namespace_population(
        root, "d250-arm-b", "B-process-init", expected_head,
        authority, attestation, fresh_tags, lambda tag: "accepted",
        extra_expected=set(same_tags))
    problems.extend(pop_problems)
    same, same_problems = _verify_same_process_units(
        root, "d250-arm-b", "B-process-init", expected_head,
        authority, attestation)
    problems.extend(same_problems)
    return {"fresh": pop, "same_process": same}, problems


def _arm_c_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any], repo_root: Path,
                 authority_fetcher: Any = None,
                 ) -> tuple[dict[str, Any], list[str]]:
    """AMENDMENT-003: verify the amended Arm-C shape.

    * d250-arm-c: the default-threading CPU-only reproduction pair.
    * d250-arm-c1: the bounded reduced-parallelism probe (5 units,
      prefix early-stop law). Verified against its own live authority.
    * d250-arm-c2 (optional): consumed ONLY when the serial gate
      closed — a C1-completed gate record binding BOTH the C1 and C2
      authority digests must be retained at the root; otherwise the
      serial condition is reported absent-with-gate-closed=False and
      the sequential walk decides (maintainer stop for either C1 verdict).
    """
    problems: list[str] = []
    default_pop, default_problems = _verify_namespace_population(
        root, "d250-arm-c", "C-cpu-threads", expected_head,
        authority, attestation,
        [u["tag"] for u in D.probe_list_for("C-cpu-threads")],
        lambda tag: "accepted")
    problems.extend(default_problems)
    c1_authority = None
    if authority is not None:
        try:
            c1_authority = P.require_live_dispatch(
                repo_root, expected_head, "d250-arm-c1",
                revalidate_authority=authority_fetcher)
        except Exception as exc:
            problems.append(
                f"live dispatch authority for d250-arm-c1 rejected: "
                f"{exc}")
            c1_authority = None
    c1_pop: dict[str, Any] = {}
    if c1_authority is not None:
        c1_pop, c1_problems = _verify_namespace_population(
            root, "d250-arm-c1", "C1-reduced-parallelism",
            expected_head, c1_authority, attestation,
            [u["tag"] for u in D.probe_list_for(
                "C1-reduced-parallelism")],
            lambda tag: "accepted")
        problems.extend(c1_problems)
    else:
        c1_pop = {"units": [], "retained_tags": []}
    # Serial population: consumed ONLY through the explicit gate.
    c1_verdict = _walk_condition(c1_pop)
    completed_verdict = ("deterministic" if c1_verdict["deterministic"]
                         else "variable" if c1_verdict["nondeterministic"]
                         else None)
    gate_path = root / D.C2_GATE_RECORD_NAME
    record_present = gate_path.exists() or gate_path.is_symlink()
    serial_gate_closed = (completed_verdict is not None and
                          c1_authority is not None and
                          D.c1_dispatch_c2_unlocked(
                              root, expected_head=expected_head,
                              c1_authority=c1_authority,
                              c1_verdict=completed_verdict))
    serial_pop: dict[str, Any] = {"units": [], "retained_tags": [],
                                  "gate_closed": serial_gate_closed}
    if record_present and not serial_gate_closed:
        problems.append("C2 gate record does not bind completed retained "
                        "C1 verdict and live C1 authority")
    if not record_present and (root / D.C2_SERIAL_NAMESPACE).exists():
        problems.append("C2 units present without dedicated gate record")
    if serial_gate_closed:
        c2_authority = None
        if authority is not None:
            try:
                c2_authority = P.require_live_dispatch(
                    repo_root, expected_head, D.C2_SERIAL_NAMESPACE,
                    revalidate_authority=authority_fetcher)
            except Exception as exc:
                problems.append(
                    f"live dispatch authority for {D.C2_SERIAL_NAMESPACE} "
                    f"rejected: {exc}")
        if c2_authority is not None:
            gate_doc = _load_c2_gate_record(root)
            if gate_doc is not None and D.c1_dispatch_c2_unlocked(
                    root, expected_head=expected_head,
                    c1_authority=c1_authority,
                    c1_verdict=completed_verdict,
                    c2_authority=c2_authority):
                serial_pop, serial_problems = _verify_namespace_population(
                    root, D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME,
                    expected_head, c2_authority, attestation,
                    [u["tag"] for u in D.probe_list_for(D.ARM_C2_NAME)],
                    lambda tag: "accepted")
                serial_pop["gate_closed"] = True
                problems.extend(serial_problems)
            else:
                problems.append(
                    "c2 gate record does not bind the live d250-arm-c2 "
                    "authority digest")
    return {"default": default_pop, "c1": c1_pop, "serial": serial_pop,
            "c1_authority": c1_authority}, problems


def _load_c2_gate_record(root: Path) -> dict[str, Any] | None:
    path = Path(root) / D.C2_GATE_RECORD_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def validate_ladder_length_authority(receipt: dict[str, Any],
                                     all_cells_max: int,
                                     selective_min: int | None = None,
                                     runtime_prompt_eval_tokens:
                                     int | None = None,
                                     ) -> dict[str, Any]:
    """Reduce one ladder length's token authority against the frozen
    token-count mechanism (correction pass 3, blocker 4A; boundary
    sides corrected in pass 5, NO-GO 5852014883).

    Uses the ACTUAL token count — never the nominal ladder label —
    for the ``indexer.top_k`` selection-width boundary judgment, and
    (when the runtime/server prompt-eval count is retained) fails
    closed unless runtime and tokenizer authority agree byte-for-byte
    on count.

    ``all_cells_max`` is the source-law all-cells maximum (2051):
    a count <= all_cells_max is on the dense/all-cells side (the
    selection width still covers the full population — 2051 itself
    is NOT selective). ``selective_min`` (default
    all_cells_max + 1 = 2052) is the first count on the selective
    side. A legacy call passing the old single ``top_k``-style
    threshold positionally still receives a meaningful dense-side
    comparison; keyword use is explicit.
    """
    actual = receipt.get("actual_token_count")
    if type(actual) is not int or actual <= 0:
        raise D.DiagnosticError(
            "ladder token authority lacks an actual token count")
    if selective_min is None:
        selective_min = all_cells_max + 1
    runtime_match = True
    if runtime_prompt_eval_tokens is not None:
        runtime_match = (runtime_prompt_eval_tokens == actual)
    return {
        "nominal_length": receipt.get("nominal_length"),
        "actual_token_count": actual,
        "crosses_top_k": actual >= selective_min,
        "all_cells_side": actual <= all_cells_max,
        "selective_side": actual >= selective_min,
        "runtime_matches_authority": runtime_match,
    }


def _arm_d_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any],
                 ) -> tuple[dict[str, Any], list[str]]:
    plan = D.probe_list_for("D-context-transition")
    problems: list[str] = []
    # Retained tokenizer authority (blocker 4A): mandatory for Arm D.
    try:
        token_doc = P.load_ladder_token_authority(root, expected_head)
    except Exception as exc:
        return {}, [f"D: ladder token authority invalid: {exc}"]
    by_length: dict[int, list[dict[str, Any]]] = {}
    for spec in plan:
        length = spec["ladder_length"]
        tag = spec["tag"]
        base = D.namespace_dir(root, "d250-arm-d")
        try:
            fact = _verify_unit_receipt(
                base / tag, "d250-arm-d", "D-context-transition", tag,
                expected_head, authority, attestation, "accepted")
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            # unexecuted planned units are fine (prefix law); record
            # nothing for them unless the directory exists (malformed
            # retained bytes still fail closed)
            if (base / tag).exists() or (base / tag).is_symlink():
                problems.append(f"D: malformed retained unit {tag}: {exc}")
            continue
        log_raw = (base / tag / "server.log").read_bytes()
        by_length.setdefault(length, []).append({
            **fact, "prompt_progress_counts": _ladder_split_shapes(
                log_raw.decode("utf-8", errors="replace")),
            "confirm_extension": bool(spec.get("confirm_extension"))})
    unplanned = _unplanned_arm_d_units(root)
    if unplanned:
        problems.append(f"D: unplanned current units: {unplanned}")
    if problems:
        return {"by_length": by_length}, problems
    # Screening population: every length needs BOTH screening units
    # (the ladder is a predeclared 2-repeat scan at every length).
    for length in D.ARM_D_LADDER_LENGTHS:
        screening = [u for u in by_length.get(length, [])
                     if not u["confirm_extension"]]
        if len(screening) != D.ARM_D_SCREEN_REPEATS:
            problems.append(
                f"D: length {length} screening population is not the "
                f"predeclared pair ({len(screening)}/2)")
    return {"by_length": by_length,
            "token_authority": token_doc}, problems


def _unplanned_arm_d_units(root: Path) -> list[str]:
    base = D.namespace_dir(root, "d250-arm-d")
    if base.is_symlink() or not base.is_dir():
        return []
    planned = {u["tag"] for u in D.probe_list_for("D-context-transition")}
    found = {c.name for c in base.iterdir()
             if c.is_dir() and not c.is_symlink() and not c.name.endswith(
                 "-quarantined")}
    unplanned = found - planned
    # ladder units' tag prefix case-<len> differs from the frozen
    # case vocabulary; validate the ladder shape lexically
    return sorted(t for t in unplanned
                  if UNIT_SAFE_TAG.fullmatch(t)) or sorted(unplanned)


# ---------------------------------------------------------------------------
# Terminal derivation (offline, retained-byte, fail-closed)
# ---------------------------------------------------------------------------

def derive_terminal(evidence_root: Path, expected_head: str, *,
                    repo_root: Path | None = None,
                    authority_fetcher: Any = None,
                    contrast_root: Path | None = None,
                    github_api: str = "https://api.github.com",
                    ) -> dict[str, Any]:
    """Derive the Issue #250 terminal from the retained evidence tree.

    No caller-supplied determinism/factor/terminal/summary values are
    accepted. Authority for each consumed namespace is LIVE-fetched
    through the canonical seam (production default
    ``issue250_physical.fetch_dispatch_authority``); the retained
    receipts must bind exactly the fetched payload. The campaign
    model attestations (opening + closing) are terminal preconditions.
    ``authority_fetcher`` is a TEST-ONLY injection seam; production
    callers pass nothing, which resolves to the REAL live fetcher.

    Sequential law: A always; B required iff A's CPU-only varies; C
    required iff B leaves variation; D required iff A-C do not
    localize. UNRESOLVED only after all REACHABLE arms are complete.
    """
    root = Path(evidence_root)
    if (not isinstance(expected_head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_head)):
        return _blocked(["expected head is not a 40-hex sha"])
    if repo_root is None:
        # production callers must pass the campaign repo root
        # explicitly (no silent cwd trust)
        return _blocked(["repo_root is required for terminal derivation"])

    # V0 precedes the A-D ladder. A retained AMD mismatch is necessary but
    # never a dispatch: A still needs its own fresh exact-head authority.
    if contrast_root is None:
        return _blocked(["accepted #248 retained contrast root is required"],
                        {"v0": {"state": D.V0_STATE_INVALID, "valid": False,
                                "a_eligible": False, "terminal": None,
                                "reason": "accepted #248 root not supplied"}})
    # METHODOLOGY-AMENDMENT-008 (reducer-admission correction): admission
    # is PATH-AWARE before the Arm-A walk.  A compliant AMENDMENT-008
    # bridge campaign root carries NO top-level d250-arm-v0-amd/ tree and
    # admits NO same-head V0 dispatch (the completed predecessor
    # dispatch is historical/stale), so ``derive_v0_state`` can never
    # run there; its predecessor chain is instead authenticated through
    # the SAME frozen bridge authority the launch gate uses —
    # ``validate_arm_a_bridge`` -> ``revalidating_arm_a_predecessors``
    # over the read-only predecessor-v0/ + predecessor-v0n/ mounts.
    # Bridge mode is never inferred from the absence of V0 evidence: a
    # valid, canonical, maintainer-adjudicated bridge record with both
    # predecessor populations fully re-authenticated is REQUIRED, and
    # any bridge-record presence with a failing authentication blocks
    # (never falls back to historical admission).  The historical
    # top-level-V0 path below is byte-for-byte unchanged.
    bridge_record_present = (root / D.ARM_A_BRIDGE_NAME).exists()
    if bridge_record_present:
        try:
            P.validate_arm_a_bridge(root, expected_head)
        except Exception as exc:
            return _blocked(
                ["Arm-A bridge admission rejected: "
                 f"{type(exc).__name__}: {exc}"],
                {"v0": {"state": D.V0_STATE_INVALID, "valid": False,
                        "a_eligible": False, "terminal": None,
                        "admission": "amendment-008-bridge",
                        "reason": f"bridge authentication failed: {exc}"}})
        try:
            predecessors = P.revalidating_arm_a_predecessors(root)
        except Exception as exc:
            return _blocked(
                ["Arm-A bridge predecessor revalidation rejected: "
                 f"{type(exc).__name__}: {exc}"],
                {"v0": {"state": D.V0_STATE_INVALID, "valid": False,
                        "a_eligible": False, "terminal": None,
                        "admission": "amendment-008-bridge",
                        "reason": f"predecessor revalidation failed: {exc}"}})
        v0 = {"state": predecessors["v0"].get("state"),
              "valid": True, "terminal": None, "a_eligible": False,
              "admission": "amendment-008-bridge",
              "reachability_source": "arm-a-bridge",
              "predecessors": {
                  ns: (predecessors[ns].get("state"),
                       predecessors[ns].get("amd_rows")
                       or predecessors[ns].get("row_classes"))
                  for ns in ("v0", "v0n")}}
    else:
        v0 = derive_v0_state(root, contrast_root, Path(repo_root),
                             expected_head,
                             authority_fetcher=authority_fetcher,
                             github_api=github_api)
    if (not bridge_record_present
            and (v0.get("state") != D.V0_STATE_AMD_VARIABLE
                 or not v0.get("a_eligible"))):
        # METHODOLOGY-AMENDMENT-008 (corrected round 2): when the V0
        # state is the ACCEPTED adjudicated stop AND the corrected
        # bridge record authenticates (exact predecessor decisions
        # revalidated from the read-only mounts), the Arm-A population
        # IS consumable — the walk proceeds to Arm A and STOPS there
        # (see the reachability_source law below). Every other
        # non-AMD_VARIABLE state blocks exactly as before.
        if v0.get("state") == D.V0_STATE_DISAGREEMENT_STOP:
            try:
                P.validate_arm_a_bridge(root, expected_head)
            except Exception as exc:
                return _blocked(
                    [f"V0 gate blocks A: {v0.get('state')}: "
                     f"{v0.get('reason', 'maintainer stop')}; "
                     f"Arm-A bridge rejected: {exc}"], {"v0": v0})
        else:
            reason = (f"V0 gate blocks A: {v0.get('state')}: "
                      f"{v0.get('reason', 'maintainer stop or third required')}")
            return _blocked([reason], {"v0": v0})

    reduction: dict[str, Any] = {"arms": {}, "contrast": None, "v0": v0}

    # Campaign model attestation preconditions (opening + closing).
    attestation: dict[str, Any] | None = None
    try:
        opening_path = root / P.MODEL_ATTESTATION_OPEN_NAME
        if opening_path.is_symlink() or not opening_path.is_file():
            raise ValueError("opening attestation missing or symlink")
        opening = json.loads(opening_path.read_bytes())
        P.validate_model_attestation(opening, expected_head)
        closing_path = root / P.MODEL_ATTESTATION_CLOSE_NAME
        if closing_path.is_symlink() or not closing_path.is_file():
            raise ValueError("closing attestation missing or symlink")
        closing = json.loads(closing_path.read_bytes())
        P.validate_closing_attestation(closing, opening)
        attestation = opening
    except (OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError, D.DiagnosticError) as exc:
        return _blocked([f"campaign model attestation invalid: {exc}"])
    if attestation is None:  # defensive narrowing; unreachable
        return _blocked(["campaign model attestation invalid"])

    # CORRECTION PASS 6 (AMENDMENT-003): the canonical generation is a
    # reduction precondition. A retired-generation path/marker, or a
    # retained cost-planning record whose generation field was
    # mutated, fails closed — v1 defect evidence can never mix into a
    # canonical terminal.
    try:
        canonical_generation = P.validate_evidence_generation(root)
    except Exception as exc:
        return _blocked([f"evidence generation binding invalid: {exc}"])
    cost_record_path = root / "cost-planning-record.json"
    if cost_record_path.is_file() and not cost_record_path.is_symlink():
        try:
            cost_record = json.loads(cost_record_path.read_bytes())
            retained_gen = cost_record.get("evidence_generation")
        except Exception as exc:
            return _blocked(
                [f"cost planning record unreadable: {exc}"])
        if retained_gen not in (None, canonical_generation):
            return _blocked(
                [f"cost planning record generation mismatch: "
                 f"{retained_gen!r} != canonical "
                 f"{canonical_generation!r} (no mixing across "
                 "generations)"])

    # Live authority for the FIRST reachable namespace decides the
    # ladder walk; every namespace consumed here is fetched live and
    # every retained receipt must bind it exactly.
    problems: list[str] = []

    def _fetch(namespace: str, arm: str) -> dict[str, Any] | None:
        try:
            payload = P.require_live_dispatch(
                repo_root, expected_head, namespace,
                revalidate_authority=authority_fetcher,
                github_api=github_api)
        except Exception as exc:  # network/OS/git loss fails closed
            problems.append(
                f"live dispatch authority for {namespace} rejected: {exc}")
            return None
        if payload.get("arm") != arm:
            problems.append(
                f"live dispatch for {namespace} binds arm "
                f"{payload.get('arm')!r} != {arm!r}")
            return None
        return payload

    # ---------------- Arm A (always required) ----------------
    authority_a = _fetch("d250-arm-a", "A-vulkan-necessity")
    if authority_a is None:
        return _blocked(problems, reduction)
    arm_a, a_problems = _arm_a_facts(
        root, expected_head, authority_a, attestation,
        contrast_root or root)
    problems.extend(a_problems)
    reduction["arms"]["A-vulkan-necessity"] = arm_a
    reduction["contrast"] = arm_a.get("contrast")
    if problems:
        return _blocked(problems, reduction)
    cpu_units = arm_a.get("units", [])
    cpu = _walk_condition(arm_a)
    arm_a["cpu_only_devnone"] = cpu
    contrast = arm_a.get("contrast") or {}
    contrast_varies = (contrast.get("row_deterministic") is False)

    # METHODOLOGY-AMENDMENT-008 (corrected round 2): a COMPLETED
    # bridge-path Arm-A population STOPS the ladder for maintainer
    # review — REGARDLESS of the result. Deterministic ⇒ review before
    # any LOCALIZED claim (no Vulkan root cause is inferred); variable
    # ⇒ review before any B execution. No terminal is emitted and no
    # later arm is auto-reachable from a bridge-path Arm A.
    if arm_a.get("reachability_source") == "arm-a-bridge":
        return _blocked([ARM_A_STOPS_LADDER], reduction)

    if cpu["deterministic"] and contrast_varies:
        # A localizes: backend-participation boundary.
        return _ok(LOCALIZED, reduction, {
            "localized_factor":
                LOCALIZED_FACTORS["A-vulkan-necessity"],
            "arm": "A-vulkan-necessity",
            "deterministic_condition":
                "cpu-only -dev none (5/5 identical rows)",
            "nondeterministic_condition":
                "accepted #248 retained ngl=1 case-3072 (row-varying)",
            "contrast_provenance": D.CONTRAST_PROVENANCE,
        })
    if cpu["deterministic"] and not contrast_varies:
        # Contrast destroyed (e.g. retained bytes no longer vary): the
        # planned comparison is destroyed; honest UNRESOLVED per the
        # frozen rule (verify_historical_contrast already fails closed
        # on contradiction, so this branch is defensive only).
        return _ok(UNRESOLVED, reduction, {
            "reason": "CPU-only deterministic but the accepted contrast "
                      "did not establish nonzero-Vulkan variation",
        })
    if cpu["nondeterministic"]:
        # CPU-only VARIES (valid early-stop prefix or full varying
        # population): Vulkan participation NOT necessary.
        # Arm B becomes REQUIRED; no terminal is emitted here.
        pass
    else:
        # incomplete (identical rows below claim threshold, or zero
        # units) or invalid — both fail closed
        return _blocked(
            ["arm A CPU-only determinism incomplete/ambiguous"],
            reduction)

    # ---------------- Arm B (required: A CPU-only varies) ----------
    # (A bridge-path Arm A already returned ARM_A_STOPS_LADDER above.)
    authority_b = _fetch("d250-arm-b", "B-process-init")
    if authority_b is None:
        return _blocked(problems, reduction)
    arm_b, b_problems = _arm_b_facts(
        root, expected_head, authority_b, attestation)
    problems.extend(b_problems)
    reduction["arms"]["B-process-init"] = arm_b
    if problems:
        return _blocked(problems, reduction)
    fresh = _walk_condition(arm_b["fresh"])
    same = _walk_condition(arm_b["same_process"])
    arm_b["cpu_fresh"] = fresh
    arm_b["cpu_same_process"] = same
    if fresh["deterministic"]:
        # A varied but B's fresh condition is deterministic —
        # contradictory across arms; fail closed per the frozen rule.
        return _blocked(
            ["arm B fresh-process CPU-only deterministic while arm A "
             "CPU-only varied (contradictory evidence)"], reduction)
    if same["deterministic"]:
        return _ok(LOCALIZED, reduction, {
            "localized_factor":
                LOCALIZED_FACTORS["B-process-init"],
            "arm": "B-process-init",
            "deterministic_condition":
                "same-process CPU-only repeats (one runtime, id_slot=3, "
                "proven full recompute)",
            "nondeterministic_condition":
                "fresh-process CPU-only repeats (-dev none)",
        })
    if not (fresh["nondeterministic"] and same["nondeterministic"]):
        # BLOCKED covers: missing/incomplete same-process population
        # (INCLUDING authority-loss truncation — a partial same-process
        # prefix without a proven mismatch can never satisfy a
        # deterministic same-process claim, per the frozen prefix law)
        return _blocked([f"arm B evidence incomplete "
                         f"(fresh={fresh['population']}, "
                         f"same_process={same['population']})"], reduction)

    # ---------------- Arm C (required: B leaves variation) ---------
    # AMENDMENT-003: the d250-arm-c reproduction pair, then the
    # bounded C1 reduced-parallelism probe; serial C2 only behind its
    # explicit gate. Reducer-state indication of the gate status is
    # carried in the reduction record.
    authority_c = _fetch("d250-arm-c", "C-cpu-threads")
    if authority_c is None:
        return _blocked(problems, reduction)
    arm_c, c_problems = _arm_c_facts(
        root, expected_head, authority_c, attestation,
        Path(repo_root), authority_fetcher=authority_fetcher)
    problems.extend(c_problems)
    reduction["arms"]["C-cpu-threads"] = arm_c
    if problems:
        return _blocked(problems, reduction)
    default = _walk_condition(arm_c["default"])
    c1 = _walk_condition(arm_c["c1"])
    serial = _walk_condition(arm_c["serial"])
    arm_c["cpu_default_threads"] = default
    arm_c["cpu_c1_reduced_parallelism"] = c1
    arm_c["cpu_serial"] = serial
    if default["deterministic"]:
        # The default-threading CPU-only condition was already proven
        # VARYING at arms A/B (same geometry). A deterministic C pair
        # contradicts that evidence — fail closed (frozen rule).
        return _blocked(
            ["arm C default-threading CPU-only deterministic while "
             "arms A/B CPU-only varied (contradictory evidence)"],
            reduction)
    if not default["nondeterministic"]:
        return _blocked(
            [f"arm C evidence incomplete "
             f"(default={default['population']})"], reduction)
    if c1.get("population") is None:
        # C1 evidence absent while the amended methodology requires it
        # before any serial/D consideration — fail closed.
        return _blocked(
            ["arm C1 bounded probe evidence missing"], reduction)
    reduction["arm_c_gate_status"] = {
        "c1_verdict": ("deterministic" if c1["deterministic"] else
                       "variable" if c1["nondeterministic"] else None),
        "c2_serial_gate_closed":
            arm_c["serial"].get("gate_closed") is True,
        "c2_serial_executed":
            bool(arm_c["serial"].get("retained_tags")),
    }
    if not (c1["deterministic"] or c1["nondeterministic"]):
        return _blocked(
            [f"arm C1 evidence incomplete (c1={c1['population']})"],
            reduction)
    # C1 complete under either verdict, but neither proves the
    # Issue #250 default-vs-serial boundary. Only C2 can localize here.
    # gate status lives on the RAW serial population dict (the walked
    # condition drops non-walk keys).
    if arm_c["serial"].get("gate_closed") is not True:
        # MAINTAINER REVIEW STOP for EITHER C1 verdict: never fall through,
        # never emit a premature UNRESOLVED.
        return _blocked([ARM_C1_VARIED_C2_UNGATED], reduction)
    if not arm_c["serial"].get("retained_tags"):
        return _blocked(
            ["c2 serial gate closed but no serial population is "
             "retained"], reduction)
    if serial["deterministic"]:
        return _ok(LOCALIZED, reduction, {
            "localized_factor": LOCALIZED_FACTORS["C2-serial"],
            "arm": "C2-serial",
            "deterministic_condition":
                "serial CPU-only -t 1 -tb 1 (identical rows at the "
                "frozen deterministic count; maintainer-gated C2 "
                "population)",
            "nondeterministic_condition":
                "default-threading CPU-only 14-thread regime (varies; "
                "established at arms A/B/C fresh CPU-only units)",
            "tested_regimes": {
                "default": "14-thread (accepted default)",
                "serial": "-t 1 -tb 1 (gated C2 regime)",
            },
        })
    if not serial["nondeterministic"]:
        return _blocked(
            [f"arm C2 evidence incomplete "
             f"(serial={serial['population']})"], reduction)
    # Serial also varies (gate closed): the bounded Arm-C methodology
    # is genuinely complete — Arm D becomes required.
    pass

    # ---------------- Arm D (required: A-C did not localize) -------
    authority_d = _fetch("d250-arm-d", "D-context-transition")
    if authority_d is None:
        return _blocked(problems, reduction)
    arm_d, d_problems = _arm_d_facts(
        root, expected_head, authority_d, attestation)
    problems.extend(d_problems)
    reduction["arms"]["D-context-transition"] = arm_d
    if problems:
        return _blocked(problems, reduction)
    token_doc = arm_d.get("token_authority") or {}
    ladder_facts: dict[int, dict[str, Any]] = {}
    for length, units in sorted(arm_d["by_length"].items()):
        row_tuples = [tuple(u["row_sha256"]) for u in units]
        pair = [tuple(u["row_sha256"]) for u in units
                if not u["confirm_extension"]]
        if len(pair) != D.ARM_D_SCREEN_REPEATS:
            problems.append(f"D: length {length} lacks its screening "
                            "pair")
            continue
        token_entry = (token_doc.get("lengths") or {}).get(str(length))
        if not token_entry:
            problems.append(
                f"D: length {length} lacks tokenizer authority")
            continue
        ladder_facts[length] = {
            # screening pair judgement ONLY (2 equal rows are NOT a
            # deterministic condition — correction pass 3, blocker 4C)
            "row_deterministic": len(set(pair)) == 1,
            "pair_identical": len(set(pair)) == 1,
            # deterministic CONFIRMATION: all retained units (screen +
            # adaptive confirm extension) identical at the frozen
            # confirmation count
            "deterministic_confirmed": (
                len(set(row_tuples)) == 1
                and len(row_tuples) >= D.ARM_D_CONFIRM_REPEATS),
            "actual_token_count": token_entry["actual_token_count"],
            "prompt_progress_counts": units[0][
                "prompt_progress_counts"],
            "unit_count": len(units),
        }
    if problems or len(ladder_facts) != len(D.ARM_D_LADDER_LENGTHS):
        return _blocked(problems or ["arm D ladder incomplete"], reduction)
    fired = _evaluate_transition_predicates(ladder_facts)
    arm_d["ladder"] = ladder_facts
    if fired is not None:
        # D LOCALIZED gate (correction pass 3, blockers 4A/4B/4C):
        # the deterministic side must be CONFIRMED at the frozen
        # count, the variable side mechanically mismatched, the
        # boundary monotone, and the fired predicate source-proven.
        boundary_det, boundary_var = fired["boundary"]
        if not ladder_facts[boundary_det]["deterministic_confirmed"]:
            return _ok(UNRESOLVED, reduction, {
                "reason": (
                    "candidate transition observed but the "
                    "boundary-adjacent deterministic length is only "
                    "pair-identical (screening), not confirmed at the "
                    "frozen deterministic count; the adaptive "
                    "confirmation extension must run before a "
                    "LOCALIZED claim"),
                "ladder": {str(k): {
                    "pair_identical": v["pair_identical"],
                    "deterministic_confirmed":
                        v["deterministic_confirmed"],
                    "actual_token_count": v["actual_token_count"]}
                    for k, v in ladder_facts.items()},
            })
        return _ok(LOCALIZED, reduction, {
            "localized_factor": LOCALIZED_FACTORS["D-context-transition"],
            "arm": "D-context-transition",
            "transition_predicate": fired["predicate"],
            "boundary": fired["boundary"],
            "boundary_actual_tokens": fired["boundary_actual_tokens"],
            "all_cells_max": fired["all_cells_max"],
            "selective_min": fired["selective_min"],
            "mechanism": fired["mechanism"],
        })
    # All reachable arms complete; no causal mechanism bound.
    return _ok(UNRESOLVED, reduction, {
        "reason": "bounded controls reproduce the instability but no "
                  "smallest runtime/execution boundary was mechanically "
                  "bound by the frozen transition predicates",
        "ladder": {str(k): {
            "pair_identical": v["pair_identical"],
            "deterministic_confirmed": v["deterministic_confirmed"],
            "actual_token_count": v["actual_token_count"]}
            for k, v in ladder_facts.items()},
    })
