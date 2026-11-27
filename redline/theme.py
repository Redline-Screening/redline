"""All visual styling of Redline: colours, page header band, status pills, sidebar and landing page parts."""
import html
from pathlib import Path

import streamlit as st

NAVY = "#12254A"
RED = "#C8102E"
INK = "#1B2638"
MUTED = "#3F4856"        # darkest grey used for labels; nothing the user must read is lighter
PAGE = "#F6F7F9"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

STATUS = {   # label, dot colour, background
    "breach": ("Breach", "#C8102E", "#FBE9EC"),
    "watch": ("Watch", "#B7791F", "#FDF3E1"),
    "clear": ("Clear", "#2F7D4F", "#E6F4EC"),
    "partial": ("Partly screened", "#6B7280", "#EEF0F3"),
    "na": ("Not screened", "#6B7280", "#EEF0F3"),
    "failed": ("Failed", "#C8102E", "#FBE9EC"),
}

# Short help per page, shown behind the "?" next to the title.
HELP = {
    "Overview": "The fund at a glance: weight in breach and on watch, companies in breach found by monitoring, and the "
                "breaches and watch list. Select a company to open its profile. Setup steps are shown until the "
                "universe, criteria and data sources are in place.",
    "Investment Universe": "Holdings and prospects to be screened. Upload a CSV file or add companies one by one; existing "
                           "companies are matched by ISIN, ticker or name. Next: Exclusion Criteria.",
    "Exclusion Criteria": "The rules the fund must not break. Revenue-based criteria breach above a revenue limit or at a "
                          "severe incident; conduct-based criteria breach through incidents at their own level; criteria of "
                          "type Both use either. Next: Data Sources.",
    "Data Sources": "Choose how companies are screened: provider files, AI screening, or both. Provider figures always take "
                    "priority over AI estimates. Next: Screening.",
    "Portfolio Monitoring": "Checks the selected holdings for new incidents once a day, one check per company covering all "
                            "active criteria. Run now starts the same check immediately, once per day. Results appear on "
                            "Alerts.",
    "Holding Screening": "Checks chosen companies against chosen criteria now, with a new web search per company and "
                         "criterion. The results of the run appear below it; all stored results are in Company Profiles.",
    "Pre-investment Screening": "Checks a company outside the investment universe before you invest, with a new web search "
                                "per criterion. The company is kept as a pre-investment company with its own Company Profile "
                                "and can be added to the universe as a prospect.",
    "Company Profile": "Stored results for one company: status per criterion, revenue exposure with its source, the status "
                       "summary and all findings with their dates. Opening a profile runs no new web search.",
    "Alerts": "Breaches and companies on watch found by Portfolio Monitoring, and imported provider incidents. Manual "
              "screening results are in Company Profiles.",
    "Help": "Overview of all pages and how they connect.",
}


