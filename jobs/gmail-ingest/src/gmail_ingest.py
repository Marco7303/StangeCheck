import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parents[3]
if load_dotenv:
    load_dotenv(dotenv_path=REPO_ROOT / ".env")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
MAX_EMAIL_TEXT_CHARS = 20000


@dataclass
class BeerPriceExtraction:
    found: bool
    business_name: str | None
    beer_type: str | None
    price: float | None
    currency: str | None
    volume: str | None
    confidence: float


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_header(headers: list[dict[str, str]], name: str) -> str | None:
    lowered = name.lower()
    for header in headers:
        if header.get("name", "").lower() == lowered:
            return header.get("value")
    return None


def decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def collect_plain_text_parts(payload: dict[str, Any]) -> list[str]:
    mime_type = payload.get("mimeType")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return [decode_base64url(body_data).decode("utf-8", errors="replace")]

    parts: list[str] = []
    for part in payload.get("parts") or []:
        parts.extend(collect_plain_text_parts(part))
    return parts


def strip_html(value: str) -> str:
    import re

    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n", value)
    value = re.sub(r"(?s)<.*?>", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def collect_html_parts(payload: dict[str, Any]) -> list[str]:
    mime_type = payload.get("mimeType")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/html" and body_data:
        html = decode_base64url(body_data).decode("utf-8", errors="replace")
        return [strip_html(html)]

    parts: list[str] = []
    for part in payload.get("parts") or []:
        parts.extend(collect_html_parts(part))
    return parts


def extract_plain_text_email_body(message: dict[str, Any]) -> str:
    payload = message.get("payload") or {}
    text_parts = collect_plain_text_parts(payload)
    if not text_parts:
        text_parts = collect_html_parts(payload)

    text = "\n\n".join(part.strip() for part in text_parts if part.strip())
    return text[:MAX_EMAIL_TEXT_CHARS]


def extract_headers(message: dict[str, Any]) -> dict[str, str | None]:
    headers = message.get("payload", {}).get("headers", [])
    return {
        "subject": normalize_header(headers, "Subject"),
        "from": normalize_header(headers, "From"),
        "date": normalize_header(headers, "Date"),
    }


def extract_email_address(value: str | None) -> str | None:
    if not value:
        return None
    _, address = parseaddr(value)
    return address.lower() or None


def build_gmail_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def build_supabase_client():
    from supabase import create_client

    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def build_openai_client():
    from openai import OpenAI

    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


class GmailBeerPriceProcessor:
    def __init__(self, gmail_service=None, supabase_client=None, openai_client=None):
        self.gmail = gmail_service or build_gmail_service()
        self.supabase = supabase_client or build_supabase_client()
        self.openai = openai_client or build_openai_client()
        self.user_id = os.environ.get("GMAIL_USER_ID", "me")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4.1")
        self.max_messages = int(os.environ.get("GMAIL_MANUAL_MAX_MESSAGES", "20"))

    def process_inbox(self) -> dict[str, int]:
        message_ids = self.list_inbox_message_ids()
        processed = 0
        updated = 0

        for message_id in message_ids:
            processed += 1
            if self.process_message(message_id):
                updated += 1

        return {
            "processed": processed,
            "updated": updated,
        }

    def list_inbox_message_ids(self) -> list[str]:
        request = (
            self.gmail.users()
            .messages()
            .list(
                userId=self.user_id,
                q="in:inbox",
                maxResults=self.max_messages,
            )
        )

        message_ids: list[str] = []
        while request is not None:
            response = request.execute()
            for message in response.get("messages", []):
                message_id = message.get("id")
                if message_id:
                    message_ids.append(message_id)
            request = (
                self.gmail.users()
                .messages()
                .list_next(request, response)
            )

        return message_ids

    def fetch_message(self, message_id: str) -> dict[str, Any]:
        return (
            self.gmail.users()
            .messages()
            .get(userId=self.user_id, id=message_id, format="full")
            .execute()
        )

    def process_message(self, message_id: str) -> bool:
        message = self.fetch_message(message_id)
        if "INBOX" not in set(message.get("labelIds") or []):
            return False

        body_text = extract_plain_text_email_body(message)
        headers = extract_headers(message)

        extraction = self.extract_beer_price(body_text, headers)
        if not extraction.found:
            self.archive_message(message_id)
            return False

        updated = self.update_venue_beer_price(
            message_id,
            message,
            body_text,
            headers,
            extraction,
        )
        self.archive_message(message_id)
        return updated

    def extract_beer_price(
        self,
        body_text: str,
        headers: dict[str, str | None],
    ) -> BeerPriceExtraction:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "found": {"type": "boolean"},
                "business_name": {"type": ["string", "null"]},
                "beer_type": {"type": ["string", "null"]},
                "price": {"type": ["number", "null"]},
                "currency": {"type": ["string", "null"]},
                "volume": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": [
                "found",
                "business_name",
                "beer_type",
                "price",
                "currency",
                "volume",
                "confidence",
            ],
        }
        response = self.openai.chat.completions.create(
            model=self.openai_model,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "beer_price_extraction",
                    "strict": True,
                    "schema": schema,
                },
            },
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract beer price data from email text. Return only data "
                        "supported by the email. If uncertain, set found=false."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Subject: {headers.get('subject') or ''}\n"
                        f"From: {headers.get('from') or ''}\n\n"
                        "Find a beer price in this email. Prefer lager/stange/draft "
                        "beer prices. Use the exact currency and volume shown when "
                        "available.\n\n"
                        f"{body_text[:MAX_EMAIL_TEXT_CHARS]}"
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return BeerPriceExtraction(
            found=bool(data.get("found")),
            business_name=data.get("business_name"),
            beer_type=data.get("beer_type"),
            price=data.get("price"),
            currency=data.get("currency"),
            volume=data.get("volume"),
            confidence=float(data.get("confidence") or 0),
        )

    def update_venue_beer_price(
        self,
        message_id: str,
        message: dict[str, Any],
        body_text: str,
        headers: dict[str, str | None],
        extraction: BeerPriceExtraction,
    ) -> bool:
        venue = self.find_matching_venue(headers, extraction)
        if not venue:
            return False

        payload = self.build_venue_price_payload(
            venue,
            extraction,
        )
        self.supabase.table("venues").update(payload).eq("id", venue["id"]).execute()
        return True

    def find_matching_venue(
        self,
        headers: dict[str, str | None],
        extraction: BeerPriceExtraction,
    ) -> dict[str, Any] | None:
        sender_email = extract_email_address(headers.get("from"))
        if sender_email:
            result = (
                self.supabase.table("venues")
                .select("*")
                .eq("email", sender_email)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]

        business_name = extraction.business_name
        if business_name:
            escaped = re.sub(r"[%_]", "", business_name).strip()
            if escaped:
                result = (
                    self.supabase.table("venues")
                    .select("*")
                    .ilike("name", f"%{escaped}%")
                    .limit(1)
                    .execute()
                )
                if result.data:
                    return result.data[0]

        return None

    def build_venue_price_payload(
        self,
        venue: dict[str, Any],
        extraction: BeerPriceExtraction,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if extraction.beer_type is not None:
            payload["cheapest_lager_name"] = extraction.beer_type
        if extraction.price is not None:
            payload["cheapest_lager_price_chf"] = extraction.price

        volume_l = self.parse_volume_l(extraction.volume)
        if volume_l is not None:
            payload["price_volume_l"] = volume_l

        timestamp = now_iso()
        payload["price_source"] = "gmail"
        payload["price_updated_at"] = timestamp
        payload["last_outreach_at"] = timestamp
        payload["outreach_count"] = (venue.get("outreach_count") or 0) + 1
        payload["email_bounce_status"] = "replied"
        payload["updated_at"] = timestamp

        return payload

    def parse_volume_l(self, value: str | None) -> float | None:
        if not value:
            return None
        normalized = value.lower().replace(",", ".")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(l|dl|cl|ml)\b", normalized)
        if not match:
            return None

        amount = float(match.group(1))
        unit = match.group(2)
        if unit == "l":
            return amount
        if unit == "dl":
            return amount / 10
        if unit == "cl":
            return amount / 100
        if unit == "ml":
            return amount / 1000
        return None

    def archive_message(self, message_id: str) -> None:
        (
            self.gmail.users()
            .messages()
            .modify(
                userId=self.user_id,
                id=message_id,
                body={"removeLabelIds": ["INBOX"]},
            )
            .execute()
        )
