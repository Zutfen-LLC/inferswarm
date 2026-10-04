# Issue #273 composed retained-byte boundary

Repository-only successor implementation. **Not physical qualification and not
permission to run a GPU.** PR #274 remains subject to exact-head review; earlier
#270 terminals and earlier full-suite/CI results are not current certification.
The #270 authority, comparator, terminal and historical evidence are not edited.
The existing #272 VRAM-total observation fix is retained.

## Public path

```python
from pathlib import Path
from issue273_evidence import produce_evidence_273
from issue273_reducer import derive_terminal_from_files_273

# Defaults use authenticated GitHub GETs with GH_TOKEN/GITHUB_TOKEN, never
# caller-supplied merged/association/verdict flags. No GPU commands run here.
proposal = produce_evidence_273(
    Path(capture_root), Path(new_evidence_root), Path(repo_root), merged_head)
# Independent maintainer/capture custody must now seal proposal['manifest_sha256'].
terminal = derive_terminal_from_files_273(
    Path(new_evidence_root), Path(repo_root), merged_head)
```

These are file-based producers/reducers over **fresh capture input**, not a live
inference executor. They neither discover hosts nor synthesize missing hardware
observations. The authorized future capture executor must emit the below raw
capture contract from its actual observations. It must complete all reference
primary/repeat units and derive determinism before launching any candidate.
The stager and reader independently enforce that order; staging does not even
parse/copy candidate receipts when retained reference bytes are nondeterministic.

`derive_terminal_273(admissions, determinism, pair_results)` remains deliberately
non-authoritative and always runtime-blocked. Only the file boundary can return
a positive terminal. Every supplied `transport=` is a **CPU recording seam**:
positive results are marked `evidence_mode=CPU_RECORDING_NONPHYSICAL` and
`physical_authority=false`. There is no caller flag to promote this to physical
authority. A default-transport result also requires `capture_mode=PHYSICAL`.

## Layout (new root; never an old #270 root)

```text
capture-input/
  freeze.json
  preflight.json
  source/<case>/<tag>/receipt.json
  source/<case>/<tag>/observation.json
  source/<case>/<tag>/rows/<decision>.f32

new-evidence-root/
  authority.json                 # independently reselected, never caller pins
  freeze.json                    # untouched capture bytes
  preflight.json                 # untouched capture bytes
  source/<case>/<tag>/receipt.json       # untouched pre-staging receipt bytes
  source/<case>/<tag>/observation.json   # untouched original observation facts
  source/<case>/<tag>/rows/<decision>.f32
  units/<case>/<tag>.json         # only row paths + staged_source binding added
  units/<case>/<tag>/rows/<decision>.f32 # independent copies, exact source bytes
  manifest.json                  # hashes of every other exact retained file
```

Cases are exactly case-256, case-1024, case-3072. Tags are reference,
reference-repeat, candidate, candidate-repeat; decisions are exactly 0..7.
A reference-nondeterministic production may contain the complete **reference-only**
set. That set can produce a reference-blocked terminal, never a positive terminal.
All other partial sets, extra files/rows, duplicate JSON keys, absolute/traversing
row paths, hardlinks, symlink files/directories/ancestors, empty extra directories,
nonregular files and concurrent directory-substitution attempts fail closed.
Manifest authentication reads actual stable file descriptors; subsequent
validators consume that same authenticated byte snapshot, not a second mutable
read or receipt digest claims.

The destination must be absent. The producer never overwrites existing evidence
or edits its capture input. Its return value is a custody-seal proposal, **not**
a terminal. Serialized output is read back before returning. Keep terminal/report
publication outside the exact evidence corpus (or separately authenticated);
adding a report file inside this root intentionally fails the exact-set law.

## Independent authority, dispatch and capture custody

The independent predecessor is the preserved historical tooling merge
`6d594eafd5ee16a640f029f63ebdd2cd96856abb`, **not** its invalidated physical
terminal. Accepted #237 ancestry, immutable #243 census/fixture authority and
#248 reference identity are consumed without redefining them. All transitive
local verifier sources plus the corrected producers are byte-checked against the
exact current Git head; frozen authority sources must also equal their predecessor
Git blobs. An uncommitted executable or substituted root authority cannot pass.
Fixture, model-member, binary, observer-library, source-pin/tree and placement
identities are selected from this authenticated predecessor contract, not chosen
from manifest labels. Placement remains explicitly reference=8 / candidate=7;
no shared #270 `ngl` constant is monkeypatched.

Both producer and reader authenticate PR #274's merged state, merge SHA, current
main SHA, main target repository and an OWNER/MEMBER issue #273 dispatch. The
canonical issue-defined dispatch is unchanged:

```text
R8I6A CORRECTIVE PHYSICAL DISPATCH
head=<exact merged main SHA>
namespace=c273-v340-comparator2-corrective
```

Exact stripped fields must be unambiguous; historical namespaces and duplicate
fields are rejected. Dispatch creation must follow the merged tooling timestamp.
The real default transport uses token-authenticated GitHub GETs and bounded,
complete comment pagination. Injected transport responses cannot publish physical
authority.

A manifest alone proves consistency, not who captured its bytes. This successor
therefore adds an **independent post-capture custody seal**, supplied by a
maintainer/capture custody authority through the authenticated issue comment
stream (not a writable evidence-root JSON and not a producer self-attestation):

