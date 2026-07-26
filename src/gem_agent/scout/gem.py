from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx

from ..models import BidSource, Tender

BASE = "https://bidplus.gem.gov.in"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _parse_dt(value: Any) -> datetime | None:
    raw = _first(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_csrf(html: str) -> str:
    match = re.search(r"csrf_bd_gem_nk'\s*:\s*'([a-f0-9]+)'", html)
    if not match:
        match = re.search(r'csrf_bd_gem_nk["\']?\s*[:=]\s*["\']([a-f0-9]+)["\']', html)
    if not match:
        raise RuntimeError("Could not extract GeM CSRF token from all-bids page")
    return match.group(1)


def _doc_to_tender(doc: dict[str, Any]) -> Tender:
    external_id = str(_first(doc.get("b_id")) or doc.get("id"))
    bid_number = str(_first(doc.get("b_bid_number")) or "")
    title = str(
        _first(doc.get("bd_category_name"))
        or _first(doc.get("b_category_name"))
        or "Untitled GeM bid"
    )
    quantity = _first(doc.get("b_total_quantity"))
    try:
        quantity_int = int(quantity) if quantity is not None else None
    except (TypeError, ValueError):
        quantity_int = None

    return Tender(
        external_id=external_id,
        source=BidSource.GEM,
        bid_number=bid_number,
        title=title,
        ministry=_first(doc.get("ba_official_details_minName")),
        department=_first(doc.get("ba_official_details_deptName")),
        quantity=quantity_int,
        start_at=_parse_dt(doc.get("final_start_date_sort")),
        end_at=_parse_dt(doc.get("final_end_date_sort")),
        url=f"{BASE}/showbidDocument/{external_id}",
        document_url=f"{BASE}/showbidDocument/{external_id}",
        raw=doc,
    )


class GemScout:
    """Public GeM BidPlus scout (no login required for discovery)."""

    def __init__(self, timeout: float = 45.0) -> None:
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GemScout:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _session_csrf(self) -> str:
        resp = self._client.get(f"{BASE}/all-bids")
        resp.raise_for_status()
        return _extract_csrf(resp.text)

    def search(self, query: str, *, pages: int = 2) -> list[Tender]:
        csrf = self._session_csrf()
        results: list[Tender] = []
        seen: set[str] = set()

        for page in range(1, pages + 1):
            postdata = {
                "page": page,
                "param": {
                    "searchBid": query,
                    "searchType": "fullText",
                },
                "filter": {
                    "bidStatusType": "ongoing_bids",
                    "byType": "all",
                    "highBidValue": "",
                    "byEndDate": {"from": "", "to": ""},
                    "sort": "Bid-End-Date-Oldest",
                },
            }
            resp = self._client.post(
                f"{BASE}/all-bids-data",
                data={
                    "payload": json.dumps(postdata, separators=(",", ":")),
                    "csrf_bd_gem_nk": csrf,
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/all-bids",
                    "Origin": BASE,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            # GeM returns HTTP 404 + {"code":404,"message":"No data found"} for empty hits
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 200:
                raise RuntimeError(f"GeM search failed for '{query}': {payload}")

            docs = (
                payload.get("response", {})
                .get("response", {})
                .get("docs", [])
            )
            if not docs:
                break
            for doc in docs:
                tender = _doc_to_tender(doc)
                if tender.external_id in seen:
                    continue
                seen.add(tender.external_id)
                results.append(tender)
        return results

    def search_many(self, queries: list[str], *, pages_per_query: int = 1) -> list[Tender]:
        merged: dict[str, Tender] = {}
        for query in queries:
            q = query.strip()
            if len(q) < 3:
                continue
            for tender in self.search(q, pages=pages_per_query):
                merged[tender.external_id] = tender
        return list(merged.values())
