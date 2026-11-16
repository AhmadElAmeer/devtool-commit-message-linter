"""Command-line interface.

    cmlint check FILE            lint one message (this is what the git hook runs)
    cmlint check -               read the message from stdin
    cmlint log [REV_RANGE]       lint existing commits, e.g. `cmlint log origin/main..HEAD`
    cmlint install-hook          install the commit-msg hook in the current repository

Exit codes: 0 = no errors, 1 = lint errors, 2 = usage/config/git problem.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .config import ConfigError, find_config
from .parser import Problem
from .rules import lint

HOOK = """#!/bin/sh
# Installed by cmlint: lint the commit message before git records the commit.
exec "{python}" -m cmlint check "$1"
"""
RECORD_SEP = "\x1e"


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SystemExit("error: git is not installed") from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"error: git {' '.join(args)} failed: {exc.stderr.strip()}") from None
    return res.stdout


def format_problems(name: str, problems: list[Problem]) -> list[str]:
    return [f"{name}:{p.line}:{p.col}: {p.severity} [{p.rule}] {p.message}" for p in problems]


def has_errors(problems: list[Problem], strict: bool) -> bool:
    return any(p.severity == "error" or strict for p in problems)


def cmd_check(a, cfg) -> int:
    if a.file == "-":
        message, name = sys.stdin.read(), "stdin"
    else:
        try:
            message = Path(a.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read {a.file}: {exc.strerror}", file=sys.stderr)
            return 2
        name = a.file
    problems = lint(message, cfg)
    if a.format == "json":
        print(json.dumps([p.__dict__ for p in problems], indent=2))
    else:
        for line in format_problems(name, problems):
            print(line, file=sys.stderr)
    failed = has_errors(problems, a.strict)
    if failed and a.format == "text":
        print("\ncommit message rejected. Format: type(scope): description, "
              "e.g. 'fix(parser): handle empty input'", file=sys.stderr)
    return 1 if failed else 0


def cmd_log(a, cfg) -> int:
    rev = a.range or "HEAD"
    args = ["log", f"--format=%H%n%B{RECORD_SEP}", rev]
    if a.max_count:
        args.insert(1, f"--max-count={a.max_count}")
    if a.no_merges:
        args.insert(1, "--no-merges")
    out = _git(*args, cwd=a.repo)
    total, failing = 0, 0
    rule_counts: Counter[str] = Counter()
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition("\n")
        total += 1
        problems = lint(message, cfg)
        errors = [p for p in problems if p.severity == "error" or a.strict]
        rule_counts.update({p.rule for p in errors})
        if errors:
            failing += 1
            if not a.summary:
                header = message.split("\n", 1)[0]
                print(f"{sha[:10]} {header[:70]}")
                for line in format_problems("  ", errors):
                    print(line.replace("  :", "  line ", 1))
    if total == 0:
        print("no commits in range")
        return 0
    passing = total - failing
    print(f"{'' if a.summary else chr(10)}{passing}/{total} commits pass ({100 * passing / total:.1f}%)")
    for rule, count in rule_counts.most_common():
        print(f"  {rule:<28} {count:>5} commits ({100 * count / total:.1f}%)")
    return 1 if failing else 0


def cmd_install(a, cfg) -> int:
    git_dir = Path(_git("rev-parse", "--git-dir", cwd=a.repo).strip())
    if not git_dir.is_absolute():
        git_dir = Path(a.repo or ".") / git_dir
    hooks = git_dir / "hooks"
    hooks.mkdir(exist_ok=True)
    target = hooks / "commit-msg"
    if target.exists() and "cmlint" not in target.read_text(errors="replace") and not a.force:
        print(f"error: {target} already exists and was not installed by cmlint; use --force to replace it",
              file=sys.stderr)
        return 2
    target.write_text(HOOK.format(python=sys.executable))
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed {target}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cmlint", description="Lint commit messages (Conventional Commits).")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="lint one commit message")
    c.add_argument("file", help="file containing the message, or - for stdin")
    c.add_argument("--format", choices=("text", "json"), default="text")

    lg = sub.add_parser("log", help="lint commits from git history")
    lg.add_argument("range", nargs="?", help="revision range, e.g. main..HEAD (default: all of HEAD)")
    lg.add_argument("-n", "--max-count", type=int)
    lg.add_argument("--no-merges", action="store_true")
    lg.add_argument("--summary", action="store_true", help="print only the totals")
    lg.add_argument("--repo", help="path to the repository (default: current directory)")

    h = sub.add_parser("install-hook", help="install the commit-msg git hook")
    h.add_argument("--force", action="store_true", help="replace an existing commit-msg hook")
    h.add_argument("--repo", help="path to the repository (default: current directory)")

    a = p.parse_args(argv)
    start = Path(getattr(a, "repo", None) or os.getcwd()).resolve()
    try:
        cfg, _ = find_config(start)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return {"check": cmd_check, "log": cmd_log, "install-hook": cmd_install}[a.cmd](a, cfg)
