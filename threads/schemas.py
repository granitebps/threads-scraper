"""Marshmallow request schemas for every /threads/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Threads resolvers and the per-route schemas. Every schema's load()
output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair), auto-detected by refs.py:
  user  a username, @username, numeric user id or threads.com profile link
  post  a post code, numeric post id or threads.com post link
  tag   a hashtag (with or without #), a /tag/ link or a topic link
"""
from marshmallow import validate

from schema_fields import BaseSchema, ChoiceField, CountryCodeField, LimitField, QueryField, RefField, StrippedString
from threads import refs


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class PostRefField(RefField):
    resolver = staticmethod(refs.resolve_post)


class TagRefField(RefField):
    resolver = staticmethod(refs.resolve_tag)


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=1000))
        super().__init__(**kwargs)


class EmptySchema(BaseSchema):
    pass


# ---- users -----------------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserRefField(metadata={"description": "username, @username, numeric user id or threads.com profile link"})


class UserPageSchema(UserSchema):
    cursor = CursorField()


class UserSearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = LimitField(default=20, max_size=50)


# ---- posts -----------------------------------------------------------------------------

class PostSchema(BaseSchema):
    post = PostRefField(metadata={"description": "post code, numeric post id or threads.com post link"})


# ---- discovery -------------------------------------------------------------------------

class PostSearchSchema(BaseSchema):
    query = QueryField(max_length=200)
    sort = ChoiceField(["top", "recent"], load_default="top")


class TagSchema(BaseSchema):
    tag = TagRefField(metadata={"description": "hashtag (with or without #), a threads.com/tag/ link or a topic link"})


class FeedSchema(BaseSchema):
    country = CountryCodeField(load_default="US")
    cursor = CursorField()
