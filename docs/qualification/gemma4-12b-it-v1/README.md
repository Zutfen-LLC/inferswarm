# Gemma 4 heterogeneous numerical-equivalence methodology

Issue [#74](https://github.com/Zutfen-LLC/inferswarm/issues/74) is the
canonical gate. [ADR 0010](../../adr/0010-heterogeneous-numerical-equivalence.md)
and its [normative supplement](../../architecture/numerical-equivalence-contract.md)
control this methodology.

The methodology is frozen for review. Physical execution is not authorized.

- [METHODOLOGY.md](METHODOLOGY.md) defines the campaign and stop rules.
- [REDUCER.md](REDUCER.md) defines numerical reduction.
- [EVIDENCE.md](EVIDENCE.md) defines evidence, preflight, and invalid runs.
- `manifests/` contains the exact corpus and all commitments.
- `manifests/qualification-draft.json` keeps the candidate excluded until all
  physical evidence and the sealed holdout pass.
- `schemas/` contains the preflight, attempt-evidence, calibration-summary, and
  threshold-manifest schemas.
- `MANIFEST.sha256` hashes every review artifact and synchronized document.
- `sealed/holdout.cms` is the encrypted holdout package.
- `sealed/recipient-certificate.pem` identifies the holdout recipient key.

The private holdout key and deterministic secret seed are not in this
repository. The custodian must not release them before a threshold manifest is
committed and independently verified.

Historical R6 remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. This directory
does not replace or modify its evidence.
