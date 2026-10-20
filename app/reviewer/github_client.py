"""Minimal GitHub REST client for reading a pull request and posting a review."""

import base64
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

API = "https://api.github.com"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF = 60.0


@dataclass
class PRFile:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str | None  # None for binary files or diffs GitHub won't render


@dataclass
class PullRequest:
    repo: str
    number: int
    title: str
    body: str
    author: str
    base_ref: str
    head_ref: str
    head_sha: str
    files: list[PRFile] = field(default_factory=list)

    def file(self, path: str) -> PRFile | None:
        return next((f for f in self.files if f.path == path), None)


def _is_rate_limited(r: httpx.Response) -> bool:
    # GitHub signals secondary rate limits with 403 + Retry-After or an exhausted quota.
    return r.status_code == 403 and (
        "retry-after" in r.headers or r.headers.get("x-ratelimit-remaining") == "0"
    )


class GitHubClient:
    def __init__(
        self,
        token: str,
        repo: str,
        timeout: float = 30,
        max_retries: int = 4,
        retry_backoff: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.repo = repo
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=API,
            timeout=timeout,
            transport=transport,
            follow_redirects=True,  # renamed/transferred repos answer with 301
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _request(self, method: str, url: str, idempotent: bool = True, **kwargs) -> httpx.Response:
        """Send a request, retrying transient failures with exponential backoff.

        Non-idempotent requests (posting a review) are retried only when GitHub certainly
        did not act on them: connection failures and rate limiting.
        """
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                r = self._http.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                if last:
                    raise
            except httpx.TransportError:
                if last or not idempotent:
                    raise
            else:
                limited = r.status_code == 429 or _is_rate_limited(r)
                retryable = limited or (idempotent and r.status_code in RETRYABLE_STATUS)
                if not retryable or last:
                    return r
                if "retry-after" in r.headers:
                    self._sleep(min(float(r.headers["retry-after"]), MAX_BACKOFF))
                    continue
            self._sleep(min(self._retry_backoff * 2**attempt, MAX_BACKOFF))
        raise AssertionError("unreachable")

    def get_pull_request(self, number: int) -> PullRequest:
        r = self._request("GET", f"/repos/{self.repo}/pulls/{number}")
        r.raise_for_status()
        pr = r.json()
        return PullRequest(
            repo=self.repo,
            number=number,
            title=pr["title"],
            body=pr.get("body") or "",
            author=pr["user"]["login"],
            base_ref=pr["base"]["ref"],
            head_ref=pr["head"]["ref"],
            head_sha=pr["head"]["sha"],
            files=self._list_files(number),
        )

    def _list_files(self, number: int) -> list[PRFile]:
        files, page = [], 1
        while True:
            r = self._request(
                "GET",
                f"/repos/{self.repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            r.raise_for_status()
            batch = r.json()
            files += [
                PRFile(f["filename"], f["status"], f["additions"], f["deletions"], f.get("patch"))
                for f in batch
            ]
            if len(batch) < 100:
                return files
            page += 1

    def get_file(self, path: str, ref: str) -> str | None:
        r = self._request("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def list_dir(self, path: str, ref: str) -> list[str] | None:
        r = self._request("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return None
        return [f"{e['path']}{'/' if e['type'] == 'dir' else ''}" for e in data]

    def create_review(self, number: int, commit_sha: str, body: str, comments: list[dict]) -> str:
        r = self._request(
            "POST",
            f"/repos/{self.repo}/pulls/{number}/reviews",
            idempotent=False,
            json={"commit_id": commit_sha, "event": "COMMENT", "body": body, "comments": comments},
        )
        r.raise_for_status()
        return r.json()["html_url"]
