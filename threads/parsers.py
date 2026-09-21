"""Threads normalizers: the web app's Relay objects (logged-out GraphQL and
the same data preloaded into pages) -> one clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical threads.com URLs, `image` / `video` / `profile_picture` for
media URLs, `*_count` for counters, `is_*` / `has_*` for booleans,
ISO-8601 UTC timestamps (the upstream's epoch seconds), numbers as numbers,
null for missing, [] for empty lists. Ids stay STRINGS: post and user ids
are 17-20 digits and overflow a JavaScript number.

Entity shapes:
  user (compact)  {id, username, full_name, link, profile_picture,
                   is_verified, is_private}
  profile         compact user + biography, bio_links, bio_mentions,
                   follower_count, topics, transparency_label
  post            {id, code, link, type, text, language, published_at,
                   topic, stats{...}, flags, author, media, link_preview,
                   gif, music, quoted_post, reposted_post, embedded_post,
                   mentions, links, stickers, replied_to_user,
                   thread_author, content_overlay, ai_detection_method}
  thread          {id, posts[...], parent_post_unavailable_reason}
                   A thread is what every Threads list is made of: one post,
                   or a chain (a reply shown under its parent, an author's
                   self-thread).

Post `type` is decoded from media_type: 19 text, 1 image, 2 video,
8 carousel, 18 repost (a wrapper whose content is `reposted_post`).

Deliberately dropped as noise:
  tracking   logging_info_token, organic_tracking_token, __token,
             __typename, fetch_token, session_id
  duplicates the composite `id` ("<post>_<user>"; `pk` kept as id), fbid
             and caption.pk (internal Facebook ids of the same post),
             text_post_app_info.id, video_dash_manifest (an XML rendition
             of video_versions), is_dash_eligible, number_of_qualities,
             lynx_url (click-tracking redirect of a bio link; the target
             `url` is kept), link_id, the l.threads.com wrapper around link
             previews (decoded to the destination), tag_cluster_name (=
             display_name), user.id (= pk), text_fragments plaintext pieces
             (the caption carries the full text)
  viewer     friendship_status, has_viewer_saved, can_reply,
             can_private_reply, show_header_follow, reply_approval_info,
             hush_info, private_reply_partner, author_notif_control,
             gen_ai_reply_bot_on_media_deny_reason — the logged-out viewer's
             own state, always null/false here
  always null logged out / unused by the web app: seo_ocr_for_related_post,
             seo_transcript_for_related_post, canonical_url,
             triage_comments, audience, metaPlace/meta_place, usertags,
             is_paid_partnership (null on all 422 posts sampled),
             caption_add_on, transcription_data, text_app_glimmer_post_info,
             algo_tweaks_info, custom_feed_preview_info, game_score_share_info,
             public_view_count_card_attachment_info,
             community_emoji_update_attachment_info,
             platform_podcast_info, text_post_app_public_views,
             ghost_post_* (ephemeral "ghost posts", never served logged out)
  presentation view_replies_cta_string ("Show replies"),
             inline_expansion_info, can_inline_expand_below,
             special_effects_enabled_str, styling_info, tappable_elements,
             show_text_post_app_badge, interop_messaging_user_fbid, is_meta_ai_bot
             (absent from profile queries),
             transparency_product(_enabled), has_onboarded_to_text_post_app,
             linkified_* (in-app deep links duplicating link fragments),
             image candidates other than the largest on list/detail
             responses (all sizes are on /posts/media)
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from . import refs

MEDIA_TYPES = {19: "text", 1: "image", 2: "video", 8: "carousel", 18: "repost"}


# ---- scalars ---------------------------------------------------------------------------

def clean(value):
    """Whitespace-trimmed string, or None for empty / non-strings."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def to_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


