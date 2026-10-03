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
