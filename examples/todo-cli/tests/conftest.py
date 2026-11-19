"""Shared fixtures. Every test runs with HOME redirected (R21)."""

import pytest

from todo import cli


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir so the real ~/.todo.json is never touched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture
def store(tmp_path):
    """Path of a store file that does not exist yet."""
    return tmp_path / "todo.json"


@pytest.fixture
def run(capsys):
    """Call todo.cli.main(argv); return (exit_code, stdout, stderr)."""

    def _run(argv):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse exits via SystemExit
            code = exc.code
        out, err = capsys.readouterr()
        return code, out, err

    return _run
