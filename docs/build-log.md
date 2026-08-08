# Build Log — Contractor Site Tune-Up MVP (task t_df9e926a)

Date: 2026-08-08 · Builder: default profile (headless agent) · Repo:
https://github.com/Beefalo1234/contractor-site-tuneup

## What was built (all free tier, no bank account used)

1. **Landing / offer page — LIVE**
   - URL: https://beefalo1234.github.io/contractor-site-tuneup/
   - Hosted on GitHub Pages (repo `contractor-site-tuneup`, `docs/` source).
   - Offer: $49 launch audit (reg. $99), first 5 contractors; 20-point
     technical + local-SEO audit, 48h plain-English report, prioritized
     fix list; done-for-you fixes $149 and $79/mo retainer upsells.
   - Embedded lead form + pre-filled email fallback (never loses a lead).

2. **Lead capture + tracking — LIVE and verified end-to-end**
   - `relay/relay.py` (stdlib Python): receives leads, appends to
     `relay/data/leads.json` + `leads.csv`, pings Telegram.
   - Cloudflare quick tunnel (no account): public form endpoint.
   - Verified: CORS preflight OK, POST stored the lead, Telegram alert
     delivered (`{"ok": true, "telegram": true}`).
   - Free tracking: leads.csv imports into Google Sheets (instructions in
     README §3); Telegram = instant alert channel.

3. **Audit pipeline (the $49 deliverable)**
   - `audit/audit.py` — 20 automated checks (HTTPS/cert, robots, sitemap,
     PageSpeed mobile+desktop, LCP, CLS, viewport, title, meta, H1, alt
     text, canonical, local-business schema, page weight, tap targets,
     phone above the fold, NAP, service-area coverage, contact page) plus
     3 built-in manual checklists (Google Business Profile, citations,
     reviews). Outputs: report.md / report.html (print-to-PDF) / report.json.
   - Tested against real tri-state contractor sites (see below).

4. **User instructions** — README.md (ops guide: keep relay alive, update
   tunnel URL, read/export leads, run audits, what needs a bank).

5. **Launch message** — docs/launch-message.md (FB trades-group post +
   LinkedIn / Nextdoor / LeadSetter cross-sell variants, posting tips).

## Pipeline test results (real contractor sites — 2026-08-08)

- Site A: https://palisadesfuel.com (HVAC, NY) → score **64/100**
  - P1: LCP 3.5s (slow mobile load) · 15/29 images missing alt text ·
    phone not near top of page · NAP address missing
  - P2: title tag length 61
- Site B: https://www.nuwayservice.com (HVAC, NY/CT) → score **52/100**
  - P1: mobile speed 63/100 · LCP 4.0s · no local-business structured
    data · phone not near top · no /contact page
  - P2: title tag 169 chars · no canonical tag
- Full reports: audit/reports/*.md (+ .html print-to-PDF, .json). Speed
  data comes from local Lighthouse 13 (Edge headless) — real measured
  numbers, not estimates.

## Ops home (durable, survives kanban cleanup)

- Project lives at **C:\Users\Gray\Desktop\contractor-site-tuneup\**
  (git clone of the repo; relay, tunnel, audit tooling all run from here).
- Watchdog cron keeps the relay alive + config in sync: job
  `cstu-relay-watchdog` (every 15 min, zero tokens, no_agent script).

## Acceptance criteria status

- Live/demoable MVP: ✅ landing page public + lead relay verified
- Clear first-customer action: ✅ "Reserve the $49 audit" form (waitlist,
  no payment needed today)
- Tracking mechanism: ✅ leads.json + leads.csv + Telegram alerts + sheet
  import path
- Log of built / needs-bank: ✅ this file (next section)

## What still needs a bank account (NOT needed for launch)

- **Gumroad / Payhip merchant-of-record checkout** — to accept $49 orders
  by card. (Their merchant account handles cards; payouts eventually need
  Gray's bank to withdraw.)
- **Stripe account** — when order volume justifies direct checkout.
- **Business checking account** — payouts, refunds, monthly retainer
  billing ($79/mo), and the bank "promised later" by the user.
- Until then: waitlist + lead capture only — by design of this task.

## Known limitations (MVP phase)

- Relay runs on this PC; form falls back to email when the PC/tunnel is
  down (page itself is always live on Pages).
- Tunnel URL is ephemeral — update `docs/config.js` + push after a tunnel
  restart (README §2); the tools/watchdog.py cron keeps this automatic.
- PageSpeed API now requires OAuth2 (keys rejected, anonymous quota gone) —
  pipeline uses local Lighthouse against Edge headless instead: free, no
  quota. `npm install` in audit/ needed once (lighthouse is in
  node_modules, gitignored).
- No payments, no automated dedupe, no custom domain yet.
