# -*- coding: utf-8 -*-
"""Build the daily playlist: fetch, resolve, enrich, pick, order, persist."""
from __future__ import annotations

import random
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta

import enrich
import sources
import store

TARGET = 25
MAX_ATTEMPTS = 110
SOURCE_CAPS = {"kexp": 12, "pitchfork": 5, "allmusic": 5, "bandcamp": 4, "radioparadise": 5}
GENRE_CAP = 4
LOOKBACK_DAYS = 14
ALBUM_LOOKBACK_DAYS = 2
# False = 近期放宽（专辑类不去重）；改成 True 恢复严格去重
STRICT_ALBUM_DEDUPE = False
ALBUM_SOURCES = {"pitchfork", "allmusic", "bandcamp"}
_build_lock = threading.Lock()


def _key(artist: str, title: str) -> str:
    return f"{enrich._norm(artist)}|{enrich._norm(title)}"


def _tidy_title(title: str, album: str) -> str:
    """Strip store-noise suffixes like '[Mixed]' or '(Album Name)'."""
    clean = re.sub(
        r"\s*[\[(](?:mixed|remaster(?:ed)?(?:\s+\d{4})?|explicit|clean|"
        r"deluxe(?: edition)?|bonus track)[\])]\s*$",
        "", title or "", flags=re.I)
    if album:
        clean = re.sub(rf"\s*[\(\[]\s*{re.escape(album)}\s*[\)\]]\s*$", "",
                       clean, flags=re.I)
    clean = re.sub(r"\s*[\(\[]\s*dj\s*[-–]?\s*kicks\s*[\)\]]\s*$", "", clean, flags=re.I)
    return clean.strip() or (title or "").strip()


def _dedupe(candidates):
    best: dict[str, sources.Candidate] = {}
    for c in candidates:
        k = _key(c.artist, c.title or c.album)
        if not k.strip("|"):
            continue
        if k not in best or c.score > best[k].score:
            best[k] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


def _accept(c, selected, artist_seen, source_count, genre_count, strict: bool) -> bool:
    artist = c.artist.strip().lower()
    if not artist or artist in artist_seen:
        return False
    if strict and source_count[c.source] >= SOURCE_CAPS.get(c.source, 6):
        return False
    genre = (c.genre or "").strip().lower()
    if strict and genre and genre_count[genre] >= GENRE_CAP:
        return False
    return True


def _record(c, selected, artist_seen, source_count, genre_count):
    selected.append(c)
    artist_seen.add(c.artist.strip().lower())
    source_count[c.source] += 1
    if c.genre:
        genre_count[c.genre.strip().lower()] += 1


def build(progress=None, force: bool = False, day: str | None = None) -> dict:
    """Generate (or reuse) the playlist for `day` (YYYY-MM-DD)."""
    day = day or date.today().isoformat()

    def report(stage: str, pct: int, detail: str = ""):
        if progress:
            progress({"stage": stage, "pct": pct, "detail": detail})

    with _build_lock:
        if not force:
            cached = store.get_playlist(day)
            if cached and cached.get("tracks"):
                return cached

        report("fetch", 4, "正在连接 KEXP / Pitchfork / AllMusic / Radio Paradise…")
        candidates, errors, stats = sources.fetch_all()
        report("fetch", 18, f"收到 {len(candidates)} 个候选")

        pool = _dedupe(candidates)
        if not pool:
            raise RuntimeError("所有数据源都没有返回内容，检查网络后重试。")

        seen = store.seen_map(30)
        today = date.fromisoformat(day)

        def recently_played(cand, key: str) -> bool:
            last = seen.get(key)
            if not last:
                return False
            # 近期放宽：专辑类来源不做去重（之前用过的也能再用）。
            # 恢复严格去重时把 STRICT_ALBUM_DEDUPE 改成 True 即可。
            if cand.source in ALBUM_SOURCES and not STRICT_ALBUM_DEDUPE:
                return False
            window = ALBUM_LOOKBACK_DAYS if cand.source in ALBUM_SOURCES else LOOKBACK_DAYS
            return last > (today - timedelta(days=window)).isoformat()

        selected: list[sources.Candidate] = []
        artist_seen: set[str] = set()
        source_count: Counter = Counter()
        genre_count: Counter = Counter()
        attempts = 0

        for strict in (True, False):
            for c in pool:
                if len(selected) >= TARGET or attempts >= MAX_ATTEMPTS:
                    break
                if not _accept(c, selected, artist_seen, source_count, genre_count, strict):
                    continue
                # 已知曲目直接跳过，不占用网络请求额度
                if c.kind == "track" and recently_played(c, _key(c.artist, c.title)):
                    continue
                attempts += 1
                pct = min(88, 20 + int(attempts / MAX_ATTEMPTS * 68))
                report("enrich", pct, f"{c.artist} — {c.title or c.album}")
                if not enrich.enrich(c):
                    continue
                key = _key(c.artist, c.title)
                if recently_played(c, key):
                    continue
                _record(c, selected, artist_seen, source_count, genre_count)
            if len(selected) >= TARGET:
                break

        if not selected:
            raise RuntimeError("候选曲目都没能补全信息（封面/链接），稍后再试。")

        report("order", 92, "正在编排顺序…")
        tracks = [{
            "key": _key(c.artist, c.title),
            "artist": c.artist,
            "title": _tidy_title(c.title, c.album),
            "album": c.album,
            "source": c.source,
            "source_label": c.source_label,
            "source_url": c.source_url,
            "context": c.context,
            "released": c.released,
            "genre": c.genre,
            "artwork": c.artwork,
            "netease_url": c.netease_url,
            "score": round(c.score, 2),
        } for c in selected]

        # Hero: prefer the editorial Pitchfork pick, else the top-scored track.
        hero_idx = next((i for i, t in enumerate(tracks) if t["source"] == "pitchfork"), 0)
        hero = tracks.pop(hero_idx)
        rng = random.Random(day)
        rng.shuffle(tracks)
        tracks.insert(0, hero)

        for i, t in enumerate(tracks, 1):
            t["index"] = i

        payload = {
            "date": day,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "tracks": tracks,
            "sources": stats,
            "errors": errors,
            "stats": {
                "candidates": len(candidates),
                "unique": len(pool),
                "selected": len(tracks),
                "lookback_days": LOOKBACK_DAYS,
            },
        }
        store.save_playlist(day, payload)
        store.mark_seen([{"key": t["key"], "artist": t["artist"], "title": t["title"]}
                         for t in tracks])
        report("done", 100, f"完成：{len(tracks)} 首")
        return payload
