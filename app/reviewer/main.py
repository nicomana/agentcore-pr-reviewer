import asyncio
import re

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from credentials import get_github_token
from github_client import GitHubClient
from reviewer import post_review, run_review
from settings import SETTINGS

app = BedrockAgentCoreApp()
log = app.logger

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parse_payload(payload) -> tuple[str, int, bool]:
    """Expected payload: {"repo": "owner/name", "pr_number": 123, "dry_run": false}."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    repo, number, dry_run = payload.get("repo"), payload.get("pr_number"), payload.get("dry_run", False)
    if not isinstance(repo, str) or not _REPO.match(repo):
        raise ValueError("repo must be a string like 'owner/name'")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError("pr_number must be a positive integer")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    return repo, number, dry_run


def review_pr(repo: str, number: int, dry_run: bool) -> dict:
    gh = GitHubClient(
        get_github_token(),
        repo,
        timeout=SETTINGS.github_timeout,
        max_retries=SETTINGS.github_max_retries,
        retry_backoff=SETTINGS.github_retry_backoff,
    )
    pr, review = run_review(gh, number)
    result = {
        "repo": repo,
        "pr_number": number,
        "head_sha": pr.head_sha,
        "summary": review.summary,
        "comments": [c.model_dump() for c in review.comments],
    }
    if not dry_run:
        result["review_url"] = post_review(gh, pr, review)
    return result


@app.entrypoint
async def invoke(payload, context):
    repo, number, dry_run = _parse_payload(payload)
    log.info("Reviewing %s#%d (dry_run=%s)", repo, number, dry_run)
    # The agent loop and GitHub calls are blocking; keep the event loop free for health pings.
    return await asyncio.to_thread(review_pr, repo, number, dry_run)


if __name__ == "__main__":
    app.run()
