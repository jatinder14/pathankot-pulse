"""GeM seller login (Playwright) + ATC attachment download.

OTP cannot be bypassed. Flow:
1. Script opens SSO, fills userid/password, attempts captcha OCR
2. Waits for OTP in GEM_OTP_FILE (default outputs/gem_otp.txt) — one line, digits only
3. After login, opens each target bid and downloads buyer ATC / scope PDFs

Usage:
  PYTHONPATH=src python -m gem_agent.gem_login_atc --headed
  # In another terminal / chat: echo 123456 > outputs/gem_otp.txt
"""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

console = Console()

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

TARGET_BIDS = [
    {
        "bid": "GEM/2026/B/7644856",
        "doc_id": "9446506",
        "folder": "01_GEM_2026_B_7644856_vocational_techprep",
        "file_ids": ["1781069052"],
    },
    {
        "bid": "GEM/2026/B/7830951",
        "doc_id": "9656920",
        "folder": "02_GEM_2026_B_7830951_vocational_online",
        "file_ids": ["1784882994"],
    },
    {
        "bid": "GEM/2026/B/7827832",
        "doc_id": "9653320",
        "folder": "03_GEM_2026_B_7827832_vocational_offline",
        "file_ids": ["1784810551", "1784810566", "1784810578", "1784810587"],
    },
    {
        "bid": "GEM/2026/B/7731421",
        "doc_id": "9543803",
        "folder": "04_GEM_2026_B_7731421_SDI_empanelment",
        "file_ids": ["1782898094", "1783015046", "1783015054", "1783015059", "1782898001"],
    },
]


def _otp_path() -> Path:
    rel = os.getenv("GEM_OTP_FILE", "outputs/gem_otp.txt")
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def wait_for_otp(timeout_sec: int = 300, *, headed: bool = True) -> str:
    """Auto-read GeM OTP from Gmail (jatinder1901243@gmail.com); fall back to file."""
    path = _otp_path()
    # clear stale file so we don't reuse an old code
    path.write_text("", encoding="utf-8")

    from .gmail_otp import fetch_latest_gem_otp, gog_auth_ready

    address = os.getenv("GMAIL_ADDRESS", "jatinder1901243@gmail.com")
    ready = gog_auth_ready(address)
    console.print(
        f"[yellow]Waiting for OTP email[/yellow] → [bold]{address}[/bold] "
        f"(gog={'ready' if ready else 'browser Gmail fallback'}) "
        f"or paste into [bold]{path}[/bold]. Timeout {timeout_sec}s."
    )
    deadline = time.time() + timeout_sec
    after = time.time() - 20
    last = ""
    last_ui = 0.0
    while time.time() < deadline:
        # 1) file paste (manual override)
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 4 and digits != last:
                console.print(f"[green]OTP from file[/green] ({len(digits)} digits)")
                return digits
            last = digits
        # 2) Gmail API / IMAP (gog)
        try:
            window = max(90, int(time.time() - after) + 60)
            otp = fetch_latest_gem_otp(newer_than_sec=min(600, window))
            if otp and otp != last:
                path.write_text(otp + "\n", encoding="utf-8")
                console.print(f"[green]OTP auto-read from Gmail[/green]: {otp}")
                return otp
        except Exception as exc:  # noqa: BLE001
            console.print(f"[dim]gmail poll:[/dim] {exc}")
        # 3) Open Gmail in Chrome profile only if IMAP/app-password unavailable
        app_pw = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
        if (not ready) and (not app_pw) and (time.time() - last_ui >= 12):
            last_ui = time.time()
            try:
                from .gmail_ui_otp import fetch_otp_from_gmail_ui

                otp = fetch_otp_from_gmail_ui(newer_than_sec=600, headed=headed)
                if otp and otp != last:
                    path.write_text(otp + "\n", encoding="utf-8")
                    return otp
            except Exception as exc:  # noqa: BLE001
                console.print(f"[dim]gmail ui:[/dim] {exc}")
        time.sleep(3)
    raise TimeoutError(f"No OTP from Gmail ({address}) or {path} within {timeout_sec}s")


