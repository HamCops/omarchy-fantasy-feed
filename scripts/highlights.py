"""Match feed plays to r/nfl `[Highlight]` posts.

Nobody publishes a clip the moment a play happens, but r/nfl users post one
within a minute or two of anything worth seeing -- faster than ESPN's own
video pipeline. Reddit's JSON API refuses non-browser clients, so this reads
the subreddit's Atom feed, which is public and stable.

Matching is deliberately conservative: a post must name a participant of the
play and be published in a window after the play's wallclock. A touchdown
play prefers a title that says so. Nothing here can score a play; a wrong
match costs a wrong video, not wrong points, so the bar is "probably the
right clip", not proof.

Network policy: one fetch at most every FETCH_INTERVAL seconds, only while
games are live or recent plays are still unmatched, with a backoff on any
failure. A fetch failure never fails the feed refresh.
"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

FEED_URL = "https://www.reddit.com/r/nfl/new.rss?limit=100"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FETCH_INTERVAL = 45          # seconds between feed reads
FAILURE_BACKOFF = 300        # seconds to wait after a refused or failed read
POST_RETENTION = 8 * 3600    # how long a post stays in the local cache
POST_CAP = 400
RESPONSE_LIMIT = 1_500_000   # bytes
TIMEOUT = 6.0

# A clip can only follow the play. Reddit's clock and ESPN's wallclock both
# drift a little, so allow a small lead; the trailing window covers a slow
# poster or a clip of the drive's final play posted after the next snap.
LEAD_SECONDS = 180
TRAIL_SECONDS = 25 * 60
MIN_SCORE = 2

_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_HREF = re.compile(r'href="(https?://[^"]+)"')
_SUFFIX = re.compile(r"^(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)
_TOUCHDOWN = re.compile(r"\b(td|touchdown|scores?|house)\b", re.IGNORECASE)
_VREDDIT = re.compile(r"^https?://v\.redd\.it/([A-Za-z0-9]+)")


def default_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home) if cache_home and Path(cache_home).is_absolute() else Path.home() / ".cache"
    return base / "fantasy-feed" / "highlights.json"


# --------------------------------------------------------------------------
# Feed
# --------------------------------------------------------------------------


def parse_feed(text: str) -> list[dict[str, Any]]:
    """Atom entries -> posts. Only `[Highlight]`-titled entries survive."""
    root = ET.fromstring(text)
    posts: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", _ATOM):
        title = (entry.findtext("a:title", default="", namespaces=_ATOM) or "").strip()
        if "highlight" not in title.lower():
            continue
        link = entry.find("a:link", _ATOM)
        permalink = link.get("href", "") if link is not None else ""
        published = (entry.findtext("a:published", default="", namespaces=_ATOM)
                     or entry.findtext("a:updated", default="", namespaces=_ATOM) or "")
        content = html.unescape(entry.findtext("a:content", default="", namespaces=_ATOM) or "")
        external = [u for u in _HREF.findall(content) if "reddit.com" not in u]
        media = external[0] if external else permalink
        # Reddit-hosted video: yt-dlp is refused without an account, but the
        # clip's HLS playlist (video + audio) is public and mpv plays it.
        hosted = _VREDDIT.match(media)
        if hosted:
            media = f"https://v.redd.it/{hosted.group(1)}/HLSPlaylist.m3u8"
        try:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        post_id = (entry.findtext("a:id", default="", namespaces=_ATOM) or permalink).strip()
        if not post_id or not permalink:
            continue
        posts.append({
            "id": post_id,
            "title": title,
            "permalink": permalink,
            "url": media,
            "publishedAt": published_at,
        })
    return posts


def fetch_feed() -> list[dict[str, Any]]:
    request = urllib.request.Request(FEED_URL, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.5",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(FEED_URL, response.status, "unexpected status", None, None)
        body = response.read(RESPONSE_LIMIT + 1)
    if len(body) > RESPONSE_LIMIT:
        raise ValueError("highlight feed exceeded the response limit")
    return parse_feed(body.decode("utf-8", errors="replace"))


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def load_cache(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if isinstance(value, Mapping) and isinstance(value.get("posts"), list):
            return dict(value)
    except (OSError, ValueError):
        pass
    return {"fetchedAt": 0, "backoffUntil": 0, "posts": []}


def save_cache(path: Path, cache: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".highlights.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(cache, stream, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def merge_posts(existing: list[dict[str, Any]], fresh: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    by_id = {p["id"]: p for p in existing if isinstance(p, Mapping) and p.get("id")}
    for post in fresh:
        by_id[post["id"]] = post
    kept = [p for p in by_id.values() if now - float(p.get("publishedAt", 0)) < POST_RETENTION]
    kept.sort(key=lambda p: -float(p.get("publishedAt", 0)))
    return kept[:POST_CAP]


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def _name_terms(display_name: str) -> tuple[str, str]:
    """(full name, last name) lowercased, suffixes stripped."""
    words = [w for w in re.split(r"\s+", str(display_name or "").strip()) if w]
    while len(words) > 1 and _SUFFIX.match(words[-1]):
        words.pop()
    full = " ".join(words).lower()
    last = words[-1].lower() if words else ""
    return full, last


def _contains_word(text: str, term: str) -> bool:
    if not term:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _wallclock(event: Mapping[str, Any]) -> float | None:
    raw = str(event.get("wallclock") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def score_post(event: Mapping[str, Any], post: Mapping[str, Any]) -> int:
    played_at = _wallclock(event)
    if played_at is None:
        return 0
    delta = float(post.get("publishedAt", 0)) - played_at
    if delta < -LEAD_SECONDS or delta > TRAIL_SECONDS:
        return 0
    title = str(post.get("title", "")).lower()
    best = 0
    for participant in event.get("participants", []) or []:
        full, last = _name_terms(participant.get("displayName", ""))
        if full and full in title:
            best = max(best, 3)
        elif _contains_word(title, last):
            best = max(best, 2)
    if best == 0:
        return 0
    touchdown = "touchdown" in str(event.get("kind", "")).lower()
    if touchdown and _TOUCHDOWN.search(title):
        best += 2
    elif touchdown:
        best -= 1
    return best


def match_highlights(events: list[dict[str, Any]], posts: list[dict[str, Any]], now: float) -> int:
    """Attach `highlight` to matching events in place. Returns matches made.

    One post serves one play: candidates are ranked by score, then by how
    soon after the play the post appeared, and assigned greedily, so a
    touchdown claims its clip ahead of the same player's earlier short run.
    """
    candidates: list[tuple[int, float, int, dict[str, Any]]] = []
    for index, event in enumerate(events):
        if event.get("lifecycle") == "voided":
            event.pop("highlight", None)
            continue
        played_at = _wallclock(event)
        for post in posts:
            score = score_post(event, post)
            if score >= MIN_SCORE:
                distance = abs(float(post.get("publishedAt", 0)) - (played_at or 0))
                candidates.append((score, distance, index, post))
    candidates.sort(key=lambda c: (-c[0], c[1]))

    chosen: dict[int, dict[str, Any]] = {}
    used_posts: set[str] = set()
    for score, _distance, index, post in candidates:
        if index in chosen or post["id"] in used_posts:
            continue
        chosen[index] = post
        used_posts.add(post["id"])

    matched = 0
    for index, event in enumerate(events):
        post = chosen.get(index)
        if post is None:
            # Keep an earlier match only while its post is not claimed elsewhere.
            current = event.get("highlight")
            if isinstance(current, Mapping) and current.get("id") in used_posts:
                event.pop("highlight", None)
            continue
        current = event.get("highlight")
        if isinstance(current, Mapping) and current.get("id") == post["id"]:
            continue
        played_at = _wallclock(event) or 0.0
        event["highlight"] = {
            "source": "reddit",
            "id": post["id"],
            "title": post["title"],
            "url": post["url"],
            "permalink": post["permalink"],
            "publishedAt": datetime.fromtimestamp(
                float(post["publishedAt"]), timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "latencySeconds": int(round(float(post["publishedAt"]) - played_at)),
        }
        matched += 1
    return matched


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _worth_fetching(snapshot: Mapping[str, Any], now: float) -> bool:
    if snapshot.get("sourceState") == "live":
        return True
    # A clip for the final play of a game can land after the slate goes final.
    for event in snapshot.get("events", []):
        if event.get("highlight") or event.get("lifecycle") == "voided":
            continue
        played_at = _wallclock(event)
        if played_at is not None and 0 <= now - played_at <= TRAIL_SECONDS:
            return True
    return False


def attach(snapshot: dict[str, Any], *, cache_path: Path | None = None,
           now: float | None = None, fetch=fetch_feed) -> dict[str, Any]:
    """Fetch (throttled) and match. Never raises; reports into snapshot.highlights."""
    now = time.time() if now is None else now
    path = cache_path or default_cache_path()
    cache = load_cache(path)
    status: dict[str, Any] = {"source": "reddit", "fetched": False, "error": ""}
    events = snapshot.get("events", [])
    due = (now - float(cache.get("fetchedAt", 0))) >= FETCH_INTERVAL
    if due and now >= float(cache.get("backoffUntil", 0)) and _worth_fetching(snapshot, now):
        try:
            fresh = fetch()
            cache["posts"] = merge_posts(cache.get("posts", []), fresh, now)
            cache["fetchedAt"] = now
            cache["backoffUntil"] = 0
            status["fetched"] = True
        except Exception as error:  # noqa: BLE001 - never fail the refresh
            cache["backoffUntil"] = now + FAILURE_BACKOFF
            status["error"] = " ".join(str(error).split())[:160] or type(error).__name__
    posts = [p for p in cache.get("posts", []) if isinstance(p, Mapping)]
    status["matched"] = match_highlights(events, posts, now)
    status["posts"] = len(posts)
    status["withHighlight"] = sum(1 for e in events if e.get("highlight"))
    try:
        save_cache(path, cache)
    except OSError as error:
        status["error"] = status["error"] or f"cache: {error}"
    snapshot["highlights"] = status
    return snapshot
