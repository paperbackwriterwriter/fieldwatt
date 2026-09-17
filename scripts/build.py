#!/usr/bin/env python3
"""Generate the static FieldWatt site into ./site from data/jobs.json + content/.

Run after fetch_jobs.py. Vercel serves ./site (see vercel.json).
"""
import html, json, os, re, shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = os.path.join(ROOT, "site")
DOMAIN = "https://fieldwatt.com"
CONTACT = "chowell7@gmail.com"

MIDWEST_HUB = ["IA", "IL", "KS", "OK", "MN"]                      # /jobs/midwest
CORRIDOR = ["IA", "NE", "KS", "OK", "SD", "ND", "MN", "IL", "MO", "TX"]  # "Wind-corridor Midwest" filter
FAMILY_ORDER = ["Wind", "Solar", "Storage", "Grid"]

# How long a job page stays valid after the build that produced it. A listing
# still in the feed is rebuilt every night, so its validThrough rides forward
# and it keeps its place in Google Jobs. Once the listing drops out of Adzuna
# the page stops being regenerated and the last expiry published for it runs
# out, which is what retires the posting. This is also the outage tolerance:
# if the nightly build stops running for longer than this, live postings start
# expiring too, so keep it comfortably longer than a failure takes to fix.
FEED_WINDOW_DAYS = 14

# Floor for publishing a figure as an annual baseSalary: federal minimum wage
# ($7.25) over a 2,080-hour year. The feed states pay as a plain number without
# a period, and some listings quote an hourly or weekly rate, or a placeholder
# like "$1". Below this floor the number cannot be a full-time annual salary,
# and nothing in the data says which period it is, so the page still shows what
# the source gave while the markup makes no salary claim at all.
MIN_ANNUAL_SALARY = 7.25 * 2080
FROM_GUIDES = {
    "Wind": [("HVAC &amp; mechanical", "/from/hvac-mechanical"), ("Military transition", "/from/military-transition"), ("Construction &amp; general labor", "/from/construction-general-labor")],
    "Solar": [("Electricians", "/from/electricians"), ("Construction &amp; general labor", "/from/construction-general-labor"), ("Military transition", "/from/military-transition")],
    "Storage": [("Electricians", "/from/electricians"), ("HVAC &amp; mechanical", "/from/hvac-mechanical"), ("Military transition", "/from/military-transition")],
    "Grid": [("Electricians", "/from/electricians"), ("Construction &amp; general labor", "/from/construction-general-labor"), ("Military transition", "/from/military-transition")],
}

from fetch_jobs import STATES, slugify  # noqa: E402

e = lambda s: html.escape(str(s), quote=True)

# --------------------------------------------------------------------------- icons
ICON = {
    "arrow": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4" aria-hidden="true"><path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path></svg>',
    "pin": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline h-4 w-4 text-primary" aria-hidden="true"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path><circle cx="12" cy="10" r="3"></circle></svg>',
    "pin5": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5 text-primary" aria-hidden="true"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path><circle cx="12" cy="10" r="3"></circle></svg>',
    "building": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5 text-primary" aria-hidden="true"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"></path><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"></path><path d="M10 6h4"></path><path d="M10 10h4"></path><path d="M10 14h4"></path><path d="M10 18h4"></path></svg>',
    "building_sm": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5 text-muted-foreground" aria-hidden="true"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"></path><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"></path><path d="M10 6h4"></path><path d="M10 10h4"></path><path d="M10 14h4"></path><path d="M10 18h4"></path></svg>',
    "external": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4" aria-hidden="true"><path d="M15 3h6v6"></path><path d="M10 14 21 3"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path></svg>',
    "chevron": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5 shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg>',
    "menu": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5" aria-hidden="true"><line x1="4" x2="20" y1="12" y2="12"></line><line x1="4" x2="20" y1="6" y2="6"></line><line x1="4" x2="20" y1="18" y2="18"></line></svg>',
    "hardhat": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5 text-primary" aria-hidden="true"><path d="M10 10V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v5"></path><path d="M14 6a6 6 0 0 1 6 6v3"></path><path d="M4 15v-3a6 6 0 0 1 6-6"></path><rect x="2" y="15" width="20" height="4" rx="1"></rect></svg>',
}

NAV = [("Jobs", "/jobs"), ("Companies", "/employers"), ("Alerts", "/alerts"), ("Pay", "/pay"), ("For employers", "/hire"), ("Training", "/training")]

LOGO = ('<picture><source media="(prefers-color-scheme: dark)" srcset="/logo-dark.svg"/>'
        '<img src="/logo-light.png" alt="FieldWatt logo" class="{cls}" decoding="async"/></picture>')


