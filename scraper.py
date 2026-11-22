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
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "te-IN,te;q=0.9,en;q=0.8"
}

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
        "ఆంధ్రప్రదేశ్", "ఏపీ", "అమరావతి",
        "విజయవాడ", "గుంటూరు", "విశాఖపట్నం",
        "తిరుపతి", "కర్నూలు", "నెల్లూరు"
    ],
    "తెలంగాణ": [
        "తెలంగాణ", "హైదరాబాద్", "వరంగల్",
        "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్"
    ],
    "జాతీయ వార్తలు": [
        "భారతదేశం", "దేశవ్యాప్తంగా", "న్యూఢిల్లీ",
        "ప్రధాని", "మోదీ", "సుప్రీంకోర్టు"
    ],
    "రాజకీయాలు": [
        "ఎన్నికలు", "రాజకీయాలు", "పార్టీ",
        "ఎమ్మెల్యే", "ఎంపీ", "మంత్రి",
        "అసెంబ్లీ", "చంద్రబాబు", "జగన్",
        "రేవంత్", "పవన్"
    ],
    "సినిమా": [
        "సినిమా", "సినీ", "హీరో", "హీరోయిన్",
        "దర్శకుడు", "ట్రైలర్", "టీజర్",
        "టాలీవుడ్", "బాక్సాఫీస్", "మూవీ"
    ],
    "క్రీడలు": [
        "క్రికెట్", "ఫుట్‌బాల్", "ఐపీఎల్",
        "టీమిండియా", "ప్రపంచకప్", "మ్యాచ్"
    ],
    "వ్యాపారం": [
        "వ్యాపారం", "బిజినెస్", "స్టాక్ మార్కెట్",
        "సెన్సెక్స్", "నిఫ్టీ", "బంగారం", "బ్యాంక్"
    ],
    "విద్య": [
        "విద్యార్థులు", "పరీక్షలు", "ఫలితాలు",
        "ఇంటర్", "టెన్త్", "విద్యాశాఖ",
        "నోటిఫికేషన్", "ఉద్యోగాలు"
    ],
    "సాంకేతికత": [
        "టెక్నాలజీ", "సాంకేతిక", "మొబైల్",
        "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్"
    ],
    "క్రైమ్": [
        "పోలీసులు", "అరెస్ట్", "నేరం",
        "దొంగతనం", "మోసం", "కేసు", "సైబర్"
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

    dim_match = re.search(
        r"(?:^|[^a-z0-9])(\d{1,3})x(\d{1,3})(?:[^a-z0-9]|$)",
        lower_path
    )

    if dim_match:
        w, h = int(dim_match.group(1)), int(dim_match.group(2))
        if w < 180 or h < 120:
            return ""

    qs = urllib.parse.parse_qs(parsed.query)

    for w_key in ("w", "width"):
        if w_key in qs:
            try:
                val = int(re.sub(r"\D", "", qs[w_key][0]) or 0)
                if val < 180:
                    return ""
            except Exception:
                pass

    has_valid_ext = lower_path.endswith(VALID_IMAGE_EXTS)

    img_paths = [
        "/image", "/images", "/img", "/photo",
        "/photos", "/media", "/upload", "/thumb"
    ]

    looks_like_img = any(k in lower_path for k in img_paths)

    if not (has_valid_ext or looks_like_img):
        return ""

    drop_keys = {
        "t", "ts", "v", "ver", "cache",
        "utm_source", "utm_medium", "utm_campaign"
    }

    clean_qs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=False
        )
        if k.lower() not in drop_keys
    ]

    cleaned = parsed._replace(
        query=urllib.parse.urlencode(clean_qs),
        fragment=""
    )

    return urllib.parse.urlunparse(cleaned)


def read_via_jina(url):
    if not url:
        return ""

    jina_url = "https://r.jina.ai/" + url

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Return-Format": "markdown"
    }

    if JINA_API_KEY:
        headers["Authorization"] = "Bearer " + JINA_API_KEY

    try:
        req = urllib.request.Request(jina_url, headers=headers)

        with urllib.request.urlopen(
            req, timeout=REQUEST_TIMEOUT
        ) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    except Exception as e:
        print(f"Jina read error ({url}): {e}")
        return ""


