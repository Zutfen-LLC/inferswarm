// r8f_rpc_cache_probe/driver.cpp
//
// Standalone external test consumer of the pinned, unmodified llama.cpp
// public backend API (ggml.h / ggml-backend.h / ggml-alloc.h / ggml-rpc.h)
// at commit b29c606e28a01b1bc8c1351026a0fa6e616bf6c4. This program is not
// part of llama.cpp and does not modify any llama.cpp source; it exercises
// the same public client-side entry points (ggml_backend_rpc_buffer_type,
// ggml_backend_alloc_ctx_tensors_from_buft, ggml_backend_tensor_set,
// ggml_backend_tensor_get) that llama.cpp's own model loader uses when a
// tensor is assigned to an RPC device, so the exact pinned
// ggml_backend_rpc_buffer_set_tensor / rpc_server::set_tensor_hash /
// rpc_server::get_cached_file code path is what runs here.
//
// Usage: driver <endpoint> <fixture_file> <set|get>
#include "ggml.h"
#include "ggml-alloc.h"
#include "ggml-backend.h"
#include "ggml-rpc.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <vector>
#include <sys/time.h>

static void mark(const char * name) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    fprintf(stderr, "[driver] marker=%s epoch=%lld.%06lld\n", name,
            (long long) tv.tv_sec, (long long) tv.tv_usec);
    fflush(stderr);
}

int main(int argc, char ** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <endpoint> <fixture_file> <set|get|setget>\n", argv[0]);
        return 1;
    }
    const char * endpoint = argv[1];
    const char * fixture_path = argv[2];
    const std::string mode = argv[3];

    std::ifstream ifs(fixture_path, std::ios::binary);
    if (!ifs) {
        fprintf(stderr, "[driver] cannot open fixture %s\n", fixture_path);
        return 1;
    }
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
    const size_t size = data.size();
    fprintf(stderr, "[driver] endpoint=%s fixture=%s size=%zu mode=%s\n", endpoint, fixture_path, size, mode.c_str());

    ggml_backend_buffer_type_t buft = ggml_backend_rpc_buffer_type(endpoint, 0);
    if (!buft) {
        fprintf(stderr, "[driver] ggml_backend_rpc_buffer_type failed\n");
        return 1;
    }

    struct ggml_init_params params = {
        /*.mem_size   =*/ ggml_tensor_overhead() + 64,
        /*.mem_buffer =*/ NULL,
        /*.no_alloc   =*/ true,
    };
    struct ggml_context * ctx = ggml_init(params);
    if (!ctx) {
        fprintf(stderr, "[driver] ggml_init failed\n");
        return 1;
    }
    struct ggml_tensor * t = ggml_new_tensor_1d(ctx, GGML_TYPE_I8, (int64_t) size);
    ggml_set_name(t, "r8f_fixture_tensor");

    mark("ALLOC_START");
    ggml_backend_buffer_t buf = ggml_backend_alloc_ctx_tensors_from_buft(ctx, buft);
    if (!buf) {
        fprintf(stderr, "[driver] ggml_backend_alloc_ctx_tensors_from_buft failed (server unreachable or alloc rejected)\n");
        ggml_free(ctx);
        return 1;
    }
    mark("ALLOC_DONE");

    int rc = 0;
    if (mode == "set") {
        ggml_backend_tensor_set(t, data.data(), 0, size);
        mark("SET_DONE");
        fprintf(stderr, "[driver] ggml_backend_tensor_set complete\n");
    } else if (mode == "get") {
        std::vector<uint8_t> out(size);
        ggml_backend_tensor_get(t, out.data(), 0, size);
        mark("GET_DONE");
        const bool match = (out == data);
        fprintf(stderr, "[driver] ggml_backend_tensor_get complete; byte-identical to fixture: %s\n", match ? "yes" : "NO-MISMATCH");
        rc = match ? 0 : 2;
    } else if (mode == "setget") {
        // set and get against the SAME allocated remote buffer/tensor within
        // one process, so get_tensor reads back exactly what set_tensor's
        // cache-hit-or-miss path actually left in the backend memory.
        ggml_backend_tensor_set(t, data.data(), 0, size);
        mark("SET_DONE");
        std::vector<uint8_t> out(size);
        ggml_backend_tensor_get(t, out.data(), 0, size);
        mark("GET_DONE");
        const bool match = (out == data);
        size_t first_mismatch = match ? 0 : SIZE_MAX;
        size_t mismatch_count = 0;
        if (!match) {
            for (size_t i = 0; i < size; i++) {
                if (out[i] != data[i]) {
                    if (first_mismatch == SIZE_MAX) first_mismatch = i;
                    mismatch_count++;
                }
            }
        }
        fprintf(stderr, "[driver] setget complete; byte-identical to fixture: %s; mismatch_count=%zu; first_mismatch_offset=%zd\n",
                match ? "yes" : "no", mismatch_count, match ? -1 : (ssize_t) first_mismatch);
        rc = match ? 0 : 2;
    } else {
        fprintf(stderr, "[driver] unknown mode %s\n", mode.c_str());
        rc = 1;
    }
    mark("BEFORE_FREE");

    ggml_backend_buffer_free(buf);
    ggml_free(ctx);
    return rc;
}
