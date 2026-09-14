Superseded evidence — attempt arme-182-physical-1
==================================================

The two warm-inventory observation records in this directory were
collected on 2026-09-14 by the pre-correction collector at commit
3276d463b2cf0fcad55a4a78ab3c5af6e721a481, under attempt
`arme-182-physical-1`.

Maintainer pre-review comment 5666244858 (NO-GO) established that
these records cannot carry acceptance authority in the Arm-E campaign:

- P1-1: the collector converted host-probe failures into empty
  observations (failed `ps` read as zero processes; failed
  `nvidia-smi` produced no GPU totals and the drift check silently
  skipped the host; failed `ss` was indistinguishable from no
  listeners) — the retained records do not mechanically distinguish
  "probe succeeded and observed none" from "probe failed";
- P1-2: the record carried no observation freshness/version identity;
  the warm snapshot's `sequence: 2` was manufactured by the planner
  adapter, not observed or authority-bound;
- P1-3: `sha256-*` objects were marked byte_digest_verified from a
  freshly computed digest without proving the filename's
  content-address identity, and nothing restricted objects to
  accepted verified-cache provenance.

What the superseded records DID prove is retained unchanged: the
physical cache state itself (411 objects on inferswarm01, 218 on
inferswarm03, all byte digests matching the accepted Arm-B
post-acquisition identities, GPU telemetry, empty process fence) was
observed read-only with before/after byte-preservation proof, and no
mutation occurred. The records remain as superseded evidence per the
maintainer's instruction; they are not deleted.

Successor: attempt `arme-182-physical-2` under the hardened collector
(fail-closed probe receipts, authority-bound observation epoch
sequence 3, content-address identity + accepted-provenance equality)
re-observes the same roots read-only. See
`../observation/` for the authoritative records.
