# gmail-outreach

Manual Gmail outreach for venues without beer prices.

Flow:

```text
Supabase venues without prices -> Gmail API -> venue inbox -> Supabase outreach fields
```

The job only runs when explicitly started. It does not schedule itself, watch the
database, or send webhooks.

## Required Environment Variables

The job reads the monorepo root `.env` file.

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
```

Optional:

```bash
GMAIL_USER_ID=me
GMAIL_SENDER_EMAIL=hello@example.com
GMAIL_SENDER_NAME=Reto
GMAIL_OUTREACH_MAX_VENUES=20
GMAIL_OUTREACH_DRY_RUN=0
GMAIL_OUTREACH_INCLUDE_ALREADY_CONTACTED=0
```

By default the job only contacts venues where:

- `email` is present
- `cheapest_lager_price_chf` is `null`
- `last_outreach_at` is `null`

Set `GMAIL_OUTREACH_INCLUDE_ALREADY_CONTACTED=1` to include venues that were
already contacted.

## Install

From the repo root:

```bash
cd jobs/gmail-outreach
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Gmail Token

This job can use the same Gmail OAuth credentials and refresh token as
`jobs/gmail-ingest` when the token was generated after the send scope was added.

If you need a token, run:

```bash
cd jobs/gmail-ingest
python scripts/get_gmail_refresh_token.py
```

Copy the printed refresh token into the root `.env`.

If you already generated a token before adding this job, generate a fresh one so
Google grants the Gmail send permission too.

## Run Manually

```bash
python scripts/run_manual_outreach.py
```

To preview the selected venues without sending email or updating Supabase:

```bash
GMAIL_OUTREACH_DRY_RUN=1 python scripts/run_manual_outreach.py
```

## Email Content

The email is written from Reto for a school project. It asks the venue for the
current price of a 0.5 l draft beer and requests the beer name and CHF price
when possible.

## Supabase Updates

After each successful send, the job updates:

```text
last_outreach_at
outreach_count
email_bounce_status
updated_at
```
