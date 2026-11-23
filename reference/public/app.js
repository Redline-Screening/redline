// Redline front end: plain JavaScript, no build step.
// Data lives in Supabase (each user sees only their own rows); AI runs through /api/ai/* on the server.
import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.2/+esm";

/* ---------- state ---------- */
const S = {
  sb: null, user: null, cfg: {}, ws: null, holdings: [], criteria: [], alerts: [], loaded: false,
  view: "overview", crit: null, critPinned: false, sel: null, scope: "held", usort: { k: "weight", d: -1 }, afilter: "open",
  panel: null, prov: null, drafts: {}, busy: {}, res: {}, err: {}, confirmDel: null, editing: null, authMode: "signin", run: null,
};
const VIEWS = [["overview", "Overview", ""], ["universe", "Fund universe", "1"], ["policy", "Screening criteria", "2"], ["sources", "Data sources", "3"], ["agent", "Screening", ""], ["risk", "Risk assessment", ""], ["alerts", "Alerts", ""]];
const AIV = { agent: 1 };

/* ---------- helpers ---------- */
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => { if (v == null || v === "") return null; const n = parseFloat(String(v).replace(/[%,\s]/g, "")); return Number.isFinite(n) ? n : null; };
const fmt = (v, d = 1) => (v == null || !Number.isFinite(Number(v)) ? "–" : Number(v).toFixed(d));
const pct = (v, d = 1) => (v == null ? "–" : fmt(v, d) + "%");
const signed = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + fmt(v, 1) + "%");
const slug = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
const today = () => new Date().toISOString().slice(0, 10);
const draft = (id, def = "") => (S.drafts[id] != null ? S.drafts[id] : def);
const safeUrl = (u) => /^https?:\/\//i.test(String(u || ""));
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3600); }
const held = () => S.holdings.filter((h) => h.type !== "prospect");
const prospects = () => S.holdings.filter((h) => h.type === "prospect");
const active = () => S.criteria.filter((c) => c.active !== false).sort((a, b) => (a.order || 0) - (b.order || 0));
const critById = (id) => S.criteria.find((c) => c.id === id);
const findH = (key) => { if (!key) return null; const k = String(key).toLowerCase(); return S.holdings.find((h) => h.id === key || String(h.ticker || "").toLowerCase() === k || String(h.isin || "").toLowerCase() === k); };
const findByName = (n) => {
  if (!n) return null;
  const k = String(n).toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
  return S.holdings.find((h) => { const m = String(h.name || "").toLowerCase().replace(/[^a-z0-9 ]/g, "").trim(); return m && (m === k || (m.split(" ")[0] === k.split(" ")[0] && m.split(" ")[0].length > 3)); });
};
const mode = () => (S.ws && S.ws.mode) || null;
const useProv = () => mode() === "provider" || mode() === "both";

/* ---------- status logic ---------- */
const LVL = ["none", "low", "medium", "high", "severe"];
const CRANK = { none: 0, low: 1, medium: 2, high: 3, severe: 4 };
function evalC(h, c) {
  const sc = (h.scores || {})[c.id];
  if (!sc || (sc.exposure == null && !sc.controversy)) return { state: "na", sc: null };
  const thr = c.threshold == null ? 0 : c.threshold, w = c.watchAt == null ? 50 : c.watchAt;
  const cl = CRANK[(sc.controversy || {}).level] || 0, lim = CRANK[c.controversyLimit || "high"] || 3;
  const revB = sc.exposure != null && sc.exposure > thr, conB = cl >= lim;
  if (revB || conB) return { state: "breach", sc, why: revB && conB ? "both" : revB ? "revenue" : "controversy" };
  if (cl >= 2 || (sc.likelihood != null && sc.likelihood >= w)) return { state: "watch", sc, why: cl >= 2 ? "controversy" : "likelihood" };
  return { state: "clear", sc };
}
const RANK = { breach: 3, watch: 2, clear: 1, na: 0 };
function evalH(h) {
  let worst = "na", hits = [];
  active().forEach((c) => { const r = evalC(h, c); if (RANK[r.state] > RANK[worst]) worst = r.state; if (r.state === "breach" || r.state === "watch") hits.push({ c, ...r }); });
  hits.sort((a, b) => RANK[b.state] - RANK[a.state]);
  return { state: worst, hits };
}
const STATE_LABEL = { breach: "Breach", watch: "Watch", clear: "Clear", na: "Not screened" };
const pill = (s) => `<span class="pill ${s}">${STATE_LABEL[s] || esc(s)}</span>`;
const sevPill = (s) => `<span class="pill ${esc(s)}">${esc(s ? s[0].toUpperCase() + s.slice(1) : "")}</span>`;
const lvlPill = (l) => { const cls = l === "severe" || l === "high" ? "breach" : l === "medium" ? "watch" : l === "low" ? "na" : "clear"; return `<span class="pill ${cls}">${l ? esc(l[0].toUpperCase() + l.slice(1)) : "–"}</span>`; };
const likeWord = (l) => (l == null ? "–" : l >= 70 ? "High" : l >= 40 ? "Medium" : "Low");
const alertsFor = (h) => { const t = String(h.ticker || h.name).toUpperCase(); return S.alerts.filter((a) => (a.tickers || []).map((x) => String(x).toUpperCase()).includes(t)); };

/* ---------- data mapping ---------- */
const mapC = (r) => ({ id: r.id, key: r.key, label: r.label, description: r.description, threshold: num(r.threshold) ?? 0, watchAt: num(r.watch_at) ?? 50, controversyLimit: r.controversy_limit || "high", keywords: r.keywords || [], active: r.active, order: r.sort });
const toDbC = (c) => { const o = {}; if ("key" in c) o.key = c.key; if ("label" in c) o.label = c.label; if ("description" in c) o.description = c.description; if ("threshold" in c) o.threshold = c.threshold; if ("watchAt" in c) o.watch_at = c.watchAt; if ("controversyLimit" in c) o.controversy_limit = c.controversyLimit; if ("keywords" in c) o.keywords = c.keywords; if ("active" in c) o.active = c.active; if ("order" in c) o.sort = c.order; return o; };
const mapH = (r) => ({ id: r.id, name: r.name, ticker: r.ticker || "", isin: r.isin || "", weight: num(r.weight), ytd: num(r.ytd), r1y: num(r.r1y), country: r.country, sector: r.sector, type: r.type, scores: r.scores || {} });
const mapA = (r) => ({ ...r });
const chk = (r) => { if (r.error) throw r.error; return r.data; };

async function loadAll() {
  const uid = S.user.id;
  const [w, h, c, a] = await Promise.all([
    S.sb.from("workspaces").select("*").eq("user_id", uid).maybeSingle(),
    S.sb.from("holdings").select("*").order("weight", { ascending: false }),
    S.sb.from("criteria").select("*").order("sort"),
    S.sb.from("alerts").select("*").order("date", { ascending: false }).limit(300),
  ]);
  let ws = chk(w);
  if (!ws) { chk(await S.sb.from("workspaces").insert({ user_id: uid })); ws = { monitor: { enabled: false, issuers: "all", criteria: [] }, providers: {} }; }
  S.ws = ws;
  S.holdings = chk(h).map(mapH);
  S.criteria = chk(c).map(mapC);
  S.alerts = chk(a).map(mapA);
  if (!S.crit || !critById(S.crit)) S.crit = (active()[0] || {}).id || null;
  S.loaded = true;
  render();
}
const DB = {
  async ws(fields) { chk(await S.sb.from("workspaces").update(fields).eq("user_id", S.user.id)); },
  async addH(obj) { const r = chk(await S.sb.from("holdings").insert(obj).select().single()); return mapH(r); },
  async updH(id, fields) { chk(await S.sb.from("holdings").update({ ...fields, updated_at: new Date().toISOString() }).eq("id", id)); },
  async delH(id) { chk(await S.sb.from("holdings").delete().eq("id", id)); },
  async addC(c) { chk(await S.sb.from("criteria").insert(toDbC(c))); },
  async updC(id, c) { chk(await S.sb.from("criteria").update(toDbC(c)).eq("id", id)); },
  async delC(id) { chk(await S.sb.from("criteria").delete().eq("id", id)); },
  async addA(rows) { chk(await S.sb.from("alerts").insert(rows)); },
  async updA(id, fields) { chk(await S.sb.from("alerts").update(fields).eq("id", id)); },
};
const writeErr = (e) => { console.error(e); toast("Could not save: " + ((e && e.message) || "check your connection and try again.")); };
async function saveScores(h, updates) { const scores = JSON.parse(JSON.stringify(h.scores || {})); Object.keys(updates).forEach((k) => (scores[k] = updates[k])); await DB.updH(h.id, { scores }); }

/* ---------- AI (server) ---------- */
async function api(path, body) {
  const { data } = await S.sb.auth.getSession();
  const token = data && data.session && data.session.access_token;
  const r = await fetch("/api/ai/" + path, { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + token }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || (r.status === 504 ? "The request took too long. Try fewer companies or criteria at once." : "Request failed (" + r.status + ")."));
  return j;
}
const aiErr = (e) => (e && e.message) || "The request did not complete. Try again.";

/* ---------- render ---------- */
function stepState() { const s1 = S.holdings.length > 0, s2 = active().length > 0, s3 = !!mode(); return { s1, s2, s3, cur: !s1 ? 1 : !s2 ? 2 : !s3 ? 3 : 0, done: s1 && s2 && s3 }; }
function render() {
  if (!S.user) return renderAuth();
  $("#auth").hidden = true; $("#app").hidden = false; $("#boot").hidden = true;
  const st = stepState();
  const openA = S.alerts.filter((a) => a.status === "new").length;
  $("#nav").innerHTML = VIEWS.map(([k, l, n]) => { const done = n && st["s" + n]; return `<button data-act="go" data-v="${k}" ${S.view === k ? 'aria-current="page"' : ""}><span>${n ? `<span class="mono muted">${done ? "✓" : n}</span> ` : ""}${l}</span>${AIV[k] ? '<span class="ai">AI</span>' : ""}${k === "alerts" && openA ? `<span class="count">${openA}</span>` : ""}</button>`; }).join("");
  const w = S.ws || {};
  $("#fundcard").innerHTML = `<span class="label">Your workspace</span><b>${esc(w.name || "Untitled fund")}</b><span class="muted">${S.holdings.length} companies · ${active().length} criteria</span><span class="muted">${mode() === "provider" ? "Screening with data provider" : mode() === "ai" ? "Screening with AI" : mode() === "both" ? "Provider data + AI" : "Screening method not set"}</span><span class="private">${esc(S.user.email || "")}</span><button class="linkbtn" data-act="signOut">Sign out</button>`;
  const m = $("#main");
  if (!S.loaded) { m.innerHTML = `<div class="wrap"><div class="empty"><h2>Loading your workspace</h2></div></div>`; return; }
  const fn = { overview: vOverview, universe: vUniverse, risk: vRisk, alerts: vAlerts, policy: vPolicy, agent: vAgent, sources: vSources }[S.view];
  m.innerHTML = `<div class="wrap">${fn()}</div>`;
}
function renderAuth() {
  $("#app").hidden = true; $("#boot").hidden = true; $("#auth").hidden = false;
  const up = S.authMode === "signup";
  $("#auth").innerHTML = `<form class="auth-card" id="authform">
    <div class="brand"><div class="brand-mark" aria-hidden="true"></div><div><b>Redline</b><small>Exclusion breach monitor</small></div></div>
    <h1>${up ? "Create your account" : "Sign in"}</h1>
    <p class="hint">Check whether your investments breach your exclusion policy. Your fund universe and criteria are private to your account.</p>
    <div class="field"><label for="au-email">Email</label><input id="au-email" type="text" autocomplete="email" data-draft="au-email" value="${esc(draft("au-email"))}"></div>
    <div class="field"><label for="au-pw">Password</label><input id="au-pw" type="password" autocomplete="${up ? "new-password" : "current-password"}" data-draft="au-pw" value="${esc(draft("au-pw"))}"></div>
    ${S.err.auth ? `<p class="err">${esc(S.err.auth)}</p>` : ""}${S.res.authNote ? `<p class="note">${esc(S.res.authNote)}</p>` : ""}
    <button class="btn primary" type="submit" ${S.busy.auth ? "disabled" : ""}>${S.busy.auth ? "Please wait…" : up ? "Create account" : "Sign in"}</button>
    <p class="hint">${up ? "Already have an account?" : "New to Redline?"} <button class="linkbtn" type="button" data-act="authMode">${up ? "Sign in" : "Create an account"}</button></p>
  </form>`;
}
function gateEmpty(title, body, btn, v) { return `<div class="empty"><h2>${title}</h2><p>${body}</p>${btn ? `<button class="btn primary" data-act="go" data-v="${v}">${btn}</button>` : ""}</div>`; }

