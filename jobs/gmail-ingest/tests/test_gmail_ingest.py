import base64
import sys
import unittest
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from gmail_ingest import (
    BeerPriceExtraction,
    GmailBeerPriceProcessor,
    extract_email_address,
    extract_plain_text_email_body,
)


def encode_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


class GmailIngestTest(unittest.TestCase):
    def test_extract_plain_text_email_body_prefers_plain_text(self):
        message = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": encode_body("<p>HTML price CHF 8.00</p>")},
                    },
                    {
                        "mimeType": "text/plain",
                        "body": {"data": encode_body("Plain price CHF 7.50")},
                    },
                ],
            }
        }

        self.assertEqual(extract_plain_text_email_body(message), "Plain price CHF 7.50")

    def test_extract_plain_text_email_body_falls_back_to_html(self):
        message = {
            "payload": {
                "mimeType": "text/html",
                "body": {
                    "data": encode_body(
                        "<html><body><p>Lager 5dl CHF 7.50</p><script>nope()</script></body></html>"
                    )
                },
            }
        }

        self.assertEqual(extract_plain_text_email_body(message), "Lager 5dl CHF 7.50")

    def test_extract_email_address_from_header(self):
        self.assertEqual(
            extract_email_address("Test Bar <hello@testbar.example>"),
            "hello@testbar.example",
        )

    def test_parse_volume_l(self):
        processor = GmailBeerPriceProcessor.__new__(GmailBeerPriceProcessor)

        self.assertEqual(processor.parse_volume_l("5dl"), 0.5)
        self.assertEqual(processor.parse_volume_l("50 cl"), 0.5)
        self.assertEqual(processor.parse_volume_l("500ml"), 0.5)

    def test_venue_payload_overwrites_extracted_price_fields(self):
        processor = GmailBeerPriceProcessor.__new__(GmailBeerPriceProcessor)
        venue = {
            "cheapest_lager_name": "Existing Lager",
            "cheapest_lager_price_chf": 6.5,
            "price_volume_l": None,
            "price_source": "website",
            "outreach_count": 2,
        }
        extraction = BeerPriceExtraction(
            found=True,
            business_name="Test Bar",
            beer_type="New Lager",
            price=7.5,
            currency="CHF",
            volume="5dl",
            confidence=0.9,
        )

        payload = processor.build_venue_price_payload(
            venue,
            extraction,
        )

        self.assertEqual(payload["cheapest_lager_name"], "New Lager")
        self.assertEqual(payload["cheapest_lager_price_chf"], 7.5)
        self.assertEqual(payload["price_volume_l"], 0.5)
        self.assertEqual(payload["price_source"], "gmail")
        self.assertEqual(payload["outreach_count"], 3)
        self.assertEqual(payload["email_bounce_status"], "replied")


if __name__ == "__main__":
    unittest.main()
