// POST /api/ai/screen
// Screens one company against chosen criteria, with or without live web search,
// saves the scores on the holding and logs alerts for new controversies.
// Body: { holdingId, criterionIds: [..], what: ["revenue","controversies"], web: true|false, context?: string }
import { post, userClient, anthropic, check, httpError, MODEL, MAX_SEARCHES } from "../../lib/server.mjs";
import { screenHolding } from "../../lib/screening.mjs";

export const config = { maxDuration: 60 };

export default post(async (req, body) => {
  const { sb, user } = await userClient(req);
  const { holdingId, criterionIds, what = ["revenue", "controversies"], web = false, context = "" } = body;
  if (!holdingId) throw httpError(400, "holdingId is required.");
  if (!Array.isArray(what) || !what.length) throw httpError(400, "Choose revenue, controversies or both.");

  const holding = check(await sb.from("holdings").select("*").eq("id", holdingId).maybeSingle());
  if (!holding) throw httpError(404, "That company is not in your universe.");

  let q = sb.from("criteria").select("*").eq("active", true);
  if (Array.isArray(criterionIds) && criterionIds.length) q = q.in("id", criterionIds);
  const criteria = check(await q);
  if (!criteria.length) throw httpError(400, "No active criteria selected.");

  const tag = holding.ticker || holding.name;
  const alerts = check(await sb.from("alerts").select("title,date,url").contains("tickers", [tag]).order("date", { ascending: false }).limit(20));
  const existingUrls = new Set(alerts.map((a) => a.url).filter(Boolean));

  const { result, scores, alerts: newAlerts, searches } = await screenHolding(anthropic(), {
    model: MODEL,
    holding,
    criteria,
    what,
    web: !!web,
    context,
    knownAlerts: alerts.slice(0, 8),
    existingUrls,
    maxUses: MAX_SEARCHES,
  });

  check(await sb.from("holdings").update({ scores, updated_at: new Date().toISOString() }).eq("id", holding.id));
  if (newAlerts.length) check(await sb.from("alerts").insert(newAlerts.map((a) => ({ ...a, user_id: user.id }))));

  return { result, scores, alertsAdded: newAlerts.length, searches };
});
