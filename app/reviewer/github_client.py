"""Minimal GitHub REST client for reading a pull request and posting a review."""

import base64
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"


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


class GitHubClient:
    def __init__(self, token: str, repo: str):
        self.repo = repo
        self._http = httpx.Client(
            base_url=API,
            timeout=30,
            follow_redirects=True,  # renamed/transferred repos answer with 301
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def get_pull_request(self, number: int) -> PullRequest:
        r = self._http.get(f"/repos/{self.repo}/pulls/{number}")
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
            r = self._http.get(
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
        r = self._http.get(f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def list_dir(self, path: str, ref: str) -> list[str] | None:
        r = self._http.get(f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return None
        return [f"{e['path']}{'/' if e['type'] == 'dir' else ''}" for e in data]

    def create_review(self, number: int, commit_sha: str, body: str, comments: list[dict]) -> str:
        r = self._http.post(
            f"/repos/{self.repo}/pulls/{number}/reviews",
            json={"commit_id": commit_sha, "event": "COMMENT", "body": body, "comments": comments},
        )
        r.raise_for_status()
        return r.json()["html_url"]
