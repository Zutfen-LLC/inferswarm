#!/usr/bin/env python3
"""Issue #157 exact-state chunk-2 replay worker (DIAGNOSTIC_ONLY).

Runs INSIDE one gpu-0 process as stage-role "first": materializes the
frozen stage-1 runtime directly (no chain, no wire, no serving
lifecycle), executes chunk 1, freezes post-chunk-1 state, then executes
the exact chunk-2 operation repeatedly from freshly reconstructed
state per trial — separating kernel/operation-intrinsic variance from
lifecycle/allocator/order variance.

No toy kernels: the real Gemma4DecoderLayer.forward path runs (real
qkv GEMM, per-head norms, rotary, real triton attention over the real
paged KV pool, real MLP) exactly as the chain's first stage does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

DIAG_SCHEMA = "inferswarm.issue157.replay-worker/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"

FIXTURE_PATH = "/srv/inferswarm/state/arm-c-retry/prompt-fixture.json"
ATTEMPT_DIRECT_RUN = (
    "/srv/inferswarm/state/arm-c-retry/attempts/armc-retry-physical-1/"
    "direct/direct-run.json"
)
ACCEPTED_FIRST_DIVERGENT = {"c109-04-02-047": 0, "c109-04-06-074": 0}


def sha256_tensor(t) -> str:
    import torch

    raw = t.detach().contiguous().view(torch.uint8)
    if raw.device.type == "cuda":
        raw = raw.cpu()
    return hashlib.sha256(raw.numpy().tobytes()).hexdigest()


def _real_state_tensors(runtime) -> list:
    """The ACTUAL mutable KV-pool state the chunk-2 path reads/writes:
    the full/swa group buffers, the full->swa index mapping, the swa
    free-list, and the page table.  (The top-level _iter_pool_tensors
    helper the accepted report uses does NOT reach these nested
    _KVGroupStorage buffers — a fact recorded by this harness.)"""
    pool = runtime.ctx.kv_cache
    tensors = [
        pool.full_kv_pool.buffer,
        pool.swa_kv_pool.buffer,
        pool.full_to_swa_index_mapping,
    ]
    free = getattr(pool, "_swa_free", None)
    page_table = runtime.ctx.page_table
    return tensors, free, page_table


def kv_state_snapshot(runtime) -> dict:
    tensors, free, page_table = _real_state_tensors(runtime)
    return {
        "tensors": [t.detach().clone() for t in tensors],
        "swa_free": None if free is None else free.detach().clone(),
        "page_table": page_table.detach().clone(),
    }


def restore_kv_state(runtime, snap: dict) -> None:
    tensors, free, page_table = _real_state_tensors(runtime)
    for live, frozen in zip(tensors, snap["tensors"]):
        live.copy_(frozen)
    if free is not None and snap["swa_free"] is not None:
        # free-list is rebuilt by slicing, not in-place: restore via the
        # pool attribute (it is a plain tensor attribute)
        pool = runtime.ctx.kv_cache
        pool._swa_free = snap["swa_free"].clone()
    page_table.copy_(snap["page_table"])


def kv_state_digests(runtime) -> list:
    tensors, free, page_table = _real_state_tensors(runtime)
    digests = [sha256_tensor(t) for t in tensors]
    if free is not None:
        digests.append(sha256_tensor(free))
    digests.append(sha256_tensor(page_table))
    return digests


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--trials", type=int, default=6)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--chain-plan", required=True)
    parser.add_argument("--intervention", default="none",
                        choices=["none", "sync", "scratch", "route",
                                 "swa-alloc"])
    args = parser.parse_args(argv)

    import torch

    scripts_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(scripts_dir))
    import issue157_instrumentation as instr

    fixture = json.loads(Path(FIXTURE_PATH).read_text())
    rows = {r["case_id"]: r for r in fixture["cases"]}
    accepted = json.loads(Path(ATTEMPT_DIRECT_RUN).read_text())
    accepted_ids = {
        e["case_id"]: [c["committed_token"] for c in e["calls"]]
        for e in accepted["invocation_transcript"]
    }
    case = args.case_id
    k = ACCEPTED_FIRST_DIVERGENT[case]
    replay = list(rows[case]["rendered_prompt_token_ids"]) + \
        accepted_ids[case][:k]
    total = len(replay)
    chunk2_tokens = replay[64:]
    prefix_len = 64

    result = {
        "schema": DIAG_SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "run_id": os.environ.get("ISSUE157_RUN_ID", "unknown"),
        "case": case,
        "replay_len": total,
        "chunk2_rows": len(chunk2_tokens),
        "intervention": args.intervention,
        "trials": args.trials,
        "started_at_ns": time.time_ns(),
        "hostname": os.uname().nodename,
        "pid": os.getpid(),
    }

    # -- 1. materialize the frozen stage-1 runtime ------------------------
    import torch  # noqa: F401

    from freetoken.distributed import set_tp_info, try_get_tp_info
    from freetoken.layers.rotary import set_rope_device

    if try_get_tp_info() is None:
        set_tp_info(rank=0, size=1)
    set_rope_device(torch.device("cuda:0"))

    from benchmarks.inferswarm_r6.stage_runtime import GemmaDenseStage

    plan = json.loads(Path(args.chain_plan).read_text())
    block = plan["blocks"][0]
    runtime = GemmaDenseStage(
        role="first", model_path=args.model, adapter_data={
            **block,
            "runtime_capacity_tokens": plan["runtime_capacity_tokens"],
            "declared_shared_state": plan.get("declared_shared_state"),
        },
    )
    result["runtime_report_keys"] = sorted(
        k_ for k_ in runtime.report().keys()
    )[:40]

    # install instrumentation AFTER runtime construction (class patches
    # apply to all instances incl. this one)
    observer = instr.install(
        os.environ.get("ISSUE157_OUT_DIR", "/tmp/issue157-harness"),
        "replay-worker-stage1",
    )
    # op-bisection: instance-level wraps on layers 0/1 (robust against
    # class-level patch interception by decorators/descriptors)
    _install_op_bisection(observer, runtime)

    # -- 2. execute chunk 1 fresh; freeze post-chunk-1 state --------------
    runtime.reset_session_state()
    hidden1, _ = runtime.prefill(replay[:prefix_len], None, 0)
    frozen = kv_state_snapshot(runtime)
    frozen_digests = kv_state_digests(runtime)
    frozen_hidden1 = hidden1.detach().clone()
    result["chunk1"] = {
        "boundary_sha256": sha256_tensor(frozen_hidden1),
        "kv_state_digests": frozen_digests,
        "rows": int(frozen_hidden1.shape[0]),
    }

    # chunk-1 repeatability control (same fresh-state discipline): run
    # chunk 1 twice more from scratch; must be byte-identical (accepted
    # fact: first chunk stable) — a mismatch classifies the harness.
    c1_digests = [result["chunk1"]["boundary_sha256"]]
    c1_state_digests = [frozen_digests]
    for _ in range(2):
        runtime.reset_session_state()
        h1, _ = runtime.prefill(replay[:prefix_len], None, 0)
        c1_digests.append(sha256_tensor(h1))
        c1_state_digests.append(kv_state_digests(runtime))
    result["chunk1_repeatability"] = {
        "digests": c1_digests,
        "byte_identical": len(set(c1_digests)) == 1,
        "kv_state_digests": c1_state_digests,
        "kv_state_byte_identical": all(
            d == frozen_digests for d in c1_state_digests
        ),
    }

    # -- 3. trials: fresh replay state per trial, exact chunk-2 op ---------
    # intervention toggle (scratch arm): installed once, toggled per arm
    scratch_on = [args.intervention == "scratch"]
    if args.intervention == "scratch":
        _prezero_decode_scratch(runtime, scratch_on)
    trial_rows = []
    for trial in range(args.trials):
        # fresh state reconstruction (never reuse mutated live state)
        runtime.reset_session_state()
        restore_kv_state(runtime, frozen)
        # (no-mutated-reuse is proven post-hoc via the restore check)

        if args.intervention == "sync":
            torch.cuda.synchronize()

        t0 = time.time_ns()
        hidden2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
        torch.cuda.synchronize()
        elapsed = time.time_ns() - t0
        trial_rows.append({
            "trial": trial,
            "chunk2_boundary_sha256": sha256_tensor(hidden2),
            "elapsed_ns": elapsed,
        })
    result["trials_detail"] = trial_rows
    digests = [r["chunk2_boundary_sha256"] for r in trial_rows]
    result["chunk2_digests"] = digests
    result["chunk2_deterministic"] = len(set(digests)) == 1

    # -- 5. no-mutated-reuse proof ----------------------------------------
    # after the last trial the live pool differs from frozen (chunk-2 KV
    # written); restoring must return it to the frozen bytes.
    live_before = kv_state_digests(runtime)
    restore_kv_state(runtime, frozen)
    live_after = kv_state_digests(runtime)
    result["no_reuse_proof"] = {
        "live_after_trials": live_before,
        "after_restore": live_after,
        "restore_returns_to_frozen": (
            live_after == result["chunk1"]["kv_state_digests"]
        ),
        "trials_mutated_state": (
            live_before != result["chunk1"]["kv_state_digests"]
        ),
    }

    # -- intervention-specific arms ----------------------------------------
    if args.intervention == "sync":
        # Treatment already ran above with a per-trial pre-prefill
        # synchronize.  The NARROWER hypothesis — an unsynchronized
        # producer/consumer race INSIDE the chunk-2 call, immediately
        # before the earliest unstable op (layer-0 attention) — is
        # tested by forcing a device-wide sync before EVERY backend
        # attention call of the chunk-2 prefill.
        from freetoken.attention.triton import TritonAttentionBackend

        orig_bf = TritonAttentionBackend.forward
        sync_on = [True]

        def syncing(self, q, k, v, layer_id, batch, attn_spec=None):
            if sync_on[0]:
                torch.cuda.synchronize()
            return orig_bf(self, q, k, v, layer_id, batch,
                           attn_spec=attn_spec)

        TritonAttentionBackend.forward = syncing
        tight = []
        try:
            for trial in range(args.trials):
                runtime.reset_session_state()
                restore_kv_state(runtime, frozen)
                hidden2, _ = runtime.prefill(chunk2_tokens, None,
                                             prefix_len)
                torch.cuda.synchronize()
                tight.append(sha256_tensor(hidden2))
        finally:
            TritonAttentionBackend.forward = orig_bf
        result["sync_tight_digests"] = tight
        # paired control: identical state, NO explicit sync (normal path)
        paired = []
        for trial in range(args.trials):
            runtime.reset_session_state()
            restore_kv_state(runtime, frozen)
            hidden2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
            torch.cuda.synchronize()
            paired.append(sha256_tensor(hidden2))
        result["sync_control_digests"] = paired
        result["sync_stabilizes"] = (
            len(set(tight)) == 1 and len(set(paired)) > 1
        )
        result["sync_tight_deterministic"] = len(set(tight)) == 1
    elif args.intervention == "scratch":
        # paired control: identical state, wrapper installed but OFF —
        # the genuinely unchanged allocation path in the same process
        scratch_on[0] = False
        paired = []
        for trial in range(args.trials):
            runtime.reset_session_state()
            restore_kv_state(runtime, frozen)
            hidden2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
            torch.cuda.synchronize()
            paired.append(sha256_tensor(hidden2))
        scratch_on[0] = True
        result["scratch_control_digests"] = paired
        result["scratch_stabilizes"] = (
            len(set(digests)) == 1 and len(set(paired)) > 1
        )
    elif args.intervention == "swa-alloc":
        # Causal intervention for the SWA-mapping hypothesis: the R6
        # standalone stage path never allocates swa slots (alloc_swa is
        # scheduler-only), so full_to_swa_index_mapping stays at the
        # all-zero sentinel: every SWA-layer prefix read resolves to
        # swa slot 0, and the chunk-2 store's racing warps make slot-0
        # content vary per trial.  ONE VARIABLE: perform the missing
        # allocation (alloc_swa over the used full slots) before chunk
        # execution; the store then writes distinct swa slots and the
        # prefix reads real per-position K/V.  Chunk-1 AND chunk-2 run
        # under the allocated mapping (the prefix must be re-derived).
        import torch as _t

        pool = runtime.ctx.kv_cache
        treatment = []
        for trial in range(args.trials):
            runtime.reset_session_state()
            # NB: reset_session_state ZEROES full_to_swa_index_mapping and
            # _swa_free (both top-level pool tensors) — the allocation
            # MUST come after it, else the intervention is neutralized.
            _reset_swa_allocator(pool)
            pool.alloc_swa(_t.arange(67, dtype=_t.int64,
                                      device=pool.full_to_swa_index_mapping
                                      .device))
            h1, _ = runtime.prefill(replay[:prefix_len], None, 0)
            h2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
            _t.cuda.synchronize()
            treatment.append({
                "chunk1": sha256_tensor(h1),
                "chunk2": sha256_tensor(h2),
            })
        # paired control: identical discipline, mapping NOT allocated
        control = []
        for trial in range(args.trials):
            runtime.reset_session_state()
            _reset_swa_allocator(pool)
            h1, _ = runtime.prefill(replay[:prefix_len], None, 0)
            h2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
            _t.cuda.synchronize()
            control.append({
                "chunk1": sha256_tensor(h1),
                "chunk2": sha256_tensor(h2),
            })
        result["swa_alloc_treatment"] = treatment
        result["swa_alloc_control"] = control
        result["swa_alloc_stabilizes"] = (
            len({r["chunk2"] for r in treatment}) == 1
            and len({r["chunk2"] for r in control}) > 1
        )
        result["swa_alloc_treatment_chunk2_deterministic"] = (
            len({r["chunk2"] for r in treatment}) == 1
        )

    elif args.intervention == "route":
        # mechanical route verification (observed at dispatch) + legal
        # alternate-route paired comparison
        routes = _observe_routes(runtime, frozen, chunk2_tokens,
                                 prefix_len)
        result["route_observation"] = routes
        # alternate route: same state, same rows/positions/KV authority;
        # the extend->paged alternative is reachable for head_dim>256
        # layers only when is_decode stays False.  For the split-k
        # decode route (is_decode=True) forcing is_decode False would
        # change kernel semantics => INTERVENTION_NOT_LEGAL there.
        alt = _alternate_route_pair(runtime, frozen, chunk2_tokens,
                                    prefix_len)
        result["route_intervention"] = alt

    result["completed_at_ns"] = time.time_ns()
    Path(args.out).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(f"[issue157-replay] {case} trials={args.trials} "
          f"intervention={args.intervention} deterministic="
          f"{result['chunk2_deterministic']}")
    return 0


def _reset_swa_allocator(pool) -> None:
    """Rebuild the swa allocator to its pristine __init__ state (dense
    zero mapping + full free-list) — the state the accepted runtime
    implicitly carries at first use."""
    import torch as _t

    n = pool._full_num_tokens
    ps = pool._page_size
    dev = pool._device
    pool.full_to_swa_index_mapping = _t.cat(
        [
            _t.zeros(n + ps, dtype=_t.int64, device=dev),
            _t.tensor([-1], dtype=_t.int64, device=dev),
        ]
    )
    pool._swa_free = _t.arange(
        1, pool._swa_num_tokens, dtype=_t.int32, device=dev
    )


def _install_op_bisection(observer, runtime) -> None:
    """Wrap layer-0/1 attention-component instance forwards so the
    ORIGINAL execution path runs unchanged while intermediates are
    captured (deep-capture gated)."""
    gids = list(runtime.block.global_layer_ids)
    for local_idx, layer in enumerate(runtime.block.layers):
        g = gids[local_idx] if local_idx < len(gids) else local_idx
        if g not in (0, 1):
            continue
        attn = layer.self_attn

        def _wrap(obj, attr, checkpoint):
            orig = getattr(obj, attr)

            def wrapped(*args, **kwargs):
                out = orig(*args, **kwargs)
                if observer.deep:
                    observer.tensor(checkpoint, out)
                return out

            setattr(obj, attr, wrapped)

        _wrap(attn.qkv_proj, "forward", f"L{g}_qkv_projected")
        _wrap(attn.q_norm, "forward", f"L{g}_q_normed")
        _wrap(attn.k_norm, "forward", f"L{g}_k_normed")
        _wrap(attn.rotary, "forward", f"L{g}_rotary_applied")
        _wrap(attn.o_proj, "forward", f"L{g}_o_proj")


def _prezero_decode_scratch(runtime, install_flag: list) -> None:
    """Deterministically zero the decode-route scratch buffers of the
    NEXT prepared metadata (B: concrete buffers proven to participate:
    attn_logits/attn_lse fp32 scratch allocated by
    _ensure_decode_scratch via torch.empty).  install_flag[0] toggles
    the wrapper ON/OFF so the paired control arm runs the genuinely
    unchanged allocation path in the same process."""
    from freetoken.attention.triton import TritonAttentionBackend

    if not hasattr(TritonAttentionBackend, "_issue157_orig_scratch"):
        TritonAttentionBackend._issue157_orig_scratch = (
            TritonAttentionBackend._ensure_decode_scratch
        )
    orig = TritonAttentionBackend._issue157_orig_scratch

    def zeroing(self, metadata, bs, num_q_heads, head_dim):
        orig(self, metadata, bs, num_q_heads, head_dim)
        if not install_flag[0]:
            return
        if metadata.attn_logits is not None:
            metadata.attn_logits.zero_()
        if metadata.attn_lse is not None:
            metadata.attn_lse.zero_()

    TritonAttentionBackend._ensure_decode_scratch = zeroing


def _observe_routes(runtime, frozen, chunk2_tokens, prefix_len):
    """Run chunk-2 once and record observed dispatch routes per layer."""
    routes = []
    from freetoken.attention.triton import TritonAttentionBackend

    orig = TritonAttentionBackend.forward

    def observing(self, q, k, v, layer_id, batch, attn_spec=None):
        md = batch.attn_metadata
        routes.append({
            "layer_id": int(layer_id),
            "rows": int(q.shape[0]),
            "head_dim": int(q.shape[-1]),
            "is_decode": bool(md.is_decode),
        })
        return orig(self, q, k, v, layer_id, batch, attn_spec=attn_spec)

    TritonAttentionBackend.forward = observing
    try:
        runtime.reset_session_state()
        restore_kv_state(runtime, frozen)
        runtime.prefill(chunk2_tokens, None, prefix_len)
        import torch

        torch.cuda.synchronize()
    finally:
        TritonAttentionBackend.forward = orig
    return routes


def _alternate_route_pair(runtime, frozen, chunk2_tokens, prefix_len):
    """Paired comparison: current dispatch vs alternate legal route.

    Legality analysis (recorded, not forced): the backend picks a route
    by (is_decode, head_dim<=256 or max_q_len>=128).  For the chunk-2
    call (is_decode True for 1-row, False otherwise), the SEMANTICALLY
    EQUIVALENT alternate route for extend chunks (2-3 rows) is the
    generic paged_attention path (used by head_dim>256 full-attention
    layers in the SAME call): same query/KV authority, same causal
    masking semantics.  We pair per-layer where both routes are legal.
    """
    import torch

    from freetoken.attention.triton import TritonAttentionBackend
    from freetoken.kernel.triton.attention import (
        extend_paged_attention,
        paged_attention,
    )

    per_layer = []
    orig = TritonAttentionBackend.forward

    def forcing(self, q, k, v, layer_id, batch, attn_spec=None):
        md = batch.attn_metadata
        spec = attn_spec or AttentionSpec()
        rows = int(q.shape[0])
        # force generic paged route for the extend chunk on layers whose
        # current route is extend_paged_attention (head_dim<=256)
        if (not md.is_decode) and rows <= 8 and q.shape[-1] <= 256:
            # same KV authority; generic paged route is the alternate
            self.kvcache.store_kv(k, v, batch.out_loc, layer_id)
            k_raw = self.kvcache.k_cache(layer_id)
            v_raw = self.kvcache.v_cache(layer_id)
            kv_heads, head_dim = k_raw.shape[-2], k_raw.shape[-1]
            indices = md.indices
            if spec.sliding_window is not None and md.swa_indices is not None:
                indices = md.swa_indices
            scale = (
                spec.sm_scale if spec.sm_scale is not None
                else q.shape[-1] ** -0.5
            )
            return paged_attention(
                q=q, k_cache=k_raw.view(-1, kv_heads, head_dim),
                v_cache=v_raw.view(-1, kv_heads, head_dim),
                indptr=md.indptr, indices=indices,
                q_to_req=md.q_to_req, q_positions=md.q_positions,
                sm_scale=scale,
                sliding_window=spec.sliding_window,
                sinks=spec.sinks,
            )
        return orig(self, q, k, v, layer_id, batch, attn_spec=attn_spec)

    from freetoken.attention import AttentionSpec

    digests = []
    TritonAttentionBackend.forward = forcing
    try:
        for _ in range(3):
            runtime.reset_session_state()
            restore_kv_state(runtime, frozen)
            h2, _ = runtime.prefill(chunk2_tokens, None, prefix_len)
            torch.cuda.synchronize()
            digests.append(sha256_tensor(h2))
    finally:
        TritonAttentionBackend.forward = orig
    return {
        "alternate": "generic_paged_for_extend_layers",
        "digests": digests,
        "deterministic": len(set(digests)) == 1,
        "note": (
            "forced the generic paged route ONLY for 2-3-row extend "
            "chunks on head_dim<=256 layers; decode-route and "
            "head_dim>256 layers unchanged"
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
