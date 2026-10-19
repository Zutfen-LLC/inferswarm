#pragma once
// Private, opt-in client instrumentation/SET grouping for the bounded 2x2 probe.
// No new wire command, no worker dependency, and no public runtime API promise.
#include "ggml-backend.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct is_factorial_rpc_tensor {
    struct ggml_tensor * tensor;
    const void * data;
    size_t offset;
    size_t size;
};

struct is_factorial_rpc_set_stats {
    uint64_t hash_begin_ns, hash_end_ns, enqueue_ns;
    uint64_t write_begin_ns, write_end_ns, flush_ns;
    uint64_t ack_first_ns, ack_end_ns;
    uint64_t payload_bytes, wire_bytes;
};

struct is_factorial_rpc_stats {
    uint64_t begin_ns, end_ns;
    struct is_factorial_rpc_set_stats sets[3];
    uint64_t group_enqueue_ns, group_dequeue_ns, group_end_ns;
    uint64_t graph_enqueue_ns, graph_write_begin_ns, graph_write_end_ns;
    uint64_t graph_uid, graph_recompute;
    uint64_t get_enqueue_ns, get_write_begin_ns, get_write_end_ns;
    uint64_t get_first_byte_ns, get_last_byte_ns;
    uint64_t tx_wire_bytes, rx_wire_bytes, tx_payload_bytes;
    uint64_t commands, set_commands, set_acks, graph_commands, get_commands;
    uint64_t pipeline, timeout_ms, failed;
};

// Caller is the sole experiment owner of this backend/endpoint until end().
// begin drains earlier dispatcher work, zeros stats, and borrows stats until
// end drains all observed work. Caller must not read stats before end returns.
GGML_BACKEND_API bool is_factorial_rpc_begin(ggml_backend_t backend, struct is_factorial_rpc_stats * stats);
// Exactly three distinct mutable tensors, at most 64 KiB each. Data must remain
// immutable through this synchronous call. Serial and pipeline use identical
// SHA-bound v7 frames; pipeline permits writes while ordered ACKs are drained.
// Deadline is a total group wall deadline including hashing/queueing (1..10000
// ms). Incomplete admission shuts down the connection and aborts the process;
// no partially admitted connection is returned to the caller.
GGML_BACKEND_API bool is_factorial_rpc_set3(ggml_backend_t backend,
    const struct is_factorial_rpc_tensor inputs[3], bool pipeline, uint32_t timeout_ms);
GGML_BACKEND_API bool is_factorial_rpc_end(ggml_backend_t backend);

#ifdef __cplusplus
}
#endif
