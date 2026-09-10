#!/usr/bin/env python3
"""Issue #133 — direct-vs-ordinary equality reducer (independent derivation).

Schema /2 — correction round for maintainer review 5172615768.

Compares, per case, deriving everything from retained raw evidence:

  1. committed token IDs at every position (ordinary: the Coordinator's
     retained per-request ``generated_token_ids`` cross-bound to the serving
     report's ``runtime_sessions`` step-0 ids under the frozen allocator;
     direct: per-case ``generated_token_ids``);
  2. committed token count (8) and per-call generated count (2);
  3. stop semantics (finish_reason == length);
  4. decoded output bytes for both arms;
  5. session/runtime identities (allocator sequence, plan digests);
  6. THE PHYSICAL INVOCATION SEAM THROUGH FIRST DIVERGENCE (new in /2):
     the ordinary Coordinator's physical ``serve_tokens`` call sequence is
     mechanically reconstructed from the frozen sources
     (``r5b_epochs.EpochServingController.serve_tokens`` → per-position
     ``xc_strategy.replay_input`` = ``prompt_token_ids +
     committed_token_ids`` → ``runtime.generate(session_id=…,
     prompt_token_ids=replay_input, max_new_tokens=2, on_token=…)``) and
     compared against the direct arm's retained invocation transcript,
     call by call, up to and including the call that produces each case's
     first divergent committed token.  After a committed-token divergence
     the replay prefixes differ BY CONSTRUCTION and are explicitly not
     required to remain equal;
  7. HTTP-content binding (new in /2): the ordinary HTTP ``content`` is
     checked for reproducibility from the frozen Coordinator's incremental
     decoding algorithm (``cpu_only.printable_increment`` prefix-holdback +
     ``coordinator._decode_incremental`` prefix diff + finished tail,
     vendored under frozen-source/924cd22e).  A content that binds to the
     incremental algorithm but differs from a one-shot
     ``decode(prompt+committed)`` is retained as a distinct
     ordinary-serving semantic observation (non-prefix-stable incremental
     decoding), NOT as an evidence problem and NOT masking the
     committed-token comparison.

No stored ``equal`` field is consumed anywhere.

Usage:
  issue133_equality_reduction.py DIRECT_DIR ORDINARY_CAMPAIGN
      SERVING_REPORT TOKENIZER_DIR [OUT]

TOKENIZER_DIR is the frozen tokenizer asset directory (the five pinned
assets).  When OUT is given the reduction is written there atomically.
"""
import hashlib
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

DIRECT_DIR = Path(sys.argv[1])
ORDINARY_CAMPAIGN = Path(sys.argv[2])
SERVING_REPORT = Path(sys.argv[3])
TOKENIZER = Path(sys.argv[4])
OUT = Path(sys.argv[5]) if len(sys.argv) > 5 else None

# Evidence root = physical-execution/ (parent of ordinary-http/) when the
# campaign layout is the retained one; derived from the serving report path.
PE = SERVING_REPORT.parent.parent
FIXTURE = PE.parent / "prompt-fixture.json"

from transformers import AutoTokenizer  # noqa: E402

# ---- frozen incremental-decoding algorithm (vendored producer bytes) -------
# Source: frozen-source/924cd22e/benchmarks/inferswarm_xc/cpu_only.py
# (printable_increment) and frozen-source/924cd22e/benchmarks/inferswarm_r6/
# coordinator.py (_decode_incremental).  Re-implemented verbatim here so the
# characterization is mechanical; the reducer refuses to run unless the
# vendored sources carry the pinned digests (checked by the terminal
# reducer; here we pin the exact semantics via constants below).

FROZEN_INCREMENTAL_BINDING = "frozen-coordinator-incremental-decode/1"


def _is_cjk(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F
        or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
        or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FAFF
    )


def _find_printable(text: str) -> str:
    if text.endswith("\n"):
        return text
    if text and len(text) > 1 and _is_cjk(ord(text[-2])):
        return text[:-1]
    if text and _is_cjk(ord(text[-1])):
        return text
    return text[: text.rfind(" ") + 1]


def printable_increment(decode, token_ids, *, finished: bool) -> str:
    decoded = decode(token_ids)
    if finished:
        return decoded
    return _find_printable(decoded)


def simulate_incremental_content(decode, prompt_ids, committed_ids):
    """Byte-exact simulation of the frozen Coordinator's HTTP content."""
    sent = ""
    parts = []
    for j in range(len(committed_ids)):
        whole = printable_increment(
            decode, prompt_ids + committed_ids[: j + 1], finished=False)
        parts.append(whole[len(sent):] if whole.startswith(sent) else "")
        sent = whole
    full = decode(prompt_ids + committed_ids)
    tail = full[len(sent):] if full.startswith(sent) else ""
    return "".join(parts) + tail


