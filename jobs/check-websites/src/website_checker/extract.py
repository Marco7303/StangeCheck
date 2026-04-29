import base64
import io
import re
import shutil

import pdfplumber
import requests
from PIL import Image

from .config import (
    BARE_PRICE_PATTERN,
    LAGER_TERMS,
    MAX_MODEL_TEXT_CHARS,
    MAX_OCR_PDF_PAGES,
    OCR_FALLBACK_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    TESSERACT_LANG,
    USER_AGENT,
    VOLUME_PATTERN,
    openai_client,
)
from .models import ExtractedDocument, HtmlDocument, PriceCandidate
from .utils import keyword_score, normalize_inline

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


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


def build_extracted_documents(
    session: requests.Session,
    html_docs: list[HtmlDocument],
    pdf_urls: list[str],
    image_urls: list[str],
) -> tuple[list[ExtractedDocument], list[str]]:
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


def format_price_variants(value: float) -> tuple[str, str, str, str]:
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
    name = re.sub(
        r"\b(?:0[.,]5\s*l|5\s*dl|50\s*cl|500\s*ml|30\s*cl|33\s*cl|35\s*cl|40\s*cl)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"\b\d{1,2}(?:[.,]\d{1,2})?\b", "", name)
    return normalize_inline(name)


def document_priority(document: ExtractedDocument) -> tuple[int, int]:
    from .crawl import url_priority

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

            from .config import PRICE_PATTERN

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
                (
                    entry
                    for entry in [line] + next_lines
                    if re.search(r"\b50\s*cl\b|\b5\s*dl\b|\b0[.,]5\s*l\b|\b500\s*ml\b", entry, re.IGNORECASE)
                ),
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
        chunks.append(f"[{document.source_type.upper()}: {document.source_url}]\n{document.text or ''}")
    return "\n\n".join(chunks)


def build_source_text_map(documents: list[ExtractedDocument]) -> dict[str, str]:
    return {
        document.source_url: normalize_inline(document.text)
        for document in documents
        if document.text
    }
