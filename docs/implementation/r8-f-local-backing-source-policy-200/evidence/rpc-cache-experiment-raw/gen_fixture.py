"""Deterministic bounded non-Qwen fixture generator for the R8-F RPC cache
experiment. Produces a single binary payload sized just over the pinned
HASH_THRESHOLD (10 MiB) so it takes the SET_TENSOR_HASH cache-probe path,
without moving anything close to the 72.5 GB Qwen3.8-Flash-Next release.

Deterministic from a fixed seed via a counter-mode SHA-256 stream, so the
exact bytes (and therefore the exact FNV-1a/SHA-256 identities recorded in
evidence) are reproducible by anyone re-running this script.
"""
import hashlib
import sys

SEED = b"inferswarm-issue200-r8f-rpc-cache-experiment-v1"
SIZE_BYTES = 12 * 1024 * 1024  # > 10 MiB HASH_THRESHOLD, bounded/small


def generate(size: int = SIZE_BYTES, seed: bytes = SEED) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:size])


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "fixture.bin"
    data = generate()
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("path:", out_path)
    print("size_bytes:", len(data))
    print("sha256:", hashlib.sha256(data).hexdigest())
