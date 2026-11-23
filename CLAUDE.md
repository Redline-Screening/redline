# Redline – exclusion-screening platform (school project)

## Scope rules
- Only work in this folder. Push only to github.com/Redline-Screening/redline.
- Never touch other repositories or folders on this computer.
- Keep secrets out of git: .streamlit/secrets.toml must be in .gitignore.

## What it does
Users upload a fund universe (holdings with ISIN, weight, returns) and set exclusion
criteria (e.g. "0% revenue from military activity"). The app checks for breaches:
- Criterion types:
  - Revenue-based (e.g. thermal coal): BREACH if revenue > limit OR a severe incident.
  - Both (e.g. military): BREACH if revenue > limit OR a high or severe incident.
    Exception: controversial weapons breach at medium or worse.
  - Conduct-based (e.g. child labour): no revenue limit; BREACH if an incident reaches
    the criterion's own breach level (medium, high or severe).
  - WATCH (all types): medium or worse incident below the breach level, or
    likelihood >= watch level.
  - A company is clear only when every active criterion has been screened.
- Revenue exposure: % of revenue from the excluded activity (AI estimate or provider
  data). Not used for conduct-based criteria.
- Findings: an AI agent searches the web for any link between company and criterion –
  past and recent scandals, court cases, NGO reports, supply-chain incidents, contracts,
  investments, subsidiaries, financing. Each finding has a short summary, a date (or
  "Date unknown"), a severity (low/medium/high/severe) and source links that appeared
  in the search results. The controversy level is the highest severity among open
  findings. A later search that finds nothing never lowers it; dismissing a finding does.
- Alerts: every finding at medium or above creates one alert with company, criterion,
  summary, date and sources. It reopens if the severity rises.
- Pages: Overview, Investment Universe, Exclusion Criteria, Data Sources, Screening,
  Risk Assessment, Alerts. Daily monitoring runs separately.

## Stack
- Streamlit multipage app, deployed on Streamlit Community Cloud.
- Supabase for all data (supabase-py). No local data files.
- Anthropic Python SDK with the web search tool. Keys only via st.secrets.
- Daily monitoring: monitor.py run by GitHub Actions (Streamlit cannot run schedules).

## AI cost control (budget: $10–20 in total until mid January 2027)
- Manual screenings: Sonnet, max 4 web searches per check. Daily monitoring: Haiku,
  max 2 web searches per check.
- Limits counted in the database before each call: 15 checks per user per day, 60 per
  day across all users. Failed checks count.
- Actual cost of each check is recorded. Total budget: $12 manual, $4 monitoring.
- Monitoring: only issuers the user toggles on (off by default, max 5 per user), one
  check per company covering all active criteria, max 5 checks per day across all
  users, only new incidents since the last check.
- At a limit show "Daily AI limit reached, try again tomorrow", not an error.
- Show the number of checks before a screening starts ("This will run 20 checks").
- Demo account: prepared results, read-only, no AI checks.
- Note on the Screening and sign-in pages: "AI checks are funded privately for this
  school project and limited per day. Contact victoria.gueissaz@student.unisg.com for a
  higher limit."
- Ask before running real, billed checks during development.

## Design
- Professional institutional finance dashboard. Light grey background, white panels
  with fine borders, navy sidebar with text labels, one blue accent (#1F5FBF),
  muted red/amber/green for breach/watch/clear.
- Font: Source Sans (Streamlit's default).
- Easy to follow: clear setup progress (1. Investment Universe, 2. Exclusion Criteria,
  3. Data Sources) and one obvious primary action per page.

## Wording
- Professional and concise. Page titles are noun phrases, never questions
  (e.g. "Exclusion Criteria", not "What your fund must not hold").
- No casual phrases. Short descriptive subtitles.

## Reference
reference/ holds the earlier JavaScript version. Port its logic, not its look:
- reference/lib/screening.mjs: prompts, web search loop, source checking
  (keep only URLs that appeared in search results), merging scores, alerts.
- reference/supabase/schema.sql: tables and row-level security.
- reference/public/app.js: features. Use the Design and Wording sections above
  instead of its styling and copy.

## Quality
- Each user only sees their own data.
- Provider figures are never overwritten by AI estimates.
- Never invent sources; label AI results as estimates.
- Run and test each feature after building it.