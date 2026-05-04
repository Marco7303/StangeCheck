# Supabase

This directory holds Supabase-related project assets.

- `migrations/` contains database schema changes

## Current Tables Touched By Migrations

- `venues` stores venue records imported from OSM and enriched by website checks.

## Gmail Ingest

Gmail ingest uses the existing `venues` columns. It updates extracted price and
email status fields such as `cheapest_lager_name`, `cheapest_lager_price_chf`,
`price_volume_l`, `price_source`, `price_updated_at`, `last_outreach_at`,
`outreach_count`, `email_bounce_status`, and `updated_at`.

Do not commit secrets or service-role credentials here.
