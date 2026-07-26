from __future__ import annotations

import httpx
from rich.console import Console

from .config import get_settings

console = Console()


def notify(message: str) -> None:
    console.print(message)
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        httpx.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": message[:3500]},
            timeout=20.0,
        )
    except httpx.HTTPError:
        console.print("[yellow]Telegram notify failed[/yellow]")
