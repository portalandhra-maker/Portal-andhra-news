# -*- coding: utf-8 -*-
"""Portal Andhra news collector.

Discovery: publisher sitemaps + publisher homepages (NO RSS dependency).
Extraction: trafilatura when installed, otherwise metadata/HTML fallback.
AI: optional Gemini Telugu rewrite; no unsupported facts are added.
Publishing: ALWAYS pending approval. This script does not publish directly.

Required: Python 3.10+
Recommended: pip install -r requirements.txt
Environment: GEMINI_API_KEY (optional), GEMINI_MODEL (optional),
             NEWS_SOURCES_JSON (optional), MAX_ITEMS, DATA_FILE
"""

from __future__ import annotations
import os, re, json, time, html, hashlib, logging, urllib.request
import urllib.parse, urllib.robotparser, xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    import trafilatura
except ImportError:
    trafilatura = None

# ------------------------------ configuration ------------------------------
DATA_FILE = Path(os.getenv("DATA_FILE", "data/news.json"))
UA = os.getenv("NEWS_UA", "PortalAndhraNewsBot/2.0 (+https://portalandhra.com)")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "18"))
DELAY = float(os.getenv("DOMAIN_DELAY", "2.5"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))
MAX_PER_SOURCE = int(os.getenv("MAX_PER_SOURCE", "20"))
MIN_ARTICLE_CHARS = int(os.getenv("MIN_ARTICLE_CHARS", "350"))
USE_GEMINI = os.getenv("USE_GEMINI", "1") != "0"
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

DEFAULT_SOURCES = [
    {"name":"Eenadu", "base":"https://www.eenadu.net", "category":"ఆంధ్రప్రదేశ్"},
    {"name":"Sakshi", "base":"https://www.sakshi.com", "category":"ఆంధ్రప్రదేశ్"},
    {"name":"Andhra Jyothy", "base":"https://www.andhrajyothy.com", "category":"ఆంధ్రప్రదేశ్"},
    {"name":"NTV Telugu", "base":"https://ntvtelugu.com", "category":"తెలుగు రాష్ట్రాలు"},
    {"name":"TV9 Telugu", "base":"https://tv9telugu.com", "category":"తెలుగు రాష్ట్రాలు"},
    {"name":"10TV", "base":"https://10tv.in", "category":"తెలుగు రాష్ట్రాలు"},
    {"name":"BBC Telugu", "base":"https://www.bbc.com/telugu", "category":"జాతీయ వార్తలు"},
    {"name":"The Hindu", "base":"https://www.thehindu.com", "category":"జాతీయ వార్తలు"},
    {"name":"Indian Express", "base":"https://indianexpress.com", "category":"జాతీయ వార్తలు"},
    {"name":"Reuters", "base":"https://www.reuters.com", "category":"అంతర్జాతీయ వార్తలు"},
    {"name":"AP News", "base":"https://apnews.com", "category":"అంతర్జాతీయ వార్తలు"},
    {"name":"PIB", "base":"https://pib.gov.in", "category":"ప్రభుత్వం"},
]


def load_sources():
    raw = os.getenv("NEWS_SOURCES_JSON", "").strip()
    if not raw:
        return DEFAULT_SOURCES
    try:
        items = json.loads(raw)
        return [x for x in items if isinstance(x, dict) and x.get("base")]
    except Exception as exc:
        logging.error("NEWS_SOURCES_JSON invalid; using defaults: %s", exc)
        return DEFAULT_SOURCES

SOURCES = load_sources()

# ------------------------------ logging / HTTP ------------------------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
_last_request: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def host_of(url):
    return urllib.parse.urlparse(url).netloc.lower()


def fetch_bytes(url, limit=3_000_000):
    host = host_of(url)
    elapsed = time.time() - _last_request.get(host, 0)
    if elapsed < DELAY:
        time.sleep(DELAY - elapsed)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "te,en-US;q=0.8,en;q=0.7"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response exceeds size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        _last_request[host] = time.time()
        return data.decode(charset, errors="replace"), response.geturl(), response.headers.get_content_type()


def robots_allowed(url):
    p = urllib.parse.urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(origin + "/robots.txt")
        try:
            text, _, _ = fetch_bytes(origin + "/robots.txt", 300_000)
            rp.parse(text.splitlines())
            _robots_cache[origin] = rp
        except Exception as exc:
            # Conservative: do not crawl a host if its robots policy cannot be checked.
            logging.warning("robots.txt unavailable for %s; skipping host (%s)", origin, type(exc).__name__)
            _robots_cache[origin] = None
    rp = _robots_cache[origin]
    return bool(rp and rp.can_fetch(UA, url))

