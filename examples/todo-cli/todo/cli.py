"""Command-line interface for the todo app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from todo import storage


def _task_id(value: str) -> int:
    """argparse type: convert a task id argument to int."""
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid task id: {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A simple todo list stored in a JSON file.",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=None,
        help="path of the JSON store file (default: ~/.todo.json)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p_add = sub.add_parser("add", help="add a new task")
    p_add.add_argument("text", nargs="+", help="task description")

    sub.add_parser("list", help="list all tasks")

    p_done = sub.add_parser("done", help="mark a task as done")
    p_done.add_argument("id", type=_task_id, help="task id")

    p_rm = sub.add_parser("remove", help="remove a task")
    p_rm.add_argument("id", type=_task_id, help="task id")
    return parser


def _err(message: str) -> int:
    print(f"todo: error: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = build_parser().parse_args(argv)
    path = Path(args.file) if args.file is not None else storage.default_store_path()

    text = None
    if args.command == "add":
        text = " ".join(args.text)
        if not text.strip():
            return _err("task text must not be empty")

    try:
        todo_list = storage.load(path)

        if args.command == "add":
            task = storage.add_task(todo_list, text)
            storage.save(todo_list, path)
            print(f"Added task {task.id}: {task.text}")
        elif args.command == "list":
            if not todo_list.tasks:
                print("No tasks.")
            else:
                for t in sorted(todo_list.tasks, key=lambda t: t.id):
                    print(f"{t.id}. [{'x' if t.done else ' '}] {t.text}")
        elif args.command == "done":
            if storage.mark_done(todo_list, args.id):
                storage.save(todo_list, path)
                print(f"Marked task {args.id} as done.")
            else:
                print(f"Task {args.id} is already done.")
        elif args.command == "remove":
            task = storage.remove_task(todo_list, args.id)
            storage.save(todo_list, path)
            print(f"Removed task {task.id}: {task.text}")
    except storage.StoreError as exc:
        return _err(str(exc))
    except storage.TaskNotFoundError as exc:
        return _err(f"no task with id {exc.task_id}")
    except storage.InvalidTaskTextError:
        return _err("task text must not be empty")
    except OSError as exc:
        return _err(f"cannot write store file '{path}': {exc.strerror or exc}")
    return 0
