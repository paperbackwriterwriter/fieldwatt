# FieldWatt — renewable trades job feed

Static site generated nightly from the Adzuna API (same pattern as Firmwarely).

- `scripts/fetch_jobs.py` — pulls jobs from Adzuna → `data/jobs.json` (needs ADZUNA_APP_ID / ADZUNA_APP_KEY)
- `scripts/build.py` — generates `site/`: home, /jobs, state + role-family pages, /jobs/midwest, every job page, employer directory + pages, /pay, sitemap
- `scripts/tuesday_email.py` — sends the Tuesday email through Resend (broadcast to an Audience)
- `content/` — the static pages (about, faq, hire, training, alerts, from/*, privacy, terms)
- `static/` — style.css, fonts, logos, site.js (menu, filters, search, forms, Stripe links)
- `api/lead.js` — Vercel function: forms → email via Resend (+ optional Audience add)
- `.github/workflows/nightly.yml` — 3:15 AM Central: fetch → build → commit
- `.github/workflows/tuesday-email.yml` — Tuesdays 7 AM Central (defaults to a test send to LEAD_TO)

`data/jobs.json` currently holds a seed snapshot (125 jobs captured from the old site). The first nightly run replaces it with live Adzuna data.

## Setup
GitHub secrets: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RESEND_API_KEY`, `RESEND_SEGMENT_ID`, `LEAD_TO`, `LEAD_FROM`.
Vercel env vars: `RESEND_API_KEY`, `LEAD_TO`, `RESEND_SEGMENT_ID`, `LEAD_FROM`.
`RESEND_AUDIENCE_ID` is still read as a fallback wherever `RESEND_SEGMENT_ID` is unset.
`LEAD_FROM` defaults to `onboarding@resend.dev`, which only delivers to the address that owns the Resend account — fine for lead notifications to `LEAD_TO`, but not for mail to anyone else. Set it to an address on a domain verified in Resend before the Tuesday email goes to real subscribers.
Vercel: import repo, Framework "Other"; `vercel.json` sets output dir = `site`.
Stripe: paste Payment Links into `static/site.js` (`window.FIELDWATT_STRIPE`).

## Not carried over (yet)
Candidate profiles / sign-in and the "Not a fit? Flag it" button — these needed the MadeThis backend.
