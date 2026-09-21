"""Cache TTL per /threads/* endpoint (cache.py, keyed on the validated
params — `user=zuck`, `user=@Zuck` and a pasted profile link all validate
to the same key).

Threads is a live social feed: like / reply counts move by the minute on
popular posts and search results turn over constantly, so the tiers stay
short. Profiles (bio, follower count) and the id resolvers change slowly.
Cursor pages are cached per cursor — a repeated page request is served from
the cache, a new cursor is a new key.
"""
from datetime import timedelta

RESOLVE_CACHE = timedelta(hours=24)          # username <-> id, code <-> id
PROFILE_CACHE = timedelta(minutes=30)
USER_THREADS_CACHE = timedelta(minutes=5)    # threads / replies / media / reposts tabs
POST_CACHE = timedelta(minutes=5)            # details, media, replies, parent posts
RELATED_CACHE = timedelta(minutes=30)
SEARCH_CACHE = timedelta(minutes=5)          # post search, tag feeds
USER_SEARCH_CACHE = timedelta(hours=1)
FEED_CACHE = timedelta(minutes=10)
