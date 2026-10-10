// Issue #301 observation-only native emitter. IS301: derived overlay marker.
//
// Strictly observation-only: no computation, kernel, placement, scheduling or
// transfer behavior changes. All hooks are guarded by is301::enabled()
// (IS301_OBSERVE=1); disabled builds run the guards as no-ops. Numeric
// identities (pid, pointers, sizes, counters) come from actual execution.
//
// Emits complete `inferswarm-native-observation/2` envelopes: canonical JSON
// (object keys sorted at every level, separators ',' ':', ASCII-safe strings)
// sealed with SHA-256 over the envelope minus terminal_digest. The canonical
// byte form and digest are verified downstream by the independent Python
// parser (phased_observation.parse_observation); agreement is a
// cross-implementation check, not a co-designed pass.
#ifndef IS301_OBSERVER_H
#define IS301_OBSERVER_H
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <cstring>
#include <mutex>
#include <string>
#include <utility>
#include <vector>
#ifdef _WIN32
#    include <process.h>
#else
#    include <unistd.h>
#endif

namespace is301 {

// ---- SHA-256 (FIPS 180-4), self-contained -------------------------------
class sha256 {
    uint32_t h[8];
    uint8_t  buf[64];
    size_t   len;
    uint64_t total;
    static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
    void process_block(const uint8_t * p) {
        static const uint32_t K[64] = {
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
            0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
            0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
            0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
            0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
            0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
            0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
            0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
            0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
        uint32_t w[64];
        for (int i = 0; i < 16; i++) {
            w[i] = (uint32_t(p[4*i]) << 24) | (uint32_t(p[4*i+1]) << 16) |
                   (uint32_t(p[4*i+2]) << 8) | uint32_t(p[4*i+3]);
        }
        for (int i = 16; i < 64; i++) {
            uint32_t s0 = rotr(w[i-15],7) ^ rotr(w[i-15],18) ^ (w[i-15] >> 3);
            uint32_t s1 = rotr(w[i-2],17) ^ rotr(w[i-2],19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
        for (int i = 0; i < 64; i++) {
            uint32_t S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = hh + S1 + ch + K[i] + w[i];
            uint32_t S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
            uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + mj;
            hh=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }
        h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=d; h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
    }
public:
    sha256() : len(0), total(0) {
        h[0]=0x6a09e667; h[1]=0xbb67ae85; h[2]=0x3c6ef372; h[3]=0xa54ff53a;
        h[4]=0x510e527f; h[5]=0x9b05688c; h[6]=0x1f83d9ab; h[7]=0x5be0cd19;
    }
    void update(const void * data, size_t n) {
        const uint8_t * p = (const uint8_t *) data;
        total += n;
        while (n > 0) {
            size_t take = 64 - len < n ? 64 - len : n;
            std::memcpy(buf + len, p, take);
            len += take; p += take; n -= take;
            if (len == 64) { process_block(buf); len = 0; }
        }
    }
    std::string hexdigest() {
        uint64_t bits = total * 8;
        uint8_t pad = 0x80;
        update(&pad, 1);
        uint8_t zero = 0;
        while (len != 56) update(&zero, 1);
        uint8_t tail[8];
        for (int i = 0; i < 8; i++) tail[i] = uint8_t(bits >> (56 - 8*i));
        update(tail, 8);  // total captured before padding; len is 56 here
        std::string out;
        char hex[9];
        for (int i = 0; i < 8; i++) {
            std::snprintf(hex, sizeof hex, "%08x", h[i]);
            out += hex;
        }
        return out;
    }
};

inline std::string sha256_hex(const std::string & data) {
    sha256 d;
    d.update(data.data(), data.size());
    return d.hexdigest();
}

// ---- environment ----------------------------------------------------------
inline bool enabled() {
    static int cached = -1;
    if (cached < 0) {
        const char * p = std::getenv("IS301_OBSERVE");
        cached = (p && std::string(p) == "1") ? 1 : 0;
    }
    return cached == 1;
}

inline long long pid() {
#ifdef _WIN32
    return (long long) _getpid();
#else
    return (long long) getpid();
#endif
}

// Linux /proc field 22: kernel process-start clock ticks (not wall time).
// Parse after the final ')' because comm can contain spaces/parentheses.
inline std::string process_start_ticks() {
    std::ifstream input("/proc/self/stat");
    std::string line, value;
    if (!std::getline(input, line)) return {};
    const size_t end = line.rfind(')');
    if (end == std::string::npos) return {};
    std::istringstream fields(line.substr(end + 1));
    for (int field = 3; field <= 22; ++field) {
        if (!(fields >> value)) return {};
    }
    if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos) return {};
    return value;
}

inline long long now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// ASCII-safe JSON string quoting; non-ASCII bytes are escaped as \u00XX so
// canonical bytes are always ASCII, matching the parser's ensure_ascii form.
inline std::string quote(const std::string & s) {
    std::string out = "\"";
    char buf[8];
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += (char) c; }
        else if (c < 32 || c > 126) { std::snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
        else { out += (char) c; }
    }
    return out + "\"";
}

// ---- bounded raw event recorder ------------------------------------------
// Static locals in inline functions have one instance across translation
// units; every hooked TU records into this single process-wide stream.
struct recorder {
    static const int MAX_EVENTS = 512;
    std::mutex mu;
    std::string events[MAX_EVENTS];
    int count = 0;
    long long dropped = 0;
    bool overflow = false;

