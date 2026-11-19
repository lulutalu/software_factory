# todo

A small command-line todo app. Tasks are stored in a JSON file, so they persist between runs.

## Requirements

- Python 3.10 or newer
- No runtime dependencies (standard library only)

## Installation

```
pip install .
```

For development (adds `pytest`):

```
pip install -e ".[test]"
```

## Usage

The installed `todo` command and `python -m todo` behave identically.

```
todo add Buy milk        # Added task 1: Buy milk
todo add "Pay rent"      # Added task 2: Pay rent
todo list
todo done 2              # Marked task 2 as done.
todo remove 1            # Removed task 1: Buy milk
python -m todo list      # same as `todo list`
```

### Subcommands

- `todo add TEXT...` adds a task. All words are joined with a single space, so `todo add Buy milk` and `todo add "Buy milk"` store the same text. The text is stored exactly as typed (no trimming). Empty or whitespace-only text is rejected and the store is not touched.
- `todo list` prints all tasks in ascending ID order. See the format below.
- `todo done ID` marks a task as done. If it is already done, it prints `Task ID is already done.`, exits 0 and does not modify the file.
- `todo remove ID` deletes a task. IDs are never reused: after removing the task with the highest ID, the next added task still gets a new, higher ID.

### `list` format

```
1. [ ] Buy milk
2. [x] Pay rent
```

`[ ]` means not done, `[x]` means done. With no tasks it prints `No tasks.`

### Store file

By default tasks are stored in `~/.todo.json`. Use `--file PATH` to choose another file. The option goes before the subcommand:

```
todo --file /tmp/t.json list
```

If the file does not exist it is treated as an empty list (`list` does not create it, `add` does). If the parent folder of `--file PATH` does not exist, the command fails with an error and the folder is not created.

The file is JSON of the form `{"next_id": 3, "tasks": [{"id": 1, "text": "Buy milk", "done": false}]}`. Unknown extra keys are ignored when loading, so they are dropped the next time the file is saved.

If the file exists but cannot be read (for example permission denied, or the path is a directory), is not valid JSON, or has the wrong structure, every command fails with an error naming the file. The file is never modified or repaired.

### Exit codes and errors

- `0`: success (including `done` on an already-done task).
- `1`: any other error, for example an unknown task ID, empty `add` text, a corrupt or unreadable store file, or a store that cannot be written. The message goes to stderr as `todo: error: ...`, with no traceback.
- `2`: usage errors from argparse (no subcommand, unknown subcommand, missing arguments, a non-integer ID such as `todo done abc`). Usage text goes to stderr.

## Running tests

```
python -m pytest
```

Run it from the repository root (after `pip install -e ".[test]"`). The tests never touch your real `~/.todo.json`: they use temporary directories and redirect `HOME`.
