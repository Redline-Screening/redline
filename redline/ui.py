"""Shared page elements."""
import re
from urllib.parse import urlsplit

import streamlit as st

from redline.constants import FINDING_CATEGORIES
from redline.evidence import EVIDENCE, INVOLVEMENT, LEGAL
from redline.rules import LABELS

# Containers with a key starting "panel" are drawn as white panels.
_CSS = """
<style>
[class*="st-key-panel"], [data-testid="stForm"], [data-testid="stMetric"] { background: #FFFFFF; }
</style>
"""


# Community Cloud shows the app in a frame titled "streamlitApp", which browsers
# display as a hover label. Keep a name for screen readers, without the label.
_FRAME_LABEL = """
<script>
try {
  const frame = window.frameElement;
  if (frame && frame.title === "streamlitApp") {
    frame.removeAttribute("title");
    frame.setAttribute("aria-label", "Redline");
  }
} catch (e) {}
</script>
"""


def apply_style() -> None:
    st.html(_CSS)
    # Fixed text only: never pass user, AI or provider text to this call.
    st.html(_FRAME_LABEL, unsafe_allow_javascript=True)


def page_header(title: str, subtitle: str) -> None:
    st.title(title, anchor=False)
    st.caption(subtitle)


def empty_panel(key: str, text: str) -> None:
    with st.container(border=True, key=f"panel-{key}"):
        st.write(text)


def set_notice(text: str) -> None:
    """Show a confirmation after the next rerun."""
    st.session_state["_notice"] = text


def show_notice() -> None:
    text = st.session_state.pop("_notice", None)
    if text:
        st.success(text)


_STATE_COLOURS = {
    "breach": ("#F7E3E1", "#9C2F27"), "watch": ("#FAF0DB", "#85570F"), "clear": ("#E2F0E7", "#2B6B45"),
    "partial": ("#E9EDF3", "#4A5870"), "na": ("#E9EDF3", "#4A5870"),
}
_BY_LABEL = {LABELS[k]: v for k, v in _STATE_COLOURS.items()}


def status_style(frame, column: str = "Status"):
    """Colour the status column of a table."""
    def css(value):
        back, text = _BY_LABEL.get(value, ("", ""))
        return f"background-color: {back}; color: {text}" if back else ""
    return frame.style.map(css, subset=[column])


def setup_steps(holdings, criteria, workspace) -> list[dict]:
    return [
        {"page": "views/universe.py", "title": "1. Investment Universe", "done": bool(holdings)},
        {"page": "views/criteria.py", "title": "2. Exclusion Criteria", "done": any(c["active"] for c in criteria)},
        {"page": "views/sources.py", "title": "3. Data Sources", "done": bool(workspace.get("mode"))},
    ]


def setup_progress(steps) -> None:
    """Progress of the three setup steps. The first open step is the primary action."""
    current = next((s for s in steps if not s["done"]), None)
    with st.container(border=True, key="panel-setup"):
        st.subheader("Setup", anchor=False)
        for column, step in zip(st.columns(3), steps):
            with column:
                st.markdown(f"**{step['title']}**")
                st.caption("Complete" if step["done"] else "Next step" if step is current else "Open")
                if st.button("Edit" if step["done"] else "Continue", key=f"setup-{step['page']}",
                             type="primary" if step is current else "secondary",
                             disabled=not step["done"] and step is not current):
                    st.switch_page(step["page"])


def next_step(page: str, title: str) -> None:
    st.page_link(page, label=f"Next step: {title}", icon=":material/arrow_forward:")


def finding_date(finding) -> str:
    if not finding.get("date"):
        return "Date unknown"
    shown = finding["date"][:{"year": 4, "month": 7}.get(finding.get("date_precision"), 10)]
    return f"{'Event' if finding.get('date_type') == 'event' else 'Reported'}: {shown}"


def evidence_facts(finding) -> list[str]:
    if not finding.get("involvement"):
        return ["Not classified"]
    return [INVOLVEMENT[finding["involvement"]], EVIDENCE.get(finding.get("evidence"), ""), LEGAL.get(finding.get("legal_status"), "")]


def incident_card(key, title, facts, summary, sources, action=None, mark=None) -> None:
    """Titles, summaries and links come from AI, sources or users: shown as plain text, never as markup."""
    with st.container(border=True, key=f"panel-incident-{key}"):
        if mark:
            st.badge(mark, color="blue")
        st.text(title)
        st.caption(" | ".join(re.sub(r"([\\`*_{}\[\]()#+!|<>~$:])", r"\\\1", x) for x in facts if x))
        if summary:
            st.text(summary)
        with st.container(horizontal=True):
            seen = set()
            for source in sources:
                url = source["url"]
                same = re.sub(r"^https?://(www\.)?|[/#?]+$", "", url.lower())
                if not re.match(r"https?://", url, re.I) or same in seen:
                    continue
                seen.add(same)
                host = re.sub(r"[^a-z0-9.-]", "", urlsplit(url).netloc.lower().removeprefix("www.")) or "Source"
                title = re.sub(r"\s+", " ", str(source.get("title") or "")).strip()
                label = f"{host}: {title[:45]}{'...' if len(title) > 45 else ''}" if title and title != url else host
                st.link_button(md_escape(label), url, type="tertiary")
            if action and st.button("Dismiss", key=f"dismiss-{key}", type="tertiary"):
                action()


STATUS_COLOURS = {"breach": "red", "watch": "orange", "clear": "green", "partial": "gray", "na": "gray"}


def status_badge(state) -> None:
    st.badge(LABELS[state], color=STATUS_COLOURS[state])


def finding_card(finding, action=None, mark=None, seen=False) -> None:
    found = []
    if seen:
        found = [f"Found {finding['first_seen']}" if finding.get("first_seen") else "",
                 f"Last confirmed {finding['last_seen']}" if finding.get("last_seen") else ""]
    incident_card(
        finding["id"], finding["title"],
        [f"Severity: {finding['severity']}", FINDING_CATEGORIES.get(finding["category"], "Other"), finding_date(finding),
         *evidence_facts(finding), *found],
        finding["summary"], finding["sources"], action, mark,
    )


COMPANY_KEY = "company-profile"
GOTO_KEY = "_goto"


def md_escape(text) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$:-])", r"\\\1", str(text))


def _open_company(company_id: str) -> None:
    st.session_state[COMPANY_KEY] = company_id
    st.session_state[GOTO_KEY] = "views/company.py"


def company_link(company_id: str, label: str, key: str) -> None:
    """Button that opens the Company Profile of one company."""
    st.button(label, key=key, type="tertiary", on_click=_open_company, args=(company_id,))
