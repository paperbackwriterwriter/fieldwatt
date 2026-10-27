#!/usr/bin/env python3
"""Fetch renewable-energy trades jobs from the Adzuna API into data/jobs.json.

Env vars (GitHub secrets):
  ADZUNA_APP_ID, ADZUNA_APP_KEY   -- free at https://developer.adzuna.com/

Run:  python scripts/fetch_jobs.py
Then: python scripts/build.py
"""
import collections, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

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
# Each query returns its newest PAGES*50 listings. Busy terms ("wind farm",
# "solar installer") have more live ads than that inside MAX_DAYS_OLD, so a
# listing a week old can drop off the back of a search while still open. The
# carry-over in main() keeps such listings until they age out; more pages
# just means fewer need carrying.
PAGES = 5
MAX_DAYS_OLD = 30
PAUSE = 0.6  # seconds between calls (Adzuna free tier is rate limited)
RETRIES = 2  # Adzuna answers 503 now and then; one retry usually clears it

# Titles that are clearly not field/trades work.
EXCLUDE = re.compile(
    r"\b(sales|account (manager|executive)|recruit(er|ing)|marketing|software|developer|analyst|"
    r"attorney|counsel|accountant|intern(ship)?|director of|vice president|vp\b|customer service|"
    r"call center|canvass|appointment setter|consultant|data entry|writer|designer)s?\b", re.I)

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
    |grid|t&d|high\s*voltage
    |(?:transmission|distribution|overhead)\s+(?:line\w*|system|substation|construction|crew|foreman|power|electric\w*|grid|utility)
    |power\s+(?:transmission|distribution|delivery)|electric(?:al)?\s+(?:transmission|distribution)
    |line\s+(foreman|crew|worker|mechanic|technician|tech|apprentice|superintendent)
    |renewables?|clean\s+energy|wind\s+farm|solar\s+farm)\b
""")
OFF_TRADE = re.compile(r"""(?xi)
  \b(carpet|flooring|upholster|stairlift|wheelchair|accessibility\s+install|mobility\s+tech
    |dental|nurse|phlebotom|veterinar|barista|cashier|bartender|housekeep|janitor|custodian
    |oil\s+change|lube\s+tech|tire\s+tech|automotive|collision|body\s+shop|attic\s+vent
    |distribution\s+(cent(er|re)|warehouse|associate)|warehouse|forklift|delivery\s+driver
    |locksmith|pest\s+control|landscap|lawn\s+care|snow\s+removal|pool\s+clean
    |telecom\w*|fiber\s+(optic|splic|groundman|lineman|tech)|fiber\s*-\s*joint|joint\s+use|cable\s+splic|catv|broadband
    |communications?\s+(lineman|linemen|technician|tech|tower)
    |window\s+(film|tint|install)|wind\s+tunnel
    |manufactur\w*|production\s+(line|operator|associate)|tube\s+mill
    |cnc|r\s*&\s*d|prototyp\w*|characterization|laboratory|lab\s+tech\w*
    |telephone|appliance|drywall|pipefitter|plumb\w*|solar\s+cells?|production\s+support
    |transmission\s+(?:rebuild\w*|repair|shop)|auto\s+tech\w*|application\s+collection)\b
