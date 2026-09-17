#!/usr/bin/env bash
# R8-G diagnostic build (Issue #207 Phase 1), run on inferswarm01 as user
# hermes. Builds the observation-only llama-server from the EXACT accepted
# source b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 in a SEPARATE worktree
# /home/hermes/llama.cpp/r8g-obs (accepted binaries untouched).
#
# Usage: bash r8g-build.sh <path-to-apply_hook.py-in-repo>
set -euo pipefail

COMMIT=b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
BASE=/home/hermes/llama.cpp
WT=$BASE/r8g-obs
BD=$WT/build-r8g
APPLY=${1:?path to apply_hook.py}

cd "$BASE"
if [ ! -d "$WT" ]; then
  git worktree add "$WT" "$COMMIT"
else
  (cd "$WT" && git checkout -q "$COMMIT" && git clean -qfd)
fi
cd "$WT"
git rev-parse HEAD | grep -q "^$COMMIT$" || { echo "wrong HEAD"; exit 1; }

PRISTINE_SHA=$(sha256sum tools/server/server-context.cpp | cut -d' ' -f1)
python3 "$APPLY"
APPLIED_SHA=$(sha256sum tools/server/server-context.cpp | cut -d' ' -f1)
PATCH_SHA=$(sha256sum "$APPLY" | cut -d' ' -f1)

mkdir -p "$BD"
cd "$BD"
cmake .. -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=86 -DLLAMA_CURL=OFF -DGGML_RPC=ON \
  -DGGML_CUDA_FA_ALL_QUANTS=OFF \
  -DGGML_CUDA_FA_QUANTS='q4_0-q4_0;q8_0-q8_0;f16-f16;bf16-bf16' \
  -DGGML_CUDA_COMPRESSION_MODE=size > cmake-config.log 2>&1
cmake --build . --target llama-server -j 8 > build.log 2>&1

BIN=$BD/bin/llama-server
BIN_SHA=$(sha256sum "$BIN" | cut -d' ' -f1)

echo "BUILD_OK"
echo "pristine_source_sha256=$PRISTINE_SHA"
echo "applied_source_sha256=$APPLIED_SHA"
echo "patch_sha256=$PATCH_SHA"
echo "binary=$BIN"
echo "binary_sha256=$BIN_SHA"

# byte-identity proof: re-apply to a pristine checkout, compare
cd "$BASE"
VERIFY=$(mktemp -d)
git worktree add -q "$VERIFY" "$COMMIT"
python3 "$APPLY" -n 2>/dev/null || true
cd "$VERIFY"
git checkout -q -- . 2>/dev/null || true
# apply again on pristine
python3 "$APPLY" >/dev/null
V_SHA=$(sha256sum tools/server/server-context.cpp | cut -d' ' -f1)
if [ "$V_SHA" = "$APPLIED_SHA" ]; then echo "REPRO_IDENTICAL"; else
  echo "REPRO_MISMATCH $V_SHA"; fi
cd "$BASE"
git worktree remove --force "$VERIFY" >/dev/null 2>&1 || true
