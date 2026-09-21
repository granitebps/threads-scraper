"""Discovery endpoints: post search, user search, tag / topic feeds and the
logged-out home feed.

What logged-out Threads serves (probed 2026-09-21):
  * post search: ONE page — 20 "top" or ~8 "recent" threads; page_info
    says has_next_page false and the site shows "Log in for more threads
    about this topic". No cursor exists to expose.
  * user search: up to 50 accounts in one call (first=50 honoured), no
    further pages.
  * tag feeds: the tag search surface (search_surface="tags", ~20
    threads); the tag's total and recent thread counts only exist in the
    /tag/<hashtag> page's og:title / og:description ("python · 2.4M threads",
    "9.3K recent threads · …") — that page's own thread list is an unrelated
    recent stream and is not used. Topic chips (tags with an id, e.g. "AI
    Threads") have no counts. An unknown tag returns no threads (no 404).
  * home feed: the "For you" feed the site shows logged-out visitors,
    localised by `specified_country`, ~12 threads then ~10 more, cursor
    paged until has_next_page is false.
"""
import re
from urllib.parse import quote

from . import parsers as P
from . import refs
from .fetch import ThreadsBadRequest, ThreadsExecutionError, graphql, run_parallel
from .ssr import load, og_meta
from .users import INVALID_CURSOR

# search_surface is lower case, exactly as the web app sends it: "default"
# for post search, "tags" for a tag / topic feed. The upper-case "DEFAULT"
# (or null) is NOT rejected — it silently returns an unrelated stream of
# recent posts with only a few keyword hits (found 2026-09-21: "SpaceX" top
# results were Taiwanese stock tips). `recent` is an int 0/1, not a bool.
_SEARCH_DEFAULTS = dict(
    after=None, before=None, first=25, last=None, meta_place_id=None,
    pinned_ids=None, power_search_info=None, tagID=None, trend_fbid=None, has_communities=False,
    has_community_green_dot=False, has_favicons=False, has_live_chats=False, has_serp_header=False,
)
_COUNT_RE = re.compile(r"([\d.,]+)\s*([KMB])?\s+(?:recent\s+)?threads?\b", re.I)
_SCALE = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def search_posts(query, sort="top"):
    """Threads matching the query, as the site's search shows them."""
    data = graphql("BarcelonaSearchResultsRefetchableQuery", query=query, search_surface="default",
                   recent=1 if sort == "recent" else 0, **_SEARCH_DEFAULTS)
    threads = P.threads_list((data.get("searchResults") or {}).get("edges"))
    return {"query": query, "sort": sort, "thread_count": len(threads), "threads": threads}


def search_users(query, limit=20):
    """Accounts matching the query (username, name)."""
    data = graphql("BarcelonaSearchUserResultsQuery", query=query, search_surface="default",
                   after=None, before=None, first=limit, last=None)
    users = []
    for edge in (data.get("searchResults") or {}).get("edges") or []:
        node = (edge or {}).get("node") if isinstance(edge, dict) else None
        ref = P.user_ref(node)
        if ref:
            ref["biography"] = P.clean((node or {}).get("biography"))
            users.append(ref)
    users = users[:limit]
    return {"query": query, "user_count": len(users), "users": users}


def parse_count(text):
    """'2.4M threads' -> 2400000, '9.3K recent threads' -> 9300, '812 threads' -> 812."""
    match = _COUNT_RE.search(text or "")
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(round(number * _SCALE.get((match.group(2) or "").upper(), 1)))


def tag_counts(og):
    """(thread_count, recent_thread_count) from a tag page's og tags. Both
    are the site's rounded display figures (2.4M = 2,400,000)."""
    title = og.get("og:title") or ""
    description = og.get("og:description") or ""
    total = parse_count(title.split("·", 1)[1]) if "·" in title else None
    recent = parse_count(description.split("·", 1)[0]) if "recent" in description.split("·", 1)[0].lower() else None
    return total, recent


def search_tag(tag):
    """Threads under a hashtag or topic, with the tag's thread counts.

    The threads come from the tag search surface (the site's
    /search?serp_type=tags results); the /tag/<name> page is read only for
    its og counts — its own preloaded list is an unrelated stream of recent
    posts, not the tag's threads."""
    name, tag_id = tag["name"], tag.get("id")

    def threads_call():
        variables = dict(_SEARCH_DEFAULTS, tagID=tag_id)
        return graphql("BarcelonaSearchResultsRefetchableQuery", query=name, search_surface="tags", recent=0,
                       **variables)

    def counts_call():
        if tag_id or " " in name:          # topic chips: no /tag/ page with counts
            return None, None
        _, html = load("/tag/" + quote(name, safe=""), label=f"tag {name}", required="BarcelonaSearchResultsQuery")
        return tag_counts(og_meta(html))

    data, (total, recent) = run_parallel([threads_call, counts_call])
    threads = P.threads_list((data.get("searchResults") or {}).get("edges"))
    return {
        "tag": {
            "id": tag_id,
            "name": name,
            "link": refs.tag_link(name, tag_id),
            "thread_count": total,
            "recent_thread_count": recent,
        },
        "thread_count": len(threads),
        "threads": threads,
    }


def get_feed(country="US", cursor=None):
    """The logged-out "For you" feed for a country."""
    country = country or "US"   # an explicit empty ?country= validates to None
    variables = dict(after=cursor, before=None, first=25, last=None, injected_media_ids=None,
                     specified_country=country)
    name = "BarcelonaLoggedOutFeedPaginationQuery" if cursor else "BarcelonaLoggedOutFeedContainerQuery"
    try:
        data = graphql(name, retry_execution_errors=not cursor, **variables)
    except ThreadsExecutionError:
        if cursor:
            raise ThreadsBadRequest(INVALID_CURSOR)
        raise
    connection = data.get("feedData") or {}
    threads = P.threads_list(connection.get("edges"))
    next_cursor, has_more = P.page_info(connection)
    return {"country": country, "thread_count": len(threads), "threads": threads,
            "next_cursor": next_cursor, "has_more": has_more}
