import base64
import io
import json
import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from supabase import create_client

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


REPO_ROOT = Path(__file__).resolve().parents[3]
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
PRICE_PATTERN = re.compile(r"(?P<price>\d{1,2}(?:[.,]\d{1,2})?)\s*(?:chf|fr\.?|franken)\b", re.IGNORECASE)
BARE_PRICE_PATTERN = re.compile(r"\b(?P<price>\d{1,2}(?:[.,]\d{1,2})?)\b")
VOLUME_PATTERN = re.compile(
    r"\b(?:0[.,]5\s*l|5\s*dl|50\s*cl|500\s*ml)\b",
    re.IGNORECASE,
)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)


@dataclass
class CrawlTask:
    url: str
    depth: int
    priority: int


@dataclass
class HtmlDocument:
    source_url: str
    text: str


@dataclass
class ExtractedDocument:
    source_url: str
    source_type: str
    text: str


@dataclass
class PriceCandidate:
    beer_name: str
    price_chf: float
    volume_l: float
    evidence: str
    source_url: str


@dataclass
class CrawlResult:
    html_documents: list[HtmlDocument]
    pdf_urls: list[str]
    image_urls: list[str]
    errors: list[str]
    debug: dict


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_inline(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "venue"


def ensure_debug_dir(venue: dict) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = slugify(venue.get("name") or "venue")
    venue_id = str(venue.get("id") or "unknown")
    path = DEBUG_ARTIFACTS_ROOT / f"{timestamp}-{slug}-{venue_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_debug_text(debug_dir: Path, relative_path: str, content: str) -> None:
    path = debug_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_debug_json(debug_dir: Path, relative_path: str, payload: dict | list) -> None:
    write_debug_text(
        debug_dir,
        relative_path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def serialize_price_candidates(candidates: list[PriceCandidate]) -> list[dict]:
    return [
        {
            "beer_name": candidate.beer_name,
            "price_chf": candidate.price_chf,
            "volume_l": candidate.volume_l,
            "evidence": candidate.evidence,
            "source_url": candidate.source_url,
        }
        for candidate in candidates
    ]


def append_note(existing: str | None, message: str | None) -> str | None:
    if not message:
        return existing
    message = normalize_inline(message)
    if not message:
        return existing
    if not existing:
        return message
    if message in existing:
        return existing
    return f"{existing} | {message}"


def status_note(status: str, detail: str | None = None) -> str:
    if detail:
        return f"{status}: {normalize_inline(detail)}"
    return status


def normalize_url(url: str) -> str:
    value = url.strip()
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme:
        return value
    return f"https://{value}"


def strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def site_family(host: str) -> str:
    host = host.lower().split(":", 1)[0]
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def same_site_family(left: str, right: str) -> bool:
    return site_family(urlparse(left).netloc) == site_family(urlparse(right).netloc)


def classify_asset(url: str) -> str:
    path = urlparse(url).path.lower()
    for extension in PDF_EXTENSIONS:
        if path.endswith(extension):
            return "pdf"
    for extension in IMAGE_EXTENSIONS:
        if path.endswith(extension):
            return "image"
    return "html"


def should_skip_image_url(page_url: str, image_url: str) -> bool:
    parsed = urlparse(image_url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if path.endswith(".svg"):
        return True
    if "emoji" in path:
        return True
    if not same_site_family(page_url, image_url):
        return True
    return False


def keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(1 for keyword in KEYWORDS if keyword in lowered)


def url_priority(url: str) -> int:
    kind = classify_asset(url)
    base = keyword_score(url)
    lowered_path = urlparse(url).path.lower()
    if kind == "pdf":
        base += 4
    elif kind == "image":
        base += 3
    if any(term in lowered_path for term in ["/menu", "/bier", "/beer", "/drinks", "/getraenke", "/getränke", "/barkarte", "/speisekarte"]):
        base += 8
    if any(term in lowered_path for term in ["/category/", "/tag/", "/author/", "/page/"]):
        base -= 6
    if re.search(r"/20\d{2}/\d{2}/", lowered_path):
        base -= 8
    filename = Path(lowered_path).name
    if any(term in filename for term in ["bier", "beer", "cider", "menu", "karte", "drinks", "getraenke", "getränke"]):
        base += 6
    if any(term in filename for term in ["logo", "team", "banner", "hero", "award", "winner", "emoji"]):
        base -= 6
    return base


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,image/*,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
        }
    )
    return session


def fetch_binary(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
    response.raise_for_status()
    return response


def scroll_page(page) -> None:
    for _ in range(SCROLL_STEPS):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(int(SCROLL_PAUSE_SECONDS * 1000))


def collect_dom_snapshot(page, keywords: list[str]) -> dict:
    script = """
    (keywords) => {
      const keywordList = keywords.map((value) => value.toLowerCase());

      const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        if (!style || style.visibility === "hidden" || style.display === "none") return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };

      const normalize = (value) =>
        (value || "")
          .replace(/[ \\t]+/g, " ")
          .replace(/\\n{3,}/g, "\\n\\n")
          .trim();

      const keywordScore = (value) => {
        const lowered = (value || "").toLowerCase();
        return keywordList.reduce((count, keyword) => count + (lowered.includes(keyword) ? 1 : 0), 0);
      };

      const cssPath = (element) => {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
        if (element.id) return `#${CSS.escape(element.id)}`;
        const parts = [];
        let node = element;
        while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
          let selector = node.nodeName.toLowerCase();
          const parent = node.parentElement;
          if (!parent) break;
          const siblings = Array.from(parent.children).filter(
            (child) => child.nodeName === node.nodeName
          );
          if (siblings.length > 1) {
            const index = siblings.indexOf(node) + 1;
            selector += `:nth-of-type(${index})`;
          }
          parts.unshift(selector);
          node = parent;
        }
        parts.unshift("body");
        return parts.join(" > ");
      };

      const bodyText = normalize(document.body?.innerText || "");

      const links = [];
      const images = [];
      const clickables = [];
      const blocks = [];
      const blockSeen = new Set();

      document.querySelectorAll("a[href]").forEach((anchor) => {
        if (!isVisible(anchor)) return;
        const href = anchor.href || "";
        if (!href) return;
        links.push({
          url: href.split("#")[0],
          label: normalize(anchor.innerText || anchor.textContent || anchor.getAttribute("aria-label") || href),
          score: keywordScore(`${anchor.innerText || ""} ${href}`),
        });
      });

      document.querySelectorAll("img[src]").forEach((image) => {
        if (!isVisible(image)) return;
        const src = image.src || "";
        if (!src) return;
        images.push({
          url: src.split("#")[0],
          label: normalize(image.alt || src),
          score: keywordScore(`${image.alt || ""} ${src}`),
        });
      });

      document.querySelectorAll("a, button, [role='button'], [onclick]").forEach((element) => {
        if (!isVisible(element)) return;
        const label = normalize(
          element.innerText ||
          element.textContent ||
          element.getAttribute("aria-label") ||
          element.getAttribute("title") ||
          ""
        );
        const href = element.href || element.getAttribute("href") || "";
        const score = keywordScore(`${label} ${href}`);
        if (score <= 0) return;
        clickables.push({
          selector: cssPath(element),
          label,
          href: href || "",
          score,
        });
      });

      const scanElements = document.querySelectorAll("a, button, h1, h2, h3, h4, h5, h6, p, span, div, li, section, article");
      scanElements.forEach((element) => {
        if (!isVisible(element)) return;
        const text = normalize(element.innerText || element.textContent || "");
        if (!text) return;
        if (keywordScore(text) <= 0) return;

        const container =
          element.closest("section, article, .menu, .content, .entry, li, ul, ol, div") ||
          element.parentElement ||
          element;

        if (!container || !isVisible(container)) return;

        const key = cssPath(container);
        if (!key || blockSeen.has(key)) return;
        blockSeen.add(key);

        const blockText = normalize(container.innerText || container.textContent || "");
        const blockLinks = Array.from(container.querySelectorAll("a[href]"))
          .map((anchor) => (anchor.href || "").split("#")[0])
          .filter(Boolean);
        const blockImages = Array.from(container.querySelectorAll("img[src]"))
          .map((image) => (image.src || "").split("#")[0])
          .filter(Boolean);

        blocks.push({
          text: blockText,
          links: Array.from(new Set(blockLinks)),
          images: Array.from(new Set(blockImages)),
          score: keywordScore(blockText),
        });
      });

      return {
        url: window.location.href.split("#")[0],
        bodyText,
        links,
        images,
        clickables,
        blocks,
      };
    }
    """
    return page.evaluate(script, keywords)


def maybe_accept_cookies(page) -> None:
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Ich stimme zu')",
        "button:has-text('Alle akzeptieren')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1200):
                locator.click(timeout=1500)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


def click_revealing_elements(page, clicked_keys: set[str]) -> list[dict]:
    revealed_snapshots: list[dict] = []

    for _ in range(3):
        snapshot = collect_dom_snapshot(page, KEYWORDS)
        candidates = sorted(
            snapshot.get("clickables", []),
            key=lambda item: item.get("score", 0),
            reverse=True,
        )
        clicked_this_round = False

        for candidate in candidates:
            selector = candidate.get("selector")
            href = candidate.get("href") or ""
            label = candidate.get("label") or selector
            key = f"{selector}|{href}|{label}"
            if key in clicked_keys:
                continue
            if href and not href.startswith("#") and "javascript:" not in href.lower():
                continue
            if not selector:
                continue

            try:
                locator = page.locator(selector).first
                if not locator.is_visible(timeout=500):
                    continue
                locator.click(timeout=2000)
                clicked_keys.add(key)
                page.wait_for_timeout(900)
                scroll_page(page)
                revealed_snapshots.append(collect_dom_snapshot(page, KEYWORDS))
                clicked_this_round = True
                if len(clicked_keys) >= MAX_INTERACTIONS_PER_PAGE:
                    return revealed_snapshots
            except Exception:
                clicked_keys.add(key)
                continue

        if not clicked_this_round:
            break

    return revealed_snapshots


def merge_snapshot_assets(
    base_url: str,
    snapshots: list[dict],
    html_candidates: dict[str, int],
    pdf_candidates: dict[str, int],
    image_candidates: dict[str, int],
    documents: list[HtmlDocument],
) -> None:
    for snapshot in snapshots:
        url = strip_fragment(snapshot.get("url") or base_url)
        body_text = snapshot.get("bodyText") or ""
        block_texts = []
        for block in snapshot.get("blocks", []):
            text = normalize_inline(block.get("text") or "")
            if text:
                block_texts.append(text[:MAX_BLOCK_TEXT_CHARS])

            for link in block.get("links", []):
                absolute = strip_fragment(urljoin(url, link))
                kind = classify_asset(absolute)
                score = block.get("score", 0) + url_priority(absolute) + 2
                if kind == "html" and same_site_family(url, absolute):
                    html_candidates[absolute] = max(html_candidates.get(absolute, 0), score)
                elif kind == "pdf":
                    pdf_candidates[absolute] = max(pdf_candidates.get(absolute, 0), score)
                elif kind == "image":
                    image_candidates[absolute] = max(image_candidates.get(absolute, 0), score)

            for image in block.get("images", []):
                absolute = strip_fragment(urljoin(url, image))
                if should_skip_image_url(url, absolute):
                    continue
                image_candidates[absolute] = max(
                    image_candidates.get(absolute, 0),
                    block.get("score", 0) + url_priority(absolute) + url_priority(url) + 6,
                )

        combined_text = body_text
        if block_texts:
            combined_text = combined_text + "\n\n[MENU_CANDIDATE_BLOCKS]\n" + "\n\n".join(block_texts)

        if combined_text:
            documents.append(HtmlDocument(source_url=url, text=combined_text[:MAX_BODY_TEXT_CHARS]))

        for link in snapshot.get("links", []):
            href = strip_fragment(link.get("url") or "")
            if not href:
                continue
            kind = classify_asset(href)
            score = int(link.get("score", 0)) + url_priority(href)
            if kind == "html" and same_site_family(url, href):
                html_candidates[href] = max(html_candidates.get(href, 0), score)
            elif kind == "pdf":
                pdf_candidates[href] = max(pdf_candidates.get(href, 0), score)
            elif kind == "image":
                image_candidates[href] = max(image_candidates.get(href, 0), score)

        for image in snapshot.get("images", []):
            src = strip_fragment(image.get("url") or "")
            if not src:
                continue
            if should_skip_image_url(url, src):
                continue
            score = int(image.get("score", 0)) + url_priority(src) + max(url_priority(url), 0)
            image_candidates[src] = max(image_candidates.get(src, 0), score)


def crawl_site(start_url: str) -> CrawlResult:
    documents: list[HtmlDocument] = []
    errors: list[str] = []
    html_candidates: dict[str, int] = {}
    pdf_candidates: dict[str, int] = {}
    image_candidates: dict[str, int] = {}
    visited_html: set[str] = set()
    queue: list[CrawlTask] = [CrawlTask(url=start_url, depth=0, priority=100)]
    visit_order: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="de-CH")
        page = context.new_page()

        while queue and len(visited_html) < MAX_HTML_PAGES:
            queue.sort(key=lambda item: (-item.priority, item.depth, item.url))
            task = queue.pop(0)
            target_url = strip_fragment(task.url)
            if target_url in visited_html:
                continue

            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(1200)
                maybe_accept_cookies(page)
                scroll_page(page)
                initial_snapshot = collect_dom_snapshot(page, KEYWORDS)
                revealed_snapshots = click_revealing_elements(page, set())
                snapshots = [initial_snapshot] + revealed_snapshots
                final_url = strip_fragment(page.url)
                if final_url in visited_html:
                    continue
                visited_html.add(final_url)
                visit_order.append(
                    {
                        "requested_url": target_url,
                        "final_url": final_url,
                        "depth": task.depth,
                        "priority": task.priority,
                    }
                )
                print(f"[FETCH_HTML] {final_url}")
                merge_snapshot_assets(final_url, snapshots, html_candidates, pdf_candidates, image_candidates, documents)

                if task.depth >= MAX_CRAWL_DEPTH:
                    continue

                for candidate_url, score in list(html_candidates.items()):
                    if candidate_url in visited_html:
                        continue
                    if not any(item.url == candidate_url for item in queue):
                        queue.append(
                            CrawlTask(
                                url=candidate_url,
                                depth=task.depth + 1,
                                priority=score,
                            )
                        )

            except PlaywrightTimeoutError as error:
                errors.append(f"{target_url}: timeout {error}")
            except Exception as error:
                errors.append(f"{target_url}: {error}")

        context.close()
        browser.close()

    ranked_pdfs = sorted(pdf_candidates.items(), key=lambda item: item[1], reverse=True)
    ranked_images = sorted(image_candidates.items(), key=lambda item: item[1], reverse=True)
    pdf_urls = [url for url, _score in ranked_pdfs[:MAX_PDF_FILES]]
    image_urls = [url for url, _score in ranked_images[:MAX_IMAGE_FILES]]

    deduped_documents: list[HtmlDocument] = []
    seen = set()
    for document in documents:
        key = (document.source_url, document.text[:500])
        if key in seen:
            continue
        seen.add(key)
        deduped_documents.append(document)

    ranked_html = sorted(html_candidates.items(), key=lambda item: item[1], reverse=True)
    debug = {
        "start_url": start_url,
        "visited_pages": visit_order,
        "ranked_html_candidates": [
            {"url": url, "score": score} for url, score in ranked_html
        ],
        "ranked_pdf_candidates": [
            {"url": url, "score": score} for url, score in ranked_pdfs
        ],
        "ranked_image_candidates": [
            {"url": url, "score": score} for url, score in ranked_images
        ],
        "selected_pdf_urls": pdf_urls,
        "selected_image_urls": image_urls,
        "crawl_errors": errors,
    }

    return CrawlResult(
        html_documents=deduped_documents,
        pdf_urls=pdf_urls,
        image_urls=image_urls,
        errors=errors,
        debug=debug,
    )


def extract_pdf_text(content: bytes) -> str:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            pages.append(text)

    lines = [line.rstrip() for line in "\n".join(pages).splitlines()]
    lines = [line for line in lines if line.strip()]
    return "\n".join(lines)


def text_looks_useful(text: str) -> bool:
    if not text:
        return False
    letters = sum(1 for char in text if char.isalpha())
    return letters >= 80


def image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def ocr_with_openai_image(image: Image.Image) -> str:
    response = openai_client.responses.create(
        model=OCR_FALLBACK_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Transcribe the visible menu text exactly. Preserve line breaks. Do not summarize.",
                    },
                    {
                        "type": "input_image",
                        "image_url": image_to_data_url(image),
                        "detail": "high",
                    },
                ],
            }
        ],
    )
    text = response.output_text or ""
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    return "\n".join(lines)


def ocr_image(image: Image.Image) -> str:
    if pytesseract and shutil.which("tesseract"):
        text = pytesseract.image_to_string(image, lang=TESSERACT_LANG)
        lines = [line.rstrip() for line in text.splitlines()]
        lines = [line for line in lines if line.strip()]
        if lines:
            return "\n".join(lines)

    return ocr_with_openai_image(image)


def extract_pdf_with_fallback(content: bytes) -> str:
    direct_text = extract_pdf_text(content)
    if text_looks_useful(direct_text):
        return direct_text

    if pdfium is None:
        return direct_text

    try:
        document = pdfium.PdfDocument(io.BytesIO(content))
        page_texts: list[str] = []
        page_count = min(len(document), MAX_OCR_PDF_PAGES)
        for page_index in range(page_count):
            page = document[page_index]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()
            ocr_text = ocr_image(image)
            if ocr_text:
                page_texts.append(f"[PDF_PAGE {page_index + 1}]\n{ocr_text}")
        combined = "\n\n".join(page_texts)
        return combined or direct_text
    except Exception:
        return direct_text


def extract_pdf_document(session: requests.Session, url: str) -> ExtractedDocument | None:
    response = fetch_binary(session, url)
    text = extract_pdf_with_fallback(response.content)
    return ExtractedDocument(source_url=url, source_type="pdf", text=text)


def extract_image_document(session: requests.Session, url: str) -> ExtractedDocument | None:
    response = fetch_binary(session, url)
    image = Image.open(io.BytesIO(response.content))
    text = ocr_image(image)
    return ExtractedDocument(source_url=url, source_type="image", text=text)


def build_extracted_documents(session: requests.Session, html_docs: list[HtmlDocument], pdf_urls: list[str], image_urls: list[str]) -> tuple[list[ExtractedDocument], list[str]]:
    documents = [
        ExtractedDocument(source_url=document.source_url, source_type="html", text=document.text)
        for document in html_docs
    ]
    errors: list[str] = []

    for pdf_url in pdf_urls:
        try:
            print(f"[FETCH_PDF] {pdf_url}")
            document = extract_pdf_document(session, pdf_url)
            if document and document.text:
                documents.append(document)
        except Exception as error:
            errors.append(f"{pdf_url}: {error}")

    for image_url in image_urls:
        try:
            print(f"[FETCH_IMAGE] {image_url}")
            document = extract_image_document(session, image_url)
            if document and document.text:
                documents.append(document)
        except Exception as error:
            errors.append(f"{image_url}: {error}")

    return documents, errors


def contains_lager_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in LAGER_TERMS)


def parse_price(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def format_price_variants(value: float) -> tuple[str, str]:
    fixed = f"{value:.2f}"
    trimmed = f"{value:g}"
    return (
        fixed,
        fixed.replace(".", ","),
        trimmed,
        trimmed.replace(".", ","),
    )


def guess_beer_name(snippet: str) -> str:
    segments = re.split(r"[-–•|:]", normalize_inline(snippet))
    if segments:
        return segments[0][:80].strip()
    return normalize_inline(snippet)[:80]


def is_line_likely_beer_name(line: str) -> bool:
    stripped = normalize_inline(line)
    if not stripped:
        return False
    if contains_lager_term(stripped):
        return True
    return stripped.isupper() and any(char.isalpha() for char in stripped)


def clean_beer_name(line: str) -> str:
    name = normalize_inline(line)
    name = re.sub(r"\b\d+(?:[.,]\d+)?\s*%\b", "", name)
    name = re.sub(r"\b(?:0[.,]5\s*l|5\s*dl|50\s*cl|500\s*ml|30\s*cl|33\s*cl|35\s*cl|40\s*cl)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\b\d{1,2}(?:[.,]\d{1,2})?\b", "", name)
    return normalize_inline(name)


def document_priority(document: ExtractedDocument) -> tuple[int, int]:
    source_bonus = {"pdf": 3, "image": 2, "html": 1}.get(document.source_type, 0)
    text_score = keyword_score(document.text[:4000]) + url_priority(document.source_url)
    return (source_bonus, text_score)


def extract_price_candidates(documents: list[ExtractedDocument]) -> list[PriceCandidate]:
    candidates: list[PriceCandidate] = []

    for document in documents:
        lines = [raw_line.rstrip() for raw_line in document.text.splitlines()]
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            if "flight" in line.lower():
                continue

            window_lines = [entry for entry in lines[index : index + 3] if entry.strip()]
            snippet = "\n".join(window_lines)
            if not contains_lager_term(snippet):
                continue

            direct_match = PRICE_PATTERN.search(snippet)
            if direct_match and VOLUME_PATTERN.search(snippet):
                price = parse_price(direct_match.group("price"))
                if price is not None:
                    candidates.append(
                        PriceCandidate(
                            beer_name=guess_beer_name(snippet),
                            price_chf=price,
                            volume_l=0.5,
                            evidence=snippet[:240],
                            source_url=document.source_url,
                        )
                    )
                continue

            if not is_line_likely_beer_name(line):
                continue

            beer_name = clean_beer_name(line)
            if not beer_name or "flight" in beer_name.lower():
                continue

            next_lines = [entry for entry in lines[index + 1 : index + 3] if entry.strip()]
            volume_line = next(
                (entry for entry in [line] + next_lines if re.search(r"\b50\s*cl\b|\b5\s*dl\b|\b0[.,]5\s*l\b|\b500\s*ml\b", entry, re.IGNORECASE)),
                None,
            )
            if not volume_line:
                continue

            price = None
            volume_match = re.search(r"\b50\s*cl\b|\b5\s*dl\b|\b0[.,]5\s*l\b|\b500\s*ml\b", volume_line, re.IGNORECASE)
            if volume_match:
                trailing_text = volume_line[volume_match.end() :]
                bare_prices = [
                    parse_price(candidate.group("price"))
                    for candidate in BARE_PRICE_PATTERN.finditer(trailing_text)
                ]
                bare_prices = [
                    candidate
                    for candidate in bare_prices
                    if candidate is not None and 3.0 <= candidate <= 25.0
                ]
                if bare_prices:
                    price = bare_prices[0]

            if price is None:
                continue

            evidence_lines = [line]
            if next_lines:
                evidence_lines.extend(next_lines[:2])
            evidence = "\n".join(evidence_lines)

            candidates.append(
                PriceCandidate(
                    beer_name=beer_name,
                    price_chf=price,
                    volume_l=0.5,
                    evidence=evidence[:240],
                    source_url=document.source_url,
                )
            )

    return candidates


def choose_clear_candidate(candidates: list[PriceCandidate]) -> PriceCandidate | None:
    if not candidates:
        return None

    unique_map: dict[tuple[str, float, str], PriceCandidate] = {}
    for candidate in candidates:
        key = (candidate.beer_name.lower(), candidate.price_chf, candidate.source_url)
        unique_map[key] = candidate

    unique = list(unique_map.values())
    if len(unique) == 1:
        return unique[0]

    ranked = sorted(unique, key=lambda candidate: candidate.price_chf)
    cheapest = ranked[0]
    second = ranked[1]
    if cheapest.price_chf < second.price_chf:
        return cheapest
    return None


def build_combined_text(documents: list[ExtractedDocument]) -> str:
    chunks: list[str] = []
    total_chars = 0
    ranked_documents = sorted(
        (document for document in documents if document.text),
        key=document_priority,
        reverse=True,
    )

    for document in ranked_documents:
        chunk = f"[{document.source_type.upper()}: {document.source_url}]\n{document.text}"
        if total_chars + len(chunk) <= MAX_MODEL_TEXT_CHARS:
            chunks.append(chunk)
            total_chars += len(chunk) + 2
            continue

        remaining = MAX_MODEL_TEXT_CHARS - total_chars
        if remaining <= 200:
            break
        chunks.append(chunk[:remaining])
        break

    return "\n\n".join(chunks)


def build_documents_dump(documents: list[ExtractedDocument]) -> str:
    chunks = []
    for document in documents:
        chunks.append(
            f"[{document.source_type.upper()}: {document.source_url}]\n{document.text or ''}"
        )
    return "\n\n".join(chunks)


def build_source_text_map(documents: list[ExtractedDocument]) -> dict[str, str]:
    return {
        document.source_url: normalize_inline(document.text)
        for document in documents
        if document.text
    }


def build_extraction_prompt(venue: dict, combined_text: str) -> str:
    schema = {
        "found": "boolean",
        "beer_name": "string | null",
        "price": "number | null",
        "currency": "string | null",
        "volume_l": "number | null",
        "evidence": "string | null",
        "source_url": "string | null",
        "reason": "string | null",
    }

    return (
        "You are extracting a venue's cheapest 0.5L lager beer from provided restaurant website text.\n"
        "You are NOT browsing. Use ONLY the provided text.\n"
        "Return JSON only.\n"
        f"Required schema: {json.dumps(schema)}\n\n"
        f"Venue name: {venue.get('name')}\n"
        f"Website: {venue.get('website')}\n\n"
        "Rules:\n"
        "- Only report found=true if there is a clear 0.5l / 5dl / 50cl / 500ml lager-like draft beer candidate.\n"
        "- Be conservative. A missed result is better than a wrong result.\n"
        "- Only choose a price if the beer name, the 0.5L volume, and the price are clearly linked in the same source.\n"
        "- If multiple prices are nearby or the pairing is ambiguous, return found=false.\n"
        "- Keep evidence short and verbatim-like from the source.\n"
        "- source_url must be one of the provided source labels.\n"
        "- currency must be CHF if found=true.\n\n"
        "Provided text:\n"
        f"{combined_text[:MAX_MODEL_TEXT_CHARS]}"
    )


def run_extraction_model(venue: dict, combined_text: str) -> dict | None:
    prompt = build_extraction_prompt(venue, combined_text)
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Return strict JSON only. If uncertain, return found=false.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def validate_model_result(
    result: dict,
    combined_text: str,
    allowed_source_urls: set[str],
    source_text_map: dict[str, str],
) -> tuple[bool, str | None]:
    if result.get("found") is not True:
        return False, "model returned found=false"

    price = result.get("price")
    if not isinstance(price, (int, float)):
        return False, "model price is not numeric"

    if result.get("volume_l") != 0.5:
        return False, "model volume is not 0.5l"

    beer_name = normalize_inline(result.get("beer_name") or "")
    if not beer_name:
        return False, "model beer_name is empty"

    evidence = result.get("evidence") or ""
    if not evidence.strip():
        return False, "model evidence is empty"

    source_url = normalize_inline(result.get("source_url") or "")
    if not source_url:
        return False, "model source_url is empty"
    if source_url not in allowed_source_urls:
        return False, "model source_url is not one of the gathered sources"

    source_text = source_text_map.get(source_url, "")
    if not source_text:
        return False, "source text for model source_url is empty"

    normalized_dump = normalize_inline(combined_text)
    normalized_evidence = normalize_inline(evidence)
    if normalized_evidence not in normalized_dump and normalized_evidence not in source_text:
        evidence_tokens = [token for token in re.split(r"\s+", normalized_evidence) if len(token) >= 3]
        overlap = sum(1 for token in evidence_tokens if token.lower() in source_text.lower())
        if overlap < max(2, min(5, len(evidence_tokens) // 2)):
            return False, "model evidence not sufficiently grounded in source text"

    if beer_name.lower() not in normalized_evidence.lower() and beer_name.lower() not in source_text.lower():
        return False, "model beer name not found in source text"

    if not VOLUME_PATTERN.search(normalized_evidence) and not VOLUME_PATTERN.search(source_text):
        return False, "model source text does not contain 0.5l volume"

    price_variants = format_price_variants(float(price))
    if not any(price_variant in normalized_evidence for price_variant in price_variants) and not any(
        price_variant in source_text for price_variant in price_variants
    ):
        return False, "model source text does not contain returned price"

    return True, None


def update_venue(venue_id, payload: dict) -> None:
    supabase.table("venues").update(payload).eq("id", venue_id).execute()


def log_venue(venue: dict, status: str, detail: str | None = None) -> None:
    prefix = f"[{status}] {venue.get('name')} ({venue.get('website')})"
    if detail:
        print(f"{prefix} - {normalize_inline(detail)}")
    else:
        print(prefix)


def load_target_venues() -> list[dict]:
    result = (
        supabase.table("venues")
        .select("*")
        .not_.is_("website", "null")
        .is_("cheapest_lager_price_chf", "null")
        .limit(MAX_VENUES_PER_RUN)
        .execute()
    )
    return result.data or []


def main():
    venues = load_target_venues()
    session = build_requests_session()

    checked = 0
    prices_found = 0
    no_price_found = 0
    unreachable = 0
    errors = 0

    for venue in venues:
        checked += 1
        website = normalize_url(venue["website"])
        debug_dir = ensure_debug_dir(venue) if DEBUG_ARTIFACTS_ENABLED else None
        log_venue(venue, "CHECKING")

        try:
            crawl_result = crawl_site(website)
            html_docs = crawl_result.html_documents
            pdf_urls = crawl_result.pdf_urls
            image_urls = crawl_result.image_urls
            crawl_errors = crawl_result.errors
            extracted_docs, extraction_errors = build_extracted_documents(
                session,
                html_docs,
                pdf_urls,
                image_urls,
            )
            combined_text = build_combined_text(extracted_docs)
            allowed_source_urls = {document.source_url for document in extracted_docs}
            source_text_map = build_source_text_map(extracted_docs)

            all_errors = crawl_errors + extraction_errors

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "summary.json",
                    {
                        "venue_id": venue.get("id"),
                        "venue_name": venue.get("name"),
                        "website": website,
                    },
                )
                write_debug_json(debug_dir, "crawl.json", crawl_result.debug)
                write_debug_json(
                    debug_dir,
                    "extraction.json",
                    {
                        "html_document_count": len(html_docs),
                        "pdf_url_count": len(pdf_urls),
                        "image_url_count": len(image_urls),
                        "extracted_document_count": len(extracted_docs),
                        "crawl_errors": crawl_errors,
                        "extraction_errors": extraction_errors,
                    },
                )
                write_debug_text(
                    debug_dir,
                    "texts/extracted_documents.txt",
                    build_documents_dump(extracted_docs),
                )
                write_debug_text(
                    debug_dir,
                    "texts/combined_text.txt",
                    combined_text,
                )

            if not normalize_inline(combined_text):
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_no_text",
                            "reason": None,
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_no_text"),
                        ),
                    },
                )
                log_venue(venue, "NO_TEXT")
                continue

            candidates = extract_price_candidates(extracted_docs)
            clear_candidate = choose_clear_candidate(candidates)

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "regex_candidates.json",
                    serialize_price_candidates(candidates),
                )

            if clear_candidate:
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_price_found_regex",
                            "candidate": {
                                "beer_name": clear_candidate.beer_name,
                                "price_chf": clear_candidate.price_chf,
                                "volume_l": clear_candidate.volume_l,
                                "evidence": clear_candidate.evidence,
                                "source_url": clear_candidate.source_url,
                            },
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "cheapest_lager_name": clear_candidate.beer_name,
                        "cheapest_lager_price_chf": clear_candidate.price_chf,
                        "price_volume_l": 0.5,
                        "price_source": "website",
                        "price_updated_at": now_iso(),
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_price_found", clear_candidate.evidence),
                        ),
                    },
                )
                prices_found += 1
                log_venue(
                    venue,
                    "FOUND_REGEX",
                    f"{clear_candidate.beer_name} CHF {clear_candidate.price_chf:.2f} | source: {clear_candidate.source_url}",
                )
                continue

            model_result = run_extraction_model(venue, combined_text)
            model_ok = False
            rejection_reason = None
            if debug_dir and model_result is not None:
                write_debug_json(debug_dir, "model_result.json", model_result)
            if model_result:
                model_ok, rejection_reason = validate_model_result(
                    model_result,
                    combined_text,
                    allowed_source_urls,
                    source_text_map,
                )

            if model_result and model_ok:
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_price_found_model",
                            "model_result": model_result,
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "cheapest_lager_name": model_result.get("beer_name"),
                        "cheapest_lager_price_chf": model_result.get("price"),
                        "price_volume_l": 0.5,
                        "price_source": "website",
                        "price_updated_at": now_iso(),
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_price_found", model_result.get("evidence")),
                        ),
                    },
                )
                prices_found += 1
                log_venue(
                    venue,
                    "FOUND_MODEL",
                    (
                        f"{model_result.get('beer_name')} CHF "
                        f"{float(model_result.get('price')):.2f} | "
                        f"source: {model_result.get('source_url')} | "
                        f"evidence: {model_result.get('evidence')}"
                    ),
                )
                continue

            reason = rejection_reason
            if not reason and model_result:
                reason = model_result.get("reason")
            if not reason and all_errors:
                reason = all_errors[0]

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "checked_no_price",
                        "reason": reason,
                        "validation_rejection_reason": rejection_reason,
                        "crawl_errors": crawl_errors,
                        "extraction_errors": extraction_errors,
                    },
                )

            update_venue(
                venue["id"],
                {
                    "website_checked_at": now_iso(),
                    "notes": append_note(
                        venue.get("notes"),
                        status_note("checked_no_price", reason),
                    ),
                },
            )
            no_price_found += 1
            log_venue(venue, "NO_PRICE", reason)

        except requests.RequestException as error:
            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "website_unreachable",
                        "reason": str(error),
                    },
                )
            update_venue(
                venue["id"],
                {
                    "website_checked_at": now_iso(),
                    "notes": append_note(
                        venue.get("notes"),
                        status_note("website_unreachable", str(error)),
                    ),
                },
            )
            unreachable += 1
            log_venue(venue, "UNREACHABLE", str(error))
        except Exception as error:
            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "error",
                        "reason": str(error),
                    },
                )
            errors += 1
            log_venue(venue, "ERROR", str(error))

    print("Website check summary")
    print(f"Venues checked: {checked}")
    print(f"Prices found: {prices_found}")
    print(f"No price found: {no_price_found}")
    print(f"Unreachable: {unreachable}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
