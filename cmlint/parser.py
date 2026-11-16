"""Parse a commit message in the Conventional Commits 1.0 format.

    type(scope)!: description          <- header (line 1)
                                       <- blank line
    body paragraphs ...                <- optional
                                       <- blank line
    Token: value                       <- footers (optional)
    BREAKING CHANGE: what broke

The header is scanned by hand rather than with one big regex so that every
mistake gets its own message and an exact column.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCISSORS = "# ------------------------ >8 ------------------------"
# ":" must be followed by a space, or end the line (git strips trailing spaces).
FOOTER_RE = re.compile(r"^((?i:breaking[ -]change)|[A-Za-z][\w-]*)(:(?: |$)| #)(.*)$")
AUTO_PREFIXES = ("Merge ", 'Revert "', "fixup! ", "squash! ", "amend! ")


@dataclass
class Problem:
    line: int
    col: int
    rule: str
    message: str
    severity: str = "error"   # "error" or "warning"


@dataclass
class Footer:
    token: str
    value: str
    line: int


@dataclass
class Commit:
    raw: str
    header: str = ""
    type: str | None = None
    type_col: int = 1
    scope: str | None = None
    scope_col: int = 0
    breaking_bang: bool = False
    description: str | None = None
    description_col: int = 0
    body_lines: list[tuple[int, str]] = field(default_factory=list)   # (line number, text)
    footers: list[Footer] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def breaking(self) -> bool:
        return self.breaking_bang or any(f.token.upper() in ("BREAKING CHANGE", "BREAKING-CHANGE") for f in self.footers)


def clean(message: str) -> str:
    """Do what git does before storing a message: cut at the scissors line
    (used by `git commit -v`), drop '#' comment lines and trailing blank lines."""
    lines = message.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if line.rstrip() == SCISSORS:
            break
        if line.startswith("#"):
            continue
        out.append(line.rstrip())
    while out and not out[-1]:
        out.pop()
    while out and not out[0]:
        out.pop(0)
    return "\n".join(out)


def is_auto_generated(message: str) -> bool:
    return message.startswith(AUTO_PREFIXES)


def parse_header(header: str, commit: Commit) -> None:
    """Fill commit.type/scope/description, recording a problem for the first
    structural mistake found."""
    p = commit.problems
    if header[:1].isspace():
        p.append(Problem(1, 1, "header-format", "header starts with whitespace; remove the leading spaces"))
        return
    if ":" not in header:
        p.append(Problem(1, 1, "header-format", "no 'type: ' prefix; write e.g. 'fix: describe the change'"))
        return
    i, n = 0, len(header)
    while i < n and (header[i].isalnum() or header[i] in "-_"):
        i += 1
    if i == 0:
        p.append(Problem(1, 1, "header-format", "header must start with a type, e.g. 'feat: ...'"))
        return
    commit.type = header[:i]
    if i < n and header[i] == "(":
        close = header.find(")", i)
        if close == -1:
            p.append(Problem(1, i + 1, "header-format", "scope opened with '(' but never closed"))
            return
        scope = header[i + 1:close]
        if not scope.strip():
            p.append(Problem(1, i + 1, "header-format", "empty scope '()'; remove the parentheses or name a scope"))
            return
        if "(" in scope:
            p.append(Problem(1, i + 1, "header-format", "nested '(' inside the scope"))
            return
        commit.scope, commit.scope_col = scope, i + 2
        i = close + 1
    if i < n and header[i] == "!":
        commit.breaking_bang = True
        i += 1
    if i < n and header[i] == " " and header[i:].lstrip()[:1] in ("(", ":", "!"):
        p.append(Problem(1, i + 1, "header-format", f"unexpected space after '{header[:i]}'"))
        return
    if i >= n or header[i] != ":":
        found = repr(header[i]) if i < n else "end of line"
        p.append(Problem(1, i + 1, "header-format", f"expected ':' after the type{'/scope' if commit.scope else ''}, found {found}"))
        return
    i += 1
    if i >= n or header[i] != " ":
        p.append(Problem(1, i + 1, "header-format", "expected exactly one space after ':'"))
        return
    i += 1
    if i < n and header[i] == " ":
        p.append(Problem(1, i + 1, "header-format", "expected exactly one space after ':'"))
        return
    if i >= n:
        p.append(Problem(1, i + 1, "header-format", "description is empty"))
        return
    commit.description, commit.description_col = header[i:], i + 1


def parse(message: str) -> Commit:
    text = clean(message)
    commit = Commit(raw=text)
    if not text:
        commit.problems.append(Problem(1, 1, "header-format", "commit message is empty"))
        return commit
    lines = text.split("\n")
    commit.header = lines[0]
    parse_header(commit.header, commit)

    rest = list(enumerate(lines[1:], start=2))
    if rest and rest[0][1].strip():
        commit.problems.append(Problem(2, 1, "body-leading-blank", "leave a blank line between the header and the body"))

    # Split the remaining text into paragraphs; the last one is the footer
    # block if its first line looks like a footer token.
    paragraphs: list[list[tuple[int, str]]] = []
    for num, line in rest:
        if line.strip():
            if not paragraphs or paragraphs[-1] is None:
                paragraphs.append([])
            paragraphs[-1].append((num, line))
        elif paragraphs and paragraphs[-1] is not None:
            paragraphs.append(None)
    paragraphs = [para for para in paragraphs if para]
    if paragraphs and FOOTER_RE.match(paragraphs[-1][0][1]):
        footer_block = paragraphs.pop()
        for num, line in footer_block:
            m = FOOTER_RE.match(line)
            if m:
                commit.footers.append(Footer(m.group(1), m.group(3), num))
            elif commit.footers:                      # continuation of the previous value
                commit.footers[-1].value += "\n" + line
    for para in paragraphs:
        commit.body_lines.extend(para)
    return commit
