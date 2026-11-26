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
    likelihood >= watch threshold (likelihood of increase).
  - A company is clear only when every active criterion has been screened.
- Revenue exposure: % of revenue from the excluded activity (AI estimate or provider
  data). Not used for conduct-based criteria.
- Findings: an AI agent searches the web for any link between company and criterion –
  past and recent scandals, court cases, NGO reports, supply-chain incidents, contracts,
  investments, subsidiaries, financing. Each finding has a short summary, a date (or
  "Date unknown"), a severity (low/medium/high/severe) and source links that appeared
  in the search results. The controversy level is the highest severity among open
  findings. A later search that finds nothing never lowers it; dismissing a finding does.
- AI revenue estimates cause a breach only if a linked source gives the share, or the
  activity's revenue and total revenue for the same year. Otherwise WATCH, labelled
  "Unsourced estimate". A single contract value is not a revenue figure. An unsourced
  estimate below 1% without any open finding is no evidence: it does not cause WATCH and is
  shown only as information.
- Each finding states involvement (company, indirect = supplier to the party involved,
  supplier of the company, partner, unclear), evidence
  (proven, alleged) and legal status. Maximum severity, enforced in code: dismissed
  case low; involvement unclear medium; company alleged or case open high, settled
  without admission medium, proven severe; supplier or partner alleged medium, proven high; indirect alleged low, proven medium.
  Severity is lowered only by a new check that finds a source establishing these.
- Summaries state only what the linked sources say. The first sentence states what
  happened or what is alleged and by whom. Outlets are named only if linked.
  Summaries never describe the source format or the AI's reasoning.
- A finding cites only sources that report that specific event; sources about other events
  (e.g. another contract) are removed, and a finding without sources is left out.
- Status summary per company and criterion in Breach or Watch: 2–3 sentences, at most 60
  words, starting with the actual cause ("Breach because of …"); an unsourced revenue
  estimate is never presented as a cause of a breach; no internal terms; proven findings are
  preferred as the strongest evidence over alleged ones. Generated after
  saving by a separate Haiku call without web search (about $0.002), only from the saved
  findings and the revenue source. Regenerated whenever the status basis changes (new check,
  dismissed finding, provider or analyst figure). Counts towards the manual budget.
- Dates are shown as exact as known (day, month or year), as Event or Reported.
- Alerts page: results of Portfolio Monitoring and provider incident imports only, in two
  boxes (Breaches, Watch), one card per company with one line per criterion (summary,
  number of findings) and "New" for changes in the latest monitoring run. Manual screening
  results stay in Screening and Company Profiles.
- Alert log: dated entries per company and criterion (Breach or Watch) for each monitoring
  day, plus provider imports; earlier days are never changed. Alerts groups them by date
  (Today, Yesterday, date) with a period filter and an .xlsx download. No AI calls.
- Pages: Overview, Investment Universe, Exclusion Criteria, Data Sources, Screening,
  Company Profiles, Alerts. Daily monitoring runs separately.

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
- Monitoring: only companies the user selects (off by default, max 10 per user), one
  check per company covering all active criteria, max 10 checks per day across all
  users, only new incidents since the last monitoring check (first check: last 30 days).
  "Run now" runs the same monitoring once per day per user.
- At a limit show "Daily AI limit reached, try again tomorrow", not an error.
- Show the number of checks before a screening starts ("This will run 20 checks").
- Demo account: prepared results, read-only, no AI checks.
- Note on the Screening and sign-in pages: "AI checks are funded privately for this
  school project and limited per day. Contact victoria.gueissaz@student.unisg.ch for a
  higher limit."
- Ask before running real, billed checks during development.

## Design
- Corporate, bank-style. All styling in redline/theme.py.
- Landing page before sign-in (no sidebar): navy hero with the logo, "Know when your
  portfolio crosses the line.", Sign in / Create account / View demo; one statement
  sentence; step cards 1–4 (4 = Analysis, expands the five analysis sections).
- Light sidebar: logo, large navigation with expanding Setup › and Screening ›; active
  page navy and semibold with a short red bar; email, Help, Sign out below.
- Every page: full-width navy band (#12254A) with the title and a "?" help popover; no
  all-caps labels, no description line; the first content element is a card.
- Page background #F6F7F9; borderless white cards, 14px radius, soft navy shadow.
- Status pills with a coloured dot: Breach red, Watch amber, Clear green, Not screened and
  Partly screened grey. Primary buttons navy, secondary white with a thin border.
- Body 16px; labels, captions and metadata at least 14px in #3F4856 or darker.
- Logo: "Redline" in navy #12254A with a thin red line #C8102E (assets/), tab icon "R".

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