```text
R8I6A CORRECTIVE CAPTURE SEAL
head=<the same exact merged main SHA>
namespace=c273-v340-comparator2-corrective
dispatch_id=<authenticated original dispatch comment ID>
manifest_sha256=<SHA256 of the retained manifest.json bytes>
```

Exactly one matching OWNER/MEMBER seal must exist, separate from the dispatch
comment, after all consumed runs finish. It authenticates the entire source/raw
capture population and its staged copies. The independent custody service must
verify the pre-staging capture/observation context before issuing this seal; the
stager must never self-publish one. This additional protocol needs maintainer
review before physical use. Changing bytes and regenerating a self-picked
manifest cannot change the externally selected seal. The CPU fixture maintains
an independent frozen transport snapshot and deliberately changes it only in
tests that simulate an authenticated malicious/invalid capture, allowing semantic
validators to be exercised beyond the byte-authentication gate.

## Capture contract and mechanical law

Source receipts use `inferswarm.issue273.captured-run/1`. They carry the new
campaign/namespace, exact head/dispatch, case/arm/repeat tag, reference ngl=8 or
candidate ngl=7, full process argv/env/PID, host/selector/ICD/BDF, subject identity,
fixture prompt bytes/token IDs, accepted runtime/model/build/request/context
identities, unique run/session/boot/start-tick provenance, start/finish times,
source-relative observation path, exactly eight row entries, sampled/forced token
arrays and per-decision metadata. Metadata records full vocabulary, actual greedy
winner, capture-before-force witness and the complete continuous prefix.

Raw observation objects use `inferswarm.issue273.raw-run-observation/1`. They are
original capture facts, **not** regenerated receipt labels:

- actual process attribution and run/session/boot/incarnation, observed inside
  that run's start/finish interval;
- complete two-GPU physical census: index, ICD, BDF, PCI vendor/device, GPU UUID,
  Vulkan UUID, device name/type; execution-observed used Vulkan UUIDs/backend;
- reference identity freshly observed and compared to accepted #248 fields;
- per-BDF before/peak/after residency counters for selected and excluded GPUs;
- runtime attestations from the captured process executable/source tree, loaded
  observer libraries, and both open/close model-member hashes;
- original observer-disabled and canonical token output and emitted-artifact
  inventories, with the distinct accepted canonical executable digest;
- successful kernel-log/PCIe/thermal/storage/power observation return codes,
  actual error inventory, negotiated width/speed, temperature, throttle and OOM
  observations. Missing/failed probes cannot become a successful empty census.

The independently sealed runtime/hash observations are capture attestations:
this reader does **not** retain/copy multi-GiB models or re-hash an unavailable
remote executable. The independent capture service must derive those facts from
actual files/processes rather than expected constants. The CPU fixture emits
synthetic observations explicitly under `CPU_RECORDING`; it proves serialization
and verifier composition, not that any GPU, executable or model was observed.

Selected process selector+ICD must resolve exactly one observed discrete device,
whose BDF/vendor/UUID matches the arm. Reference requires RTX3060 lineage and a
positive RX580 (AMD 67df) excluded record; candidate requires the independently
validated two-index preflight's frozen selection and positive second-V340 record.
Used-device UUIDs must be the singleton selected UUID. Selected residency must be
positive, excluded delta strictly below the accepted noise bound, and all devices
must reclaim residency after the run. Candidate placement must retain the
accepted ngl=7 residency window. Preflight also reuses the raw V340 identity
parser/comparison, including #272's required VRAM-total facts.

Source→stage binding is derived from source receipt **bytes** and all source row
**bytes**, including repeats. Stage metadata/identity cannot change, and staged
rows must equal source rows. Full-vocabulary FP32 size/finiteness and greedy
winner are independently re-derived. Unique process/session/run/source provenance
is enforced across all consumed primary/repeat units. Reference determinism uses
the existing independent retained-byte comparator first; a mismatch returns
`R8I6A_REFERENCE_NONDETERMINISTIC_BLOCKED` before candidate parsing or pair work.
Candidate runs must start after every reference unit finishes. Every primary and
repeat is fully admitted. Existing metadata/prefix, determinism, inertness and
anti-aliasing verifiers are reused independently of the defective shared-placement
validator. Both primary and repeat candidate prefixes must be the corresponding
reference winners. Numerical disagreement is diagnostic only and never controls
selection/admission. Historical #270 terminal strings cannot be reclassified via
a new schema.

## Verification scope

`tests/test_issue273_evidence.py` constructs a tiny, source-authenticated Git
repository and a real serialized CPU recording population. It exercises the
production capture→stage→manifest→independent-seal→reader→terminal path without
mocking validators. Public-path attacks include coherently rebound source/stage
prefix/provenance forgeries, raw device/exclusion/inertness/platform changes,
actual FP32 byte mutations, digest-claim forgery, missing/extra sets, symlink and
intermediate-directory substitution, independent-authority substitution, dispatch
ambiguity/stale merge/no seal, and reference stop-before-candidate controls.

The focused tests, preserved #270 suite, source mutation checker, planner/parity,
retention and status checks are local CPU gates only. Full-suite/hosted CI,
expensive finalizer and exact-head independent reviews remain parent-owned.
No historical evidence is rewritten; no holdout/private payload is opened; no
physical census, comparator execution, predictive calibration or threshold work
is authorized or performed by this implementation pass.
