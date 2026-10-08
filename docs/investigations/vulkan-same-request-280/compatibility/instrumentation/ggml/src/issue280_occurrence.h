// Issue #280 R8-A2: graph-local, (input, copy)-keyed producer occurrence
// identity, shared across the scheduler and Vulkan translation units.
//
// ODR-shared through C++17 inline-function statics: one registry for the
// whole process, no exported symbols, no change to the emitter's
// translation-unit-local logging design. All counter sites run on the
// scheduler's host thread at the pin (llama_context::graph_compute ->
// exactly one ggml_backend_sched_graph_compute_async call per observer
// graph), so no synchronization is added.
//
// Law (must equal the collector's copy_manifest occurrence derivation):
//   - reset() clears all state; called at entry of
//     ggml_backend_sched_graph_compute_async, which is 1:1 with the
//     observer's graph_begin scope;
//   - assign(input, copy) records and returns the 0-based occurrence for
//     the key since the last reset (the copy_manifest site; the manifest
//     loop runs for every planned cross-die input BEFORE any copy event,
//     so assigns always precede begins);
//   - begin(input, copy) starts the next copy EVENT for the key: it
//     returns the assigned occurrence at the key's cursor and advances it
//     (repeated pairs within one graph yield 0, then 1);
//   - current(input, copy) recalls the occurrence of the key's most
//     recently begun event (the copy_path and boundary_end sites, which
//     fire inside the copy event opened by begin).
#ifndef ISSUE280_OCCURRENCE_H
#define ISSUE280_OCCURRENCE_H
#include <cstddef>
#include <map>
#include <utility>
#include <vector>

namespace issue280_occurrence {

struct key_type {
    const void * input;
    const void * copy;
};

inline bool operator<(const key_type & a, const key_type & b) {
    return std::make_pair(a.input, a.copy) < std::make_pair(b.input, b.copy);
}

struct per_key_state {
    std::vector<int> assigned;   // occurrences assigned by copy_manifest, in order
    std::size_t cursor = 0;      // copy events begun so far
};

inline std::map<key_type, per_key_state> & registry() {
    static std::map<key_type, per_key_state> state;
    return state;
}

inline void reset() {
    registry().clear();
}

inline int assign(const void * input, const void * copy) {
    per_key_state & entry = registry()[key_type{ input, copy }];
    const int occurrence = static_cast<int>(entry.assigned.size());
    entry.assigned.push_back(occurrence);
    return occurrence;
}

inline int begin(const void * input, const void * copy) {
    per_key_state & entry = registry()[key_type{ input, copy }];
    if (entry.cursor < entry.assigned.size()) {
        return entry.assigned[entry.cursor++];
    }
    return static_cast<int>(entry.assigned.size()); // unassigned event (not reachable in well-formed producer order)
}

inline int current(const void * input, const void * copy) {
    const per_key_state & entry = registry()[key_type{ input, copy }];
    return entry.cursor == 0 ? 0 : entry.assigned[entry.cursor - 1];
}

} // namespace issue280_occurrence

#endif
