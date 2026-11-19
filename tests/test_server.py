"""Tests for the dashboard server (ui/server.py). Standard library only.

Run: python3 -m unittest discover -s tests -v
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ui"))
import server  # noqa: E402


class FirstVerdictTest(unittest.TestCase):
    def verdict(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "review.md"
            p.write_text(text, encoding="utf-8")
            return server.first_verdict(p)

    def test_valid_verdicts(self):
        self.assertEqual(self.verdict("VERDICT: APPROVED\n"), "APPROVED")
        self.assertEqual(self.verdict("verdict :  changes_requested \n"), "CHANGES_REQUESTED")

    def test_skips_blank_and_fence_lines(self):
        self.assertEqual(self.verdict("\n```\n\nVERDICT: APPROVED\n```\n"), "APPROVED")

    def test_only_first_line_counts(self):
        # A verdict quoted further down must not be picked up.
        self.assertEqual(self.verdict("# Review\nVERDICT: APPROVED\n"), "INVALID")

    def test_empty_and_missing(self):
        self.assertEqual(self.verdict(""), "INVALID")
        self.assertIsNone(server.first_verdict(Path("/nonexistent/review.md")))


class ValidateAnswerTest(unittest.TestCase):
    APPROVAL = {"id": "approval-1", "kind": "approval"}
    QUESTIONS = {"id": "spec-1", "kind": "questions", "questions": [
        {"id": "q1", "question": "DB?", "options": ["sqlite", "postgres"], "multi": False},
    ]}

    def test_approval(self):
        ok, err = server.validate_answer(self.APPROVAL, {"id": "approval-1", "decision": "approve"})
        self.assertIsNone(err)
        self.assertEqual(ok["decision"], "approve")

    def test_request_changes_needs_feedback(self):
        _, err = server.validate_answer(self.APPROVAL, {"id": "approval-1", "decision": "request_changes"})
        self.assertIsNotNone(err)

    def test_stale_id_and_unknown_decision(self):
        self.assertIsNotNone(server.validate_answer(self.APPROVAL, {"id": "old", "decision": "approve"})[1])
        self.assertIsNotNone(server.validate_answer(self.APPROVAL, {"id": "approval-1", "decision": "merge"})[1])

    def test_questions(self):
        body = {"id": "spec-1", "answers": {"q1": {"choices": ["sqlite"], "text": ""}}}
        ok, err = server.validate_answer(self.QUESTIONS, body)
        self.assertIsNone(err)
        self.assertEqual(ok, {"answers": {"q1": {"choices": ["sqlite"], "text": ""}}})

    def test_questions_rejects_bad_choices(self):
        for choices in (["mysql"], ["sqlite", "postgres"]):  # not an option / two on single-choice
            body = {"id": "spec-1", "answers": {"q1": {"choices": choices}}}
            self.assertIsNotNone(server.validate_answer(self.QUESTIONS, body)[1], choices)

    def test_extra_fields_are_dropped(self):
        body = {"id": "approval-1", "decision": "approve", "evil": "x"}
        ok, _ = server.validate_answer(self.APPROVAL, body)
        self.assertNotIn("evil", ok)


class HttpTest(unittest.TestCase):
    """Starts the real handler on a free port and checks the security rules."""

    TOKEN = "test-token"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".factory"
        (self.root / "inbox").mkdir(parents=True)
        (self.root / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (self.root / "secret.txt").write_text("nope", encoding="utf-8")
        handler = server.make_handler(self.root, {"last_request": 0}, self.TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": self.host}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def post_answer(self, payload, **overrides):
        headers = {"Origin": f"http://{self.host}", "X-Factory-Token": self.TOKEN,
                   "Content-Type": "application/json"}
        headers.update(overrides)
        return self.request("POST", "/api/answer", json.dumps(payload), headers)[0]

    def set_pending(self):
        (self.root / "inbox" / "pending.json").write_text(
            json.dumps({"id": "approval-1", "kind": "approval"}), encoding="utf-8")

    def test_serves_factory_markdown(self):
        status, data = self.request("GET", "/api/file?path=spec.md")
        self.assertEqual((status, data), (200, b"# Spec\n"))

    def test_file_access_is_restricted(self):
        for path in ("../../etc/passwd", "secret.txt", "/etc/hostname", ""):
            status, _ = self.request("GET", f"/api/file?path={path}")
            self.assertEqual(status, 404, path)

    def test_rejects_foreign_host(self):  # DNS rebinding
        status, _ = self.request("GET", "/api/state", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_post_security_checks(self):
        self.set_pending()
        ok = {"id": "approval-1", "decision": "approve"}
        self.assertEqual(self.post_answer(ok, **{"X-Factory-Token": "wrong"}), 403)
        self.assertEqual(self.post_answer(ok, Origin="http://evil.example"), 403)
        self.assertEqual(self.post_answer(ok, **{"Content-Type": "text/plain"}), 415)
        self.assertFalse((self.root / "inbox" / "answer.json").exists())

    def test_first_answer_wins(self):
        self.set_pending()
        ok = {"id": "approval-1", "decision": "approve"}
        self.assertEqual(self.post_answer(ok), 200)
        self.assertEqual(self.post_answer({**ok, "decision": "reject"}), 409)
        saved = json.loads((self.root / "inbox" / "answer.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["decision"], saved["source"]), ("approve", "browser"))

    def test_nothing_pending(self):
        self.assertEqual(self.post_answer({"id": "x", "decision": "approve"}), 409)


if __name__ == "__main__":
    unittest.main()