def layout(title, desc, body, path, extra_head=""):
    canonical = DOMAIN + ("" if path == "/" else path)
    nav_links = "".join(f'<a class="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground" href="{h}">{t}</a>' for t, h in NAV)
    mobile_links = "".join(f'<a class="block py-2 text-sm font-medium text-muted-foreground hover:text-foreground" href="{h}">{t}</a>' for t, h in NAV)
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><link rel="stylesheet" href="/style.css"/><title>{e(title)}</title><meta name="description" content="{e(desc)}"/><meta name="application-name" content="FieldWatt"/><link rel="manifest" href="/manifest.webmanifest"/><link rel="canonical" href="{canonical}"/><meta property="og:title" content="{e(title)}"/><meta property="og:description" content="{e(desc)}"/><meta property="og:url" content="{canonical}"/><meta property="og:site_name" content="FieldWatt"/><meta property="og:image" content="{DOMAIN}/logo-light.png"/><meta property="og:type" content="website"/><meta name="twitter:card" content="summary"/><link rel="icon" href="/logo-light.png" type="image/png"/><link rel="apple-touch-icon" href="/logo-light.png"/>{extra_head}</head><body class="__variable_5afde0 font-sans antialiased"><div class="flex min-h-screen flex-col"><header class="sticky top-0 z-40 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"><div class="mx-auto flex h-[4.5rem] max-w-7xl items-center justify-between px-4 sm:px-6 md:h-20 lg:px-8"><a class="flex shrink-0 items-center" aria-label="FieldWatt home" href="/">{LOGO.format(cls="h-12 w-auto max-w-[3.5rem] object-contain sm:h-14 sm:max-w-[4rem]")}</a><nav class="hidden items-center gap-6 lg:flex">{nav_links}<div class="flex items-center gap-2"><a class="inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-medium transition-colors bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-3 rounded-none" href="/alerts">Get free job alerts</a></div></nav><button id="menu-btn" class="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:hidden" aria-label="Toggle menu" aria-expanded="false">{ICON["menu"]}</button></div><nav id="mobile-menu" class="hidden border-t border-border px-4 py-3 lg:hidden" aria-label="Mobile navigation">{mobile_links}<a class="mt-2 inline-flex h-10 items-center bg-primary px-4 text-sm font-medium text-primary-foreground" href="/alerts">Get free job alerts</a></nav></header><main class="flex-1">{body}</main><footer class="border-t border-border bg-background"><div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8"><div class="grid gap-8 md:grid-cols-4"><div class="md:col-span-2"><a class="inline-flex items-center" aria-label="FieldWatt home" href="/">{LOGO.format(cls="h-14 w-auto max-w-[4.5rem] object-contain sm:h-16 sm:max-w-[5rem]")}</a><p class="mt-3 max-w-md text-sm text-muted-foreground">Every wind, solar, and grid job. One feed, every Tuesday.</p></div><div><p class="text-sm font-semibold text-foreground">Explore</p><nav class="mt-3 space-y-2"><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/jobs">Browse jobs</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/alerts">Free alerts</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/employers">Employer directory</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/pay">Pay snapshot</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/about">About</a></nav></div><div><p class="text-sm font-semibold text-foreground">For partners</p><nav class="mt-3 space-y-2"><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/hire">Feature a job</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/training">List a program</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="/faq">FAQ</a><a class="block text-sm text-muted-foreground transition-colors hover:text-foreground" href="mailto:{CONTACT}">Contact</a></nav></div></div><div class="mt-8 border-t border-border pt-8 text-center"><p class="text-xs text-muted-foreground">© {datetime.now().year} FieldWatt. All rights reserved.</p><p class="mt-3 flex justify-center gap-4 text-xs text-muted-foreground"><a class="hover:text-foreground" href="/privacy">Privacy</a><a class="hover:text-foreground" href="/terms">Terms</a></p></div></div></footer></div><script src="/site.js" defer></script><script>window.va=window.va||function(){{(window.vaq=window.vaq||[]).push(arguments);}};</script><script defer src="/_vercel/insights/script.js"></script></body></html>'''


# --------------------------------------------------------------------------- pieces
def tags(job):
    return '<p class="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-primary-foreground">' + "".join(f'<span class="bg-primary px-2 py-1">{f}</span>' for f in job["families"]) + "</p>"


def card(job):
    snippet = job["description"][:260].rstrip() + ("…" if len(job["description"]) > 260 else "")
    pay = f'<p class="font-semibold text-foreground">{e(job["pay"])}</p>' if job.get("pay") else '<p class="text-sm text-muted-foreground">Pay not listed</p>'
    return (f'<article class="grid gap-3 py-5 sm:grid-cols-[1fr_auto] sm:items-center" data-job data-state="{job["state"]}" data-fam="{" ".join(job["families"])}">'
            f'<div>{tags(job)}<h3 class="mt-3 font-[family-name:var(--font-heading)] text-lg font-bold"><a class="hover:text-primary" href="/jobs/{job["slug"]}">{e(job["title"])}</a></h3>'
            f'<p class="mt-1 text-sm text-muted-foreground"><a class="font-medium text-foreground underline decoration-primary/60 underline-offset-4 hover:text-primary" href="/employers/{job["company_slug"]}">{e(job["company"])}</a> · {ICON["pin"]} {e(job["location"])}</p>'
            f'<p class="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{e(snippet)}</p></div>'
            f'<div class="flex items-center gap-4 sm:flex-col sm:items-end">{pay}<a class="inline-flex items-center gap-1 text-sm font-semibold text-foreground underline decoration-primary decoration-2 underline-offset-4" href="/jobs/{job["slug"]}">Job details {ICON["arrow"]}</a></div></article>')


def cards(jobs):
    if not jobs:
        return '<p class="py-10 text-sm text-muted-foreground">No current listings match. Check back after the next nightly update, or <a class="underline decoration-primary underline-offset-4" href="/alerts">turn on free alerts</a>.</p>'
    return '<div class="divide-y divide-border border-y border-border" id="job-list">' + "".join(card(j) for j in jobs) + "</div>"


def filters(jobs, state_counts, fam_counts, current_state="", current_fam=""):
    """Search box + state/family selects. The selects navigate to the static pages; the search filters in-page."""
    corridor_n = sum(state_counts.get(s, 0) for s in CORRIDOR)
    opts = f'<option value="">All states ({len(jobs)})</option><option value="midwest"{" selected" if current_state == "midwest" else ""}>Wind-corridor Midwest ({corridor_n})</option>'
    for code, name in sorted(STATES.items(), key=lambda kv: kv[1]):
        n = state_counts.get(code, 0)
        if n:
            opts += f'<option value="{slugify(name)}"{" selected" if current_state == slugify(name) else ""}>{name} ({n})</option>'
    fopts = f'<option value="">All role families</option>' + "".join(
        f'<option value="{f.lower()}"{" selected" if current_fam == f.lower() else ""}>{f} ({fam_counts.get(f, 0)})</option>' for f in FAMILY_ORDER)
    return (f'<div class="mb-6 grid gap-3 border border-border bg-card p-4 md:grid-cols-[1fr_220px_190px]">'
            f'<input id="job-search" placeholder="Search jobs or companies" class="h-11 border border-input bg-background px-3 text-sm outline-none ring-ring focus:ring-2" value=""/>'
            f'<select id="state-select" class="h-11 border border-input bg-background px-3 text-sm" aria-label="State">{opts}</select>'
            f'<select id="family-select" class="h-11 border border-input bg-background px-3 text-sm" aria-label="Role family">{fopts}</select></div>')


def listing_page(title, h1, intro, jobs, all_jobs, state_counts, fam_counts, path, eyebrow="FieldWatt job feed", current_state="", current_fam="", extra=""):
    updated = UPDATED.strftime("%b %-d")
    body = (f'<div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{eyebrow}</p>'
            f'<h1 class="mt-3 font-[family-name:var(--font-heading)] text-4xl font-bold">{h1}</h1><p class="mt-4 max-w-2xl leading-7 text-muted-foreground">{intro}</p>'
            f'<p class="mt-3 text-sm font-semibold text-muted-foreground">{len(jobs)} field jobs · {len({j["company_slug"] for j in jobs})} companies · updated {updated}</p>'
            f'<p class="mt-4 text-sm text-muted-foreground">Research a company before you apply in the <a class="font-semibold text-foreground underline decoration-primary decoration-2 underline-offset-4 hover:text-primary" href="/employers">company directory</a>.</p>'
            f'{extra}<div class="mt-10">{filters(all_jobs, state_counts, fam_counts, current_state, current_fam)}{cards(jobs)}</div></div>')
    return layout(title, intro, body, path)


# --------------------------------------------------------------------------- structured data
# Pay strings as fetch_jobs.py writes them: "$120,000", "$95,000–$110,000".
# The seed snapshot also carries one legacy "$129,522 · from $62.27/hr".
PAY_RE = re.compile(r"^\$([\d,]+)(?:–\$([\d,]+))?(?: · .*)?$")


def base_salary(job):
    """Annual baseSalary for a JobPosting, or None.

    Only listings where the employer stated pay qualify. Every other figure in
    the feed is the source's own estimate (shown as "est. …"), and publishing
    one as baseSalary would claim the employer offers a number it never named.
    Figures too small to be an annual salary are dropped for the same reason:
    see MIN_ANNUAL_SALARY.
    """
    if not job.get("pay_listed") or not job.get("pay"):
        return None
    m = PAY_RE.match(job["pay"])
    if not m:
        return None
    lo = int(m.group(1).replace(",", ""))
    hi = int((m.group(2) or m.group(1)).replace(",", ""))
    if lo < MIN_ANNUAL_SALARY:
        return None
    amount = {"@type": "QuantitativeValue", "unitText": "YEAR"}
    if lo == hi:
        amount["value"] = lo
    else:
        amount["minValue"], amount["maxValue"] = lo, hi
    return {"@type": "MonetaryAmount", "currency": "USD", "value": amount}


def json_ld(data):
    """Serialize to JSON-LD that cannot break out of its <script> element."""
    out = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                    ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        out = out.replace(ch, esc)
    return f'<script type="application/ld+json">{out}</script>'


def valid_through(job):
    """When this posting expires if the feed stops carrying it.

    Anchored on the feed's own timestamp rather than on the posting date: a
    listing can sit on the source for months, and expiring it on its age would
    retire a role the site still shows. Never lands on or before datePosted,
    which would publish a posting that is already expired.
    """
    window = UPDATED.date() + timedelta(days=FEED_WINDOW_DAYS)
    posted = date.fromisoformat(job["posted"])
    return max(window, posted + timedelta(days=1)).isoformat()


def job_ld(job):
    """Google JobPosting markup for one job page.

    employmentType is left out on purpose: the feed does not carry it, and
    guessing would put a claim in the markup that the page does not make.
    directApply is false because applying goes through the source's listing,
    not the employer's own form.
    """
    address = {"@type": "PostalAddress", "addressRegion": job["state"], "addressCountry": "US"}
    if job.get("city"):
        address["addressLocality"] = job["city"]
    data = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": job["title"],
        "description": description(job),
        "datePosted": job["posted"],
        "validThrough": valid_through(job),
        "hiringOrganization": {"@type": "Organization", "name": job["company"]},
        "jobLocation": {"@type": "Place", "address": address},
        "identifier": {"@type": "PropertyValue", "name": job["company"], "value": job["id"]},
        "url": f"{DOMAIN}/jobs/{job['slug']}",
        "directApply": False,
    }
    salary = base_salary(job)
    if salary:
        data["baseSalary"] = salary
    return json_ld(data)


def description(job):
    """The role text exactly as the job page shows it."""
    return job["description"] + ("…" if len(job["description"]) >= 1200 else "")


def job_page(job):
    fam = job["families"][0]
    guides = "".join(f'<a class="border border-border bg-card px-4 py-3 text-sm font-semibold hover:border-primary hover:text-primary" href="{h}">{t}</a>' for t, h in FROM_GUIDES[fam])
    pay = e(job["pay"]) if job.get("pay") else "Not listed"
    hire_q = "company=" + e(job["company"]).replace(" ", "+") + "&amp;jobTitle=" + e(job["title"]).replace(" ", "+")
    body = f'''<section class="field-grid border-b border-border bg-secondary text-secondary-foreground"><div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8"><a class="text-xs font-semibold uppercase tracking-[0.16em] text-primary hover:text-secondary-foreground" href="/jobs">All jobs</a><div class="mt-6 grid gap-7 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-end"><div><p class="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">{"".join(f"<span>{f}</span>" for f in job["families"])}<span>field role</span></p><h1 class="mt-4 max-w-4xl font-[family-name:var(--font-heading)] text-4xl font-bold leading-tight sm:text-6xl">{e(job["title"])}</h1><p class="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-lg text-secondary-foreground/80">{ICON["building"]} <a class="font-semibold text-secondary-foreground underline decoration-primary underline-offset-4" href="/employers/{job["company_slug"]}">{e(job["company"])}</a><span aria-hidden="true">·</span>{ICON["pin5"]} {e(job["location"])}</p></div><div class="space-y-4"><a href="{e(job["apply_url"])}" target="_blank" rel="noreferrer noopener" class="inline-flex min-h-12 w-full items-center justify-center gap-2 bg-primary px-5 py-3 text-sm font-bold text-primary-foreground hover:bg-primary/90">View application source {ICON["external"]}</a><div class="border-l-4 border-primary bg-background/10 px-4 py-4 text-left"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Hiring for this role?</p><p class="mt-2 text-sm leading-6 text-secondary-foreground/80">Highlight a live field opening to the FieldWatt renewable-trades audience. Paid placements are labeled.</p><a class="mt-3 inline-flex items-center gap-2 text-sm font-bold text-secondary-foreground underline decoration-primary decoration-2 underline-offset-4 hover:text-primary" href="/hire?{hire_q}#featured-job-intake">Feature this job {ICON["arrow"]}</a></div></div></div></div></section><section class="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:px-8 lg:py-16"><article><div class="grid gap-px border border-border bg-border sm:grid-cols-3"><div class="bg-card p-5"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Location</p><p class="mt-2 font-semibold">{e(job["location"])}</p></div><div class="bg-card p-5"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Pay</p><p class="mt-2 font-semibold">{pay}</p></div><div class="bg-card p-5"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Source freshness</p><p class="mt-2 font-semibold">Updated {UPDATED.strftime("%B %-d, %Y")}</p></div></div><div class="mt-10"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Role overview</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-3xl font-bold">What the employer shared</h2><p class="mt-5 max-w-3xl text-lg leading-8 text-muted-foreground">{e(description(job))}</p><p class="mt-4 text-sm text-muted-foreground">Listed {e(job["posted"])}. Full details, requirements, and the application are on the employer&#x27;s listing.</p></div><div class="mt-10 border-t border-border pt-10"><div class="flex items-center gap-2">{ICON["hardhat"]}<p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Background fit</p></div><h2 class="mt-3 font-[family-name:var(--font-heading)] text-3xl font-bold">Your current experience can transfer.</h2><p class="mt-4 max-w-3xl leading-7 text-muted-foreground">This {fam.lower()} role can draw on the experience you already have. These FieldWatt guides can help you compare the role before you apply.</p><div class="mt-6 flex flex-wrap gap-3">{guides}</div></div></article><aside class="space-y-6"><div class="border border-border bg-accent p-6"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">More like this</p><div class="mt-4 space-y-3"><a class="flex items-center justify-between border-b border-border pb-3 text-sm font-bold text-foreground hover:text-primary" href="/jobs/{slugify(job["state_name"])}">{e(job["state_name"])} jobs {ICON["arrow"]}</a><a class="flex items-center justify-between border-b border-border pb-3 text-sm font-bold text-foreground hover:text-primary" href="/jobs/{fam.lower()}">{fam} jobs {ICON["arrow"]}</a><a class="flex items-center justify-between border-b border-border pb-3 text-sm font-bold text-foreground hover:text-primary" href="/jobs/{slugify(job["state_name"])}/{fam.lower()}">{fam} jobs in {e(job["state_name"])} {ICON["arrow"]}</a></div></div><div class="border border-border bg-card p-6"><p class="text-sm font-semibold text-foreground">Want new matches by email?</p><p class="mt-2 text-sm leading-6 text-muted-foreground">The Tuesday email is free and keeps you close to new field roles.</p><a class="mt-4 inline-flex h-10 items-center bg-primary px-4 text-sm font-medium text-primary-foreground" href="/alerts?role={fam}&amp;state={job["state"]}">Get free alerts</a></div></aside></section>'''
    title = f'{job["title"]} at {job["company"]} in {job["location"]} | FieldWatt'
    return layout(title, job["description"][:300], body, f'/jobs/{job["slug"]}', job_ld(job))


