#!/usr/bin/env python3
"""Issue #273 (R8-I6A) — corrected comparator/2 admission law.

The accepted #270 reducer admitted a reduction whose staged "reference"
receipts were relabeled V340L runs (radeon ICD, VK device 0, executed on
inferswarm05; rows byte-identical to the candidate arm). Root cause, in
increasing order of severity:

  1. ``issue270_comparator`` pinned ONE placement (``SELECTED_PLACEMENT_NGL
     == 7``) for BOTH arms and additionally required reference ngl ==
     candidate ngl; the physically accepted reference placement is 8.
  2. Arm identity was admitted from receipt LABELS (host/bdf/icd/
     subject_identity fields) that the executor writes; the process
     attribution (ICD, selector env, argv) — the only part bound to the
     real execution — was never cross-checked against them, so a
     candidate process could be relabeled reference.
  3. Staged receipts had no immutable binding to the ORIGINAL source run
     receipt captured before staging, so identity-bearing fields could
     be rewritten after capture without breaking admission.
  4. Nothing refused cross-arm evidence aliasing (the same underlying
     run/row bytes serving both arms).

This module enforces the corrected invariants WITHOUT redefining the
accepted comparator/2 semantics, the frozen #243/#248 subject law, the
fixture ladder, or the historical #270 evidence (which stays historical
— nothing here reclassifies it as valid):

  * per-arm placement contract: reference ngl=8, candidate ngl=7
    (ARM_PLACEMENT; a single shared ngl rule is invalid);
  * arm identity derived from trustworthy process/device/backend
    evidence: the reference arm's process attribution MUST resolve to
    the NVIDIA ICD, the candidate arm's to the RADV ICD — mutually
    exclusive — and the ICD/selector/env facts may not contradict the
    claimed arm, host, or BDF;
  * immutable staged->source binding: every staged receipt carries a
    ``source_run`` block (path + digest of the ORIGINAL pre-staging run
    receipt), plus per-row source digests; the staged receipt's
    identity-bearing fields must equal the source receipt's — writable
    labels cannot override source attribution;
  * distinct provenance objects per arm: server pid, argv, and row-byte
    digests must differ across arms where they must be distinct
    physical executions; no cross-arm aliasing of raw rows or receipts;
  * per-arm deterministic-repeat admission BEFORE pair comparison;
  * fail-closed everywhere; no numerical agreement influences any
    evidence-selection decision.

Offline and injectable: pure functions over dicts/bytes, no I/O of its
own beyond optional hashing helpers. Physical execution remains gated
on maintainer dispatch at the merged corrective head.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

import issue270_authority as C

SCHEMA = "inferswarm.issue273.corrective-admission/1"
STAGED_SOURCE_SCHEMA = "inferswarm.issue273.staged-source-binding/1"

Digest64_RE = re.compile(r"^[0-9a-f]{64}$")

# Per-arm placement contract (#273): the reference arm's accepted
# placement on the RTX 3060 is ngl=8 (~7.66 GiB); the candidate arm's
# accepted #243 placement on one V340L die is ngl=7. A single shared
# ngl rule is INVALID (the #270 defect).
REFERENCE_PLACEMENT_NGL = 8
CANDIDATE_PLACEMENT_NGL = 7
ARM_PLACEMENT = {"reference": REFERENCE_PLACEMENT_NGL,
                 "candidate": CANDIDATE_PLACEMENT_NGL}

# Arm -> required Vulkan ICD. Mutually exclusive by construction: the
# reference resolves through the NVIDIA ICD only, the candidate through
# the RADV ICD only. A process attributed to the wrong ICD can never
# satisfy the claimed arm.
ARM_ICD = {"reference": C.NVIDIA_ICD, "candidate": C.RADV_ICD}

# Arm -> required host (frozen #248/#243 law, re-bound fresh at run).
ARM_HOST = {"reference": C.REFERENCE_HOST, "candidate": C.CANDIDATE_HOST}

# Fields on a staged receipt that are IDENTITY-BEARING: after capture
# they must equal the source run receipt's fields byte-for-byte. This
# is what makes post-capture relabeling mechanically impossible.
IDENTITY_FIELDS = (
    "arm", "host", "bdf", "icd", "selector", "cuda_visible_devices",
    "ngl", "subject_identity", "process_attribution",
)

# Fields that must DIFFER between the two arms' receipts because they
# are distinct physical executions on distinct hosts (a same-value here
# means the same underlying run is serving both arms).
DISTINCT_PROVENANCE_FIELDS = (
    "server_pid",           # process_attribution.server_pid
    "server_argv",          # process_attribution.server_argv
)


class AdmissionError(RuntimeError):
    """Raised by hard-fail admission helpers (fail-closed law)."""


def expected_placement(arm: str) -> int:
    """Per-arm frozen placement; unknown arms fail closed."""
    try:
        return ARM_PLACEMENT[arm]
    except KeyError:
        raise AdmissionError(f"unknown arm {arm!r}") from None


def expected_icd(arm: str) -> str:
    try:
        return ARM_ICD[arm]
    except KeyError:
        raise AdmissionError(f"unknown arm {arm!r}") from None


def expected_host(arm: str) -> str:
    try:
        return ARM_HOST[arm]
    except KeyError:
        raise AdmissionError(f"unknown arm {arm!r}") from None


# ---------------------------------------------------------------------------
# Process-attribution law (trustworthy identity)
# ---------------------------------------------------------------------------

def process_attribution_problems(receipt: dict[str, Any], arm: str,
                                 ) -> list[str]:
    """Derive the arm's trustworthy identity from process attribution.

    The claimed labels (host/bdf/icd) are CLAIMS; the process env /
    argv are the execution facts. Admission requires the facts to
    resolve to the claimed arm:

      * server_env VK_ICD_FILENAMES == the arm's REQUIRED ICD;
      * server_env selector (GGML_VK_VISIBLE_DEVICES) present and an
        int-string; GGML_VK_VISIBLE_DEVICES may not select a device on
        a DIFFERENT host's enumeration (cross-host substitution);
      * server_argv binds the frozen model subject and -ngl == the
        ARM-SPECIFIC placement;
      * CUDA fenced off (cuda_visible_devices == "-1" in env and top
        level);
      * the process host (server_env INFERSWARM_HOST, when the
        producer captures it) must equal the arm's required host.
    """
    problems: list[str] = []
    pa = receipt.get("process_attribution")
    if not isinstance(pa, dict):
        return [f"{arm}: process attribution missing"]
    env = pa.get("server_env") or {}
    if not isinstance(env, dict):
        return [f"{arm}: server_env malformed"]
    want_icd = expected_icd(arm)
    if env.get("VK_ICD_FILENAMES") != want_icd:
        problems.append(
            f"{arm}: process ICD {env.get('VK_ICD_FILENAMES')!r} != "
            f"required arm ICD {want_icd!r} — claimed arm contradicts "
            f"the executed backend")
    if receipt.get("icd") != want_icd:
        problems.append(
            f"{arm}: receipt icd label {receipt.get('icd')!r} != "
            f"required arm ICD {want_icd!r}")
    if receipt.get("cuda_visible_devices") != "-1":
        problems.append(f"{arm}: CUDA not fenced off at top level")
    if env.get("CUDA_VISIBLE_DEVICES") != "-1":
        problems.append(f"{arm}: CUDA not fenced off in process env")
    selector = env.get("GGML_VK_VISIBLE_DEVICES")
    if (not isinstance(selector, str)
            or re.fullmatch(r"[0-9]+", selector) is None):
        problems.append(
            f"{arm}: GGML_VK_VISIBLE_DEVICES missing/non-numeric in "
            f"process env")
    proc_host = env.get("INFERSWARM_HOST")
    if proc_host is None:
        problems.append(
            f"{arm}: process host observation (INFERSWARM_HOST) missing "
            f"— admission requires the executor-recorded host fact")
    elif proc_host != expected_host(arm):
        problems.append(
            f"{arm}: process host {proc_host!r} != required arm host "
            f"{expected_host(arm)!r}")
    if receipt.get("host") != expected_host(arm):
        problems.append(
            f"{arm}: receipt host label {receipt.get('host')!r} != "
            f"required {expected_host(arm)!r}")
    bdf = receipt.get("bdf")
    if arm == "reference":
        # The accepted #248 reference BDF (domain-wide form).
        if bdf != "00000000:03:00.0":
            problems.append(
                f"reference: bdf {bdf!r} != accepted #248 reference "
                f"placement 00000000:03:00.0")
    elif bdf not in C.DIE_BDFS:
        problems.append(
            f"candidate: bdf {bdf!r} not in the frozen V340 die set "
            f"{C.DIE_BDFS}")
    # argv: model binding + arm-specific placement
    argv = pa.get("server_argv")
    if not isinstance(argv, list) or not argv:
        problems.append(f"{arm}: server argv missing")
        return problems
    argv_s = [str(a) for a in argv]
    if not any(str(C.MODEL_DIR) in a for a in argv_s):
        problems.append(f"{arm}: argv does not bind the frozen model")
    want_ngl = expected_placement(arm)
    if "-ngl" in argv_s:
        i = argv_s.index("-ngl")
        if i + 1 >= len(argv_s) or argv_s[i + 1] != str(want_ngl):
            problems.append(
                f"{arm}: argv -ngl != arm placement {want_ngl}")
    else:
        problems.append(f"{arm}: argv lacks -ngl")
    if receipt.get("ngl") != want_ngl:
        problems.append(
            f"{arm}: receipt ngl {receipt.get('ngl')!r} != arm "
            f"placement {want_ngl} (per-arm contract; the shared ngl==7 "
            f"rule of #270 was invalid)")
    pid = pa.get("server_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        problems.append(f"{arm}: server pid missing/invalid")
    return problems


# ---------------------------------------------------------------------------
# Staged -> source immutable binding
# ---------------------------------------------------------------------------

def _digest_ok(value: Any) -> bool:
    return isinstance(value, str) and Digest64_RE.fullmatch(value) is not None


def staged_source_problems(staged: dict[str, Any], source: dict[str, Any],
                           ) -> list[str]:
    """Bind a staged receipt immutably to its ORIGINAL source run receipt.

    The staged receipt must carry ``staged_source`` = {schema, path,
    receipt_sha256, row_digests}; the source digest must be well-formed;
    and every IDENTITY field must be IDENTICAL between staged and
    source. A staged receipt that rewrote host/BDF/ICD/selector/ngl/
    subject_identity/process_attribution relative to the source is
    REJECTED — identity cannot be minted at staging time.
    """
    problems: list[str] = []
    binding = staged.get("staged_source")
    if not isinstance(binding, dict) \
            or binding.get("schema") != STAGED_SOURCE_SCHEMA:
        return ["staged receipt lacks the immutable staged-source binding"]
    path = binding.get("path")
    if not isinstance(path, str) or not path:
        problems.append("staged-source path missing")
    if not _digest_ok(binding.get("receipt_sha256")):
        problems.append("staged-source receipt digest malformed")
    rows = binding.get("row_digests")
    if not isinstance(rows, dict) or not rows:
        problems.append("staged-source row digests missing")
    else:
        for d, digest in sorted(rows.items()):
            if not _digest_ok(digest):
                problems.append(f"staged-source row {d} digest malformed")
    # Identity fields are immutable across staging.
    for field in IDENTITY_FIELDS:
        if staged.get(field) != source.get(field):
            problems.append(
                f"staged receipt rewrote identity field {field!r} "
                f"relative to the source run receipt — post-capture "
                f"relabeling rejected")
    # The staged receipt's claimed row digests must equal the source's
    # for every decision the source carries.
    staged_rows = staged.get("rows") or {}
    source_rows = source.get("rows") or {}
    for d in sorted(set(staged_rows) & set(source_rows)):
        if staged_rows[d].get("sha256") != source_rows[d].get("sha256"):
            problems.append(
                f"staged row {d} digest != source row digest — row bytes "
                f"substituted at staging")
    return problems


def bind_staged_source(source_receipt: dict[str, Any], rel_path: str,
                       receipt_digest: str, row_digests: dict[str, str],
                       ) -> dict[str, Any]:
    """Producer helper: build the immutable staged-source binding block."""
    return {
        "schema": STAGED_SOURCE_SCHEMA,
        "path": rel_path,
        "receipt_sha256": receipt_digest,
        "row_digests": dict(row_digests),
    }


def source_digest_problems(staged: dict[str, Any],
                           computed_source_digest: str,
                           computed_row_digests: dict[str, str],
                           ) -> list[str]:
    """The staged binding's digests must equal digests computed NOW from
    the retained source bytes — not from the staged receipt's claims."""
    problems: list[str] = []
    binding = staged.get("staged_source") or {}
    if binding.get("receipt_sha256") != computed_source_digest:
        problems.append(
            "staged-source receipt digest != independently computed "
            "digest of the source run receipt")
    bound_rows = binding.get("row_digests") or {}
    for d in sorted(set(bound_rows) | set(computed_row_digests)):
        want = computed_row_digests.get(d)
        got = bound_rows.get(d)
        if want != got:
            problems.append(
                f"staged-source row {d} digest != independently computed "
                f"source row digest")
    return problems


