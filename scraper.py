import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta

DATA_FILE = "data/news.json"

XAI_API_KEY = os.environ.get("XAI_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()

GROK_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

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