    void record(const std::string & name) {
        std::lock_guard<std::mutex> lock(mu);
        if (count >= MAX_EVENTS) { dropped++; overflow = true; return; }
        std::string row = std::string("{\"event\":") + quote(name) +
                          ",\"sequence\":" + std::to_string(count) + "}";
        events[count++] = row;
    }
};

inline recorder & stream() {
    static recorder instance;
    return instance;
}

// Observation facts accumulated by the process (bounded, ASCII-safe). Key
// order is normalized at envelope time: canonical JSON requires sorted keys
// at every level, matching the downstream parser's sort_keys=True form.
struct facts_builder {
    std::mutex mu;
    std::vector<std::pair<std::string, std::string>> rows;
    std::vector<std::string> array_keys;  // keys whose value renders with brackets
    long long dropped = 0;
    bool overflowed = false;
    void mark_array(const std::string & key) {
        for (auto & k : array_keys) { if (k == key) return; }
        array_keys.push_back(key);
    }
    bool is_array(const std::string & key) const {
        for (auto & k : array_keys) { if (k == key) return true; }
        return false;
    }
    void add(const std::string & key, const std::string & canonical_value) {
        std::lock_guard<std::mutex> lock(mu);
        static const size_t FACT_BOUND = 4096;
        if (canonical_value.size() > FACT_BOUND) { dropped++; overflowed = true; return; }
        for (auto & row : rows) {
            if (row.first == key) {
                // Scalar overwrite onto an accumulated array would corrupt the
                // canonical form: refuse (keep the last well-formed value).
                if (is_array(key)) { dropped++; return; }
                row.second = canonical_value; return;
            }
        }
        rows.emplace_back(key, canonical_value);
    }
    // Append one canonical element to the array value under key (bounded).
    // Array rows are stored as element lists; brackets are applied at render.
    void append(const std::string & key, const std::string & canonical_element) {
        static const size_t FACT_BOUND = 4096;
        std::lock_guard<std::mutex> lock(mu);
        if (canonical_element.size() > FACT_BOUND) { dropped++; return; }  // bounded first element
        for (auto & row : rows) {
            if (row.first == key) {
                if (!is_array(key)) { dropped++; return; }  // never corrupt a scalar fact
                if (row.second.size() + canonical_element.size() + 1 > FACT_BOUND) {
                    dropped++; overflowed = true; return;
                }
                if (!row.second.empty()) row.second += ",";
                row.second += canonical_element;
                return;
            }
        }
        mark_array(key);
        rows.emplace_back(key, canonical_element);
    }
    std::string canonical_object() {
        std::lock_guard<std::mutex> lock(mu);
        std::sort(rows.begin(), rows.end());
        std::string out = "{";
        for (size_t i = 0; i < rows.size(); i++) {
            if (i) out += ",";
            out += quote(rows[i].first) + ":" +
                   (is_array(rows[i].first) ? "[" + rows[i].second + "]" : rows[i].second);
        }
        return out + "}";
    }
    // Canonical form for one key's accumulated array elements.
    std::string canonical_array(const std::string & key) {
        std::lock_guard<std::mutex> lock(mu);
        for (auto & row : rows) {
            if (row.first == key) { return "[" + row.second + "]"; }
        }
        return "[]";
    }
};

inline facts_builder & facts() {
    static facts_builder instance;
    return instance;
}

// Canonical scalar helpers.
inline std::string kv_str(const char * k, const std::string & v) {
    return quote(k) + std::string(":") + quote(v);
}
inline std::string kv_num(const char * k, long long v) {
    return quote(k) + std::string(":") + std::to_string(v);
}
inline std::string kv_raw(const char * k, const std::string & canonical_json) {
    return quote(k) + std::string(":") + canonical_json;
}
inline std::string kv_bool(const char * k, bool v) {
    return quote(k) + std::string(":") + (v ? "true" : "false");
}
// Canonical 4-dimension shape array ["n0",...,"n3"] for transfer facts.
inline std::string kv_shape(const char * k, const int64_t * ne) {
    std::string out = quote(k) + std::string(":[");
    for (int i = 0; i < 4; i++) {
        if (i) out += ",";
        out += std::to_string((long long) ne[i]);
    }
    return out + "]";
}

// ---- envelope emission -----------------------------------------------------
// Build the complete canonical envelope (sorted keys everywhere) and seal it
// with SHA-256 over everything except terminal_digest itself.
inline std::string envelope(const char * phase, const std::string & participant,
                            const std::string & plan_digest,
                            const std::string & invocation_token,
                            const std::string & generation, const char * stream_kind,
                            bool terminal, bool snapshot_fence) {
    recorder & r = stream();
    std::lock_guard<std::mutex> lock(r.mu);
    std::string seq = "[";
    for (int i = 0; i < r.count; i++) {
        if (i) seq += ",";
        seq += r.events[i];
    }
    seq += "]";
    long long dropped_events = 0;
    bool capture_overflow = r.overflow;
    {
        facts_builder & f = facts();
        std::lock_guard<std::mutex> flock(f.mu);
        dropped_events = r.dropped + f.dropped;
        capture_overflow = r.overflow || f.overflowed;
    }
    std::string facts_json = facts().canonical_object();
    std::string core;
    core += "{";
    core += kv_num("dropped_events", dropped_events) + ",";
    core += kv_num("event_count", (long long) r.count) + ",";
    core += kv_raw("facts", facts_json) + ",";
    core += kv_str("invocation_token", invocation_token) + ",";
    core += kv_bool("overflow", capture_overflow) + ",";
    core += kv_str("participant_id", participant) + ",";
    core += kv_str("phase", phase) + ",";
    core += kv_str("plan_digest", plan_digest) + ",";
    core += kv_str("schema", "inferswarm-native-observation/2") + ",";
    core += kv_raw("sequence", seq) + ",";
    core += kv_num("sequence_start", 0) + ",";
    core += kv_bool("snapshot_fence", snapshot_fence) + ",";
    core += kv_str("stream_generation", generation) + ",";
    core += kv_str("stream_kind", stream_kind) + ",";
    core += kv_bool("terminal", terminal) + ",";
    core += "\"terminal_sequence\":" + std::to_string(r.count);
    std::string digest = sha256_hex(core + "}");
    core += ",\"terminal_digest\":" + quote(digest);
    core += "}";
    return core;
}

// Reset per-capture state; a reset must use a NEW generation upstream.
inline void reset() {
    recorder & r = stream();
    facts_builder & f = facts();
    std::lock_guard<std::mutex> lock(r.mu);
    std::lock_guard<std::mutex> flock(f.mu);
    r.count = 0; r.dropped = 0; r.overflow = false;
    for (int i = 0; i < recorder::MAX_EVENTS; i++) r.events[i].clear();
    f.rows.clear();
    f.dropped = 0;
    f.overflowed = false;
}

// ---- bounded collector export ---------------------------------------------
// Writes one sealed envelope under $IS301_EXPORT_DIR. Each capture is isolated
// by a fresh generation and reset only after atomic publication succeeds.
inline void export_capture(const char * phase, const char * stream_kind,
                           bool terminal, bool snapshot_fence,
                           const char * participant) {
    if (!enabled()) return;
    static const std::string export_dir = [] {
        const char * value = std::getenv("IS301_EXPORT_DIR");
        return value ? std::string(value) : std::string();
    }();
    if (export_dir.empty()) return;
    static const int MAX_EXPORTS = 64;
    static int export_counter = 0;
    static long long owner_pid = 0;
    static std::string owner_start;
    // Reject fork reentry before touching an inherited mutex/state.
    static const long long exporter_pid = pid();
    const long long process_id = pid();
    if (exporter_pid != process_id) {
        std::fprintf(stderr, "is301: inherited export ownership refused\n");
        return;
    }
    static std::mutex export_mu;
    std::lock_guard<std::mutex> export_lock(export_mu);
    const std::string start_ticks = process_start_ticks();
    if (start_ticks.empty() || (owner_pid != 0 &&
        (owner_pid != process_id || owner_start != start_ticks))) {
        std::fprintf(stderr, "is301: export owner identity mismatch\n");
        return;
    }
    if (export_counter >= MAX_EXPORTS) {
        std::fprintf(stderr, "is301: export cap reached\n");
        return;
    }
    if (export_counter == 0) {
        // One export directory serves at most ONE observing process, claimed
        // ATOMICALLY via O_CREAT|O_EXCL: concurrent starters cannot both win,
        // so a shared directory cannot accumulate exports across processes.
        // A stale claim from a crashed process fails closed (controller owns
        // directory layout: one fresh directory per observed process).
        const std::string claim = export_dir + "/is301-claim";
        const int fd = ::open(claim.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
        if (fd < 0) {
            std::fprintf(stderr, "is301: export dir already claimed by another process\n");
            return;
        }
        const std::string owner = std::to_string(process_id) + "\n" + start_ticks + "\n" + participant + "\n";
        const bool claimed = ::write(fd, owner.data(), owner.size()) == (ssize_t) owner.size();
        ::close(fd);
        if (!claimed) return;
        owner_pid = process_id;
        owner_start = start_ticks;
    }
    const int current = export_counter++;
    const std::string generation = std::string("exp-") + std::to_string(process_id) + "-" +
        std::to_string(current) + "-" + std::to_string(now_ns());
    const std::string body = envelope(phase, participant, std::string(64, '0'),
        "export", generation, stream_kind, terminal, snapshot_fence);
    char suffix[32];
    std::snprintf(suffix, sizeof suffix, "-%04d.json", current);
    const std::string name = export_dir + "/" + participant + "-" +
        std::to_string(process_id) + suffix;
    const std::string temporary = name + ".tmp";
    std::FILE * out = std::fopen(temporary.c_str(), "wb");
    if (!out) return;
    const bool written = std::fwrite(body.data(), 1, body.size(), out) == body.size();
    const bool closed = std::fclose(out) == 0;
    if (!written || !closed || std::rename(temporary.c_str(), name.c_str()) != 0) {
        std::remove(temporary.c_str());
        return;
    }
    reset();
}

} // namespace is301

#endif // IS301_OBSERVER_H
