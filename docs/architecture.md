# Architecture

Planned POC flow:

```text
OSM/Overpass -> import job -> Supabase -> web frontend
Gmail inbox -> manual Gmail ingest -> OpenAI -> Supabase
Supabase venues without prices -> manual Gmail outreach -> venue inbox
```

## Components

- `jobs/import-osm` will fetch and normalize source venue data.
- `jobs/gmail-ingest` scans the Gmail inbox when run manually, extracts beer
  prices from email text, updates matching venue rows in Supabase, and archives
  processed messages.
- `jobs/gmail-outreach` scans Supabase when run manually, sends venues without
  prices a prewritten Gmail request for their 0.5 l draft beer price, and marks
  outreach metadata on the venue row.
- `supabase` will store the canonical venue records and schema history.
- `apps/web` will read that data and present it in the frontend.

## Intent

The import job pulls venue data from OSM/Overpass, validates and reshapes it, then writes it into Supabase. The web frontend reads from that database-backed source rather than from static mock data once the integration is in place.