""")
# Employers whose name says they are in another trade. "MasTec Communications
# Group" posts aerial linemen, and they string fibre, not power.
OFF_TRADE_CO = re.compile(r"(?i)\b(communications?|telecom\w*|cable\s+splicing|broadband|fiber|window|solar\s+control)\b")
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


# "Solar" in a name the rest of which says roofing or air conditioning is a
# contractor in that trade that also does some solar, not a solar company.
OTHER_TRADE_CO = re.compile(r"(?i)\b(roof\w*|refrigerat\w*|appliance|air\s+condition\w*|heating|hvac|plumb\w*|pool|screen|shade|film|tint|control)")


def renewable_employer(company):
    return (bool(company) and bool(RENEWABLE_CO.search(company))
            and not OFF_TRADE.search(company) and not OTHER_TRADE_CO.search(company))


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
        # Only listings that pass vetting on their own count. A staffing
        # agency's two rejected "Solar Project Manager" ads must not vouch
        # for its "Data Scientist" or "General Laborer" ads.
        if sum(1 for j in js if vet(j)[1] == "title") >= min_anchors:
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
    # A utility's own fibre crew ("Substation Fiber Technician") stays; a
    # telecom contractor's linemen do not, whatever the title calls them.
    if OFF_TRADE_CO.search(company) and not re.search(r"(?i)substation|transmission|utility|power", title):
        return False, "different trade"
    if not is_field_role(title):
        return False, "not field work"
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


# Roles that are never field work, whatever else the title says. Teaching a
# lineworker course is not lineworker work.
OFFICE_ONLY = re.compile(r"""(?xi)
  \b(professor|instructor|faculty|lecturer|trainer|educator
    |director|president|officer|executive
    |estimator|analyst|planner|scheduler|architect|administrator|controller
    |coordinator|recruiter|buyer|paralegal|auditor|underwriter
    |compliance|procurement|payroll|bookkeep
    |finance|financial|accountant|accounting|marketing|human\s+resources|legal|counsel
    |customer\s+(service|success|support)|dispatcher|drafter|drafting|cad
    |originator|business\s+development|sales
    |academic|program\s+manager|division\s+manager|tech(?:nical)?\s+support
    |(?<!field\sservice\s)representative|market\s+development|account\s+manager|data\s+scientist|archaeolog\w*
    |scientist|administrative|receptionist|clerk|safety\s+professional|appointment\s+setter)s?\b
""")

# Roles that read as office work unless the title also names a trade.
OFFICE_UNLESS_TRADE = re.compile(r"""(?xi)
  \b(engineer|engineering|manager|mgr|management|supervisor|superintendent
    |specialist|lead|consultant|advisor|strateg\w*|liaison|agent|associate|assistant)s?\b
""")

# Hands-on work. These win over the line above: an "Electrical Engineering
# Technician" is a technician, and a "Substation Foreman" runs a crew on site.
TRADE = re.compile(r"""(?xi)
  \b(technician|tech|installer|install|foreman|lineman|linemen|lineworker
    |line\s+work\w*|mechanic|operator|apprentice|journeyman|journeyperson
    |laborer|labourer|crew|electrician|welder|rigger|fitter|millwright
    |climber|splicer|groundman|groundsman|wireman|troubleshooter|roof\w*
    |operating\s+engineer|stationary\s+engineer|field\s+service\s+engineer)\b
