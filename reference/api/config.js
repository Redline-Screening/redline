// Gives the browser the public Supabase settings (the anon key is meant to be public;
// row-level security in the database protects each user's data).
export default function handler(req, res) {
  const url = process.env.SUPABASE_URL;
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    res.status(500).json({ error: "SUPABASE_URL and SUPABASE_ANON_KEY are not set on the server." });
    return;
  }
  res.setHeader("Cache-Control", "no-store");
  res.status(200).json({ supabaseUrl: url, supabaseAnonKey: anonKey, monitorTime: process.env.MONITOR_TIME_LABEL || "every morning around 07:30 Zurich time" });
}
