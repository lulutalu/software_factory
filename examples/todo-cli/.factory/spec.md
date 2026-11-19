# Spec: Python CLI todo app with JSON storage

## 1. Goal

Build a small command-line todo manager in Python. It has four subcommands: `add`, `list`, `done` and `remove`. Tasks are saved in a JSON file (default `~/.todo.json`, overridable with `--file PATH`), so they persist between runs. The app is a `todo` package that uses only the Python standard library at runtime. It can be run as `python -m todo` or installed as a `todo` console command. It ships with pytest unit tests for each command and for the storage layer, plus a `README.md` and a project `CLAUDE.md`. The aim is a self-contained, testable tool for managing a personal task list from the terminal.

## 2. Context

- **Repository state**: `<project>` is an empty git repository (no commits). It contains only the `.factory/` pipeline directory. There is no existing code, `README.md` or project `CLAUDE.md`. Everything is created from scratch.
- **Stack (decided)**:
  - Python 3.10 or newer.
  - Runtime: standard library only (for example `argparse`, `json`, `pathlib`). No third-party runtime dependencies.
  - Tests: `pytest`, as a test/dev-only dependency declared as an optional extra (`[project.optional-dependencies] test = ["pytest"]`) in `pyproject.toml`.
  - Packaging: a `todo` package with a `pyproject.toml`. It is runnable as `python -m todo` and declares a `todo` console script.
