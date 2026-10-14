// Minimal RPC worker for the remote resident-block overlap prototype.
//
// Exposes the pinned llama.cpp RPC server (ggml_backend_rpc_start_server,
// protocol v6.0.0, TCP) over one endpoint with exactly one backend device.
// This is the entire worker: no loader, no engine, no scheduling policy —
// the coordinator's harness owns all orchestration through the pinned RPC
// client, and the weight tensors the coordinator uploads stay resident in
// server-side buffers for the lifetime of the connection (freed by
// ~rpc_server when the client disconnects).
//
// Device selection defaults to the first non-CPU device (CUDA when built
// with --cuda), mirroring the pin's tools/rpc/rpc-server.cpp; --device
// overrides by exact backend device name. --device cpu forces the CPU
// backend (used by the offline loopback integration test).
#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-rpc.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>

static void usage(const char * argv0) {
    fprintf(stderr,
            "usage: %s --host H --port P [--device NAME] [--threads N]\n"
            "  Serves the pinned ggml RPC protocol on H:P with ONE device.\n"
            "  Default device: first non-CPU backend device, else CPU.\n",
            argv0);
}

int main(int argc, char ** argv) {
    std::string host = "127.0.0.1";
    int port = -1;
    std::string device_name;
    int threads = (int)(std::thread::hardware_concurrency() / 2);
    if (threads < 1) threads = 1;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&](const char * what) -> std::string {
            if (i + 1 >= argc) { fprintf(stderr, "error: %s needs a value\n", what); exit(2); }
            return argv[++i];
        };
        if (a == "--host") host = next("--host");
        else if (a == "--port") port = atoi(next("--port").c_str());
        else if (a == "--device") device_name = next("--device");
        else if (a == "--threads") threads = atoi(next("--threads").c_str());
        else if (a == "--help" || a == "-h") { usage(argv[0]); return 0; }
        else { fprintf(stderr, "error: unknown arg %s\n", a.c_str()); usage(argv[0]); return 2; }
    }
    if (port < 1 || port > 65535) { fprintf(stderr, "error: --port must be 1..65535\n"); return 2; }

    ggml_backend_dev_t dev = nullptr;
    if (!device_name.empty()) {
        dev = ggml_backend_dev_by_name(device_name.c_str());
        if (!dev) {
            fprintf(stderr, "error: unknown device '%s'; known devices:\n", device_name.c_str());
            for (size_t d = 0; d < ggml_backend_dev_count(); ++d) {
                ggml_backend_dev_t k = ggml_backend_dev_get(d);
                fprintf(stderr, "  %s\n", ggml_backend_dev_name(k));
            }
            return 2;
        }
    } else {
        for (size_t d = 0; d < ggml_backend_dev_count() && !dev; ++d) {
            ggml_backend_dev_t k = ggml_backend_dev_get(d);
            if (ggml_backend_dev_type(k) != GGML_BACKEND_DEVICE_TYPE_CPU) dev = k;
        }
        if (!dev) dev = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU);
    }
    if (!dev) { fprintf(stderr, "error: no backend device available\n"); return 2; }

    size_t free_b = 0, total_b = 0;
    ggml_backend_dev_memory(dev, &free_b, &total_b);
    printf("RPC_WORKER device=%s description=%s free_mib=%zu total_mib=%zu threads=%d\n",
           ggml_backend_dev_name(dev), ggml_backend_dev_description(dev),
           free_b / (1024 * 1024), total_b / (1024 * 1024), threads);
    fflush(stdout);
    // The server binds, prints its own banner and serves connections
    // serially until killed; buffers uploaded by a client stay resident for
    // that client's connection lifetime.
    std::string endpoint = host + ":" + std::to_string(port);
    ggml_backend_rpc_start_server(endpoint.c_str(), /*cache_dir=*/nullptr,
                                   (size_t)threads, 1, &dev);
    fprintf(stderr, "error: rpc server exited\n");
    return 1;
}
