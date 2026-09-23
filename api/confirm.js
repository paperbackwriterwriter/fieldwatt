// Vercel serverless function: the link in a subscription confirmation email.
//
// Opening the link (GET) only shows a page with a Confirm button. Pressing the
// button (POST) is what adds the address to the mailing list. Corporate email
// security scanners -- Safe Links, Mimecast, Proofpoint -- open every link in
// incoming mail to vet it, and when opening was enough they "confirmed" the
// real addresses the form bot had submitted: one did so for two emails
// fourteen seconds apart. Scanners fetch links; they do not submit forms.
//
// The POST must also arrive a moment after the page was shown. A person reads
// before clicking; a sandbox that renders the page and presses everything on
// it does not.

const crypto = require("crypto");
const { signupSig } = require("./lead.js");

const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const MIN_DWELL_MS = 1500;

function page(res, code, title, body) {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  // never let a cache or prefetcher reuse a confirmation page
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Robots-Tag", "noindex");
  return res
    .status(code)
    .send(
      '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
        "<title>" + title + " | FieldWatt</title>" +
        '<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.6;color:#111">' +
        body
    );
}

function fail(res) {
  return page(
    res,
    400,
    "Link expired",
    "<h1>That link didn't work.</h1>" +
      "<p>It may have expired or been copied incompletely. Sign up again and use the newest email.</p>" +
      '<p><a href="/alerts">Back to FieldWatt alerts</a></p>'
  );
}

function read(req) {
  const q = req.query || {};
  return {
    email: String(q.e || "").trim(),
    form: String(q.f || ""),
    role: String(q.r || ""),
    state: String(q.st || ""),
    ts: String(q.t || ""),
    sig: String(q.s || ""),
  };
}

function valid(p) {
  if (!p.email || !p.form || !/^\d+$/.test(p.ts) || !p.sig) return false;
  if (Date.now() - Number(p.ts) > MAX_AGE_MS) return false;
  const want = Buffer.from(signupSig([p.email.toLowerCase(), p.form, p.role, p.state, p.ts]));
  const got = Buffer.from(p.sig);
  return want.length === got.length && crypto.timingSafeEqual(want, got);
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formBody(req) {
  let b = req.body;
  if (typeof b === "string") b = Object.fromEntries(new URLSearchParams(b));
  return b && typeof b === "object" ? b : {};
}

module.exports = async (req, res) => {
  const p = read(req);
  if (!valid(p)) return fail(res);

  // GET: ask. Nothing changes until a person presses the button.
  if (req.method !== "POST") {
    const action = "/api/confirm?" + new URLSearchParams({
      e: p.email, f: p.form, r: p.role, st: p.state, t: p.ts, s: p.sig,
    });
    return page(
      res,
      200,
      "Confirm your subscription",
      "<h1>One more step</h1>" +
        "<p>Confirm that <strong>" + esc(p.email) + "</strong> should get FieldWatt's Tuesday job emails.</p>" +
        '<form method="post" action="' + esc(action) + '">' +
        '<input type="hidden" name="shown" value="' + Date.now() + '">' +
        '<button type="submit" style="padding:12px 20px;background:#f5c518;border:0;font-weight:bold;font-size:1rem;cursor:pointer">Confirm my subscription</button>' +
        "</form>" +
        "<p style=\"color:#666;font-size:.9rem\">Didn't sign up? Close this page and nothing happens.</p>"
    );
  }

  // POST: the button was pressed.
  const shown = Number(formBody(req).shown);
  if (!(shown > 0) || Date.now() - shown < MIN_DWELL_MS) {
    console.warn("confirm rejected: no dwell", Date.now() - shown, "ms");
    return fail(res);
  }

  const key = process.env.RESEND_API_KEY;
  const headers = {
    Authorization: "Bearer " + key,
    "Content-Type": "application/json",
  };

  const segment =
    process.env.RESEND_SEGMENT_ID || process.env.RESEND_AUDIENCE_ID;
  if (segment) {
    try {
      const c = await fetch("https://api.resend.com/contacts", {
        method: "POST",
        headers,
        body: JSON.stringify({
          email: p.email,
          unsubscribed: false,
          segments: [{ id: segment }],
        }),
      });
      // Confirming twice lands here with the contact already present; that is
      // fine and still counts as confirmed.
      if (!c.ok) console.error("contact add failed", c.status, await c.text());
    } catch (e) {
      console.error("contact add failed", e);
    }
  }

  const to = process.env.LEAD_TO;
  if (key && to) {
    const detail = [p.role && "role " + p.role, p.state && "state " + p.state]
      .filter(Boolean)
      .join(", ");
    // How long after signing up the person confirmed. Minutes is normal; a
    // few seconds deserves a second look.
    const secs = Math.round((Date.now() - Number(p.ts)) / 1000);
    try {
      await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers,
        body: JSON.stringify({
          from: process.env.LEAD_FROM || "onboarding@resend.dev",
          to: [to],
          subject: "[FieldWatt] confirmed subscriber - " + p.email,
          text:
            p.email + " confirmed via " + p.form + (detail ? " (" + detail + ")" : "") +
            ", " + secs + "s after signing up.\n" + new Date().toISOString(),
        }),
      });
    } catch (e) {
      console.error("notify failed", e);
    }
  }

  res.setHeader("Location", "/confirmed");
  return res.status(303).end();
};
