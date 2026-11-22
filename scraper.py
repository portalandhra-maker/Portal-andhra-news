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


def b2s(hex_str):
    return bytes.fromhex(hex_str).decode("utf-8")


BLOCKED_KEYWORDS = [
    "murder", "suicide", "rape", "porn", "sex",
    "betting", "casino", "gambling",
    "ushodaya", "prosecuted", "georgia-fulton",
    b2s("e0b0b9e0b0a4e0b18d"),
    b2s("e0b086e0b0a4e0b18de0b0aee0b0b9e0b0a4e0b18d"),
    b2s("e0b0ace0b186e0b09fe0b18de0b09fe0b082e0b097"),
    b2s("e0b09ce0b182e0b0a6e0b082"),
    b2s("e0b085e0b0b6e0b18de0b0b2e0b180e0b0b2"),
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
    {"url": "https://www.10tv.in/andhra-pradesh", "source": "10TV", "default_cat": b2s("e0b086e0b082e0b0a7e0b18de0b0b0e0b0aae0b18de0b0aae0b18de0b0b0e0b0a6e0b187e0b0b6e0b18d")},
    {"url": "https://www.10tv.in/telangana", "source": "10TV", "default_cat": b2s("e0b0a4e0b186e0b0b2e0b082e0b097e0b0a3")},
    {"url": "https://www.ntvtelugu.com/category/andhra-pradesh", "source": "NTV Telugu", "default_cat": b2s("e0b086e0b082e0b0a7e0b18de0b0b0e0b0aae0b18de0b0aae0b18de0b0b0e0b0a6e0b187e0b0b6e0b18d")},
    {"url": "https://www.ntvtelugu.com/category/telangana", "source": "NTV Telugu", "default_cat": b2s("e0b0a4e0b186e0b0b2e0b082e0b097e0b0a3")},
    {"url": "https://www.tv9telugu.com/movies", "source": "TV9 Telugu", "default_cat": b2s("e0b0b8e0b0b3e0b0a8e0b0bfe0b0aee0b0be")},
]

CATEGORY_RULES = {
    b2s("e0b086e0b082e0b0a7e0b18de0b0b0e0b0aae0b18de0b0aae0b18de0b0b0e0b0a6e0b187e0b0b6e0b18d"): [
        b2s("e0b086e0b082e0b0a7e0
