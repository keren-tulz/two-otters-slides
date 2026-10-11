#!/usr/bin/env python3
"""Weekly report on how the carousels are doing.

Writes reports/YYYY-MM-DD.md into the repository and, when CLICKUP_LIST is set,
files the same thing as a ClickUp task so it turns up where the work already is.

Every number comes from Instagram's own insights. Where a metric is missing the
line says so rather than guessing, because a report that quietly invents a zero
is worse than one that admits a gap.
"""
import datetime
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.facebook.com/v23.0"
CLICKUP = "https://api.clickup.com/api/v2"
HERE = pathlib.Path(__file__).parent

# Asked for one at a time, because a single unsupported name makes Meta reject
# the whole call, and which names are supported changes between API versions.
MEDIA_METRICS = ["reach", "likes", "comments", "saved", "shares",
                 "total_interactions", "profile_visits", "follows"]


def graph(path, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read().decode())["error"]["message"]}
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:                                  # network, timeout
        return {"error": str(e)}


def media_stats(media_id):
    """Insights for one post, skipping whatever this account cannot report."""
    out = {}
    for metric in MEDIA_METRICS:
        r = graph(f"{media_id}/insights", metric=metric)
        for row in r.get("data", []):
            values = row.get("values") or [{}]
            out[row["name"]] = values[0].get("value")
    return out


def num(v):
    return f"{v:,}" if isinstance(v, int) else "–"


def build():
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    account = graph(USER, fields="username,followers_count,media_count")
    published = json.loads((HERE / "published.json").read_text()) \
        if (HERE / "published.json").exists() else {}
    sched = {str(p["post"]): p
             for p in json.loads((HERE / "schedule.json").read_text())}

    lines = [f"# Two Otters · week to {today:%d %b %Y}", ""]

    if account.get("error"):
        lines += [f"Instagram would not answer: {account['error']}", ""]
    else:
        lines += [
            f"**@{account.get('username')}** · "
            f"{num(account.get('followers_count'))} followers · "
            f"{num(account.get('media_count'))} posts",
            "",
        ]

    # Posts that went out in the last seven days, newest first.
    recent = []
    for key, rec in published.items():
        when = datetime.datetime.fromisoformat(rec["published_at"]).date()
        if when >= week_ago:
            recent.append((when, key, rec))
    recent.sort(reverse=True)

    lines += ["## This week", ""]
    if not recent:
        lines += ["Nothing went out this week.", ""]
    for when, key, rec in recent:
        post = sched.get(key, {})
        s = media_stats(rec["media_id"])
        lines += [
            f"### {when:%a %d %b} · post {key} · {post.get('title', '')}",
            "",
            f"| reach | likes | comments | saves | shares |",
            f"|---|---|---|---|---|",
            f"| {num(s.get('reach'))} | {num(s.get('likes'))} | "
            f"{num(s.get('comments'))} | {num(s.get('saved'))} | "
            f"{num(s.get('shares'))} |",
            "",
        ]
        if s.get("follows"):
            lines += [f"Brought **{num(s['follows'])}** new followers.", ""]

    # Everything published so far, ranked, so the pattern is visible.
    table = []
    for key, rec in published.items():
        s = media_stats(rec["media_id"])
        reach = s.get("reach")
        table.append((reach if isinstance(reach, int) else -1, key, s))
    table.sort(reverse=True)

    if len(table) > 1:
        lines += ["## Everything so far, by reach", "",
                  "| post | title | reach | saves | comments |",
                  "|---|---|---|---|---|"]
        for _, key, s in table:
            post = sched.get(key, {})
            lines.append(
                f"| {key} | {post.get('title', '')[:40]} | "
                f"{num(s.get('reach'))} | {num(s.get('saved'))} | "
                f"{num(s.get('comments'))} |")
        lines.append("")
        best = sched.get(table[0][1], {}).get("title")
        worst = sched.get(table[-1][1], {}).get("title")
        lines += [f"Best so far: **{best}**. Weakest: **{worst}**.", ""]

    upcoming = [p for p in sched.values()
                if datetime.datetime.fromisoformat(p["at"]).date() > today][:2]
    if upcoming:
        lines += ["## Next up", ""]
        for p in upcoming:
            d = datetime.datetime.fromisoformat(p["at"]).date()
            lines.append(f"- {d:%a %d %b} · post {p['post']} · {p['title']}")
        lines.append("")

    return today, "\n".join(lines)


def file_in_clickup(title, body, list_id, token):
    req = urllib.request.Request(
        f"{CLICKUP}/list/{list_id}/task",
        data=json.dumps({"name": title, "markdown_description": body}).encode(),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("url")
    except Exception as e:
        print(f"could not file it in ClickUp: {e}")
        return None


if __name__ == "__main__":
    USER = os.environ["IG_USER_ID"].strip()
    TOKEN = os.environ["IG_TOKEN"].strip()

    day, text = build()
    out = HERE / "reports" / f"{day:%Y-%m-%d}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text + "\n")
    print(f"wrote {out.relative_to(HERE)}")

    cu_token = os.environ.get("CLICKUP_TOKEN", "").strip()
    cu_list = os.environ.get("CLICKUP_LIST", "").strip()
    if cu_token and cu_list:
        url = file_in_clickup(f"Social report · {day:%d %b}", text,
                              cu_list, cu_token)
        if url:
            print(f"filed in ClickUp: {url}")

    print()
    print(text)
