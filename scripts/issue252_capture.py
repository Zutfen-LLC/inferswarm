"""#252 retained dispatch-custody contract: retrieval-bound authority.

Live authorization (verify_dispatch in issue252_physical) and retrospective
evidence admission (the retained-byte reducer) are deliberately SEPARATE:

- the LIVE gate freshly fetches PR, issue and exact comment immediately before
  each unit and emits a canonical retained capture bound to those raw bytes;
- the REDUCER consumes only the retained capture, and re-authenticates it by
  INDEPENDENTLY RE-FETCHING the immutable GitHub comment by exact ID through
  the PRODUCTION HTTPS SEAM ONLY (issue252_physical.fetch_dispatch_comment),
  requiring every authentication-bearing field of the live comment to equal
  the retained capture bytes. A locally fabricated, merely self-consistent
  authority object can never satisfy admission because the retained fields
  must byte-equal a real GitHub API comment — and no API in this module or
  the reducer accepts a caller-supplied fetcher.

Immutable comment fields (id, body, author_association, created_at, html_url,
user.login, issue_url) never change after creation, so this re-fetch is not a
dependence on mutable current GitHub state: PR state/merged/draft and issue
state are authenticated against the RETAINED execution-time snapshot only,
never re-derived from the live repository at reduction time.

No code in this module performs a physical launch, and no fetch happens at
import time. Network access occurs only inside the production seam
(issue252_physical.fetch_dispatch_comment) when verify_capture re-fetches
a retained comment; the verify API has no fetch parameter.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import issue252_constants as C
import issue252_arms as A

CAPTURE_SCHEMA = "inferswarm.issue252.dispatch-capture/2"
SHA = re.compile(r"[0-9a-f]{40}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
API_ROOT = "https://api.github.com/repos/Zutfen-LLC/inferswarm"
# The PR conversation endpoint of THIS repository, exactly. A comment captured
# from any other endpoint (issue #252's own timeline, a review, an inline
# review comment, another repository) is not admissible.
COMMENTS_URL_PREFIX = API_ROOT + "/issues/comments/"

# The production fetch seam (issue252_physical.fetch_dispatch_comment) is
# the ONLY re-fetch implementation; no API in this module accepts a
# caller-supplied fetcher, so there is no fetcher type alias here.


class CaptureInvalid(ValueError):
    """A retained capture or its re-fetch does not authenticate."""


# Authentication-bearing comment fields. Every one must equal the independently
# re-fetched live comment at reduction time; none is trusted because it is
# internally consistent with the rest of the capture.
AUTH_FIELDS = ("author_association", "body", "created_at", "html_url", "id",
               "issue_url", "user")


def canonical_bytes(comment: dict[str, Any]) -> bytes:
    """Canonical retained raw-comment bytes: sorted, compact, UTF-8.

    The capture pins these bytes; any later mutation of retained raw bytes is
    detectable by digest and by re-fetch comparison.
    """
    subset = {k: comment[k] for k in sorted(AUTH_FIELDS) if k in comment}
    return json.dumps(subset, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _user_login(comment: dict[str, Any]) -> Any:
    user = comment.get("user")
    return user.get("login") if isinstance(user, dict) else None


def validate_capture_body(comment: dict[str, Any], *, repo_pr_number: int) -> str:
    """Validate the immutable comment shape and exact dispatch body law.

    Returns the arm. Raises CaptureInvalid on any failure. Pure: no fetch.
    """
    if not isinstance(comment, dict):
        raise CaptureInvalid("comment object missing")
    body = comment.get("body")
    if not isinstance(body, str) or len(body.splitlines()) != 3:
        raise CaptureInvalid("dispatch body must have exactly three lines")
    phrase, head_line, arm_line = body.splitlines()
    if phrase != C.DISPATCH_PHRASE_FORMAT:
        raise CaptureInvalid("dispatch phrase mismatch")
    if not head_line.startswith("head=") or not SHA.fullmatch(head_line[5:]):
        raise CaptureInvalid("dispatch head malformed")
    if not arm_line.startswith("arm=") or arm_line[4:] not in A.ARMS:
        raise CaptureInvalid("dispatch arm unknown")
    arm = arm_line[4:]
    if comment.get("author_association") not in ("OWNER", "MEMBER"):
        raise CaptureInvalid("dispatch author is not OWNER/MEMBER")
    if type(comment.get("id")) is not int or comment["id"] <= 0:
        raise CaptureInvalid("dispatch comment ID missing")
    if not TIMESTAMP.fullmatch(str(comment.get("created_at", ""))):
        raise CaptureInvalid("dispatch comment creation timestamp missing")
    expected_issue_url = f"{API_ROOT}/issues/{repo_pr_number}"
    if comment.get("issue_url") != expected_issue_url:
        raise CaptureInvalid(
            "comment is not a top-level PR conversation comment of this PR")
    html_url = comment.get("html_url")
    if not isinstance(html_url, str) or html_url != (
            f"https://github.com/Zutfen-LLC/inferswarm/pull/{repo_pr_number}"
            f"#issuecomment-{comment['id']}"):
        raise CaptureInvalid("comment html_url is not a PR conversation comment")
    if not isinstance(_user_login(comment), str) or not _user_login(comment):
        raise CaptureInvalid("commenter login missing")
    return arm


def build_capture(comment: dict[str, Any], *, pr: dict[str, Any],
                  issue: dict[str, Any], repo_pr_number: int) -> dict[str, Any]:
    """Emit the retained capture the LIVE gate must retain per dispatch.

    Validates the immutable comment law, then binds the execution-time mutable
    state (PR open/unmerged/non-draft targeting main, exact PR head, issue
    open, arm-to-namespace mapping) into the retained snapshot with pinned
    SHA-256 custody over the canonical raw comment bytes.
    """
    arm = validate_capture_body(comment, repo_pr_number=repo_pr_number)
    spec = A.ARMS[arm]
    head = comment["body"].splitlines()[1][5:]
    if not isinstance(pr, dict) or not isinstance(issue, dict):
        raise CaptureInvalid("live PR/issue state missing")
    if issue.get("state") != "open" or issue.get("number") != C.ISSUE:
        raise CaptureInvalid("issue #252 is not open")
    # The snapshot's own PR number must equal the campaign PR: the capture
    # must not be emittable claiming PR 253 from a comment/PR pair whose
    # live snapshot says otherwise (adversarial probe: pr.number = -1).
    if type(pr.get("number")) is not int or pr["number"] != repo_pr_number:
        raise CaptureInvalid("live PR snapshot is not the campaign PR")
    if pr.get("state") != "open" or pr.get("merged") is not False or pr.get("draft") is not False:
        raise CaptureInvalid("PR is not open, unmerged and non-draft")
    if not isinstance(pr.get("head"), dict) or pr["head"].get("sha") != head:
        raise CaptureInvalid("PR head does not equal authorized execution head")
    if not isinstance(pr.get("base"), dict) or pr["base"].get("ref") != "main":
        raise CaptureInvalid("PR does not target main")
    raw = canonical_bytes(comment)
    return {
        "schema": CAPTURE_SCHEMA,
        "repo": "Zutfen-LLC/inferswarm",
        "pr_number": repo_pr_number,
        "issue_number": C.ISSUE,
        "head_sha": head,
        "arm": arm,
        "namespace": spec["namespace"],
        "comment_id": comment["id"],
        "commenter_login": _user_login(comment),
        "author_association": comment["author_association"],
        "created_at": comment["created_at"],
        "body": comment["body"],
        "raw_comment_sha256": hashlib.sha256(raw).hexdigest(),
        "execution_time_state": {
            "pr_open": True, "pr_merged": False, "pr_draft": False,
            "pr_base_ref": "main", "pr_head": head,
            "issue_state": "open",
        },
    }


def validate_capture_structure(retained: dict[str, Any]) -> dict[str, Any]:
    """Structural law of a retained capture. Pure; no fetch.

    Consumed both by reducer-side verify_capture (before the independent
    re-fetch) and by unit-receipt validation. Establishes internal structure
    ONLY -- never sufficient for authority admission on its own.
    """
    if not isinstance(retained, dict) or retained.get("schema") != CAPTURE_SCHEMA:
        raise CaptureInvalid("retained capture schema mismatch")
    if retained.get("repo") != "Zutfen-LLC/inferswarm":
        raise CaptureInvalid("retained capture is not for this repository")
    arm = retained.get("arm")
    if arm not in A.ARMS or A.validate_arms():
        raise CaptureInvalid("retained capture arm unknown/invalid")
    head = retained.get("head_sha")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise CaptureInvalid("retained capture head malformed")
    if retained.get("namespace") != A.ARMS[arm]["namespace"]:
        raise CaptureInvalid("retained capture namespace/arm mismatch")
    body = retained.get("body")
    if not isinstance(body, str) or body != (
            f"{C.DISPATCH_PHRASE_FORMAT}\nhead={head}\narm={arm}"):
        raise CaptureInvalid("retained capture body law mismatch")
    if type(retained.get("comment_id")) is not int or retained["comment_id"] <= 0:
        raise CaptureInvalid("retained capture comment ID missing")
    if retained.get("pr_number") != C.CAMPAIGN_PR:
        raise CaptureInvalid("retained capture PR number mismatch")
    if retained.get("issue_number") != C.ISSUE:
        raise CaptureInvalid("retained capture issue number mismatch")
    if retained.get("author_association") not in ("OWNER", "MEMBER"):
        raise CaptureInvalid("retained capture author not OWNER/MEMBER")
    if not isinstance(retained.get("raw_comment_sha256"), str) or len(
            retained["raw_comment_sha256"]) != 64:
        raise CaptureInvalid("retained capture raw digest malformed")
    state = retained.get("execution_time_state")
    if not isinstance(state, dict) or state != {
            "pr_open": True, "pr_merged": False, "pr_draft": False,
            "pr_base_ref": "main", "pr_head": head, "issue_state": "open"}:
        raise CaptureInvalid("retained execution-time state law mismatch")
    return retained


def verify_capture(retained: dict[str, Any], *,
                   repo_pr_number: int) -> dict[str, Any]:
    """Reducer-side admission of a RETAINED capture. Fail closed.

    Requires, in order:
      1. retained capture structural law (schema, repo, PR number, arm,
         namespace, head, body, digests);
      2. INDEPENDENT re-fetch of the exact comment by ID through the
         PRODUCTION GitHub HTTPS seam (issue252_physical.
         fetch_dispatch_comment) — there is NO fetch parameter, so no
         caller of this API can substitute an authority fetcher;
      3. every authentication-bearing live field byte-equal to the retained
         capture (self-consistency of the retained object proves nothing);
      4. live comment still satisfies the immutable comment law.

    Returns the authenticated capture. Never trusts caller-supplied
    author_association, comment ID, PR state, or body.

    TRUST BOUNDARY: the only fetch implementation is the production HTTPS
    seam, which enforces the canonical-repository URL prefix and real
    network transport. A caller-supplied callable is NOT independent
    GitHub authority — a lambda serving a local dictionary can satisfy any
    digest check — and is structurally unrepresentable through this API
 (round-4 adversarial review; previously a runtime boolean check).
 Offline synthetic-fixture tests verify the same law by patching the
 production fetch function object with a standard unittest seam owned
 by the test (FixtureMixin.offline_authority_fetch), never through
 this API.
 """
    validate_capture_structure(retained)
    if type(repo_pr_number) is not int or retained.get("pr_number") != repo_pr_number:
        raise CaptureInvalid("retained capture PR number mismatch")
    # Deferred import: issue252_physical imports this module.
    import issue252_physical as _P
    arm = retained["arm"]
    head = retained["head_sha"]

    # Independent retrieval of the real GitHub comment by exact ID.
    url = f"{COMMENTS_URL_PREFIX}{retained['comment_id']}"
    try:
        live = _P.fetch_dispatch_comment(url)
    except _P.DispatchRefused as exc:
        raise CaptureInvalid(f"dispatch comment re-fetch refused: {exc}") from exc
    except OSError as exc:
        # transport failure (offline host, timeout, DNS): fail closed as a
        # capture-invalid admission, never a crash-to-caller
        raise CaptureInvalid(
            f"dispatch comment re-fetch transport failure: {exc}") from exc
    if not isinstance(live, dict):
        raise CaptureInvalid("re-fetched comment object missing")
    live_raw = canonical_bytes(live)
    if hashlib.sha256(live_raw).hexdigest() != retained.get("raw_comment_sha256"):
        raise CaptureInvalid("re-fetched comment bytes differ from retained capture")
    live_arm = validate_capture_body(live, repo_pr_number=repo_pr_number)
    if live_arm != arm:
        raise CaptureInvalid("re-fetched comment arm differs from retained capture")
    # Belt-and-braces per-field equality for every authentication-bearing
    # field the capture retains (digest equality above already implies all
    # of these plus html_url/issue_url/user, which the live-law validation
    # additionally constrains to this PR's conversation).
    if live.get("id") != retained.get("comment_id"):
        raise CaptureInvalid("re-fetched comment id differs")
    for field, retained_key in (("author_association", "author_association"),
                                ("body", "body"),
                                ("created_at", "created_at")):
        if live.get(field) != retained.get(retained_key):
            raise CaptureInvalid(f"re-fetched comment {field} differs")
    if _user_login(live) != retained.get("commenter_login"):
        raise CaptureInvalid("re-fetched commenter login differs")
    return retained


def load_capture(root: Path, rel: str) -> dict[str, Any]:
    path = Path(root) / rel
    if path.is_symlink() or not path.is_file():
        raise CaptureInvalid(f"retained capture missing/unsafe: {rel}")
    try:
        doc = json.loads(path.read_bytes())
    except json.JSONDecodeError as exc:
        raise CaptureInvalid(f"retained capture malformed: {rel}") from exc
    if not isinstance(doc, dict):
        raise CaptureInvalid(f"retained capture object missing: {rel}")
    return doc
