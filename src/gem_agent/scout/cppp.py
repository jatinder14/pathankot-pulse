from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..models import BidSource, Tender

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Best-effort public search endpoints. CPPP often uses CAPTCHA; failures are soft.
CPPP_CANDIDATES = [
    "https://eprocure.gov.in/eprocure/app?page=FrontEndTendersByOrganisation&service=page",
    "https://eprocure.gov.in/eprocure/app",
]


class CpppScout:
    """Best-effort CPPP discovery. Returns [] if portal blocks scraping."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CpppScout:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def search(self, query: str) -> list[Tender]:
        tenders: list[Tender] = []
        for url in CPPP_CANDIDATES:
            try:
                resp = self._client.get(url, params={"searchText": query} if "app" == url.rstrip("/").split("/")[-1] else None)
                if resp.status_code != 200:
                    continue
                if "captcha" in resp.text.lower() and "tender" not in resp.text.lower()[:2000]:
                    continue
                tenders.extend(self._parse_html(resp.text, query))
                if tenders:
                    break
            except httpx.HTTPError:
                continue
        return tenders

    def search_many(self, queries: list[str]) -> list[Tender]:
        merged: dict[str, Tender] = {}
        for query in queries:
            for tender in self.search(query):
                merged[tender.external_id] = tender
        return list(merged.values())

    def _parse_html(self, html: str, query: str) -> list[Tender]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[Tender] = []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text(" ", strip=True).split())
            href = a["href"]
            if not text or len(text) < 12:
                continue
            if not re.search(r"tender|software|training|AI|e-?learn", text, re.I):
                continue
            if not re.search(re.escape(query.split()[0]), text, re.I) and "tender" not in text.lower():
                # keep broad tender links even if exact query word missing
                if "tender" not in text.lower():
                    continue
            external_id = hashlib.sha1(f"{href}|{text}".encode()).hexdigest()[:16]
            full_url = href if href.startswith("http") else f"https://eprocure.gov.in{href}"
            results.append(
                Tender(
                    external_id=external_id,
                    source=BidSource.CPPP,
                    bid_number=f"CPPP-{external_id}",
                    title=text[:240],
                    url=full_url,
                    document_url=full_url,
                    raw={"query": query, "href": href},
                )
            )
            if len(results) >= 15:
                break
        return results


def manual_tender(
    *,
    bid_number: str,
    title: str,
    url: str | None = None,
    ministry: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Tender:
    external_id = hashlib.sha1(bid_number.encode()).hexdigest()[:16]
    return Tender(
        external_id=external_id,
        source=BidSource.MANUAL,
        bid_number=bid_number,
        title=title,
        ministry=ministry,
        url=url,
        document_url=url,
        raw=extra or {},
    )


def search_url_for_query(query: str) -> str:
    return f"https://bidplus.gem.gov.in/all-bids?searchBid={quote_plus(query)}"
