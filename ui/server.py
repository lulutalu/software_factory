#!/usr/bin/env python3
"""Read-only live dashboard for a software-factory run.

Serves ui/index.html and a small JSON API over the files in a project's
.factory/ directory. Standard library only. Binds to 127.0.0.1.

Usage:
    python3 server.py --factory-dir /path/to/project/.factory [--port 8765]

On start it writes .factory/ui.json ({"url", "pid"}) and prints the URL.
It exits by itself after --idle-timeout seconds without any request
(the open page polls every 2s, so it stays alive while you watch).
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).resolve().parent
ALLOWED_SUFFIXES = {".md", ".json"}
MAX_FILE_BYTES = 2 * 1024 * 1024


def first_verdict(path: Path):
    """Return APPROVED / CHANGES_REQUESTED from a review file's first line, or None."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            line = f.readline().strip()
    except OSError:
        return None
    if line.startswith("VERDICT:"):
        return line.split(":", 1)[1].strip() or None
    return None


def list_files(root: Path):
    """All .md/.json files under .factory/, relative paths, with mtime and size."""
    files = []
    if not root.is_dir():
        return files
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in ALLOWED_SUFFIXES and p.name != "ui.json":
            st = p.stat()
            files.append({
                "path": p.relative_to(root).as_posix(),
                "mtime": st.st_mtime,
                "size": st.st_size,
            })
    return files


def read_status(root: Path, cache: dict):
    """Parse status.json; on a partial/invalid write, keep serving the last good copy."""
    p = root / "status.json"
    try:
        cache["status"] = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cache["status"] = None
    except (OSError, json.JSONDecodeError):
        pass  # mid-write: keep previous value
    return cache.get("status")


def make_handler(root: Path, state: dict):
    cache = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the background output quiet
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            state["last_request"] = time.monotonic()
            url = urlparse(self.path)

            if url.path in ("/", "/index.html"):
                body = (UI_DIR / "index.html").read_bytes()
                return self._send(200, body, "text/html; charset=utf-8")

            if url.path == "/api/state":
                return self._json({
                    "factory_dir": str(root),
                    "exists": root.is_dir(),
                    "status": read_status(root, cache),
                    "verdicts": {
                        "code": first_verdict(root / "review-code.md"),
                        "security": first_verdict(root / "review-security.md"),
                    },
                    "files": list_files(root),
                    "server_time": time.time(),
                })

            if url.path == "/api/file":
                rel = parse_qs(url.query).get("path", [""])[0]
                target = (root / rel).resolve()
                # Only files inside .factory/, only .md/.json.
                if (not rel or root.resolve() not in target.parents
                        or target.suffix not in ALLOWED_SUFFIXES or not target.is_file()):
                    return self._json({"error": "not found"}, 404)
                data = target.read_bytes()[:MAX_FILE_BYTES]
                return self._send(200, data, "text/plain; charset=utf-8")

            self._json({"error": "not found"}, 404)

        def do_POST(self):  # read-only dashboard
            self._json({"error": "read-only"}, 405)

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Handler


def bind(handler, port: int, attempts: int = 20):
    for p in range(port, port + attempts):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), handler)
        except OSError:
            continue
    sys.exit(f"No free port in {port}-{port + attempts - 1}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--factory-dir", required=True, help="path to the project's .factory/ directory")
    ap.add_argument("--port", type=int, default=8765, help="first port to try (default 8765)")
    ap.add_argument("--idle-timeout", type=int, default=1800, help="exit after N idle seconds (default 1800)")
    args = ap.parse_args()

    root = Path(args.factory_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = {"last_request": time.monotonic()}
    httpd = bind(make_handler(root, state), args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    (root / "ui.json").write_text(json.dumps({"url": url, "pid": os.getpid()}) + "\n", encoding="utf-8")
    print(f"FACTORY_UI {url}", flush=True)

    def idle_watch():
        while True:
            time.sleep(30)
            if time.monotonic() - state["last_request"] > args.idle_timeout:
                httpd.shutdown()
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        try:
            info = json.loads((root / "ui.json").read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                (root / "ui.json").unlink()
        except (OSError, json.JSONDecodeError):
            pass


if __name__ == "__main__":
    main()
