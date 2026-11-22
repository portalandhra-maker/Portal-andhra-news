import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

DATA_FILE = "data/news.json"
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 5
MAX_ITEMS_PER_FEED = 6
REQUEST_TIMEOUT = 25

IST = timezone(timedelta(hours=5, minutes=30))

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex",
    "betting", "casino", "gambling",
    "ushodaya", "prosecuted", "georgia-fulton",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

# Web scraping (Jina) కి అనుకూలమైన సోర్సుల RSS ఫీడ్స్
RSS_FEEDS = [
    {
        "url": "https://news.google.com/rss/search?q=site:10tv.in+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "10TV",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:ntvtelugu.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "NTV Telugu",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:tv9telugu.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "TV9 Telugu",
        "default_cat": "తెలంగాణ"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:andhrajyothy.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "Andhra Jyothy",
        "default_cat": "ఆంధ్రప్రదేశ్"
    },
    {
        "url": "https://news.google.com/rss/search?q=site:sakshi.com+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "Sakshi",
        "default_cat": "తెలంగాణ"
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
        old_links = [item.get("sourceUrl", ""), item.get("originalSourceUrl", "")]
        if link and link in old_links:
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


def extract_original_url(link):
    try:
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        original = params.get("url", [""])[0]
        if original.startswith(("https://", "http://")):
            return original
    except Exception:
        pass
    return ""


def parse_rss_date(date_text):
    if date_text:
        try:
            dt = parsedate_to_datetime(date_text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")
        except Exception:
            pass
    return datetime.now(IST).strftime("%d %b %Y, %I:%M %p")


def fetch_rss_items(feed):
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(feed["url"], headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    items = []

    for item in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
        raw_title = (item.findtext("title") or "").strip()
        source_el = item.find("source")
        source_name = (source_el.text or feed["source"]).strip() if source_el is not None else feed["source"]
        source_home = source_el.attrib.get("url", "") if source_el is not None else ""

        clean_title = re.sub(r"\s+-\s+[^-]+$", "", raw_title).strip()
        link = (item.findtext("link") or "").strip()

        desc_html = item.findtext("description") or ""
        desc_text = html.unescape(re.sub(r"<[^>]+>", " ", desc_html))
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        desc_text = re.sub(r"\s+-\s+[^-]+$", "", desc_text).strip()

        pub_date = item.findtext("pubDate") or ""
        original_url = extract_original_url(link)

        if clean_title and link:
            items.append({
                "title": clean_title,
                "link": link,
                "original_url": original_url,
                "description": desc_text,
                "source_name": source_name,
                "source_home": source_home,
                "pub_date": pub_date
            })

    return items


def scrape_content_via_jina(target_url):
    """Jina Reader ద్వారా ఆర్టికల్ పూర్తి కంటెంట్ మరియు మొదటి ఇమేజ్ తీసుకోవడం"""
    if not target_url:
        return "", ""

    jina_url = f"https://r.jina.ai/{target_url}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Return-Format": "markdown"
    }
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"

    try:
        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            md_text = resp.read().decode("utf-8", errors="ignore")

        if not md_text or not is_adsense_safe(md_text):
            return "", ""

        # మొదటి ఇమేజ్ URL (వీలైతే)
        img_match = re.search(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", md_text)
        image_url = img_match.group(1) if img_match else ""
        if image_url and any(bad in image_url.lower() for bad in ["logo", "icon", "avatar", "sprite", "ads"]):
            image_url = ""

        lines = [ln.strip() for ln in md_text.splitlines()]
        clean_paragraphs = []
        for ln in lines:
            if (
                len(ln) >= 50
                and not ln.startswith("![")
                and not ln.startswith("[")
                and not ln.startswith("#")
                and not ln.startswith("*")
                and not ln.startswith("-")
                and "http" not in ln
            ):
                clean_line = re.sub(r"\s+", " ", ln).strip()
                clean_paragraphs.append(clean_line)

        full_content = "\n\n".join(clean_paragraphs[:8])[:2500]
        return full_content, image_url

    except Exception as e:
        print(f"Jina scrape error ({target_url}): {e}")
        return "", ""


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


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            news_list = json.load(f)
    else:
        news_list = []

    old_total = len(news_list)
    news_list = clean_old_news(news_list)
    removed = old_total - len(news_list)
    added = 0

    for feed in RSS_FEEDS:
        if added >= MAX_NEW_ITEMS_PER_RUN:
            break
        try:
            entries = fetch_rss_items(feed)
        except Exception as e:
            print(f"RSS error ({feed['source']}): {e}")
            continue

        for entry in entries:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            title = entry["title"]
            description = entry["description"]
            link = entry["link"]
            target_url = entry["original_url"] or link

            if len(title) < 15:
                continue
            if not is_adsense_safe(f"{title} {description}"):
                continue
            if is_duplicate(news_list, title, link):
                continue
            if entry["original_url"] and is_duplicate(news_list, title, entry["original_url"]):
                continue

            scraped_body, image_url = scrape_content_via_jina(target_url)

            if len(scraped_body) >= 120 and is_adsense_safe(scraped_body):
                content = scraped_body
                summary = scraped_body[:220].rsplit(" ", 1)[0] + "..."
            else:
                fallback = description if len(description) > 30 else title
                content = fallback
                summary = fallback[:220]

            category = detect_category(title, f"{description} {content}", feed["default_cat"])

            news_list.insert(0, {
                "id": f"{int(time.time())}_{added + 1}",
                "title": title,
                "category": category,
                "summary": summary,
                "content": content,
                "image": image_url,
                "sourceUrl": link,
                "originalSourceUrl": entry["original_url"],
                "sourceName": entry["source_name"],
                "sourceHome": entry["source_home"],
                "publishedAt": parse_rss_date(entry["pub_date"]),
                "createdAt": datetime.now(timezone.utc).isoformat()
            })
            added += 1
            time.sleep(1)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"Done. Added {added} new articles, removed {removed} old. Total: {len(news_list)}")


if __name__ == "__main__":
    main()
