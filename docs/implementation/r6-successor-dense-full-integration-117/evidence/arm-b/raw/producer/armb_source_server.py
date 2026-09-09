"""Arm-B SOURCE transport server (inferswarm01): HTTP Range GET over the
authorized source root /srv/models/gemma-r6, LAN-bound.

This exposes the accepted #99 operator-local-http source read contract for
the remote participant (inferswarm03). It serves ONLY Range GETs; it is not
an orchestration bypass (all consumer reads happen inside acquire_artifact
under Coordinator tickets).
"""
from __future__ import annotations

import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path("/srv/models/gemma-r6")
HOST, PORT = "10.0.0.141", 18486


class RangeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        name = self.path.lstrip("/")
        path = (ROOT / name).resolve()
        if not path.is_file() or ROOT not in path.parents:
            self.send_error(404, "SOURCE_OBJECT_UNAVAILABLE")
            return
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        start, end = 0, size
        if range_header and range_header.startswith("bytes="):
            first, _, last = range_header[len("bytes="):].partition("-")
            start = int(first)
            end = size if not last else int(last) + 1
        with open(path, "rb") as h:
            h.seek(start)
            body = h.read(end - start)
        self.send_response(206 if range_header else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if range_header:
            self.send_header("Content-Range",
                             f"bytes {start}-{start + len(body) - 1}/{size}")
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), RangeHandler)
    print(f"source serving {ROOT} on {HOST}:{PORT}", flush=True)
    server.serve_forever()
