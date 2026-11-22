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

BAD_IMAGE_PATTERNS = [
    "logo", "icon", "favicon", "avatar", "sprite", "badge", "button",
    "banner", "advert", "ad-", "ads", "doubleclick", "googlesyndication",
    "facebook.com/tr", "pixel", "tracker", "spacer", "blank", "placeholder",
    "default-thumb", "no-image", "author", "profile", "whatsapp", "twitter",
    "youtube.com", "play-store", "app-store"
]

VALID_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

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
        "ఏఐ", "గూగుల్", "ఐఫోన్", "సాఫ్ట్‌వేర్
