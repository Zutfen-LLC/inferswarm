#!/usr/bin/env python3
"""#254 R8-I3C Phase 1 live producer: real process execution + per-unit custody.

PHASE-A SCOPE: this module implements the live producer machinery. During
Phase A (this PR) NOTHING in this module is executed against a GPU/model:
its physical entrypoints refuse to run without a fresh, independently
re-fetched ``R8I3C PHYSICAL DISPATCH #254`` comment (issue #254 Phase B law)
on the still-open producer PR at the exact head. No API in this module
accepts caller-supplied physical observations.

Producer properties implemented here (issue #254 Phase A):

1. Fresh dispatch authentication immediately before each unit
   (fetch_live_dispatch): PR/issue/comment fetched individually through the
   production HTTPS seam; validates repository, PR number (dynamically
   resolved — never a guessed constant), open/non-draft/unmerged state,
   exact head, base main, branch identity, arm, OWNER/MEMBER authority,
   and the exact 3-line body law. Fail-closed on drift.
2. Frozen launch construction: consumes the accepted issue252_arms contract
   and issue252_physical.launch_geometry — one-factor discipline stays
   mechanical (argv/env byte-equality with the frozen geometry).
3. Real process execution (execute_unit): the producer launches the pinned
   comparator server itself, reads back the live process's actual
   /proc/<pid>/cmdline and /proc/<pid>/environ, issues the byte-exact
   accepted request itself, captures the raw response bytes, collects the
   observer rows/meta itself, and terminates the process group fail-closed.
4. Identity and custody: comparator binary SHA-256 (frozen #252 constant),
   model-member stat witnesses before/after the unit, the accepted #248
   read-only identity observation seam, ngl=1 Vulkan placement evidence
   from the retained server log + no-CUDA environment proof, per-unit
   server-log bytes.
5. Atomic retained evidence: each unit is assembled in a ``.unit-<tag>.tmp``
   staging directory, fsynced, receipt-validated (validate_unit_receipt +
   producer-attestation re-derivation), and only then atomically renamed
   into the arm namespace. A crash leaves only the staging directory (which
   resume refuses to continue through); a producer status/failure record is
   retained on abort.
6. Fail-closed stop law (run_arm): only the next legal prefix unit may
   execute; after each unit the stop condition is derived from retained
   bytes via D.prefix_population_facts; first mismatch stops the arm;
   5 identical = deterministic; a completed mismatch population refuses any
   continuation (restart ambiguity refusal).
7. No synthetic authority path: there is no public API that takes raw
   response bytes, rows, identity, placement, logs, or a receipt and marks
   them physical. The only physical path is execute_unit -> its own
   subprocess + probes, and it requires live dispatch authority obtained
   inside this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import issue252_constants as C252
import issue254_constants as C
import issue252_arms as A
import issue252_physical as P252
import issue252_capture as CAP252
import issue252_terminal as T252
import issue250_diagnostic as D
import issue250_physical as B250
import issue248_identity as I248

API_ROOT = "https://api.github.com/repos/Zutfen-LLC/inferswarm"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")

# Execution seam constants (accepted #250 producer values).
PORT = P252.PORT
SERVER_READY_TIMEOUT_S = B250.SERVER_READY_TIMEOUT_S
LLAMA_ROOT = P252.LLAMA_ROOT
MODEL_DIR = P252.MODEL_DIR
COMPARATOR_SHA256 = C252.COMPARATOR_SHA256


class ProducerError(RuntimeError):
    """Producer gate failure: the unit cannot start or continue."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise ProducerError(f"git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_fsynced(path: Path, doc: Any) -> bytes:
    raw = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    with open(path, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return raw


# ---------------------------------------------------------------------------
# 1. Live dispatch authority (#254 phrase on the producer PR)
# ---------------------------------------------------------------------------

def _api_get_json(path: str) -> Any:
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue254-producer"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API_ROOT}/{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def resolve_producer_pr(head_branch: str) -> int:
    """Resolve THIS campaign's producer PR number through the live API.

    Never a hand-guessed constant: the PR is found by its exact head branch
    name among OPEN pull requests. ISSUE254_PR may pin the expectation on
    the executing host; a mismatch with the live lookup fails closed.
    """
    if not head_branch.startswith(C.PRODUCER_BRANCH_PREFIX):
        raise ProducerError(
            f"producer branch {head_branch!r} does not carry the frozen "
            f"prefix {C.PRODUCER_BRANCH_PREFIX!r}")
    pulls = _api_get_json(f"pulls?state=open&per_page=100")
    matches = [p for p in pulls
               if p.get("head", {}).get("ref") == head_branch
               and p.get("base", {}).get("ref") == "main"]
    if len(matches) != 1:
        raise ProducerError(
            f"producer PR for branch {head_branch!r} is not uniquely open "
            f"against main (found {len(matches)})")
    number = matches[0]["number"]
    pinned = os.environ.get(C.PR_ENV)
    if pinned is not None:
        if str(number) != pinned.strip():
            raise ProducerError(
                f"pinned {C.PR_ENV}={pinned} disagrees with live producer "
                f"PR {number}")
    return number


def validate_live_body(body: Any) -> tuple[str, str]:
    """Exact 3-line #254 dispatch body law. Returns (head, arm)."""
    if not isinstance(body, str) or len(body.splitlines()) != 3:
        raise ProducerError("dispatch body must have exactly three lines")
    phrase, head_line, arm_line = body.splitlines()
    if phrase != C.DISPATCH_PHRASE:
        raise ProducerError("dispatch phrase mismatch")
    if not head_line.startswith("head=") or not SHA40.fullmatch(head_line[5:]):
        raise ProducerError("dispatch head malformed")
    if not arm_line.startswith("arm=") or arm_line[4:] not in A.ARMS:
        raise ProducerError("dispatch arm unknown")
    return head_line[5:], arm_line[4:]


def validate_live_comment_provenance(comment: Any, *,
                                     pr_number: int) -> None:
    """Authority-bearing provenance law of a #254 dispatch comment.

    Round-2 correction (review blocker 2); mirrors the hardened schema-/2
    doctrine (issue252_capture.validate_capture_body): the comment must
    be a TOP-LEVEL CONVERSATION comment of the exact producer PR in the
    canonical repository. An exact three-line dispatch body on an issue
    timeline, another PR's conversation, or an inline review comment is
    not authority. Pure; consumes the live/re-fetched comment object and
    never trusts capture-retained copies.
    """
    if not isinstance(comment, dict):
        raise ProducerError("dispatch comment object missing")
    cid = comment.get("id")
    if type(cid) is not int or cid <= 0:
        raise ProducerError("dispatch comment id missing")
    if type(pr_number) is not int or pr_number <= 0:
        raise ProducerError("producer PR number malformed")
    if comment.get("issue_url") != f"{API_ROOT}/issues/{pr_number}":
        raise ProducerError(
            "dispatch comment is not a top-level conversation comment of "
            "the producer PR (issue_url mismatch)")
    html_url = comment.get("html_url")
    if not isinstance(html_url, str) or html_url != (
            f"https://github.com/Zutfen-LLC/inferswarm/pull/{pr_number}"
            f"#issuecomment-{cid}"):
        raise ProducerError(
            "dispatch comment html provenance is not an exact producer-PR "
            "conversation comment")
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise ProducerError("dispatch commenter login missing")


def fetch_live_dispatch(repo_root: Path, expected_head: str | None = None,
                        head_branch: str | None = None,
                        pr_number: int | None = None) -> dict[str, Any]:
    """Fresh PR/issue/comment authentication immediately before a unit.

    Fetches the PR, the issue and every top-level PR-conversation comment
    individually; finds dispatch comments carrying the exact #254 phrase;
    requires exactly ONE valid one (ambiguity refuses); validates repository,
    PR open/non-draft/unmerged, base main, exact live head == dispatch head
    == local clean HEAD on the matching branch, issue #254 open,
    OWNER/MEMBER author, and retained-parent authority (accepted #252
    Phase-0 terminalization + llama pin) unchanged.

    No parameter of this function supplies authority: ``expected_head`` and
    ``pr_number`` are OPTIONAL CROSS-CHECKS only; the live PR head and the
    resolved PR number are always derived from the API, and the dispatch
    head must equal both the live PR head and the local repository HEAD.
    """
    root = Path(repo_root)
    local_head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ProducerError("repository worktree is dirty")
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        raise ProducerError("repository detached HEAD")
    if head_branch is not None and branch != head_branch:
        raise ProducerError("repository branch differs from producer branch")
    if pr_number is None:
        pr_number = resolve_producer_pr(branch)
    pr = _api_get_json(f"pulls/{pr_number}")
    if (pr.get("state") != "open" or pr.get("merged") is not False
            or pr.get("draft") is not False):
        raise ProducerError("producer PR is not open, unmerged, non-draft")
    if pr.get("base", {}).get("ref") != "main":
        raise ProducerError("producer PR base is not main")
    if pr.get("head", {}).get("ref") != branch:
        raise ProducerError("live PR head branch differs from local branch")
    live_head = pr.get("head", {}).get("sha")
    if not isinstance(live_head, str) or not SHA40.fullmatch(live_head):
        raise ProducerError("live PR head malformed")
    if live_head != local_head:
        raise ProducerError("dispatch head moved: local HEAD differs")
    if expected_head is not None and live_head != expected_head:
        raise ProducerError("dispatch head moved: caller cross-check differs")
    issue = _api_get_json(f"issues/{C.ISSUE}")
    if issue.get("state") != "open":
        raise ProducerError(f"issue #{C.ISSUE} is not open")
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _api_get_json(
            f"issues/{pr_number}/comments?page={page}&per_page=100")
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            raise ProducerError("unbounded comment pagination")
    valid: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or C.DISPATCH_PHRASE not in body:
            continue
        head, arm = validate_live_body(body)
        if head != live_head:
            continue  # stale dispatch for an older head: not authority
        if comment.get("author_association") not in ("OWNER", "MEMBER"):
            continue
        # Round-2 provenance law (review blocker 2): the comment must be a
        # top-level conversation comment of THIS producer PR in the
        # canonical repository (issue/other-PR/review bodies are skipped;
        # a surviving exact-body comment elsewhere yields zero valid
        # candidates, which refuses below with the ambiguity error).
        try:
            validate_live_comment_provenance(comment, pr_number=pr_number)
        except ProducerError:
            continue
        valid.append(comment)
    if len(valid) != 1:
        raise ProducerError(
            f"expected exactly one valid live dispatch comment at head "
            f"{live_head}, found {len(valid)}")
    comment = valid[0]
    head, arm = validate_live_body(comment["body"])
    # Retained parent authority must authenticate from this checkout.
    try:
        terminal = P252.P0.verify_terminalization(root)
        pin = P252.P0.verify_llama_pin(LLAMA_ROOT)
    except Exception as exc:
        raise ProducerError(f"retained parent authority unauthenticated: {exc}")
    if (terminal.get("terminal") != C252.PREDECESSOR_TERMINAL
            or terminal.get("execution_head") != C252.ACCEPTED_EXECUTION_HEAD
            or pin.get("head") != C252.LLAMA_PIN
            or pin.get("tree") != C252.LLAMA_PIN_TREE):
        raise ProducerError("retained parent authority unauthenticated")
    return {"pr_number": pr_number, "head_sha": live_head,
            "arm": arm, "namespace": A.ARMS[arm]["namespace"],
            "comment_id": comment["id"],
            "commenter_login": comment.get("user", {}).get("login"),
            "author_association": comment["author_association"],
            "created_at": comment["created_at"],
            "issue_url": comment["issue_url"],
            "body": comment["body"],
            "body_sha256": _sha(comment["body"].encode("utf-8")),
            "issue_state": issue["state"]}


def build_live_capture(dispatch: dict[str, Any]) -> dict[str, Any]:
    """Build the retained live capture (schema /3) from a fresh dispatch.

    Binds the authentication-bearing immutable comment fields, the
    execution-time mutable PR/issue state, the producer-PR number and the
    #254 phrase — the additive successor record the reducer admits for
    #254-era evidence (issue252_capture schema /2 stays byte-identical for
    the merged Phase-0 campaign).
    """
    head, arm = validate_live_body(dispatch["body"])
    if dispatch["head_sha"] != head:
        raise ProducerError("dispatch head/body mismatch")
    raw_comment = {"author_association": dispatch["author_association"],
                   "body": dispatch["body"],
                   "created_at": dispatch["created_at"],
                   "id": dispatch["comment_id"],
                   "issue_url": dispatch["issue_url"],
                   "user": {"login": dispatch["commenter_login"]}}
    # Round-2 provenance binding (review blocker 2): html_url is retained
    # in the /3 capture and its canonical projection, mirroring the
    # hardened schema-/2 AUTH_FIELDS doctrine (issue252_capture).
    html_url = (f"https://github.com/Zutfen-LLC/inferswarm/pull/"
                f"{dispatch['pr_number']}"
                f"#issuecomment-{dispatch['comment_id']}")
    raw_comment["html_url"] = html_url
    return {
        "schema": C.LIVE_CAPTURE_SCHEMA,
        "repo": "Zutfen-LLC/inferswarm",
        "pr_number": dispatch["pr_number"],
        "issue_number": C.ISSUE,
        "dispatch_phrase": C.DISPATCH_PHRASE,
        "head_sha": head,
        "arm": arm,
        "namespace": A.ARMS[arm]["namespace"],
        "comment_id": dispatch["comment_id"],
        "commenter_login": dispatch["commenter_login"],
        "author_association": dispatch["author_association"],
        "created_at": dispatch["created_at"],
        "body": dispatch["body"],
        "html_url": html_url,
        "issue_url": dispatch["issue_url"],
        "raw_comment_sha256": _sha(CAP252.canonical_bytes(raw_comment)),
        "execution_time_state": {
            "pr_open": True, "pr_merged": False, "pr_draft": False,
            "pr_base_ref": "main", "pr_head": head,
            "issue_state": "open",
        },
    }


def validate_live_capture_structure(cap: dict[str, Any]) -> None:
    """Structural law of a retained /3 live capture. Pure."""
    if not isinstance(cap, dict) or cap.get("schema") != C.LIVE_CAPTURE_SCHEMA:
        raise ProducerError("live capture schema mismatch")
    if cap.get("repo") != "Zutfen-LLC/inferswarm":
        raise ProducerError("live capture is not for this repository")
    head, arm = validate_live_body(cap.get("body"))
    if cap.get("head_sha") != head:
        raise ProducerError("live capture head/body mismatch")
    if cap.get("arm") != arm or arm not in A.ARMS:
        raise ProducerError("live capture arm mismatch")
    if cap.get("namespace") != A.ARMS[arm]["namespace"]:
        raise ProducerError("live capture namespace/arm mismatch")
    if cap.get("dispatch_phrase") != C.DISPATCH_PHRASE:
        raise ProducerError("live capture phrase mismatch")
    number = cap.get("pr_number")
    if type(number) is not int or number <= 0 or number == C252.CAMPAIGN_PR:
        raise ProducerError("live capture PR number invalid")
    if cap.get("issue_number") != C.ISSUE:
        raise ProducerError("live capture issue number mismatch")
    if cap.get("author_association") not in ("OWNER", "MEMBER"):
        raise ProducerError("live capture author not OWNER/MEMBER")
    if type(cap.get("comment_id")) is not int or cap["comment_id"] <= 0:
        raise ProducerError("live capture comment ID missing")
    if not isinstance(cap.get("commenter_login"), str) or not cap[
            "commenter_login"]:
        raise ProducerError("live capture commenter login missing")
    # Round-2 provenance law (review blocker 2): the retained capture must
    # carry the exact canonical PR-conversation html_url for this comment
    # (mirrors the schema-/2 doctrine); verify_live_capture additionally
    # re-derives it from the independently re-fetched live comment.
    number = cap["pr_number"]
    cid = cap["comment_id"]
    if cap.get("html_url") != (
            f"https://github.com/Zutfen-LLC/inferswarm/pull/{number}"
            f"#issuecomment-{cid}"):
        raise ProducerError(
            "live capture html provenance is not an exact producer-PR "
            "conversation comment")
    if cap.get("issue_url") != f"{API_ROOT}/issues/{number}":
        raise ProducerError(
            "live capture is not a top-level comment of the producer PR")
    raw = cap.get("raw_comment_sha256")
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-f]{64}", raw):
        raise ProducerError("live capture raw digest malformed")
    state = cap.get("execution_time_state")
    if not isinstance(state, dict) or state != {
            "pr_open": True, "pr_merged": False, "pr_draft": False,
            "pr_base_ref": "main", "pr_head": head, "issue_state": "open"}:
        raise ProducerError("live capture execution-time state law mismatch")


