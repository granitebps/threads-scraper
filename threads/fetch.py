"""Threads transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no proxy needed (validated 2026-09-21 from direct Indian
egress and through US/GB/DE residential exits; 30 back-to-back GraphQL calls from
one IP all answered 200). threads.com runs no bot challenge at all; its only
walls are login walls, and everything this package serves is on the
logged-out side of them.

Two upstream surfaces:

  * GRAPHQL  POST https://www.threads.com/graphql/query
    The web app's own logged-out Relay queries, sent as persisted doc_ids
    (queries.py). Three traps, each worth a silent failure:
      - every relay-provider boolean the query declares must be in
        `variables` (queries.variables_for) or the answer is HTTP 200
        {"errors":[{"message":"execution error"}],"data":null};
      - the header `x-logged-out-threads-migrated-request: true` is
        mandatory — without it the root field errors ("execution error",
        path ["user"]) although the request is otherwise identical;
      - the call needs a csrftoken cookie echoed in `x-csrftoken` (Django
        double-submit; no cookie -> 403 Instagram "Page Not Found" HTML).
        A random token works, so a session needs NO bootstrap page. The
        `lsd` value is not validated either (any non-empty token passes).
    A missing entity is `data.<root>: null` with no error.

  * PAGES    GET https://www.threads.com/@user/post/<code>, /tag/<name>
    Server-rendered pages that embed the same Relay results in
    `<script type="application/json" data-sjs>` blocks (ssr.py). Used only
    where the logged-out GraphQL answers null: a post's direct replies and
    its parent chain (BarcelonaPostPageDownward/UpwardQuery) and the tag
    page's thread counts. `/t/<code>` redirects to the canonical
    `/@user/post/<code>`. An unknown user redirects to /login/, an unknown
    post to `/?error=invalid_post` (or, via /t/<code>, stays on /t/ with an
    empty app shell); an unknown tag renders an empty page.

FALLBACK: a thread whose direct egress is refused (403 / 429 / HTML where
JSON was expected) moves to a residential proxy exit
(config.THREADS_FALLBACK_PROXY_COUNTRY) for THREADS_DIRECT_COOLDOWN
seconds. If residential exits start being challenged too, the next step is
the patchright pattern (g2 pool): warm a Chrome on https://www.threads.com/
and run these same POSTs through the in-page fetch. Not built: dead code
while plain HTTP works.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ThreadsUpstreamError  transport failure / 5xx                   — retryable
  ThreadsExecutionError GraphQL "execution error" with no data     — retryable,
                        except on paged calls (a bad cursor -> 400)
  ThreadsBlocked        403 / 429 / HTML instead of JSON          — retryable
  ThreadsBadRequest     upstream 400                              — never retried
  ThreadsNotFound       unknown user / post / tag                 — never retried
  ThreadsTimeout        the caller's deadline() ran out           — not retried here

DEADLINE: `with deadline(seconds):` bounds every request, retry and backoff
made inside the block (including run_parallel fan-out) to one total budget.
Without it the nested retries (ssr.load x _retrying x timeouts) can run for
minutes; the MCP server sets one per tool call. Unset = no bound, so the
REST API and main.py behave as before.
"""
import contextvars
import json
import os
import secrets
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

from .queries import QUERIES, variables_for

SITE = "https://www.threads.com"
GRAPHQL_URL = SITE + "/graphql/query"
IMPERSONATE = "chrome"

# Constants of the threads.com web app (same for every logged-out visitor).
APP_ID = "238260118697367"
ASBD_ID = "359341"

GRAPHQL_TIMEOUT = 30
PAGE_TIMEOUT = 45          # post pages are 0.7-1 MB
FANOUT_WORKERS = 4

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
}


class ThreadsUpstreamError(UpstreamError):
    """Transport failure, 5xx or a GraphQL execution error — retryable."""


class ThreadsExecutionError(ThreadsUpstreamError):
    """GraphQL answered `data: null` with "execution error" — a transient
    backend failure, a stale doc_id / provider list, or (on paged queries)
    a cursor the server cannot decode."""