""")


def is_field_role(title):
    """The site promises field work -- turbine techs, installers, linemen,
    substation crews -- so office roles in the same industry do not belong."""
    title = title or ""
    if OFFICE_ONLY.search(title):
        return False
    if OFFICE_UNLESS_TRADE.search(title) and not TRADE.search(title):
        return False
    return True


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


_VALUED = (r"job\s+title|position\s+title|location|work\s+location|requisition\s+(?:id|number)|req\s+id"
           r"|job\s+id|job\s+number|date\s+posted|job\s+type|department|schedule|shift|job\s+posting\s+end\s+date"
           r"|job\s+category|job\s+level|business\s+unit|work\s+type|company")
_HEADING = r"company\s+summary(?:\s+statement)?|position\s+summary|job\s+summary|overview|summary|about\s+us|full[- ]time\s+description|job\s+description"
DESC_LABEL = re.compile(
    rf"(?i)^(?:requisition(?:\s+(?:id|number|#))?\s*:?\s*#?\d+\b"
    rf"|(?:{_HEADING})\b\s*:?(?=\s*(?-i:[A-Z0-9]))"
    rf"|(?:{_VALUED})\s*:\s*.{{0,90}}?(?=\s+(?:{_VALUED}|{_HEADING})\b))\s*")


def clean_description(text: str) -> str:
    """Whitespace-collapsed, minus the boilerplate some boards prepend: a third
    of listings opened "Job Description Job Description Benefits: ..."."""
    s = re.sub(r"\s+", " ", text).strip()
    s = re.sub(r"^(?:(?:job\s+)?description\s*:?\s*)+", "", s, flags=re.I)
    # leading metadata: "Job Title: X Location: Y Requisition ID: 123 ..."
    for _ in range(8):
        t = DESC_LABEL.sub("", s, count=1)
        if t == s:
            break
        s = t
    return s.strip()


def strip_location(title: str, city: str, state: str, state_name: str) -> str:
    """Drop a trailing location the feed already carries separately, so the
    title names the job ("Wind Technician II" not "Wind Technician II -
    Lubbock, TX"). Google asks for exactly that in a JobPosting title. Only
    the listing's own city or state is removed; anything else stays."""
    if not state:
        return title
    places = [re.escape(p) for p in (city, state_name) if p]
    place = "|".join(places + [re.escape(state)]) if places else re.escape(state)
    loc = rf"(?:{place})(?:\s*,\s*(?:{re.escape(state)}|{re.escape(state_name)}))?"
    t = re.sub(rf"\s+(?:in|at)\s+{loc}\s*$", "", title, flags=re.I)
    t = re.sub(rf"(?:\s*[-–|,(]\s*|\s+){loc}\s*\)?\s*$", "", t, flags=re.I)
    return tidy_tail(t) or title


def tidy_tail(t):
    """What stripping can leave behind: "Solar Roof Lead (South Bay" once
    ", CA)" goes, "Wind Technician III - Northern Divide:" or "(Reading /".
    An unclosed bracket at the end only ever held a place, so it goes too."""
    for _ in range(3):
        depth, cut = 0, None
        for i, ch in enumerate(t):
            if ch in "([":
                if depth == 0:
                    cut = i
                depth += 1
            elif ch in ")]" and depth:
                depth -= 1
        if depth and cut is not None:
            t = t[:cut]
        t = t.strip(" -–|,:/")
    return t


# Words some boards and staffing agencies bolt onto a title. None of them
# name the job, and Google's JobPosting rules ask for the job alone.
TITLE_NOISE = [
    r"\s+job\s+details\s*\|.*$",            # "... Job Details | Black & Veatch Family of Companies"
    r"\s*[-–]\s*hiring\s+asap.*$",
    r"\s*[-–(]*\s*\b(?:urgent(?:ly)?\s+need(?:ed)?|immediate(?:ly)?\s+hiring|hiring\s+(?:immediately|asap))\b\s*!*\)?",
    r"\s*[-–]?\s*\bapply\s+now\b.*$",
    r"\s*[,.]?\s*\bpaying\s+\$[\d.,]+\s*(?:per|an|/)\s*(?:hour|hr)\b\.?",
    r"\s*\bstart\s+asap\b",
    r"^hiring\s+for\s+",
    r"\s+in\s*,\s*[^,]*,?\s*$",                # "General Laborer In , Cleburne ,"
]


def clean_title(title, company=""):
    t = re.sub(r"</?strong>", "", title or "")
    for rx in TITLE_NOISE:
        t = re.sub(rx, " ", t, flags=re.I)
    if company:
        t = re.sub(rf"\s*\|\s*{re.escape(company)}.*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,!])", r"\1", t)
    return tidy_tail(t) or (title or "").strip()


# Pay stated in the listing's own words. Adzuna's estimate is shown when the
# employer said nothing, but "est. $144,637" above a description that says
# "Earn $75,000 to $100,000 a year" misleads, so the employer's figure wins.
_NUM = r"\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{1,2})?)\s*(k)?"
PAY_RANGE = re.compile(r"\$" + _NUM[3:] + r"(?:\s*(?:-|–|to)\s*" + _NUM + r")?"
                       r"(\s*(?:/|per|an|a)\s*(?:hour|hr)\b)?", re.I)
NOT_PAY = re.compile(r"(?i)per\s+diem|/\s*day|a\s+day|per\s+day|daily|bonus|stipend|allowance|reimburs|sign[- ]on|referral")


def _amount(num, k):
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def _dollars(v):
    return f"${v:.0f}" if v == int(v) else f"${v:.2f}"


def pay_from_text(desc):
    for m in PAY_RANGE.finditer(desc or ""):
        around = desc[max(0, m.start() - 30):m.end() + 25]
        if NOT_PAY.search(around):
            continue
        lo = _amount(m.group(1), m.group(2) or (m.group(4) if m.group(3) else None))
        hi = _amount(m.group(3), m.group(4) or m.group(2)) if m.group(3) else lo
        if hi < lo:
            continue
        if m.group(5):
            if 12 <= lo <= 150 and hi <= 150:
                return (f"{_dollars(lo)}/hr" if lo == hi else f"{_dollars(lo)}–{_dollars(hi)}/hr")
        elif 20000 <= lo <= 300000 and hi <= 300000 and (m.group(2) or m.group(4) or "," in m.group(1)):
            return (f"${int(lo):,}" if lo == hi else f"${int(lo):,}–${int(hi):,}")
    return None


def refine(job):
    """Cleaning that applies to every listing, including ones carried over
    from earlier nights that were cleaned by older rules."""
    job["title"] = clean_title(job["title"], job.get("company", ""))
    job["title"] = strip_location(job["title"], job.get("city", ""), job.get("state", ""), job.get("state_name", ""))
    if job.get("city") and job["city"] == job.get("state_name"):
        job["city"] = ""
        job["location"] = job["state_name"]
    desc = job.get("description", "")
    job["description"] = clean_description(desc)
    if not job.get("pay_listed"):
        stated = pay_from_text(job["description"])
        if stated:
            job["pay"], job["pay_listed"] = stated, True
    # Adzuna marks some full-time jobs part-time; only the listing's own words
    # are trusted for that.
    emp = job.get("employment") or []
    if "PART_TIME" in emp and not (re.search(r"\bpart[ -]time\b", desc, re.I)
                                   and not re.search(r"\bfull[ -]time\b", desc, re.I)):
        emp = [x for x in emp if x != "PART_TIME"]
        if re.search(r"\bfull[ -]time\b", desc, re.I):
            emp.insert(0, "FULL_TIME")
    job["employment"] = emp
    return job


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
    company = ((raw.get("company") or {}).get("display_name") or "Employer").strip()
    title = clean_title((raw.get("title") or "").strip(), company)
    desc = clean_description(raw.get("description") or "")
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
    # Adzuna sends contract_time (full_time / part_time) and contract_type
    # (permanent / contract) on some listings. Kept in Google's JobPosting
    # vocabulary so the page can state them; absent means unknown, never a
    # default.
    employment = []
    time_ = {"full_time": "FULL_TIME", "part_time": "PART_TIME"}.get(raw.get("contract_time"))
    # refine() drops PART_TIME again unless the listing itself says so
    if not time_:
        # the listing's own words, when the feed field is blank
        if re.search(r"\bfull[ -]time\b", desc, re.I) and not re.search(r"\bpart[ -]time\b", desc, re.I):
            time_ = "FULL_TIME"
        elif re.search(r"\bpart[ -]time\b", desc, re.I) and not re.search(r"\bfull[ -]time\b", desc, re.I):
            time_ = "PART_TIME"
    if time_:
        employment.append(time_)
    if raw.get("contract_type") == "contract":
        employment.append("CONTRACTOR")
    title = strip_location(title, city, state, state_name)
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
        "employment": employment,
        "source": "adzuna",
    }


