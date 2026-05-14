![Stange Check logo](apps/web/src/assets/logo-light.svg)

# Stange Check

Small monorepo for the Stange Check frontend and the data jobs that feed it.

Stange Check helps people compare beer prices around them so they can find more affordable options quickly. The project was built around a simple idea: beer prices in Switzerland have been rising fast, and it should be easier to see where a reasonably priced `0.5L` lager is still available.

Live app: https://stange-check.vercel.app/

## Project Map

- [apps/web/README.md](./apps/web/README.md) explains how to install, configure, and run the web app.
- [jobs/README.md](./jobs/README.md) gives the backend jobs overview.
- [jobs/import-osm/README.md](./jobs/import-osm/README.md) covers importing venues from OSM/Overpass into Supabase.
- [jobs/check-websites/README.md](./jobs/check-websites/README.md) covers website-based price extraction.
- [jobs/gmail-ingest/README.md](./jobs/gmail-ingest/README.md) covers manual Gmail ingestion into Supabase.
- [jobs/gmail-outreach/README.md](./jobs/gmail-outreach/README.md) covers manual outreach to venues without prices.

## Repo Layout

- `apps/web` contains the Vite + React frontend.
- `jobs` contains the Python jobs and their package-specific documentation.
- `.env.example` is the committed template for local configuration.

## Data Flow

```text
OSM/Overpass -> import job -> Supabase -> web frontend
Venue websites -> website checker -> Supabase -> web frontend
Gmail inbox -> manual Gmail ingest -> OpenAI -> Supabase
Supabase venues without prices -> manual Gmail outreach -> venue inbox
```

## Local Config

Keep real secrets in an untracked root `.env` file and use `.env.example` as the template.
