# -*- coding: utf-8 -*-
"""
portalandhra.com — Telugu news scraper (FINAL, syntax-safe)

Guarantee: Jina / Gemini / trafilatura / oka feed / oka item fail aina kuda
run aagadu. Deterministic brief + సందర్భం + మూలం tho data/news.json vastundi.

Auto-detect: JINA_API_KEY, GEMINI_API_KEY (nee workflow lo already unnayi)
Kill switch: USE_JINA=0 / USE_LLM=0  -> instant no-API run
Optional   : LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, SITE_URL, MAX_PER_FEED, MAX_ITEMS
"""

import os
import re
import json
import html
import time
import hashlib
import unicodedata
import urllib.request
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False          # lekunte stdlib <article>/<main> fallback

# ------------------------------------------------------------------ config
DATA_FILE = "data/news.json"
IST = timezone(timedelta(hours=5, minutes=30))

SITE_URL = os.getenv("SITE_URL", "https://portalandhra.com").rstrip("/")
UA = os.getenv(
    "NEWS_UA",
    "Mozilla/5.0 (compatible; PortalandhraBot/1.0; +https://portalandhra.com)",
)

JINA_KEY = os.getenv("JINA_API_KEY", "").strip()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
USE_JINA = bool(JINA_KEY) and os.getenv("USE_JINA", "1") != "0"
USE_LLM = os.getenv("USE_LLM", "1") != "0"

MAX_PER_FEED = int(os.getenv("MAX_PER_FEED", "8"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "300"))
MAX_SENTENCES = 4
MAX_BRIEF_CHARS = 420              # full copy kadu — brief matrame
MAX_LLM_CALLS = int(os.getenv("MAX_LLM_CALLS", "12"))
LLM_TIMEOUT = 12
DELAY_SEC = 2.0
TIMEOUT = 15

# 👈 ee line valla aa quote-SyntaxError malli raddu (escapes levu)
TRIM_CHARS = " \t" + '"' + "'" + "`,;()<>[]"

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# --- nee 3 Google feeds alage unnayi ---
RSS_FEEDS = [
    {
        "url": "https://news.google.com/rss/search?q=Andhra+Pradesh+Telugu&hl=te&gl=IN&ceid=IN:te",
        "category": "ఆంధ్రప్రదేశ్",
    },
    {
        "url": "https://news.google.com/rss/search?q=Telangana+Hyderabad+Telugu&hl=te&gl=IN&ceid=IN:te",
        "category": "తెలంగాణ",
    },
    {
        "url": "https://news.google.com/rss?hl=te&gl=IN&ceid=IN:te",
        "category": "జాతీయ వార్తలు",
    },
]

# --- ikkada nundi asalu body vastundi ---
DIRECT_FEEDS = [
    {
        "url": "https://pib.gov.in/RssMain.aspx?ModId=6&Langcode=21&Regid=3",
        "category": "ప్రభుత్వం",
        "kind": "direct",
        "official": True,
    },
    # verify chesi uncomment cheyyi:
    # {"url": "https://www.eenadu.net/telugu/rss.xml", "category": "రాష్ట్రం",
    #  "kind": "direct", "official": False},
]

CONTEXT_MAP = {
    "ఆంధ్రప్రదేశ్": "దీని ప్రభావం జిల్లా స్థాయిలో ఎలా ఉంటుందనేది తదుపరి అధికారిక ప్రకటనల్లో స్పష్టమవుతుంది.",
    "తెలంగాణ": "జిల్లా, మండల స్థాయి అమలు వివరాలు రాబోయే ఉత్తర్వుల్లో అందుబాటులోకి వస్తాయి.",
    "జాతీయ వార్తలు": "రాష్ట్రాలపై దీని ప్రభావానికి సంబంధించి అధికారిక స్పందన గమనించాల్సి ఉంటుంది.",
    "ప్రభుత్వం": "ఈ అంశానికి సంబంధించి అధికారిక ఉత్తర్వులు, తదుపరి సమాచారం గమనించాల్సి ఉంటుంది.",
}
DEFAULT_CONTEXT = "ఈ వార్తకు సంబంధించిన తదుపరి అధికారిక సమాచారం కోసం మూల లింక్ గమనించండి."

BOILERPLATE = (
    "ఇక్కడ చదవండి", "మరిన్ని వార్తలు", "క్లిక్", "షేర్", "ట్రెండింగ్", "ప్రకటన",
    "ఫొటో:", "Share", "Facebook", "WhatsApp", "Advertisement", "Read More",
    "Also Read", "Subscribe", "Photo:",
)
BAD_HOSTS = (
    "google.com", "gstatic.com", "googleusercontent.com",
    "consent.google", "schema.org", "w3.org",
)

