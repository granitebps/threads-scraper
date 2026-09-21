"""User endpoints: resolve, profile, and the four profile tabs (threads,
replies, media, reposts).

`user` is {"id": ..., "username": ...} from refs.resolve_user (a username,
@username, numeric id or profile link). Every endpoint first looks the user
up with the hovercard query (by username or by id — a ~2 KB answer), which
both proves the user exists (a null user is a 404) and supplies the numeric
id the tab queries need. Lookups are memoised in-process for
LOOKUP_TTL seconds so a paging client does not pay for it on every page.

Tabs page with opaque cursors (`cursor` in, `next_cursor` out). Page sizes
are fixed server-side whatever `first` asks for: 25 threads for threads and
replies, 15 for media (probed 2026-09-21 with first=50/100).
"""
import threading
import time

from . import parsers as P
from .fetch import ThreadsBadRequest, ThreadsExecutionError, ThreadsNotFound, graphql

LOOKUP_TTL = 600
_lookup_lock = threading.Lock()
_lookups = {}           # ("id"|"username", value) -> (expires, raw hovercard user)

TAB_QUERIES = {
    "threads": "BarcelonaProfileThreadsTabRefetchableDirectQuery",
    "replies": "BarcelonaProfileRepliesTabRefetchableDirectQuery",
    "media": "BarcelonaProfileMediaTabRefetchableDirectQuery",
    "reposts": "BarcelonaProfileRepostsTabRefetchableDirectQuery",
}
PAGE_SIZE = 25
INVALID_CURSOR = "invalid cursor: pass the next_cursor value from the previous page unchanged"


def _describe(user):
    return f"@{user['username']}" if user.get("username") else f"user id {user.get('id')}"


def lookup(user):
    """The raw hovercard user for a resolved ref; ThreadsNotFound if the
    account does not exist (or is not on Threads)."""
    key = ("username", user["username"]) if user.get("username") else ("id", user.get("id"))
    now = time.time()
    with _lookup_lock:
        hit = _lookups.get(key)
        if hit and hit[0] > now:
            return hit[1]
    if key[0] == "username":
        data = graphql("BarcelonaUsernameHovercardImplDirectQuery", username=key[1])
    else:
        data = graphql("BarcelonaUserHovercardImplQuery", userID=key[1])
    raw = data.get("user")
    if not isinstance(raw, dict) or not (raw.get("pk") or raw.get("id")):
        raise ThreadsNotFound(f"{_describe(user)} not found on Threads")
    with _lookup_lock:
        if len(_lookups) > 5000:
            _lookups.clear()
        _lookups[key] = (now + LOOKUP_TTL, raw)
        uid = str(raw.get("pk") or raw.get("id"))
        _lookups[("id", uid)] = (now + LOOKUP_TTL, raw)
        if raw.get("username"):
            _lookups[("username", str(raw["username"]).lower())] = (now + LOOKUP_TTL, raw)
    return raw


def user_id(user):
    raw = lookup(user)
    return str(raw.get("pk") or raw.get("id"))


def resolve(user):
    """Username <-> numeric id, with the basic account facts."""
    raw = lookup(user)
    out = P.user_ref(raw)
    out["biography"] = P.clean(raw.get("biography"))
    out["follower_count"] = P.to_int(raw.get("follower_count"))
    return out


def get_profile(user):
    """The full profile: bio, bio links, follower count, topics."""
    uid = user_id(user)
    data = graphql("BarcelonaProfilePageDirectQuery", userID=uid, canSeeFeedsTab=False, showLinkedIGStats=False)
    parsed = P.profile(data.get("user"))
    if parsed is None:
        raise ThreadsNotFound(f"{_describe(user)} not found on Threads")
    return parsed


def _tab(user, tab, cursor):
    raw_user = lookup(user)
    uid = str(raw_user.get("pk") or raw_user.get("id"))
    try:
        data = graphql(TAB_QUERIES[tab], retry_execution_errors=not cursor, userID=uid, after=cursor,
                       before=None, first=PAGE_SIZE, last=None, allow_page_info_for_lox_user=True)
    except ThreadsExecutionError:
        if cursor:
            raise ThreadsBadRequest(INVALID_CURSOR)
        raise
    connection = data.get("mediaData") or {}
    threads = P.threads_list(connection.get("edges"))
    next_cursor, has_more = P.page_info(connection)
    return {
        "user": P.user_ref(raw_user),
        "thread_count": len(threads),
        "threads": threads,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def get_threads(user, cursor=None):
    """The user's own threads (the profile's Threads tab), newest first.
    A thread is one post or an author's self-thread chain."""
    return _tab(user, "threads", cursor)


def get_replies(user, cursor=None):
    """The user's replies, each shown under the post it answers (posts[0]
    is the parent, the last post is the user's reply)."""
    return _tab(user, "replies", cursor)


def get_media(user, cursor=None):
    """The user's posts with photos or videos (the Media tab)."""
    return _tab(user, "media", cursor)


def get_reposts(user, cursor=None):
    """What the user reposted: each post is a `repost` wrapper whose
    `reposted_post` is the original."""
    return _tab(user, "reposts", cursor)
