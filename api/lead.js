// Vercel serverless function: receives form submissions from the site.
// Works on the Vercel Hobby plan.
//
// Two kinds of form come through here:
//
//   Subscriptions (tuesday-email, job-alert, guide-email) never go straight
//   onto the mailing list. The address gets a confirmation email with a signed
//   link, and only clicking it (api/confirm.js) adds the contact to the segment.
//   A bot has been submitting other people's real addresses, and it drives a
//   real browser that passes Turnstile, so the only proof that an address
//   wants the newsletter is its owner clicking the link.
//
//   Leads (hire-inquiry, training-partner, employer-claim) are emailed to
//   LEAD_TO as before, and are never added to the mailing list.
//
// Env vars to set in the Vercel project:
//   RESEND_API_KEY    - from resend.com (Full access)
//   LEAD_TO           - where submissions go (your inbox)
//   LEAD_FROM         - optional; defaults to onboarding@resend.dev, which
//                       only delivers to the address that owns the Resend
//                       account. Once the site's domain is verified in
//                       Resend, set this to e.g.
//                       "FieldWatt <hello@fieldwatt.com>".
//   RESEND_SEGMENT_ID - optional; the segment confirmed subscribers join.
//                       RESEND_AUDIENCE_ID is still accepted as a fallback.
//   TURNSTILE_SECRET_KEY - optional; when set, every submission must carry a
//                       valid Cloudflare Turnstile token or it is rejected.
//   SIGNUP_SECRET     - optional; signs confirmation links. Falls back to
//                       RESEND_API_KEY, which is already secret and server-only.
//   SITE_URL          - optional; base for confirmation links. Defaults to
//                       https://fieldwatt.com.

const crypto = require("crypto");

const ALLOWED_FIELDS = 40;
const SUBSCRIBE_FORMS = new Set(["tuesday-email", "job-alert", "guide-email"]);

// A person needs longer than this to read a form and fill it in. Client
// supplied and therefore forgeable, so it is a cheap extra filter rather than
// a control to rely on.
const MIN_FILL_MS = 3000;

// Fields a bot fills with generated text. The one hitting FieldWatt writes
// strings like "GelEXnymZqdGKwKGI": a single run of ten or more letters with
// capitals scattered through it. Real names have spaces or at most a couple
// of internal capitals (McKenzie, DeShawn).
const NAME_FIELDS = ["name", "contactName", "programName", "school", "company"];

function looksGenerated(v) {
  const s = String(v || "").trim().replace(/\s+LLC$/i, "");
  if (!/^[A-Za-z]{10,}$/.test(s)) return false;
  return (s.slice(1).match(/[A-Z]/g) || []).length >= 3;
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function signingKey() {
  return process.env.SIGNUP_SECRET || process.env.RESEND_API_KEY || "";
}

// The confirmation link carries everything api/confirm.js needs, signed so it
// cannot be forged or edited, which is what lets this work with no database.
function signupSig(parts) {
  return crypto
    .createHmac("sha256", signingKey())
    .update(parts.join("\n"))
    .digest("base64url");
}

async function turnstileOk(token, ip) {
  const secret = process.env.TURNSTILE_SECRET_KEY;
  if (!secret) return "not configured";
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
    return out.success === true ? "passed" : false;
  } catch (e) {
    // Cloudflare unreachable. Fail closed: a spam run is the likelier cause
    // of a flood of unverifiable submissions than an outage.
    console.error("turnstile verify failed", e);
    return false;
  }
}

async function sendEmail(headers, msg) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers,
    body: JSON.stringify(msg),
  });
  if (!r.ok) console.error("Resend error", r.status, await r.text());
  return r.ok;
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
  const verified = await turnstileOk(body.turnstileToken, ip);
  if (!verified) {
    return res.status(400).json({ error: "Verification failed" });
  }

  // Generated names. Answer 200 so the bot learns nothing about why.
  const generated = NAME_FIELDS.find((f) => looksGenerated(body[f]));
  if (generated) {
    console.warn("rejected: generated text in", generated);
    return res.status(200).json({ ok: true });
  }

  const email = String(body.email || body.workEmail || "").trim();
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return res.status(400).json({ error: "Invalid email" });
  }

  const site = String(body.site || "Website").slice(0, 60);
  const form = String(body.form || "form").slice(0, 60);

  const key = process.env.RESEND_API_KEY;
  const to = process.env.LEAD_TO;
  if (!key || !to) {
    console.error("RESEND_API_KEY or LEAD_TO not set");
    return res.status(500).json({ error: "Not configured" });
  }
  const from = process.env.LEAD_FROM || "onboarding@resend.dev";
  const headers = {
    Authorization: "Bearer " + key,
    "Content-Type": "application/json",
  };

  // Subscriptions: ask the address's owner, and tell no one else yet.
  if (SUBSCRIBE_FORMS.has(form)) {
    if (!email) return res.status(400).json({ error: "Email required" });
    const role = String(body.role || "").slice(0, 40);
    const state = String(body.state || "").slice(0, 40);
    const ts = String(Date.now());
    const sig = signupSig([email.toLowerCase(), form, role, state, ts]);
    const base = (process.env.SITE_URL || "https://fieldwatt.com").replace(/\/$/, "");
    const link =
      base +
      "/api/confirm?" +
      new URLSearchParams({ e: email, f: form, r: role, st: state, t: ts, s: sig });

    const html =
      "<p>Someone asked to get FieldWatt job emails at this address.</p>" +
      '<p><a href="' + esc(link) + '" style="display:inline-block;padding:10px 18px;background:#f5c518;color:#111;font-weight:bold;text-decoration:none">Confirm my subscription</a></p>' +
      "<p>If that wasn't you, ignore this email. Nothing happens unless you click, and you won't hear from us again.</p>" +
      '<p style="color:#999;font-size:12px">FieldWatt — renewable trades jobs · fieldwatt.com</p>';

    const ok = await sendEmail(headers, {
      from,
      to: [email],
      subject: "Confirm your FieldWatt job emails",
      html,
      text:
        "Someone asked to get FieldWatt job emails at this address.\n\n" +
        "Confirm: " + link + "\n\n" +
        "If that wasn't you, ignore this email. Nothing happens unless you click.",
    });
    if (!ok) return res.status(502).json({ error: "Email failed" });
    return res.status(200).json({ ok: true, confirm: true });
  }

  // Leads: forward to the inbox. Never added to the mailing list.
  const skip = [
    "site", "form", "website", "turnstileToken", "elapsedMs",
    "cf-turnstile-response",
  ];
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

  const html =
    "<p><strong>" + esc(site) + "</strong> - " + esc(form) + "</p>" +
    "<table>" + rows + "</table>" +
    '<p style="color:#999;font-size:12px">' +
    new Date().toISOString() +
    " · turnstile: " + esc(verified) +
    "</p>";

  const ok = await sendEmail(headers, {
    from,
    to: [to],
    reply_to: email || undefined,
    subject: "[" + site + "] " + form + (email ? " - " + email : ""),
    html,
  });
  if (!ok) return res.status(502).json({ error: "Email failed" });

  return res.status(200).json({ ok: true });
};

module.exports.signupSig = signupSig;
module.exports.looksGenerated = looksGenerated;
