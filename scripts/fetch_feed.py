#!/usr/bin/env python3
"""Fetch mine-action headlines into docs/data/feed.json.
 
Standard library only. Stores headline, link, source, date. Never article text.
A failing source is logged and skipped; existing items are never wiped.
"""
import email.utils
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
 
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "sources.json")
FEED_PATH = os.path.join(ROOT, "docs", "data", "feed.json")
USER_AGENT = "minedetection.org headline bot (+https://minedetection.org)"
ATOM = "{http://www.w3.org/2005/Atom}"
 
 
def log(level, msg):
    # GitHub Actions turns ::warning:: lines into annotations.
    prefix = "::warning::" if level == "warn" else ""
    print(f"{prefix}{msg}", flush=True)
 
 
def http(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
 
 
def http_retry(url, tries=4, wait=20):
    """Retry on HTTP 429. GitHub runners share IPs, so GDELT's per-IP
    limit is often already spent by someone else. Waits 20, 40, 60 s."""
    for attempt in range(tries):
        try:
            return http(url)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            log("info", f"429 from {urllib.parse.urlsplit(url).netloc}, "
                        f"retrying in {wait * (attempt + 1)} s")
            time.sleep(wait * (attempt + 1))
 
 
def norm_url(url):
    p = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
             if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"),
         urllib.parse.urlencode(query), ""))
 
 
def norm_title(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
 
 
def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
def make_item(title, url, source, published, origin, country=None):
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if not title or not url:
        return None
    return {
        "id": hashlib.sha1(norm_url(url).encode()).hexdigest()[:16],
        "title": title,
        "url": url.strip(),
        "source": (source or urllib.parse.urlsplit(url).netloc).strip(),
        "published": published,
        "origin": origin,
        "country": country,
    }
 
 
# ---------- sources ----------
 
def fetch_gdelt(cfg):
    items = []
    for i, query in enumerate(cfg.get("queries", [])):
        if i:
            time.sleep(6)  # GDELT asks for about one request per 5 s
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(cfg.get("maxrecords", 75)),
            "timespan": cfg.get("timespan", "3d"),
            "sort": "datedesc",
        }
        raw = http_retry("https://api.gdeltproject.org/api/v2/doc/doc?"
                         + urllib.parse.urlencode(params))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # GDELT answers query-syntax errors with plain text
            raise RuntimeError("non-JSON reply: "
                               + raw[:200].decode("utf-8", "replace"))
        for a in data.get("articles", []):
            published = None
            if a.get("seendate"):
                try:
                    published = iso(datetime.strptime(a["seendate"],
                                                      "%Y%m%dT%H%M%SZ"))
                except ValueError:
                    pass
            it = make_item(a.get("title"), a.get("url"), a.get("domain"),
                           published, "news", a.get("sourcecountry"))
            if it:
                items.append(it)
    return items
 
 
def fetch_reliefweb(cfg):
    appname = os.environ.get("RELIEFWEB_APPNAME", "").strip()
    if not appname:
        log("info", "reliefweb: RELIEFWEB_APPNAME not set, skipping")
        return None
    body = {
        "preset": "latest",
        "limit": cfg.get("limit", 50),
        "profile": "list",
        "filter": {"field": "theme", "value": cfg.get("theme", "Mine Action")},
        "fields": {"include": ["title", "url", "url_alias", "date.created",
                               "source.shortname", "source.name",
                               "primary_country.name"]},
    }
    url = ("https://api.reliefweb.int/v2/reports?appname="
           + urllib.parse.quote(appname))
    raw = http(url, data=json.dumps(body).encode(),
               headers={"Content-Type": "application/json"})
    data = json.loads(raw)
    items = []
    for d in data.get("data", []):
        f = d.get("fields", {})
        sources = f.get("source") or []
        src = ", ".join(s.get("shortname") or s.get("name", "") for s in sources)
        country = (f.get("primary_country") or {}).get("name")
        it = make_item(f.get("title"), f.get("url_alias") or f.get("url"),
                       src or "ReliefWeb", (f.get("date") or {}).get("created"),
                       "reliefweb", country)
        if it:
            items.append(it)
    return items
 
 
