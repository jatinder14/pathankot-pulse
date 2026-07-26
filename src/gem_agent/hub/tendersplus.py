"""Scrape TendersPlus active tenders via SSR ng-state (same data the site renders)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from .store import Lead, _now, load_hub_config

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE = "https://tendersplus.com/active-tender"
DETAIL = "https://tendersplus.com/tender-details/{uuid}"

# Portals Tenders+ aggregates (shown as source pills)
KNOWN_SOURCES = [
    "GEM",
    "eprocure",
    "IREPS",
    "MSTC",
    "nProcure",
    "CPWD",
    "PHED Haryana",
    "GEM-Auction",
    "eprocure-AP",
    "eprocure-Bihar",
    "eprocure-SPPP",
    "eprocure-KPPP",
    "eprocure-CG",
]


def _id(key: str) -> str:
    return hashlib.sha1(f"tendersplus|{key}".encode()).hexdigest()[:16]


def _strip_em(htmlish: str) -> str:
    return re.sub(r"</?em>", "", htmlish or "", flags=re.I)


def _build_active_url(
    *,
    page: int,
    keywords: list[str],
    states: list[str] | None = None,
    sources: list[str] | None = None,
    year: int = 2026,
    search_mode: str = "ALL",
) -> str:
    """Build Tenders+ URL with browser-like encoding.

    Critical: do NOT percent-encode ':' inside filter=KEYWORD:... — httpx's default
    encoding breaks their filter parser and returns the unfiltered 150k+ corpus.
    """
    from urllib.parse import quote

    parts = [
        "sort=RELEVANCE:DESC",
        f"pageNumber={page}",
        "pageSize=10",
        "tenderType=ACTIVE",
        "tenderEntity=TENDER_LISTING",
        f"year={year}",
        "removeUnavailableTenderAmountCards=false",
        "removeUnavailableEmdCards=false",
    ]
    for kw in keywords:
        parts.append(f"filter=KEYWORD:{quote(kw, safe='')}")
    parts.append(f"filter=SEARCHMODE:{search_mode}")
    for st in states or []:
        parts.append(f"filter=LOCATION_STRING:{quote(st, safe='')}")
    for src in sources or []:
        parts.append(f"filter=PROCUREMENT_SOURCE:{quote(src, safe='')}")
    return f"{BASE}?{'&'.join(parts)}"


def _fetch_page(
    client: httpx.Client,
    *,
    page: int,
    keywords: list[str],
    states: list[str] | None = None,
    sources: list[str] | None = None,
    year: int = 2026,
    search_mode: str = "ALL",
) -> dict[str, Any]:
    url = _build_active_url(
        page=page,
        keywords=keywords,
        states=states,
        sources=sources,
        year=year,
        search_mode=search_mode,
    )
    r = client.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    script = soup.find("script", id="ng-state")
    if not script or not script.string:
        return {"content": [], "totalElements": 0, "totalPages": 0}
    data = json.loads(script.string)
    for key, val in data.items():
        if not (isinstance(key, str) and key.startswith("tender-") and isinstance(val, dict)):
            continue
        tables = (val.get("data") or {}).get("tpsTenderTables") or {}
        if "content" in tables:
            return tables
    return {"content": [], "totalElements": 0, "totalPages": 0}


def _row_to_lead(row: dict[str, Any], *, keyword: str) -> Lead:
    uuid = row.get("uuid") or row.get("tenderId") or ""
    title = (row.get("authority_name") or "Tender").strip() + " Tender"
    summary = _strip_em(row.get("highlighted_summary") or row.get("summary") or "")
    boq = _strip_em(row.get("highlighted_boq") or "")
    state = row.get("state") or ""
    district = row.get("district") or ""
    source = row.get("external_source") or ""
    value = row.get("estimated_bid_value") or ""
    url = DETAIL.format(uuid=uuid) if uuid else BASE
    tags = ["tendersplus", "tender"]
    if source:
        tags.append(source.lower().replace(" ", "-"))
    if state:
        tags.append(state.lower().replace(" ", "-"))
    return Lead(
        id=_id(uuid or f"{row.get('tenderId')}|{summary[:40]}"),
        portal="tendersplus",
        section="Active tenders",
        kind="tenders",
        title=f"{title}: {summary[:160]}" if summary else title,
        url=url,
        location=", ".join(x for x in [district.title() if district else "", state] if x),
        pincode="",
        price=f"₹ {value}" if value and not str(value).startswith("₹") else str(value),
        starts_at=row.get("startDate") or "",
        ends_at=row.get("endDate") or "",
        buyer=row.get("organization_name") or row.get("authority_name") or "",
        summary=(boq[:280] if boq else summary) or f"Source: {source}",
        tags=tags,
        scraped_at=_now(),
        meta={
            "tender_id": row.get("tenderId"),
            "uuid": uuid,
            "source": source,
            "ministry": row.get("ministry"),
            "category": row.get("product_category"),
            "keyword": keyword,
            "boq_match": bool(row.get("keyword_match_in_docs")),
            "raw_value": value,
        },
    )


def scrape_tendersplus(
    *,
    keywords: list[str] | None = None,
    states: list[str] | None = None,
    max_pages: int | None = None,
    year: int = 2026,
    delay_s: float = 0.35,
) -> list[Lead]:
    """Paginate TendersPlus active listings for each keyword (SSR ng-state).

    Site caps pageSize at 10. Pass max_pages=None to pull every page for each keyword
    (can be hundreds of pages — use carefully).
    """
    cfg = load_hub_config()
    region = cfg.get("region") or {}
    prefs = cfg.get("tender_filters") or {}
    default_kw = list(prefs.get("keywords_boost") or []) or [
        "training",
        "digital literacy",
        "artificial intelligence",
        "skill development",
        "computer",
    ]
    keywords = keywords or default_kw
    # Pathankot-first: also pull Punjab when no explicit states
    if states is None:
        states = [region.get("state") or "Punjab"]

    leads: list[Lead] = []
    with httpx.Client(
        timeout=45.0,
        headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"},
        follow_redirects=True,
    ) as client:
        for kw in keywords:
            # First without state (national), then with Punjab bias — merge
            for st_filter in (None, states):
                page = 1
                total_pages = 1
                while page <= total_pages:
                    if max_pages is not None and page > max_pages:
                        break
                    try:
                        tables = _fetch_page(
                            client,
                            page=page,
                            keywords=[kw],
                            states=st_filter,
                            year=year,
                        )
                    except Exception:
                        break
                    content = tables.get("content") or []
                    total_pages = int(tables.get("totalPages") or 1)
                    if max_pages is not None:
                        total_pages = min(total_pages, max_pages)
                    for row in content:
                        leads.append(_row_to_lead(row, keyword=kw))
                    if not content:
                        break
                    page += 1
                    time.sleep(delay_s)
                # only run national once per keyword then state
                if st_filter is None and not states:
                    break

    return _dedupe_leads(leads)


def scrape_tendersplus_all_for_keyword(
    keyword: str,
    *,
    max_pages: int | None = None,
    year: int = 2026,
    checkpoint_every: int = 25,
    on_checkpoint: Any | None = None,
) -> tuple[list[Lead], dict[str, Any]]:
    """Scrape every page for one keyword (e.g. Steel Bars). Returns leads + meta.

    checkpoint_every: invoke on_checkpoint(leads, meta) every N pages so callers can persist.
    """
    leads: list[Lead] = []
    meta: dict[str, Any] = {
        "keyword": keyword,
        "pages_fetched": 0,
        "total": 0,
        "total_pages": 0,
    }
    with httpx.Client(
        timeout=45.0,
        headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"},
        follow_redirects=True,
    ) as client:
        page = 1
        total_pages = 1
        while page <= total_pages:
            if max_pages is not None and page > max_pages:
                break
            tables = _fetch_page(client, page=page, keywords=[keyword], year=year)
            content = tables.get("content") or []
            meta["total"] = int(tables.get("totalElements") or meta["total"] or 0)
            total_pages = int(tables.get("totalPages") or 1)
            meta["total_pages"] = total_pages
            if max_pages is not None:
                total_pages = min(total_pages, max_pages)
            for row in content:
                leads.append(_row_to_lead(row, keyword=keyword))
            meta["pages_fetched"] = page
            meta["stored"] = len(leads)
            if not content:
                break
            if checkpoint_every and page % checkpoint_every == 0 and on_checkpoint:
                on_checkpoint(_dedupe_leads(leads), dict(meta))
            page += 1
            time.sleep(0.25)
    return _dedupe_leads(leads), meta


def _dedupe_leads(leads: list[Lead]) -> list[Lead]:
    seen: set[str] = set()
    out: list[Lead] = []
    for lead in leads:
        key = (lead.meta or {}).get("uuid") or lead.url or lead.id
        if key in seen:
            continue
        seen.add(key)
        out.append(lead)
    return out
