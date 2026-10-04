#!/usr/bin/env python3
"""Issue #270 (R8-I6) — physical authority-gate producer and terminal reducer.

PHASE STRUCTURE (Issue #270; physical work is bounded to
historical-excluded comparator/2 authority observations):

  Phase 0  authority + repository reconciliation (repo checks; this
           module's phase0_reconciliation entrypoint plus
           tests/test_issue270_authority.py).
  Phase 1  durable subject/tooling freeze — the frozen-freeze record
           (append-only) binds every identity BEFORE any acceptance-
           bearing observation.
  Phase 2  platform/placement preflight — fresh host identity, fresh
           two-index load-only selector binding (accepted #243 law),
           ngl=7 bounded-residency proof, second-die exclusion, CUDA
           absence, observer inertness at load.
  Phase 3  historical-excluded comparator/2 execution — bounded fixture
           set {case-256, case-1024, case-3072}; per case: reference
           continuous run + repeat, candidate continuous run + repeat,
           observer-disabled/canonical inertness controls; exactly 8
           decisions and 8+8 rows per unit.
  Phase 4  validation — the retained-byte reducer (derive_terminal)
           derives the SINGLE terminal mechanically; numerical deltas
           are retained as diagnostics; NO threshold is derived.

Every entrypoint gates FIRST: live exact-head maintainer dispatch
(OWNER/MEMBER top-level PR comment; phrase + head= + namespace=),
exact clean local head, frozen subject/tooling identities. There is NO
authority parameter anywhere.

Hard prohibitions are structurally enforced (see issue270_authority):
no predictive calibration, no c237-* execution, no threshold
derivation, no holdout access, no second-die participation, no
mixed-vendor single request, no placement optimization, no #241
resurrection, no generic planner policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import issue270_authority as C
import issue270_comparator as comparator

EVIDENCE_SCHEMA = "inferswarm.issue270.evidence-root/1"
FREEZE_SCHEMA = "inferswarm.issue270.subject-freeze/1"
PREFLIGHT_SCHEMA = "inferswarm.issue270.phase2-preflight/1"
UNIT_SCHEMA = "inferswarm.issue270.unit/1"
REDUCTION_SCHEMA = "inferswarm.issue270.reduction/1"
TERMINAL_SCHEMA = "inferswarm.issue270.terminal/1"

FREEZE_NAME = "issue270-subject-freeze.json"
BINDING_NAME = "selector-binding.json"
PREFLIGHT_NAME = "phase2-preflight.json"
REDUCTION_NAME = "reduction.json"
TERMINAL_NAME = "TERMINAL.json"


SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class PhysicalError(RuntimeError):
    pass


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Live dispatch authority (no authority parameter exists)
# ---------------------------------------------------------------------------

def fetch_dispatch_authority(repo_root: Path, expected_head: str, namespace: str,
                             revalidate_authority: Callable[..., Any] | None = None,
                             github_api: str = "https://api.github.com"
                             ) -> dict[str, Any]:
    """Live exact-head maintainer dispatch for THIS campaign.

    Production performs live GitHub API requests; tests inject
    ``revalidate_authority``. An OWNER/MEMBER top-level PR/issue
    conversation comment carrying the exact dispatch phrase, the exact
    head SHA and the campaign namespace as exact stripped lines
    authorizes execution; anything else (stale head, wrong namespace,
    wrong association) fails closed.
    """
    if revalidate_authority is not None:
        doc = revalidate_authority(expected_head=expected_head,
                                   namespace=namespace)
        return _validate_authority(doc, expected_head, namespace)
    import urllib.request
    repo = "Zutfen-LLC/inferswarm"
    number = C.PR_NUMBER or C.ISSUE
    url = (f"{github_api}/repos/{repo}/issues/{number}/comments"
           "?per_page=100")
    request = urllib.request.Request(url)
    token = os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        comments = json.loads(response.read())
    return _select_dispatch(comments, expected_head, namespace)


def _select_dispatch(comments: list[dict[str, Any]], expected_head: str,
                     namespace: str) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    for comment in comments:
        lines = [ln.strip() for ln in str(comment.get("body", "")).splitlines()]
        if (C.DISPATCH_PHRASE in lines
                and f"head={expected_head}" in lines
                and f"namespace={namespace}" in lines
                and comment.get("author_association") in ("OWNER", "MEMBER")):
            if (latest is None
                    or str(comment.get("created_at", ""))
                    > str(latest.get("created_at", ""))):
                latest = comment
    if latest is None:
        raise PhysicalError(
            "no valid current-head maintainer dispatch comment found")
    return {
        "schema": "inferswarm.issue270.dispatch-authority/1",
        "issue": C.ISSUE,
        "pr_number": C.PR_NUMBER,
        "comment_id": latest["id"],
        "commenter": latest["user"]["login"],
        "commenter_association": latest["author_association"],
        "created_at": latest["created_at"],
        "head_sha": expected_head,
        "namespace": namespace,
        "dispatch_phrase": C.DISPATCH_PHRASE,
    }


def _validate_authority(doc: Any, expected_head: str,
                        namespace: str) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise PhysicalError("dispatch authority must be an object")
    if doc.get("schema") != "inferswarm.issue270.dispatch-authority/1":
        raise PhysicalError("dispatch authority schema mismatch")
    if doc.get("issue") != C.ISSUE:
        raise PhysicalError("dispatch authority issue mismatch")
    if doc.get("head_sha") != expected_head:
        raise PhysicalError("dispatch authority head mismatch")
    if doc.get("namespace") != namespace:
        raise PhysicalError("dispatch authority namespace mismatch")
    if doc.get("dispatch_phrase") != C.DISPATCH_PHRASE:
        raise PhysicalError("dispatch authority phrase mismatch")
    if doc.get("commenter_association") not in ("OWNER", "MEMBER"):
        raise PhysicalError("dispatch commenter not OWNER/MEMBER")
    if (not isinstance(doc.get("comment_id"), int)
            or isinstance(doc.get("comment_id"), bool)
            or doc.get("comment_id", 0) <= 0):
        raise PhysicalError("dispatch comment_id malformed")
    return doc


def require_live_dispatch(repo_root: Path, expected_head: str, namespace: str,
                          revalidate_authority: Callable[..., Any] | None = None,
                          github_api: str = "https://api.github.com"
                          ) -> dict[str, Any]:
    C.validate_namespace(namespace)
    authority = fetch_dispatch_authority(repo_root, expected_head, namespace,
                                         revalidate_authority, github_api)
    _require_clean_head(repo_root, expected_head)
    return authority


def _require_clean_head(repo_root: Path, expected_head: str) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root,
                            capture_output=True, text=True,
                            check=True).stdout
    if head != expected_head:
        raise PhysicalError(
            f"local HEAD {head} != authorized head {expected_head}")
    if status.strip():
        raise PhysicalError("worktree is dirty at the authorized head")


# ---------------------------------------------------------------------------
# Binary / model authentication
# ---------------------------------------------------------------------------

def verify_comparator_binary(binary: Path,
                             lib_dir: Path | None = None) -> str:
    path = Path(binary)
    if path.is_symlink() or not path.is_file():
        raise PhysicalError(f"comparator binary missing: {path}")
    digest = C.file_sha256(path)
    if digest != C.COMPARATOR_SHA256:
        raise PhysicalError(
            f"binary sha mismatch: {digest} != {C.COMPARATOR_SHA256}")
    if lib_dir is not None:
        lib_dir = Path(lib_dir)
        if lib_dir.is_symlink() or not lib_dir.is_dir():
            raise PhysicalError(f"binary lib dir missing: {lib_dir}")
        if str(path.parent) != str(lib_dir):
            raise PhysicalError("binary must live inside its lib dir")
        for name, want in C.OBSERVER_LIBS.items():
            lib = lib_dir / name
            if lib.is_symlink() or not lib.is_file():
                raise PhysicalError(f"frozen observer library missing: {name}")
            got = C.file_sha256(lib)
            if got != want:
                raise PhysicalError(
                    f"observer library {name} drift: {got} != {want}")
    return digest


def verify_canonical_distinct(binary_sha: str, canonical: Path) -> str:
    if not Path(canonical).is_file():
        raise PhysicalError(f"canonical binary missing: {canonical}")
    canonical_sha = C.file_sha256(canonical)
    if canonical_sha != C.CANONICAL_SHA256:
        raise PhysicalError(
            f"canonical binary sha mismatch: {canonical_sha} != "
            f"{C.CANONICAL_SHA256}")
    if canonical_sha == binary_sha:
        raise PhysicalError(
            "canonical no-hook binary must be byte-distinct from the "
            "comparator binary")
    return canonical_sha


def model_member_hashes(model_dir: Path) -> dict[str, str]:
    model_dir = Path(model_dir)
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise PhysicalError(f"model dir missing: {model_dir}")
    got = {}
    for member in C.MODEL_MEMBERS:
        p = model_dir / member
        if p.is_symlink() or not p.is_file():
            raise PhysicalError(f"model member missing: {member}")
        got[member] = C.file_sha256(p)
    if got != C.MODEL_MEMBER_SHA256:
        raise PhysicalError(
            "model member hashes do not match the frozen three-member set")
    return got


def verify_fixtures(repo_root: Path) -> dict[str, Any]:
    return C.load_fixtures(repo_root)


# ---------------------------------------------------------------------------
# Phase 0 — authority + repository reconciliation
# ---------------------------------------------------------------------------

def phase0_reconciliation(repo_root: Path,
                          current_main: str) -> dict[str, Any]:
    """Mechanical Phase-0 record: the accepted-authority checklist.

    Repository-only (no host writes): verifies the accepted authority
    surfaces are present and internally consistent, records the
    current-main reconciliation against the issue's base, and refuses
    the campaign when comparator/2 semantics/tool identities cannot be
    mechanically identified.
    """
    root = Path(repo_root)
    problems: list[str] = []
    if current_main != C.STARTING_MAIN:
        # Drift is reconcilable, not fatal — but it is recorded and the
        # caller must classify overlap before physical work.
        problems.append(
            f"origin/main advanced from {C.STARTING_MAIN} to {current_main}")
    # 1. #237 methodology authority is reachable in main's lineage.
    try:
        merge = subprocess.run(
            ["git", "cat-file", "-t", C.ACCEPTED_237_MERGE], cwd=root,
            capture_output=True, text=True, check=True).stdout.strip()
        if merge != "commit":
            problems.append("#237 merge object missing")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", C.ACCEPTED_237_MERGE,
             current_main], cwd=root, capture_output=True)
        if ancestor.returncode == 1:
            problems.append("#237 merge not an ancestor of current main")
        elif ancestor.returncode not in (0, 1):
            # Unknown future head: git cannot classify it locally. Record
            # the drift for caller classification (reconcilable class).
            problems.append(
                f"main-unknown-locally: current main {current_main} is "
                f"unknown to the local repository — #237 ancestry "
                f"unverifiable locally")
    except subprocess.CalledProcessError as exc:
        problems.append(f"#237 authority unreachable: {exc}")
    # 2. comparator/2 semantics/tool identities resolvable on main.
    if C.COMPARATOR_SHA256 != comparator.__dict__.get(
            "RUN_SCHEMA") and C.COMPARATOR_SHA256 is None:
        problems.append("comparator binary identity missing")
    if not SHA40_RE.fullmatch(C.LLAMA_SOURCE_PIN):
        problems.append("llama.cpp source pin malformed")
    if C.COMPARATOR_V2_ID != "inferswarm.qwen38-vulkan-comparator/2":
        problems.append("comparator/2 id drift")
    # 3. #243 retained subject information present and self-consistent.
    try:
        C.validate_candidate_authority()
    except C.AuthorityError as exc:
        problems.append(f"#243 retained subject unusable: {exc}")
    # 4/5. #241 historical + #239 dispatch-blocked are STATE facts
    # verified live at execution time by the thin driver (GitHub API);
    # the module constants carry the exact comment identities.
    # 6. holdout untouched: the sealed holdout path must still exist,
    # byte-identical; predictive corpora must be absent from the
    # campaign plan (structural: validate_case refuses everything but
    # the three historical fixtures).
    holdout = root / "docs/qualification/qwen38-vulkan-v1/sealed/holdout.cms"
    if holdout.is_symlink() or not holdout.is_file():
        problems.append("sealed holdout ciphertext missing (must stay sealed)")
    record = {
        "schema": "inferswarm.issue270.phase0-reconciliation/1",
        "campaign": C.CAMPAIGN_ID,
        "starting_main": C.STARTING_MAIN,
        "current_main": current_main,
        "accepted_authority": {
            "issue237_merge": C.ACCEPTED_237_MERGE,
            "issue237_terminal": C.ACCEPTED_237_TERMINAL,
            "issue237_acceptance_comment": C.ACCEPTED_237_ACCEPTANCE_COMMENT,
            "issue241_head": C.ACCEPTED_241_HEAD,
            "issue241_terminal": C.ACCEPTED_241_TERMINAL,
            "issue241_adjudication_comment": C.ACCEPTED_241_ADJUDICATION_COMMENT,
            "issue243_terminal": C.ACCEPTED_243_TERMINAL,
            "issue243_closure_comment": C.ACCEPTED_243_CLOSURE_COMMENT,
        },
        "comparator_semantics": C.V2_OBSERVER,
        "comparator_id": C.COMPARATOR_V2_ID,
        "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
        "fixture_cases": list(C.FIXTURE_CASES),
        "prohibited_cases": list(C.PROHIBITED_CASES),
        "problems": problems,
        "reconciled": not problems,
        "checked_at": _utcnow(),
    }
    if problems:
        # Authority drift above the reconcilable-main class fails closed.
        reconcilable = ("origin/main advanced", "main-unknown-locally:")
        fatal = [p for p in problems
                 if not any(p.startswith(prefix) for prefix in reconcilable)]
        if fatal:
            raise PhysicalError(
                "Phase-0 authority reconciliation failed: " + "; ".join(fatal))
    return record


# ---------------------------------------------------------------------------
# Fresh host observations (injectable seams)
# ---------------------------------------------------------------------------

def _read_cmd(argv: list[str], timeout: int = 30) -> str:
    result = subprocess.run(argv, capture_output=True, text=True,
                            timeout=timeout)
    if result.returncode != 0:
        raise PhysicalError(
            f"observer command failed ({argv[0]}): {result.stderr.strip()[:200]}")
    if not result.stdout.strip():
        raise PhysicalError(f"observer command produced no output: {argv[0]}")
    return result.stdout


def _sysfs(bdf: str, rel: str) -> str:
    dev = Path("/sys/bus/pci/devices") / bdf
    path = dev / rel
    if path.is_symlink() or not path.is_file():
        raise PhysicalError(f"sysfs source missing: {path}")
    return path.read_text().strip()


def observe_v340_host(sysfs_reader: Callable[[str, str], str] | None = None,
                      command_runner: Callable[[list[str]], str] | None = None,
                      hostname: str | None = None) -> dict[str, Any]:
    """Fresh read-only inferswarm05 observation (no compute, no model).

    Raw block + derived identity; tests inject the readers. Covers: host
    identity, per-die sysfs identity (both dies observed independently),
    Vulkan enumeration under the RADV ICD only, and Mesa/RADV/kernel
    identities.
    """
    sysfs_reader = sysfs_reader or _sysfs
    command_runner = command_runner or _read_cmd
    host = hostname or _read_cmd(["hostname"]).strip()
    if host != C.CANDIDATE_HOST:
        raise PhysicalError(f"wrong host: {host!r} != {C.CANDIDATE_HOST!r}")
    raw: dict[str, Any] = {"host": host, "dies": {}}
    for bdf in C.DIE_BDFS:
        die_raw: dict[str, str] = {}
        for rel in ("vendor", "device", "subsystem_vendor",
                    "subsystem_device", "revision", "current_link_speed",
                    "current_link_width", "max_link_speed", "max_link_width"):
            die_raw[rel] = sysfs_reader(bdf, rel)
        driver_link = Path("/sys/bus/pci/devices") / bdf / "driver"
        if not driver_link.is_symlink():
            raise PhysicalError(f"kernel driver link missing for {bdf}")
        die_raw["driver"] = driver_link.resolve().name
        card_dir = Path("/sys/bus/pci/devices") / bdf / "drm"
        cards = sorted(p.name for p in card_dir.glob("card[0-9]*")) \
            if card_dir.is_dir() else []
        if len(cards) != 1:
            raise PhysicalError(f"no unique DRM card for {bdf}: {cards}")
        die_raw["drm_card"] = cards[0]
        die_raw["mem_info_vram_used"] = sysfs_reader(
            bdf, "drm/" + cards[0] + "/device/mem_info_vram_used") \
            if False else sysfs_reader(bdf, "mem_info_vram_used")
        # #272/#273: derive_v340_identity REQUIRES mem_info_vram_total;
        # capture it in the raw superset (fail-closed: a host whose
        # sysfs lacks it cannot produce a derivable identity).
        die_raw["mem_info_vram_total"] = sysfs_reader(
            bdf, "mem_info_vram_total")
        raw["dies"][bdf] = die_raw
    raw["uname"] = _read_cmd(["uname", "-r"]).strip()
    icd_path = Path(C.RADV_ICD)
    if icd_path.is_symlink() or not icd_path.is_file():
        raise PhysicalError(f"RADV ICD missing: {icd_path}")
    raw["icd"] = {"path": C.RADV_ICD, "sha256": C.file_sha256(icd_path)}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("VK_", "GGML_VK"))}
    env["VK_ICD_FILENAMES"] = C.RADV_ICD
    proc = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                          text=True, timeout=60, env=env)
    raw["vulkaninfo"] = {"stdout": proc.stdout, "stderr": proc.stderr,
                         "rc": proc.returncode}
    if proc.returncode != 0:
        raise PhysicalError(
            "vulkaninfo --summary failed under the RADV ICD: "
            + proc.stderr.strip()[:200])
    derived = derive_v340_identity(raw)
    return {"schema": "inferswarm.issue270.host-observation/1",
            "host": host, "raw": raw, "derived": derived,
            "observed_at": _utcnow()}


def derive_v340_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """Derive the fresh die identities from raw observation bytes.

    Never reads the frozen constants: values are derived and then
    compared by the caller. Both dies must enumerate; exactly the two
    expected RADV VEGA10 devices must appear (llvmpipe is expected on
    this host but is never a die).
    """
    text = str(raw["vulkaninfo"]["stdout"])
    if "VULKANINFO" not in text or "Vulkan Instance Version" not in text:
        raise PhysicalError("vulkaninfo receipt lacks its header")
    m = re.search(r"Vulkan Instance Version:\s*(\S+)", text)
    if not m:
        raise PhysicalError("vulkaninfo instance version missing")
    devices: dict[int, dict[str, str]] = {}
    for block in re.split(r"^GPU\d+:\s*$", text, flags=re.MULTILINE)[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            fm = re.fullmatch(r"\s*(\w+)\s+=\s+(.+?)\s*", line)
            if fm:
                fields[fm.group(1)] = fm.group(2)
        if fields.get("deviceType") == "PHYSICAL_DEVICE_TYPE_CPU":
            continue  # llvmpipe — never a die
        idx_match = re.search(
            r"GPU(\d+):", text[:text.find(block) + 8].rsplit("GPU", 1)[-1]) \
            if False else None
        devices[len(devices)] = fields
    # Map each enumerated RADV device to its die BDF via the RADV UUID
    # (bus-derived; accepted #241/#243 law). Selection NEVER assumes
    # enumeration order.
    by_bdf: dict[str, dict[str, Any]] = {}
    for _, fields in devices.items():
        uuid = fields.get("deviceUUID")
        bdf = C._bdf_from_radv_uuid(uuid or "")
        if bdf is None:
            raise PhysicalError(
                f"unexpected non-die Vulkan device: {fields.get('deviceName')!r}")
        if bdf not in C.DIE_BDFS:
            raise PhysicalError(f"unexpected die BDF enumerated: {bdf}")
        for key in ("apiVersion", "deviceName", "deviceUUID", "driverID",
                    "driverInfo"):
            if key not in fields:
                raise PhysicalError(f"vulkaninfo die block lacks {key}")
        by_bdf[bdf] = fields
    if set(by_bdf) != set(C.DIE_BDFS):
        raise PhysicalError(
            f"exactly the two V340L dies must enumerate; got {sorted(by_bdf)}")
    derived: dict[str, Any] = {
        "vulkan_instance": m.group(1),
        "kernel": str(raw["uname"]),
        "icd_sha256": raw["icd"]["sha256"],
        "dies": {},
    }
    for bdf, fields in by_bdf.items():
        sysfs_raw = raw["dies"][bdf]
        derived["dies"][bdf] = {
            "vendor_id": "0x" + sysfs_raw["vendor"].removeprefix("0x"),
            "device_id": "0x" + sysfs_raw["device"].removeprefix("0x"),
            "subsystem_vendor_id":
                "0x" + sysfs_raw["subsystem_vendor"].removeprefix("0x"),
            "subsystem_device_id":
                "0x" + sysfs_raw["subsystem_device"].removeprefix("0x"),
            "revision": sysfs_raw["revision"],
            "kernel_driver": sysfs_raw["driver"],
            "drm_card": sysfs_raw["drm_card"],
            "vram_total_bytes": int(sysfs_raw["mem_info_vram_total"]),
            "vram_used_bytes": int(sysfs_raw["mem_info_vram_used"]),
            "current_link_speed": sysfs_raw["current_link_speed"],
            "current_link_width": sysfs_raw["current_link_width"],
            "max_link_speed": sysfs_raw["max_link_speed"],
            "max_link_width": sysfs_raw["max_link_width"],
            "vulkan_device_uuid": fields["deviceUUID"],
            "vulkan_device_name": fields["deviceName"],
            "vulkan_driver_id": fields["driverID"],
            "vulkan_driver_info": fields["driverInfo"],
            "vulkan_api_version": fields["apiVersion"],
        }
    return derived


def identity_problems_vs_frozen(derived: dict[str, Any]) -> list[str]:
    """Fail-closed comparison of a fresh observation vs accepted #243."""
    problems: list[str] = []
    if derived["kernel"] != C.EXPECTED_CANDIDATE["kernel"]:
        problems.append(
            f"kernel drift: {derived['kernel']!r} != "
            f"{C.EXPECTED_CANDIDATE['kernel']!r}")
    for bdf, die in derived["dies"].items():
        for key, want in (
                ("vendor_id", C.EXPECTED_CANDIDATE["vendor_id"]),
                ("device_id", C.EXPECTED_CANDIDATE["device_id"]),
                ("subsystem_vendor_id",
                 C.EXPECTED_CANDIDATE["subsystem_vendor_id"]),
                ("subsystem_device_id",
                 C.EXPECTED_CANDIDATE["subsystem_device_id"]),
                ("revision", C.EXPECTED_CANDIDATE["revision"]),
                ("vram_total_bytes", C.EXPECTED_CANDIDATE["vram_total_bytes"]),
                ("max_link_speed", C.EXPECTED_CANDIDATE["max_link_speed"]),
                ("max_link_width", C.EXPECTED_CANDIDATE["max_link_width"]),
                ("vulkan_device_name",
                 C.EXPECTED_CANDIDATE["vulkan_device_name"]),
                ("vulkan_driver_id",
                 C.EXPECTED_CANDIDATE["vulkan_driver_id"]),
                ("vulkan_driver_info",
                 C.EXPECTED_CANDIDATE["vulkan_driver_info"]),
                ("vulkan_api_version",
                 C.EXPECTED_CANDIDATE["vulkan_api_version"]),
                ("vulkan_device_uuid",
                 C.EXPECTED_VULKAN_DEVICE_UUIDS[bdf]),
                ("kernel_driver", "amdgpu")):
            got = die.get(key)
            if got != want:
                problems.append(
                    f"{bdf} {key}: drift (observed {got!r} != frozen {want!r})")
    if derived["vulkan_instance"] != C.EXPECTED_CANDIDATE["vulkan_instance"]:
        problems.append(
            f"vulkan instance drift: {derived['vulkan_instance']!r} != "
            f"{C.EXPECTED_CANDIDATE['vulkan_instance']!r}")
    return problems
