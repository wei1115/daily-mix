# -*- coding: utf-8 -*-
"""Daily Mix tunnel: expose the local server through a Cloudflare quick tunnel.

Usage: double-click 开启隧道.bat  (or: python tunnel/tunnel.py)

The app itself keeps running unchanged; this only adds a public HTTPS URL.
Requests arriving through Cloudflare (they carry a Cf-Ray header) must pass
HTTP Basic auth using the credentials stored in access.txt.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

TUNNEL_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(TUNNEL_DIR)
VENDOR_DIR = os.path.join(TUNNEL_DIR, "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)
CLOUDFLARED = os.path.join(TUNNEL_DIR, "cloudflared.exe")
ACCESS_FILE = os.path.join(APP_DIR, "access.txt")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def app_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


def find_port():
    for port in range(8787, 8812):
        if app_alive(port):
            return port
    return None


def ensure_credentials() -> tuple[str, str]:
    if os.path.exists(ACCESS_FILE):
        raw = open(ACCESS_FILE, encoding="utf-8").read().strip()
        if ":" in raw:
            user, password = raw.split(":", 1)
            return user, password
    user = "mix"
    password = secrets.token_urlsafe(6)
    with open(ACCESS_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"{user}:{password}\n")
    return user, password


def start_app() -> subprocess.Popen | None:
    print("  本地服务没在跑，正在启动…")
    env = dict(os.environ)
    env["DM_NO_BROWSER"] = "1"
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=APP_DIR, env=env,
                            creationflags=flags)
    for _ in range(40):
        time.sleep(0.5)
        if find_port():
            return proc
    return proc


def main():
    if not os.path.exists(CLOUDFLARED):
        print("  找不到 cloudflared.exe，请先下载到：")
        print(f"  {CLOUDFLARED}")
        sys.exit(1)

    user, password = ensure_credentials()

    port = find_port()
    app_proc = None
    if port is None:
        app_proc = start_app()
        port = find_port()
        if port is None:
            print("  本地服务启动失败，请先双击 启动.bat 看看报什么错。")
            sys.exit(1)
    print(f"  本地服务: http://127.0.0.1:{port}/")

    print("  正在建立 Cloudflare 隧道…")
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}",
         "--no-autoupdate", "--protocol", "http2"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    url_holder = {"url": ""}

    def pump():
        for line in proc.stdout:
            line = line.rstrip()
            if not url_holder["url"]:
                match = URL_RE.search(line)
                if match:
                    url_holder["url"] = match.group(0)
                    show_banner(match.group(0), user, password, port)
            if "ERR" in line:
                print(f"  [cloudflared] {line[:160]}")

    threading.Thread(target=pump, daemon=True).start()

    deadline = time.time() + 45
    while not url_holder["url"] and time.time() < deadline:
        if proc.poll() is not None:
            print("  隧道进程退出了，检查网络后重试。")
            sys.exit(1)
        time.sleep(0.4)

    if not url_holder["url"]:
        print("  45 秒内没拿到公网地址，可能是网络到 Cloudflare 不通。")
        proc.terminate()
        sys.exit(1)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n  正在关闭隧道…")
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("  隧道已关闭。本地服务仍在运行，直接开 http://127.0.0.1:%d/ 即可。" % port)
    finally:
        if app_proc and app_proc.poll() is None:
            pass  # 本地服务留给用户，窗口自己关


def show_banner(url: str, user: str, password: str, port: int):
    print()
    print("  " + "=" * 52)
    print("   公网地址（手机、外网都能打开）")
    print(f"   {url}")
    print()
    print(f"   用户名: {user}")
    print(f"   密码:   {password}")
    print("  " + "=" * 52)
    print("   手机扫码直接打开（扫码后输入上面的账号密码）：")
    print()
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # noqa: BLE001
        print(f"   （二维码生成失败：{exc}）")
    print(f"   本地地址不变: http://127.0.0.1:{port}/")
    print("   按 Ctrl+C 关闭隧道（本地服务不受影响）")
    print("   关掉这个窗口，公网地址立刻失效。")
    print()


if __name__ == "__main__":
    main()
