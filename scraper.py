
import os
import re
import json
import time
import html
import shutil
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta


# =====================================================
# PORTAL ANDHRA - NEWS AGGREGATOR V2.0
# =====================================================

DATA_FILE = "data/news.json"
BACKUP_FILE = "data/news_backup.json"
LOG_FILE = "data/news_errors.log"

MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 5
MAX_ITEMS_PER_FEED = 6
REQUEST_TIMEOUT = 25

IST = timezone(timedelta(hours=5, minutes=30))


# =====================================================
# LOGGING
# =====================================================

os.makedirs("data", exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)


# =====================================================
# BLOCKED KEYWORDS
# =====================================================

BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn",
    "betting", "casino", "gambling",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్",
    "జూదం", "అశ్లీల"
]


def is_adsense_safe(text):

    text = (text or "").lower()

    for word in BLOCKED_KEYWORDS:

        word = word.lower()

        if re.search(r"^[a-z]+$", word):
            if re.search(r"\b" + re.escape(word) + r"\b", text):
                return False
        elif word in text:
            return False

    return True


# =====================================================
# RSS FEEDS
# =====================================================

RSS_FEEDS = [

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
        "default_cat": "ఆంధ్రప్రదేశ్"
    },

    {
        "url": "https://news.google.com/rss/search?q=site:10tv.in+when:1d&hl=te&gl=IN&ceid=IN:te",
        "source": "10TV",
        "default_cat": "ఇతర వార్తలు"
    }

]


# =====================================================
# SMART CATEGORY DETECTION (WITHOUT AI)
# =====================================================

CATEGORY_RULES = {

    "ఆంధ్రప్రదేశ్": [
        "ఆంధ్రప్రదేశ్", "ఆంధ్ర ప్రదేశ్", "ఏపీ",
        "అమరావతి", "విజయవాడ", "గుంటూరు",
        "విశాఖపట్నం", "విశాఖ", "తిరుపతి",
        "కర్నూలు", "కడప", "నెల్లూరు",
        "పల్నాడు", "ప్రకాశం", "చిత్తూరు",
        "అనంతపురం", "ఏలూరు", "కాకినాడ",
        "ముఖ్యమంత్రి", "చంద్రబాబు", "జగన్"
    ],

    "తెలంగాణ": [
        "తెలంగాణ", "హైదరాబాద్", "వరంగల్",
        "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్",
        "నల్గొండ", "సిద్దిపేట", "మహబూబ్ నగర్",
        "రేవంత్ రెడ్డి", "కెసిఆర్", "కేటీఆర్"
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
        "ప్రతిపక్షం", "అసెంబ్లీ", "ఎన్నికల సంఘం"
    ],

    "క్రైమ్": [
        "పోలీసులు", "అరెస్ట్", "నేరం",
        "దొంగతనం", "మోసం", "కేసు నమోదు",
        "విచారణ", "అక్రమాలు"
    ],

    "సినిమా": [
        "సినిమా", "సినీ", "హీరో", "హీరోయిన్",
        "దర్శకుడు", "ట్రైలర్", "టీజర్",
        "టాలీవుడ్", "బాలీవుడ్", "బాక్సాఫీస్",
        "పాట విడుదల", "సినీ పరిశ్రమ"
    ],

    "క్రీడలు": [
        "క్రికెట్", "ఫుట్‌బాల్", "కబడ్డీ",
        "ఐపీఎల్", "టీమిండియా", "విరాట్ కోహ్లీ",
        "రోహిత్ శర్మ", "ప్రపంచకప్", "ఒలింపిక్స్"
    ],

    "వ్యాపారం": [
        "వ్యాపారం", "స్టాక్ మార్కెట్", "షేర్ మార్కెట్",
        "సెన్సెక్స్", "నిఫ్టీ", "బంగారం ధర",
        "వెండి ధర", "ఆర్థిక వ్యవస్థ", "బడ్జెట్"
    ],

    "విద్య": [
        "విద్యార్థులు", "పరీక్షలు", "ఫలితాలు",
        "ఇంటర్", "టెన్త్", "విద్యాశాఖ",
        "నోటిఫికేషన్", "ఉద్యోగాలు", "రిక్రూట్మెంట్"
    ],

    "సాంకేతికత": [
        "టెక్నాలజీ", "సాంకేతిక", "మొబైల్",
        "స్మార్ట్ ఫోన్", "కృత్రిమ మేధస్సు",
        "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్"
    ]

}


