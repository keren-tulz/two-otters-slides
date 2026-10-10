#!/usr/bin/env python3
"""Publish the Two Otters carousels to Instagram on schedule.

Run with no arguments and it publishes everything that is due and not yet out.
Run with a post number to force one: `python3 publish.py 4`.

Two environment variables are needed:
  IG_USER_ID  the Instagram professional account id
  IG_TOKEN    a Facebook PAGE access token for Two-Otters.Studio, carrying
              instagram_content_publish and instagram_basic

The account is tied to a Facebook page, which is why this goes through
graph.facebook.com and a page token rather than the Instagram-login flow. That
flow refuses this account outright with "Access denied to the target Instagram
account". A page token derived from a long-lived user token has no expiry, so
there is nothing to renew.

Meta fetches each slide from its raw.githubusercontent URL, which is why this
repository has to stay public until the last post goes out.

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

API = "https://graph.facebook.com/v23.0"
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


def describe_token():
    """Say enough about the stored token to spot a wrong paste, and no more.

    Length and prefix are enough to tell an Instagram token from an app secret or
    a half-copied string. The value itself is never printed.
    """
    kind = "looks like a Meta access token" if TOKEN.startswith("EAA") else \
           "does NOT start with EAA, so it is probably not an access token at all"
    print(f"IG_USER_ID is {len(USER)} characters, starts with {USER[:4]}")
    print(f"IG_TOKEN is {len(TOKEN)} characters and {kind}")


def check():
    """Prove the whole path works without putting anything on the profile.

    Containers are staged and then simply abandoned; Meta drops an unpublished
    container after 24 hours, and nothing appears on the account in the meantime.
    """
    describe_token()
    me = call("GET", USER, fields="id,username")
    print(f"token works, reaching @{me.get('username')}")
    token_status()

    sched = json.loads((HERE / "schedule.json").read_text())
    post = sched[0]
    print(f"staging every slide of post {post['post']} without publishing")

    children = []
    for i, url in enumerate(post["slides"], 1):
        r = call("POST", f"{USER}/media", image_url=url, is_carousel_item="true")
        children.append(r["id"])
        print(f"  slide {i:02d} accepted")
    for i, cid in enumerate(children, 1):
        wait_ready(cid, f"slide {i:02d}")
    print(f"  all {len(children)} slides fetched and processed by Meta")

    r = call("POST", f"{USER}/media", media_type="CAROUSEL",
             children=",".join(children), caption=post["caption"])
    wait_ready(r["id"], "carousel")
    print(f"  carousel container {r['id']} is ready to publish")
    print("\nstopping here on purpose. Nothing was posted.")


def token_status():
    """Report how healthy the stored token is, without printing any of it.

    A page token derived from a long-lived user token has no expiry, so there is
    nothing to renew. This only exists to say so out loud, and to warn early if
    the token stored is the wrong kind and will lapse mid-schedule.
    """
    info = call("GET", "debug_token", input_token=TOKEN).get("data", {})
    if not info.get("is_valid"):
        print("WARNING: Meta reports this token as not valid.")
        return
    expires = info.get("expires_at")
    if expires:
        when = datetime.datetime.fromtimestamp(expires, datetime.timezone.utc)
        left = when - datetime.datetime.now(datetime.timezone.utc)
        print(f"WARNING: this token expires {when:%Y-%m-%d %H:%M} UTC, "
              f"in {left.days} days. Replace it before then.")
    else:
        print(f"token is a {info.get('type', 'unknown')} token with no expiry")


if __name__ == "__main__":
    # A secret pasted into GitHub keeps whatever whitespace came with it, and a
    # stray newline is enough for Meta to answer "cannot parse access token".
    USER = os.environ["IG_USER_ID"].strip()
    TOKEN = os.environ["IG_TOKEN"].strip()

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        token_status()
        raise SystemExit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check()
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