# ---------------------------------------------------------------------------
# Cross-arm anti-aliasing + provenance distinctness
# ---------------------------------------------------------------------------

def cross_arm_problems(reference: dict[str, Any],
                       candidate: dict[str, Any],
                       ) -> list[str]:
    """No cross-arm aliasing; distinct physical executions.

      * reference and candidate receipts must be distinct provenance
        objects (different server pids/argv — different processes);
      * no raw row bytes may alias: the per-decision row digests must
        differ across arms (identical full-vocab FP32 rows from two
        different vendors' silicon at the same decisions is the #270
        substitution signature);
      * arms must not share the same staged-source run (receipt digest).
    """
    problems: list[str] = []
    ref_pa = reference.get("process_attribution") or {}
    cand_pa = candidate.get("process_attribution") or {}
    for field in DISTINCT_PROVENANCE_FIELDS:
        if ref_pa.get(field) == cand_pa.get(field):
            problems.append(
                f"reference/candidate share the same {field} — not "
                f"distinct physical executions")
    ref_rows = reference.get("rows") or {}
    cand_rows = candidate.get("rows") or {}
    for d in sorted(set(ref_rows) & set(cand_rows)):
        if ref_rows[d].get("sha256") == cand_rows[d].get("sha256"):
            problems.append(
                f"row {d} byte-aliasing across arms — identical row "
                f"digest for reference and candidate (the #270 "
                f"substitution signature)")
    ref_src = (reference.get("staged_source") or {}).get("receipt_sha256")
    cand_src = (candidate.get("staged_source") or {}).get("receipt_sha256")
    if ref_src is not None and ref_src == cand_src:
        problems.append(
            "reference/candidate staged evidence binds the SAME source "
            "run — cross-arm evidence aliasing")
    # Backend exclusivity is implied by ARM_ICD but double-checked here
    # so a future edit to one surface cannot silently decouple them.
    if reference.get("icd") == candidate.get("icd"):
        problems.append(
            "reference/candidate ICDs identical — the NVIDIA/RADV "
            "backend pair must be mutually exclusive")
    return problems


