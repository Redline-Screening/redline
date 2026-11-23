# Redline: exclusion-screening website

Redline lets anyone with an account upload a fund universe, set exclusion criteria (for example "no revenue from military activity"), and check whether their investments breach those criteria. An AI agent searches the internet for controversies linked to each criterion (for example a weapons contract or a surveillance scandal), estimates revenue exposure, raises alerts, and can monitor the portfolio every day.

It is plain HTML and JavaScript with a few server functions, so there is no build step.

| Part | Service | Cost for a school project |
|---|---|---|
| Website and API functions | Vercel (Hobby) | Free |
| Accounts and database | Supabase (Free) | Free |
| AI screening and web search | Anthropic API | Pay per use (set a spending limit) |
| Daily monitoring job | GitHub Actions | Free |

---

## How it works

```
Browser (public/app.js)
  │  sign in, universe, criteria, alerts ──────────► Supabase (Postgres + row-level security)
  │  "Run screening", "Check a news item" ...
  ▼
Vercel functions (api/ai/*.js) ── Claude API + web search tool ──► scores and alerts saved in Supabase
                                                                      ▲
GitHub Actions, every morning (scripts/monitor.mjs) ─────────────────┘  daily monitoring for every user who switched it on
```

- **Each user's data is private.** Row-level security in the database (`supabase/schema.sql`) means a user can only read and change their own rows.
- **API keys stay on the server.** The browser never sees the Anthropic key; it calls `/api/ai/...`, which checks the user's login first.
- **Web screening runs one company and one criterion per request**, so every request finishes well within Vercel's time limit. The browser shows progress as it goes.
- **Sources are checked.** The AI must give a URL for every controversy, and the server keeps only URLs that actually appeared in the web search results. A claimed controversy with no real source is downgraded to "none".
- **Provider data wins.** Revenue figures loaded from ISS STOXX, MSCI, Sustainalytics or another provider are never overwritten by AI estimates.

### Breach rules

For each criterion:

- **Breach** when the revenue share is above the limit, **or** a controversy reaches the criterion's controversy level (default: high or worse).
- **Watch** when a medium controversy appears, or the likelihood that exposure rises passes the watch level.

---

## Set it up (about 30–45 minutes)

You need: a GitHub account, a Supabase account, a Vercel account (sign in with GitHub) and an Anthropic Console account. All can be created with your email.

### 1. Put the code on GitHub

1. Create a new **private** repository on github.com, for example `redline`.
2. Upload all files from this folder: on the repository page click **Add file → Upload files**, then drag in the folder contents, including the hidden `.github` folder.
   - If the upload skips `.github`, create the file `.github/workflows/daily-monitoring.yml` by hand with **Add file → Create new file** and paste its content.
   - Or, if you know git, run `git init`, `git add .`, `git commit -m "Redline"` and push.

### 2. Create the database (Supabase)

