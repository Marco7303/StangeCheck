import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(dotenv_path=REPO_ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
OCR_FALLBACK_MODEL = os.environ.get("OCR_FALLBACK_MODEL", OPENAI_MODEL)
TESSERACT_LANG = os.environ.get("TESSERACT_LANG", "deu+eng")

MAX_VENUES_PER_RUN = 20
PAGE_TIMEOUT_MS = 15000
MAX_HTML_PAGES = 12
MAX_CRAWL_DEPTH = 3
MAX_INTERACTIONS_PER_PAGE = 8
MAX_PDF_FILES = 6
MAX_IMAGE_FILES = 8
MAX_OCR_PDF_PAGES = 8
MAX_MODEL_TEXT_CHARS = 24000
MAX_BODY_TEXT_CHARS = 12000
MAX_BLOCK_TEXT_CHARS = 3000
SCROLL_STEPS = 6
SCROLL_PAUSE_SECONDS = 0.35
REQUEST_TIMEOUT_SECONDS = 20
DEBUG_ARTIFACTS_ENABLED = os.environ.get("CHECK_WEBSITES_DEBUG", "1") != "0"
DEBUG_ARTIFACTS_ROOT = REPO_ROOT / "jobs" / "check-websites" / "debug"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

KEYWORDS = [
    "karte",
    "speisekarte",
    "getränkekarte",
    "getraenkekarte",
    "menü",
    "menu",
    "barkarte",
    "weinkarte",
    "bierkarte",
    "angebot",
    "bier",
    "biere",
    "vom fass",
    "offenbier",
    "zapfbier",
    "lager",
    "helles",
    "pils",
    "pilsner",
    "weizen",
    "weissbier",
    "brauerei",
    "getränke",
    "getraenke",
    "trinken",
    "aperitif",
    "alkohol",
    "food menu",
    "drink menu",
    "drinks menu",
    "beverage menu",
    "bar menu",
    "wine list",
    "beer menu",
    "beer",
    "beers",
    "draft",
    "draught",
    "on tap",
    "tap list",
    "ale",
    "wheat beer",
    "craft beer",
    "brewery",
    "drinks",
    "beverages",
    "bar",
    "alcohol",
    "pdf",
    "download",
    "menu pdf",
    "drinks pdf",
    "bierkarte pdf",
]

LAGER_TERMS = [
    "lager",
    "helles",
    "pils",
    "pilsner",
    "bier",
    "beer",
    "offen",
    "vom fass",
    "draft",
    "draught",
    "feldschlösschen",
    "feldschloesschen",
    "cardinal",
    "calanda",
    "eichhof",
    "heineken",
    "carlsberg",
    "hop house",
    "birra moretti",
    "corona",
    "stella artois",
    "san miguel",
    "peroni",
    "guinness",
    "quöllfrisch",
    "quöllfrisch",
    "quoellfrisch",
    "valaisanne",
    "hürlimann",
    "huerlimann",
    "ittinger",
    "haldengut",
    "schützengarten",
    "schuetzengarten",
    "chopfab",
    "kronenbourg",
    "beck",
    "estrella damm",
    "pilsner urquell",
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_EXTENSIONS = {".pdf"}
WHITESPACE_PATTERN = re.compile(r"[ \t]+")
PRICE_PATTERN = re.compile(
    r"(?P<price>\d{1,2}(?:[.,]\d{1,2})?)\s*(?:chf|fr\.?|franken)\b",
    re.IGNORECASE,
)
BARE_PRICE_PATTERN = re.compile(r"\b(?P<price>\d{1,2}(?:[.,]\d{1,2})?)\b")
VOLUME_PATTERN = re.compile(
    r"\b(?:0[.,]5\s*l|5\s*dl|50\s*cl|500\s*ml)\b",
    re.IGNORECASE,
)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
