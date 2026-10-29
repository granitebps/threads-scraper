"""Threads Scraper as an MCP server: five read-only tools over the same
scraper functions the REST API (routes.py) serves.

    python mcp_server.py           # streamable HTTP on http://127.0.0.1:8000/mcp
    python mcp_server.py --stdio   # stdio, for a local MCP client

Environment:

    MCP_HOST             HTTP bind address (default 127.0.0.1; the container sets 0.0.0.0)
    PORT                 HTTP port (default 8000, config.PORT)
    MCP_TOOL_TIMEOUT     seconds one tool call may spend on threads.com (default 45)
    MCP_MAX_CONCURRENCY  tool calls running at once (default 4)
    MCP_CACHE_SIZE       cached tool results kept in memory (default 500)

Inputs are validated by the REST API's own schemas (threads/schemas.py), so
`post` and `username` accept the same forms: a post code, numeric id or
threads.com link; a username, @username, numeric user id or profile link.

Every tool answers with the scraper's JSON, null / empty fields and avatar
URLs (`profile_picture`) dropped, as
structured content plus one text block. Failures come back as
`isError: true` with {"error": {"code", "message", "retryable"}}.
"""
import argparse
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Annotated, Literal

import anyio
import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
from schema_fields import load_query
from threads import cache_config, discovery, posts, schemas, users
from threads.fetch import ThreadsBadRequest, ThreadsNotFound, ThreadsTimeout, ThreadsUpstreamError, deadline

HOST = os.environ.get("MCP_HOST", "127.0.0.1")
TOOL_TIMEOUT = float(os.environ.get("MCP_TOOL_TIMEOUT", "45"))
MAX_CONCURRENCY = int(os.environ.get("MCP_MAX_CONCURRENCY", "4"))
CACHE_SIZE = int(os.environ.get("MCP_CACHE_SIZE", "500"))

log = logging.getLogger("threads_mcp")


# ---- cache -----------------------------------------------------------------------
# Parsed results only (never page HTML), keyed on the validated params, so
# `zuck`, `@Zuck` and a pasted profile link share one entry. LRU-bounded so
# memory stays flat however long the server runs.