CSS = f"""
<style>
html, body, [data-testid="stApp"] {{ font-size: 16px; color: {INK}; }}
[data-testid="stApp"], [data-testid="stMain"] {{ background: {PAGE}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding: 0 2.5rem 4rem 2.5rem; max-width: none; }}
[data-testid="stMain"] > div:first-child {{ padding-top: 0 !important; }}

/* Text size and contrast: labels, captions and metadata at least 14px and dark grey. */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
[data-testid="stWidgetLabel"] p, [data-testid="stMetricLabel"] p {{ font-size: 14px !important; color: {MUTED} !important; }}
[data-testid="stCaptionContainer"] {{ opacity: 1 !important; }}
[data-testid="stMetricValue"] {{ font-size: 28px !important; font-weight: 600 !important; color: {NAVY} !important; }}
h2, h3 {{ color: {NAVY} !important; font-weight: 600 !important; }}
h2 {{ font-size: 1.35rem !important; }}

/* Cards: borderless, white, rounded, soft navy shadow. */
[class*="st-key-panel"], [data-testid="stMetric"] {{
  background: #FFFFFF !important; border: none !important; border-radius: 14px !important;
  box-shadow: 0 2px 12px rgba(18, 37, 74, 0.08) !important; position: relative; z-index: 1; }}
[data-testid="stMetric"] {{ padding: 16px 18px !important; }}
[data-testid="stExpander"] details {{ border: none !important; border-radius: 12px !important; background: #FFFFFF;
  box-shadow: 0 1px 6px rgba(18, 37, 74, 0.07); }}

/* Buttons: primary navy, secondary white with a thin border. */
button[kind="primary"], button[data-testid="stBaseButton-primary"] {{ background: {NAVY} !important; border-color: {NAVY} !important;
  color: #FFFFFF !important; border-radius: 8px !important; }}
button[kind="secondary"], button[data-testid="stBaseButton-secondary"] {{ background: #FFFFFF !important; border: 1px solid #C9D0DB !important;
  color: {NAVY} !important; border-radius: 8px !important; }}

button:disabled {{ opacity: .45 !important; cursor: not-allowed !important; }}

/* Page header: full-width navy band; the first card overlaps its lower edge. */
.st-key-rl-band {{ background: {NAVY}; margin: -1rem -2.5rem -2.6rem -2.5rem; padding: 3.4rem 2.5rem 3.8rem 2.5rem;
  width: calc(100% + 5rem) !important; max-width: none !important; }}
.st-key-rl-band p {{ margin: 0; }}
.rl-title {{ color: #FFFFFF; font-size: 26px; font-weight: 600; line-height: 1.25; }}
.st-key-rl-band [data-testid="stPopover"] button {{ background: transparent !important; color: #FFFFFF !important;
  border: 1px solid rgba(255,255,255,.45) !important; border-radius: 50% !important; width: 30px; height: 30px; padding: 0 !important; min-height: 0; }}

/* Status pills. */
.rl-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px 2px 8px; border-radius: 999px;
  font-size: 14px; font-weight: 600; line-height: 1.6; }}
.rl-pill i {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}

/* Sidebar: white, no boxes, navigation in large navy-grey text. */
[data-testid="stSidebar"] {{ background: #FFFFFF !important; border-right: 1px solid #E8EBF0; }}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: .5rem; }}
[class*="st-key-nav-"] button {{ background: transparent !important; border: none !important; box-shadow: none !important;
  justify-content: flex-start !important; padding: 6px 12px !important; width: 100%; border-left: 3px solid transparent !important;
  border-radius: 0 !important; min-height: 0; }}
[class*="st-key-nav-"] button p {{ font-size: 19px !important; color: #3A4658 !important; font-weight: 400; }}
[class*="st-key-nav-sub-"] button {{ padding-left: 34px !important; }}
[class*="st-key-nav-sub-"] button p {{ font-size: 16px !important; }}
[class*="st-key-nav-"] button:disabled p {{ color: #8B94A3 !important; }}
.st-key-rl-account p, .st-key-rl-account button p {{ font-size: 14px !important; color: {MUTED} !important; }}
.st-key-rl-account button {{ background: transparent !important; border: none !important; padding: 2px 0 !important;
  justify-content: flex-start !important; min-height: 0; }}

/* Landing page. */
.st-key-rl-hero {{ background: {NAVY}; margin: -1rem -2.5rem 0 -2.5rem; padding: 4.5rem 4rem 3.2rem 4rem;
  width: calc(100% + 5rem) !important; max-width: none !important; }}
.st-key-rl-hero a {{ color: #FFFFFF !important; }}
.st-key-rl-body {{ padding: 0 1.5rem; max-width: 1180px; }}
.rl-statement {{ color: #FFFFFF; font-size: 36px; font-weight: 600; line-height: 1.2; margin: 1.6rem 0 .9rem 0; }}
.st-key-rl-hero button {{ min-height: 48px !important; padding: 0 28px !important; }}
.st-key-rl-hero button p {{ font-size: 17px !important; font-weight: 600 !important; }}
.rl-rule {{ width: 72px; height: 3px; background: {RED}; margin-bottom: 1.6rem; }}
.st-key-rl-hero [data-testid="stCaptionContainer"] p {{ color: #D5DCE8 !important; }}
.st-key-rl-hero button[data-testid="stBaseButton-secondary"] {{ background: transparent !important; color: #FFFFFF !important;
  border-color: rgba(255,255,255,.6) !important; }}
.st-key-rl-hero button[data-testid="stBaseButton-primary"] {{ background: #FFFFFF !important; color: {NAVY} !important; border-color: #FFFFFF !important; }}
.rl-step-no {{ color: {NAVY}; font-weight: 600; font-size: 40px; line-height: 1; margin: 0; }}
.rl-step-line {{ width: 12px; height: 3px; background: {NAVY}; margin: 8px 0 14px 2px; }}
.rl-lead {{ font-size: 26px; line-height: 1.4; color: {NAVY}; font-weight: 500; max-width: 980px; margin: 2.4rem 0 2rem 0; }}
.st-key-rl-analysis-open button {{ border-radius: 50% !important; width: 40px; height: 40px; padding: 0 !important; }}

/* Portfolio Monitoring: the daily switch is the main control. */
.st-key-pm-switch label p {{ font-size: 19px !important; font-weight: 600 !important; color: {NAVY} !important; }}
.st-key-pm-switch [data-testid="stCheckbox"] label > span + div {{ transform: scale(1.7); transform-origin: left center;
  margin-right: 30px; }}
.rl-switch-state {{ font-size: 17px; color: {MUTED}; margin: 0; }}

/* Fade-in on scroll where the browser supports scroll-driven animations; static elsewhere. */
@supports (animation-timeline: view()) {{
  [class*="st-key-rl-reveal"] {{ animation: rl-fade linear both; animation-timeline: view(); animation-range: entry 0% entry 40%; }}
  @keyframes rl-fade {{ from {{ opacity: 0; transform: translateY(16px); }} to {{ opacity: 1; transform: none; }} }}
}}
</style>
"""


def apply() -> None:
    st.html(CSS)


def pill(state: str) -> str:
    label, dot, back = STATUS[state]
    return f'<span class="rl-pill" style="background:{back};color:{dot}"><i style="background:{dot}"></i>{label}</span>'


def show_pill(state: str) -> None:
    st.html(pill(state))


def header(title: str) -> None:
    """Navy band at the top of every page: the title and "?" help. Explanations live in the help."""
    with st.container(key="rl-band"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(f'<p class="rl-title">{html.escape(title)}</p>')
            if title in HELP:
                with st.popover("?", help="Help"):
                    st.write(HELP[title])


def logo(light: bool = False) -> str:
    return str(ASSETS / ("redline-logo-light.svg" if light else "redline-logo.svg"))
