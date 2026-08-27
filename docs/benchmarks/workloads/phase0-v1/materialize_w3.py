#!/usr/bin/env python3
"""Materialize InferSwarm Phase-0 W3 long-context fixture.

The fixture is generated instead of checked in as a ~50 KiB blob so the source
contract is reviewable. The output bytes are deterministic and hash-pinned by
manifest.json. This script makes no measurements.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

MODEL_REPO = "nvidia/Qwen3.6-35B-A3B-NVFP4"
MODEL_REV = "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
EXPECTED_SHA256 = "279c11ce0194e1d839dc92d910785d996a93e33046d047a018a652b24e75f2b3"

TOPICS = [
    ("model pin", f"The Phase-0/1 checkpoint is {MODEL_REPO} at immutable revision {MODEL_REV}; canonical runs may not follow upstream main."),
    ("baseline selection", "CANONICAL_PERFORMANCE_BASELINE is the measured winner of the predeclared B1–B5 single-GPU sweep, not whichever arm is easiest for the candidate to beat."),
    ("correctness reference", "CORRECTNESS_REFERENCE is a fixed non-distributed single-device GPU configuration and is never chosen by speed or used as the performance denominator."),
    ("workload freeze", "W1–W4 prompts, output lengths, sampling, chat-template settings, and content hashes are frozen before candidate performance is observed."),
    ("W1 shape", "W1 is coding/agentic, at most 2,000 prompt tokens, with exactly 512 generated tokens under ignore_eos."),
    ("W2 shape", "W2 is open-ended reasoning/conversation, at most 1,000 prompt tokens, with exactly 512 generated tokens under ignore_eos."),
    ("W3 shape", "W3 is the long-context class, targeted at 16,000 prompt tokens; the harness freezes a plus-or-minus 15 percent band and an absolute 20,000-token ceiling."),
    ("W4 shape", "W4 is the short interactive class, targeted at 128 prompt tokens with a plus-or-minus 25 percent band and exactly 128 generated tokens."),
    ("sampling", "Performance requests state temperature, top_p, and top_k explicitly so server defaults cannot drift; the correctness reference overrides the same frozen prompts to greedy sampling."),
    ("seed boundary", "FreeToken exposes no sampling seed, so the manifest records seed as null rather than pretending sampled generations are seeded."),
    ("GPU identity", "Canonical Phase 0 selects one physical RTX 3060 by stable GPU UUID and verifies the running engine reports the same device."),
    ("hardware profile", "The hardware profile records CPU/RAM/OS, driver, CUDA-facing environment, PCIe current/max link, topology, VRAM bandwidth, and expert microbench diagnostics."),
    ("microbenchmark rule", "VRAM bandwidth and single-expert latency are diagnostics only; neither can establish an end-to-end performance win."),
    ("bench-bw prerequisite", "A fresh NVFP4 `ft bench bw` profile is a session-level prerequisite because B2 and B3 both consume it, including reversed traversal."),
    ("B1–B5 sweep", "All five baseline arms are legitimate FreeToken configurations; the sweep records explicit NVFP4 backend choices rather than relying on defaults."),
    ("warmups", "Each arm/workload block performs two discarded warmup generations before ten measured generations, with no selective repetition removal."),
    ("sessions", "Two complete sessions are required; the second reverses traversal order so thermal or temporal drift is not assigned to one configuration."),
    ("variance", "Run-to-run variance is part of the evidence; a baseline coefficient of variation above five percent in any class invalidates the campaign for threshold decisions."),
    ("prefill", "Prefill throughput is measured at the model-forward boundary with request attribution; prompt_tokens divided by TTFT is explicitly not a prefill measurement."),
    ("TTFT", "TTFT remains an end-to-end first-token observation that includes work outside the raw prefill kernel and is compared separately from decode."),
    ("routing traces", "Issue #3 records expert selections and cache hit/miss behavior on the frozen workloads so placement decisions are grounded in routing evidence."),
    ("coverage distinction", "Resident expert coverage, routing hit rate, and tokens per second are three different quantities; coverage is never promoted into a throughput claim."),
    ("graph safety", "Routing histograms that require collect_decode_freq come from graph-disabled diagnostic runs; graph-enabled gating runs may use graph-safe cache statistics."),
    ("Phase-1 scope", "The first distributed mechanism is same-host two-GPU decode-time resident expert execution; it is not a network worker, RPC fabric, or generalized scheduler."),
    ("remote ownership", "A route assigned to GPU 1 executes there exactly once; silent fallback to GPU 0 or CPU is invalid mechanism evidence."),
    ("remote payload", "All GPU-1-selected experts for a layer/step are represented in one destination-batched activation/routing dispatch rather than one request per expert."),
    ("resident weights", "GPU-1 expert weights are loaded during startup/placement and steady-state decode must not stream those weights to service remote routes."),
    ("placement", "Phase-1 placement is static, deterministic, evidence-derived from Phase-0 routing/cache traces, and hash-pinned before candidate throughput is observed."),
    ("host RAM tier", "Host RAM remains a first-class execution/storage tier; secondary GPUs augment rather than replace the existing offload path."),
    ("mixed tiers later", "Primary GPU plus secondary GPU plus host RAM in one inference run is a later hard architecture acceptance criterion, not a Phase-1 prerequisite."),
    ("network later", "Ordinary 1 GbE is evaluated only after the local mechanism; Phase 0/1 must not smuggle network conclusions into a same-host result."),
    ("evidence labels", "Every numeric claim is labeled MEASURED, CALCULATED, ESTIMATED, or SPECULATIVE; a planning record must not masquerade as a measurement."),
]

QUESTIONS = [
    "Review focus: what exact artifact would prove this statement held for a run?",
    "Review focus: name the failure mode if this invariant is violated silently.",
    "Review focus: which later conclusion would become invalid if this record were wrong?",
    "Review focus: distinguish the measured fact from any inference someone might be tempted to draw.",
    "Review focus: identify the cheapest preflight or post-run check that makes this auditable.",
    "Review focus: explain why this is held constant rather than tuned after seeing throughput.",
    "Review focus: state whether this belongs to mechanism validity, correctness, performance, or provenance.",
    "Review focus: point out any plausible source of accidental cherry-picking or goalpost movement.",
]

PHASES = [
    "campaign setup",
    "preflight",
    "baseline execution",
    "instrumentation review",
    "evidence audit",
    "Phase-1 handoff",
]

HEADER = """Long-context engineering review workload.