/* Overview */
function setupSteps(st) {
  const step = (n, done, title, body, btn, v) => `<div class="step ${done ? "done" : st.cur === n ? "current" : ""}"><span class="n">${done ? "✓" : n}</span><div><h3>${title}</h3><p>${body}</p></div><button class="btn ${st.cur === n ? "primary" : ""}" data-act="go" data-v="${v}">${btn}</button></div>`;
  return `<div class="setup">
  ${step(1, st.s1, "Add your fund universe", st.s1 ? `${held().length} holdings and ${prospects().length} prospects loaded.` : "Upload a CSV from your portfolio system, paste a list in any format, or add companies one by one.", st.s1 ? "Edit" : "Add universe", "universe")}
  ${step(2, st.s2, "Set your screening criteria", st.s2 ? `${active().length} exclusion criteria active: ${esc(active().map((c) => c.label).join(", "))}.` : "Describe what the fund must not hold in your own words, or pick from common exclusions such as weapons, coal or tobacco.", st.s2 ? "Edit" : "Set criteria", "policy")}
  ${step(3, st.s3, "Choose how to screen", st.s3 ? (mode() === "provider" ? "Using data from your ESG data provider." : mode() === "ai" ? "The AI screens your universe for you." : "Provider data where available, AI for the gaps.") : "Load data from a provider such as ISS STOXX or MSCI if you have a licence, or let the AI do the screening.", st.s3 ? "Change" : "Choose", "sources")}
  </div>`;
}
function vOverview() {
  const st = stepState(), w = S.ws || {}, H = held(), A = active();
  if (!st.done) {
    return `<div class="head"><div><span class="label">Welcome to Redline</span><h1>Check whether your investments breach your exclusion policy</h1><p>Set up your workspace in three steps. Redline then screens every company against your criteria for revenue exposure and controversies, and alerts you when a company moves closer to a breach.</p></div></div>
    <section class="panel"><div class="panel-h"><h2>Name your fund or portfolio</h2><span class="private">Only you can see this workspace</span></div>
      <div class="row"><div class="field"><label for="ws-name">Fund or portfolio name</label><input id="ws-name" type="text" data-draft="ws-name" value="${esc(draft("ws-name", w.name || ""))}" placeholder="e.g. Global Technology Fund"></div><button class="btn" data-act="saveName">Save name</button></div>
    </section>${setupSteps(st)}`;
  }
  const ev = H.map((h) => ({ h, e: evalH(h) }));
  const wsum = (s) => ev.filter((x) => x.e.state === s).reduce((a, x) => a + (x.h.weight || 0), 0);
  const screened = ev.filter((x) => x.e.state !== "na").length;
  const openA = S.alerts.filter((a) => a.status === "new" || a.status === "escalated");
  const flagged = ev.filter((x) => x.e.state === "breach" || x.e.state === "watch").sort((a, b) => RANK[b.e.state] - RANK[a.e.state] || (b.h.weight || 0) - (a.h.weight || 0));
  return `<div class="head"><div><span class="label">${esc(w.name || "Your fund")}</span><h1>Exclusion breach overview</h1><p>${A.length} active exclusion criteria applied to ${H.length} holdings. A holding is in breach when its revenue share in an excluded activity is above your limit or it has a serious controversy linked to a criterion, and on watch when a moderate controversy appears or exposure is likely to rise.</p></div>
  <div class="toolbar"><button class="btn primary" data-act="go" data-v="agent">Run a screening</button></div></div>
  <div class="kpis">
    <div class="kpi breach"><span class="label">In breach</span><span class="v">${pct(wsum("breach"))}</span><span class="s">of fund weight, ${ev.filter((x) => x.e.state === "breach").length} holdings</span></div>
    <div class="kpi watch"><span class="label">On watch</span><span class="v">${pct(wsum("watch"))}</span><span class="s">of fund weight, ${ev.filter((x) => x.e.state === "watch").length} holdings</span></div>
    <div class="kpi"><span class="label">Open alerts</span><span class="v">${openA.length}</span><span class="s">${openA.filter((a) => a.severity === "high").length} high severity</span></div>
    <div class="kpi"><span class="label">Screened</span><span class="v">${screened}/${H.length}</span><span class="s">holdings with a score</span></div>
  </div>
  ${screened === 0 ? `<div class="empty"><h2>Your universe has not been screened yet</h2><p>Screen your holdings for revenue exposure and controversies${useProv() ? ", or load your data provider's export" : ""}.</p><div class="toolbar"><button class="btn primary" data-act="go" data-v="agent">Run a screening</button>${useProv() ? `<button class="btn" data-act="go" data-v="sources">Load provider data</button>` : ""}</div></div>` : `
  <div class="split">
    <section class="panel"><div class="panel-h"><h2>Breaches and watch list</h2><span class="hint">Click a company for its assessment</span></div>
      ${flagged.length ? `<div class="tbl-wrap"><table><thead><tr><th>Company</th><th class="r">Weight</th><th>Criterion</th><th class="r">Revenue / limit</th><th>Status</th></tr></thead><tbody>
      ${flagged.map(({ h, e }) => { const t = e.hits[0]; return `<tr class="click" data-act="openH" data-id="${esc(h.id)}"><td class="co"><b>${esc(h.name)}</b><span>${esc(h.ticker || "")}</span></td><td class="r num">${pct(h.weight)}</td><td>${esc(t.c.label)}${e.hits.length > 1 ? ` <span class="muted">+${e.hits.length - 1}</span>` : ""}${t.sc.controversy && CRANK[t.sc.controversy.level] >= 2 ? `<br><span class="hint">${esc(t.sc.controversy.level)} controversy</span>` : ""}</td><td class="r num">${pct(t.sc.exposure)} / ${pct(t.c.threshold || 0, 0)}</td><td>${pill(e.state)}</td></tr>`; }).join("")}
      </tbody></table></div>` : `<p class="muted">No holding is in breach or on watch under your current criteria.</p>`}
    </section>
    <section class="panel"><div class="panel-h"><h2>Latest alerts</h2><button class="btn ghost" data-act="go" data-v="alerts">All alerts</button></div>
      <div class="list">${S.alerts.slice(0, 4).map(alertCard).join("") || '<p class="muted">No alerts yet. Run a web screening or check a news item under Alerts.</p>'}</div>
    </section>
  </div>
  <section class="panel"><div class="panel-h"><h2>Fund weight in breach by criterion</h2><span class="hint">Share of fund weight in breach for each criterion</span></div>
    <div class="tbl-wrap"><table><thead><tr><th>Criterion</th><th class="r">Limit</th><th style="width:40%">Weight in breach</th><th class="r">Holdings</th><th class="r">Not screened</th></tr></thead><tbody>
    ${A.map((c) => { const r = H.map((h) => ({ h, r: evalC(h, c) })); const bw = r.filter((x) => x.r.state === "breach").reduce((s, x) => s + (x.h.weight || 0), 0); const n = r.filter((x) => x.r.state === "breach").length; const na = r.filter((x) => x.r.state === "na").length;
      return `<tr class="click" data-act="goCrit" data-c="${esc(c.id)}"><td><b>${esc(c.label)}</b></td><td class="r num">${pct(c.threshold || 0, 0)}</td><td><div class="expcell"><span class="num">${pct(bw)}</span><div class="bar ${bw > 0 ? "breach" : "clear"}"><i style="width:${Math.min(100, bw)}%"></i></div></div></td><td class="r num">${n}</td><td class="r num">${na}</td></tr>`; }).join("")}
    </tbody></table></div>
  </section>`}`;
}
function nextStep(n) { const st = stepState(); if (st.done || st.cur <= n) return ""; const v = { 2: "policy", 3: "sources" }[st.cur]; const l = { 2: "Next: set screening criteria", 3: "Next: choose how to screen" }[st.cur]; return `<div class="toolbar"><button class="btn primary" data-act="go" data-v="${v}">${l} →</button></div>`; }

