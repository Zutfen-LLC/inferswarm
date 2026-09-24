"""Standalone per-field-tolerant hwmon sampler for the #241 diagnostic."""
import time
from pathlib import Path

OUT = Path("/home/hermes/is241-diag/hwmon-live.log")
P = "/sys/class/hwmon/hwmon2"
VRAM = "/sys/bus/pci/devices/0000:02:00.0/mem_info_vram_used"


def rd(p, div=1.0):
    try:
        return str(int(Path(p).read_text()) / div)
    except Exception:
        return "NA"


while True:
    parts = [
        time.strftime("%H:%M:%S"),
        f"temp={rd(P + '/temp1_input', 1000)}C",
        f"power={rd(P + '/power1_input', 1e6)}W",
        f"fan={rd(P + '/fan1_input')}rpm",
        f"vram={rd(VRAM, 2**20)}MiB",
    ]
    line = " ".join(parts)
    with OUT.open("a") as f:
        f.write(line + "\n")
    time.sleep(2)