# ------------------------------ HTML parsing ------------------------------
class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.meta={}; self.title=False; self.title_text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "meta":
            k=(a.get("property") or a.get("name") or "").lower()
            if k and a.get("content"): self.meta[k]=a["content"].strip()
        if tag == "title": self.title=True
    def handle_endtag(self, tag):
        if tag == "title": self.title=False
    def handle_data(self, data):
        if self.title: self.title_text.append(data)


def parse_page(markup):
    p=PageParser(); p.feed(markup or ""); return p


def clean_text(s):
    s=html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def canonical_url(url, page_parser=None, final_url=None):
    if page_parser:
        c=page_parser.meta.get("og:url") or page_parser.meta.get("twitter:url")
        if c:
            return urllib.parse.urljoin(final_url or url, c)
    return final_url or url


def parse_date(value):
    if not value: return ""
    try:
        dt=parsedate_to_datetime(value)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception: return ""

# ------------------------------ discovery ------------------------------
def sitemap_urls(source):
    base=source["base"].rstrip("/")
    candidates=[base + "/sitemap.xml", base + "/sitemap_index.xml", base + "/news-sitemap.xml"]
    robots=base + "/robots.txt"
    try:
        if robots_allowed(robots):
            txt,_,_=fetch_bytes(robots, 300_000)
            for line in txt.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidates.insert(0, line.split(":",1)[1].strip())
    except Exception: pass
    seen=set(); queue=candidates[:]; found=[]; visited=set()
    while queue and len(visited)<8 and len(found)<MAX_PER_SOURCE*4:
        sm=queue.pop(0)
        if sm in visited: continue
        visited.add(sm)
        try:
            if not robots_allowed(sm): continue
            raw,_,_=fetch_bytes(sm, 5_000_000)
            root=ET.fromstring(raw)
            for node in root.iter():
                if node.tag.lower().endswith("loc") and node.text:
                    loc=node.text.strip()
                    if loc.endswith(".xml") or "sitemap" in loc.lower():
                        if loc not in visited and len(queue)<20: queue.append(loc)
                    elif loc not in seen:
                        seen.add(loc); found.append(loc)
                        if len(found)>=MAX_PER_SOURCE*4: break
        except Exception as exc:
            logging.debug("sitemap skip %s: %s", sm, type(exc).__name__)
    return found


def homepage_urls(source):
    base=source["base"].rstrip("/")
    try:
        if not robots_allowed(base + "/"): return []
        raw,final,_=fetch_bytes(base + "/")
        p=parse_page(raw); out=[]; seen=set()
        for href in p.links:
            u=urllib.parse.urljoin(final, href)
            q=urllib.parse.urlparse(u)
            if q.scheme not in ("http","https") or q.netloc.lower()!=urllib.parse.urlparse(base).netloc.lower(): continue
            if re.search(r"\.(jpg|jpeg|png|gif|webp|pdf|mp4|xml)(\?|$)", q.path, re.I): continue
            if any(x in q.path.lower() for x in ("/tag/","/author/","/category/","/video/","/photo/")): continue
            if u not in seen: seen.add(u); out.append(u)
        return out[:MAX_PER_SOURCE*2]
    except Exception as exc:
        logging.warning("homepage discovery failed %s: %s", base, type(exc).__name__)
        return []

# ------------------------------ article extraction ------------------------------
def extract_article(url, source):
    if not robots_allowed(url):
        raise PermissionError("blocked by robots.txt")
    markup, final, _ = fetch_bytes(url, 4_000_000)
    p=parse_page(markup)
    title=clean_text(p.meta.get("og:title") or p.meta.get("twitter:title") or " ".join(p.title_text))
    description=clean_text(p.meta.get("og:description") or p.meta.get("description") or p.meta.get("twitter:description"))
    image=urllib.parse.urljoin(final, p.meta.get("og:image") or p.meta.get("twitter:image") or "") if (p.meta.get("og:image") or p.meta.get("twitter:image")) else ""
    canonical=canonical_url(url,p,final)
    published=(p.meta.get("article:published_time") or p.meta.get("datepublished") or p.meta.get("pubdate") or p.meta.get("date"))
    body=""
    if trafilatura:
        try:
            body=trafilatura.extract(markup, url=final, include_comments=False, include_tables=False,
                                     include_links=False, favor_precision=True) or ""
        except Exception as exc:
            logging.debug("trafilatura error %s: %s", final, type(exc).__name__)
    if not body:
        body=description
    body=clean_text(body)
    if not title or len(body)<MIN_ARTICLE_CHARS:
        raise ValueError("article text too short or title missing")
    return {"title":title,"description":description,"body":body,"url":canonical,
            "image":image,"published_at":parse_date(published),"source":source["name"],
            "source_category":source.get("category", "ఇతర వార్తలు")}