def load_previous():
    """Last night's feed, so listings that fell off the back of a search are
    not mistaken for closed ones."""
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("jobs") or []
    except (OSError, ValueError):
        return []


def carry_over(jobs, previous, today):
    """Add listings from the previous feed that this fetch did not return and
    that are still younger than MAX_DAYS_OLD, the same window the search
    itself uses. A listing the employer has closed can linger until it ages
    out, but that is no worse than what Adzuna's own window already allows,
    and far better than open jobs vanishing because a busy search term pushed
    them past the last page. They go through vetting again like everything
    else. Returns how many were added."""
    cutoff = (today - timedelta(days=MAX_DAYS_OLD)).isoformat()
    n = 0
    for j in previous:
        if j.get("source") == "adzuna" and j["id"] not in jobs and j.get("posted", "") >= cutoff:
            jobs[j["id"]] = j
            n += 1
    return n


# One posting syndicated to every city an employer works in: SOLV Energy's
# "Solar Field Service Technician (Multiple Locations)" arrived as 100 copies.
# A hundred identical pages is thin content to Google and a wall of the same
# card to a reader. Keep a few per state so the state pages still show it.
# Copies in different cities of a state can each be what someone searching
# that town needs, so up to three stay. Copies in the same city are the same
# page twice; only one of those stays.
MAX_COPIES_PER_STATE = 3


