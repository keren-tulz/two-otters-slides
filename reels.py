#!/usr/bin/env python3
"""Publish the Two Otters reels to Instagram on schedule.

The carousel publisher's sibling. Run with no arguments and it publishes every
reel in reels.json that is due and not yet out. `python3 reels.py tip-A` forces
one. `python3 reels.py --check` uploads the next reel and stops before
publishing, so nothing appears on the profile.

Each video is a release asset on this repository (tag `reels`), named after the
reel's id. The runner downloads it and hands the bytes to Meta directly through
the resumable upload endpoint, so nothing depends on Meta being able to fetch a
video URL. Covers, where a reel has one, are fetched by Meta from raw.github.

published.json records what went out, under the key "reel:<id>", in the same
file the carousels use, so one commit step covers both.
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
UPLOAD = "https://rupload.facebook.com/ig-api-upload/v23.0"
REPO = "keren-tulz/two-otters-slides"
ASSETS = f"https://github.com/{REPO}/releases/download/reels"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
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
        raise SystemExit(f"Graph API {e.code} on {method} {path}\n{e.read().decode()[:500]}")


def fetch(asset):
    url = f"{ASSETS}/{urllib.parse.quote(asset)}"
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit(f"could not download {asset}: HTTP {e.code}")
    if len(data) < 100_000:
        raise SystemExit(f"{asset} is only {len(data)} bytes, refusing to post it")
    return data


def stage(reel):
    """Create the container, upload the video, wait until Meta has processed it."""
    caption = reel["caption"]
    if reel.get("hashtags"):
        caption = f"{caption}\n\n{reel['hashtags']}"
    if len(caption) > 2200:
        raise SystemExit(f"{reel['id']} caption is {len(caption)} characters, over 2200")

    video = fetch(reel["asset"])
    if video is None:
        print(f"{reel['id']}: {reel['asset']} is not uploaded yet, skipping")
        return None
    print(f"{reel['id']}: {len(video) / 1e6:.1f} MB downloaded")

    params = {"media_type": "REELS", "upload_type": "resumable",
              "caption": caption, "share_to_feed": "true"}
    if reel.get("cover"):
        params["cover_url"] = f"{RAW}/{reel['cover']}"
    container = call("POST", f"{USER}/media", **params)["id"]

    req = urllib.request.Request(
        f"{UPLOAD}/{container}", data=video, method="POST",
        headers={"Authorization": f"OAuth {TOKEN}", "offset": "0",
                 "file_size": str(len(video))})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            ok = json.load(r).get("success")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"upload failed with {e.code}\n{e.read().decode()[:500]}")
    if not ok:
        raise SystemExit("Meta did not confirm the upload")
    print("  uploaded")

    for _ in range(90):
        s = call("GET", container, fields="status_code,status")
        if s.get("status_code") == "FINISHED":
            print("  processed")
            return container
        if s.get("status_code") == "ERROR":
            raise SystemExit(f"{reel['id']} failed to process: {s.get('status')}")
        time.sleep(5)
    raise SystemExit(f"{reel['id']} never finished processing")


if __name__ == "__main__":
    USER = os.environ["IG_USER_ID"].strip()
    TOKEN = os.environ["IG_TOKEN"].strip()

    path = HERE / "reels.json"
    if not path.exists():
        print("no reels.json, nothing to do")
        raise SystemExit(0)
    sched = json.loads(path.read_text())
    done = json.loads(STATE.read_text()) if STATE.exists() else {}
    pending = [r for r in sched if f"reel:{r['id']}" not in done]

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    now = datetime.datetime.now(datetime.timezone.utc)

    if arg == "--check":
        if not pending:
            print("every reel is already out")
            raise SystemExit(0)
        # `--check studio-1` stages that reel; without an id, the next one that has a video.
        only = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
        if only:
            pending = [r for r in pending if r["id"] == only]
        container = next((c for c in map(stage, pending) if c), None)
        if not container:
            raise SystemExit("no pending reel has its video uploaded")
        print(f"container {container} is ready. Stopping here on purpose, nothing was posted.")
        raise SystemExit(0)

    if arg:
        due = [r for r in pending if r["id"] == arg]
    else:
        due = [r for r in pending if datetime.datetime.fromisoformat(r["at"]) <= now]

    if not due:
        print("no reel due")
        raise SystemExit(0)

    # One reel a day at most. If a video arrives late, or publishing was paused,
    # the backlog drains one evening at a time instead of flooding the profile.
    if not arg:
        last = max((datetime.datetime.fromisoformat(v["published_at"])
                    for k, v in done.items() if k.startswith("reel:")), default=None)
        if last and now - last < datetime.timedelta(hours=20):
            print("a reel already went out in the last 20 hours, waiting")
            raise SystemExit(0)

    out = 0
    for reel in due:
        container = stage(reel)
        if not container:
            continue
        media_id = call("POST", f"{USER}/media_publish", creation_id=container)["id"]
        print(f"  published, media id {media_id}")
        done[f"reel:{reel['id']}"] = {"media_id": media_id, "published_at": now.isoformat()}
        STATE.write_text(json.dumps(done, indent=1) + "\n")
        out += 1
        # A long pause must never dump a backlog on the profile in one evening.
        break
    print(f"done: {out} reel(s)")
