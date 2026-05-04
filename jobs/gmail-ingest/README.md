# gmail-ingest

Manual Gmail ingestion for venue beer prices.

Flow:

```text
Gmail inbox -> Gmail API -> OpenAI structured extraction -> Supabase venues -> archive email
```

The job only runs when explicitly started. There is no webhook, Pub/Sub
subscription, or Gmail watch in this package.

## Required Environment Variables

The job reads the monorepo root `.env` file.

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
OPENAI_API_KEY=...
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
```

Optional:

```bash
GMAIL_USER_ID=me
GMAIL_MANUAL_MAX_MESSAGES=20
OPENAI_MODEL=gpt-4.1
```

Do not commit real secrets.

## Install

From the repo root:

```bash
cd jobs/gmail-ingest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Get a Local Gmail Refresh Token

Create an OAuth desktop client in Google Cloud with Gmail API enabled, then run:

```bash
python scripts/get_gmail_refresh_token.py
```

Copy the printed refresh token into the root `.env`.

## Run Manually

```bash
python scripts/run_manual_ingest.py
```

The job scans current Gmail inbox messages, extracts beer prices, updates a
matching `venues` row, and archives each processed message. It matches venues by
sender email first, then by extracted business name. If no venue matches, the
email is archived without changing the database.

For matched venues, Gmail may overwrite:

```text
cheapest_lager_name
cheapest_lager_price_chf
price_volume_l
```

It also refreshes:

```text
price_source
price_updated_at
last_outreach_at
outreach_count
email_bounce_status
updated_at
```

No Gmail-specific database columns are required.

## Tests

```bash
python -m unittest discover -s tests
```
