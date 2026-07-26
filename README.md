# Pathankot Pulse

Professional tender intelligence for **JR Consulting Co.** (Pathankot, Punjab 145023).

Scrapes GeM, CPPP, Punjab e-Proc, TendersPlus (eprocure / IREPS / MSTC / GeM), bank & gov auctions, and OLX — then ranks opportunities against your MSME preferences (no/exempt EMD · ≤2y experience · ≤₹40L turnover · CS/AI/digital literacy training).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python -m gem_agent hub-scrape
python -m gem_agent serve --host 0.0.0.0 --port 8787
# open http://127.0.0.1:8787
```

### Deep-scrape TendersPlus keyword (all pages)

```bash
PYTHONPATH=src python -m gem_agent tendersplus --keyword "Steel Bars"
```

## Docker / Cloud Run

```bash
docker build -t pathankot-pulse .
docker run --rm -p 8787:8787 pathankot-pulse
```

Deploy (example):

```bash
gcloud run deploy pathankot-pulse \
  --source . \
  --project=jr-consulting-co \
  --region=asia-south1 \
  --allow-unauthenticated \
  --memory=1Gi \
  --timeout=300 \
  --set-env-vars=PYTHONPATH=/app/src
```

## Config

- `config/hub.yaml` — region, portals, TendersPlus keywords
- `config/profile.yaml` — company + bid policy
- `config/keywords.yaml` — GeM search queries

## Security

Never commit `.env` (GeM / Gmail credentials). `owner.mode: private` by default in `hub.yaml`.