/* Universe */
function vUniverse() {
  const list = S.scope === "held" ? held() : prospects();
  const c = critById(S.crit) || active()[0];
  const rows = list.map((h) => ({ h, e: evalH(h), r: c ? evalC(h, c) : { state: "na", sc: null } }));
  const k = S.usort.k, d = S.usort.d;
  const val = (x) => k === "name" ? String(x.h.name || "").toLowerCase() : k === "exp" ? (x.r.sc && x.r.sc.exposure != null ? x.r.sc.exposure : -1) : k === "con" ? (x.r.sc && x.r.sc.controversy ? CRANK[x.r.sc.controversy.level] || 0 : -1) : k === "status" ? RANK[x.e.state] : x.h[k] == null ? -1e9 : x.h[k];
  rows.sort((a, b) => { const A = val(a), B = val(b); return (A > B ? 1 : A < B ? -1 : 0) * d; });
  const th = (key, lab, cls = "") => `<th class="${cls}"><button data-act="sort" data-k="${key}">${lab}${S.usort.k === key ? (S.usort.d > 0 ? " ↑" : " ↓") : ""}</button></th>`;
  const totW = held().reduce((s, h) => s + (h.weight || 0), 0);
  const empty = !S.holdings.length;
  const panel = empty && !S.panel ? "import" : S.panel;
  return `<div class="head"><div><span class="label">Step 1</span><h1>Fund universe</h1><p>${empty ? "Add the companies you hold, and any you are thinking of buying. Upload a CSV, paste a list in any format, or add them one by one." : `${held().length} holdings (${pct(totW)} of weight) and ${prospects().length} prospects. Prospects are companies you are considering; screen them before you buy.`}</p></div>
  ${empty ? "" : `<div class="toolbar"><div class="seg"><button data-act="scope" data-s="held" aria-pressed="${S.scope === "held"}">Holdings</button><button data-act="scope" data-s="prospect" aria-pressed="${S.scope === "prospect"}">Prospects</button></div>
  <button class="btn" data-act="panel" data-p="import">Upload CSV</button><button class="btn" data-act="panel" data-p="paste">Paste a list</button><button class="btn" data-act="panel" data-p="add">Add company</button></div>`}</div>
  ${empty ? `<div class="toolbar"><div class="seg"><button data-act="panel" data-p="import" aria-pressed="${panel === "import"}">Upload CSV</button><button data-act="panel" data-p="paste" aria-pressed="${panel === "paste"}">Paste a list (AI)</button><button data-act="panel" data-p="add" aria-pressed="${panel === "add"}">Add one by one</button></div></div>` : ""}
  ${panel === "import" ? importPanel(empty) : ""}${panel === "paste" ? pastePanel(empty) : ""}${panel === "add" ? addPanel(empty) : ""}
  ${empty ? "" : `
  ${c ? `<div class="toolbar"><span class="label">Show exposure for</span>${active().map((x) => `<button class="chipbtn" data-act="setCrit" data-c="${esc(x.id)}" aria-pressed="${c.id === x.id}">${esc(x.label)}</button>`).join("")}</div>` : ""}
  <div class="tbl-wrap"><table><thead><tr>${th("name", "Company")}<th>ISIN</th>${th("weight", "Weight", "r")}${th("ytd", "YTD", "r")}${th("r1y", "1Y", "r")}${th("exp", "Revenue exposure")}${th("con", "Controversy")}${th("status", "Status")}</tr></thead><tbody>
  ${rows.map(({ h, e, r }) => { const thr = c ? c.threshold || 0 : 0; const sc = r.sc; const wp = sc && sc.exposure != null ? Math.min(100, (sc.exposure / Math.max(thr, 10, sc.exposure)) * 100) : 0;
    return `<tr class="click" data-act="openH" data-id="${esc(h.id)}"><td class="co"><b>${esc(h.name)}</b><span>${esc(h.ticker || "")}${h.country ? " · " + esc(h.country) : ""}</span></td><td class="mono">${esc(h.isin || "")}</td><td class="r num">${h.type === "prospect" ? "–" : pct(h.weight, 2)}</td><td class="r num ${h.ytd > 0 ? "pos" : h.ytd < 0 ? "neg" : ""}">${signed(h.ytd)}</td><td class="r num ${h.r1y > 0 ? "pos" : h.r1y < 0 ? "neg" : ""}">${signed(h.r1y)}</td>
    <td>${sc && sc.exposure != null ? `<div class="expcell"><span class="num">${pct(sc.exposure)}</span><div class="bar ${r.why === "revenue" || r.why === "both" ? "breach" : r.state === "watch" ? "watch" : "clear"}"><i style="width:${Math.max(sc.exposure > 0 ? 3 : 0, wp)}%"></i></div></div>` : '<span class="muted">–</span>'}</td>
    <td>${sc && sc.controversy ? lvlPill(sc.controversy.level) : "–"}</td><td>${pill(e.state)}</td></tr>`; }).join("") || `<tr><td colspan="8" class="muted">No ${S.scope === "held" ? "holdings" : "prospects"} yet.</td></tr>`}
  </tbody></table></div>
  ${nextStep(1)}`}`;
}
const closeBtn = (empty) => (empty ? "" : '<button class="btn ghost" data-act="panel" data-p="">Close</button>');
function importPanel(empty) {
  return `<section class="panel"><div class="panel-h"><h2>Upload a CSV</h2>${closeBtn(empty)}</div>
  <p class="hint">Export positions from your portfolio or broker system. Columns are matched by name: name, ticker, isin, weight, ytd, 1y, country, sector, type (holding or prospect). Only name is required. Companies already in your universe are updated by ticker or ISIN.</p>
  <textarea id="imp-csv" class="mono" data-draft="imp-csv" placeholder="name,ticker,isin,weight&#10;Logitech International,LOGN,CH0025751329,2.0&#10;Nestlé,NESN,CH0038863350,4.5">${esc(draft("imp-csv"))}</textarea>
  <div class="toolbar"><input id="imp-file" type="file" accept=".csv,text/csv,text/plain" data-chg="impfile"><button class="btn primary" data-act="importCsv">Import</button></div></section>`;
}
function pastePanel(empty) {
  const r = S.res.parse;
  return `<section class="panel ai"><div class="panel-h"><h2>Paste a list in any format</h2>${closeBtn(empty)}</div>
  <p class="hint">Paste from a broker statement, a factsheet, an email or a spreadsheet. The AI picks out the companies, tickers, ISINs and weights. You check the list before anything is added.</p>
  <textarea id="paste-txt" data-draft="paste-txt" placeholder="e.g. 12% Microsoft, 8% Nestle, 5.5% ASML Holding NV (NL0010273215), Roche 4%…">${esc(draft("paste-txt"))}</textarea>
  <div class="toolbar"><button class="btn primary" data-act="parseList" ${S.busy.parse ? "disabled" : ""}>${S.busy.parse ? "Reading…" : "Read list"}</button></div>
  ${S.busy.parse ? '<div class="thinking">Claude is reading your list…</div>' : ""}${S.err.parse ? `<p class="err">${esc(S.err.parse)}</p>` : ""}
  ${r ? `<div class="tbl-wrap"><table><thead><tr><th>Company</th><th>Ticker</th><th>ISIN</th><th class="r">Weight</th></tr></thead><tbody>${r.map((x) => `<tr><td>${esc(x.name)}</td><td class="mono">${esc(x.ticker || "")}</td><td class="mono">${esc(x.isin || "")}</td><td class="r num">${x.weight == null ? "–" : pct(x.weight, 2)}</td></tr>`).join("")}</tbody></table></div>
  <p class="note">Tickers and ISINs the AI was not sure about are left blank. Check identifiers against your records.</p>
  <div class="toolbar"><button class="btn primary" data-act="addParsed">Add ${r.length} companies</button><button class="btn ghost" data-act="clearParsed">Discard</button></div>` : ""}</section>`;
}
function addPanel(empty) {
  return `<section class="panel"><div class="panel-h"><h2>Add a company</h2>${closeBtn(empty)}</div>
  <div class="row"><div class="field"><label for="ad-name">Company name</label><input id="ad-name" type="text" data-draft="ad-name" value="${esc(draft("ad-name"))}"></div><div class="field"><label for="ad-ticker">Ticker</label><input id="ad-ticker" type="text" data-draft="ad-ticker" value="${esc(draft("ad-ticker"))}"></div><div class="field"><label for="ad-isin">ISIN</label><input id="ad-isin" type="text" data-draft="ad-isin" value="${esc(draft("ad-isin"))}"></div></div>
  <div class="row"><div class="field"><label for="ad-weight">Weight %</label><input id="ad-weight" type="number" step="0.01" data-draft="ad-weight" value="${esc(draft("ad-weight"))}"></div><div class="field"><label for="ad-type">Type</label><select id="ad-type" data-draft="ad-type"><option value="holding">Holding</option><option value="prospect" ${draft("ad-type") === "prospect" ? "selected" : ""}>Prospect</option></select></div><button class="btn primary" data-act="addCo">Add</button></div></section>`;
}

