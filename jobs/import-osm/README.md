# import-osm

This job imports venue candidates from OSM/Overpass into Supabase.

Current behavior:

- query Overpass for Zug venues
- filter `amenity=pub|bar|biergarten|nightclub`
- include `amenity=restaurant` with `bar=yes`
- include `brewery=*` venues
- keep only venues that have a `name` and either an email or website
- insert new venues into the `venues` table in Supabase
- for existing venues, only update fields where OSM provides a non-empty changed value
- leave existing stored values untouched when the incoming OSM value is empty

## Python setup

From the repo root:

```bash
cd jobs/import-osm
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Required environment variables

The script reads the monorepo root `.env` file.

Required variables:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

Do not commit real secrets.

## Run

From `jobs/import-osm` with the virtual environment activated:

```bash
python src/import_osm.py
```

## Notes

- The script is written so it can be run from any working directory and still resolve the root `.env`.
- It has not been fully end-to-end verified here against live Overpass and Supabase because that would require network access and real credentials.
- It assumes a Supabase table named `venues` with fields compatible with:
  `name`, `address`, `city`, `canton`, `country`, `lat`, `lng`, `email`, `website`, `osm_type`, `osm_id`, `osm_tags`, `source`, `discovery_status`
- It also assumes a unique conflict target on `osm_type,osm_id` for the upsert.