def verify_live_capture(cap: dict[str, Any]) -> dict[str, Any]:
    """Reducer-side admission of a retained /3 live capture: independent
    re-fetch of the immutable comment by exact ID through the production
    HTTPS seam; byte-equality of every authentication-bearing field.

    Round-2 correction (review blocker 2): the re-fetched comment's
    authority-bearing PROVENANCE is mechanically bound to the exact
    producer PR at reduction time — ``issue_url`` must be the PR's issues
    API URL and ``html_url`` the exact canonical PR-conversation comment
    URL for ``cap['pr_number']`` and the exact comment id. An exact-body
    OWNER/MEMBER comment on an issue timeline, another PR, or an inline
    review comment cannot back a /3 capture (mirrors the hardened
    schema-/2 verify_capture doctrine).
    """
    validate_live_capture_structure(cap)
    live = P252.fetch_dispatch_comment(
        f"{API_ROOT}/issues/comments/{cap['comment_id']}")
    validate_live_body(live.get("body"))
    # Live provenance law: the re-fetched comment must BE a top-level
    # conversation comment of the exact producer PR named by the capture.
    validate_live_comment_provenance(live, pr_number=cap["pr_number"])
    # Round-2 cross-check: the retained pr_number must resolve to a PR
    # whose IMMUTABLE head ref carries the frozen #254 producer-branch
    # prefix (the same law resolve_producer_pr uses at dispatch time).
    # This binds the PR number to a producer PR without checking mutable
    # PR state (open/merged/draft/base are execution-time facts retained
    # in the capture, never re-derived at reduction time) — the /2
    # doctrine of validating only immutable identity at reduction.
    pr = P252.fetch_dispatch_comment(f"{API_ROOT}/pulls/{cap['pr_number']}")
    if (not isinstance(pr, dict) or pr.get("number") != cap["pr_number"]):
        raise ProducerError("retained producer PR does not resolve")
    head_ref = pr.get("head", {}).get("ref")
    if not isinstance(head_ref, str) or not head_ref.startswith(
            C.PRODUCER_BRANCH_PREFIX):
        raise ProducerError(
            "retained producer PR head branch is not a #254 producer branch")
    # Same projection as build time: every authentication-bearing field,
    # with ``user`` reduced to the login (the only retained authority
    # semantics; the live API's extra user fields are not authority).
    user = live.get("user")
    projected = {"author_association": live.get("author_association"),
                 "body": live.get("body"),
                 "created_at": live.get("created_at"),
                 "id": live.get("id"),
                 "issue_url": live.get("issue_url"),
                 "html_url": live.get("html_url"),
                 "user": {"login": user.get("login") if isinstance(
                     user, dict) else None}}
    if _sha(CAP252.canonical_bytes(projected)) != cap["raw_comment_sha256"]:
        raise ProducerError(
            "re-fetched comment bytes differ from retained live capture")
    if live.get("id") != cap["comment_id"]:
        raise ProducerError("re-fetched comment id differs")
    if live.get("body") != cap["body"]:
        raise ProducerError("re-fetched comment body differs")
    if live.get("author_association") != cap["author_association"]:
        raise ProducerError("re-fetched comment author differs")
    if live.get("created_at") != cap["created_at"]:
        raise ProducerError("re-fetched comment creation differs")
    if live.get("html_url") != cap["html_url"]:
        raise ProducerError("re-fetched comment html provenance differs")
    if live.get("issue_url") != cap["issue_url"]:
        raise ProducerError("re-fetched comment issue provenance differs")
    if projected["user"]["login"] != cap["commenter_login"]:
        raise ProducerError("re-fetched commenter login differs")
    return cap


