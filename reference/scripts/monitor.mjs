// Daily monitoring job.
// For every user who switched daily monitoring on, searches the web for new controversies
// linked to their chosen issuers and criteria, updates scores and adds alerts.
// Runs from GitHub Actions (.github/workflows/daily-monitoring.yml) or by hand: npm run monitor
//
// Needs: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY
// Optional: ANTHROPIC_MODEL, MAX_CHECKS_PER_RUN (default 60), MAX_SEARCHES_PER_CHECK (default 3)
import { createClient } from "@supabase/supabase-js";
import Anthropic from "@anthropic-ai/sdk";
import { screenHolding, today } from "../lib/screening.mjs";

const need = (n) => {
  const v = process.env[n];
  if (!v) { console.error(`Missing ${n}`); process.exit(1); }
  return v;
};
const sb = createClient(need("SUPABASE_URL"), need("SUPABASE_SERVICE_ROLE_KEY"), { auth: { persistSession: false } });
const claude = new Anthropic({ apiKey: need("ANTHROPIC_API_KEY") });
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-5-5";
const MAX_CHECKS = Number(process.env.MAX_CHECKS_PER_RUN || 60);
const MAX_SEARCHES = Number(process.env.MAX_SEARCHES_PER_CHECK || 3);
const WHAT = ["controversies", "revenue"];

const check = (r, what) => { if (r.error) throw new Error(`${what}: ${r.error.message}`); return r.data; };

async function main() {
  const date = today();
  const workspaces = check(await sb.from("workspaces").select("*"), "workspaces")
    .filter((w) => w.monitor && w.monitor.enabled && w.monitor.lastRun !== date);
  console.log(`${workspaces.length} workspace(s) with daily monitoring due.`);
  let checks = 0;

  for (const ws of workspaces) {
    const uid = ws.user_id;
    const mon = ws.monitor;
    const criteria = check(await sb.from("criteria").select("*").eq("user_id", uid).eq("active", true), "criteria")
      .filter((c) => !mon.criteria || !mon.criteria.length || mon.criteria.includes(c.id));
    let holdings = check(await sb.from("holdings").select("*").eq("user_id", uid), "holdings");
    if (Array.isArray(mon.issuers)) holdings = holdings.filter((h) => mon.issuers.includes(h.id));
    holdings.sort((a, b) => (b.weight || 0) - (a.weight || 0));
    const existing = check(await sb.from("alerts").select("url").eq("user_id", uid), "alerts");
    const existingUrls = new Set(existing.map((a) => a.url).filter(Boolean));
    const since = mon.lastRun || new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);

    let screened = 0, added = 0, failed = 0, skipped = 0;
    for (const h of holdings) {
      let holding = h;
      for (const c of criteria) {
        if (checks >= MAX_CHECKS) { skipped++; continue; }
        checks++;
        try {
          const { scores, alerts } = await screenHolding(claude, {
            model: MODEL, holding, criteria: [c], what: WHAT, web: true, since, existingUrls, maxUses: MAX_SEARCHES,
          });
          check(await sb.from("holdings").update({ scores, updated_at: new Date().toISOString() }).eq("id", holding.id), "update holding");
          holding = { ...holding, scores };
          if (alerts.length) {
            check(await sb.from("alerts").insert(alerts.map((a) => ({ ...a, user_id: uid }))), "insert alerts");
            added += alerts.length;
          }
          screened++;
        } catch (e) {
          failed++;
          console.error(`  ${h.name} / ${c.label}: ${e.message}`);
        }
      }
    }
    const note = `Checked ${screened} company-criterion pairs since ${since}, ${added} new alert(s)${failed ? `, ${failed} failed` : ""}${skipped ? `, ${skipped} skipped (run limit reached)` : ""}.`;
    check(await sb.from("workspaces").update({ monitor: { ...mon, lastRun: date, lastNote: note } }).eq("user_id", uid), "update workspace");
    console.log(`Workspace ${uid.slice(0, 8)}…: ${note}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
