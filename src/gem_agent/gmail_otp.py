"""Fetch latest GeM login OTP from Gmail.

Priority:
1) `gog` CLI (OAuth) if authenticated for the account
2) IMAP + Google App Password (GMAIL_ADDRESS / GMAIL_APP_PASSWORD)
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from rich.console import Console

console = Console()

# Ensure .env is loaded when this module is used standalone
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

OTP_RE = re.compile(
    r"(?:OTP|One[- ]Time Password|Your OTP|GeM is)[^\d]{0,80}(\d{4,8})",
    re.I,
)


def _decode(s: str | email.header.Header | None) -> str:
    if s is None:
        return ""
    if isinstance(s, str):
        return s
    parts = decode_header(s)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        texts = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                texts.append(payload.decode(charset, errors="replace"))
        return "\n".join(texts)
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_otp(text: str) -> str | None:
    m = OTP_RE.search(text or "")
    if m:
        return m.group(1)
    m = re.search(r"GeM is\s+(\d{4,8})", text or "", re.I)
    return m.group(1) if m else None


def fetch_via_gog(
    *,
    address: str | None = None,
    newer_than_sec: int = 600,
) -> str | None:
    if not shutil.which("gog"):
        return None
    address = (address or os.getenv("GMAIL_ADDRESS") or "jatinder1901243@gmail.com").strip()
    query = 'from:noreply@gem.gov.in subject:OTP newer_than:1d'
    try:
        proc = subprocess.run(
            [
                "gog",
                "gmail",
                "messages",
                "search",
                query,
                "-a",
                address,
                "--max",
                "5",
                "--include-body",
                "--json",
                "--results-only",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]gog failed:[/yellow] {exc}")
        return None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        if err:
            console.print(f"[yellow]gog:[/yellow] {err}")
        return None
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    # results-only may be list or {messages:[...]}
    if isinstance(data, dict):
        msgs = data.get("messages") or data.get("result") or data.get("items") or []
    else:
        msgs = data
    now = datetime.now(timezone.utc)
    best: tuple[float, str] | None = None
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        subject = str(msg.get("subject") or msg.get("Subject") or "")
        body = ""
        for key in ("body", "text", "snippet", "plain", "html"):
            if msg.get(key):
                body += "\n" + str(msg[key])
        # nested body
        b = msg.get("payload") or {}
        if isinstance(b, dict):
            body += "\n" + str(b.get("body") or b.get("text") or "")
        blob = subject + "\n" + body
        otp = _extract_otp(blob)
        if not otp:
            continue
        # age from internalDate (ms) or date
        age = 0.0
        if msg.get("internalDate"):
            try:
                ms = int(msg["internalDate"])
                age = now.timestamp() - (ms / 1000.0)
            except Exception:
                age = 0.0
        elif msg.get("date") or msg.get("Date"):
            try:
                dt = parsedate_to_datetime(str(msg.get("date") or msg.get("Date")))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (now - dt.astimezone(timezone.utc)).total_seconds()
            except Exception:
                age = 0.0
        if age > newer_than_sec:
            continue
        if best is None or age < best[0]:
            best = (age, otp)
    if best:
        console.print(f"[green]Gmail OTP via gog[/green] {best[1]} (age≈{int(best[0])}s)")
        return best[1]
    return None


def fetch_via_imap(
    *,
    address: str | None = None,
    app_password: str | None = None,
    newer_than_sec: int = 600,
) -> str | None:
    address = (address or os.getenv("GMAIL_ADDRESS") or "").strip()
    app_password = (app_password or os.getenv("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
    if not address or not app_password:
        return None

    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(address, app_password)
    try:
        mail.select("INBOX")
        typ, data = mail.search(None, '(FROM "noreply@gem.gov.in")')
        if typ != "OK" or not data or not data[0]:
            return None
        ids = data[0].split()
        for msg_id in reversed(ids[-15:]):
            typ, msg_data = mail.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subj = _decode(msg.get("Subject"))
            date_hdr = msg.get("Date")
            try:
                dt = parsedate_to_datetime(date_hdr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
                if age > newer_than_sec:
                    continue
            except Exception:
                age = -1
            body = _body(msg)
            otp = _extract_otp(subj + "\n" + body)
            if not otp:
                continue
            console.print(
                f"[green]Gmail OTP via IMAP[/green] {otp} (age≈{int(age)}s, subject={subj[:60]!r})"
            )
            return otp
        return None
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def fetch_latest_gem_otp(*, newer_than_sec: int = 600) -> str | None:
    # Prefer IMAP when app password is configured (avoids noisy gog OAuth errors)
    app_pw = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
    if app_pw:
        otp = fetch_via_imap(newer_than_sec=newer_than_sec)
        if otp:
            return otp
        return fetch_via_gog(newer_than_sec=newer_than_sec)
    otp = fetch_via_gog(newer_than_sec=newer_than_sec)
    if otp:
        return otp
    return fetch_via_imap(newer_than_sec=newer_than_sec)


def wait_for_gem_otp_email(
    *,
    timeout_sec: int = 180,
    poll_sec: float = 4.0,
    newer_than_sec: int = 300,
    after_epoch: float | None = None,
) -> str:
    """Poll Gmail until a fresh GeM OTP appears (preferably after after_epoch)."""
    deadline = time.time() + timeout_sec
    after_epoch = after_epoch or (time.time() - 30)
    console.print(
        f"[yellow]Polling Gmail[/yellow] for GeM OTP "
        f"(timeout {timeout_sec}s, every {poll_sec}s)…"
    )
    while time.time() < deadline:
        otp = fetch_latest_gem_otp(newer_than_sec=newer_than_sec)
        if otp:
            # Prefer OTPs from emails newer than login attempt; still accept if age small
            return otp
        time.sleep(poll_sec)
    raise TimeoutError("No fresh GeM OTP email within timeout")


def gog_auth_ready(address: str | None = None) -> bool:
    if not shutil.which("gog"):
        return False
    address = (address or os.getenv("GMAIL_ADDRESS") or "jatinder1901243@gmail.com").strip()
    proc = subprocess.run(
        ["gog", "auth", "list", "-p"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return address.lower() in out.lower() and "No tokens" not in out


if __name__ == "__main__":
    print(fetch_latest_gem_otp(newer_than_sec=3600) or "none")
