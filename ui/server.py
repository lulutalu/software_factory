#!/usr/bin/env python3
"""Live dashboard for a software-factory run.

Serves ui/index.html and a small JSON API over the files in a project's
.factory/ directory. Standard library only. Binds to 127.0.0.1.

Usage:
    python3 server.py --factory-dir /path/to/project/.factory [--port 8765]

On start it writes .factory/ui.json ({"url", "pid"}) and prints the URL.
It exits by itself after --idle-timeout seconds without any request
(the open page polls every 2s, so it stays alive while you watch).

Everything is read-only except one write: POST /api/answer, which lets the
user answer the orchestrator's pending question (.factory/inbox/pending.json)
from the page. The server writes the answer to .factory/inbox/answer.json and
the orchestrator picks it up (see skills/factory/SKILL.md). The POST requires:
the right Host (DNS rebinding), a same-origin Origin header (CSRF), the
per-server token embedded in the page, a JSON body under 64 KiB, and an
answer that matches the pending question.
"""

import argparse
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).resolve().parent
ALLOWED_SUFFIXES = {".md", ".json"}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 64 * 1024
MAX_TEXT = 8000
DECISIONS = {"approve", "request_changes", "reject"}
TOKEN_PLACEHOLDER = b"__FACTORY_TOKEN__"

VERDICT_RE = re.compile(r"^VERDICT\s*:\s*(APPROVED|CHANGES_REQUESTED)\s*$", re.IGNORECASE)


def first_verdict(path: Path):
    """Verdict of a review file, using the same rule as the orchestrator (SKILL.md).

    Skips blank lines and ``` fence lines; the first remaining line must be
    "VERDICT: APPROVED" or "VERDICT: CHANGES_REQUESTED" (any case, extra spaces OK).
    Only that line counts: a verdict quoted further down is ignored.
    Returns None if the file doesn't exist yet, "INVALID" if it can't be parsed.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("```"):
                    continue
                m = VERDICT_RE.match(line)
                return m.group(1).upper() if m else "INVALID"
    except FileNotFoundError:
        return None
    except OSError:
        return "INVALID"
    return "INVALID"  # empty file, or only blanks/fences


def read_json(path: Path):
    """Parsed JSON file, or None if missing/unreadable/mid-write."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_json_atomic(path: Path, obj):
    """Write via a temp file + rename, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")  # .tmp is never served
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_answer(pending: dict, body):
    """Check a browser answer against the pending question.

    Returns (answer, None) with only the validated fields, or (None, error).
    The format of pending.json / answer.json is defined in SKILL.md.
    """
    if not isinstance(body, dict) or body.get("id") != pending.get("id"):
        return None, "this question is no longer pending (reload the page)"
    kind = pending.get("kind")

    if kind == "approval":
        decision, feedback = body.get("decision"), body.get("feedback", "")
        if decision not in DECISIONS:
            return None, "invalid decision"
        if not isinstance(feedback, str) or len(feedback) > MAX_TEXT:
            return None, f"feedback must be text under {MAX_TEXT} characters"
        if decision == "request_changes" and not feedback.strip():
            return None, "feedback is required to request changes"
        return {"decision": decision, "feedback": feedback.strip()}, None

    if kind == "questions":
        answers = body.get("answers")
        if not isinstance(answers, dict):
            return None, "invalid answers"
        out = {}
        for q in pending.get("questions") or []:
            qid = q.get("id")
            a = answers.get(qid)
            if not isinstance(a, dict):
                return None, f"missing answer for {qid}"
            choices, text = a.get("choices", []), a.get("text", "")
            allowed = set(q.get("options") or [])
            if (not isinstance(choices, list)
                    or not all(isinstance(c, str) and c in allowed for c in choices)
                    or len(set(choices)) != len(choices)
                    or (not q.get("multi") and len(choices) > 1)
                    or not isinstance(text, str) or len(text) > MAX_TEXT):
                return None, f"invalid answer for {qid}"
            if not choices and not text.strip():
                return None, f"please answer: {q.get('question', qid)}"
            out[qid] = {"choices": choices, "text": text.strip()}
        return {"answers": out}, None

    return None, "unknown question kind"


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


def make_handler(root: Path, state: dict, token: str):
    cache = {}
    inbox = root / "inbox"
    answer_lock = threading.Lock()  # one answer at a time: first one wins

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

        def _host_ok(self):
            # Blocks DNS rebinding: a page on evil.example resolving to 127.0.0.1
            # would send "Host: evil.example".
            port = self.server.server_address[1]
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            state["last_request"] = time.monotonic()
            if not self._host_ok():
                return self._json({"error": "bad host"}, 403)
            url = urlparse(self.path)

            if url.path in ("/", "/index.html"):
                body = (UI_DIR / "index.html").read_bytes().replace(TOKEN_PLACEHOLDER, token.encode())
                return self._send(200, body, "text/html; charset=utf-8")

            if url.path == "/api/state":
                pending = read_json(inbox / "pending.json")
                answer = read_json(inbox / "answer.json")
                pending = pending if isinstance(pending, dict) else None
                return self._json({
                    "factory_dir": str(root),
                    "exists": root.is_dir(),
                    "status": read_status(root, cache),
                    "verdicts": {
                        "code": first_verdict(root / "review-code.md"),
                        "security": first_verdict(root / "review-security.md"),
                    },
                    "pending": pending,
                    "answered": bool(pending and isinstance(answer, dict)
                                     and answer.get("id") == pending.get("id")),
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

        def do_POST(self):
            state["last_request"] = time.monotonic()
            if urlparse(self.path).path != "/api/answer":
                return self._json({"error": "not found"}, 404)
            if not self._host_ok():
                return self._json({"error": "bad host"}, 403)
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                return self._json({"error": "bad origin"}, 403)
            given = self.headers.get("X-Factory-Token", "")
            if not secrets.compare_digest(given.encode(), token.encode()):
                return self._json({"error": "bad token (reload the page)"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                return self._json({"error": "expected application/json"}, 415)
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._json({"error": "length required"}, 411)
            if not 0 < length <= MAX_BODY_BYTES:
                return self._json({"error": "body too large"}, 413)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json({"error": "invalid JSON"}, 400)

            with answer_lock:
                pending = read_json(inbox / "pending.json")
                if not isinstance(pending, dict):
                    return self._json({"error": "nothing to answer right now"}, 409)
                existing = read_json(inbox / "answer.json")
                if isinstance(existing, dict) and existing.get("id") == pending.get("id"):
                    return self._json({"error": "already answered"}, 409)
                answer, err = validate_answer(pending, body)
                if err:
                    return self._json({"error": err}, 400)
                answer = {"id": pending["id"], "source": "browser",
                          "answered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          **answer}
                write_json_atomic(inbox / "answer.json", answer)
            return self._json({"ok": True})

        def _method_not_allowed(self):
            self._json({"error": "method not allowed"}, 405)

        do_PUT = do_DELETE = do_PATCH = _method_not_allowed

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
    token = secrets.token_urlsafe(32)  # lives only in memory and in the served page
    httpd = bind(make_handler(root, state, token), args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    (root / "ui.json").write_text(json.dumps({"url": url, "pid": os.getpid()}) + "\n", encoding="utf-8")
    print(f"FACTORY_UI {url}", flush=True)

    def idle_watch():
        while True:
            time.sleep(30)
            if time.monotonic() - state["last_request"] > args.idle_timeout:
                httpd.shutdown()
                return

    def on_sigterm(signum, frame):
        # `kill <pid>` should clean up ui.json like a normal stop does.
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_sigterm)
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
