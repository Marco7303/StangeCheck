from .config import MAX_VENUES_PER_RUN, supabase
from .utils import normalize_inline


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
