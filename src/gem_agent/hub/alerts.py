"""Match alerts for usable private jobs (+ optional tender APPLY matches).

Dedupes by lead id under outputs/hub/alerted_ids.json.
Channels: console, Telegram (if configured), email via Gmail SMTP (if app password set).
"""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from ..config import get_settings, load_profile
from ..notify import notify
from .jobs import usable_jobs
from .store import HUB_DIR

ALERTED_PATH = HUB_DIR / "alerted_ids.json"


def _load_alerted() -> set[str]:
    if not ALERTED_PATH.exists():
        return set()
    try:
        data = json.loads(ALERTED_PATH.read_text(encoding="utf-8"))
        return set(data.get("ids") or [])
    except (json.JSONDecodeError, OSError):
        return set()


def _save_alerted(ids: set[str]) -> None:
    HUB_DIR.mkdir(parents=True, exist_ok=True)
    # Keep last 2000 ids
    trimmed = sorted(ids)[-2000:]
    ALERTED_PATH.write_text(
        json.dumps({"ids": trimmed}, indent=2),
        encoding="utf-8",
    )


def _send_email(subject: str, body: str) -> bool:
    settings = get_settings()
    profile = load_profile()
    to_addr = (profile.get("company") or {}).get("contact_email") or ""
    gmail = getattr(settings, "gmail_address", "") or ""
    password = getattr(settings, "gmail_app_password", "") or ""
    # Also read from env via settings fields we'll add
    import os

    gmail = gmail or os.getenv("GMAIL_ADDRESS", "")
    password = password or os.getenv("GMAIL_APP_PASSWORD", "")
    to_addr = to_addr or gmail
    if not (gmail and password and to_addr):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25) as smtp:
            smtp.login(gmail, password)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001
        return False


def format_job_alert(jobs: list[dict[str, Any]]) -> str:
    lines = [
        "Pathankot Pulse — private jobs matching you",
        f"{len(jobs)} usable match(es) near Pathankot / Kathua / Jammu / Punjab",
        "",
    ]
    for j in jobs[:12]:
        meta = j.get("meta") or {}
        score = meta.get("fit_score") or "?"
        lines.append(f"• [{score}] {j.get('title')}")
        lines.append(f"  {j.get('location') or '—'} · {j.get('buyer') or meta.get('source') or ''}")
        if j.get("url"):
            lines.append(f"  {j['url']}")
        why = []
        why.extend(meta.get("role_hits") or [])
        why.extend(meta.get("near_hits") or [])
        if why:
            lines.append(f"  why: {', '.join(why[:6])}")
        lines.append("")
    lines.append("Open Pathankot Pulse → Private jobs tab to review.")
    return "\n".join(lines)


def alert_new_usable_jobs(
    *,
    jobs: list[dict[str, Any]] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Notify on new usable private jobs. Returns summary."""
    pool = jobs if jobs is not None else usable_jobs()
    alerted = _load_alerted()
    fresh = [j for j in pool if force or (j.get("id") and j["id"] not in alerted)]
    if not fresh:
        return {"sent": False, "new": 0, "channels": []}

    text = format_job_alert(fresh)
    channels: list[str] = ["console"]
    settings = get_settings()
    notify(text)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append("telegram")

    if _send_email(
        subject=f"Pathankot Pulse: {len(fresh)} private job match(es) for you",
        body=text,
    ):
        channels.append("email")

    for j in fresh:
        if j.get("id"):
            alerted.add(j["id"])
    _save_alerted(alerted)

    # Persist last alert digest
    digest_path = HUB_DIR / "last_job_alert.txt"
    digest_path.write_text(text, encoding="utf-8")

    return {"sent": True, "new": len(fresh), "channels": channels, "ids": [j.get("id") for j in fresh]}


def alert_apply_tenders(apply_rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Optional: alert when contractor-fit finds APPLY-grade GeM tenders."""
    if not apply_rows:
        return {"sent": False, "new": 0}
    alerted = _load_alerted()
    fresh = []
    for row in apply_rows:
        key = f"apply:{(row.get('bid_number') or row.get('id') or row.get('title') or '')}"
        rid = hashlib_id(key)
        if rid in alerted:
            continue
        row = dict(row)
        row["_alert_id"] = rid
        fresh.append(row)
    if not fresh:
        return {"sent": False, "new": 0}

    lines = ["Pathankot Pulse — GeM APPLY matches for JR Consulting", ""]
    for r in fresh[:8]:
        lines.append(f"• {r.get('verdict')} · {r.get('title')}")
        lines.append(f"  {r.get('bid_number') or ''} · {r.get('location') or ''}")
        if r.get("url"):
            lines.append(f"  {r['url']}")
        lines.append("")
    text = "\n".join(lines)
    notify(text)
    _send_email(subject=f"Pathankot Pulse: {len(fresh)} APPLY tender(s)", body=text)
    for r in fresh:
        alerted.add(r["_alert_id"])
    _save_alerted(alerted)
    return {"sent": True, "new": len(fresh)}


def hashlib_id(key: str) -> str:
    import hashlib

    return hashlib.sha1(key.encode()).hexdigest()[:16]
