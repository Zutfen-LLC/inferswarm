#!/usr/bin/env python3
"""Additive D1 successor of the frozen six-file Issue280 source overlay.

Only the graph metadata insertion changes. Original producer and overlays
remain byte-for-byte untouched. No hardware/build/model/dispatch execution.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/investigations/vulkan-same-request-280/compatibility"
SEMANTICS = BUNDLE / "source-semantics"
OVERLAY = BUNDLE / "instrumentation"
spec = importlib.util.spec_from_file_location("i280_source_predecessor", ROOT / "scripts/issue280_source.py")
assert spec is not None and spec.loader is not None
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
PIN = old.PIN
SOURCE_HASHES = old.SOURCE_HASHES
GRAPH_HOOK = '''    if (issue280::enabled()) {
        std::string observed_unique_ids = "[";
        for (uint32_t observed_i = 0; observed_i < ubatch.n_seqs_unq; ++observed_i) {
            if (observed_i != 0) { observed_unique_ids += ","; }
            observed_unique_ids += std::to_string(ubatch.seq_id_unq[observed_i]);
        }
        observed_unique_ids += "]";
        issue280::event observed_graph("graph_begin");
        observed_graph.p("graph", res->get_gf()).n("tokens", ubatch.n_tokens)
            .n("sequences", ubatch.n_seqs).n("n_seq_tokens", ubatch.n_seq_tokens)
            .n("b_equal_seqs", ubatch.b_equal_seqs ? 1 : 0)
            .n("n_seqs_unq", ubatch.n_seqs_unq).json("seq_ids_unq", observed_unique_ids);
        if (ubatch.n_seqs_unq > 0) { observed_graph.n("seq", ubatch.seq_id_unq[0]); }
        observed_graph.emit();
    }
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(originals):
    files, prior = old.transform(originals)
    old_graph = old.INSERTIONS["src/llama-context.cpp"][1][1]
    context = files["src/llama-context.cpp"].decode()
    if context.count(old_graph) != 1:
        raise ValueError("predecessor graph insertion mismatch")
    files["src/llama-context.cpp"] = context.replace(old_graph, GRAPH_HOOK, 1).encode()
    patch = "".join("".join(difflib.unified_diff(originals[p].decode().splitlines(True),
                        files[p].decode().splitlines(True), fromfile="a/" + p, tofile="b/" + p))
                    for p in sorted(originals))
    members = {p: sha(data) for p, data in files.items()}
    members.update({"issue280_observer.h": sha(old.HEADER.read_bytes()),
                    "issue280_occurrence.h": sha(old.OCCURRENCE_HEADER.read_bytes())})
    identity = {k: v for k, v in prior.items() if k not in {"patch", "patch_sha256", "transformed_sha256", "overlay_tree_sha256"}}
    identity.update({"schema": "issue280-source-compat-overlay/1",
                     "predecessor_overlay_tree_sha256": prior["overlay_tree_sha256"],
                     "predecessor_patch_sha256": prior["patch_sha256"],
                     "predecessor_transformed_sha256": prior["transformed_sha256"],
                     "transformed_sha256": {p: sha(data) for p, data in files.items()},
                     "patch_sha256": sha(patch.encode()), "patch": patch,
                     "overlay_tree_sha256": sha(json.dumps(members, sort_keys=True).encode()),
                     "graph_hook_sha256": sha(GRAPH_HOOK.encode()),
                     "purpose": "D1 complete unique-sequence metadata only; D3 producer unchanged"})
    return files, identity


def verify_overlay():
    originals = {p: (SEMANTICS / p).read_bytes() for p in SOURCE_HASHES}
    files, generated = transform(originals)
    retained = json.loads((OVERLAY / "source-identity.json").read_text())
    if (retained.get("base_git_tree") != "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
            or retained.get("full_transformed_git_tree") != "f3cd359feada1ba883955582cecf13dc75f1dcb8"
            or retained.get("overlay_tree_sha256") != "6e73ce72b8c6f5a06ead05dc2db64fb2274cf90a51a1d2a2936e100fd3ab7f8b"):
        raise ValueError("successor frozen full-tree/overlay identity drift")
    for key, value in generated.items():
        if key != "patch" and retained.get(key) != value:
            raise ValueError("successor source identity drift: " + key)
    if (OVERLAY / "applied-source.patch").read_bytes() != generated["patch"].encode():
        raise ValueError("successor source patch drift")
    for p, data in files.items():
        if (OVERLAY / p).read_bytes() != data:
            raise ValueError("successor source overlay drift: " + p)
        for header in (old.HEADER, old.OCCURRENCE_HEADER):
            if (OVERLAY / Path(p).parent / header.name).read_bytes() != header.read_bytes():
                raise ValueError("successor emitter/helper drift")
    return retained


def cpu_probe():
    """Compile/execute the VERBATIM inserted block, not a hand-written emitter.

    This is a CPU metadata syntax/semantics probe, NOT a Vulkan integration build.
    Local includes are intentionally tiny; member types/semantics are bound to
    the archived pinned batch declaration and builder via custody verification.
    """
    result = {"ok": False, "rows": [], "physical_execution": "NONE"}
    try:
        identity = verify_overlay()
        includes = '''#include <cstdint>
#include <string>
#include <iostream>
#define I280_LOG(s) (std::cout << "I280 " << s << "\\n")
#include "issue280_observer.h"
struct ProbeBatch { bool b_equal_seqs; uint32_t n_tokens, n_seq_tokens, n_seqs, n_seqs_unq; const int32_t * seq_id_unq; };
struct ProbeResult { void * get_gf() { return this; } };
void probe(const ProbeBatch & ubatch) { ProbeResult result; auto * res = &result;
'''
        main = '''}
int main() {
    setenv("ISSUE280_OBSERVE", "1", 1);
    int32_t single[] = {0}, multi[] = {0,1}, other[] = {7};
    probe({false,31,1,31,1,single});
    probe({true,4,2,2,2,multi});
    probe({true,4,4,1,1,other});
}
'''
        with tempfile.TemporaryDirectory(prefix="i280-d1-probe-") as td:
            td = Path(td)
            (td / "probe.cpp").write_text(includes + GRAPH_HOOK + main)
            subprocess.run(["c++", "-std=c++17", "-Werror", "-Wall", "-Wextra", "-I", str(old.HEADER.parent),
                            str(td / "probe.cpp"), "-o", str(td / "probe")], check=True,
                           capture_output=True, text=True)
            run = subprocess.run([str(td / "probe")], check=True, capture_output=True, text=True)
        rows = [json.loads(line.split("I280 ", 1)[1]) for line in run.stdout.splitlines()]
        for row, tokens, sets, per_set, ids in zip(rows, (31,4,4), (31,2,1), (1,2,4), ([0],[0,1],[7])):
            if (row["tokens"] != tokens or row["sequences"] != sets or row["n_seq_tokens"] != per_set
                    or row["seq_ids_unq"] != ids or row["n_seqs_unq"] != len(ids) or row["seq"] != ids[0]):
                raise ValueError("successor CPU producer semantics mismatch")
        if len(rows) != 3:
            raise ValueError("successor CPU producer row count mismatch")
        result.update({"ok": True, "rows": rows, "overlay_tree_sha256": identity["overlay_tree_sha256"],
                       "full_transformed_git_tree": identity["full_transformed_git_tree"],
                       "claim": "INSERTED_BLOCK_CPU_SYNTAX_AND_METADATA_ONLY_NOT_VULKAN_BUILD"})
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        result["problem"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    files, identity = transform({p: (args.source / p).read_bytes() for p in SOURCE_HASHES})
    identity.update(old.full_tree_identity(args.source, files))
    args.output.mkdir(parents=True, exist_ok=False)
    for p, data in files.items():
        target = args.output / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        for header in (old.HEADER, old.OCCURRENCE_HEADER):
            (target.parent / header.name).write_bytes(header.read_bytes())
    (args.output / "applied-source.patch").write_text(identity.pop("patch"))
    (args.output / "source-identity.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n")
    print(json.dumps(identity, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
