alter table public.venues
  add column if not exists user_flagged boolean default false;
