from dataclasses import dataclass


@dataclass
class CrawlTask:
    url: str
    depth: int
    priority: int


@dataclass
class HtmlDocument:
    source_url: str
    text: str


@dataclass
class ExtractedDocument:
    source_url: str
    source_type: str
    text: str


@dataclass
class PriceCandidate:
    beer_name: str
    price_chf: float
    volume_l: float
    evidence: str
    source_url: str


@dataclass
class CrawlResult:
    html_documents: list[HtmlDocument]
    pdf_urls: list[str]
    image_urls: list[str]
    errors: list[str]
