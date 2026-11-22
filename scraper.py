import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta

DATA_FILE = "data/news.json"

# ఏ API KEY సెట్ చేస్తే దాన్ని వాడుతుంది (XAI_API_KEY లేదా GEMINI_API_KEY)
XAI_API_KEY = os.environ.get("XAI_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()

GROK_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

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

# డైరెక్ట్ న్యూస్ వెబ్‌సైట్ల సెక్షన్ పేజీలు (RSS లేదు)
DIRECT_WEBSITES = [
    {
        "url": "https://www.10tv.in/andhra-pradesh",
        "source": "10TV",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://www.10tv.in/telangana",
        "source": "10TV",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://www.ntvtelugu.com/category/andhra-pradesh",
        "source": "NTV Telugu",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://www.ntvtelugu.com/category/telangana",
        "source": "NTV Telugu",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://www.tv9telugu.com/movies",
        "source": "TV9 Telugu",
        "default_cat": "సినిమా"
    }
]

CATEGORY_RULES = {
    "ఆంధ్రప్రదేశ్": [
        "ఆంధ్రప్రదేశ్", "ఆంధ్ర ప్రదేశ్", "ఏపీ",
        "అమరావతి", "విజయవాడ", "గుంటూరు",
        "విశాఖపట్నం", "విశాఖ", "తిరుపతి",
        "కర్నూలు", "కడప", "నెల్లూరు",
        "పల్నాడు", "ప్రకాశం", "చిత్తూరు",
        "అనంతపురం", "ఏలూరు", "కాకినాడ"
    ],
    "తెలంగాణ": [
        "తెలంగాణ", "హైదరాబాద్", "వరంగల్",
        "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్",
        "నల్గొండ", "సిద్దిపేట", "మహబూబ్ నగర్"
    ],
    "జాతీయ వార్తలు": [
        "భారతదేశం", "దేశవ్యాప్తంగా", "న్యూఢిల్లీ",
        "లోక్ సభ", "రాజ్యసభ", "ప్రధాని",
        "నరేంద్ర మోదీ", "సుప్రీంకోర్టు",
        "పార్లమెంట్", "కేంద్ర ప్రభుత్వం"
    ],
    "రాజకీయాలు": [
        "ఎన్నికలు", "రాజకీయాలు", "పార్టీ",
        "ఎమ్మెల్యే", "ఎంపీ", "మంత్రి",
        "ప్రతిపక్షం", "అసెంబ్లీ", "చంద్రబాబు",
        "జగన్", "రేవంత్ రెడ్డి", "కెసిఆర్", "కేటీఆర్", "పవన్ కళ్యాణ్"
    ],
    "సినిమా": [
        "సినిమా", "సినీ", "హీరో", "హీరోయిన్",
        "దర్శకుడు", "ట్రైలర్", "టీజర్",
        "టాలీవుడ్", "బాలీవుడ్", "బాక్సాఫీస్",
        "పాట విడుదల", "సినీ పరిశ్రమ", "మూవీ"
    ],
    "క్రీడలు": [
        "క్రికెట్", "ఫుట్‌బాల్", "కబడ్డీ",
        "ఐపీఎల్", "టీమిండియా", "విరాట్ కోహ్లీ",
        "రోహిత్ శర్మ", "ప్రపంచకప్", "ఒలింపిక్స్", "మ్యాచ్"
    ],
    "వ్యాపారం": [
        "వ్యాపారం", "బిజినెస్", "స్టాక్ మార్కెట్", "షేర్ మార్కెట్",
        "సెన్సెక్స్", "నిఫ్టీ", "బంగారం ధర",
        "వెండి ధర", "ఆర్థిక వ్యవస్థ", "బడ్జెట్", "బ్యాంక్"
    ],
    "విద్య": [
        "విద్యార్థులు", "పరీక్షలు", "ఫలితాలు",
        "ఇంటర్", "టెన్త్", "విద్యాశాఖ",
        "నోటిఫికేషన్", "ఉద్యోగాలు", "రిక్రూట్మెంట్", "యూనివర్సిటీ"
    ],
    "సాంకేతికత": [
        "టెక్నాలజీ", "సాంకేతిక", "మొబైల్",
        "స్మార్ట్ ఫోన్", "కృత్రిమ మేధస్సు",
        "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్"
    ],
    "క్రైమ్": [
        "పోలీసులు", "అరెస్ట్", "నేరం",
        "దొంగతనం", "మోసం", "కేసు నమోదు",
        "విచారణ", "అక్రమాలు", "సైబర్"
    ],
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


def fetch_html(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Direct HTML fetch error ({url}): {e}")
        return ""


def fetch_via_jina(url):
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Return-Format": "markdown"
    }
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"
    try:
        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Jina fetch error ({url}): {e}")
        return ""


def extract_article_links(section_url):
    raw_html = fetch_html(section_url)
    base_domain = urllib.parse.urlparse(section_url).netloc
    candidates = []

    if raw_html:
        anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html, flags=re.S | re.I)
        for href, inner_html in anchors:
            full_url = urllib.parse.urljoin(section_url, html.unescape(href.strip()))
            parsed = urllib.parse.urlparse(full_url)
            if parsed.netloc != base_domain:
                continue
            if full_url.rstrip("/") == section_url.rstrip("/"):
                continue
            if any(skip in full_url.lower() for skip in [
                "/category/", "/tag/", "/author/", "/video", "/videos",
                "/photo", "/photos", "/gallery", "/web-stories", "login", "privacy", "about"
            ]):
                continue
            # ఆర్టికల్ URL లా పొడవైన slug/path ఉండేలా చూడటం
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) < 2 and not re.search(r"-\d{4,}", parsed.path):
                continue

            title = html.unescape(re.sub(r"<[^>]+>", " ", inner_html))
            title = re.sub(r"\s+", " ", title).strip()
            if 20 <= len(title) <= 180 and is_adsense_safe(title):
                candidates.append({"title": title, "url": full_url})

    if not candidates:
        md = fetch_via_jina(section_url)
        for title, href in re.findall(r"\[([^\]]{20,180})\]\((https?://[^\s)]+)\)", md or ""):
            if urllib.parse.urlparse(href).netloc == base_domain and href.rstrip("/") != section_url.rstrip("/"):
                clean_t = re.sub(r"\s+", " ", title).strip()
                if is_adsense_safe(clean_t):
                    candidates.append({"title": clean_t, "url": href})

    seen = set()
    unique = []
    for c in candidates:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    return unique[:MAX_LINKS_PER_PAGE]


