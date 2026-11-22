import os
import re
import json
import html
import shutil
import asyncio
import urllib.parse
from datetime import datetime, timezone, timedelta
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# ==========================================
# PORTAL ANDHRA CONFIGURATION
# ==========================================

DATA_FILE = "data/news.json"

MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 3
MAX_LINKS_PER_PAGE = 6

IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# CONTENT FILTER
# ==========================================

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex",
    "betting", "casino", "gambling",
    "ushodaya", "prosecuted", "georgia-fulton",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

BAD_IMAGE_PATTERNS = [
    "logo", "icon", "favicon", "avatar", "sprite",
    "badge", "button", "banner", "advert", "ads",
    "doubleclick", "googlesyndication", "pixel",
    "tracker", "spacer", "blank", "placeholder",
    "no-image", "author", "profile", "whatsapp",
    "twitter", "youtube.com", "play-store", "svg"
]

VALID_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# ==========================================
# NEWS SOURCES (Sakshi, NTV, TV9, V6, 10TV)
# ==========================================

DIRECT_WEBSITES = [
    # --- SAKSHI ---
    {
        "url": "https://sakshi.com",
        "source": "Sakshi",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://sakshi.com",
        "source": "Sakshi",
        "default_cat": "తెలంగాణ"
    },

    # --- NTV TELUGU ---
    {
        "url": "https://ntvtelugu.com",
        "source": "NTV Telugu",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://ntvtelugu.com",
        "source": "NTV Telugu",
        "default_cat": "తెలంగాణ"
    },

    # --- TV9 TELUGU ---
    {
        "url": "https://tv9telugu.com",
        "source": "TV9 Telugu",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://tv9telugu.com",
        "source": "TV9 Telugu",
        "default_cat": "తెలంగాణ"
    },

    # --- V6 VELUGU ---
    {
        "url": "https://v6velugu.com",
        "source": "V6 Velugu",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://v6velugu.com",
        "source": "V6 Velugu",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },

    # --- 10TV ---
    {
        "url": "https://10tv.in",
        "source": "10TV",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://10tv.in",
        "source": "10TV",
        "default_cat": "తెలంగాణ"
    }
]

# ==========================================
# CATEGORIES
# ==========================================

CATEGORY_RULES = {
    "ఆంధ్రప్రదేశ్": ["ఆంధ్రప్రదేశ్", "ఏపీ", "అమరావతి", "విజయవాడ", "గుంటూరు", "విశాఖపట్నం", "తిరుపతి", "కర్నూలు", "నెల్లూరు"],
    "తెలంగాణ": ["తెలంగాణ", "హైదరాబాద్", "వరంగల్", "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్"],
    "జాతీయ వార్తలు": ["భారతదేశం", "దేశవ్యాప్తంగా", "న్యూఢిల్లీ", "ప్రధాని", "మోదీ", "సుప్రీంకోర్టు"],
    "రాజకీయాలు": ["ఎన్నికలు", "రాజకీయాలు", "పార్టీ", "ఎమ్మెల్యే", "ఎంపీ", "మంత్రి", "అసెంబ్లీ", "చంద్రబాబు", "జగన్", "రేవంత్", "పవన్"],
    "సినిమా": ["సినిమా", "సినీ", "హీరో", "హీరోయిన్", "దర్శకుడు", "ట్రైలర్", "టీజర్", "టాలీవుడ్", "బాక్సాఫీస్", "మూవీ"],
    "క్రీడలు": ["క్రికెట్", "ఫుట్‌బాల్", "ఐపీఎల్", "టీమిండియా", "ప్రపంచకప్", "మ్యాచ్"],
    "వ్యాపారం": ["వ్యాపారం", "బిజినెస్", "స్టాక్ మార్కెట్", "సెన్సెక్స్", "నిఫ్టీ", "బంగారం", "బ్యాంక్"],
    "విద్య": ["విద్యార్థులు", "పరీక్షలు", "ఫలితాలు", "ఇంటర్", "టెన్త్", "విద్యాశాఖ", "నోటిఫికేషన్", "ఉద్యోగాలు"],
    "సాంకేతికత": ["టెక్నాలజీ", "సాంకేతిక", "మొబైల్", "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్"],
    "క్రైమ్": ["పోలీసులు", "అరెస్ట్", "నేరం", "దొంగతనం", "మోసం", "కేసు", "సైబర్"],
    "ఇతర వార్తలు": []
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def load_news():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return [item for item in data if isinstance(item, dict) and item.get("title")]
    except Exception as e:
        print(f"JSON ERROR: {e}")
        backup_file = f"{DATA_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DATA_FILE, backup_file)
        return []

def save_news(news_list):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, DATA_FILE)
    print(f"✅ Saved {len(news_list)} total articles to {DATA_FILE}")

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

