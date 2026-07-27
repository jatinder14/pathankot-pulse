"""Private jobs — Pathankot-first, currently active only.

Priority:
1. Pathankot / Sujanpur / Gurdaspur home belt
2. Nearby factories (Varun Pepsi Pathankot, Pioneer, Kandhari/Coca-Cola Kathua)
3. Drop stale posts older than max_age_days (default 45)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .store import Lead, _now, load_hub_config

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_QUERIES = [
    "jobs in Pathankot",
    "factory jobs Pathankot",
    "IT support Pathankot",
    "area manager Pathankot",
    "computer operator Pathankot",
]

DEFAULT_LOCATIONS = [
    "Pathankot",
    "Sujanpur",
    "Gurdaspur",
    "Kathua",
    "Jammu",
]

PATHANKOT_TOKENS = ("pathankot", "sujanpur", "145023")
NEAR_BELT_TOKENS = ("gurdaspur", "nurpur", "kangra", "kathua", "samba")
REGION_TOKENS = ("jammu", "punjab", "j&k", "jammu and kashmir")

FIT_TOKENS = [
    "ai",
    "artificial intelligence",
    "training",
    "trainer",
    "digital literacy",
    "computer",
    "it support",
    "technical support",
    "software",
    "area manager",
    "contractor",
    "freelance",
    "consultant",
    "faculty",
    "instructor",
    "skill",
    "e-learning",
    "edtech",
    "partner",
    "developer",
    "support engineer",
    "helpdesk",
    "network",
    "adhoc",
    "ad-hoc",
    "ad hoc",
    "specialist",
    "part time",
    "part-time",
    "visiting",
    "contract basis",
    "on call",
    "on-call",
    "gig",
    "retainership",
]

ADHOC_TOKENS = [
    "adhoc",
    "ad-hoc",
    "ad hoc",
    "specialist",
    "freelance",
    "freelancer",
    "consultant",
    "contract basis",
    "contractual",
    "part time",
    "part-time",
    "visiting faculty",
    "visiting",
    "guest faculty",
    "retainership",
    "on call",
    "on-call",
    "hourly",
    "project basis",
    "temporary",
    "temp ",
    "weekend",
    "side",
    "empanel",
    "empanelment",
    "vendor",
    "outsource",
    "outsourcing",
    "agency",
    "partner",
]

STORE_OPEN_TOKENS = [
    "store opening",
    "new store",
    "showroom",
    "outlet opening",
    "franchise",
    "retail store",
    "store manager",
    "store launch",
    "coming soon",
    "inauguration",
    "mall",
    "pos ",
    "billing",
    "cashier",
    "floor manager",
    "visual merchandis",
    "brand activation",
    "fit-out",
    "fit out",
    "store it",
    "cctv",
    "inventory",
]

DEFAULT_RETAIL_BRANDS = [
    "reliance smart",
    "vishal mega mart",
    "more retail",
    "trends",
    "croma",
    "vijay sales",
    "decathlon",
    "pantaloons",
    "domino",
    "mcdonald",
    "burger king",
    "cafe coffee day",
    "starbucks",
    "max fashion",
    "bata",
    "lenskart",
    "jockey",
    "lifestyle",
    "westside",
]

NEAR_TOKENS = [
    *PATHANKOT_TOKENS,
    *NEAR_BELT_TOKENS,
    *REGION_TOKENS,
    "chandigarh",
    "mohali",
    "jalandhar",
    "amritsar",
    "india",
    "remote",
    "work from home",
    "wfh",
]

LOCAL_EMPLOYER_HINTS = [
    "kandhari",
    "coca-cola",
    "coca cola",
    "varun beverage",
    "pepsi",
    "pioneer industr",
    "pdil",
    "projects and development india",
    "beverage",
    "bottling",
    "distillery",
    "fbo",
]

FACTORY_ROLE_TOKENS = [
    "supervisor",
    "engineer",
    "electrician",
    "fitter",
    "operator",
    "maintenance",
    "quality",
    "production",
    "chemist",
    "store",
    "technician",
    "manager",
    "trainee",
    "helper",
    "shift",
    "computer",
    "it ",
    "sap",
    "admin",
    "hr ",
    "training",
    "safety",
    "warehouse",
    "logistics",
    "diploma",
    "graduate",
    "executive",
    "incharge",
]

JOB_HOSTS = (
    "indeed.",
    "naukri.",
    "linkedin.",
    "apna.co",
    "shine.com",
    "foundit.",
    "timesjobs.",
    "freshersworld.",
    "monsterindia.",
    "glassdoor.",
    "instahyre.",
    "cutshort.",
    "wellfound.",
    "angellist.",
    "remotive.",
    "weworkremotely.",
    "jobicy.",
    "arbeitnow.",
    "hirist.",
    "iimjobs.",
    "foodtechnetwork.",
    "jobsfood.",
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _id(key: str) -> str:
    return hashlib.sha1(f"private_jobs|{key}".encode()).hexdigest()[:16]


def _client(*, timeout: float = 22.0, verify: bool = True) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"},
        follow_redirects=True,
        verify=verify,
    )


def _cfg_jobs() -> dict[str, Any]:
    return load_hub_config().get("private_jobs") or {}


def _max_age_days() -> int:
    return int(_cfg_jobs().get("max_age_days") or 45)


def _queries() -> list[str]:
    return list(_cfg_jobs().get("queries") or DEFAULT_QUERIES)


def _locations() -> list[str]:
    return list(_cfg_jobs().get("locations") or DEFAULT_LOCATIONS)


def _local_employers() -> list[dict[str, Any]]:
    return list(_cfg_jobs().get("local_employers") or [])


def _apna_cities() -> list[str]:
    cities = list(_cfg_jobs().get("apna_cities") or ["pathankot", "kathua", "jammu"])
    if "pathankot" in cities:
        cities = ["pathankot"] + [c for c in cities if c != "pathankot"]
    return cities


def parse_posted_date(raw: str | None) -> datetime | None:
    """Parse foodtech '17Nov', ISO dates, or '3 days ago' into aware UTC datetime."""
    if not raw:
        return None
    text = " ".join(str(raw).strip().split())
    if not text:
        return None
    now = datetime.now(timezone.utc)

    try:
        if "T" in text or re.match(r"^\d{4}-\d{2}-\d{2}", text):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", text, re.I)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        delta = {
            "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=30 * n),
        }[unit]
        return now - delta
    if re.search(r"\b(today|just now)\b", text, re.I):
        return now
    if re.search(r"\byesterday\b", text, re.I):
        return now - timedelta(days=1)

    m = re.fullmatch(r"(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text, re.I)
    if m:
        day = int(m.group(1))
        month = _MONTHS[m.group(2).lower()[:3]]
        year = now.year
        try:
            dt = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
        if dt > now + timedelta(days=1):
            dt = datetime(year - 1, month, day, tzinfo=timezone.utc)
        return dt

    m = re.search(
        r"(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s*(\d{4})",
        text,
        re.I,
    )
    if m:
        day, mon, year = int(m.group(1)), _MONTHS[m.group(2).lower()[:3]], int(m.group(3))
        try:
            return datetime(year, mon, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def is_active(posted_at: datetime | None, *, max_age_days: int | None = None) -> bool:
    if posted_at is None:
        return True
    days = max_age_days if max_age_days is not None else _max_age_days()
    return datetime.now(timezone.utc) - posted_at <= timedelta(days=days)


def location_rank(blob: str) -> int:
    """0 = Pathankot home, higher = farther."""
    b = blob.lower()
    # Explicit Pathankot/Sujanpur home (not only "near Pathankot")
    home = any(t in b for t in ("pathankot", "sujanpur", "145023"))
    near = any(t in b for t in NEAR_BELT_TOKENS)
    if home and not near:
        return 0
    if home and near:
        # "Kathua · near Pathankot" → belt, not home
        if any(t in b for t in ("kathua", "samba", "jammu")) and "sujanpur" not in b:
            # True Pathankot city slug wins
            if re.search(r"\bpathankot,\s*punjab\b|/job/pathankot/|pathankot plant|pathankot jobs", b):
                return 0
            return 1
        return 0
    if near:
        return 1
    if any(t in b for t in REGION_TOKENS):
        return 2
    if any(t in b for t in ("india", "remote", "wfh", "work from home")):
        return 3
    return 4


def _retail_brands() -> list[str]:
    raw = _cfg_jobs().get("retail_brands") or DEFAULT_RETAIL_BRANDS
    return [str(x).lower() for x in raw]


def score_job(
    title: str,
    summary: str = "",
    location: str = "",
    *,
    employer: str = "",
    source: str = "",
    posted_at: datetime | None = None,
) -> dict[str, Any]:
    blob = f"{title} {summary} {location} {employer}".lower()
    role_hits = [t for t in FIT_TOKENS if t in blob]
    near_hits = [t for t in NEAR_TOKENS if t in blob]
    factory_hits = [t for t in FACTORY_ROLE_TOKENS if t in blob]
    adhoc_hits = [t for t in ADHOC_TOKENS if t in blob]
    store_hits = [t for t in STORE_OPEN_TOKENS if t in blob]
    brand_hits = [b for b in _retail_brands() if b in blob]
    employer_hit = any(h in blob for h in LOCAL_EMPLOYER_HINTS)
    loc_rank = location_rank(blob)
    pathankot = loc_rank == 0
    adhoc = bool(adhoc_hits) or source == "adhoc" or "adhoc" in blob
    store_open = bool(store_hits) or bool(brand_hits) or source == "retail"

    score = min(
        100,
        12 * len(set(role_hits))
        + 8 * len(set(factory_hits))
        + 14 * len(set(adhoc_hits))
        + 12 * len(set(store_hits))
        + 10 * len(set(brand_hits)),
    )
    if pathankot:
        score = min(100, score + 35)
        near_hits = list(dict.fromkeys(["pathankot", *near_hits]))
    elif loc_rank == 1:
        score = min(100, score + 20)
    elif loc_rank == 2:
        score = min(100, score + 8)

    if adhoc and pathankot:
        score = min(100, score + 18)
    if store_open and loc_rank <= 1:
        score = min(100, score + 16)

    remoteish = any(t in blob for t in ("remote", "wfh", "work from home", "worldwide", "anywhere"))
    is_near = loc_rank <= 2
    active = is_active(posted_at)
    if posted_at and active:
        score = min(100, score + 8)
    if posted_at and not active:
        score = max(0, score - 40)

    why = list(dict.fromkeys(role_hits + factory_hits + adhoc_hits + store_hits + brand_hits))[:8]

    if source in ("local_factory", "apna", "foodtech", "adhoc", "retail") or employer_hit or store_open:
        score = max(score, 70 if pathankot else (55 if employer_hit or store_open else 42))
        usable = is_near and active and (
            employer_hit
            or bool(factory_hits)
            or bool(role_hits)
            or adhoc
            or store_open
            or pathankot
        )
        return {
            "score": score,
            "usable": usable,
            "role_hits": why,
            "near_hits": near_hits[:4],
            "local_factory": source in ("local_factory", "apna", "foodtech") or employer_hit,
            "adhoc": adhoc,
            "store_open": store_open,
            "pathankot": pathankot,
            "location_rank": loc_rank,
            "active": active,
        }

    usable = (
        active
        and score >= 24
        and (bool(role_hits) or adhoc or store_open)
        and (pathankot or (is_near and not remoteish) or ("india" in blob and bool(role_hits)))
    )
    if remoteish and "india" not in blob and not pathankot:
        usable = False
        score = max(0, score - 20)

    return {
        "score": score,
        "usable": usable,
        "role_hits": why,
        "near_hits": near_hits[:4],
        "local_factory": False,
        "adhoc": adhoc,
        "store_open": store_open,
        "pathankot": pathankot,
        "location_rank": loc_rank,
        "active": active,
    }


def _lead(
    *,
    title: str,
    url: str,
    location: str,
    summary: str,
    source: str,
    query: str,
    employer: str = "",
    posted_at: datetime | None = None,
    require_active: bool = True,
) -> Lead | None:
    title = " ".join((title or "").split())
    if len(title) < 10:
        return None
    if re.search(r"^(home|login|privacy|cookie|about|search)$", title, re.I):
        return None
    if require_active and posted_at is not None and not is_active(posted_at):
        return None

    fit = score_job(
        title, summary, location, employer=employer, source=source, posted_at=posted_at
    )
    if fit.get("location_rank", 9) >= 4 and not fit.get("local_factory"):
        return None

    tags = ["private_job", source]
    if fit.get("local_factory"):
        tags.append("local_factory")
    if fit.get("pathankot"):
        tags.append("pathankot")
    if fit.get("adhoc"):
        tags.append("adhoc")
    if fit.get("store_open"):
        tags.append("store_open")
    if fit.get("active"):
        tags.append("active")
    if fit["usable"]:
        tags.append("usable")

    meta: dict[str, Any] = {
        "source": source,
        "query": query,
        "employer": employer,
        "fit_score": fit["score"],
        "usable": fit["usable"],
        "local_factory": fit.get("local_factory", False),
        "adhoc": fit.get("adhoc", False),
        "store_open": fit.get("store_open", False),
        "pathankot": fit.get("pathankot", False),
        "location_rank": fit.get("location_rank", 9),
        "active": fit.get("active", True),
        "role_hits": fit["role_hits"],
        "near_hits": fit["near_hits"],
    }
    if posted_at:
        meta["posted_at"] = posted_at.isoformat()

    return Lead(
        id=_id(url or f"{title}|{location}|{employer}"),
        portal="private_jobs",
        section="Private jobs",
        kind="jobs",
        title=title,
        url=url,
        location=location or "—",
        summary=(summary or "")[:400],
        tags=tags,
        scraped_at=_now(),
        buyer=employer or source,
        meta=meta,
    )


def _unwrap_ddg(href: str) -> str:
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    return href


def _is_job_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in JOB_HOSTS)


def _scrape_foodtechnetwork(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    base = "https://www.foodtechnetwork.in"
    seen_urls: set[str] = set()
    for emp in _local_employers():
        name = emp.get("name") or ""
        loc = emp.get("location") or "Pathankot, Punjab"
        for term in list(emp.get("search") or [])[:3]:
            try:
                r = client.get(f"{base}/?s={quote_plus(term)}")
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text[:500_000], "html.parser")
                for art in soup.select("article")[:15]:
                    a = art.select_one("h2.entry-title a, h3.entry-title a, h2 a")
                    if not a:
                        continue
                    href = a.get("href") or ""
                    if not href.startswith("http"):
                        href = urljoin(base, href)
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = a.get_text(" ", strip=True)
                    date_el = art.select_one(".entry-date, .entry-meta-date, time")
                    posted = parse_posted_date(
                        date_el.get_text(" ", strip=True) if date_el else None
                    )
                    lead = _lead(
                        title=title,
                        url=href,
                        location=loc,
                        summary=(
                            f"{name} · FoodTechNetwork · posted "
                            f"{date_el.get_text(strip=True) if date_el else '?'}"
                        ),
                        source="foodtech",
                        query=term,
                        employer=name,
                        posted_at=posted,
                        require_active=True,
                    )
                    if lead:
                        leads.append(lead)
            except httpx.HTTPError:
                continue
    return leads


def _scrape_apna_local(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    near_words = ("pathankot", "sujanpur", "gurdaspur", "kathua", "jammu", "samba")
    for city in _apna_cities()[:4]:
        slug = f"full_time-jobs-in-{city}"
        try:
            r = client.get(f"https://apna.co/jobs/{slug}")
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text[:700_000], "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("https://apna.co/job/"):
                    continue
                text = a.get_text(" ", strip=True)
                if len(text) < 20:
                    continue
                href_l = href.lower()
                text_l = text.lower()
                if city == "pathankot":
                    if "/job/pathankot/" not in href_l and "pathankot" not in text_l:
                        if not any(h in text_l for h in LOCAL_EMPLOYER_HINTS):
                            continue
                elif not (
                    f"/job/{city}/" in href_l
                    or any(w in text_l for w in near_words)
                    or any(h in text_l for h in LOCAL_EMPLOYER_HINTS)
                ):
                    continue
                if "delivery boy" in text_l and not any(
                    t in text_l for t in ("factory", "supervisor", "engineer", "it ", "computer")
                ):
                    continue
                employer = ""
                for hint in LOCAL_EMPLOYER_HINTS:
                    if hint in text_l:
                        employer = hint.title()
                        break
                loc_label = (
                    "Pathankot, Punjab"
                    if city == "pathankot" or "pathankot" in text_l
                    else f"{city.title()} · near Pathankot"
                )
                lead = _lead(
                    title=text.split("₹")[0].strip()[:160],
                    url=href,
                    location=loc_label,
                    summary=text[:360],
                    source="apna",
                    query=slug,
                    employer=employer,
                    posted_at=datetime.now(timezone.utc),
                )
                if lead:
                    leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_jobsfood_local(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    urls = [
        "https://jobsfood.tech/job-opportunities-in-distillery-plant/",
        "https://jobsfood.tech/category/food-technology-jobs-2/",
    ]
    for page in urls:
        try:
            r = client.get(page)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text[:400_000], "html.parser")
            for a in soup.select("article h2 a, .entry-title a, h3 a")[:20]:
                href = a.get("href") or ""
                if not href.startswith("http"):
                    continue
                title = a.get_text(" ", strip=True)
                if len(title) < 12:
                    continue
                tl = title.lower()
                if not any(
                    w in tl or w in href.lower()
                    for w in (
                        "pioneer",
                        "distillery",
                        "pathankot",
                        "kandhari",
                        "varun",
                        "beverage",
                        "factory",
                    )
                ):
                    continue
                parent = a.find_parent("article") or a.parent
                date_el = parent.select_one("time, .entry-date, .posted-on") if parent else None
                raw_date = None
                if date_el:
                    raw_date = date_el.get("datetime") or date_el.get_text(" ", strip=True)
                posted = parse_posted_date(raw_date)
                lead = _lead(
                    title=title,
                    url=href,
                    location="Pathankot, Punjab",
                    summary="jobsfood.tech · Pathankot manufacturing",
                    source="local_factory",
                    query="pathankot factory",
                    employer="Pioneer Industries" if "pioneer" in tl else "",
                    posted_at=posted,
                    require_active=posted is not None,
                )
                if lead:
                    leads.append(lead)
            if "distillery-plant" in page:
                body = soup.get_text("\n", strip=True)
                for m in re.finditer(
                    r"(\d+[\.\)]?\s+[A-Za-z][^\n]{8,80})\s*\n\s*Qualification[^\n]{0,120}",
                    body,
                ):
                    role = m.group(1).strip()
                    lead = _lead(
                        title=f"Pioneer Industries Pathankot — {role}",
                        url=page,
                        location="Pathankot, Punjab",
                        summary=m.group(0)[:320],
                        source="local_factory",
                        query="pioneer pathankot",
                        employer="Pioneer Industries",
                        posted_at=datetime.now(timezone.utc),
                    )
                    if lead:
                        leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_duckduckgo(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    combos: list[tuple[str, str]] = []
    pathankot_locs = [
        l for l in _locations() if "pathankot" in l.lower() or "sujanpur" in l.lower()
    ]
    other_locs = [l for l in _locations() if l not in pathankot_locs]
    for loc in (pathankot_locs + other_locs)[:5]:
        for q in _queries()[:8]:
            combos.append((q, loc))
    for q, loc in combos[:16]:
        query = f"{q} jobs {loc} 2026"
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            r = client.get(url)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a.result__a")[:10]:
                title = a.get_text(" ", strip=True)
                href = _unwrap_ddg(a.get("href") or "")
                if not href.startswith("http"):
                    continue
                snippet_el = a.find_parent("div", class_="result") or a.parent
                snippet = ""
                if snippet_el:
                    sn = snippet_el.select_one(".result__snippet")
                    snippet = sn.get_text(" ", strip=True) if sn else ""
                if not _is_job_url(href):
                    fit = score_job(title, snippet, loc)
                    if fit["score"] < 50 or fit.get("location_rank", 9) > 1:
                        continue
                lead = _lead(
                    title=title,
                    url=href,
                    location=loc,
                    summary=snippet or f"Web · {q}",
                    source="web",
                    query=q,
                    posted_at=None,
                    require_active=False,
                )
                if lead:
                    leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_remotive(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    for q in ("training India", "IT support India", "AI trainer"):
        try:
            r = client.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(q)}")
            if r.status_code >= 400:
                continue
            for j in (r.json().get("jobs") or [])[:25]:
                title = j.get("title") or ""
                loc = j.get("candidate_required_location") or "Remote"
                loc_l = loc.lower()
                if not any(x in loc_l for x in ("india", "worldwide", "anywhere")):
                    continue
                posted = parse_posted_date(j.get("publication_date"))
                cats = (
                    " ".join(j.get("categories") or [])
                    if isinstance(j.get("categories"), list)
                    else str(j.get("category") or "")
                )
                lead = _lead(
                    title=title,
                    url=j.get("url") or "",
                    location=loc,
                    summary=f"{j.get('company_name') or ''} · {cats} · Remotive",
                    source="remotive",
                    query=q,
                    posted_at=posted,
                    require_active=True,
                )
                if lead and (lead.meta or {}).get("fit_score", 0) >= 30:
                    leads.append(lead)
        except (httpx.HTTPError, ValueError):
            continue
    return leads


def _dedupe(leads: list[Lead]) -> list[Lead]:
    seen: set[str] = set()
    out: list[Lead] = []
    for lead in leads:
        key = (lead.url or lead.title).lower().split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(lead)
    out.sort(
        key=lambda x: (
            int((x.meta or {}).get("location_rank", 9)),
            0 if (x.meta or {}).get("active", True) else 1,
            0 if "usable" in (x.tags or []) else 1,
            -int((x.meta or {}).get("fit_score") or 0),
        )
    )
    return out


def _scrape_retail_adhoc(client: httpx.Client) -> list[Lead]:
    """Ad-hoc specialist + brands opening stores in Pathankot / nearby."""
    leads: list[Lead] = []
    brand_qs = [
        f"{b} Pathankot hiring" for b in _retail_brands()[:10]
    ] + [
        "new store opening Pathankot jobs",
        "showroom opening Pathankot",
        "franchise Pathankot hiring",
        "store manager Pathankot",
        "adhoc specialist Pathankot IT",
        "freelance IT consultant Pathankot",
        "visiting faculty computer Pathankot",
        "POS training Pathankot store",
        "CCTV installation Pathankot contract",
        "part time computer trainer Pathankot",
    ]
    for q in brand_qs[:18]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(q + ' 2026')}"
        try:
            r = client.get(url)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a.result__a")[:8]:
                title = a.get_text(" ", strip=True)
                href = _unwrap_ddg(a.get("href") or "")
                if not href.startswith("http"):
                    continue
                snippet_el = a.find_parent("div", class_="result") or a.parent
                snippet = ""
                if snippet_el:
                    sn = snippet_el.select_one(".result__snippet")
                    snippet = sn.get_text(" ", strip=True) if sn else ""
                blob = f"{title} {snippet} {q}".lower()
                is_adhoc = any(t in blob for t in ADHOC_TOKENS)
                is_store = any(t in blob for t in STORE_OPEN_TOKENS) or any(
                    b in blob for b in _retail_brands()
                )
                if not (is_adhoc or is_store or "pathankot" in blob):
                    continue
                src = "adhoc" if is_adhoc and not is_store else ("retail" if is_store else "web")
                brand = next((b.title() for b in _retail_brands() if b in blob), "")
                lead = _lead(
                    title=title,
                    url=href,
                    location="Pathankot, Punjab",
                    summary=snippet or f"Side hustle · {q}",
                    source=src,
                    query=q,
                    employer=brand,
                    posted_at=None,
                    require_active=False,
                )
                if lead:
                    leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def scrape_private_jobs() -> list[Lead]:
    """Pathankot-first active jobs + ad-hoc / store-opening side income."""
    leads: list[Lead] = []
    with _client() as client:
        leads.extend(_scrape_apna_local(client))
        leads.extend(_scrape_retail_adhoc(client))
        leads.extend(_scrape_foodtechnetwork(client))
        leads.extend(_scrape_jobsfood_local(client))
        leads.extend(_scrape_duckduckgo(client))
        leads.extend(_scrape_remotive(client))
    return _dedupe(leads)[:220]


def local_factory_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        posted = parse_posted_date(meta.get("posted_at"))
        if posted and not is_active(posted):
            continue
        tags = d.get("tags") or []
        if meta.get("local_factory") or "local_factory" in tags:
            out.append(d)
            continue
        blob = f"{d.get('title')} {d.get('summary')} {d.get('buyer')}".lower()
        if any(h in blob for h in LOCAL_EMPLOYER_HINTS):
            out.append(d)
    out.sort(
        key=lambda x: (
            int((x.get("meta") or {}).get("location_rank", 9)),
            -int((x.get("meta") or {}).get("fit_score") or 0),
        )
    )
    return out


def usable_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        posted = parse_posted_date(meta.get("posted_at"))
        if posted and not is_active(posted):
            continue
        if meta.get("usable") or "usable" in (d.get("tags") or []):
            out.append(d)
            continue
        fit = score_job(
            d.get("title") or "",
            d.get("summary") or "",
            d.get("location") or "",
            employer=str(meta.get("employer") or d.get("buyer") or ""),
            source=str(meta.get("source") or ""),
            posted_at=posted,
        )
        if fit["usable"]:
            d.setdefault("meta", {}).update(fit)
            out.append(d)
    out.sort(
        key=lambda x: (
            int((x.get("meta") or {}).get("location_rank", 9)),
            -int((x.get("meta") or {}).get("fit_score") or 0),
        )
    )
    return out


def adhoc_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Ad-hoc / specialist / store-opening / freelance side-income leads near Pathankot."""
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        posted = parse_posted_date(meta.get("posted_at"))
        if posted and not is_active(posted):
            continue
        tags = d.get("tags") or []
        blob = f"{d.get('title')} {d.get('summary')} {d.get('location')} {d.get('buyer')}".lower()
        if (
            meta.get("adhoc")
            or meta.get("store_open")
            or "adhoc" in tags
            or "store_open" in tags
            or any(t in blob for t in ADHOC_TOKENS)
            or any(t in blob for t in STORE_OPEN_TOKENS)
            or any(b in blob for b in _retail_brands())
        ):
            # Prefer near Pathankot belt
            if location_rank(blob) > 2:
                continue
            out.append(d)
    out.sort(
        key=lambda x: (
            int((x.get("meta") or {}).get("location_rank", 9)),
            0 if (x.get("meta") or {}).get("adhoc") else 1,
            -int((x.get("meta") or {}).get("fit_score") or 0),
        )
    )
    return out


def pathankot_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Active jobs in Pathankot city / plant (not only 'near Pathankot')."""
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        posted = parse_posted_date(meta.get("posted_at"))
        if posted and not is_active(posted):
            continue
        blob = f"{d.get('title')} {d.get('summary')} {d.get('location')} {d.get('buyer')}"
        rank = meta.get("location_rank")
        if rank is None:
            rank = location_rank(blob)
        # Home only
        if int(rank) == 0 or re.search(
            r"pathankot,\s*punjab|/job/pathankot/|pathankot plant", blob, re.I
        ):
            # Exclude pure Kathua/Jammu with only "near Pathankot"
            if re.search(r"\bkathua\b|\bjammu\b|\bsamba\b", blob, re.I) and not re.search(
                r"pathankot,\s*punjab|/job/pathankot/|sujanpur", blob, re.I
            ):
                continue
            out.append(d)
    out.sort(key=lambda x: -int((x.get("meta") or {}).get("fit_score") or 0))
    return out
