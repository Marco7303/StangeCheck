alter table public.venues
  add column if not exists last_outreach_at timestamptz,
  add column if not exists outreach_count integer default 0,
  add column if not exists email_bounce_status text;
