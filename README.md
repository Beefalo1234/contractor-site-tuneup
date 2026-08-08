# Contractor Site Tune-Up — MVP Operations Guide

A $99 (launch: $49) technical + local-SEO audit for home-service contractors
(HVAC / roofing / solar / plumbing / electrical / painting / landscaping) in
NY, NJ, and CT. Delivered in 48 hours as a plain-English PDF with a
prioritized fix list.

**Live links**
- Landing page: https://beefalo1234.github.io/contractor-site-tuneup/
- Repo: https://github.com/Beefalo1234/contractor-site-tuneup
- Relay health: `https://<tunnel-url>/health` (see relay/tunnel-url.txt)

---

## 1. How a lead flows (30 seconds to know)

1. Contractor lands on the page and submits the form.
2. The page POSTs the lead to the relay (this PC) through a free Cloudflare
   quick tunnel.
3. `relay/relay.py` appends the lead to `relay/data/leads.json` and
   `relay/data/leads.csv`, and pings **Telegram** (Gray's home channel) so a
   new lead is visible instantly.
4. If the relay is unreachable (PC off, tunnel down), the form automatically
   falls back to a pre-filled email to graydon3.14@gmail.com — a lead is
   never silently lost.

## 2. Keep the relay alive (start after every reboot)

```bash
bash start-relay.sh
```

This launches `relay/relay.py` + `tools/cloudflared.exe` and prints the
public URL. It needs `relay/secrets.env` (copy from `secrets.env.example`,
values live in `C:\Users\Gray\AppData\Local\hermes\.env`).

**If the tunnel URL changed** (it does on every tunnel restart), the form
still works — but to keep the *primary* path live, update `docs/config.js`:

```js
const RELAY_URLS = ["https://NEW-URL.trycloudflare.com"];
```

then push to GitHub (Pages rebuilds automatically, ~1 min):

```bash
git add docs/config.js && git commit -m "update relay URL" && git push
```

## 3. Read and track leads

- All leads: `relay/data/leads.json` (rich) and `relay/data/leads.csv` (sheet-ready).
- To feed the free tracking sheet: open Google Sheets → File → Import →
  upload `leads.csv`. Columns: id, ts_utc, name, company, website, trade,
  email, phone, intent, source, notes.
- Every new lead also lands in Telegram — check the home channel for the
  🔥 alert before anything else.
- Duplicate check is manual for now: search the CSV by email/website.

## 4. Run an audit (the $49 deliverable)

```bash
python3 audit/audit.py https://example.com --out audit/reports/example
```

- Free-tier only: PageSpeed Insights API (works keyless at low volume) +
  plain HTTP checks. No paid APIs, no licenses.
- Outputs: `example.md` (plain-English report), `example.html` (styled,
  printable to PDF), `example.json` (raw data).
- Custom service area: `--cities "White Plains,New Rochelle,Yonkers"`.
- The report covers 20 points (speed, on-page, local SEO, conversion) plus
  three short manual checklists (Google Business Profile, citations,
  reviews) built into the report.
- Delivery: convert the HTML to PDF (print dialog), send to the client,
  offer the 15-min walkthrough call.

## 5. What still needs a bank account (later, not now)

- **Gumroad / Payhip** merchant-of-record checkout (accept $49 orders with a
  card — no bank needed on our side for the merchant, but payout
  withdrawal to a bank account is required later).
- **Stripe** account (when payments grow).
- **Business checking** for payouts and the monthly retainer billing.
- Until then: waitlist + lead capture only, per plan. Invoice after the
  bank account exists, or use Gumroad's merchant-of-record (their bank, not
  ours) — Gray decides.

## 6. Tooling notes (all free tiers)

| Tool | Why |
|---|---|
| GitHub Pages | durable public landing page, free, custom domain later |
| Cloudflare quick tunnel | free public URL for the local relay (no account) |
| relay.py (stdlib Python) | lead store + Telegram alert, zero deps |
| Lighthouse 13 + Edge headless | local speed/technical metrics — free, no API quota (audit/speed check) |
| Telegram bot | instant lead notifications to Gray's channel |
| Google Sheets (manual import) | free tracking/analytics sheet |

> Note: Google's PageSpeed Insights API now requires OAuth2 (API keys are
> rejected and the anonymous quota is exhausted), so the audit pipeline
> uses a local Lighthouse run against Edge headless instead — same metrics,
> no quota, no account.

## 7. Known limitations (MVP phase)

- The relay only runs while this PC is on and the tunnel is up. The page
  itself (GitHub Pages) is always live; the *form* falls back to email when
  the relay is down.
- Tunnel URLs are ephemeral (see section 2).
- PageSpeed API is keyless and rate-limited; fine for a handful of audits a
  day. If volume grows, Gray adds a free Google Cloud API key.
- No payments yet — waitlist/lead capture only (by design, task
  t_df9e926a).
