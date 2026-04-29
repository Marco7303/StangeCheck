# Architecture

Planned POC flow:

```text
OSM/Overpass -> import job -> Supabase -> web frontend
```

## Components

- `jobs/import-osm` will fetch and normalize source venue data.
- `supabase` will store the canonical venue records and schema history.
- `apps/web` will read that data and present it in the frontend.

## Intent

The import job pulls venue data from OSM/Overpass, validates and reshapes it, then writes it into Supabase. The web frontend reads from that database-backed source rather than from static mock data once the integration is in place.
