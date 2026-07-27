"""Private jobs near Pathankot / Kathua / Jammu / Punjab.

Priority sources:
- Local factories/brands (Kandhari/Coca-Cola, Varun/Pepsi, Pioneer, PDIL) via FoodTechNetwork + Apna
- Remote AI / IT boards (Remotive, Jobicy, WeWorkRemotely) as secondary
"""

from __future__ import annotations

import hashlib
import re
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
    "AI training partner",
    "digital literacy trainer",
    "computer instructor",
    "IT support",
    "area manager IT",
    "software contractor",
    "skill development trainer",
    "technical support engineer",
]

DEFAULT_LOCATIONS = [
    "Pathankot",
    "Kathua",
    "Jammu",
    "Gurdaspur",
    "Punjab",
]

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
]

NEAR_TOKENS = [
    "pathankot",
    "kathua",
    "jammu",
    "gurdaspur",
    "punjab",
    "sujanpur",
    "kangra",
    "j&k",
    "jammu and kashmir",
    "samba",
    "chandigarh",
    "mohali",
    "jalandhar",
    "amritsar",
    "india",
    "remote",
    "work from home",
    "wfh",
    "worldwide",
    "anywhere",
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
)


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
    return (load_hub_config().get("private_jobs") or {})


def _queries() -> list[str]:
    return list(_cfg_jobs().get("queries") or DEFAULT_QUERIES)


def _locations() -> list[str]:
    return list(_cfg_jobs().get("locations") or DEFAULT_LOCATIONS)


def _local_employers() -> list[dict[str, Any]]:
    return list(_cfg_jobs().get("local_employers") or [])


def _apna_cities() -> list[str]:
    return list(_cfg_jobs().get("apna_cities") or ["pathankot", "kathua", "jammu"])


def score_job(
    title: str,
    summary: str = "",
    location: str = "",
    *,
    employer: str = "",
    source: str = "",
) -> dict[str, Any]:
    blob = f"{title} {summary} {location} {employer}".lower()
    role_hits = [t for t in FIT_TOKENS if t in blob]
    near_hits = [t for t in NEAR_TOKENS if t in blob]
    factory_hits = [t for t in FACTORY_ROLE_TOKENS if t in blob]
    employer_hit = any(h in blob for h in LOCAL_EMPLOYER_HINTS)
    score = min(100, 12 * len(set(role_hits)) + 10 * len(set(near_hits)) + 8 * len(set(factory_hits)))
    remoteish = any(t in blob for t in ("remote", "wfh", "work from home", "worldwide", "anywhere"))
    is_near = bool(near_hits) or any(x in blob for x in ("pathankot", "kathua", "jammu", "gurdaspur", "samba"))

    # Local factory / brand hiring (Coca-Cola, Pepsi, Pioneer, etc.)
    if source in ("local_factory", "apna", "foodtech") or employer_hit:
        score = max(score, 55 if employer_hit else 42)
        usable = is_near and (employer_hit or bool(factory_hits) or bool(role_hits))
        return {
            "score": score,
            "usable": usable,
            "role_hits": (role_hits + factory_hits)[:6],
            "near_hits": near_hits[:4],
            "local_factory": True,
        }

    usable = score >= 24 and bool(role_hits) and (bool(near_hits) or remoteish)
    return {
        "score": score,
        "usable": usable,
        "role_hits": role_hits[:6],
        "near_hits": near_hits[:4],
        "local_factory": False,
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
) -> Lead | None:
    title = " ".join((title or "").split())
    if len(title) < 10:
        return None
    if re.search(r"^(home|login|privacy|cookie|about|search)$", title, re.I):
        return None
    fit = score_job(title, summary, location, employer=employer, source=source)
    tags = ["private_job", source]
    if fit.get("local_factory"):
        tags.append("local_factory")
    if fit["usable"]:
        tags.append("usable")
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
        meta={
            "source": source,
            "query": query,
            "employer": employer,
            "fit_score": fit["score"],
            "usable": fit["usable"],
            "local_factory": fit.get("local_factory", False),
            "role_hits": fit["role_hits"],
            "near_hits": fit["near_hits"],
        },
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
    """Scrape FoodTechNetwork for Kandhari / Varun / Pioneer hiring posts."""
    leads: list[Lead] = []
    base = "https://www.foodtechnetwork.in"
    seen_urls: set[str] = set()
    for emp in _local_employers():
        name = emp.get("name") or ""
        loc = emp.get("location") or "Pathankot belt"
        for term in list(emp.get("search") or [])[:3]:
            try:
                r = client.get(f"{base}/?s={quote_plus(term)}")
                if r.status_code >= 400:
                    continue
                soup = BeautifulSoup(r.text[:500_000], "html.parser")
                for a in soup.select("h2.entry-title a, h3.entry-title a, article h2 a")[:12]:
                    href = a.get("href") or ""
                    if not href.startswith("http"):
                        href = urljoin(base, href)
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = a.get_text(" ", strip=True)
                    lead = _lead(
                        title=title,
                        url=href,
                        location=loc,
                        summary=f"{name} · FoodTechNetwork · {term}",
                        source="foodtech",
                        query=term,
                        employer=name,
                    )
                    if lead:
                        leads.append(lead)
            except httpx.HTTPError:
                continue
    return leads