def ocr_captcha(png_bytes: bytes) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image, ImageOps, ImageFilter

        img = Image.open(io.BytesIO(png_bytes)).convert("L")
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )
        return re.sub(r"[^A-Za-z0-9]", "", text)[:8]
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Captcha OCR unavailable:[/yellow] {exc}")
        return ""


def _click_first(page, selectors: list[str], *, force: bool = True) -> bool:
    for sel in selectors:
        loc = page.locator(sel)
        if not loc.count():
            continue
        try:
            loc.first.click(force=force, timeout=10_000)
            return True
        except Exception:
            try:
                page.evaluate(
                    """(sel) => {
                      const el = document.querySelector(sel);
                      if (el) { el.click(); return true; }
                      return false;
                    }""",
                    sel,
                )
                return True
            except Exception:
                continue
    # last resort: submit first form
    try:
        page.evaluate("() => { const f = document.querySelector('form'); if (f) f.requestSubmit(); }")
        return True
    except Exception:
        return False


def run(headed: bool = True, otp_timeout: int = 300) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Install playwright: pip install playwright && playwright install chromium"
        ) from exc

    user = os.getenv("GEM_USERNAME", "").strip()
    password = os.getenv("GEM_PASSWORD", "").strip()
    if not user or not password:
        raise SystemExit("Set GEM_USERNAME and GEM_PASSWORD in .env")

    out_root = ROOT / "outputs" / "apply_kit" / "06_gem_downloaded_atc"
    out_root.mkdir(parents=True, exist_ok=True)
    auth_state = out_root / "gem_auth.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=200 if headed else 0)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(45_000)

        console.print("Opening GeM SSO…")
        page.goto(
            "https://sso.gem.gov.in/ARXSSO/oauth/doLogin",
            wait_until="commit",
            timeout=90_000,
        )
        page.wait_for_selector("#loginid", timeout=30_000)
        page.screenshot(path=str(out_root / "01_sso.png"))

        # Userid step
        page.fill("#loginid", user)

        # Captcha: #captcha1 from CaptchaServlet
        captcha_img = page.locator("#captcha1, img[src*='CaptchaServlet']")
        code = ""
        if captcha_img.count():
            png = captcha_img.first.screenshot()
            (out_root / "captcha.png").write_bytes(png)
            code = ocr_captcha(png)
            cap_file = ROOT / "outputs" / "gem_captcha.txt"
            if not code:
                console.print(
                    f"[yellow]Captcha image →[/yellow] {out_root / 'captcha.png'}\n"
                    f"Paste captcha text in chat OR write to [bold]{cap_file}[/bold]"
                )
                cap_file.write_text("", encoding="utf-8")
                deadline = time.time() + 300
                while time.time() < deadline:
                    if page.locator("input[type='password']").count():
                        code = "__manual__"
                        break
                    if cap_file.exists():
                        got = re.sub(r"\s+", "", cap_file.read_text(encoding="utf-8").strip())
                        if len(got) >= 3:
                            code = got
                            break
                    time.sleep(1)
            if code and code != "__manual__":
                console.print(f"Captcha: [cyan]{code}[/cyan]")
                page.fill("#captcha_math", code)
                _click_first(
                    page,
                    [
                        "button[type='submit']",
                        "input[type='submit']",
                        "button:has-text('Submit')",
                        "button:has-text('Login')",
                    ],
                )
        else:
            _click_first(page, ["button[type='submit']", "input[type='submit']"])

        page.wait_for_timeout(2000)
        page.screenshot(path=str(out_root / "02_after_userid.png"))

        # Password (wait up to 90s — includes manual captcha path)
        pwd_ok = False
        for _ in range(45):
            for sel in ["#password", "input[name='password']", "input[type='password']"]:
                if page.locator(sel).count():
                    page.fill(sel, password)
                    pwd_ok = True
                    break
            if pwd_ok:
                break
            time.sleep(2)
        if not pwd_ok:
            page.screenshot(path=str(out_root / "login_stuck.png"))
            (out_root / "login_stuck.html").write_text(page.content(), encoding="utf-8")
            raise SystemExit("Password field not found — see login_stuck.png")

        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_root / "03_after_password.png"))

        # GeM requires clicking "Generate OTP" before email/SMS is sent
        generated = _click_first(
            page,
            [
                "button:has-text('Generate OTP')",
                "input[value*='Generate OTP' i]",
                "#generateOtp",
                "button:has-text('Generate')",
                "a:has-text('Generate OTP')",
            ],
        )
        if generated:
            console.print("[cyan]Clicked Generate OTP[/cyan] — watching Gmail…")
        else:
            console.print("[yellow]Generate OTP button not found — trying Submit[/yellow]")
            _click_first(
                page,
                [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Login')",
                    "button:has-text('Submit')",
                ],
            )
        page.wait_for_timeout(2000)
        page.screenshot(path=str(out_root / "03b_after_generate_otp.png"))

        # OTP field
        otp_sel = None
        for _ in range(30):
            for sel in [
                "#otp",
                "input[name='otp']",
                "input[id*='otp' i]",
                "input[placeholder*='OTP' i]",
                "input[aria-label*='OTP' i]",
            ]:
                try:
                    if page.locator(sel).count():
                        otp_sel = sel
                        break
                except Exception:
                    continue
            if otp_sel:
                break
            # maybe landed on dashboard already
            if "gem.gov.in" in page.url and "sso" not in page.url.lower():
                break
            time.sleep(1.5)
        if otp_sel:
            console.print(
                "[bold green]OTP screen ready[/bold green] — auto-reading "
                "from Gmail (or paste into outputs/gem_otp.txt)"
            )
            # Mark time so we only accept OTPs after Generate click
            otp = wait_for_otp(otp_timeout, headed=headed)
            page.fill(otp_sel, otp)
            _click_first(
                page,
                [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Verify')",
                    "button:has-text('Submit')",
                    "button:has-text('Validate')",
                    "button:has-text('Login')",
                ],
            )
        else:
            console.print("[yellow]No OTP field detected — continuing if session is already open.[/yellow]")

        page.wait_for_timeout(5000)
        page.screenshot(path=str(out_root / "04_logged_in.png"))
        context.storage_state(path=str(auth_state))
        console.print(f"Auth state saved: {auth_state}")

        downloaded = download_atc_files(page, out_root)
        browser.close()

    summary = out_root / "DOWNLOAD_SUMMARY.md"
    lines = ["# ATC download summary", f"Files: {len(downloaded)}", ""] + [f"- {x}" for x in downloaded]
    summary.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]Done.[/green] {len(downloaded)} files. See {summary}")
    return summary


