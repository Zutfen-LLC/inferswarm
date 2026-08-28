# P0-I publication data

This directory contains sanitized publication artifacts derived from the canonical P0-I routing/residency campaign.

Source run integrity is recorded in `p0i-publication.sha256.txt` and in the human-readable investigation result. The byte-preserved raw run remains a host artifact because it contains local provenance that is not appropriate for public repository publication.

The publication files intentionally contain routing identities/counts and the frozen Phase-1 placement, but no prompt text, generated output text, hostname, or host-local model path.

The historical `phase1-qwen36-placement-v1.json` artifact remains
byte-identical and replayable at SHA-256
`255dce5d335c5017de06eff54cfd1c8a0599d2dbd6c84c7fb0fb856701596a2c`.
Its `complement_5442` placement and `global_hot_5442` diagnostic are preserved.

The canonical pre-performance Phase-1 candidate now uses
`phase1-qwen36-placement-v2.json` / `coverage_constrained_complement_5442`,
SHA-256
`2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`.
Its checksum is published in `phase1-placement-v2.sha256.txt`; the correction
and its pre-performance firewall are documented in
`../../implementation/phase1-placement-methodology-correction-v2.md`.
