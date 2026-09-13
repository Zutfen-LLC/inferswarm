#!/usr/bin/env python3
"""Issue #157 chunk-2 diagnostic instrumentation (DIAGNOSTIC_ONLY).

NEVER REACHED from ordinary execution: this file lives in the InferSwarm
repository's scripts/ directory and is imported ONLY by the env-gated
``sitecustomize`` shim staged for #157 diagnostic runs
(``ISSUE157_STAGE_INSTRUMENT=1``); without that variable the shim is a
no-op and the frozen FreeToken tree executes byte-identical code (zero
source changes; producer == accepted research head verbatim).

Auto-arming semantics: the observer records EVERY prefill call's
identity; deep op-level checkpoints arm automatically on the chunk-2
call shape (start >= 64, 1 <= rows <= 8) for stage-1-role processes.
All records flush to a per-process JSONL file at call end — complete
trial distributions, no selection.

Capture surface per issue #157 Phase 1 (stage 1, global layers 0 and 1):
  call/state identity, first-chunk-end state, earliest-operation
  checkpoints (qkv projection, per-head norms, rotary, KV slice pre/post
  write, attention output, o_proj, after-layer residual), execution
  context (actual kernel route observed at dispatch, scratch buffer
  identity for the decode route, CUDA stream, allocator state).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

DIAG_SCHEMA = "inferswarm.issue157.instrumentation/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
CHUNK_ROWS = 64           # frozen boundary contract per-call capacity
CHUNK2_MAX_ROWS = 8       # deep-capture arming threshold (required 1-3)


def _tensor_facts(t: Any) -> dict:
    import torch

    if not isinstance(t, torch.Tensor):
        return {"kind": type(t).__name__}
    facts: dict[str, Any] = {
        "dtype": str(t.dtype),
        "shape": list(t.shape),
        "stride": list(t.stride()),
        "device": str(t.device),
    }
    if t.numel() == 0:
        facts["sha256"] = hashlib.sha256(b"").hexdigest()
        facts["nonfinite"] = 0
        return facts
    try:
        raw = t.detach().contiguous().view(torch.uint8)
        if raw.device.type == "cuda":
            raw = raw.cpu()
        facts["sha256"] = hashlib.sha256(raw.numpy().tobytes()).hexdigest()
        f32 = t.detach().float()
        if f32.device.type == "cuda":
            f32 = f32.cpu()
        facts["nonfinite"] = int((~torch.isfinite(f32)).sum().item())
    except Exception as exc:  # diagnostics must never break execution
        facts["capture_error"] = f"{type(exc).__name__}: {exc}"
    return facts


class Issue157Sink:
    """Per-stage-process JSONL capture sink (explicit diagnostic dir)."""

    def __init__(self, out_dir: str, stage_label: str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.stage_label = stage_label
        self.run_id = os.environ.get("ISSUE157_RUN_ID", "unknown-run")
        self.attempt = os.environ.get("ISSUE157_ATTEMPT", "0")
        self.path = self.out_dir / (
            f"i157-{self.stage_label}-{self.run_id}-{self.attempt}.jsonl"
        )
        self.rows = 0

    def write(self, kind: str, payload: dict) -> None:
        doc = {
            "schema": DIAG_SCHEMA,
            "classification": DIAGNOSTIC_ONLY,
            "kind": kind,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "stage": self.stage_label,
            "pid": os.getpid(),
            "time_ns": time.time_ns(),
            **payload,
        }
        with open(self.path, "a") as fh:
            fh.write(json.dumps(doc, sort_keys=True) + "\n")
        self.rows += 1


class Chunk2Observer:
    """Records call identity + armed deep checkpoints; auto-arms on the
    chunk-2 call shape.  One instance per stage process."""

    def __init__(self, sink: Issue157Sink):
        self.sink = sink
        self.records: list[dict] = []
        self.deep = False          # deep checkpoints armed (chunk-2 call)
        self.call_seq = 0
        self.cur: dict[str, Any] = {}
        self.global_layer_ids: list[int] = []
        self.attention_wrapped: set[int] = set()

    # -- record helpers ---------------------------------------------------
    def rec(self, checkpoint: str, payload: dict) -> None:
        self.records.append({
            "checkpoint": checkpoint,
            "call_seq": self.call_seq,
            "time_ns": time.time_ns(),
            **payload,
        })

    def tensor(self, checkpoint: str, t: Any, **extra) -> None:
        self.rec(checkpoint, {"tensor": _tensor_facts(t), **extra})

    def raw(self, checkpoint: str, value: Any) -> None:
        self.rec(checkpoint, {"value": value})

    # -- call lifecycle -----------------------------------------------------
    def begin_call(self, *, role, start, rows, token_ids, hidden) -> bool:
        self.call_seq += 1
        self.cur = {
            "role": role,
            "start": int(start),
            "rows": int(rows),
            "token_ids": (
                [int(t) for t in token_ids] if token_ids is not None else None
            ),
            "hidden_shape": (
                list(hidden.shape) if hidden is not None else None
            ),
        }
        self.deep = (
            role in ("first", "single")
            and start >= CHUNK_ROWS
            and 1 <= rows <= CHUNK2_MAX_ROWS
        )
        self.cur["deep_capture"] = self.deep
        return self.deep

    def end_call(self, result_facts: dict | None = None) -> None:
        if self.cur:
            self.cur["result"] = result_facts or {}
            self.sink.write("call", {"call": self.cur,
                                     "records": self.records})
        self.records = []
        self.deep = False
        self.cur = {}


OBSERVER: Chunk2Observer | None = None


def _try(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def install(out_dir: str, stage_label: str) -> Chunk2Observer:
    """Install class-level patches into THIS (stage) process.  All
    patches delegate to the original implementation; capture is additive
    only, and deep capture fires solely on the chunk-2 call shape."""
    import torch

    from freetoken.attention.triton import TritonAttentionBackend
    from freetoken.models.gemma4.attention import Gemma4Attention
    from benchmarks.inferswarm_r6 import stage_runtime

    global OBSERVER
    sink = Issue157Sink(out_dir, stage_label)
    observer = Chunk2Observer(sink)
    OBSERVER = observer

    # ---- GemmaDenseStage.prefill: call/state identity -------------------
    orig_prefill = stage_runtime.GemmaDenseStage.prefill

    def instrumented_prefill(self, token_ids, hidden_or_ids, start: int):
        rows = (
            len(token_ids) if token_ids is not None
            else int(hidden_or_ids.shape[0])
        )
        deep = observer.begin_call(
            role=self.role, start=start, rows=rows,
            token_ids=token_ids, hidden=hidden_or_ids,
        )
        observer.global_layer_ids = list(self.block.global_layer_ids)
        if deep or (
            self.role in ("first", "single")
            and start == 0
            and rows == CHUNK_ROWS
        ):
            import torch as _t

            ctx_facts = {
                "cuda_stream": str(_t.cuda.current_stream()),
                "cuda_device": _t.cuda.current_device(),
                "cuda_allocated": int(_t.cuda.memory_allocated()),
                "cuda_reserved": int(_t.cuda.memory_reserved()),
                "page_table": _tensor_facts(self.ctx.page_table),
            }
            observer.raw("call_context", ctx_facts)
            observer.raw(
                "kv_state_at_call_start",
                _try(self.logical_state_records, int(start) + int(rows)),
            )
        result = orig_prefill(self, token_ids, hidden_or_ids, start)
        if observer.cur:
            facts = (
                _tensor_facts(result[0])
                if isinstance(result, tuple) and result
                else {"kind": type(result).__name__}
            )
            observer.end_call(facts)
        return result

    stage_runtime.GemmaDenseStage.prefill = instrumented_prefill

    # ---- layer sequence: after-layer residual checkpoints ----------------
    orig_exec = stage_runtime.execute_dense_layer_sequence

    def instrumented_execute(layers, hidden, *, after_layer_hook=None):
        if not (observer.deep or observer.cur.get("start") == 0):
            return orig_exec(layers, hidden, after_layer_hook=after_layer_hook)
        gids = observer.global_layer_ids

        def hook(local_index: int, h):
            g = gids[local_index] if local_index < len(gids) else local_index
            if g in (0, 1):
                observer.tensor(f"after_layer_{g}", h, global_layer=g)
            if after_layer_hook is not None:
                after_layer_hook(local_index, h)

        return orig_exec(layers, hidden, after_layer_hook=hook)

    stage_runtime.execute_dense_layer_sequence = instrumented_execute

    # ---- Gemma4Attention.forward: wrap instance ops on first touch -------
    orig_attn_forward = Gemma4Attention.forward

    def instrumented_attn_forward(self, x):
        g_local = getattr(self, "_layer_id", None)
        gids = observer.global_layer_ids
        g = (
            gids[g_local]
            if isinstance(g_local, int) and g_local < len(gids)
            else g_local
        )
        if observer.deep and g in (0, 1):
            if g not in observer.attention_wrapped:
                _wrap_attention_instance(observer, self, g)
                observer.attention_wrapped.add(g)
            observer.tensor(f"L{g}_attn_input", x)
        out = orig_attn_forward(self, x)
        if observer.deep and g in (0, 1):
            observer.tensor(f"L{g}_attn_output_oproj", out)
        return out

    Gemma4Attention.forward = instrumented_attn_forward

    # ---- TritonAttentionBackend.forward: route + KV-write + scratch ------
    orig_backend_forward = TritonAttentionBackend.forward

    def instrumented_backend_forward(
        self, q, k, v, layer_id, batch, attn_spec=None
    ):
        md = getattr(batch, "attn_metadata", None)
        rows = int(q.shape[0])
        gids = observer.global_layer_ids
        g = (
            gids[layer_id] if layer_id < len(gids) else layer_id
        )
        target = observer.cur.get("start", -1) or 0
        is_chunk2_call = (
            observer.cur.get("role") in ("first", "single")
            and target >= CHUNK_ROWS
            and rows <= CHUNK2_MAX_ROWS
        )
        if md is not None and is_chunk2_call:
            route = {
                "global_layer": g,
                "rows": rows,
                "head_dim": int(q.shape[-1]),
                "is_decode": bool(md.is_decode),
                "max_q_len": int(md.max_q_len),
                "sliding_window": (
                    None if attn_spec is None or attn_spec.sliding_window is None
                    else int(attn_spec.sliding_window)
                ),
                "prefix_lens": md.prefix_lens.tolist()
                if md.prefix_lens is not None else None,
                "cu_seqlens_q": md.cu_seqlens_q_gpu.tolist()
                if md.cu_seqlens_q_gpu is not None else None,
                "q_positions": md.q_positions.tolist()
                if md.q_positions is not None else None,
                "positions": batch.positions.tolist()
                if batch.positions is not None else None,
            }
            observer.raw(f"route_L{g}", route)
            if g in (0, 1):
                kv_len = (
                    int(md.indptr[-1].item())
                    if md.indptr is not None else None
                )
                observer.tensor(
                    f"L{g}_kv_slice_pre_write",
                    self.kvcache.k_cache(layer_id)[:kv_len],
                    kv_len=kv_len,
                )
                for attr in ("attn_logits", "attn_lse", "num_kv_splits"):
                    t = getattr(md, attr, None)
                    if t is not None:
                        observer.tensor(
                            f"L{g}_scratch_{attr}_pre", t,
                        )
        out = orig_backend_forward(
            self, q, k, v, layer_id, batch, attn_spec=attn_spec
        )
        if md is not None and is_chunk2_call and g in (0, 1):
            observer.tensor(f"L{g}_attention_output", out)
            kv_len = (
                int(md.indptr[-1].item())
                if md.indptr is not None else None
            )
            observer.tensor(
                f"L{g}_kv_slice_post_write",
                self.kvcache.k_cache(layer_id)[:kv_len],
                kv_len=kv_len,
            )
            for attr in ("attn_logits", "attn_lse", "num_kv_splits"):
                t = getattr(md, attr, None)
                if t is not None:
                    observer.tensor(f"L{g}_scratch_{attr}_post", t)
        return out

    TritonAttentionBackend.forward = instrumented_backend_forward

    sink.write("installed", {
        "stage_label": stage_label,
        "out_dir": str(sink.out_dir),
        "argv0": os.environ.get("ISSUE157_STAGE_ROLE", stage_label),
    })
    return observer


def _wrap_attention_instance(
    observer: Chunk2Observer, attn, g: int
) -> None:
    """Wrap ONE attention instance's internal ops so the ORIGINAL
    execution path runs unchanged while intermediates are captured."""

    def wrap(obj, attr, checkpoint, reshape=None):
        orig = getattr(obj, attr)

        def wrapped(*args, **kwargs):
            out = orig(*args, **kwargs)
            if observer.deep:
                observer.tensor(checkpoint, out)
            return out

        setattr(obj, attr, wrapped)

    wrap(attn.qkv_proj, "forward", f"L{g}_qkv_projected")
    wrap(attn.q_norm, "forward", f"L{g}_q_normed")
    wrap(attn.k_norm, "forward", f"L{g}_k_normed")
    wrap(attn.v_norm, "forward", f"L{g}_v_normed")
    wrap(attn.rotary, "forward", f"L{g}_rotary_applied")
    wrap(attn.o_proj, "forward", f"L{g}_o_proj")