def cap_duplicates(jobs, published=frozenset()):
    """Keep one copy per (title, employer, city) and at most
    MAX_COPIES_PER_STATE per (title, employer, state). Copies already
    published last night win, then the lowest id, so the same copies survive
    night after night instead of whichever Adzuna returned first, which used
    to flip pages between live and "closed".
    Returns (kept, moved): moved maps each dropped id to the slug of the copy
    that stays, so a dropped page can send people there."""
    jobs = sorted(jobs, key=lambda j: (j["id"] not in published, str(j["id"])))
    per_state, per_city = {}, {}
    out, moved = [], {}
    for j in jobs:
        key = (j["title"].lower(), j["company_slug"], j["state"])
        city_key = key + ((j.get("city") or "").lower(),)
        first = per_city.get(city_key)
        if first is None and len(per_state.get(key, [])) >= MAX_COPIES_PER_STATE:
            first = per_state[key][0]
        if first is not None:
            moved[j["id"]] = first["slug"]
            continue
        per_city[city_key] = j
        per_state.setdefault(key, []).append(j)
        out.append(j)
    if moved:
        print(f"  dropped {len(moved)} duplicate copies of syndicated postings")
    return out, moved


# Jobs that left the feed. Their pages used to vanish, so every link Google,
# the Tuesday email or a job seeker's bookmark still held returned a 404 and
# Search Console filled with "Not found" errors. For a few weeks after a
# listing goes, its page says so instead and points at live work nearby.
RETIRED_FILE = os.path.join(ROOT, "data", "retired.json")
RETIRED_DAYS = 21
RETIRED_KEYS = ("id", "slug", "title", "company", "company_slug", "state", "state_name", "families")


def load_retired():
    try:
        with open(RETIRED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def record_retired(previous, kept, today, moved=None):
    """A dropped duplicate is still an open job, so its entry says where the
    copy that stayed is (moved_to) and its page sends people there."""
    moved = moved or {}
    live = {j["id"] for j in kept}
    cutoff = (today - timedelta(days=RETIRED_DAYS)).isoformat()
    retired = load_retired()
    retired = [r for r in retired if r["id"] not in live and r["retired"] >= cutoff]
    for r in retired:
        if r["id"] in moved:
            r["moved_to"] = moved[r["id"]]
        else:
            r.pop("moved_to", None)
    known = {r["id"] for r in retired}
    added = 0
    for j in previous:
        if j["id"] not in live and j["id"] not in known:
            r = {k: j.get(k) for k in RETIRED_KEYS}
            r["retired"] = today.isoformat()
            if j["id"] in moved:
                r["moved_to"] = moved[j["id"]]
            retired.append(r)
            added += 1
    with open(RETIRED_FILE, "w", encoding="utf-8") as f:
        json.dump(retired, f, indent=1, ensure_ascii=False)
    return added


def main():
    if not APP_ID or not APP_KEY:
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY")
    jobs = {}
    calls = 0
    for q in QUERIES:
        for page in range(1, PAGES + 1):
            data = None
            for attempt in range(1, RETRIES + 2):
                try:
                    data = api(q, page)
                    break
                except Exception as e:  # noqa
                    print(f"  ! {q} p{page} (try {attempt}): {e}")
                    time.sleep(3 * attempt)
            if data is None:
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
    today = datetime.now(timezone.utc).date()
    previous = load_previous()
    # A dead API (bad key, outage, a changed response shape) must fail the run
    # rather than quietly republish last night's feed under today's date.
    if calls == 0 or len(jobs) < max(50, len(previous) // 5):
        sys.exit(f"Adzuna returned {len(jobs)} usable listings from {calls} calls "
                 f"(last feed had {len(previous)}); not overwriting the feed")
    # A listing keeps the URL it was first published under, whatever the
    # title cleaning does to it later; the slug only has to be stable. A
    # listing that was away for a night or two gets its old URL back too.
    prev_slug = {r["id"]: r["slug"] for r in load_retired()}
    prev_slug.update({j["id"]: j["slug"] for j in previous})
    for j in jobs.values():
        j["slug"] = prev_slug.get(j["id"], j["slug"])
    carried = carry_over(jobs, previous, today)
    print(f"  carried over {carried} listings not in this fetch but still inside {MAX_DAYS_OLD} days")

    # Vetting runs once over the whole batch, because whether an employer is a
    # renewable outfit is read off its other listings.
    candidates = [refine(j) for j in jobs.values()]
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
    # Retired means gone from the source, failed vetting, or a duplicate copy
    # that was dropped; that last kind points at the copy that stayed.
    kept, moved = cap_duplicates(kept, {j["id"] for j in previous})
    print(f"  retired {record_retired(previous, kept, today, moved)} listings that left the feed")

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
