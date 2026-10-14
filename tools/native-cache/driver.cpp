// #311 regression consumer, adapted from the retained offline-cache driver.
// Exercises the actual native tensor-set/hash-hit/get backend APIs with exact bytes.
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
#include <sys/resource.h>
#include <unistd.h>

static void mark(const char * name) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    fprintf(stderr, "[driver] marker=%s epoch=%lld.%06lld\n", name,
            (long long) tv.tv_sec, (long long) tv.tv_usec);
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    fprintf(stderr, "[driver] memory marker=%s maxrss_kib=%ld\n", name, ru.ru_maxrss);
    fflush(stderr);
    usleep(30000);
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

    mark("FIXTURE_LOADED");
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
    const bool q8 = argc > 4 && std::string(argv[4]) == "q8";
    const size_t padding = argc > 4 && std::string(argv[4]) == "offset" ? 128 : 0;
    struct ggml_tensor * t = ggml_new_tensor_1d(ctx, q8 ? GGML_TYPE_Q8_0 : GGML_TYPE_I8,
        q8 ? (int64_t) (size / 34 * 32) : (int64_t) (size + 2 * padding));
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
        ggml_backend_tensor_set(t, data.data(), padding, size);
        mark("SET_DONE");
        fprintf(stderr, "[driver] ggml_backend_tensor_set complete\n");
    } else if (mode == "get") {
        std::vector<uint8_t> out(size);
        ggml_backend_tensor_get(t, out.data(), padding, size);
        mark("GET_DONE");
        const bool match = (out == data);
        fprintf(stderr, "[driver] ggml_backend_tensor_get complete; byte-identical to fixture: %s\n", match ? "yes" : "NO-MISMATCH");
        rc = match ? 0 : 2;
    } else if (mode == "setget") {
        // set and get against the SAME allocated remote buffer/tensor within
        // one process, so get_tensor reads back exactly what set_tensor's
        // cache-hit-or-miss path actually left in the backend memory.
        if (argc > 4 && std::string(argv[4]) == "async") {
            ggml_backend_t backend = ggml_backend_rpc_init(endpoint, 0);
            ggml_backend_tensor_set_async(backend, t, data.data(), padding, size);
            ggml_backend_synchronize(backend);
            ggml_backend_free(backend);
        } else {
            ggml_backend_tensor_set(t, data.data(), padding, size);
        }
        mark("SET_DONE");
        std::vector<uint8_t> out(size);
        ggml_backend_tensor_get(t, out.data(), padding, size);
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