def detect_category(title, description, default_cat):

    text = (title + " " + description).lower()

    scores = {}

    for category, keywords in CATEGORY_RULES.items():

        score = 0

        for keyword in keywords:

            if keyword.lower() in text:
                score += 1

        if score > 0:
            scores[category] = score

    if not scores:
        return default_cat

    return max(scores, key=scores.get)


# =====================================================
# TITLE NORMALIZATION
# =====================================================

def normalize_title(text):

    text = (text or "").lower()

    text = re.sub(r"[^\w\s]", "", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =====================================================
# DUPLICATE NEWS DETECTION
# =====================================================

def is_duplicate(existing_list, title, link):

    norm_new = normalize_title(title)

    for item in existing_list:

        old_links = [
            item.get("sourceUrl", ""),
            item.get("originalSourceUrl", "")
        ]

        if link and link in old_links:
            return True

        norm_old = normalize_title(item.get("title", ""))

        if not norm_new or not norm_old:
            continue

        if norm_new == norm_old:
            return True

        if min(len(norm_new), len(norm_old)) >= 20:

            similarity = SequenceMatcher(
                None,
                norm_new,
                norm_old
            ).ratio()

            if similarity >= 0.92:
                return True

    return False


# =====================================================
# GOOGLE NEWS ORIGINAL URL EXTRACTION
# =====================================================

def extract_original_url(link):

    try:

        parsed = urllib.parse.urlparse(link)

        params = urllib.parse.parse_qs(parsed.query)

        original = params.get("url", [""])[0]

        if original.startswith("https://") or original.startswith("http://"):
            return original

    except Exception:
        pass

    return ""


# =====================================================
# RSS DATE PARSING
# =====================================================

def parse_rss_date(date_text):

    if date_text:

        try:

            dt = parsedate_to_datetime(date_text)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(IST).strftime(
                "%d %b %Y, %I:%M %p"
            )

        except Exception:
            pass

    return datetime.now(IST).strftime(
        "%d %b %Y, %I:%M %p"
    )


# =====================================================
# RSS FETCH
# =====================================================

def fetch_rss_items(feed):

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PortalAndhra/2.0)"
    }

    req = urllib.request.Request(
        feed["url"],
        headers=headers
    )

    with urllib.request.urlopen(
        req,
        timeout=REQUEST_TIMEOUT
    ) as response:

        xml_data = response.read()

    root = ET.fromstring(xml_data)

    items = []

    for item in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:

        raw_title = (item.findtext("title") or "").strip()

        source_element = item.find("source")

        source_name = feed["source"]
        source_home = ""

        if source_element is not None:

            source_name = (
                source_element.text or feed["source"]
            ).strip()

            source_home = source_element.attrib.get("url", "")

        clean_title = raw_title

        if source_name:

            suffix = " - " + source_name

            if clean_title.endswith(suffix):
                clean_title = clean_title[:-len(suffix)].strip()

        link = (item.findtext("link") or "").strip()

        description_html = item.findtext("description") or ""

        description = html.unescape(
            re.sub(r"<[^>]+>", " ", description_html)
        )

        description = re.sub(
            r"\s+", " ", description
        ).strip()

        description = re.sub(
            r"\s+-\s+[^-]+$", "", description
        ).strip()

        pub_date = item.findtext("pubDate") or ""

        original_url = extract_original_url(link)

        if clean_title and link:

            items.append({

                "title": clean_title,

                "link": link,

                "original_url": original_url,

                "description": description,

                "source_name": source_name,

                "source_home": source_home,

                "pub_date": pub_date

            })

    return items


