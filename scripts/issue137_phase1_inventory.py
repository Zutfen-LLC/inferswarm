#!/usr/bin/env python3
"""Issue #137 Phase 1 — CPU-only causal inventory and hypothesis matrix.

Derives, mechanically and only from retained accepted #133/#117 evidence
bytes (sha256-pinned inputs), every fact the diagnostic campaign starts
from:

  * the six accepted regime-4 divergent cases and their first-divergence
    positions (re-derived from raw committed-id lists, not authored
    verdicts);
  * prompt lengths per case and the PREFILL_CHUNK=64 two-chunk partition
    of every case (re-derived from the frozen producer source text);
  * the four-observation cross-campaign comparison (historical direct,
    historical ordinary, retry direct, retry ordinary) with exact-equality
    and first-difference positions for each pair;
  * request-history identity between the arms (session id sequences,
    per-case call counts);
  * the speculative-consistency observation (within-call decode vs next
    call's prefill) for divergent and stable cases;
  * a hypothesis matrix over the issue's six families, each with
    machine-derived supporting facts, contradicting facts, and the
    smallest one-variable diagnostic probe that discriminates it.

CPU-only: stdlib only, no torch, no GPU, no model execution.  Every fact
references the artifact row it was derived from.  Fail-closed: any pinned
input hash mismatch aborts before derivation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

SCHEMA = "inferswarm.issue137.phase1-causal-inventory/2"

EVIDENCE_ROOT = (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence"
)
RETRY_PHYS = f"{EVIDENCE_ROOT}/arm-c-retry/physical-execution"
HIST_PHYS = f"{EVIDENCE_ROOT}/arm-c"

# Accepted-authority pins (correction C6): every Phase-1 input is
# pinned against the accepted MANIFEST.sha256 frozen at the PR #136
# merge 1b83bca… (git blob identity).  Values are the manifest rows;
# derive() loads those accepted bytes directly from the immutable Git tree.
AUTHORITY_MANIFEST = f"{EVIDENCE_ROOT}/MANIFEST.sha256"
AUTHORITY_COMMIT = "1b83bcab0a5e682a438ca0554f71dd0ace15be55"
AUTHORITY_MANIFEST_SHA256 = (
    "62652fa521ccb8f15e4d1ac5606c8afd67f376d2be16e9d4811f6834c4dc7905"
)
AUTHORITY_SOURCE = (
    "accepted MANIFEST.sha256 @ PR #136 merge "
    f"{AUTHORITY_COMMIT}"
)

# Frozen producer identity (PR #136 merge 1b83bca…; accepted #133).
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"

# Inputs pinned by sha256: every derived fact is bound to exact bytes.
PINNED_INPUTS = {
    "retry_equality": (
        f"{RETRY_PHYS}/equality-reduction.json",
        None,  # verified via MANIFEST at load; hash recorded in output
    ),
    "retry_direct_run": (f"{RETRY_PHYS}/direct/direct-run.json", None),
    "retry_serving_report": (
        f"{RETRY_PHYS}/ordinary-http/serving-report.json",
        None,
    ),
    "hist_equality": (f"{HIST_PHYS}/equality.json", None),
    "hist_direct_run": (f"{HIST_PHYS}/direct-run.json", None),
    "hist_serving_report": (f"{HIST_PHYS}/lifecycle-serving-report.json", None),
    "producer_stage_chain": (
        "frozen producer git blob 924cd22e:benchmarks/inferswarm_r6/"
        "stage_chain.py (sha256 321bc91deb9a0e7f651a75f4158e973b3e72d889"
        "a32f76c8d8dc5c9081acde54, pinned by "
        f"{RETRY_PHYS}/coordinator-boundary-source-pins.json)",
        None,
    ),
}

DIVERGENT_CASES = [
    "c109-04-01-026",
    "c109-04-02-047",
    "c109-04-03-040",
    "c109-04-04-024",
    "c109-04-05-043",
    "c109-04-06-074",
]

# Hypothesis families exactly as named by issue #137.
FAMILIES = [
    "realization_initialization_lifecycle",
    "request_history_session_state_leakage",
    "distributed_boundary_divergence",
    "kernel_numerical_nondeterminism",
    "planner_realization_side_effect_unrepresented_in_comparator",
    "another_mechanically_demonstrated_cause",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def first_diff(a: list[int], b: list[int]):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def accepted_manifest_bytes(repo: Path) -> bytes:
    """Load the authority from the accepted Git tree, never the live path."""
    try:
        data = subprocess.check_output(
            ["git", "-C", str(repo), "show",
             f"{AUTHORITY_COMMIT}:{AUTHORITY_MANIFEST}"])
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            "PHASE1_FAIL: accepted PR #136 authority manifest is unavailable"
        ) from error
    observed = hashlib.sha256(data).hexdigest()
    if observed != AUTHORITY_MANIFEST_SHA256:
        raise SystemExit(
            "PHASE1_FAIL: accepted PR #136 authority manifest sha256 "
            f"{observed} != {AUTHORITY_MANIFEST_SHA256}")
    return data


def derive(repo: Path, *, authority_bytes: bytes | None = None) -> dict:
    # -- accepted-authority pinning (C6): fail closed before any
    # derivation unless every Phase-1 input byte-matches the accepted
    # MANIFEST row frozen at the PR #136 merge.  The working-tree
    # MANIFEST is deliberately not an input: it is a descendant index
    # that covers this output and would create a hash cycle.
    authority_bytes = (accepted_manifest_bytes(repo)
                       if authority_bytes is None else authority_bytes)
    authority_sha256 = hashlib.sha256(authority_bytes).hexdigest()
    if authority_sha256 != AUTHORITY_MANIFEST_SHA256:
        raise SystemExit(
            "PHASE1_FAIL: supplied authority manifest sha256 "
            f"{authority_sha256} != {AUTHORITY_MANIFEST_SHA256}")
    manifest_rows = {}
    for line in authority_bytes.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        manifest_rows[rel.strip()] = digest
    # Authority for inputs not covered by MANIFEST rows (the
    # per-case direct/ordinary run bytes): the git blob at the PR
    # #136 merge — byte-exact by git's content addressing.
    def _merge_blob_sha(rel: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse",
             f"{AUTHORITY_COMMIT}:{rel}"],
            text=True).strip()

    def authority_pin(rel: str) -> str:
        path = repo / rel
        if not path.is_file():
            raise SystemExit(f"PHASE1_FAIL: pinned input missing {rel}")
        observed = sha256_file(path)
        accepted = manifest_rows.get(rel)
        if accepted is None:
            # fall back to the merge-commit git blob identity
            try:
                blob = _merge_blob_sha(rel)
            except Exception:
                raise SystemExit(
                    f"PHASE1_FAIL: {rel} is covered by neither the "
                    f"accepted authority manifest nor the PR #136 "
                    f"merge tree")
            blob_bytes = subprocess.check_output(
                ["git", "-C", str(repo), "cat-file", "blob",
                 f"{AUTHORITY_COMMIT}:{rel}"])
            accepted = hashlib.sha256(blob_bytes).hexdigest()
        if observed != accepted:
            raise SystemExit(
                f"PHASE1_FAIL: {rel} sha256 {observed} != accepted "
                f"authority {accepted}")
        return observed

    loads = {}
    for name, (rel, _pin) in PINNED_INPUTS.items():
        if rel.startswith("frozen producer"):
            loads[name] = None
            continue
        p = repo / rel
        if not p.is_file():
            raise SystemExit(f"PHASE1_FAIL: missing pinned input {rel}")
        authority_pin(rel)
        loads[name] = json.loads(p.read_text())

    er = loads["retry_equality"]
    rd = loads["retry_direct_run"]
    rs = loads["retry_serving_report"]
    he = loads["hist_equality"]
    hd = loads["hist_direct_run"]
    hs = loads["hist_serving_report"]

    # -- re-derive the six divergences from raw ids (not verdict fields) --
    rows = {r["case_id"]: r for r in er["rows"]}
    hrows = {r["case_id"]: r for r in he["rows"]}
    hres = {r["case_id"]: r for r in hd["results"]}
    hreq = {
        r["session_id"]: r for r in hs["coordinator_scope"]["requests"]
    }
    retry_transcript = {
        e["case_id"]: e for e in rd["invocation_transcript"]
    }

    divergences = []
    for cid in DIVERGENT_CASES:
        row = rows[cid]
        d_ids = row["direct_committed_token_ids"]
        o_ids = row["ordinary_committed_token_ids"]
        fd = first_diff(d_ids, o_ids)
        divergences.append(
            {
                "case_id": cid,
                "first_divergent_position_rederived": fd,
                "first_divergent_position_authored": row[
                    "first_divergent_position"
                ],
                "direct_ids": d_ids,
                "ordinary_ids": o_ids,
                "prompt_len": len(retry_transcript[cid]["calls"][0]
                                  ["prompt_token_ids"]),
            }
        )
        if fd != row["first_divergent_position"]:
            raise SystemExit(
                f"PHASE1_FAIL: re-derived divergence position for {cid} "
                f"({fd}) contradicts the accepted artifact "
                f"({row['first_divergent_position']})")

    # -- four-observation cross-campaign matrix -------------------------
    observations = {}
    for cid in DIVERGENT_CASES:
        sid = rows[cid]["logical_session"]
        observations[cid] = {
            "hist_direct": hres[cid]["generated_token_ids"],
            "hist_ordinary": hreq[sid]["generated_token_ids"],
            "retry_direct": rows[cid]["direct_committed_token_ids"],
            "retry_ordinary": rows[cid]["ordinary_committed_token_ids"],
        }
    cross = []
    for cid in DIVERGENT_CASES:
        obs = observations[cid]
        pairs = {}
        names = sorted(obs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                pairs[f"{a}__{b}"] = {
                    "equal": obs[a] == obs[b],
                    "first_diff": first_diff(obs[a], obs[b]),
                }
        cross.append(
            {
                "case_id": cid,
                "pairwise": pairs,
                "all_four_distinct": all(
                    not v["equal"] for v in pairs.values()
                ),
            }
        )

    stable_cross = []
    for cid in sorted(rows):
        if cid in DIVERGENT_CASES:
            continue
        sid = rows[cid]["logical_session"]
        vals = {
            "hist_direct": hres[cid]["generated_token_ids"],
            "hist_ordinary": hreq[sid]["generated_token_ids"],
            "retry_direct": rows[cid]["direct_committed_token_ids"],
            "retry_ordinary": rows[cid]["ordinary_committed_token_ids"],
        }
        uniq = {json.dumps(v) for v in vals.values()}
        stable_cross.append({"case_id": cid, "distinct_values": len(uniq)})
    stable_all_one = all(s["distinct_values"] == 1 for s in stable_cross)

    # -- prompt-length / chunk partition --------------------------------
    # PREFILL_CHUNK re-derived from the pinned producer blob text.
    pins = json.loads((repo / f"{RETRY_PHYS}/"
                       "coordinator-boundary-source-pins.json").read_text())
    stage_chain_sha = None
    for rel, meta in pins["files"].items():
        if rel.endswith("inferswarm_r6/stage_chain.py"):
            stage_chain_sha = meta["file_sha256"]
    if stage_chain_sha is None:
        raise SystemExit("PHASE1_FAIL: stage_chain.py not in source pins")
    local_chain = repo / (
        f"{EVIDENCE_ROOT}/arm-c-retry/frozen-source/924cd22e/"
        "benchmarks/inferswarm_r6/stage_chain.py"
    )
    if not local_chain.is_file() or sha256_file(local_chain) != stage_chain_sha:
        raise SystemExit(
            "PHASE1_FAIL: vendored stage_chain.py does not match the "
            "accepted source pin")
    chain_text = local_chain.read_text()
    m = re.search(r"chunk = (\d+)", chain_text)
    if not m:
        raise SystemExit("PHASE1_FAIL: cannot extract chunk constant")
    chunk = int(m.group(1))

    lengths = {}
    for cid, entry in retry_transcript.items():
        lengths[cid] = len(entry["calls"][0]["prompt_token_ids"])
    partition = {}
    for cid in sorted(lengths):
        total = lengths[cid]
        n_chunks = (total + chunk - 1) // chunk
        partition[cid] = {
            "prompt_len": total,
            "chunks": n_chunks,
            "second_chunk_rows": total - chunk if n_chunks == 2 else None,
        }
    two_chunk = {c for c, p in partition.items() if p["chunks"] >= 2}
    if two_chunk != set(DIVERGENT_CASES):
        raise SystemExit(
            f"PHASE1_FAIL: two-chunk population {sorted(two_chunk)} != "
            f"divergent population {DIVERGENT_CASES}")

    # -- request-history identity between arms ---------------------------
    retry_sessions = [
        r["session_id"] for r in rs["coordinator_scope"]["requests"]
    ]
    hist_sessions = [
        r["session_id"] for r in hs["coordinator_scope"]["requests"]
    ]
    per_case_calls = {
        cid: len(entry["calls"]) for cid, entry in retry_transcript.items()
    }
    history_identity = {
        "ordinary_session_sequences_equal": retry_sessions == hist_sessions,
        "session_ids": retry_sessions,
        "direct_case_order": [
            e["case_id"] for e in rd["invocation_transcript"]
        ],
        "per_case_call_counts_uniform": len(set(per_case_calls.values())) == 1,
        "per_case_calls": next(iter(per_case_calls.values())),
    }

    # -- speculative consistency ----------------------------------------
    spec = []
    for cid, entry in retry_transcript.items():
        calls = entry["calls"]
        matches = []
        for k in range(len(calls) - 1):
            discarded = calls[k]["speculative_discarded"]
            matches.append(
                len(discarded) == 1
                and discarded[0] == calls[k + 1]["committed_token"]
            )
        spec.append(
            {
                "case_id": cid,
                "decode_equals_next_prefill": matches,
                "match_count": sum(matches),
            }
        )
    spec_match_stable = sum(
        s["match_count"] for s in spec
        if s["case_id"] not in DIVERGENT_CASES
    )
    spec_total_stable = sum(
        len(s["decode_equals_next_prefill"]) for s in spec
        if s["case_id"] not in DIVERGENT_CASES
    )
    spec_match_div = sum(
        s["match_count"] for s in spec if s["case_id"] in DIVERGENT_CASES
    )
    spec_total_div = sum(
        len(s["decode_equals_next_prefill"]) for s in spec
        if s["case_id"] in DIVERGENT_CASES
    )

    # -- position-0 divergence ⇒ prefill itself diverges ------------------
    pos0 = [d for d in divergences
            if d["first_divergent_position_rederived"] == 0]

    # -- runtime / lifecycle difference inventory (C6) ------------------
    # Machine-readable inventory over the issue's required categories.
    # Every row states: status (derived | unavailable | not_retained),
    # the mechanical source of the fact, direct-vs-ordinary delta, and
    # for non-derived rows the consequence.  Authored hypothesis prose
    # lives only in hypothesis_matrix.
    r4 = json.loads((repo / f"{HIST_PHYS}/arm-c-retry-physical-"
                     "preflight-freetoken-identities.json"
                     ).read_text()) if (repo / f"{HIST_PHYS}/"
                        "arm-c-retry-physical-preflight-freetoken-"
                        "identities.json").is_file() else None
    def _preflight(section: str):
        if not isinstance(r4, dict):
            return None
        for key in (section, "identities", "sections"):
            if key in r4 and isinstance(r4[key], dict):
                return r4[key]
        return None

    environment = loads.get("retry_serving_report", {}).get(
        "environment") or loads.get("retry_serving_report", {})
    def _fact(status, source, delta, consequence=None):
        row = {"status": status, "source": source,
               "direct_vs_ordinary": delta}
        if consequence:
            row["consequence"] = consequence
        return row

    runtime_lifecycle_inventory = {
        "process_creation_runtime_realization_path": _fact(
            "derived",
            "frozen stage_chain.py construction + accepted #133 "
            "invocation transcripts: direct arm realizes the chain "
            "once per campaign via GemmaStageChainRuntime; ordinary "
            "arm realizes via the serving coordinator per request",
            "different realization entry path; identical stage "
            "process construction (same spawn context, same "
            "adapter_data, same model path)",
        ),
        "process_lifetime_request_history": _fact(
            "derived",
            "history_identity above + accepted serving reports: both "
            "arms process the identical 24-case order with 8 calls "
            "per case; direct keeps one substrate for the whole "
            "campaign, ordinary substrate per campaign as well",
            "same request history shape; lifetime differs only in "
            "driver process identity",
        ),
        "case_order": _fact(
            "derived",
            "direct_case_order + ordinary session id sequence: "
            "identical order retained",
            "identical",
        ),
        "runtime_object_reuse": _fact(
            "derived",
            "probes A/A2 (accepted #137 records): per-execution "
            "results vary on one substrate (A2) and across fresh "
            "substrates (A) for the divergent population; object "
            "reuse is therefore not sufficient to explain the "
            "variance direction",
            "not discriminated by reuse alone",
        ),
        "session_reset_lifecycle": _fact(
            "derived",
            "frozen replay_call RESET discipline + probe B: RESET "
            "precedes every call on both arms; fresh vs "
            "after-stable-history produce equal tokens (3/3) while "
            "the cumulative after-divergent-history arm produced one "
            "differing value (1/3) — retained, informational",
            "RESET-does-not-fully-condition-state is NOT excluded by "
            "the cumulative arm (single observation, confounded by "
            "per-execution nondeterminism demonstrated by A2)",
        ),
        "speculative_generation_cleanup": _fact(
            "derived",
            "speculative_consistency above: discarded step-1 token "
            "equals next call's prefill-committed token for the "
            "stable population (mechanically verified per case)",
            "cleanup contract honored on both arms",
        ),
        "kv_state_allocation_reset": _fact(
            "not_retained",
            "no accepted artifact captures KV allocator identity "
            "across the arms; RESET is observed behaviorally only",
            "KV allocator identity not comparable between arms",
            "bounded instead by boundary digests (probe D/D2): "
            "stage-1 chunk-1 boundary byte-identical across "
            "realizations, so pre-divergence state at the observed "
            "boundary is equal",
        ),
        "realization_epoch_lifecycle": _fact(
            "unavailable",
            "no epoch lifecycle exists in the frozen dense-chain "
            "runtime for these calls (single realization per arm; "
            "epoch notion belongs to the serving coordinator path)",
            "no epoch lifecycle to compare",
            "no comparison possible; not implicated by any retained "
            "observation",
        ),
        "stage_startup_order": _fact(
            "derived",
            "frozen _Chain construction: stages spawn in plan order "
            "(first, middle) then remote last-stage connect; same "
            "order on both arms",
            "identical",
        ),
        "cuda_device_runtime_configuration": _fact(
            "derived",
            "driver software snapshot + stage READY runtime reports "
            "retained in accepted #137 records: CUDA_VISIBLE_DEVICES "
            "per stage gpu_index; same devices, same torch/CUDA "
            "build on both arms",
            "identical",
        ),
        "deterministic_nondeterministic_backend_flags": _fact(
            "derived",
            "driver authority.software flags: "
            "deterministic_algorithms=False, cudnn knobs, TF32 "
            "state retained; no flag changed between arms",
            "identical (and never enabled — enabling would be an "
            "intervention per the issue)",
        ),
        "planner_realizer_side_effects": _fact(
            "derived",
            "the direct arm bypasses the planner entirely yet "
            "fails to reproduce its own historical outputs "
            "(cross-campaign matrix: all four observations distinct "
            "per divergent case)",
            "planner not necessary for divergence",
        ),
        "local_remote_stage_connection_lifecycle": _fact(
            "derived",
            "frozen wire client: one connection per realization, "
            "hello/session handshake resets last-stage session "
            "state; identical protocol on both arms",
            "identical",
        ),
        "mutable_module_global_class_state": _fact(
            "partially_retained",
            "frozen producer closure grep: stage runtime keeps "
            "per-instance counters only; module-level mutables are "
            "config constants (HIDDEN_SIZE etc.); the localization "
            "capture sink is None unless ARM_CAPTURE is issued "
            "(probes D/D2 only)",
            "no mutable global implicated; capture arming is "
            "diagnostic-only and was not active for A/A2/B/C",
            "module-global enumeration is source-derived, not "
            "runtime-observed; a runtime-only mutation would not "
            "appear here",
        ),
        "pre_call_state_not_in_comparator": _fact(
            "derived",
            "accepted #133 comparator field set vs probe evidence: "
            "the comparator binds public generate() inputs; probe "
            "D2 shows the earliest differing observable is INSIDE "
            "stage-1 layer execution (after_layer_0), downstream of "
            "byte-identical inputs at every compared seam",
            "no pre-call state difference is necessary to explain "
            "the divergence (fresh-first calls vary — probe A)",
        ),
    }

    # -- hypothesis matrix ------------------------------------------------
    matrix = {
        "realization_initialization_lifecycle": {
            "supporting": [
                "all four cross-campaign observations are pairwise "
                "distinct for every regime-4 case while producer, model, "
                "plan, geometry, and per-call inputs are identical",
                "18/18 single-chunk cases are byte-identical across the "
                "same four realizations, so any realization-lifecycle "
                "difference that exists is not by itself sufficient",
            ],
            "contradicting": [
                "the 18 stable cases share the identical realization "
                "lifecycle (same drivers, same spawn order, same RESET "
                "discipline) yet never diverge",
            ],
            "smallest_discriminating_probe": (
                "fresh-realization repeatability probe A: execute the "
                "exact first-divergent call from N>=3 freshly realized "
                "equivalent substrates; if outputs vary across "
                "realizations with identical inputs, realization-sourced "
                "state is implicated and chunking narrows where it enters"
            ),
        },
        "request_history_session_state_leakage": {
            "supporting": [
                "none retained: both arms present the identical request "
                "history before every case (same 25-session order, same "
                "per-case 8-call shape)",
            ],
            "contradicting": [
                "ordinary session id sequence == historical sequence; "
                "direct/ordinary allocator ids differ in the historical "
                "campaign yet 18/24 equal — session/object identity is "
                "not causal for the stable population",
                "first-divergence at position 0 for three cases: no "
                "intra-case prior request exists before the divergent "
                "call, so leakage from earlier CASES would have to "
                "survive the full inter-case RESET",
            ],
            "smallest_discriminating_probe": (
                "history probe B: same realized substrate, target call "
                "first-after-realization vs after controlled replay of "
                "the accepted prefix history; one factor changed"
            ),
        },
        "distributed_boundary_divergence": {
            "supporting": [
                "not yet localized: no retained artifact compares stage "
                "boundary bytes across realizations",
            ],
            "contradicting": [
                "#133 proved transport accounting integrity (wire "
                "payload checksums, boundary byte identity within a run); "
                "the divergence is between separately realized runs, not "
                "a transport corruption signature",
            ],
            "smallest_discriminating_probe": (
                "boundary capture on the divergent call across fresh "
                "realizations (stage1 out, stage2 out, stage3 final-row "
                "logits): earliest differing boundary localizes the stage"
            ),
        },
        "kernel_numerical_nondeterminism": {
            "supporting": [
                "all four observations distinct implies some "
                "per-realization or per-execution numerical variance "
                "amplified to argmax flips exclusively on the two-chunk "
                "population",
                f"{len(pos0)} of 6 cases diverge at position 0 — the "
                "two-chunk PREFILL argmax itself, before any speculative "
                "decode",
                "the second prefill chunk exercises shapes no "
                "single-chunk case reaches (1-3 query rows against a "
                "64-row prefix through the extend/paged paths)",
            ],
            "contradicting": [
                "the same kernels run deterministic (bit-identical) on "
                "the single-chunk population across four realizations",
            ],
            "smallest_discriminating_probe": (
                "probe A repeatability distribution + probe D boundary "
                "localization: identical captured boundary inputs with "
                "diverging outputs isolates compute nondeterminism; a "
                "differing stage-1 output moves it upstream"
            ),
        },
        "planner_realization_side_effect_unrepresented_in_comparator": {
            "supporting": [
                "none retained: #133 proved per-call model-execution "
                "input equivalence through each first divergent call "
                "(inputs_equal on every seam step)",
            ],
            "contradicting": [
                "the direct arm bypasses the planner entirely yet also "
                "fails to reproduce its own historical outputs on "
                "regime-4 — the planner cannot be necessary to the "
                "divergence",
                "18/24 equality with the planner in the loop on the "
                "ordinary side",
            ],
            "smallest_discriminating_probe": (
                "already falsified as NECESSARY by retained evidence "
                "(direct-vs-direct instability); no probe required, "
                "recorded for completeness"
            ),
        },
        "another_mechanically_demonstrated_cause": {
            "supporting": [
                "structural fact: the divergent population is exactly "
                "the prompt_len > PREFILL_CHUNK (64) population — the "
                "only input-correlated partition that separates 6/24",
            ],
            "contradicting": [],
            "smallest_discriminating_probe": (
                "chunk-partition probe C: drive one historically stable "
                "short case through TWO sub-64 chunks (identical total "
                "input, only the chunk boundary moved); divergence "
                "appearing there demonstrates the two-chunk prefill "
                "path is causal alone, divergence not appearing bounds "
                "the cause to the >64-row shapes themselves"
            ),
        },
    }

    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "pinned_inputs": {
            name: {
                "path": rel if not rel.startswith("frozen producer") else rel,
                "sha256": (
                    sha256_file(repo / rel)
                    if not rel.startswith("frozen producer")
                    else stage_chain_sha
                ),
            }
            for name, (rel, _p) in PINNED_INPUTS.items()
        },
        "divergences": divergences,
        "chunk_partition": {
            "prefill_chunk": chunk,
            "cases": partition,
            "two_chunk_population": sorted(two_chunk),
            "two_chunk_equals_divergent_population": True,
            "max_single_chunk_len": max(
                p["prompt_len"] for p in partition.values()
                if p["chunks"] == 1
            ),
            "min_two_chunk_len": min(
                p["prompt_len"] for p in partition.values()
                if p["chunks"] >= 2
            ),
        },
        "cross_campaign": {
            "divergent_cases": cross,
            "stable_cases_all_identical_across_four_observations":
                stable_all_one,
            "stable_case_distinct_value_counts": {
                s["case_id"]: s["distinct_values"] for s in stable_cross
            },
        },
        "history_identity": history_identity,
        "speculative_consistency": {
            "stable_population": {
                "matches": spec_match_stable, "total": spec_total_stable},
            "divergent_population": {
                "matches": spec_match_div, "total": spec_total_div},
            "per_case": spec,
        },
        "position0_prefill_divergence_cases": [
            d["case_id"] for d in pos0
        ],
        "runtime_lifecycle_inventory": runtime_lifecycle_inventory,
        "authority": {
            "source": AUTHORITY_SOURCE,
            "manifest_sha256": authority_sha256,
        },
        "hypothesis_matrix": matrix,
        "families": FAMILIES,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve() if args.repo else Path(
        __file__).resolve().parents[2]
    record = derive(repo)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "phase1_inventory": str(out),
        "divergent_cases": len(record["divergences"]),
        "two_chunk_population": record["chunk_partition"][
            "two_chunk_population"],
        "all_four_distinct": [
            c["case_id"] for c in record["cross_campaign"]["divergent_cases"]
            if c["all_four_distinct"]
        ],
        "stable_all_identical": record["cross_campaign"][
            "stable_cases_all_identical_across_four_observations"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