CANON_RE = re.compile(
    r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""",
    re.I,
)

_robots, _last_hit = {}, {}
_llm_calls = 0


# ------------------------------------------------------------------ existing
def load_news():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print("Load error: " + str(e))
        return []


def save_news(items):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ helpers
def log(msg):
    print("[portal] " + msg, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def key_of(title, source):
    """Paatha JSON lo guid lekapoina pani chese stable dedup key."""
    return hashlib.sha1((norm(title) + "|" + norm(source)).encode("utf-8")).hexdigest()[:16]


def nums(s):
    return set(re.findall(r"\d[\d,.:/-]*", s or ""))


def telugu_ratio(s):
    return len(re.findall(r"[\u0C00-\u0C7F]", s or "")) / max(1, len(s or ""))


def clean_html(raw):
    if not raw:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def clean_markdown(md):
    """Jina header lines + link syntax teesi plain text matrame."""
    lines = []
    for ln in (md or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("!["):
            continue
        if re.match(r"^(Title|URL Source|Published Time|Markdown Content|Warning|Author):", s, re.I):
            continue
        s = re.sub(r"$$([^$$]+)$$$$[^)]+$$", r"\1", s)
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"[*_>`|]+", "", s)
        lines.append(s)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def sentences(text):
    out = []
    for p in re.split(r"(?<=[.!?।])\s+|\n+", text or ""):
        p = p.strip()
        if len(p) < 12:
            continue
        if len(p) < 160 and any(b.lower() in p.lower() for b in BOILERPLATE):
            continue
        out.append(p)
    return out


def polite_wait(url):
    host = urllib.parse.urlparse(url).netloc
    gap = time.time() - _last_hit.get(host, 0)
    if gap < DELAY_SEC:
        time.sleep(DELAY_SEC - gap)
    _last_hit[host] = time.time()


def can_fetch(url):
    p = urllib.parse.urlparse(url)
    base = p.scheme + "://" + p.netloc
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                rp.parse(r.read().decode("utf-8", errors="replace").splitlines())
        except Exception:
            # robots 403/timeout isté content aagipokunda: 2s delay + UA tho allow
            rp.allow_all = True
        _robots[base] = rp
    try:
        return _robots[base].can_fetch(UA, url)
    except Exception:
        return True


def fetch_html(url):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept-Language": "te,en;q=0.8"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            enc = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(enc, errors="replace")
    except Exception as e:
        log("  ! fetch fail: " + type(e).__name__)
        return None


def extract_text_from_page(page):
    if not page:
        return ""
    if HAS_TRAFILATURA:
        txt = trafilatura.extract(
            page, target_language="te",
            include_comments=False, include_links=False, include_tables=False,
        )
        if txt and len(txt.strip()) > 180:
            return re.sub(r"\n{3,}", "\n\n", txt.strip())
    m = re.search(r"(?is)<(article|main)[^>]*>(.*?)</\1>", page)
    return clean_html(m.group(2) if m else page)[:5000]


def fetch_page_text(url):
    if not url or not can_fetch(url):
        return ""
    polite_wait(url)
    return extract_text_from_page(fetch_html(url))


# ------------------------------------------------------------------ Jina ⭐
def jina_read(target):
    """-> (markdown, publisher_url, image_url). Error aina 3-tuple ee."""
    if not USE_JINA:
        return "", "", ""
    try:
        time.sleep(0.5)
        url = "https://r.jina.ai/" + target
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Authorization": "Bearer " + JINA_KEY,
            "Accept": "text/markdown",
            "X-Return-Format": "markdown",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            md = r.read().decode("utf-8", errors="replace")

        m = re.search(r"^URL Source:\s*(\S+)", md, re.M)
        pub = html.unescape(m.group(1)).strip(TRIM_CHARS) if m else ""
        if pub and not pub.startswith("http"):
            pub = ""

        mi = re.search(r"!$$[^$$]*$$$$(https?://[^)\s]+)$$", md)
        img = html.unescape(mi.group(1)).strip(TRIM_CHARS) if mi else ""
        return md, pub, img
    except Exception as e:
        log("  ! jina fail: " + type(e).__name__)
        return "", "", ""


# ------------------------------------------------------------------ resolver
def resolve_google_link(google_link):
    """-> (publisher_url, article_html). Jina lenappudu / fail ayyappudu."""
    try:
        req = urllib.request.Request(google_link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            final = r.geturl()
            page = r.read().decode("utf-8", errors="replace")

        netloc = urllib.parse.urlparse(final).netloc.lower()
        if not any(g in netloc for g in ("google.", "gstatic.", "googleusercontent.")):
            return final, page

        m = CANON_RE.search(page)
        cands = ([html.unescape(m.group(1))] if m else []) + re.findall(r"https?://[^\s<>]+", page)
        for c in cands:
            c = html.unescape(c).strip(TRIM_CHARS)     # 👈 syntax-safe
            if c.startswith("//"):
                c = "https:" + c
            if not c.startswith("http") or any(b in c for b in BAD_HOSTS):
                continue
            if not urllib.parse.urlparse(c).netloc:
                continue
            return c, ""
    except Exception as e:
        log("  ! resolve fail: " + type(e).__name__)
    return "", ""


# ------------------------------------------------------------------ content
def get_text(item, link, kind, title):
    """-> (text, origin, publisher_url, image_url)"""
    if kind == "direct":
        enc = clean_html(item.findtext("content:encoded", default="", namespaces=NS))
        if len(enc) > 180:
            return enc, "rss:content-encoded", link, ""
        desc = clean_html(item.findtext("description") or "")
        if len(desc) > 180 and norm(desc) != norm(title):
            return desc, "rss:description", link, ""
        t = fetch_page_text(link)
        if len(t) > 180:
            return t, "publisher-page", link, ""
        return desc, "headline-only", link, ""

    # Google News <description> lo body undadu — nammamu
    desc = clean_html(item.findtext("description") or "")
    if len(desc) > 180 and norm(desc) != norm(title):
        return desc, "rss:description", "", ""

    publisher_url, article_html, image = "", "", ""

    # 1) nee JINA_API_KEY — "content dorakataledu" ki asalu fix
    if USE_JINA:
        md, pub, img = jina_read(link)
        image = img
        txt = clean_markdown(md)
        if len(txt) > 180 and telugu_ratio(txt) > 0.20:
            return txt, "jina", pub, image
        publisher_url = pub or ""

    # 2) redirect / canonical / publisher page
    if not publisher_url:
        publisher_url, article_html = resolve_google_link(link)

    if publisher_url:
        if article_html and can_fetch(publisher_url):
            t = extract_text_from_page(article_html)
            if len(t) > 180:
                return t, "publisher-page", publisher_url, image
        t = fetch_page_text(publisher_url)
        if len(t) > 180:
            return t, "publisher-page", publisher_url, image

    return "", "headline-only", publisher_url, image


def make_brief(text, title, source_name):
    """SPIN LEDU — వాక్యాలను ఎంచుకుంటాం మాత్రమే. అంకెలు/పేర్లు మార్చం."""
    if len(text) > 180:
        picked, total = [], 0
        for s in sentences(text):
            if len(picked) >= MAX_SENTENCES or total + len(s) > MAX_BRIEF_CHARS:
                break
            picked.append(s)
            total += len(s) + 1
        brief = " ".join(picked).strip()
        if brief and not re.search(r"[.!?।]$", brief):
            brief = re.sub(r"[^.!?।]*$", "", brief).strip()
        if brief:
            return brief
    # body dorakaledu -> ఊహించం, honest ga cheptham
    return (
        title + ". ఈ వార్తను " + source_name + " ప్రచురించింది. "
        + "అధికారిక వివరాలు, తదుపరి సమాచారం మూల లింకులో చూడవచ్చు."
    )


# ------------------------------------------------------------------ LLM (optional)
def llm_config():
    """Workflow lo GEMINI_API_KEY undi -> automatic detect. XAI khali -> ignore."""
    explicit = os.getenv("LLM_API_KEY", "").strip()
    if explicit:
        base = (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        return explicit, base, os.getenv("LLM_MODEL", "gpt-4o-mini")
    if GEMINI_KEY:
        return (
            GEMINI_KEY,
            "https://generativelanguage.googleapis.com/v1beta/openai",
            os.getenv("LLM_MODEL", "gemini-2.0-flash"),
        )
    xai = os.getenv("XAI_API_KEY", "").strip()
    if xai:
        return xai, "https://api.x.ai/v1", os.getenv("LLM_MODEL", "grok-3-mini")
    return None


def polish_with_llm(brief, title):
    """Fail / guard reject / limit aina -> None -> deterministic brief ee final."""
    global _llm_calls
    if not USE_LLM or _llm_calls >= MAX_LLM_CALLS:
        return None
    cfg = llm_config()
    if not cfg:
        return None
    key, base, model = cfg
    _llm_calls += 1

    prompt = """నువ్వు అనుభవజ్ఞుడైన తెలుగు న్యూస్ ఎడిటర్ వి. ఇచ్చిన సంక్షిప్త వార్తను మెరుగుపరుచు.
1. పేర్లు, తేదీలు, అంకెలు, స్థలాలు ఏ మాత్రం మార్చొద్దు; కొత్త విషయం జోడించొద్దు.
2. సంధి, కారకం తప్పొద్దు. 'మంత్రి' ని 'సచివుడు' లాంటి పదాలుగా మార్చొద్దు.
3. కేవలం తెలుగులో రాయి. చివరగా 'సందర్భం:' అని ఒక వాక్యం రాయి.
ఫార్మాట్:
<3-4 వాక్యాలు>

సందర్భం: <ఒక వాక్యం>"""

    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "శీర్షిక: " + title + "\n\n" + brief},
        ],
    }
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
            out = json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log("  ! LLM fail -> deterministic: " + type(e).__name__)
        return None

    if "సందర్భం:" not in out:
        return None
    body, ctx = out.split("సందర్భం:", 1)
    body = body.strip()
    lines = ctx.strip().splitlines()
    ctx = lines[0].strip() if lines else ""

    # కొత్త అంకె / English leakage / ఖాళీ -> reject
    if not body or not ctx or nums(body) - nums(brief) or telugu_ratio(body + ctx) < 0.45:
        log("  ! LLM guard reject -> fallback")
        return None
    return body[:MAX_BRIEF_CHARS], ctx


# ------------------------------------------------------------------ item utils
def parse_date(item):
    raw = item.findtext("pubDate") or item.findtext("dc:date", default="", namespaces=NS) or ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).isoformat()
    except Exception:
        return datetime.now(IST).isoformat()


def parse_image(item):
    for path in ("media:content", "media:thumbnail"):
        el = item.find(path, NS)
        if el is not None and (el.get("url") or "").startswith("http"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and (enc.get("url") or "").startswith("http"):
        return enc.get("url")
    return ""


def fetch_rss_items(feed_url, category, kind="google", official=False):
    req = urllib.request.Request(
        feed_url, headers={"User-Agent": UA, "Accept-Language": "te,en;q=0.8"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    results = []

    for item in root.findall("./channel/item")[:MAX_PER_FEED]:
        try:                                   # 👈 ikkada try...
            raw_title = (item.findtext("title") or "").strip()   # 👈 .strip() fix
            link = (item.findtext("link") or "").strip()
            source_el = item.find("source")
            if source_el is not None:
                source_name = (source_el.text or "Google News").strip()
                source_home = (source_el.get("url") or "").strip()
            else:
                source_name, source_home = "Google News", ""

            title = raw_title.rsplit(" - ", 1)[0].strip() if " - " in raw_title else raw_title
            if not title or not link:
                continue

            text, origin, publisher_url, image = get_text(item, link, kind, title)
            brief = make_brief(text, title, source_name)
            context = CONTEXT_MAP.get(category, DEFAULT_CONTEXT)
            ai = False

            # headline-only ki LLM ippinchamu — adi ఊహిస్తుంది
            if origin != "headline-only":
                got = polish_with_llm(brief, title)
                if got:
                    brief, context, ai = got[0], got[1], True

            if not image:
                image = parse_image(item)

            results.append({
                "title": title,
                "content": (
                    brief + "\n\nసందర్భం: " + context + "\n\n"
                    + "మూలం: " + source_name + " · పూర్తి వార్తకు పై లింక్ ఉపయోగించండి."
                ),
                "category": category,
                "source": source_name,
                "url": link,                  # Google link ne — click pani chestundi
                "image": image,
                "published_at": parse_date(item),
                "guid": key_of(title, source_name),
                "source_home": source_home,
                "publisher_url": publisher_url,
                "context": context,
                "content_from": origin,
                "ai_polished": ai,
                "official": official,
                "needs_review": origin == "headline-only",
                "site": SITE_URL,
            })
            log("  OK [" + origin + ("+AI" if ai else "") + "] " + title[:46] + "...")
        except Exception as e:                 # 👈 ...ikkaḍa except CLOSED ✅
            log("  ! item skip: " + type(e).__name__ + " " + str(e)[:80])
            continue

    return results


def main():
    log("start -> " + SITE_URL + " | jina=" + str(USE_JINA) + " llm=" + str(USE_LLM))
    existing = load_news()
    seen = set()
    for x in existing:
        if isinstance(x, dict):
            seen.add(x.get("guid") or key_of(x.get("title", ""), x.get("source", "")))
    added = []

    for feed in RSS_FEEDS + DIRECT_FEEDS:
        cat = feed["category"]
        log("-> " + cat)
        try:
            items = fetch_rss_items(
                feed["url"], cat,
                kind=feed.get("kind", "google"),
                official=feed.get("official", False),
            )
        except Exception as e:
            log("  ! feed error: " + type(e).__name__ + " " + str(e)[:100])
            continue

        for it in items:
            if it["guid"] in seen:
                continue
            seen.add(it["guid"])
            added.append(it)

    if not added:
        log("No new items -> save ledu, redeploy ledu ✅")
        return

    merged = added + existing
    merged.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    save_news(merged[:MAX_ITEMS])
    log("Added " + str(len(added)) + " -> total " + str(min(len(merged), MAX_ITEMS)) + " -> " + DATA_FILE)


if __name__ == "__main__":
    main()
