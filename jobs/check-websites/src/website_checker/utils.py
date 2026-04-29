import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import DEBUG_ARTIFACTS_ROOT, KEYWORDS, WHITESPACE_PATTERN
from .models import PriceCandidate


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


def keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(1 for keyword in KEYWORDS if keyword in lowered)
