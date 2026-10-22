# -*- coding: utf-8 -*-
"""Generate the static site: one HTML page per day plus a JSON archive.

Usage:
    python export_site.py            # build today, then render
    python export_site.py --no-build # render from existing data/*.json

Output (site/):
    index.html            -> newest day
    {date}.html           -> one page per day
    data/{date}.json      -> raw playlist payload
    data/index.json       -> list of available days
    assets/style.css      -> copy of the local stylesheet
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
from html import escape

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import builder  # noqa: E402

SITE = os.path.join(BASE, "site")
DATA = os.path.join(SITE, "data")
ASSETS = os.path.join(SITE, "assets")
REGENERATE_URL = os.environ.get("REGENERATE_URL", "")

SOURCE_NAMES = {
    "kexp": "KEXP",
    "pitchfork": "Pitchfork",
    "aquarium": "Aquarium Drunkard",
    "quietus": "The Quietus",
    "soulbounce": "SoulBounce",
    "radioparadise": "Radio Paradise",
}


def orpheus_url(song_id: str) -> str:
    command = {"type": "song", "id": str(song_id), "cmd": "play"}
    encoded = base64.b64encode(
        json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"orpheus://{encoded}"


def song_id(url: str) -> str:
    if not url or "id=" not in url:
        return ""
    return url.rsplit("id=", 1)[-1].split("&")[0]


def available_days() -> list[str]:
    if not os.path.isdir(DATA):
        return []
    return sorted(
        (name[:-5] for name in os.listdir(DATA)
         if name.endswith(".json") and name != "index.json"),
        reverse=True,
    )


def load_day(day: str) -> dict:
    with open(os.path.join(DATA, f"{day}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def track_row(index: int, track: dict) -> str:
    sid = song_id(track.get("netease_url", ""))
    art = track.get("artwork") or ""
    cover = (f'<img src="{escape(art)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
             if art else
             f'<div class="cover-fallback" style="background:hsl({(index * 47) % 360} 40% 45%)">'
             f'{escape((track.get("artist") or "?")[:1].upper())}</div>')
    cloud = (f'<a class="icon-btn" href="{escape(orpheus_url(sid))}" '
             f'title="在网易云客户端播放">云</a>' if sid else
             '<span class="icon-btn disabled" title="没有匹配到网易云">云</span>')
    web = (f'<a class="icon-btn" href="{escape(track.get("netease_url", ""))}" '
           f'target="_blank" rel="noopener" title="打开网页版">网</a>' if track.get("netease_url") else "")
    album = f'<span class="dot">·</span>{escape(track.get("album", ""))}' if track.get("album") else ""
    source_name = SOURCE_NAMES.get(track.get("source", ""), track.get("source", ""))
    selected = " selected" if index == 1 else ""
    data = (f'data-artist="{escape(track.get("artist", ""))}" '
            f'data-album="{escape(track.get("album", ""))}" '
            f'data-context="{escape(track.get("context", ""))}" '
            f'data-artwork="{escape(art)}" '
            f'data-orpheus="{escape(orpheus_url(sid)) if sid else ""}" '
            f'data-web="{escape(track.get("netease_url", ""))}" '
            f'data-source-url="{escape(track.get("source_url", ""))}" '
            f'data-source-name="{escape(source_name)}"')
    return f"""
      <li class="track{selected}" {data}>
        <div class="idx"><span class="num">{index:02d}</span></div>
        <div class="cover-wrap">{cover}</div>
        <div class="t-main">
          <div class="t-title">{escape(track.get("title", "未知曲目"))}</div>
          <div class="t-sub">{escape(track.get("artist", ""))}{album}</div>
        </div>
        <div class="t-side">
          <div class="row-actions">{cloud}{web}</div>
        </div>
      </li>"""


def render_page(day: str, payload: dict, days: list[str]) -> str:
    tracks = payload.get("tracks", [])
    hero = tracks[0] if tracks else {}
    sources = payload.get("sources", {})

    totals: dict[str, int] = {}
    for t in tracks:
        totals[t.get("source", "")] = totals.get(t.get("source", ""), 0) + 1

    source_rows = "".join(
        f'<li><span>{escape(SOURCE_NAMES[k])}</span><span class="n">{totals.get(k, 0)} / {sources.get(k, 0)}</span></li>'
        for k in SOURCE_NAMES
        if sources.get(k) or totals.get(k)
    )

    history_rows = "".join(
        f'<li><a href="{d}.html">{d}</a></li>' for d in days[:30]
    )

    hero_sid = song_id(hero.get("netease_url", ""))
    hero_cover = hero.get("artwork") or ""

    regen = (f'<a class="ghost-btn" href="{escape(REGENERATE_URL)}" target="_blank" rel="noopener">重新生成</a>'
             if REGENERATE_URL else "")

    rows = "".join(track_row(i, t) for i, t in enumerate(tracks, 1))
    errors = payload.get("errors") or []
    error_note = (f'<p class="hint warn">部分来源失败：{escape("；".join(errors))}</p>'
                  if errors else "")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{day} · Soulboy</title>
<link rel="stylesheet" href="assets/style.css">
<style>
  /* 静态页没有悬停态，操作按钮常显 */
  .row-actions{{opacity:1;transform:none}}
  .source-list a{{color:var(--text);text-decoration:none}}
  .source-list a:hover{{color:var(--accent)}}
  .track{{cursor:pointer}}
  .track.selected{{background:rgba(255,255,255,.055)}}
  .track.selected .t-title{{color:var(--accent)}}
</style>
</head>
<body>
<div class="bg-glow"></div>
<header class="topbar">
  <div class="brand">
    <span class="brand-dot"></span>
    <span class="brand-name">Soulboy</span>
    <span class="brand-sub">DAILY MIX</span>
  </div>
  <div class="top-actions">{regen}</div>
</header>

<main>
  <section class="layout">
    <div class="col-main">
      <div class="meta-line">
        <span class="mono">{day}</span>
        <span class="meta-sep">/</span>
        <span class="mono">{len(tracks)} 首 / {len({t.get('source') for t in tracks})} 个来源</span>
      </div>
      <ol class="track-list">{rows}</ol>
    </div>

    <aside class="col-side">
      <div class="card pick-card">
        <p class="card-label" id="pickLabel">今日主打</p>
        <div class="pick-cover"><img id="pickImg" src="{escape(hero_cover)}" alt="" referrerpolicy="no-referrer"></div>
        <h2 class="pick-artist" id="pickArtist">{escape(hero.get("artist", ""))}</h2>
        <p class="pick-album" id="pickAlbum">{escape(hero.get("album", ""))}</p>
        <p class="pick-context" id="pickContext">{escape(hero.get("context", ""))}</p>
        <div class="pick-actions">
          <a class="chip" id="pickNetease" href="{escape(orpheus_url(hero_sid)) if hero_sid else '#'}">在客户端播放</a>
          <a class="chip" id="pickWeb" href="{escape(hero.get("netease_url", "")) if hero.get("netease_url") else '#'}" target="_blank" rel="noopener">网页版</a>
        </div>
        <a class="source-link" id="pickSource" href="{escape(hero.get("source_url", "#"))}" target="_blank" rel="noopener">→ 查看原文</a>
      </div>

      <div class="card">
        <p class="card-label">今日来源</p>
        <ul class="source-list"><li class="head"><span>来源</span><span class="n">已选/候选</span></li>{source_rows}</ul>
        {error_note}
      </div>

      <div class="card">
        <p class="card-label">历史</p>
        <ul class="source-list">{history_rows or '<li><span>还没有更早的歌单</span></li>'}</ul>
      </div>
    </aside>
  </section>
</main>

<script>
(function () {{
  var rows = Array.prototype.slice.call(document.querySelectorAll('.track'));
  var pick = {{
    label: document.getElementById('pickLabel'),
    img: document.getElementById('pickImg'),
    artist: document.getElementById('pickArtist'),
    album: document.getElementById('pickAlbum'),
    context: document.getElementById('pickContext'),
    netease: document.getElementById('pickNetease'),
    web: document.getElementById('pickWeb'),
    source: document.getElementById('pickSource')
  }};
  function select(row) {{
    rows.forEach(function (r) {{ r.classList.remove('selected'); }});
    row.classList.add('selected');
    pick.label.textContent = '正在查看';
    var art = row.dataset.artwork || '';
    if (art) {{
      pick.img.src = art;
      pick.img.style.display = 'block';
    }} else {{
      pick.img.removeAttribute('src');
      pick.img.style.display = 'none';
    }}
    pick.artist.textContent = row.dataset.artist || '';
    pick.album.textContent = row.dataset.album || '';
    pick.context.textContent = row.dataset.context || '';
    if (row.dataset.orpheus) {{
      pick.netease.href = row.dataset.orpheus;
      pick.netease.classList.remove('disabled');
    }} else {{
      pick.netease.href = '#';
      pick.netease.classList.add('disabled');
    }}
    if (row.dataset.web) {{
      pick.web.href = row.dataset.web;
      pick.web.classList.remove('disabled');
    }} else {{
      pick.web.href = '#';
      pick.web.classList.add('disabled');
    }}
    pick.source.href = row.dataset.sourceUrl || '#';
    pick.source.textContent = row.dataset.sourceName
      ? '→ 查看 ' + row.dataset.sourceName + ' 原文'
      : '→ 查看原文';
  }}
  rows.forEach(function (row) {{
    row.addEventListener('click', function (ev) {{
      if (ev.target.closest('a')) return;
      select(row);
    }});
  }});
}})();
</script>
</body>
</html>
"""


def main():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(ASSETS, exist_ok=True)

    if "--no-build" not in sys.argv:
        payload = builder.build(force=True)
        day = payload["date"]
        with open(os.path.join(DATA, f"{day}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
    else:
        days = available_days()
        if not days:
            raise SystemExit("data/ 里没有可渲染的 JSON")
        day = days[0]

    shutil.copyfile(os.path.join(BASE, "web", "style.css"),
                    os.path.join(ASSETS, "style.css"))

    days = available_days()
    rendered = []
    for d in days:
        try:
            data = load_day(d)
        except (OSError, json.JSONDecodeError):
            print(f"  skip unreadable {d}.json")
            continue
        with open(os.path.join(SITE, f"{d}.html"), "w", encoding="utf-8") as fh:
            fh.write(render_page(d, data, days))
        rendered.append(d)

    if not rendered:
        raise SystemExit("没有可渲染的歌单数据")

    latest = rendered[0]
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_page(latest, load_day(latest), days))

    with open(os.path.join(DATA, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"days": rendered}, fh, ensure_ascii=False, indent=1)

    print(f"static site ready: {SITE} ({len(rendered)} day(s), latest {latest})")


if __name__ == "__main__":
    main()