def employer_page(name, slug, jobs):
    body = f'''<section class="field-grid border-b border-border bg-secondary text-secondary-foreground"><div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8"><a class="text-xs font-semibold uppercase tracking-[0.16em] text-primary hover:text-secondary-foreground" href="/employers">Employer directory</a><h1 class="mt-4 max-w-4xl font-[family-name:var(--font-heading)] text-4xl font-bold leading-tight sm:text-6xl">{e(name)}</h1><p class="mt-5 max-w-2xl text-lg leading-8 text-secondary-foreground/80">FieldWatt links applicants to the employer&#x27;s own application page. We do not take applications or represent employers in the hiring process.</p><p class="mt-4 text-sm font-semibold text-secondary-foreground/80">{len(jobs)} current relevant listing{"s" if len(jobs) != 1 else ""}</p></div></section><section class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Jobs from this employer</p>{cards(jobs)}<a class="mt-8 inline-flex items-center gap-2 text-sm font-bold underline decoration-primary decoration-2 underline-offset-4" href="/jobs">Browse all jobs {ICON["arrow"]}</a></section><section class="border-t border-border bg-muted/40"><div class="mx-auto grid max-w-7xl gap-8 px-4 py-12 sm:px-6 lg:grid-cols-2 lg:px-8"><div class="border border-border bg-card p-6"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Free page claim</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-2xl font-bold">Is this your page?</h2><p class="mt-3 text-sm leading-6 text-muted-foreground">Verify control of a company work inbox to request this page. Verification does not automatically establish ownership; FieldWatt may review mismatches or abuse.</p><form class="mt-5 grid gap-3" data-form="employer-claim"><input type="hidden" name="company" value="{e(name)}"/><input type="hidden" name="website" value=""/><label class="text-sm font-semibold text-foreground">Work email<input class="mt-2 w-full border border-input bg-background px-3 py-2.5 text-sm text-foreground outline-none ring-ring focus:ring-2" type="email" name="email" required="" placeholder="you@company.com"/></label><button class="inline-flex h-10 items-center justify-center bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90" type="submit">Claim this page free</button><p class="text-xs text-muted-foreground" data-status aria-live="polite"></p></form></div><div class="border border-border bg-card p-6"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Paid placement options</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-2xl font-bold">Feature active field work.</h2><p class="mt-3 text-sm leading-6 text-muted-foreground">Choose a labeled placement through self-serve checkout. These options are separate from claiming this free directory page.</p><div class="mt-5 flex flex-col gap-3 sm:flex-row"><a class="inline-flex h-10 items-center justify-center border border-border px-4 text-sm font-medium hover:border-primary" href="/hire#featured-job">Feature a job — $149</a><a class="inline-flex h-10 items-center justify-center border border-border px-4 text-sm font-medium hover:border-primary" href="/hire#featured-company">Featured Company — $299/month</a></div></div></div></section>'''
    return layout(f"{name} Jobs | FieldWatt", f"Current renewable trades listings from {name}, with links to the employer's own application page.", body, f"/employers/{slug}")


