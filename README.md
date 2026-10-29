# Threads Scraper MCP

A read-only MCP server for public Threads content, built on a fork of
[omkarcloud/threads-scraper](https://github.com/omkarcloud/threads-scraper).
It talks to threads.com's own logged-out web API over plain HTTP: no account,
no API key, no browser.

It replaces [threads-mcp](https://github.com/granitebps/threads-mcp) for Fami
and keeps that server's tool names.

## Tools

| Tool | Input | Returns |
|---|---|---|
| `search_posts` | `query`, `sort` (`top` / `recent`), `limit` (1-25, default 10) | Matching threads. One page only: about 20 top or 8 recent. |
| `get_post` | `post` | One post: text, stats, author, media, link preview, quoted / reposted post. |
| `get_post_replies` | `post` | The first ~8 direct replies with their chains, pinned replies, the author's self-thread. `has_more` means more exist behind a login. |
| `get_profile` | `username` | Bio, bio links, follower count, verified badge, topics. |
| `get_profile_posts` | `username`, `cursor` | The user's threads, newest first, 25 per page. Pass `next_cursor` back as `cursor` while `has_more` is true. |

- `post` takes a post code (`DHcqKN_ufwv`), a numeric post id, or a
  threads.com / threads.net post link.
- `username` takes a username, `@username`, a numeric user id, or a profile link.
- Results are the scraper's JSON with null and empty fields left out. Avatar
  URLs (`profile_picture`) are dropped too: they repeat on every post and
  were a third or more of list results.
- Media comes back as URLs (`media.image`, `media.video`, carousel
  `media.items[]`, `accessibility_caption`). The fbcdn URLs are signed and
  expire, so the client should download them soon after the call.
- Failures come back as an MCP tool error (`isError: true`) with
  `{"error": {"code", "message", "retryable"}}`. Codes: `invalid_input`,
  `not_found`, `upstream_rejected`, `timeout`, `upstream_unavailable`,
  `internal_error`.

## Run locally (stdio)

Requires Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Point your MCP client at the venv's Python with absolute paths:

```json
{
  "mcpServers": {
    "threads": {
      "command": "/absolute/path/to/threads-scraper/.venv/bin/python",
      "args": ["/absolute/path/to/threads-scraper/mcp_server.py", "--stdio"]
    }
  }
}
```

Or with Claude Code:

```bash
claude mcp add threads -- /absolute/path/to/threads-scraper/.venv/bin/python /absolute/path/to/threads-scraper/mcp_server.py --stdio
```

Without `--stdio` the server speaks streamable HTTP on
`http://127.0.0.1:8000/mcp`.

## Deploy on the homeserver

The compose file joins the external `ai-routing` Docker network and
publishes no ports, so only containers on that network can reach it.

```bash
docker network inspect ai-routing >/dev/null 2>&1 || docker network create ai-routing
docker compose up -d --build
```

Fami (OpenClaw) then connects over streamable HTTP:

```json
"threads": {
  "enabled": true,
  "url": "http://threads-scraper:8000/mcp",
  "transport": "streamable-http",
  "toolFilter": {
    "include": ["search_posts", "get_post", "get_post_replies", "get_profile", "get_profile_posts"]
  }
}
```

The container runs as `nobody` on a read-only filesystem, capped at 128 MB
of memory, half a CPU and 64 processes. `GET /health` backs the Docker
healthcheck.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | HTTP bind address |
| `PORT` | `8000` | HTTP port |
| `MCP_TOOL_TIMEOUT` | `45` | Seconds one tool call may spend on threads.com, retries included |
| `MCP_MAX_CONCURRENCY` | `4` | Tool calls running at once |
| `MCP_CACHE_SIZE` | `500` | Results kept in the in-memory cache (TTLs in `threads/cache_config.py`) |
| `THREADS_PROXY` | none | Proxy for every upstream request, e.g. `http://user:pass@host:port` |

## REST API and Python use

The upstream REST API is still in the repo but is not started by the image.
Run it locally with `python run.py` (16 endpoints on
`http://localhost:8000`, listed in `routes.py`), or call the functions
directly as `main.py` shows.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests run offline against captured payloads in `threads/fixtures/`.

## Limits

Everything comes from the logged-out side of threads.com. Search and
replies are the limited windows the site shows logged-out visitors, not
complete archives. The GraphQL `doc_id`s in `threads/queries.py` are the web
app's persisted queries; when Meta rotates them, the affected calls fail
with `upstream_unavailable` until they are re-harvested.

## License

MIT, see [LICENSE](LICENSE). Use it in line with the laws that apply to you
and Threads' terms; see [SECURITY.md](SECURITY.md).
