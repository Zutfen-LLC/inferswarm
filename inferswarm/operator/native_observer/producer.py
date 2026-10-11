#!/usr/bin/env python3
"""#301 native producer: finite fact catalog and build-manifest emission.

Pure Python-side helpers shared by the supervised builder. The native side
(is301_observer.h + transformed sources) emits the actual facts; this module
defines the finite event catalog and assembles `q8-native-build-manifest/2`
bodies that parse_build_manifest accepts. It never claims the unmodified
base and never executes anything.
"""
from __future__ import annotations

from inferswarm.operator.phased_observation import (
    BUILD_MANIFEST_SCHEMA, NATIVE_STREAM_SCHEMA, PINNED_BASE_REVISION,
    PINNED_BASE_TREE,
)

# Finite event catalog emitted by the observation overlay. Observation-only:
# each name is a native seam fact, never a computation/placement change.
EVENT_CATALOG = (
    'alloc_ctx_tensors',        # backend buffer allocation completed (ggml-alloc.c)
    'graph_compute',            # synchronous graph compute returned (ggml-backend.cpp)
    'sched_graph_compute',      # scheduler-completion path actually used by llama-server; async entry observed at completion
    'tensor_set',               # backend tensor write completed (ggml-backend.cpp)
    'tensor_get',               # backend tensor read completed (ggml-backend.cpp)
    'rpc_set_tensor',           # RPC client SET_TENSOR dispatched+awaited
    'rpc_get_tensor',           # RPC client GET_TENSOR completed
    'rpc_server_client',        # RPC server accepted a connection
    'rpc_server_command',       # RPC server completed a command ordinal
    'model_load_all_data',      # loader completed weight placement pass
    'kv_cache_constructed',     # persistent KV cache constructor completed
    'server_task_new_id',       # server task id assigned (task lifecycle)
    'server_task_processed',    # task dequeued for processing
    'server_response_send',     # response dispatched to waiting task
    'fixture_alloc',            # tiny fixture: allocation observed
    'fixture_cpu_init',         # tiny fixture: CPU backend initialized
    'fixture_graph',            # tiny fixture: graph compute observed
    'fixture_set',              # tiny fixture: tensor write observed
    'fixture_get',              # tiny fixture: tensor readback observed
    'fixture_rpc_loopback',     # tiny fixture: RPC loopback GET completed
    'fixture_fact_bounds',      # adversarial fact-bounds fixture marker event
)

# Facts (bounded catalog, mirroring the issue text): process/build/config and
# physical bindings; tensor/state/component/base-buffer extents; request/task
# lineage ({task_id, response_id: "unknown" until observed}) and responses
# ({task_id}); transfer endpoints/shapes/bytes/completions; output custody.
# Allocation records are preserved per allocation as [{buffer_bytes, backend}].
# Unsupported values are emitted as the explicit string "unknown", never fabricated.
FACT_KEYS = (
    'process',      # {pid, argv0, start_unix_ns}
    'build',        # {compiler, executable_sha256} — join key, not proof
    'config',       # observed effective argv/flag facts
    'allocations',  # [{buffer_bytes, backend}] records preserved per allocation
    'graphs',       # [{graph_id, nodes, status}]
    'transfers',    # [{op, endpoint, tensor, offset, bytes}]
    'tasks',        # [{task_id, response_id: "unknown" until observed}]
    'responses',    # [{task_id}]
)


def build_manifest_body(*, compiler: str, options, executable_sha256: str,
                        backend_libraries, patch_sha256: str,
                        transformed_manifest_sha256: str) -> dict:
    """Assemble a q8-native-build-manifest/2 body from actual build facts."""
    return {
        'schema': BUILD_MANIFEST_SCHEMA,
        'base_revision': PINNED_BASE_REVISION,
        'base_tree': PINNED_BASE_TREE,
        'patch_sha256': patch_sha256,
        'transformed_manifest_sha256': transformed_manifest_sha256,
        'protocol': NATIVE_STREAM_SCHEMA,
        'compiler': compiler,
        'build_options': list(options),
        'executable_sha256': executable_sha256,
        'backend_libraries': [{'name': name, 'sha256': sha}
                              for name, sha in sorted(backend_libraries)],
    }
