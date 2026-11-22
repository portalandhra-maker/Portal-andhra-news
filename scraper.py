import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

DATA_FILE = "data/news.json"
MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 5

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex", "betting", "casino", "gambling",
    "ushodaya", "prosecuted", "georgia-fulton",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

# NTV, TV9, ABN (Andhra Jyothy), Sakshi, 10TV ఆధారిత RSS ఫీడ్స్
RSS_FEEDS = [
    {
        "url": "https://news.google.com/rss/search?q=site:ntvtelugu.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:tv9telugu.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:andhrajyothy.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:sakshi.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:10tv.in+when:1d&hl=te&gl=IN&ceid=IN:te",
        "default_cat": "సినిమా"
    }
]


def fetch_rss_items(feed_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(feed_url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    items = []
    for item in root.findall(".//item")[:6]:
        raw_title = (item.findtext("title") or "").strip()
        clean_title = re.sub(r"\s+-\s+[^-]+$", "", raw_title).strip()

        link = (item.findtext("link") or "").strip()
        desc_html = item.findtext("description") or ""
        desc_text = html.unescape(re.sub(r"<[^>]+>", " ", desc_html))
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        desc_text = re.sub(r"\s+-\s+[^-]+$", "", desc_text).strip()

        if clean_title and link:
            items.append({
                "title": clean_title,
                "link": link,
                "description": desc_text
            })
    return items


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


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            news_list = json.load(f)
    else:
        news_list = []

    news_list = clean_old_news(news_list)
    added = 0

    for feed in RSS_FEEDS:
        if added >= MAX_NEW_ITEMS_PER_RUN:
            break
        try:
            entries = fetch_rss_items(feed["url"])
        except Exception as e:
            print(f"RSS error ({feed['default_cat']}): {e}")
            continue

        for entry in entries:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            title = entry["title"]
            if len(title) < 15 or not is_adsense_safe(title):
                continue
            if is_duplicate(news_list, title, entry["link"]):
                continue

            summary = entry["description"] if len(entry["description"]) > 30 else title
            content = f"{summary}\n\nఈ అంశానికి సంబంధించిన తాజా వివరాలు మరియు పరిణామాలు కొనసాగుతున్నాయి."

            ist = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist)

            news_list.insert(0, {
                "id": f"{int(time.time())}_{added + 1}",
                "title": title,
                "category": feed["default_cat"],
                "summary": summary[:220],
                "content": content,
                "image": "",
                "sourceUrl": entry["link"],
                "publishedAt": now_ist.strftime("%d %b %Y, %I:%M %p"),
                "createdAt": datetime.now(timezone.utc).isoformat()
            })
            added += 1
            time.sleep(0.5)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"Done. Added {added} new articles. Total: {len(news_list)}")


if __name__ == "__main__":
    main()
