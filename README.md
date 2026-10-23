# 🧵 Threads Scraper

Threads Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Threads data for free.

## ✨ What Can I Get?

- 🧵 **Posts from 400M+ monthly users** — text, likes, replies, reposts, quotes, photos & videos
- 🔍 **Search posts, people & tags** — top or recent posts, 50 accounts per search, tag thread counts
- 💬 **Full conversations** — top replies with their chains, parent posts & related threads
- 🎥 **Every image & video** — each carousel slide, every size, direct download links

## 🎥 Example: A Full Threads Post

```json
{
  "user": { "username": "selenagomez", "full_name": "Selena Gomez", "is_verified": true },
  "thread_count": 11,
  "threads": [
    {
      "posts": [
        {
          "id": "3592932022910843951",
          "code": "DHcqKN_ufwv",
          "link": "https://www.threads.com/@selenagomez/post/DHcqKN_ufwv",
          "type": "carousel",
          "text": "I Said I Love You First with itsbennyblanco is officially out in the world! 🖤",
          "published_at": "2025-03-21T04:21:35Z",
          "stats": { "like_count": 14968, "reply_count": 512, "repost_count": 445, "quote_count": 38, "share_count": 56 },
          "author": { "username": "selenagomez", "full_name": "Selena Gomez", "is_verified": true },
          "media": {
            "type": "carousel",
            "width": 1080,
            "height": 1350,
            "image": "https://instagram.fdel3-4.fna.fbcdn.net/v/t51.75761-15/485309103_17904753036102062_5577327263744989368_n.jpg?stp=dst-jpg_e35_tt6&_nc_cat=101&_nc_map=urlgen_bucketless&ig_cache_key=MzU5MjkzMjAxODMzMDcyMDc0NQ%3D%3D.3-ccb7-5&ccb=7-5&_nc_sid=58cdad&efg=eyJ2ZW5jb2RlX3RhZyI6IkNBUk9VU0VMX0lURU0ueHBpZHMuMTA4MC5zZHIucmVndWxhcl9waG90by5DMyJ9&_nc_ohc=a3uYTW9wKoQQ7kNvwFxJ2v-&_nc_oc=AdrCFwkKJB0gJH_zDMvCw5CZ75tU7rUMZJ2ZJ7pgMh71M0Eh0d9TtCTusYbIrvIq9Tw&_nc_ad=z-m&_nc_cid=0&_nc_zt=23&_nc_ht=instagram.fdel3-4.fna&_nc_gid=SQE2WgBUUiYU6T4XUVqDKg&_nc_ss=7a22e&oh=00_AQKCX-WT7qSmkHPeEF59IAVIlBLAUu8QYU51snnNcDJPLQ&oe=6AB6E51D"
          }
        }
      ]
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Threads Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/threads-scraper
cd threads-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/users/threads?user=selenagomez"
```

```json
{
  "user": { "username": "selenagomez", "full_name": "Selena Gomez", "is_verified": true },
  "thread_count": 11,
  "threads": [
    {
      "posts": [
        {
          "id": "3597158294504132267",
          "code": "DHrrGkIxM6r",
          "type": "image",
          "text": "Thank you for all the support on I Said I Love You First 🖤 Slow & Reverbed version of the album is now available on my store for digital download  itsbennyblanco",
          "published_at": "2025-03-27T00:18:26Z",
          "stats": { "like_count": 8674, "reply_count": 2053, "repost_count": 211, "quote_count": 15, "share_count": 108 },
          "author": { "username": "selenagomez", "full_name": "Selena Gomez", "is_verified": true }
        }
      ]
    }
  ],
  "has_more": false
}
```

All 16 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

16 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| User Threads | `/users/threads` | A user's posts with full stats and media, 25 per page |
| Search Users | `/search/users` | Up to 50 matching accounts with bio and verified badge |
| User Profile | `/users/profile` | Bio, bio links, follower count, topics and avatar |
| User Replies / Media / Reposts | `/users/replies`, `/users/media`, `/users/reposts` | Every profile tab, paginated, with the original posts inside |
| Search Posts | `/search/posts` | Top or most recent posts for any keyword |
| Search Tags | `/search/tags` | Threads under a hashtag or topic, with thread counts |
| Post Details | `/posts/details` | Everything about one post in a single call |
| Post Replies | `/posts/replies` | Top replies with their chains, pinned replies, author follow-ups |
| Parent Posts | `/posts/parent-posts` | The whole conversation above any reply |
| Related Threads | `/posts/related` | Recommended threads plus more from the same author |
| Post Media | `/posts/media` | Every image size and video version, ready to download |
| Home Feed | `/feed` | The public For You feed for any country |
| Resolve User / Post | `/users/resolve`, `/posts/resolve` | Usernames and post codes to numeric IDs, and back |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-threads-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-threads-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-threads-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/users/threads",
    params={"user": "selenagomez"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Threads Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Threads%20Scraper%20API.)

[![Ask Us by Email about Threads Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Threads%20Scraper%20API&body=I%20need%20help%20using%20the%20Threads%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV shows, ratings, cast & box office
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/threads-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/threads-scraper)