def employers_index(employers):
    rows = "".join(
        f'<a class="group flex items-center justify-between gap-5 py-5" href="/employers/{slug}"><span class="flex min-w-0 items-center gap-3 font-[family-name:var(--font-heading)] text-xl font-bold text-foreground group-hover:text-primary"><span class="flex shrink-0 items-center justify-center border border-border bg-card p-2 h-10 w-10">{ICON["building_sm"]}</span> <span class="truncate">{e(name)}</span></span><span class="flex items-center gap-3 text-sm text-muted-foreground">{n} job{"s" if n != 1 else ""} {ICON["chevron"]}</span></a>'
        for name, slug, n in employers)
    body = f'''<section class="field-grid border-b border-border bg-secondary text-secondary-foreground"><div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Employer directory</p><h1 class="mt-4 max-w-3xl font-[family-name:var(--font-heading)] text-4xl font-bold leading-tight sm:text-6xl">Renewable field employers, in one place.</h1><p class="mt-6 max-w-2xl text-lg leading-8 text-secondary-foreground/80">Review relevant jobs by employer, then apply through the employer&#x27;s own application site.</p></div></section><section class="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8"><p class="max-w-3xl border-l-2 border-primary pl-4 text-sm leading-6 text-muted-foreground">This directory is generated from current active listings. Employer pages link back to the original application source.</p><input id="employer-search" placeholder="Search {len(employers)} companies" class="mt-8 h-11 w-full max-w-md border border-input bg-background px-3 text-sm outline-none ring-ring focus:ring-2"/><div class="mt-6 divide-y divide-border border-y border-border" id="employer-list">{rows}</div></section>'''
    return layout("Employer Directory | FieldWatt", "Renewable field employers with current wind, solar, storage and grid listings.", body, "/employers")


