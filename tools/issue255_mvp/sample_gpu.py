#!/usr/bin/env python3
"""Issue-255-only per-process NVIDIA sampling; one owned PID and one GPU."""
import json
import subprocess
import sys
import time

pid = int(sys.argv[1])
while True:
    at = time.time()
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu',
                          '--format=csv,noheader,nounits'], capture_output=True, text=True)
    apps = subprocess.run(['nvidia-smi', '--query-compute-apps=pid,used_gpu_memory',
                           '--format=csv,noheader,nounits'], capture_output=True, text=True)
    try:
        memory, util = [int(x.strip()) for x in gpu.stdout.splitlines()[0].split(',')]
        processes = {}
        for row in apps.stdout.splitlines():
            fields = row.split(',')
            if len(fields) >= 2 and fields[0].strip().isdigit():
                processes[int(fields[0].strip())] = fields[1].strip()
        print(json.dumps({'epoch': at, 'used_mib': memory, 'util_percent': util,
                          'pids': sorted(processes), 'process_memory': processes,
                          'sample_error': gpu.stderr or apps.stderr or None}), flush=True)
    except (IndexError, ValueError) as exc:
        print(json.dumps({'epoch': at, 'error': str(exc), 'gpu_output': gpu.stdout,
                          'apps_output': apps.stdout}), flush=True)
    try:
        import os
        os.kill(pid, 0)
    except ProcessLookupError:
        break
    time.sleep(.25)
