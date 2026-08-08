#!/usr/bin/env python3
"""
Contractor Site Tune-Up — relay watchdog (free, stdlib only).

Keeps the lead relay + Cloudflare tunnel alive and the landing page's
form endpoint current. Intended to run from cron every ~15 minutes:
  - healthy relay + unchanged tunnel URL  -> prints nothing (silent)
  - relay down                            -> restarts it and the tunnel
  - tunnel URL changed                    -> updates site/config.js and
                                            pushes to GitHub so the live
                                            page always points at the relay

Run:  python3 tools/watchdog.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(ROOT, "relay", "relay.py")
CLOUDFLARED = os.path.join(ROOT, "tools", "cloudflared.exe")
CONFIG_JS = os.path.join(ROOT, "docs", "config.js")
TUNNEL_LOG = os.path.join(ROOT, "relay", "tunnel.log")
RELAY_LOG = os.path.join(ROOT, "relay", "relay.log")
URL_FILE = os.path.join(ROOT, "relay", "tunnel-url.txt")
HEALTH = "http://127.0.0.1:8791/health"


def healthy():
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def current_tunnel_url():
    try:
        with open(TUNNEL_LOG, encoding="utf-8", errors="replace") as fh:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", fh.read())
        return m.group(0) if m else None
    except Exception:
        return None


def configured_url():
    try:
        with open(CONFIG_JS, encoding="utf-8") as fh:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", fh.read())
        return m.group(0) if m else None
    except Exception:
        return None


def start_detached(cmd, logfile):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with open(logfile, "a", encoding="utf-8") as log:
        subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags)


def start_relay():
    start_detached([sys.executable, RELAY], RELAY_LOG)
    time.sleep(3)


def start_tunnel():
    start_detached([CLOUDFLARED, "tunnel", "--url", "http://127.0.0.1:8791",
                    "--no-autoupdate"], TUNNEL_LOG)


def wait_for_url(timeout=45):
    start = time.time()
    while time.time() - start < timeout:
        url = current_tunnel_url()
        if url:
            return url
        time.sleep(3)
    return None


def update_config_and_push(new_url):
    try:
        with open(CONFIG_JS, encoding="utf-8") as fh:
            content = fh.read()
        content = re.sub(r"https://[a-z0-9-]+\.trycloudflare\.com",
                         new_url, content, count=1)
        with open(CONFIG_JS, "w", encoding="utf-8") as fh:
            fh.write(content)
        subprocess.run(["git", "add", "docs/config.js"], cwd=ROOT,
                       check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m",
                        "watchdog: update relay URL to %s" % new_url],
                       cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT,
                       check=True, capture_output=True)
        return True
    except Exception as exc:
        print("watchdog: config update failed: %s" % exc)
        return False


def main():
    if healthy():
        cfg = configured_url()
        cur = current_tunnel_url()
        if cfg and cur and cfg != cur:
            if update_config_and_push(cur):
                print("watchdog: tunnel URL changed to %s — config.js "
                      "updated and pushed" % cur)
        return  # healthy: stay silent

    print("watchdog: relay DOWN — restarting")
    start_relay()
    start_tunnel()
    url = wait_for_url()
    if not url:
        print("watchdog: tunnel URL not found after restart; check "
              "relay/tunnel.log")
        return
    with open(URL_FILE, "w", encoding="utf-8") as fh:
        fh.write(url + "\n")
    print("watchdog: relay restarted; tunnel URL: %s" % url)
    if configured_url() != url:
        if update_config_and_push(url):
            print("watchdog: site config.js updated to new URL")


if __name__ == "__main__":
    main()
