---
name: gem-msme-bidder
description: >-
  JR Consulting Co. GeM MSME bidding rules: Pathankot/Punjab-first location
  preference, eligibility filters, full agent autonomy to download all bid/ATC
  docs and prepare apply packets, OTP automation, and apply-kit conventions.
  Use when the user asks about GeM bids, tenders, ATC download, prepare bid
  docs, contractor fit, MSME/EMD exemption, Pathankot training contracts,
  gem-tender-agent, or JR Consulting Co. bidding.
---

# GeM MSME Bidder — JR Consulting Co.

Authoritative operating rules for GeM seller work for this company. Prefer these
over ad-hoc guesses. Project root:

`gem-tender-agent/` (apply kit under `outputs/apply_kit/`).

For company identity and paths, see [reference.md](reference.md).

---

## 0. Agent autonomy (default = act)

The agent is **fully free** to do end-to-end bid prep without waiting for
step-by-step permission, including:

- Scout, rank, and open bids that match filters
- Log into GeM (creds in `.env`), solve captcha/OTP flows (Gmail auto-read)
- **Download all available documents** for a chosen bid (main PDF, ATC, scope,
  certificates, corrigenda, annexures) into that bid’s folder
- Read every downloaded PDF and update checklists
- **Prepare bid docs**: covering letter, technical proposal, compliance matrix,
  MSE/EMD undertaking, escalation matrix, company profile PDF drafts, upload
  pack under `outputs/apply_kit/`
- Fix scripts, retry downloads, refresh digests

**Only hard stops (need human):**

1. Final GeM **Participate / submit** (user confirms OTP/DSC on portal)
2. Inventing fake experience, CA certs, or office proofs that do not exist
3. Paying EMD / creating bank guarantees without explicit user OK
4. Committing secrets or pushing credentials to git

If blocked on ATC UI-only links, keep trying automation; if still impossible,
tell the user exactly which clicks remain — then continue preparing everything
else for that bid.

---

## 1. Company posture (who we are)

- **Trade:** JR Consulting Co. · **Legal:** Jatinder Mahajan (Proprietorship)
- **Micro MSME (Services)** · Udyam `UDYAM-PB-16-0016845` · GSTIN `03FOKPM0985K1ZI`
- **Base:** Sujanpur / **Pathankot, Punjab** (primary operating location)
- **Target work:** AI / CS / digital literacy / vocational-tech training for
  **non-tech government buyers**
- **Email for OTP:** `jatinder1901243@gmail.com` · Mobile `9781948706`

---

## 2. Location preference (rank order)

When scouting or ranking, **location is a first-class sort key**:

1. **Pathankot / nearby Punjab** (Sujanpur, Gurdaspur belt, local consignees) — **highest priority**
2. **Rest of Punjab** — still strong
3. **Online / remote delivery** with no foreign-state office clause — strong
4. **Other states** — only if we are **eligible** (see below)
5. Deprioritize or flag 🔴 if office-in-consignee-state cannot be met

**Eligible for other states when any of:**

- No “office must be in state of Consignee” clause, **or**
- Clause exists but we have (or user will provide) documentary office proof in
  that state, **or**
- Delivery is fully online and ATC does not impose an out-of-state office proof

Do **not** skip a good out-of-state bid solely because it is not Pathankot —
rank it below local/Punjab/online, then pursue if EMD/exp/TO filters pass.

---

## 3. Bid filter rules (scout / shortlist)

| Rule | Prefer | Soft/Hard |
|------|--------|-----------|
| Location | Pathankot → Punjab → online → other eligible states | Soft sort |
| EMD | **No** EMD, or MSE can claim exemption | Soft prefer |
| Experience required | **≤ 2 years** (or MSE/Startup relaxation = Yes) | Soft |
| Turnover required | **≤ ₹40 lakh** (or MSE relaxation = Yes) | Soft |
| Category | Training / vocational / CS / digital literacy | Soft |
| Office-in-consignee-state | Consignee state ≠ Punjab and no office proof → **high reject risk** | **Hard flag** |
| MSE Exp/TO relaxation = No | Need real CA + work-order proofs — warn / skip until docs exist | Hard prefer skip |
| Closed / PDF end date past | Verify live; default **skip** | Hard |

Parse GeM EMD carefully: `/EMD Detail … /Required No` means **no EMD**.

---

## 4. Decision tree (apply or prepare)

```
1. Still open on GeM?  No → skip
2. Rank by location (Section 2)
3. Office-in-consignee-state?
   Yes AND consignee state ≠ Punjab AND no office proof →
     🔴 flag; prepare only if user wants to risk / will add office proof
4. DOWNLOAD ALL DOCS (main PDF + PDF annotation links — Section 8)
5. Read ATC / scope SUBJECT — must fit CS / AI / digital literacy /
   vocational-IT training. Metrology, genset repair, Personal Development
   (non-IT), pure hardware, etc. → 🔴 SKIP even if EMD/MSE look good
6. MSE Exp/TO relaxation = No AND missing CA + experience?
   → warn / skip; do not fake proofs
7. Else → PREPARE BID PACKET aligned to actual ATC subject (not generic CS pitch)
```

**Never recommend apply from category title alone.** GeM “Vocational Training”
titles often hide a different course in `upload_nas` scope PDFs
(e.g. “measurement uncertainty”, “Personal Development / GeM training aids”).

---

## 5. Priority order (example shortlist rules)

When comparing open training bids:

