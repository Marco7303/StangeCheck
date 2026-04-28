# Stange Check Monorepo

This repository is now structured as a small monorepo.

## Layout

- `apps/web` contains the Vite frontend.
- `jobs/import-osm` will contain the OSM to Supabase import job.
- `supabase/migrations` contains database schema changes.
- `docs` contains lightweight project documentation.

## Frontend

The current frontend lives in `apps/web` and should behave exactly as before.

Run it with:

```bash
cd apps/web
npm install
npm run dev
```

The frontend reads environment variables from the monorepo root `.env`.

## Planned Data Flow

The planned POC architecture is:

```text
OSM/Overpass -> import job -> Supabase -> web frontend
```

See `docs/architecture.md` for a short overview.

## Secrets

Secrets must never be committed.

- Keep local secrets in untracked `.env` files only.
- Use the monorepo root `.env` for local configuration.
- Commit only the root `.env.example`.
