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

DATA_FILE = "data/news.json"

JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()
XAI_API_KEY = os.environ.get("XAI_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

CRAWL4AI_LLM_PROVIDER = os.environ.get("CRAWL4AI_LLM_PROVIDER", "").strip()
CRAWL4AI_LLM_API_KEY = os.environ.get("CRAWL4AI_LLM_API_KEY", "").strip()

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


# =====================================================
# 1. READ -> JINA READER
# =====================================================

def read_via_jina(url):
    """Jina Reader ద్వారా పేజీ / ఆర్టికల్ చదవడం"""
    if not url:
        return ""
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
        print(f"Jina read error ({url}): {e}")
        return ""


def fetch_html_fallback(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"HTML fallback error ({url}): {e}")
        return ""


def extract_links_from_jina(section_url):
    md_text = read_via_jina(section_url)
    base_domain = urllib.parse.urlparse(section_url).netloc
    candidates = []

    if md_text:
        for title, href in re.findall(r"\[([^\]]{20,180})\]\((https?://[^\s)]+)\)", md_text):
            parsed = urllib.parse.urlparse(href)
            if parsed.netloc != base_domain:
                continue
            if href.rstrip("/") == section_url.rstrip("/"):
                continue
            if any(skip in href.lower() for skip in [
                "/category/", "/tag/", "/author/", "/video", "/videos",
                "/photo", "/photos", "/gallery", "/web-stories", "login", "privacy", "about"
            ]):
                continue
            clean_t = re.sub(r"\s+", " ", title).strip()
            if is_adsense_safe(clean_t):
                candidates.append({"title": clean_t, "url": href})

    if not candidates:
        raw_html = fetch_html_fallback(section_url)
        if raw_html:
            for href, inner_html in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html, flags=re.S | re.I):
                full_url = urllib.parse.urljoin(section_url, html.unescape(href.strip()))
                parsed = urllib.parse.urlparse(full_url)
                if parsed.netloc == base_domain and full_url.rstrip("/") != section_url.rstrip("/"):
                    path_parts = [p for p in parsed.path.split("/") if p]
                    if len(path_parts) >= 2 or re.search(r"-\d{4,}", parsed.path):
                        clean_t = html.unescape(re.sub(r"<[^>]+>", " ", inner_html))
                        clean_t = re.sub(r"\s+", " ", clean_t).strip()
                        if 20 <= len(clean_t) <= 180 and is_adsense_safe(clean_t):
                            candidates.append({"title": clean_t, "url": full_url})

    seen = set()
    unique = []
    for c in candidates:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    return unique[:MAX_LINKS_PER_PAGE]


def read_article_via_jina(article_url, fallback_title):
    md_text = read_via_jina(article_url)
    title = fallback_title
    image_url = ""
    paragraphs = []

    if md_text:
        h1_match = re.search(r"^#\s+(.+)$", md_text, flags=re.M)
        if h1_match:
            h1_txt = re.sub(r"\s+", " ", h1_match.group(1)).strip()
            if len(h1_txt) >= 15:
                title = h1_txt

        for raw_img in re.findall(r"!\[[^\]]*\]\(([^\s)]+)", md_text):
            cleaned = clean_image_url(raw_img, article_url)
            if cleaned:
                image_url = cleaned
                break

        lines = [
            re.sub(r"\s+", " ", ln.strip()).strip()
            for ln in md_text.splitlines()
            if len(ln.strip()) >= 50
            and not ln.strip().startswith(("![", "[", "#", "*", "-", ">"))
            and "http" not in ln.lower()
        ]
        paragraphs = lines[:8]

    content = "\n\n".join(paragraphs)[:2500]
    return title, content, image_url


# =====================================================
# 2. REWRITE -> CRAWL4AI (WITH GROK/GEMINI FALLBACK)
# =====================================================

