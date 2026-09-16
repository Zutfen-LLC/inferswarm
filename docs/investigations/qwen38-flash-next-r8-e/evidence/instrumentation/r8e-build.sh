#!/usr/bin/env bash
# R8-E observation build (Issue #199), verified steps on inferswarm01.
# Worktree /home/hermes/llama.cpp/r8e-obs at the exact accepted source
# b29c606e28a01b1bc8c1351026a0fa6e616bf6c4; apply_hook.py applies the
# observation-only hook to tools/server/server-context.cpp; build with
# the accepted configure flags into build-obs/. The accepted build-v041
# tree and its binaries are NEVER touched.
set -euo pipefail
cd /home/hermes/llama.cpp
git worktree list | grep -q r8e-obs || \
  git worktree add r8e-obs b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
cd r8e-obs
git status --porcelain | grep -v 'r8e-obs/' || true
python3 <path-to>/apply_hook.py
CUDACXX=/usr/local/cuda/bin/nvcc cmake -S . -B build-obs \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DLLAMA_CURL=OFF -DGGML_RPC=ON -DGGML_CUDA_FA_ALL_QUANTS=OFF \
  -DGGML_CUDA_FA_QUANTS="q4_0-q4_0;q8_0-q8_0;f16-f16;bf16-bf16" \
  -DGGML_CUDA_COMPRESSION_MODE=size
cmake --build build-obs --target llama-server -j 24
sha256sum build-obs/bin/llama-server
