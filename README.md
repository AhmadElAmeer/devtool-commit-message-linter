# devtool-commit-message-linter

[![CI](https://github.com/AhmadElAmeer/devtool-commit-message-linter/actions/workflows/ci.yml/badge.svg)](https://github.com/AhmadElAmeer/devtool-commit-message-linter/actions/workflows/ci.yml)

`cmlint` checks commit messages against the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format. It runs as a git `commit-msg` hook, as a CLI, or over existing history. Errors point at the exact line and column, like a compiler's. It's pure Python with no dependencies.

```
$ git commit -m "fix(auth) Added retry"
.git/COMMIT_EDITMSG:1:10: error [header-format] expected ':' after the type/scope, found ' '

commit message rejected. Format: type(scope): description, e.g. 'fix(parser): handle empty input'
```

## Problem

A consistent commit history lets teams generate changelogs, pick version numbers automatically (`feat` → minor, `!`/`BREAKING CHANGE` → major), and scan `git log` quickly. Conventions only stay consistent if something checks them at the moment of committing. "Please follow the format" in a contributing guide isn't enough: the survey below found mistakes even in the history of the best-known commit-linting project itself.

## Overview

- `cmlint/parser.py` cleans a message the way git does (comment lines, the `git commit -v` scissors line, CRLF). It then splits it into header, body and footers. The header is scanned by hand instead of matched with one regex, so each mistake gets its own message and column.
- `cmlint/rules.py` applies configurable rules and returns problems with a severity (error or warning).
- `cmlint/config.py` reads `.cmlint.toml` or `[tool.cmlint]` in `pyproject.toml`. It searches upward but never past the repository root, and rejects unknown keys and bad values.
- `cmlint/cli.py` provides `check` (one message; what the hook runs), `log` (lint history with totals per rule) and `install-hook`.

## Key features

- Header checks with exact columns:
  - missing type, a stray space before `(` or `:`, a missing space after `:`;
  - empty, unclosed or nested scope, leading whitespace, empty description.
- Rules:
  - type list, with "did you mean 'refactor'?" for typos;
  - lowercase type, scope list or required scope, header length;
  - description: lowercase start (acronyms allowed), no trailing period, minimum length;
  - imperative mood (`add`, not `added`/`adds`), WIP detection;
  - a blank line after the header, body line length (URLs exempt);
  - `BREAKING CHANGE` footers must have a description and be written in capitals.
- Merge, revert, `fixup!`, `squash!` and `amend!` messages are skipped. `ignore-patterns` skips others, such as release-tool commits.
- Warnings don't block a commit unless `--strict` is used. Output as text or `--format json`.
- `install-hook` refuses to overwrite a commit-msg hook it didn't install, unless given `--force`.

## Tech stack

- Python 3.11+ (uses `tomllib`), standard library only
- git
- pytest, including tests that run real `git commit` through the installed hook

## Architecture

```
git commit ──► .git/hooks/commit-msg ──► python -m cmlint check .git/COMMIT_EDITMSG
                                              │
              config.py: .cmlint.toml or [tool.cmlint] (searched up to the repo root)
                                              │
              parser.py: clean() ─► parse() ─► Commit(type, scope, !, description, body, footers)
                                              │                + structural problems
              rules.py:  lint() ─► header / body / footer rules ─► [Problem(line, col, rule, severity)]
                                              │
              cli.py:    print "file:line:col: error [rule] message", exit 1 if any error
```

## Installation

```bash
git clone https://github.com/AhmadElAmeer/devtool-commit-message-linter.git
cd devtool-commit-message-linter
python3 -m pip install -e .        # gives you the `cmlint` command
```

Without installing: `PYTHONPATH=/path/to/devtool-commit-message-linter python3 -m cmlint ...`

## Usage

```bash
cd your-project
cmlint install-hook                    # every `git commit` is now checked
cmlint log origin/main..HEAD           # check the commits on your branch before pushing
cmlint log -n 500 --no-merges --summary
echo "feat: add search" | cmlint check -
cmlint --strict check MSG              # warnings fail too
```

Configuration (all keys optional):

```toml
# .cmlint.toml, or [tool.cmlint] in pyproject.toml
types = ["feat", "fix", "docs", "refactor", "test", "chore", "release"]
scopes = ["api", "ui", "db"]           # empty or absent = any scope
scope-required = true
header-max-length = 100
body-max-line-length = 100
description-min-length = 3
imperative-mood = "error"              # "error", "warning" (default) or "off"
ignore-auto-generated = true
ignore-patterns = ['^v\d+\.\d+\.\d+']  # skip release-tool commits like "v21.2.4"
```

This repository dogfoods it: its `pyproject.toml` sets `imperative-mood = "error"`, and every commit in it went through the installed hook. The hook rejected the first attempt at this repository's own first commit, whose body had a 153-character line.

## Results: a survey of real projects

`scripts/survey.sh` lints the 1,000 most recent non-merge commits of three public projects. It runs first with the default rules, then with a config matching each project's own conventions. Full output is in [docs/survey.md](docs/survey.md).

| project (commit surveyed) | uses Conventional Commits? | default rules | project config |
|---|---|---:|---:|
| vitejs/vite (`8aa52a9a99`) | yes | 71.2% pass | **98.5%** pass |
| conventional-changelog/commitlint (`f26bc5264c`) | yes | 89.5% pass | **99.2%** pass |
| pallets/flask (`49943b5a94`) | no | 0.4% pass | — |

What the failures actually were:

- **Vite's 21.5% "too long" headers come from its merge process, not from careless authors.** 939 of 1,000 headers end with the pull-request number GitHub adds on squash-merge (`(#12345)`), which pushes many past 72 characters. A further 73 commits use a project-specific `release:` type. Allowing `release` and 100 characters (commitlint's own default) raises compliance to 98.5%. The remaining 15 headers are 101–118 characters long.
- **commitlint's 4.6% header-format failures were almost all release-tool commits** named just `v21.2.4`. With `ignore-patterns` for those, 99.2% pass. The 8 real failures left are ones a hook would have caught:
  - two headers starting with spaces (`  chore: …`);
  - branch names used as headers (`Chore/deps prettier v3 3`);
  - the typo `refctor:`, for which cmlint now suggests `refactor`;
  - `Fix regression…` with no type.
- **Flask doesn't use the convention,** so 99% "fail" the header format. That's a project choice, not a quality problem. The survey shows that the linter's verdict only means something relative to the convention a project has chosen.

The survey also changed the tool: `ignore-patterns`, the leading-whitespace message and the type suggestions were all added because of what it found.

## Testing

```bash
python3 -m pytest -q        # 53 tests, under 1 second
```

- **Parser:** 13 malformed-header cases, each checked for exactly one error at the expected column. It also checks extraction of type, scope, `!`, body and multi-line footers, and git's cleanup (comments, scissors, CRLF, trailing blank lines).
- **Rules:** every rule triggers and passes as expected, including the boundary (72 characters passes, 73 fails), acronyms, URL exemption, imperative suggestions (`'fix', not 'fixes'`), auto-generated messages and `ignore-patterns`.
- **Real git:** the installed hook rejects a bad `git commit` (no commit is created), accepts a good one, and uses the repository's config. It refuses to replace a foreign hook without `--force`, and fails cleanly outside a repository.
- **History:** `log` totals and per-rule counts, revision ranges, messages with bodies and footers, merge commits with and without `--no-merges`.
- **Config:** `pyproject.toml` found from a subfolder, the search stops at the repository root, and invalid keys, types, values, regexes and TOML are each rejected with a clear message.

To check the tests can fail, ten bugs were planted one at a time:

- comment lines kept;
- the scissors line ignored;
- auto-generated messages linted;
- imperative mood an error by default;
- URLs not exempt from line length;
- acronyms rejected;
- header length off by one;
- the hook not executable;
- the config search escaping the repository;
- `--no-merges` ignored.

All ten are caught. Running the suite from a fresh clone found a test-isolation bug: some CLI tests picked up this repository's own `[tool.cmlint]` settings from the working directory. Every test now runs in its own empty folder.

While the tests were being written they also found a real bug: `BREAKING CHANGE:` with nothing after it wasn't recognised as a footer, because git strips the trailing space and the pattern required `": "`.

## Design decisions and challenges

- **A hand-written header scanner.** One regex can say "doesn't match", but not *why*. Scanning character by character gives each mistake its own message and column, which is what makes a rejected commit quick to fix.
- **Cleaning like git.** The hook sees the message file *before* git strips comments, including the whole diff below the scissors line when using `git commit -v`. Linting that text as-is would report false errors, so `clean()` repeats git's rules.
- **Errors vs warnings.** "Imperative mood" is a heuristic based on a word list, so by default it warns instead of blocking a commit. Teams that want it strict can set `imperative-mood = "error"`.
- **Config never leaves the repository.** The upward search stops at the folder containing `.git`, so a stray `.cmlint.toml` in a parent folder can't silently change a project's rules.
- **Never overwrite someone else's hook.** Projects often have their own `commit-msg` hook; `install-hook` only replaces one it installed itself.

## Future improvements

- A [pre-commit](https://pre-commit.com/) framework hook definition (`.pre-commit-hooks.yaml`).
- A GitHub Action that lints all commits in a pull request.
- Generating a changelog and the next version number from the parsed commits.
- Per-type rules, e.g. requiring a body for `feat` or a footer for `fix`.

## What this project teaches

- How git hooks work: where they live, what arguments they get, and how a non-zero exit cancels a commit.
- Writing a small hand-made parser with precise error reporting, instead of relying on one regex.
- Designing a configurable CLI tool: config discovery, validation, exit codes, text and JSON output.
- Testing tools that call other programs, by running real `git` in temporary repositories.
- Measuring a tool on real data, and letting the results change the design.

## License

MIT — see [LICENSE](LICENSE).