def fetch_html_fallback(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)

        with urllib.request.urlopen(
            req, timeout=REQUEST_TIMEOUT
        ) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    except Exception as e:
        print(f"HTML fallback error ({url}): {e}")
        return ""


def should_skip_link(href):
    low = href.lower()

    bad_parts = [
        "/category/", "/tag/", "/author/", "/video",
        "/videos", "/photo", "/photos", "/gallery",
        "/web-stories", "login", "privacy", "about"
    ]

    return any(p in low for p in bad_parts)


def extract_links_from_jina(section_url):
    md_text = read_via_jina(section_url)

    base_domain = urllib.parse.urlparse(section_url).netloc
    candidates = []

    if md_text:
        pattern = r"\[([^\]]{20,180})\]\((https?://[^\s)]+)\)"

        for title, href in re.findall(pattern, md_text):
            parsed = urllib.parse.urlparse(href)

            same_host = parsed.netloc == base_domain
            not_self = href.rstrip("/") != section_url.rstrip("/")

            if not (same_host and not_self):
                continue

            if should_skip_link(href):
                continue

            clean_t = re.sub(r"\s+", " ", title).strip()

            if is_adsense_safe(clean_t):
                candidates.append({
                    "title": clean_t,
                    "url": href
                })

    if not candidates:
        raw_html = fetch_html_fallback(section_url)

        if raw_html:
            a_pat = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'

            for href, inner in re.findall(
                a_pat, raw_html, flags=re.S | re.I
            ):
                full_url = urllib.parse.urljoin(
                    section_url, html.unescape(href.strip())
                )

                parsed = urllib.parse.urlparse(full_url)

                if parsed.netloc != base_domain:
                    continue

                if full_url.rstrip("/") == section_url.rstrip("/"):
                    continue

                parts = [p for p in parsed.path.split("/") if p]

                has_id = bool(re.search(r"-\d{4,}", parsed.path))

                if len(parts) < 2 and not has_id:
                    continue

                clean_t = html.unescape(
                    re.sub(r"<[^>]+>", " ", inner)
                )

                clean_t = re.sub(r"\s+", " ", clean_t).strip()

                if 20 <= len(clean_t) <= 180 and is_adsense_safe(clean_t):
                    candidates.append({
                        "title": clean_t,
                        "url": full_url
                    })

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
        h1_match = re.search(
            r"^#\s+(.+)$", md_text, flags=re.M
        )

        if h1_match:
            h1_txt = re.sub(
                r"\s+", " ", h1_match.group(1)
            ).strip()

            if len(h1_txt) >= 15:
                title = h1_txt

        img_pat = r"!\[[^\]]*\]\(([^\s)]+)"

        for raw_img in re.findall(img_pat, md_text):
            cleaned = clean_image_url(raw_img, article_url)

            if cleaned:
                image_url = cleaned
                break

        skip_prefix = ("![", "[", "#", "*", "-", ">")

        for ln in md_text.splitlines():
            s = re.sub(r"\s+", " ", ln.strip()).strip()

            if len(s) < 50:
                continue

            if s.startswith(skip_prefix):
                continue

            if "http" in s.lower():
                continue

            paragraphs.append(s)

    content = "\n\n".join(paragraphs[:8])[:2500]

    return title, content, image_url


def build_rewrite_prompt(raw_title, raw_content, default_cat):
    return (
        "Rewrite this Telugu news item into original, clear, "
        "AdSense-safe Telugu with title, category, summary, "
        f"and content.\nDefault category: {default_cat}\n"
        f"Title: {raw_title}\n"
        f"Content: {raw_content[:1800]}\n"
        'Return JSON only: {"title":"","category":"",'
        '"summary":"","content":""}'
    )


def parse_json_loose(text):
    if not text:
        return None

    cleaned = re.sub(
        r"^```json\s*|\s*```$", "",
        text.strip(), flags=re.S
    ).strip()

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