def detect_category(text, default_cat):
    for cat, keywords in CATEGORY_RULES.items():
        if any(kw in text for kw in keywords):
            return cat
    return default_cat

def clean_image_url(raw_url, base_url="", trusted=False):
    if not raw_url:
        return ""
    url = html.unescape(str(raw_url).strip()).strip("\"'()<>")
    if not url or url.startswith("data:"):
        return ""
    url = urllib.parse.urljoin(base_url, url)
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    lower_full = url.lower()
    lower_path = parsed.path.lower()
    if any(pat in lower_full for pat in BAD_IMAGE_PATTERNS) or lower_path.endswith(".svg"):
        return ""
    return parsed._replace(fragment="").geturl()

def extract_article_links(crawl_result, base_url):
    """Sakshi, NTV, TV9, V6, 10TV అన్ని సైట్‌ల నుండి ఆర్టికల్ URLs ను ఫిల్టర్ చేస్తుంది."""
    links = []
    internal_links = crawl_result.links.get("internal", [])
    base_domain = urllib.parse.urlparse(base_url).netloc.replace("www.", "")

    skip_words = [
        "/category/", "/tag/", "/tags/", "/author/", "/video", "/videos",
        "/photo", "/photos", "/live-tv", "/epaper", "/gallery", "/web-stories",
        "/about", "/contact", "/privacy", "/terms"
    ]

    for link_obj in internal_links:
        href = link_obj.get("href", "")
        if not href:
            continue

        full_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full_url)
        link_domain = parsed.netloc.replace("www.", "")

        # అదే వెబ్‌సైట్ డొమైన్ అయి ఉండాలి
        if link_domain != base_domain:
            continue

        path = parsed.path.rstrip("/")
        if not path or full_url.rstrip("/") == base_url.rstrip("/"):
            continue

        # కేటగిరీ, వీడియో, ఫోటో పేజీలను వదిలేయండి
        if any(skip in path.lower() for skip in skip_words):
            continue

        # అసలు ఆర్టికల్ లింక్‌లకు సాధారణంగా పొడవైన స్లగ్ (slug) లేదా ID ఉంటుంది
        slug = path.split("/")[-1]
        if len(slug) < 15:
            continue

        if full_url not in links:
            links.append(full_url)
        if len(links) >= MAX_LINKS_PER_PAGE:
            break

    return links

def extract_clean_content(markdown_text):
    """Markdown నుండి మెనూలు, యాడ్స్ తీసేసి అసలు వార్త పేరాలను మాత్రమే తీసుకుంటుంది."""
    lines = markdown_text.split("\n")
    content_lines = []
    for line in lines:
        line = line.strip()
        # చిన్న లింక్‌లు, మెనూ ఐటమ్స్, ఇమేజ్ ట్యాగ్‌లను స్కిప్ చేయండి
        if not line or line.startswith(("*", "-", "#", "!", "[", "|")):
            continue
        if len(line) < 45:
            continue
        content_lines.append(line)
    return "\n\n".join(content_lines)

# ==========================================
# MAIN CRAWLER LOGIC
# ==========================================

async def scrape_news():
    existing_news = load_news()
    existing_urls = {item.get("url") for item in existing_news if item.get("url")}
    new_articles = []

    browser_cfg = BrowserConfig(
        headless=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Sakshi, TV9 వంటి భారీ సైట్‌లు లోడ్ అవ్వడానికి 45 సెకన్ల టైమ్-అవుట్
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        delay_before_return_html=2.5,
        page_timeout=45000,
        word_count_threshold=15,
        remove_overlay_elements=True
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for site in DIRECT_WEBSITES:
            print(f"\n--- Checking Category [{site['source']}]: {site['url']} ---")
            try:
                cat_result = await crawler.arun(url=site["url"], config=run_cfg)
            except Exception as e:
                print(f"Error loading category {site['url']}: {e}")
                continue

            if not cat_result.success:
                print(f"Failed to load category: {site['url']}")
                continue

            article_urls = extract_article_links(cat_result, site["url"])
            print(f"Found {len(article_urls)} article links.")

            added_from_site = 0
            for art_url in article_urls:
                if art_url in existing_urls:
                    continue
                if added_from_site >= MAX_NEW_ITEMS_PER_RUN:
                    break

