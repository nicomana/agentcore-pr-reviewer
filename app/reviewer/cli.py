"""Run a review locally, without AgentCore: uv run python cli.py owner/repo 123 [--post]

Uses GITHUB_TOKEN, falling back to `gh auth token`. Prints the review; posts it only with --post.
"""

import argparse
import json
import os
import subprocess

from main import review_pr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("pr_number", type=int)
    parser.add_argument("--post", action="store_true", help="post the review to GitHub")
    args = parser.parse_args()

    if not os.getenv("GITHUB_TOKEN"):
        os.environ["GITHUB_TOKEN"] = subprocess.check_output(["gh", "auth", "token"], text=True).strip()

    result = review_pr(args.repo, args.pr_number, dry_run=not args.post)
    print(result["summary"], "\n")
    for c in result["comments"]:
        print(f"--- {c['path']}:{c['line']}\n{c['body']}\n")
    if "review_url" in result:
        print(f"Posted: {result['review_url']}")
    else:
        print(json.dumps({"inline_comments": len(result["comments"])}))


if __name__ == "__main__":
    main()