class ThreadsBlocked(ThreadsUpstreamError, Blocked):
    """403 / 429, or HTML where JSON was expected — retryable on a new exit."""


class ThreadsBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class ThreadsNotFound(NotFound):
    """The user / post / tag does not exist — never retried."""


class ThreadsTimeout(ThreadsUpstreamError):
    """The deadline() budget ran out before Threads answered."""


# ---- deadline --------------------------------------------------------------------
_deadline = contextvars.ContextVar("threads_deadline", default=None)


@contextmanager
def deadline(seconds):
    """Bound everything fetched inside the block to `seconds` in total."""
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def _remaining():
    end = _deadline.get()
    return None if end is None else end - time.monotonic()


def _timeout(default):
    """The request timeout to use: `default`, cut to what the deadline leaves."""
    left = _remaining()
    if left is None:
        return default
    if left <= 0:
        raise ThreadsTimeout("ran out of time waiting for threads.com")
    return min(default, left)


# ---- sessions --------------------------------------------------------------------
# One curl session per worker thread (a curl handle must not be shared across
# threads), each with its own random csrftoken/lsd pair.
_local = threading.local()
_TOKEN_CHARS = string.ascii_letters + string.digits


def _token(n):
    return "".join(secrets.choice(_TOKEN_CHARS) for _ in range(n))


def _session():
    sess = getattr(_local, "session", None)
    via_proxy = getattr(_local, "proxy_until", 0) > time.time()
    if sess is not None and getattr(sess, "_th_proxied", False) != via_proxy:
        _drop_session()
        sess = None
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.threads_proxy() or (config.threads_fallback_proxy() if via_proxy else None)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess._th_proxied = via_proxy
        sess._th_csrf = _token(32)
        sess._th_lsd = "AV" + _token(9)
        sess.cookies.set("csrftoken", sess._th_csrf, domain=".threads.com")
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _escalate():
    """Direct egress (or the current exit) was refused: run this thread
    through a fresh residential exit for a while (no fallback configured =
    just rebuild the session with new tokens)."""
    if config.threads_fallback_proxy() is not None:
        _local.proxy_until = time.time() + config.THREADS_DIRECT_COOLDOWN
    _drop_session()


