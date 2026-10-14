# Future bounded hardware check (#315)

This is a recipe for later explicit physical dispatch, not execution authority.
The target is one worker with 16 GiB host RAM and two 12 GiB GPUs. It remains
unqualified. Compact native fixtures can test the patched RPC path directly under
separate physical dispatch; both endpoints need the same patched identity. A
full Q8 operator acceptance additionally needs the selective source-contract
connection described in [README.md](README.md).

1. Freeze the model revision/representation, exact assigned immutable ranges,
   shared metadata, runtime/build hashes, per-device usable headroom, host staging
   envelope, disk budget and stop thresholds. Use the current Q8 subject for
   initial comparisons. Include loader/source work in coordinator accounting.
2. On an empty owned cache, load the declared assignment once. Record exact
   acquisition payload, setup/control bytes, local reads/hashes, actual host
   RAM/swap peak and per-GPU residency. Verify correctness before any timing
   comparison. Stop on integrity failure, OOM, swap/headroom breach or identity
   drift; preserve the failure without retrying it into a PASS.
3. Reconnect, then restart the worker using unchanged disk backing. Require zero
   unchanged weight payload and correct materialization. Change A+B to B+C;
   require only missing C payload. Verify valid unassigned A remains within the
   configured disk budget. Measure activations separately during a bounded
   request under its separately approved workload envelope.
4. In a disposable fixture cache, interrupt a publication and corrupt/truncate a
   published file. Require no accepted false hit and complete verified recovery.
   Preserve original source/cache/evidence. Confirm transient host staging is
   bounded as assigned/cache size grows; CPU RSS from this PR cannot qualify it.

No merge, cluster/GPU action, model acquisition, full-model inference or #300
closure is authorized by this coding PR. Do not dispatch Final CPU Validation
from this task; maintainer review is the stopping point.