1. Go to [supabase.com](https://supabase.com) → **New project**. Pick a region near you (for example Frankfurt or Zurich), set a database password and wait until it is ready.
2. Open **SQL Editor → New query**, paste the whole content of `supabase/schema.sql` and click **Run**. You should see "Success".
3. Open **Authentication → Sign In / Providers → Email**:
   - For a school project you can switch **Confirm email** off, so classmates can sign in straight away.
   - If you leave it on, people must click the link in the confirmation email before they can sign in.
4. Open **Project Settings → API** (or **Data API / API Keys**) and copy:
   - **Project URL** → this is `SUPABASE_URL`
   - **anon / public key** → this is `SUPABASE_ANON_KEY`
   - **service_role key** → this is `SUPABASE_SERVICE_ROLE_KEY`. It is secret: use it only in GitHub Actions secrets, never in the website.

### 3. Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com), create an account and add a payment method under **Billing** (prepaid credit works, for example $10).
2. Under **Settings → Limits**, set a low monthly spending limit so costs can't run away.
3. **API Keys → Create Key.** Copy it; it starts with `sk-ant-`. This is `ANTHROPIC_API_KEY`.
4. Web search must be allowed for your organization. It is on by default; an admin can turn it off under the Console's privacy or tool settings.

### 4. Put the website online (Vercel)

1. Go to [vercel.com](https://vercel.com) → **Add New → Project** → import your GitHub repository.
2. **Framework preset: Other.** Leave the build command empty. The output directory is `public` (Vercel uses it automatically).
3. Open **Environment Variables** and add:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `ANTHROPIC_API_KEY`
4. Click **Deploy**. After about a minute you get a link like `https://redline-yourname.vercel.app`.
5. Back in Supabase, open **Authentication → URL Configuration** and set **Site URL** to your Vercel link, so confirmation emails point to your site.

### 5. Switch on daily monitoring (GitHub Actions)

1. In your GitHub repository go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `ANTHROPIC_API_KEY`
2. Go to the **Actions** tab, enable workflows if GitHub asks, open **Daily monitoring** and click **Run workflow** once to test it.
3. From then on it runs every morning (05:30 UTC). It screens only users who switched **Daily monitoring** on in the website, and only once per day each.

### 6. Try it

1. Open your Vercel link, click **Create an account** and sign in.
2. **Step 1:** upload `sample/universe.csv` under **Fund universe → Upload CSV**.
3. **Step 2:** under **Screening criteria**, add **Military & defence revenue**.
4. **Step 3:** under **Data sources**, choose **Let the AI screen**.
5. **Screening:** choose **Selected issuers** → *Meta Platforms*, **Web search**, then **Run screening**. After about 30–60 seconds, Meta shows its controversy level with source links under **Risk assessment**, and new alerts appear under **Alerts**.
6. Switch on **Daily monitoring** at the bottom of the Screening page.

To share it, send your classmates the link; each creates their own account and gets a private workspace.

---

## Costs and limits

- **One web check** (one company × one criterion) uses up to 4 web searches plus tokens: roughly $0.05–0.15 with the default model. Screening 10 companies against 2 criteria is about 20 checks.
- **Daily monitoring** is capped at 60 checks per run in total (`MAX_CHECKS_PER_RUN`). Lower it under **Settings → Secrets and variables → Actions → Variables** if you want to spend less.
- **Quick estimate** (no web search) is much cheaper but can miss recent events.
- **To stop all spending,** disable the workflow in the Actions tab and revoke or limit the API key in the Anthropic Console.

## Optional settings

These are environment variables in Vercel; the monitoring job uses the same names as GitHub secrets or variables.

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Model for screening, policy drafting, triage and questions |
| `ANTHROPIC_FAST_MODEL` | `claude-haiku-5-5` | Model for reading pasted lists |
| `MAX_SEARCHES_PER_CHECK` | `4` (website), `3` (monitoring) | Web searches allowed per company × criterion |
| `MONITOR_TIME_LABEL` | `every morning around 07:30 Zurich time` | The time text shown on the Screening page |

## Run it on your own computer (optional)

```bash
npm install
npm test                 # offline tests of the screening logic
npm i -g vercel
cp .env.example .env.local   # fill in your keys
vercel dev               # opens http://localhost:3000
```

## Files

| File | Purpose |
|---|---|
| `public/index.html`, `public/styles.css`, `public/app.js` | The website (all pages and views) |
| `api/config.js` | Gives the browser the public Supabase settings |
| `api/ai/screen.js` | Screens one company for revenue exposure and controversies (with or without web search), saves scores and alerts |
| `api/ai/policy.js` | Turns a written policy into criteria |
| `api/ai/parse-list.js` | Reads holdings from a pasted list |
| `api/ai/triage.js` | Checks whether a pasted news item affects the fund |
| `api/ai/ask.js` | Answers questions about the portfolio |
| `lib/screening.mjs` | Shared screening logic: prompt, web search, source checking, merging, alerts |
| `lib/server.mjs` | Login check, clients and error handling for the API |
| `scripts/monitor.mjs` | Daily monitoring job |
| `.github/workflows/daily-monitoring.yml` | Runs the job every morning |
| `supabase/schema.sql` | Database tables and row-level security |
| `sample/universe.csv` | Example universe for testing |

## Troubleshooting

| What you see | What to do |
|---|---|
| "Redline is not configured yet" | Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Vercel and **redeploy** (Deployments → ⋯ → Redeploy). |
| "Database: relation … does not exist" | Run `supabase/schema.sql` in the Supabase SQL Editor. |
| "Claude API: …credit balance…" | Add credit under Billing in the Anthropic Console. |
| "Claude API: …web search…disabled" | Allow web search for your organization in the Anthropic Console. |
| A check says "took too long" | Run it again. Each check is one company × one criterion; fewer searches (`MAX_SEARCHES_PER_CHECK=3`) make it faster. |
| No confirmation email arrives | Supabase's built-in email has a low hourly limit. Switch **Confirm email** off for the project (step 2.3). |
| Daily monitoring didn't run | Check the Actions tab for errors and that the three secrets are set. Scheduled workflows also pause after 60 days without repository activity. |

## Notes for the presentation

- **AI estimates are not audited ESG data.** Every score shows its source (provider, analyst, AI web agent or AI estimate), its date and its confidence, and controversies link to the articles found.
- **Provider integrations use file exports.** Live API connections to ISS STOXX, MSCI, Sustainalytics or RepRisk need a commercial licence; the platform imports their exports instead.
