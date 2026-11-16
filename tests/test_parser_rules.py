import pytest

from cmlint.parser import clean, parse
from cmlint.rules import Config, lint


def rules(message, **cfg):
    return [p.rule for p in lint(message, Config(**cfg)) if p.severity == "error"]


def warnings(message, **cfg):
    return [p.rule for p in lint(message, Config(**cfg)) if p.severity == "warning"]


# ---- valid messages ------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "feat: add login",
    "fix(parser): handle empty input",
    "feat(api)!: drop v1 endpoints",
    "docs: API keys explained in the README",  # an acronym may start the description
    "refactor(core-utils): split helpers",
    "chore: bump deps\n\nUpdates every dev dependency to its latest minor version.",
    "fix: avoid crash\n\nFirst paragraph.\n\nSecond paragraph.\n\nRefs: #123\nReviewed-by: Ana",
    "feat!: new config format\n\nBREAKING CHANGE: the old .ini files are no longer read",
    "fix: wrap long line\n\nSee https://example.com/" + "x" * 150 + " for details",
])
def test_valid_messages_have_no_errors(msg):
    assert rules(msg) == []


# ---- header structure: one precise problem each ------------------------

@pytest.mark.parametrize("msg,col,text", [
    ("", 1, "empty"),
    ("Fixed the bug", 1, "no 'type: ' prefix"),
    ("Fixed bug: the login", 6, "expected ':'"),
    ("feat (api): x y z", 5, "unexpected space"),
    ("feat : add x", 5, "unexpected space"),
    ("feat:add x", 6, "one space"),
    ("feat:  add x", 7, "one space"),
    ("feat: ", 6, "one space"),
    ("feat(api: add x", 5, "never closed"),
    ("feat(): add x", 5, "empty scope"),
    ("feat(a(b)): add x", 5, "nested"),
    (": add x", 1, "start with a type"),
    ("  chore: add x", 1, "whitespace"),
])
def test_header_format_errors(msg, col, text):
    problems = [p for p in lint(msg) if p.rule == "header-format"]
    assert len(problems) == 1, problems
    assert problems[0].col == col and text in problems[0].message


def test_unparseable_header_does_not_also_report_type_rules():
    assert rules("Fixed bug.") == ["header-format"]


def test_parse_extracts_parts():
    c = parse("feat(api)!: drop v1\n\nWhy we did it.\n\nBREAKING CHANGE: v1 is gone\n  and will not return\nRefs #42")
    assert (c.type, c.scope, c.breaking_bang, c.description) == ("feat", "api", True, "drop v1")
    assert [line for _, line in c.body_lines] == ["Why we did it."]
    assert [(f.token, f.value) for f in c.footers] == [("BREAKING CHANGE", "v1 is gone\n  and will not return"), ("Refs", "42")]
    assert c.breaking and c.description_col == 13


def test_breaking_change_footer_without_bang_still_counts():
    assert parse("feat: x\n\nBREAKING-CHANGE: config moved").breaking


# ---- content rules -------------------------------------------------------

def test_type_rules():
    assert rules("FEAT: add x") == ["type-case"]
    assert rules("feature: add x") == ["type-enum"]
    msg = lint("refctor: tidy up")[0].message
    assert "did you mean 'refactor'" in msg
    assert "did you mean" not in lint("wibble: add x")[0].message
    assert rules("release: 1.2.3", types=["feat", "release"]) == []


def test_scope_rules():
    assert rules("fix: x y z", scope_required=True) == ["scope-required"]
    assert rules("fix(db): x y z", scopes=["api", "ui"]) == ["scope-enum"]
    assert rules("fix(api): x y z", scopes=["api", "ui"]) == []


def test_description_rules():
    assert rules("fix: Add retry") == ["description-case"]
    assert rules("fix: add retry.") == ["description-full-stop"]
    assert rules("fix: ab") == ["description-min-length"]
    assert rules("fix: " + "a" * 80) == ["header-max-length"]
    assert rules("fix: " + "a" * 80, header_max_length=100) == []
    assert rules("fix: " + "a" * 67) == []                     # exactly 72 characters is allowed
    assert rules("fix: " + "a" * 68) == ["header-max-length"]


def test_imperative_mood_is_a_warning_by_default():
    assert rules("fix: added retry") == []
    assert warnings("fix: added retry") == ["imperative-mood"]
    assert "'add', not 'added'" in lint("fix: added retry")[0].message
    assert "'fix', not 'fixes'" in lint("fix: fixes crash")[0].message
    assert rules("fix: added retry", imperative_mood="error") == ["imperative-mood"]
    assert lint("fix: added retry", Config(imperative_mood="off")) == []


def test_wip_is_flagged():
    assert warnings("feat: wip login page") == ["no-wip"]


def test_body_rules():
    assert rules("fix: add x\nno blank line") == ["body-leading-blank"]
    long = "word " * 30
    problems = [p for p in lint("fix: add x\n\nshort\n" + long) if p.rule == "body-max-line-length"]
    assert len(problems) == 1 and problems[0].line == 4
    assert rules("fix: add x\n\n" + long, body_max_line_length=200) == []


def test_breaking_change_footer_rules():
    assert rules("feat: x y z\n\nBREAKING CHANGE: ") == ["breaking-change-description"]
    assert rules("feat: x y z\n\nBreaking change: api moved") == ["breaking-change-case"]


# ---- what git does to a message before the hook sees it ------------------

def test_comments_and_scissors_are_removed():
    msg = ("fix: add x\n\nreal body\n# Please enter the commit message\n"
           "# ------------------------ >8 ------------------------\nDo not modify the line above.\ndiff --git a b\n")
    assert clean(msg) == "fix: add x\n\nreal body"
    assert rules(msg) == []


def test_crlf_and_trailing_blank_lines():
    assert clean("fix: add x\r\n\r\nbody\r\n\r\n\r\n") == "fix: add x\n\nbody"
    assert rules("fix: add x\r\n\r\nbody\r\n") == []


@pytest.mark.parametrize("msg", [
    "Merge branch 'main' into feature",
    'Revert "feat: add login"\n\nThis reverts commit abc123.',
    "fixup! feat: add login",
    "squash! fix: something",
])
def test_auto_generated_messages_are_ignored(msg):
    assert lint(msg) == []
    assert rules(msg, ignore_auto_generated=False) != []


def test_ignore_patterns():
    assert rules("v21.2.4", ignore_patterns=[r"^v\d+\.\d+\.\d+"]) == []
    assert rules("v21.2.4") == ["header-format"]