def download_atc_files(page, out_root: Path) -> list[str]:
    """Download main bid PDFs + buyer ATC attachments using authenticated session."""
    downloaded: list[str] = []
    for item in TARGET_BIDS:
        bid_url = f"https://bidplus.gem.gov.in/showbidDocument/{item['doc_id']}"
        folder = ROOT / "outputs" / "apply_kit" / item["folder"] / "atc_from_gem"
        folder.mkdir(parents=True, exist_ok=True)
        console.print(f"\n[bold]{item['bid']}[/bold] → {bid_url}")

        # Main bid PDF often triggers download on navigation
        try:
            with page.expect_download(timeout=45_000) as dl_info:
                try:
                    page.goto(bid_url, wait_until="commit", timeout=45_000)
                except Exception as exc:
                    if "Download is starting" not in str(exc):
                        raise
            download = dl_info.value
            dest = folder / f"main_bid_{item['doc_id']}.pdf"
            download.save_as(str(dest))
            downloaded.append(str(dest))
            console.print(f"  main PDF → {dest.name}")
        except Exception as exc:
            console.print(f"  [yellow]main PDF nav:[/yellow] {exc}")
            # Fallback: authenticated GET
            try:
                resp = page.request.get(bid_url)
                body = resp.body()
                if body[:4] == b"%PDF":
                    dest = folder / f"main_bid_{item['doc_id']}.pdf"
                    dest.write_bytes(body)
                    downloaded.append(str(dest))
                    console.print(f"  main PDF GET → {dest.name} ({len(body)} bytes)")
            except Exception as exc2:
                console.print(f"  [red]main PDF failed:[/red] {exc2}")

        # Known ATC / buyer document file ids
        for fid in item["file_ids"]:
            urls = [
                f"https://bidplus.gem.gov.in/resources/buyerDocument/{fid}.pdf",
                f"https://bidplus.gem.gov.in/resources/buyerDocument/{fid}",
                f"https://bidplus.gem.gov.in/viewDocument/{fid}",
                f"https://bidplus.gem.gov.in/showbidDocument/{fid}",
                f"https://mkp.gem.gov.in/resources/buyerDocument/{fid}.pdf",
                f"https://mkp.gem.gov.in/resources/buyerDocument/{fid}",
            ]
            got = False
            for url in urls:
                try:
                    resp = page.request.get(url, timeout=60_000)
                    body = resp.body()
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if resp.status == 200 and (body[:4] == b"%PDF" or "pdf" in ctype):
                        dest = folder / f"atc_{fid}.pdf"
                        dest.write_bytes(body)
                        downloaded.append(str(dest))
                        console.print(f"  ATC {fid} → {dest.name} ({len(body)} bytes)")
                        got = True
                        break
                    # HTML viewer page — look for pdf link
                    if resp.status == 200 and b"<" in body[:200]:
                        text = body.decode("utf-8", errors="replace")
                        for m in re.finditer(r'https?://[^"\']+\.pdf', text, re.I):
                            try:
                                r2 = page.request.get(m.group(0), timeout=60_000)
                                b2 = r2.body()
                                if b2[:4] == b"%PDF":
                                    dest = folder / f"atc_{fid}.pdf"
                                    dest.write_bytes(b2)
                                    downloaded.append(str(dest))
                                    console.print(f"  ATC {fid} linked → {dest.name}")
                                    got = True
                                    break
                            except Exception:
                                continue
                        if got:
                            break
                except Exception:
                    continue
            if not got:
                console.print(f"  [yellow]ATC {fid} not downloaded[/yellow]")

        # Seller bid listing / detail pages sometimes expose ATC links
        for list_url in [
            f"https://bidplus.gem.gov.in/bidding/{item['doc_id']}",
            f"https://bidplus.gem.gov.in/showbid/{item['doc_id']}",
            f"https://bidplus.gem.gov.in/bidlists?search_key={item['bid']}",
        ]:
            try:
                page.goto(list_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)
                shot = folder / "bid_page.png"
                page.screenshot(path=str(shot), full_page=True)
                for name in [
                    "a[href*='buyerDocument']",
                    "a[href*='.pdf']",
                    "text=/view the file/i",
                    "text=/ATC/i",
                ]:
                    locs = page.locator(name)
                    n = min(locs.count(), 8)
                    for i in range(n):
                        try:
                            with page.expect_download(timeout=8000) as dl:
                                locs.nth(i).click(timeout=3000)
                            download = dl.value
                            dest = folder / download.suggested_filename
                            download.save_as(str(dest))
                            downloaded.append(str(dest))
                            console.print(f"  link → {dest.name}")
                        except Exception:
                            continue
                break
            except Exception:
                continue

    return downloaded