def extract_article_data(article_url, fallback_title):
    raw_html = fetch_html(article_url)
    title = fallback_title
    image_url = ""
    paragraphs = []

    if raw_html:
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", raw_html, flags=re.S | re.I)
        if h1_match:
            h1_txt = html.unescape(re.sub(r"<[^>]+>", " ", h1_match.group(1)))
            h1_txt = re.sub(r"\s+", " ", h1_txt).strip()
            if len(h1_txt) >= 15:
                title = h1_txt

        og_match = re.search(
            r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            raw_html,
            flags=re.I
        )
        if og_match:
            image_url = clean_image_url(og_match.group(1), article_url)

        body_html = re.sub(
            r"<(script|style|nav|header|footer|aside|noscript|form)[^>]*>.*?</\1>",
            " ",
            raw_html,
            flags=re.S | re.I
        )
        for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, flags=re.S | re.I):
            txt = html.unescape(re.sub(r"<[^>]+>", " ", p))
            txt = re.sub(r"\s+", " ", txt).strip()
            if len(txt) >= 50 and "http" not in txt.lower():
                paragraphs.append(txt)

        if not image_url:
            for cand in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, flags=re.I):
                cleaned = clean_image_url(cand, article_url)
                if cleaned:
                    image_url = cleaned
                    break

    content = "\n\n".join(paragraphs[:8])[:2500]

    if len(content) < 120:
        md = fetch_via_jina(article_url)
        if md:
            if not image_url:
                for raw_img in re.findall(r"!\[[^\]]*\]\(([^\s)]+)", md):
                    cleaned = clean_image_url(raw_img, article_url)
                    if cleaned:
                        image_url = cleaned
                        break
            lines = [
                re.sub(r"\s+", " ", ln.strip()).strip()
                for ln in md.splitlines()
                if len(ln.strip()) >= 50
                and not ln.strip().startswith(("![", "[", "#", "*", "-", ">"))
                and "http" not in ln.lower()
            ]
            if lines:
                content = "\n\n".join(lines[:8])[:2500]

    return title, content, image_url


def rewrite_with_ai(raw_title, raw_content, default_cat):
    """XAI_API_KEY లేదా GEMINI_API_KEY ఉంటే సొంత తెలుగులో రీరైట్ చేస్తుంది"""
    prompt = f"""
మీరు 'Portal Andhra' తెలుగు న్యూస్ పోర్టల్ ఎడిటర్.
కింద ఇచ్చిన సమాచారం ఆధారంగా ఏ వెబ్‌సైట్ నుండి కూడా నేరుగా కాపీ చేయకుండా, స్పష్టమైన, సహజమైన సొంత తెలుగులో వార్త కథనం రాయండి.
గూగుల్ యాడ్‌సెన్స్ పాలసీలకు అనుగుణంగా నిష్పాక్షికంగా, సున్నితమైన హింస/అశ్లీల/బెట్టింగ్ అంశాలు లేకుండా రాయండి.

విభాగాలు: ఆంధ్రప్రదేశ్, తెలంగాణ, జాతీయ వార్తలు, రాజకీయాలు, సినిమా, క్రీడలు, వ్యాపారం, విద్య, సాంకేతికత, క్రైమ్, ఇతర వార్తలు (డిఫాల్ట్: {default_cat})

మూల శీర్షిక: {raw_title}
మూల సమాచారం: {raw_content[:1800]}

JSON మాత్రమే రిటర్న్ చేయండి:
{{
