"""Read latest GeM OTP by opening Gmail in a persistent Playwright browser.

Used when `gog` OAuth / IMAP app-password are not configured yet.
First run: log into jatinder1901243@gmail.com in the opened window (once).
Later runs reuse saved cookies under outputs/browser_profiles/gmail.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from rich.console import Console

from .gmail_otp import OTP_RE, _extract_otp

console = Console()

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "outputs" / "browser_profiles" / "gmail"
ADDRESS = os.getenv("GMAIL_ADDRESS", "jatinder1901243@gmail.com").strip()


def fetch_otp_from_gmail_ui(*, newer_than_sec: int = 600, headed: bool = True) -> str | None:
    """Open Gmail search for GeM OTP and return the newest code, or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    PROFILE.mkdir(parents=True, exist_ok=True)
    query = "from:noreply@gem.gov.in subject:OTP"
    url = f"https://mail.google.com/mail/u/0/#search/{query.replace(' ', '+')}"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=not headed,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(2500)

            # If Google sign-in gate
            if "accounts.google.com" in page.url or page.locator("input[type='email']").count():
                console.print(
                    f"[yellow]Gmail login needed[/yellow] — sign in as [bold]{ADDRESS}[/bold] "
                    "in the browser window (one-time). Waiting up to 3 minutes…"
                )
                deadline = time.time() + 180
                while time.time() < deadline:
                    if "mail.google.com" in page.url and "accounts.google.com" not in page.url:
                        break
                    time.sleep(2)
                else:
                    console.print("[red]Gmail UI login timed out[/red]")
                    return None
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(2000)

            # Click top result row if present
            row = page.locator("tr.zA").first
            if row.count():
                try:
                    row.click(timeout=5000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

            # Prefer open message body, else page text
            body = ""
            for sel in [".a3s.aiL", ".ii.gt", "[data-message-id]", "div[role='main']"]:
                loc = page.locator(sel)
                if loc.count():
                    try:
                        body = loc.first.inner_text(timeout=3000)
                        if body and ("OTP" in body.upper() or re.search(r"\d{6}", body)):
                            break
                    except Exception:
                        continue
            if not body:
                body = page.inner_text("body")

            otp = _extract_otp(body) or (OTP_RE.search(body).group(1) if OTP_RE.search(body) else None)
            if otp:
                console.print(f"[green]Gmail OTP via browser UI[/green] {otp}")
            return otp
        finally:
            context.close()


def wait_ui_otp(*, timeout_sec: int = 180, poll_sec: float = 8.0, headed: bool = True) -> str | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            otp = fetch_otp_from_gmail_ui(newer_than_sec=600, headed=headed)
            if otp:
                return otp
        except Exception as exc:  # noqa: BLE001
            console.print(f"[dim]gmail ui:[/dim] {exc}")
        time.sleep(poll_sec)
    return None