def run_download_only(*, headed: bool = True) -> Path:
    """Reuse saved gem_auth.json session to download ATC files."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Install playwright") from exc

    out_root = ROOT / "outputs" / "apply_kit" / "06_gem_downloaded_atc"
    auth_state = out_root / "gem_auth.json"
    if not auth_state.exists():
        raise SystemExit(f"Missing {auth_state} — run full login first")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=100 if headed else 0)
        context = browser.new_context(storage_state=str(auth_state), accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(45_000)
        # warm session on gem
        page.goto("https://bidplus.gem.gov.in/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(out_root / "05_session_reuse.png"))
        downloaded = download_atc_files(page, out_root)
        context.storage_state(path=str(auth_state))
        browser.close()

    summary = out_root / "DOWNLOAD_SUMMARY.md"
    lines = ["# ATC download summary", f"Files: {len(downloaded)}", ""] + [f"- {x}" for x in downloaded]
    summary.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]Done.[/green] {len(downloaded)} files. See {summary}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--otp-timeout", type=int, default=300)
    ap.add_argument(
        "--download-only",
        action="store_true",
        help="Skip login; reuse outputs/.../gem_auth.json",
    )
    args = ap.parse_args()
    if args.download_only:
        run_download_only(headed=not args.headless)
    else:
        run(headed=not args.headless, otp_timeout=args.otp_timeout)


if __name__ == "__main__":
    main()