1. Local / Punjab / online + No EMD + MSE exp Yes → **do first**
2. Strong category fit + out-of-state office clause → only if eligible (office proof)
3. Urgent but MSE relaxation No + no proofs → skip or prep-only after warn
4. Likely closed / heavy QCBS without docs → skip unless still open

Always re-check live GeM dates.

---

## 6. Location / office clause (critical)

> **AVAILABILITY OF OFFICE OF SERVICE PROVIDER:** An office of the Service
> Provider must be located in the **state of Consignee**.
> **DOCUMENTARY EVIDENCE TO BE SUBMITTED.**

- Consignee address → state (e.g. MILIT Pune → Maharashtra).
- Without that state’s office proof = **🔴 hard blocker** for award/eval risk.
- “Buyers Location” / on-the-job ≠ same as office-in-state clause — read ATC.

---

## 7. MSE / EMD / documents rules

- Claim **MSE purchase preference** / **EMD exemption** where allowed; upload Udyam.
- MSE Exp/TO relaxation = Yes → Udyam as exemption support; keep CA/exp as backup.
- MSE Exp/TO relaxation = **No** → real experience + turnover proofs required.
- Never invent past work orders, CA certificates, or office leases.
- Do **not** auto-click final Participate without human confirmation.

Ready pack: GST, Udyam, PAN, cancelled cheque, trainer CVs.  
Often missing: CA turnover, past work orders — call out clearly in checklist.

---

## 8. Download-all + prepare-bid workflow (agent runs this)

For each chosen bid, create/use:

```
outputs/apply_kit/<NN>_<bid_slug>/
  atc_from_gem/          ← ALL GeM downloads (main + ATC + annexures)
  ELIGIBILITY_RECHECK.md ← after reading ATC subject
  covering_letter.*
  technical_proposal.*
  compliance_matrix.*
  mse_undertaking.*
  APPLY_GUIDE.md
```

**Agent must:**

1. Fetch main bid PDF: `https://bidplus.gem.gov.in/showbidDocument/{doc_id}`
2. **Extract real hyperlinks from PDF annotations** (not text filenames):
   - Prefer `…/resources/upload_nas/…/biddoc/bid-{doc_id}/{file_id}.pdf`
     — often **public**, no login (this is the detailed scope / ATC attachment)
   - Also save `admin.gem.gov.in/apis/v1/gtc/pdfByDate/…` if present
   - Do **not** rely only on `showbidDocument/{file_id}` or
     `resources/buyerDocument/{file_id}` — those often return empty PDF / 404
   - “Click here to view the file” may map to `bidding/downloadOmppdfile/`
     (session/POST; may still fail) — note gap; continue with `upload_nas` files
3. If attachments are image scans → render page (e.g. PyMuPDF) and read visually/OCR
4. Write `ELIGIBILITY_RECHECK.md` with subject fit + MSE/location gates
5. Only if subject fits: draft letter/proposal/compliance/MSE undertaking to **that**
   syllabus — never leave a generic CS/AI draft on a mismatched scope
6. Copy company PDFs / point to `05_ready_to_upload_pdfs/`
7. Apply steps list (MSE ticks, EMD claim, uploads) — stop before Participate

**Known false positives (Jul 2026 lessons):**

| Bid | Looked OK on filters | Actual scope → skip |
|-----|----------------------|---------------------|
| GEM/2026/B/7830951 | Online, no EMD, MSE exp Yes | Measurement uncertainty course |
| GEM/2026/B/7827832 | No EMD | Personal Development / GeM trg aids · East Siang · MSE Exp+TO **No** |
| GEM/2026/B/7644856 | Tech-prep fit | MH office-in-consignee-state 🔴 |

---

## 9. GeM login + OTP automation

Secrets in gitignored `gem-tender-agent/.env`:

- `GEM_USERNAME` / `GEM_PASSWORD`
- `GMAIL_ADDRESS=jatinder1901243@gmail.com`
- `GMAIL_APP_PASSWORD` (prefer over broken `gog` OAuth)

```bash
PYTHONPATH=src python -m gem_agent.gem_login_atc --headed
```

Flow: userid + captcha → password → **Generate OTP** → IMAP read GeM email OTP
→ submit. Fallback: `outputs/gem_otp.txt`. Captcha fallback: `outputs/gem_captcha.txt`.

---

## 10. Agent behaviour checklist

- Prefer **Pathankot/Punjab**, then other **eligible** locations — say the rank.
- When user picks a bid: **download everything via PDF annotation URLs + write
  docs** without asking permission for each file.
- **Subject gate after ATC** — skip mismatched courses; say why in one line.
- Be direct on 🔴 blockers; still download/read so the skip is evidence-based.
- Separate risks: **location** vs **subject** vs **docs/ATC** vs **cash (EMD/ePBG)**.
- Rescout from **last digest date** when user asks for “new tenders”; compare
  bid numbers to prior `outputs/digests/*` and highlight **new since last run**.
- Preferred new-tender search: **`started-from`** — `start_at >= today` (or
  `--since YYYY-MM-DD`), **no end-date cutoff**:
  `PYTHONPATH=src python -m gem_agent started-from --pages 3`
- OTP relay/paste OK for product ideas — **not** phone SMS device takeover.

---

## Quick invoke examples

- “gem-msme-bidder: find Pathankot / Punjab training bids”  
- “Prepare full apply pack for GEM/2026/B/7830951”  
- “Download all docs for this bid and draft the proposal”  
- “Rank these bids by our location + MSE rules”
