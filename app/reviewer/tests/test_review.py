import pytest

from diff import annotate_patch
from github_client import PRFile, PullRequest
from main import _parse_payload
from reviewer import InlineComment, Review, build_tools

PATCH = """\
@@ -10,4 +10,5 @@ def f():
     a = 1
-    b = 2
+    b = 3
+    c = 4
     return a
\\ No newline at end of file"""


def test_annotate_patch_numbers_new_side_lines():
    text, lines = annotate_patch(PATCH)
    assert lines == {10, 11, 12, 13}
    assert "    11 +    b = 3" in text
    assert "       -    b = 2" in text


def test_annotate_patch_multiple_hunks():
    _, lines = annotate_patch("@@ -1 +1 @@\n-x\n+y\n@@ -50,2 +60,2 @@\n ctx\n+new")
    assert lines == {1, 60, 61}


@pytest.fixture
def tools_and_review():
    pr = PullRequest("o/r", 1, "t", "", "me", "main", "feat", "abc",
                     [PRFile("src/a.py", "modified", 2, 1, PATCH)])
    review = Review()
    tools = {t.tool_name: t for t in build_tools(None, pr, review)}
    return tools, review


def test_submit_review_rejects_lines_outside_diff(tools_and_review):
    tools, review = tools_and_review
    msg = tools["submit_review"]("s", [InlineComment(path="src/a.py", line=99, body="x"),
                                       InlineComment(path="nope.py", line=1, body="x")])
    assert "src/a.py:99" in msg and "nope.py" in msg
    assert not review.submitted


def test_submit_review_records_valid_review(tools_and_review):
    tools, review = tools_and_review
    assert tools["submit_review"]("ok", [InlineComment(path="src/a.py", line=11, body="x")]) == "Review recorded."
    assert review.submitted and review.comments[0].line == 11


def test_submit_review_through_strands_validation(tools_and_review):
    tools, review = tools_and_review
    t = tools["submit_review"]
    args = t._metadata.validate_input({"summary": "ok", "comments": [{"path": "src/a.py", "line": 12, "body": "x"}]})
    assert t(**args) == "Review recorded."
    assert review.comments[0].path == "src/a.py"


@pytest.mark.parametrize("payload", [
    None, {}, {"repo": "bad", "pr_number": 1}, {"repo": "o/r", "pr_number": "1"},
    {"repo": "o/r", "pr_number": True}, {"repo": "o/r", "pr_number": 1, "dry_run": "yes"},
])
def test_parse_payload_rejects_invalid(payload):
    with pytest.raises(ValueError):
        _parse_payload(payload)


def test_parse_payload_ok():
    assert _parse_payload({"repo": "o/r", "pr_number": 3}) == ("o/r", 3, False)
