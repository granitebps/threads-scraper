"""Offline tests for the MCP tool layer (mcp_server.py) and the fetch
deadline — no network. Upstream calls are replaced with the captured
payloads in threads/fixtures/, so these run the real parsers.

    python -m pytest test_mcp_server.py -q
"""
import json
import os
import time

import anyio
import pytest

import mcp_server
from threads import discovery, fetch, posts, users
from threads.fetch import ThreadsNotFound, ThreadsTimeout, ThreadsUpstreamError

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "threads", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def call(tool, **kwargs):
    result = anyio.run(lambda: tool(**kwargs))
    assert json.loads(result.content[0].text) == result.structured_content
    return result


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(mcp_server, "_cache", mcp_server.TTLCache(100))
    users._lookups.clear()


class Upstream:
    """Fake fetch.graphql: answers by query name and counts the calls."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, name, retry_execution_errors=True, **variables):
        self.calls.append((name, variables))
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer


# ---- compact -------------------------------------------------------------------------

def test_compact_drops_empty_values_but_keeps_top_level_and_falsy_scalars():
    data = {"threads": [], "next_cursor": None, "has_more": False,
            "post": {"text": "", "media": None, "items": [], "stats": {"like_count": 0}, "tags": {},
                     "author": {"username": "zuck", "profile_picture": "https://cdn/x.jpg"}}}
    assert mcp_server.compact(data) == {"threads": [], "has_more": False,
                                        "post": {"stats": {"like_count": 0}, "author": {"username": "zuck"}}}


# ---- tools ---------------------------------------------------------------------------

def test_get_post_parses_fixture_and_caches_across_input_forms(monkeypatch):
    upstream = Upstream({"BarcelonaPostPageTargetQuery": load("post_text.json")})
    monkeypatch.setattr(posts, "graphql", upstream)

    first = call(mcp_server.get_post, post="DdZ7sQvkTFn")
    assert not first.is_error
    assert first.structured_content["id"] == "3988481471392330087"
    assert first.structured_content["author"]["username"] == "zuck"
    assert None not in first.structured_content.values()

    second = call(mcp_server.get_post, post="https://www.threads.com/@zuck/post/DdZ7sQvkTFn")
    assert second.structured_content == first.structured_content
    assert len(upstream.calls) == 1          # the link resolved to the same cache key


def test_search_posts_limit_trims_cached_result(monkeypatch):
    upstream = Upstream({"BarcelonaSearchResultsRefetchableQuery": load("search_top.json")})
    monkeypatch.setattr(discovery, "graphql", upstream)

    full = call(mcp_server.search_posts, query="SpaceX", limit=25).structured_content
    assert full["thread_count"] >= 2
    one = call(mcp_server.search_posts, query="SpaceX", limit=1).structured_content
    assert one["thread_count"] == 1 and one["threads"] == full["threads"][:1]
    assert len(upstream.calls) == 1
    assert upstream.calls[0][1]["recent"] == 0


def test_get_profile_posts_pages_with_cursor(monkeypatch):
    upstream = Upstream({
        "BarcelonaUsernameHovercardImplDirectQuery": load("hovercard_zuck.json"),
        "BarcelonaProfileThreadsTabRefetchableDirectQuery": load("tab_posts.json"),
    })
    monkeypatch.setattr(users, "graphql", upstream)

    result = call(mcp_server.get_profile_posts, username="@Zuck")
    page = result.structured_content
    assert page["user"]["username"] == "zuck"
    assert "profile_picture" not in result.content[0].text
    assert "threads" in page and "has_more" in page

    call(mcp_server.get_profile_posts, username="zuck", cursor="abc")
    tab_calls = [v for name, v in upstream.calls if name.startswith("BarcelonaProfileThreadsTab")]
    assert [v["after"] for v in tab_calls] == [None, "abc"]


def test_invalid_input_is_a_tool_error_without_upstream_call(monkeypatch):
    upstream = Upstream({})
    monkeypatch.setattr(posts, "graphql", upstream)

    result = call(mcp_server.get_post, post="not a post!")
    assert result.is_error
    error = result.structured_content["error"]
    assert error["code"] == "invalid_input" and error["retryable"] is False
    assert "post" in error["message"]
    assert upstream.calls == []


@pytest.mark.parametrize("raised, code, retryable", [
    (ThreadsNotFound("@nobody not found on Threads"), "not_found", False),
    (ThreadsTimeout("ran out of time"), "timeout", True),
    (ThreadsUpstreamError("HTTP 502"), "upstream_unavailable", True),
    (RuntimeError("boom"), "internal_error", False),
])
def test_scraper_failures_map_to_error_codes(monkeypatch, raised, code, retryable):
    monkeypatch.setattr(users, "graphql", Upstream({"BarcelonaUsernameHovercardImplDirectQuery": raised}))

    result = call(mcp_server.get_profile, username="nobody")
    assert result.is_error
    assert result.structured_content["error"]["code"] == code
    assert result.structured_content["error"]["retryable"] is retryable


def test_failures_are_not_cached(monkeypatch):
    upstream = Upstream({"BarcelonaPostPageTargetQuery": ThreadsUpstreamError("HTTP 502")})
    monkeypatch.setattr(posts, "graphql", upstream)
    call(mcp_server.get_post, post="DdZ7sQvkTFn")
    upstream.answers["BarcelonaPostPageTargetQuery"] = load("post_text.json")
    assert not call(mcp_server.get_post, post="DdZ7sQvkTFn").is_error


def test_cache_is_bounded_and_expires(monkeypatch):
    from datetime import timedelta
    cache = mcp_server.TTLCache(2)
    for key in "abc":
        cache.set(key, key, timedelta(minutes=1))
    assert cache.get("a") is None and cache.get("c") == "c"
    cache.set("d", "d", timedelta(seconds=-1))
    assert cache.get("d") is None


# ---- deadline ------------------------------------------------------------------------

def test_deadline_stops_retries_instead_of_sleeping_through_backoff():
    attempts = []

    def failing():
        attempts.append(1)
        raise ThreadsUpstreamError("HTTP 500")

    started = time.monotonic()
    with fetch.deadline(0.5), pytest.raises(ThreadsTimeout):
        fetch._retrying(failing)
    assert time.monotonic() - started < 1
    assert len(attempts) == 1                # the 2 s backoff would overrun the budget


def test_deadline_caps_request_timeout_and_reaches_parallel_workers():
    assert fetch._timeout(30) == 30          # no deadline: unchanged
    with fetch.deadline(5):
        assert fetch._timeout(30) <= 5
        assert all(t <= 5 for t in fetch.run_parallel([lambda: fetch._timeout(30)] * 2))
    with fetch.deadline(-1), pytest.raises(ThreadsTimeout):
        fetch._timeout(30)
