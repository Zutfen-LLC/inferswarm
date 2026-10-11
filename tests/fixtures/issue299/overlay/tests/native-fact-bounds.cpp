// Adversarial bounded-facts proof; the real allocation seam exercises the C shim.
#include "is301_observer.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>

static void write_capture(const std::string & path, const std::string & body) {
    std::FILE * out = std::fopen(path.c_str(), "wb");
    if (!out) std::abort();
    if (std::fwrite(body.data(), 1, body.size(), out) != body.size()) std::abort();
    if (std::fclose(out) != 0) std::abort();
}

static void add_clean_facts() {
    for (int id = 1; id <= 3; ++id) {
        is301::facts().append("tasks", std::string("{") +
            is301::kv_str("response_id", "unknown") + "," +
            is301::kv_num("task_id", id) + "}");
    }
    for (int id = 1; id <= 2; ++id) {
        is301::facts().append("responses", std::string("{") +
            is301::kv_num("task_id", id) + "}");
    }
    // This mirrors is301_fact_alloc; the C shim path is exercised by the real alloc seam.
    for (int i = 0; i < 2; ++i) {
        is301::facts().append("allocations", std::string("{") +
            is301::kv_str("backend", "CPU") + "," +
            is301::kv_num("buffer_bytes", 4096) + "}");
    }
}

static std::string capture(const char * generation) {
    return is301::envelope("dynamic", "native-fact-bounds", std::string(64, '0'),
        "export", generation, "whole", true, false);
}

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    const std::string dir(argv[1]);
    is301::stream().record("fixture_fact_bounds");
    add_clean_facts();
    // Preserve the original first-element append refusal control.
    const std::string append_before = is301::facts().canonical_object();
    is301::facts().append("oversized", is301::quote(std::string(4097, 'x')));
    assert(append_before == is301::facts().canonical_object());
    assert(is301::facts().dropped == 1);
    write_capture(dir + "/fact-bounds-capture.json", capture("fact-bounds-bad"));
    is301::reset();
    is301::stream().record("fixture_fact_bounds");
    add_clean_facts();
    is301::facts().add("overwrite-bound", is301::quote("small"));
    const std::string before = is301::facts().canonical_object();
    is301::facts().add("overwrite-bound", is301::quote(std::string(4097, 'x')));
    assert(before == is301::facts().canonical_object());
    assert(is301::facts().dropped == 1);
    assert(is301::facts().overflowed);
    write_capture(dir + "/fact-scalar-overwrite.json", capture("fact-scalar-overwrite"));
    is301::reset();
    is301::stream().record("fixture_fact_bounds");
    add_clean_facts();
    assert(is301::facts().dropped == 0 && !is301::facts().overflowed);
    write_capture(dir + "/fact-bounds-clean.json", capture("fact-bounds-clean"));
    std::puts("IS301 fact-bounds fixture PASS");
    return 0;
}