def _scrape_apna_local(client: httpx.Client) -> list[Lead]:
    """Apna.co verified vacancies in Pathankot / Kathua / Jammu."""
    leads: list[Lead] = []
    near_words = ("pathankot", "kathua", "jammu", "gurdaspur", "samba", "sujanpur")
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
                # Keep only jobs in our belt (URL slug or visible location)
                if not (
                    f"/job/{city}/" in href_l
                    or any(w in text_l for w in near_words)
                    or any(h in text_l for h in LOCAL_EMPLOYER_HINTS)
                ):
                    continue
                # Skip pure delivery-only unless factory keyword
                if "delivery boy" in text_l and not any(
                    t in text_l for t in ("factory", "supervisor", "engineer", "it ", "computer")
                ):
                    continue
                employer = ""
                for hint in LOCAL_EMPLOYER_HINTS:
                    if hint in text_l:
                        employer = hint.title()
                        break
                lead = _lead(
                    title=text.split("₹")[0].strip()[:160],
                    url=href,
                    location=city.title() + ", near Pathankot belt",
                    summary=text[:360],
                    source="apna",
                    query=slug,
                    employer=employer,
                )
                if lead:
                    leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_jobsfood_local(client: httpx.Client) -> list[Lead]:
    """Pioneer Industries / distillery posts on jobsfood.tech."""
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
            body = soup.get_text(" ", strip=True)
            if "pathankot" not in body.lower() and "distillery" not in page:
                pass
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
                    for w in ("pioneer", "distillery", "pathankot", "kandhari", "varun", "beverage", "factory")
                ):
                    continue
                lead = _lead(
                    title=title,
                    url=href,
                    location="Pathankot, Punjab",
                    summary="jobsfood.tech · local food / beverage manufacturing",
                    source="local_factory",
                    query="distillery",
                    employer="Pioneer Industries" if "pioneer" in tl else "",
                )
                if lead:
                    leads.append(lead)
            # Parse inline vacancy lines on Pioneer distillery page
            if "distillery-plant" in page:
                for m in re.finditer(
                    r"(\d+[\.\)]?\s+[A-Za-z][^\n]{8,80})\s*\n\s*Qualification[^\n]{0,120}",
                    body,
                ):
                    role = m.group(1).strip()
                    lead = _lead(
                        title=f"Pioneer Industries — {role}",
                        url=page,
                        location="Pathankot, Punjab",
                        summary=m.group(0)[:320],
                        source="local_factory",
                        query="pioneer distillery",
                        employer="Pioneer Industries",
                    )
                    if lead:
                        leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_duckduckgo(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    combos: list[tuple[str, str]] = []
    for loc in _locations()[:5]:
        for q in _queries()[:7]:
            combos.append((q, loc))
    # Cap requests
    for q, loc in combos[:18]:
        query = f"{q} jobs {loc}"
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            r = client.get(url)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a.result__a")[:12]:
                title = a.get_text(" ", strip=True)
                href = _unwrap_ddg(a.get("href") or "")
                if not href.startswith("http"):
                    continue
                # Prefer real job hosts; still keep other India results with strong role fit
                snippet_el = a.find_parent("div", class_="result") or a.parent
                snippet = ""
                if snippet_el:
                    sn = snippet_el.select_one(".result__snippet")
                    snippet = sn.get_text(" ", strip=True) if sn else ""
                if not _is_job_url(href):
                    fit = score_job(title, snippet, loc)
                    if fit["score"] < 36:
                        continue
                lead = _lead(
                    title=title,
                    url=href,
                    location=loc,
                    summary=snippet or f"Web result · {q}",
                    source="web",
                    query=q,
                )
                if lead:
                    leads.append(lead)
        except httpx.HTTPError:
            continue
    return leads


def _scrape_remotive(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    searches = ["training", "AI", "support", "education", "software", "teacher"]
    for q in searches:
        try:
            r = client.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(q)}")
            if r.status_code >= 400:
                continue
            for j in (r.json().get("jobs") or [])[:40]:
                title = j.get("title") or ""
                loc = j.get("candidate_required_location") or "Remote"
                cats = " ".join(j.get("categories") or []) if isinstance(j.get("categories"), list) else str(j.get("category") or "")
                summary = f"{j.get('company_name') or ''} · {cats} · Remotive"
                lead = _lead(
                    title=title,
                    url=j.get("url") or "",
                    location=loc,
                    summary=summary,
                    source="remotive",
                    query=q,
                )
                if lead and (lead.meta or {}).get("fit_score", 0) >= 24:
                    leads.append(lead)
        except (httpx.HTTPError, ValueError):
            continue
    return leads


def _scrape_jobicy(client: httpx.Client) -> list[Lead]:
    leads: list[Lead] = []
    for tag in ("software", "education", "support", "devops"):
        try:
            r = client.get(f"https://jobicy.com/api/v2/remote-jobs?count=30&tag={tag}")
            if r.status_code >= 400:
                continue
            for j in (r.json().get("jobs") or [])[:30]:
                title = j.get("jobTitle") or j.get("title") or ""
                loc = j.get("jobGeo") or "Remote"
                summary = f"{j.get('companyName') or ''} · {j.get('jobIndustry') or ''} · Jobicy"
                lead = _lead(
                    title=title,
                    url=j.get("url") or j.get("jobUrl") or "",
                    location=loc,
                    summary=summary,
                    source="jobicy",
                    query=tag,
                )
                if lead and (lead.meta or {}).get("fit_score", 0) >= 24:
                    leads.append(lead)
        except (httpx.HTTPError, ValueError):
            continue
    return leads


def _scrape_wwr_rss(client: httpx.Client) -> list[Lead]:
    import xml.etree.ElementTree as ET

    leads: list[Lead] = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    for feed in feeds:
        try:
            r = client.get(feed)
            if r.status_code >= 400 or "<item>" not in r.text:
                continue
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:30]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True)
                lead = _lead(
                    title=title,
                    url=link,
                    location="Remote",
                    summary=desc[:360],
                    source="weworkremotely",
                    query="remote",
                )
                if lead and (lead.meta or {}).get("fit_score", 0) >= 24:
                    leads.append(lead)
        except Exception:  # noqa: BLE001
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
            0 if "usable" in (x.tags or []) else 1,
            -int((x.meta or {}).get("fit_score") or 0),
        )
    )
    return out