# ------------------------------ category / dedupe ------------------------------
CATEGORY_RULES = [
    ("సినిమా", ["cinema","movie","film","tollywood","నటుడు","నటి","సినిమా","చిత్రం","ట్రైలర్"]),
    ("క్రీడలు", ["sport","cricket","ipl","football","olympic","క్రికెట్","క్రీడ","మ్యాచ్"]),
    ("ఉద్యోగాలు & విద్య", ["job","jobs","recruitment","exam","result","education","విద్య","ఉద్యోగ","నోటిఫికేషన్","పరీక్ష"]),
    ("బిజినెస్", ["business","market","stock","economy","బిజినెస్","మార్కెట్","ఆర్థిక"]),
    ("టెక్నాలజీ", ["technology","tech","ai","సాంకేతిక","టెక్నాలజీ"]),
    ("క్రైమ్", ["crime","police","murder","arrest","హత్య","అరెస్ట్","పోలీసు","నేరం"]),
    ("రాజకీయాలు", ["politic","election","minister","government","రాజకీయ","ఎన్నిక","మంత్రి","ప్రభుత్వం"]),
    ("అంతర్జాతీయ వార్తలు", ["world","international","united states","china","russia","యుద్ధం","అంతర్జాతీయ"]),
    ("ఆంధ్రప్రదేశ్", ["andhra pradesh","amaravati","విజయవాడ","గుంటూరు","ఆంధ్రప్రదేశ్"]),
    ("తెలంగాణ", ["telangana","hyderabad","హైదరాబాద్","తెలంగాణ"]),
]

def category_for(article):
    hay=(article.get("title","")+" "+article.get("body","")).lower()
    for category, words in CATEGORY_RULES:
        if any(w.lower() in hay for w in words): return category
    return article.get("source_category") or "ఇతర వార్తలు"


def stable_id(url, title):
    return hashlib.sha256((url.strip().lower() or title.strip().lower()).encode("utf-8")).hexdigest()[:20]


def title_fingerprint(title):
    return re.sub(r"[^\w\u0c00-\u0c7f]", "", title.lower())

# ------------------------------ AI rewrite ------------------------------
def gemini_rewrite(article):
    if not USE_GEMINI or not GEMINI_KEY:
        return None
    prompt = """మీరు తెలుగు న్యూస్ డెస్క్ ఎడిటర్. కింద ఇచ్చిన మూల సమాచారాన్ని మాత్రమే ఉపయోగించండి.
కల్పిత వివరాలు, ఊహలు, నేపథ్య వాక్యాలు, కోట్స్ లేదా కారణాలు జోడించవద్దు.
పేర్లు, ప్రదేశాలు, తేదీలు, సంఖ్యలు, మొత్తాలు, హోదాలు మార్చవద్దు.
మూలం అసంపూర్ణంగా ఉంటే దాన్ని పూర్తిగా ఉన్నట్లు రాయకండి.
పూర్తి కథనాన్ని కాపీ చేయకుండా స్వతంత్రంగా రాసిన సంక్షిప్త తెలుగు వార్త ఇవ్వండి.
JSON మాత్రమే ఇవ్వండి: {\"headline\":\"...\",\"summary\":\"...\",\"article\":\"...\",\"category\":\"...\"}

SOURCE TITLE: {title}
SOURCE DESCRIPTION: {description}
SOURCE TEXT: {body}
""".format(title=article["title"], description=article["description"], body=article["body"][:12000])
    endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    payload={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.1,"responseMimeType":"application/json"}}
    req=urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=35) as r: data=json.loads(r.read().decode("utf-8"))
        text=data["candidates"][0]["content"]["parts"][0]["text"]
        result=json.loads(text)
        headline=clean_text(result.get("headline")); summary=clean_text(result.get("summary")); body=clean_text(result.get("article"))
        if not headline or not summary or len(body)<100: return None
        # Basic safety gate: numbers in output must not introduce numbers absent from source.
        source_nums=set(re.findall(r"\d[\d,.]*", article["title"]+" "+article["body"]))
        output_nums=set(re.findall(r"\d[\d,.]*", headline+" "+summary+" "+body))
        if not output_nums.issubset(source_nums):
            logging.warning("AI output introduced numeric facts; sending to manual review")
            return None
        return {"headline":headline,"summary":summary,"article":body,
                "category":clean_text(result.get("category") or category_for(article))}
    except Exception as exc:
        logging.warning("Gemini rewrite failed: %s", type(exc).__name__)
        return None

