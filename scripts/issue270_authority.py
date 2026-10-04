#!/usr/bin/env python3
"""Issue #270 (R8-I6) — frozen campaign constants and accepted authority.

Authority-gate scope ONLY: qualify one exact V340L Vega10 die on
inferswarm05 as a comparator/2 physical subject against the accepted
RTX 3060 Vulkan reference on inferswarm01, using the accepted continuous
comparator/2 semantics UNCHANGED and the historical-excluded fixture
ladder ONLY.

Hard prohibitions encoded structurally (each enforced by a validator in
this module or by scripts/issue270_physical.py / issue270_terminal.py):

  * NO predictive calibration / NO ``c237-*`` execution;
  * NO R8-J selected-stress threshold work / NO threshold derivation;
  * NO holdout plaintext/decrypt/secret access / NO holdout
    authorization commit;
  * NO mixed NVIDIA+AMD participant execution inside one request
    (reference and candidate run on SEPARATE hosts, one device each);
  * NO Vulkan RPC serving qualification;
  * NO second V340L die in the correctness comparator;
  * NO coherent-16-GiB / cross-die P2P/coherency claim;
  * NO placement optimization based on numerical agreement;
  * NO resurrection of #241 as active authority;
  * NO generic planner branch on model name, GPU vendor/model, backend
    string, PCIe slot, hostname, or issue ID.

Self-containment: PR #242 (the #241 qualification branch carrying
scripts/issue241_*.py) was closed UNMERGED, so NOTHING may import it.
The accepted comparator/2 semantics are re-declared locally in
scripts/issue270_comparator.py; every accepted SUBJECT identity is
consumed from main-resident authority bytes (scripts/issue250_diagnostic
constants, scripts/issue248_identity, the #243 retained import) and is
cross-verified by tests/test_issue270_authority.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue250_diagnostic as D  # accepted main constants (pin/binaries/model)
import issue250_physical as P  # accepted V0 observer-library identities

# ---------------------------------------------------------------------------
# Campaign identity
# ---------------------------------------------------------------------------
ISSUE = 270
KIND = "R8-I6"
CAMPAIGN_ID = "issue270-r8i6-v340-comparator2"
STARTING_MAIN = "4c6df96cd03e50fbb990256507eb859769536aad"

# Exact dispatch phrase is matched as an exact stripped comment line and
# is never spelled in report prose.
DISPATCH_PHRASE = "R8I6 PHYSICAL DISPATCH #270"
# Bound to the real PR immediately after `gh pr create` (the #250
# precedent: DIAGNOSTIC_PR_NUMBER carried a verified-live comment).
PR_NUMBER: int | None = None

# ---------------------------------------------------------------------------
# Accepted authority consumed (read-only; verified by committed tests)
# ---------------------------------------------------------------------------
ACCEPTED_237_MERGE = "3aa59aed74df7f00302a6a2eb84640623b7cc14b"
ACCEPTED_237_TERMINAL = "R8I_QWEN38_HETEROGENEOUS_VULKAN_METHODOLOGY_FROZEN"
ACCEPTED_237_ACCEPTANCE_COMMENT = 5774946656

ACCEPTED_241_HEAD = "4e8b4fc369defe409f68da46e26d152eade4df47"
ACCEPTED_241_TERMINAL = "R8I3_COMPARATOR_V2_BLOCKED"
ACCEPTED_241_DISPATCH_COMMENT = 5817651663
ACCEPTED_241_ADJUDICATION_COMMENT = 5818984406
ACCEPTED_241_CLOSURE_COMMENT = 5945134855
ACCEPTED_241_EVIDENCE_ROOT = "inferswarm01:/home/hermes/is241-campaign-v3/"
# Decision-report-cited self-digest of the accepted #241 top-level
# SHA256SUMS (356 rows). Historical contrast/precedent only; never a
# live authority for #270 execution.
ACCEPTED_241_MANIFEST_SELF_DIGEST = (
    "78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb")

ACCEPTED_243_TERMINAL = (
    "R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE")
ACCEPTED_243_DECISION_COMMENT = 5803481831
ACCEPTED_243_GO_COMMENT = 5803559861
ACCEPTED_243_CLOSURE_COMMENT = 5803624698

# #239 / R8-J must remain dispatch-blocked; #244 must not gain reachability.
BLOCKED_239_SEQUENCE_COMMENT = 5910516878

R8I4_AREA_REL = "docs/investigations/qwen38-flash-next-r8-i4-v340l-z440"
R8I4_CENSUS_REL = (
    f"{R8I4_AREA_REL}/retained/evidence/phase1/phase1-census.json")
R8I4_CONSTANTS_REL = (
    f"{R8I4_AREA_REL}/retained/producers/issue243_constants.py")
R8I4_README_REL = f"{R8I4_AREA_REL}/README.md"

# ---------------------------------------------------------------------------
# Frozen subject: runtime lineage + model + binaries (main-accepted bytes)
# ---------------------------------------------------------------------------
LLAMA_SOURCE_PIN = D.LLAMA_PIN
ACCEPTED_LLAMA_SOURCE_TREE = D.ACCEPTED_LLAMA_SOURCE_TREE
COMPARATOR_SHA256 = D.SERVER_BINARIES["comparator"]
CANONICAL_SHA256 = D.SERVER_BINARIES["canonical"]
MODEL_DIR = D.MODEL_DIR
MODEL_MEMBERS = D.MODEL_MEMBERS
MODEL_MEMBER_SHA256 = D.MODEL_MEMBER_SHA256
MODEL_MEMBER_1 = D.MODEL_MEMBER_1
REQUEST_CONTRACT = dict(D.REQUEST_CONTRACT)
REQUEST_CONTRACT_KEYS = frozenset(REQUEST_CONTRACT)
CONTEXT_SETTINGS = {"ctx-size": 8192, "batch-size": 512}

N_VOCAB = D.N_VOCAB
ROW_BYTES = D.ROW_BYTES
DECISIONS = D.DECISIONS

# Two-index preflight (accepted #243/#250 two-die law): the fresh
# index->BDF binding is load-only evidence; the canonical die selection
# for the whole campaign is derived by this FROZEN rule from the
# validated record content — never from enumeration order.
TWO_INDEX_RULE = "lexicographically-smallest-selected-bdf-of-validated-two-index-preflight"
BINDING_SCHEMA = "inferswarm.issue270.selector-binding/1"

# Retained observer-library identities of the exact comparator binary
# (accepted #250 V0 OBSERVER_LIBS — the same staged binary on
# inferswarm05 verified by the accepted V0 preflight).
OBSERVER_LIBS = dict(P.V0_OBSERVER_LIBS)

# Historical-excluded fixture ladder (accepted bytes; hash-verified).
FIXTURE_LADDER_REL = D.FIXTURE_LADDER_REL
FIXTURE_LADDER_SHA256 = D.FIXTURE_LADDER_SHA256
# Bounded regimes short/middle/long. case-4096 was NEVER executed by any
# accepted campaign (#241 stopped before it; #248/#250 refused it) and is
# refused outright here: no preauthorization path exists.
FIXTURE_CASES = ("case-256", "case-1024", "case-3072")
PROHIBITED_CASE_PREFIXES = ("c237-", "h237-", "p237-")
PROHIBITED_CASES = ("case-4096",)

# ---------------------------------------------------------------------------
# Frozen selector mechanism (accepted #243/#250 law — never reinvented)
# ---------------------------------------------------------------------------
CANDIDATE_HOST = "inferswarm05"
REFERENCE_HOST = "inferswarm01"
RADV_ICD = "/usr/share/vulkan/icd.d/radeon_icd.json"
NVIDIA_ICD = "/usr/share/vulkan/icd.d/nvidia_icd.json"
SELECTED_PLACEMENT_NGL = 7        # accepted #243 practical placement
BIND_PROBE_NGL = 1                # index->BDF binding probe placement
HBM_RESERVE_BYTES = 1_073_741_824  # accepted #243 1 GiB reserve precedent
EXCLUDED_NOISE_BYTES = 64 * 1024 * 1024  # accepted #243 excluded-die bound
# Accepted #243 measured single-die residency window at ngl=7 under the
# bounded Qwen workload (~6.29-6.32 GiB selected; independently sampled
# excluded die below the noise bound). A live ngl=7 load outside this
# window is material drift from the accepted placement -> STOP before
# acceptance-bearing work.
NGL7_RESIDENCY_MIN_BYTES = 6_000_000_000
NGL7_RESIDENCY_MAX_BYTES = 6_800_000_000

# comparator/2 identity (continuous semantics; supersession chain
# documented in V2_OBSERVER below).
COMPARATOR_V2_ID = "inferswarm.qwen38-vulkan-comparator/2"
V2_OBSERVER = {
    "requests_per_case": 1,
    "decisions": DECISIONS,
    "reference_arm": (
        "one continuous request: consume frozen prompt; capture untouched "
        "full-vocab FP32 row at decision d; choose frozen greedy reference "
        "winner; append it to live state; repeat through 8 decisions"),
    "candidate_arm": (
        "one continuous request: consume identical prompt; capture "
        "untouched full-vocab FP32 row at decision d; record candidate "
        "winner; AFTER row capture force/append the REFERENCE token for "
        "decision d; continue live state to d+1; repeat through 8 "
        "decisions"),
    "capture_before_force": (
        "source-order proof required: row capture occurs before "
        "reference-token forcing at every decision"),
    "authority_gate_only": (
        "#270 establishes physical comparator/2 authority for a future "
        "maintainer decision; it performs no predictive calibration, "
        "derives no threshold, and grants no R8-J execution"),
}

# ---------------------------------------------------------------------------
# Reference arm (accepted #248 identity — consumed, never re-frozen).
# Fresh binding at execution time is mandatory; these constants are the
# comparison target for the fresh raw observation.
# ---------------------------------------------------------------------------
REFERENCE_IDENTITY_FIELDS = (
    "host", "gpu_uuid", "bdf", "pci_id", "subsystem_vendor_id",
    "subsystem_device_id", "revision", "negotiated_width", "max_width",
    "max_link_speed_capability", "kernel_driver", "nvidia_driver", "icd",
    "vulkan_device_name", "vulkan_device_uuid", "vulkan_api",
    "vulkan_driver", "selector",
)


def reference_identity() -> dict[str, Any]:
    """Accepted RTX 3060 reference identity (issue248 — read-only copy)."""
    import issue248_identity as I
    frozen = I.frozen_identity("B")
    missing = [f for f in REFERENCE_IDENTITY_FIELDS if f not in frozen]
    if missing:
        raise RuntimeError(
            f"accepted reference identity incomplete: {missing}")
    return {f: frozen[f] for f in REFERENCE_IDENTITY_FIELDS}


# ---------------------------------------------------------------------------
# Candidate arm: V340L identity DERIVED from the retained #243 census
# bytes on main (never transcribed by hand into production constants).
# ---------------------------------------------------------------------------
DIE_BDFS = ("0000:07:00.0", "0000:0b:00.0")  # #243 two-die census order
EXPECTED_CANDIDATE = {
    "host": CANDIDATE_HOST,
    "vendor_id": "0x1002",
    "device_id": "0x6864",
    "subsystem_vendor_id": "0x1002",
    "subsystem_device_id": "0x0c00",
    "revision": "0x05",
    "vram_total_bytes": 8_573_157_376,
    "max_link_speed": "8.0 GT/s PCIe",
    "max_link_width": "16",
    "vulkan_device_name": "AMD Radeon Pro V340 (RADV VEGA10)",
    "vulkan_driver_id": "DRIVER_ID_MESA_RADV",
    "vulkan_driver_info": "Mesa 25.0.7-2+deb13u1",
    "vulkan_api_version": "1.4.305",
    "vulkan_instance": "1.4.309",
    "kernel": "6.12.107+deb13-amd64",
    "baseboard_product": "212B",
    "min_dram_bytes": 134_985_306_112,
}
EXPECTED_VULKAN_DEVICE_UUIDS = {
    "0000:07:00.0": "00000000-0700-0000-0000-000000000000",
    "0000:0b:00.0": "00000000-0b00-0000-0000-000000000000",
}

# Enumerated Vulkan device indices are NEVER assumed: the fresh
# index->BDF binding comes from per-die load-only VRAM-delta probes
# (accepted #243 law; #250 V0 two-index preflight shape).
LLAMA_VK_SELECTOR_ENV = "GGML_VK_VISIBLE_DEVICES"
CUDA_EXCLUDE_ENV = "CUDA_VISIBLE_DEVICES"


class AuthorityError(RuntimeError):
    """Raised when accepted authority cannot be consumed mechanically."""


def _census(path: Path | None = None) -> dict[str, Any]:
    census_path = Path(path) if path else ROOT / R8I4_CENSUS_REL
    if census_path.is_symlink() or not census_path.is_file():
        raise AuthorityError(f"#243 retained census missing: {census_path}")
    try:
        doc = json.loads(census_path.read_bytes())
    except (ValueError, OSError) as exc:
        raise AuthorityError(f"#243 census unreadable: {exc}") from exc
    if doc.get("schema") != "inferswarm.issue243.census/1":
        raise AuthorityError("#243 census schema mismatch")
    if doc.get("campaign") != "issue243-r8i4-v340l-z440-characterization":
        raise AuthorityError("#243 census campaign mismatch")
    return doc


def candidate_identity_from_census(
        census_path: Path | None = None) -> dict[str, Any]:
    """Derive the frozen V340L candidate identity from retained bytes.

    Every consumed field is parsed out of the accepted #243 phase-1
    census document; a malformed or missing source fails closed. The
    result must equal EXPECTED_CANDIDATE (double lock: retained bytes
    AND the independently transcribed expectation), enforced by
    validate_candidate_authority — production never trusts a single
    transcription.
    """
    doc = _census(census_path)
    dies = doc.get("dies")
    if not isinstance(dies, dict) or set(dies) != {"card1", "card2"}:
        raise AuthorityError("#243 census dies malformed")
    by_bdf: dict[str, dict[str, Any]] = {}
    for card, entry in dies.items():
        if not isinstance(entry, dict):
            raise AuthorityError("#243 census die entry malformed")
        bdf = entry.get("bdf")
        if bdf not in DIE_BDFS:
            raise AuthorityError(f"#243 census unexpected die BDF: {bdf!r}")
        by_bdf[bdf] = entry
    if set(by_bdf) != set(DIE_BDFS):
        raise AuthorityError("#243 census does not cover both dies")
    host = doc.get("host") or {}
    if host.get("hostname") != CANDIDATE_HOST:
        raise AuthorityError("#243 census hostname mismatch")
    baseboard = str(host.get("baseboard", ""))
    if EXPECTED_CANDIDATE["baseboard_product"] not in baseboard:
        raise AuthorityError("#243 census baseboard mismatch")
    card1 = by_bdf[DIE_BDFS[0]]
    derived: dict[str, Any] = {
        "host": CANDIDATE_HOST,
        "vendor_id": card1.get("vendor"),
        "device_id": card1.get("device"),
        "subsystem_vendor_id": card1.get("subsystem_vendor"),
        "subsystem_device_id": card1.get("subsystem_device"),
        "revision": card1.get("revision"),
        "vram_total_bytes": int(card1["mem_info_vram_total"]),
        "max_link_speed": card1.get("max_link_speed"),
        "max_link_width": card1.get("max_link_width"),
    }
    missing = [k for k, v in derived.items() if v in (None, "")]
    if missing:
        raise AuthorityError(f"#243 census lacks fields: {missing}")
    for bdf in DIE_BDFS:
        entry = by_bdf[bdf]
        for field in ("mem_info_vram_total",):
            if int(entry[field]) != EXPECTED_CANDIDATE["vram_total_bytes"]:
                raise AuthorityError(
                    f"#243 census {bdf} {field} mismatch vs accepted import")
    vulkan = doc.get("vulkan") or {}
    summary = str(vulkan.get("summary", ""))
    parsed = _parse_census_vulkan_summary(summary)
    derived["vulkan_instance"] = parsed["instance"]
    derived["vulkan_api_version"] = parsed["devices"][DIE_BDFS[0]]["apiVersion"]
    derived["vulkan_device_name"] = parsed["devices"][DIE_BDFS[0]]["deviceName"]
    derived["vulkan_driver_id"] = parsed["devices"][DIE_BDFS[0]]["driverID"]
    derived["vulkan_driver_info"] = parsed["devices"][DIE_BDFS[0]]["driverInfo"]
    uname = str(host.get("uname", ""))
    m = re.search(r"Linux \S+ (\S+)", uname)
    derived["kernel"] = m.group(1) if m else None
    # Baseboard product derives from the dmidecode capture (board 212B).
    baseboard_text = str(host.get("baseboard", ""))
    bm = re.search(r"Product Name:\s*(\S+)", baseboard_text)
    derived["baseboard_product"] = bm.group(1) if bm else None
    derived["dies"] = {
        bdf: {
            "vulkan_device_uuid":
                parsed["devices"][bdf]["deviceUUID"],
            "vram_total_bytes": int(by_bdf[bdf]["mem_info_vram_total"]),
        }
        for bdf in DIE_BDFS
    }
    return derived


def _census_dram_bytes(doc: dict[str, Any]) -> int | None:
    """Retained host DRAM total from the census meminfo capture."""
    meminfo = str((doc.get("host") or {}).get("meminfo", ""))
    m = re.search(r"MemTotal:\s+(\d+)\s+kB", meminfo)
    return int(m.group(1)) * 1024 if m else None


def _parse_census_vulkan_summary(text: str) -> dict[str, Any]:
    """Parse the retained census vulkaninfo summary (all device blocks)."""
    if "VULKANINFO" not in text or "Vulkan Instance Version" not in text:
        raise AuthorityError("census vulkaninfo lacks its header")
    m = re.search(r"Vulkan Instance Version:\s*(\S+)", text)
    if not m:
        raise AuthorityError("census vulkaninfo instance version missing")
    devices: dict[str, dict[str, str]] = {}
    for block in re.split(r"^GPU\d+:\s*$", text, flags=re.MULTILINE)[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            fm = re.fullmatch(r"\s*(\w+)\s+=\s+(.+?)\s*", line)
            if fm:
                fields[fm.group(1)] = fm.group(2)
        uuid = fields.get("deviceUUID")
        if not uuid:
            continue  # llvmpipe-style CPU device without a die UUID
        bdf = _bdf_from_radv_uuid(uuid)
        if bdf is None:
            continue
        devices[bdf] = fields
    if set(devices) != set(DIE_BDFS):
        raise AuthorityError(
            f"census vulkaninfo die blocks malformed: {sorted(devices)}")
    return {"instance": m.group(1), "devices": devices}


def _bdf_from_radv_uuid(uuid: str) -> str | None:
    """RADV Vega10 deviceUUID encodes the BDF (accepted #241/#243 law)."""
    m = re.fullmatch(r"00000000-([0-9a-f]{4})-0000-0000-000000000000", uuid)
    if not m:
        return None
    bus = m.group(1)[:2]
    slot = m.group(1)[2:]
    try:
        int(bus, 16)
        int(slot, 16)
    except ValueError:
        return None
    return f"0000:{bus}:{slot}.0"


def validate_candidate_authority(census_path: Path | None = None) -> dict[str, Any]:
    """Retained-bytes derivation must equal the transcribed expectation."""
    derived = candidate_identity_from_census(census_path)
    for key, want in EXPECTED_CANDIDATE.items():
        if key in ("min_dram_bytes",):
            continue
        got = derived.get(key)
        if got != want:
            raise AuthorityError(
                f"#243-derived candidate {key}: {got!r} != expected {want!r}")
    dram = _census_dram_bytes(_census(census_path))
    if dram is None or dram < EXPECTED_CANDIDATE["min_dram_bytes"]:
        raise AuthorityError("#243 census DRAM total missing/below accepted")
    if (set(derived["dies"]) != set(DIE_BDFS)
            or derived["dies"][DIE_BDFS[0]]["vulkan_device_uuid"]
            != EXPECTED_VULKAN_DEVICE_UUIDS[DIE_BDFS[0]]
            or derived["dies"][DIE_BDFS[1]]["vulkan_device_uuid"]
            != EXPECTED_VULKAN_DEVICE_UUIDS[DIE_BDFS[1]]):
        raise AuthorityError("#243-derived die UUID binding mismatch")
    return derived


# ---------------------------------------------------------------------------
# Namespace / case discipline
# ---------------------------------------------------------------------------
CAMPAIGN_NAMESPACE_RE = re.compile(r"^c270-[a-z0-9][a-z0-9-]*[a-z0-9]$")
FORBIDDEN_NAMESPACE_SUBSTRINGS = (
    "c237-", "h237-", "p237-",      # predictive / holdout namespaces
    "threshold", "calibration",      # prohibited work products
    "holdout",
)
CASE_RE = re.compile(r"^case-(256|1024|3072)$")


def validate_namespace(namespace: str) -> str:
    if not isinstance(namespace, str) or not CAMPAIGN_NAMESPACE_RE.fullmatch(
            namespace):
        raise AuthorityError(f"invalid campaign namespace: {namespace!r}")
    for bad in FORBIDDEN_NAMESPACE_SUBSTRINGS:
        if bad in namespace:
            raise AuthorityError(
                f"forbidden namespace substring {bad!r} in {namespace!r}")
    return namespace


def validate_case(case_id: str) -> str:
    """Historical-excluded fixtures ONLY (fail closed on everything else)."""
    if not isinstance(case_id, str) or CASE_RE.fullmatch(case_id) is None:
        raise AuthorityError(
            f"case {case_id!r} is not an authorized historical-excluded "
            "fixture (case-4096 and every predictive namespace are "
            "prohibited outright)")
    for pref in PROHIBITED_CASE_PREFIXES:
        if case_id.startswith(pref):
            raise AuthorityError(
                f"predictive case namespace {pref!r} is prohibited")
    return case_id


def load_fixtures(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and hash-verify the accepted historical excluded ladder."""
    root = Path(repo_root) if repo_root else ROOT
    p = root / FIXTURE_LADDER_REL
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FIXTURE_LADDER_SHA256:
        raise AuthorityError(
            f"fixture ladder sha256 drift: {digest} != "
            f"{FIXTURE_LADDER_SHA256}")
    doc = json.loads(data)
    cases = {c["case_id"]: c for c in doc["cases"]}
    missing = [c for c in FIXTURE_CASES if c not in cases]
    if missing:
        raise AuthorityError(f"fixture cases missing: {missing}")
    return {c: cases[c] for c in FIXTURE_CASES}


# ---------------------------------------------------------------------------
# Terminal vocabulary (exact; one terminal per execution)
# ---------------------------------------------------------------------------
TERMINAL_PASS = "R8I6_V340_COMPARATOR2_PHYSICAL_AUTHORITY_PASS"
TERMINAL_INFRASTRUCTURE_BLOCKED = (
    "R8I6_V340_COMPARATOR2_INFRASTRUCTURE_BLOCKED")
TERMINAL_RUNTIME_BLOCKED = "R8I6_V340_COMPARATOR2_RUNTIME_BLOCKED"
TERMINAL_AUTHORITY_BLOCKED = "R8I6_V340_COMPARATOR2_AUTHORITY_BLOCKED"
REDUCER_BLOCKED_INCOMPLETE = "R8I6_REDUCER_BLOCKED_INCOMPLETE"
TERMINALS = (
    TERMINAL_PASS, TERMINAL_INFRASTRUCTURE_BLOCKED,
    TERMINAL_RUNTIME_BLOCKED, TERMINAL_AUTHORITY_BLOCKED,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def authority_digest(doc: Any) -> str:
    """Canonical digest over any authority/record object."""
    return sha256_bytes(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
