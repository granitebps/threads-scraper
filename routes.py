"""The 16 Threads endpoints. Every path is served with and without the
`/threads` prefix, so code generated against the hosted API on RapidAPI
(paths like /users/threads) runs unchanged against this server.

Params are validated by the same marshmallow schemas the hosted API uses
(threads/schemas.py): `user`, `post` and `tag` each accept a bare value or a
pasted threads.com link."""
import json

from bottle import request, response, route

from schema_fields import load_query
from threads import discovery, posts, schemas, users
from threads.fetch import ThreadsBadRequest, ThreadsNotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    transport/blocks -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(fn(**data))
    except ValueError as e:                # bad value
        return json_response({"error": str(e)}, 400)
    except ThreadsBadRequest as e:         # upstream rejected the request (e.g. a bad cursor)
        return json_response({"error": f"threads rejected the request: {e}"}, 400)
    except ThreadsNotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"threads {label} failed: {e}"}, 500)


def mount(path, schema, fn):
    """Serve fn at /path and /threads/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "threads_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/threads" + path, method="GET")(handler)


ENDPOINTS = [
    ("/users/threads", schemas.UserPageSchema, users.get_threads),
    ("/search/users", schemas.UserSearchSchema, discovery.search_users),
    ("/users/profile", schemas.UserSchema, users.get_profile),
    ("/users/replies", schemas.UserPageSchema, users.get_replies),
    ("/users/media", schemas.UserPageSchema, users.get_media),
    ("/users/reposts", schemas.UserPageSchema, users.get_reposts),
    ("/search/posts", schemas.PostSearchSchema, discovery.search_posts),
    ("/search/tags", schemas.TagSchema, discovery.search_tag),
    ("/posts/details", schemas.PostSchema, posts.get_details),
    ("/posts/replies", schemas.PostSchema, posts.get_replies),
    ("/posts/parent-posts", schemas.PostSchema, posts.get_parent_posts),
    ("/posts/related", schemas.PostSchema, posts.get_related),
    ("/posts/media", schemas.PostSchema, posts.get_media),
    ("/feed", schemas.FeedSchema, discovery.get_feed),
    ("/users/resolve", schemas.UserSchema, users.resolve),
    ("/posts/resolve", schemas.PostSchema, posts.resolve),
]

for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