# ---------------------------------------------------------------------------
# Whole-admission entry point
# ---------------------------------------------------------------------------

def admission_problems(staged: dict[str, Any], arm: str,
                       source: dict[str, Any],
                       source_receipt_digest: str | None = None,
                       source_row_digests: dict[str, str] | None = None,
                       ) -> list[str]:
    """All admission checks for one staged arm receipt.

    When the independently computed source digests are supplied (they
    are computed by the caller from RETAINED SOURCE BYTES, never taken
    from the staged receipt's claims), the staged binding's digest
    chain is authenticated too; omitting them fails closed.
    """
    if staged.get("arm") != arm:
        return [f"arm mismatch: {staged.get('arm')!r} != {arm!r}"]
    problems = (process_attribution_problems(staged, arm)
                + staged_source_problems(staged, source))
    if source_receipt_digest is None or source_row_digests is None:
        problems.append(
            f"{arm}: independently computed source digests not supplied "
            f"— digest-chain authentication fails closed")
    else:
        problems += source_digest_problems(
            staged, source_receipt_digest, source_row_digests)
    return problems


def admit_pair(reference: dict[str, Any], reference_source: dict[str, Any],
               candidate: dict[str, Any], candidate_source: dict[str, Any],
               reference_repeat: dict[str, Any],
               candidate_repeat: dict[str, Any],
               reference_deterministic: bool | None = None,
               candidate_deterministic: bool | None = None,
               reference_source_digest: str | None = None,
               reference_source_row_digests: dict[str, str] | None = None,
               candidate_source_digest: str | None = None,
               candidate_source_row_digests: dict[str, str] | None = None,
               ) -> dict[str, Any]:
    """Full corrected admission over one case's staged evidence.

    Deterministic-repeat admission is PER ARM and precedes the pair
    comparison: a reference primary/repeat mismatch is terminally
    rejected before any cross-vendor comparison happens. The
    determinism verdicts come from ``comparator.validate_determinism``
    (independently computed row-byte digests — never two claimed
    strings); admission consumes the verdict, never re-derives it from
    claims. ``None`` means "not yet computed" and fails closed.
    """
    problems: list[str] = []
    for label, rep in (("reference", reference_repeat),
                       ("candidate", candidate_repeat)):
        if not isinstance(rep, dict):
            problems.append(
                f"{label} repeat receipt missing — admission fails closed")
    if problems:
        return {"schema": SCHEMA,
                "case_id": reference.get("case_id"),
                "admitted": False, "problems": problems}
    problems += [f"reference: {p}"
                 for p in admission_problems(
                     reference, "reference", reference_source,
                     reference_source_digest,
                     reference_source_row_digests)]
    problems += [f"candidate: {p}"
                 for p in admission_problems(
                     candidate, "candidate", candidate_source,
                     candidate_source_digest,
                     candidate_source_row_digests)]
    # Repeats must be the same arm/host/backend as their primary and
    # carry their own staged-source binding.
    for label, prim, rep, src in (
            ("reference", reference, reference_repeat, reference_source),
            ("candidate", candidate, candidate_repeat, candidate_source)):
        if rep.get("arm") != label:
            problems.append(f"{label} repeat arm mismatch")
        if rep.get("host") != prim.get("host") or \
                rep.get("icd") != prim.get("icd") or \
                rep.get("ngl") != prim.get("ngl"):
            problems.append(
                f"{label} repeat host/ICD/ngl != its primary — repeat "
                f"must be the same arm placement")
        rep_src = rep.get("staged_source") or {}
        if rep_src.get("schema") != STAGED_SOURCE_SCHEMA:
            problems.append(
                f"{label} repeat lacks the staged-source binding")
        # A repeat is a distinct process: pid must differ from primary.
        rep_pid = (rep.get("process_attribution") or {}).get("server_pid")
        prim_pid = (prim.get("process_attribution") or {}).get("server_pid")
        if rep_pid == prim_pid:
            problems.append(
                f"{label} repeat shares the primary's server pid — not a "
                f"fresh process")
        # Cross-arm aliasing between a repeat and the OTHER arm.
        other = candidate if label == "reference" else reference
        rep_rows = rep.get("rows") or {}
        other_rows = other.get("rows") or {}
        for d in sorted(set(rep_rows) & set(other_rows)):
            if rep_rows[d].get("sha256") == other_rows[d].get("sha256"):
                problems.append(
                    f"{label} repeat row {d} aliases the other arm's row")
    problems += cross_arm_problems(reference, candidate)
    # Per-arm deterministic-repeat admission gates the PAIR comparison:
    # the reference verdict is consumed FIRST; a None (not computed)
    # fails closed — the pair can never admit on unproven determinism.
    if reference_deterministic is not True:
        problems.append(
            "reference primary/repeat determinism not proven — pair "
            "comparison refused (per-arm determinism precedes "
            "cross-vendor comparison)")
    if candidate_deterministic is not True:
        problems.append(
            "candidate primary/repeat determinism not proven — pair "
            "comparison refused (per-arm determinism precedes "
            "cross-vendor comparison)")
    return {
        "schema": SCHEMA,
        "case_id": reference.get("case_id"),
        "admitted": not problems,
        "problems": problems,
    }
