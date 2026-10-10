// Native two-process adversarial export proof. Parent build only; no unittest compile.
#include "is301_observer.h"
#include <cassert>
#include <sys/wait.h>

static std::string read_file(const std::filesystem::path & path) {
    std::ifstream input(path, std::ios::binary);
    assert(input);
    return std::string(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
}

static std::vector<std::pair<std::string, std::string>> snapshot(const std::string & dir) {
    std::vector<std::pair<std::string, std::string>> files;
    for (const auto & entry : std::filesystem::directory_iterator(dir)) {
        assert(entry.is_regular_file());
        files.emplace_back(entry.path().filename().string(), read_file(entry.path()));
    }
    std::sort(files.begin(), files.end());
    return files;
}

static int status(pid_t child) {
    int result = 0;
    assert(::waitpid(child, &result, 0) == child);
    assert(WIFEXITED(result));
    return WEXITSTATUS(result);
}

int main(int argc, char ** argv) {
    if (argc != 2 || !is301::enabled()) return 2;
    const std::string dir(argv[1]);
    const char * configured = std::getenv("IS301_EXPORT_DIR");
    assert(configured && dir == configured);
    assert(snapshot(dir).empty());
    int gate[2];
    assert(::pipe(gate) == 0);
    pid_t children[2];
    for (int i = 0; i < 2; ++i) {
        children[i] = ::fork();
        assert(children[i] >= 0);
        if (children[i] == 0) {
            ::close(gate[1]);
            char start;
            assert(::read(gate[0], &start, 1) == 1);
            ::close(gate[0]);
            // First use of the real exporter occurs AFTER the synchronized gate.
            const std::string ticks = is301::process_start_ticks();
            assert(!ticks.empty());
            is301::facts().add("process", std::string("{") +
                is301::kv_num("pid", is301::pid()) + "," +
                is301::kv_num("start_ticks", std::stoll(ticks)) + "}");
            is301::stream().record("fixture_export_claim");
            is301::export_capture("dynamic", "whole", true, false, "claim-race");
            const std::string own = dir + "/claim-race-" + std::to_string(is301::pid()) + "-0000.json";
            if (!std::filesystem::exists(own)) ::_exit(23);
            const std::string owner = read_file(dir + "/is301-claim");
            const std::string expected_owner = std::to_string(is301::pid()) + "\n" + ticks + "\nclaim-race\n";
            assert(owner == expected_owner);
            const auto before = snapshot(dir);
            assert(before.size() == 2);
            // A fork inherits a nonzero counter and owner: it MUST NOT bypass claim.
            const pid_t inherited = ::fork();
            assert(inherited >= 0);
            if (inherited == 0) {
                is301::export_capture("dynamic", "whole", true, false, "fork-reentry");
                ::_exit(0);
            }
            assert(status(inherited) == 0);
            assert(snapshot(dir) == before); // inherited ownership refused
            ::_exit(0);
        }
    }
    ::close(gate[0]);
    assert(::write(gate[1], "go", 2) == 2);
    ::close(gate[1]);
    std::vector<int> results = {status(children[0]), status(children[1])};
    std::sort(results.begin(), results.end());
    assert((results == std::vector<int>{0, 23}));
    const auto before = snapshot(dir);
    assert(before.size() == 2);
    // Both owners are now exited: a stale claim cannot be reclaimed or overwritten.
    is301::export_capture("dynamic", "whole", true, false, "stale-reentry");
    is301::export_capture("dynamic", "whole", true, false, "stale-reentry");
    assert(snapshot(dir) == before); // stale claim refused
    std::puts("IS301 native claim proof PASS: one owner/export, fork and stale refusal");
    return 0;
}
