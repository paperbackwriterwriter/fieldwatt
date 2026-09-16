// Vercel serverless function: receives form submissions from the site and
// emails them to you through Resend. Works on the Vercel Hobby plan.
//
// Env vars to set in the Vercel project:
//   RESEND_API_KEY   - from resend.com
//   LEAD_TO          - where submissions go (your inbox)
//   LEAD_FROM        - optional; defaults to onboarding@resend.dev, which only
//                      delivers to the address that owns the Resend account.
//                      Once the site's domain is verified in Resend, set this
//                      to e.g. "Fieldwatt <hello@fieldwatt.com>".
//   RESEND_AUDIENCE_ID - optional; if set, email signups are also added as
//                      contacts to that Resend audience (for newsletters).

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
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body && typeof body === "object" ? body : {};

  // Honeypot: real users never fill this.
  if (body.website) return res.status(200).json({ ok: true });

  const email = String(body.email || "").trim();
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return res.status(400).json({ error: "Invalid email" });
  }

  const site = String(body.site || "Website").slice(0, 60);
  const form = String(body.form || "form").slice(0, 60);

  const rows = Object.entries(body)
    .filter(([k]) => !["site", "form", "website"].includes(k))
    .slice(0, ALLOWED_FIELDS)
    .map(([k, v]) => `<tr><td style="padding:4px 12px 4px 0;color:#666">${esc(k)}</td><td style="padding:4px 0">${esc(typeof v === "object" ? JSON.stringify(v) : v).slice(0, 4000)}</td></tr>`)
    .join("");

  const key = process.env.RESEND_API_KEY;
  const to = process.env.LEAD_TO;
  if (!key || !to) {
    console.error("RESEND_API_KEY or LEAD_TO not set");
    return res.status(500).json({ error: "Not configured" });
  }
  const from = process.env.LEAD_FROM || "onboarding@resend.dev";

  const html = `<p><strong>${esc(site)}</strong> — ${esc(form)}</p><table>${rows}</table><p style="color:#999;font-size:12px">${new Date().toISOString()}</p>`;

  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from,
      to: [to],
      reply_to: email || undefined,
      subject: `[${site}] ${form}${email ? " — " + email : ""}`,
      html,
    }),
  });

  if (!r.ok) {
    console.error("Resend error", r.status, await r.text());
    return res.status(502).json({ error: "Email failed" });
  }

  // Optional: add to a Resend audience for newsletters / alerts.
  const aud = process.env.RESEND_AUDIENCE_ID;
  if (aud && email) {
    try {
      await fetch(`https://api.resend.com/audiences/${aud}/contacts`, {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ email, unsubscribed: false }),
      });
    } catch (e) {
      console.error("audience add failed", e);
    }
  }

  return res.status(200).json({ ok: true });
};
