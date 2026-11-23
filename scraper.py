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

# optional — lekunte stdlib fallback pani chestundi (pip avasaram ledu)
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

DATA_FILE = "data/news.json"
IST = timezone(timedelta(hours=5, minutes=30))

UA = os.getenv(
    "NEWS_UA",
    "Mozilla/5.0 (compatible; TeluguNewsBrief/1.0; +https://yourdomain.com)",
)
MAX_PER_FEED = 8
MAX_ITEMS = 300          # news.json perigipokunda
MAX_SENTENCES = 4
MAX_BRIEF_CHARS = 420    # full article kadu — brief matrame (copyright safe)
DELAY_SEC = 2.0

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# ⚠️ Nee 3 feeds alage unnayi — em marchaledu
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

# 👇 IDEE ASALU FIX: ikkada body text vastundi. URLs ni okasari verify chesko.
DIRECT_FEEDS = [
    {
        "url": "https://pib.gov.in/RssMain.aspx?ModId=6&Langcode=21&Regid=3",
        "category": "ప్రభుత్వం",
        "kind": "direct",
        "official": True,
    },
    # {"url": "https://www.eenadu.net/telugu/rss.xml", "category": "రాష్ట్రం",
    #  "kind": "direct", "official": False},   # verify chesi uncomment cheyyi
    # {"url": "https://www.sakshi.com/rss/telugu", "category": "రాష్ట్రం",
    #  "kind": "direct", "official": False},
]

CONTEXT_MAP = {
    "ఆంధ్రప్రదేశ్": "దీని ప్రభావం జిల్లా స్థాయిలో ఎలా ఉంటుందనేది తదుపరి అధికారిక ప్రకటనల్లో స్పష్టమవుతుంది.",
    "తెలంగాణ": "జిల్లా / మండల స్థాయి అమలు వివరాలు రాబోయే ఉత్తర్వుల్లో అందుబాటులోకి వస్తాయి.",
    "జాతీయ వార్తలు": "రాష్ట్రాలపై దీని ప్రభావానికి సంబంధించి అధికారిక స్పందన గమనించాల్సి ఉంటుంది.",
    "ప్రభుత్వం": "ఈ అంశానికి సంబంధించి అధికారిక ఉత్తర్వులు, తదుపరి అప్‍డేట్‍లు గమనించాల్సి ఉంటుంది.",
}
DEFAULT_CONTEXT = "ఈ వార్తకు సంబంధించిన తదుపరి అధికారిక సమాచారం కోసం మూల లింక్ గమనించండి."

BOILERPLATE = (
    "ఇక్కడ చదవండి", "మరిన్ని వార్తలు", "క్లిక్", "షేర్", "ట్రెండింగ్", "ప్రకటన",
    "ఫొటో:", "Share", "Facebook", "WhatsApp", "Advertisement", "Read More",
    "Also Read", "Subscribe", "Photo:",
)
BAD_HOSTS = ("google.com", "gstatic.com", "googleusercontent.com", "schema.org", "w3.org")

_robots, _last_hit = {}, {}


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
        print(f"Load error: {e}")
        return []


def save_news(items):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ helpers
def log(msg):
    print(f"[fetch] {msg}", flush=True)


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def key_of(title, source):
    """Paatha items (guid leni) tho kuda pani chese stable dedup key."""
    return hashlib.sha1(f"{norm(title)}|{norm(source)}".encode("utf-8")).hexdigest()[:16]


def clean_html(raw):
    if not raw:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def sentences(text):
    out = []
    for p in re.split(r"(?<=[.!?।])\s+|\n+", text):
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
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp.disallow_all = True          # conservative: teliyakunte aapu
        _robots[base] = rp
    try:
        return _robots[base].can_fetch(UA, url)
    except Exception:
        return False


def fetch_html(url):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept-Language": "te,en;q=0.8"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            enc = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(enc, errors="replace")
    except Exception as e:
        log(f"  ! fetch fail: {type(e).__name__}")
        return None


