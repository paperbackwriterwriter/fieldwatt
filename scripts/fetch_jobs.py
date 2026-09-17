#!/usr/bin/env python3
"""Fetch renewable-energy trades jobs from the Adzuna API into data/jobs.json.

Env vars (GitHub secrets):
  ADZUNA_APP_ID, ADZUNA_APP_KEY   -- free at https://developer.adzuna.com/

Run:  python scripts/fetch_jobs.py
Then: python scripts/build.py
"""
import collections, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

APP_ID = os.environ.get("ADZUNA_APP_ID")
APP_KEY = os.environ.get("ADZUNA_APP_KEY")
ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "jobs.json")

# Search phrases. Each is run for up to PAGES pages of 50 results.
QUERIES = [
    "wind turbine technician", "wind technician", "wind site technician", "blade technician",
    "solar installer", "solar technician", "pv installer", "solar electrician", "solar field technician",
    "utility scale solar", "solar construction",
    "battery storage technician", "bess technician", "energy storage technician",
    "journeyman lineman", "apprentice lineman", "lineman", "substation technician", "substation electrician",
    "transmission line", "distribution lineman", "relay technician", "grid technician",
    "renewable energy technician", "wind farm", "solar farm",
]
PAGES = 3
MAX_DAYS_OLD = 30
PAUSE = 0.6  # seconds between calls (Adzuna free tier is rate limited)

# Titles that are clearly not field/trades work.
EXCLUDE = re.compile(
    r"\b(sales|account (manager|executive)|recruit(er|ing)|marketing|software|developer|analyst|"
    r"attorney|counsel|accountant|intern(ship)?|director of|vice president|vp\b|customer service|"
    r"call center|canvass|appointment setter|consultant|data entry|writer|designer)\b", re.I)

FAMILIES = [
    ("Wind", re.compile(r"\b(wind|turbine|gwo|nacelle|blade)\b", re.I)),
    ("Solar", re.compile(r"\b(solar|pv|photovoltaic|module install)\b", re.I)),
    ("Storage", re.compile(r"\b(battery|bess|energy storage|storage)\b", re.I)),
    ("Grid", re.compile(r"\b(lineman|linemen|lineworker|substation|transmission|distribution|utility|grid|relay|switchgear|powerline|power line)\b", re.I)),
]

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_BY_NAME = {v: k for k, v in STATES.items()}


# --------------------------------------------------------------------------- vetting
# Adzuna matches on the search phrase, so a query for "solar installer" also
# returns flooring and stairlift jobs whose text happens to say "solar" once.
# Everything below decides whether a listing is really renewable or grid field
# work before it reaches the feed.

# A renewable or grid word in a title is strong on its own: a title is short,
# so the word describes the job rather than passing through boilerplate.
TITLE_TERM = re.compile(r"""(?xi)
  \b(wind|turbine|nacelle|blade|gwo
    |solar|pv|photovoltaic
    |bess|lineman|linemen|lineworker|powerline|power\s+line
    |substation|switchgear|switchyard|relay
    |grid|transmission|distribution|t&d|high\s*voltage|overhead
    |line\s+(foreman|crew|worker|mechanic|technician|tech|apprentice|superintendent)
    |renewables?|clean\s+energy|wind\s+farm|solar\s+farm)\b
""")
OFF_TRADE = re.compile(r"""(?xi)
  \b(carpet|flooring|upholster|stairlift|wheelchair|accessibility\s+install|mobility\s+tech
    |dental|nurse|phlebotom|veterinar|barista|cashier|bartender|housekeep|janitor|custodian
    |oil\s+change|lube\s+tech|tire\s+tech|automotive|collision|body\s+shop|attic\s+vent
    |distribution\s+(cent(er|re)|warehouse|associate)|warehouse|forklift|delivery\s+driver
    |locksmith|pest\s+control|landscap|lawn\s+care|snow\s+removal|pool\s+clean)\b
""")
# In a description, only these specific phrases count as evidence.
DESC_TERM = re.compile(r"""(?xi)
  wind\s+(turbine|farm|energy|power|technician|tech|site|project|hub|major|component|blade|industry|generator)
| (turbine|blade)\s+(technician|tech|maintenance|service|repair|generator)
| \b(nacelle|gwo)\b
| solar\s+(panel|array|farm|energy|module|installer|installation|technician|tech|service|project|
           site|field|electrician|crew|laborer|system|battery|power|plant|pv)
| \b(photovoltaic)\b | \bpv\s+(system|module|installer|array|panel|solar)\b
| utility[\s-]scale\s+(solar|wind|storage|renewable)
| battery\s+(energy\s+)?storage | \bbess\b | energy\s+storage\s+(system|technician|project)
| \b(lineman|linemen|lineworker|powerline|power\s+line)\b
| line\s+(foreman|crew|worker|mechanic|apprentice)
| \b(substation|switchgear|switchyard)\b
| (transmission|distribution)\s+(line|lines|system|network)
| overhead\s+(line|distribution|conductor)
| relay\s+(technician|protection)
| \b(renewable|clean)\s+energy\b
""")
# A company whose NAME is unambiguous evidence of the industry.
RENEWABLE_CO = re.compile(r"(?i)\b(solar|wind|renewab|photovolta|turbine)")


def _body(company, desc):
    """Description with the employer's own name removed when that name cannot
    be trusted. 'Solar Contract Carpet' must not vouch for its flooring jobs;
    'Solar Champs LLC' may vouch for its electricians."""
    if company and OFF_TRADE.search(company):
        return re.sub(re.escape(company), " ", desc, flags=re.I)
    return desc


def title_anchor(title):
    """Renewable work established by the title alone."""
    title = title or ""
    return bool(TITLE_TERM.search(title)) and not OFF_TRADE.search(title)


