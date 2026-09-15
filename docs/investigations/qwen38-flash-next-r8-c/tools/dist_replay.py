#!/usr/bin/env python3
"""Dist-replay verification over the retained R-arm logits.

Question: does llama.cpp's ACTUAL fallback sampler chain at b29c606e
("logits -> dist", mt19937(0), uniform_real_distribution, cumulative-sum
crossing over UNsorted vocab logits) reproduce the accepted R8-B reference
token stream from the R8-C tool's retained full-vocab logits rows?

This is the non-perturbation + mechanism proof combined: if the accepted
stream equals dist-replay(logits) on every position, the accepted R8-B
"greedy" was actually seeded distribution sampling, and every cross-arm
divergence is explained by sub-logit-noise numerical differences moving the
cumulative-sum crossing point.
"""
import json
import struct
import sys

class MT19937:
    def __init__(self, s):
        self.m = [0] * 624; self.i = 624
        self.m[0] = s & 0xFFFFFFFF
        for i in range(1, 624):
            self.m[i] = (1812433253 * (self.m[i-1] ^ (self.m[i-1] >> 30)) + i) & 0xFFFFFFFF
    def gen(self):
        if self.i >= 624:
            for i in range(624):
                y = (self.m[i] & 0x80000000) | (self.m[(i+1) % 624] & 0x7FFFFFFF)
                self.m[i] = self.m[(i+397) % 624] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
            self.i = 0
        r = self.m[self.i]; self.i += 1
        r ^= r >> 11; r ^= (r << 7) & 0x9D2C5680; r ^= (r << 15) & 0xEFC60000; r ^= r >> 18
        return r

def uniform_real_01(mt):
    # libstdc++ __generate_canonical<double, 53, mt19937>: two 32-bit draws
    return (mt.gen() * 4294967296.0 + mt.gen()) / 2.0**64

def dist_step(v, mt):
    n = len(v)
    mx = max(v)
    pr = [2.718281828459045 ** (x - mx) for x in v]
    s = sum(pr)
    rnd = uniform_real_01(mt)
    tgt = s * rnd
    run = 0.0
    for i in range(n):
        run += pr[i]
        if run >= tgt:
            return i
    return n - 1

def main(bin_path, meta_path, accepted):
    meta = json.load(open(meta_path))
    n = meta["n_vocab"]
    data = open(bin_path, "rb").read()
    assert len(data) == meta["n_rows"] * n * 4, (len(data), meta)
    mt = MT19937(0)
    picks = []
    for r in range(meta["n_rows"]):
        v = struct.unpack_from("<%df" % n, data, r * n * 4)
        picks.append(dist_step(v, mt))
    ok = picks == accepted
    print(json.dumps({
        "bin": bin_path, "sampler_mode": meta.get("sampler"),
        "dist_replay_tokens": picks, "accepted_stream": accepted,
        "exact_match": ok,
    }))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3])))
