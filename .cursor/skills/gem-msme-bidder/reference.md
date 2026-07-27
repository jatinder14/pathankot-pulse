# JR Consulting Co. — GeM reference

## Identity

| Field | Value |
|-------|-------|
| Trade name | JR Consulting Co. |
| Legal | Jatinder Mahajan (Proprietorship) |
| GSTIN | `03FOKPM0985K1ZI` |
| PAN | `FOKPM0985K` |
| Udyam | `UDYAM-PB-16-0016845` (Micro · Services · NIC 62/6209/62099) |
| Address | 221, Arya samaj gali, Sujanpur, Pathankot, Punjab 145023 |
| Phone | 9781948706 |
| Email | jatinder1901243@gmail.com |
| Profile YAML | `gem-tender-agent/config/profile.yaml` |
| Secrets | `gem-tender-agent/.env` (gitignored) |

## Tooling

| Task | Command / path |
|------|----------------|
| Dashboard | `python -m gem_agent serve` → `http://127.0.0.1:8787` |
| Contractor fit | `contractor-fit` / UI |
| Upcoming closing | `python -m gem_agent` upcoming via API / UI |
| Started from today | `PYTHONPATH=src python -m gem_agent started-from --pages 4` |
| Started since date | `… started-from --since 2026-07-25` (no end-date cutoff) |
| Login + ATC attempt | `PYTHONPATH=src python -m gem_agent.gem_login_atc --headed` |
| Reuse session download | `… gem_login_atc --download-only` |
| Gmail OTP module | `src/gem_agent/gmail_otp.py` (IMAP app password) |
| Auth state | `outputs/apply_kit/06_gem_downloaded_atc/gem_auth.json` |

## Location ranking (always apply)

1. Pathankot / nearby Punjab  
2. Kathua / Jammu belt (esp. private jobs)  
3. Rest of Punjab  
4. Online (no out-of-state office proof required)  
5. Other states **if eligible** (no office-in-state clause, or office proof exists)

## Pathankot Pulse — private jobs

| Item | Detail |
|------|--------|
| UI tab | Private jobs (`#private-jobs`) |
| Config | `config/hub.yaml` → `private_jobs` |
| Scraper | `src/gem_agent/hub/jobs.py` (Indeed RSS / Jooble / TimesJobs) |
| Alerts | `src/gem_agent/hub/alerts.py` → Telegram + Gmail |
| Schedule | 07:00 full · 14:00 jobs-only (Asia/Kolkata) |
| API | `GET /api/hub/jobs` · `POST /api/hub/jobs/scrape` · `POST /api/hub/alerts/test` |
| Live | https://pathankot-pulse-696545445518.asia-south1.run.app |

Usable = role keywords (AI training / IT / contractor…) **and** near-belt location.

## Shortlist snapshot (Jul 2026 — re-verify live)

| Bid | Doc PDF | Ends (PDF) | Rule of thumb |
|-----|---------|------------|---------------|
| GEM/2026/B/7830951 | https://bidplus.gem.gov.in/showbidDocument/9656920 | 31 Jul 09:00 | **SKIP** — ATC scope = measurement uncertainty (not CS/AI) |
| GEM/2026/B/7644856 | https://bidplus.gem.gov.in/showbidDocument/9446506 | 30 Jul 14:00 | Tech-prep fit; **MH office clause** 🔴 unless office proof |
| GEM/2026/B/7827832 | https://bidplus.gem.gov.in/showbidDocument/9653320 | 27 Jul 19:00 | **SKIP** — PD/GeM trg aids · East Siang · MSE Exp+TO No |
| GEM/2026/B/7731421 | https://bidplus.gem.gov.in/showbidDocument/9543803 | 24 Jul (likely closed) | Skip unless still open — QCBS, no MSE relaxation |

### ATC download lesson
Extract PDF **annotation** URIs: `resources/upload_nas/.../bid-{id}/{file}.pdf` (often public).
Do not stop at `showbidDocument/{file_id}` (empty) or text-only `178….pdf` names.
Last full scout digests before this rescout: **2026-07-25** (`outputs/digests/*_20260725_*`).

## Agent should auto-build per bid

Download → `atc_from_gem/` · Draft → covering letter, tech proposal, compliance, MSE undertaking · Update → `FINAL_VERIFIED_CHECKLIST.md` · Stop before portal Participate.

## Apply-kit folders

```
gem-tender-agent/outputs/apply_kit/
  00_company_docs/
  01_GEM_2026_B_7644856_vocational_techprep/
  02_GEM_2026_B_7830951_vocational_online/
  03_GEM_2026_B_7827832_vocational_offline/
  04_GEM_2026_B_7731421_SDI_empanelment/
  05_ready_to_upload_pdfs/
  06_gem_downloaded_atc/
  FINAL_VERIFIED_CHECKLIST.md
  ATC_DOWNLOAD_NEEDED.md
```

Save ATC PDFs into each bid’s `atc_from_gem/` subfolder.
