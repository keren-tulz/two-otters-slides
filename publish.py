#!/usr/bin/env python3
"""Publish the Two Otters carousels to Instagram on schedule.

Run with no arguments and it publishes everything that is due and not yet out.
Run with a post number to force one: `python3 publish.py 4`.

Two environment variables are needed:
  IG_USER_ID  the Instagram professional account id
  IG_TOKEN    an Instagram user access token with instagram_business_content_publish

The token comes from the Instagram-login flow, so the host is graph.instagram.com,
not graph.facebook.com. Meta fetches each slide from its raw.githubusercontent URL,
which is why this repository has to stay public until the last post goes out.

Everything about what goes out lives in schedule.json next to this file.
published.json records what already went, and the workflow commits it back, so a
rerun on the same day is a no-op rather than a double post.
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v23.0"
HERE = pathlib.Path(__file__).parent
STATE = HERE / "published.json"


def call(method, path, **params):
    params["access_token"] = TOKEN
    body = urllib.parse.urlencode(params)
    if method == "POST":
        req = urllib.request.Request(f"{API}/{path}", data=body.encode(), method="POST")
    else:
        req = urllib.request.Request(f"{API}/{path}?{body}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # The token is in the body we sent, never in the error Meta sends back.
        raise SystemExit(f"Graph API {e.code} on {method} {path}\n{e.read().decode()[:500]}")


def wait_ready(container_id, label, tries=45):
    """A container has to finish processing before it can be used or published."""
    for _ in range(tries):
        s = call("GET", container_id, fields="status_code,status")
        code = s.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise SystemExit(f"{label} failed to process: {s.get('status')}")
        time.sleep(4)
    raise SystemExit(f"{label} never finished processing")


def publish(post):
    n, slides, caption = post["post"], post["slides"], post["caption"]
    if not caption:
        raise SystemExit(f"post {n} has no caption yet, refusing to publish it")

    if len(slides) == 1:
        # A one-image post is a plain image, not a carousel of one.
        print(f"post {n}: single image")
        r = call("POST", f"{USER}/media", image_url=slides[0], caption=caption)
        container = r["id"]
        wait_ready(container, "image")
    else:
        print(f"post {n}: {len(slides)} slides")
        children = []
        for i, url in enumerate(slides, 1):
            r = call("POST", f"{USER}/media", image_url=url, is_carousel_item="true")
            children.append(r["id"])
            print(f"  slide {i:02d} staged")
        for i, cid in enumerate(children, 1):
            wait_ready(cid, f"slide {i:02d}")

        r = call("POST", f"{USER}/media", media_type="CAROUSEL",
                 children=",".join(children), caption=caption)
        container = r["id"]
        wait_ready(container, "carousel")

    r = call("POST", f"{USER}/media_publish", creation_id=container)
    media_id = r["id"]
    print(f"  published, media id {media_id}")

    # Post 19 opens with "we'll go first", so the first comment has to be ours.
    first = post.get("first_comment")
    if first:
        call("POST", f"{media_id}/comments", message=first)
        print("  first comment posted")
    return media_id


def refresh_token():
    """Extend the 60 day token.

    The new token goes to a file rather than to stdout, so it never lands in a
    workflow log. The workflow pipes that file into `gh secret set` and deletes it.
    """
    body = urllib.parse.urlencode({"grant_type": "ig_refresh_token",
                                   "access_token": TOKEN})
    req = urllib.request.Request(
        f"https://graph.instagram.com/refresh_access_token?{body}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            fresh = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"refresh failed {e.code}\n{e.read().decode()[:400]}")

    days = int(fresh.get("expires_in", 0)) // 86400
    out = HERE / ".new_token"
    out.write_text(fresh["access_token"])
    out.chmod(0o600)
    print(f"token refreshed, valid for another {days} days")


if __name__ == "__main__":
    USER = os.environ["IG_USER_ID"]
    TOKEN = os.environ["IG_TOKEN"]

    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        refresh_token()
        raise SystemExit(0)

    sched = json.loads((HERE / "schedule.json").read_text())
    done = json.loads(STATE.read_text()) if STATE.exists() else {}

    forced = sys.argv[1] if len(sys.argv) > 1 else None
    now = datetime.datetime.now(datetime.timezone.utc)

    due = []
    for p in sched:
        key = str(p["post"])
        if key in done:
            continue
        if forced:
            if key == forced:
                due.append(p)
        elif datetime.datetime.fromisoformat(p["at"]) <= now:
            due.append(p)

    if not due:
        print("nothing due")
        raise SystemExit(0)

    for p in due:
        done[str(p["post"])] = {"media_id": publish(p),
                                "published_at": now.isoformat()}
        STATE.write_text(json.dumps(done, indent=1) + "\n")
    print(f"done: {len(due)} post(s)")
