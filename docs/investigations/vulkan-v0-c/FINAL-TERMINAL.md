# V0-C final terminal and physical-evidence disposition

Issue: Zutfen-LLC/inferswarm#143

Terminal: `V0C_EVIDENCE_BLOCKED`

## Mechanical canonical-execution audit

**Answer: yes.** The retained physical invocation in
`raw/v0c-amd-a-01/` occurred before the final capability/device/Memory
Resource/execution-unit hardening.

The raw observation was committed as
`0de81ddde18f2c7981fe1086f96d04e473f1cba1` at
`2026-09-12T13:22:53-04:00`, with parent
`93d65669ae432e9e7b16f01631d8b07c7eee7d5a`. Its tree bound the then-current
control-plane source bytes:

- `scripts/v0c_execution_seam.py` SHA-256
  `9a19017365ee69748891c0a619d6eaeb764273a124d506f6540336f23825b259`;
- `scripts/v0c_vulkan_adapter.py` SHA-256
  `3ff79f70342c8b8ca3c5c441fe7bcd4597ab748ca82911fbb24d5b19f6cf5537`.

The retained run binds the Phase-0 llama.cpp source commit
`8ea290247c87ced2ab245b056ffe96dbcf90d36c`, `llama-cli` SHA-256
`5a8f5edec3cafce77e371b082f4dd52f07d38a72704a652063f6255a018c36ec`,
model SHA-256
`9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`,
selector `Vulkan1`, and BDF `02:00.0`. Its backend stderr proves the selected
Vulkan device and 37/37 layer offload, but it was an adapter-substrate smoke
rather than a frozen-plan realization.

## Why the observation is not canonical for the final implementation

The final hardening changes correctness-bearing execution semantics, not only
metadata:

- a capability now requires an adapter-validated observation bound to the
  exact Compute Unit, Memory Resource, execution unit, evidence, BDF, and
  runtime identity;
- candidate identity now includes the Memory Resource, implementation, and
  evidence identities, and a frozen plan rejects a candidate with a different
  execution unit, Memory Resource, or derived candidate identity;
- fallback text and ambiguous/mismatched device/offload observations fail
  closed before a capability can be created.

Therefore the earlier smoke cannot establish final capability eligibility,
physical-device binding, Memory Resource binding, strategy execution-unit
binding, candidate/plan identity, fallback rejection, or final execution
attribution. It remains retained as the noncanonical initial observation;
it is not rewritten, reclassified as a pass, or used to derive a tolerance.

## Disposition and next authorized evidence

No new canonical physical execution was performed for this finalization. The
prospectively frozen methodology remains unchanged and permits a later
canonical run only when it is driven by the final frozen plan and can retain
all required materialization/residency, reconciliation, fallback, and result
attribution records. Until that evidence exists, the terminal is
`V0C_EVIDENCE_BLOCKED`.

This is an integration-spike result only. It makes no production Vulkan,
public API, preferred-backend, performance, or cross-backend-equivalence
claim.