def pay_page(jobs):
    listed = [j for j in jobs if j.get("pay")]
    groups = ""
    for fam in FAMILY_ORDER:
        fj = [j for j in listed if fam in j["families"]]
        fj.sort(key=lambda j: j["pay_listed"], reverse=True)
        items = "".join(f'<li class="py-3 text-sm"><a class="font-semibold text-foreground hover:text-primary" href="/jobs/{j["slug"]}">{e(j["title"])}</a> <span class="text-muted-foreground">· {e(j["state_name"])} · {e(j["pay"])}</span></li>' for j in fj[:8])
        empty = '<li class="py-3 text-sm text-muted-foreground">No listings with pay this week.</li>'
        groups += f'<div class="mt-8"><h2 class="font-[family-name:var(--font-heading)] text-2xl font-bold">{fam}</h2><ul class="mt-3 divide-y divide-border border-y border-border">{items or empty}</ul></div>'
    body = f'''<section class="field-grid border-b border-border bg-secondary text-secondary-foreground"><div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Pay in the feed</p><h1 class="mt-4 max-w-3xl font-[family-name:var(--font-heading)] text-4xl font-bold leading-tight sm:text-6xl">See pay where an employer lists it.</h1><p class="mt-6 max-w-2xl text-lg leading-8 text-secondary-foreground/80">FieldWatt preserves pay information provided with a job listing. Figures marked &quot;est.&quot; are the source&#x27;s estimate, not the employer&#x27;s. FieldWatt does not publish market benchmarks or promise a range for a role.</p></div></section><section class="mx-auto max-w-4xl px-4 py-12 sm:px-6 lg:px-8"><p class="border-l-2 border-primary pl-4 text-sm leading-6 text-muted-foreground">Listed pay only: examples below are drawn from active listings that include compensation. They are not wage claims or market data.</p>{groups}<p class="mt-10 text-sm leading-6 text-muted-foreground">Always confirm compensation, per diem, travel, overtime, benefits, and local requirements with the employer before accepting a role.</p><a class="mt-6 inline-flex items-center gap-2 text-sm font-bold underline decoration-primary decoration-2 underline-offset-4" href="/jobs">Browse the job feed {ICON["arrow"]}</a></section>'''
    return layout("Pay in the FieldWatt Feed | FieldWatt", "Pay from active renewable trades listings that include compensation.", body, "/pay")


