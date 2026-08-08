#!/usr/bin/env python3
"""
Contractor Site Tune-Up — automated audit pipeline (free-tier, stdlib only).

Runs a 20-point technical + local-SEO audit of a contractor website and
produces a plain-English, prioritized report (Markdown + HTML + JSON).

Checks (automated unless marked [manual]):
  1  HTTPS + certificate valid                  [auto]
  2  robots.txt present + not blocking          [auto]
  3  sitemap.xml present + parseable            [auto]
  4  Mobile page-speed score (PageSpeed API)    [auto]
  5  Desktop page-speed score                   [auto]
  6  Mobile load speed (LCP)                    [auto]
  7  Layout stability (CLS)                     [auto]
  8  Mobile viewport meta tag                   [auto]
  9  Title tag (present, right length)          [auto]
 10  Meta description (present, right length)   [auto]
 11  Exactly one H1 on homepage                 [auto]
 12  Image alt text (share missing)             [auto]
 13  Canonical tag present                      [auto]
 14  Local-business structured data             [auto]
 15  Total page weight (images/JS)              [auto]
 16  Tap targets usable on mobile               [auto]
 17  Phone number on homepage, above the fold   [auto]
 18  NAP on homepage (name/address/phone)       [auto]
 19  City / service-area coverage on pages      [auto]
 20  Contact page reachable with form/phone     [auto]
 21  Google Business Profile basics             [manual - instructions included]
 22  Citation / directory consistency           [manual - checklist included]
 23  Reviews presence                           [manual - instructions included]

Usage:
  python3 audit.py https://example.com --out reports/example
  python3 audit.py https://example.com --out reports/example --cities "New Rochelle,White Plains"

Outputs:
  <out>.md   plain-English report (the deliverable)
  <out>.html styled report (self-contained)
  <out>.json raw findings (data)

Free tier: PageSpeed Insights API works without a key at low volume.
"""
import argparse
import datetime
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 25
DEFAULT_CITIES = [
    "New York", "Brooklyn", "Queens", "Bronx", "Staten Island",
    "Westchester", "White Plains", "New Rochelle", "Yonkers", "Mount Vernon",
    "Long Island", "Nassau", "Suffolk", "Huntington", "Hempstead",
    "New Jersey", "Jersey City", "Newark", "Bergen", "Essex County",
    "Connecticut", "Fairfield", "Bridgeport", "Stamford", "Norwalk",
]

STATUS = {"P0": "fix first — costing you calls",
          "P1": "important — fix soon",
          "P2": "worth doing",
          "OK": "good — no action needed"}


