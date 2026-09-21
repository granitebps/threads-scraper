"""Offline tests for the Threads refs, SSR extractor and parsers — no network.

Every fixture in threads/fixtures/ is a real upstream payload captured on
2026-09-21 through threads/fetch.py: the logged-out GraphQL `data` objects
verbatim (lists trimmed to a few edges, DASH manifests and tracking tokens
blanked) and the Relay results the post / tag pages preload. The assertions
pin the field mapping decoded from live data, so a silent upstream rename
shows up here rather than as nulls in a customer's response.

    python -m pytest threads/test_parsers.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from threads import discovery, parsers as P, queries, refs, schemas, ssr  # noqa: E402
from schema_fields import load_query  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


# ---- refs --------------------------------------------------------------------------------

def test_code_and_id_round_trip():
    assert refs.code_to_id("DdZ7sQvkTFn") == "3988481471392330087"
    assert refs.id_to_code("3988481471392330087") == "DdZ7sQvkTFn"
    assert refs.code_to_id("Db2gd-oFEiA") == "3960495719916521600"


@pytest.mark.parametrize("value", [
    "zuck", "@zuck", "@Zuck", " ZUCK ",
    "https://www.threads.com/@zuck", "https://www.threads.net/@zuck/",
    "threads.com/@zuck", "https://www.threads.com/@zuck/post/DdZ7sQvkTFn",
])
def test_user_ref_username_forms(value):
    assert refs.resolve_user(value) == {"id": None, "username": "zuck"}


def test_user_ref_id_and_forced_username():
    assert refs.resolve_user("63055343223") == {"id": "63055343223", "username": None}
    assert refs.resolve_user("@123") == {"id": None, "username": "123"}


@pytest.mark.parametrize("value", ["", "not a user!", "https://instagram.com/zuck", "https://www.threads.com/search?q=x",
                                   "a" * 31])
def test_user_ref_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


@pytest.mark.parametrize("value", [
    "DdZ7sQvkTFn", "3988481471392330087", "3988481471392330087_63055343223",
    "https://www.threads.com/@zuck/post/DdZ7sQvkTFn", "https://www.threads.net/@zuck/post/DdZ7sQvkTFn/media",
    "https://www.threads.com/t/DdZ7sQvkTFn", "www.threads.com/@zuck/post/DdZ7sQvkTFn?xmt=abc",
])
def test_post_ref_forms(value):
    assert refs.resolve_post(value) == "3988481471392330087"


@pytest.mark.parametrize("value", ["", "https://example.com/t/DdZ7sQvkTFn", "https://www.threads.com/@zuck", "no spaces allowed"])
def test_post_ref_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_post(value)


def test_tag_ref_forms():
    assert refs.resolve_tag("#python") == {"name": "python", "id": None}
    assert refs.resolve_tag("https://www.threads.com/tag/python") == {"name": "python", "id": None}
    assert refs.resolve_tag("https://www.threads.com/search?q=AI%20Threads&serp_type=tags&tag_id=18399895213044171") == \
        {"name": "AI Threads", "id": "18399895213044171"}
    with pytest.raises(ValueError):
        refs.resolve_tag("#")


def test_tag_link_forms():
    assert refs.tag_link("python") == "https://www.threads.com/tag/python"
    assert refs.tag_link("AI Threads", "18399895213044171") == \
        "https://www.threads.com/search?q=AI+Threads&serp_type=tags&tag_id=18399895213044171"


# ---- schemas -----------------------------------------------------------------------------

def test_schemas_resolve_and_reject():
    data, error = load_query(schemas.UserPageSchema, {"user": "https://www.threads.net/@Zuck"})
    assert error is None and data == {"user": {"id": None, "username": "zuck"}, "cursor": None}
    data, error = load_query(schemas.PostSchema, {"post": "https://www.threads.com/t/DdZ7sQvkTFn"})
    assert data == {"post": "3988481471392330087"}
    data, error = load_query(schemas.FeedSchema, {"country": "gb"})
    assert data == {"country": "GB", "cursor": None}
    data, error = load_query(schemas.FeedSchema, {})
    assert data["country"] == "US"
    _, error = load_query(schemas.PostSchema, {"post": "DdZ7sQvkTFn", "url": "x"})
    assert error and "url" in error["errors"]
    _, error = load_query(schemas.UserSearchSchema, {"query": "nasa", "limit": "51"})
    assert error and "limit" in error["errors"]
    _, error = load_query(schemas.PostSearchSchema, {"query": "python", "sort": "new"})
    assert error and "sort" in error["errors"]


# ---- queries -----------------------------------------------------------------------------

def test_variables_carry_every_declared_provider():
    for name, query in queries.QUERIES.items():
        variables = queries.variables_for(name, x=1)
        assert variables["x"] == 1
        for provider in query["providers"]:
            assert isinstance(variables[f"__relay_internal__pv__{provider}relayprovider"], bool), (name, provider)
    assert queries.PROVIDER_VALUES["BarcelonaIsLoggedOut"] is True
    assert queries.PROVIDER_VALUES["BarcelonaIsLoggedIn"] is False


# ---- ssr ---------------------------------------------------------------------------------

def _page(entries, attrs='type="application/json" data-content-len="10" data-sjs'):
    blob = {"require": [["ScheduledServerJS", "handle", None, [{"__bbox": {"require": [
        ["RelayPrefetchedStreamCache", "next", [], [key, {"__bbox": {"complete": True, "result": {"data": data}}}]]
        for key, data in entries]}}]]]}
    return f'<html><head><meta property="og:title" content="python &#xb7; 2.4M threads" /></head>' \
           f'<body><script {attrs}>{json.dumps(blob)}</script></body></html>'


def test_ssr_prefetched_and_og():
    html = _page([("adp_BarcelonaPostPageTargetQueryRelayPreloader_6ab0fd", {"media": {"pk": "1"}})])
    assert ssr.prefetched(html) == {"BarcelonaPostPageTargetQuery": {"media": {"pk": "1"}}}
    assert ssr.og_meta(html)["og:title"] == "python · 2.4M threads"
    # attribute order / missing data-content-len must not matter
    html = _page([("adp_XQueryRelayPreloader_1", {"a": 1})], attrs='data-sjs type="application/json"')
    assert ssr.prefetched(html) == {"XQuery": {"a": 1}}
    assert ssr.prefetched("<html>no data</html>") == {}


def test_tag_counts():
    assert discovery.tag_counts({"og:title": "python · 2.4M threads",
                                 "og:description": "9.3K recent threads · Discover conversations"}) == (2_400_000, 9_300)
    assert discovery.tag_counts({"og:title": "arsenalthreads · 2,812 threads",
                                 "og:description": "8 recent threads · Discover"}) == (2812, 8)
    assert discovery.tag_counts({"og:title": "zzqq", "og:description": "Discover conversations"}) == (None, None)


# ---- users -------------------------------------------------------------------------------

def test_profile_zuck():
    out = P.profile(load("profile_zuck.json")["user"])
    assert out["id"] == "63055343223" and out["username"] == "zuck"
    assert out["full_name"] == "Mark Zuckerberg" and out["link"] == "https://www.threads.com/@zuck"
    assert isinstance(out["follower_count"], int) and out["follower_count"] > 1_000_000
    assert out["is_verified"] is True and out["is_private"] is False
    assert "s640x640" in out["profile_picture"]                      # largest HD version
    assert out["topics"] and out["topics"][0]["name"] == "AI Threads"
    assert out["topics"][0]["id"] == "18399895213044171"
    assert list(out)[:4] == ["id", "username", "full_name", "link"]


def test_profile_bio_links():
    out = P.profile(load("profile_mosseri.json")["user"])
    assert out["bio_links"] == [{"link": "http://mosseri.net/", "title": None, "is_verified": False}]


def test_hovercard_missing_user_is_none():
    assert load("hovercard_missing.json")["user"] is None
    assert P.user_ref(None) is None and P.profile(None) is None


# ---- posts -------------------------------------------------------------------------------

def test_text_post():
    out = P.post(load("post_text.json")["media"])
    assert out["id"] == "3988481471392330087" and out["code"] == "DdZ7sQvkTFn"
    assert out["link"] == "https://www.threads.com/@zuck/post/DdZ7sQvkTFn"
    assert out["type"] == "text" and out["media"] is None
    assert out["text"].startswith("Muse for Mac is out today!")
    assert out["published_at"] == "2026-09-17T22:27:44Z"
    stats = out["stats"]
    assert all(isinstance(stats[k], int) for k in ("like_count", "reply_count", "repost_count", "quote_count", "share_count"))
    assert out["links"] == [{"link": "http://ai.meta.com/muse/download", "display_text": "ai.meta.com/muse…"}]
    assert out["author"]["username"] == "zuck" and out["reply_control"] == "everyone"
    assert list(out)[:3] == ["id", "code", "link"]


def test_video_post():
    out = P.post(load("post_video.json")["media"])
    assert out["type"] == "video"
    media = out["media"]
    assert media["type"] == "video" and media["width"] == 1080 and media["height"] == 1920
    assert media["video"].startswith("https://") and media["image"].startswith("https://")
    assert media["has_audio"] is True and media["items"] == []


def test_carousel_post_and_media_endpoint():
    raw = load("post_carousel.json")["media"]
    out = P.post(raw)
    assert out["type"] == "carousel" and len(out["media"]["items"]) == 10
    first = out["media"]["items"][0]
    assert first["type"] == "image" and first["image"].startswith("https://") and first["video"] is None
    full = P.post_media(raw)
    assert full["item_count"] == 10
    sizes = full["items"][0]["images"]
    assert len(sizes) > 3 and sizes[0]["width"] >= sizes[-1]["width"]
    assert len({(s["width"], s["height"]) for s in sizes}) == len(sizes)   # no duplicate sizes


def test_repost_wrapper():
    out = P.post(load("post_repost.json")["media"])
    assert out["type"] == "repost" and out["media"] is None and out["text"] is None
    inner = out["reposted_post"]
    assert inner["author"]["username"] == "meta" and inner["type"] == "video"
    assert inner["reposted_post"] is None           # nesting stops one level down


def test_reply_post():
    out = P.post(load("post_reply.json")["media"])
    assert out["is_reply"] is True
    assert out["replied_to_user"]["username"] == "merab.dvalishvili"
    assert out["thread_author"]["username"] == "merab.dvalishvili"


def test_missing_post_is_none():
    assert load("post_missing.json")["media"] is None
    assert P.post(None) is None and P.post({}) is None


def test_post_never_crashes_on_partial_input():
    partial = {"pk": "3988481471392330087", "text_post_app_info": None, "user": "garbage", "caption": [],
               "image_versions2": {"candidates": [None, {"url": ""}]}, "carousel_media": "x", "video_versions": [{}],
               "taken_at": "not a number"}
    out = P.post(partial)
    assert out["id"] == "3988481471392330087" and out["code"] == "DdZ7sQvkTFn"
    assert out["author"] is None and out["media"] is None and out["published_at"] is None
    assert out["link"] == "https://www.threads.com/t/DdZ7sQvkTFn"


def test_unwrap_link():
    assert P.unwrap_link("https://l.threads.com/?u=https%3A%2F%2Fwww.tiobe.com%2Ftiobe-index%2F&e=AT") == \
        "https://www.tiobe.com/tiobe-index/"
    assert P.unwrap_link("https://example.com/a") == "https://example.com/a"
    assert P.unwrap_link("") is None


# ---- lists -------------------------------------------------------------------------------

def test_profile_tabs():
    posts = load("tab_posts.json")["mediaData"]
    threads = P.threads_list(posts["edges"])
    assert len(threads) == 6 and all(t["posts"][0]["author"]["username"] == "zuck" for t in threads)
    assert any(len(t["posts"]) > 1 for t in threads)                  # self-thread chains
    cursor, more = P.page_info(posts)
    assert more is True and cursor

    replies = P.threads_list(load("tab_replies.json")["mediaData"]["edges"])
    assert all(len(t["posts"]) == 2 for t in replies)
    assert replies[0]["posts"][-1]["author"]["username"] == "zuck" and replies[0]["posts"][-1]["is_reply"] is True

    reposts = P.threads_list(load("tab_reposts.json")["mediaData"]["edges"])
    assert reposts[0]["posts"][0]["type"] == "repost" and reposts[0]["posts"][0]["reposted_post"]


def test_search_feed_and_related_containers():
    assert len(P.threads_list(load("search_top.json")["searchResults"]["edges"])) == 4
    assert len(P.threads_list(load("search_recent.json")["searchResults"]["edges"])) == 3
    assert len(P.threads_list(load("feed.json")["feedData"]["edges"])) == 4
    related = load("related.json")
    assert len(P.threads_list(related["relatedPosts"]["threads"])) == 3
    assert len(P.threads_list(related["ownerThreads"]["edges"])) == 3
    users = [P.user_ref(e["node"]) for e in load("search_users.json")["searchResults"]["edges"]]
    assert users[0]["username"] == "zuck" and users[0]["id"] == "63055343223"


def test_post_page_replies_and_parents():
    page = load("page_post.json")
    info = page["BarcelonaPostPageDownwardQuery"]["media"]["text_post_app_info"]
    first = P.thread_view_posts(info["direct_replies"]["edges"][0]["node"])
    assert first and first[0]["is_reply"] is True
    assert P.page_info(info["direct_replies"])[1] is True
    reply_page = load("page_reply.json")
    up = reply_page["BarcelonaPostPageUpwardQuery"]["media"]["text_post_app_info"]
    parents = P.thread_view_posts(up["containing_thread"])
    assert [p["author"]["username"] for p in parents] == ["merab.dvalishvili"]


def test_tag_page_fixture():
    page = load("page_tag.json")
    assert discovery.tag_counts(page["og"])[0] == 2_400_000
    assert len(P.threads_list(page["BarcelonaSearchResultsQuery"]["searchResults"]["edges"])) == 3


def test_malformed_edges_are_skipped():
    assert P.threads_list([None, 1, {}, {"node": {"thread_items": [{"post": None}]}}]) == []
    assert P.page_info(None) == (None, False)
    assert P.page_info({"page_info": {"has_next_page": True, "end_cursor": ""}}) == (None, False)


# ---- search variables (regression: upper-case surface = unrelated results) -----------

def test_search_sends_lowercase_surfaces_and_int_recent(monkeypatch):
    calls = []

    def fake_graphql(name, **variables):
        calls.append((name, variables))
        return {"searchResults": {"edges": []}}

    monkeypatch.setattr(discovery, "graphql", fake_graphql)
    monkeypatch.setattr(discovery, "load", lambda *a, **k: ({}, '<meta property="og:title" content="ai · 1.2M threads" />'))
    discovery.search_posts("SpaceX")
    discovery.search_posts("SpaceX", sort="recent")
    discovery.search_users("nasa", 5)
    out = discovery.search_tag({"name": "ai", "id": None})
    surfaces = [(name.replace("Barcelona", ""), v["search_surface"], v.get("recent")) for name, v in calls]
    assert surfaces == [("SearchResultsRefetchableQuery", "default", 0), ("SearchResultsRefetchableQuery", "default", 1),
                        ("SearchUserResultsQuery", "default", None), ("SearchResultsRefetchableQuery", "tags", 0)]
    assert out["tag"]["thread_count"] == 1_200_000