def home_page(jobs, employers, state_counts):
    fresh = jobs[:8]
    updated = UPDATED.strftime("%b %-d")
    guides = "".join(f'<a class="group border border-border bg-card p-5 transition-colors hover:border-primary" href="{h}"><p class="font-[family-name:var(--font-heading)] text-lg font-bold text-foreground">{t}</p><span class="mt-4 inline-flex items-center gap-2 text-sm font-bold text-muted-foreground group-hover:text-foreground">See role matches {ICON["arrow"]}</span></a>'
                     for t, h in [("Electricians", "/from/electricians"), ("HVAC &amp; mechanical", "/from/hvac-mechanical"), ("Military transition", "/from/military-transition"), ("Construction &amp; general labor", "/from/construction-general-labor")])
    body = f'''<section class="field-grid bg-secondary text-secondary-foreground"><div class="mx-auto grid max-w-7xl gap-12 px-4 py-18 sm:px-6 sm:py-24 lg:grid-cols-[1.25fr_0.75fr] lg:px-8"><div><p class="inline-flex border border-secondary-foreground/30 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em]">Wind · Solar · Storage · Grid</p><h1 class="mt-7 max-w-4xl font-[family-name:var(--font-heading)] text-5xl font-bold leading-[0.96] tracking-tight sm:text-7xl">Renewable trades jobs. <span class="text-primary">No noise.</span></h1><p class="mt-7 max-w-2xl text-lg leading-8 text-secondary-foreground/80">FieldWatt tracks the field work: turbine techs, solar installers, battery storage, linemen, and substation crews. One clear feed, every Tuesday.</p><p class="mt-4 text-sm font-semibold text-secondary-foreground/80">{len(jobs)} field jobs · {len(employers)} companies · updated {updated}</p><div class="mt-10 flex flex-col gap-3 sm:flex-row sm:items-start"><div class="flex flex-col items-stretch gap-2"><a class="inline-flex h-12 items-center justify-center gap-2 bg-primary px-5 text-sm font-bold text-primary-foreground" href="/jobs">Browse jobs {ICON["arrow"]}</a><a class="inline-flex h-12 items-center justify-center border border-secondary-foreground/40 px-5 text-sm font-bold" href="/hire#featured-job">Post a Job</a></div><a class="inline-flex h-12 items-center justify-center border border-secondary-foreground/40 px-5 text-sm font-bold" href="/alerts">Turn on free alerts</a></div></div><aside class="border border-secondary-foreground/20 bg-background/5 p-6 sm:p-8"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Built for people on the tools</p><dl class="mt-8 space-y-7"><div><dt class="flex items-center gap-3 font-semibold">{ICON["hardhat"]} Role-first filters</dt><dd class="mt-2 text-sm leading-6 text-secondary-foreground/70">Search the jobs that match your electrical, mechanical, construction, or military background.</dd></div><div><dt class="flex items-center gap-3 font-semibold">{ICON["pin5"]} Midwest focus</dt><dd class="mt-2 text-sm leading-6 text-secondary-foreground/70">Start with Iowa, Nebraska, Kansas, Oklahoma, South Dakota, North Dakota, Minnesota, Illinois, Missouri, and Texas — then take the work wherever it goes.</dd></div><div><dt class="flex items-center gap-3 font-semibold">{ICON["building"]} Tuesday dispatch</dt><dd class="mt-2 text-sm leading-6 text-secondary-foreground/70">Get useful new openings without checking every employer career page.</dd></div></dl></aside></div></section><section class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8"><div class="flex flex-col justify-between gap-4 border-b border-border pb-6 sm:flex-row sm:items-end"><div><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Fresh from the feed</p><h2 class="mt-2 font-[family-name:var(--font-heading)] text-3xl font-bold">Jobs that keep the grid moving.</h2></div><a class="text-sm font-bold underline decoration-primary decoration-2 underline-offset-4" href="/jobs">See every job</a></div><div class="mt-2">{cards(fresh)}</div></section><section class="border-y border-border bg-muted/40"><div class="mx-auto grid max-w-7xl gap-8 px-4 py-16 sm:px-6 lg:grid-cols-[0.7fr_1.3fr] lg:px-8"><div><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">For your background</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-3xl font-bold">Bring the skills you already use.</h2><p class="mt-4 max-w-md leading-7 text-muted-foreground">Start with a plain-language guide, then move into the job families that fit your experience.</p></div><div class="grid gap-3 sm:grid-cols-2">{guides}</div></div></section><section class="border-y border-border bg-accent"><div class="mx-auto grid max-w-7xl gap-8 px-4 py-16 sm:px-6 lg:grid-cols-[0.85fr_1.15fr] lg:px-8"><div><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">The Tuesday email</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-3xl font-bold">A short job list. No recruiter spam.</h2><p class="mt-4 max-w-md leading-7 text-muted-foreground">New jobs by role and state, plus pay where it is listed. Free for job seekers.</p></div><div class="self-end"><form class="grid gap-3 sm:grid-cols-2" data-form="tuesday-email"><input type="hidden" name="website" value=""/><div class="sm:col-span-2 sm:grid sm:grid-cols-[1fr_auto] sm:gap-3"><label class="sr-only" for="home-email">Email address</label><input id="home-email" name="email" type="email" autocomplete="email" required="" placeholder="you@example.com" class="h-11 min-w-0 w-full border border-input bg-card px-3 text-sm text-foreground outline-none ring-ring focus:ring-2" value=""/><button class="inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-medium transition-colors bg-primary text-primary-foreground hover:bg-primary/90 py-2 mt-3 h-11 w-full rounded-sm px-5 sm:mt-0 sm:w-auto" type="submit">Get the Tuesday email</button></div><p class="sm:col-span-2 text-xs leading-5 text-muted-foreground">Free to use. FieldWatt sends the Tuesday job email. Unsubscribe in one click at any time.</p><p class="sm:col-span-2 text-sm text-muted-foreground" data-status aria-live="polite"></p></form></div></div></section><section class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8"><div class="grid gap-8 border-y border-border py-10 lg:grid-cols-[1fr_1fr]"><div><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">For employers</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-2xl font-bold">Hiring field crews?</h2><p class="mt-3 max-w-md leading-7 text-muted-foreground">Ask about a featured job, company page, or Tuesday sponsor placement.</p><a class="mt-5 inline-flex border-b-2 border-primary pb-1 text-sm font-bold text-foreground" href="/hire">Feature a job</a></div><div class="border-t border-border pt-8 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0"><p class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">For training programs</p><h2 class="mt-3 font-[family-name:var(--font-heading)] text-2xl font-bold">Connect students to the field.</h2><p class="mt-3 max-w-md leading-7 text-muted-foreground">Explore regional partner placement and clearly labeled sponsored listings.</p><a class="mt-5 inline-flex border-b-2 border-primary pb-1 text-sm font-bold text-foreground" href="/training">List your program</a></div></div></section>'''
    return layout("Renewable-Energy Trades Jobs | FieldWatt", "FieldWatt tracks wind, solar, storage and grid field jobs. One clear feed, every Tuesday.", body, "/")


