"""Configurable lint rules applied to a parsed commit."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .parser import Commit, Problem, is_auto_generated, parse

DEFAULT_TYPES = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"]

# Common non-imperative first words. "Add", not "Added"/"Adds"/"Adding".
NON_IMPERATIVE = {
    "added", "adds", "adding", "fixed", "fixes", "fixing", "updated", "updates", "updating",
    "changed", "changes", "changing", "removed", "removes", "removing", "deleted", "deletes",
    "created", "creates", "implemented", "implements", "improved", "improves", "refactored",
    "refactors", "renamed", "renames", "moved", "moves", "bumped", "bumps", "made", "makes",
    "replaced", "replaces", "upgraded", "upgrades", "cleaned", "cleans", "used", "uses",
    "allowed", "allows", "introduced", "introduces", "supported", "supports", "converted", "converts",
}


@dataclass
class Config:
    types: list[str] = field(default_factory=lambda: list(DEFAULT_TYPES))
    scopes: list[str] = field(default_factory=list)          # empty = any scope allowed
    scope_required: bool = False
    header_max_length: int = 72
    body_max_line_length: int = 100
    description_min_length: int = 3
    imperative_mood: str = "warning"                         # "error", "warning" or "off"
    ignore_auto_generated: bool = True
    ignore_patterns: list[str] = field(default_factory=list)  # regexes; a matching header is skipped


def lint(message: str, config: Config | None = None) -> list[Problem]:
    cfg = config or Config()
    commit = parse(message)
    if cfg.ignore_auto_generated and is_auto_generated(commit.raw):
        return []
    if any(re.search(pattern, commit.header) for pattern in cfg.ignore_patterns):
        return []
    problems = list(commit.problems)
    problems += _header_rules(commit, cfg)
    problems += _body_rules(commit, cfg)
    problems += _footer_rules(commit)
    return sorted(problems, key=lambda p: (p.line, p.col, p.rule))


def _header_rules(c: Commit, cfg: Config) -> list[Problem]:
    out = []
    if len(c.header) > cfg.header_max_length:
        out.append(Problem(1, cfg.header_max_length + 1, "header-max-length",
                           f"header is {len(c.header)} characters; the limit is {cfg.header_max_length}"))
    if c.type is not None and c.description is not None:
        if c.type != c.type.lower():
            out.append(Problem(1, c.type_col, "type-case", f"type must be lowercase: '{c.type.lower()}'"))
        if c.type.lower() not in cfg.types:
            close = difflib.get_close_matches(c.type.lower(), cfg.types, n=1, cutoff=0.6)
            hint = f"did you mean '{close[0]}'? " if close else ""
            out.append(Problem(1, c.type_col, "type-enum",
                               f"unknown type '{c.type}'; {hint}allowed: {', '.join(cfg.types)}"))
    if c.description is None:
        return out          # header did not parse; the parser already reported why
    if c.scope is None and cfg.scope_required:
        out.append(Problem(1, len(c.type or "") + 1, "scope-required", "a scope is required, e.g. 'fix(parser): ...'"))
    if c.scope is not None and cfg.scopes and c.scope not in cfg.scopes:
        out.append(Problem(1, c.scope_col, "scope-enum", f"unknown scope '{c.scope}'; allowed: {', '.join(cfg.scopes)}"))
    d, col = c.description, c.description_col
    if len(d.strip()) < cfg.description_min_length:
        out.append(Problem(1, col, "description-min-length",
                           f"description is too short (minimum {cfg.description_min_length} characters)"))
    if d[:1].isupper() and not (len(d) > 1 and d[1].isupper()):     # allow acronyms like "API ..."
        out.append(Problem(1, col, "description-case", "start the description with a lowercase letter"))
    if d.rstrip().endswith("."):
        out.append(Problem(1, len(c.header.rstrip()), "description-full-stop", "do not end the description with a period"))
    first = d.split()[0].lower().strip(",:") if d.split() else ""
    if cfg.imperative_mood != "off" and first in NON_IMPERATIVE:
        out.append(Problem(1, col, "imperative-mood",
                           f"use the imperative mood: '{_imperative(first)}', not '{first}'", cfg.imperative_mood))
    if first in ("wip", "wip:") or d.lower().startswith("wip "):
        out.append(Problem(1, col, "no-wip", "work-in-progress commits should not be merged; squash them first", "warning"))
    return out


def _imperative(word: str) -> str:
    irregular = {"made": "make", "makes": "make", "used": "use", "uses": "use", "moved": "move",
                 "moves": "move", "removed": "remove", "removes": "remove", "changed": "change",
                 "changes": "change", "created": "create", "creates": "create", "updated": "update",
                 "updates": "update", "improved": "improve", "improves": "improve", "renamed": "rename",
                 "renames": "rename", "replaced": "replace", "replaces": "replace", "upgraded": "upgrade",
                 "upgrades": "upgrade", "allowed": "allow", "introduced": "introduce", "introduces": "introduce",
                 "supported": "support", "converted": "convert", "deleted": "delete", "deletes": "delete",
                 "fixes": "fix", "bumped": "bump", "bumps": "bump", "implemented": "implement",
                 "refactored": "refactor", "cleaned": "clean", "fixed": "fix", "added": "add"}
    if word in irregular:
        return irregular[word]
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _body_rules(c: Commit, cfg: Config) -> list[Problem]:
    out = []
    for num, line in c.body_lines:
        if len(line) > cfg.body_max_line_length and not _is_unbreakable(line):
            out.append(Problem(num, cfg.body_max_line_length + 1, "body-max-line-length",
                               f"line is {len(line)} characters; wrap at {cfg.body_max_line_length}"))
    return out


def _is_unbreakable(line: str) -> bool:
    """Long URLs and lines without spaces can't be wrapped, so they're allowed."""
    stripped = line.strip()
    return " " not in stripped or "://" in stripped


def _footer_rules(c: Commit) -> list[Problem]:
    out = []
    for f in c.footers:
        is_breaking = f.token.upper() in ("BREAKING CHANGE", "BREAKING-CHANGE")
        if is_breaking and not f.value.strip():
            out.append(Problem(f.line, 1, "breaking-change-description", "BREAKING CHANGE needs a description of what broke"))
        if is_breaking and f.token not in ("BREAKING CHANGE", "BREAKING-CHANGE"):
            out.append(Problem(f.line, 1, "breaking-change-case", "write the footer token as 'BREAKING CHANGE' in capitals"))
    return out
