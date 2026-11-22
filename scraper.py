import os
import re
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.8-flash"
DATA_FILE = "data/news.json"
MAX_AGE_DAYS = 15
MAX_NEW_ITEMS_PER_RUN = 3

# AdSense పాలసీలకు విరుద్ధమైన పదాలు
BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex", "betting", "casino", "gambling",
    "హత్య", "ఆత్మహత్య", "బెట్టింగ్", "జూదం", "అశ్లీల"
]

# మీరు స్క్రేప్ చేయాలనుకునే వెబ్‌సైట్ల పేజీ URLs
TARGET_PAGES = [
    {"url": "https://www.eenadu.net/andhra-pradesh", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.eenadu.net/telangana", "default_cat": "తెలంగాణ"},
    {"url": "https://www.eenadu.net/movies", "default_cat": "సినిమా"}
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_html(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def scrape_links(page_url, default_cat):
    candidates = []
    try:
        html = fetch_html(page_url)
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urllib.parse.urlparse(page_url).netloc

        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            href = urllib.parse.urljoin(page_url, a["href"])

            if len(title) < 25 or len(title) > 160:
                continue
            if urllib.parse.urlparse(href).netloc != base_domain:
                continue
            if href.rstrip("/") == page_url.rstrip("/"):
                continue

            candidates.append({
                "title": title,
                "link": href,
                "default_cat": default_cat
            })
    except Exception as e:
        print(f"Page scrape error ({page_url}): {e}")

    # డూప్లికేట్ లింక్స్ తొలగించడం
    seen = set()
    unique = []
    for c in candidates:
        if c["link"] not in seen:
            seen.add(c["link"])
            unique.append(c)
    return unique[:10]


def scrape_article_text(article_url):
    try:
        html = fetch_html(article_url)
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        clean_paras = [p for p in paragraphs if len(p) > 40]
        return "\n".join(clean_paras[:8])[:2500]
    except Exception as e:
        print(f"Article fetch error ({article_url}): {e}")
        return ""


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


def rewrite_with_gemini(raw_title, raw_body, default_cat):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
మీరు ఒక తెలుగు న్యూస్ పోర్టల్ (Portal Andhra) ఎడిటర్.
కింది ముడి వార్త సమాచారం ఆధారంగా, ఏ వెబ్‌సైట్ నుండి కూడా నేరుగా కాపీ చేయకుండా, పూర్తిగా సొంత, సహజమైన తెలుగులో కొత్త వార్త రాయండి.
గూగుల్ యాడ్‌సెన్స్ పాలసీలకు అనుగుణంగా నిష్పాక్షికంగా రాయండి.

ముడి శీర్షిక: {raw_title}
సమాచారం: {raw_body}
విభాగాలు: ఆంధ్రప్రదేశ్, తెలంగాణ, సినిమా, క్రీడలు, బిజినెస్ (డిఫాల్ట్: {default_cat})

JSON ఫార్మాట్‌లో మాత్రమే సమాధానం ఇవ్వండి:
{{
  "title": "సొంత తెలుగు శీర్షిక",
  "category": "విభాగం పేరు",
  "summary": "2 వాక్యాల సారాంశం",
  "content": "3 నుండి 4 పేరాల పూర్తి వార్త కథనం (పేరాల మధ్య \\n వాడండి)"
}}
"""
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.6,
            "responseMimeType": "application/json"
        }
    }).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text.strip())
        except Exception as e:
            print(f"Gemini attempt {attempt + 1} failed: {e}")
            time.sleep(3)
    return None


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY missing!")
        return

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            news_list = json.load(f)
    else:
        news_list = []

    news_list = clean_old_news(news_list)
    added = 0

    for target in TARGET_PAGES:
        if added >= MAX_NEW_ITEMS_PER_RUN:
            break
        links = scrape_links(target["url"], target["default_cat"])
        for item in links:
            if added >= MAX_NEW_ITEMS_PER_RUN:
                break
            if not is_adsense_safe(item["title"]) or is_duplicate(news_list, item["title"], item["link"]):
                continue

            body = scrape_article_text(item["link"])
            if len(body) < 120 or not is_adsense_safe(body):
                continue

            rewritten = rewrite_with_gemini(item["title"], body, item["default_cat"])
            if not rewritten:
                continue

            ist = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist)

            news_list.insert(0, {
                "id": f"{int(time.time())}_{added + 1}",
                "title": rewritten.get("title", item["title"]),
                "category": rewritten.get("category", item["default_cat"]),
                "summary": rewritten.get("summary", ""),
                "content": rewritten.get("content", ""),
                "image": "",
                "sourceUrl": item["link"],
                "publishedAt": now_ist.strftime("%d %b %Y, %I:%M %p"),
                "createdAt": datetime.now(timezone.utc).isoformat()
            })
            added += 1
            time.sleep(2)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"Done. Added {added} new articles. Total: {len(news_list)}")


if __name__ == "__main__":
    main()
