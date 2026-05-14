# Web App

This package contains the Stange Check frontend built with Vite and React.

## What It Does

- Shows venues and beer prices in the browser.
- Uses Supabase REST data when browser env vars are present.
- Falls back to bundled mock data if Supabase browser config is missing or the fetch fails.
- Uses Mapbox for the live map view when a Mapbox token is configured.

## Setup

The app reads environment variables from the monorepo root `.env`.

Start by creating that file from the root `.env.example`, then set the values you need for frontend development:

- `VITE_MAPBOX_ACCESS_TOKEN` enables the live map.
- `VITE_SUPABASE_URL` points the browser at your Supabase project.
- `VITE_SUPABASE_ANON_KEY` is the browser-safe Supabase publishable key.

If the Supabase browser variables are not set, the UI still starts and uses mock venue data.

## Run Locally

```bash
cd apps/web
npm install
npm run dev
```

Vite will print the local development URL in the terminal.

## Other Commands

```bash
npm run build
npm run preview
```

- `build` creates a production build.
- `preview` serves the built app locally for a quick check.
