# Redline – exclusion-screening platform (school project)

## Scope rules
- Only work in this folder. Push only to github.com/Redline-Screening/redline.
- Never touch other repositories or folders on this computer.
- Keep secrets out of git: .streamlit/secrets.toml must be in .gitignore.

## What it does
Users upload a fund universe (holdings with ISIN, weight, returns) and set exclusion
criteria (e.g. "0% revenue from military activity"). The app checks for breaches:
- Revenue exposure: % of revenue from the excluded activity (AI estimate or provider data).
- Controversies: an AI agent searches the web for incidents linked to each criterion
  and rates them none/low/medium/high/severe, with source links.
- Status per criterion: BREACH if revenue > limit OR controversy >= the criterion's
  breach level (default high); WATCH if medium controversy or likelihood >= watch level.
- Pages: Overview, Investment Universe, Exclusion Criteria, Data Sources, Screening,
  Risk Assessment, Alerts. Daily monitoring runs separately.

## Stack
- Streamlit multipage app, deployed on Streamlit Community Cloud.
- Supabase for all data (supabase-py). No local data files.
- Anthropic Python SDK with the web search tool. Keys only via st.secrets.
- Daily monitoring: monitor.py run by GitHub Actions (Streamlit cannot run schedules).

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