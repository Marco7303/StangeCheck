import requests

from .config import DEBUG_ARTIFACTS_ENABLED
from .crawl import crawl_site
from .extract import (
    build_combined_text,
    build_documents_dump,
    build_extracted_documents,
    build_requests_session,
    build_source_text_map,
    choose_clear_candidate,
    extract_price_candidates,
)
from .llm import run_extraction_model, validate_model_result
from .persistence import load_target_venues, log_venue, update_venue
from .utils import (
    append_note,
    ensure_debug_dir,
    normalize_inline,
    normalize_url,
    now_iso,
    serialize_price_candidates,
    status_note,
    write_debug_json,
    write_debug_text,
)


def main():
    venues = load_target_venues()
    session = build_requests_session()

    checked = 0
    prices_found = 0
    no_price_found = 0
    unreachable = 0
    errors = 0

    for venue in venues:
        checked += 1
        website = normalize_url(venue["website"])
        debug_dir = ensure_debug_dir(venue) if DEBUG_ARTIFACTS_ENABLED else None
        log_venue(venue, "CHECKING")

        try:
            crawl_result = crawl_site(website)
            html_docs = crawl_result.html_documents
            pdf_urls = crawl_result.pdf_urls
            image_urls = crawl_result.image_urls
            crawl_errors = crawl_result.errors
            extracted_docs, extraction_errors = build_extracted_documents(
                session,
                html_docs,
                pdf_urls,
                image_urls,
            )
            combined_text = build_combined_text(extracted_docs)
            allowed_source_urls = {document.source_url for document in extracted_docs}
            source_text_map = build_source_text_map(extracted_docs)

            all_errors = crawl_errors + extraction_errors

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "summary.json",
                    {
                        "venue_id": venue.get("id"),
                        "venue_name": venue.get("name"),
                        "website": website,
                    },
                )
                write_debug_json(debug_dir, "crawl.json", crawl_result.debug)
                write_debug_json(
                    debug_dir,
                    "extraction.json",
                    {
                        "html_document_count": len(html_docs),
                        "pdf_url_count": len(pdf_urls),
                        "image_url_count": len(image_urls),
                        "extracted_document_count": len(extracted_docs),
                        "crawl_errors": crawl_errors,
                        "extraction_errors": extraction_errors,
                    },
                )
                write_debug_text(
                    debug_dir,
                    "texts/extracted_documents.txt",
                    build_documents_dump(extracted_docs),
                )
                write_debug_text(
                    debug_dir,
                    "texts/combined_text.txt",
                    combined_text,
                )

            if not normalize_inline(combined_text):
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_no_text",
                            "reason": None,
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_no_text"),
                        ),
                    },
                )
                log_venue(venue, "NO_TEXT")
                continue

            candidates = extract_price_candidates(extracted_docs)
            clear_candidate = choose_clear_candidate(candidates)

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "regex_candidates.json",
                    serialize_price_candidates(candidates),
                )

            if clear_candidate:
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_price_found_regex",
                            "candidate": {
                                "beer_name": clear_candidate.beer_name,
                                "price_chf": clear_candidate.price_chf,
                                "volume_l": clear_candidate.volume_l,
                                "evidence": clear_candidate.evidence,
                                "source_url": clear_candidate.source_url,
                            },
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "cheapest_lager_name": clear_candidate.beer_name,
                        "cheapest_lager_price_chf": clear_candidate.price_chf,
                        "price_volume_l": 0.5,
                        "price_source": "website",
                        "price_updated_at": now_iso(),
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_price_found", clear_candidate.evidence),
                        ),
                    },
                )
                prices_found += 1
                log_venue(
                    venue,
                    "FOUND_REGEX",
                    f"{clear_candidate.beer_name} CHF {clear_candidate.price_chf:.2f} | source: {clear_candidate.source_url}",
                )
                continue

            model_result = run_extraction_model(venue, combined_text)
            model_ok = False
            rejection_reason = None
            if debug_dir and model_result is not None:
                write_debug_json(debug_dir, "model_result.json", model_result)
            if model_result:
                model_ok, rejection_reason = validate_model_result(
                    model_result,
                    combined_text,
                    allowed_source_urls,
                    source_text_map,
                )

            if model_result and model_ok:
                if debug_dir:
                    write_debug_json(
                        debug_dir,
                        "result.json",
                        {
                            "status": "checked_price_found_model",
                            "model_result": model_result,
                        },
                    )
                update_venue(
                    venue["id"],
                    {
                        "cheapest_lager_name": model_result.get("beer_name"),
                        "cheapest_lager_price_chf": model_result.get("price"),
                        "price_volume_l": 0.5,
                        "price_source": "website",
                        "price_updated_at": now_iso(),
                        "website_checked_at": now_iso(),
                        "notes": append_note(
                            venue.get("notes"),
                            status_note("checked_price_found", model_result.get("evidence")),
                        ),
                    },
                )
                prices_found += 1
                log_venue(
                    venue,
                    "FOUND_MODEL",
                    (
                        f"{model_result.get('beer_name')} CHF "
                        f"{float(model_result.get('price')):.2f} | "
                        f"source: {model_result.get('source_url')} | "
                        f"evidence: {model_result.get('evidence')}"
                    ),
                )
                continue

            reason = rejection_reason
            if not reason and model_result:
                reason = model_result.get("reason")
            if not reason and all_errors:
                reason = all_errors[0]

            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "checked_no_price",
                        "reason": reason,
                        "validation_rejection_reason": rejection_reason,
                        "crawl_errors": crawl_errors,
                        "extraction_errors": extraction_errors,
                    },
                )

            update_venue(
                venue["id"],
                {
                    "website_checked_at": now_iso(),
                    "notes": append_note(
                        venue.get("notes"),
                        status_note("checked_no_price", reason),
                    ),
                },
            )
            no_price_found += 1
            log_venue(venue, "NO_PRICE", reason)

        except requests.RequestException as error:
            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "website_unreachable",
                        "reason": str(error),
                    },
                )
            update_venue(
                venue["id"],
                {
                    "website_checked_at": now_iso(),
                    "notes": append_note(
                        venue.get("notes"),
                        status_note("website_unreachable", str(error)),
                    ),
                },
            )
            unreachable += 1
            log_venue(venue, "UNREACHABLE", str(error))
        except Exception as error:
            if debug_dir:
                write_debug_json(
                    debug_dir,
                    "result.json",
                    {
                        "status": "error",
                        "reason": str(error),
                    },
                )
            errors += 1
            log_venue(venue, "ERROR", str(error))

    print("Website check summary")
    print(f"Venues checked: {checked}")
    print(f"Prices found: {prices_found}")
    print(f"No price found: {no_price_found}")
    print(f"Unreachable: {unreachable}")
    print(f"Errors: {errors}")
