#!/usr/bin/env python3
"""Fetch renewable-energy trades jobs from the Adzuna API into data/jobs.json.

Env vars (GitHub secrets):
  ADZUNA_APP_ID, ADZUNA_APP_KEY   -- free at https://developer.adzuna.com/

Run:  python scripts/fetch_jobs.py
Then: python scripts/build.py
"""
import json, os, re, sys, time, urllib.parse, urllib.request
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
    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(jobs),
        "jobs": sorted(jobs.values(), key=lambda j: j["posted"], reverse=True),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {len(jobs)} jobs ({calls} API calls) -> {OUT}")


if __name__ == "__main__":
    main()