async def rewrite_with_crawl4ai(
    crawler, raw_title, raw_content, default_cat
):
    if not CRAWL4AI_LLM_PROVIDER:
        return None

    prompt = build_rewrite_prompt(
        raw_title, raw_content, default_cat
    )

    try:
        from crawl4ai import CrawlerRunConfig, LLMConfig
        from crawl4ai.extraction_strategy import LLMExtractionStrategy

        llm_cfg = LLMConfig(
            provider=CRAWL4AI_LLM_PROVIDER,
            api_token=CRAWL4AI_LLM_API_KEY or None
        )

        strategy = LLMExtractionStrategy(
            llm_config=llm_cfg,
            instruction=prompt,
            extraction_type="text",
            apply_chunking=False
        )

        run_cfg = CrawlerRunConfig(
            extraction_strategy=strategy
        )

        escaped = html.escape(raw_content[:1800])

        raw_html = (
            "raw:<html><body><article><p>"
            + escaped
            + "</p></article></body></html>"
        )

        res = await crawler.arun(
            url=raw_html,
            config=run_cfg
        )

        if res and res.success and res.extracted_content:
            parsed = parse_json_loose(res.extracted_content)

            if isinstance(parsed, list) and parsed:
                parsed = parsed[0]

            if isinstance(parsed, dict):
                if parsed.get("title") and parsed.get("content"):
                    return parsed

    except Exception as e:
        print(f"Crawl4AI rewrite error: {e}")

    return None


def detect_category(title, description, default_cat):
    text = f"{title} {description}".lower()

    scores = {}

    for category, keywords in CATEGORY_RULES.items():
        if not keywords:
            continue

        score = sum(
            1 for kw in keywords if kw.lower() in text
        )

        if score > 0:
            scores[category] = score

    return max(scores, key=scores.get) if scores else default_cat


def normalize_title(text):
    text = re.sub(
        r"[^\w\s]", "", (text or "").lower()
    )

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
            ratio = SequenceMatcher(
                None, norm_new, norm_old
            ).ratio()

            if ratio >= 0.90:
                return True

    return False


def clean_old_news(items):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=MAX_AGE_DAYS)
    )

    kept = []

    for item in items:
        created = item.get("createdAt")

        if not created:
            kept.append(item)
            continue

        try:
            dt = datetime.fromisoformat(
                created.replace("Z", "+00:00")
            )

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

    async with AsyncWebCrawler() as crawler:

        for site in DIRECT_WEBSITES:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            links = extract_links_from_jina(site["url"])

            for cand in links:
                if added >= MAX_NEW_ITEMS_PER_RUN:
                    break

                if is_duplicate(
                    news_list,
                    cand["title"],
                    cand["url"]
                ):
                    continue

                title, raw_content, image_url = read_article_via_jina(
                    cand["url"],
                    cand["title"]
                )

                if len(raw_content) < 120:
                    continue

                if not is_adsense_safe(
                    f"{title} {raw_content}"
                ):
                    continue

                rewritten = await rewrite_with_crawl4ai(
                    crawler,
                    title,
                    raw_content,
                    site["default_cat"]
                )

                if rewritten:
                    final_title = str(
                        rewritten.get("title") or title
                    ).strip()

                    final_content = str(
                        rewritten.get("content") or raw_content
                    ).strip()

                    final_summary = str(
                        rewritten.get("summary") or ""
                    ).strip()

                    cat_cand = str(
                        rewritten.get("category") or ""
                    ).strip()

                    if cat_cand in CATEGORY_RULES:
                        final_cat = cat_cand
                    else:
                        final_cat = detect_category(
                            final_title,
                            final_content,
                            site["default_cat"]
                        )

                    if not final_summary:
                        final_summary = (
                            final_content[:220].rsplit(" ", 1)[0]
                            + "..."
                        )

                else:
                    final_title = title
                    final_content = raw_content

                    final_summary = (
                        raw_content[:220].rsplit(" ", 1)[0]
                        + "..."
                    )

                    final_cat = detect_category(
                        final_title,
                        final_content,
                        site["default_cat"]
                    )

                combo = (
                    f"{final_title} "
                    f"{final_summary} "
                    f"{final_content}"
                )

                if not is_adsense_safe(combo):
                    continue

                if is_duplicate(
                    news_list,
                    final_title,
                    cand["url"]
                ):
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
                    "publishedAt": now_ist.strftime(
                        "%d %b %Y, %I:%M %p"
                    ),
                    "createdAt": datetime.now(
                        timezone.utc
                    ).isoformat()
                })

                added += 1

                await asyncio.sleep(1)

    os.makedirs(
        os.path.dirname(DATA_FILE),
        exist_ok=True
    )

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            news_list,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Done. Added {added} new articles, "
        f"removed {removed} old. Total: {len(news_list)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