def dump_debug(name, text):
    """Write a raw response to $THREADS_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("THREADS_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


def _retrying(fn, no_retry=()):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except ThreadsTimeout:
            raise
        except no_retry:
            raise
        except ThreadsBlocked as e:
            last = e
            _escalate()
        except ThreadsUpstreamError as e:
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            pause = config.RETRY_BACKOFF * attempt
            left = _remaining()
            if left is not None and left <= pause:
                raise ThreadsTimeout(f"ran out of time retrying threads.com (last error: {last})")
            time.sleep(pause)
    raise last


# ---- GraphQL -------------------------------------------------------------------------

def _is_execution_error(errors):
    return any("execution error" in str((e or {}).get("message", "")) for e in errors or [])


def graphql(name, retry_execution_errors=True, **variables):
    """Run one persisted logged-out query -> its `data` object.

    A missing entity comes back as data with a null root (callers turn that
    into ThreadsNotFound). `data: null` with errors is either a transient
    backend failure or a stale doc_id / provider list — retried, then
    surfaced as an upstream error naming the query so a re-harvest is
    obvious from the logs. Paged calls pass retry_execution_errors=False:
    an undecodable cursor fails the same way every time, so retrying only
    delays the 400."""
    query = QUERIES[name]
    body = {
        "lsd": None,
        "doc_id": query["doc_id"],
        "variables": json.dumps(variables_for(name, **variables), separators=(",", ":")),
        "fb_api_req_friendly_name": name,
        "fb_api_caller_class": "RelayModern",
        "server_timestamps": "true",
        "__a": "1",
        "__comet_req": "29",
        "__user": "0",
        "av": "0",
    }

    def once():
        sess = _session()
        body["lsd"] = sess._th_lsd
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": SITE,
            "referer": SITE + "/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-asbd-id": ASBD_ID,
            "x-csrftoken": sess._th_csrf,
            "x-fb-friendly-name": name,
            "x-fb-lsd": sess._th_lsd,
            "x-ig-app-id": APP_ID,
            "x-logged-out-threads-migrated-request": "true",
        }
        if query.get("root"):
            headers["x-root-field-name"] = query["root"]
        timeout = _timeout(GRAPHQL_TIMEOUT)
        try:
            resp = sess.post(GRAPHQL_URL, data=body, headers=headers, timeout=timeout)
        except Exception as e:
            raise ThreadsUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status in (401, 403, 429):
            dump_debug(f"blocked_{name}", text)
            raise ThreadsBlocked(f"HTTP {status} on {name}")
        if status >= 500:
            raise ThreadsUpstreamError(f"HTTP {status} on {name}")
        if not text.lstrip().startswith("{"):
            dump_debug(f"nonjson_{name}", text)
            raise ThreadsBlocked(f"{name} returned a non-JSON body")
        try:
            payload = json.loads(text)
        except ValueError:
            dump_debug(f"badjson_{name}", text)
            raise ThreadsUpstreamError(f"could not parse JSON from {name}")
        if status == 400:
            raise ThreadsBadRequest(f"threads rejected {name}")
        if status != 200:
            raise ThreadsUpstreamError(f"HTTP {status} on {name}")
        data = payload.get("data")
        if data is None:
            dump_debug(f"error_{name}", text)
            if _is_execution_error(payload.get("errors")):
                raise ThreadsExecutionError(f"{name} failed upstream (execution error)")
            raise ThreadsUpstreamError(f"{name} returned no data")
        return data

    return _retrying(once, no_retry=() if retry_execution_errors else (ThreadsExecutionError,))


# ---- pages ------------------------------------------------------------------------------

def get_page(path, *, label):
    """GET one threads.com page -> (html, final_url). Unknown users/tags
    redirect to the login page and unknown posts to `/?error=invalid_post`;
    both are ThreadsNotFound here."""
    url = SITE + path

    def once():
        sess = _session()
        timeout = _timeout(PAGE_TIMEOUT)
        try:
            resp = sess.get(url, headers=PAGE_HEADERS, timeout=timeout, allow_redirects=True)
        except Exception as e:
            raise ThreadsUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        final = str(resp.url or url)
        if status == 404:
            raise ThreadsNotFound(f"{label} not found")
        if status in (401, 403, 429):
            dump_debug("blocked_page", resp.text)
            raise ThreadsBlocked(f"HTTP {status} on {path}")
        if status >= 500 or status != 200:
            raise ThreadsUpstreamError(f"HTTP {status} on {path}")
        parsed = urlparse(final)
        if parsed.path.startswith("/login") or "error=invalid_post" in (parsed.query or ""):
            raise ThreadsNotFound(f"{label} not found")
        # a real post's /t/<code> redirects to /@user/post/<code>; an unknown
        # code answers 200 with an empty app shell and stays on /t/
        if path.startswith("/t/") and parsed.path.startswith("/t/"):
            raise ThreadsNotFound(f"{label} not found")
        html = resp.text or ""
        if "<html" not in html[:3000].lower():
            dump_debug("nonhtml", html)
            raise ThreadsBlocked(f"{path} returned a non-HTML body")
        return html, final

    return _retrying(once)


# ---- fan-out -------------------------------------------------------------------------

def run_parallel(fns):
    """Run zero-arg callables in parallel; results align with `fns`.
    Exceptions propagate from the first failing call. Each call runs in a
    copy of the caller's context so a deadline() reaches the workers."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(contextvars.copy_context().run, fn) for fn in fns]
        return [f.result() for f in futures]


if __name__ == "__main__":
    # Smoke test: python -m threads.fetch [username]
    who = sys.argv[1] if len(sys.argv) > 1 else "zuck"
    data = graphql("BarcelonaUsernameHovercardImplDirectQuery", username=who)
    user = data.get("user") or {}
    print("user:", user.get("username"), user.get("pk"), user.get("follower_count"))
