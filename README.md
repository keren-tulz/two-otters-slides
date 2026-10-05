# Two Otters · scheduled Instagram carousels

This repository both **hosts the slides** and **publishes them**.

The slides live here in the open because the Instagram Graph API fetches each
`image_url` from a public address. Nothing private is in here: the token lives in
the repository's encrypted secrets, never in a file.

```
slides/postNN_SS.png   146 slides, 1080x1350
schedule.json          what goes out, when, with which caption
publish.py             the publisher
published.json         written by the workflow after each post
```

## How a post goes out

`.github/workflows/publish.yml` runs every day at 17:00 UTC. `publish.py` looks at
`schedule.json`, finds anything whose time has passed and that is not already in
`published.json`, and publishes it. A day that fails is simply picked up the next
day, so a single bad run never silently drops a post.

To push one out by hand: **Actions → Publish the scheduled carousel → Run
workflow**, optionally with a post number.

## The two secrets

| Secret | What it is |
|---|---|
| `IG_USER_ID` | the Instagram account id |
| `IG_TOKEN` | an Instagram user access token with `instagram_business_content_publish` |

Optionally `GH_PAT`, a token that may write repository secrets. When it is set, each
run refreshes `IG_TOKEN` and stores the new one, so the 60-day expiry never arrives.
Without it the run still refreshes the token and prints how long it has left, but
`IG_TOKEN` has to be replaced by hand before it lapses.

## Notes

- Posts 8, 9 and 18 are single images rather than carousels. `publish.py` handles both.
- Post 19 has a pinned first comment; the publisher posts it right after the carousel.
- Keep this repository public until the last post goes out, or Meta cannot fetch the slides.
