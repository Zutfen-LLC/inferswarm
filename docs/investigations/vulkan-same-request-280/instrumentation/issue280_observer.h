// Issue #280 observation-only raw emitter. No ggml/Vulkan dependencies.
// The including producer supplies I280_LOG using its EXISTING logging path.
#ifndef ISSUE280_OBSERVER_H
#define ISSUE280_OBSERVER_H
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <sstream>
#include <string>

namespace { // translation-unit local: logging macro differs per producer
namespace issue280 {
static inline bool enabled() {
    const char * p = std::getenv("ISSUE280_OBSERVE");
    return p && std::string(p) == "1";
}
static inline long long now() {
#ifdef I280_CLOCK
    return I280_CLOCK();
#else
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
#endif
}
static inline std::string quote(const std::string & s) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out << '\\' << c; }
        else if (c < 32) { out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c); }
        else { out << c; }
    }
    out << '"';
    return out.str();
}
class event {
    std::ostringstream out;
public:
    explicit event(const char * name) {
        out << "{\"schema\":\"issue280-raw/1\",\"event\":" << quote(name)
            << ",\"ts_ns\":" << now();
    }
    event & s(const char * k, const std::string & v) {
        out << ',' << quote(k) << ':' << quote(v); return *this;
    }
    event & n(const char * k, long long v) {
        out << ',' << quote(k) << ':' << v; return *this;
    }
    event & p(const char * k, const void * v) {
        std::ostringstream ptr; ptr << v; return s(k, ptr.str());
    }
    void emit() {
        if (enabled()) { I280_LOG(out.str() + "}"); }
    }
};
}
} // anonymous namespace
// Guards ensure disabled hooks do not evaluate metadata/logging expressions.
#define I280_EVENT(name) if (issue280::enabled()) issue280::event(name)
#endif