class PageParser(HTMLParser):
    """Pulls the bits the audit needs out of an HTML document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self.meta_desc = None
        self.meta_viewport = False
        self.h1s = []
        self.imgs = []          # (has_alt, has_src)
        self.canonical = None
        self.ldjson = []
        self.text_parts = []
        self.links = []         # (href, text)
        self.forms = 0
        self.in_title = False
        self.in_h1 = False
        self._skip_depth = 0
        self._in_ldjson = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        low = tag.lower()
        if low == "script":
            if (a.get("type") or "").strip().lower() == "application/ld+json":
                self._in_ldjson = True
            self._skip_depth += 1
            return
        if low in ("style", "noscript"):
            self._skip_depth += 1
            return
        if low == "title":
            self.in_title = True
        elif low == "h1":
            self.in_h1 = True
            self.h1s.append("")
        elif low == "meta":
            name = (a.get("name") or "").lower()
            prop = (a.get("property") or "").lower()
            content = a.get("content", "")
            if name == "description" or prop == "og:description":
                self.meta_desc = content.strip()
            if name == "viewport":
                self.meta_viewport = True
        elif low == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif low == "img":
            self.imgs.append((bool(a.get("alt")), bool(a.get("src"))))
        elif low == "a":
            href = a.get("href") or ""
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self.links.append(href)
        elif low == "form":
            self.forms += 1

    def handle_endtag(self, tag):
        low = tag.lower()
        if low == "script":
            self._in_ldjson = False
        if low in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif low == "title":
            self.in_title = False
        elif low == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        if self._in_ldjson:
            self.ldjson.append(data)
            return
        if self._skip_depth:
            return
        if self.in_title:
            self.title = (self.title or "") + data
        if self.in_h1 and self.h1s:
            self.h1s[-1] += data
        if data.strip():
            self.text_parts.append(data)


def fetch(url, timeout=TIMEOUT, max_bytes=2_000_000):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return resp.status, resp.headers, data


def http_status(url, timeout=TIMEOUT):
    """Return status code or None (unreachable/error)."""
    try:
        return fetch(url, timeout=timeout)[0]
    except Exception:
        return None


def get_text(url):
    try:
        status, _, data = fetch(url)
        if status >= 400:
            return None, status
        return data.decode("utf-8", errors="replace"), status
    except Exception as exc:
        return None, exc


def cert_not_expired(host):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        return True, ""
    except Exception as exc:
        return False, str(exc)[:120]


def lighthouse_local(url, mode="mobile"):
    """Run Lighthouse locally against Edge headless (free, no API).
    Returns parsed JSON metrics or None. mode: 'mobile' | 'desktop'."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        proc = subprocess.run(
            ["node", os.path.join(here, "lh.js"), url, mode],
            capture_output=True, text=True, timeout=200)
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if out.startswith("{"):
                return json.loads(out)
            print("  [lighthouse %s] no output" % mode, flush=True)
        else:
            print("  [lighthouse %s] rc=%d %s"
                  % (mode, proc.returncode,
                     proc.stderr.strip()[-200:]), flush=True)
    except Exception as exc:
        print("  [lighthouse %s] failed: %s" % (mode, exc), flush=True)
    return None


