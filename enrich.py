# -*- coding: utf-8 -*-
"""Enrichment: canonical metadata, cover art, and NetEase deep links.

iTunes Search API needs no key and powers artwork. NetEase is searched through
its public web endpoint only to build a song link. Everything is cached in
SQLite so a daily rebuild is cheap.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time
import urllib.parse

import store
from sources import FetchError, http_json

GAP_ITUNES = 0.8
GAP_OTHER = 0.20
COOLDOWN_SECONDS = 45
_lock = threading.Lock()
_last = {"itunes": 0.0, "other": 0.0}
_cooldown_until = 0.0


def _throttle(kind: str):
    gap = GAP_ITUNES if kind == "itunes" else GAP_OTHER
    with _lock:
        wait = gap - (time.time() - _last[kind])
        if wait > 0:
            time.sleep(wait)
        _last[kind] = time.time()


def _norm(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"\((?:feat|ft|with)[^)]*\)", " ", s)
    s = re.sub(r"\b(?:feat\.?|ft\.?|featuring)\b.*$", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", s)
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def upscale_artwork(url: str) -> str:
    if not url:
        return ""
    return (url.replace("100x100bb", "600x600bb")
               .replace("60x60bb", "600x600bb")
               .replace("30x30bb", "600x600bb"))


# ---------------------------------------------------------------------------
# iTunes
# ---------------------------------------------------------------------------

def _itunes_search(term: str, entity: str, limit: int):
    global _cooldown_until

    url = ("https://itunes.apple.com/search?" +
           urllib.parse.urlencode({"term": term, "entity": entity,
                                   "limit": limit, "country": "us"}))
    cache_key = "itunes-raw:" + url
    cached = store.cache_get(cache_key, max_age_days=30)
    if cached is not None:
        return cached

    if time.time() < _cooldown_until:
        return []

    results = []
    try:
        _throttle("itunes")
        data = http_json(url)
        results = data.get("results") or []
    except FetchError as exc:
        if "403" in str(exc) or "429" in str(exc):
            # Apple is rate limiting: back off for everyone, keep the build moving.
            _cooldown_until = time.time() + COOLDOWN_SECONDS
        results = []

    # Never cache an empty answer: a transient 403 must not poison future builds.
    if results:
        store.cache_set(cache_key, results)
    return results


def _pack_track(r: dict) -> dict:
    return {
        "artist": r.get("artistName") or "",
        "title": r.get("trackName") or "",
        "album": r.get("collectionName") or "",
        "artwork": upscale_artwork(r.get("artworkUrl100") or ""),
        "genre": r.get("primaryGenreName") or "",
        "released": (r.get("releaseDate") or "")[:10],
        "store_url": r.get("trackViewUrl") or "",
    }


def itunes_track(artist: str, title: str) -> dict:
    key = f"itrack:{_norm(artist)}|{_norm(title)}"
    cached = store.cache_get(key, 60)
    if cached is not None:
        return cached

    na, nt = _norm(artist), _norm(title)
    best, best_score = None, 0.0
    for r in _itunes_search(f"{artist} {title}", "song", 10):
        if r.get("kind") not in (None, "song"):
            continue
        ra, rt = _norm(r.get("artistName", "")), _norm(r.get("trackName", ""))
        score = 0.55 * _sim(na, ra) + 0.45 * _sim(nt, rt)
        if na and ra and (na in ra or ra in na):
            score += 0.08
        if nt and rt and (nt in rt or rt in nt):
            score += 0.08
        if score > best_score:
            best, best_score = r, score

    payload = _pack_track(best) if best and best_score >= 0.60 else {}
    store.cache_set(key, payload)
    return payload


def itunes_album_track(artist: str, album: str) -> dict:
    key = f"ialbum:{_norm(artist)}|{_norm(album)}"
    cached = store.cache_get(key, 60)
    if cached is not None:
        return cached

    na, nal = _norm(artist), _norm(album)
    best, best_score = None, 0.0
    for r in _itunes_search(f"{artist} {album}", "song", 25):
        ra = _norm(r.get("artistName", ""))
        rc = _norm(r.get("collectionName", ""))
        if _sim(na, ra) < 0.55:
            continue
        score = 0.45 * _sim(na, ra) + 0.55 * _sim(nal, rc)
        if nal and rc and (nal in rc or rc in nal):
            score += 0.10
        if r.get("trackNumber") == 1:
            score += 0.04
        if score > best_score:
            best, best_score = r, score

    payload = _pack_track(best) if best and best_score >= 0.55 else {}
    store.cache_set(key, payload)
    return payload


# ---------------------------------------------------------------------------
# NetEase / QQ deep links (no login, search only)
# ---------------------------------------------------------------------------

def _netease_cover(song_id) -> str:
    if not song_id:
        return ""
    try:
        _throttle("other")
        payload = urllib.parse.quote(json.dumps([{"id": song_id}]))
        data = http_json(
            f"https://music.163.com/api/v3/song/detail?c={payload}",
            referer="https://music.163.com/")
        songs = data.get("songs") or []
        if songs:
            return ((songs[0].get("al") or {}).get("picUrl") or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def netease_lookup(artist: str, title: str) -> dict:
    """Return {'url': song page, 'cover': album art} for the best NetEase match."""
    key = f"ne:{_norm(artist)}|{_norm(title)}"
    cached = store.cache_get(key, 60)
    if cached is not None:
        return cached

    result = {"url": "", "cover": ""}
    try:
        _throttle("other")
        q = urllib.parse.quote(f"{artist} {title}")
        data = http_json(
            f"https://music.163.com/api/search/get?s={q}&type=1&limit=8&offset=0",
            referer="https://music.163.com/")
        songs = (data.get("result") or {}).get("songs") or []
        na = _norm(artist)
        for s in songs:
            names = [_norm(a.get("name", "")) for a in (s.get("artists") or [])]
            if any(_sim(na, n) >= 0.55 for n in names if n):
                result["url"] = f"https://music.163.com/song?id={s.get('id')}"
                result["cover"] = _netease_cover(s.get("id"))
                break
    except Exception:  # noqa: BLE001
        pass
    store.cache_set(key, result)
    return result


def netease_link(artist: str, title: str) -> str:
    return netease_lookup(artist, title).get("url", "")


def qq_lookup(artist: str, title: str) -> dict:
    """Deprecated: QQ Music support was removed. Kept so old imports fail softly."""
    return {"url": "", "albummid": ""}


def qq_link(artist: str, title: str) -> str:
    return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich(candidate, progress=None) -> bool:
    """Fill metadata on a Candidate in place. Returns True if usable."""
    if candidate.kind == "album":
        packed = itunes_album_track(candidate.artist, candidate.album)
        if not packed:
            return False
        candidate.title = packed["title"]
        candidate.album = packed.get("album") or candidate.album
        candidate.artwork = candidate.artwork or packed.get("artwork", "")
        candidate.genre = packed.get("genre", "")
        candidate.released = candidate.released or packed.get("released", "")
        candidate.kind = "track"
    else:
        packed = itunes_track(candidate.artist, candidate.title)
        if packed:
            candidate.artwork = candidate.artwork or packed.get("artwork", "")
            candidate.genre = packed.get("genre", "")
            candidate.released = candidate.released or packed.get("released", "")

    if not candidate.title:
        return False

    ne = netease_lookup(candidate.artist, candidate.title)
    candidate.netease_url = ne.get("url", "")
    candidate.qq_url = ""
    if not candidate.artwork and ne.get("cover"):
        candidate.artwork = ne["cover"]
    if progress:
        progress(candidate)
    return True