def to_bool(value):
    """True/False for real booleans (and 0/1), None when absent."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def to_id(value):
    """An upstream numeric id as a string (they exceed 2**53)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def iso_utc(epoch):
    """Epoch seconds -> 2026-09-17T14:27:44Z."""
    seconds = to_int(epoch)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def unwrap_link(url):
    """https://l.threads.com/?u=<target>&e=... -> <target> (the click-tracking
    redirect Threads puts around outbound links); anything else unchanged."""
    text = clean(url)
    if not text:
        return None
    parsed = urlparse(text)
    if (parsed.hostname or "").startswith("l.threads.") or (parsed.hostname or "").startswith("l.instagram."):
        target = (parse_qs(parsed.query).get("u") or [None])[0]
        return clean(target) or text
    return text


def lower_token(value):
    text = clean(value)
    return text.lower() if text else None


# ---- images / video ----------------------------------------------------------------------

def image_sizes(candidates):
    """[{link, width, height}] largest first, duplicates (same size) dropped."""
    out, seen = [], set()
    rows = [c for c in _list(candidates) if isinstance(c, dict) and clean(c.get("url"))]
    rows.sort(key=lambda c: (to_int(c.get("width")) or 0) * (to_int(c.get("height")) or 0), reverse=True)
    for c in rows:
        size = (to_int(c.get("width")), to_int(c.get("height")))
        if size in seen:
            continue
        seen.add(size)
        out.append({"link": clean(c.get("url")), "width": size[0], "height": size[1]})
    return out


def best_image(candidates):
    sizes = image_sizes(candidates)
    return sizes[0]["link"] if sizes else None


def video_versions(versions):
    """[{link, type}] in upstream order (the first is what the web player
    picks). `type` is Instagram's rendition code (101/102/103)."""
    return [{"link": clean(v.get("url")), "type": to_int(v.get("type"))}
            for v in _list(versions) if isinstance(v, dict) and clean(v.get("url"))]


def best_video(versions):
    rows = video_versions(versions)
    return rows[0]["link"] if rows else None


def _candidates(raw):
    return _dict(raw.get("image_versions2")).get("candidates")


# ---- users ---------------------------------------------------------------------------------

def user_ref(raw):
    """Compact user: an author, a mention, a search hit."""
    raw = _dict(raw)
    username = clean(raw.get("username"))
    user_id = to_id(raw.get("pk") or raw.get("id"))
    if not username and not user_id:
        return None
    hd = image_sizes(raw.get("hd_profile_pic_versions"))
    return {
        "id": user_id,
        "username": username,
        "full_name": clean(raw.get("full_name")),
        "link": refs.user_link(username),
        "profile_picture": hd[0]["link"] if hd else clean(raw.get("profile_pic_url")),
        "is_verified": to_bool(raw.get("is_verified")),
        "is_private": to_bool(raw.get("text_post_app_is_private")),
    }


def text_entities(fragments_holder):
    """Mentions, links and stickers out of a text_fragments block."""
    mentions, links, stickers = [], [], []
    for frag in _list(_dict(_dict(fragments_holder).get("text_fragments")).get("fragments")):
        if not isinstance(frag, dict):
            continue
        mention = _dict(_dict(frag.get("mention_fragment")).get("mentioned_user"))
        if mention:
            ref = user_ref(mention)
            if ref:
                mentions.append({"id": ref["id"], "username": ref["username"], "link": ref["link"]})
        link = _dict(frag.get("link_fragment"))
        if link and clean(link.get("uri")):
            links.append({"link": unwrap_link(link.get("uri")), "display_text": clean(link.get("display_text"))})
        sticker = _dict(frag.get("inline_sticker_fragment"))
        if sticker and (clean(sticker.get("sticker_url")) or clean(sticker.get("sticker_id"))):
            stickers.append({"id": clean(sticker.get("sticker_id")), "image": clean(sticker.get("sticker_url"))})
    return mentions, links, stickers


def topic(raw):
    """A topic tag (tag_header on posts, profile_tags on profiles)."""
    raw = _dict(raw)
    name = clean(raw.get("display_name")) or clean(raw.get("name")) or clean(raw.get("tag_cluster_name"))
    if not name:
        return None
    tag_id = to_id(raw.get("id"))
    return {
        "id": tag_id,
        "name": name,
        "link": refs.tag_link(name, tag_id),
        "is_community": to_bool(raw.get("is_community")),
        "emoji": clean(raw.get("community_emoji")),
    }


