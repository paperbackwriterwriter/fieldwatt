#!/usr/bin/env python3
"""Send the Tuesday FieldWatt job email through Resend.

Env:
  RESEND_API_KEY     required (Full access key)
  RESEND_SEGMENT_ID  segment to broadcast to (signups are added by /api/lead)
  LEAD_TO            your inbox (used for test sends)
  LEAD_FROM          e.g. "FieldWatt <hello@fieldwatt.com>". The domain must
                     be verified in Resend. Until then onboarding@resend.dev
                     is used, which only delivers to your own address.
  TEST_ONLY          "true" sends one email to LEAD_TO instead of a broadcast
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
KEY = os.environ.get("RESEND_API_KEY")
SEGMENT = (os.environ.get("RESEND_SEGMENT_ID")
           or os.environ.get("RESEND_AUDIENCE_ID"))
TO = os.environ.get("LEAD_TO")
FROM = os.environ.get("LEAD_FROM") or "onboarding@resend.dev"
TEST = str(os.environ.get("TEST_ONLY", "true")).lower() == "true"
SITE = "https://fieldwatt.com"
UNSUB = "{{{RESEND_UNSUBSCRIBE_URL}}}"


def post(path, payload):
    req = urllib.request.Request(
        "https://api.resend.com" + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + KEY,
            "Content-Type": "application/json",
            # Resend's firewall rejects Python's default User-Agent (403).
            "User-Agent": "fieldwatt-tuesday-email/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        sys.exit("Resend " + path + " failed: HTTP "
                 + str(e.code) + " " + detail)


def esc(s):
    s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def job_row(j):
    meta = esc(j["company"]) + " · " + esc(j["location"])
    if j.get("pay"):
        meta += " · " + esc(j["pay"])
    return (
        '<li style="margin:0 0 10px">'
        '<a href="' + SITE + "/jobs/" + j["slug"] + '" '
        'style="color:#111;font-weight:700;text-decoration:none">'
        + esc(j["title"]) + "</a><br>"
        '<span style="color:#555;font-size:14px">' + meta + "</span>"
        "</li>"
    )


def build_html(jobs, new):
    sections = ""
    for fam in ["Wind", "Solar", "Storage", "Grid"]:
        fj = [j for j in new if fam in j["families"]][:10]
        if not fj:
            continue
        sections += (
            '<h2 style="font-size:18px;margin:28px 0 10px">' + fam + "</h2>"
            '<ul style="padding-left:18px;margin:0">'
            + "".join(job_row(j) for j in fj)
            + "</ul>"
        )
    date = datetime.now().strftime("%B %-d")
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:600px;'
        'margin:0 auto;padding:24px;color:#111">'
        '<p style="font-size:12px;letter-spacing:.14em;'
        'text-transform:uppercase;color:#777;margin:0">'
        "FieldWatt · Tuesday job email</p>"
        '<h1 style="font-size:24px;margin:8px 0 4px">'
        "New field work for " + date + "</h1>"
        '<p style="color:#555;margin:0 0 8px">'
        + str(len(new)) + " new wind, solar, storage and grid listings "
        "this week · " + str(len(jobs)) + " live in the feed.</p>"
        '<p style="margin:0 0 16px"><a href="' + SITE + '/jobs" '
        'style="color:#111;font-weight:700">Browse every job →</a></p>'
        + sections +
        '<hr style="border:0;border-top:1px solid #e5e5e5;margin:32px 0">'
        '<p style="color:#888;font-size:12px">'
        "FieldWatt links you to the employer's own listing; we never see "
        'your application. Pay marked "est." is the source\'s estimate.'
        '<br>Hiring? <a href="' + SITE + '/hire" style="color:#555">'
        "Feature a job</a> · "
        '<a href="' + UNSUB + '" style="color:#555">Unsubscribe</a></p>'
        "</div>"
    )
    subject = ("FieldWatt: " + str(len(new))
               + " new renewable field jobs (" + date + ")")
    return subject, html


def main():
    if not KEY:
        sys.exit("RESEND_API_KEY not set")
    path = os.path.join(ROOT, "data", "jobs.json")
    with open(path, encoding="utf-8") as f:
        jobs = json.load(f)["jobs"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    week_ago = cutoff.strftime("%Y-%m-%d")
    new = [j for j in jobs if j.get("posted", "") >= week_ago]
    if not new:
        new = jobs[:40]

    subject, html = build_html(jobs, new)

    # Broadcasts need a verified sending domain (LEAD_FROM). Until that is
    # set, every run just sends a test copy to LEAD_TO.
    if TEST or not SEGMENT or not os.environ.get("LEAD_FROM"):
        if not TO:
            sys.exit("LEAD_TO not set for test send")
        r = post("/emails", {
            "from": FROM,
            "to": [TO],
            "subject": "[TEST] " + subject,
            "html": html.replace(UNSUB, SITE),
        })
        print("test email sent:", r)
        return

    b = post("/broadcasts", {
        "segment_id": SEGMENT,
        "from": FROM,
        "subject": subject,
        "html": html,
        "name": subject,
    })
    post("/broadcasts/" + b["id"] + "/send", {})
    print("broadcast sent:", b["id"])


if __name__ == "__main__":
    main()
