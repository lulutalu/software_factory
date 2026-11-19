"""Task model and JSON storage for the todo app.

Pure logic: no argparse, no printing. Errors are raised as exceptions.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Task:
    """A single todo item."""

    id: int
    text: str
    done: bool = False


@dataclass
class TodoList:
    """All tasks plus the next ID to assign (IDs are never reused)."""

    next_id: int = 1
    tasks: list[Task] = field(default_factory=list)


class StoreError(Exception):
    """Store file unreadable / invalid JSON / wrong structure."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"invalid store file '{path}': {reason}")


class InvalidTaskTextError(ValueError):
    """Task text empty or whitespace-only."""


class TaskNotFoundError(LookupError):
    """No task with the given ID."""

    def __init__(self, task_id: int):
        self.task_id = task_id
        super().__init__(f"task {task_id} not found")


def default_store_path() -> Path:
    """Return ~/.todo.json, evaluated at call time."""
    return Path("~/.todo.json").expanduser()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load(path: Path) -> TodoList:
    """Load the store.

    A missing file (FileNotFoundError) yields an empty list, nothing created;
    any other read error raises StoreError.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return TodoList()
    except OSError as exc:
        raise StoreError(path, exc.strerror or str(exc)) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise StoreError(path, f"file is not valid UTF-8 ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise StoreError(path, f"invalid JSON ({exc})") from exc
    except RecursionError as exc:
        raise StoreError(path, "JSON is nested too deeply") from exc

    if not isinstance(data, dict):
        raise StoreError(path, "top-level value must be an object")
    if "next_id" not in data:
        raise StoreError(path, "missing 'next_id'")
    if not _is_int(data["next_id"]):
        raise StoreError(path, "'next_id' must be an integer")
    if "tasks" not in data:
        raise StoreError(path, "missing 'tasks'")
    if not isinstance(data["tasks"], list):
        raise StoreError(path, "'tasks' must be a list")

    tasks = []
    for index, entry in enumerate(data["tasks"]):
        if not isinstance(entry, dict):
            raise StoreError(path, f"task entry {index} must be an object")
        for key in ("id", "text", "done"):
            if key not in entry:
                raise StoreError(path, f"task entry {index} is missing '{key}'")
        if not _is_int(entry["id"]):
            raise StoreError(path, f"task entry {index}: 'id' must be an integer")
        if not isinstance(entry["text"], str):
            raise StoreError(path, f"task entry {index}: 'text' must be a string")
        if not isinstance(entry["done"], bool):
            raise StoreError(path, f"task entry {index}: 'done' must be a boolean")
        tasks.append(Task(id=entry["id"], text=entry["text"], done=entry["done"]))

    tasks.sort(key=lambda t: t.id)
    return TodoList(next_id=data["next_id"], tasks=tasks)


def save(todo: TodoList, path: Path) -> None:
    """Atomically write the store as UTF-8 JSON. OSError propagates."""
    path = Path(path)
    payload = {
        "next_id": todo.next_id,
        "tasks": [{"id": t.id, "text": t.text, "done": t.done} for t in todo.tasks],
    }
    content = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add_task(todo: TodoList, text: str) -> Task:
    """Append a new task (text stored verbatim) and bump next_id."""
    if not text.strip():
        raise InvalidTaskTextError("task text must not be empty")
    task = Task(id=todo.next_id, text=text, done=False)
    todo.tasks.append(task)
    todo.next_id += 1
    return task


def _find(todo: TodoList, task_id: int) -> Task:
    for task in todo.tasks:
        if task.id == task_id:
            return task
    raise TaskNotFoundError(task_id)


def mark_done(todo: TodoList, task_id: int) -> bool:
    """Mark a task done. Return False if it already was."""
    task = _find(todo, task_id)
    if task.done:
        return False
    task.done = True
    return True


def remove_task(todo: TodoList, task_id: int) -> Task:
    """Remove and return a task; next_id is left unchanged."""
    task = _find(todo, task_id)
    todo.tasks.remove(task)
    return task
