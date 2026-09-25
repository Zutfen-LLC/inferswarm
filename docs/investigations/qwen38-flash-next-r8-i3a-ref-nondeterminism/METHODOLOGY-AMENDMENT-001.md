R8-I3A diagnostic methodology amendment 001 — correction round 2
=================================================================

Dated 2026-09-24. Repository-only correction; no physical diagnostic unit,
model workload, predictive case, or case-4096 has been executed by this
correction. The accepted #241 evidence, comparator/2 methodology, blocked
terminal, and #248 Phase-0 analysis are unchanged.

Freeze chronology caveat: the original METHODOLOGY.md header states
"FROZEN 2026-09-25". That date is later than this amendment's date. The
original document remains byte-identical; this amendment does not assert
that a future-dated header proves a completed freeze. Maintainer review
must resolve the chronology before any physical dispatch.

Health custody
--------------
A successful unit must retain a bounded raw kernel journal query (including
an exit-zero empty response as a negative observation), a raw NVIDIA driver
telemetry query, and the producer's timestamped before/during/after samples.
The reference-arm samples include the executing GPU's raw NVIDIA driver
telemetry within the unit window; the candidate-arm samples include raw AMD
hwmon sensors. The health receipt fixes each artifact's relative path, byte
count, SHA-256, and execution window, plus the exact collection command and
return code. The unit receipt binds the health receipt's bytes, SHA-256, and
window. The reducer checks every required unit's actual bytes, digests,
collection shape, and device identity independently; absence, malformed
bytes, wrong windows, and receipt/raw disagreements block with terminal null.
A post-run driver query is identity/context evidence only: its untimestamped
throttle state cannot establish a causal in-window hardware failure.

A platform-instability terminal requires a verified fatal observation in a
unit window: a subject-BDF NVIDIA XID/device-loss or fatal PCIe/AER line,
a host-fatal kernel marker, a timestamped executing-device driver thermal or
power limit, a retained driver critical sensor violation, or an explicit
low-level fatal marker in a producer sample. An unrelated GPU's XID or a
numeric temperature/power reading without a driver limit is not a fatal
predicate. All required units must independently verify before even a
positive platform finding may select a terminal.

Terminal authority
------------------
The reducer consumes the complete frozen Phase-1 repeatability population,
Phase-2A ngl=1/2/4/6/8 two-repeat placement ladder, Phase-2B
case-256/1024/3072 two-repeat regime ladder, and the Phase-3 observer and
canonical controls. Each unit is bound to its frozen namespace, tag, case,
arm, index, ngl, binary digest, three-member model set, request contract,
launch argv/environment, executing process attribution, response bytes,
observer row bytes, dual-capture row, identity observations, and raw platform
health. Extra current units cannot be silently omitted from a plan.
case-4096 is not required for completion and remains forbidden without the
same comment's explicit authorization.

Within-process comparator/R8-E agreement at position zero establishes
capture faithfulness, not Vulkan causality. Stable tokens from a different
binary do not establish comparator-observer causality; the comparator-off
variant has no row capture. The accepted frozen probes do not contain a
reviewed same-binary, single-factor row-level observer intervention or a
Vulkan-specific causal control. Therefore neither localized conclusion is
reachable from these probes alone. Complete row variation without such a
control yields R8I3_REF_NONDETERMINISM_UNRESOLVED, with retained placement,
regime, capture, and health facts; an absent required observation yields
R8I3_REDUCER_BLOCKED_INCOMPLETE with terminal null. A deterministic first
repeat population cannot override contradictory later completed probes.
No new intervention is authorized by this amendment.

Old-head defect reproduction (ec9a064d8af174fe2c4edac5748728ac1a7dee5e)
-------------------------------------------------------------------------
In a CPU-only scratch unit with unit.json and identity-post.json but without
device-samples.json or kernel-journal.raw, the old _platform_health returned
fatal_states=[] and a sole identity-post.json evidence path. Its required
probe names were only repeat, observer, canonical. The old terminal decision
branch, with its dual-capture helper held satisfied to isolate that branch,
emitted R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED and
platform_health_clean=true without any Phase-2 probe. An AST count over the
old tests/test_issue248_diagnostic.py found zero direct derive_terminal calls.
The old branch proof isolates decision logic; it does not claim a physical
Vulkan result. The new direct tests use retained-byte fixtures and reject
missing or contradictory health and Phase-2 evidence.
