# -*- coding: utf-8 -*-
"""每日混音 — entry point. Starts the local server and opens the browser."""
from __future__ import annotations

import os
import socket
import sys
import threading
import urllib.request
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# pythonw（无控制台）下 sys.stdout 可能是 None，print 会直接崩
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import server  # noqa: E402
import store   # noqa: E402

PORT_START = 8787
PORT_TRIES = 25
HOST = os.environ.get("DM_HOST", "127.0.0.1")
NO_BROWSER = os.environ.get("DM_NO_BROWSER") == "1"


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def running_port():
    """Return the port of an already-running instance, if any."""
    for port in range(PORT_START, PORT_START + 5):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=0.3) as resp:
                if resp.status == 200:
                    return port
        except Exception:  # noqa: BLE001
            continue
    return None


def bind(host: str = "127.0.0.1"):
    for offset in range(PORT_TRIES):
        port = PORT_START + offset
        try:
            return server.serve(port, host), port
        except OSError:
            continue
    raise SystemExit(f"端口 {PORT_START}-{PORT_START + PORT_TRIES - 1} 都被占用了。")


def main():
    no_browser = NO_BROWSER or "--no-browser" in sys.argv[1:]

    existing = running_port()
    if existing:
        url = f"http://127.0.0.1:{existing}/"
        print(f"  服务已经在运行: {url}")
        if not no_browser:
            webbrowser.open(url)
        return

    store.init()
    httpd, port = bind(HOST)
    url = f"http://127.0.0.1:{port}/"

    # 每次启动都重新生成一张当天歌单；页面内刷新不会重复生成
    if os.environ.get("DM_NO_BUILD") != "1":
        server.build_async(force=True)

    if not no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    print()
    print("  每日混音  ·  DAILY MIX")
    print("  " + "-" * 46)
    print(f"  界面:  {url}")
    if HOST == "0.0.0.0":
        ip = lan_ip()
        if ip:
            print(f"  手机:  http://{ip}:{port}/   （需在同一个 Wi-Fi）")
    print(f"  数据:  {store.DB_PATH}")
    print("  " + "-" * 46)
    print("  关闭这个窗口即停止服务。")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
