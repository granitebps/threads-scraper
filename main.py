"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See README.md for the full endpoint list.
"""
import json
import os

from threads import discovery, posts, refs, users

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a username, @username, numeric id or any threads.com profile link
    save("threads_selenagomez.json", users.get_threads(refs.resolve_user("selenagomez")))

    # a post code, numeric id or any threads.com post link
    save("post_DHcqKN_ufwv.json", posts.get_details(refs.resolve_post("DHcqKN_ufwv")))

    # top (or sort="recent") posts for a keyword
    save("search_spacex.json", discovery.search_posts("SpaceX"))
