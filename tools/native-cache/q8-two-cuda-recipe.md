# Later Hermes recipe: Q8 on two CUDA devices (#313)

This recipe is a reviewable handoff, not execution authority. Physical access,
model reads, downloads, GPU probes and host operations remain outside this
coding task. Stop on any identity, capacity, placement or cleanup mismatch.

## 1. Current inventory and identity admission

1. Record fresh read-only inventory for inferswarm05 and inferswarm03: CPU/RAM,
   free RAM and swap, source member identities under `/srv/models`, free SSD,
   existing listeners/process owners, both GPU UUIDs, PCI addresses, negotiated
   link widths, driver/runtime versions, clocks, temperatures and measured free
   VRAM. Historical labels such as x16/x4 and nominal 12 GiB are hypotheses.
2. Bind inferswarm05 as the full-source CPU coordinator and inferswarm03 as the
   assigned-only worker. Do not acquire full model members on the worker.
3. Admit the exact reviewed `step-a-cpu05-cuda03` client/worker manifests only
   when the deployed executables, libraries, compiler/CUDA closure and native
   pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` match. If the observer must
   change to emit endpoint/device ordinals, build into a fresh owned directory,
   capture complete manifests, and stop for separate review. Never alias a CPU
   identity as CUDA or promote a source-inspected candidate.
4. Bind device order by observed UUID: worker `CUDA0,CUDA1`; use the worker's
   fully-qualified DNS name and its absolute trailing-dot spelling for the two
   registrations. Independently resolve both spellings to the same worker and
   verify that they enumerate the intended devices as `RPC0` and `RPC3` in
   that order.

## 2. Freeze budgets from the real census

Generate the full plan before launch. Require exact, disjoint state ranges and
the fixed ownership census: layers 41--44 on GPU 0 (11,035,064,960 B encoded
weights), layers 45--47 plus output on GPU 1 (8,957,357,824 B), all earlier
layers/source on the coordinator. For each GPU separately, sum encoded weights,
persistent state/KV, backend extents/repacking, graph, workspace, observer and a
declared reserve against measured available VRAM. For worker RAM, sum assigned
metadata/page residence, verification, transport, receive/cache staging,
runtime heap and a declared host reserve against measured available RAM. Record
phase peaks rather than aggregating VRAM or treating worker RAM as a weight
mirror. Unknown or unmeasured terms, insufficient headroom, or a plan that
requires the full model on the worker are STOP.

## 3. One cold start and one restart

1. With owned processes stopped, run the existing assigned-only preparation.
   Acquire only missing immutable whole tensors for both GPU banks. Record
   source reads/hashes, weight payload, metadata/control and cache publication
   separately.
2. Start one owned RPC server with `--device CUDA0,CUDA1`, then the coordinator
   with the two endpoint registrations, `--device CPU,RPC0,RPC3`,
   `--gpu-layers 8`, and `--tensor-split 4,4`. Use the unchanged short fixed
   request and existing numerical diagnostics/thresholds.
3. During the request, bind samples to owned PIDs and UUIDs. Require measured
   weight residency and backend execution on both GPUs, per-device peak/reserve,
   worker host peak/headroom, the coordinator-mediated GPU0-to-GPU1 transition,
   correct final output custody, and complete cleanup. CPU-fixture evidence is
   not a substitute.
4. Stop only the owned processes. Reconstruct preparation from the unchanged
   durable cache, start once more, and repeat exactly the same request. Require
   zero missing-weight acquisition payload and zero unchanged-weight SET
   payload, while again observing both GPUs and the same placement/output.

Preserve cold/restart receipts and failures. Do not retry into PASS, adjust the
frozen allocation after launch, run extra requests, claim fit from nominal VRAM,
or close #313/#311/#315/#300. The next smallest physical operation is exactly
this one cold/restart pair after the per-device observer receipt and complete
memory census have received separate review and dispatch.
