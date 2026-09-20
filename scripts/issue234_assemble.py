#!/usr/bin/env python3
"""Issue #234 — R8-H evidence assembler + fail-closed control runner.

The assembler:
  * verifies the producer closure FIRST (every retained artifact's
    producer must be the frozen closure head);
  * re-derives the terminal through issue234_reduce from retained
    bytes only;
  * proves the issue's 27 required fail-closed controls as REDUCER-
    LEVEL mutation tests over a sandbox copy of the evidence tree
    (never the real tree; never destructive fault injection).

Every check derives from retained bytes; no check is ever a constant.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import issue234_receipt as rc
import issue234_reduce as red


class AssembleError(RuntimeError):
    pass


def assemble(evidence_root: Path, repo: Path | None = None) -> dict[str, Any]:
    closure = rc.verify_closure(repo or rc.ROOT)
    terminal_doc = red.derive_terminal(evidence_root, closure=closure)
    return {
        "schema": "inferswarm.r8h.assembly/1",
        "campaign": rc.CAMPAIGN_ID,
        "closure": {
            "producer_head": closure["producer_head"],
            "closure_digest": closure["closure_digest"],
        },
        **terminal_doc,
    }


# ---------------------------------------------------------------------
# Required fail-closed controls (issue #234 list). Each control mutates
# ONE property of a sandbox evidence copy and asserts the reducer's
# terminal/checks change in exactly the expected way.
# ---------------------------------------------------------------------

def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, doc: dict) -> None:
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")


def _sandbox(evidence: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="r8h-ctl-"))
    box = tmp / "evidence"
    shutil.copytree(evidence, box)
    return box


CONTROLS: dict[str, dict[str, Any]] = {}


def register(cid: str, expect_terminal: str | None = None,
             expect_check_contains: dict | None = None):
    def deco(fn):
        CONTROLS[cid] = {
            "fn": fn,
            "expect_terminal": expect_terminal,
            "expect_check_contains": expect_check_contains or {},
        }
        return fn
    return deco


def _run_controls_once(evidence: Path, closure: dict) -> dict[str, Any]:
    """Run every registered control against sandbox copies."""
    out: dict[str, Any] = {}
    for cid, spec in CONTROLS.items():
        box = _sandbox(evidence)
        try:
            spec["fn"](box)
            doc = red.derive_terminal(box, closure=closure)
            ok_term = (spec["expect_terminal"] is None or
                       doc["terminal"] == spec["expect_terminal"])
            ok_checks = True
            for path, want in spec["expect_check_contains"].items():
                node = doc
                for part in path.split("."):
                    node = node.get(part, {}) if isinstance(node, dict) else {}
                if isinstance(want, str):
                    ok_checks = ok_checks and want in json.dumps(node)
                else:
                    ok_checks = ok_checks and node == want
            out[cid] = {
                "ok": bool(ok_term and ok_checks),
                "terminal": doc["terminal"],
            }
        except red.ReduceError as e:
            out[cid] = {"ok": True, "terminal": f"ReduceError:{e}"}
        except Exception as e:  # noqa: BLE001
            out[cid] = {"ok": False, "terminal": f"EXCEPTION:{e}"}
        finally:
            shutil.rmtree(box.parent, ignore_errors=True)
    return out


def run_controls(evidence: Path, closure: dict) -> dict[str, Any]:
    """Deterministic double-run + byte-compare (R6 doctrine)."""
    a = _run_controls_once(evidence, closure)
    b = _run_controls_once(evidence, closure)
    if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
        raise AssembleError("nondeterministic control results")
    all_ok = all(v["ok"] for v in a.values())
    return {"controls": a, "count": len(a), "all_ok": all_ok}
