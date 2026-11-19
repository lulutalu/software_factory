VERDICT: APPROVED

## Summary
Round 2 resolves both blocking code findings from round 1. `storage.load()` no longer pre-checks with `Path.exists()`: it reads inside a `try`, treats only `FileNotFoundError` as a missing store, and wraps every other `OSError` in `StoreError` (C1). As a result, the CLI's `except OSError` ("cannot write store file") is now reachable only from `storage.save` (C3). Ten new regression tests cover these cases, the docs match the new behaviour, and the full suite passes (63/63) with no regressions in A2-A16. A1 still needs manual verification by the user, because this environment has no pip or venv. As the orchestrator instructed, that environment limitation is not counted against the code.

## Acceptance criteria
- A1: NOT VERIFIABLE HERE (needs the user to check manually; not counted as blocking, per orchestrator instruction). There is no pip (`import pip` gives ModuleNotFoundError), no `python` command and no `pip` command. Partial checks: `pyproject.toml` is unchanged since round 1. It has `requires-python = ">=3.10"`, `dependencies = []`, `test = ["pytest"]` and `todo = "todo.cli:main"`. Round 1 already confirmed the wheel and editable-wheel builds, the metadata and an emulated console script. `python3 -m todo --help` exits 0. The user should run: `python3 -m venv .venv && .venv/bin/pip install -e ".[test]" && .venv/bin/todo --help && .venv/bin/python -m todo --help && .venv/bin/python -m pytest`.
- A2: PASS. The imports in `todo/` are `__future__, argparse, dataclasses, json, os, pathlib, sys, tempfile` and `todo`/`todo.cli`.
- A3: PASS. `list` on a missing store prints `No tasks.`, exits 0 and does not create the file. The new `test_load_missing_parent_dir_is_empty` also confirms that a missing parent directory still counts as a missing store and is not created.
- A4: PASS. `add Buy milk` prints `Added task 1: Buy milk`, and the store is exactly `{"next_id": 2, "tasks": [{"id": 1, "text": "Buy milk", "done": false}]}`.
- A5: PASS. `add "Pay rent"` gets ID 2. `add "  "` and `add ""` exit 1 with `todo: error: task text must not be empty`, and `cmp` shows the store unchanged.
- A6: PASS. `done 2` exits 0, and `list` prints exactly `1. [ ] Buy milk` / `2. [x] Pay rent`.
- A7: PASS. Running `done 2` again prints `Task 2 is already done.`, exits 0 and leaves the bytes unchanged.
- A8: PASS. `remove 2` exits 0, `list` shows only task 1, and `add Walk dog` gets ID 3.
- A9: PASS. `done 999`, `remove 999` and `remove 2` exit 1 with `todo: error: no task with id N`. `done abc` exits 2 (argparse). The bytes are unchanged in all four cases.
- A10: PASS. No args, `frobnicate`, `add`, `done` and `remove` each exit 2 with usage.
- A11: PASS. For `not json{`, `[]` and `{"tasks": "oops"}`, the commands `list`, `add x`, `done 1` and `remove 1` all exit 1. Each stderr names the file, none contains a traceback, and the file content is unchanged. New in this round: a store whose parent directory is chmod 000 now makes all four commands exit 1 with `invalid store file '<path>': Permission denied`, and the file stays unchanged. An unreadable file (chmod 000) gives `Permission denied`, a directory path gives `Is a directory`, and a parent that is a regular file gives `Not a directory`, all exit 1.
- A12: PASS. With `HOME` set to a temporary directory and no `--file`, `add Test` creates `$HOME/.todo.json` and `list` reads it.
- A13: PASS. `tests/test_storage.py` calls `storage.load/save/add_task/mark_done/remove_task` directly, including the 6 new load tests.
- A14: PASS. `python3 -m pytest` gives 63 passed. Every R20 item is still covered, plus the new unreadable/inaccessible-store regressions.
- A15: PASS. `~/.todo.json` was absent before and after the pytest run. I checked with `ls`/`stat` only and never read its contents.
- A16: PASS. The README "Store file" and "Exit codes" sections and the CLAUDE.md "Corrupt store (R17)" decision and Conventions line match the real behaviour I checked by hand (permission denied, directory path, missing parent). The minor C5 wording issue from round 1 remains (see C5).

## Tests
`python3 -m pytest -q -rs -p no:cacheprovider` from the repo root (Python 3.14.4, run as non-root uid 1000, so the chmod tests ran instead of being skipped): **63 passed, 0 failed, 0 skipped**. That is 53 from round 1 plus 10 new: 6 in `tests/test_storage.py` and 4 parametrized cases of `test_unreadable_store_fails_every_command` in `tests/test_cli.py`. Every chmod-based test restores permissions in `finally` and checks the file bytes are unchanged. `test_load_permission_error_without_chmod` covers the same path without chmod, so it also runs as root. I also re-ran the A3-A12 scenarios by hand with `python3 -m todo` in a scratch directory and all matched.