# ---------------------------------------------------------------------------
# 2/3/4. Frozen launch + real process execution + identity custody
# ---------------------------------------------------------------------------

def verify_comparator(binary: Path) -> str:
    """Authenticate the comparator binary against the frozen #252 SHA."""
    digest = _sha(Path(binary).read_bytes())
    if digest != COMPARATOR_SHA256:
        raise ProducerError(
            f"comparator binary sha256 {digest} != frozen "
            f"{COMPARATOR_SHA256}")
    return digest


def observe_model_stats(model_dir: Path) -> dict[str, dict[str, int]]:
    """Fresh stat witness for every frozen model member."""
    witness = {}
    for name in C252.MODEL_MEMBERS:
        path = Path(model_dir) / name
        st = path.stat()
        witness[name] = {"bytes": st.st_size, "device": st.st_dev,
                         "inode": st.st_ino, "mtime_ns": st.st_mtime_ns,
                         "ctime_ns": st.st_ctime_ns}
    return witness


def stat_witness_changed(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    problems = []
    for name in C252.MODEL_MEMBERS:
        if before.get(name) != after.get(name):
            problems.append(name)
    return problems


def _proc_readback(proc_pid: int) -> dict[str, Any]:
    """Read back the live server's actual argv/env from /proc."""
    cmdline = Path(f"/proc/{proc_pid}/cmdline").read_bytes()
    argv = cmdline.rstrip(b"\0").split(b"\0")
    env = dict(chunk.split(b"=", 1) for chunk in
               Path(f"/proc/{proc_pid}/environ").read_bytes().split(b"\0")
               if b"=" in chunk)
    return {"argv": [a.decode("utf-8", "surrogateescape") for a in argv],
            "env_raw_sha256": _sha(Path(f"/proc/{proc_pid}/environ")
                                   .read_bytes())}


def _check_process_attribution(proc_pid: int, argv: list[str],
                               env: dict[str, str]) -> None:
    """The live process must still carry the exact frozen argv/env."""
    readback = _proc_readback(proc_pid)
    if readback["argv"] != argv:
        raise ProducerError("live server argv drift (forged/substituted process)")
    observed_env = {}
    for key, value in env.items():
        observed_env[key.encode()] = value.encode()
    environ = Path(f"/proc/{proc_pid}/environ").read_bytes().split(b"\0")
    live_env = dict(chunk.split(b"=", 1) for chunk in environ if b"=" in chunk)
    for key, value in observed_env.items():
        if live_env.get(key) != value:
            raise ProducerError(f"live server env drift: {key.decode()}")


def _wait_healthy(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + SERVER_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ProducerError(f"server exited early rc={proc.returncode}")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    raise ProducerError("server never became healthy")


def _post_completion(port: int, request: dict[str, Any],
                     prompt: str, timeout_s: float) -> tuple[bytes, Any]:
    payload = json.dumps({**request, "prompt": prompt}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        if response.status != 200:
            raise ProducerError(f"completion HTTP status {response.status}")
        raw = response.read(16 * 1024 * 1024)
    return raw, json.loads(raw)


def _collect_observer(unit_dir: Path) -> tuple[list[bytes], bytes]:
    meta = (unit_dir / "obs.meta.json").read_bytes()
    rows = [(unit_dir / f"obs.row{n}.f32").read_bytes()
            for n in range(D.DECISIONS)]
    return rows, meta


def _placement_from_log(server_log: bytes,
                        env: dict[str, str]) -> dict[str, Any]:
    """ngl=1 Vulkan placement evidence from retained log + env law."""
    if env.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise ProducerError("CUDA not excluded from the execution path")
    if env.get("VK_ICD_FILENAMES") != P252.ICD:
        raise ProducerError("Vulkan ICD is not the frozen subject ICD")
    text = server_log.decode("utf-8", errors="strict")
    import issue252_mechanism as M
    enum_lines = [line for line in text.splitlines()
                  if M.ENUM_LINE.match(line)]
    if len(enum_lines) != 1:
        raise ProducerError(
            "server log does not carry exactly one Vulkan device "
            "enumeration line")
    family = M.ENUM_LINE.match(enum_lines[0]).group("family")
    if family not in ("NV_coopmat2",):
        raise ProducerError(
            f"participating Vulkan device family {family!r} is not the "
            "frozen subject capability")
    return {"output_projection": "Vulkan", "embedding": "CPU", "ngl": 1,
            "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
            "vulkan_family": family,
            "cuda_participation": False,
            "enumeration_line": enum_lines[0]}


def _terminate_group(proc: subprocess.Popen) -> None:
    """Stop the unit's process group fail-closed; verify it is dead."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    if proc.poll() is None:
        raise ProducerError("measured server process survived cleanup")


def execute_unit(*, dispatch: dict[str, Any], arm: str, unit_index: int,
                 binary: Path, unit_dir: Path, prompt: str,
                 timeout_s: float,
                 request: dict[str, Any] | None = None,
                 identity_observer: Callable[[], dict[str, Any]] | None = None,
                 health_runner: Callable[[], Any] | None = None) -> dict[str, Any]:
    """ONE physical unit: launch, measure, collect, terminate, attest.

    The only physical execution path. ``dispatch`` MUST be the dict returned
    by fetch_live_dispatch in this same process (re-authentication happens
    in run_unit immediately before this call). No parameter supplies
    observations: rows/response/identity/placement all originate from the
    launched process and host probes inside this function.
    """
    if arm not in A.ARMS:
        raise ProducerError("unknown arm")
    if dispatch.get("arm") != arm:
        raise ProducerError("dispatch arm does not match the executing arm")
    request = D.validate_request_contract(
        request if request is not None else D.REQUEST_CONTRACT)
    observer_dir = unit_dir
    geom = P252.launch_geometry(arm, binary, MODEL_DIR / next(iter(C252.MODEL_MEMBERS)), observer_dir)
    argv, env = geom["argv"], geom["env"]
    binary_sha = verify_comparator(binary)
    stats_pre = observe_model_stats(MODEL_DIR)
    identity_pre = (identity_observer or _default_identity_observer)()
    identity_pre_problems = _identity_problems(identity_pre)
    if identity_pre_problems:
        raise ProducerError(f"pre-launch identity drift: {identity_pre_problems}")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = unit_dir / "server.log"
    proc = None
    server_pid = None
    try:
        with log_path.open("wb") as log_file:
            full_env = {**os.environ, **env}
            proc = subprocess.Popen(argv, env=full_env, stdout=log_file,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
            _wait_healthy(proc, PORT)
            _check_process_attribution(proc.pid, argv, env)
            raw_response, response = _post_completion(
                PORT, request, prompt, timeout_s)
            server_pid = proc.pid
            rows, meta = _collect_observer(unit_dir)
            identity_post = (identity_observer or _default_identity_observer)()
            identity_post_problems = _identity_problems(identity_post)
            if identity_post_problems:
                raise ProducerError(
                    f"post-unit identity drift: {identity_post_problems}")
    finally:
        if proc is not None:
            _terminate_group(proc)
    # Placement evidence is derived from the COMPLETE retained server log
    # (read only after the measured process has terminated).
    placement = _placement_from_log(log_path.read_bytes(), env)
    stats_post = observe_model_stats(MODEL_DIR)
    drift = stat_witness_changed(stats_pre, stats_post)
    if drift:
        raise ProducerError(f"model stat witness changed during unit: {drift}")
    ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if proc is None:
        raise ProducerError("server process never launched")
    exit_info = {"returncode": proc.returncode,
                 "cleanup_verified": proc.poll() is not None}
    return {"arm": arm, "unit_index": unit_index,
            "dispatch_comment_id": dispatch["comment_id"],
            "dispatch_body_sha256": dispatch["body_sha256"],
            "producer_head": dispatch["head_sha"],
            "server_pid": server_pid, "started_at": started_at,
            "ended_at": ended_at, "binary_sha256": binary_sha,
            "model_stat_witness": stats_pre,
            "argv": argv, "env": env,
            "request": request,
            "request_sha256": _sha(json.dumps(
                {**request, "prompt": prompt},
                sort_keys=True).encode()),
            "response_raw": raw_response,
            "response_raw_sha256": _sha(raw_response),
            "observer_rows": rows, "observer_meta": meta,
            "server_log": log_path.read_bytes(),
            "identity_pre": identity_pre, "identity_post": identity_post,
            "placement": placement,
            "process_exit": exit_info,
            "health": (health_runner or _default_health_runner)()}


def _default_identity_observer() -> dict[str, Any]:
    """Real read-only identity observation through the accepted #248 seam.

    Returns the raw #248 observation (schema/arm/raw) AFTER it passes the
    frozen #248 identity law; the flat HOST_FACTS view the #252 receipt
    retains is derived independently from the raw bytes.
    """
    observation = I248.observe_arm_identity("B")
    problems = I248.identity_problems("B", observation)
    if problems:
        raise ProducerError(
            f"identity observation drift: {problems}")
    return observation


def _flat_identity(observation: dict[str, Any]) -> dict[str, Any]:
    """Derive the flat #252 HOST_FACTS view from a #248 raw observation.

    Non-circular: every value is derived from the raw observation bytes
    through the accepted #248 parsers, then required to equal the frozen
    HOST_FACTS by _identity_problems.
    """
    derived = I248.derive_identity_from_raw("B", observation["raw"])
    icd_name = Path(derived["icd"]).name
    icd_vendor = (icd_name[:-len("_icd.json")]
                  if icd_name.endswith("_icd.json") else icd_name)
    flat = {"host": derived["host"], "reference_arm": "B",
            "gpu": derived["vulkan_device_name"], "bdf": derived["bdf"],
            "gpu_uuid": derived["gpu_uuid"],
            "driver": derived["nvidia_driver"],
            "icd": icd_vendor,
            "vulkan": derived["vulkan_api"]}
    # Retain the raw bytes for custody alongside the derived flat view.
    return {**flat, "raw": observation["raw"]}


def _identity_problems(observation: dict[str, Any]) -> list[str]:
    """Frozen #252 identity law for one observation. Fail-closed.

    A #248-shaped observation (schema/arm/raw) must pass the accepted #248
    identity law first, then its derived flat view must equal HOST_FACTS.
    An already-flat observation (injected test seam / legacy shape) is
    checked directly against HOST_FACTS.
    """
    if observation.get("schema") == I248.IDENTITY_SCHEMA:
        problems = I248.identity_problems("B", observation)
        if problems:
            return problems
        observation = _flat_identity(observation)
    return [f"{k}: {observation.get(k)!r} != {v!r}"
            for k, v in C252.HOST_FACTS.items()
            if observation.get(k) != v]


def _default_health_runner() -> dict[str, Any]:
    """Read-only health probe (telemetry snapshot; never a threshold)."""
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used,temperature.gpu",
         "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
    return {"nvidia_smi_raw": smi.stdout, "rc": smi.returncode}


# ---------------------------------------------------------------------------
# 5. Atomic retained evidence + producer attestation
# ---------------------------------------------------------------------------

def build_producer_attestation(unit: dict[str, Any]) -> dict[str, Any]:
    """Digest-bound producer attestation over every retained artifact."""
    attestation = {
        "schema": C.PRODUCER_SCHEMA,
        "producer_head": unit["producer_head"],
        "dispatch_capture_comment_id": unit["dispatch_comment_id"],
        "dispatch_body_sha256": unit["dispatch_body_sha256"],
        "unit_index": unit["unit_index"],
        "tag": f"case-3072-B-{unit['arm'].lower()}-{unit['unit_index']:03d}",
        "server_pid": unit["server_pid"],
        "started_at": unit["started_at"], "ended_at": unit["ended_at"],
        "comparator_sha256": unit["binary_sha256"],
        "model_stat_witness": unit["model_stat_witness"],
        "server_argv": unit["argv"], "server_env": unit["env"],
        "request_sha256": unit["request_sha256"],
        "response_raw_sha256": unit["response_raw_sha256"],
        "response_raw_bytes": len(unit["response_raw"]),
        "observer_meta_sha256": _sha(unit["observer_meta"]),
        "observer_row_sha256": [_sha(r) for r in unit["observer_rows"]],
        "observer_row_bytes": [len(r) for r in unit["observer_rows"]],
        "server_log_sha256": _sha(unit["server_log"]),
        "identity_pre": unit["identity_pre"],
        "identity_post": unit["identity_post"],
        "placement": unit["placement"],
        "process_exit": unit["process_exit"],
        "health": unit["health"],
    }
    validate_producer_attestation(attestation)
    return attestation


def validate_producer_attestation(att: dict[str, Any]) -> None:
    """Fail-closed structural law of a producer attestation."""
    if not isinstance(att, dict) or att.get("schema") != C.PRODUCER_SCHEMA:
        raise ProducerError("attestation schema mismatch")
    if not isinstance(att.get("producer_head"), str) or not SHA40.fullmatch(
            att["producer_head"]):
        raise ProducerError("attestation producer head missing")
    if type(att.get("dispatch_capture_comment_id")) is not int:
        raise ProducerError("attestation dispatch comment id missing")
    index = att.get("unit_index")
    if type(index) is not int or not 1 <= index <= 5:
        raise ProducerError("attestation unit index law")
    arm_tag = re.fullmatch(r"case-3072-B-(a\d)-(\d{3})", att.get("tag", ""))
    if not arm_tag or int(arm_tag.group(2)) != index:
        raise ProducerError("attestation unit tag/index mismatch")
    if type(att.get("server_pid")) is not int or att["server_pid"] <= 0:
        raise ProducerError("attestation server PID missing")
    for key in ("started_at", "ended_at"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                            str(att.get(key, ""))):
            raise ProducerError(f"attestation {key} malformed")
    if att.get("comparator_sha256") != COMPARATOR_SHA256:
        raise ProducerError("attestation comparator sha mismatch")
    witness = att.get("model_stat_witness")
    if (not isinstance(witness, dict) or set(witness) != set(C252.MODEL_MEMBERS)
            or any(not isinstance(v, dict) or
                   set(v) != {"bytes", "device", "inode", "mtime_ns", "ctime_ns"}
                   for v in witness.values())):
        raise ProducerError("attestation model stat witness malformed")
    argv, env = att.get("server_argv"), att.get("server_env")
    if not isinstance(argv, list) or not isinstance(env, dict):
        raise ProducerError("attestation argv/env missing")
    # One-factor discipline: the attested argv/env must equal the FROZEN
    # launch geometry byte-for-byte (adversarial case 9: a CUDA-enabled or
    # otherwise tampered environment is never attestable).
    arm_id = arm_tag.group(1).upper()  # e.g. "a3" -> "A3"
    out_dir = env.get("LLAMA_OBSERVE_OUT")
    if not isinstance(out_dir, str) or not out_dir:
        raise ProducerError("attestation observer dir missing")
    geometry = P252.launch_geometry(
        arm_id, Path(argv[0]) if argv else Path("/x"),
        MODEL_DIR / next(iter(C252.MODEL_MEMBERS)), Path(out_dir))
    if argv != geometry["argv"] or env != geometry["env"]:
        raise ProducerError(
            "attestation argv/env differs from the frozen one-factor "
            "geometry")
    for key in ("request_sha256", "response_raw_sha256",
                "observer_meta_sha256", "server_log_sha256",
                "dispatch_body_sha256"):
        if not isinstance(att.get(key), str) or not re.fullmatch(
                r"[0-9a-f]{64}", att[key]):
            raise ProducerError(f"attestation {key} malformed")
    rows = att.get("observer_row_sha256")
    lengths = att.get("observer_row_bytes")
    if (not isinstance(rows, list) or len(rows) != D.DECISIONS
            or not isinstance(lengths, list) or len(rows) != len(lengths)
            or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in rows)
            or any(type(n) is not int or n != D.ROW_BYTES for n in lengths)
            or type(att.get("response_raw_bytes")) is not int
            or att["response_raw_bytes"] <= 0):
        raise ProducerError("attestation row/response custody malformed")
    if not isinstance(att.get("process_exit"), dict) or att[
            "process_exit"].get("cleanup_verified") is not True:
        raise ProducerError("attestation process exit/cleanup missing")
    placement = att.get("placement")
    if (not isinstance(placement, dict) or
            placement.get("output_projection") != "Vulkan" or
            placement.get("embedding") != "CPU" or placement.get("ngl") != 1 or
            placement.get("gpu_uuid") != C252.HOST_FACTS["gpu_uuid"] or
            placement.get("cuda_participation") is not False):
        raise ProducerError("attestation placement evidence missing")


def publish_unit_atomically(*, evidence_root: Path, namespace: str, tag: str,
                            artifacts: dict[str, bytes],
                            receipt: dict[str, Any],
                            attestation: dict[str, Any]) -> Path:
    """Stage → fsync → validate → atomic rename. Never a partial unit."""
    base = Path(evidence_root) / namespace
    base.mkdir(parents=True, exist_ok=True)
    final = base / tag
    if final.exists() or final.is_symlink():
        raise ProducerError(f"retained unit already exists (append-only): {tag}")
    staging = base / f".unit-{tag}.tmp"
    if staging.exists() or staging.is_symlink():
        raise ProducerError(
            f"incomplete staging directory from an earlier attempt refuses "
            f"ambiguous continuation: {staging.name} (quarantine it first)")
    staging.mkdir()
    try:
        for name, raw in artifacts.items():
            path = staging / name
            with open(path, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        _write_json_fsynced(staging / "unit.json", receipt)
        _write_json_fsynced(staging / "producer-attestation.json", attestation)
        # Validate the COMPLETE staged tree before publication.
        staged_receipt = json.loads((staging / "unit.json").read_bytes())
        P252.validate_unit_receipt(staged_receipt)
        validate_producer_attestation(
            json.loads((staging / "producer-attestation.json").read_bytes()))
        for n in range(D.DECISIONS):
            row = (staging / f"obs.row{n}.f32").read_bytes()
            if len(row) != D.ROW_BYTES or _sha(row) != receipt[
                    "observer_rows"][n]:
                raise ProducerError("staged observer row custody mismatch")
        raw = (staging / "response.json.raw").read_bytes()
        if (_sha(raw) != receipt["response_raw_sha256"]
                or len(raw) != receipt["response_raw_bytes"]):
            raise ProducerError("staged raw response custody mismatch")
        _fsync_dir(staging)
        os.rename(staging, final)
        _fsync_dir(base)
    except Exception:
        # Retain the failed staging tree for diagnosis; it is never
        # complete evidence and resume refuses to continue through it.
        raise
    return final


# ---------------------------------------------------------------------------
# 6. Unit orchestration under the fail-closed stop law
# ---------------------------------------------------------------------------

def planned_tags(arm: str) -> list[str]:
    return [f"case-3072-B-{arm.lower()}-{i:03d}" for i in range(1, 6)]


def retained_tags(evidence_root: Path, namespace: str) -> list[str]:
    base = Path(evidence_root) / namespace
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and not p.is_symlink()
                  and not p.name.startswith("."))


def staging_directories(evidence_root: Path, namespace: str) -> list[str]:
    base = Path(evidence_root) / namespace
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and p.name.startswith(".unit-"))


def next_legal_unit(evidence_root: Path, arm: str) -> int | None:
    """The next legal prefix index, or None when the arm is complete.

    Refuses ambiguous continuation: any staging directory, any gap, any
    duplicate, or any retained population that already answered (mismatch
    stop) blocks further execution.
    """
    namespace = A.ARMS[arm]["namespace"]
    if staging_directories(evidence_root, namespace):
        raise ProducerError(
            "incomplete staging unit present: crash recovery requires "
            "explicit quarantine before any continuation")
    planned = planned_tags(arm)
    retained = retained_tags(evidence_root, namespace)
    if set(retained) - set(planned):
        raise ProducerError("unplanned retained unit (no cherry-picking)")
    if len(set(retained)) != len(retained):
        raise ProducerError("duplicate retained units")
    digests: dict[str, tuple[str, ...]] = {}
    for tag in retained:
        index = planned.index(tag) + 1
        unit = Path(evidence_root) / namespace / tag
        # Each retained unit must be a structurally valid receipt for its
        # exact prefix index (a copy of unit 001 under tag 002 is a
        # duplicate, not a valid unit 002).
        rec = json.loads((unit / "unit.json").read_bytes())
        if rec.get("unit_index") != index or rec.get("tag") != tag:
            raise ProducerError(
                f"retained unit {tag} receipt index/tag mismatch")
        digests[tag] = (_sha(b"".join(
            (unit / f"obs.row{n}.f32").read_bytes()
            for n in range(D.DECISIONS))),)
    if retained:
        facts = D.prefix_population_facts(
            planned, retained, digests,
            deterministic_required=A.REPEAT_LAW["deterministic_requires"])
        if facts["population"] == "invalid":
            raise ProducerError(
                "retained prefix invalid: " + str(facts.get("invalid")))
        if facts["population"] == "complete_nondeterministic_prefix":
            return None  # mismatch already answered: the arm has stopped
        if facts["population"] == "complete_deterministic":
            return None  # five identical: arm complete
        # "incomplete" = a contiguous all-identical prefix below five:
        # the frozen arm plan continues toward the deterministic count
        # (three identical is screening stability only, never a stop).
    n = len(retained)
    return n + 1 if n < len(planned) else None


def retain_status_record(evidence_root: Path, namespace: str,
                         record: dict[str, Any]) -> None:
    """Machine-readable producer status/failure record on abort.

    Written at the EVIDENCE ROOT (a file, not a directory): the #252
    reducer polices namespace directories, so a status record inside a
    namespace would be an unplanned entry blocking reduction.
    """
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"producer-status-{namespace}.json"
    doc = {"schema": "inferswarm.issue254.producer-status/1",
           "namespace": namespace, **record}
    _write_json_fsynced(path, doc)


def run_unit(*, repo_root: Path, evidence_root: Path, arm: str,
             binary: Path, timeout_s: float,
             prompt: str | None = None,
             ) -> dict[str, Any]:
    """Re-authenticate dispatch, derive the next legal unit, execute, retain.

    The single production orchestration entrypoint. Round-2 correction
    (review blocker 1): NO injectable seams — this function exposes no
    fetch, execute, identity-observer or health-runner parameter and
    unconditionally calls the production fetch_live_dispatch,
    execute_unit, identity-observation and health paths, which obtain
    every observation from the producer's own launched process and host
    probes. Offline tests exercise this same production logic by
    patching the internal production function objects from test code
    (unittest.mock), never through this signature. There is deliberately
    no **kwargs: a generic kwargs escape could recreate the removed seams.
    """
    if arm not in A.ARMS:
        raise ProducerError("unknown arm")
    namespace = A.ARMS[arm]["namespace"]
    index = next_legal_unit(evidence_root, arm)
    if index is None:
        raise ProducerError("arm has no next legal unit (stopped/complete)")
    dispatch = fetch_live_dispatch(repo_root=repo_root)
    if dispatch["arm"] != arm:
        raise ProducerError(
            "live dispatch authorizes a different arm (one dispatch = one arm)")
    tag = f"case-3072-B-{arm.lower()}-{index:03d}"
    if prompt is None:
        fixtures = B250.verify_fixtures(repo_root)
        prompt = fixtures[D.CASE]["prompt_text"]
        assert prompt is not None  # frozen fixture always carries the text
    staging = Path(evidence_root) / namespace
    staging.mkdir(parents=True, exist_ok=True)
    work = staging / f".exec-{tag}.tmp"
    if work.exists() or work.is_symlink():
        raise ProducerError(f"execution scratch already present: {work.name}")
    work.mkdir()
    try:
        capture = build_live_capture(dispatch)
        validate_live_capture_structure(capture)
        unit = execute_unit(dispatch=dispatch, arm=arm, unit_index=index,
                            binary=Path(binary), unit_dir=work,
                            prompt=prompt, timeout_s=timeout_s)
        attestation = build_producer_attestation(unit)
        # Retained receipt: the #252 frozen unit-receipt contract, with the
        # retained authority being EXACTLY the #254 live capture (schema
        # /3 — the reducer's additive admission path). The producer
        # attestation is retained beside the receipt and bound by digest
        # re-derivation at reduction time (verify_unit_producer_binding).
        receipt = P252.build_unit_receipt(
            authority=capture, unit_index=index, binary=Path(binary),
            model_member=MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
            observer_dir=work, identity_pre=unit["identity_pre"],
            identity_post=unit["identity_post"],
            placement=unit["placement"], raw_response=unit["response_raw"],
            rows=unit["observer_rows"], observer_meta=unit["observer_meta"],
            server_log=unit["server_log"], server_pid=unit["server_pid"],
            model_stat_witness=unit["model_stat_witness"],
            request=unit["request"])
        artifacts = {
            "response.json.raw": unit["response_raw"],
            "obs.meta.json": unit["observer_meta"],
            "server.log": unit["server_log"],
            "identity-pre.json": json.dumps(
                unit["identity_pre"], sort_keys=True).encode(),
            "identity-post.json": json.dumps(
                unit["identity_post"], sort_keys=True).encode(),
            "placement.json": json.dumps(
                unit["placement"], sort_keys=True).encode(),
        }
        for n, row in enumerate(unit["observer_rows"]):
            artifacts[f"obs.row{n}.f32"] = row
        final = publish_unit_atomically(
            evidence_root=Path(evidence_root), namespace=namespace, tag=tag,
            artifacts=artifacts, receipt=receipt, attestation=attestation)
        return {"tag": tag, "unit_dir": str(final), "index": index,
                "row_digest": _sha(b"".join(unit["observer_rows"]))}
    except Exception as exc:
        retain_status_record(Path(evidence_root), namespace, {
            "status": "unit_failed", "arm": arm, "tag": tag,
            "error": f"{type(exc).__name__}: {exc}",
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        raise
    finally:
        if work.exists():
            for child in sorted(work.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
            work.rmdir()


def run_arm(*, repo_root: Path, evidence_root: Path, arm: str,
            binary: Path, timeout_s: float,
            ) -> dict[str, Any]:
    """Execute an arm under the fail-closed stop law (unit-by-unit).

    Round-2 correction (review blocker 1): calls ONLY the production
    run_unit path — no fetch/execute/identity/health injection of any
    kind (tests patch internal production function objects instead).
    """
    results = []
    while True:
        try:
            outcome = run_unit(repo_root=repo_root,
                               evidence_root=evidence_root, arm=arm,
                               binary=binary, timeout_s=timeout_s)
        except ProducerError as exc:
            if "no next legal unit" in str(exc) and results:
                break
            raise
        results.append(outcome)
    retained = retained_tags(evidence_root, A.ARMS[arm]["namespace"])
    planned = planned_tags(arm)
    digest_map = {}
    for tag in retained:
        unit = Path(evidence_root) / A.ARMS[arm]["namespace"] / tag
        digest_map[tag] = (_sha(b"".join(
            (unit / f"obs.row{n}.f32").read_bytes()
            for n in range(D.DECISIONS))),)
    facts = D.prefix_population_facts(
        planned, retained, digest_map,
        deterministic_required=A.REPEAT_LAW["deterministic_requires"])
    return {"arm": arm, "units": results,
            "population": facts["population"],
            "stop_reason": facts.get("stop_reason")}


# ---------------------------------------------------------------------------
# Reducer-side admission: producer-attested physical evidence
# ---------------------------------------------------------------------------

def verify_unit_producer_binding(unit_dir: Path, receipt: dict[str, Any],
                                 expected_head: str) -> None:
    """Re-derive the producer attestation binding from retained bytes.

    The receipt alone (self-consistent bytes) is NOT physical authority: the
    retained producer attestation must exist, validate, match every digest
    the receipt carries, name the same unit/dispatch/head, and the retained
    live capture must independently re-verify (verify_live_capture).
    """
    att_path = Path(unit_dir) / "producer-attestation.json"
    if att_path.is_symlink() or not att_path.is_file():
        raise ProducerError("producer attestation missing (not physical)")
    att = json.loads(att_path.read_bytes())
    validate_producer_attestation(att)
    if att["producer_head"] != expected_head:
        raise ProducerError("producer attestation head mismatch")
    if (att["unit_index"] != receipt["unit_index"]
            or att["tag"] != receipt["tag"]):
        raise ProducerError("producer attestation unit mismatch")
    if att["dispatch_capture_comment_id"] != receipt["authority"].get(
            "comment_id"):
        raise ProducerError("producer attestation dispatch comment mismatch")
    if (att["server_pid"] != receipt["server_pid"]
            or att["server_argv"] != receipt["server_argv"]
            or att["server_env"] != receipt["server_env"]
            or att["comparator_sha256"] != receipt["binary_sha256"]
            or att["model_stat_witness"] != receipt["model_stat_witness"]
            or att["observer_meta_sha256"] != receipt["observer_meta_sha256"]
            or att["server_log_sha256"] != receipt["server_log_sha256"]
            or att["response_raw_sha256"] != receipt["response_raw_sha256"]
            or att["observer_row_sha256"] != receipt["observer_rows"]
            or att["placement"] != receipt["placement"]):
        raise ProducerError(
            "producer attestation does not bind the retained unit bytes")
    authority = receipt["authority"]
    producer_sha = authority.get("producer_attestation_sha256")
    if producer_sha is not None:
        # Optional producer digest carried INSIDE the live capture by the
        # producer at retention time (never required by the structural
        # law — binding is proven by these retained bytes, not a label).
        if (not isinstance(producer_sha, str)
                or producer_sha != _sha(json.dumps(
                    att, sort_keys=True).encode())):
            raise ProducerError(
                "live capture producer-attestation digest does not match "
                "retained attestation bytes")


def is_producer_attested(unit_dir: Path, receipt: dict[str, Any],
                         expected_head: str) -> bool:
    try:
        verify_unit_producer_binding(unit_dir, receipt, expected_head)
    except (ProducerError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    return True