def build_rewrite_prompt(raw_title, raw_content, default_cat):
    return f"""
మీరు 'Portal Andhra' తెలుగు న్యూస్ పోర్టల్ ఎడిటర్.
కింద ఇచ్చిన సమాచారం ఆధారంగా ఏ వెబ్‌సైట్ నుండి కూడా నేరుగా కాపీ చేయకుండా, స్పష్టమైన, సహజమైన సొంత తెలుగులో వార్త కథనం రాయండి.
గూగుల్ యాడ్‌సెన్స్ పాలసీలకు అనుగుణంగా నిష్పాక్షికంగా, సున్నితమైన హింస/అశ్లీల/బెట్టింగ్ అంశాలు లేకుండా రాయండి.

విభాగాలు: ఆంధ్రప్రదేశ్, తెలంగాణ, జాతీయ వార్తలు, రాజకీయాలు, సినిమా, క్రీడలు, వ్యాపారం, విద్య, సాంకేతికత, క్రైమ్, ఇతర వార్తలు (డిఫాల్ట్: {default_cat})

మూల శీర్షిక: {raw_title}
మూల సమాచారం: {raw_content[:1800]}

JSON మాత్రమే రిటర్న్ చేయండి:
{{
  "title": "సొంత తెలుగు శీర్షిక",
  "category": "విభాగం పేరు",
  "summary": "2 వాక్యాల సారాంశం",
  "content": "3-4 పేరాల పూర్తి తెలుగు కథనం (పేరాల మధ్య \\n\\n వాడండి)"
}}
""".strip()


def parse_json_loose(text):
    if not text:
        return None
    cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.S).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def rewrite_with_crawl4ai(raw_title, raw_content, default_cat):
    """Crawl4AI LLMExtractionStrategy ద్వారా సొంత తెలుగులో రీరైట్ చేయడం"""
    prompt = build_rewrite_prompt(raw_title, raw_content, default_cat)

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, LLMConfig
        from crawl4ai.extraction_strategy import LLMExtractionStrategy

        provider = CRAWL4AI_LLM_PROVIDER or (
            "xai/" + GROK_MODEL if XAI_API_KEY else (
                "gemini/" + GEMINI_MODEL if GEMINI_API_KEY else ""
            )
        )
        api_key = CRAWL4AI_LLM_API_KEY or XAI_API_KEY or GEMINI_API_KEY

        if not provider:
            return None

        llm_cfg = LLMConfig(provider=provider, api_token=api_key or None)
        strategy = LLMExtractionStrategy(
            llm_config=llm_cfg,
            instruction=prompt,
            extraction_type="text",
            apply_chunking=False
        )
        run_cfg = CrawlerRunConfig(extraction_strategy=strategy)

        # Jina తో చదివిన టెక్స్ట్‌ను data URL ద్వారా Crawl4AI కి ఇచ్చి రీరైట్ చేయించడం
        safe_b64 = urllib.parse.quote(f"<html><body><article><p>{html.escape(raw_content[:1800])}</p></article></body></html>")
        data_url = f"data:text/html;charset=utf-8,{safe_b64}"

        async with AsyncWebCrawler() as crawler:
            res = await crawler.arun(url=data_url, config=run_cfg)
            if res and res.success and res.extracted_content:
                parsed = parse_json_loose(res.extracted_content)
                if isinstance(parsed, list) and parsed:
                    parsed = parsed[0]
                if isinstance(parsed, dict) and parsed.get("title") and parsed.get("content"):
                    return parsed
    except Exception as e:
        print(f"Crawl4AI rewrite fallback: {e}")

    # Direct Grok / Gemini API fallback
    if XAI_API_KEY:
        try:
            payload = json.dumps({
                "model": GROK_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful Telugu news editor returning valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.x.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "User-Agent": "Mozilla/5.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                parsed = parse_json_loose(data["choices"][0]["message"]["content"])
                if parsed and parsed.get("title") and parsed.get("content"):
                    return parsed
        except Exception as e:
            print(f"Grok rewrite failed: {e}")

    if GEMINI_API_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"}
        }).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    parsed = parse_json_loose(data["candidates"][0]["content"]["parts"][0]["text"])
                    if parsed and parsed.get("title") and parsed.get("content"):
                        return parsed
            except Exception as e:
                print(f"Gemini rewrite attempt {attempt + 1} failed: {e}")
                time.sleep(15)

    return None