/* Risk */
function vRisk() {
  const A = active(); const c = critById(S.crit) || A[0];
  if (!S.holdings.length || !c) return `<div class="head"><div><span class="label">Risk assessment</span><h1>Risk assessment</h1></div></div>` + gateEmpty("Finish setting up first", "Add your fund universe and screening criteria, then run a screening.", "Go to setup", "overview");
  const sel = findH(S.sel);
  return `<div class="head"><div><span class="label">Risk assessment</span><h1>${esc(c.label)}</h1><p>${esc(c.description || "")} Revenue limit ${pct(c.threshold || 0, 0)}; a ${esc(c.controversyLimit || "high")} or worse controversy is a breach. Watch level: likelihood of rising exposure at ${fmt(c.watchAt == null ? 50 : c.watchAt, 0)} or above.</p></div><div class="toolbar"><button class="btn" data-act="go" data-v="agent">Run a screening</button></div></div>
  <div class="toolbar">${A.map((x) => `<button class="chipbtn" data-act="setCrit" data-c="${esc(x.id)}" aria-pressed="${x.id === c.id}">${esc(x.label)}</button>`).join("")}</div>
  <div class="split">
    <section class="panel"><div class="panel-h"><h2>Exposure vs. likelihood of increase</h2><span class="hint">Bubble size = fund weight · hollow = prospect</span></div>
      ${matrix(c)}
      <div class="legend"><span><i style="background:var(--breach-soft);border:1px solid var(--breach)"></i>Above revenue limit</span><span><i style="background:var(--watch-soft);border:1px solid var(--watch)"></i>Within limit, likely to rise</span><span><i style="background:var(--ok-soft);border:1px solid var(--ok)"></i>Clear</span></div>
      <p class="note">Bubble colour shows the overall status, so a company can be red inside the clear zone when a serious controversy puts it in breach. The horizontal axis uses a square-root scale so small revenue shares stay visible.</p>
    </section>
    <section class="panel">${sel ? detail(sel) : `<h2>Company detail</h2><p class="muted">Select a bubble or a company in the fund universe to see its assessment across all criteria.</p>`}</section>
  </div>`;
}
function matrix(c) {
  const W = 640, H = 380, L = 48, R = 18, T = 16, B = 46, pw = W - L - R, ph = H - T - B;
  const pts = S.holdings.map((h) => ({ h, r: evalC(h, c) })).filter((x) => x.r.sc);
  if (!pts.length) return gateEmpty("No scores for this criterion yet", "Run a screening to place companies on the chart.", "Run a screening", "agent");
  const mx = Math.max(10, ...pts.map((p) => p.r.sc.exposure || 0));
  const xmax = [10, 25, 50, 100].find((v) => v >= mx) || 100;
  const X = (e) => L + Math.sqrt(Math.max(0, e || 0) / xmax) * pw, Y = (l) => T + (1 - Math.max(0, Math.min(100, l || 0)) / 100) * ph;
  const thr = c.threshold || 0, wa = c.watchAt == null ? 50 : c.watchAt;
  let s = `<svg class="matrix" viewBox="0 0 ${W} ${H}" role="img" aria-label="Risk matrix for ${esc(c.label)}">`;
  s += `<rect x="${X(thr)}" y="${T}" width="${L + pw - X(thr)}" height="${ph}" fill="var(--breach-soft)"/>`;
  s += `<rect x="${L}" y="${T}" width="${X(thr) - L}" height="${Y(wa) - T}" fill="var(--watch-soft)"/>`;
  s += `<rect x="${L}" y="${Y(wa)}" width="${X(thr) - L}" height="${T + ph - Y(wa)}" fill="var(--ok-soft)"/>`;
  [0, 25, 50, 75, 100].forEach((v) => { s += `<line x1="${L}" x2="${L + pw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L - 8}" y="${Y(v) + 3}" text-anchor="end">${v}</text>`; });
  [0, 1, 5, 10, 25, 50, 100].filter((v) => v <= xmax).forEach((v) => { s += `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${T + ph}" stroke="var(--line)"/><text x="${X(v)}" y="${T + ph + 16}" text-anchor="middle">${v}%</text>`; });
  s += `<line x1="${X(thr)}" x2="${X(thr)}" y1="${T}" y2="${T + ph}" stroke="var(--breach)" stroke-width="2"/><text x="${X(thr) + 5}" y="${T + 12}" style="fill:var(--breach)">limit ${thr}%</text>`;
  s += `<text x="${L + pw / 2}" y="${H - 6}" text-anchor="middle">Share of revenue from excluded activity</text>`;
  s += `<text transform="translate(12 ${T + ph / 2}) rotate(-90)" text-anchor="middle">Likelihood exposure rises, next 12 months</text>`;
  pts.sort((a, b) => (b.h.weight || 0) - (a.h.weight || 0)).forEach(({ h, r }) => {
    const x = X(r.sc.exposure), y = Y(r.sc.likelihood), rad = h.type === "prospect" ? 6 : 4 + Math.sqrt(h.weight || 0) * 2.6;
    const col = r.state === "breach" ? "var(--breach)" : r.state === "watch" ? "var(--watch)" : "var(--ok)";
    const isSel = S.sel === h.id;
    s += `<g data-act="openH" data-id="${esc(h.id)}"><circle cx="${x}" cy="${y}" r="${rad}" fill="${h.type === "prospect" ? "var(--surface)" : col}" fill-opacity="${h.type === "prospect" ? 1 : 0.78}" stroke="${isSel ? "var(--ink)" : col}" stroke-width="${isSel ? 2.5 : 1.5}"><title>${esc(h.name)}: ${fmt(r.sc.exposure)}% revenue, likelihood ${fmt(r.sc.likelihood, 0)}${r.sc.controversy ? ", " + esc(r.sc.controversy.level) + " controversy" : ""}</title></circle><text class="tk" x="${Math.min(x + rad + 3, W - 30)}" y="${y + 3.5}">${esc(h.ticker || h.name)}</text></g>`;
  });
  return `<div style="overflow-x:auto">${s}</svg></div>`;
}
function detail(h) {
  const e = evalH(h), A = active(), al = alertsFor(h), ed = S.editing === h.id, k = "h:" + h.id;
  return `<div class="panel-h"><div><span class="label">${h.type === "prospect" ? "Prospect" : "Holding · " + pct(h.weight, 2) + " of fund"}</span><h2>${esc(h.name)}</h2><span class="mono muted">${esc(h.ticker || "")} · ${esc(h.isin || "no ISIN")}</span></div>${pill(e.state)}</div>
  <div class="toolbar"><button class="btn primary" data-act="rescreen" data-id="${esc(h.id)}" data-web="1" ${S.busy[k] ? "disabled" : ""}>${S.busy[k] ? "Screening…" : "Screen with web search"}</button><button class="btn" data-act="rescreen" data-id="${esc(h.id)}" ${S.busy[k] ? "disabled" : ""}>Quick estimate</button><button class="btn" data-act="edit" data-id="${esc(h.id)}">${ed ? "Cancel edit" : "Edit scores"}</button>${S.confirmDel === "h:" + h.id ? `<button class="btn danger" data-act="delH" data-id="${esc(h.id)}">Confirm remove</button>` : `<button class="btn ghost danger" data-act="askDelH" data-id="${esc(h.id)}">Remove</button>`}</div>
  ${S.busy[k] ? `<div class="thinking">${esc(S.busy[k])}</div>` : ""}${S.err[k] ? `<p class="err">${esc(S.err[k])}</p>` : ""}
  ${ed ? editForm(h) : A.map((c) => { const r = evalC(h, c), sc = r.sc; if (!sc) return `<div class="critcard"><div class="top"><b>${esc(c.label)}</b>${pill("na")}</div></div>`;
    const con = sc.controversy;
    return `<div class="critcard"><div class="top"><b>${esc(c.label)}</b>${pill(r.state)}</div>
    <div class="stats"><div><span class="label">Revenue exposure</span><b class="${r.why === "revenue" || r.why === "both" ? "neg" : ""}">${pct(sc.exposure)}</b><span class="hint">limit ${pct(c.threshold || 0, 0)}</span></div><div><span class="label">Likelihood ↑</span><b>${fmt(sc.likelihood, 0)}</b><span class="hint">${likeWord(sc.likelihood)}</span></div><div><span class="label">Source</span><b style="font-size:.9rem">${esc(sc.source || "–")}</b><span class="hint">${esc(sc.confidence ? sc.confidence + " confidence" : "")}${sc.date ? " · " + esc(sc.date) : ""}</span></div></div>
    ${sc.basis ? `<p class="hint"><b>Basis:</b> ${esc(sc.basis)}</p>` : ""}${sc.rationale ? `<p style="font-size:.86rem">${esc(sc.rationale)}</p>` : ""}
    ${(sc.signals || []).length ? `<ul class="signals">${sc.signals.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${con ? `<div class="top" style="border-top:1px dashed var(--line);padding-top:8px"><span class="label">Controversies</span>${lvlPill(con.level)}</div>${con.summary ? `<p style="font-size:.86rem">${esc(con.summary)}</p>` : ""}${(con.sources || []).length ? `<ul class="signals">${con.sources.filter((x) => safeUrl(x.url)).map((x) => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || x.url)}</a>${x.date ? ` <span class="muted">${esc(x.date)}</span>` : ""}</li>`).join("")}</ul>` : ""}<p class="hint">${esc(con.via || "Web search")}${con.checked ? " · checked " + esc(con.checked) : ""}</p>` : ""}</div>`; }).join("")}
  <div class="panel-h"><h3>Alerts for this company</h3><span class="hint">${al.length}</span></div>
  <div class="list">${al.slice(0, 4).map(alertCard).join("") || '<p class="muted">No alerts logged.</p>'}</div>`;
}
function editForm(h) {
  return active().map((c) => { const sc = (h.scores || {})[c.id] || {}; const p = `ed-${h.id}-${c.id}`;
    return `<div class="critcard"><b>${esc(c.label)}</b><div class="row"><div class="field"><label for="${p}-e">Revenue exposure %</label><input id="${p}-e" type="number" step="0.1" min="0" max="100" value="${esc(draft(p + "-e", sc.exposure == null ? "" : sc.exposure))}" data-draft="${p}-e"></div><div class="field"><label for="${p}-l">Likelihood 0–100</label><input id="${p}-l" type="number" step="1" min="0" max="100" value="${esc(draft(p + "-l", sc.likelihood == null ? "" : sc.likelihood))}" data-draft="${p}-l"></div></div><div class="field"><label for="${p}-n">Analyst note</label><input id="${p}-n" type="text" value="${esc(draft(p + "-n", sc.rationale || ""))}" data-draft="${p}-n"></div></div>`; }).join("") + `<div class="toolbar"><button class="btn primary" data-act="saveEdit" data-id="${esc(h.id)}">Save scores</button></div>`;
}

