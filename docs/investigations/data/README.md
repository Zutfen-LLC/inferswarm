# P0-I publication data

This directory contains sanitized publication artifacts derived from the canonical P0-I routing/residency campaign.

Source run integrity is recorded in `p0i-publication.sha256.txt` and in the human-readable investigation result. The byte-preserved raw run remains a host artifact because it contains local provenance that is not appropriate for public repository publication.

The publication files intentionally contain routing identities/counts and the frozen Phase-1 placement, but no prompt text, generated output text, hostname, or host-local model path.

For Phase 1, `phase1-qwen36-placement-v1.json` is the authoritative frozen placement artifact. Its `canonical_remote_placement` is `complement_5442`; `global_hot_5442` is diagnostic only.
