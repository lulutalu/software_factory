"""Tests for todo.cli via main(argv), plus a few subprocess tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def seed(run, store, *texts):
    for t in texts:
        assert run(["--file", str(store), "add", t])[0] == 0


def test_list_no_file(run, store):  # A3
    code, out, _ = run(["--file", str(store), "list"])
    assert code == 0
    assert out.strip() == "No tasks."
    assert not store.exists()


def test_add_creates_expected_json(run, store):  # A4
    code, out, _ = run(["--file", str(store), "add", "Buy milk"])
    assert code == 0
    assert "1" in out
    assert json.loads(store.read_text(encoding="utf-8")) == {
        "next_id": 2,
        "tasks": [{"id": 1, "text": "Buy milk", "done": False}],
    }


def test_add_multi_word_joined(run, store, tmp_path):  # A4
    other = tmp_path / "other.json"
    run(["--file", str(store), "add", "Buy milk"])
    code, _, _ = run(["--file", str(other), "add", "Buy", "milk"])
    assert code == 0
    assert json.loads(other.read_text())["tasks"][0]["text"] == "Buy milk"


@pytest.mark.parametrize("text", ["", "   "])
def test_add_blank_existing_store(run, store, text):  # A5
    seed(run, store, "x")
    before = store.read_bytes()
    code, _, err = run(["--file", str(store), "add", text])
    assert code != 0
    assert err.strip()
    assert store.read_bytes() == before


@pytest.mark.parametrize("text", ["", "   "])
def test_add_blank_no_store(run, store, text):  # A5
    code, _, err = run(["--file", str(store), "add", text])
    assert code != 0
    assert err.strip()
    assert not store.exists()


def test_list_output_after_done(run, store):  # A6
    seed(run, store, "Buy milk", "Pay rent")
    assert run(["--file", str(store), "done", "2"])[0] == 0
    code, out, _ = run(["--file", str(store), "list"])
    assert code == 0
    assert out == "1. [ ] Buy milk\n2. [x] Pay rent\n"


def test_done_twice_is_noop(run, store):  # A7
    seed(run, store, "Buy milk", "Pay rent")
    run(["--file", str(store), "done", "2"])
    before = store.read_bytes()
    code, out, _ = run(["--file", str(store), "done", "2"])
    assert code == 0
    assert "already done" in out
    assert store.read_bytes() == before


def test_remove_then_ids_not_reused(run, store):  # A8
    seed(run, store, "Buy milk", "Pay rent")
    code, _, _ = run(["--file", str(store), "remove", "2"])
    assert code == 0
    _, out, _ = run(["--file", str(store), "list"])
    assert out == "1. [ ] Buy milk\n"
    assert run(["--file", str(store), "add", "Walk dog"])[0] == 0
    _, out, _ = run(["--file", str(store), "list"])
    assert out == "1. [ ] Buy milk\n3. [ ] Walk dog\n"


@pytest.mark.parametrize(
    "argv",
    [["done", "999"], ["remove", "999"], ["remove", "2"], ["done", "abc"]],
)
def test_bad_id_errors(run, store, argv):  # A9
    seed(run, store, "Buy milk", "Pay rent")
    run(["--file", str(store), "remove", "2"])
    before = store.read_bytes()
    code, _, err = run(["--file", str(store), *argv])
    assert code != 0
    assert err.strip()
    assert store.read_bytes() == before


@pytest.mark.parametrize(
    "argv", [[], ["frobnicate"], ["add"], ["done"], ["remove"]]
)
def test_usage_errors(run, store, argv):  # A10
    code, _, err = run(["--file", str(store), *argv])
    assert code != 0
    assert "usage:" in err
    assert not store.exists()


def test_no_args_usage(run):  # A10
    code, _, err = run([])
    assert code != 0
    assert "usage:" in err


@pytest.mark.parametrize(
    "content", [b"not json{", b"[]", b'{"tasks": "oops"}'], ids=["junk", "list", "bad-tasks"]
)
@pytest.mark.parametrize(
    "argv", [["list"], ["add", "x"], ["done", "1"], ["remove", "1"]], ids=lambda a: a[0]
)
def test_corrupt_store(run, store, content, argv):  # A11
    store.write_bytes(content)
    code, _, err = run(["--file", str(store), *argv])
    assert code != 0
    assert str(store) in err
    assert "Traceback" not in err
    assert store.read_bytes() == content


def test_file_option_before_subcommand(run, store):  # A12
    assert run(["--file", str(store), "add", "x"])[0] == 0
    assert store.exists()


def test_default_path_uses_home(run, fake_home):  # A12
    default = fake_home / ".todo.json"
    assert not default.exists()
    assert run(["add", "Test"])[0] == 0
    assert default.exists()
    code, out, _ = run(["list"])
    assert code == 0
    assert out == "1. [ ] Test\n"


def _sub(args, home):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [sys.executable, "-m", "todo", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_subprocess_help(fake_home):  # A1
    r = _sub(["--help"], fake_home)
    assert r.returncode == 0
    assert "usage:" in r.stdout


def test_subprocess_persistence(fake_home, store):  # A1, R18
    r = _sub(["--file", str(store), "add", "x"], fake_home)
    assert r.returncode == 0
    r = _sub(["--file", str(store), "list"], fake_home)
    assert r.returncode == 0
    assert r.stdout == "1. [ ] x\n"


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a non-root POSIX user",
)
@pytest.mark.parametrize(
    "argv", [["list"], ["add", "x"], ["done", "1"], ["remove", "1"]]
)
def test_unreadable_store_fails_every_command(run, tmp_path, argv):  # C1, C3, A11, A14
    d = tmp_path / "locked"
    d.mkdir()
    f = d / "todo.json"
    seed(run, f, "task one")
    before = f.read_bytes()
    os.chmod(d, 0o000)
    try:
        code, out, err = run(["--file", str(f), *argv])
    finally:
        os.chmod(d, 0o700)
    assert code == 1
    assert str(f) in err
    assert "Traceback" not in err
    assert "cannot write" not in err
    assert "No tasks." not in out
    assert f.read_bytes() == before
