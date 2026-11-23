# -*- coding: utf-8 -*-
"""
portalandhra.com — Telugu news scraper (FULL / FINAL)

Guarantee:
  * Jina / Gemini / trafilatura / oka feed / oka item fail aina run aagadu.
  * Prati item ki veru url / external_url / id / detail_url / guid.
  * Paatha news.json lo unni "ప్రచురించింది" vaakyam auto-tholagipotundi.
  * Body dorakakapothe kuda clean teaser vastundi (fake "published in" ledu).

Env (anni optional):
  JINA_API_KEY, GEMINI_API_KEY        -> workflow lo already unnayi, auto-detect
  LLM_MODEL=gemini-2.5-flash
  USE_JINA=0 / USE_LLM=0              -> instant kill switch
  KEEP_THIN=0                         -> body leni varta assale publish avvadu
  JINA_SELECTOR=article
  SITE_URL, MAX_PER_FEED, MAX_ITEMS, SAFE_REPHRASE
"""

import os
import re
import json
import html
import time
import base64
import hashlib
import unicodedata
import urllib.request
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import Counter
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
KEEP_THIN = os.getenv("KEEP_THIN", "1") == "1"
SAFE_REPHRASE = os.getenv("SAFE_REPHRASE", "1") == "1"
JINA_SELECTOR = os.getenv("JINA_SELECTOR", "").strip()

MAX_PER_FEED = int(os.getenv("MAX_PER_FEED", "8"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "300"))
MAX_SENTENCES = 4
MAX_BRIEF_CHARS = 420
MIN_BODY_CHARS = 160
MAX_LLM_CALLS = 12
LLM_TIMEOUT = 12
DELAY_SEC = 2.0
TIMEOUT = 15

# 👈 quote-confusion ledu: okate safe literal
TRIM_CHARS = " \t'\"`,;()<>[]"

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

# --- ikkada nundi 100% attributed body vastundi ---
DIRECT_FEEDS = [
    {
        "url": "https://pib.gov.in/RssMain.aspx?ModId=6&Langcode=21&Regid=3",
        "category": "ప్రభుత్వం",
        "kind": "direct",
        "official": True,
    },
    # verify chesi uncomment cheyyi anna:
    # {"url": "https://www.eenadu.net/telugu/rss.xml", "category": "రాష్ట్రం",
    #  "kind": "direct", "official": False},
    # {"url": "https://www.andhrajyothy.com/rss", "category": "రాష్ట్రం",
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
    "Also Read", "Subscribe", "Photo:", "Skip to content",
)
BAD_HOSTS = (
    "google.com", "gstatic.com", "googleusercontent.com",
    "consent.google", "schema.org", "w3.org",
)

# కేవలం reporting verbs — పేర్లు/అంకెలు/కారకాలు మార్చం
SAFE_VERBS = (
    ("చెప్పారు", "తెలిపారు"),
    ("చెప్పిన", "తెలిపిన"),
    ("ప్రకటించారు", "వెల్లడించారు"),
    ("తెలియజేశారు", "తెలిపారు"),
)

DISTRICTS = (
    "చిత్తూరు", "అనంతపురం", "కర్నూలు", "గుంటూరు", "కృష్ణా", "గోదావరి",
    "విశాఖ", "శ్రీకాకుళం", "విజయనగరం", "ప్రకాశం", "నెల్లూరు", "కడప",
    "హైదరాబాద్", "వరంగల్", "ఖమ్మం", "నల్గొండ", "మహబూబ్", "కరీంనగర్",
    "ఆదిలాబాద్", "నిజామాబాద్", "మెదక్", "రంగారెడ్డి", "అమరావతి",
)

FACT_RE = re.compile(
    r"\d|₹|రూ|%|శాతం|కోట్ల|లక్షల|జిల్లా|మండలం|పథకం|ఉత్తర్వు|జీవో|"
    r"మంజూరు|ప్రారంభ|నిర్ణయం|ఎన్నిక|ధర|బడ్జెట్|"
    r"జనవరి|ఫిబ్రవరి|మార్చి|ఏప్రిల్|మే|జూన్|జూలై|ఆగస్టు|సెప్టెంబర్|"
    r"అక్టోబర్|నవంబర్|డిసెంబర్|సోమ|మంగళ|బుధ|గురు|శుక్ర|శని|ఆది"
)

CANON_RE = re.compile(
    r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""",
    re.I,
)

_robots, _last_hit = {}, {}
_llm_calls, _llm_dead, _jina_dead = 0, False, False


# ------------------------------------------------------------------ existing I/O
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
    return hashlib.sha1((norm(title) + "|" + norm(source)).encode("utf-8")).hexdigest()[:16]


def nums(s):
    return set(re.findall(r"\d[\d,.:/-]*", s or ""))


def norm_nums(s):
    return {re.sub(r"[,\s]", "", n).strip(".:/-") for n in nums(s)}


def telugu_ratio(s):
    return len(re.findall(r"[\u0C00-\u0C7F]", s or "")) / max(1, len(s or ""))


def is_google(u):
    try:
        n = urllib.parse.urlparse(u or "").netloc.lower()
    except Exception:
        return False
    return any(g in n for g in ("google.", "gstatic.", "googleusercontent."))


def slugify(title, key):
    # isalnum() Telugu aksharalni kuda true istundi
    s = unicodedata.normalize("NFKC", title or "").lower()
    s = "".join(ch for ch in s if ch.isalnum() or ch in " -_")
    s = re.sub(r"[\s_-]+", "-", s).strip("-")[:60] or "vartalu"
    return s + "-" + key[:8]


def clean_html(raw):
    if not raw:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def clean_markdown(md):
    """Jina headers / link syntax teesi plain Telugu text matrame."""
    lines = []
    for ln in (md or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("![") or re.match(r"^[-=]{3,}$", s):
            continue
        if re.match(
            r"^(Title|URL Source|Published Time|Markdown Content|Warning|Author|Description):",
            s, re.I,
        ):
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


def score_sentence(s, title):
    sc = 0
    if FACT_RE.search(s):
        sc += 3
    if any(d in s for d in DISTRICTS):
        sc += 2
    if re.search(r"\d", s):
        sc += 2
    if '"' in s or "“" in s or "”" in s or " అని " in s:
        sc += 2
    if norm(s) == norm(title):
        sc -= 6
    if len(s) > 220:
        sc -= 1
    if any(b.lower() in s.lower() for b in BOILERPLATE):
        sc -= 6
    return sc


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
            rp.allow_all = True        # robots 403/timeout -> aagipokunda, 2s delay tho
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
        if txt and len(txt.strip()) >= MIN_BODY_CHARS:
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
    """-> (markdown, publisher_url, image_url). Oka fail -> key off, migilivi fast."""
    global _jina_dead
    if not USE_JINA or _jina_dead or not target:
        return "", "", ""
    try:
        time.sleep(