def _label(value):
    if isinstance(value, dict):
        for key in ("label", "text", "title", "name"):
            if clean(value.get(key)):
                return clean(value.get(key))
        return None
    return clean(value)


def profile(raw):
    """Full profile (BarcelonaProfilePageDirectQuery.user)."""
    raw = _dict(raw)
    base = user_ref(raw)
    if base is None:
        return None
    mentions, bio_links_inline, _ = text_entities(raw.get("text_app_biography"))
    bio_links = []
    for link in _list(raw.get("bio_links")):
        if isinstance(link, dict) and clean(link.get("url")):
            bio_links.append({"link": clean(link.get("url")), "title": clean(link.get("title")),
                              "is_verified": to_bool(link.get("is_verified"))})
    known = {b["link"] for b in bio_links}
    for link in bio_links_inline:
        if link["link"] not in known:
            bio_links.append({"link": link["link"], "title": link["display_text"], "is_verified": None})
    topics = [t for t in (topic(_dict(e).get("node")) for e in _list(_dict(raw.get("profile_tags")).get("edges"))) if t]
    return {
        "id": base["id"],
        "username": base["username"],
        "full_name": base["full_name"],
        "link": base["link"],
        "biography": clean(raw.get("biography")),
        "follower_count": to_int(raw.get("follower_count")),
        "is_verified": base["is_verified"],
        "is_private": base["is_private"],
        "profile_picture": base["profile_picture"],
        "bio_links": bio_links,
        "bio_mentions": mentions,
        "topics": topics,
        "transparency_label": _label(raw.get("transparency_label")),
    }


# ---- posts ---------------------------------------------------------------------------------

def media(raw):
    """The post's own media (None for text-only posts and repost wrappers):
    {type, width, height, image, video, has_audio, accessibility_caption,
    items[]} — carousel slides in `items`, each with the same fields."""
    raw = _dict(raw)
    carousel = [m for m in _list(raw.get("carousel_media")) if isinstance(m, dict)]
    image = best_image(_candidates(raw))
    video = best_video(raw.get("video_versions"))
    if not carousel and not image and not video:
        return None
    kind = "carousel" if carousel else ("video" if video else "image")
    return {
        "type": kind,
        "width": to_int(raw.get("original_width")),
        "height": to_int(raw.get("original_height")),
        "image": image if not carousel else (best_image(_candidates(carousel[0])) or image),
        "video": video,
        "has_audio": to_bool(raw.get("has_audio")),
        "accessibility_caption": clean(raw.get("accessibility_caption")),
        "items": [media_item(m) for m in carousel],
    }


def media_item(raw, full=False):
    """One carousel slide (or, with full=True, any media with every size)."""
    raw = _dict(raw)
    video = raw.get("video_versions")
    out = {
        "id": to_id(raw.get("pk")),
        "type": "video" if best_video(video) else "image",
        "width": to_int(raw.get("original_width")),
        "height": to_int(raw.get("original_height")),
        "image": best_image(_candidates(raw)),
        "video": best_video(video),
        "has_audio": to_bool(raw.get("has_audio")),
        "accessibility_caption": clean(raw.get("accessibility_caption")),
    }
    if full:
        out["images"] = image_sizes(_candidates(raw))
        out["videos"] = video_versions(video)
    return out


def link_preview(raw):
    raw = _dict(raw)
    target = unwrap_link(raw.get("url"))
    if not target and not clean(raw.get("title")):
        return None
    return {
        "link": target,
        "domain": clean(raw.get("display_url")),
        "title": clean(raw.get("title")),
        "description": clean(raw.get("description")),
        "image": clean(raw.get("image_url")),
        "favicon": clean(raw.get("favicon_url")),
    }