def psi(url, strategy):
    """PageSpeed Insights API (free, keyless). Returns dict or None."""
    q = urllib.parse.urlencode([
        ("url", url), ("strategy", strategy),
        ("category", "performance"), ("category", "accessibility"),
    ])
    api = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + q
    req = urllib.request.Request(api, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def psi_value(data, *path, default=None):
    node = data
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def norm_href(base, href):
    return urllib.parse.urljoin(base, href)


def same_domain(base, url):
    return urllib.parse.urlparse(base).netloc == urllib.parse.urlparse(url).netloc


def phone_in_text(text):
    return re.search(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", text) is not None


def addr_in_text(text):
    return re.search(r"\b\d{1,5}\s+[A-Z][A-Za-z0-9. ]{3,60}"
                     r"(street|st|avenue|ave|road|rd|lane|ln|drive|dr|"
                     r"boulevard|blvd|way|court|ct|place|pl|highway|hwy)\b",
                     text, re.IGNORECASE) is not None


class Audit:
    def __init__(self, url, cities):
        self.base = url.rstrip("/")
        self.host = urllib.parse.urlparse(self.base).netloc
        self.cities = cities
        self.findings = []
        self.psi_mobile = None
        self.psi_desktop = None
        self.lh = None          # local Lighthouse mobile metrics
        self.lh_desktop = None  # local Lighthouse desktop metrics
        self.page = None          # PageParser of homepage
        self.internal_pages = []  # [(url, title, first_chunk)]

    # ---- helpers -------------------------------------------------
    def add(self, n, status, summary, detail="", how=""):
        self.findings.append({
            "n": n, "status": status, "summary": summary,
            "detail": detail, "how": how,
        })
        print("[%s] %2d  %s" % (status, n, summary), flush=True)

    # ---- checks --------------------------------------------------
    def run(self):
        print("== %s ==" % self.base, flush=True)
        self.cert()
        self.robots_sitemap()
        self.speed()
        self.onpage()
        self.local_seo()
        self.conversion()
        self.manual_checks()
        return self.findings

    def cert(self):
        ok, err = cert_not_expired(self.host)
        if ok:
            self.add(1, "OK", "HTTPS certificate is valid",
                     "https://%s serves a valid certificate." % self.host)
        else:
            self.add(1, "P0", "HTTPS certificate missing or expired",
                     "Could not verify a valid certificate: %s" % err,
                     "Reinstall/refresh the SSL certificate (ask your web "
                     "host — it usually takes 10 minutes and is often free).")

    def robots_sitemap(self):
        robots = http_status(self.base + "/robots.txt")
        if robots is None:
            self.add(2, "P1", "No robots.txt found",
                     "Google has to guess which pages to crawl.",
                     "Add a robots.txt with a sitemap line (see fix #3). "
                     "One file, 2 minutes.")
        elif robots >= 400:
            self.add(2, "P1", "robots.txt returns error %s" % robots,
                     "", "See fix #3.")
        else:
            _, _, data = fetch(self.base + "/robots.txt")
            text = data.decode("utf-8", errors="replace")
            if re.search(r"^Disallow:\s*/\s*$", text, re.M):
                self.add(2, "P0", "robots.txt blocks the whole site",
                         "Google can't index anything.",
                         "Change the Disallow rule or delete it, then "
                         "re-test in Search Console.")
            else:
                self.add(2, "OK", "robots.txt present and not blocking")

        sitemap = http_status(self.base + "/sitemap.xml")
        if sitemap and sitemap < 400:
            _, _, data = fetch(self.base + "/sitemap.xml")
            body = data.decode("utf-8", errors="replace").lower()
            n_urls = body.count("<url>")
            n_index = body.count("<sitemap>")
            if n_urls or n_index:
                kind = ("%d URL(s)" % n_urls) if n_urls else (
                    "%d sitemap file(s) (index)" % n_index)
                self.add(3, "OK", "sitemap.xml present with %s" % kind)
            else:
                self.add(3, "P1", "sitemap.xml exists but looks empty",
                         "Search engines need actual page URLs in it.",
                         "Use a sitemap plugin/generator and re-submit in "
                         "Google Search Console.")
        else:
            self.add(3, "P1", "No sitemap.xml",
                     "Google has to discover every page itself — slower "
                     "indexing for new pages.",
                     "Generate one (free tools or your CMS plugin), upload "
                     "to /sitemap.xml, submit in Google Search Console.")

    def speed(self):
        # Local Lighthouse (Edge headless) is primary — free, no API quota.
        self.lh = lighthouse_local(self.base, "mobile")
        self.lh_desktop = lighthouse_local(self.base, "desktop")
        lh = self.lh or {}

        score = lh.get("perf_score")
        if score is not None:
            if score >= 80:
                self.add(4, "OK", "Mobile speed score: %d/100" % score)
            elif score >= 50:
                self.add(4, "P1", "Mobile speed score: %d/100" % score,
                         "Most competitors are in the 70s–90s.",
                         "Apply the P0/P1 speed fixes below; re-test free at "
                         "pagespeed.web.dev.")
            else:
                self.add(4, "P0", "Mobile speed score: %d/100" % score,
                         "Slow pages lose calls — on mobile, every extra "
                         "second drops conversions.",
                         "Start with the biggest images (fix #15) and any "
                         "slow plugins; see the LCP fix below.")
        else:
            self.psi_mobile = psi(self.base, "mobile")
            score = psi_value(self.psi_mobile, "lighthouseResult",
                              "categories", "performance", "score")
            if isinstance(score, (int, float)):
                score = round(score * 100)
                if score >= 80:
                    self.add(4, "OK", "Mobile speed score: %d/100" % score)
                elif score >= 50:
                    self.add(4, "P1", "Mobile speed score: %d/100" % score,
                             "Most competitors are in the 70s–90s.")
                else:
                    self.add(4, "P0", "Mobile speed score: %d/100" % score,
                             "Slow pages lose calls.",
                             "Start with the biggest images and slow plugins.")
            else:
                self.add(4, "P1", "Could not measure mobile speed",
                         "Local Lighthouse and the PageSpeed API both "
                         "failed (the API now requires OAuth).",
                         "Measure once free at pagespeed.web.dev and "
                         "re-run the audit, or ask your web person.")

        ds = (self.lh_desktop or {}).get("perf_score")
        if ds is not None:
            if ds < 50:
                self.add(5, "P1", "Desktop speed score: %d/100" % ds,
                         "", "Same fixes as mobile — usually image weight.")
            else:
                self.add(5, "OK", "Desktop speed score: %d/100" % ds)

        lcp = lh.get("lcp")
        if lcp:
            try:
                secs = float(re.search(r"[\d.]+", lcp).group())
            except Exception:
                secs = 0
            if secs > 4:
                self.add(6, "P0", "Mobile load speed (LCP): %s" % lcp,
                         "Target is under 2.5s. This is usually the #1 "
                         "culprit for lost calls.",
                         "Compress/convert hero images to WebP, enable "
                         "caching, and remove heavy third-party scripts. "
                         "Your web person can do this in an afternoon.")
            elif secs > 2.5:
                self.add(6, "P1", "Mobile load speed (LCP): %s" % lcp,
                         "Target is under 2.5s.",
                         "Same fixes as above — start with the hero image.")
            else:
                self.add(6, "OK", "Mobile load speed (LCP): %s" % lcp)

        cls = lh.get("cls")
        if cls is not None:
            try:
                val = float(re.search(r"[\d.]+", str(cls)).group())
            except Exception:
                val = 0
            if val > 0.1:
                self.add(7, "P1", "Page layout shifts while loading: %s" % cls,
                         "Elements jump around, people tap the wrong thing.",
                         "Give images and embeds fixed width/height in code.")
            else:
                self.add(7, "OK", "Layout stability (CLS): %s" % cls)

    def onpage(self):
        html, err = get_text(self.base)
        if not html:
            self.add(8, "P0", "Homepage unreachable",
                     "Could not fetch the site: %s" % err)
            return
        parser = PageParser()
        parser.feed(html)
        self.page = parser

        if parser.meta_viewport:
            self.add(8, "OK", "Mobile viewport is configured")
        else:
            self.add(8, "P0", "No mobile viewport tag",
                     "The site renders zoomed-out on phones.",
                     "Add <meta name=\"viewport\" content=\"width=device-"
                     "width, initial-scale=1\"> to the <head>.")

        title = (parser.title or "").strip()
        if not title:
            self.add(9, "P1", "No title tag",
                     "The browser tab and Google results show a blank "
                     "heading.", "Write a title with your service + city, "
                     "e.g. \"HVAC Repair in White Plains, NY | Smith "
                     "Heating\".")
        elif not 30 <= len(title) <= 60:
            self.add(9, "P2", "Title tag length: %d chars" % len(title),
                     "Ideally 30–60 characters so Google shows it in full.",
                     "Tighten the title to include service + city.")
        else:
            self.add(9, "OK", "Title tag looks good: \"%s\"" % title[:60])

        desc = parser.meta_desc
        if not desc:
            self.add(10, "P1", "No meta description",
                     "Google writes its own (often bad) description under "
                     "your listing.",
                     "Write 1–2 sentences with your service, city, and a "
                     "reason to call.")
        elif not 70 <= len(desc) <= 160:
            self.add(10, "P2", "Meta description length: %d chars" % len(desc),
                     "Ideally 70–160 characters.", "Tighten it — include "
                     "service, city, and a call to action.")
        else:
            self.add(10, "OK", "Meta description looks good")

        n_h1 = len(parser.h1s)
        if n_h1 == 1:
            self.add(11, "OK", "One H1 heading on the homepage")
        elif n_h1 == 0:
            self.add(11, "P1", "No H1 heading on the homepage",
                     "Search engines and screen readers use it as the page "
                     "topic.", "Add one H1 with your main service, e.g. "
                     "\"Heating & Air Conditioning in White Plains\".")
        else:
            self.add(11, "P2", "%d H1 headings on the homepage" % n_h1,
                     "Multiple H1s dilute the page topic.",
                     "Keep one H1; change the rest to H2/H3.")

        total = len(parser.imgs)
        missing = sum(1 for alt, _ in parser.imgs if not alt)
        if total == 0:
            self.add(12, "P2", "No images found on homepage",
                     "Contractor sites with real work photos convert "
                     "better.", "Add photos of finished jobs.")
        elif missing / total > 0.3:
            self.add(12, "P1", "%d of %d images missing alt text" % (missing, total),
                     "Google can't tell what the photos show; screen "
                     "readers can't either.",
                     "Add short descriptions to each image alt field "
                     "(e.g. \"new roof installation in Yonkers\"). "
                     "One afternoon, done.")
        else:
            self.add(12, "OK", "Image alt text looks good (%d/%d)" % (total - missing, total))

        if parser.canonical:
            self.add(13, "OK", "Canonical tag present")
        else:
            self.add(13, "P2", "No canonical tag",
                     "If the same page is reachable at multiple URLs, "
                     "Google may split its ranking.",
                     "Add <link rel=\"canonical\" href=\"...\"> pointing at "
                     "the one true URL of each page.")

        ld = " ".join(parser.ldjson).lower()
        local_types = ("localbusiness", "plumber", "hvacbusiness",
                       "roofingcontractor", "electrical", "homeandconstruct"
                       "ionbusiness", "generalcontractor", "locksmith",
                       "paint", "landscaping", "homeandgarden")
        if any(t in ld for t in local_types):
            self.add(14, "OK", "Local-business structured data found")
        else:
            self.add(14, "P1", "No local-business structured data",
                     "Google can't confirm your service area or hours — "
                     "you lose rich snippets and local trust.",
                     "Add LocalBusiness JSON-LD (name, address, phone, "
                     "geo, hours). Ask your web person — 10 minutes.")

    def local_seo(self):
        if not self.page:
            self.add(17, "P1", "Homepage not readable — local-SEO checks "
                     "skipped", "Site could not be fetched; re-run once "
                     "the site is reachable.")
            return
        text = " ".join(self.page.text_parts) or ""
        first_chunk = text[:4000]

        phone = phone_in_text(text)
        head_parts = " ".join((self.page.text_parts or [])[:4])[:3000]
        above_fold = phone_in_text(head_parts)
        if phone and above_fold:
            self.add(17, "OK", "Phone number visible near the top of the page")
        elif phone:
            self.add(17, "P1", "Phone number not near the top of the page",
                     "Visitors shouldn't scroll to find how to call you.",
                     "Add a tap-to-call button in the header — on mobile it "
                     "should be one tap.")
        else:
            self.add(17, "P0", "No phone number found on the homepage",
                     "This is the single biggest call-killer.",
                     "Put your phone number in the header, visible on every "
                     "page, tap-to-call on mobile.")

        if phone and addr_in_text(text):
            self.add(18, "OK", "NAP (name, address, phone) on homepage")
        elif phone:
            self.add(18, "P1", "Address missing next to the phone (NAP)",
                     "Google and customers like a full name/address/phone "
                     "block.", "Add your full address to the footer of "
                     "every page.")
        else:
            self.add(18, "P1", "NAP incomplete — see phone fix",
                     "Name/address/phone should match your Google Business "
                     "Profile exactly.",
                     "After adding the phone (fix #17), make sure name, "
                     "address, and phone match your GBP listing exactly.")

        # city coverage: homepage + up to 8 internal pages
        pages = [self.base]
        seen = set()
        for href in (self.page.links or []):
            full = norm_href(self.base, href)
            if same_domain(self.base, full) and full not in seen:
                seen.add(full)
                pages.append(full)
            if len(pages) >= 9:
                break
        cities_found = {}
        for p in pages:
            h, _ = get_text(p)
            if not h:
                continue
            title = re.search(r"<title[^>]*>(.*?)</title>", h,
                              re.I | re.S)
            title_text = (title.group(1).strip() if title else "")
            low = (title_text + " " + h[:3000]).lower()
            chunk = low[:3000]
            for c in self.cities:
                if c.lower() in chunk:
                    cities_found.setdefault(c, []).append(p.split("//")[-1][:60])
        if len(cities_found) >= 2:
            self.add(19, "OK", "Service-area coverage found: %s" % ", ".join(
                list(cities_found)[:5]))
        elif cities_found:
            self.add(19, "P1", "Thin service-area coverage",
                     "Only found: %s" % ", ".join(cities_found),
                     "Add a page per town you serve (\"HVAC repair in New "
                     "Rochelle\") — this is how local contractors rank "
                     "for \"near me\" searches.")
        else:
            self.add(19, "P1", "No service-area pages found",
                     "Your site doesn't mention the towns you serve, so "
                     "you can't rank for \"[service] near me\" in those "
                     "towns.",
                     "Add a short page for each town you serve, with the "
                     "service + town in the title.")

        contact_status = None
        for path in ("/contact", "/contact-us", "/contact.html",
                     "/contactus"):
            st = http_status(self.base + path)
            if st and st < 400:
                contact_status = st
                contact_url = self.base + path
                break
        if contact_status:
            ch, _ = get_text(contact_url)
            if ch:
                cp = PageParser()
                cp.feed(ch)
                if cp.forms or phone_in_text(ch[:4000]):
                    self.add(20, "OK", "Contact page reachable with a form/phone")
                else:
                    self.add(20, "P1", "Contact page has no form or phone",
                             "", "Add a simple form or your phone number.")
            else:
                self.add(20, "OK", "Contact page reachable")
        else:
            self.add(20, "P1", "No contact page found",
                     "Homeowners need an obvious way to reach you.",
                     "Add a /contact page with phone, email, and a short "
                     "form.")

    def conversion(self):
        lh = self.lh or {}
        weight = lh.get("page_weight")
        if weight:
            try:
                kb = float(re.search(r"[\d.]+", weight).group())
            except Exception:
                kb = 0
            if kb > 2500:
                self.add(15, "P1", "Page weight: %s" % weight,
                         "Heavy pages are slow on phone data plans.",
                         "Compress images (fix #6), remove unused plugins "
                         "and scripts.")
            else:
                self.add(15, "OK", "Page weight: %s" % weight)
        taps = lh.get("tap_score")
        if taps is not None and taps < 1:
            self.add(16, "P2", "Some tap targets are too small on mobile",
                     "Buttons/links under 48px are hard to hit on a phone.",
                     "Increase button/clickable sizes and spacing.")
        elif taps == 1:
            self.add(16, "OK", "Tap targets are sized correctly on mobile")

    def manual_checks(self):
        self.add(21, "OK", "[Manual] Google Business Profile basics — "
                 "verify in 10 min",
                 "Open your GBP listing (business.google.com): 1) is the "
                 "phone number the same as your website's? 2) are hours "
                 "current? 3) is your service area set? 4) have you "
                 "answered recent questions/reviews?")
        self.add(22, "OK", "[Manual] Citation consistency — verify in "
                 "30 min",
                 "Search your business name on: Yelp, Bing Places, "
                 "YellowPages, Angi, HomeAdvisor, Thumbtack, BBB. The name, "
                 "address, and phone must match your website exactly — "
                 "mismatches confuse Google and cost local rankings.")
        self.add(23, "OK", "[Manual] Reviews — verify in 15 min",
                 "On Google, how many reviews does your business have vs. "
                 "your top 3 local competitors? If you're behind, set a "
                 "monthly habit of asking happy customers for a review "
                 "(a text link works best).")

    # ---- report --------------------------------------------------
    def score(self):
        auto = [f for f in self.findings
                if not f["summary"].startswith("[Manual]")]
        n0 = sum(1 for f in auto if f["status"] == "P0")
        n1 = sum(1 for f in auto if f["status"] == "P1")
        n2 = sum(1 for f in auto if f["status"] == "P2")
        return max(0, min(100, 100 - 15 * n0 - 8 * n1 - 4 * n2))

    def to_md(self):
        lines = []
        lines.append("# Website Audit — %s" % self.base)
        lines.append("")
        lines.append("**Audit date:** %s  " % datetime.date.today().isoformat())
        lines.append("**Overall score:** %d / 100" % self.score())
        lines.append("")
        lines.append("This report is written for a busy business owner. "
                     "Every issue has a one-line task and a plain-English "
                     "how-to. Fixes are ranked by what brings in calls "
                     "first.")
        lines.append("")
        for prio in ("P0", "P1", "P2", "OK"):
            group = [f for f in self.findings if f["status"] == prio]
            if not group:
                continue
            lines.append("## %s — %s" % (prio, STATUS[prio]))
            lines.append("")
            for f in group:
                lines.append("**%d. %s**" % (f["n"], f["summary"]))
                if f["detail"]:
                    lines.append("")
                    lines.append(f["detail"])
                if f["how"]:
                    lines.append("")
                    lines.append("> How to fix: %s" % f["how"])
                lines.append("")
        lines.append("---")
        lines.append("_Generated by Contractor Site Tune-Up. Manual checks "
                     "(#21–23) are instructions, not automated results — "
                     "they take about an hour total and are worth doing._")
        return "\n".join(lines)

    def to_html(self, md_text):
        esc = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = re.sub(r"^# (.*)$", r"<h1>\1</h1>", esc, flags=re.M)
        body = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body, flags=re.M)
        body = re.sub(r"^> (.*)$", r"<blockquote>\1</blockquote>", body, flags=re.M)
        body = re.sub(r"^\*\*(.*)\*\*$", r"<p class=\"item\"><b>\1</b></p>",
                      body, flags=re.M)
        body = re.sub(r"^---$", "<hr>", body, flags=re.M)
        body = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", body)
        body = re.sub(r"_([^_]+)_", r"<i>\1</i>", body)
        return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Website Audit — %s</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
max-width:760px;margin:0 auto;padding:24px;color:#1c2733;line-height:1.6}
h1{color:#0d1b2a}h2{margin-top:28px;color:#e9650a;font-size:1.15rem}
.item{margin:10px 0 2px}blockquote{background:#f7f6f2;border-left:4px solid #ff7a1a;
padding:8px 14px;margin:6px 0 16px;border-radius:0 8px 8px 0;color:#5b6b7c}
hr{border:none;border-top:1px solid #e4e1d9;margin:28px 0}
</style></head><body>%s
</body></html>""" % (self.base, body)


def main():
    ap = argparse.ArgumentParser(description="Contractor Site Tune-Up audit")
    ap.add_argument("url", help="e.g. https://example.com")
    ap.add_argument("--out", default="report",
                    help="output base path (writes .md, .html, .json)")
    ap.add_argument("--cities", default=",".join(DEFAULT_CITIES),
                    help="comma-separated service-area cities to check")
    args = ap.parse_args()

    url = args.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]

    audit = Audit(url, cities)
    audit.run()
    md = audit.to_md()
    html = audit.to_html(md)

    with open(args.out + ".md", "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(args.out + ".html", "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(args.out + ".json", "w", encoding="utf-8") as fh:
        json.dump({"url": url, "score": audit.score(),
                   "findings": audit.findings}, fh, indent=2)
    print("Score: %d/100  ->  %s.{md,html,json}" % (audit.score(), args.out),
          flush=True)


if __name__ == "__main__":
    main()