## Findings
### C1 — RESOLVED (was BLOCKING) — `load()` treated an existing but inaccessible store as missing
- category: correctness
- where: todo/storage.py:60-80
- problem: resolved. The `exists()` pre-check is gone. `read_bytes()` is guarded with `except FileNotFoundError` (returns an empty `TodoList()`) placed before `except OSError` (raises `StoreError(path, exc.strerror or str(exc))`). The decode/parse handlers and their reason strings are unchanged, and nothing else in `storage.py` changed. Checked by hand on 3.14 (parent chmod 000 now exits 1 instead of printing `No tasks.`) and covered by the new tests. On 3.10-3.12 the same `PermissionError` now comes from `read_bytes()` and is wrapped in the same way. I could not run those versions here, but the code path does not depend on the version.
- suggested fix: none.

### C2 — NON-BLOCKING — A1 cannot be verified in this environment (user must check it)
- category: spec
- where: pyproject.toml (A1 / R22)
- problem: `pip install -e ".[test]"` in a fresh venv and the installed `todo --help` cannot be run here (no pip, no ensurepip, no `python`). The orchestrator is handing this to the user, so it is not blocking. All partial checks passed (see A1).
- suggested fix: the user runs the commands listed under A1 on a machine with pip.

### C3 — RESOLVED (was BLOCKING) — T2 round 1 agent warning (OSError deviation reachable from `load`)
- category: agent-warning
- where: todo/cli.py:92-93
- problem: resolved by C1. `load` can no longer raise `OSError`, so `cannot write store file` can only come from `storage.save`. The `test_unreadable_store_fails_every_command` test asserts that `"cannot write"` is not in stderr for all four commands, and my manual runs agree. All round 2 reports have *Notes / blockers*: none. Stdout write failures are buffered and surface only at interpreter exit, not inside the `try` (checked with `>/dev/full`), so the CLAUDE.md statement that this branch is "only reachable from `storage.save`" holds in practice.
- suggested fix: none.

### C4 — NON-BLOCKING — Atomic save resets file mode to 0600 and replaces symlinks
- category: correctness
- where: todo/storage.py:112-132
- problem: unchanged from round 1. `mkstemp` creates the temp file as 0600 and `os.replace` replaces the store, so a 0644 store becomes 0600 and a symlinked store is replaced by a regular file. This is not documented.
- suggested fix: either document it, or copy the existing mode and resolve symlinks before saving. Ask the user which behaviour they want.

### C5 — NON-BLOCKING — README says a missing `--file` parent folder makes "the command" fail
- category: style
- where: README.md:59 (and CLAUDE.md:36)
- problem: unchanged. Only `add` fails (`cannot write store file`, exit 1). `list` prints `No tasks.` and exits 0, and `done`/`remove` fail with `no task with id N`. Checked by hand again this round.
- suggested fix: reword to "`add` fails with an error and the folder is not created".

### C6 — NON-BLOCKING — Some code in cli.py does nothing
- category: maintainability
- where: todo/cli.py:90-91, todo/cli.py:74
- problem: unchanged. The `except storage.InvalidTaskTextError` branch cannot run because of the pre-check at lines 58-61, and the `sorted(...)` repeats the sort `load()` already does.
- suggested fix: drop the branch or add a comment that it is a safety net. The extra sort is harmless.

### C7 — NON-BLOCKING — Minor test weaknesses
- category: tests
- where: tests/test_cli.py:36, tests/test_cli.py:136-138, tests/test_storage.py:143-155
- problem: the unused first `run(...)` in `test_add_multi_word_joined` is still there. `test_file_option_before_subcommand` still only checks that the file exists. The "nothing tests the unreadable store" part of round 1 is now resolved. New minor point: `test_load_inaccessible_parent_raises_store_error` does not assert that the path appears in the error message, though the CLI test for the same scenario does.
- suggested fix: remove or assert the unused call, assert the content in the `--file` test, and optionally assert `str(f) in str(exc.value)` in the parent test.

### C8 — NON-BLOCKING — Test-run artifacts are untracked in the repo
- category: scope
- where: tests/__pycache__/, todo/__pycache__/, .pytest_cache/
- problem: unchanged. The bytecode caches from test runs show up as untracked in `git status`, because the user chose to have no `.gitignore`. I did not delete them.
- suggested fix: the user should not commit them. Delete them (`find . -name __pycache__ -prune -exec rm -rf {} +`) or reconsider the `.gitignore` decision.