def parse_feed_xml(raw, feed_name):
    root = ET.fromstring(raw)
    items = []
    for node in root.iter("item"):  # RSS 2.0
        published = None
        pub = node.findtext("pubDate")
        if pub:
            try:
                published = iso(email.utils.parsedate_to_datetime(pub))
            except (TypeError, ValueError):
                pass
        it = make_item(node.findtext("title"), node.findtext("link"),
                       feed_name, published, "feeds")
        if it:
            items.append(it)
    for node in root.iter(ATOM + "entry"):  # Atom
        link = None
        for l in node.findall(ATOM + "link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href")
                break
        published = None
        stamp = node.findtext(ATOM + "published") or node.findtext(ATOM + "updated")
        if stamp:
            try:
                published = iso(datetime.fromisoformat(stamp.replace("Z", "+00:00")))
            except ValueError:
                pass
        it = make_item(node.findtext(ATOM + "title"), link, feed_name,
                       published, "feeds")
        if it:
            items.append(it)
    return items
 
 
# ---------- main ----------
 
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default
 
 
def title_ok(item, include, exclude):
    if item["origin"] == "reliefweb":
        return True
    t = item["title"]
    return bool(include.search(t)) and not exclude.search(t)
 
 
def main():
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        log("warn", f"cannot read {CONFIG_PATH}")
        return 1
    tf = cfg.get("title_filter", {})
    include = re.compile(tf.get("include", "."), re.I)
    exclude = re.compile(tf.get("exclude", "a^"), re.I)
 
    jobs = []
    if cfg.get("gdelt", {}).get("enabled", True):
        jobs.append(("GDELT", lambda: fetch_gdelt(cfg["gdelt"])))
    if cfg.get("reliefweb", {}).get("enabled", True):
        jobs.append(("ReliefWeb", lambda: fetch_reliefweb(cfg["reliefweb"])))
    for feed in cfg.get("rss", {}).get("feeds", []):
        jobs.append((feed["name"],
                     lambda f=feed: parse_feed_xml(http(f["url"]), f["name"])))
 
    fresh, status = [], []
    for name, job in jobs:
        try:
            result = job()
            if result is None:
                status.append({"name": name, "ok": True, "skipped": True})
                continue
            got = [i for i in result if title_ok(i, include, exclude)]
            fresh.extend(got)
            status.append({"name": name, "ok": True, "count": len(got)})
            log("info", f"{name}: {len(got)} items")
        except (urllib.error.URLError, OSError, ValueError,
                RuntimeError, ET.ParseError) as e:
            status.append({"name": name, "ok": False, "error": str(e)[:200]})
            log("warn", f"{name} failed: {e}")
 
    old = load_json(FEED_PATH, {}).get("items", [])
    cutoff = iso(datetime.now(timezone.utc)
                 - timedelta(days=cfg.get("retention_days", 30)))
 
    merged, seen_ids, seen_titles = [], set(), set()
    for it in sorted(fresh + old,
                     key=lambda i: i.get("published") or "", reverse=True):
        if it.get("published") and it["published"] < cutoff:
            continue
        nt = norm_title(it["title"])
        if it["id"] in seen_ids or nt in seen_titles:
            continue  # syndicated copies share a title
        seen_ids.add(it["id"])
        seen_titles.add(nt)
        merged.append(it)
    merged = merged[: cfg.get("max_items", 300)]
 
    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    with open(FEED_PATH, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": iso(datetime.now(timezone.utc)),
                   "sources": status, "items": merged},
                  fh, ensure_ascii=False, indent=1)
    log("info", f"wrote {len(merged)} items")
    return 0
 
 
if __name__ == "__main__":
    sys.exit(main())
 
