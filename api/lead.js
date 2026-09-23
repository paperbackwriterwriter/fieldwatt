// Vercel serverless function: receives form submissions from the site and
// emails them to you through Resend. Works on the Vercel Hobby plan.
//
// Env vars to set in the Vercel project:
//   RESEND_API_KEY    - from resend.com (Full access)
//   LEAD_TO           - where submissions go (your inbox)
//   LEAD_FROM         - optional; defaults to onboarding@resend.dev, which
//                       only delivers to the address that owns the Resend
//                       account. Once the site's domain is verified in
//                       Resend, set this to e.g.
//                       "FieldWatt <hello@fieldwatt.com>".
//   RESEND_SEGMENT_ID - optional; if set, email signups are also saved as
//                       Resend contacts in that segment (for newsletters).
//                       RESEND_AUDIENCE_ID is still accepted as a fallback.
//   TURNSTILE_SECRET_KEY - optional; when set, every submission must carry a
//                       valid Cloudflare Turnstile token or it is rejected.
//                       Leave unset and the endpoint keeps working on the
//                       honeypot and timing check alone.

// A person needs longer than this to read a form and fill it in. Client
// supplied and therefore forgeable, so it is a cheap extra filter rather than
// a control to rely on -- Turnstile is what actually holds.
const MIN_FILL_MS = 3000;

async function turnstileOk(token, ip) {
  const secret = process.env.TURNSTILE_SECRET_KEY;
  if (!secret) return true; // not configured: nothing to verify against
  if (!token) return false;
  try {
    const form = new URLSearchParams({ secret, response: token });
    if (ip) form.set("remoteip", ip);
    const r = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      { method: "POST", body: form }
    );
    const out = await r.json();
    if (!out.success) console.error("turnstile rejected", out["error-codes"]);
    return out.success === true;
  } catch (e) {
    // Cloudflare unreachable. Fail closed: a spam run is the likelier cause
    // of a flood of unverifiable submissions than an outage.
    console.error("turnstile verify failed", e);
    return false;
  }
}

const ALLOWED_FIELDS = 40;

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") {
    return res.status(405).json({ error: "POST only" });
  }

  let body = req.body;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      body = {};
    }
  }
  body = body && typeof body === "object" ? body : {};

  // Honeypot: real users never fill this.
  if (body.website) return res.status(200).json({ ok: true });

  // Submitted faster than anyone could read the form.
  if (Number(body.elapsedMs) >= 0 && Number(body.elapsedMs) < MIN_FILL_MS) {
    console.warn("rejected: submitted in", body.elapsedMs, "ms");
    return res.status(200).json({ ok: true });
  }

  const ip =
    (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || undefined;
  if (!(await turnstileOk(body.turnstileToken, ip))) {
    return res.status(400).json({ error: "Verification failed" });
  }

  const email = String(body.email || "").trim();
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return res.status(400).json({ error: "Invalid email" });
  }

  const site = String(body.site || "Website").slice(0, 60);
  const form = String(body.form || "form").slice(0, 60);

  const skip = ["site", "form", "website", "turnstileToken", "elapsedMs"];
  const rows = Object.entries(body)
    .filter(([k]) => !skip.includes(k))
    .slice(0, ALLOWED_FIELDS)
    .map(([k, v]) => {
      const val = typeof v === "object" ? JSON.stringify(v) : v;
      return (
        '<tr><td style="padding:4px 12px 4px 0;color:#666">' +
        esc(k) +
        '</td><td style="padding:4px 0">' +
        esc(val).slice(0, 4000) +
        "</td></tr>"
      );
    })
    .join("");

  const key = process.env.RESEND_API_KEY;
  const to = process.env.LEAD_TO;
  if (!key || !to) {
    console.error("RESEND_API_KEY or LEAD_TO not set");
    return res.status(500).json({ error: "Not configured" });
  }
  const from = process.env.LEAD_FROM || "onboarding@resend.dev";

  const html =
    "<p><strong>" + esc(site) + "</strong> - " + esc(form) + "</p>" +
    "<table>" + rows + "</table>" +
    '<p style="color:#999;font-size:12px">' +
    new Date().toISOString() +
    "</p>";

  const headers = {
    Authorization: "Bearer " + key,
    "Content-Type": "application/json",
  };

  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers,
    body: JSON.stringify({
      from,
      to: [to],
      reply_to: email || undefined,
      subject: "[" + site + "] " + form + (email ? " - " + email : ""),
      html,
    }),
  });

  if (!r.ok) {
    console.error("Resend error", r.status, await r.text());
    return res.status(502).json({ error: "Email failed" });
  }

  // Optional: save as a Resend contact in a segment.
  const segment =
    process.env.RESEND_SEGMENT_ID || process.env.RESEND_AUDIENCE_ID;
  if (segment && email) {
    try {
      const c = await fetch("https://api.resend.com/contacts", {
        method: "POST",
        headers,
        body: JSON.stringify({
          email,
          unsubscribed: false,
          segments: [{ id: segment }],
        }),
      });
      if (!c.ok) {
        console.error("contact add failed", c.status, await c.text());
      }
    } catch (e) {
      console.error("contact add failed", e);
    }
  }

  return res.status(200).json({ ok: true });
};
