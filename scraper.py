import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

DATA_FILE = "data/news.json"
IST = timezone(timedelta(hours=5, minutes=30))

# Google News Telugu RSS feeds (AP, Telangana, & Top Telugu)
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


def fetch_rss_items(feed_url, category):
    req = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    results = []

    for item in root.findall("./channel/item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source_name = (source_el.text or "Google News").strip() if source_el is not None else "Google News"

        # Title chivarlo " - Source Name" unte neat ga clean cheddam
        title = raw_title.rsplit(" - ", 1)[0].strip() if " - " in raw_title else raw_title

        if not title or not link:
            continue

        results.append({
            "title": title,
            "content": f"{title} — పూర్తి వివరాల కోసం మూల వార్తను చూడండి.",
            "category": category,
            "source": source_name,
            "url": link,
            "image": "",
            "published_at": datetime.now(IST).isoformat(),
        })

    return results


def main():
    existing = load_news()
    seen_titles = {x.get("title") for x in existing if x.get("title")}
    added = []

    for feed in RSS_FEEDS:
        try:
