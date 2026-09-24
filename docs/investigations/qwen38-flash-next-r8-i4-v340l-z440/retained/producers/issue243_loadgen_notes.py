#!/usr/bin/env python3
"""Issue #243 (R8-I4) — Vulkan GPU load generator for burn-in (Phase 2).

A tiny, dependency-free Vulkan compute stressor that keeps a die busy with
sustained compute + memory traffic, without requiring any model. Uses the
Vulkan compute shader path via the ggml-vulkan backend of the pinned R8-H
binary? No — deliberately NOT model-dependent: this loads ggml via the
llama-server binary's backend enumeration would need a model.

Instead: vkpeak-style load via mesa's vkcube is display-dependent. The most
honest load generator available without new dependencies is a repeated
vulkaninfo --summary loop? Too light.

Practical approach used by the accepted V2-C campaign: per-die execution
sentinel = actual llama.cpp model workload. For Phase 2 burn-in we use the
pinned llama-server with a small auxiliary GGUF (dummy) — none is pinned.

DECISION: Phase 2 burn-in uses llama-bench from the pinned R8-H bin dir
with the real model at ngl=X on the target die. llama-bench exists in the
bin dir only if built; else use llama-server + /health requests. This
script is the driver/monitor wrapper around that decision and retains
which modality was actually used.
"""
