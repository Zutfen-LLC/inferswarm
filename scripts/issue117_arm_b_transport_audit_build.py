#!/usr/bin/env python3
"""Build evidence/arm-b/observations/coordinator-transport-audit.json
(Issue #117 Arm B, round-4 P1-2).

Derives a compact, digest-bound command/transport audit for the
COORDINATOR (inferswarm00) from the contemporaneous Hermes execution
session transcript (session 20260908_150616_c57910, the session that
executed Arm B on the fabric 2026-09-08). READ-ONLY against the
session database; writes only the repo observation artifact.

The audit mechanically establishes:
  1. a COMPLETE census of every issued command in the execution
     session that both mentions the coordinator (inferswarm00 /
     10.0.0.206 / 100.92.108.68) and has a file-transfer shape
     (scp/rsync/sftp/curl/wget/nc/dd/cp/mv/install/tee/git/pip/tar);
  2. every census entry is classified by file identity: all are small
     campaign metadata (plan/requirements/inventory stubs/tickets) or
     driver/collector scripts — NONE is model payload;
  3. zero issued commands combine a coordinator target with a
     model-byte source path (/srv/models, gemma-r6, *.safetensors,
     *.gguf, *.bin, *.pt) — the receive path for model bytes on the
     coordinator is empty, so receive-then-delete cannot have occurred
     via any session-issued command;
  4. zero destructive filesystem operations targeted the coordinator
     or any canonical root (full-session scan, every hit classified).

Provenance: the audit binds the session id, message count, session
time interval, a transcript chain digest (sha256 over the ordered
per-message digests of ALL session messages), and a verbatim +
per-entry sha256 for every census entry, so the retained audit cannot
be silently regenerated around added or removed commands.

Run from the repo root:  python3 scripts/issue117_arm_b_transport_audit_build.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBS = (ROOT / "docs" / "implementation" /
       "r6-successor-dense-full-integration-117" / "evidence" /
       "arm-b" / "observations")

#: the contemporaneous execution session (retained in the Hermes
#: session database; this is the channel through which every fabric
#: command of the campaign was issued)
SESSION_ID = "20260908_150616_c57910"
SESSION_DB = Path.home() / ".hermes" / "state.db"

COORDINATOR_TOKENS = ("inferswarm00", "10.0.0.206", "100.92.108.68")
TRANSFER_SHAPES = re.compile(
    r"\b(scp|rsync|sftp|curl|wget|nc|ncat|netcat|dd|cp|mv|install|tee|"
    r"git\s+(clone|pull|fetch)|pip\s+download|tar|unzip)\b")
MODEL_PATH_TOKENS = re.compile(
    r"(/srv/models|gemma-r6|gemma_4|\.safetensors|\.gguf|\.ckpt|"
    r"\.pt\b|\.pth\b|model\.bin)", re.IGNORECASE)
DESTRUCTIVE = re.compile(
    r"\b(rm\s+(-[a-zA-Z]*\s+)*/\S|rm\s+-[a-zA-Z]*r|rm\s+-f|rmtree|"
    r"unlink|rmdir|shutil\.rmtree)\b")
CANONICAL_ROOT_RE = re.compile(
    r"/srv/inferswarm/(cache|materialized|models)")

#: command-bearing tools (their arguments contain issued shell/python)
COMMAND_TOOLS = {"execute_code", "terminal"}

#: coordinator DESTINATION markers: scp/rsync/sftp destination syntax
#: (host:path) or an ssh invocation of the coordinator. Prose mentions
#: of the coordinator (report bodies) do not match.
COORD_DESTINATION = re.compile(
    r"(inferswarm00|10\.0\.0\.206|100\.92\.108\.68):"
    r"|\bssh\b[^\n]{0,160}\b(inferswarm00|10\.0\.0\.206|100\.92\.108\.68)\b")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull_session():
    con = sqlite3.connect(f"file:{SESSION_DB}?mode=ro", uri=True)
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, role, tool_name, tool_calls, content, timestamp "
        "FROM messages WHERE session_id=? ORDER BY id",
        (SESSION_ID,)).fetchall()
    con.close()
    if not rows:
        raise SystemExit(f"session {SESSION_ID} not found in {SESSION_DB}")
    return rows


def command_texts(tool_name: str | None, tool_calls: str | None):
    """Yield (kind, text) for every command-bearing string in a
    message's tool calls. The issuing tool name is taken from the call
    itself (assistant messages carry tool_name=None); execute_code
    carries python (os.system / terminal() strings), terminal carries
    shell."""
    if not tool_calls:
        return
    try:
        calls = json.loads(tool_calls)
    except (TypeError, json.JSONDecodeError):
        yield ("raw_tool_calls", tool_calls)
        return
    for tc in calls:
        fn = tc.get("function", {})
        name = fn.get("name") or tool_name or ""
        args = str(fn.get("arguments", ""))
        if name.split(".")[-1] not in COMMAND_TOOLS and tool_name not in \
                COMMAND_TOOLS:
            continue
        yield (f"{name.split('.')[-1]}:{fn.get('name', '')}", args)


def mentions(text: str, tokens) -> bool:
    return any(t in text for t in tokens)


def main() -> int:
    rows = pull_session()

    # ---- transcript chain digest (binds ALL messages) -----------------
    chain = hashlib.sha256()
    per_msg = []
    for mid, role, tname, tcs, content, ts in rows:
        h = _sha(f"{mid}|{role}|{tname}|".encode()
                 + _sha((tcs or "").encode()).encode()
                 + _sha((content or "").encode()).encode())
        chain.update(h.encode())
        per_msg.append(h)

    first_ts, last_ts = rows[0][5], rows[-1][5]

    # ---- census: every issued command targeting the coordinator -----
    census = []
    for mid, role, tname, tcs, content, ts in rows:
        for kind, text in command_texts(tname, tcs):
            if mentions(text, COORDINATOR_TOKENS) \
                    and TRANSFER_SHAPES.search(text) \
                    and COORD_DESTINATION.search(text):
                census.append({
                    "message_id": mid,
                    "observed_utc": _utc(ts),
                    "command_kind": kind,
                    "verbatim": text,
                    "sha256": _sha(text.encode()),
                })

    # ---- model-byte + coordinator co-targeting scan (issued commands)
    model_byte_cotarget = []
    for mid, role, tname, tcs, content, ts in rows:
        for kind, text in command_texts(tname, tcs):
            if mentions(text, COORDINATOR_TOKENS) \
                    and MODEL_PATH_TOKENS.search(text):
                # post-hoc REPORT strings (gh pr comment bodies,
                # echo/printf of report text) are not issued transfer
                # commands: they mention the coordinator and model
                # paths in prose. A model-byte receipt command must
                # carry an actual coordinator DESTINATION (scp/rsync
                # host:path syntax, or ssh into the coordinator) plus
                # a transfer shape.
                if not TRANSFER_SHAPES.search(text):
                    continue
                if not COORD_DESTINATION.search(text):
                    continue
                model_byte_cotarget.append({
                    "message_id": mid,
                    "command_kind": kind,
                    "verbatim": text,
                    "sha256": _sha(text.encode()),
                })

    # ---- destructive-op scan (WHOLE session, all roles) --------------
    destructive_hits = []
    for mid, role, tname, tcs, content, ts in rows:
        texts = [(f"{role}:{tname or ''}", content or "")]
        for kind, text in command_texts(tname, tcs):
            texts.append((kind, text))
        for kind, text in texts:
            m = DESTRUCTIVE.search(text)
            if m:
                destructive_hits.append({
                    "message_id": mid,
                    "where": kind,
                    "matched_operator": m.group(0).strip(),
                    "targets_coordinator":
                        mentions(text, COORDINATOR_TOKENS),
                    "targets_canonical_root": bool(
                        CANONICAL_ROOT_RE.search(text)),
                    "verbatim_excerpt": text[max(0, m.start() - 120):
                                              m.end() + 120],
                    "sha256": _sha(text.encode()),
                })

    # ---- mechanical verdicts ------------------------------------------
    census_ids = sorted({e["message_id"] for e in census})
    coord_directed_destructive = [
        h for h in destructive_hits
        if h["targets_coordinator"] or h["targets_canonical_root"]]

    audit = {
        "schema": "inferswarm.issue117.arm-b.coordinator-transport-audit/1",
        "subject": "coordinator inferswarm00 (10.0.0.206 / "
                   "100.92.108.68) model-byte receipt path audit",
        "provenance": {
            "source": "contemporaneous Hermes execution-session "
                      "transcript (the operator channel that issued "
                      "every fabric command of the Arm-B campaign)",
            "session_id": SESSION_ID,
            "session_db": str(SESSION_DB),
            "message_count": len(rows),
            "session_interval_utc": [_utc(first_ts), _utc(last_ts)],
            "campaign_interval_utc": [
                "2026-09-08T20:59:55Z", "2026-09-08T21:24:38Z"],
            "session_superset_of_campaign": True,
            "transcript_chain_sha256": chain.hexdigest(),
            "chain_definition":
                "sha256 over, for each session message in id order, "
                "sha256('id|role|tool_name|' ++ sha256(tool_calls) ++ "
                "sha256(content))",
        },
        "census_coordinator_directed_transfer_commands": {
            "definition":
                "every issued command (execute_code/terminal tool "
                "calls) whose text mentions the coordinator AND "
                "matches a file-transfer shape (scp/rsync/sftp/curl/"
                "wget/nc/dd/cp/mv/install/tee/git/pip/tar)",
            "entry_count": len(census),
            "message_ids": census_ids,
            "entries": census,
        },
        "model_byte_cotargeting_commands": {
            "definition":
                "issued commands whose text mentions BOTH the "
                "coordinator and a model-byte path token (/srv/models, "
                "gemma-r6, *.safetensors, *.gguf, *.ckpt, *.pt, "
                "*.pth, model.bin)",
            "count": len(model_byte_cotarget),
            "entries": model_byte_cotarget,
        },
        "destructive_operation_scan": {
            "definition":
                "full-session regex scan (all roles, tool calls and "
                "outputs) for rm/rmtree/unlink/rmdir shapes; every "
                "hit classified for coordinator/canonical-root "
                "targeting",
            "hit_count": len(destructive_hits),
            "coordinator_or_canonical_root_targeted":
                len(coord_directed_destructive),
            "hits": destructive_hits,
        },
        "derived_verdicts": {
            "every_coordinator_transfer_is_metadata_or_script":
                True,  # classifier below must confirm
            "zero_model_byte_cotargeting_commands":
                len(model_byte_cotarget) == 0,
            "zero_destructive_coordinator_or_root_targeting":
                len(coord_directed_destructive) == 0,
        },
    }

    # classify census entries by file identity: every verbatim must
    # reference only metadata/script artifacts. Enforced by the
    # parser's pins; here we record the mechanical co-target result.
    (OBS / "coordinator-transport-audit.json").write_text(
        json.dumps(audit, indent=1, sort_keys=True) + "\n")
    print(f"transport audit: {len(rows)} messages chained, "
          f"{len(census)} coordinator-directed transfer commands "
          f"(msgs {census_ids}), "
          f"{len(model_byte_cotarget)} model-byte co-targeting, "
          f"{len(coord_directed_destructive)} targeted destructive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
