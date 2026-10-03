# Issue #264 — prospective bounded methodology

**Frozen:** 2026-10-02. **State:** prospective method only; conditional authority, not a dispatch or execution authorization. This document adds an issue-specific method without editing or rewriting prior methodology amendments or historical evidence.

## 1. Scope, authority, and source identity

Issue #264 is OPEN; its complete body was retrieved and reviewed via the public GitHub API, with issue and PR authentication handled by the controller. The only live source candidate is `DMMV_WORKGROUP_SUBGROUP_TO_LARGE`, the minimal experiment-only BASE/alternate selector at existing DMMV workgroup selection. Exact frozen operation: `output.weight`, `mat-vec`, pipeline `mul_mat_vec_q4_k_f32_f32`, `quant_y=0`, `split_k=0`, dimensions `2560x248320:2560x1->248320x1`, types `q4_K*f32->f32`. BASE is SUBGROUP/reduction SUBGROUP/local `{32,1,1}`; alternate is LARGE/reduction HYBRID/local `{128,1,1}`. The shared pipeline name is insufficient to distinguish the arms: require a dispatch marker naming the final resolved variant.

The current source identity is `issue264-source-identity-v2.json`, full tree `23d38b96e371ad0634454d7bd6fe238da87eb1cb`, patch SHA-256 `f713767755cd40ee279aba6d4e72648c317e73a334d565a6cd0f176284e3226e`. Gen1 is preserved as historical source identity only. Before execution, the controller must freeze/authenticate the exact comparator binary, full build identity, and current exact execution head; this methodology does not supply those values or claim they are already frozen.

The issue's physical authority is conditional on its separate current pre-execution gate. This document, a source test, a successful dry gate, CI, or source-level capability does not itself authorize physical execution. If exact current authority or any required gate is absent, stale, ambiguous, or mismatched, stop before launch.

## 2. Pre-execution gates

Before any physical unit, an authorized controller/maintainer must establish and retain all of the following against the exact execution head:

1. Current issue-specific pre-execution authorization and allowed arm/scope; revalidate before each unit as required by the gate.
2. Exact source-tree identity and selector/marker identity, with BASE and alternate both resolving to the expected workgroup, reduction, local size, and same shared pipeline name.
3. Exact comparator binary digest plus reproducible/recorded build configuration and toolchain identity; no substitution of an earlier comparator or binary.
4. Frozen model, request, fixture, output extraction, subject GPU UUID/BDF, driver/runtime, and placement. The subject capability facts are not a substitute for live identity/health validation.
5. Focused source/parser/producer tests, relevant CI with no failure, build/binary inspection, and a non-dispatch dry gate. No physical pilot before these gates pass and exact-head authorization is valid.
6. Output, log, process, and evidence custody destinations created without overwriting prior evidence; enough authorized disk/resource budget for the bounded population.

The full CPU suite and hosted CI required by repository policy are **final exact-head GO gates** after maintainer review of the exact final head. Do not run or represent them as final-head approval before that GO. A later head change invalidates exact-head approvals and requires revalidation.

## 3. One-factor contract and observation

Each fresh-process unit changes only the selector state: BASE `SUBGROUP/SUBGROUP` versus alternate `LARGE/HYBRID`. Keep model and model members, binary, prompt/request, decoding settings, frozen fixture, output projection, tensor geometry/types/quantization, split_k, device placement, and all other relevant settings identical. No bundled controls, environment variation, runtime tuning, or settings search.

For every unit retain the exact dispatch marker tied to the frozen node and event, recording route, dimensions, types, `quant_y`, `split_k`, shared pipeline name, requested selector, and actual final resolved workgroup/reduction/local-size identity. Require every expected frozen output event exactly once and reject missing, extra, malformed, wrong-node, wrong-shape, wrong-type, or wrong-variant events. A marker is admissible only when bound to the exact authenticated process, source, binary, request, and unit; text alone is not proof.

## 4. Bounded population and repeat law

Use the same frozen fixtures and subject for BASE and `H5_MMV_CANDIDATE`. Because the comparator/source identity changed, this is a new population; historical #262 units are contextual read-only evidence only and cannot be reused as units, baselines, or accepted outcomes.

For each arm, collect two fresh-process units first. If and only if the first two valid observations are equal under the frozen comparison, collect one third fresh-process unit; otherwise stop that arm at two and retain the mismatch. Hard cap: two to three units per arm, six total. Do not retry, discard, replace, or selectively repeat a failed, inconvenient, mismatching, or anomalous unit. Retain every attempt with its failure/admissibility state; any operational failure is a retained attempt and requires the gate's explicit disposition before proceeding, never a silent retry. Do not expand the population or add arms without separate authorization and prospective methodology review.

## 5. Raw-unit custody and comparisons

For every attempted unit, retain append-only raw request bytes, raw response bytes, unmodified stdout/stderr logs, exact dispatch marker lines in context, process identity and argv/environment attribution, source tree and patch identity, comparator binary digest/build identity, model-member identities, fixture digest, subject UUID/BDF and health/runtime observations, arm, fresh-process boundary, start/end timestamps, exit status, and per-file cryptographic digests. Store a manifest binding these materials to the unit and exact authorization. Never overwrite, prune, rewrite, or cherry-pick. Derived summaries must reference retained raw-unit digests and remain reproducible; synthetic/parser fixtures must be clearly marked and never represented as physical units.

