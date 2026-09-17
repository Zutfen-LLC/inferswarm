# V2-B — Radeon Pro V340L dual-die qualification (issue #210)

Status: COMPLETE — terminal `V2B_V340L_DUAL_DIE_QUALIFICATION_PASS`
(derived by `scripts/issue210_terminal.py` from the retained artifacts;
see TERMINAL.json). The terminal mechanically requires, derived from
retained bytes on every run: per-die qualification/canonical PASS with
full offload, byte-exact output and accounting 0/0/0 across all
repeats, raw stdout/stderr digests re-hashed from the retained raw
files, correct and distinct selector/BDF bindings, distinct Compute
Units, portability audit PASS, the accepted V2-A predecessor identity
(merge `e38ebe9` declared by both authorities AND carried by the
retained accepted V2-A terminal artifact), and the retained Phase-1
topology proving root port `00:1d.0` and PM8533 upstream `02:00.0`
both negotiated Gen3 x1 (`8.0 GT/s`, width `1`) in
`raw/phase1/pci-topology.json`. A mutation of any one predicate
prevents the PASS terminal.

Both physical Vega 10 dies on the newly installed V340L were
independently qualified through the accepted V2-A reusable harness,
byte-unchanged: all 18 harness source files are byte-identical to merge
`e38ebe9` (mechanical git diff), of which 14 carry individual sha256
pins in accepted V2-A R3 artifacts (all re-verified):

- die A: selector `Vulkan1` -> BDF `06:00.0`, `cu-v340l-die-a` /
  `mr-v340l-die-a-vram`
- die B: selector `Vulkan2` -> BDF `09:00.0`, `cu-v340l-die-b` /
  `mr-v340l-die-b-vram`

Per die: fresh prospective v3 authority (this namespace), qualification
PASS with full 37/37 layer offload and zero-token-identity-probed
selector/BDF binding, generic plan, canonical execution PASS with
accounting 0/0/0 and byte-exact visible output vs the accepted frozen
V1-A reference, 3x canonical repeats with identical visible output.

Both dies produce byte-identical visible output (to each other and to
the frozen reference). The portability audit
(PORTABILITY-AUDIT.json) classifies all differences as
authority/runtime/evidence DATA ONLY: identical harness bytes, no
subject-specific code, no falsified invariant, both subjects coexist as
distinct Compute Units / Memory Resources in one generic snapshot (each
authority carries its sibling die as the ontology pressure resource).

## Environment (Phase 1, fresh freeze)

- host `inferswarm02`, Debian 13, kernel `7.1.8+deb13-amd64`,
  cmdline `amdgpu.rebar=0`
- runtime bytes reused byte-identically from accepted V2-A R3:
  llama-cli `5a8f5ede…` (llama.cpp `8ea290247…`, Vulkan build),
  Qwen2.5-3B-Instruct Q4_K_M `9c9f56a3…`, RADV Mesa 25.0.7-2+deb13u1,
  Vulkan loader 1.4.309
- topology: Intel 200-series PCH Root Port #9 `00:1d.0` —
  **negotiated PCIe Gen3 x1 (8.0 GT/s, width 1), mechanically proven in
  `raw/phase1/pci-topology.json`** — Microchip PM8533 fanout switch
  (`11f8:8533`, upstream port `02:00.0` negotiated Gen3 x1 / cap x16,
  internal switch-to-GPU links Gen3 x16) — two Vega 10 endpoints
  `1002:6864` (`06:00.0`, `09:00.0`), each amdgpu-bound, 56 CUs,
  8,573,157,376 B HBM2, ECC active, 8 GiB BAR0, SR-IOV total VFs 4
  with 0 enabled
- early-PCI bridge/BAR allocation retries appear in retained boot logs
  (`raw/phase1/dmesg_pci_retry.out`); final resources are valid and are
  environment evidence, not a qualification failure

## Discovery (Phase 2)

`v2a_discovery_v3.py` (accepted, unmodified): the two identically-named
dies classify AMBIGUOUS by exact-name join (recorded inventory fact) and
are bound ONLY by the bounded zero-generation identity probe — the
runtime's own selected-device line — retaining raw probe bytes under
`raw/discovery/`. Vulkan0 (Intel iGPU) bound by name-join. Selectors and
BDFs were freshly discovered; nothing was copied from the issue text.

## Negative controls

Fail-closed controls in `tests/test_issue210_v2b_v340l.py` (38 tests)
mutating the REAL retained evidence in isolated sandbox copies and
re-running the actual terminal reducer end to end: wrong/superseded
V2-A predecessor identity (merge and terminal), missing or non-Gen3-x1
Phase-1 topology evidence (root port Gen1/Gen2/wrong-width, PM8533
upstream Gen1/Gen2/wrong-width, erased speed/width), nonzero accounting
(recorded and raw-bytes-derived: unexplained host mirror, post-ready
source fetches, unplanned state movements), raw stdout/stderr digest
mutation, selector/BDF swap, one-die-PASS-only promotion, plus the
retained loader-level authority controls (wrong selector/BDF, stale
inventory, mutated accepted evidence, partial offload, wrong-die
attribution, accounting substitution).

## Nonclaims

No concurrent dual-die performance scaling, no aggregate 16 GiB
single-address-space semantics, no shared-x1 contention envelope, no
production scheduler policy, no x1 economic suitability (issue #35 owns
that), no Qwen3.8/DeepSeek V4.1 qualification, no mixed-vendor
execution, no SR-IOV VF support, no ROCm/HIP qualification, no
production Vulkan support, no public backend API stability, no
preferred/default backend decision.

## Harness identity

Accepted V2-A merge `e38ebe9` ancestral to campaign start
`267b983de…`. No V2-A harness file was modified; the V2-B scripts in
this directory are additive authority-builders/assemblers over the
accepted engine (`scripts/issue210_build_authorities.py`,
`scripts/issue210_assemble.py`, `scripts/issue210_terminal.py`).
