"""Multi-portal scrapers — real listings only (no search-shortcut cards)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from .store import Lead, _now, load_hub_config

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SKIP_TITLE = re.compile(
    r"^(home|search|login|register|contact|about|privacy|terms|click here|more|"
    r"read more|search property|view all|next|prev|open |search |google|"
    r"tenders by closing date|tenders by organisation|advanced search|"
    r"latest tenders|corrigendum|help|faq|sitemap)$",
    re.I,
)

NAV_JUNK = re.compile(
    r"tenders by (closing|organisation|location)|advanced search|click here|"
    r"view all|login|register|sitemap|corrigenda?$",
    re.I,
)


def _id(portal: str, key: str) -> str:
    return hashlib.sha1(f"{portal}|{key}".encode()).hexdigest()[:16]


def _client(*, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"},
        follow_redirects=True,
    )


def _clean_title(text: str) -> str | None:
    text = " ".join((text or "").split())
    if len(text) < 18:
        return None
    if SKIP_TITLE.match(text):
        return None
    if NAV_JUNK.search(text):
        return None
    if text.lower().startswith(("search ", "open ", "google ·")):
        return None
    return text[:220]


def _dedupe(leads: list[Lead]) -> list[Lead]:
    seen: set[str] = set()
    out: list[Lead] = []
    for lead in leads:
        key = lead.url or lead.id
        if not key or key in seen:
            continue
        if "shortcut" in lead.tags:
            continue
        if "google.com/search" in (lead.url or ""):
            continue
        seen.add(key)
        out.append(lead)
    return out


def scrape_gem(*, pages: int = 2) -> list[Lead]:
    from ..scout.started_from import run_started_from_scout

    payload = run_started_from_scout(pages=pages)
    leads: list[Lead] = []
    for t in payload.get("tenders") or []:
        title = _clean_title(t.get("title") or "")
        if not title:
            continue
        url = t.get("url") or ""
        if not url:
            continue
        leads.append(
            Lead(
                id=_id("gem", t.get("external_id") or t.get("bid_number") or url),
                portal="gem",
                section="Government tenders",
                kind="tenders",
                title=title,
                url=url,
                location="India (GeM)",
                buyer=f"{t.get('ministry') or ''} / {t.get('department') or ''}".strip(" /"),
                starts_at=(t.get("start_at") or "")[:19],
                ends_at=(t.get("end_at") or "")[:19],
                summary=f"GeM · {t.get('days_left')}d left" if t.get("days_left") is not None else "GeM listing",
                tags=["gem", "tender"],
                scraped_at=_now(),
                meta={"bid_number": t.get("bid_number")},
            )
        )
    return _dedupe(leads)


def scrape_cppp() -> list[Lead]:
    from ..config import get_settings, load_keywords
    from ..scout.cppp import CpppScout

    kw = load_keywords(get_settings())
    queries = (kw.get("gem_queries") or ["training", "digital literacy", "skill development"])[:8]
    leads: list[Lead] = []
    with CpppScout() as scout:
        for t in scout.search_many(queries):
            title = _clean_title(t.title)
            if not title or not t.url:
                continue
            leads.append(
                Lead(
                    id=_id("cppp", t.external_id),
                    portal="cppp",
                    section="Government tenders",
                    kind="tenders",
                    title=title,
                    url=t.url,
                    location="India (CPPP)",
                    buyer=t.ministry or "",
                    summary="CPPP listing",
                    tags=["cppp", "tender"],
                    scraped_at=_now(),
                )
            )
    return _dedupe(leads)


def scrape_punjab() -> list[Lead]:
    cfg = load_hub_config()
    city = (cfg.get("region") or {}).get("city") or "Pathankot"
    pin = (cfg.get("region") or {}).get("pincode") or "145023"
    bases = [
        "https://eproc.punjab.gov.in",
        "https://eproc.punjab.gov.in/nicgep/app",
    ]
    leads: list[Lead] = []
    with _client() as client:
        for base in bases:
            try:
                r = client.get(base)
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text[:400_000], "html.parser")
                for a in soup.find_all("a", href=True)[:120]:
                    title = _clean_title(a.get_text(" ", strip=True))
                    href = a["href"]
                    if not title:
                        continue
                    if not re.search(r"tender|bid|auction|notice|corrigendum|NIT", title, re.I):
                        continue
                    # Skip bare portal nav
                    if href.rstrip("/").endswith(("eproc.punjab.gov.in", "nicgep/app")):
                        continue
                    url = href if href.startswith("http") else urljoin(base, href)
                    leads.append(
                        Lead(
                            id=_id("punjab", url),
                            portal="punjab",
                            section="State tenders",
                            kind="tenders",
                            title=title,
                            url=url,
                            location=f"Punjab · {city} {pin}",
                            summary="Punjab e-Procurement listing",
                            tags=["punjab", "state", "tender"],
                            scraped_at=_now(),
                        )
                    )
                if leads:
                    break
            except Exception:
                continue
    return _dedupe(leads)[:40]


def scrape_bank_auctions() -> list[Lead]:
    """Real bank auction rows near Pathankot / Punjab — no Google/search cards."""
    cfg = load_hub_config()
    city = (cfg.get("region") or {}).get("city") or "Pathankot"
    pin = (cfg.get("region") or {}).get("pincode") or "145023"
    state = (cfg.get("region") or {}).get("state") or "Punjab"
    leads: list[Lead] = []

    search_urls = [
        f"https://www.bankeauctions.com/Home/AuctionSearch?searchtext={quote_plus(city)}",
        f"https://www.bankeauctions.com/Home/AuctionSearch?searchtext={quote_plus('Pathankot Punjab')}",
        f"https://www.bankeauctions.com/Home/AuctionSearch?searchtext={quote_plus('Gurdaspur')}",
        "https://ibapi.in/sale_info_home.aspx",
        f"https://www.foreclosureindia.com/bank-auctions/punjab",
        "https://www.foreclosureindia.com/bank-auctions/pathankot",
    ]

    with _client(timeout=18.0) as client:
        for url in search_urls:
            try:
                r = client.get(url)
                if r.status_code >= 400:
                    continue
                html = r.text[:350_000]
                soup = BeautifulSoup(html, "html.parser")

                # Table rows often hold auction properties
                for tr in soup.find_all("tr")[:80]:
                    cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                    if len(cells) < 2:
                        continue
                    blob = " | ".join(cells)
                    if not re.search(r"auction|property|bank|pathankot|punjab|gurdaspur|sale", blob, re.I):
                        continue
                    title = _clean_title(blob)
                    if not title:
                        continue
                    link = tr.find("a", href=True)
                    full = url
                    if link:
                        href = link["href"]
                        full = href if href.startswith("http") else urljoin(url, href)
                    near = bool(re.search(r"pathankot|gurdaspur|145023|sujanpur|punjab", blob, re.I))
                    if not near and "punjab" not in blob.lower() and "pathankot" not in url.lower():
                        continue
                    leads.append(
                        Lead(
                            id=_id("bank_auction", full + title[:40]),
                            portal="bank_auction",
                            section="Bank property & vehicles",
                            kind="auctions",
                            title=title,
                            url=full,
                            location=f"{city}, {state}" if near else state,
                            pincode=pin if near else "",
                            price=next((c for c in cells if re.search(r"₹|Rs\.?\s*\d", c)), ""),
                            summary="Bank auction listing (scraped)",
                            tags=["bank", "auction"] + (["pathankot"] if near else ["punjab"]),
                            scraped_at=_now(),
                        )
                    )

                for a in soup.find_all("a", href=True)[:100]:
                    title = _clean_title(a.get_text(" ", strip=True))
                    href = a["href"]
                    if not title:
                        continue
                    blob = f"{title} {href}".lower()
                    if not re.search(r"auction|property|sarfaesi|sale.?notice|pathankot|gurdaspur", blob):
                        continue
                    if any(x in href.lower() for x in ("login", "register", "javascript:", "#")):
                        continue
                    full = href if href.startswith("http") else urljoin(url, href)
                    near = bool(re.search(r"pathankot|gurdaspur|145023|sujanpur", blob, re.I))
                    leads.append(
                        Lead(
                            id=_id("bank_auction", full),
                            portal="bank_auction",
                            section="Bank property & vehicles",
                            kind="auctions",
                            title=title,
                            url=full,
                            location=f"{city}, {state}" if near else f"{state}",
                            pincode=pin if near else "",
                            summary="Bank auction listing (scraped)",
                            tags=["bank", "auction"] + (["pathankot"] if near else []),
                            scraped_at=_now(),
                        )
                    )
            except Exception:
                continue

    return _dedupe(leads)[:50]


def scrape_gov_auctions() -> list[Lead]:
    cfg = load_hub_config()
    city = (cfg.get("region") or {}).get("city") or "Pathankot"
    pin = (cfg.get("region") or {}).get("pincode") or "145023"
    leads: list[Lead] = []
    portals = [
        "https://www.mstcecommerce.com/",
        "https://www.mstcindia.co.in/",
        "https://eauction.gov.in/",
    ]
    with _client(timeout=15.0) as client:
        for url in portals:
            try:
                r = client.get(url)
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text[:300_000], "html.parser")
                for a in soup.find_all("a", href=True)[:90]:
                    title = _clean_title(a.get_text(" ", strip=True))
                    href = a["href"]
                    if not title:
                        continue
                    if not re.search(r"auction|e-?sale|property|scrap|lot|tender|vehicle", f"{title} {href}", re.I):
                        continue
                    if href.rstrip("/") in {u.rstrip("/") for u in portals}:
                        continue
                    full = href if href.startswith("http") else urljoin(url, href)
                    leads.append(
                        Lead(
                            id=_id("gov_auction", full),
                            portal="gov_auction",
                            section="Gov property & vehicles",
                            kind="auctions",
                            title=title,
                            url=full,
                            location=f"India · prefer {city} {pin}",
                            summary="Gov auction listing (scraped)",
                            tags=["gov", "auction"],
                            scraped_at=_now(),
                        )
                    )
            except Exception:
                continue
    return _dedupe(leads)[:50]


def scrape_vehicles() -> list[Lead]:
    cfg = load_hub_config()
    city = (cfg.get("region") or {}).get("city") or "Pathankot"
    pin = (cfg.get("region") or {}).get("pincode") or "145023"
    leads: list[Lead] = []
    urls = [
        "https://www.mstcecommerce.com/",
        "https://eauction.gov.in/",
        f"https://www.bankeauctions.com/Home/AuctionSearch?searchtext={quote_plus(f'vehicle {city}')}",
    ]
    with _client(timeout=15.0) as client:
        for url in urls:
            try:
                r = client.get(url)
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text[:300_000], "html.parser")
                for a in soup.find_all("a", href=True)[:80]:
                    title = _clean_title(a.get_text(" ", strip=True))
                    href = a["href"]
                    if not title:
                        continue
                    if not re.search(r"vehicle|scrap|car|bus|truck|automobile|two.?wheeler", f"{title} {href}", re.I):
                        continue
                    full = href if href.startswith("http") else urljoin(url, href)
                    leads.append(
                        Lead(
                            id=_id("vehicles", full),
                            portal="vehicles",
                            section="Vehicles & scrap",
                            kind="auctions",
                            title=title,
                            url=full,
                            location=f"{city} / Punjab {pin}",
                            pincode=pin,
                            summary="Vehicle / scrap auction (scraped)",
                            tags=["vehicle", "scrap"],
                            scraped_at=_now(),
                        )
                    )
            except Exception:
                continue
    return _dedupe(leads)[:40]


def _olx_from_scripts(html: str, *, city: str, pin: str, label: str, page_url: str) -> list[Lead]:
    leads: list[Lead] = []
    # Next.js / hydrated JSON blobs
    for m in re.finditer(
        r'"title"\s*:\s*"([^"\\]{12,160})".{0,400}?"price".{0,80}?"value"\s*:\s*(\d+)',
        html,
        re.S,
    ):
        title = m.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        price = m.group(2)
        title = _clean_title(title)
        if not title:
            continue
        leads.append(
            Lead(
                id=_id("olx", title[:80] + price),
                portal="olx",
                section="Local classifieds",
                kind="classifieds",
                title=title,
                url=page_url,
                location=f"{city}, Punjab {pin}",
                pincode=pin,
                price=f"₹{int(price):,}",
                summary=f"OLX · {label}",
                tags=["olx", "pathankot", "property"],
                scraped_at=_now(),
            )
        )
        if len(leads) >= 25:
            break

    # __NEXT_DATA__ style
    for m in re.finditer(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        blob = json.dumps(data)
        for tm in re.finditer(r'"title"\s*:\s*"([^"\\]{12,160})"', blob):
            title = _clean_title(tm.group(1))
            if not title:
                continue
            leads.append(
                Lead(
                    id=_id("olx", title[:90]),
                    portal="olx",
                    section="Local classifieds",
                    kind="classifieds",
                    title=title,
                    url=page_url,
                    location=f"{city} {pin}",
                    pincode=pin,
                    summary=f"OLX · {label}",
                    tags=["olx", "pathankot"],
                    scraped_at=_now(),
                )
            )
            if len(leads) >= 30:
                break
    return leads


def scrape_olx() -> list[Lead]:
    """Real OLX listings near Pathankot — parse item links + embedded JSON."""
    cfg = load_hub_config()
    city = (cfg.get("region") or {}).get("city") or "Pathankot"
    pin = (cfg.get("region") or {}).get("pincode") or "145023"
    nearby = list((cfg.get("region") or {}).get("nearby") or [])[:3]
    places = [city] + nearby

    queries: list[tuple[str, str]] = []
    for place in places:
        pl = place.lower()
        queries.extend(
            [
                (f"house {place}", f"https://www.olx.in/items/q-house-{quote_plus(pl)}"),
                (f"plot {place}", f"https://www.olx.in/items/q-plot-{quote_plus(pl)}"),
                (f"flat {place}", f"https://www.olx.in/items/q-flat-{quote_plus(pl)}"),
            ]
        )
    # Location landing pages
    queries.append((f"{city} home", f"https://www.olx.in/{city.lower()}/"))

    leads: list[Lead] = []
    with _client(timeout=16.0) as client:
        for label, url in queries[:8]:
            try:
                r = client.get(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Accept": "text/html,application/xhtml+xml",
                        "Referer": "https://www.olx.in/",
                    },
                )
                if r.status_code >= 400:
                    continue
                chunk = r.text[:800_000]
                leads.extend(_olx_from_scripts(chunk, city=city, pin=pin, label=label, page_url=url))

                # item URLs often look like /item/description-iid-1234567890
                for m in re.finditer(
                    r'href="((?:https://www\.olx\.in)?/item/[^"]+)"[^>]*>\s*([^<]{10,160})',
                    chunk,
                ):
                    href, title_raw = m.group(1), m.group(2)
                    title = _clean_title(BeautifulSoup(title_raw, "html.parser").get_text(" ", strip=True))
                    if not title:
                        continue
                    full = href if href.startswith("http") else urljoin("https://www.olx.in", href)
                    leads.append(
                        Lead(
                            id=_id("olx", full),
                            portal="olx",
                            section="Local classifieds",
                            kind="classifieds",
                            title=title,
                            url=full,
                            location=f"{city} / nearby · {pin}",
                            pincode=pin,
                            summary=f"OLX · {label}",
                            tags=["olx", "pathankot", "nearby"],
                            scraped_at=_now(),
                        )
                    )

                soup = BeautifulSoup(chunk[:250_000], "html.parser")
                for a in soup.find_all("a", href=True)[:100]:
                    href = a["href"]
                    if "/item/" not in href:
                        continue
                    title = _clean_title(a.get_text(" ", strip=True))
                    if not title:
                        # try aria / img alt nearby
                        img = a.find("img")
                        if img and img.get("alt"):
                            title = _clean_title(img["alt"])
                    if not title:
                        continue
                    full = href if href.startswith("http") else urljoin("https://www.olx.in", href)
                    leads.append(
                        Lead(
                            id=_id("olx", full),
                            portal="olx",
                            section="Local classifieds",
                            kind="classifieds",
                            title=title,
                            url=full,
                            location=f"{city} / nearby · {pin}",
                            pincode=pin,
                            summary=f"OLX · {label}",
                            tags=["olx", "pathankot", "nearby"],
                            scraped_at=_now(),
                        )
                    )
            except Exception:
                continue
    return _dedupe(leads)[:60]
