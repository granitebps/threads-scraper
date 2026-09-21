"""Threads reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  user   zuck | @zuck | 63055343223 (numeric user id) | @123 (an all-digit
         username, the @ forces the username reading)
         | https://www.threads.com/@zuck | https://www.threads.net/@zuck
         | https://www.threads.com/@zuck/post/DdZ7sQvkTFn (the post's author)
    -> {"id": "63055343223", "username": None} or {"id": None, "username": "zuck"}

  post   DdZ7sQvkTFn (the shortcode in post links)
         | 3988481471392330087 (numeric post id) | 3988481471392330087_63055343223
         | https://www.threads.com/@zuck/post/DdZ7sQvkTFn[/media]
         | https://www.threads.com/t/DdZ7sQvkTFn | threads.net links
    -> "3988481471392330087"
    The shortcode IS the numeric id in base64 (alphabet A-Z a-z 0-9 - _),
    so no lookup is needed: code_to_id / id_to_code (verified against 318
    live posts, 2026-09-21).

  tag    python | #python | https://www.threads.com/tag/python
         | https://www.threads.com/search?q=python&serp_type=tags
         | https://www.threads.com/search?q=AI%20Threads&serp_type=tags&tag_id=18399895213044171
    -> {"name": "python", "id": None} / {"name": "AI Threads", "id": "18399895213044171"}
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://www.threads.com"

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}

_HOST_RE = re.compile(r"(^|\.)threads\.(com|net)$")
_USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")
_USER_ID_RE = re.compile(r"^\d{1,20}$")
_POST_ID_RE = re.compile(r"^(\d{15,20})(?:_\d+)?$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
_BARE_LINK_RE = re.compile(r"^(?:www\.)?threads\.(?:com|net)(?:[/?#]|$)", re.I)


def code_to_id(code):
    """Post shortcode -> numeric post id (as a string; ids exceed 2**53)."""
    value = 0
    for ch in code:
        value = value * 64 + _INDEX[ch]
    return str(value)


def id_to_code(post_id):
    """Numeric post id -> shortcode."""
    value = int(post_id)
    out = ""
    while value > 0:
        value, rem = divmod(value, 64)
        out = _ALPHABET[rem] + out
    return out


def _as_url(text):
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return "https:" + text
    return "https://" + text


def _looks_like_link(text):
    # a bare host must end at a path/query boundary: "threads.community" or
    # "www.threads.fan" are valid usernames, not links
    low = text.lower()
    return low.startswith(("http://", "https://", "//")) or bool(_BARE_LINK_RE.match(text))


def _parse_link(text, kind):
    parsed = urlparse(_as_url(text))
    if not _HOST_RE.search((parsed.hostname or "").lower()):
        raise ValueError(f"{kind} link must be a threads.com link")
    return parsed, [unquote(p) for p in parsed.path.split("/") if p]


def resolve_user(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("user must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "user")
        if not parts or not parts[0].startswith("@") or len(parts[0]) < 2:
            raise ValueError(f"no @username in link {text!r}")
        text = parts[0]
    if text.startswith("@"):
        name = text[1:].lower()
        if not _USERNAME_RE.match(name):
            raise ValueError(f"invalid Threads username {text!r}")
        return {"id": None, "username": name}
    if _USER_ID_RE.match(text):
        return {"id": text, "username": None}
    name = text.lower()
    if not _USERNAME_RE.match(name):
        raise ValueError(f"user must be a Threads username, a numeric user id or a threads.com profile link, got {text!r}")
    return {"id": None, "username": name}


def resolve_post(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("post must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "post")
        code = None
        for i, part in enumerate(parts):
            if part in ("post", "t") and i + 1 < len(parts):
                code = parts[i + 1]
                break
        if code is None or not _CODE_RE.match(code):
            raise ValueError(f"no post code in link {text!r}")
        return code_to_id(code)
    match = _POST_ID_RE.match(text)
    if match:
        return match.group(1)
    if _CODE_RE.match(text):
        return code_to_id(text)
    raise ValueError(f"post must be a Threads post code, a numeric post id or a threads.com post link, got {text!r}")


def resolve_tag(value):
    """-> {"name": ..., "id": tag id or None}. A pasted topic link
    (/search?q=<name>&serp_type=tags&tag_id=<id>, what the site links topic
    chips to) keeps its tag id; a bare name or /tag/<name> link has none."""
    text = str(value or "").strip()
    tag_id = None
    if _looks_like_link(text):
        parsed, parts = _parse_link(text, "tag")
        if len(parts) >= 2 and parts[0] == "tag":
            text = parts[1]
        elif parts and parts[0] == "search":
            query = parse_qs(parsed.query)
            text = (query.get("q") or [""])[0]
            tag_id = (query.get("tag_id") or [None])[0]
            if tag_id and not _USER_ID_RE.match(tag_id):
                tag_id = None
        else:
            raise ValueError(f"no tag in link {value!r}")
    text = " ".join(text.lstrip("#").split())
    if not text:
        raise ValueError("tag must not be empty")
    if len(text) > 100:
        raise ValueError("tag must be at most 100 characters")
    return {"name": text, "id": tag_id}


def user_link(username):
    return f"{SITE}/@{username}" if username else None


def post_link(username, code):
    if not code:
        return None
    return f"{SITE}/@{username}/post/{code}" if username else f"{SITE}/t/{code}"


def tag_link(name, tag_id=None):
    """A topic's page. Topics with an id open as the site's own topic search
    (`/tag/<display name>` only resolves space-free hashtag slugs)."""
    from urllib.parse import quote, urlencode
    if not name:
        return None
    if tag_id:
        return f"{SITE}/search?{urlencode({'q': name, 'serp_type': 'tags', 'tag_id': tag_id})}"
    return f"{SITE}/tag/{quote(name, safe='')}"
