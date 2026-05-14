import base64
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parents[3]
if load_dotenv:
    load_dotenv(dotenv_path=REPO_ROOT / ".env")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
DEFAULT_MAX_VENUES = 20


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


class GmailOutreachProcessor:
    def __init__(self, gmail_service=None, supabase_client=None):
        self.gmail = gmail_service or build_gmail_service()
        self.supabase = supabase_client or build_supabase_client()
        self.user_id = os.environ.get("GMAIL_USER_ID", "me")
        self.sender_email = os.environ.get("GMAIL_SENDER_EMAIL")
        self.sender_name = os.environ.get("GMAIL_SENDER_NAME", "Reto")
        self.max_venues = int(
            os.environ.get("GMAIL_OUTREACH_MAX_VENUES", str(DEFAULT_MAX_VENUES))
        )
        self.include_already_contacted = env_flag(
            "GMAIL_OUTREACH_INCLUDE_ALREADY_CONTACTED",
            False,
        )
        self.dry_run = env_flag("GMAIL_OUTREACH_DRY_RUN", False)

    def run(self) -> dict[str, int]:
        venues = self.load_target_venues()
        sent = 0
        skipped = 0
        would_send = 0

        for venue in venues:
            if not self.valid_email(venue.get("email")):
                skipped += 1
                continue

            if self.dry_run:
                would_send += 1
                continue

            self.send_outreach_email(venue)
            self.mark_outreach_sent(venue)
            sent += 1

        return {
            "selected": len(venues),
            "sent": sent,
            "would_send": would_send,
            "skipped": skipped,
            "dry_run": int(self.dry_run),
        }

    def load_target_venues(self) -> list[dict[str, Any]]:
        query = (
            self.supabase.table("venues")
            .select(
                "id,name,email,cheapest_lager_price_chf,last_outreach_at,outreach_count"
            )
            .is_("cheapest_lager_price_chf", "null")
            .not_.is_("email", "null")
            .order("outreach_count", desc=False, nullsfirst=True)
            .order("name")
            .limit(self.max_venues)
        )

        if not self.include_already_contacted:
            query = query.is_("last_outreach_at", "null")

        result = query.execute()
        return result.data or []

    def send_outreach_email(self, venue: dict[str, Any]) -> dict[str, Any]:
        raw_message = self.build_raw_message(venue)
        return (
            self.gmail.users()
            .messages()
            .send(userId=self.user_id, body={"raw": raw_message})
            .execute()
        )

    def build_raw_message(self, venue: dict[str, Any]) -> str:
        message = EmailMessage()
        message["To"] = venue["email"]
        if self.sender_email:
            message["From"] = f"{self.sender_name} <{self.sender_email}>"
        message["Subject"] = "Kurze Frage zum Bierpreis"
        message.set_content(self.build_email_body(venue))

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        return encoded.rstrip("=")

    def build_email_body(self, venue: dict[str, Any]) -> str:
        venue_name = venue.get("name") or "Ihr Lokal"
        return (
            f"Guten Tag {venue_name} Team\n\n"
            "Mein Name ist Reto und ich sammle fuer ein Schulprojekt aktuelle "
            "Bierpreise in der Umgebung.\n\n"
            "Koennten Sie mir kurz mitteilen, was bei Ihnen aktuell ein 0.5 l "
            "Bier vom Fass kostet? Falls moeglich gerne mit Biername und Preis "
            "in CHF.\n\n"
            "Vielen Dank und freundliche Gruesse\n"
            "Reto"
        )

    def mark_outreach_sent(self, venue: dict[str, Any]) -> None:
        payload = self.build_outreach_payload(venue)
        self.supabase.table("venues").update(payload).eq("id", venue["id"]).execute()

    def build_outreach_payload(self, venue: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_iso()
        return {
            "last_outreach_at": timestamp,
            "outreach_count": (venue.get("outreach_count") or 0) + 1,
            "email_bounce_status": "sent",
            "updated_at": timestamp,
        }

    def valid_email(self, value: str | None) -> bool:
        if not value:
            return False
        stripped = value.strip()
        return "@" in stripped and "." in stripped.rsplit("@", 1)[-1]
