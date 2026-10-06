#!/usr/bin/env python3
"""Exact public-SOURCE-only additive Issue #280 transform; no build/launch.

Produces a four-source overlay plus raw emitter, diff, and byte identities.
No synchronization, tensor reads/transfers, dispatches or scheduler decisions
are added or replaced. Existing callback hooks are NOT reused: R8-G's callback
breaks graph ranges and adds synchronization, and cannot prove submissions.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
import subprocess
from pathlib import Path

PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation/issue280_observer.h"
SOURCE_HASHES = {
    "ggml/src/ggml-backend.cpp": "a39c4fe81b043c7e8616ebe57afb75d727c692fe3b26c3e9bc2ddde3c6991041",
    "ggml/src/ggml-vulkan/ggml-vulkan.cpp": "c84f67465dfa0a24e034663f510d8b92310e3be7a7fbca231760be234b7c9f9d",
    "tools/server/server-context.cpp": "2f5d65ce6ef0504b5c8cf55a74c68d3959c49784ba380ef836566b7a7d5fa12b",
    "src/llama-context.cpp": "6429ebec7c926945987e6fe037317af0f99265490bc14b0606d9487a62a76453",
}

# INSERTIONS ONLY. Anchors are pinned verbatim and must occur exactly once.
INSERTIONS = {
    "tools/server/server-context.cpp": [
        ('#include <fstream>\n', '\n#define I280_LOG(s) LOG_INF("I280 %s\\n", (s).c_str())\n#include "issue280_observer.h"\n', 'after'),
        ('            ret = llama_decode(ctx_tgt, batch_view);\n', '''            // Metadata only; preserve the existing worker and decode/sync seam.
            if (issue280::enabled()) {
                static bool observed_identity_emitted = false; // logger state only, single worker
                if (!observed_identity_emitted) {
                    issue280::event("recording").s("kind", "SOURCE_OBSERVER")
                        .s("source_pin", "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4").emit();
                    observed_identity_emitted = true;
                }
                for (auto & observed_slot : slots) {
                    if (!observed_slot.is_processing()) { continue; }
                    bool observed_member = false;
                    for (int ti = 0; ti < batch_view.n_tokens; ++ti) {
                        for (int si = 0; si < batch_view.n_seq_id[ti]; ++si) {
                            observed_member |= batch_view.seq_id[ti][si] == observed_slot.id;
                        }
                    }
                    if (observed_member) {
                        issue280::event("batch_begin").n("request", observed_slot.task->id)
                            .n("seq", observed_slot.id).n("tokens", batch_view.n_tokens)
                            .s("phase", observed_slot.stats.n_gen == 0 ? "prefill" : "decode")
                            .n("speculative", observed_slot.can_speculate() ? 1 : 0).emit();
                    }
                }
            }
''', 'before'),
        ('                llama_synchronize(ctx_tgt);\n            }\n        });\n', '        I280_EVENT("batch_end").n("status", ret).emit();\n', 'after'),
        ('                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);\n', '''                I280_EVENT("sample").n("request", slot.task->id)
                    .n("position", slot.stats.n_gen).n("token", id)
                    .n("eos", llama_vocab_is_eog(vocab, id) ? 1 : 0).emit();
''', 'after'),
        ('    void send_final_response(server_slot & slot) {\n', '''        I280_EVENT("response").n("request", slot.task->id)
            .n("sampled", slot.stats.n_gen).n("prompt_processed", slot.stats.n_prompt_processed)
            .n("prompt_cached", slot.stats.n_prompt_cached)
            .n("eos", slot.stop == STOP_TYPE_EOS ? 1 : 0).emit();
''', 'after'),
    ],
    "src/llama-context.cpp": [
        ('#include <string>\n', '\n#define I280_LOG(s) LLAMA_LOG_INFO("I280 %s\\n", (s).c_str())\n#include "issue280_observer.h"\n', 'after'),
        ('    const auto status = graph_compute(res->get_gf(), ubatch.n_tokens > 1);\n', '''    I280_EVENT("graph_begin").p("graph", res->get_gf()).n("tokens", ubatch.n_tokens)
        .n("sequences", ubatch.n_seqs).n("seq", ubatch.seq_id_unq[0]).emit();
''', 'before'),
        ('    const auto status = graph_compute(res->get_gf(), ubatch.n_tokens > 1);\n', '    I280_EVENT("graph_end").p("graph", res->get_gf()).n("status", status).emit();\n', 'after'),
    ],
    "ggml/src/ggml-backend.cpp": [
        ('#include "ggml-impl.h"\n', '\n#define I280_LOG(s) GGML_LOG_INFO("I280 %s\\n", (s).c_str())\n#include "issue280_observer.h"\n', 'after'),
        ('    struct ggml_backend_sched_split * splits = sched->splits;\n', '''    // Pre-execution logical ranges. Read scheduler tables without hash insertion.
    if (issue280::enabled()) {
        for (int ps = 0; ps < sched->n_splits; ++ps) {
            auto * planned = &splits[ps];
            auto * destination = sched->backends[planned->backend_id];
            for (int pi = 0; pi < planned->n_inputs; ++pi) {
                auto * input = planned->inputs[pi];
                const size_t hid = ggml_hash_find(&sched->hash_set, input);
                auto * source = sched->backends[sched->hv_tensor_backend_ids[hid]];
                auto * copy = tensor_id_copy(hid, planned->backend_id, sched->cur_copy);
                if (source == destination || ggml_backend_buffer_is_host(input->buffer) ||
                        ggml_backend_buffer_is_host(copy->buffer)) { continue; }
                issue280::event("copy_manifest").s("tensor", input->name)
                    .s("src", ggml_backend_name(source)).s("dst", ggml_backend_name(destination))
                    .p("input", input).p("copy", copy).n("bytes", ggml_nbytes(input))
                    .s("type", ggml_type_name(input->type))
                    .n("ne0", input->ne[0]).n("ne1", input->ne[1]).n("ne2", input->ne[2]).n("ne3", input->ne[3])
                    .n("nb0", input->nb[0]).n("nb1", input->nb[1]).n("nb2", input->nb[2]).n("nb3", input->nb[3])
                    .n("view_offset", input->view_offs).emit();
            }
        }
    }
''', 'after'),
        ('            struct ggml_tensor * input_cpy = tensor_copy(input, split_backend_id, sched->cur_copy);\n', '''            if (issue280::enabled() && input_backend != split_backend &&
                    !ggml_backend_buffer_is_host(input->buffer) && !ggml_backend_buffer_is_host(input_cpy->buffer)) {
                issue280::event("boundary_begin").s("tensor", input->name)
                    .s("src", ggml_backend_name(input_backend)).s("dst", ggml_backend_name(split_backend))
                    .p("input", input).p("copy", input_cpy).n("bytes", ggml_nbytes(input)).emit();
            }
''', 'after'),
        ('        }\n\n        if (!sched->callback_eval) {\n', '''            if (issue280::enabled() && input_backend != split_backend &&
                    !ggml_backend_buffer_is_host(input->buffer) && !ggml_backend_buffer_is_host(input_cpy->buffer)) {
                issue280::event("boundary_end").p("input", input).p("copy", input_cpy).emit();
            }
''', 'before'),
    ],
    "ggml/src/ggml-vulkan/ggml-vulkan.cpp": [
        ('#include "ggml-backend-impl.h"\n', '\n#define I280_LOG(s) GGML_LOG_INFO("I280 %s\\n", (s).c_str())\n#include "issue280_observer.h"\nstatic const char * issue280_cached_bdf(ggml_backend_t backend);\n', 'after'),
        ('            ctx->p->q->handle->submit({}, fence);\n', '            I280_EVENT("fence_marker").p("subctx", ctx.get()).emit();\n', 'after'),
        ('            ctx->device->compute_queue->handle->submit({ si }, ctx->fence);\n', '            I280_EVENT("fence_marker").p("ctx", ctx).s("path", "transfer_timeline").emit();\n', 'after'),
        ('            ctx->device->compute_queue->handle->submit({}, ctx->fence);\n', '            I280_EVENT("fence_marker").p("ctx", ctx).s("path", "empty_queue").emit();\n', 'after'),
        ('        VK_CHECK(dst->device->device.waitForFences({ dst->device->fence }, true, UINT64_MAX), "vk_buffer_write_2d waitForFences", dst->device);\n        dst->device->device.resetFences({ dst->device->fence });\n', '        I280_EVENT("complete").p("ctx", subctx.get()).s("wait", "write_transfer_fence").emit();\n', 'after'),
        ('        VK_CHECK(src->device->device.waitForFences({ src->device->fence }, true, UINT64_MAX), "vk_buffer_copy waitForFences", src->device);\n        src->device->device.resetFences({ src->device->fence });\n', '        I280_EVENT("complete").p("ctx", subctx.get()).s("wait", "copy_transfer_fence").emit();\n', 'after'),
        ('    ctx->p->q->handle->submit(submit_infos, fence);\n', '''    if (issue280::enabled()) {
        for (const auto & seq : ctx->seqs) {
            for (const auto & submitted : seq) {
                issue280::event("submit").p("subctx", ctx.get()).p("cmd", submitted.buffer)
                    .n("use", submitted.buffer->use_counter).emit();
            }
        }
    }
''', 'after'),
        ('    ctx->gc.contexts.emplace_back(result);\n', '    I280_EVENT("ctx_create").p("subctx", result.get()).p("ctx", ctx).emit();\n', 'after'),
        ('    VK_LOG_DEBUG("ggml_vk_create_temporary_context(" << result << ")");\n', '    I280_EVENT("ctx_create").p("subctx", result.get()).p("ctx", result.get()).emit();\n', 'after'),
        ('        subctx->s->buffer->buf.dispatch(wg0, wg1, wg2);\n', '''        I280_EVENT("dispatch").p("ctx", ctx).p("cmd", subctx->s->buffer)
            .n("use", subctx->s->buffer->use_counter).s("pipeline", pipeline->name)
            .n("x", wg0).n("y", wg1).n("z", wg2).emit();
''', 'after'),
        ('    ggml_tensor * src0 = node->src[0];\n    ggml_tensor * src1 = node->src[1];\n    ggml_tensor * src2 = node->src[2];\n    ggml_tensor * src3 = node->src[3];\n', '', 'after'),
        ('    // closed explicitly below, and by the destructor on the early returns\n', '''    if (issue280::enabled()) {
        issue280::event("node").p("ctx", ctx).p("cmd", compute_ctx->s->buffer)
            .n("use", compute_ctx->s->buffer->use_counter).s("tensor", node->name)
            .s("op", ggml_op_name(node->op)).emit();
        for (int fi = 0; fi <= ctx->num_additional_fused_ops; ++fi) {
            const ggml_tensor * member = cgraph->nodes[node_idx + fi];
            for (int si = 0; si < GGML_MAX_SRC; ++si) {
                const ggml_tensor * w = member->src[si];
                if (!w || !w->buffer || !ggml_backend_buffer_is_vk(w->buffer) ||
                        ggml_backend_buffer_get_usage(w->buffer) != GGML_BACKEND_BUFFER_USAGE_WEIGHTS) { continue; }
                auto * wb = (ggml_backend_vk_buffer_context *) w->buffer->context;
                if (wb->dev_buffer->device != ctx->device) { continue; }
                issue280::event("weight").p("ctx", ctx).p("cmd", compute_ctx->s->buffer)
                    .n("use", compute_ctx->s->buffer->use_counter).s("tensor", w->name)
                    .p("buffer", wb->dev_buffer.get()).n("offset", vk_tensor_offset(w) + w->view_offs)
                    .n("bytes", ggml_nbytes(w)).n("buffer_bytes", wb->dev_buffer->size).emit();
            }
        }
    }
''', 'before'),
        ('    ctx->device->diag_cgraph = nullptr;\n    ctx->device->diag_prev_start = -1;\n    ctx->device->diag_prev_end = -1;\n', '''    I280_EVENT("vk_graph_begin").p("ctx", ctx).s("backend", ggml_backend_name(backend))
        .s("bdf", issue280_cached_bdf(backend)).emit();
''', 'before'),
        ('    return GGML_STATUS_SUCCESS;\n\n    UNUSED(backend);\n', '    I280_EVENT("vk_graph_end").p("ctx", ctx).emit();\n', 'before'),
        ('            ctx->device->device.resetFences({ ctx->fence });\n            ctx->submit_pending = false;\n            ctx->device->diag_cgraph = cgraph;\n', '            I280_EVENT("complete").p("ctx", ctx).s("wait", "serialized_fence").emit();\n', 'after'),
        ('    }\n    ctx->device->device.resetFences({ ctx->fence });\n', '    I280_EVENT("complete").p("ctx", ctx).s("wait", "fence_spin_success").emit();\n', 'after'),
        ('            VK_CHECK(ctx->device->device.waitForFences({ ctx->fence }, true, UINT64_MAX), "synchronize waitForFences", ctx->device);\n            ctx->device->device.resetFences({ ctx->fence });\n', '            I280_EVENT("complete").p("ctx", ctx).s("wait", "synchronize_fence").emit();\n', 'after'),
        ('    int op_offload_min_batch_size;\n};\n', '''
static const char * issue280_cached_bdf(ggml_backend_t backend) {
    auto * dev = (ggml_backend_vk_device_context *) backend->device->context;
    return dev->pci_bus_id.c_str(); // already cached by original device registration
}
''', 'after'),
        ('        ggml_vk_buffer_copy(dst_buf, vk_tensor_offset(dst) + dst->view_offs, src_buf, vk_tensor_offset(src) + src->view_offs, ggml_nbytes(src));\n', '''        if (issue280::enabled() && src_buf->device != dst_buf->device) {
            issue280::event("copy_path").p("input", src).p("copy", dst)
                .p("src_buffer", src_buf.get()).p("dst_buffer", dst_buf.get()).emit();
        }
''', 'before'),
        ('        ggml_vk_buffer_copy(src->device->sync_staging, 0, src, src_offset, size);\n', '''        I280_EVENT("host_leg").p("src_buffer", src.get()).p("dst_buffer", dst.get())
            .s("direction", "device_to_host").n("bytes", size)
            .s("mechanism", "source device copy to mapped sync_staging; existing fence complete").emit();
''', 'after'),
        ('        ggml_vk_buffer_write(dst, dst_offset, src->device->sync_staging->ptr, size);\n', '''        I280_EVENT("host_leg").p("src_buffer", src.get()).p("dst_buffer", dst.get())
            .s("direction", "host_to_device").n("bytes", size)
            .s("mechanism", "buffer_write from mapped source staging; original blocking path complete").emit();
''', 'after'),
        ('    vkev->cmd_buffer_use_counter = cmd_buf->use_counter;\n', '    I280_EVENT("event_record").p("ctx", ctx).p("sync_event", event).n("value", vkev->tl_semaphore.value).emit();\n', 'after'),
        ('        VK_CHECK(device->device.waitSemaphores(swi, UINT64_MAX), "event_synchronize", device);\n', '        I280_EVENT("event_complete").p("sync_event", event).n("value", val).emit();\n', 'after'),
    ],
}
# Remove the unused metadata-only no-op entry: it was a discovery anchor,
# not an inserted hook; all remaining entries MUST add real log bytes.
INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"] = [
    op for op in INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"] if op[1]
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(originals):
    if set(originals) != set(SOURCE_HASHES) or any(sha(originals[p]) != h for p, h in SOURCE_HASHES.items()):
        raise ValueError("pinned source identity mismatch; STOP before transform")
    transformed = {}
    for path, operations in INSERTIONS.items():
        src = originals[path].decode()
        for anchor, extra, where in operations:
            if src.count(anchor) != 1:
                raise ValueError(f"observation anchor gap {path}: {anchor!r}; STOP")
            replacement = extra + anchor if where == "before" else anchor + extra
            src = src.replace(anchor, replacement, 1)
        transformed[path] = src.encode()
    patch = "".join("".join(difflib.unified_diff(originals[p].decode().splitlines(True),
                                                  transformed[p].decode().splitlines(True),
                                                  fromfile="a/"+p, tofile="b/"+p)) for p in sorted(originals))
    header = HEADER.read_bytes()
    identity = {"schema": "issue280-source-overlay/1", "source_pin": PIN,
                "physical_runner": "HELD_UNAVAILABLE", "original_sha256": SOURCE_HASHES,
                "transformed_sha256": {p: sha(v) for p, v in transformed.items()},
                "emitter_sha256": sha(header), "patch_sha256": sha(patch.encode()),
                "overlay_tree_sha256": sha(json.dumps({**{p: sha(v) for p, v in transformed.items()},
                                                       "issue280_observer.h": sha(header)}, sort_keys=True).encode()),
                "patch": patch,
                "build_identity": "NOT_BUILT; CPU syntax/recording is not a Vulkan build"}
    return transformed, identity


def remove_insertions(path, transformed):
    src = transformed.decode()
    for _, extra, _ in reversed(INSERTIONS[path]):
        if src.count(extra) != 1:
            raise ValueError(f"inserted hook identity mismatch: {path}")
        src = src.replace(extra, "", 1)
    return src.encode()


def full_tree_identity(source, files):
    """Calculate real Git blob/tree identities without writing any Git objects.

    Read ONLY public-source Git TREE metadata. Never read other source-member
    bytes, model files, runtime binaries, or an untracked tree. Authenticate
    reconstruction against Git's original tree before adding the overlay.
    """
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    if git("rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("pinned source HEAD mismatch; STOP")
    def object_hash(kind, data):
        return hashlib.sha1(kind.encode()+b" "+str(len(data)).encode()+b"\0"+data).hexdigest()
    members = {}
    for row in git("ls-tree", "-r", "-z", PIN).split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        mode, _, oid = metadata.decode().split()
        members[path.decode()] = (mode, oid)
    def tree_hash(entries):
        tree = {}
        for path, value in entries.items():
            node = tree
            parts = path.split("/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        def recurse(node):
            body = b""
            for name in sorted(node, key=lambda n: (n + ("/" if isinstance(node[n], dict) else "")).encode()):
                entry = node[name]
                mode, oid = ("40000", recurse(entry)) if isinstance(entry, dict) else entry
                body += mode.encode()+b" "+name.encode()+b"\0"+bytes.fromhex(oid)
            return object_hash("tree", body)
        return recurse(tree)
    original_tree = git("rev-parse", PIN+"^{tree}").decode().strip()
    if tree_hash(members) != original_tree:
        raise ValueError("original Git tree reconstruction mismatch; STOP")
    for path, data in files.items():
        members[path] = ("100644", object_hash("blob", data))
        header_path = str(Path(path).parent / "issue280_observer.h")
        members[header_path] = ("100644", object_hash("blob", HEADER.read_bytes()))
    return {"base_git_tree": original_tree, "full_transformed_git_tree": tree_hash(members)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pinned public source root ONLY")
    parser.add_argument("output", type=Path, help="new source-overlay directory; existing paths refused")
    args = parser.parse_args()
    original = {p: (args.source / p).read_bytes() for p in SOURCE_HASHES}
    files, identity = transform(original)
    identity.update(full_tree_identity(args.source, files))
    # Validate EVERYTHING before writing; this tool never edits the source root.
    args.output.mkdir(parents=True, exist_ok=False)
    for p, data in files.items():
        target = args.output / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        (target.parent / "issue280_observer.h").write_bytes(HEADER.read_bytes())
    (args.output / "applied-source.patch").write_text(identity.pop("patch"))
    (args.output / "source-identity.json").write_text(json.dumps(identity, sort_keys=True, indent=2)+"\n")
    print(json.dumps(identity, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
