// Vercel serverless function: the link in a subscription confirmation email.
// Checks the signature api/lead.js put on the link, then adds the address to
// the mailing list and tells LEAD_TO about the new subscriber. Nothing reaches
// the list any other way.

const crypto = require("crypto");
const { signupSig } = require("./lead.js");

const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function fail(res) {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  return res
    .status(400)
    .send(
      '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>Link expired | FieldWatt</title>' +
        '<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.6">' +
        "<h1>That link didn't work.</h1>" +
        "<p>It may have expired or been copied incompletely. Sign up again and use the newest email.</p>" +
        '<p><a href="/alerts">Back to FieldWatt alerts</a></p>'
    );
}

module.exports = async (req, res) => {
  const q = req.query || {};
  const email = String(q.e || "").trim();
  const form = String(q.f || "");
  const role = String(q.r || "");
  const state = String(q.st || "");
  const ts = String(q.t || "");
  const sig = String(q.s || "");

  if (!email || !form || !/^\d+$/.test(ts) || !sig) return fail(res);
  if (Date.now() - Number(ts) > MAX_AGE_MS) return fail(res);

  const want = Buffer.from(signupSig([email.toLowerCase(), form, role, state, ts]));
  const got = Buffer.from(sig);
  if (want.length !== got.length || !crypto.timingSafeEqual(want, got)) {
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
          email,
          unsubscribed: false,
          segments: [{ id: segment }],
        }),
      });
      // Clicking twice lands here with the contact already present; that is
      // fine and still counts as confirmed.
      if (!c.ok) console.error("contact add failed", c.status, await c.text());
    } catch (e) {
      console.error("contact add failed", e);
    }
  }

  const to = process.env.LEAD_TO;
  if (key && to) {
    const detail = [role && "role " + role, state && "state " + state]
      .filter(Boolean)
      .join(", ");
    try {
      await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers,
        body: JSON.stringify({
          from: process.env.LEAD_FROM || "onboarding@resend.dev",
          to: [to],
          subject: "[FieldWatt] confirmed subscriber - " + email,
          text:
            email + " confirmed via " + form + (detail ? " (" + detail + ")" : "") +
            ".\n" + new Date().toISOString(),
        }),
      });
    } catch (e) {
      console.error("notify failed", e);
    }
  }

  res.setHeader("Location", "/confirmed");
  return res.status(302).end();
};
