"""Shared page elements."""
import streamlit as st

# Containers with a key starting "panel" are drawn as white panels.
_CSS = """
<style>
[class*="st-key-panel"], [data-testid="stForm"] { background: #FFFFFF; }
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