/* Alerts */
function alertCard(a) {
  const done = a.status === "reviewed" || a.status === "dismissed";
  const origin = { reprisk: "RepRisk", ai: "AI check", web: "AI web search", manual: "Manual" }[a.origin] || a.source || "News";
  return `<article class="alert ${esc(a.severity)} ${done ? "done" : ""}"><div class="stripe"></div><div class="body">
  <div class="meta">${sevPill(a.severity)}<span class="mono">${esc(a.date || "")}</span>${(a.tickers || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}<span>${esc((a.criteria || []).map((id) => (critById(id) || {}).label || "").filter(Boolean).join(", "))}</span><span>· ${esc(origin)}</span><span>· ${esc(a.status)}</span></div>
  <h3>${esc(a.title)}</h3>${a.summary ? `<p style="font-size:.86rem">${esc(a.summary)}</p>` : ""}
  <div class="acts">${safeUrl(a.url) ? `<a class="btn ghost" href="${esc(a.url)}" target="_blank" rel="noopener">Source</a>` : ""}${a.status !== "reviewed" ? `<button class="btn" data-act="aStatus" data-id="${esc(a.id)}" data-s="reviewed">Mark reviewed</button>` : ""}${a.status !== "escalated" ? `<button class="btn" data-act="aStatus" data-id="${esc(a.id)}" data-s="escalated">Escalate</button>` : ""}${a.status !== "dismissed" ? `<button class="btn ghost" data-act="aStatus" data-id="${esc(a.id)}" data-s="dismissed">Dismiss</button>` : ""}</div>
  </div></article>`;
}
function vAlerts() {
  let L = S.alerts;
  if (S.afilter === "open") L = L.filter((a) => a.status === "new" || a.status === "escalated");
  if (S.afilter === "high") L = L.filter((a) => a.severity === "high");
  const tr = S.res.triage;
  return `<div class="head"><div><span class="label">Alerts</span><h1>Breach alerts</h1><p>Signals that a company in your universe has moved into, or closer to, an excluded activity. Web screenings and daily monitoring add alerts here; you can also paste a news item for the AI to check.</p></div>
  <div class="toolbar"><div class="seg"><button data-act="afilter" data-f="open" aria-pressed="${S.afilter === "open"}">Open</button><button data-act="afilter" data-f="high" aria-pressed="${S.afilter === "high"}">High</button><button data-act="afilter" data-f="all" aria-pressed="${S.afilter === "all"}">All</button></div></div></div>
  ${S.holdings.length && active().length ? `<section class="panel ai"><div class="panel-h"><h2>Check a news item with AI</h2><span class="hint">Paste a headline, article, RepRisk incident or filing extract</span></div>
    <textarea id="tri-text" data-draft="tri-text" placeholder="e.g. 'Company X wins contract to supply drone guidance software to the army…'">${esc(draft("tri-text"))}</textarea>
    <div class="toolbar"><button class="btn primary" data-act="triage" ${S.busy.triage ? "disabled" : ""}>${S.busy.triage ? "Checking…" : "Check"}</button><span class="hint">Checks the item against ${active().length} criteria and ${S.holdings.length} companies.</span></div>
    ${S.busy.triage ? '<div class="thinking">Claude is reading the item…</div>' : ""}${S.err.triage ? `<p class="err">${esc(S.err.triage)}</p>` : ""}
    ${tr ? `<div class="critcard"><div class="top"><b>${tr.relevant ? esc(tr.title) : "Not relevant to your criteria"}</b>${tr.relevant ? sevPill(tr.severity) : ""}</div><p style="font-size:.86rem">${esc(tr.why || tr.summary || "")}</p>${tr.relevant ? `<div class="chips">${(tr.tickers || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${(tr.criteria || []).map((id) => `<span class="chip">${esc((critById(id) || {}).label || id)}</span>`).join("")}</div><div class="toolbar"><button class="btn primary" data-act="addTriage">Log as alert</button><button class="btn ghost" data-act="clearTriage">Discard</button></div>` : ""}</div>` : ""}
  </section>` : gateEmpty("Set up your workspace first", "Alerts need a fund universe and screening criteria.", "Go to setup", "overview")}
  <div class="list">${L.map(alertCard).join("") || (S.alerts.length ? `<div class="empty"><h2>No alerts in this view</h2></div>` : "")}</div>`;
}

/* Criteria */
const TEMPLATES = [
  { key: "military", label: "Military & defence revenue", description: "Revenue from military customers, defence contracts, or products and services for military end use, including cloud and AI for armed forces.", threshold: 0, watchAt: 50, controversyLimit: "high", keywords: ["military", "defence", "defense", "army", "weapon", "pentagon", "armed forces", "warfare"] },
  { key: "military-finance", label: "Defence investment & financing", description: "Financing, venture investment or strategic stakes in defence companies.", threshold: 0, watchAt: 50, controversyLimit: "high", keywords: ["defence fund", "stake", "investment", "financing", "venture"] },
  { key: "controversial-weapons", label: "Controversial weapons", description: "Cluster munitions, anti-personnel mines, nuclear, chemical and biological weapons, including key components.", threshold: 0, watchAt: 30, controversyLimit: "medium", keywords: ["cluster", "landmine", "nuclear weapon", "chemical weapon", "biological", "controversial weapon"] },
  { key: "surveillance", label: "State surveillance & dual-use AI", description: "Revenue from mass-surveillance, predictive policing or targeting tools sold to state security agencies.", threshold: 5, watchAt: 55, controversyLimit: "high", keywords: ["surveillance", "facial recognition", "intelligence", "spyware", "policing"] },
  { key: "thermal-coal", label: "Thermal coal", description: "Mining of thermal coal or coal-fired power generation.", threshold: 5, watchAt: 50, controversyLimit: "high", keywords: ["coal"] },
  { key: "oil-gas-expansion", label: "Oil & gas expansion", description: "Exploration and development of new oil and gas fields, including Arctic and oil sands.", threshold: 5, watchAt: 50, controversyLimit: "high", keywords: ["oil", "gas", "arctic", "oil sands", "fracking"] },
  { key: "tobacco", label: "Tobacco", description: "Production of tobacco products; distribution above the limit.", threshold: 0, watchAt: 50, controversyLimit: "high", keywords: ["tobacco", "cigarette", "nicotine"] },
  { key: "gambling", label: "Gambling", description: "Operation of gambling services or supply of gambling equipment.", threshold: 5, watchAt: 50, controversyLimit: "high", keywords: ["gambling", "casino", "betting"] },
  { key: "adult", label: "Adult entertainment", description: "Production or distribution of adult entertainment.", threshold: 0, watchAt: 50, controversyLimit: "high", keywords: ["adult", "pornograph"] },
  { key: "forced-labour", label: "Forced labour in supply chain", description: "Credible evidence of forced or child labour in own operations or tier-1 suppliers.", threshold: 0, watchAt: 40, controversyLimit: "medium", keywords: ["forced labour", "forced labor", "child labour", "uyghur", "modern slavery"] },
  { key: "ungc", label: "UN Global Compact violations", description: "Severe, verified breaches of UNGC principles on human rights, labour, environment or corruption.", threshold: 0, watchAt: 40, controversyLimit: "high", keywords: ["human rights", "corruption", "bribery", "violation", "global compact"] },
];
function vPolicy() {
  const A = S.criteria.slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  const pd = S.res.policy, have = new Set(S.criteria.map((c) => c.key).filter(Boolean));
  return `<div class="head"><div><span class="label">Step 2</span><h1>What your fund must not hold</h1><p>Each criterion has a revenue limit (0% means any exposure is a breach), a controversy level that counts as a breach, and a watch level for the likelihood that exposure rises. Start from a common exclusion or describe your own policy in words.</p></div></div>
  <section class="panel"><div class="panel-h"><h2>Common exclusions</h2><span class="hint">Click to add with standard limits, then adjust</span></div>
    <div class="chips">${TEMPLATES.map((t) => `<button class="chipbtn" data-act="addTpl" data-c="${t.key}" ${have.has(t.key) ? "disabled" : ""}>${have.has(t.key) ? "✓ " : "+ "}${esc(t.label)}</button>`).join("")}</div>
  </section>
  <section class="panel ai"><div class="panel-h"><h2>Describe your policy in plain language</h2><span class="hint">The AI turns it into measurable criteria</span></div>
    <textarea id="pol-text" data-draft="pol-text" placeholder="e.g. The fund excludes any company with revenue from military activity, military financing or military-related products. We also exclude companies earning more than 5% of revenue from thermal coal…">${esc(draft("pol-text"))}</textarea>
    <div class="toolbar"><button class="btn primary" data-act="draftPolicy" ${S.busy.policy ? "disabled" : ""}>${S.busy.policy ? "Drafting…" : "Draft criteria"}</button><span class="hint">You review every criterion before it is added.</span></div>
    ${S.busy.policy ? '<div class="thinking">Claude is reading your policy…</div>' : ""}${S.err.policy ? `<p class="err">${esc(S.err.policy)}</p>` : ""}
    ${pd ? `<div class="list">${pd.map((c, i) => `<div class="critcard"><div class="top"><b>${esc(c.label)}</b><span class="mono">limit ${fmt(num(c.threshold), 0)}% · controversy ${esc(c.controversyLimit || "high")}+ · watch ${fmt(num(c.watchAt), 0)}</span></div><p class="hint">${esc(c.description)}</p>${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}<div class="toolbar"><button class="btn" data-act="addDraft" data-i="${i}" ${have.has(slug(c.key)) ? "disabled" : ""}>${have.has(slug(c.key)) ? "In your criteria" : "Add"}</button></div></div>`).join("")}</div><div class="toolbar"><button class="btn primary" data-act="addAllDrafts">Add all new</button><button class="btn ghost" data-act="clearDrafts">Discard drafts</button></div>` : ""}
  </section>
  <section class="panel"><div class="panel-h"><h2>Your criteria</h2><span class="hint">${active().length} of ${A.length} on</span></div>
    ${A.length ? A.map((c) => `<div class="policyrow"><button class="switch" role="switch" aria-checked="${c.active !== false}" aria-label="Apply ${esc(c.label)}" data-act="toggleC" data-c="${esc(c.id)}"></button><div><b>${esc(c.label)}</b><div class="desc">${esc(c.description || "")}</div><div class="desc" style="margin-top:4px"><label for="cl-${esc(c.id)}">Controversy breach at</label> <select id="cl-${esc(c.id)}" data-chg="conlim" data-c="${esc(c.id)}" style="width:auto;padding:2px 6px">${[["medium", "Medium or worse"], ["high", "High or worse"], ["severe", "Severe only"]].map(([v, l]) => `<option value="${v}" ${(c.controversyLimit || "high") === v ? "selected" : ""}>${l}</option>`).join("")}</select></div></div>
      <div class="field pn"><label for="th-${esc(c.id)}">Limit %</label><input id="th-${esc(c.id)}" type="number" min="0" max="100" step="0.5" value="${esc(c.threshold || 0)}" data-chg="thr" data-c="${esc(c.id)}"></div>
      <div class="field pn"><label for="wa-${esc(c.id)}">Watch at</label><input id="wa-${esc(c.id)}" type="number" min="0" max="100" step="5" value="${esc(c.watchAt == null ? 50 : c.watchAt)}" data-chg="wa" data-c="${esc(c.id)}"></div>
      <div class="pn">${S.confirmDel === c.id ? `<button class="btn danger" data-act="delC" data-c="${esc(c.id)}">Confirm remove</button>` : `<button class="btn ghost" data-act="askDel" data-c="${esc(c.id)}">Remove</button>`}</div></div>`).join("") : '<p class="muted">No criteria yet. Add a common exclusion above or draft criteria from your policy text.</p>'}
  </section>${nextStep(2)}`;
}

/* Data sources */
const PROVIDERS = [
  { id: "iss", name: "ISS STOXX", what: "Norm-Based Research, controversial weapons and sector involvement data", kind: "scores" },
  { id: "msci", name: "MSCI ESG Research", what: "Business Involvement Screening: revenue shares by activity", kind: "scores" },
  { id: "sustainalytics", name: "Morningstar Sustainalytics", what: "Product Involvement: revenue ranges by activity", kind: "scores" },
  { id: "reprisk", name: "RepRisk", what: "Daily ESG incidents and controversy alerts", kind: "incidents" },
  { id: "other", name: "Other provider or in-house research", what: "Any CSV with company, category and revenue share", kind: "scores" },
];
function vSources() {
  const m = mode(), provs = (S.ws && S.ws.providers) || {};
  const ch = (id, who, title, body, items) => `<button class="choice" data-act="setMode" data-m="${id}" aria-pressed="${m === id}"><span class="who">${who}</span><h2>${title}</h2><p class="hint">${body}</p><ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul></button>`;
  const p = PROVIDERS.find((x) => x.id === S.prov);
  return `<div class="head"><div><span class="label">Step 3</span><h1>How should Redline screen your universe?</h1><p>Institutions with an ESG data licence can load provider data. Individual investors and smaller firms can let the AI do the research. You can combine both.</p></div></div>
  <div class="choices">
    ${ch("provider", "For institutions with a data licence", "Use my data provider", "Load screening data from ISS STOXX, MSCI, Sustainalytics or RepRisk.", ["Revenue shares come from your provider", "Incidents arrive as alerts", "AI web search still available for controversies"])}
    ${ch("ai", "For individuals and smaller firms", "Let the AI screen", "No subscription needed. The AI searches the web for each company and criterion.", ["Finds controversies with source links", "Estimates revenue exposure and its trend", "Daily monitoring raises new alerts"])}
    ${ch("both", "Recommended for institutions", "Provider data + AI", "Use provider figures where they exist and let the AI cover controversies and the gaps.", ["Provider figures always take priority", "AI covers prospects and uncovered names", "AI adds controversies and likelihood"])}
  </div>
  ${useProv() ? `<section class="panel"><div class="panel-h"><h2>Data providers</h2><span class="hint">Load an export from each provider you license</span></div>
    ${PROVIDERS.map((x) => { const st = provs[x.id]; return `<div class="prov"><div><b>${esc(x.name)}</b><span>${esc(x.what)}${st && st.last ? ` · last loaded ${esc(st.last)}, ${st.rows} rows` : ""}</span></div><button class="btn ${S.prov === x.id ? "primary" : ""}" data-act="openProv" data-p="${x.id}">${st ? "Load again" : "Connect"}</button></div>`; }).join("")}
    <p class="note">Live API connections to these providers need your firm's licence and credentials. Until such a connection is built for your licence, export the data from the provider's platform and load it here; matching is by ISIN, then company name.</p>
  </section>${p ? provPanel(p) : ""}` : ""}
  ${nextStep(3)}${stepState().done ? `<div class="toolbar"><button class="btn" data-act="go" data-v="agent">Go to screening →</button></div>` : ""}`;
}
function provPanel(p) {
  const pr = S.res.prov;
  if (p.kind === "incidents") return `<section class="panel"><div class="panel-h"><h2>Load ${esc(p.name)} incidents</h2><button class="btn ghost" data-act="openProv" data-p="">Close</button></div>
    <p class="hint">Paste the CSV from a RepRisk incident export. Columns are matched by name (company, ISIN, date, headline or title, severity, URL, ESG issues or topic tags). Rows are matched to your universe by ISIN, then by name; topics are mapped to your criteria by keyword.</p>
    <textarea id="rr-csv" class="mono" data-draft="rr-csv" placeholder="Company Name,ISIN,Incident Date,Headline,Severity,Source URL,ESG Issues">${esc(draft("rr-csv"))}</textarea>
    <div class="toolbar"><input id="rr-file" type="file" accept=".csv,text/csv" data-chg="rrfile"><button class="btn primary" data-act="importRR">Load incidents</button></div></section>`;
  return `<section class="panel"><div class="panel-h"><h2>Load ${esc(p.name)} data</h2><button class="btn ghost" data-act="openProv" data-p="">Close</button></div>
    <p class="hint">Paste or choose the CSV export. Each row needs a company (ISIN or name), an involvement category and a revenue share. Columns are matched by name: isin, company/issuer, category/activity/involvement, revenue/percent/max, flag. Rows with a flag but no revenue share are recorded as involvement of unknown size.</p>
    <textarea id="pv-csv" class="mono" data-draft="pv-csv" placeholder="ISIN,Issuer,Category,Revenue %&#10;US69608A1088,Palantir Technologies,Military Contracting,41.0">${esc(draft("pv-csv"))}</textarea>
    <div class="toolbar"><input id="pv-file" type="file" accept=".csv,text/csv,text/plain" data-chg="pvfile"><button class="btn" data-act="readProv">Read file</button></div>
    ${pr && pr.provider === p.id ? `<div class="panel-h"><h3>Match categories to your criteria</h3><span class="hint">${pr.rows.length} rows, ${pr.matched} matched to companies in your universe</span></div>
      <div class="list">${pr.cats.map((c, i) => `<div class="maprow"><span>${esc(c.name)} <span class="muted">(${c.count})</span></span><span class="arrow">→</span><select data-chg="catmap" data-i="${i}"><option value="">Ignore</option>${active().map((a) => `<option value="${esc(a.id)}" ${c.map === a.id ? "selected" : ""}>${esc(a.label)}</option>`).join("")}</select></div>`).join("")}</div>
      <div class="toolbar"><button class="btn primary" data-act="applyProv">Apply to universe</button><button class="btn ghost" data-act="clearProv">Discard</button></div>` : ""}
  </section>`;
}

/* Screening */
const sget = (k, def) => (S.drafts[k] != null ? S.drafts[k] : def);
function vAgent() {
  const A = active();
  if (!A.length) return `<div class="head"><div><span class="label">Screening</span><h1>Screening</h1></div></div>` + gateEmpty("Set your screening criteria first", "Screenings check companies against your own criteria.", "Set criteria", "policy");
  const scope = sget("scr-scope", S.holdings.length ? "universe" : "new"), method = sget("scr-method", "web");
  const wantRev = sget("scr-rev", true), wantCon = sget("scr-con", true);
  const selIss = S.drafts["scr-iss"] || {}, selCrit = S.drafts["scr-crit"] || {};
  const q = S.res.ask, mon = (S.ws && S.ws.monitor) || {}, run = S.run;
  const monIss = mon.issuers == null ? "all" : mon.issuers, monCrit = mon.criteria || [];
  return `<div class="head"><div><span class="label">Screening</span><h1>Screen for revenue exposure and controversies</h1><p>Screen the whole universe, chosen issuers, or a company before you invest. The web search screening looks on the internet for controversies that touch your criteria, such as a weapons contract or a surveillance scandal, and estimates revenue exposure from the latest disclosures.</p></div></div>
  <section class="panel ai"><div class="panel-h"><h2>New screening</h2></div>
    <div class="field"><span class="label">1 · What to screen</span><div class="chips"><label class="check"><input type="checkbox" data-chg="scrflag" data-k="scr-con" ${wantCon ? "checked" : ""}> Controversies and incidents</label><label class="check"><input type="checkbox" data-chg="scrflag" data-k="scr-rev" ${wantRev ? "checked" : ""}> Revenue exposure</label></div></div>
    <div class="field"><span class="label">2 · Which companies</span><div class="seg">${[["universe", "Whole universe"], ["issuers", "Selected issuers"], ["new", "New issuer, before investing"]].map(([k, l]) => `<button data-act="scrSet" data-k="scr-scope" data-v="${k}" aria-pressed="${scope === k}" ${k !== "new" && !S.holdings.length ? "disabled" : ""}>${l}</button>`).join("")}</div></div>
    ${scope === "issuers" ? `<div class="chips" style="max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:var(--r);padding:10px">${S.holdings.slice().sort((a, b) => (b.weight || 0) - (a.weight || 0)).map((h) => `<label class="check"><input type="checkbox" data-chg="scrpick" data-g="scr-iss" data-id="${esc(h.id)}" ${selIss[h.id] ? "checked" : ""}> ${esc(h.name)} <span class="muted mono">${esc(h.ticker || "")}</span></label>`).join("")}</div>` : ""}
    ${scope === "new" ? `<div class="row"><div class="field"><label for="ag-name">Company</label><input id="ag-name" type="text" data-draft="ag-name" value="${esc(draft("ag-name"))}" placeholder="e.g. Snowflake"></div><div class="field"><label for="ag-ticker">Ticker</label><input id="ag-ticker" type="text" data-draft="ag-ticker" value="${esc(draft("ag-ticker"))}"></div><div class="field"><label for="ag-isin">ISIN</label><input id="ag-isin" type="text" data-draft="ag-isin" value="${esc(draft("ag-isin"))}"></div></div>
      <div class="field"><label for="ag-ctx">Context to consider (optional)</label><textarea id="ag-ctx" data-draft="ag-ctx" placeholder="Paste filings, contract announcements or news.">${esc(draft("ag-ctx"))}</textarea></div><p class="hint">The company is added to your universe as a prospect so you can follow it.</p>` : ""}
    <div class="field"><span class="label">3 · Against which criteria</span><div class="chips">${A.map((c) => `<label class="check"><input type="checkbox" data-chg="scrpick" data-g="scr-crit" data-id="${esc(c.id)}" ${selCrit[c.id] === false ? "" : "checked"}> ${esc(c.label)}</label>`).join("")}</div></div>
    <div class="field"><span class="label">4 · How</span><div class="seg"><button data-act="scrSet" data-k="scr-method" data-v="web" aria-pressed="${method === "web"}">Web search</button><button data-act="scrSet" data-k="scr-method" data-v="quick" aria-pressed="${method === "quick"}">Quick estimate</button></div>
      <p class="hint">${method === "web" ? "Searches the internet for each company and criterion and saves the sources. About 20–60 seconds per company and criterion." : "From Claude's own knowledge, without web search. Faster and cheaper, but recent events may be missing."}</p></div>
    <div class="toolbar"><button class="btn primary" data-act="runScreening" ${run && run.active ? "disabled" : ""}>${run && run.active ? "Screening…" : "Run screening"}</button>${run && run.active ? `<button class="btn ghost" data-act="stopRun">Stop after current check</button>` : ""}</div>
    ${run ? `<div class="field"><div class="progress"><i style="width:${run.total ? Math.round((run.done / run.total) * 100) : 0}%"></i></div><p class="hint">${run.active ? `Checking ${esc(run.current || "")} (${run.done + 1} of ${run.total})` : `Finished: ${run.done} of ${run.total} checks`}${run.alerts ? `, ${run.alerts} new alerts` : ""}${run.errors.length ? `, ${run.errors.length} failed` : ""}.</p>${run.errors.length ? `<p class="err">${esc(run.errors.slice(-3).join(" · "))}</p>` : ""}${!run.active && run.done ? `<div class="toolbar"><button class="btn" data-act="go" data-v="${run.lastHolding && run.total <= 4 ? "risk" : "overview"}" ${run.lastHolding ? `data-sel="${esc(run.lastHolding)}"` : ""}>See results →</button></div>` : ""}</div>` : ""}
  </section>
  <section class="panel"><div class="panel-h"><h2>Daily monitoring</h2><button class="switch" role="switch" aria-checked="${!!mon.enabled}" aria-label="Daily monitoring" data-act="monToggle"></button></div>
    <p style="font-size:.9rem">When on, the AI searches the news ${esc(S.cfg.monitorTime || "every morning")} for the issuers and criteria below and raises an alert when something new turns up.${mon.lastRun ? ` Last run ${esc(mon.lastRun)}${mon.lastNote ? ": " + esc(mon.lastNote) : ""}` : ""}</p>
    <div class="field"><span class="label">Issuers to watch</span><div class="seg"><button data-act="monScope" data-v="all" aria-pressed="${monIss === "all"}">All companies</button><button data-act="monScope" data-v="pick" aria-pressed="${monIss !== "all"}">Selected issuers</button></div></div>
    ${monIss !== "all" ? `<div class="chips" style="max-height:200px;overflow:auto;border:1px solid var(--line);border-radius:var(--r);padding:10px">${S.holdings.map((h) => `<label class="check"><input type="checkbox" data-chg="monpick" data-g="issuers" data-id="${esc(h.id)}" ${monIss.includes(h.id) ? "checked" : ""}> ${esc(h.name)}</label>`).join("")}</div>` : ""}
    <div class="field"><span class="label">Criteria to watch</span><div class="chips">${A.map((c) => `<label class="check"><input type="checkbox" data-chg="monpick" data-g="criteria" data-id="${esc(c.id)}" ${!monCrit.length || monCrit.includes(c.id) ? "checked" : ""}> ${esc(c.label)}</label>`).join("")}</div></div>
  </section>
  <section class="panel ai"><div class="panel-h"><h2>Ask about your portfolio</h2><span class="hint">Answers use your universe, scores, criteria and alerts</span></div>
    <div class="row"><div class="field"><label for="ask-q">Question</label><input id="ask-q" type="text" data-draft="ask-q" value="${esc(draft("ask-q"))}" placeholder="Which holdings have high-severity weapons controversies?"></div><button class="btn primary" data-act="ask" ${S.busy.ask ? "disabled" : ""}>${S.busy.ask ? "Thinking…" : "Ask"}</button></div>
    ${S.busy.ask ? '<div class="thinking">Claude is reading your portfolio…</div>' : ""}${S.err.ask ? `<p class="err">${esc(S.err.ask)}</p>` : ""}${q ? `<div class="answer">${esc(q)}</div>` : ""}
  </section>`;
}

/* ---------- CSV ---------- */
function parseCSV(text) {
  const rows = []; let row = [], cur = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch; }
    else if (ch === '"') q = true;
    else if (ch === "," || ch === ";" || ch === "\t") { row.push(cur); cur = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cur); cur = ""; if (row.some((c) => c.trim() !== "")) rows.push(row); row = []; }
    else cur += ch;
  }
  row.push(cur); if (row.some((c) => c.trim() !== "")) rows.push(row);
  if (!rows.length) return [];
  const hdr = rows[0].map((h) => h.trim().toLowerCase());
  return rows.slice(1).map((r) => { const o = {}; hdr.forEach((h, i) => (o[h] = (r[i] || "").trim())); return o; });
}
const pick = (o, ...keys) => { for (const k of Object.keys(o)) { if (keys.some((x) => k === x || k.includes(x)) && o[k] !== "") return o[k]; } return ""; };
const matchRow = (r) => findH(pick(r, "isin").toUpperCase()) || findH(pick(r, "ticker", "symbol")) || findByName(pick(r, "issuer", "company", "name"));
function guessCrit(text) { const t = String(text).toLowerCase(); const c = active().find((c) => (c.keywords || []).some((k) => t.includes(k)) || t.includes(String(c.label).toLowerCase().split(" ")[0])); return c ? c.id : ""; }

