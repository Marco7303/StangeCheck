import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

# Load the monorepo root .env regardless of the current working directory.
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=REPO_ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

OVERPASS_QUERY = """
[out:json][timeout:60];
area["boundary"="administrative"]["name"="Zug"]["admin_level"="8"]->.searchArea;

(
  node["amenity"~"^(pub|bar|food_court|biergarten|nightclub)$"](area.searchArea);
  way["amenity"~"^(pub|bar|food_court|biergarten|nightclub)$"](area.searchArea);
  relation["amenity"~"^(pub|bar|food_court|biergarten|nightclub)$"](area.searchArea);

  node["brewery"](area.searchArea);
  way["brewery"](area.searchArea);
  relation["brewery"](area.searchArea);
);

out center tags;
"""

def build_address(tags: dict) -> str | None:
    parts = [
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
        tags.get("addr:postcode"),
        tags.get("addr:city"),
    ]
    address = ", ".join([p for p in parts if p])
    return address or None


def main():
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": OVERPASS_QUERY},
        headers={
            "Accept": "application/json",
            "User-Agent": "stangecheck-import-osm/0.0.1",
        },
        timeout=90,
    )

    if not response.ok:
        print("Overpass request failed.")
        print(f"Status: {response.status_code}")
        body = response.text.strip()
        if body:
            print("Response body:")
            print(body)
        response.raise_for_status()

    response.raise_for_status()

    elements = response.json().get("elements", [])

    inserted = 0
    skipped = 0

    for el in elements:
        tags = el.get("tags", {})

        name = tags.get("name")
        email = tags.get("email") or tags.get("contact:email")
        website = tags.get("website") or tags.get("contact:website")

        if not name or not (email or website):
            skipped += 1
            continue

        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")

        row = {
            "name": name,
            "address": build_address(tags),
            "city": tags.get("addr:city") or "Zug",
            "canton": "ZG",
            "country": "CH",
            "lat": lat,
            "lng": lng,
            "email": email,
            "website": website,
            "osm_type": el.get("type"),
            "osm_id": el.get("id"),
            "osm_tags": tags,
            "source": "osm",
            "discovery_status": "discovered",
        }

        supabase.table("venues").upsert(
            row,
            on_conflict="osm_type,osm_id",
        ).execute()

        inserted += 1

    print(f"Import finished. Inserted/updated: {inserted}. Skipped: {skipped}.")


if __name__ == "__main__":
    main()
