#!/usr/bin/env python3
"""Read a post's caption from its ClickUp task.

ClickUp is where Keren edits, so it is the source of truth for caption text. The
copy in schedule.json is only a fallback for when ClickUp cannot be reached, so
a ClickUp outage delays nothing.

The task description holds the caption under a heading, between that heading and
the next horizontal rule or heading. Tasks written in the first batch use the
Hebrew heading, later ones use the English one, so both are matched.
"""
import json
import re
import urllib.error
import urllib.request

API = "https://api.clickup.com/api/v2/task"

# "## קאפשן", "**Caption**", "**Caption** - rewritten so ...", "## Caption:"
# Every gap here is [ \t] rather than \s, because \s would swallow the newline
# after the heading and eat the caption's own first line with it.
#
# The markers are optional: ClickUp's plain description drops them, so there the
# heading is a bare line reading just "קאפשן". That is why an unmarked heading
# has to be the whole line, or every mention of the word inside the copy would
# look like one.
HEADING = re.compile(
    r"^[ \t]*(?:"
    r"(?:#{1,6}[ \t]*|\*\*)[ \t]*(?:קאפשן|caption)[ \t]*:?[ \t]*(?:\*\*)?[^\n]*"
    r"|"
    r"(?:קאפשן|caption)[ \t]*:?[ \t]*"
    r")$",
    re.IGNORECASE | re.MULTILINE,
)
# Where the caption ends: a horizontal rule in any of the spellings ClickUp
# emits, the next heading, or one of the section titles used in these tasks.
# The bare titles matter only for the plain-text description, which carries no
# rules or hashes at all.
SECTIONS = ("הערות עיצוב", "תוכן השקפים", "תוכן השקף",
            "slides", "notes", "the graphic", "pinned first comment")
STOP = re.compile(
    r"^[ \t]*(?:"
    r"\*[ \t]*\*[ \t]*\*|-{3,}|_{3,}|#{1,6}[ \t]+\S"
    r"|(?:\*\*)?(?:" + "|".join(re.escape(s) for s in SECTIONS) + r")\b[^\n]*"
    r")$",
    re.IGNORECASE | re.MULTILINE)


def strip_markdown(text):
    """Instagram shows asterisks and brackets literally, so take them out."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)   # [label](url) -> label
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text, flags=re.S)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = text.replace("\\-", "-").replace("\\_", "_").replace("\\#", "#")
    return text


def extract_caption(description):
    """Pull the caption body out of a task description, or None."""
    if not description:
        return None
    m = HEADING.search(description)
    if not m:
        return None
    rest = description[m.end():]
    stop = STOP.search(rest)
    body = rest[:stop.start()] if stop else rest
    body = strip_markdown(body).strip()
    return body or None


def fetch_caption(task_id, token, timeout=20):
    """Return the caption from ClickUp, or None if anything at all goes wrong.

    Never raises. A caption that cannot be fetched falls back to schedule.json,
    which is always better than skipping the post.
    """
    if not (task_id and token):
        return None
    # Without include_markdown_description ClickUp returns only the plain text,
    # which has no headings or rules left in it and is far harder to cut cleanly.
    req = urllib.request.Request(
        f"{API}/{task_id}?include_markdown_description=true",
        headers={"Authorization": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            task = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  ClickUp unreachable for {task_id} ({e}), using the stored caption")
        return None
    return extract_caption(task.get("markdown_description")
                           or task.get("description"))