def gif(raw):
    """giphy_media_info -> {id, link, webp, width, height}."""
    raw = _dict(raw)
    images = _dict(raw.get("images"))
    best = _dict(images.get("fixed_height")) or next((_dict(v) for v in images.values() if isinstance(v, dict)), {})
    if not clean(best.get("url")) and not clean(best.get("webp")):
        return None
    return {
        "id": to_id(raw.get("id")),
        "link": clean(best.get("url")),
        "webp": clean(best.get("webp")),
        "width": to_int(best.get("width")),
        "height": to_int(best.get("height")),
    }


def music(raw):
    """text_app_music_info -> the song attached to a post."""
    info = _dict(raw)
    video = _dict(info.get("music_consumable_video"))
    meta = _dict(video.get("audio_metadata"))
    asset = _dict(meta.get("audio_asset"))
    title = clean(_dict(asset.get("display_title")).get("text"))
    if not title and not asset.get("song_id"):
        return None
    tags = [clean(_dict(t).get("name")) for t in _list(asset.get("tags"))]
    explicit = None
    if "Explicit" in tags:
        explicit = True
    elif "NotExplicit" in tags:
        explicit = False
    return {
        "id": to_id(asset.get("song_id")),
        "title": title,
        "artist": clean(_dict(asset.get("display_artist")).get("text")),
        "image": clean(_dict(asset.get("large_display_image")).get("downloadable_uri"))
        or clean(_dict(asset.get("display_image")).get("downloadable_uri")),
        "start_ms": to_int(video.get("audio_start_time_in_ms")),
        "is_explicit": explicit,
        "is_available": to_bool(info.get("is_available_for_consumption")),
    }


def content_overlay(raw):
    raw = _dict(raw)
    if not raw:
        return None
    return {"type": lower_token(raw.get("overlay_type")), "description": clean(raw.get("description"))}


def _author_ref(raw):
    ref = user_ref(raw)
    if ref is None:
        return None
    return {"id": ref["id"], "username": ref["username"], "link": ref["link"],
            "profile_picture": ref["profile_picture"]}


def post(raw, depth=0):
    """One post. Nested posts (quoted / reposted / embedded) are parsed one
    level deep: a quote of a quote stops at the inner post's own fields."""
    raw = _dict(raw)
    post_id = to_id(raw.get("pk")) or to_id(str(raw.get("id") or "").split("_")[0])
    code = clean(raw.get("code")) or (refs.id_to_code(post_id) if post_id and post_id.isdigit() else None)
    if not post_id and not code:
        return None
    info = _dict(raw.get("text_post_app_info"))
    author = user_ref(raw.get("user"))
    username = author["username"] if author else None
    share = _dict(info.get("share_info"))
    pinned = _dict(info.get("pinned_post_info"))
    mentions, links, stickers = text_entities(info)
    media_type = to_int(raw.get("media_type"))
    detection = lower_token(_dict(raw.get("gen_ai_detection_method")).get("detection_method"))
    nested = (lambda value: post(value, depth + 1) if depth < 1 and isinstance(value, dict) and value else None)
    return {
        "id": post_id,
        "code": code,
        "link": refs.post_link(username, code),
        "type": MEDIA_TYPES.get(media_type, str(media_type) if media_type is not None else None),
        "text": clean(_dict(raw.get("caption")).get("text")),
        "language": clean(raw.get("detected_language")),
        "published_at": iso_utc(raw.get("taken_at")),
        "topic": topic(info.get("tag_header")),
        "stats": {
            "like_count": to_int(raw.get("like_count")),
            "reply_count": to_int(info.get("direct_reply_count")),
            "repost_count": to_int(info.get("repost_count")),
            "quote_count": to_int(info.get("quote_count")),
            "share_count": to_int(info.get("reshare_count")),
        },
        "is_reply": to_bool(info.get("is_reply")),
        "is_edited": to_bool(raw.get("caption_is_edited")),
        "is_pinned_to_profile": to_bool(pinned.get("is_pinned_to_profile")),
        "is_pinned_to_parent": to_bool(pinned.get("is_pinned_to_parent_post")),
        "is_spoiler": to_bool(info.get("is_spoiler_media")),
        "is_liked_by_thread_author": to_bool(info.get("is_liked_by_root_author")),
        "is_like_count_hidden": to_bool(raw.get("like_and_view_counts_disabled")),
        "is_unavailable": to_bool(info.get("is_post_unavailable")),
        "unavailable_reason": clean(info.get("post_unavailable_reason")),
        "reply_control": lower_token(info.get("reply_control")),
        "self_thread_count": to_int(info.get("self_thread_count")),
        "author": author,
        "media": media(raw) if media_type != 18 else None,
        "link_preview": link_preview(info.get("link_preview_attachment")),
        "gif": gif(raw.get("giphy_media_info")),
        "music": music(raw.get("text_app_music_info")),
        "quoted_post": nested(share.get("quoted_post")),
        "reposted_post": nested(share.get("reposted_post")),
        "embedded_post": nested(info.get("linked_inline_media")),
        "is_quoted_post_unavailable": to_bool(share.get("quoted_attachment_post_unavailable")),
        "mentions": mentions,
        "links": links,
        "stickers": stickers,
        "replied_to_user": _author_ref(info.get("reply_to_author")),
        "thread_author": _author_ref(info.get("root_post_author")),
        "content_overlay": content_overlay(raw.get("media_overlay_info")),
        "ai_detection_method": None if detection in (None, "none") else detection,
    }


