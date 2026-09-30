#!/usr/bin/env python3
"""#252 prospective, structural-only physical contract. NO runner or execution.

A comment is a live authority only when the caller fetches the PR, issue and
TOP-LEVEL PR conversation comment immediately before EACH unit. The pure gate
also accepts an offline snapshot for fixture verification; a snapshot alone
never grants physical authority. No code in this module launches a server.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import issue252_constants as C
import issue252_phase0 as P0
import issue252_arms as A
import issue250_diagnostic as D  # accepted byte-exact request and full-row geometry

UNIT_SCHEMA = "inferswarm.issue252.prospective-unit/1"
PORT = 19000
LLAMA_ROOT = Path("/home/zutfen/llama.cpp-252")
MODEL_DIR = Path("/srv/models/qwen38-ud-iq1-s")
ICD = "/usr/share/vulkan/icd.d/nvidia_icd.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX256 = re.compile(r"[0-9a-f]{64}\Z")


class DispatchRefused(ValueError):
    """A unit cannot start under this snapshot."""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise DispatchRefused(f"repository git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_dispatch_comment(api_url: str) -> dict[str, Any]:
    """Thin GET-only seam. Caller must fetch PR, issue and comment individually.

    Never invoked at import or by verify_dispatch; injectable with a synthetic
    fetcher in offline tests. The caller must assemble one fresh snapshot.
    """
    if not api_url.startswith("https://api.github.com/repos/Zutfen-LLC/inferswarm/"):
        raise DispatchRefused("dispatch fetch URL is not the canonical repository API")
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue252"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def verify_dispatch(comment: dict[str, Any], repo_root: Path,
                    pr_head: str) -> dict[str, Any]:
    """Validate a *fresh* PR/issue/comment snapshot and immutable parents.

    Snapshot keys: body, author_association, id, issue_url, pr (GitHub pulls
    object), issue (GitHub issues object). The comment must be from the PR's
    conversation endpoint, not a review, issue #252, or arbitrary comment.
    No cached snapshot may be passed to a physical runner as live authority.
    """
    if not isinstance(comment, dict):
        raise DispatchRefused("dispatch snapshot missing")
    body = comment.get("body")
    if not isinstance(body, str) or len(body.splitlines()) != 3:
        raise DispatchRefused("dispatch body must have exactly three lines")
    phrase, head_line, arm_line = body.splitlines()
    if phrase != C.DISPATCH_PHRASE_FORMAT:
        raise DispatchRefused("dispatch phrase mismatch")
    if not head_line.startswith("head=") or not SHA.fullmatch(head_line[5:]):
        raise DispatchRefused("dispatch head malformed")
    if not arm_line.startswith("arm=") or arm_line[4:] not in A.ARMS:
        raise DispatchRefused("dispatch arm unknown")
    arm = arm_line[4:]
    spec = A.ARMS[arm]
    if not isinstance(pr_head, str) or not SHA.fullmatch(pr_head):
        raise DispatchRefused("PR head malformed")
    if head_line[5:] != pr_head:
        raise DispatchRefused("dispatch head moved")
    if comment.get("author_association") not in ("OWNER", "MEMBER"):
        raise DispatchRefused("dispatch author is not OWNER/MEMBER")
    pr, issue = comment.get("pr"), comment.get("issue")
    if not isinstance(pr, dict) or not isinstance(issue, dict):
        raise DispatchRefused("live PR/issue state missing")
    if issue.get("state") != "open" or issue.get("number") != C.ISSUE:
        raise DispatchRefused("issue #252 is not open")
    if pr.get("state") != "open" or pr.get("merged") is not False or pr.get("draft") is not False:
        raise DispatchRefused("PR is not open, unmerged and non-draft")
    if not isinstance(pr.get("head"), dict) or pr["head"].get("sha") != pr_head:
        raise DispatchRefused("PR head moved")
    if not isinstance(pr.get("base"), dict) or pr["base"].get("ref") != "main":
        raise DispatchRefused("PR base is not main")
    number = pr.get("number")
    if type(number) is not int or number <= 0 or comment.get("issue_url") != (
            f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{number}"):
        raise DispatchRefused("comment is not a top-level PR conversation comment")
    if type(comment.get("id")) is not int or comment["id"] <= 0:
        raise DispatchRefused("dispatch comment ID missing")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                        str(comment.get("created_at", ""))):
        raise DispatchRefused("dispatch comment creation timestamp missing")
    if comment.get("namespace") != spec["namespace"]:
        raise DispatchRefused("dispatch namespace/arm mismatch")
    if A.validate_arms():
        raise DispatchRefused("frozen arms invalid")
    if _git(Path(repo_root), "rev-parse", "HEAD") != pr_head:
        raise DispatchRefused("repository HEAD differs from PR head")
    if _git(Path(repo_root), "status", "--porcelain", "--untracked-files=all"):
        raise DispatchRefused("repository branch is dirty")
    branch = _git(Path(repo_root), "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        raise DispatchRefused("repository detached HEAD")
    if pr["head"].get("ref") != branch:
        raise DispatchRefused("repository branch differs from live PR branch")
    try:
        terminal = P0.verify_terminalization(Path(repo_root))
        pin = P0.verify_llama_pin(LLAMA_ROOT)
    except Exception as exc:
        raise DispatchRefused(f"retained parent authority unauthenticated: {exc}") from exc
    if (not isinstance(terminal, dict) or terminal.get("terminal") != C.PREDECESSOR_TERMINAL
            or terminal.get("execution_head") != C.ACCEPTED_EXECUTION_HEAD
            or not isinstance(pin, dict) or pin.get("head") != C.LLAMA_PIN
            or pin.get("tree") != C.LLAMA_PIN_TREE):
        raise DispatchRefused("retained parent authority unauthenticated")
    return {"head_sha": pr_head, "arm": arm, "namespace": spec["namespace"],
            "comment_id": comment["id"], "body": body,
            "body_sha256": _digest(body.encode("utf-8")),
            "author_association": comment["author_association"],
            "issue_number": C.ISSUE, "pr_number": number,
            "parent_terminalization_head": C.ACCEPTED_TERMINALIZATION_HEAD}


def launch_geometry(arm: str, binary: Path, model_member: Path,
                    observer_dir: Path) -> dict[str, Any]:
    """Build inert argv/env strings; never spawn a process.

    The caller must independently attest the binary/member bytes and record
    their observed identities; a pathname is not a hash witness.
    """
    if arm not in A.ARMS or A.validate_arms():
        raise ValueError("unknown/invalid frozen arm")
    spec = A.ARMS[arm]
    if spec["geometry"] != {"ngl": 1, "case": "case-3072",
                            "fresh_process_per_unit": True,
                            "request_contract": "byte-exact accepted #241/#250"}:
        raise ValueError("arm geometry drift")
    if Path(model_member) != MODEL_DIR / next(iter(C.MODEL_MEMBERS)):
        raise ValueError("model launch member is not frozen member 1/path")
    if not str(binary) or not str(observer_dir):
        raise ValueError("binary/observer path missing")
    argv = [str(binary), "--model", str(model_member), "-ngl", "1",
            "--ctx-size", "8192", "--batch-size", "512", "--host",
            "127.0.0.1", "--port", str(PORT)]
    env = {"CUDA_VISIBLE_DEVICES": "-1", "VK_ICD_FILENAMES": ICD,
           "GGML_VK_VISIBLE_DEVICES": "0", "LLAMA_OBSERVE_CAPTURE": "8",
           "LLAMA_OBSERVE_OUT": str(observer_dir), "LLAMA_OBSERVE_FORCE": ""}
    if spec["control"]["kind"] != "env":
        raise ValueError("unimplemented control kind (no implicit argv delta)")
    env[spec["control"]["name"]] = "1"
    return {"argv": argv, "env": env, "arm": arm,
            "namespace": spec["namespace"], "control": spec["control"],
            "geometry": dict(spec["geometry"])}


def build_unit_receipt(*, authority: dict[str, Any], unit_index: int,
                       binary: Path, model_member: Path, observer_dir: Path,
                       identity_pre: dict[str, Any], identity_post: dict[str, Any],
                       placement: dict[str, Any], raw_response: bytes,
                       rows: list[bytes], observer_meta: bytes,
                       server_log: bytes, server_pid: int,
                       model_stat_witness: dict[str, Any],
                       request: dict[str, Any], fix_commit: str | None = None,
                       binary_sha256: str = C.COMPARATOR_SHA256) -> dict[str, Any]:
    """Construct a receipt from supplied observations (not a producer).

    Supplied observations have NO authority until validate_unit_receipt and
    retained-byte re-derivation have both passed. No default custody facts.
    """
    arm = authority["arm"]
    geom = launch_geometry(arm, binary, model_member, observer_dir)
    if type(unit_index) is not int or not 1 <= unit_index <= 5:
        raise ValueError("unit index must be 001..005")
    rec = {"schema": UNIT_SCHEMA, "head_sha": authority["head_sha"],
           "authority": dict(authority), "arm": arm,
           "namespace": geom["namespace"], "unit_index": unit_index,
           "tag": f"case-3072-B-{arm.lower()}-{unit_index:03d}",
           "control": geom["control"], "geometry": geom["geometry"],
           "server_argv": geom["argv"], "server_env": geom["env"],
           "server_pid": server_pid, "binary_sha256": binary_sha256,
           "fix_commit": fix_commit,
           "model_members": dict(C.MODEL_MEMBERS),
           "model_launch_member": str(model_member),
           "model_stat_witness": model_stat_witness,
           "llama_pin": C.LLAMA_PIN, "llama_pin_tree": C.LLAMA_PIN_TREE,
           "host_facts": dict(C.HOST_FACTS), "identity_pre": identity_pre,
           "identity_post": identity_post, "placement": placement,
           "request": request, "response_raw_sha256": _digest(raw_response),
           "response_raw_bytes": len(raw_response),
           "observer_rows": [_digest(row) for row in rows],
           "observer_row_bytes": [len(row) for row in rows],
           "observer_meta_sha256": _digest(observer_meta),
           "server_log_sha256": _digest(server_log)}
    validate_unit_receipt(rec)
    return rec


def validate_unit_receipt(receipt: dict[str, Any]) -> None:
    """Fail-closed structural/cross-binding check; no claim of physical proof."""
    r = receipt
    if not isinstance(r, dict) or r.get("schema") != UNIT_SCHEMA:
        raise ValueError("receipt schema mismatch")
    arm = r.get("arm")
    if arm not in A.ARMS or A.validate_arms():
        raise ValueError("receipt arm unknown")
    spec = A.ARMS[arm]
    auth = r.get("authority")
    if (not isinstance(auth, dict) or auth.get("arm") != arm
            or auth.get("namespace") != spec["namespace"]
            or auth.get("head_sha") != r.get("head_sha")
            or auth.get("issue_number") != C.ISSUE
            or auth.get("parent_terminalization_head") != C.ACCEPTED_TERMINALIZATION_HEAD
            or auth.get("author_association") not in ("OWNER", "MEMBER")
            or type(auth.get("comment_id")) is not int or auth["comment_id"] <= 0
            or not isinstance(auth.get("body"), str)
            or auth["body"] != f"{C.DISPATCH_PHRASE_FORMAT}\nhead={r.get('head_sha')}\narm={arm}"
            or auth.get("body_sha256") != _digest(auth["body"].encode())
            or not isinstance(r.get("head_sha"), str) or not SHA.fullmatch(r["head_sha"])):
        raise ValueError("receipt dispatch authority/head mismatch")
    index = r.get("unit_index")
    if (type(index) is not int or not 1 <= index <= 5
            or r.get("tag") != f"case-3072-B-{arm.lower()}-{index:03d}"):
        raise ValueError("receipt unit tag/index mismatch")
    if (r.get("namespace") != spec["namespace"] or r.get("control") != spec["control"]
            or r.get("geometry") != spec["geometry"]):
        raise ValueError("receipt arm/control/namespace geometry mismatch")
    argv, env = r.get("server_argv"), r.get("server_env")
    if (not isinstance(argv, list) or len(argv) != 13
            or not isinstance(env, dict) or not isinstance(env.get("LLAMA_OBSERVE_OUT"), str)
            or not env["LLAMA_OBSERVE_OUT"] or not isinstance(r.get("model_launch_member"), str)):
        raise ValueError("receipt argv/env/observer path missing")
    geometry = launch_geometry(arm, Path(argv[0]), Path(r["model_launch_member"]),
                               Path(env["LLAMA_OBSERVE_OUT"]))
    if argv != geometry["argv"] or env != geometry["env"]:
        raise ValueError("receipt argv/env differs from frozen one-factor geometry")
    if ((r.get("fix_commit") is None and r.get("binary_sha256") != C.COMPARATOR_SHA256)
            or (r.get("fix_commit") is not None and
                (not isinstance(r["fix_commit"], str) or not SHA.fullmatch(r["fix_commit"])
                 or not isinstance(r.get("binary_sha256"), str)
                 or not HEX256.fullmatch(r["binary_sha256"])
                 or r["binary_sha256"] == C.COMPARATOR_SHA256))
            or r.get("llama_pin") != C.LLAMA_PIN
            or r.get("llama_pin_tree") != C.LLAMA_PIN_TREE
            or r.get("model_members") != C.MODEL_MEMBERS
            or r.get("host_facts") != C.HOST_FACTS):
        raise ValueError("receipt source/model/host identity mismatch")
    witness = r.get("model_stat_witness")
    if (not isinstance(witness, dict) or set(witness) != set(C.MODEL_MEMBERS)
            or any(not isinstance(v, dict) or
                   set(v) != {"bytes", "device", "inode", "mtime_ns", "ctime_ns"} or
                   any(type(n) is not int or n < 0 for n in v.values())
                   for v in witness.values())):
        raise ValueError("receipt model stat witness missing or malformed")
    for key in ("identity_pre", "identity_post"):
        identity = r.get(key)
        if (not isinstance(identity, dict) or
                any(identity.get(k) != v for k, v in C.HOST_FACTS.items())):
            raise ValueError(f"receipt {key} identity missing or drifted")
    placement = r.get("placement")
    if (not isinstance(placement, dict) or
            placement.get("output_projection") != "Vulkan" or
            placement.get("embedding") != "CPU" or
            placement.get("ngl") != 1 or
            placement.get("gpu_uuid") != C.HOST_FACTS["gpu_uuid"]):
        raise ValueError("receipt Vulkan placement observation missing")
    if r.get("request") != D.REQUEST_CONTRACT:
        raise ValueError("receipt byte-exact accepted request identity mismatch")
    if type(r.get("server_pid")) is not int or r["server_pid"] <= 0:
        raise ValueError("receipt server PID missing")
    for key in ("response_raw_sha256", "observer_meta_sha256", "server_log_sha256"):
        if not isinstance(r.get(key), str) or not HEX256.fullmatch(r[key]):
            raise ValueError(f"receipt {key} custody missing")
    rows, lengths = r.get("observer_rows"), r.get("observer_row_bytes")
    if (not isinstance(rows, list) or len(rows) != D.DECISIONS or
            not isinstance(lengths, list) or len(rows) != len(lengths) or
            any(not isinstance(h, str) or not HEX256.fullmatch(h) for h in rows) or
            any(type(n) is not int or n != D.ROW_BYTES for n in lengths) or
            type(r.get("response_raw_bytes")) is not int or r["response_raw_bytes"] <= 0):
        raise ValueError("receipt raw response/full row bytes custody missing")
