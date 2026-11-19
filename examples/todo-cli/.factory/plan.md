# Plan (round 2)

## Approach
This fix round covers only the BLOCKING findings from `.factory/review-code.md`. The security review approved the code, and no NON-BLOCKING finding (C4-C8, S1-S5) is planned.

- **C1** (fixed in T1): `todo/storage.py` `load()` currently checks `path.exists()` before reading. On Python 3.13+ that check returns False for an existing store it cannot access, so the command wrongly shows `No tasks.`. On Python 3.10-3.12 it raises `PermissionError`, which the CLI reports as "cannot write". The fix removes the pre-check and reads inside the `try`. Only `FileNotFoundError` means "missing store" (an empty `TodoList()`, nothing created). Every other `OSError` becomes `StoreError`, so the CLI's existing `except storage.StoreError` prints `todo: error: invalid store file '<path>': <strerror>` and returns 1. No other part of the storage contract from round 1 changes.
- **C3**: fixing C1 resolves this. After the fix, `load()` never lets an `OSError` escape, so the CLI's `except OSError` ("cannot write store file") can only be reached from `storage.save`. That makes its wording accurate. `todo/cli.py` does **not** change in this round.
- **Documented behaviour changes** (handled in T3 so the docs stay accurate):
  - An existing store that cannot be read now fails every command with exit 1 and an error naming the file. Before, it could look empty.
  - A store path whose parent component is a regular file (for example `--file somefile/t.json`) now fails with `NotADirectoryError` turned into `StoreError`. Before, it was treated as empty.
  - A missing parent directory still raises `FileNotFoundError`, so it is still treated as an empty list. `list` still prints `No tasks.` and `add` still fails on write. That behaviour is unchanged.
- **C2** (environment limitation, no task planned): A1 needs `pip install -e ".[test]"` in a fresh venv, then `todo --help`. This environment has no pip, no ensurepip and no `python` command. The specialists cannot fix that, and no code change is needed: the reviewer's partial checks of the wheel build, metadata, entry point and emulated console script all passed. **The orchestrator must hand this check to the user**, who should run: `python3 -m venv .venv && .venv/bin/pip install -e ".[test]" && .venv/bin/todo --help && .venv/bin/python -m todo --help && .venv/bin/python -m pytest`.

## Tasks

### T1 — Fix load() so that an inaccessible store raises StoreError
- specialist: data
- wave: 1
- files: todo/storage.py
- covers: C1, C3
- instructions: Edit only `load()` in `todo/storage.py`. Keep every other function, name, signature and message string unchanged.
  - Delete the `if not path.exists(): return TodoList()` pre-check (currently lines 63-64).
  - Read the file inside the existing `try` block. Put the `FileNotFoundError` handler **before** the general `OSError` handler, because `FileNotFoundError` is a subclass of `OSError`:
    ```python
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return TodoList()
    except OSError as exc:
        raise StoreError(path, exc.strerror or str(exc)) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc: ...   # keep the existing handlers and reason strings
    except json.JSONDecodeError as exc: ...
    except RecursionError as exc: ...
    ```
    A single `try` with `except FileNotFoundError` listed first is also acceptable. Either way, `UnicodeDecodeError`, `json.JSONDecodeError` and `RecursionError` keep their current reason strings.
  - Required behaviour after the change:
    - a missing file, including a missing parent directory, returns `TodoList()` and creates nothing;
    - `PermissionError` (an unreadable file, or a parent directory that is not searchable), `IsADirectoryError` (the path is a directory), `NotADirectoryError` (a parent component is a regular file) and any other `OSError` raise `StoreError`, and `str(exc)` contains the path;
    - nothing is ever written during `load`.
  - Update the `load()` docstring to say: "missing file (FileNotFoundError) yields an empty list, nothing created; any other read error raises StoreError."
  - Do not touch `todo/cli.py`. Fixing load makes its `except OSError` reachable only from `save`, which resolves C3. Do not write tests (T2 owns them) or docs (T3 owns them).
  - Before reporting, run `python3 -m pytest -q` from the repo root. All 53 existing tests must still pass.