def scrape_private_jobs() -> list[Lead]:
    """Local factories first, then remote IT/training boards."""
    leads: list[Lead] = []
    with _client() as client:
        leads.extend(_scrape_foodtechnetwork(client))
        leads.extend(_scrape_apna_local(client))
        leads.extend(_scrape_jobsfood_local(client))
        leads.extend(_scrape_duckduckgo(client))
        leads.extend(_scrape_remotive(client))
        leads.extend(_scrape_jobicy(client))
        leads.extend(_scrape_wwr_rss(client))
    return _dedupe(leads)[:280]


def local_factory_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Jobs tagged local_factory or from known nearby employers."""
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        tags = d.get("tags") or []
        if meta.get("local_factory") or "local_factory" in tags:
            out.append(d)
            continue
        blob = f"{d.get('title')} {d.get('summary')} {d.get('buyer')}".lower()
        if any(h in blob for h in LOCAL_EMPLOYER_HINTS):
            out.append(d)
    out.sort(key=lambda x: -int((x.get("meta") or {}).get("fit_score") or 0))
    return out


def usable_jobs(leads: list[Lead] | list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if leads is None:
        from .store import load_leads

        leads = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    out: list[dict[str, Any]] = []
    for row in leads:
        d = row.to_dict() if isinstance(row, Lead) else dict(row)
        meta = d.get("meta") or {}
        if meta.get("usable") or "usable" in (d.get("tags") or []):
            out.append(d)
            continue
        fit = score_job(d.get("title") or "", d.get("summary") or "", d.get("location") or "")
        if fit["usable"]:
            d.setdefault("meta", {}).update(fit)
            out.append(d)
    out.sort(key=lambda x: -int((x.get("meta") or {}).get("fit_score") or 0))
    return out
