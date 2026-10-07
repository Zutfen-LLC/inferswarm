#!/usr/bin/env python3
"""Permanently reproduce accepted-collector RED and independent CPU mutations.

No models, servers, devices, GPU APIs, networks or launches are used. Untouched
sequence projections let D2/D3 mutations reach their real semantic validator.
"""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[3]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def mutate(raw, event, fields=None, predicate=lambda r: True, drop=False, first=False):
    lines, hits = [], 0
    for line in raw.splitlines():
        if "I280 " not in line:
            lines.append(line)
            continue
        row = json.loads(line.split("I280 ", 1)[1])
        if row["event"] == event and predicate(row) and (not first or not hits):
            hits += 1
            if drop:
                continue
            row.update(fields or {})
        lines.append("I280 " + json.dumps(row, separators=(",", ":")))
    if not hits:
        raise ValueError("mutation target missing: " + event)
    return "\n".join(lines) + "\n"

def main():
    m = module("i280_mutations_observer", ROOT / "scripts/issue280_observer.py")
    raw = gzip.decompress((BUNDLE / "observer-R1-cold.i280.raw.gz").read_bytes()).decode()
    assert hashlib.sha256(raw.encode()).hexdigest() == m._compat.RAW_SHA256
    old = module("i280_accepted_observer", BUNDLE / "accepted-observer.py")
    assert hashlib.sha256((BUNDLE / "accepted-observer.py").read_bytes()).hexdigest() == m._compat.ACCEPTED_OBSERVER_SHA256
    red = old.validate_admission(raw, old.physical_280_contracts()["A"])
    assert not red["ok"] and red["problems"] == ["graph sequence/request mismatch"], red
    green = m.validate_admission(raw, m.physical_280_contracts()["A"])
    assert green["ok"], green
    tests = [
        ("D1-multisequence", "sequence", mutate(raw, "graph_begin", {"n_seqs_unq": 2, "seq_ids_unq": [0,1], "n_seq_tokens": 1}, first=True)),
        ("D1-wrong-unique-id", "sequence", mutate(raw, "graph_begin", {"n_seqs_unq": 1, "seq_ids_unq": [1], "n_seq_tokens": 1}, first=True)),
        ("D1-wrong-sequence", "sequence", mutate(raw, "graph_begin", {"seq": 1}, first=True)),
        ("D1-terminal-sequence-conflict", "sequence", mutate(raw, "request_end", {"seq": 1})),
        ("D1-witness-transfer-token-attack", "sequence", mutate(raw, "batch_begin", {"token_ids": [0]*31}, first=True)),
        ("request-mismatch", "cross-request", mutate(raw, "graph_begin", {"request": 99}, first=True)),
        ("wrong-BDF", "BDF", mutate(raw, "vk_graph_begin", {"bdf": "0000:0b:00.0"})),
        ("missing-upper-block", "inventory", mutate(raw, "weight_inventory", predicate=lambda r: r["tensor"].startswith("blk.35."), drop=True)),
        ("missing-KV", "kv_cache", mutate(raw, "kv_inventory", drop=True)),
        ("missing-completed-compute", "completed", mutate(raw, "complete", drop=True)),
        ("D2-explicit-conflict", "conflicting", mutate(raw, "weight_inventory", {"backend":"Vulkan0"}, lambda r: r["bdf"] == "CPU_Mapped")),
        ("D3-wrong-output-op", "output role", mutate(raw, "node", {"op":"ADD"}, lambda r: r["tensor"] == "result_output")),
        ("D3-output-norm-is-not-output", "output role", mutate(raw, "node", {"tensor":"output_norm"}, lambda r: r["tensor"] == "result_output")),
        ("D3-missing-actual-operand", "output role", mutate(raw, "weight", predicate=lambda r: r["tensor"] == "token_embd.weight", drop=True)),
        ("D3-wrong-operand-bytes", "output role", mutate(raw, "weight", {"bytes":128}, lambda r: r["tensor"] == "token_embd.weight")),
        ("D3-missing-CPU-backing", "output role", mutate(raw, "weight_inventory", predicate=lambda r: r["tensor"] == "token_embd.weight" and r["bdf"] == "CPU_Mapped", drop=True)),
        ("D3-corrupt-CPU-backing", "output role", mutate(raw, "weight_inventory", {"bytes":128}, lambda r: r["tensor"] == "token_embd.weight" and r["bdf"] == "CPU_Mapped")),
        ("D3-distinct-output-prevents-tied-fallback", "output role", mutate(raw, "weight_inventory", {"tensor":"output.weight"}, lambda r: r["tensor"] == "output_norm.weight")),
        ("D3-model-drift", "output role", mutate(raw, "recording", {"model_sha256":"wrong"})),
    ]
    for name in ("CPU_Mapped_FAKE", "VulkanCPU_Mapped", "CPUfoo", "unknown_accelerator", "unassigned"):
        tests.append(("D2-" + name, "placement", mutate(raw, "weight_inventory", {"bdf":name,"backend":name}, lambda r: r["bdf"] == "CPU_Mapped")))
    lines = raw.splitlines()
    row = json.loads(lines[3].split("I280 ",1)[1])
    assert row["tensor"] == "token_embd.weight"
    row["buffer"] = "ambiguous-copy"
    lines.insert(4, "I280 " + json.dumps(row))
    tests.append(("D3-ambiguous-GPU-copy", "output role", "\n".join(lines)+"\n"))
    corrupt = mutate(raw, "weight_inventory", {"bytes":128}, lambda r: r["tensor"] == "token_embd.weight")
    corrupt = mutate(corrupt, "weight", {"bytes":128}, lambda r: r["tensor"] == "token_embd.weight")
    tests.append(("D3-corrupt-all-matching-sizes", "output role", corrupt))
    builder = module("i280_mutations_builder", ROOT / "tests/test_issue280_admission.py")
    tests.append(("D3-wrong-output-die", "output role", builder.build_stream(output_bdf=builder.DIE_A)))
    result = {"schema":"issue280-compatibility-mutations/1", "physical_execution":"NONE",
              "accepted_red":red, "corrected_green":green, "mutations":[]}
    for name, reason, candidate in tests:
        contract = m.physical_280_contracts()["B" if name == "D3-wrong-output-die" else "A"]
        verdict = m.validate_admission(candidate, contract)
        if verdict["ok"] or not any(reason in p for p in verdict["problems"]):
            raise AssertionError((name, reason, verdict))
        result["mutations"].append({"name":name, "expected_reason":reason, "ok":False,
                                    "problems":verdict["problems"],
                                    "sequence_evidence":verdict["sequence_evidence"]})
    result["mutation_count"] = len(result["mutations"])
    print(json.dumps(result, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
