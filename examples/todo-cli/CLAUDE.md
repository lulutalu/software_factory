# CLAUDE.md

Python CLI todo app (`add`, `list`, `done`, `remove`) storing tasks in a JSON file. See `README.md` for user docs.

## Architecture

```
todo/__init__.py   package marker
todo/__main__.py   enables `python -m todo`
todo/cli.py        argparse, stdout/stderr output, exit codes
todo/storage.py    Task/TodoList dataclasses, load/save, add_task/mark_done/remove_task, exceptions
tests/             pytest suite (conftest.py, test_storage.py, test_cli.py)
pyproject.toml     packaging, `todo` console script, `test` extra
```

Split: `storage.py` is pure logic. It does no printing and no argument parsing, and reports problems by raising exceptions (`StoreError`, `TaskNotFoundError`, `InvalidTaskTextError`). `cli.py` handles argparse, all terminal output and exit codes, and translates storage exceptions into messages.

## Conventions

- Standard library only at runtime. `pytest` is only in the `test` extra.
- Errors go to stderr as `todo: error: ...`. Argparse usage errors exit 2, other errors exit 1. Expected errors never show a traceback.
- Saves are atomic (temp file in the same directory, fsync, `os.replace`).
- Tests never touch `~/.todo.json`: an autouse fixture in `tests/conftest.py` points `HOME` at a temp dir, and tests use `--file` / `tmp_path`.
- No `.gitignore` in the repo (deliberate decision).
- The CLI's `except OSError` ("cannot write store file") is only reachable from `storage.save`, because `load` wraps every read error in `StoreError`.
- Do not commit unless the user asks.

## Decisions

- **Store format (R14)**: UTF-8 JSON object `{"next_id": int, "tasks": [{"id": int, "text": str, "done": bool}]}`.
- **ID policy (R15)**: `next_id` is persisted; the first ID is 1 and IDs are never reused, even after removing the highest ID.
- **Already done (R10)**: `done` on a done task is a success (exit 0) with a note and no write.
- **Corrupt store (R17)**: an invalid JSON or wrong-structure store fails every command, names the file in the error, never modifies the file, and is never auto-repaired. A missing file is an empty list; `list` does not create it. An existing store that cannot be read (PermissionError, IsADirectoryError, NotADirectoryError or any other `OSError` except `FileNotFoundError`) also raises `StoreError`, and therefore fails every command with exit 1. Only `FileNotFoundError` counts as a missing store. `load()` deliberately does not pre-check with `Path.exists()`, because on Python 3.13+ that check hides permission errors (review finding C1).
- **Text (R6/R7)**: words are joined with a single space and stored verbatim (no trimming). Empty or whitespace-only text is rejected before the store is loaded or touched.
- Unknown extra JSON keys are ignored on load, so they are dropped on the next save.
- `--file` with a nonexistent parent folder gives an error (exit 1); the folder is not created.

## Out of scope

Editing task text, extra metadata (priorities, due dates, tags), undone/clear/bulk commands, filtering or sorting `list`, env var or config file for the store path, corrupt-store recovery, concurrency/locking, colour or TUI, third-party runtime dependencies, PyPI/CI.
