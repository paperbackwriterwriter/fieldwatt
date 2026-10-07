#!/usr/bin/env python3
"""Tell Google which job pages appeared or closed, through the Indexing API.

Google built this API for pages with JobPosting markup: a notification gets
the page crawled within hours instead of whenever the sitemap comes round,
which on a feed that adds and retires hundreds of pages a night is the
difference between being indexed and not.

Runs after the nightly build and push. Needs:
  GOOGLE_INDEXING_KEY  the JSON key of a Google Cloud service account that
                       has the Indexing API enabled and is an Owner of the
                       fieldwatt.com property in Search Console. Absent, the
                       script prints a note and exits 0.

Default quota is 200 notifications a day, so the script spends it on the
newest listings first, then on pages that just closed, and remembers what it
has sent in data/indexing-state.json. Nothing is re-sent while a page is
unchanged.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SITE = os.environ.get("SITE_URL", "https://fieldwatt.com").rstrip("/")
STATE = os.path.join(ROOT, "data", "indexing-state.json")
DAILY_LIMIT = int(os.environ.get("INDEXING_DAILY_LIMIT", "190"))
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
DRY = "--dry-run" in sys.argv


def token(key_json):
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key_json), scopes=["https://www.googleapis.com/auth/indexing"])
    creds.refresh(Request())
    return creds.token


def notify(tok, url, kind):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"url": url, "type": kind}).encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


def main():
    key = os.environ.get("GOOGLE_INDEXING_KEY")
    if not key and not DRY:
        print("GOOGLE_INDEXING_KEY not set; skipping Google indexing notifications")
        return
    with open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8") as f:
        jobs = json.load(f)["jobs"]
    retired_path = os.path.join(ROOT, "data", "retired.json")
    retired = json.load(open(retired_path, encoding="utf-8")) if os.path.exists(retired_path) else []
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    notified = state.get("notified", {})
    closed = state.get("deleted", {})

    live = {j["slug"] for j in jobs}
    # newest first: a listing posted today is worth more to a searcher than
    # one that has been up three weeks and may have been crawled anyway
    new = [j["slug"] for j in sorted(jobs, key=lambda j: j["posted"], reverse=True) if j["slug"] not in notified]
    gone = [r["slug"] for r in retired if r["slug"] not in live and r["slug"] not in closed]
    queue = [(s, "URL_UPDATED") for s in new] + [(s, "URL_UPDATED") for s in gone]
    print(f"{len(new)} new pages and {len(gone)} closed pages to notify; sending up to {DAILY_LIMIT}")

    tok = None if DRY else token(key)
    today = datetime.now(timezone.utc).date().isoformat()
    retired_slugs = {r["slug"] for r in retired}
    sent = 0
    for slug, kind in queue[:DAILY_LIMIT]:
        url = f"{SITE}/jobs/{slug}"
        if DRY:
            print("  would send", kind, url)
            continue
        status, err = notify(tok, url, kind)
        if status == 200:
            (closed if slug in retired_slugs and slug not in live else notified)[slug] = today
            sent += 1
        elif status == 429:
            print("  quota exhausted after", sent, "notifications")
            break
        else:
            print(f"  ! {status} for {url}: {err}")
            if status in (401, 403):
                break

    # forget pages that no longer exist on either list, so the file stays small
    live_or_closed = live | {r["slug"] for r in retired}
    state = {
        "notified": {s: d for s, d in notified.items() if s in live},
        "deleted": {s: d for s, d in closed.items() if s in live_or_closed},
        "last_run": today,
    }
    if not DRY:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
    print(f"sent {sent} notifications; {len(queue) - sent} still queued for later runs")


if __name__ == "__main__":
    main()
