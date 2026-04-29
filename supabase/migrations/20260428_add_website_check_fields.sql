alter table public.venues
  add column if not exists website_checked_at timestamptz,
  add column if not exists website_check_status text,
  add column if not exists website_price_evidence text,
  add column if not exists cheapest_lager_name text,
  add column if not exists cheapest_lager_price_chf numeric,
  add column if not exists price_volume_l numeric,
  add column if not exists price_source text,
  add column if not exists price_updated_at timestamptz,
  add column if not exists needs_human_review boolean default false,
  add column if not exists notes text;