def detect_category(title, description, default_cat):
    text = f"{title} {description}".lower()
    scores = {}
    for category, keywords in CATEGORY_RULES.items():
        if not keywords:
            continue
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[category] = score
    return max(scores, key=scores.get) if scores else default_cat


def normalize_title(text):
    text = re.sub(r"[^\w\s]", "", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def is_duplicate(existing_list, title, link):
    norm_new = normalize_title(title)
    for item in existing_list:
        if link and link == item.get("sourceUrl", ""):
            return True
        norm_old = normalize_title(item.get("title", ""))
        if not norm_new or not norm_old:
            continue
        if norm_new == norm_old:
            return True
        if min(len(norm_new), len(norm_old)) >= 20:
            if SequenceMatcher(None, norm_new, norm_old).ratio() >= 0.90:
                return True
    return False


def clean_old_news(items):
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    kept = []
    for item in items:
        created = item.get("createdAt")
        if not created:
            kept.append(item)
            continue
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                kept.append(item)
        except Exception:
            kept.append(item)
    return kept


async def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            news_list = json.load(f)
    else:
        news_list = []

    old_total = len(news_list)
    news_list = clean_old_news(news_list)
    removed = old_total - len(news_list)
    added = 0

    for site in DIRECT_WEBSITES:
        if added >= MAX_NEW_ITEMS_PER_RUN:
            break

        # 1. Jina ద్వారా సెక్షన్ పేజీ నుండి లింక్స్ చదవడం
        links = extract_links_from_jina(site["url"])

        for cand in links:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            if is_duplicate(news_list, cand["title"], cand["url"]):
                continue

            # 2. Jina ద్వారా ఆర్టికల్ కంటెంట్ + ఇమేజ్ చదవడం
            title, raw_content, image_url = read_article_via_jina(cand["url"], cand["title"])
            if len(raw_content) < 120:
                continue
            if not is_adsense_safe(f"{title} {raw_content}"):
                continue

            # 3. Crawl4AI ద్వారా రీరైట్ చేయడం
            rewritten = await rewrite_with_crawl4ai(title, raw_content, site["default_cat"])
            if rewritten:
                final_title = str(rewritten.get("title") or title).strip()
                final_content = str(rewritten.get("content") or raw_content).strip()
                final_summary = str(rewritten.get("summary") or "").strip()
                cat_cand = str(rewritten.get("category") or "").strip()
                final_cat = cat_cand if cat_cand in CATEGORY_RULES else detect_category(
                    final_title, final_content, site["default_cat"]
                )
                if not final_summary:
                    final_summary = final_content[:220].rsplit(" ", 1)[0] + "..."
            else:
                final_title = title
                final_content = raw_content
                final_summary = raw_content[:220].rsplit(" ", 1)[0] + "..."
                final_cat = detect_category(final_title, final_content, site["default_cat"])

            if not is_adsense_safe(f"{final_title} {final_summary} {final_content}"):
                continue
            if is_duplicate(news_list, final_title, cand["url"]):
                continue

            now_ist = datetime.now(IST)
            news_list.insert(0, {
                "id": f"{int(time.time())}_{added + 1}",
                "title": final_title,
                "category": final_cat,
                "summary": final_summary[:240],
                "content": final_content,
                "image": image_url,
                "sourceUrl": cand["url"],
                "sourceName": site["source"],
                "publishedAt": now_ist.strftime("%d %b %Y, %I:%M %p"),
                "createdAt": datetime.now(timezone.utc).isoformat()
            })
            added += 1
            await asyncio.sleep(1.2)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"Done. Added {added} new articles, removed {removed} old. Total: {len(news_list)}")


if __name__ == "__main__":
    asyncio.run(main())
