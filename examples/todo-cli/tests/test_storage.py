"""Tests for todo.storage (no CLI parser involved)."""

import json
import os
import pathlib

import pytest

from todo import storage
from todo.storage import (
    InvalidTaskTextError,
    StoreError,
    TaskNotFoundError,
    TodoList,
)


def test_load_missing_file_is_empty_and_not_created(store):  # A3
    todo = storage.load(store)
    assert todo.tasks == []
    assert todo.next_id == 1
    assert not store.exists()


def test_add_task_assigns_incrementing_ids():  # A4
    todo = TodoList()
    t1 = storage.add_task(todo, "a")
    t2 = storage.add_task(todo, "b")
    assert (t1.id, t2.id) == (1, 2)
    assert todo.next_id == 3
    assert [t.text for t in todo.tasks] == ["a", "b"]


@pytest.mark.parametrize("text", ["", "   "])
def test_add_task_rejects_blank(text):  # A5
    todo = TodoList()
    with pytest.raises(InvalidTaskTextError):
        storage.add_task(todo, text)
    assert todo.tasks == []
    assert todo.next_id == 1


def test_mark_done_true_then_false():  # A7
    todo = TodoList()
    storage.add_task(todo, "a")
    assert storage.mark_done(todo, 1) is True
    assert storage.mark_done(todo, 1) is False
    assert todo.tasks[0].done is True


def test_unknown_id_raises():  # A9
    todo = TodoList()
    storage.add_task(todo, "a")
    with pytest.raises(TaskNotFoundError):
        storage.mark_done(todo, 99)
    with pytest.raises(TaskNotFoundError):
        storage.remove_task(todo, 99)


def test_ids_not_reused_after_removing_highest():  # R15
    todo = TodoList()
    storage.add_task(todo, "a")
    storage.add_task(todo, "b")
    storage.remove_task(todo, 2)
    t = storage.add_task(todo, "c")
    assert t.id == 3


def test_save_load_round_trip_and_exact_format(store):  # R14, R18
    todo = TodoList()
    storage.add_task(todo, "Buy milk")
    storage.add_task(todo, "Pay rent")
    storage.mark_done(todo, 2)
    storage.save(todo, store)
    assert storage.load(store) == todo
    assert json.loads(store.read_text(encoding="utf-8")) == {
        "next_id": 3,
        "tasks": [
            {"id": 1, "text": "Buy milk", "done": False},
            {"id": 2, "text": "Pay rent", "done": True},
        ],
    }


CORRUPT = [
    pytest.param(b"not json{", id="bad-json"),
    pytest.param(b"[]", id="top-level-list"),
    pytest.param(b'{"tasks": "oops"}', id="tasks-not-list"),
    pytest.param(b'{"tasks": []}', id="missing-next-id"),
    pytest.param(b'{"next_id": true, "tasks": []}', id="next-id-bool"),
    pytest.param(
        b'{"next_id": 2, "tasks": [{"id": 1, "text": "a"}]}', id="task-missing-done"
    ),
    pytest.param(
        b'{"next_id": 2, "tasks": [{"id": "1", "text": "a", "done": false}]}',
        id="id-string",
    ),
    pytest.param(
        b'{"next_id": 2, "tasks": [{"id": 1, "text": "a", "done": "yes"}]}',
        id="done-string",
    ),
    pytest.param(b"\xff\xfe\x00bad", id="non-utf8"),
]


@pytest.mark.parametrize("content", CORRUPT)
def test_load_corrupt_raises_store_error(store, content):  # A11
    store.write_bytes(content)
    with pytest.raises(StoreError) as info:
        storage.load(store)
    assert str(store) in str(info.value)
    assert store.read_bytes() == content


# --- Regression tests for unreadable or inaccessible stores (C1, A11, A14) ---

needs_user = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a non-root POSIX user",
)


def _seed_store(path):
    todo = TodoList()
    storage.add_task(todo, "keep me")
    storage.save(todo, path)
    return path.read_bytes()


@needs_user
def test_load_unreadable_file_raises_store_error(store):  # C1, A11
    before = _seed_store(store)
    os.chmod(store, 0o000)
    try:
        with pytest.raises(StoreError) as exc:
            storage.load(store)
        assert str(store) in str(exc.value)
    finally:
        os.chmod(store, 0o600)
    assert store.read_bytes() == before


@needs_user
def test_load_inaccessible_parent_raises_store_error(tmp_path):  # C1, A11
    d = tmp_path / "locked"
    d.mkdir()
    f = d / "todo.json"
    before = _seed_store(f)
    os.chmod(d, 0o000)
    try:
        with pytest.raises(StoreError):
            storage.load(f)
    finally:
        os.chmod(d, 0o700)
    assert f.read_bytes() == before


def test_load_directory_path_raises_store_error(store):  # C1, A11
    store.mkdir()
    with pytest.raises(StoreError) as exc:
        storage.load(store)
    assert str(store) in str(exc.value)


def test_load_parent_is_file_raises_store_error(tmp_path):  # C1, A11
    f = tmp_path / "plain"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(StoreError):
        storage.load(f / "todo.json")


def test_load_permission_error_without_chmod(store, monkeypatch):  # C1, A11
    _seed_store(store)

    def boom(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pathlib.Path, "read_bytes", boom)
    with pytest.raises(StoreError) as exc:
        storage.load(store)
    assert "Permission denied" in str(exc.value)
    assert str(store) in str(exc.value)


def test_load_missing_parent_dir_is_empty(tmp_path):  # A3, A14
    missing = tmp_path / "nope"
    todo = storage.load(missing / "todo.json")
    assert todo.tasks == []
    assert todo.next_id == 1
    assert not missing.exists()