# =====================================================
# OLD NEWS CLEANUP
# =====================================================

def clean_old_news(items):

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=MAX_AGE_DAYS
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

            logging.warning(
                "Invalid createdAt: %s",
                created
            )

            kept.append(item)

    return kept


# =====================================================
# LOAD JSON SAFELY
# =====================================================

def load_news():

    if not os.path.exists(DATA_FILE):
        return []

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError("News JSON must contain a list")

        return data

    except Exception as error:

        logging.error(
            "JSON loading failed: %s",
            error
        )

        # Do not overwrite damaged original data.
        raise RuntimeError(
            "News JSON could not be loaded. Original file preserved."
        ) from error


# =====================================================
# SAFE JSON SAVE + BACKUP
# =====================================================

def save_news(news_list):

    temp_file = DATA_FILE + ".tmp"

    if os.path.exists(DATA_FILE):

        shutil.copy2(
            DATA_FILE,
            BACKUP_FILE
        )

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                news_list,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            DATA_FILE
        )

    finally:

        if os.path.exists(temp_file):
            os.remove(temp_file)


# =====================================================
# MAIN FUNCTION
# =====================================================

def main():

    news_list = load_news()

    old_total = len(news_list)

    news_list = clean_old_news(news_list)

    removed = old_total - len(news_list)

    added = 0

    logging.info("News collection started")

    for feed in RSS_FEEDS:

        if added >= MAX_NEW_ITEMS_PER_RUN:
            break

        try:

            entries = fetch_rss_items(feed)

        except Exception as error:

            logging.error(
                "RSS error - %s: %s",
                feed["source"],
                error
            )

            print(
                f"RSS error ({feed['source']}): {error}"
            )

            continue

        for entry in entries:

            if added >= MAX_NEW_ITEMS_PER_RUN:
                break

            title = entry["title"]

            description = entry["description"]

            link = entry["link"]

            if len(title) < 15:
                continue

            # Check both headline and description.
            if not is_adsense_safe(title + " " + description):
                continue

            if is_duplicate(
                news_list,
                title,
                link
            ):
                continue

            if entry["original_url"]:

                if is_duplicate(
                    news_list,
                    title,
                    entry["original_url"]
                ):
                    continue

            summary = (
                description
                if len(description) > 30
                else title
            )

            category = detect_category(
                title,
                description,
                feed["default_cat"]
            )

            now_ist = datetime.now(IST)

            now_utc = datetime.now(timezone.utc)

            news_item = {

                "id": f"{int(time.time())}_{added + 1}",

                "title": title,

                "category": category,

                "summary": summary[:220],

                # No fabricated news content.
                "content": summary,

                "image": "",

                # Existing field retained for compatibility.
                "sourceUrl": link,

                # Additional source information.
                "originalSourceUrl": entry["original_url"],

                "sourceName": entry["source_name"],

                "sourceHome": entry["source_home"],

                "publishedAt": parse_rss_date(
                    entry["pub_date"]
                ),

                "createdAt": now_utc.isoformat()

            }

            news_list.insert(0, news_item)

            added += 1

            logging.info(
                "News added: %s | %s",
                category,
                title
            )

            time.sleep(0.5)

    # Save even when no new news is found,
    # so old news cleanup is applied.
    save_news(news_list)

    print("--------------------------------")
    print("PORTAL ANDHRA NEWS AGGREGATOR")
    print("--------------------------------")
    print(f"New News Added : {added}")
    print(f"Old News Removed : {removed}")
    print(f"Total News : {len(news_list)}")
    print("--------------------------------")

    logging.info(
        "Completed. Added=%s Removed=%s Total=%s",
        added,
        removed,
        len(news_list)
    )


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logging.exception(
            "Main execution failed: %s",
            error
        )

        print("Execution failed:", error)
