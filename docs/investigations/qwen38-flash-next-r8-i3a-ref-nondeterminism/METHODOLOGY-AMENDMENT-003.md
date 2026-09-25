METHODOLOGY AMENDMENT 003 — Campaign-level model attestation
=============================================================
Dated: 2026-09-25 (maintainer STOP-order correction, PR #249)

Ordered by: maintainer STOP directive issued after the first physical
diagnostic unit had run (unit `case-3072-B-baseline-001`, completed and
QUARANTINED under `d248-ref-repeats/`; HEAD movement makes it
non-terminal-bearing).

Original text (METHODOLOGY.md, section 7 custody rules and the
run_diagnostic_unit gate order): every physical unit performed a full
SHA-256 verification of all three accepted model members
(`verify_model_members`) before launch — approximately 72.5 GiB of
hashing per unit across a ~31-unit campaign.

Observation that falsified the design: the per-unit full read adds a
complete model traversal to every unit without materially improving
the model-identity guarantee relevant to a single campaign execution
session; the maintainer classified this as unacceptable campaign
design and ordered the campaign stopped before any additional unit.

Exact amendment (this commit):

1. Before the first physical unit, `open_campaign_attestation` hashes
   all three frozen GGUF members against the accepted #241 SHA-256
   values exactly once and durably retains
   `model-attestation-open.json` (append-only) at the evidence root,
   carrying per member: canonical name/path, SHA-256, byte size,
   device/inode, mtime_ns/ctime_ns, explicit non-symlink/regular-file
   status, plus a canonical digest of the complete attestation.
2. Every physical unit binds `model_attestation_sha256` (the opening
   digest) in its receipt and performs only the cheap fail-closed
   stat/topology witness (`D.attestation_witness`) immediately before
   launch; any member path/topology/device/inode/size/mtime/ctime
   change stops the campaign and requires a full re-hash before
   further execution.
3. After the last unit, `close_campaign_attestation` performs one
   final full three-member SHA-256 verification, requires member
   digest+stat identity with the opening, and durably retains
   `model-attestation-close.json` (append-only).
4. Terminal reduction requires: valid opening attestation, every unit
   bound to it, every unit's stat witness matching the attested
   member identity, and a valid closing re-hash bound to the opening.
5. No unit re-hashes the member set on the unchanged campaign path
   (structurally asserted by
   `test_no_per_unit_model_rehash_on_the_unchanged_path`).

Why this is custody-design correction, not evidence weakening: the
cryptographic model-identity guarantee is preserved at campaign
granularity (open + close full hash against the same frozen accepted
digests, bounding the entire execution window), the per-unit witness
adds file-identity checks that did not exist before (inode/device/
timestamps), and all binary/request/identity/health/live-dispatch
gates are unchanged. No threshold, holdout, predictive, or
qualification semantics are touched.

Mutation controls (tests/test_issue248_diagnostic.py): changed member
bytes before opening, replaced inode with identical content, changed
size/timestamps, symlink substitution, missing member/topology,
arbitrary replacement model, missing opening/closing receipt, tampered
opening digest, closing/opening stat mismatch, unit bound to a foreign
attestation digest, unit stat-witness mismatch, append-only reopen
rejection, and the unchanged-model open→close positive path.
