"""Relay payloads server-rendered into threads.com pages.

Every page ships its preloaded query results inside
`<script type="application/json" data-sjs>` blocks: nested `__bbox`
objects whose `require` lists contain entries like

    ["RelayPrefetchedStreamCache", "next", [],
     ["adp_BarcelonaPostPageDownwardQueryRelayPreloader_<hash>",
      {"__bbox": {"complete": true, "result": {"data": {...}}}}]]

prefetched(html) returns {"BarcelonaPostPageDownwardQuery": data, ...}.
The data objects are byte-for-byte what the matching GraphQL query returns,
so the same parsers read both.
"""
import html as html_lib
import json
import re

# Attribute order / data-content-len are not relied on: only the data-sjs
# marker and the JSON type.
_SCRIPT_RE = re.compile(r'<script\b(?=[^>]*\bdata-sjs\b)(?=[^>]*application/json)[^>]*>(.*?)</script>', re.S)
_META_RE = re.compile(r'<meta\s+property="(og:[a-z:_]+)"\s+content="([^"]*)"')


def _walk(node, out):
    if isinstance(node, dict):
        req = node.get("require")
        if isinstance(req, list):
            for entry in req:
                if (isinstance(entry, list) and len(entry) >= 4 and entry[0] == "RelayPrefetchedStreamCache"
                        and isinstance(entry[3], list) and len(entry[3]) >= 2):
                    key, payload = entry[3][0], entry[3][1]
                    if isinstance(key, str) and isinstance(payload, dict):
                        name = key.split("RelayPreloader")[0]
                        if name.startswith("adp_"):
                            name = name[4:]
                        result = (payload.get("__bbox") or {}).get("result") or {}
                        if isinstance(result, dict) and name not in out:
                            out[name] = result.get("data")
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, out)


def prefetched(html):
    """{query name: data} for every Relay result preloaded into the page."""
    out = {}
    for match in _SCRIPT_RE.finditer(html or ""):
        try:
            blob = json.loads(match.group(1))
        except ValueError:
            continue
        _walk(blob, out)
    return out


def og_meta(html):
    """{og:title: ..., og:description: ...} with entities decoded."""
    return {k: html_lib.unescape(v) for k, v in _META_RE.findall(html or "")}


PAGE_ATTEMPTS = 3


def load(path, *, label, required):
    """GET a page -> (prefetched data, html) once `required` (a query name)
    is among its preloaded results.

    Unknown posts / users never get here (fetch.get_page turns their
    redirects into a 404) and an unknown tag still ships an empty result, so
    a page WITHOUT the required query is an upstream rendering variant —
    seen once in ~40 post-page fetches on 2026-09-21, not reproducible — and
    is re-fetched on a fresh session instead of being reported as empty."""
    from .fetch import ThreadsUpstreamError, _drop_session, dump_debug, get_page
    for _ in range(PAGE_ATTEMPTS):
        html, _final = get_page(path, label=label)
        data = prefetched(html)
        if data.get(required) is not None:
            return data, html
        dump_debug("page_without_" + required, html)
        _drop_session()
    raise ThreadsUpstreamError(f"{label}: the page came back without its data {PAGE_ATTEMPTS} times")