- **Global conventions that apply** (from the user's global instructions):
  - Do not commit. Builders leave changes uncommitted and suggest a commit message.
  - Keep documentation up to date. User docs go in `README.md` and docs for future Claude sessions go in `CLAUDE.md`, both at the repository root.
  - Do not assume. Anything not settled by this spec should be raised, not silently decided.
- **Notation**: in this spec, `todo ...` means the installed console command. Every example must behave the same way when run as `python -m todo ...`. "The store" means the JSON file in use: `~/.todo.json` by default, or the path given with `--file`.

## 3. Requirements

**Packaging and runtime**

- **R1**: The repository root contains a `pyproject.toml` that declares:
  - a project that provides the `todo` package;
  - `requires-python = ">=3.10"`;
  - no runtime dependencies (empty or absent `dependencies`);
  - an optional dependency group `test` containing `pytest`;
  - a console script entry point named `todo` that runs the CLI.
- **R2**: The `todo` package has a `__main__.py`, so `python -m todo <args>` runs the CLI with the same behaviour as the `todo` command.
- **R3**: The package source (not the tests) imports only standard library modules and modules from the `todo` package itself.

**CLI**

- **R4**: The CLI has exactly four subcommands: `add`, `list`, `done` and `remove`. Argument parsing uses `argparse`.
- **R5**: The CLI accepts a `--file PATH` option that selects the store file. Without it, the store is `~/.todo.json`, with `~` expanded to the current user's home directory. The option must work when placed before the subcommand (for example `todo --file /tmp/t.json list`).
- **R6**: `todo add <text...>` accepts one or more words. The task text is all the positional words joined with a single space (so `todo add Buy milk` and `todo add "Buy milk"` both store `Buy milk`). It creates a new task with that text and `done = false`, saves it to the store, prints a confirmation to stdout that includes the new task's ID, and exits with code 0.
- **R7**: If the resulting text for `add` is empty or contains only whitespace (for example `todo add ""` or `todo add "   "`), the app prints an error to stderr, exits with a non-zero code, and does not create or modify the store.
- **R8**: `todo list` prints every task (done and not done) to stdout in ascending ID order, one per line, in exactly this format:
  - not done: `<id>. [ ] <text>` (for example `1. [ ] Buy milk`);
  - done: `<id>. [x] <text>` (for example `2. [x] Pay rent`).
  If there are no tasks, it prints a clear message (for example `No tasks.`) and exits with code 0.
- **R9**: `todo done <id>` marks the task with that ID as done, saves the change, prints a confirmation to stdout and exits with code 0.
- **R10**: `todo done <id>` on a task that is already done is a no-op success. It prints a note saying the task was already done, exits with code 0, and leaves the store content unchanged.
- **R11**: `todo remove <id>` deletes the task with that ID from the store, prints a confirmation to stdout and exits with code 0.
- **R12**: If `done` or `remove` gets an ID that does not exist (including an ID that was removed earlier), or an argument that is not a valid integer ID, the app prints an error to stderr, exits with a non-zero code and leaves the store unchanged.
- **R13**: Running with no subcommand, an unknown subcommand, or missing required arguments (`todo add` with no words, `todo done` or `todo remove` with no ID) prints usage/help text and exits with a non-zero code.

**Storage**

- **R14**: The store is a single UTF-8 JSON file. Its top-level value is an object with:
  - `next_id`: an integer, the ID the next added task will get;
  - `tasks`: a list of task objects, each with `id` (integer), `text` (string) and `done` (boolean).
  (This structure is derived from R15: a persisted counter is needed so that IDs are never reused after removal.)
- **R15**: IDs are stable, auto-incrementing integers. The first task ever added to a new store gets ID 1. Each new task gets the current `next_id`, and `next_id` then goes up by 1. IDs are never reused: removing a task, including the one with the highest ID, does not cause its ID to be given to a later task. Existing tasks keep their IDs when other tasks are removed.
- **R16**: If the store file does not exist, the app treats it as an empty task list with `next_id = 1`. `list` succeeds with the empty message without creating the file, and `add` creates the file.
- **R17**: If the store file exists but is not valid JSON, or does not match the structure in R14 (for example the top level is not an object, `next_id` or `tasks` is missing or has the wrong type, or a task is missing `id`/`text`/`done` or has a wrong type), every command fails. It prints a clear error to stderr that names the file, exits with a non-zero code, and does not modify the file. No Python traceback is shown.
- **R18**: After any successful modifying command (`add`, `done` on a not-done task, `remove`), the store contains valid JSON in the R14 structure that reflects the change, and running `list` again in a new process shows it.
- **R19**: The storage and task logic (load, save, add, mark done, remove) lives in code separate from argument parsing and output, so it can be imported and unit-tested without starting a subprocess or calling the CLI parser.

**Tests**

- **R20**: The project has pytest unit tests in a `tests/` directory at the repository root. They cover:
  - each of `add`, `list`, `done` and `remove` on the success path;
  - the error paths in R7, R12 and R13;
  - the already-done no-op in R10;
  - the `list` output format in R8, including both `[ ]` and `[x]` lines and the empty message;
  - multi-word joining in R6;
  - the missing-file case in R16;
  - the corrupt/invalid-file cases in R17 (at least one invalid-JSON case and one wrong-structure case), including a check that the file is unchanged;
  - ID non-reuse after removal in R15, including removing the highest-ID task and then adding;
  - persistence across a save/load round trip (R18);
  - the `--file` option in R5.
- **R21**: Tests never read or write the real `~/.todo.json`. Every test uses a temporary file or directory (for example pytest's `tmp_path`), passed through `--file` or directly to the storage code. Tests that would otherwise use the default path redirect it (for example by setting `HOME` to a temporary directory).
- **R22**: After `pip install -e ".[test]"`, the full suite runs with `python -m pytest` from the repository root and passes.

**Documentation**

- **R23**: `README.md` at the repository root documents:
  - requirements (Python 3.10+, no runtime dependencies);
  - installation (including `pip install .` / `pip install -e ".[test]"`);
  - usage of each subcommand, with examples, the `list` output format and the `--file` option / default store location;
  - how to run the tests.
- **R24**: `CLAUDE.md` at the repository root documents for future Claude sessions:
  - the architecture (package layout and the split between storage logic and CLI);
  - conventions (standard library only at runtime, pytest for tests, errors to stderr with non-zero exit, tests never touching `~/.todo.json`);
  - the decisions recorded in this spec (store format from R14, ID policy from R15, already-done behaviour from R10, corrupt-file behaviour from R17, text validation and joining from R6/R7).

## 4. Acceptance criteria

Unless a check says otherwise, CLI checks use `--file <tmp>/todo.json`, where `<tmp>` is a fresh empty temporary directory.

- **A1**: In a fresh virtual environment with Python 3.10 or newer, `pip install -e ".[test]"` succeeds. After that, `todo --help` and `python -m todo --help` both print usage and exit with code 0. `pyproject.toml` lists no runtime dependencies and has `pytest` only under the `test` extra (R1, R2).
- **A2**: A search of the package source for imports finds only standard library modules and `todo` modules (R3).
- **A3**: `todo list` with no store file present prints the empty-list message, exits with code 0, and does not create the file (R8, R16).
- **A4**: `todo add Buy milk` exits with code 0 and prints a confirmation containing `1`. The store now exists and parses as JSON equal to `{"next_id": 2, "tasks": [{"id": 1, "text": "Buy milk", "done": false}]}` (key order and whitespace aside) (R6, R14, R15, R16, R18).
- **A5**: `todo add "Pay rent"` adds a task with text `Pay rent` and ID 2. `todo add "  "` and `todo add ""` each exit with a non-zero code, print an error to stderr, and leave the store byte-for-byte unchanged (R6, R7).
- **A6**: After A4 and A5, `todo done 2` exits with code 0. `todo list` then prints exactly these two lines:
  ```
  1. [ ] Buy milk
  2. [x] Pay rent
  ```
  (R8, R9, R18)
- **A7**: Running `todo done 2` again exits with code 0, prints a note that the task was already done, and leaves the store byte-for-byte unchanged (R10).
- **A8**: `todo remove 2` exits with code 0, and task 2 no longer appears in `todo list` or in the store, while task 1 is unchanged. A following `todo add Walk dog` gets ID 3, not 2 (R11, R15, R18).
- **A9**: `todo done 999`, `todo remove 999`, `todo remove 2` (already removed) and `todo done abc` each exit with a non-zero code, write an error to stderr, and leave the store byte-for-byte unchanged (R12).
- **A10**: `todo` with no arguments, `todo frobnicate`, `todo add`, `todo done` and `todo remove` (no ID) each print usage/help and exit with a non-zero code (R13).
- **A11**: Write `not json{` to the store, then run `todo list`, `todo add x`, `todo done 1` and `todo remove 1`. Each exits with a non-zero code, prints an error to stderr that names the file and contains no traceback, and the file still contains exactly `not json{`. Repeat with valid JSON of the wrong structure (for example `[]` and `{"tasks": "oops"}`) and get the same result (R17).
- **A12**: With `HOME` set to a temporary directory and no `--file` option, `todo add Test` creates `$HOME/.todo.json`, and `todo list` reads it (R5).
- **A13**: Inspection shows the storage/task functions or classes can be imported and called directly without the CLI parser, and at least one unit test does so (R19).
- **A14**: `python -m pytest` from the repository root runs and all tests pass. Reading the tests shows that each item listed in R20 is covered (R20, R22).
- **A15**: Record whether `~/.todo.json` exists and, if it does, its modification time and contents. Run `python -m pytest`. The file is not created, modified or deleted (R21).
- **A16**: `README.md` and `CLAUDE.md` exist at the repository root and contain the items listed in R23 and R24. The commands shown in `README.md` work as documented (R23, R24).

## 5. Out of scope

- Editing a task's text after it is created.
- Priorities, due dates, tags, projects, timestamps or any other task metadata beyond `id`, `text` and `done`.
- Un-marking a task (an "undone" command), clearing or bulk operations, and passing several IDs in one call.
- Filtering, hiding completed tasks, search or sorting options for `list`.
- Choosing the store through an environment variable or config file (only `--file` is supported).
- Recovering from a corrupt store (backups, auto-repair, starting fresh).
- Concurrency and file locking for simultaneous runs.
- Colour or other rich terminal output, interactive/TUI modes, shell completion.
- Third-party runtime dependencies.
- Publishing to PyPI, CI configuration and git commits.

## 6. Open questions

None