class TTLCache:
    def __init__(self, size):
        self.size = size
        self._data = OrderedDict()      # key -> (expires, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if hit[0] <= time.monotonic():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return hit[1]

    def set(self, key, value, ttl):
        if self.size <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic() + ttl.total_seconds(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


_cache = TTLCache(CACHE_SIZE)
_limiter = None


def _get_limiter():
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(MAX_CONCURRENCY)
    return _limiter


# ---- results ---------------------------------------------------------------------

class ToolFailure(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


# Avatar URLs: ~500 chars each, repeated on every post's author, expiring,
# and not needed by the MCP's users — a third or more of a list's tokens.
OMIT_KEYS = frozenset({"profile_picture"})


def compact(value, top=True):
    """Drop OMIT_KEYS, None, "" and empty lists / dicts — they cost tokens
    and carry nothing. False and 0 are kept, and so are the top-level keys
    (an empty `threads: []` is an answer, not noise)."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in OMIT_KEYS:
                continue
            item = compact(item, top=False)
            if item is None or (not top and (item == "" or item == [] or item == {})):
                continue
            out[key] = item
        return out
    if isinstance(value, list):
        return [compact(item, top=False) for item in value]
    return value


def _result(data, is_error=False):
    return CallToolResult(
        content=[TextContent(text=json.dumps(data, ensure_ascii=False, separators=(",", ":")))],
        structured_content=data,
        is_error=is_error,
    )


def _error(code, message, retryable=False):
    return _result({"error": {"code": code, "message": message, "retryable": retryable}}, is_error=True)


def _validate(schema, params):
    data, error = load_query(schema, {k: v for k, v in params.items() if v is not None})
    if error:
        fields = error.get("errors") or {}
        detail = "; ".join(f"{name}: {' '.join(map(str, msgs))}" for name, msgs in fields.items())
        raise ToolFailure("invalid_input", detail or error.get("error") or "invalid input")
    return data


def _fetch(tool, fn, data, ttl):
    """Run one scraper call under the tool deadline, through the cache."""
    key = (tool, json.dumps(data, sort_keys=True, default=str))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    with deadline(TOOL_TIMEOUT):
        value = compact(fn(**data))
    _cache.set(key, value, ttl)
    return value


async def _run(tool, work):
    """Call `work()` in a worker thread (bounded by MAX_CONCURRENCY) and map
    the scraper's failure taxonomy onto tool errors."""
    try:
        return _result(await anyio.to_thread.run_sync(work, limiter=_get_limiter()))
    except ToolFailure as e:
        return _error(e.code, e.message, e.retryable)
    except ValueError as e:
        return _error("invalid_input", str(e))
    except ThreadsNotFound as e:
        return _error("not_found", str(e) or "not found")
    except ThreadsBadRequest as e:
        return _error("upstream_rejected", str(e) or "threads.com rejected the request")
    except ThreadsTimeout as e:
        return _error("timeout", str(e), retryable=True)
    except ThreadsUpstreamError as e:
        return _error("upstream_unavailable", f"threads.com did not answer: {e}", retryable=True)
    except Exception:
        log.exception("%s failed", tool)
        return _error("internal_error", f"{tool} failed unexpectedly")


# ---- tools -----------------------------------------------------------------------

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
MEDIA_NOTE = (" Media is returned as URLs (`media.image`, `media.video`, carousel `media.items[]`, "
              "`accessibility_caption`); the fbcdn URLs are signed and expire, so download them soon "
              "after the call rather than storing them.")

PostRef = Annotated[str, Field(description="Post code (e.g. DHcqKN_ufwv), numeric post id, or a threads.com / threads.net post link.")]
UserRef = Annotated[str, Field(description="Username, @username, numeric user id, or a threads.com profile link.")]

server = MCPServer(
    name="threads-scraper",
    instructions=("Read-only access to public Threads content, logged out. Search and reply lists are the "
                  "limited public windows threads.com shows logged-out visitors, not complete archives."),
)


@server.tool(annotations=READ_ONLY, description=(
    "Search public Threads posts by keyword. Logged-out search returns a single page (about 20 top "
    "or about 8 recent threads) with no further pages." + MEDIA_NOTE))
async def search_posts(
    query: Annotated[str, Field(description="Keyword or phrase to search for.")],
    sort: Annotated[Literal["top", "recent"], Field(description="top (default) or recent.")] = "top",
    limit: Annotated[int, Field(ge=1, le=25, description="Maximum threads to return (1-25).")] = 10,
) -> CallToolResult:
    def work():
        data = _validate(schemas.PostSearchSchema, {"query": query, "sort": sort})
        result = dict(_fetch("search_posts", discovery.search_posts, data, cache_config.SEARCH_CACHE))
        result["threads"] = (result.get("threads") or [])[:limit]
        result["thread_count"] = len(result["threads"])
        return result
    return await _run("search_posts", work)


@server.tool(annotations=READ_ONLY, description=(
    "Get one Threads post with its text, stats, author, media, link preview and quoted / "
    "reposted post." + MEDIA_NOTE))
async def get_post(post: PostRef) -> CallToolResult:
    def work():
        data = _validate(schemas.PostSchema, {"post": post})
        return _fetch("get_post", posts.get_details, data, cache_config.POST_CACHE)
    return await _run("get_post", work)


@server.tool(annotations=READ_ONLY, description=(
    "Get the replies under a Threads post as threads.com shows them logged out: the first ~8 direct "
    "replies (each with the chain under it), pinned replies and the author's self-thread. "
    "`has_more` means more replies exist but need a login; there is no next page." + MEDIA_NOTE))
async def get_post_replies(post: PostRef) -> CallToolResult:
    def work():
        data = _validate(schemas.PostSchema, {"post": post})
        return _fetch("get_post_replies", posts.get_replies, data, cache_config.POST_CACHE)
    return await _run("get_post_replies", work)


@server.tool(annotations=READ_ONLY, description=(
    "Get a public Threads profile: name, bio, bio links, follower count, verified badge and "
    "topics."))
async def get_profile(username: UserRef) -> CallToolResult:
    def work():
        data = _validate(schemas.UserSchema, {"user": username})
        return _fetch("get_profile", users.get_profile, data, cache_config.PROFILE_CACHE)
    return await _run("get_profile", work)


@server.tool(annotations=READ_ONLY, description=(
    "Get a user's own threads, newest first, 25 per page. Pass `next_cursor` from the previous "
    "answer as `cursor` for the next page while `has_more` is true." + MEDIA_NOTE))
async def get_profile_posts(
    username: UserRef,
    cursor: Annotated[str | None, Field(description="next_cursor from the previous page; omit for the first page.")] = None,
) -> CallToolResult:
    def work():
        data = _validate(schemas.UserPageSchema, {"user": username, "cursor": cursor})
        return _fetch("get_profile_posts", users.get_threads, data, cache_config.USER_THREADS_CACHE)
    return await _run("get_profile_posts", work)


@server.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def main():
    parser = argparse.ArgumentParser(description="Threads Scraper MCP server")
    parser.add_argument("--stdio", action="store_true", help="serve over stdio instead of HTTP")
    args = parser.parse_args()
    if args.stdio:
        server.run("stdio")
    else:
        server.run("streamable-http", host=HOST, port=config.PORT, stateless_http=True, json_response=True)


if __name__ == "__main__":
    main()
