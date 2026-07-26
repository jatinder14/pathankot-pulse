# Pathankot Pulse — publish guide

Private by default (`config/hub.yaml` → `owner.mode: private`, region fixed to Pathankot **145023**).

## Local (you only)

```bash
cd gem-tender-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m gem_agent hub-scrape
PYTHONPATH=src python -m gem_agent serve --host 127.0.0.1 --port 8787
# open http://127.0.0.1:8787
```

Daily scrape (three layers — pick any):

1. **In-app** — while `serve` is running, APScheduler fires at **07:00 Asia/Kolkata** automatically.
2. **macOS LaunchAgent** (works even if the UI is off):
   ```bash
   cp scripts/com.pathankot.pulse.scrape.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.pathankot.pulse.scrape.plist
   ```
3. **cron** (optional):
   ```cron
   0 7 * * * /Users/flexiple_jr/Desktop/talent/gem-tender-agent/scripts/daily_hub_scrape.sh
   ```

## Docker

```bash
docker compose up --build -d
# UI: http://localhost:8787
docker compose run --rm pulse-scraper   # one-shot scrape (profile scrape)
```

## Publish for the world

1. Flip `owner.mode` to `public` in `config/hub.yaml` when ready.
2. Optionally set `region.region_mode: user_select` and add a city picker later.
3. Deploy the container to any host that exposes port 8787:

| Platform | Notes |
|----------|--------|
| **Railway** | New project → Deploy from Dockerfile → set port `8787` |
| **Render** | Web Service → Docker → health check `/health` |
| **Fly.io** | `fly launch` + `fly deploy` from this folder |
| **VPS** | `docker compose up -d` behind Caddy/Nginx TLS |

Mount a persistent volume on `/app/outputs` so scraped leads survive restarts.

## Portal sections (never mixed)

| Section | Portal ids |
|---------|------------|
| Government tenders | `gem`, `cppp` |
| State tenders | `punjab` |
| Bank property & vehicles | `bank_auction` (IBAPI, BankeAuctions, SBI) |
| Gov property & vehicles | `gov_auction` (MSTC, eauction.gov.in) |
| Local classifieds | `olx` |

Other portals worth adding later: ForeclosureIndia, AuctionTiger, C1 India, state forest/police vehicle auctions, IREDA/PSU scrap portals.

## API

- `GET /` — Pathankot Pulse UI
- `GET /api/hub` — sectioned JSON
- `POST /api/hub/scrape` — run scrapers
- `GET /gem` — GeM operator tools
- `GET /health` — liveness
