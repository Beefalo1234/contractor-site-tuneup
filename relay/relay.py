#!/usr/bin/env python3
"""
Contractor Site Tune-Up — lead relay (local, free-tier).
Receives lead submissions from the landing page (via Cloudflare quick tunnel),
appends them to data/leads.json + data/leads.csv, and pings Gray's Telegram
channel so a new lead is visible instantly.

Run:  python relay.py            (serves on 127.0.0.1:8791)
Env:  TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL  (or relay/secrets.env)

Endpoints:
  POST /api/lead   {name, company, website, trade, email, phone, intent, source}
  GET  /health     -> {"ok": true}
"""
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import parse, request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
LEADS_JSON = os.path.join(DATA_DIR, "leads.json")
LEADS_CSV = os.path.join(DATA_DIR, "leads.csv")
PORT = int(os.environ.get("RELAY_PORT", "8791"))

CSV_FIELDS = ["id", "ts_utc", "name", "company", "website", "trade",
              "email", "phone", "intent", "source", "notes"]

ALLOWED_TRADES = ["HVAC", "Roofing", "Solar", "Plumbing", "Electrical",
                  "Painting", "Landscaping", "Other"]


def load_secrets():
    """Token from env first, then relay/secrets.env (gitignored)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    if not token or not chat:
        secrets_file = os.path.join(BASE, "secrets.env")
        if os.path.exists(secrets_file):
            with open(secrets_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k == "TELEGRAM_BOT_TOKEN" and not token:
                            token = v.strip()
                        elif k == "TELEGRAM_HOME_CHANNEL" and not chat:
                            chat = v.strip()
    return token, chat


TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL = load_secrets()


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_json(record):
    rows = []
    if os.path.exists(LEADS_JSON):
        with open(LEADS_JSON, encoding="utf-8") as fh:
            try:
                rows = json.load(fh)
                if not isinstance(rows, list):
                    rows = []
            except json.JSONDecodeError:
                rows = []
    rows.append(record)
    with open(LEADS_JSON, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False)


def append_csv(record):
    new_file = not os.path.exists(LEADS_CSV)
    with open(LEADS_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in CSV_FIELDS})


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print("[relay] WARN: telegram not configured; lead alert skipped",
              flush=True)
        return False
    url = ("https://api.telegram.org/bot%s/sendMessage"
           % TELEGRAM_BOT_TOKEN)
    body = parse.urlencode({
        "chat_id": TELEGRAM_HOME_CHANNEL,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    for attempt in range(3):
        try:
            req = request.Request(url, data=body, method="POST")
            with request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:  # noqa: BLE001 - keep the relay alive
            print("[relay] telegram attempt %d failed: %s"
                  % (attempt + 1, exc), flush=True)
            time.sleep(2)
    return False


def normalize_website(raw):
    site = (raw or "").strip()
    if not site:
        return ""
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


class Handler(BaseHTTPRequestHandler):
    server_version = "CSTURelay/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Requested-With")

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "service": "cstu-relay"})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parsed = parse.urlparse(self.path)
        if parsed.path != "/api/lead":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return

        name = (data.get("name") or "").strip()[:80]
        company = (data.get("company") or "").strip()[:120]
        website = normalize_website(data.get("website"))[:200]
        trade = (data.get("trade") or "").strip()[:40]
        email = (data.get("email") or "").strip().lower()[:120]
        phone = (data.get("phone") or "").strip()[:40]
        intent = (data.get("intent") or "audit").strip()[:40]
        source = (data.get("source") or "landing-page").strip()[:60]
        notes = (data.get("notes") or "").strip()[:500]

        if not name or not email:
            self._json(400, {"ok": False,
                             "error": "name and email are required"})
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            self._json(400, {"ok": False, "error": "email looks invalid"})
            return

        record = {
            "id": uuid.uuid4().hex[:10],
            "ts_utc": utc_now(),
            "name": name, "company": company, "website": website,
            "trade": trade, "email": email, "phone": phone,
            "intent": intent, "source": source, "notes": notes,
        }
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            append_json(record)
            append_csv(record)
        except Exception as exc:  # noqa: BLE001
            print("[relay] storage error: %s" % exc, flush=True)
            self._json(500, {"ok": False, "error": "storage failed"})
            return

        tg = ("NEW LEAD - Contractor Site Tune-Up\n"
              "Name: %s\nCompany: %s\nWebsite: %s\nTrade: %s\n"
              "Intent: %s\nEmail: %s\nPhone: %s\nSource: %s\n%s"
              % (name, company or "-", website or "-", trade or "-",
                 intent, email, phone or "-", source, record["id"]))
        tg_ok = send_telegram(tg)
        print("[relay] lead %s stored%s; telegram=%s"
              % (record["id"], "" if website else " (no website)",
                 "ok" if tg_ok else "FAILED"), flush=True)
        self._json(200, {"ok": True, "id": record["id"],
                         "telegram": tg_ok})


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("[relay] listening on http://127.0.0.1:%d  (data in %s)"
          % (PORT, DATA_DIR), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[relay] stopped", flush=True)
