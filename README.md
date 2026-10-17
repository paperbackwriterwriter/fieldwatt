# FieldWatt — renewable trades job feed

Static site generated nightly from the Adzuna API (same pattern as Firmwarely).

- `scripts/fetch_jobs.py` — pulls jobs from Adzuna → `data/jobs.json` (needs ADZUNA_APP_ID / ADZUNA_APP_KEY)
- `scripts/build.py` — generates `site/`: home, /jobs, state + role-family pages, /jobs/midwest, every job page, employer directory + pages, /pay, sitemap
- `scripts/tuesday_email.py` — sends the Tuesday email through Resend (broadcast to an Audience)
- `content/` — the static pages (about, faq, hire, training, alerts, from/*, privacy, terms)
- `static/` — style.css, fonts, logos, site.js (menu, filters, search, forms, Stripe links)
- `api/lead.js` — Vercel function: lead forms (hire, training) → email to LEAD_TO; signup forms → a confirmation email with a signed link
- `api/confirm.js` — the confirmation link: shows a Confirm button, and only pressing it adds the address to the Resend segment (double opt-in; email scanners open links but don't press buttons)
- `.github/workflows/nightly.yml` — 08:15 UTC daily (3:15 AM CDT / 2:15 AM CST): fetch → build → commit → Google Indexing API → check the form handlers load. A fetch that gets nothing usable from Adzuna fails the run instead of republishing the old feed.
- `.github/workflows/tuesday-email.yml` — Tuesdays 12:00 UTC (7 AM CDT / 6 AM CST): the scheduled run broadcasts to the segment; a manual run defaults to a test send to LEAD_TO

`data/jobs.json` is rewritten by the nightly run; `data/retired.json` lists jobs that left the feed in the last three weeks, so their pages can say "closed" instead of vanishing.

## Setup
GitHub secrets: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RESEND_API_KEY`, `RESEND_SEGMENT_ID`, `LEAD_TO`, `LEAD_FROM`.
Vercel env vars: `RESEND_API_KEY`, `LEAD_TO`, `RESEND_SEGMENT_ID`, `LEAD_FROM`, `TURNSTILE_SECRET_KEY` (required in production: without it every form is refused). Optional: `SIGNUP_SECRET` (signs confirmation links; falls back to the Resend key), `SITE_URL` (defaults to https://fieldwatt.com).
`RESEND_AUDIENCE_ID` is still read as a fallback wherever `RESEND_SEGMENT_ID` is unset.
`LEAD_FROM` defaults to `onboarding@resend.dev`, which only delivers to the address that owns the Resend account — fine for lead notifications to `LEAD_TO`, but not for mail to anyone else. Set it to an address on a domain verified in Resend before the Tuesday email goes to real subscribers.
Vercel: import repo, Framework "Other"; `vercel.json` sets output dir = `site`.
Stripe: paste Payment Links into `static/site.js` (`window.FIELDWATT_STRIPE`).

## Featured placements
`data/featured.json` is where a sold or pilot placement goes. The build puts featured jobs at the top of the home page, `/jobs`, every state and family page, the employer page and the Tuesday email, each labeled "Featured"; a featured company gets a label on its page and in the directory, and all of its feed listings move to the top. Every entry has an `until` date (inclusive) and drops out of the next nightly build after it, so nothing needs removing by hand.

```json
{
  "jobs": [
    {"id": "5897993711", "until": "2026-11-01", "apply_url": "https://careers.example.com/123"},
    {"until": "2026-11-01", "title": "Wind Technician II", "company": "Example Energy",
     "location": "Big Spring, Texas", "state": "TX", "families": ["Wind"],
     "pay": "$68,000–$82,000", "description": "…", "apply_url": "https://careers.example.com/456"}
  ],
  "companies": [{"slug": "example-energy", "until": "2026-11-01"}],
  "sponsors": [{"from": "2026-10-20", "until": "2026-10-20", "name": "Example Training",
                "text": "One line about the sponsor.", "url": "https://example.com"}]
}
```

- An entry with an `id` features that listing from the feed (the number at the end of its `/jobs/...--adzuna-NNN` URL). Any other field on the entry overrides the feed's, usually `apply_url` so the job links to the employer's own careers page.
- An entry without an `id` is a job the employer gave us directly: `title`, `company`, `location`, `state`, `families` and `apply_url` are required. Families are `Wind`, `Solar`, `Storage`, `Grid`. Optional: `pay`, `description`, `from` (start date), `employment` (e.g. `["FULL_TIME"]`).
- A company `slug` is the end of its `/employers/...` URL.
- A `sponsors` entry is the paid Tuesday newsletter slot: it appears, labeled "Sponsor", in every Tuesday email sent between `from` and `until`.

After editing, commit to main and run the **nightly-feed** workflow by hand (Actions → nightly-feed → Run workflow, tick "skip fetch") to publish without waiting for the night. A mistake in the file fails the build with a message naming the entry rather than silently dropping the placement.

## Training program pages
`data/programs.json` holds the Featured Program pages the training page offers. Each entry builds `/training/<slug>` and a card in the "Featured programs" section of `/training` (the section is absent while the file is empty).

```json
[{"slug": "iowa-lakes-wind", "name": "Wind Energy & Turbine Technology",
  "school": "Iowa Lakes Community College", "city": "Estherville", "state": "IA",
  "url": "https://www.iowalakes.edu/...", "focus": ["Wind"], "length": "2-year AAS",
  "description": "What the program covers, in the school's own words.", "type": "partner"}]
```

`type` is `partner` (the free founding-partner page) or `sponsored` (the $199/month placement, which also needs `"until": "YYYY-MM-DD"` and drops out after that date). `focus` uses the feed's families: Wind, Solar, Storage, Grid. The page links to live jobs in the program's state and trades. A bad entry fails the build naming it.

## Google Indexing API
`scripts/index_google.py` runs at the end of the nightly workflow and tells Google which job pages are new or have closed, so they are crawled within hours rather than whenever the sitemap comes round. It needs the GitHub secret `GOOGLE_INDEXING_KEY`: the JSON key of a Google Cloud service account with the Indexing API enabled, added as an **Owner** of the fieldwatt.com property in Search Console. Without the secret the step prints a note and does nothing. Default quota is 200 notifications a day; a quarter goes to pages that just closed, the rest to the newest listings, and anything left waits for the next night. `data/indexing-state.json` records what has been sent. `python scripts/index_google.py --dry-run` shows what a run would send.

## Not carried over (yet)
Candidate profiles / sign-in and the "Not a fit? Flag it" button — these needed the MadeThis backend.
