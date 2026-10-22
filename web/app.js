/* Soulboy — frontend */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    playlist: null,
    pollTimer: null,
    pollCount: 0,
  };

  const SOURCE_NAMES = {
    kexp: "KEXP",
    pitchfork: "Pitchfork",
    aquarium: "Aquarium Drunkard",
    quietus: "The Quietus",
    soulbounce: "SoulBounce",
    blow: "吹音乐 Blow",
    radioparadise: "Radio Paradise",
  };

  /* ---------------- helpers ---------------- */

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function todayLocal() {
    const d = new Date();
    const off = d.getTimezoneOffset();
    return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
  }

  function weekdayCN(iso) {
    const names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    const d = new Date(`${iso}T00:00:00`);
    return Number.isNaN(d.getTime()) ? "" : names[d.getDay()];
  }

  function hueFor(text) {
    let h = 0;
    for (let i = 0; i < (text || "x").length; i++) h = (h * 31 + text.charCodeAt(i)) % 360;
    return h;
  }

  function formatBytes(n) {
    if (!n) return "0 KB";
    if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function toast(msg) {
    let box = document.querySelector(".toast");
    if (!box) {
      box = el("div", "toast");
      document.body.append(box);
    }
    box.textContent = msg;
    box.classList.add("show");
    clearTimeout(box._timer);
    box._timer = setTimeout(() => box.classList.remove("show"), 2200);
  }

  /* ---------------- 网易云 ---------------- */

  function clientSongId(neteaseUrl) {
    const match = /[?&]id=(\d+)/.exec(neteaseUrl || "");
    return match ? match[1] : "";
  }

  function isLocalOrigin() {
    return ["127.0.0.1", "localhost"].includes(location.hostname);
  }

  function openInClient(songId, webUrl) {
    fetch("/api/open-client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: songId }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        toast("已发送到网易云客户端");
      })
      .catch(() => {
        toast("本地服务没响应，已改用网页版");
        if (webUrl) window.open(webUrl, "_blank", "noopener");
      });
  }

  function openTrack(track) {
    const songId = clientSongId(track.netease_url);
    if (isLocalOrigin() && songId) {
      openInClient(songId, track.netease_url);
    } else if (track.netease_url) {
      window.open(track.netease_url, "_blank", "noopener");
    } else {
      toast("没有匹配到网易云链接");
    }
  }

  /* ---------------- view ---------------- */

  function showLoading(progress) {
    $("loading").classList.remove("hidden");
    $("content").classList.add("hidden");
    $("errorState").classList.add("hidden");
    if (progress) {
      const pct = Math.max(2, Math.min(100, progress.pct || 0));
      $("loadBar").style.width = `${pct}%`;
      if (progress.detail) $("loadDetail").textContent = progress.detail;
    }
  }

  function showError(message) {
    $("loading").classList.add("hidden");
    $("content").classList.add("hidden");
    $("errorState").classList.remove("hidden");
    $("errDetail").textContent = message || "未知错误";
  }

  function showContent() {
    $("loading").classList.add("hidden");
    $("errorState").classList.add("hidden");
    $("content").classList.remove("hidden");
  }

  /* ---------------- loading ---------------- */

  async function load(date) {
    try {
      const data = await api(date ? `/api/today?date=${encodeURIComponent(date)}` : "/api/today");
      if (data.playlist) {
        stopPolling();
        render(data.playlist);
        return;
      }
      if (data.status === "building") {
        showLoading(data.progress);
        startPolling(date);
        return;
      }
      stopPolling();
      showLoading(data.progress || null);
      showError(data.error || "这一天还没有歌单。");
    } catch (err) {
      showError(`连接本地服务失败：${err.message}`);
    }
  }

  function startPolling(date) {
    if (state.pollTimer) return;
    state.pollCount = 0;
    state.pollTimer = setInterval(async () => {
      state.pollCount += 1;
      try {
        const data = await api(`/api/today${date ? `?date=${encodeURIComponent(date)}` : ""}`);
        if (data.playlist) {
          stopPolling();
          render(data.playlist);
        } else if (data.status === "building") {
          showLoading(data.progress);
        } else {
          stopPolling();
          showError(data.error || "生成失败。");
        }
      } catch (err) {
        if (state.pollCount > 40) {
          stopPolling();
          showError("轮询超时，请刷新页面重试。");
        }
      }
    }, 1300);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  /* ---------------- render ---------------- */

  function render(playlist) {
    state.playlist = playlist;
    showContent();
    document.title = `${playlist.date} · Soulboy`;

    $("dateLabel").textContent = `${playlist.date} ${weekdayCN(playlist.date)}`;
    const sourceCount = new Set(playlist.tracks.map((t) => t.source)).size;
    $("statsLabel").textContent = `${playlist.tracks.length} 首 / ${sourceCount} 个来源`;

    renderTracks(playlist.tracks);
    renderPick(playlist.tracks[0]);
    renderSources(playlist);
    syncArchive(playlist.date);
    loadStats();
  }

  function coverNode(entry) {
    const wrap = el("div", "cover-wrap");
    if (entry.artwork) {
      const img = document.createElement("img");
      img.src = entry.artwork;
      img.alt = "";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", () => {
        img.remove();
        wrap.append(fallbackNode(entry, 52));
      });
      wrap.append(img);
    } else {
      wrap.append(fallbackNode(entry, 52));
    }
    return wrap;
  }

  function fallbackNode(entry, size) {
    const fb = el("div", "cover-fallback", (entry.artist || "?").trim().charAt(0).toUpperCase());
    const hue = hueFor(entry.artist || entry.album || "x");
    fb.style.background = `linear-gradient(135deg, hsl(${hue} 45% 58%), hsl(${(hue + 40) % 360} 40% 40%))`;
    if (size) fb.style.fontSize = `${Math.round(size * 0.36)}px`;
    return fb;
  }

  function renderTracks(tracks) {
    const list = $("trackList");
    list.textContent = "";
    tracks.forEach((track, i) => {
      const li = el("li", "track");
      li.dataset.index = String(i);

      const idx = el("div", "idx");
      idx.append(el("span", "num", String(i + 1).padStart(2, "0")));

      const main = el("div", "t-main");
      main.append(el("div", "t-title", track.title || "未知曲目"));
      const sub = el("div", "t-sub");
      sub.append(document.createTextNode(track.artist || "未知艺人"));
      if (track.album) {
        sub.append(el("span", "dot", "·"));
        sub.append(document.createTextNode(track.album));
      }
      main.append(sub);

      const side = el("div", "t-side");

      const actions = el("div", "row-actions");
      const ne = el("button", "icon-btn", "云");
      ne.type = "button";
      ne.title = "在网易云播放";
      ne.setAttribute("aria-label", "在网易云播放");
      if (!track.netease_url) {
        ne.classList.add("disabled");
        ne.disabled = true;
      }
      ne.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (track.netease_url) openTrack(track);
      });
      actions.append(ne);
      side.append(actions);

      li.append(idx, coverNode(track), main, side);
      li.addEventListener("click", (ev) => {
        if (ev.target.closest("a, button")) return;
        selectTrack(i);
      });
      list.append(li);
    });
  }

  function selectTrack(index) {
    const track = state.playlist && state.playlist.tracks[index];
    if (!track) return;
    renderPick(track, false);
    document.querySelectorAll(".track").forEach((row) => {
      row.classList.toggle("selected", Number(row.dataset.index) === index);
    });
  }

  function renderPick(track, initial = true) {
    $("pickLabel").textContent = initial ? "今日主打" : "正在查看";
    const img = $("pickImg");
    const initialEl = $("pickInitial");
    img.style.display = track.artwork ? "block" : "none";
    initialEl.style.display = track.artwork ? "none" : "flex";
    initialEl.textContent = (track.artist || "?").trim().charAt(0).toUpperCase();
    const hue = hueFor(track.artist || "x");
    initialEl.style.background = `linear-gradient(135deg, hsl(${hue} 45% 58%), hsl(${(hue + 40) % 360} 40% 40%))`;
    img.onerror = () => {
      img.style.display = "none";
      initialEl.style.display = "flex";
    };
    if (track.artwork) img.src = track.artwork;

    $("pickArtist").textContent = track.artist || "未知艺人";
    $("pickAlbum").textContent = track.album || track.title || "";
    $("pickContext").textContent = track.context || "";
    $("pickSource").textContent = track.source_url
      ? `→ 查看 ${SOURCE_NAMES[track.source] || track.source} 原文`
      : "";
    $("pickSource").href = track.source_url || "#";

    const songId = clientSongId(track.netease_url);
    const ne = $("pickNetease");
    if (songId) {
      ne.href = track.netease_url;
      ne.classList.remove("disabled");
      ne.onclick = (ev) => {
        if (isLocalOrigin()) {
          ev.preventDefault();
          openInClient(songId, track.netease_url);
        }
      };
    } else {
      ne.href = "#";
      ne.classList.add("disabled");
      ne.onclick = null;
    }
    const web = $("pickWeb");
    if (track.netease_url) {
      web.href = track.netease_url;
      web.classList.remove("disabled");
    } else {
      web.href = "#";
      web.classList.add("disabled");
    }

    $("dtGenre").textContent = track.genre || "未知";
    $("dtYear").textContent = track.year || (track.released || "").slice(0, 4) || "未知";
    $("dtArtist").textContent = track.artist || "未知";
    $("dtAlbum").textContent = track.album || "未知";

    const review = track.excerpt_zh || track.excerpt || "";
    $("dtReview").textContent = review;
    $("reviewBlock").style.display = review ? "block" : "none";
  }

  function renderSources(playlist) {
    const list = $("sourceList");
    list.textContent = "";

    const head = el("li", "head");
    head.append(el("span", "", "来源"));
    head.append(el("span", "n", "已选/候选"));
    list.append(head);

    const sources = playlist.sources || {};
    const totals = {};
    playlist.tracks.forEach((t) => {
      totals[t.source] = (totals[t.source] || 0) + 1;
    });
    Object.keys(SOURCE_NAMES).forEach((key) => {
      if (!(sources[key] || totals[key])) return;
      const li = el("li");
      li.append(el("span", "", SOURCE_NAMES[key]));
      li.append(el("span", "n", `${totals[key] || 0} / ${sources[key] || 0}`));
      li.title = "已选 / 候选";
      list.append(li);
    });
    const errors = playlist.errors || [];
    $("sourceErrors").textContent = errors.length ? `部分来源失败：${errors.join("；")}` : "";
  }

  let archiveLoaded = false;
  async function syncArchive(selected) {
    if (!archiveLoaded) {
      try {
        const data = await api("/api/archive");
        const sel = $("archive");
        sel.textContent = "";
        (data.dates || []).forEach((d) => {
          const opt = document.createElement("option");
          opt.value = d.date;
          opt.textContent = d.date;
          sel.append(opt);
        });
        if (!data.dates || !data.dates.length) {
          const opt = document.createElement("option");
          opt.value = selected;
          opt.textContent = selected;
          sel.append(opt);
        }
        archiveLoaded = true;
      } catch (err) {
        return;
      }
    }
    $("archive").value = selected;
  }

  async function loadStats() {
    try {
      const s = await api("/api/stats");
      $("dbStats").textContent =
        `${formatBytes(s.bytes)} · 歌单 ${s.playlists} · 去重 ${s.seen} · 缓存 ${s.cache}`;
    } catch (err) {
      $("dbStats").textContent = "统计读取失败";
    }
  }

  /* ---------------- export ---------------- */

  function buildText() {
    if (!state.playlist) return "";
    const lines = state.playlist.tracks.map((t, i) =>
      `${String(i + 1).padStart(2, "0")}. ${t.artist} — ${t.title}`);
    return `Soulboy ${state.playlist.date}\n${"-".repeat(28)}\n${lines.join("\n")}`;
  }

  function download(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function csvEscape(value) {
    const s = String(value ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function buildCSV() {
    const rows = [["序号", "艺人", "曲目", "专辑", "来源", "网易云", "原文"]];
    state.playlist.tracks.forEach((t, i) => {
      rows.push([i + 1, t.artist, t.title, t.album, SOURCE_NAMES[t.source] || t.source,
                 t.netease_url, t.source_url]);
    });
    return "\ufeff" + rows.map((r) => r.map(csvEscape).join(",")).join("\r\n");
  }

  $("copyBtn").addEventListener("click", async () => {
    const text = buildText();
    try {
      await navigator.clipboard.writeText(text);
      toast("清单已复制");
    } catch (err) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("清单已复制");
    }
  });

  $("csvBtn").addEventListener("click", () => {
    if (!state.playlist) return;
    download(`soulboy-${state.playlist.date}.csv`, buildCSV(), "text/csv;charset=utf-8");
  });

  $("clearBtn").addEventListener("click", async () => {
    const ok = confirm(
      "清理过往缓存？\n\n" +
      "会删除：今天之前的历史歌单、封面与网易云匹配缓存、30 天前的去重记录。\n" +
      "今天的歌单会保留。此操作不可撤销。");
    if (!ok) return;

    const btn = $("clearBtn");
    btn.disabled = true;
    btn.textContent = "清理中…";
    try {
      const res = await api("/api/clear-cache", { method: "POST" });
      const c = res.cleared;
      toast(`已清理 ${c.playlists} 张历史歌单、${c.cache} 条缓存、${c.seen} 条旧去重记录`);
      archiveLoaded = false;
      await syncArchive(state.playlist ? state.playlist.date : todayLocal());
      await loadStats();
    } catch (err) {
      toast("清理失败：" + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "清理过往缓存";
    }
  });

  /* ---------------- events ---------------- */

  $("refresh").addEventListener("click", async () => {
    try {
      $("refresh").disabled = true;
      await api("/api/refresh", { method: "POST" });
      showLoading({ pct: 3, detail: "重新生成中…" });
      startPolling($("archive").value || null);
    } catch (err) {
      toast("启动失败：" + err.message);
    } finally {
      setTimeout(() => { $("refresh").disabled = false; }, 1500);
    }
  });

  $("retryBtn").addEventListener("click", () => load($("archive").value || null));
  $("archive").addEventListener("change", (ev) => load(ev.target.value));

  /* ---------------- 卡片堆叠 ---------------- */

  function initDeck(root) {
    if (!root) return;
    const cards = Array.from(root.querySelectorAll(".deck-card"));
    let front = 0;
    let animating = false;

    const render = () => {
      cards.forEach((card, i) => {
        card.classList.toggle("is-front", i === front);
        card.classList.toggle("is-back", i !== front);
        card.classList.remove("leaving");
      });
    };

    const swap = () => {
      if (animating) return;
      animating = true;
      cards[front].classList.add("leaving");
      setTimeout(() => {
        front = (front + 1) % cards.length;
        render();
        setTimeout(() => { animating = false; }, 80);
      }, 300);
    };

    const back = () => {
      if (animating) return;
      animating = true;
      front = (front - 1 + cards.length) % cards.length;
      const card = cards[front];
      cards.forEach((c, i) => {
        c.classList.toggle("is-front", i === front);
        c.classList.toggle("is-back", i !== front);
        c.classList.remove("leaving");
      });
      card.classList.add("entering");
      void card.offsetWidth;
      requestAnimationFrame(() => card.classList.remove("entering"));
      setTimeout(() => { animating = false; }, 440);
    };

    /* 左键点一下切换；滚轮交给页面正常滚动 */
    root.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return;
      if (front === 0) swap(); else back();
    });

    render();
  }

  /* ---------------- boot ---------------- */

  initDeck($("deck"));
  load(null);
  setInterval(() => {
    if (!state.playlist) return;
    const today = todayLocal();
    if (state.playlist.date !== today) {
      archiveLoaded = false;
      load(null);
    }
  }, 10 * 60 * 1000);
})();