### T2 — Regression tests for unreadable or inaccessible stores
- specialist: tests
- wave: 2
- files: tests/test_storage.py, tests/test_cli.py
- covers: C1, C3, A11, A14, A15
- instructions: Add tests to the existing files. Do not change the existing tests. Use the existing fixtures from `tests/conftest.py`: `store` (`tmp_path / "todo.json"`, which does not exist yet), `run` (returns `(code, out, err)`) and the autouse `fake_home`. Never touch the real `~/.todo.json`.
  - **Permission helper / skip rule**: tests that rely on `chmod` must be skipped when `not hasattr(os, "geteuid") or os.geteuid() == 0`, because root ignores permission bits and non-POSIX systems behave differently. Use `pytest.mark.skipif(..., reason="needs a non-root POSIX user")`. Restore permissions in a `try/finally` (or a fixture finalizer) so that `tmp_path` cleanup still works: set mode 0o700 on directories and 0o600 on files.
  - **tests/test_storage.py**: add these tests (import `os` as needed).
    1. `test_load_unreadable_file_raises_store_error`: write a valid store (for example via `storage.save` of a list with one task), `chmod 0o000` the file, and assert that `storage.load(store)` raises `StoreError` whose `str()` contains `str(store)`. After restoring permissions, assert the bytes are unchanged. (skipif root)
    2. `test_load_inaccessible_parent_raises_store_error`: create `d = tmp_path / "locked"`, save a valid store at `d / "todo.json"`, `chmod 0o000` on `d`, and assert that `load` raises `StoreError` and does **not** return an empty list. Restore the mode, then check the file is unchanged. (skipif root) This is the exact C1 scenario.
    3. `test_load_directory_path_raises_store_error`: `store.mkdir()`, and assert that `storage.load(store)` raises `StoreError` containing the path. No skip is needed.
    4. `test_load_parent_is_file_raises_store_error`: write any file `f = tmp_path / "plain"`, and assert that `storage.load(f / "todo.json")` raises `StoreError`. No skip is needed.
    5. `test_load_permission_error_without_chmod`: this one runs even as root. Use `monkeypatch` to replace `pathlib.Path.read_bytes` with a function that raises `PermissionError(13, "Permission denied")`. Write a valid store first so that the file really exists. Assert that `load` raises `StoreError` and that the message contains `Permission denied` and the path.
    6. `test_load_missing_parent_dir_is_empty`: `storage.load(tmp_path / "nope" / "todo.json")` returns an empty `TodoList` (`next_id == 1`, no tasks), and the directory is not created.
  - **tests/test_cli.py**: add one test, `test_unreadable_store_fails_every_command`, parametrized over `["list"]`, `["add", "x"]`, `["done", "1"]` and `["remove", "1"]` (skipif root). Save a valid store containing task 1 in `d = tmp_path / "locked"`, then `chmod 0o000` on `d`. Run `run(["--file", str(d / "todo.json"), *argv])` and assert:
    - the exit code is 1;
    - `str(d / "todo.json")` is in stderr;
    - `"Traceback"` is not in stderr;
    - `"cannot write"` is not in stderr (C3);
    - `"No tasks."` is not in stdout.
    Restore the mode in `finally` and assert the file bytes are unchanged.
  - Run the full suite with `python3 -m pytest -q` from the repo root and report the counts, including how many tests were skipped and why. Before and after the run, record whether the real `~/.todo.json` exists and its mtime, using `ls`/`stat` only. Do not read its contents. Report that it was untouched (A15).
  - If a test exposes a bug in `todo/`, report it. Do not edit files outside your list.

### T3 — Keep README.md and CLAUDE.md in sync with the new load behaviour
- specialist: backend
- wave: 2
- files: README.md, CLAUDE.md
- covers: C1
- instructions: Make minimal wording changes only. Read the updated `todo/storage.py` first and match its real behaviour. Do not rewrite other sections, and do not address NON-BLOCKING findings (C4, C5 and so on are out of scope for this round).
  - **README.md**, section "Store file":
    - Change the paragraph that begins "If the file exists but is not valid JSON or has the wrong structure..." so that it also covers unreadable stores. Suggested text: "If the file exists but cannot be read (for example permission denied, or the path is a directory), is not valid JSON, or has the wrong structure, every command fails with an error naming the file. The file is never modified or repaired."
    - In "Exit codes and errors", change "a corrupt store file" to "a corrupt or unreadable store file".
    - Leave the missing-parent-folder sentence unchanged. A missing parent is still treated as a missing file.
  - **CLAUDE.md**, section "Decisions":
    - Extend the **Corrupt store (R17)** bullet with these points:
      - an existing store that cannot be read (PermissionError, IsADirectoryError, NotADirectoryError or any other `OSError` except `FileNotFoundError`) also raises `StoreError`, and therefore fails every command with exit 1;
      - only `FileNotFoundError` counts as a missing store, which is an empty list;
      - `load()` deliberately does not pre-check with `Path.exists()`, because on Python 3.13+ that check hides permission errors (review finding C1).
    - Add one line to Conventions: the CLI's `except OSError` ("cannot write store file") is only reachable from `storage.save`, because `load` wraps every read error in `StoreError`.
  - Check that every README statement you touch matches real behaviour. You may use `chmod` on a temp directory plus `python3 -m todo --file <tmp>/locked/todo.json list` (skip this if running as root). Never touch the real `~/.todo.json`.

## Not planned (environment limitation)
- **C2 / A1**: no task, because the specialists cannot fix it. The orchestrator must report to the user that A1 needs manual verification on a machine with pip. The commands are in the Approach section.

## Summary
3 tasks in 2 waves.
- Wave 1: T1 (data: the `load()` fix in `todo/storage.py`).
- Wave 2: T2 (tests: regression tests for unreadable, inaccessible, directory and parent-is-file stores, then running the suite) and T3 (backend: minimal README.md and CLAUDE.md updates). These run in parallel and own different files.

Specialists involved: data, tests and backend. `todo/cli.py` is unchanged. C2 is passed to the user as an environment limitation.
