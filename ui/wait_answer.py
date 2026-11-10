#!/usr/bin/env python3
"""Wait until the dashboard records an answer to a pending question.

The orchestrator starts this in the background after writing
.factory/inbox/pending.json, then ends its turn. Exits when:
  0  .factory/inbox/answer.json exists with the same id (answered in the browser);
     prints "FACTORY_ANSWER <json>"
  3  pending.json is gone or has another id (answered in the terminal, or cancelled);
     prints "FACTORY_ANSWER_CANCELLED"

Usage:
    python3 wait_answer.py --factory-dir /path/to/project/.factory --id spec-1
"""

import argparse
import json
import sys
import time
from pathlib import Path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--factory-dir", required=True)
    ap.add_argument("--id", required=True, help="id of the pending question")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()
    inbox = Path(args.factory_dir).resolve() / "inbox"

    while True:
        answer = read_json(inbox / "answer.json")
        if isinstance(answer, dict) and answer.get("id") == args.id:
            print("FACTORY_ANSWER " + json.dumps(answer), flush=True)
            return 0
        pending = read_json(inbox / "pending.json")
        # Missing or replaced pending.json: the question was answered elsewhere.
        # (A mid-write read also returns None, so require two misses in a row.)
        if not (isinstance(pending, dict) and pending.get("id") == args.id):
            time.sleep(args.interval)
            pending = read_json(inbox / "pending.json")
            if not (isinstance(pending, dict) and pending.get("id") == args.id):
                print("FACTORY_ANSWER_CANCELLED", flush=True)
                return 3
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
