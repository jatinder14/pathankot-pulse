#!/usr/bin/env bash
# Daily Pathankot Pulse scrape — add to crontab:
#   0 7 * * * /path/to/gem-tender-agent/scripts/daily_hub_scrape.sh >> /tmp/pulse_scrape.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY=python3
fi
"$PY" -m gem_agent hub-scrape
echo "OK $(date -u +%Y-%m-%dT%H:%M:%SZ)"
