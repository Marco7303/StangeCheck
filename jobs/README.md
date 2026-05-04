# Jobs

This directory contains backend-style jobs and services that feed Supabase.

## Packages

- `import-osm` imports venue candidates from OSM/Overpass into Supabase.
- `check-websites` crawls known venue websites and extracts 0.5L lager prices.
- `gmail-ingest` scans Gmail manually, extracts beer prices from emails, updates
  matching `venues` rows, and archives processed Gmail messages.

Each package has its own `README.md`, `requirements.txt`, and setup/run notes.

## Environment

Jobs read configuration from the monorepo root `.env`. Keep real credentials
there only, and keep `.env.example` as the committed template.
