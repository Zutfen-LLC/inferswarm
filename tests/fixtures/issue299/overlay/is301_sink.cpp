// Single owner of the #301 observation state for each executable.
// Implements the C shim over the shared is301 recorder. Observation-only.
#include "is301_observer.h"
#include "is301_c_shim.h"

extern "C" int is301_is_enabled(void) { return is301::enabled() ? 1 : 0; }
extern "C" void is301_record_event(const char * name) {
    if (is301::enabled()) is301::stream().record(name);
}
extern "C" void is301_fact_num(const char * key, long long value) {
    if (is301::enabled()) is301::facts().add(key, std::to_string(value));
}
extern "C" void is301_fact_str(const char * key, const char * value) {
    if (is301::enabled()) is301::facts().add(key, is301::quote(value));
}
extern "C" void is301_fact_alloc(long long buffer_bytes, const char * backend) {
    if (is301::enabled()) is301::facts().append("allocations", std::string("{") +
        is301::kv_str("backend", backend ? backend : "unknown") + "," +
        is301::kv_num("buffer_bytes", buffer_bytes) + "}");
}
