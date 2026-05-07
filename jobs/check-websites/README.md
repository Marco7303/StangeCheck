# check-websites

This job checks venue websites already stored in Supabase and tries to extract
the cheapest valid 0.5L lager beer price from messy restaurant/bar websites.

The pipeline is intentionally split into two parts:

1. deterministic interactive crawling and content reading
2. LLM reasoning over extracted text only

That means the model does not browse, click links, or fetch URLs itself.

## What This Job Does

- selects up to 20 venues per run from the existing `venues` table
- only checks venues where `website` is present and `cheapest_lager_price_chf` is still `null`
- uses Playwright to render the homepage like a real user
- scrolls the page and allows JS-driven content to load
- scans links, buttons, `role="button"` elements, and `onclick` elements
- clicks keyword-relevant controls to reveal hidden menu sections, dropdowns, modals, and asset links
- re-scans the DOM after each interaction
- collects same-site HTML pages plus linked PDFs and linked images
- extracts text from:
  - visible HTML
  - PDF files
  - scanned PDFs via OCR fallback
  - linked menu images via OCR
- preserves source boundaries and line structure as much as possible
- tries a deterministic regex pass first
- only calls OpenAI if deterministic extraction is not clear
- writes successful prices back into the existing `venues` table

## Required Environment Variables

The script reads the monorepo root `.env` file.

Required variables:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
OPENAI_API_KEY=...
```

Optional overrides:

```bash
OPENAI_MODEL=gpt-4.1
OCR_FALLBACK_MODEL=gpt-4.1
TESSERACT_LANG=deu+eng
```

Do not commit real secrets.

## Install

From the repo root:

```bash
cd jobs/check-websites
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Recommended for OCR quality:

- install the local `tesseract` binary
- install German and English language packs if available

If Tesseract is not available, the job falls back to OpenAI-based image
transcription for linked images and scanned PDFs.

## Run Manually

From `jobs/check-websites` with the virtual environment activated:

```bash
python src/check_websites.py
```

## How The Extraction Works

1. Playwright loads the site and simulates a user session.
2. Keyword-relevant buttons and controls are clicked to reveal hidden content.
3. The crawler collects:
   - visible HTML text
   - linked same-site pages
   - linked PDF files
   - linked image files
4. PDFs and images are converted into text.
5. All extracted text is combined into labeled blocks such as:

```text
[HTML: https://example.com/menu]
...

[PDF: https://example.com/drinks.pdf]
...

[IMAGE: https://example.com/bierkarte.jpg]
...
```

6. A deterministic regex pass looks for clear 0.5L lager candidates first.
7. If regex is not decisive, OpenAI gets the extracted text and returns strict JSON.
8. The result is validated before updating Supabase.

## Important Constraints

- max 20 venues per run
- no external search
- no guessed URLs
- no browser automation by the model
- no direct URL browsing by the model
- if the price/beer/volume pairing is ambiguous, the job should prefer `found=false`

## Notes

- Playwright is required because some menus only appear after JS rendering or user interaction.
- OCR is necessary because many menus are images or scanned PDFs.
- One failing website should not stop the rest of the run.
- The job stores short run context in `notes` and marks `website_checked_at` when a run completes.