/* ---------- screening runs (browser drives one check at a time) ---------- */
async function runChecks(jobs, { web, what, context }) {
  S.run = { active: true, total: jobs.length, done: 0, alerts: 0, errors: [], current: "", stop: false, lastHolding: jobs.length ? jobs[jobs.length - 1].holding.id : null };
  render();
  for (const job of jobs) {
    if (S.run.stop) break;
    S.run.current = `${job.holding.name}${job.criteria.length === 1 ? " · " + (critById(job.criteria[0]) || {}).label : ""}`;
    render();
    try {
      const r = await api("screen", { holdingId: job.holding.id, criterionIds: job.criteria, what, web, context });
      S.run.alerts += r.alertsAdded || 0;
      const h = S.holdings.find((x) => x.id === job.holding.id);
      if (h && r.scores) h.scores = r.scores;
    } catch (e) {
      S.run.errors.push(`${job.holding.name}: ${aiErr(e)}`);
    }
    S.run.done++;
    render();
  }
  S.run.active = false;
  await loadAll();
}

/* ---------- actions ---------- */
const ACT = {
  go(d) { S.view = d.v; S.panel = null; S.prov = null; if (d.sel) S.sel = d.sel; render(); window.scrollTo(0, 0); },
  goCrit(d) { S.crit = d.c; S.view = "risk"; render(); window.scrollTo(0, 0); },
  openH(d) { S.sel = d.id; if (S.view !== "risk") { S.view = "risk"; window.scrollTo(0, 0); } const h = findH(d.id); if (h) { const e = evalH(h); if (e.hits[0] && !S.critPinned) S.crit = e.hits[0].c.id; } render(); },
  setCrit(d) { S.crit = d.c; S.critPinned = true; render(); },
  sort(d) { S.usort = S.usort.k === d.k ? { k: d.k, d: -S.usort.d } : { k: d.k, d: d.k === "name" ? 1 : -1 }; render(); },
  scope(d) { S.scope = d.s; render(); },
  panel(d) { S.panel = d.p || null; render(); },
  afilter(d) { S.afilter = d.f; render(); },
  edit(d) { S.editing = S.editing === d.id ? null : d.id; render(); },
  authMode() { S.authMode = S.authMode === "signup" ? "signin" : "signup"; S.err.auth = null; S.res.authNote = null; render(); },
  async signOut() { await S.sb.auth.signOut(); },
  askDelH(d) { S.confirmDel = "h:" + d.id; render(); },
  async delH(d) { try { await DB.delH(d.id); S.confirmDel = null; S.sel = null; toast("Removed from universe"); await loadAll(); } catch (e) { writeErr(e); } },
  async saveName() { const n = draft("ws-name").trim(); if (!n) { toast("Enter a name"); return; } try { await DB.ws({ name: n }); toast("Saved"); await loadAll(); } catch (e) { writeErr(e); } },
  async setMode(d) { try { await DB.ws({ mode: d.m }); toast(d.m === "provider" ? "Screening with your data provider" : d.m === "ai" ? "The AI will screen your universe" : "Provider data first, AI for the gaps"); await loadAll(); } catch (e) { writeErr(e); } },
  openProv(d) { S.prov = d.p || null; S.res.prov = null; render(); },
  async saveEdit(d) {
    const h = findH(d.id); const up = {};
    active().forEach((c) => { const p = `ed-${h.id}-${c.id}`; const old = (h.scores || {})[c.id] || {}; const e = num(draft(p + "-e", old.exposure)), l = num(draft(p + "-l", old.likelihood)); if (e == null) return;
      up[c.id] = Object.assign({}, old, { exposure: e, likelihood: l, rationale: draft(p + "-n", old.rationale || ""), source: "Analyst", date: today(), confidence: old.confidence || "medium" }); });
    try { await saveScores(h, up); S.editing = null; toast("Scores saved"); await loadAll(); } catch (e) { writeErr(e); }
  },
  async aStatus(d, el) { try { el.disabled = true; await DB.updA(d.id, { status: d.s }); toast(d.s === "reviewed" ? "Marked reviewed" : d.s === "escalated" ? "Escalated" : "Dismissed"); await loadAll(); } catch (e) { el.disabled = false; writeErr(e); } },
  async toggleC(d) { const c = critById(d.c); try { await DB.updC(c.id, { active: c.active === false }); await loadAll(); } catch (e) { writeErr(e); } },
  askDel(d) { S.confirmDel = d.c; render(); },
  async delC(d) { try { await DB.delC(d.c); S.confirmDel = null; toast("Criterion removed"); await loadAll(); } catch (e) { writeErr(e); } },
  async addTpl(d) { const t = TEMPLATES.find((x) => x.key === d.c); try { await DB.addC({ ...t, active: true, order: S.criteria.length + 1 }); toast("Added " + t.label); await loadAll(); } catch (e) { writeErr(e); } },
  async addCo() {
    const name = draft("ad-name").trim(); if (!name) { toast("Enter a company name"); return; }
    try { await DB.addH({ name, ticker: draft("ad-ticker").trim().toUpperCase(), isin: draft("ad-isin").trim().toUpperCase(), weight: num(draft("ad-weight")) || 0, type: draft("ad-type", "holding") === "prospect" ? "prospect" : "holding" });
      ["ad-name", "ad-ticker", "ad-isin", "ad-weight"].forEach((k) => delete S.drafts[k]); toast("Added " + name); await loadAll(); } catch (e) { writeErr(e); }
  },
  async importCsv() {
    const rows = parseCSV(draft("imp-csv")); if (!rows.length) { toast("Paste CSV with a header row first"); return; }
    let n = 0; const inserts = [];
    try {
      for (const r of rows) {
        const name = pick(r, "name", "company", "security", "issuer"); if (!name) continue;
        const ticker = pick(r, "ticker", "symbol").toUpperCase(), isin = pick(r, "isin").toUpperCase();
        const f = { name, ticker, isin };
        const w = num(pick(r, "weight", "wgt", "% of")); if (w != null) f.weight = w;
        const y = num(pick(r, "ytd")); if (y != null) f.ytd = y;
        const o = num(pick(r, "1y", "return_1y", "1 year", "12m")); if (o != null) f.r1y = o;
        const ct = pick(r, "country"); if (ct) f.country = ct;
        const sc = pick(r, "sector"); if (sc) f.sector = sc;
        f.type = pick(r, "type").toLowerCase().startsWith("pros") ? "prospect" : "holding";
        const ex = findH(ticker) || findH(isin);
        if (ex) await DB.updH(ex.id, f); else inserts.push(f);
        n++;
      }
      if (inserts.length) chk(await S.sb.from("holdings").insert(inserts));
      delete S.drafts["imp-csv"]; S.panel = null; toast(`Imported ${n} companies`); await loadAll();
    } catch (e) { writeErr(e); }
  },
  async parseList() {
    const t = draft("paste-txt").trim(); if (!t) { toast("Paste your list first"); return; }
    S.busy.parse = true; S.err.parse = null; S.res.parse = null; render();
    try { S.res.parse = (await api("parse-list", { text: t })).holdings; } catch (e) { S.err.parse = aiErr(e); }
    S.busy.parse = false; render();
  },
  async addParsed() {
    let n = 0; const inserts = [];
    try {
      for (const x of S.res.parse) {
        const ticker = String(x.ticker || "").toUpperCase(), isin = String(x.isin || "").toUpperCase();
        const ex = findH(ticker) || findH(isin) || findByName(x.name);
        const f = { name: x.name, ticker, isin }; if (num(x.weight) != null) f.weight = num(x.weight);
        if (ex) await DB.updH(ex.id, f); else inserts.push({ ...f, type: "holding", weight: f.weight || 0 });
        n++;
      }
      if (inserts.length) chk(await S.sb.from("holdings").insert(inserts));
      S.res.parse = null; delete S.drafts["paste-txt"]; S.panel = null; toast(`Added ${n} companies`); await loadAll();
    } catch (e) { writeErr(e); }
  },
  clearParsed() { S.res.parse = null; render(); },
  readProv() {
    const rows = parseCSV(draft("pv-csv")); if (!rows.length) { toast("Paste the provider CSV first"); return; }
    const cats = {}; let matched = 0;
    rows.forEach((r) => { const c = pick(r, "category", "activity", "involvement", "segment", "theme") || "Uncategorised"; cats[c] = (cats[c] || 0) + 1; if (matchRow(r)) matched++; });
    S.res.prov = { provider: S.prov, rows, matched, cats: Object.entries(cats).map(([name, count]) => ({ name, count, map: guessCrit(name) })) }; render();
  },
  clearProv() { S.res.prov = null; render(); },
  async applyProv() {
    const pr = S.res.prov, p = PROVIDERS.find((x) => x.id === pr.provider); const map = {}; pr.cats.forEach((c) => { if (c.map) map[c.name] = c.map; });
    const upd = {}; let used = 0, skip = 0;
    pr.rows.forEach((r) => {
      const h = matchRow(r); const cat = pick(r, "category", "activity", "involvement", "segment", "theme") || "Uncategorised"; const cid = map[cat]; if (!h || !cid) { skip++; return; }
      let v = num(pick(r, "revenue", "percent", "pct", "max", "share", "%")); const flag = pick(r, "flag", "involved", "indicator").toLowerCase();
      let basis = `${p.name}: ${cat}`; if (v == null) { if (/^(y|yes|true|1)/.test(flag)) { v = 0.1; basis += ", involvement flagged, revenue share not given"; } else { skip++; return; } }
      upd[h.id] = upd[h.id] || {}; const prev = upd[h.id][cid];
      upd[h.id][cid] = { exposure: prev ? Math.max(prev.exposure, v) : v, confidence: "high", basis, rationale: "", signals: [], source: p.name, date: today() }; used++;
    });
    try {
      for (const id of Object.keys(upd)) { const h = findH(id); const merged = {}; Object.entries(upd[id]).forEach(([cid, sc]) => { const old = (h.scores || {})[cid] || {}; merged[cid] = Object.assign({}, old, sc); }); await saveScores(h, merged); }
      const provs = JSON.parse(JSON.stringify((S.ws && S.ws.providers) || {})); provs[p.id] = { last: today(), rows: used }; await DB.ws({ providers: provs });
      S.res.prov = null; delete S.drafts["pv-csv"]; S.prov = null; toast(`Applied ${used} rows to ${Object.keys(upd).length} companies${skip ? `, skipped ${skip}` : ""}`); await loadAll();
    } catch (e) { writeErr(e); }
  },
  async importRR() {
    const rows = parseCSV(draft("rr-csv")); if (!rows.length) { toast("Paste the RepRisk CSV first"); return; }
    const out = []; let skip = 0;
    rows.forEach((r) => {
      const h = matchRow(r); if (!h) { skip++; return; }
      const text = (pick(r, "issue", "topic", "tag") + " " + pick(r, "headline", "title", "summary")).toLowerCase();
      const crits = S.criteria.filter((c) => (c.keywords || []).some((k) => text.includes(k))).map((c) => c.id);
      const sv = pick(r, "severity").toLowerCase(); const sev = /high|3/.test(sv) ? "high" : /med|2/.test(sv) ? "medium" : "low";
      const dt = pick(r, "date"); const parsed = dt && !isNaN(Date.parse(dt)) ? new Date(dt).toISOString().slice(0, 10) : today();
      out.push({ title: pick(r, "headline", "title") || "RepRisk incident", summary: pick(r, "summary", "description"), date: parsed, severity: sev, tickers: [h.ticker || h.name], criteria: crits, url: pick(r, "url", "link"), origin: "reprisk", source: "RepRisk", status: "new" });
    });
    try {
      if (out.length) await DB.addA(out);
      const provs = JSON.parse(JSON.stringify((S.ws && S.ws.providers) || {})); provs.reprisk = { last: today(), rows: out.length }; await DB.ws({ providers: provs });
      delete S.drafts["rr-csv"]; S.prov = null; toast(`Loaded ${out.length} incidents${skip ? `, skipped ${skip} without a matching company` : ""}`); await loadAll();
    } catch (e) { writeErr(e); }
  },
  async draftPolicy() {
    const t = draft("pol-text").trim(); if (!t) { toast("Describe your policy first"); return; }
    S.busy.policy = true; S.err.policy = null; render();
    try { S.res.policy = (await api("policy", { text: t, existing: S.criteria.map((c) => c.key).filter(Boolean) })).criteria; } catch (e) { S.err.policy = aiErr(e); }
    S.busy.policy = false; render();
  },
  async addDraft(d) { const c = S.res.policy[+d.i]; try { await DB.addC(fromDraft(c, S.criteria.length + 1)); toast("Added " + c.label); await loadAll(); } catch (e) { writeErr(e); } },
  async addAllDrafts() {
    const have = new Set(S.criteria.map((c) => c.key)); const rows = S.res.policy.filter((c) => !have.has(slug(c.key))).map((c, i) => toDbC(fromDraft(c, S.criteria.length + 1 + i)));
    try { if (rows.length) chk(await S.sb.from("criteria").insert(rows)); S.res.policy = null; toast(`Added ${rows.length} criteria`); await loadAll(); } catch (e) { writeErr(e); }
  },
  clearDrafts() { S.res.policy = null; render(); },
  async rescreen(d) {
    const h = findH(d.id); const k = "h:" + h.id; const web = d.web === "1";
    S.busy[k] = web ? `Searching the web for ${h.name} across ${active().length} criteria… (about ${Math.max(1, active().length) * 30} seconds)` : `Estimating ${h.name}…`; S.err[k] = null; render();
    try {
      let alerts = 0;
      for (const c of web ? active().map((c) => [c.id]) : [active().map((c) => c.id)]) {
        const r = await api("screen", { holdingId: h.id, criterionIds: c, what: ["revenue", "controversies"], web });
        alerts += r.alertsAdded || 0; h.scores = r.scores;
      }
      toast(`Screened ${h.name}${alerts ? `, ${alerts} new alerts` : ""}`);
    } catch (e) { S.err[k] = aiErr(e); }
    S.busy[k] = null; await loadAll();
  },
  scrSet(d) { S.drafts[d.k] = d.v; render(); },
  stopRun() { if (S.run) S.run.stop = true; toast("Stopping after the current check"); },
  async runScreening() {
    const A = active(), sel = S.drafts["scr-crit"] || {}; const crits = A.filter((c) => sel[c.id] !== false).map((c) => c.id);
    if (!crits.length) { toast("Pick at least one criterion"); return; }
    const what = []; if (sget("scr-rev", true)) what.push("revenue"); if (sget("scr-con", true)) what.push("controversies"); if (!what.length) { toast("Choose revenue, controversies or both"); return; }
    const scope = sget("scr-scope", S.holdings.length ? "universe" : "new"), web = sget("scr-method", "web") === "web";
    let list = [];
    if (scope === "universe") list = S.holdings.slice().sort((a, b) => (b.weight || 0) - (a.weight || 0));
    if (scope === "issuers") { const ids = Object.keys(S.drafts["scr-iss"] || {}).filter((k) => S.drafts["scr-iss"][k]); list = S.holdings.filter((h) => ids.includes(h.id)); if (!list.length) { toast("Pick at least one issuer"); return; } }
    if (scope === "new") {
      const name = draft("ag-name").trim(); if (!name) { toast("Enter the company name"); return; }
      const ticker = draft("ag-ticker").trim().toUpperCase(), isin = draft("ag-isin").trim().toUpperCase();
      let h = findH(ticker) || findH(isin) || findByName(name);
      try { if (!h) h = await DB.addH({ name, ticker, isin, weight: 0, type: "prospect" }); } catch (e) { writeErr(e); return; }
      S.holdings.push(h); list = [h];
    }
    // Web: one request per company and criterion (keeps each request short). Quick: one per company.
    const jobs = web ? list.flatMap((h) => crits.map((c) => ({ holding: h, criteria: [c] }))) : list.map((h) => ({ holding: h, criteria: crits }));
    await runChecks(jobs, { web, what, context: scope === "new" ? draft("ag-ctx").trim() : "" });
  },
  async monToggle() { const m = Object.assign({ issuers: "all", criteria: [] }, (S.ws && S.ws.monitor) || {}); m.enabled = !m.enabled; try { await DB.ws({ monitor: m }); toast(m.enabled ? "Daily monitoring is on" : "Daily monitoring is off"); await loadAll(); } catch (e) { writeErr(e); } },
  async monScope(d) { const m = Object.assign({ issuers: "all", criteria: [] }, (S.ws && S.ws.monitor) || {}); m.issuers = d.v === "all" ? "all" : []; try { await DB.ws({ monitor: m }); await loadAll(); } catch (e) { writeErr(e); } },
  async triage() {
    const t = draft("tri-text").trim(); if (!t) { toast("Paste a news item first"); return; }
    S.busy.triage = true; S.err.triage = null; S.res.triage = null; render();
    try { S.res.triage = await api("triage", { text: t }); } catch (e) { S.err.triage = aiErr(e); }
    S.busy.triage = false; render();
  },
  async addTriage() {
    const r = S.res.triage;
    try { await DB.addA([{ title: r.title, summary: r.summary, date: r.date || today(), severity: ["high", "medium", "low"].includes(r.severity) ? r.severity : "medium", tickers: r.tickers || [], criteria: (r.criteria || []).filter((id) => critById(id)), origin: "ai", source: "AI check", url: "", status: "new" }]);
      S.res.triage = null; delete S.drafts["tri-text"]; toast("Alert logged"); await loadAll(); } catch (e) { writeErr(e); }
  },
  clearTriage() { S.res.triage = null; render(); },
  async ask() {
    const q = draft("ask-q").trim(); if (!q) { toast("Type a question"); return; }
    S.busy.ask = true; S.err.ask = null; S.res.ask = null; render();
    try { S.res.ask = (await api("ask", { question: q })).answer; } catch (e) { S.err.ask = aiErr(e); }
    S.busy.ask = false; render();
  },
};
function fromDraft(c, order) {
  return { key: slug(c.key || c.label), label: c.label, description: c.description, threshold: num(c.threshold) || 0, watchAt: num(c.watchAt) == null ? 50 : num(c.watchAt), controversyLimit: ["medium", "high", "severe"].includes(c.controversyLimit) ? c.controversyLimit : "high", keywords: Array.isArray(c.keywords) ? c.keywords : [], active: true, order };
}

