import os
import re
import json
import time
import html
import asyncio
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta
from crawl4ai import AsyncWebCrawler

DATA_FILE = "data/news.json"

JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()
CRAWL4AI_LLM_PROVIDER = os.environ.get("CRAWL4AI_LLM_PROVIDER", "").strip()
CRAWL4AI_LLM_API_KEY = os.environ.get("CRAWL4AI_LLM_API_KEY", "").strip()

MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 3
MAX_LINKS_PER_PAGE = 5
REQUEST_TIMEOUT = 25

IST = timezone(timedelta(hours=5, minutes=30))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "te-IN,te;q=0.9,en-US;q=0.8,en;q=0.7"
}

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex",
    "betting", "casino", "gambling",
    "ushodaya", "prosecuted", "georgia-fulton",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

BAD_IMAGE_PATTERNS = [
    "logo", "icon", "favicon", "avatar", "sprite", "badge", "button",
    "banner", "advert", "ad-", "ads", "doubleclick", "googlesyndication",
    "facebook.com/tr", "pixel", "tracker", "spacer", "blank", "placeholder",
    "default-thumb", "no-image", "author", "profile", "whatsapp", "twitter",
    "youtube.com", "play-store", "app-store", "svg"
]

VALID_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

DIRECT_WEBSITES = [
    {"url": "https://www.10tv.in/andhra-pradesh", "source": "10TV", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.10tv.in/telangana", "source": "10TV", "default_cat": "తెలంగాణ"},
    {"url": "https://www.ntvtelugu.com/category/andhra-pradesh", "source": "NTV Telugu", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.ntvtelugu.com/category/telangana", "source": "NTV Telugu", "default_cat": "తెలంగాణ"},
    {"url": "https://www.tv9telugu.com/movies", "source": "TV9 Telugu", "default_cat": "సినిమా"}
]

CATEGORY_RULES = {
    "ఆంధ్రప్రదేశ్": ["ఆంధ్రప్రదేశ్", "ఏపీ", "అమరావతి", "విజయవాడ", "గుంటూరు", "విశాఖపట్నం", "తిరుపతి", "కర్నూలు", "నెల్లూరు"],
    "తెలంగాణ": ["తెలంగాణ", "హైదరాబాద్", "వరంగల్", "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్", "నల్గొండ"],
    "జాతీయ వార్తలు": ["భారతదేశం", "దేశవ్యాప్తంగా", "న్యూఢిల్లీ", "లోక్ సభ", "ప్రధాని", "మోదీ", "సుప్రీంకోర్టు", "కేంద్ర ప్రభుత్వం"],
    "రాజకీయాలు": ["ఎన్నికలు", "రాజకీయాలు", "పార్టీ", "ఎమ్మెల్యే", "ఎంపీ", "మంత్రి", "అసెంబ్లీ", "చంద్రబాబు", "జగన్", "రేవంత్", "పవన్"],
    "సినిమా": ["సినిమా", "సినీ", "హీరో", "హీరోయిన్", "దర్శకుడు", "ట్రైలర్", "టీజర్", "టాలీవుడ్", "బాక్సాఫీస్", "మూవీ"],
    "క్రీడలు": ["క్రికెట్", "ఫుట్‌బాల్", "కబడ్డీ", "ఐపీఎల్", "టీమిండియా", "ప్రపంచకప్", "మ్యాచ్"],
    "వ్యాపారం": ["వ్యాపారం", "బిజినెస్", "స్టాక్ మార్కెట్", "సెన్సెక్స్", "నిఫ్టీ", "బంగారం", "బడ్జెట్", "బ్యాంక్"],
    "విద్య": ["విద్యార్థులు", "పరీక్షలు", "ఫలితాలు", "ఇంటర్", "టెన్త్", "విద్యాశాఖ", "నోటిఫికేషన్", "ఉద్యోగాలు"],
    "సాంకేతికత": ["టెక్నాలజీ", "సాంకేతిక", "మొబైల్", "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్"],
    "క్రైమ్": ["పోలీసులు", "అరెస్ట్", "నేరం", "దొంగతనం", "మోసం", "కేసు", "విచారణ", "సైబర్"],
    "ఇతర వార్తలు": []
}


def is_adsense_safe(text):
    lower = (text or "").lower()
    for word in BLOCKED_KEYWORDS:
        w = word.lower()
        if re.search(r"^[a-z-]+$", w):
            if re.search(r"\b" + re.escape(w) + r"\b", lower):
                return False
        elif w in lower:
            return False
    return True


def clean_image_url(raw_url, base_url=""):
    if not raw_url:
        return ""
    url = html.unescape(raw_url.strip()).strip("\"'()<>")
    if not url or url.startswith("data:"):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif base_url and url.startswith("/"):
        url = urllib.parse.urljoin(base_url, url)

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""

    lower_full = url.lower()
    lower_path = parsed.path.lower()

    if any(pat in lower_full for pat in BAD_IMAGE_PATTERNS):
        return ""

    dim_match = re.search(r"(?:^|[^a-z0-9])(\d{1,3})x(\d{1,3})(?:[^a-z0-9]|$)", lower_path)
    if dim_match:
        w, h = int(dim_match.group(1)), int(dim_match.group(2))
        if w < 180 or h < 120:
            return ""

    qs = urllib.parse.parse_qs(parsed.query)
    for w_key in ("w", "width"):
        if w_key in qs:
            try:
                if int(re.sub(r"\D", "", qs[w_key][0]) or 0) < 180:
                    return ""
            except Exception:
                pass

    has_valid_ext = lower_path.endswith(VALID_IMAGE_EXTS)
    looks_like_image_cdn = any(
        k in lower_path for k in ["/image", "/images", "/img", "/photo", "/photos", "/media", "/upload", "/thumb"]
    )
    if not (has_valid_ext or looks_like_image_cdn):
        return ""

    clean_query_items = [
        (k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in ("t", "ts", "v", "ver", "cache", "utm_source", "utm_medium", "utm_campaign")
    ]
    cleaned = parsed._replace(query=urllib.parse.urlencode(clean_query_items), fragment="")
    return urllib.parse.urlunparse(cleaned)


def read_via_jina(url):
    if not url:
        return ""
    jina_url = f"
