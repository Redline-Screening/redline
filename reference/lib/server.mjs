// Helpers for the API routes: auth, Supabase client, Anthropic client, error handling.
import { createClient } from "@supabase/supabase-js";
import Anthropic from "@anthropic-ai/sdk";

export const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-5-5";
export const FAST_MODEL = process.env.ANTHROPIC_FAST_MODEL || "claude-haiku-5-5";
export const MAX_SEARCHES = Number(process.env.MAX_SEARCHES_PER_CHECK || 4);

export function httpError(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}

function need(name) {
  const v = process.env[name];
  if (!v) throw httpError(500, `The server is missing the ${name} setting. Add it in Vercel → Settings → Environment Variables and redeploy.`);
  return v;
}

/** Supabase client acting as the signed-in user (row-level security applies). */
export async function userClient(req) {
  const token = String(req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  if (!token) throw httpError(401, "Sign in first.");
  const sb = createClient(need("SUPABASE_URL"), need("SUPABASE_ANON_KEY"), {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await sb.auth.getUser(token);
  if (error || !data || !data.user) throw httpError(401, "Your session has expired. Sign in again.");
  return { sb, user: data.user };
}

export function anthropic() {
  return new Anthropic({ apiKey: need("ANTHROPIC_API_KEY") });
}

/** Wrap a POST handler with JSON parsing and readable errors. */
export function post(fn) {
  return async function handler(req, res) {
    if (req.method !== "POST") {
      res.status(405).json({ error: "Use POST." });
      return;
    }
    try {
      let body = req.body;
      if (typeof body === "string") body = body ? JSON.parse(body) : {};
      const out = await fn(req, body || {});
      res.status(200).json(out);
    } catch (e) {
      const status = e.status && e.status >= 400 && e.status < 600 ? e.status : 500;
      let message = e.message || "Something went wrong.";
      if (e.error && e.error.error && e.error.error.message) message = "Claude API: " + e.error.error.message;
      if (status === 429) message = "The AI is busy (rate limit). Wait a minute and try again.";
      console.error(e);
      res.status(status).json({ error: message });
    }
  };
}

/** Throw on a Supabase error, return data otherwise. */
export function check(r) {
  if (r.error) throw httpError(400, "Database: " + r.error.message);
  return r.data;
}