/* ---------- events ---------- */
document.addEventListener("click", (e) => { const t = e.target.closest("[data-act]"); if (!t || t.disabled) return; const f = ACT[t.dataset.act]; if (f) { if (t.tagName !== "A") e.preventDefault(); f(t.dataset, t); } });
document.addEventListener("input", (e) => { const t = e.target; if (t.dataset && t.dataset.draft) S.drafts[t.dataset.draft] = t.value; });
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "authform") return;
  e.preventDefault();
  const email = draft("au-email").trim(), password = draft("au-pw");
  if (!email || !password) { S.err.auth = "Enter your email and a password."; render(); return; }
  S.busy.auth = true; S.err.auth = null; S.res.authNote = null; render();
  try {
    if (S.authMode === "signup") {
      const { data, error } = await S.sb.auth.signUp({ email, password });
      if (error) throw error;
      if (!data.session) S.res.authNote = "Check your inbox and confirm your email, then sign in.";
    } else {
      const { error } = await S.sb.auth.signInWithPassword({ email, password });
      if (error) throw error;
    }
  } catch (err) { S.err.auth = err.message || "Sign-in failed."; }
  S.busy.auth = false; delete S.drafts["au-pw"]; if (!S.user) render();
});
document.addEventListener("change", async (e) => {
  const t = e.target, k = t.dataset && t.dataset.chg;
  if (!k) { if (t.dataset && t.dataset.draft) S.drafts[t.dataset.draft] = t.value; return; }
  if (k === "scrflag") { S.drafts[t.dataset.k] = t.checked; return; }
  if (k === "scrpick") { const g = t.dataset.g; S.drafts[g] = Object.assign({}, S.drafts[g] || {}); S.drafts[g][t.dataset.id] = t.checked; return; }
  if (k === "catmap") { S.res.prov.cats[+t.dataset.i].map = t.value; return; }
  if (k === "impfile" || k === "rrfile" || k === "pvfile") { const f = t.files && t.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { S.drafts[{ impfile: "imp-csv", rrfile: "rr-csv", pvfile: "pv-csv" }[k]] = String(r.result); render(); }; r.readAsText(f); return; }
  try {
    if (k === "monpick") {
      const m = Object.assign({ issuers: "all", criteria: [] }, (S.ws && S.ws.monitor) || {}); const g = t.dataset.g;
      let arr = g === "criteria" ? (m.criteria && m.criteria.length ? m.criteria.slice() : active().map((c) => c.id)) : Array.isArray(m.issuers) ? m.issuers.slice() : [];
      arr = arr.filter((x) => x !== t.dataset.id); if (t.checked) arr.push(t.dataset.id); if (g === "criteria" && arr.length === active().length) arr = [];
      m[g] = arr; await DB.ws({ monitor: m }); S.ws.monitor = m; return;
    }
    if (k === "conlim") { await DB.updC(t.dataset.c, { controversyLimit: t.value }); toast("Criteria updated"); await loadAll(); return; }
    if (k === "thr" || k === "wa") { const v = num(t.value); if (v == null) return; await DB.updC(t.dataset.c, k === "thr" ? { threshold: v } : { watchAt: v }); toast("Criteria updated"); await loadAll(); }
  } catch (err) { writeErr(err); }
});

/* ---------- start ---------- */
(async function start() {
  try {
    const r = await fetch("/api/config");
    S.cfg = await r.json();
    if (!r.ok) throw new Error(S.cfg.error || "Configuration missing");
  } catch (e) {
    $("#boot").innerHTML = `<div class="empty"><h2>Redline is not configured yet</h2><p>${esc(e.message)}. Add the Supabase and Anthropic settings in your hosting provider and redeploy (see README).</p></div>`;
    return;
  }
  S.sb = createClient(S.cfg.supabaseUrl, S.cfg.supabaseAnonKey);
  S.sb.auth.onAuthStateChange((_event, session) => {
    const u = session ? session.user : null;
    const changed = (u && u.id) !== (S.user && S.user.id);
    S.user = u;
    if (!u) { S.loaded = false; S.holdings = []; S.criteria = []; S.alerts = []; S.ws = null; render(); return; }
    if (changed) { S.loaded = false; render(); setTimeout(() => loadAll().catch((e) => { toast("Could not load your data: " + e.message); }), 0); }
  });
  const { data } = await S.sb.auth.getSession();
  if (!data.session) render();
})();
