import json
import subprocess
import sys
from pathlib import Path

import pytest

from cmlint.cli import main
from cmlint.config import ConfigError, find_config, from_mapping

ROOT = Path(__file__).resolve().parent.parent


def git(repo, *args, check=True, env_python=True):
    env = None
    if env_python:
        import os
        env = {**os.environ, "PYTHONPATH": str(ROOT)}   # so the hook's `python -m cmlint` finds the package
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check, env=env)


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Run every test in an empty folder, so the config of whatever repository
    the tests are run from (including this one's pyproject.toml) can't leak in."""
    work = tmp_path / "cwd"
    work.mkdir()
    (work / ".git").mkdir()          # stop the config search here
    monkeypatch.chdir(work)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def commit(repo, message, name="f.txt"):
    (repo / name).write_text(message)
    git(repo, "add", name)
    return git(repo, "commit", "-q", "-m", message, check=False)


# ---- the real git hook ------------------------------------------------------

def test_installed_hook_blocks_bad_messages_and_allows_good_ones(repo, capsys):
    assert main(["install-hook", "--repo", str(repo)]) == 0
    hook = repo / ".git" / "hooks" / "commit-msg"
    assert hook.exists() and hook.stat().st_mode & 0o111

    bad = commit(repo, "Fixed stuff")
    assert bad.returncode != 0
    assert "header-format" in bad.stderr and "rejected" in bad.stderr
    assert git(repo, "rev-list", "--all", "--count", check=False).stdout.strip() in ("", "0")

    good = commit(repo, "feat: add the first file")
    assert good.returncode == 0, good.stderr
    assert git(repo, "log", "--format=%s").stdout.strip() == "feat: add the first file"


def test_hook_uses_repository_config(repo):
    (repo / ".cmlint.toml").write_text('types = ["add", "remove"]\n')
    main(["install-hook", "--repo", str(repo)])
    assert commit(repo, "feat: add x y").returncode != 0
    assert commit(repo, "add: new thing").returncode == 0


def test_install_refuses_to_overwrite_a_foreign_hook(repo, capsys):
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\necho mine\n")
    assert main(["install-hook", "--repo", str(repo)]) == 2
    assert hook.read_text() == "#!/bin/sh\necho mine\n"
    assert main(["install-hook", "--repo", str(repo), "--force"]) == 0
    assert "cmlint" in hook.read_text()


def test_install_outside_a_repository_fails(tmp_path):
    with pytest.raises(SystemExit, match="git rev-parse"):
        main(["install-hook", "--repo", str(tmp_path)])


# ---- linting history -------------------------------------------------------

def test_log_reports_failing_commits_and_totals(repo, capsys):
    for msg in ["feat: add a", "Fixed b", "fix: Add c", "docs: add d"]:
        commit(repo, msg, name=msg[:3])
    assert main(["log", "--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "2/4 commits pass (50.0%)" in out
    assert "header-format" in out and "description-case" in out
    assert "Fixed b" in out and "feat: add a" not in out


def test_log_range_and_all_passing(repo, capsys):
    commit(repo, "Bad start", name="a")
    git(repo, "tag", "base")
    commit(repo, "feat: add b", name="b")
    commit(repo, "fix: repair c", name="c")
    assert main(["log", "base..HEAD", "--repo", str(repo)]) == 0
    assert "2/2 commits pass" in capsys.readouterr().out


def test_log_handles_bodies_and_skips_merges(repo, capsys):
    commit(repo, "feat: add a\n\nA body line.\n\nRefs: #1", name="a")
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "fix: add b", name="b")
    git(repo, "checkout", "-q", "main")
    commit(repo, "fix: add c", name="c")
    git(repo, "merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
    assert main(["log", "--repo", str(repo), "--summary"]) == 0      # merge message is ignored
    assert "4/4 commits pass" in capsys.readouterr().out
    assert main(["log", "--repo", str(repo), "--summary", "--no-merges"]) == 0
    assert "3/3 commits pass" in capsys.readouterr().out


# ---- check command and configuration --------------------------------------

def test_check_file_text_and_json(tmp_path, capsys):
    f = tmp_path / "MSG"
    f.write_text("fix: Added retry.\n")
    assert main(["check", str(f)]) == 1
    err = capsys.readouterr().err
    assert f"{f}:1:6: error [description-case]" in err
    assert main(["check", str(f), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert {d["rule"] for d in data} == {"description-case", "description-full-stop", "imperative-mood"}


def test_strict_turns_warnings_into_failures(tmp_path):
    f = tmp_path / "MSG"
    f.write_text("fix: added retry\n")
    assert main(["check", str(f)]) == 0
    assert main(["--strict", "check", str(f)]) == 1


def test_check_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("feat: add stdin support\n"))
    assert main(["check", "-"]) == 0


def test_check_missing_file(tmp_path, capsys):
    assert main(["check", str(tmp_path / "nope")]) == 2


def test_config_from_pyproject_and_errors(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[tool.cmlint]\nheader-max-length = 50\nscope-required = true\n')
    sub = tmp_path / "pkg" / "deep"
    sub.mkdir(parents=True)
    cfg, source = find_config(sub)
    assert cfg.header_max_length == 50 and cfg.scope_required and source.endswith("pyproject.toml")

    for bad in [{"colour": 1}, {"header-max-length": "50"}, {"header-max-length": 0},
                {"scope-required": "yes"}, {"types": []}, {"imperative-mood": "loud"},
                {"ignore-patterns": ["(unclosed"]}]:
        with pytest.raises(ConfigError):
            from_mapping(bad)


def test_config_search_stops_at_repository_root(tmp_path):
    (tmp_path / ".cmlint.toml").write_text("header-max-length = 10\n")
    inner = tmp_path / "project"
    (inner / ".git").mkdir(parents=True)
    cfg, source = find_config(inner)
    assert source is None and cfg.header_max_length == 72


def test_invalid_toml_is_a_usage_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / ".git").mkdir()
    (tmp_path / "bad" / ".cmlint.toml").write_text("types = [unclosed\n")
    monkeypatch.chdir(tmp_path / "bad")
    msg = tmp_path / "MSG"
    msg.write_text("feat: add x\n")
    assert main(["check", str(msg)]) == 2
    assert "invalid TOML" in capsys.readouterr().err