The following is a frozen, synthetic-but-project-grounded engineering ledger built from the public InferSwarm Phase-0/1 contracts and FreeToken harness behavior. It contains no benchmark measurements and makes no performance claim. Treat repeated invariants as independent review entries from a long-running project log rather than as permission to ignore them.

Read the entire ledger. After the final record, produce a compact audit that:
1. groups the recurring risks into provenance, workload integrity, correctness, mechanism validity, and performance methodology;
2. identifies at least five dependencies where a failure early in Phase 0 would invalidate a later Phase-1 claim;
3. calls out any pair of records that can appear contradictory unless the distinction between diagnostic evidence and gating evidence is preserved.

BEGIN LEDGER

"""

FOOTER = """

END LEDGER

Do not invent measured numbers. Base the audit only on the frozen ledger above, and preserve the distinction between what is precommitted, what must be measured, and what is intentionally deferred."""


def render() -> str:
    records: list[str] = []
    for i in range(176):
        topic, statement = TOPICS[i % len(TOPICS)]
        question = QUESTIONS[(i * 3 + i // len(TOPICS)) % len(QUESTIONS)]
        phase = PHASES[(i * 5 + i // 7) % len(PHASES)]
        records.append(
            f"[Record {i + 1:03d}] Phase: {phase}. Topic: {topic}.\n"
            f"State: {statement}\n"
            f"{question}\n"
        )
    return HEADER + "\n".join(records) + FOOTER


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path(__file__).with_name("w3-long-context.txt")),
        help="output fixture path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify deterministic bytes/hash without writing",
    )
    args = parser.parse_args()

    content = render()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            f"W3 generator drift: expected {EXPECTED_SHA256}, rendered {digest}"
        )

    if args.check:
        print(f"PASS sha256={digest} chars={len(content)} words={len(content.split())}")
        return 0

    out = Path(args.out)
    out.write_text(content, encoding="utf-8")
    print(f"wrote {out} sha256={digest} chars={len(content)} words={len(content.split())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