tok = AutoTokenizer.from_pretrained(
    str(TOKENIZER), trust_remote_code=False, local_files_only=True)

direct_cases = {}
for p in sorted(DIRECT_DIR.glob("direct-c109-*.json")):
    d = json.loads(p.read_text())
    direct_cases[d["case_id"]] = d

campaign = json.loads(ORDINARY_CAMPAIGN.read_text())
serving = json.loads(SERVING_REPORT.read_text())
fixture = json.loads(FIXTURE.read_text())
sessions = serving["epochs"][0]["runtime_sessions"]
crequests = serving["coordinator_scope"]["requests"]
csessions = serving["sessions"]
direct_run = json.loads((DIRECT_DIR / "direct-run.json").read_text())

by_logical = defaultdict(list)
for s in sessions:
    by_logical[s["session_id"] // 1_000_000].append(s)
for v in by_logical.values():
    v.sort(key=lambda s: s["session_id"])

problems = []
rows = []
records = campaign["records"]
if len(records) != 24:
    problems.append(f"ordinary records: {len(records)} != 24")
if len(direct_cases) != 24:
    problems.append(f"direct cases: {len(direct_cases)} != 24")
if len(crequests) != 25 or len(csessions) != 25:
    problems.append(
        f"coordinator requests/sessions {len(crequests)}/{len(csessions)}"
        " != 25/25")

serving_plan = serving["epochs"][0]["plan_digest"]

# request↔session binding must be by retained identity, never list order
# alone: the coordinator assigns session_id = len(request_log)+1 in arrival
# order and the campaign records carry request_session_index.
req_by_sid = {r["session_id"]: r for r in crequests}
if sorted(req_by_sid) != list(range(1, 26)):
    problems.append("coordinator request session ids not exactly 1..25")

# Bind transcript rows to cases via the results list (same order, verified
# by case_id equality below).
transcript_by_case = {}
for res, tr in zip(direct_run["results"],
                   direct_run["invocation_transcript"]):
    if res["case_id"] != tr["case_id"]:
        problems.append(
            f"direct transcript order drift at {res['case_id']}")
        continue
    transcript_by_case[res["case_id"]] = tr

http_discrepancy_cases = []

for i, rec in enumerate(records):
    case_id = rec["case_id"]
    logical = rec["request_session_index"]
    d = direct_cases.get(case_id)
    if d is None:
        problems.append(f"{case_id}: no direct case")
        continue
    if logical != i + 1:
        problems.append(
            f"{case_id}: request_session_index {logical} != arrival {i+1}")
    req = req_by_sid.get(logical)
    if req is None:
        problems.append(f"{case_id}: no coordinator request for session"
                        f" {logical}")
        continue
    if req.get("fencing_arm_injections"):
        problems.append(f"{case_id}: ordinary request carries fencing"
                        " injections")
    body = rec.get("response_body") or rec["response"]
    choices = body["choices"][0]
    finish = choices["finish_reason"]
    content = choices["message"]["content"]

    fixture_case = fixture["cases"][i]
    if fixture_case["case_id"] != case_id:
        problems.append(f"{case_id}: fixture order drift at {i}")

    # ---- prompt identity across all three retained sources ----
    ord_prompt = list(req["prompt_token_ids"])
    fx_prompt = list(fixture_case["rendered_prompt_token_ids"])
    dir_prompt = list(d["prompt_token_ids"])
    prompts_equal = ord_prompt == fx_prompt == dir_prompt
    if not prompts_equal:
        problems.append(
            f"{case_id}: ordinary coordinator prompt ids != frozen fixture"
            " / direct prompt ids")

    # ---- committed ids, both arms, from raw retained bytes ----
    ord_ids = [int(x) for x in req["generated_token_ids"]]
    dir_ids = list(d["generated_token_ids"])

    # bind ordinary committed ids to the runtime sessions (allocator rule:
    # runtime_id = logical*1_000_000 + global sequence; for logical L the
    # eight calls are sequences 8*(L-1)+1 .. 8*L in both arms)
    case_sessions = by_logical.get(logical, [])
    if len(case_sessions) != 8:
        problems.append(f"{case_id}: {len(case_sessions)} runtime sessions"
                        " != 8")
        continue
    expected_runtime_ids = [
        logical * 1_000_000 + 8 * (logical - 1) + j + 1 for j in range(8)]
    runtime_ids = [s["session_id"] for s in case_sessions]
    if runtime_ids != expected_runtime_ids:
        problems.append(
            f"{case_id}: runtime allocator sequence drift {runtime_ids}")
    for j, s in enumerate(case_sessions):
        if len(s["generated_token_ids"]) != 2:
            problems.append(
                f"{case_id}: runtime session {s['session_id']} generated"
                f" {len(s['generated_token_ids'])} != 2")
        if s["plan_digest"] != serving_plan:
            problems.append(f"{case_id}: runtime session plan digest drift")
    # the committed id at position j IS the step-0 id of runtime session j
    for j, s in enumerate(case_sessions):
        if j < len(ord_ids) and s["generated_token_ids"][:1] != ord_ids[j:j + 1]:
            problems.append(
                f"{case_id}: committed id at position {j} not bound to"
                " runtime step-0 observation")
    # token_events attribution must agree with the committed sequence
    ev_positions = [e["position"] for e in req["token_events"]]
    ev_ids = [e["token_id"] for e in req["token_events"]]
    if ev_positions != list(range(len(ev_ids))) or ev_ids != ord_ids:
        problems.append(
            f"{case_id}: token_events attribution drift")

    if len(dir_ids) != 8 or len(ord_ids) != 8:
        problems.append(
            f"{case_id}: committed count direct={len(dir_ids)}"
            f" ordinary={len(ord_ids)} != 8")
    if finish != "length":
        problems.append(f"{case_id}: finish {finish} != length")

    # ---- invocation seam through first divergence ----
    tr = transcript_by_case.get(case_id)
    if tr is None:
        problems.append(f"{case_id}: no direct invocation transcript")
        continue
    calls = tr["calls"]
    if len(calls) != 8:
        problems.append(
            f"{case_id}: direct transcript {len(calls)} calls != 8")
        continue
    fdiv = next((j for j, (a, b) in enumerate(zip(ord_ids, dir_ids))
                 if a != b), None)
    # per-call input equivalence for every call up to and including the
    # first divergent one (for equal cases: all eight calls)
    seam_checks = []
    for j in range(8):
        c = calls[j]
        ord_prefix = ord_prompt + ord_ids[:j]
        dir_input = list(c["prompt_token_ids"])
        seam = {
            "position": j,
            "ordinary_runtime_session_id": expected_runtime_ids[j],
            "direct_runtime_session_id": c.get("runtime_session_id"),
            "ordinary_input_ids": ord_prefix,
            "direct_input_ids": dir_input,
            "max_new_tokens": c.get("max_new_tokens"),
            "on_token_present": c.get("on_token_present"),
            "direct_committed_step0": c.get("committed_token"),
            "direct_discarded_step1": c.get("speculative_discarded"),
            "ordinary_step0_runtime": (
                case_sessions[j]["generated_token_ids"][0]
                if len(case_sessions[j]["generated_token_ids"]) == 2
                else None),
            "ordinary_step1_discarded_runtime": (
                case_sessions[j]["generated_token_ids"][1]
                if len(case_sessions[j]["generated_token_ids"]) == 2
                else None),
        }
        seam["inputs_equal"] = (
            seam["ordinary_input_ids"] == seam["direct_input_ids"])
        seam["session_ids_equal"] = (
            seam["ordinary_runtime_session_id"]
            == seam["direct_runtime_session_id"])
        seam["call_shape_equal"] = (
            seam["max_new_tokens"] == 2 and seam["on_token_present"] is True)
        # commit-step-zero / discard-step-one semantics on both arms
        # (speculative_discarded is the retained LIST of discarded ids —
        # exactly the step-1+ tail of response_token_ids)
        seam["commit_step_zero_semantics"] = (
            seam["direct_committed_step0"]
            == (calls[j].get("response_token_ids") or [None])[0]
            and seam["ordinary_step0_runtime"] == ord_ids[j])
        seam["discard_step_one_semantics"] = (
            list(calls[j].get("speculative_discarded") or [])
            == list(calls[j].get("response_token_ids") or [None, None])[1:])
        seam_checks.append(seam)
    checked = (fdiv + 1) if fdiv is not None else 8
    pre_divergence_equivalent = all(
        s["inputs_equal"] and s["session_ids_equal"]
        and s["call_shape_equal"] and s["commit_step_zero_semantics"]
        and s["discard_step_one_semantics"]
        for s in seam_checks[:checked])
    # post-divergence inputs differ by construction; assert they differ
    # exactly by the committed prefix (no other drift) only in shape:
    for s in seam_checks[checked:]:
        if not s["call_shape_equal"] or not s["session_ids_equal"]:
            problems.append(
                f"{case_id}: call-shape/session drift after divergence")

    # ---- decodes and HTTP-content characterization ----
    ord_decode = tok.decode(ord_prompt + ord_ids)
    dir_decode = tok.decode(dir_prompt + dir_ids)
    incr_sim = simulate_incremental_content(
        lambda ids: tok.decode(ids), ord_prompt, ord_ids)
    binds_incremental = incr_sim == content
    binds_full = ord_decode == content
    if not binds_incremental:
        problems.append(
            f"{case_id}: HTTP content not reproducible from frozen"
            " coordinator incremental decoding (evidence-binding defect)")
    if not binds_full:
        http_discrepancy_cases.append(case_id)

    rows.append({
        "case_id": case_id,
        "logical_session": logical,
        "runtime_session_ids": runtime_ids,
        "first_divergent_position": fdiv,
        "pre_divergence_inputs_equivalent": pre_divergence_equivalent,
        "prompts_equal_across_sources": prompts_equal,
        "committed_ids_equal": list(ord_ids) == dir_ids,
        "decoded_equal": ord_decode == dir_decode,
        "ordinary_committed_token_ids": ord_ids,
        "direct_committed_token_ids": dir_ids,
        "direct_full_decode_sha256": hashlib.sha256(
            dir_decode.encode(errors="surrogatepass")).hexdigest(),
        "ordinary_full_decode_sha256": hashlib.sha256(
            ord_decode.encode(errors="surrogatepass")).hexdigest(),
        "ordinary_http_content_sha256": hashlib.sha256(
            content.encode(errors="surrogatepass")).hexdigest(),
        "http_content": {
            "binds_frozen_incremental_decode": binds_incremental,
            "binds_one_shot_full_decode": binds_full,
            "binding": FROZEN_INCREMENTAL_BINDING if binds_incremental
            else None,
        },
        "finish_reason": finish,
        "committed_count": len(dir_ids),
        "invocation_seam": [
            {k: v for k, v in s.items()
             if k not in ("ordinary_input_ids", "direct_input_ids")}
            | {"input_ids_sha256": hashlib.sha256(
                json.dumps(v, separators=(",", ":")).encode()).hexdigest(),
               "inputs_equal": s["inputs_equal"]}
            for s, v in ((s, s["ordinary_input_ids"])
                         for s in seam_checks)],
    })

equal_count = sum(1 for r in rows if r["committed_ids_equal"])
inv_equiv_all = all(r["pre_divergence_inputs_equivalent"] and
                    r["prompts_equal_across_sources"] for r in rows)
http_characterized = all(
    r["http_content"]["binds_frozen_incremental_decode"] for r in rows)

result = {
    "schema": "inferswarm.issue133.arm-c-retry.equality-reduction/2",
    "case_count": len(rows),
    "equal_count": equal_count,
    "serving_plan_digest": serving_plan,
    "invocation_equivalence": {
        "premise": "ordinary and direct model-execution inputs identical"
                   " through the call producing each case's first"
                   " divergent committed token (frozen #129/#133"
                   " comparator contract)",
        "holds": inv_equiv_all,
        "first_divergent_positions": {
            r["case_id"]: r["first_divergent_position"] for r in rows
            if r["first_divergent_position"] is not None},
        "post_divergence_note": "after a committed-token divergence the"
        " replay prefixes differ by construction; equality of inputs is"
        " not required past the first divergent position",
    },
    "http_content_characterization": {
        "all_bind_frozen_incremental_decode": http_characterized,
        "binding": FROZEN_INCREMENTAL_BINDING,
        "algorithm": "cpu_only.printable_increment prefix-holdback +"
                     " coordinator._decode_incremental prefix diff +"
                     " finished tail (vendored frozen producer bytes)",
        "cases_differing_from_one_shot_decode": http_discrepancy_cases,
        "classification": "distinct ordinary-serving semantic observation:"
                          " non-prefix-stable incremental decoding" if
        http_characterized else "evidence-binding defect",
    },
    "rows": rows,
    "problems": problems,
    "passed": not problems and equal_count == 24,
}
text = json.dumps(result, indent=2, sort_keys=True) + "\n"
if OUT is not None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(OUT.parent), suffix=".tmp")
    try:
        os.write(fd, text.encode())
        os.close(fd)
        os.replace(tmp, OUT)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
print(text)
sys.exit(0 if result["passed"] else 1)
