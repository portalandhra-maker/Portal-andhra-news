import os
import re
import json
import time
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from crawl4ai import AsyncWebCrawler

JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
DATA_FILE = "data/news.json"
MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 3

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex", "betting", "casino", "gambling",
    "hatya", "aatmahatya", "judam", "ashleela",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

TARGET_PAGES = [
    {"url": "https://www.eenadu.net/andhra-pradesh", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.eenadu.net/telangana", "default_cat": "తెలంగాణ"},
    {"url": "https://www.eenadu.net/movies", "default_cat": "సినిమా"}
]


def fetch_via_jina(target_url):
    jina_url = f"https://r.jina.ai/{target_url}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Return-Format": "markdown"
    }
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"

    req = urllib.request.Request(jina_url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


async def fetch_markdown(crawler, target_url):
    # 1. ముందుగా Crawl4AI తో ప్రయత్నించడం
    try:
        result = await crawler.arun(url=target_url)
        if result and result.success and result.markdown and len(result.markdown.strip()) > 200:
            return result.markdown
    except Exception as e:
        print(f"Crawl4AI error ({target_url}): {e}")

    # 2. Crawl4AI విఫలమైతే Jina fallback
    try:
        print(f"Falling back to Jina for: {target_url}")
        return fetch_via_jina(target_url)
    except Exception as e:
        print(f"Jina fallback error ({target_url}): {e}")
        return ""


def extract_links(md_text, page_url, default_cat):
    candidates = []
    base_domain = urllib.parse.urlparse(page_url).netloc

    matches = re.findall(r"\[([^\]]{25,160})\]\((https?://[^\s)]+)\)", md_text or "")
    for title, href in matches:
        title = re.sub(r"\s+", " ", title).strip()
        if urllib.parse.urlparse(href).netloc != base_domain:
            continue
        if href.rstrip("/") == page_url.rstrip("/"):
            continue
        if any(ext in href.lower() for ext in [".jpg", ".png", ".webp", "/video", "/photos"]):
            continue

        candidates.append({
            "title": title,
            "link": href,
            "default_cat": default_cat
        })

    seen = set()
    unique = []
    for c in candidates:
        if c["link"] not in seen:
            seen.add(c["link"])
            unique.append(c)
    return unique[:6]


def clean_article_text(md_text):
    lines = [line.strip() for line in (md_text or "").splitlines()]
    clean_lines = [
        ln for ln in lines
        if len(ln) > 45 and not ln.startswith("![") and not ln.startswith("[") and not ln.startswith("#") and "http" not in ln
    ]
    return "\n".join(clean_lines[:6])[:1800]


def is_adsense_safe(text):
    lower = (text or "").lower()
    return not any(word.lower() in lower for word in BLOCKED_KEYWORDS)


def normalize_title(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def is_duplicate(existing_list, title, link):
    norm_new = normalize_title(title)
    for item in existing_list:
        if link and item.get("sourceUrl") == link:
            return True
        norm_old = normalize_title(item.get("title", ""))
        if norm_new and norm_old and (norm_new == norm_old or norm_new in norm_old or norm_old in norm_new):
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

    news_list = clean_old_news(news_list)
    added = 0

    async with AsyncWebCrawler() as crawler:
        for target in TARGET_PAGES:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            page_md = await fetch_markdown(crawler, target["url"])
            links = extract_links(page_md, target["url"], target["default_cat"])

            for item in links:
                if added >= MAX_NEW_ITEMS_PER_RUN:
                    break
                if not is_adsense_safe(item["title"]) or is_duplicate(news_list, item["title"], item["link"]):
                    continue

                art_md = await fetch_markdown(crawler, item["link"])
                body = clean_article_text(art_md)
                if len(body) < 100 or not is_adsense_safe(body):
                    continue

                summary_text = body[:220].rsplit(" ", 1)[0] + "..."
                ist = timezone(timedelta(hours=5, minutes=30))
                now_ist = datetime.now(ist)

                news_list.insert(0, {
                    "id": f"{int(time.time())}_{added + 1}",
                    "title": item["title"],
                    "category": target["default_cat"],
                    "summary": summary_text,
                    "content": body,
                    "image": "",
                    "sourceUrl": item["link"],
                    "publishedAt": now_ist.strftime("%d %b %Y, %I:%M %p"),
                    "createdAt": datetime.now(timezone.utc).isoformat()
                })
                added += 1
                await asyncio.sleep(1)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"Done. Added {added} new articles. Total: {len(news_list)}")


if __name__ == "__main__":
    asyncio.run(main())