# --------------------------------------------------------------------------- main
def write(path, content):
    p = os.path.join(SITE, path.lstrip("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    global UPDATED
    data = json.load(open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8"))
    jobs = data["jobs"]
    UPDATED = datetime.fromisoformat(data["updated"].replace("Z", "+00:00")) if data.get("updated") else datetime.now(timezone.utc)

    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)

    state_counts = Counter(j["state"] for j in jobs)
    fam_counts = Counter(f for j in jobs for f in j["families"])
    by_state = defaultdict(list)
    by_fam = defaultdict(list)
    by_emp = defaultdict(list)
    emp_name = {}
    for j in jobs:
        by_state[j["state"]].append(j)
        for f in j["families"]:
            by_fam[f].append(j)
        by_emp[j["company_slug"]].append(j)
        emp_name.setdefault(j["company_slug"], j["company"])
    employers = sorted(((emp_name[s], s, len(v)) for s, v in by_emp.items()), key=lambda t: t[0].lower())

    urls = []

    def add(path, content, sitemap=True):
        write("index.html" if path == "/" else path.strip("/") + "/index.html", content)
        if sitemap:
            urls.append(path)

    add("/", home_page(jobs, employers, state_counts))
    add("/jobs", listing_page("Renewable Trades Jobs | FieldWatt", "Find work that fits your tools.",
                              "Search active wind, solar, storage, and grid roles. Apply directly with the employer.",
                              jobs, jobs, state_counts, fam_counts, "/jobs", eyebrow="Daily job feed"))

    hub = [j for j in jobs if j["state"] in MIDWEST_HUB]
    add("/jobs/midwest", listing_page("Midwest Renewable Trades Jobs | FieldWatt", "Midwest jobs hub",
                                      "Live wind, solar, storage, and grid roles across Iowa, Illinois, Kansas, Oklahoma, and Minnesota.",
                                      hub, jobs, state_counts, fam_counts, "/jobs/midwest", current_state="midwest"))

    for code, name in STATES.items():
        sj = by_state.get(code, [])
        if not sj:
            continue
        s = slugify(name)
        add(f"/jobs/{s}", listing_page(f"Renewable trades jobs in {name} | FieldWatt", f"Renewable trades jobs in {name}",
                                       f"Active field roles in {name}, listed pay where available, and employer application links. New listings are added nightly.",
                                       sj, jobs, state_counts, fam_counts, f"/jobs/{s}", current_state=s))
        for fam in FAMILY_ORDER:
            fj = [j for j in sj if fam in j["families"]]
            if fj:
                add(f"/jobs/{s}/{fam.lower()}", listing_page(f"{fam} jobs in {name} | FieldWatt", f"{fam} jobs in {name}",
                                                             f"Current {fam.lower()} field roles in {name} from the FieldWatt feed.",
                                                             fj, jobs, state_counts, fam_counts, f"/jobs/{s}/{fam.lower()}", current_state=s, current_fam=fam.lower()))
    for fam in FAMILY_ORDER:
        add(f"/jobs/{fam.lower()}", listing_page(f"{fam} jobs | FieldWatt", f"{fam} jobs across the feed",
                                                 f"Every current {fam.lower()} field role in the FieldWatt feed, updated nightly.",
                                                 by_fam.get(fam, []), jobs, state_counts, fam_counts, f"/jobs/{fam.lower()}", current_fam=fam.lower()))
    for j in jobs:
        add(f"/jobs/{j['slug']}", job_page(j))
    add("/employers", employers_index(employers))
    for name, slug, n in employers:
        add(f"/employers/{slug}", employer_page(name, slug, by_emp[slug]))
    add("/pay", pay_page(jobs))

    # static content pages
    pages = json.load(open(os.path.join(ROOT, "content", "pages.json"), encoding="utf-8"))
    corridor = []
    for code in MIDWEST_HUB:
        if state_counts.get(code):
            corridor.append((f"{STATES[code]} jobs", f"/jobs/{slugify(STATES[code])}", state_counts[code]))
        for fam in FAMILY_ORDER:
            n = sum(1 for j in by_state.get(code, []) if fam in j["families"])
            if n >= 3:
                corridor.append((f"{fam} jobs in {STATES[code]}", f"/jobs/{slugify(STATES[code])}/{fam.lower()}", n))
    corridor.sort(key=lambda t: -t[2])
    corridor_html = "".join(f'<a class="text-sm font-semibold text-foreground underline decoration-primary/70 underline-offset-4 hover:text-primary" href="{h}">{t} ({n})</a>' for t, h, n in corridor[:8])
    for p in pages:
        body = open(os.path.join(ROOT, "content", p["file"]), encoding="utf-8").read().replace("<!--CORRIDOR_LINKS-->", corridor_html)
        # a page people only reach after paying has nothing to offer a searcher,
        # so it stays out of the index and out of the sitemap
        head = '<meta name="robots" content="noindex,follow"/>' if p.get("noindex") else ""
        add(p["path"], layout(p["title"], p["description"], body, p["path"], head), sitemap=not p.get("noindex"))

    # assets
    shutil.copytree(os.path.join(ROOT, "static"), SITE, dirs_exist_ok=True)
    # search index for the in-page filter
    write("jobs-index.json", json.dumps([{"t": j["title"], "c": j["company"], "l": j["location"], "s": j["state"], "f": j["families"], "u": "/jobs/" + j["slug"], "p": j.get("pay")} for j in jobs], ensure_ascii=False))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n")
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sm += "".join(f"  <url><loc>{DOMAIN}{'' if u == '/' else u}</loc></url>\n" for u in urls) + "</urlset>\n"
    write("sitemap.xml", sm)
    print(f"built {len(urls)} pages ({len(jobs)} jobs, {len(employers)} employers) -> {SITE}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    main()