def post_media(raw):
    """Every rendition of a post's media for /posts/media: each slide (or
    the single image/video) with all image sizes and video versions."""
    raw = _dict(raw)
    base = post(raw) or {}
    carousel = [m for m in _list(raw.get("carousel_media")) if isinstance(m, dict)]
    items = [media_item(m, full=True) for m in carousel] if carousel else []
    if not carousel and (best_image(_candidates(raw)) or best_video(raw.get("video_versions"))) and base.get("type") != "repost":
        items = [media_item(raw, full=True)]
    return {
        "id": base.get("id"),
        "code": base.get("code"),
        "link": base.get("link"),
        "type": base.get("type"),
        "author": base.get("author"),
        "item_count": len(items),
        "items": items,
        "gif": base.get("gif"),
        "music": base.get("music"),
        "link_preview": base.get("link_preview"),
    }


# ---- threads / lists -----------------------------------------------------------------------

def thread(thread_id, items):
    """A list entry: {id, posts[], parent_post_unavailable_reason}."""
    posts, reason = [], None
    for item in _list(items):
        item = _dict(item)
        reason = reason or clean(item.get("parent_post_unavailable_reason"))
        parsed = post(item.get("post"))
        if parsed:
            posts.append(parsed)
    if not posts:
        return None
    return {"id": to_id(thread_id) or posts[0]["id"], "posts": posts, "parent_post_unavailable_reason": reason}


def edge_thread(edge):
    """Any list edge Threads sends -> thread. Handles every container seen:
    profile tabs / owner threads ({node: {id, thread_items}}), search
    ({node: {thread: {id, thread_items}}}), logged-out feed
    ({text_post_app_thread: {id, thread_items}}) and related posts (the
    thread object itself)."""
    edge = _dict(edge)
    for holder in (_dict(edge.get("node")).get("thread"), edge.get("text_post_app_thread"), edge.get("node"), edge):
        holder = _dict(holder)
        if "thread_items" in holder:
            return thread(holder.get("id"), holder.get("thread_items"))
    return None


def threads_list(edges):
    return [t for t in (edge_thread(e) for e in _list(edges)) if t]


def page_info(connection):
    info = _dict(_dict(connection).get("page_info"))
    cursor = clean(info.get("end_cursor"))
    more = bool(info.get("has_next_page")) and bool(cursor)
    return (cursor if more else None), more


def thread_view_posts(view):
    """A post page's thread view ({posts: {edges: [{node: post}]}}) -> posts."""
    return [p for p in (post(_dict(e).get("node")) for e in _list(_dict(_dict(view).get("posts")).get("edges"))) if p]
