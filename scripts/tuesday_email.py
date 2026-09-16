#!/usr/bin/env python3
"""Send the Tuesday FieldWatt job email through Resend.

Env:
  RESEND_API_KEY      required
  RESEND_AUDIENCE_ID  audience to broadcast to (contacts are added by /api/lead)
  LEAD_TO             your inbox (used for TEST_ONLY sends)
  LEAD_FROM           e.g. "FieldWatt <hello@fieldwatt.com>" (domain must be verified in Resend;
                      before that, onboarding@resend.dev only delivers to LEAD_TO)
  TEST_ONLY           "true" -> send a single email to LEAD_TO instead of a broadcast
"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
KEY = os.environ.get("RESEND_API_KEY")
AUD = os.environ.get("RESEND_AUDIENCE_ID")
TO = os.environ.get("LEAD_TO")
FROM = os.environ.get("LEAD_FROM") or "onboarding@resend.dev"
TEST = str(os.environ.get("TEST_ONLY", "true")).lower() == "true"
SITE = "https://fieldwatt.com"


def post(path, payload):
    req = urllib.request.Request("https://api.resend.com" + path, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    if not KEY:
        sys.exit("RESEND_API_KEY not set")
    data = json.load(open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8"))
    jobs = data["jobs"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    new = [j for j in jobs if j.get("posted", "") >= week_ago] or jobs[:40]

    sections = ""
    for fam in ["Wind", "Solar", "Storage", "Grid"]:
        fj = [j for j in new if fam in j["families"]][:10]
        if not fj:
            continue
        rows = "".join(
            f'<li style="margin:0 0 10px"><a href="{SITE}/jobs/{j["slug"]}" style="color:#111;font-weight:700;text-decoration:none">{esc(j["title"])}</a><br>'
            f'<span style="color:#555;font-size:14px">{esc(j["company"])} · {esc(j["location"])}{" · " + esc(j["pay"]) if j.get("pay") else ""}</span></li>'
            for j in fj)
        sections += f'<h2 style="font-size:18px;margin:28px 0 10px">{fam}</h2><ul style="padding-left:18px;margin:0">{rows}</ul>'

    date = datetime.now().strftime("%B %-d")
    html = f'''<div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#111">
<p style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#777;margin:0">FieldWatt · Tuesday job email</p>
<h1 style="font-size:24px;margin:8px 0 4px">New field work for {date}</h1>
<p style="color:#555;margin:0 0 8px">{len(new)} new wind, solar, storage and grid listings this week · {len(jobs)} live in the feed.</p>
<p style="margin:0 0 16px"><a href="{SITE}/jobs" style="color:#111;font-weight:700">Browse every job →</a></p>
{sections}
<hr style="border:0;border-top:1px solid #e5e5e5;margin:32px 0">
<p style="color:#888;font-size:12px">FieldWatt links you to the employer's own listing; we never see your application. Listed pay only — "est." figures are the source's estimate.<br>
Hiring? <a href="{SITE}/hire" style="color:#555">Feature a job</a>. &nbsp;·&nbsp; <a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}" style="color:#555">Unsubscribe</a></p>
</div>'''
    subject = f"FieldWatt: {len(new)} new renewable field jobs ({date})"

    if TEST or not AUD:
        if not TO:
            sys.exit("LEAD_TO not set for test send")
        r = post("/emails", {"from": FROM, "to": [TO], "subject": "[TEST] " + subject, "html": html.replace("{{{RESEND_UNSUBSCRIBE_URL}}}", SITE)})
        print("test email sent:", r)
        return
    b = post("/broadcasts", {"audience_id": AUD, "from": FROM, "subject": subject, "html": html, "name": subject})
    post(f"/broadcasts/{b['id']}/send", {})
    print("broadcast sent:", b["id"])


if __name__ == "__main__":
    main()
