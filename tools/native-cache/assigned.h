// Private #311 immutable upload guard. No model loader or distribution protocol.
#pragma once
#include <fstream>
#include <sstream>
#include <map>
#include <array>

struct assigned_range {
    uint32_t type;
    std::array<uint32_t, 4> ne;
    uint64_t length;
    std::string sha;
};

static const std::map<std::string, assigned_range> & assigned_ranges() {
    static const auto ranges = [] {
        std::map<std::string, assigned_range> result;
        const char * path = getenv("IS311_ASSIGNED");
        if (!path) { return result; }
        std::ifstream file(path);
        GGML_ASSERT(file.good());
        std::string line;
        size_t bytes = 0;
        while (std::getline(file, line)) {
            bytes += line.size() + 1;
            GGML_ASSERT(bytes <= 1048576);
            std::istringstream row(line);
            std::string name, extra;
            assigned_range range;
            GGML_ASSERT(bool(row >> name >> range.type >> range.ne[0] >> range.ne[1]
                >> range.ne[2] >> range.ne[3] >> range.length >> range.sha));
            GGML_ASSERT(!(row >> extra) && range.sha.size() == 64);
            GGML_ASSERT(result.emplace(name, range).second);
        }
        GGML_ASSERT(file.eof() && !result.empty());
        return result;
    }();
    return ranges;
}

static bool assigned_upload(const rpc_msg_set_tensor_hash_req & request) {
    const auto & ranges = assigned_ranges();
    const auto it = ranges.find(request.tensor.name);
    if (it == ranges.end()) { return false; }
    const auto & range = it->second;
    if (request.tensor.view_src != 0 || request.tensor.view_offs != 0) { return false; }
    if (request.offset != 0 || request.size != range.length || request.tensor.type != range.type) { return false; }
    for (size_t i = 0; i < 4; ++i) {
        if (request.tensor.ne[i] != range.ne[i]) { return false; }
    }
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < 32; ++i) {
        if (range.sha[2*i] != hex[request.sha256[i] >> 4]
            || range.sha[2*i+1] != hex[request.sha256[i] & 15]) { return false; }
    }
    return true;
}
