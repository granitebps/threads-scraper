"""Post endpoints: details, media, replies, parent posts, related threads
and id resolution.

`post` is the numeric post id from refs.resolve_post (a shortcode, numeric
id or threads.com post link — the shortcode decodes to the id locally).

Details, media and related come from the logged-out GraphQL. Replies and
parent posts do NOT: logged out, BarcelonaPostPageDownwardQuery and
UpwardQuery answer `direct_replies` / `containing_thread` as null, while the
post page itself is server-rendered with both preloaded (first 8 direct
replies, the author's self-thread, pinned replies, the chain of parent
posts). So those two read the page (`/t/<code>`, which redirects to the
canonical `/@user/post/<code>`). More replies than the page preloads need a
logged-in session — the site shows "Log in to see more replies" — so the
replies endpoint reports `has_more` but no cursor.
"""
from . import parsers as P
from . import refs
from .fetch import ThreadsNotFound, graphql
from .ssr import load

RELATED_OWNER_POSTS = 10


def _target(post):
    data = graphql("BarcelonaPostPageTargetQuery", postID=post)
    media = data.get("media")
    if not isinstance(media, dict) or not media.get("pk"):
        raise ThreadsNotFound(f"post {refs.id_to_code(post)} not found")
    return media


def get_details(post):
    """One post with everything: text, stats, media, link preview, quoted /
    reposted / embedded post, mentions, links, topic, music."""
    return P.post(_target(post))


def get_media(post):
    """Every image size and video rendition of the post's media (each
    carousel slide separately), for downloading."""
    return P.post_media(_target(post))


def resolve(post):
    """Shortcode <-> numeric id, with the canonical link and the author."""
    raw = _target(post)
    parsed = P.post(raw)
    return {
        "id": parsed["id"],
        "code": parsed["code"],
        "link": parsed["link"],
        "author": parsed["author"],
        "published_at": parsed["published_at"],
    }


def get_related(post):
    """Threads the site recommends under the post, plus more threads from
    the same author. (relatedPosts.trending_threads is always null logged
    out and is not exposed.)"""
    raw = _target(post)
    owner = P.to_id((raw.get("user") or {}).get("pk")) if isinstance(raw.get("user"), dict) else None
    data = graphql("BarcelonaLoggedOutRelatedPostsQuery", targetPostID=post, ownerID=owner,
                   ownerPostsCount=RELATED_OWNER_POSTS, relatedPostIgids=None,
                   skipOwnerThreads=owner is None, skipRelatedPosts=False, trendingKeyword=None)
    related = P.threads_list((data.get("relatedPosts") or {}).get("threads"))
    from_author = P.threads_list((data.get("ownerThreads") or {}).get("edges"))
    from_author = [t for t in from_author if t["posts"] and t["posts"][0]["id"] != post]
    return {
        "post_id": post,
        "related_thread_count": len(related),
        "related_threads": related,
        "author_thread_count": len(from_author),
        "author_threads": from_author,
    }


def _page(post):
    code = refs.id_to_code(post)
    data, _ = load(f"/t/{code}", label=f"post {code}", required="BarcelonaPostPageTargetQuery")
    target = (data.get("BarcelonaPostPageTargetQuery") or {}).get("media")
    if not isinstance(target, dict) or not target.get("pk"):
        raise ThreadsNotFound(f"post {code} not found")
    return data, target


def get_replies(post):
    """The post's direct replies as the page shows them logged out (the
    first ~8, each with the reply chain the site expands under it), plus
    pinned replies and the author's self-thread continuation."""
    data, target = _page(post)
    info = ((data.get("BarcelonaPostPageDownwardQuery") or {}).get("media") or {}).get("text_post_app_info") or {}
    direct = info.get("direct_replies") or {}
    replies = []
    for edge in direct.get("edges") or []:
        posts = P.thread_view_posts((edge or {}).get("node"))
        if posts:
            replies.append({"id": posts[0]["id"], "posts": posts, "parent_post_unavailable_reason": None})
    pinned = []
    for edge in (info.get("pinned_replies") or {}).get("edges") or []:
        posts = P.thread_view_posts((edge or {}).get("node"))
        if posts:
            pinned.append({"id": posts[0]["id"], "posts": posts, "parent_post_unavailable_reason": None})
    _, has_more = P.page_info(direct)
    parsed = P.post(target)
    return {
        "post": parsed,
        "reply_count": (parsed.get("stats") or {}).get("reply_count"),
        "returned_reply_count": len(replies),
        "replies": replies,
        "pinned_replies": pinned,
        "self_thread": P.thread_view_posts(info.get("self_thread")),
        "has_more": has_more,
        "has_unavailable_replies": P.to_bool(info.get("has_unavailable_replies")),
    }


def get_parent_posts(post):
    """For a reply: the chain of posts above it, root post first."""
    data, target = _page(post)
    info = ((data.get("BarcelonaPostPageUpwardQuery") or {}).get("media") or {}).get("text_post_app_info") or {}
    parents = P.thread_view_posts(info.get("containing_thread"))
    parents = [p for p in parents if p["id"] != post]
    return {
        "post": P.post(target),
        "reply_level": P.to_int(info.get("reply_level")),
        "parent_post_count": len(parents),
        "parent_posts": parents,
    }

