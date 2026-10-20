import httpx
import pytest

from github_client import GitHubClient


def make_client(responses, max_retries=3):
    """Client whose transport replays `responses` (status codes, header dicts or exceptions)."""
    calls, sleeps = [], []

    def handler(request):
        calls.append(request.method)
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, {})
        return httpx.Response(status, headers=headers, json={"html_url": "u", "ok": True})

    gh = GitHubClient("t", "o/r", max_retries=max_retries, retry_backoff=1,
                      transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return gh, calls, sleeps


def test_get_retries_5xx_with_exponential_backoff():
    gh, calls, sleeps = make_client([502, 503, 200])
    assert gh._request("GET", "/x").status_code == 200
    assert len(calls) == 3 and sleeps == [1, 2]


def test_get_honors_retry_after_on_rate_limit():
    gh, calls, sleeps = make_client([(403, {"retry-after": "7"}), 200])
    assert gh._request("GET", "/x").status_code == 200
    assert sleeps == [7]


def test_get_gives_up_after_max_retries():
    gh, calls, _ = make_client([500], max_retries=2)
    assert gh._request("GET", "/x").status_code == 500
    assert len(calls) == 3


def test_client_errors_are_not_retried():
    gh, calls, _ = make_client([404, 200])
    assert gh._request("GET", "/x").status_code == 404
    assert len(calls) == 1


def test_plain_403_is_not_retried():
    gh, calls, _ = make_client([403, 200])
    assert gh._request("GET", "/x").status_code == 403
    assert len(calls) == 1


def test_connection_errors_are_retried():
    gh, calls, _ = make_client([httpx.ConnectError("boom"), 200])
    assert gh._request("GET", "/x").status_code == 200
    assert len(calls) == 2


def test_post_review_not_retried_on_5xx():
    # GitHub may have created the review before failing; retrying could post it twice.
    gh, calls, _ = make_client([502, 200])
    with pytest.raises(httpx.HTTPStatusError):
        gh.create_review(1, "sha", "body", [])
    assert calls == ["POST"]


def test_post_review_not_retried_on_read_timeout():
    gh, calls, _ = make_client([httpx.ReadTimeout("slow"), 200])
    with pytest.raises(httpx.ReadTimeout):
        gh.create_review(1, "sha", "body", [])
    assert len(calls) == 1


def test_post_review_retried_on_rate_limit():
    gh, calls, _ = make_client([429, 200])
    assert gh.create_review(1, "sha", "body", []) == "u"
    assert calls == ["POST", "POST"]
