import json
import re

from .config import MAX_MODEL_TEXT_CHARS, OPENAI_MODEL, VOLUME_PATTERN, openai_client
from .extract import format_price_variants
from .utils import normalize_inline


def build_extraction_prompt(venue: dict, combined_text: str) -> str:
    schema = {
        "found": "boolean",
        "beer_name": "string | null",
        "price": "number | null",
        "currency": "string | null",
        "volume_l": "number | null",
        "evidence": "string | null",
        "source_url": "string | null",
        "reason": "string | null",
    }

    return (
        "You are extracting a venue's cheapest 0.5L lager beer from provided restaurant website text.\n"
        "You are NOT browsing. Use ONLY the provided text.\n"
        "Return JSON only.\n"
        f"Required schema: {json.dumps(schema)}\n\n"
        f"Venue name: {venue.get('name')}\n"
        f"Website: {venue.get('website')}\n\n"
        "Rules:\n"
        "- Only report found=true if there is a clear 0.5l / 5dl / 50cl / 500ml lager-like draft beer candidate.\n"
        "- Be conservative. A missed result is better than a wrong result.\n"
        "- Only choose a price if the beer name, the 0.5L volume, and the price are clearly linked in the same source.\n"
        "- If multiple prices are nearby or the pairing is ambiguous, return found=false.\n"
        "- Keep evidence short and verbatim-like from the source.\n"
        "- source_url must be one of the provided source labels.\n"
        "- currency must be CHF if found=true.\n\n"
        "Provided text:\n"
        f"{combined_text[:MAX_MODEL_TEXT_CHARS]}"
    )


def run_extraction_model(venue: dict, combined_text: str) -> dict | None:
    prompt = build_extraction_prompt(venue, combined_text)
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Return strict JSON only. If uncertain, return found=false.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def validate_model_result(
    result: dict,
    combined_text: str,
    allowed_source_urls: set[str],
    source_text_map: dict[str, str],
) -> tuple[bool, str | None]:
    if result.get("found") is not True:
        return False, "model returned found=false"

    price = result.get("price")
    if not isinstance(price, (int, float)):
        return False, "model price is not numeric"

    if result.get("volume_l") != 0.5:
        return False, "model volume is not 0.5l"

    beer_name = normalize_inline(result.get("beer_name") or "")
    if not beer_name:
        return False, "model beer_name is empty"

    evidence = result.get("evidence") or ""
    if not evidence.strip():
        return False, "model evidence is empty"

    source_url = normalize_inline(result.get("source_url") or "")
    if not source_url:
        return False, "model source_url is empty"
    if source_url not in allowed_source_urls:
        return False, "model source_url is not one of the gathered sources"

    source_text = source_text_map.get(source_url, "")
    if not source_text:
        return False, "source text for model source_url is empty"

    normalized_dump = normalize_inline(combined_text)
    normalized_evidence = normalize_inline(evidence)
    if normalized_evidence not in normalized_dump and normalized_evidence not in source_text:
        evidence_tokens = [token for token in re.split(r"\s+", normalized_evidence) if len(token) >= 3]
        overlap = sum(1 for token in evidence_tokens if token.lower() in source_text.lower())
        if overlap < max(2, min(5, len(evidence_tokens) // 2)):
            return False, "model evidence not sufficiently grounded in source text"

    if beer_name.lower() not in normalized_evidence.lower() and beer_name.lower() not in source_text.lower():
        return False, "model beer name not found in source text"

    if not VOLUME_PATTERN.search(normalized_evidence) and not VOLUME_PATTERN.search(source_text):
        return False, "model source text does not contain 0.5l volume"

    price_variants = format_price_variants(float(price))
    if not any(price_variant in normalized_evidence for price_variant in price_variants) and not any(
        price_variant in source_text for price_variant in price_variants
    ):
        return False, "model source text does not contain returned price"

    return True, None
