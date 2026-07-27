from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .approval import ApprovalGate
from .pipeline import TenderPipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"

# In-process scrape job (one at a time) so the UI can poll progress.
_scrape_lock = threading.Lock()
_scrape_job: dict[str, Any] = {
    "status": "idle",
    "message": "No scrape running",
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_scrape_job(portals: list[str] | None) -> None:
    global _scrape_job
    try:
        from .hub import run_hub_scrape

        _scrape_job["message"] = "Scanning portals…"
        result = run_hub_scrape(portals=portals, fit_pages=1, fit_max_docs=20)
        counts = result.get("counts") or {}
        total = sum(int(v) for v in counts.values())
        rec = result.get("recommendations") or {}
        _scrape_job.update(
            {
                "status": "done",
                "message": f"Updated {total:,} listings"
                + (f" · {rec.get('apply', 0)} apply matches" if rec else ""),
                "finished_at": _utc_now(),
                "result": result,
                "error": None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        _scrape_job.update(
            {
                "status": "error",
                "message": f"Scrape failed: {exc}",
                "finished_at": _utc_now(),
                "error": str(exc),
            }
        )
    finally:
        try:
            _scrape_lock.release()
        except RuntimeError:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .hub.scheduler import start_daily_scheduler, stop_daily_scheduler

    start_daily_scheduler()
    yield
    stop_daily_scheduler()


app = FastAPI(
    title="Pathankot Pulse",
    description="Sectioned multi-portal leads — GeM, CPPP, Punjab, bank/gov auctions, OLX",
    version="0.3.0",
    lifespan=lifespan,
)


class ManualIn(BaseModel):
    bid_number: str
    title: str
    url: str | None = None
    ministry: str | None = None
    score: float = 0.7


class NoteIn(BaseModel):
    note: str = ""


def _hub_html() -> str:
    path = STATIC_DIR / "hub.html"
    return path.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Pathankot Pulse — primary public-facing UI (private mode default)."""
    return _hub_html()


@app.get("/health")
def health():
    from .hub.scheduler import scheduler_status

    return {"ok": True, "service": "pathankot-pulse", "scheduler": scheduler_status()}


@app.get("/api/hub")
def api_hub():
    from .hub.jobs import adhoc_jobs, local_factory_jobs, pathankot_jobs, usable_jobs
    from .hub.recommend import load_recommendations
    from .hub.scheduler import scheduler_status
    from .hub.store import load_hub_config, load_leads

    data = load_leads()
    cfg = load_hub_config()
    # Strip any legacy shortcut cards from API responses
    by = data.get("by_portal") or {}
    cleaned = {}
    for portal, rows in by.items():
        cleaned[portal] = [
            r
            for r in rows
            if "shortcut" not in (r.get("tags") or [])
            and "google.com/search" not in (r.get("url") or "")
            and not str(r.get("title") or "").lower().startswith(("search ", "open "))
        ]
    data["by_portal"] = cleaned
    data["counts"] = {k: len(v) for k, v in cleaned.items()}
    data["config"] = {
        "brand": (cfg.get("owner") or {}).get("brand"),
        "tagline": (cfg.get("owner") or {}).get("tagline"),
        "mode": (cfg.get("owner") or {}).get("mode"),
        "portals": cfg.get("portals") or [],
        "region": cfg.get("region") or data.get("region"),
        "tender_filters": cfg.get("tender_filters") or {},
        "private_jobs": cfg.get("private_jobs") or {},
    }
    data["scheduler"] = scheduler_status()
    data["recommendations"] = load_recommendations()
    jobs = cleaned.get("private_jobs") or []
    data["private_jobs"] = {
        "all": jobs,
        "usable": usable_jobs(jobs),
        "local_factory": local_factory_jobs(jobs),
        "pathankot": pathankot_jobs(jobs),
        "adhoc": adhoc_jobs(jobs),
        "count": len(jobs),
        "usable_count": len(usable_jobs(jobs)),
        "local_factory_count": len(local_factory_jobs(jobs)),
        "pathankot_count": len(pathankot_jobs(jobs)),
        "adhoc_count": len(adhoc_jobs(jobs)),
    }
    return data


@app.get("/api/hub/jobs")
def api_hub_jobs(usable_only: bool = Query(False)):
    from .hub.jobs import local_factory_jobs, usable_jobs
    from .hub.store import load_leads

    rows = (load_leads().get("by_portal") or {}).get("private_jobs") or []
    if usable_only:
        return {"jobs": usable_jobs(rows), "count": len(usable_jobs(rows))}
    return {"jobs": rows, "usable": usable_jobs(rows), "count": len(rows)}


@app.post("/api/hub/jobs/scrape")
def api_hub_jobs_scrape():
    """Scrape only private jobs + send alerts for new usable matches."""
    from .hub import run_hub_scrape

    return run_hub_scrape(
        portals=["private_jobs"],
        with_recommendations=False,
        fit_pages=0,
        fit_max_docs=0,
    )


@app.post("/api/hub/alerts/test")
def api_hub_alerts_test():
    """Re-send alert for current usable jobs (ignores dedupe)."""
    from .hub.alerts import alert_new_usable_jobs

    return alert_new_usable_jobs(force=True)


@app.get("/api/hub/recommendations")
def api_hub_recommendations():
    from .hub.recommend import load_recommendations

    return load_recommendations()


@app.post("/api/hub/recommendations")
def api_hub_recommendations_run(pages: int = 2, max_docs: int = 30):
    from .hub.recommend import build_apply_recommendations

    return build_apply_recommendations(pages=pages, max_docs=max_docs)


@app.get("/api/hub/scrape/status")
def api_hub_scrape_status():
    """Poll current / last scrape job (used by Update listings button)."""
    return dict(_scrape_job)


@app.post("/api/hub/scrape")
def api_hub_scrape(
    portals: str | None = Query(None, description="Comma-separated portal ids"),
    sync: bool = Query(False, description="If true, block until scrape finishes"),
):
    """Start a portal scrape + preference re-match.

    Default is async (returns immediately; poll ``/api/hub/scrape/status``).
    Pass ``sync=true`` for CLI / scripts.
    """
    from .hub import run_hub_scrape

    selected = [p.strip() for p in portals.split(",") if p.strip()] if portals else None

    if sync:
        return run_hub_scrape(portals=selected, fit_pages=1, fit_max_docs=20)

    if not _scrape_lock.acquire(blocking=False):
        return {
            "ok": False,
            "started": False,
            "status": _scrape_job.get("status"),
            "message": _scrape_job.get("message") or "Scrape already running",
        }

    _scrape_job.update(
        {
            "status": "running",
            "message": "Starting scrape across GeM, CPPP, TendersPlus, auctions…",
            "started_at": _utc_now(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
    )
    threading.Thread(target=_run_scrape_job, args=(selected,), daemon=True).start()
    # Tiny yield so status is readable immediately
    time.sleep(0.05)
    return {
        "ok": True,
        "started": True,
        "status": "running",
        "message": _scrape_job["message"],
    }


@app.get("/gem", response_class=HTMLResponse)
def gem_operator_ui() -> str:
    """Legacy GeM tender operator dashboard."""
    return _GEM_OPERATOR_HTML


_GEM_OPERATOR_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>GeM Tender Agent</title>
  <style>
    :root { --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa8bc; --accent:#3d9cf0; --ok:#3ecf8e; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:radial-gradient(1200px 600px at 10% -10%, #1b2a44, var(--bg)); color:var(--text); }
    main { max-width:1100px; margin:0 auto; padding:32px 20px 60px; }
    h1 { font-size:28px; margin:0 0 8px; }
    p { color:var(--muted); }
    .row { display:flex; gap:10px; flex-wrap:wrap; margin:18px 0 24px; }
    button { background:var(--accent); color:#041018; border:0; border-radius:10px; padding:10px 14px; font-weight:700; cursor:pointer; }
    button.secondary { background:#243246; color:var(--text); }
    table { width:100%; border-collapse:collapse; background:var(--card); border-radius:14px; overflow:hidden; }
    th, td { padding:10px 12px; border-bottom:1px solid #2a3750; text-align:left; font-size:14px; vertical-align:top; }
    th { color:var(--muted); font-weight:600; }
    a { color:#8ec5ff; }
    .tag { display:inline-block; padding:2px 8px; border-radius:999px; background:#243246; font-size:12px; }
    .ok { color:var(--ok); }
  </style>
</head>
<body>
<main>
  <p><a href="/">← Pathankot Pulse</a></p>
  <h1>GeM Tender Agent</h1>
  <p>AI training contractor mode: no EMD · ≤2y exp · ≤₹40L turnover · ≥7 days left · Pathankot rank.</p>
  <div class="row">
    <button onclick="runScout()">Run scout</button>
    <button onclick="runUpcoming()" style="background:#3ecf8e;color:#041018">Closing next 7 days</button>
    <button class="warn" onclick="runFit()" style="background:#ffb020;color:#1a1200">Contractor fit (Pathankot)</button>
    <button class="secondary" onclick="runDaily()">Daily digest</button>
    <button class="secondary" onclick="loadRows()">Refresh</button>
    <button class="secondary" onclick="loadFit()">Show last fit report</button>
    <button class="secondary" onclick="loadUpcoming()">Show last closing list</button>
  </div>
  <div id="status" class="ok"></div>
  <h3>Closing next 7 days (AI / training)</h3>
  <table>
    <thead>
      <tr><th>Days left</th><th>End</th><th>Bid</th><th>Buyer</th><th>Title</th></tr>
    </thead>
    <tbody id="upcoming"></tbody>
  </table>
  <h3>Eligible contractor matches</h3>
  <table>
    <thead>
      <tr><th>Prox</th><th>Bid</th><th>Exp</th><th>TO</th><th>Where</th><th>End</th><th>Title</th></tr>
    </thead>
    <tbody id="fit"></tbody>
  </table>
  <h3>All scored tenders</h3>
  <table>
    <thead>
      <tr><th>Score</th><th>Bid</th><th>Title</th><th>Decision</th><th>End</th><th>Actions</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</main>
<script>
async function loadRows(){
  const res = await fetch('/api/tenders');
  const data = await res.json();
  const body = document.getElementById('rows');
  body.innerHTML = data.map(r => `
    <tr>
      <td>${(r.fit_score||0).toFixed(2)}</td>
      <td><div>${r.bid_number}</div><a href="${r.url||'#'}" target="_blank">open</a></td>
      <td>${r.title||''}</td>
      <td><span class="tag">${r.decision||'-'}</span></td>
      <td>${(r.end_at||'').slice(0,10)}</td>
      <td>
        <button class="secondary" onclick="analyze('${r.bid_number}')">Analyse</button>
        <button class="secondary" onclick="draft('${r.bid_number}')">Draft</button>
        <button onclick="approve('${r.bid_number}')">Approve</button>
      </td>
    </tr>`).join('');
}
function renderFit(payload){
  const rows = (payload.matches||[]);
  document.getElementById('fit').innerHTML = rows.map(r => `
    <tr>
      <td>${r.proximity||0}</td>
      <td><div>${r.bid_number||''}</div><a href="${r.url||'#'}" target="_blank">open</a></td>
      <td>${r.experience_years_required ?? '—'}</td>
      <td>${r.turnover_required_inr==null ? '—' : (r.turnover_required_inr/100000).toFixed(1)+'L'}</td>
      <td>${(r.cities||r.states||[]).slice(0,2).join(',')||'?'}</td>
      <td>${(r.end_at||'').slice(0,10)}</td>
      <td>${(r.title||'').slice(0,80)}</td>
    </tr>`).join('') || '<tr><td colspan="7">No eligible matches yet — click Contractor fit</td></tr>';
  document.getElementById('status').textContent =
    `Fit: ${rows.length} matches · scanned ${payload.scanned||0} · report ${payload.report_path||''}`;
}
async function loadFit(){
  const res = await fetch('/api/contractor-fit');
  const data = await res.json();
  renderFit(data);
}
async function runFit(){
  document.getElementById('status').textContent = 'Running contractor-fit scrape (GeM PDFs + watchlist)… this can take a few minutes';
  const res = await fetch('/api/contractor-fit', {method:'POST'});
  const data = await res.json();
  renderFit(data);
}
function renderUpcoming(payload){
  const rows = (payload.tenders||[]);
  document.getElementById('upcoming').innerHTML = rows.map(r => `
    <tr>
      <td><span class="tag">${r.days_left ?? '?'}d</span></td>
      <td>${(r.end_at||'').slice(0,16).replace('T',' ')}</td>
      <td><div>${r.bid_number||''}</div><a href="${r.url||'#'}" target="_blank">open</a></td>
      <td>${[r.ministry,r.department].filter(Boolean).join(' / ')||'—'}</td>
      <td>${(r.title||'').slice(0,100)}</td>
    </tr>`).join('') || '<tr><td colspan="5">No closing tenders in window — click Closing next 7 days</td></tr>';
  document.getElementById('status').textContent =
    `Closing ${payload.window_start||''}→${payload.window_end||''}: ${payload.count||0} tenders · scanned ${payload.listings_scanned||0}`;
}
async function loadUpcoming(){
  const res = await fetch('/api/upcoming-closing');
  const data = await res.json();
  renderUpcoming(data);
}
async function runUpcoming(){
  document.getElementById('status').textContent = 'Scanning GeM for bids closing in next 7 days…';
  const res = await fetch('/api/upcoming-closing?days=7&pages=2', {method:'POST'});
  const data = await res.json();
  renderUpcoming(data);
}
async function runScout(){
  document.getElementById('status').textContent = 'Scouting GeM…';
  await fetch('/api/scout', {method:'POST'});
  document.getElementById('status').textContent = 'Scout complete';
  loadRows();
}
async function runDaily(){
  document.getElementById('status').textContent = 'Running daily pipeline…';
  await fetch('/api/daily', {method:'POST'});
  document.getElementById('status').textContent = 'Daily complete';
  loadRows();
}
async function analyze(bid){
  document.getElementById('status').textContent = 'Analysing '+bid;
  await fetch('/api/analyze/'+encodeURIComponent(bid), {method:'POST'});
  loadRows();
}
async function draft(bid){
  document.getElementById('status').textContent = 'Drafting '+bid;
  const res = await fetch('/api/draft/'+encodeURIComponent(bid), {method:'POST'});
  const data = await res.json();
  document.getElementById('status').textContent = 'Draft: '+(data.path||'');
  loadRows();
}
async function approve(bid){
  await fetch('/api/approve/'+encodeURIComponent(bid), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({note:'Approved via UI'})});
  document.getElementById('status').textContent = 'Approved '+bid;
  loadRows();
}
loadRows();
loadFit();
loadUpcoming();
</script>
</body>
</html>
"""


@app.get("/api/tenders")
def api_tenders(min_score: float = 0.3, limit: int = 50):
    pipe = TenderPipeline()
    return pipe.db.list_tenders(min_score=min_score, limit=limit)


@app.post("/api/scout")
def api_scout():
    pipe = TenderPipeline()
    scored = pipe.scout(pages_per_query=1, include_cppp=False)
    return {"matched": len(scored)}


@app.post("/api/daily")
def api_daily():
    pipe = TenderPipeline()
    return pipe.run_daily(top_n=8, auto_analyze=True)


@app.post("/api/analyze/{bid_number:path}")
def api_analyze(bid_number: str):
    pipe = TenderPipeline()
    try:
        result = pipe.analyze(bid_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result.model_dump()


@app.post("/api/draft/{bid_number:path}")
def api_draft(bid_number: str):
    pipe = TenderPipeline()
    try:
        path = pipe.draft(bid_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"path": path}


@app.post("/api/approve/{bid_number:path}")
def api_approve(bid_number: str, body: NoteIn):
    gate = ApprovalGate()
    try:
        result = gate.approve(bid_number, body.note)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": result.status.value, "message": result.message}


@app.post("/api/reject/{bid_number:path}")
def api_reject(bid_number: str, body: NoteIn):
    gate = ApprovalGate()
    result = gate.reject(bid_number, body.note)
    return {"status": result.status.value, "message": result.message}


@app.post("/api/manual")
def api_manual(body: ManualIn):
    from .scout.cppp import manual_tender

    pipe = TenderPipeline()
    tender = manual_tender(
        bid_number=body.bid_number,
        title=body.title,
        url=body.url,
        ministry=body.ministry,
    )
    pipe.db.upsert_tender(
        tender,
        fit_score=body.score,
        matched_keywords=["manual"],
        reasons=["Manual entry"],
    )
    return {"ok": True}


@app.get("/api/contractor-fit")
def api_contractor_fit_get():
    import json
    from .config import OUTPUT_DIR

    digests = sorted((OUTPUT_DIR / "digests").glob("ai_train_contractor_fit_*.json"), reverse=True)
    if not digests:
        return {"matches": [], "scanned": 0, "message": "No report yet"}
    data = json.loads(digests[0].read_text(encoding="utf-8"))
    data["report_path"] = str(digests[0])
    return data


@app.post("/api/contractor-fit")
def api_contractor_fit_run(pages: int = 2, max_docs: int = 40):
    import json
    from datetime import datetime

    from .scout.contractor_fit import run_contractor_fit_scout, save_report

    payload = run_contractor_fit_scout(pages=pages, max_docs=max_docs)
    path = save_report(payload)
    serializable = json.loads(
        json.dumps(payload, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o))
    )
    serializable["report_path"] = str(path)
    return serializable


@app.get("/api/upcoming-closing")
def api_upcoming_closing_get():
    import json
    from .config import OUTPUT_DIR

    digests = sorted((OUTPUT_DIR / "digests").glob("upcoming_closing_*.json"), reverse=True)
    if not digests:
        return {"tenders": [], "count": 0, "message": "No report yet"}
    data = json.loads(digests[0].read_text(encoding="utf-8"))
    data["report_path"] = str(digests[0])
    return data


@app.post("/api/upcoming-closing")
def api_upcoming_closing_run(days: int = 7, pages: int = 2):
    from .scout.upcoming import run_upcoming_closing_scout, save_upcoming_report

    payload = run_upcoming_closing_scout(days=days, pages=pages)
    path = save_upcoming_report(payload)
    payload["report_path"] = str(path)
    return payload
