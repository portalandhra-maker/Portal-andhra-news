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
    {"url": "https://www.10tv.in/andhra-pradesh", "source": "10TV", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.10tv.in/telangana", "source": "10TV", "default_cat": "తెలంగాణ"},
    {"url": "https://www.ntvtelugu.com/category/andhra-pradesh", "source": "NTV Telugu", "default_cat": "ఆంధ్రప్రదేశ్"},
    {"url": "https://www.ntvtelugu.com/category/telangana", "source": "NTV Telugu", "default_cat": "తెలంగాణ"},
    {"url": "https://www.tv9telugu.com/movies", "source": "TV9 Telugu", "default_cat": "సినిమా"}
]

CATEGORY_RULES = {
    "ఆంధ్రప్రదేశ్": ["ఆంధ్రప్రదేశ్", "ఏపీ", "అమరావతి", "విజయవాడ", "గుంటూరు", "విశాఖపట్నం", "తిరుపతి", "కర్నూలు", "నెల్లూరు"],
    "తెలంగాణ": ["తెలంగాణ", "హైదరాబాద్", "వరంగల్", "కరీంనగర్", "ఖమ్మం", "నిజామాబాద్", "నల్గొండ"],
    "జాతీయ వార్తలు": ["భారతదేశం", "దేశవ్యాప్తంగా", "న్యూఢిల్లీ", "లోక్ సభ", "ప్రధాని", "మోదీ", "సుప్రీంకోర్టు", "కేంద్ర ప్రభుత్వం"],
    "రాజకీయాలు": ["ఎన్నికలు", "రాజకీయాలు", "పార్టీ", "ఎమ్మెల్యే", "ఎంపీ", "మంత్రి", "అసెంబ్లీ", "చంద్రబాబు", "జగన్", "రేవంత్",
