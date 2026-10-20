"""PR review agent: Strands tools bound to one pull request, plus posting the result."""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from strands import Agent, tool

from diff import annotate_patch, commentable_lines
from github_client import GitHubClient, PullRequest
from model.load import load_model, load_retry_strategy
from prompts import SYSTEM_PROMPT, review_prompt
from settings import SETTINGS

REVIEW_MARKER = "<!-- agentcore-pr-review -->"


class InlineComment(BaseModel):
    path: str = Field(description="File path exactly as listed in get_pr_overview")
    line: int = Field(description="New-file line number from the left column of get_file_diff")
    body: str = Field(description="Markdown comment, starting with a severity tag")


@dataclass
class Review:
    summary: str = ""
    comments: list[InlineComment] = field(default_factory=list)
    submitted: bool = False


def build_tools(gh: GitHubClient, pr: PullRequest, review: Review) -> list:
    @tool
    def get_pr_overview() -> str:
        """Get the PR title, description, branches and the list of changed files."""
        lines = [
            f"Title: {pr.title}",
            f"Author: {pr.author}",
            f"Branches: {pr.head_ref} -> {pr.base_ref}",
            f"Description:\n{pr.body[: SETTINGS.max_description_chars] or '(none)'}",
            "",
            f"Changed files ({len(pr.files)}):",
        ]
        for f in pr.files:
            note = "" if f.patch else " (no diff available: binary or too large)"
            lines.append(f"- {f.path} [{f.status}] +{f.additions} -{f.deletions}{note}")
        return "\n".join(lines)

    @tool
    def get_file_diff(path: str) -> str:
        """Get the diff for one changed file. The left column is the new-file line number
        to use for inline comments; removed lines have no number.

        Args:
            path: File path as listed in get_pr_overview.
        """
        f = pr.file(path)
        if f is None:
            return f"{path} is not part of this PR."
        if not f.patch:
            return f"No diff available for {path}."
        return annotate_patch(f.patch)[0]

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a file from the PR head commit, with line numbers. Use it for context
        around a change. Long files are returned in chunks; ask for the next range.

        Args:
            path: Repository-relative file path.
            start_line: First line to return (1-based).
            end_line: Last line to return (inclusive). Defaults to the largest allowed chunk.
        """
        content = gh.get_file(path, pr.head_sha)
        if content is None:
            return f"{path} not found at {pr.head_sha[:7]} (or it is a directory/binary)."
        all_lines = content.splitlines()
        start, chunk = max(start_line, 1), SETTINGS.max_file_lines
        end = min(end_line or start + chunk - 1, start + chunk - 1, len(all_lines))
        body = "\n".join(f"{n:>6}  {all_lines[n - 1]}" for n in range(start, end + 1))
        return f"{path} lines {start}-{end} of {len(all_lines)}\n{body}"

    @tool
    def list_directory(path: str = "") -> str:
        """List files in a repository directory at the PR head commit.

        Args:
            path: Repository-relative directory path; empty for the repo root.
        """
        entries = gh.list_dir(path, pr.head_sha)
        return "\n".join(entries) if entries is not None else f"{path or '/'} is not a directory."

    @tool
    def submit_review(summary: str, comments: list[InlineComment]) -> str:
        """Submit the final review. Call once, at the end.

        Args:
            summary: Markdown summary of the review.
            comments: Inline comments on specific changed lines. May be empty.
        """
        # Strands validates tool input with pydantic, then hands nested models over as dicts.
        comments = [InlineComment.model_validate(c) for c in comments]
        errors = []
        for c in comments:
            f = pr.file(c.path)
            if f is None:
                errors.append(f"{c.path}: not a changed file")
            elif c.line not in commentable_lines(f.patch):
                errors.append(f"{c.path}:{c.line}: line is not in the diff")
        if errors:
            return "Review rejected, fix these comments and call submit_review again:\n" + "\n".join(errors)
        review.summary, review.comments, review.submitted = summary, comments, True
        return "Review recorded."

    return [get_pr_overview, get_file_diff, read_file, list_directory, submit_review]


def run_review(gh: GitHubClient, pr_number: int) -> tuple[PullRequest, Review]:
    pr = gh.get_pull_request(pr_number)
    review = Review()
    agent = Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=build_tools(gh, pr, review),
        retry_strategy=load_retry_strategy(),
        callback_handler=None,
    )
    agent(review_prompt(pr.repo, pr.number))
    if not review.submitted:
        raise RuntimeError("Agent finished without calling submit_review")
    return pr, review


def post_review(gh: GitHubClient, pr: PullRequest, review: Review) -> str:
    return gh.create_review(
        pr.number,
        pr.head_sha,
        f"{review.summary}\n\n{REVIEW_MARKER}",
        [{"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in review.comments],
    )
