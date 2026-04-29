from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import (
    IMAGE_EXTENSIONS,
    KEYWORDS,
    MAX_BLOCK_TEXT_CHARS,
    MAX_BODY_TEXT_CHARS,
    MAX_CRAWL_DEPTH,
    MAX_HTML_PAGES,
    MAX_IMAGE_FILES,
    MAX_INTERACTIONS_PER_PAGE,
    MAX_PDF_FILES,
    PAGE_TIMEOUT_MS,
    PDF_EXTENSIONS,
    SCROLL_PAUSE_SECONDS,
    SCROLL_STEPS,
    USER_AGENT,
)
from .models import CrawlResult, CrawlTask, HtmlDocument
from .utils import keyword_score, normalize_inline, same_site_family, strip_fragment


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
    path = urlparse(image_url).path.lower()
    if path.endswith(".svg"):
        return True
    if "emoji" in path:
        return True
    if not same_site_family(page_url, image_url):
        return True
    return False


def url_priority(url: str) -> int:
    kind = classify_asset(url)
    base = keyword_score(url)
    lowered_path = urlparse(url).path.lower()
    if kind == "pdf":
        base += 4
    elif kind == "image":
        base += 3
    if any(
        term in lowered_path
        for term in ["/menu", "/bier", "/beer", "/drinks", "/getraenke", "/getränke", "/barkarte", "/speisekarte"]
    ):
        base += 8
    if any(term in lowered_path for term in ["/category/", "/tag/", "/author/", "/page/"]):
        base -= 6
    if __import__("re").search(r"/20\d{2}/\d{2}/", lowered_path):
        base -= 8
    filename = Path(lowered_path).name
    if any(term in filename for term in ["bier", "beer", "cider", "menu", "karte", "drinks", "getraenke", "getränke"]):
        base += 6
    if any(term in filename for term in ["logo", "team", "banner", "hero", "award", "winner", "emoji"]):
        base -= 6
    return base


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
        "ranked_html_candidates": [{"url": url, "score": score} for url, score in ranked_html],
        "ranked_pdf_candidates": [{"url": url, "score": score} for url, score in ranked_pdfs],
        "ranked_image_candidates": [{"url": url, "score": score} for url, score in ranked_images],
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
