"""Faithful Python re-implementation of the FNV-1a hash used by the pinned
llama.cpp commit b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 in
ggml/src/ggml-rpc/ggml-rpc.cpp:

    static uint64_t fnv_hash(const uint8_t * data, size_t len,
                              uint64_t hash = 0xcbf29ce484222325ULL) {
        const uint64_t fnv_prime = 0x100000001b3ULL;
        for (size_t i = 0; i < len; ++i) {
            hash ^= data[i];
            hash *= fnv_prime;
        }
        return hash;
    }

Used only to (a) predict the cache filename the pinned server will use for
a given fixture so an external adapter can pre-populate it, and (b)
cross-validate that prediction against the filename the real pinned binary
actually produces. This is NOT treated as InferSwarm trust authority -- see
docs/implementation/r8-f-local-backing-source-policy-200/evidence/
rpc-cache-experiment.json for the explicit non-claim.
"""
MASK64 = (1 << 64) - 1
FNV_OFFSET_BASIS = 0xcbf29ce484222325
FNV_PRIME = 0x100000001b3


def fnv1a(data: bytes, seed: int = FNV_OFFSET_BASIS) -> int:
    h = seed
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & MASK64
    return h


def hash_hex(data: bytes) -> str:
    return "%016x" % fnv1a(data)


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], "rb") as fh:
        print(hash_hex(fh.read()))
