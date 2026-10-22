# -*- coding: utf-8 -*-
"""Data sources: pull candidate tracks/albums from curated music sites.

Every fetcher returns (candidates, error_or_None) and never raises, so one
broken upstream never takes down the daily build.
"""
from __future__ import annotations

import gzip
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TIMEOUT = 20
RETRIES = 2


class FetchError(RuntimeError):
    pass


def http_get(url: str, referer: str | None = None, accept: str = "*/*",
             headers: dict | None = None) -> bytes:
    last = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip",
                **({"Referer": referer} if referer else {}),
                **(headers or {}),
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < RETRIES:
                time.sleep(0.8 * (attempt + 1))
    raise FetchError(f"{type(last).__name__}: {last}")


def http_json(url: str, referer: str | None = None):
    return json.loads(http_get(url, referer=referer))


# ---------------------------------------------------------------------------
# Candidate model
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    artist: str
    title: str = ""
    album: str = ""
    source: str = ""
    source_label: str = ""
    source_url: str = ""
    context: str = ""
    released: str = ""
    rotation: str = ""
    score: float = 0.0
    artwork: str = ""
    netease_url: str = ""
    genre: str = ""
    kind: str = "track"          # "track" (ready) or "album" (needs resolving)


def _iso_date(value: str) -> str:
    """Pull YYYY-MM-DD out of an ISO timestamp or plain date."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    return m.group(0) if m else ""


def _recency_bonus(released: str) -> float:
    d = _iso_date(released)
    if not d:
        return 0.0
    try:
        days = (datetime.now() - datetime.strptime(d, "%Y-%m-%d")).days
    except ValueError:
        return 0.0
    if days < -30:
        return 0.0
    if days <= 120:
        return 2.0
    if days <= 400:
        return 1.4
    if days <= 800:
        return 0.7
    return 0.0


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# KEXP — human-curated Seattle radio, publishes every play
# ---------------------------------------------------------------------------

ROTATION_BONUS = {
    "heavy rotation": 2.6,
    "medium rotation": 1.7,
    "light rotation": 0.9,
    "add": 1.2,
    "r&b": 0.5,
    "library": 0.0,
}


def fetch_kexp(hours: int = 24, max_pages: int = 3):
    out: list[Candidate] = []
    seen: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    url = "https://api.kexp.org/v2/plays/?limit=100&ordering=-airdate"
    try:
        for _ in range(max_pages):
            data = http_json(url)
            results = data.get("results") or []
            if not results:
                break
            reached_old = False
            for play in results:
                airdate = play.get("airdate") or ""
                try:
                    when = datetime.fromisoformat(airdate)
                except ValueError:
                    continue
                if when < cutoff:
                    reached_old = True
                    break
                if play.get("play_type") != "trackplay":
                    continue
                artist = _clean(play.get("artist") or "")
                song = _clean(play.get("song") or "")
                if not artist or not song or artist.lower() in {"various artists", "n/a"}:
                    continue
                key = f"{artist.lower()}|{song.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                rotation = _clean(play.get("rotation_status") or "")
                bonus = ROTATION_BONUS.get(rotation.lower(), 0.0)
                released = _iso_date(play.get("release_date") or "")
                out.append(Candidate(
                    artist=artist,
                    title=song,
                    album=_clean(play.get("album") or ""),
                    source="kexp",
                    source_label="KEXP",
                    source_url="https://www.kexp.org/",
                    context=f"KEXP 播出 · {when.astimezone().strftime('%m-%d %H:%M')}",
                    released=released,
                    rotation=rotation,
                    score=3.2 + bonus + _recency_bonus(released),
                ))
            if reached_old:
                break
            nxt = data.get("next")
            if not nxt:
                break
            url = nxt
        return out, None
    except Exception as exc:  # noqa: BLE001
        return out, f"KEXP: {exc}"


# ---------------------------------------------------------------------------
# Radio Paradise — six hand-programmed channels, now-playing endpoint
# ---------------------------------------------------------------------------

RP_CHANNELS = {
    0: "主混音",
    1: "Mellow",
    2: "Rock",
    3: "Global",
    4: "Eclectic",
    5: "Serenity",
}


def fetch_radioparadise():
    out: list[Candidate] = []
    errors = []
    for chan, name in RP_CHANNELS.items():
        try:
            d = http_json(f"https://api.radioparadise.com/api/now_playing?chan={chan}")
            artist = _clean(d.get("artist") or "")
            title = _clean(d.get("title") or "")
            if not artist or not title:
                continue
            out.append(Candidate(
                artist=artist,
                title=title,
                album=_clean(d.get("album") or ""),
                source="radioparadise",
                source_label="Radio Paradise",
                source_url="https://radioparadise.com/",
                context=f"Radio Paradise · {name}频道正在播",
                released=_iso_date(str(d.get("year") or "")),
                artwork=_clean(d.get("cover") or ""),
                score=2.2 + (0.6 if chan == 0 else 0.0),
            ))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"RP chan{chan}: {exc}")
    return out, ("; ".join(errors) if errors else None)


# ---------------------------------------------------------------------------
# Pitchfork — Best New Albums page (JSON-LD list) + per-review og:title
# ---------------------------------------------------------------------------

def _pitchfork_items(limit: int = 6):
    raw = http_get("https://pitchfork.com/reviews/best/albums/",
                   referer="https://pitchfork.com/")
    page = raw.decode("utf-8", "replace")
    items = []
    for block in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        entries = data.get("itemListElement") if isinstance(data, dict) else None
        if not entries:
            continue
        for entry in entries:
            name = _clean(re.sub(r"[*_]", "", str(entry.get("name") or "")))
            url = str(entry.get("url") or "")
            if name and url:
                items.append((name, url))
        break
    return items[:limit]


def fetch_pitchfork(limit: int = 8):
    out: list[Candidate] = []
    errors = []
    try:
        items = _pitchfork_items(limit)
    except Exception as exc:  # noqa: BLE001
        return out, f"Pitchfork: {exc}"
    if not items:
        return out, "Pitchfork: 未能解析最佳新专辑列表"
    for name, url in items:
        try:
            page = http_get(url, referer="https://pitchfork.com/").decode("utf-8", "replace")
            m = re.search(r'<meta property="og:title" content="([^"]+)"', page)
            title = html.unescape(m.group(1)) if m else name
            img = re.search(r'<meta property="og:image" content="([^"]+)"', page)
            artist, album = "", title
            if ": " in title:
                artist, album = title.split(": ", 1)
            out.append(Candidate(
                artist=_clean(artist),
                album=_clean(album),
                title="",
                source="pitchfork",
                source_label="Pitchfork",
                source_url=url,
                context="Pitchfork 最佳新专辑",
                artwork=_clean(img.group(1)) if img else "",
                score=4.4,
                kind="album",
            ))
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Pitchfork {url.rsplit('/', 2)[-2]}: {exc}")
    return out, ("; ".join(errors) if errors else None)


# ---------------------------------------------------------------------------
# AllMusic — editor-selected weekly new releases (JSON-LD CollectionPage)
# ---------------------------------------------------------------------------

ALLMUSIC_HEADERS = {
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Encoding": "identity",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_allmusic(limit: int = 10):
    out: list[Candidate] = []
    try:
        page = http_get("https://www.allmusic.com/newreleases",
                        referer="https://www.allmusic.com/",
                        headers=ALLMUSIC_HEADERS).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return out, f"AllMusic: {exc}"

    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data.get("hasPart") if isinstance(data, dict) else None
        if not items:
            continue
        for it in items[:limit]:
            name = _clean(str(it.get("name") or ""))
            by_artist = it.get("byArtist")
            if isinstance(by_artist, list):
                artist = _clean(", ".join(
                    str((a or {}).get("name") or "") for a in by_artist if isinstance(a, dict)))
            elif isinstance(by_artist, dict):
                artist = _clean(str(by_artist.get("name") or ""))
            else:
                artist = ""
            url = str(it.get("url") or "")
            if not name or not artist:
                continue
            out.append(Candidate(
                artist=artist,
                title="",
                album=name,
                source="allmusic",
                source_label="AllMusic",
                source_url=url,
                context="AllMusic 本周精选新碟",
                artwork=_clean(str(it.get("image") or "")),
                score=4.0,
                kind="album",
            ))
        break
    return out, None


# ---------------------------------------------------------------------------
# Aquarium Drunkard — editorial album picks titled "Artist :: Album"
# ---------------------------------------------------------------------------

AQUARIUM_SKIP = (
    "interview", "transmissions", "the aquarium drunkard show", "introducing",
    "rfad", "podcast", "mixtape", "radio free",
)

AQUARIUM_TITLE = re.compile(r"^(.{2,90}?)\s*::\s*(.{2,120})$")


def _rss_entries(raw: bytes):
    """Tolerant RSS <item> scan (some feeds are not well-formed XML)."""
    text = raw.decode("utf-8", "replace")
    for chunk in re.findall(r"<item\b[^>]*>(.*?)</item>", text, re.S | re.I):
        title_m = re.search(r"<title>(.*?)</title>", chunk, re.S | re.I)
        title = title_m.group(1) if title_m else ""
        title = re.sub(r"^\s*<!\[CDATA\[(.*?)\]\]>\s*$", r"\1", title, flags=re.S)
        link_m = re.search(r"<link>(.*?)</link>", chunk, re.S | re.I)
        link = (link_m.group(1) if link_m else "").strip()
        yield _clean(title), link


def fetch_aquarium(limit: int = 6):
    out: list[Candidate] = []
    try:
        raw = http_get("https://aquariumdrunkard.com/feed/",
                       referer="https://aquariumdrunkard.com/")
    except Exception as exc:  # noqa: BLE001
        return out, f"Aquarium: {exc}"

    for title, link in _rss_entries(raw):
        if len(out) >= limit:
            break
        if not title or not link:
            continue
        if any(word in title.lower() for word in AQUARIUM_SKIP):
            continue
        match = AQUARIUM_TITLE.match(title)
        if not match:
            continue
        artist, album = match.group(1).strip(), match.group(2).strip()
        if not artist or not album:
            continue
        out.append(Candidate(
            artist=artist,
            title="",
            album=album,
            source="aquarium",
            source_label="Aquarium Drunkard",
            source_url=link,
            context="Aquarium Drunkard 推荐",
            score=4.0,
            kind="album",
        ))
    return out, (None if out else "Aquarium: 0 matched")


# ---------------------------------------------------------------------------
# The Quietus — editorial reviews; titles vary, so parse defensively
# ---------------------------------------------------------------------------

QUIETUS_SKIP = (
    "interview", "live report", "news", "column", "feature", "playlist",
    "premiere", "video", "photo", "podcast", "competition", "subscriber",
)

QUIETUS_PREFIX = re.compile(
    r"^(?:album\s+(?:review|of\s+the\s+week)|reviews?|track\s+review|"
    r"film|book|live)\s*[:\-–—]\s*", re.I)

QUIETUS_SPLIT = re.compile(r"\s+(?:–|—|::|\|)\s+")


def fetch_quietus(limit: int = 5):
    out: list[Candidate] = []
    try:
        raw = http_get("https://thequietus.com/feed",
                       referer="https://thequietus.com/")
    except Exception as exc:  # noqa: BLE001
        return out, f"Quietus: {exc}"

    samples = []
    for title, link in _rss_entries(raw):
        if len(out) >= limit:
            break
        if not title or not link:
            continue
        if any(word in title.lower() for word in QUIETUS_SKIP):
            continue
        stripped = QUIETUS_PREFIX.sub("", title).strip()
        parts = QUIETUS_SPLIT.split(stripped, maxsplit=1)
        if len(parts) != 2:
            if len(samples) < 4:
                samples.append(title[:50])
            continue
        artist, album = parts[0].strip(), parts[1].strip()
        if not artist or not album:
            continue
        out.append(Candidate(
            artist=artist,
            title="",
            album=album,
            source="quietus",
            source_label="The Quietus",
            source_url=link,
            context="The Quietus 乐评",
            score=4.2,
            kind="album",
        ))
    if out:
        return out, None
    return out, f"Quietus: 0 matched; samples={samples}"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def fetch_all():
    candidates: list[Candidate] = []
    errors: list[str] = []
    stats: dict[str, int] = {}

    for name, fetcher in (("kexp", fetch_kexp), ("pitchfork", fetch_pitchfork),
                          ("allmusic", fetch_allmusic), ("aquarium", fetch_aquarium),
                          ("quietus", fetch_quietus),
                          ("radioparadise", fetch_radioparadise)):
        items, err = fetcher()
        stats[name] = len(items)
        candidates.extend(items)
        if err:
            errors.append(err)
    return candidates, errors, stats
