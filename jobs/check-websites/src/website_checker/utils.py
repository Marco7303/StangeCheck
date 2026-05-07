import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .config import KEYWORDS, WHITESPACE_PATTERN


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_inline(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


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


def keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(1 for keyword in KEYWORDS if keyword in lowered)
