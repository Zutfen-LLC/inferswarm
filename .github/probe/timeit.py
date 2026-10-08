"""Per-test timing harness (outside production behavior).

usage: timeit.py OUT.json module [module ...]
Runs `unittest` for the given test modules serially in-process and records
per-test wall time, status, and also per-module setUpModule/class time via
the same events. Prints nothing from tests (buffered).
"""
import json, sys, time, unittest, os, resource

out = sys.argv[1]
mods = sys.argv[2:]
if len(mods) == 1 and mods[0].startswith("group:"):
    g = json.load(open("scripts/ci_groups.json"))["groups"][mods[0][6:]]["test_modules"]
    mods = ["tests." + m for m in g]
elif len(mods) == 1 and mods[0].startswith("list:"):
    mods = ["tests." + m for m in mods[0][5:].split(",")]
sys.path.insert(0, os.getcwd())

class R(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []
        self._t = {}
    def startTest(self, test):
        self._t[test.id()] = time.perf_counter()
        super().startTest(test)
    def _rec(self, test, status):
        t = time.perf_counter() - self._t.pop(test.id(), time.perf_counter())
        self.rows.append({"id": test.id(), "status": status, "seconds": round(t, 4)})
    def addSuccess(self, test): self._rec(test, "ok"); super().addSuccess(test)
    def addFailure(self, test, err): self._rec(test, "FAIL"); super().addFailure(test, err)
    def addError(self, test, err): self._rec(test, "ERROR"); super().addError(test, err)
    def addSkip(self, test, reason): self._rec(test, "skip"); super().addSkip(test, reason)

t0 = time.perf_counter()
c0 = time.process_time()
loader = unittest.TestLoader()
suite = loader.loadTestsFromNames(mods)
load_s = time.perf_counter() - t0
t1 = time.perf_counter()
runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), resultclass=R, verbosity=0)
res = runner.run(suite)
run_s = time.perf_counter() - t1
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
json.dump({"modules": mods, "load_seconds": round(load_s, 3), "run_seconds": round(run_s, 3),
           "cpu_seconds_self": round(time.process_time() - c0, 3),
           "tests_run": res.testsRun, "failures": len(res.failures), "errors": len(res.errors),
           "skipped": len(res.skipped), "rows": res.rows}, open(out, "w"), indent=1)
print(f"tests={res.testsRun} fail={len(res.failures)} err={len(res.errors)} skip={len(res.skipped)} load={load_s:.1f}s run={run_s:.1f}s")
sys.exit(0 if res.wasSuccessful() else 1)