def renewable_employer(company):
    return bool(company) and bool(RENEWABLE_CO.search(company)) and not OFF_TRADE.search(company)


def trusted_companies(jobs, min_anchors=2):
    """Employers the feed itself shows to be renewable outfits. Big operators
    post plenty of generically titled roles ('Technician II'), so trust is
    earned by how many unambiguous listings a company has, not by what share
    of them are unambiguous -- Vestas would fail a ratio test that a staffing
    agency passes."""
    by_co = collections.defaultdict(list)
    for j in jobs:
        by_co[j.get("company_slug") or j["company"]].append(j)
    out = set()
    for slug, js in by_co.items():
        if sum(1 for j in js if title_anchor(j["title"])) >= min_anchors:
            out.add(slug)
        elif renewable_employer(js[0].get("company", "")):
            out.add(slug)
    return out


def vet(job, trusted=frozenset()):
    """(ok, reason) -- is this renewable or grid field work?"""
    title = job["title"]
    company = job.get("company", "")
    if OFF_TRADE.search(title):
        return False, "different trade"
    if title_anchor(title):
        return True, "title"
    hits = DESC_TERM.findall(_body(company, job.get("description", "")))
    if len(hits) >= 2:
        return True, "description"
    if (job.get("company_slug") or company) in trusted:
        return True, "renewable employer"
    if hits:
        return False, "single passing mention"
    return False, "no renewable evidence"


# Pay below federal minimum wage over a 2,080-hour year is not an annual salary:
# it is an hourly or weekly rate the source published without a period, or a
# placeholder like "$1". The figure cannot be shown or trusted, so the listing
# does not go in the feed.
MIN_ANNUAL_SALARY = 7.25 * 2080
PAY_RE = re.compile(r"^\$([\d,]+)(?:–\$([\d,]+))?(?: · .*)?$")


def pay_too_low(pay, pay_listed):
    if not pay_listed or not pay:
        return False
    m = PAY_RE.match(pay)
    return bool(m) and int(m.group(1).replace(",", "")) < MIN_ANNUAL_SALARY


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80] or "job"


def classify(title: str, desc: str):
    fams = [name for name, rx in FAMILIES if rx.search(title)]
    if not fams:
        fams = [name for name, rx in FAMILIES if rx.search(desc)]
    return fams


def api(query: str, page: int):
    q = urllib.parse.urlencode({
        "app_id": APP_ID, "app_key": APP_KEY, "results_per_page": 50,
        "what": query, "max_days_old": MAX_DAYS_OLD, "sort_by": "date",
        "content-type": "application/json",
    })
    url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "fieldwatt-feed/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def normalize(raw: dict):
    title = (raw.get("title") or "").strip()
    title = re.sub(r"</?strong>", "", title)
    desc = re.sub(r"\s+", " ", raw.get("description") or "").strip()
    if not title or EXCLUDE.search(title):
        return None
    fams = classify(title, desc)
    if not fams:
        return None
    area = (raw.get("location") or {}).get("area") or []
    state_name = area[1] if len(area) > 1 else ""
    state = STATE_BY_NAME.get(state_name, "")
    city = area[-1] if len(area) > 2 else ""
    loc = ", ".join(x for x in [city, state_name] if x)
    if not state:
        return None
    smin, smax = raw.get("salary_min"), raw.get("salary_max")
    predicted = str(raw.get("salary_is_predicted", "0")) == "1"
    pay = None
    if smin or smax:
        lo, hi = int(smin or smax), int(smax or smin)
        if predicted:
            pay = f"est. ${(lo + hi) // 2:,}"
        elif lo == hi:
            pay = f"${lo:,}"
        else:
            pay = f"${lo:,}–${hi:,}"
    if pay_too_low(pay, bool(pay and not predicted)):
        return None
    jid = str(raw.get("id"))
    company = ((raw.get("company") or {}).get("display_name") or "Employer").strip()
    return {
        "id": jid,
        "slug": f"{slugify(title)}--adzuna-{jid}",
        "title": title,
        "company": company,
        "company_slug": slugify(company),
        "city": city,
        "state": state,
        "state_name": state_name,
        "location": loc,
        "families": fams,
        "description": desc[:1200],
        "pay": pay,
        "pay_listed": bool(pay and not predicted),
        "apply_url": raw.get("redirect_url"),
        "posted": (raw.get("created") or "")[:10],
        "source": "adzuna",
    }


def main():
    if not APP_ID or not APP_KEY:
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY")
    jobs = {}
    calls = 0
    for q in QUERIES:
        for page in range(1, PAGES + 1):
            try:
                data = api(q, page)
            except Exception as e:  # noqa
                print(f"  ! {q} p{page}: {e}")
                break
            calls += 1
            results = data.get("results") or []
            for raw in results:
                j = normalize(raw)
                if j and j["id"] not in jobs:
                    jobs[j["id"]] = j
            print(f"  {q} p{page}: {len(results)} results, total {len(jobs)}")
            if len(results) < 50:
                break
            time.sleep(PAUSE)
    # Vetting runs once over the whole batch, because whether an employer is a
    # renewable outfit is read off its other listings.
    candidates = list(jobs.values())
    trusted = trusted_companies(candidates)
    kept, rejected = [], collections.Counter()
    for j in candidates:
        ok, why = vet(j, trusted)
        if ok:
            kept.append(j)
        else:
            rejected[why] += 1
    for why, n in rejected.most_common():
        print(f"  vetting dropped {n}: {why}")
    print(f"  vetting kept {len(kept)} of {len(candidates)}")

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(kept),
        "jobs": sorted(kept, key=lambda j: j["posted"], reverse=True),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {len(kept)} jobs ({calls} API calls) -> {OUT}")


if __name__ == "__main__":
    main()