def extract_text_from_page(page):
    """trafilatura unte adi; lekunte <article>/<main> slice + stdlib clean."""
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


def resolve_google_link(google_link):
    """Google redirect ni publisher URL ki marchu.
    Returns (publisher_url, article_html) — article_html only if redirect directly landed."""
    try:
        req = urllib.request.Request(google_link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            final = r.geturl()
            page = r.read().decode("utf-8", errors="replace")
        if "news.google.com" not in urllib.parse.urlparse(final).netloc:
            return final, page                      # ✅ direct landing

        m = re.search(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)", page, re.I)
        cands = ([html.unescape(m.group(1))] if m else []) + re.findall(r"https?://[^\s<>]+", page)
        for c in cands:
            c = html.unescape(c.strip("\"'"),;"))
            if any(b in c for b in BAD_HOSTS) or not urllib.parse.urlparse(c).netloc:
                continue
            return c, ""                            # deeni ni separate ga fetch chestham
    except Exception:
        pass
    return "", ""


# ------------------------------------------------------------------ content
def get_text(item, link, kind):
    """-> (text, origin, publisher_url). Google desc ni 'text' la nammamu."""
    publisher_url = ""

    if kind == "direct":
        enc = clean_html(item.findtext("content:encoded", default="", namespaces=NS))
        if len(enc) > 180:
            return enc, "rss:content-encoded", ""
        desc = clean_html(item.findtext("description") or "")
        if len(desc) > 180:
            return desc, "rss:description", ""
        t = fetch_page_text(link)                   # direct link = publisher ee
        if len(t) > 180:
            return t, "publisher-page", ""
        return desc, "headline-only", ""

    # ---- Google News
    desc = clean_html(item.findtext("description") or "")
    title_now = clean_html(item.findtext("title") or "")
    if len(desc) > 180 and norm(desc) != norm(title_now):
        return desc, "rss:description", ""

    pub, article_html = resolve_google_link(link)
    publisher_url = pub or ""
    if article_html and pub and can_fetch(pub):
        t = extract_text_from_page(article_html)
        if len(t) > 180:
            return t, "publisher-page", publisher_url
    if pub:
        t = fetch_page_text(pub)
        if len(t) > 180:
            return t, "publisher-page", publisher_url
    return "", "headline-only", publisher_url


def make_brief(text, title, source_name):
    """SPIN LEDU — వాక్యాలను ఎంచుకుంటాం మాత్రమే. పదాలు / అంకెలు మార్చం."""
    if len(text) > 180:
        picked, total = [], 0
        for s in sentences(text):
            if len(picked) >= MAX_SENTENCES or total + len(s) > MAX_BRIEF_CHARS:
                break
            picked.append(s)
            total += len(s) + 1
        brief = " ".join(picked).strip()
        if brief:
            if not re.search(r"[.!?।]$", brief):
                brief = re.sub(r"[^.!?।]*$", "", brief).strip()
            return brief
    # headline-only: ఊహించం, honestly cheptham
    return (
        f"{title}. ఈ వార్తను {source_name} ప్రచురించింది. "
        "అధికారిక వివరాలు, తదుపరి అప్‍డేట్‍లు మూల లింక్‍లో చూడవచ్చు."
    )


def nums(s):
    return set(re.findall(r"\d[\d,.:/-]*", s))


def telugu_ratio(s):
    return len(re.findall(r"[\u0C00-\u0C7F]", s)) / max(1, len(s))


def polish_with_llm(brief, title):
    """Optional. LLM_API_KEY lekunte assale pilavadu. Headline-only ki eppudu pilavadu."""
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    prompt = (
        "నువ్వు తెలుగు న్యూస్ ఎడిటర్ వి. ఇచ్చిన సంక్షిప్త వార్తను మెరుగుపరుచు.\n"
        "1. పేర్లు, తేదీలు, అంకెలు, స్థలాలు ఏ మాత్రం మార్చొద్దు; కొత్త విషయం జోడించొద్దు.\n"
        "2. సంధి/కారకం తప్పొద్దు. 'మంత్రి→సచివుడు' లాంటి పద మార్పులు వద్దు.\n"
        "3. కేవలం తెలుగు. చివరగా 'సందర్భం:' అని ఒక వాక్యం రాయి.\n"
        "ఫార్మాట్:\n<3-4 వాక్యాలు>\n\nసందర్భం: <ఒక వాక్యం>"
    )
    payload = {
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0.2, "max_tokens": 500,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"శీర్షిక: {title}\n\n{brief}"},
        ],
    }
    try:
        req = urllib.request.Request(
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log(f"  ! LLM fail → deterministic brief: {type(e).__name__}")
        return None

    if "సందర్భం:" not in out:
        return None
    body, ctx = out.split("సందర్భం:", 1)
    body, ctx = body.strip(), ctx.strip().splitlines()[0].strip()
    # 🛡️ కొత్త అంకె / English leakage / ఖాళీ → reject
    if not body or nums(body) - nums(brief) or telugu_ratio(body + ctx) < 0.45:
        log("  ! LLM guard reject → fallback")
        return None
    return body[:MAX_BRIEF_CHARS], ctx


# ------------------------------------------------------------------ item utils
def parse_date(item):
    raw = item.findtext("pubDate") or item.findtext("dc:date", namespaces=NS) or ""
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
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source_name = (source_el.text or "Google News").strip() if source_el is not None else "Google News"
        source_home = (source_el.get("url") or "").strip() if source_el is not None else ""

        title = raw_title.rsplit(" - ", 1)[0].strip() if " - " in raw_title else raw_title
        if not title or not link:
            continue

        text, origin, publisher_url = get_text(item, link, kind)
        brief = make_brief(text, title, source_name)
        context = CONTEXT_MAP.get(category, DEFAULT_CONTEXT)
        ai = False

        # ⚠️ headline-only ki LLM ippinchamu — adi ఊహిస్తుంది
        if origin != "headline-only":
            got = polish_with_llm(brief, title)
            if got:
                brief, context, ai = got[0], got[1], True

        results.append({
            # ---- పాత keys అలాగే ఉన్నాయి (frontend debba padadu) ----
            "title": title,
            "content": (
                f"{brief}\n\nసందర్భం: {context}\n\n"
                f"మూలం: {source_name} · పూర్తి వార్తకు పై లింక్ ఉపయోగించండి."
            ),
            "category": category,
            "source": source_name,
            "url": link,                    # 👈 Google link ne — click pani chestundi
            "image": parse_image(item),
            "published_at": parse_date(item),   # 👈 now(IST) kadu, asalu pubDate
            # ---- కొత్త keys (additive) ----
            "guid": key_of(title, source_name),
            "source_home": source_home,
            "publisher_url": publisher_url,
            "context": context,
            "content_from": origin,
            "ai_polished": ai,
            "official": official,
            "needs_review": origin == "headline-only",
        })
        log(f"  ✓ [{origin}{'+AI' if ai else ''}] {title[:46]}…")

    return results


def main():
    existing = load_news()
    # paatha file lo guid lekapoina pani cheyyadaniki
    seen = {key_of(x.get("title", ""), x.get("source", "")) for x in existing}
    added = []

    for feed in RSS_FEEDS + DIRECT_FEEDS:
        cat = feed["category"]
        log(f"→ {cat}")
        try:
            items = fetch_rss_items(
                feed["url"], cat,
                kind=feed.get("kind", "google"),
                official=feed.get("official", False),
            )
        except Exception as e:
            log(f"  ! feed error: {type(e).__name__}: {e}")
            continue

        for it in items:
            if it["guid"] in seen:
                continue
            seen.add(it["guid"])
            added.append(it)

    if not added:
        log("No new items ✅ (empty commit / redeploy ledu)")
        return

    merged = added + existing
    merged.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    save_news(merged[:MAX_ITEMS])
    log(f"Added {len(added)} → total {min(len(merged), MAX_ITEMS)} → {DATA_FILE}")


if __name__ == "__main__":
    main()