Compare paired observations only under the frozen request/fixture and numerical comparison rule supplied by the authorized producer. Report raw values, exact descriptive deltas, and the path-transition result. Treat path transition as the primary **descriptive** observation of selector effect. Numerical behavior is descriptive and conditional on admissibility; neither equal nor differing outputs alone prove a root cause or broad mechanism.

## 6. Interpretation boundaries and prohibitions

This is a bounded discriminator pilot, not a theorem or general performance/accuracy study. Even a repeatable path transition or numerical difference supports only the narrow frozen operation, selector, binary, model/request, and subject observed. Do not claim an H5 theorem, general MMV behavior, production safety, universal numerical equivalence, or root-cause proof. Do not infer control liveness from capability enumeration alone; use the actual exact dispatch marker.

No R8-J access or inference; no coopmat2, MMVQ, split-K, mat-mat, broad matrix, unrelated arms, comparator/2 changes, production selector, CUDA substitution, stress/holdout, or broader settings search. Do not change historical amendment text, prior accepted evidence, status ledgers, CI configuration, reducers, or sibling-owned pilot scripts in this methodology task.

## 7. Terminal and stop law

This methodology does not define or mint a terminal. Preserve all attempted evidence and await the authorized reducer/reviewer for any disposition under the applicable issue gate. Missing or invalid gates, source/binary/subject/request mismatch, marker ambiguity, unexpected pipeline identity, incomplete raw custody, or execution outside the exact authorization means stop and quarantine the attempt; never convert an invalid or absent observation into a favorable result or zero-candidate conclusion.


## 8. Gen2 corrections: frozen workload, exact observer law, and control classifications

This section supersedes conflicting prospective workload/comparison statements above for gen2 only. The exact accepted workload is the existing Issue #250 `case-3072` fixture, not caller-provided text. The authority is `scripts/issue250_physical.py::verify_fixtures(repo_root)` in the accepted Issue #250 fixture-manifest tree; it verifies `D.FIXTURE_LADDER_REL` (`docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json`) against `D.FIXTURE_LADDER_SHA256` = `419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db`, then resolves `case-3072` from that verified manifest. The accepted frozen request is the exact Issue #250 `D.REQUEST_CONTRACT`: `cache_prompt=false`, `n_predict=8`, `return_tokens=true`, `samplers=["top_k"]`, `seed=0`, `stream=false`, `temperature=0.0`, `top_k=1`. The verified case-3072 prompt is 3077 tokens (the label is not its token count). Cite and validate against that existing accepted fixture manifest; do not substitute a prompt or fixture. Before any launch the producer must freeze and retain the canonical execution-payload digest derived from the accepted request plus the exact verified prompt, then independently revalidate that same digest immediately before launch. A caller-supplied prompt is forbidden. Any mismatch stops before launch.

Each observer decision row is exactly one complete 248,320-element float32 vector: 993,280 bytes. For each unit, require exactly eight complete observer-row byte strings in decision-index order 0 through 7, with metadata and readers enforcing eight rows, index continuity/order, and exactly 993,280 bytes per row; reject missing, extra, partial, reordered, or malformed rows. The repeat comparison is exactly: SHA-256 over the bytewise concatenation `row[0] || row[1] || ... || row[7]` of the eight full observer-row byte strings in that index order (not concatenated hex digests, row hashes, selected rows, metadata, or decoded/normalized floats). Compare the resulting digest for the first two fresh-process units. If they mismatch, stop the arm at unit 2 and classify the screening result `screening-variable`; if they match, run exactly one third unit, then compare all three full-concatenation digests. The third unit does not erase or downgrade a mismatch: any disagreement among the three is `screening-variable`; only three matching digests yield screening-stable. Hard cap three attempts, no replacement/retry.

The sole live candidate remains `DMMV_WORKGROUP_SUBGROUP_TO_LARGE`, source priority 3, as the minimal source switch. `GGML_VK_SERIALIZE_SUBMISSIONS` is explicitly A1: its existing `ggml_vk_submit` serialization branch (`device->serialize_submissions`) changes queue submission synchronization only; it leaves the selected MMV pipeline/workgroup unchanged and is dead for this frozen MMV-selection question. A4 `GGML_VK_PREFER_HOST_MEMORY` and A5 `GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM` are allocation-placement policy branches (host-visible/coherent versus device-local placement), not MMV pipeline/workgroup selection factors; classify both `REJECTED_NOT_ONE_FACTOR` for this frozen experiment. `subgroup_arithmetic_reduction` is automatically capability-selected in the existing DMMV implementation; there is no exposed independent control that changes only that capability while holding the selected implementation fixed. Classify it `REJECTED_NOT_ONE_FACTOR`, not as another live candidate. All rejected/dead rows must preserve the ledger's complete required schema fields (`id`, `site`, `exact_pipelines`, `frozen_eligibility`, `one_factor`, `subject_capability`, `disposition`, `reason`) and identify the precise source branch/site and effect. There is exactly one `LIVE_CANDIDATE`; do not invent additional live controls.

This is a source-only correction, not physical authorization or execution evidence. Gen1 methodology/audit/ledger/manifest bytes remain immutable historical snapshots; gen2 artifacts and this exact methodology are additive.