# ------------------------------ persistence ------------------------------
def load_existing():
    if not DATA_FILE.exists() or DATA_FILE.stat().st_size==0: return []
    try:
        data=json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data,list) else []
    except Exception as exc:
        logging.error("Existing news.json unreadable; refusing to overwrite it: %s", exc)
        raise


def save_atomic(items):
    DATA_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=DATA_FILE.with_suffix(DATA_FILE.suffix+".tmp")
    tmp.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(DATA_FILE)


def make_record(article):
    uid=stable_id(article["url"],article["title"])
    ai=gemini_rewrite(article)
    headline=ai["headline"] if ai else article["title"]
    summary=ai["summary"] if ai else article["description"]
    body=ai["article"] if ai else ""
    category=(ai.get("category") if ai else "") or category_for(article)
    # Keep old common keys while adding explicit provenance and editorial state.
    return {
        "id":uid, "slug":re.sub(r"[^a-z0-9-]+","-",headline.lower()).strip("-")[:55]+"-"+uid[:6],
        "title":headline, "headline":headline, "description":summary,
        "summary":summary, "content":body, "article":body,
        "category":category, "image":article["image"], "image_url":article["image"],
        "url":article["url"], "external_url":article["url"], "source_url":article["url"],
        "source":article["source"], "published_at":article["published_at"],
        "collected_at":now_iso(), "status":"pending", "approval_status":"pending",
        "verification_status":"needs_editor_review", "ai_processed":bool(ai),
        "is_published":False
    }


def main():
    logging.info("Portal Andhra collector starting; sources=%d",len(SOURCES))
    existing=load_existing()
    known_ids={str(x.get("id","")) for x in existing if isinstance(x,dict)}
    known_urls={str(x.get("source_url") or x.get("external_url") or x.get("url") or "").rstrip("/") for x in existing if isinstance(x,dict)}
    known_titles={title_fingerprint(str(x.get("title") or x.get("headline") or "")) for x in existing if isinstance(x,dict)}
    added=[]; failures=[]; seen_this_run=set()
    for source in SOURCES:
        if len(added)>=MAX_ITEMS: break
        base=source["base"].rstrip("/")
        logging.info("Discovering %s",source["name"])
        urls=sitemap_urls(source)
        if not urls: urls=homepage_urls(source)
        count=0
        for url in urls:
            if count>=MAX_PER_SOURCE or len(added)>=MAX_ITEMS: break
            try:
                if url in seen_this_run or not robots_allowed(url): continue
                seen_this_run.add(url)
                # Only crawl URLs belonging to configured publisher host.
                if urllib.parse.urlparse(url).netloc.lower()!=urllib.parse.urlparse(base).netloc.lower(): continue
                article=extract_article(url,source)
                uid=stable_id(article["url"],article["title"])
                fp=title_fingerprint(article["title"])
                if uid in known_ids or article["url"].rstrip("/") in known_urls or (fp and fp in known_titles): continue
                record=make_record(article)
                added.append(record); known_ids.add(uid); known_urls.add(article["url"].rstrip("/")); known_titles.add(fp)
                count+=1
                logging.info("Collected pending: %s",record["title"][:100])
            except Exception as exc:
                failures.append({"source":source["name"],"url":url,"error":type(exc).__name__})
                logging.debug("Article skipped %s: %s",url,type(exc).__name__)
    if added:
        # Preserve current frontend data and append new items at the beginning.
        save_atomic((added+existing)[:max(MAX_ITEMS*5,500)])
    logging.info("Finished: added=%d failures=%d existing=%d",len(added),len(failures),len(existing))
    if failures:
        # One concise summary in Actions logs; no per-article email is sent here.
        by_source={}
        for f in failures: by_source[f["source"]]=by_source.get(f["source"],0)+1
        logging.warning("Failure summary by source: %s",json.dumps(by_source,ensure_ascii=False))
    if not added and failures:
        logging.warning("No new articles collected. Check robots rules, source sitemap availability and workflow dependencies.")

if __name__ == "__main__":
    main()
