"""#241 crash-leg diagnostic reproduction (case-1024 C arm), 2026-09-24.

NOT a campaign execution — a hardware-fault reproduction for the
operator's live nvtop observation. Runs the exact frozen Phase-3
crash-leg geometry (case-1024, candidate arm C, ngl=8, frozen request
contract, exact fixture prompt) using the accepted canonical no-hook
R8-H Vulkan binary (same pinned llama.cpp build b29c606e, same load
geometry as the comparator/2 server whose observer is INERT during
loading). Historical fixtures only; zero predictive cases; zero holdout
access. One repeat: approximately what case-1024-C was doing when the
link dropped (~50% of a 1022-token prompt at 36.46 tok/s).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVER = Path("/home/hermes/llama.cpp/r8h-matched/build-r8h-vk/bin/llama-server")
MODEL = Path("/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf")
PROMPT = Path("/home/hermes/is241-diag/case-1024-prompt.txt").read_text()
OUT = Path("/home/hermes/is241-diag")

REQUEST = {"cache_prompt": False, "n_predict": 8, "return_tokens": True,
           "samplers": ["top_k"], "seed": 0, "stream": False,
           "temperature": 0.0, "top_k": 1, "prompt": PROMPT}
ENV = {"CUDA_VISIBLE_DEVICES": "-1",
       "GGML_VK_VISIBLE_DEVICES": "0",
       "VK_ICD_FILENAMES": "/usr/share/vulkan/icd.d/radeon_icd.json"}
ARGV = [str(SERVER), "--model", str(MODEL), "--n-gpu-layers", "8",
        "--ctx-size", "8192", "--batch-size", "512",
        "--host", "127.0.0.1", "--port", "19001", "-lv", "5"]


def sample(tag):
    p = "/sys/class/hwmon/hwmon2"
    try:
        temp = int(Path(p, "temp1_input").read_text()) / 1000
        pw = int(Path(p, "power1_input").read_text()) / 1e6
        fan = int(Path(p, "fan1_input").read_text())
        vr = int(Path("/sys/bus/pci/devices/0000:02:00.0/mem_info_vram_used").read_text()) / 2**20
        line = f"{tag} temp={temp:.1f}C power={pw:.2f}W fan={fan}rpm vram={vr:.0f}MiB"
    except Exception as exc:
        line = f"{tag} hwmon-read-error: {exc}"
    Path(OUT, "hwmon-samples.log").open("a").write(time.strftime("%H:%M:%S ") + line + "\n")
    print(line, flush=True)


def main():
    env = {**os.environ, **ENV}
    log = Path(OUT, "diag-server.log")
    t0 = time.monotonic()
    print(f"launching: {' '.join(ARGV[1:])}", flush=True)
    with log.open("wb") as lf:
        proc = subprocess.Popen(ARGV, stdout=lf, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
        try:
            # sample during model load (the sustained PCIe/VRAM phase)
            while time.monotonic() - t0 < 900:
                if proc.poll() is not None:
                    raise RuntimeError(f"server exited early rc={proc.returncode}")
                sample("load")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:19001/health", timeout=1) as h:
                        if h.status == 200:
                            break
                except OSError:
                    time.sleep(2)
            sample("ready")
            body = json.dumps(REQUEST).encode()
            req = urllib.request.Request("http://127.0.0.1:19001/completion",
                                         data=body,
                                         headers={"Content-Type": "application/json"})
            sample("prompt-start")
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = resp.read()
            sample("prompt-done")
            doc = json.loads(raw)
            tokens = doc.get("tokens", doc.get("tokens_predicted"))
            print("tokens:", tokens, flush=True)
            Path(OUT, "diag-response.json").write_bytes(raw)
            print(f"total wall: {time.monotonic()-t0:.1f}s", flush=True)
        finally:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=15)
            except Exception as exc:
                print(f"shutdown: {exc}", flush=True)
            sample("post")


if __name__ == "__main__":
    main()
