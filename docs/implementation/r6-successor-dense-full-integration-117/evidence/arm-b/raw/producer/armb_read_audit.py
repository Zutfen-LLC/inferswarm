
"""Runtime-read audit analyzer: classify every file access in a strace log."""
import json, re, sys
log_path, participant, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
GEMMA = "/srv/models/gemma-r6"
MATERIALIZED = "/srv/inferswarm/materialized/issue117"
CACHE = "/srv/inferswarm/cache/issue117"
weight_reads = []
classified = {"gemma_whole_model_reads": [], "materialized_reads": [],
              "cache_reads": [], "python_lib_reads": 0, "proc_sys_reads": 0,
              "other_reads": [], "gemma_config_metadata_reads": []}
for line in open(log_path, errors="replace"):
    m = re.search(r'"([^"]+)"', line)
    if not m:
        continue
    path = m.group(1)
    is_read = any(op in line for op in ('openat', 'readlink', 'stat', 'access', 'execve', 'mmap'))
    if not is_read:
        continue
    if path.startswith(GEMMA):
        if path.endswith("model.safetensors"):
            weight_reads.append(path)
            classified["gemma_whole_model_reads"].append(path)
        else:
            classified["gemma_config_metadata_reads"].append(path)
    elif path.startswith(MATERIALIZED):
        classified["materialized_reads"].append(path)
    elif path.startswith(CACHE):
        classified["cache_reads"].append(path)
    elif path.startswith(("/usr/lib/python", "/usr/local/lib/python", "/home/zutfen/FreeToken", "/srv/inferswarm/state/arm-b/scripts")):
        classified["python_lib_reads"] += 1
    elif path.startswith(("/proc", "/sys", "/dev")):
        classified["proc_sys_reads"] += 1
    else:
        classified["other_reads"].append(path)
doc = {
  "schema": "inferswarm.issue117.arm-b.runtime-read-audit/1",
  "participant_id": participant,
  "strace_log": log_path,
  "mechanism": "strace -f -e trace=file over the entire realization subprocess",
  "gemma_whole_model_weight_read_count": len(weight_reads),
  "gemma_whole_model_weight_paths": sorted(set(weight_reads)),
  "classified": {k: (v if isinstance(v, int) else sorted(set(v))) for k, v in classified.items()},
  "unexplained_full_model_dependency": 1 if weight_reads else 0,
}
json.dump(doc, open(out_path, "w"), indent=1)
print(json.dumps({k: doc[k] for k in ("participant_id", "gemma_whole_model_weight_read_count", "unexplained_full_model_dependency")}))
