# V0-C final terminal and canonical-attempt disposition

Issue: Zutfen-LLC/inferswarm#143

Terminal: `V0C_EVIDENCE_BLOCKED`

A final authority-pinned qualification and one plan-driven canonical attempt
were performed locally on `inferswarm02`. The V0-C executable was
`/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli`, SHA-256
`5a8f5edec3cafce77e371b082f4dd52f07d38a72704a652063f6255a018c36ec`.
The older V0-A executable was not used.

Qualification `v0c-amd-a-final-qualification-01` passed with the exact source,
runtime, and model identities, selected `Vulkan1` at `02:00.0`, 37/37 layer
offload, no fallback, and clean exit. It minted
`cap-v0c-amd-a-s2-final-01` and the generic planner selected
`candidate-d3a1cdda2ead943f86e5c00ac534420964566ac8ddb237d53e0009b1702d25d4`.
The frozen plan digest is
`f0e9c51393ece62b3164b4c1050aa2e4651b91f67de5bb81747aeb11cb041464`.

Canonical attempt `v0c-amd-a-final-canonical-01` had clean exit, exact device
and full-offload proofs, and no fallback. Its direct llama.cpp diagnostics
included named model/KV/compute buffers and the ready-state marker, but after
ready emitted memory-breakdown headers without final Host/device breakdown
rows. The parser therefore cannot mechanically establish unexplained persistent
host mirror bytes, source fetches after ready, or unplanned state movements.
It does not manufacture zero from process RSS or missing lines.

Consequently no object under the canonical-execution-observation schema and no
execution receipt was minted. The retained raw attempt, accounting failure,
correctness reduction, and controls identify the concrete blocker. The old
`v0c-amd-a-01` smoke remains noncanonical; it supplied neither a tolerance nor
an output-derived contract change. The opaque execution-contract gate remains
an architectural S2 clarification.

This remains an integration spike: no public API, preferred/default-backend
ADR, production-support claim, or cross-backend equivalence claim is made.
