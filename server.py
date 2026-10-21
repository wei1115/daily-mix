# -*- coding: utf-8 -*-
"""Local web server: static frontend + JSON API + background playlist builder."""
from __future__ import annotations

import base64
import ctypes
import hmac
import json
import mimetypes
import os
import re
import subprocess
import threading
import traceback
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import store

ACCESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "access.txt")
NETEASE_DEFAULT = r"D:\网易云音乐\CloudMusic\cloudmusic.exe"
_access_cache = {"mtime": 0.0, "value": ""}


def netease_exe() -> str:
    """Locate the NetEase Cloud Music client (registry first, then default path)."""
    candidates = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"orpheus\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
        match = re.search(r'"([^"]+\.exe)"', command)
        if match:
            candidates.append(match.group(1))
    except OSError:
        pass
    candidates.append(NETEASE_DEFAULT)
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def _access_credentials() -> str:
    """Read 'user:password' from access.txt, cached by mtime."""
    try:
        mtime = os.path.getmtime(ACCESS_FILE)
    except OSError:
        return ""
    if mtime != _access_cache["mtime"]:
        try:
            with open(ACCESS_FILE, encoding="utf-8") as fh:
                _access_cache["value"] = fh.read().strip()
        except OSError:
            _access_cache["value"] = ""
        _access_cache["mtime"] = mtime
    return _access_cache["value"]

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

LOCK = threading.Lock()
STATE = {
    "status": "idle",          # idle | building | ready | error
    "progress": {"stage": "", "pct": 0, "detail": ""},
    "error": "",
    "started_at": "",
    "finished_at": "",
}


def _set_progress(info: dict):
    with LOCK:
        STATE["progress"] = info


def _today() -> str:
    return date.today().isoformat()


def build_async(force: bool = False) -> bool:
    """Start a background build. Returns False if one is already running."""
    import builder  # local import avoids a circular import at module load

    with LOCK:
        if STATE["status"] == "building":
            return False
        STATE["status"] = "building"
        STATE["error"] = ""
        STATE["started_at"] = _now()
        STATE["progress"] = {"stage": "start", "pct": 1, "detail": "准备中…"}

    def run():
        try:
            payload = builder.build(progress=_set_progress, force=force)
            with LOCK:
                STATE["status"] = "ready"
                STATE["finished_at"] = _now()
                STATE["progress"] = {"stage": "done", "pct": 100,
                                     "detail": f"{len(payload.get('tracks', []))} 首"}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                STATE["status"] = "error"
                STATE["error"] = str(exc)
                STATE["finished_at"] = _now()

    threading.Thread(target=run, daemon=True).start()
    return True


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


class Handler(BaseHTTPRequestHandler):
    server_version = "DailyMix/1.0"

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            print(f"  {fmt % args}")

    # -- helpers ---------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: str):
        if not os.path.isfile(path):
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- auth ------------------------------------------------------------
    def _auth_ok(self) -> bool:
        """Only requests that came through the Cloudflare tunnel need a password."""
        if not self.headers.get("Cf-Ray"):
            return True
        creds = _access_credentials()
        if not creds:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            given = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:  # noqa: BLE001
            return False
        return hmac.compare_digest(given, creds)

    def _reject(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Daily Mix", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        if not self._auth_ok():
            return self._reject()
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if route == "/api/today":
            day = (query.get("date") or [_today()])[0]
            payload = store.get_playlist(day)
            with LOCK:
                state = dict(STATE)

            if day == _today() and state["status"] == "building":
                return self._json({
                    "date": day,
                    "status": "building",
                    "progress": state["progress"],
                    "error": "",
                    "playlist": None,
                })

            if payload is None:
                return self._json({
                    "date": day,
                    "status": "empty",
                    "progress": state["progress"] if day == _today() else {},
                    "error": state["error"] or "这一天还没有歌单",
                    "playlist": None,
                })
            return self._json({
                "date": day,
                "status": "ready",
                "progress": state["progress"] if day == _today() else {},
                "error": "",
                "playlist": payload,
            })

        if route == "/api/archive":
            return self._json({"dates": store.list_dates(60), "today": _today()})

        if route == "/api/stats":
            return self._json(store.db_stats())

        if route == "/api/health":
            with LOCK:
                state = dict(STATE)
            return self._json({"ok": True, "state": state, "today": _today()})

        if route in ("/", "/index.html"):
            return self._file(os.path.join(WEB, "index.html"))

        if route.startswith("/web/"):
            rel = os.path.normpath(route[len("/web/"):]).replace("\\", "/")
            if rel.startswith("..") or rel.startswith("/"):
                return self._json({"error": "bad path"}, 400)
            return self._file(os.path.join(WEB, rel))

        if route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._auth_ok():
            return self._reject()
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if parsed.path == "/api/refresh":
            started = build_async(force=True)
            return self._json({"started": started})

        if parsed.path == "/api/clear-cache":
            result = store.clear_cache(keep_today=True)
            return self._json({"ok": True, "cleared": result})

        if parsed.path == "/api/open-client":
            # 只允许本机点击时拉起客户端，防止公网访客控制这台电脑
            if self.headers.get("Cf-Ray"):
                return self._json({"ok": False, "error": "仅限本机使用"}, 403)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                payload = {}
            song_id = str(payload.get("id") or "")
            if not song_id.isdigit():
                return self._json({"ok": False, "error": "bad id"}, 400)
            exe = netease_exe()
            if not exe:
                return self._json({"ok": False, "error": "找不到网易云客户端"}, 404)
            command = {"type": "song", "id": song_id, "cmd": "play"}
            encoded = base64.b64encode(
                json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
            try:
                # 处理请求的是工作线程；ShellExecute 需要先初始化 COM，否则会静默失败
                hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)
                try:
                    os.startfile(f"orpheus://{encoded}")  # noqa: S606 - Windows shell open
                finally:
                    if hr == 0:
                        ctypes.windll.ole32.CoUninitialize()
            except (OSError, AttributeError) as exc:
                return self._json({"ok": False, "error": str(exc)}, 500)
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def serve(port: int = 8787, host: str = "127.0.0.1"):
    store.init()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
